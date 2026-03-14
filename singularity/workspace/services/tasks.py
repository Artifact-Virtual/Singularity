"""
Google Tasks service — list, create, complete.

Usage:
    tasks = TasksService(creds)
    lists = tasks.task_lists()
    items = tasks.list_tasks()
    tasks.create("Buy groceries")
    tasks.complete("task_id")
"""
from __future__ import annotations

import logging
from typing import Optional

from googleapiclient.discovery import build

log = logging.getLogger("singularity.workspace.tasks")


class TasksService:
    """Google Tasks API wrapper."""

    def __init__(self, creds):
        self._service = build("tasks", "v1", credentials=creds)

    def task_lists(self) -> list[dict]:
        """List all task lists."""
        result = self._service.tasklists().list().execute()
        return [
            {"id": tl["id"], "title": tl.get("title", ""), "updated": tl.get("updated", "")}
            for tl in result.get("items", [])
        ]

    def list_tasks(
        self,
        tasklist_id: str = "@default",
        show_completed: bool = False,
        max_results: int = 50,
    ) -> list[dict]:
        """
        List tasks in a task list.
        
        Args:
            tasklist_id: Task list ID (default: @default).
            show_completed: Include completed tasks.
            max_results: Maximum tasks to return.
        """
        result = self._service.tasks().list(
            tasklist=tasklist_id,
            showCompleted=show_completed,
            maxResults=max_results,
        ).execute()

        return [
            {
                "id": t["id"],
                "title": t.get("title", ""),
                "status": t.get("status", ""),
                "due": t.get("due", ""),
                "notes": t.get("notes", ""),
                "updated": t.get("updated", ""),
            }
            for t in result.get("items", [])
        ]

    def create(
        self,
        title: str,
        tasklist_id: str = "@default",
        notes: Optional[str] = None,
        due: Optional[str] = None,
    ) -> dict:
        """
        Create a new task.
        
        Args:
            title: Task title.
            tasklist_id: Task list ID.
            notes: Task notes/description.
            due: Due date (ISO 8601 / RFC 3339).
        """
        task = {"title": title}
        if notes:
            task["notes"] = notes
        if due:
            task["due"] = due

        result = self._service.tasks().insert(
            tasklist=tasklist_id, body=task
        ).execute()
        log.info(f"Task created: {title} → {result['id']}")
        return result

    def complete(self, task_id: str, tasklist_id: str = "@default") -> dict:
        """Mark a task as completed."""
        result = self._service.tasks().patch(
            tasklist=tasklist_id,
            task=task_id,
            body={"status": "completed"},
        ).execute()
        log.info(f"Task completed: {task_id}")
        return result

    def delete(self, task_id: str, tasklist_id: str = "@default") -> None:
        """Delete a task."""
        self._service.tasks().delete(
            tasklist=tasklist_id, task=task_id
        ).execute()
        log.info(f"Task deleted: {task_id}")
