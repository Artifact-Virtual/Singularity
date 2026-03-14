"""
Google Workspace Integration — Native CLI + Agent access.

Provides authenticated access to all Google Workspace services:
  Gmail, Drive, Docs, Sheets, Slides, Calendar, Tasks, People, Keep

Plus Gemini-powered features:
  NotebookLM-style podcast generation from research papers

Auth: OAuth2 desktop flow with persistent refresh tokens.
"""

from singularity.workspace.auth import WorkspaceAuth
from singularity.workspace.client import WorkspaceClient

__all__ = ["WorkspaceAuth", "WorkspaceClient"]
