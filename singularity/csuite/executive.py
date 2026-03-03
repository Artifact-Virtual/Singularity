"""
CSUITE — Executive Agent
============================

An Executive wraps an AgentLoop with role-specific permissions,
scoped tools, memory partitions, and reporting format.

Each executive is a self-contained agent that:
    1. Receives tasks from the Coordinator (Singularity)
    2. Runs its own think/act/observe loop
    3. Produces structured reports
    4. Emits events back through the bus
    5. Stays within its permission boundaries

Executives don't know about each other. They don't coordinate directly.
Singularity handles all cross-executive orchestration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from .roles import Role, RoleType

if TYPE_CHECKING:
    from ..bus import EventBus
    from ..voice.chain import ProviderChain
    from ..sinew.executor import ToolExecutor

logger = logging.getLogger("singularity.csuite.executive")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    TIMEOUT = "timeout"


@dataclass
class TaskResult:
    """Result of an executive task execution."""
    task_id: str
    role: RoleType
    status: TaskStatus
    response: str = ""
    findings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    iterations_used: int = 0
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role.value,
            "status": self.status.value,
            "response": self.response,
            "findings": self.findings,
            "actions": self.actions,
            "files_modified": self.files_modified,
            "duration_seconds": round(self.duration_seconds, 2),
            "iterations_used": self.iterations_used,
            "error": self.error,
            "timestamp": self.timestamp,
        }

    @property
    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"[{self.role.value.upper()}] {self.status.value} "
            f"({self.iterations_used} iterations, {self.duration_seconds:.1f}s)"
        )


@dataclass
class Task:
    """A task dispatched to an executive."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    priority: str = "normal"      # low, normal, high, critical
    deadline: Optional[str] = None
    requester: str = "aria"       # who dispatched this
    context: dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 25
    timestamp: float = field(default_factory=time.time)


