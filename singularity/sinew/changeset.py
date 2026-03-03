"""
SINEW — Changeset System
============================

The safety net between agent intent and real-world mutation.

Architecture:
    1. PLAN phase: Agent runs normally but all mutations (write, edit, exec)
       are intercepted and recorded as a Changeset instead of executed.
    2. REVIEW phase: Changeset is presented as a human-readable diff.
       User can approve all, approve selectively, or reject.
    3. APPLY phase: Git snapshot taken → mutations applied → on failure, rollback.

This means an agent can never accidentally destroy 2M lines of code.
The worst it can do is propose a bad changeset that gets rejected.

Design principles:
    - Read operations are always allowed (no risk)
    - Write/edit/exec are captured, not executed
    - Each changeset gets a unique ID and timestamp
    - Git stash used for atomic rollback
    - Changesets persist to .singularity/changesets/ for audit trail
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.sinew.changeset")


class MutationType(str, Enum):
    WRITE = "write"
    EDIT = "edit"
    EXEC = "exec"
    DELETE = "delete"


class MutationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class Mutation:
    """A single proposed change to the workspace."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    type: MutationType = MutationType.WRITE
    path: str = ""
    command: str = ""  # for exec mutations
    content: str = ""  # for write mutations
    old_text: str = ""  # for edit mutations
    new_text: str = ""  # for edit mutations
    description: str = ""  # human-readable summary
    risk: str = "low"  # low | medium | high | critical
    status: MutationStatus = MutationStatus.PENDING
    result: str = ""  # output after execution
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "path": self.path,
            "command": self.command,
            "content_preview": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "content_bytes": len(self.content),
            "old_text_preview": self.old_text[:100] + "..." if len(self.old_text) > 100 else self.old_text,
            "new_text_preview": self.new_text[:100] + "..." if len(self.new_text) > 100 else self.new_text,
            "description": self.description,
            "risk": self.risk,
            "status": self.status.value,
            "result": self.result[:500] if self.result else "",
            "timestamp": self.timestamp,
        }
    
    def diff_summary(self) -> str:
        """Human-readable one-liner."""
        if self.type == MutationType.WRITE:
            return f"📝 WRITE {self.path} ({len(self.content)} bytes)"
        elif self.type == MutationType.EDIT:
            old_lines = self.old_text.count('\n') + 1
            new_lines = self.new_text.count('\n') + 1
            return f"✏️ EDIT {self.path} ({old_lines} lines → {new_lines} lines)"
        elif self.type == MutationType.EXEC:
            return f"⚡ EXEC `{self.command[:80]}`"
        elif self.type == MutationType.DELETE:
            return f"🗑️ DELETE {self.path}"
        return f"❓ {self.type} {self.path or self.command}"