class Executive:
    """
    An executive agent with role-specific behavior.
    
    Each executive has:
        - A Role (permissions, prompt, keywords)
        - A ProviderChain (LLM access)
        - A ToolExecutor (scoped to their permissions)
        - An EventBus connection (for events and reporting)
        - A workspace directory (for their files/memory)
    """

    def __init__(
        self,
        role: Role,
        bus: EventBus,
        provider_chain: ProviderChain,
        tool_executor: ToolExecutor,
        workspace: Path,
    ):
        self.role = role
        self.bus = bus
        self.provider_chain = provider_chain
        self.tool_executor = tool_executor
        self.workspace = workspace
        self._busy = False
        self._current_task: Optional[Task] = None
        self._task_history: list[TaskResult] = []

        # Ensure workspace exists
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "memory").mkdir(exist_ok=True)
        (self.workspace / "reports").mkdir(exist_ok=True)

        logger.info(f"{self.role.emoji} {self.role.name} executive initialized — workspace: {self.workspace}")

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def name(self) -> str:
        return self.role.name

    @property
    def history(self) -> list[TaskResult]:
        return list(self._task_history)

    async def execute(self, task: Task) -> TaskResult:
        """
        Execute a task through the agent loop.
        
        This is the main entry point. The executive:
        1. Builds a scoped system prompt (role prompt + task + context)
        2. Runs think/act/observe iterations
        3. Enforces tool permissions per iteration
        4. Produces a TaskResult
        5. Emits completion event to bus
        """
        if self._busy:
            return TaskResult(
                task_id=task.task_id,
                role=self.role.role_type,
                status=TaskStatus.BLOCKED,
                error=f"{self.name} is already executing a task",
            )

        self._busy = True
        self._current_task = task
        start_time = time.time()
        iterations = 0

        await self.bus.emit("csuite.task.started", {
            "role": self.role.role_type.value,
            "task_id": task.task_id,
            "description": task.description[:200],
            "priority": task.priority,
        })

        try:
            # Build the conversation for this task
            messages = self._build_messages(task)

            response_text = ""
            all_findings: list[str] = []
            all_actions: list[str] = []
            files_modified: list[str] = []

            # Agent loop — think/act/observe
            for i in range(task.max_iterations):
                iterations = i + 1

                # Get LLM response
                try:
                    llm_response = await self.provider_chain.chat(
                        messages=messages,
                        tools=self._get_scoped_tool_definitions(),
                    )
                except Exception as e:
                    logger.error(f"{self.name} LLM call failed iteration {iterations}: {e}")
                    break

                # If no tool calls, we're done — this is the final response
                if not llm_response.tool_calls:
                    response_text = llm_response.text or ""
                    break

                # Execute tool calls (with permission enforcement)
                messages.append({
                    "role": "assistant",
                    "content": llm_response.text or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in llm_response.tool_calls
                    ],
                })

                for tc in llm_response.tool_calls:
                    result = await self._execute_tool_with_guard(tc.name, tc.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

                    # Track file modifications
                    if tc.name in ("write", "edit") and "path" in tc.arguments:
                        files_modified.append(tc.arguments["path"])

                    all_actions.append(f"{tc.name}: {self._summarize_args(tc.arguments)}")

            # Determine status
            elapsed = time.time() - start_time
            timed_out = iterations >= task.max_iterations and not response_text

            if timed_out:
                status = TaskStatus.TIMEOUT
            elif response_text:
                status = TaskStatus.COMPLETE
                # Parse structured findings from response
                all_findings = self._extract_findings(response_text)
            else:
                status = TaskStatus.FAILED

            result = TaskResult(
                task_id=task.task_id,
                role=self.role.role_type,
                status=status,
                response=response_text,
                findings=all_findings,
                actions=all_actions,
                files_modified=files_modified,
                duration_seconds=elapsed,
                iterations_used=iterations,
            )

            # Persist report
            await self._save_report(result)

            # Emit completion event
            await self.bus.emit("csuite.task.completed", result.to_dict())

            # Check escalation
            if status in (TaskStatus.TIMEOUT, TaskStatus.FAILED) and self.role.escalation.escalate_on_failure:
                await self.bus.emit("csuite.escalation", {
                    "role": self.role.role_type.value,
                    "task_id": task.task_id,
                    "reason": "timeout" if timed_out else "failure",
                    "description": task.description[:200],
                })

            self._task_history.append(result)
            return result

        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(f"{self.name} task execution failed: {e}")
            result = TaskResult(
                task_id=task.task_id,
                role=self.role.role_type,
                status=TaskStatus.FAILED,
                error=str(e),
                duration_seconds=elapsed,
                iterations_used=iterations,
            )
            self._task_history.append(result)
            await self.bus.emit("csuite.task.failed", result.to_dict())
            return result

        finally:
            self._busy = False
            self._current_task = None

    def _build_messages(self, task: Task) -> list[dict[str, Any]]:
        """Build the initial message list for a task."""
        system = self.role.system_prompt

        # Add context if provided
        if task.context:
            system += "\n\n## Additional Context\n"
            for k, v in task.context.items():
                system += f"- **{k}:** {v}\n"

        user_content = f"**DISPATCH** [{task.priority.upper()}]\n\n{task.description}"
        if task.deadline:
            user_content += f"\n\n**Deadline:** {task.deadline}"

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    def _get_scoped_tool_definitions(self) -> list[dict[str, Any]]:
        """Return tool definitions filtered to this executive's permissions."""
        from ..sinew.definitions import TOOL_DEFINITIONS
        allowed = set(self.role.tools.allowed_tools)
        return [t for t in TOOL_DEFINITIONS if t.get("function", {}).get("name") in allowed]

    async def _execute_tool_with_guard(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool with permission guards."""
        # Check tool is allowed
        if tool_name not in self.role.tools.allowed_tools:
            return f"PERMISSION DENIED: {self.name} cannot use tool '{tool_name}'"

        # Check path permissions for file operations
        if tool_name in ("read", "write", "edit") and "path" in arguments:
            path = arguments["path"]
            if not self._check_path_permission(path, write=(tool_name != "read")):
                return f"PERMISSION DENIED: {self.name} cannot access '{path}'"

        # Enforce exec timeout
        if tool_name == "exec" and "timeout" not in arguments:
            arguments["timeout"] = min(
                arguments.get("timeout", 30),
                self.role.tools.max_exec_timeout,
            )

        try:
            result = await self.tool_executor.execute(tool_name, arguments)
            return str(result)
        except Exception as e:
            return f"TOOL ERROR: {tool_name} failed — {e}"

    def _check_path_permission(self, path: str, write: bool = False) -> bool:
        """Check if a path is within allowed directories."""
        # Normalize
        path = path.lstrip("/").lstrip("./")

        # Check forbidden first
        for fp in self.role.tools.forbidden_paths:
            if path.startswith(fp.lstrip("./")):
                return False

        # Check read-only paths (block writes)
        if write:
            for rp in self.role.tools.read_only_paths:
                if path.startswith(rp.lstrip("./")):
                    return False

        # Check allowed workspace paths
        for wp in self.role.tools.workspace_paths:
            if path.startswith(wp.lstrip("./")):
                return True

        # Check read-only paths (allow reads)
        if not write:
            for rp in self.role.tools.read_only_paths:
                if path.startswith(rp.lstrip("./")):
                    return True

        return False

    def _extract_findings(self, response: str) -> list[str]:
        """Extract bullet-point findings from structured response."""
        findings = []
        in_findings = False
        for line in response.split("\n"):
            stripped = line.strip()
            if "FINDINGS:" in stripped.upper():
                in_findings = True
                continue
            if in_findings:
                if stripped.startswith("- "):
                    findings.append(stripped[2:])
                elif stripped and not stripped.startswith("-"):
                    # New section header
                    in_findings = False
        return findings

    def _summarize_args(self, args: dict[str, Any]) -> str:
        """Summarize tool arguments for action log."""
        if "path" in args:
            return args["path"]
        if "command" in args:
            cmd = args["command"]
            return cmd[:80] + ("..." if len(cmd) > 80 else "")
        if "query" in args:
            return f"query: {args['query'][:60]}"
        return str(args)[:80]

    async def _save_report(self, result: TaskResult) -> None:
        """Persist a task report to the executive's reports directory."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        report_path = self.workspace / "reports" / f"{ts}.json"
        try:
            report_path.write_text(json.dumps(result.to_dict(), indent=2))
        except Exception as e:
            logger.error(f"Failed to save report: {e}")

    def status_snapshot(self) -> dict[str, Any]:
        """Current status for health monitoring."""
        return {
            "role": self.role.role_type.value,
            "busy": self._busy,
            "current_task": self._current_task.task_id if self._current_task else None,
            "tasks_completed": len([r for r in self._task_history if r.status == TaskStatus.COMPLETE]),
            "tasks_failed": len([r for r in self._task_history if r.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT)]),
            "total_tasks": len(self._task_history),
        }