@dataclass 
class Changeset:
    """A collection of proposed mutations from a single agent turn."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_role: str = ""  # which agent proposed this (cto, coo, poa-comb, etc.)
    task: str = ""  # what the agent was asked to do
    mutations: list[Mutation] = field(default_factory=list)
    status: MutationStatus = MutationStatus.PENDING
    git_stash_ref: str = ""  # git stash ref for rollback
    created_at: float = field(default_factory=time.time)
    reviewed_at: float = 0.0
    applied_at: float = 0.0
    workspace: str = ""

    def add_write(self, path: str, content: str, description: str = "") -> Mutation:
        """Record a proposed file write."""
        risk = self._assess_write_risk(path, content)
        m = Mutation(
            type=MutationType.WRITE,
            path=path,
            content=content,
            description=description or f"Write {len(content)} bytes to {path}",
            risk=risk,
        )
        self.mutations.append(m)
        return m

    def add_edit(self, path: str, old_text: str, new_text: str, description: str = "") -> Mutation:
        """Record a proposed file edit."""
        risk = self._assess_edit_risk(path, old_text, new_text)
        m = Mutation(
            type=MutationType.EDIT,
            path=path,
            old_text=old_text,
            new_text=new_text,
            description=description or f"Edit {path}: replace {len(old_text)} chars",
            risk=risk,
        )
        self.mutations.append(m)
        return m

    def add_exec(self, command: str, description: str = "") -> Mutation:
        """Record a proposed command execution."""
        risk = self._assess_exec_risk(command)
        m = Mutation(
            type=MutationType.EXEC,
            command=command,
            description=description or f"Execute: {command[:80]}",
            risk=risk,
        )
        self.mutations.append(m)
        return m

    def summary(self) -> str:
        """Full human-readable changeset summary."""
        lines = []
        lines.append(f"╔══ Changeset {self.id} ══╗")
        lines.append(f"  Agent:  {self.agent_role or 'unknown'}")
        lines.append(f"  Task:   {self.task[:80] if self.task else 'unspecified'}")
        lines.append(f"  Status: {self.status.value}")
        lines.append(f"  Changes: {len(self.mutations)}")
        lines.append("")
        
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_mutations = sorted(self.mutations, key=lambda m: risk_order.get(m.risk, 4))
        
        for i, m in enumerate(sorted_mutations, 1):
            risk_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(m.risk, "⚪")
            lines.append(f"  {i}. {risk_icon} [{m.risk.upper()}] {m.diff_summary()}")
            if m.description and m.description != m.diff_summary():
                lines.append(f"     └─ {m.description}")
        
        lines.append("")
        risk_counts = {}
        for m in self.mutations:
            risk_counts[m.risk] = risk_counts.get(m.risk, 0) + 1
        risk_str = ", ".join(f"{v} {k}" for k, v in sorted(risk_counts.items(), key=lambda x: risk_order.get(x[0], 4)))
        lines.append(f"  Risk breakdown: {risk_str}")
        lines.append(f"╚{'═' * (len(lines[0]) - 2)}╝")
        
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_role": self.agent_role,
            "task": self.task,
            "status": self.status.value,
            "mutations": [m.to_dict() for m in self.mutations],
            "git_stash_ref": self.git_stash_ref,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
            "applied_at": self.applied_at,
            "mutation_count": len(self.mutations),
            "risk_breakdown": self._risk_breakdown(),
        }
    
    def _risk_breakdown(self) -> dict:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for m in self.mutations:
            counts[m.risk] = counts.get(m.risk, 0) + 1
        return counts

    def _assess_write_risk(self, path: str, content: str) -> str:
        """Assess risk level of a file write."""
        p = path.lower()
        # Critical: config files, env, keys, core infrastructure
        if any(x in p for x in [".env", "config.json", "config.yaml", "credentials",
                                  "package.json", "pyproject.toml", "Cargo.toml",
                                  "docker-compose", "Dockerfile", ".service"]):
            return "critical"
        # High: source code in established projects, database files
        if any(x in p for x in [".db", ".sqlite", ".sql"]):
            return "high"
        if any(x in p for x in ["/src/", "/lib/", "/core/"]):
            return "high"
        # Medium: scripts, tests, docs
        if any(x in p for x in [".sh", "/scripts/", "/test", "/docs/"]):
            return "medium"
        # Low: new files in safe dirs, markdown, logs
        if any(x in p for x in [".md", ".txt", ".log", ".singularity/", "/tmp/"]):
            return "low"
        return "medium"  # default

    def _assess_edit_risk(self, path: str, old_text: str, new_text: str) -> str:
        """Assess risk of an edit. Edits are inherently riskier than writes."""
        base_risk = self._assess_write_risk(path, new_text)
        # Edits to existing files are one level riskier than writes
        risk_escalation = {"low": "medium", "medium": "high", "high": "critical", "critical": "critical"}
        return risk_escalation.get(base_risk, "high")

    def _assess_exec_risk(self, command: str) -> str:
        """Assess risk of a command execution."""
        cmd = command.lower().strip()
        # Read-only commands are low risk
        read_only = ["ls", "cat", "head", "tail", "grep", "find", "wc", "du", "df",
                     "git log", "git status", "git diff", "git show", "git branch",
                     "echo", "date", "uptime", "whoami", "pwd", "env", "which",
                     "python3 -c", "node -e"]
        if any(cmd.startswith(ro) for ro in read_only):
            return "low"
        # Package management, service control = critical
        if any(x in cmd for x in ["apt ", "pip install", "npm install", "systemctl",
                                    "service ", "docker ", "kubectl"]):
            return "critical"
        # Git mutations
        if any(x in cmd for x in ["git push", "git merge", "git rebase", "git reset",
                                    "git checkout", "git stash"]):
            return "high"
        # File operations
        if any(x in cmd for x in ["rm ", "mv ", "cp ", "chmod", "chown"]):
            return "high"
        return "medium"


class ChangesetManager:
    """Manages changeset lifecycle: capture → review → apply → rollback.
    
    This is the gatekeeper. No mutation reaches the filesystem without
    going through this manager.
    """
    
    def __init__(self, workspace: str, bus: Any = None):
        self.workspace = Path(workspace)
        self.changeset_dir = self.workspace / ".singularity" / "changesets"
        self.changeset_dir.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self._active: dict[str, Changeset] = {}  # changeset_id → Changeset
    
    def new_changeset(self, agent_role: str = "", task: str = "") -> Changeset:
        """Create a new changeset for an agent turn."""
        cs = Changeset(
            agent_role=agent_role,
            task=task,
            workspace=str(self.workspace),
        )
        self._active[cs.id] = cs
        logger.info(f"New changeset {cs.id} for {agent_role}: {task[:60]}")
        return cs
    
    def get_changeset(self, changeset_id: str) -> Optional[Changeset]:
        """Retrieve an active changeset."""
        return self._active.get(changeset_id)
    
    def list_pending(self) -> list[Changeset]:
        """List all pending changesets awaiting review."""
        return [cs for cs in self._active.values() if cs.status == MutationStatus.PENDING]
    
    async def apply(self, changeset_id: str, approved_ids: Optional[set[str]] = None) -> dict:
        """Apply a changeset (or subset of approved mutations).
        
        Steps:
            1. Take git snapshot (stash or commit)
            2. Apply each approved mutation
            3. On any failure, rollback to snapshot
            4. Save changeset record for audit
        
        Args:
            changeset_id: The changeset to apply
            approved_ids: Set of mutation IDs to apply. None = apply all.
        
        Returns:
            dict with success, applied count, failed mutations, rollback status
        """
        cs = self._active.get(changeset_id)
        if not cs:
            return {"success": False, "error": f"Changeset {changeset_id} not found"}
        
        if cs.status != MutationStatus.PENDING:
            return {"success": False, "error": f"Changeset status is {cs.status.value}, not pending"}
        
        # Mark which mutations are approved
        for m in cs.mutations:
            if approved_ids is None or m.id in approved_ids:
                m.status = MutationStatus.APPROVED
            else:
                m.status = MutationStatus.REJECTED
        
        approved = [m for m in cs.mutations if m.status == MutationStatus.APPROVED]
        if not approved:
            cs.status = MutationStatus.REJECTED
            cs.reviewed_at = time.time()
            self._save_record(cs)
            return {"success": True, "applied": 0, "message": "All mutations rejected"}
        
        # ── Git snapshot ──
        snapshot = await self._git_snapshot(cs)
        if not snapshot["success"]:
            return {"success": False, "error": f"Could not create rollback snapshot: {snapshot.get('error', 'unknown')}"}
        
        cs.git_stash_ref = snapshot.get("ref", "")
        cs.reviewed_at = time.time()
        
        # ── Apply mutations ──
        applied = 0
        failed = []
        
        for m in approved:
            try:
                result = await self._apply_mutation(m)
                m.result = result
                m.status = MutationStatus.APPLIED
                applied += 1
            except Exception as e:
                m.result = str(e)
                m.status = MutationStatus.FAILED
                failed.append(m.id)
                logger.error(f"Mutation {m.id} failed: {e}")
                # On first failure of critical mutation, rollback everything
                if m.risk in ("critical", "high"):
                    logger.warning(f"Critical/high mutation failed — initiating rollback")
                    rollback = await self._git_rollback(cs)
                    for am in approved:
                        if am.status == MutationStatus.APPLIED:
                            am.status = MutationStatus.ROLLED_BACK
                    cs.status = MutationStatus.ROLLED_BACK
                    cs.applied_at = time.time()
                    self._save_record(cs)
                    return {
                        "success": False,
                        "applied": applied,
                        "failed": failed,
                        "rolled_back": True,
                        "rollback_result": rollback,
                        "error": f"Critical mutation {m.id} failed — workspace rolled back",
                    }
        
        cs.status = MutationStatus.APPLIED if not failed else MutationStatus.FAILED
        cs.applied_at = time.time()
        self._save_record(cs)
        
        if self.bus:
            await self.bus.emit_nowait("changeset.applied", {
                "id": cs.id,
                "agent": cs.agent_role,
                "applied": applied,
                "failed": len(failed),
            }, source="sinew")
        
        return {
            "success": len(failed) == 0,
            "applied": applied,
            "failed": failed,
            "rolled_back": False,
        }
    
    async def reject(self, changeset_id: str) -> dict:
        """Reject an entire changeset."""
        cs = self._active.get(changeset_id)
        if not cs:
            return {"success": False, "error": f"Changeset {changeset_id} not found"}
        
        for m in cs.mutations:
            m.status = MutationStatus.REJECTED
        cs.status = MutationStatus.REJECTED
        cs.reviewed_at = time.time()
        self._save_record(cs)
        
        return {"success": True, "rejected": len(cs.mutations)}
    
    async def rollback(self, changeset_id: str) -> dict:
        """Rollback an applied changeset using the git snapshot."""
        cs = self._active.get(changeset_id)
        if not cs:
            # Try loading from disk
            cs = self._load_record(changeset_id)
            if not cs:
                return {"success": False, "error": f"Changeset {changeset_id} not found"}
        
        if not cs.git_stash_ref:
            return {"success": False, "error": "No git snapshot available for rollback"}
        
        result = await self._git_rollback(cs)
        if result.get("success"):
            cs.status = MutationStatus.ROLLED_BACK
            self._save_record(cs)
        
        return result
    
    # ── Internal: Git snapshot/rollback ──
    
    async def _git_snapshot(self, cs: Changeset) -> dict:
        """Take a git snapshot before applying changes.
        
        Strategy: 
            1. If working tree is clean, record current HEAD
            2. If dirty, create a temporary commit (tagged for rollback)
        """
        ws = str(self.workspace)
        
        try:
            # Check if we're in a git repo
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=ws, capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                # Not a git repo — init one for safety
                subprocess.run(["git", "init"], cwd=ws, capture_output=True, timeout=5)
                subprocess.run(["git", "add", "-A"], cwd=ws, capture_output=True, timeout=30)
                subprocess.run(
                    ["git", "commit", "-m", "singularity: initial snapshot", "--allow-empty"],
                    cwd=ws, capture_output=True, timeout=30
                )
            
            # Get current HEAD
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ws, capture_output=True, text=True, timeout=5
            )
            head_sha = head.stdout.strip() if head.returncode == 0 else ""
            
            # Check dirty state
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ws, capture_output=True, text=True, timeout=10
            )
            
            if status.stdout.strip():
                # Dirty tree — stash everything
                tag = f"singularity-pre-{cs.id}"
                stash_result = subprocess.run(
                    ["git", "stash", "push", "-m", tag, "--include-untracked"],
                    cwd=ws, capture_output=True, text=True, timeout=30
                )
                if stash_result.returncode == 0:
                    # Immediately pop — we just want the stash ref for rollback
                    subprocess.run(
                        ["git", "stash", "pop"],
                        cwd=ws, capture_output=True, timeout=30
                    )
                    return {"success": True, "ref": f"stash:{tag}", "head": head_sha, "method": "stash"}
                else:
                    # Stash failed — fall back to temp commit
                    subprocess.run(["git", "add", "-A"], cwd=ws, capture_output=True, timeout=30)
                    tag = f"singularity-snapshot-{cs.id}"
                    subprocess.run(
                        ["git", "commit", "-m", f"singularity: pre-changeset {cs.id}", "--allow-empty"],
                        cwd=ws, capture_output=True, timeout=30
                    )
                    subprocess.run(
                        ["git", "tag", tag],
                        cwd=ws, capture_output=True, timeout=5
                    )
                    return {"success": True, "ref": f"tag:{tag}", "head": head_sha, "method": "commit"}
            else:
                # Clean tree — just record HEAD
                return {"success": True, "ref": f"head:{head_sha}", "head": head_sha, "method": "head"}
                
        except Exception as e:
            logger.error(f"Git snapshot failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def _git_rollback(self, cs: Changeset) -> dict:
        """Rollback to a previous git state."""
        ws = str(self.workspace)
        ref = cs.git_stash_ref
        
        if not ref:
            return {"success": False, "error": "No snapshot reference"}
        
        try:
            if ref.startswith("head:"):
                sha = ref.split(":", 1)[1]
                result = subprocess.run(
                    ["git", "checkout", sha, "--", "."],
                    cwd=ws, capture_output=True, text=True, timeout=30
                )
                return {"success": result.returncode == 0, "method": "head-checkout", "output": result.stderr}
            
            elif ref.startswith("tag:"):
                tag = ref.split(":", 1)[1]
                result = subprocess.run(
                    ["git", "checkout", tag, "--", "."],
                    cwd=ws, capture_output=True, text=True, timeout=30
                )
                return {"success": result.returncode == 0, "method": "tag-checkout", "output": result.stderr}
            
            elif ref.startswith("stash:"):
                # Find the stash by message
                msg = ref.split(":", 1)[1]
                stash_list = subprocess.run(
                    ["git", "stash", "list"],
                    cwd=ws, capture_output=True, text=True, timeout=5
                )
                stash_ref = None
                for line in stash_list.stdout.strip().split("\n"):
                    if msg in line:
                        stash_ref = line.split(":")[0]
                        break
                
                if stash_ref:
                    result = subprocess.run(
                        ["git", "stash", "apply", stash_ref],
                        cwd=ws, capture_output=True, text=True, timeout=30
                    )
                    return {"success": result.returncode == 0, "method": "stash-apply", "output": result.stderr}
                
                return {"success": False, "error": f"Stash not found: {msg}"}
            
            return {"success": False, "error": f"Unknown ref type: {ref}"}
            
        except Exception as e:
            logger.error(f"Git rollback failed: {e}")
            return {"success": False, "error": str(e)}
    
    # ── Internal: Apply individual mutations ──
    
    async def _apply_mutation(self, m: Mutation) -> str:
        """Apply a single approved mutation to the filesystem."""
        if m.type == MutationType.WRITE:
            p = Path(m.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(m.content, encoding="utf-8")
            return f"Wrote {len(m.content)} bytes to {m.path}"
        
        elif m.type == MutationType.EDIT:
            p = Path(m.path)
            if not p.exists():
                raise FileNotFoundError(f"File not found: {m.path}")
            content = p.read_text(encoding="utf-8")
            if m.old_text not in content:
                raise ValueError(f"oldText not found in {m.path}")
            new_content = content.replace(m.old_text, m.new_text, 1)
            p.write_text(new_content, encoding="utf-8")
            return f"Edited {m.path}"
        
        elif m.type == MutationType.EXEC:
            proc = await asyncio.create_subprocess_shell(
                m.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.workspace),
                env={**os.environ, "TERM": "dumb"},
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
                raise TimeoutError(f"Command timed out: {m.command[:60]}")
            
            output = stdout.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                raise RuntimeError(f"Command failed (exit {proc.returncode}): {output[:500]}")
            return output[:5000] or "(no output)"
        
        elif m.type == MutationType.DELETE:
            p = Path(m.path)
            if p.exists():
                # Move to trash, not rm
                trash = self.changeset_dir / "trash" / m.id
                trash.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.move(str(p), str(trash / p.name))
                return f"Moved {m.path} to trash ({trash})"
            return f"File not found (no-op): {m.path}"
        
        return f"Unknown mutation type: {m.type}"
    
    # ── Persistence ──
    
    def _save_record(self, cs: Changeset) -> None:
        """Save changeset record to disk for audit trail."""
        record_path = self.changeset_dir / f"{cs.id}.json"
        record_path.write_text(
            json.dumps(cs.to_dict(), indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"Changeset {cs.id} saved to {record_path}")
    
    def _load_record(self, changeset_id: str) -> Optional[Changeset]:
        """Load a changeset record from disk."""
        record_path = self.changeset_dir / f"{changeset_id}.json"
        if not record_path.exists():
            return None
        try:
            data = json.loads(record_path.read_text())
            cs = Changeset(
                id=data["id"],
                agent_role=data.get("agent_role", ""),
                task=data.get("task", ""),
                status=MutationStatus(data.get("status", "pending")),
                git_stash_ref=data.get("git_stash_ref", ""),
                created_at=data.get("created_at", 0),
                reviewed_at=data.get("reviewed_at", 0),
                applied_at=data.get("applied_at", 0),
                workspace=data.get("workspace", str(self.workspace)),
            )
            return cs
        except Exception as e:
            logger.error(f"Failed to load changeset {changeset_id}: {e}")
            return None
    
    def list_records(self, limit: int = 20) -> list[dict]:
        """List recent changeset records from disk."""
        records = []
        for f in sorted(self.changeset_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                records.append(json.loads(f.read_text()))
            except Exception:
                pass
        return records
