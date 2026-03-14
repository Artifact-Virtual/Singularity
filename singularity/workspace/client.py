"""
Unified Google Workspace client.

Single entry point for all Workspace services:
  client.gmail.send(...)
  client.drive.list(...)
  client.docs.create(...)
  client.sheets.read(...)
  client.slides.list(...)
  client.calendar.events(...)
  client.tasks.list(...)
  client.notebook.generate_podcast(...)
"""
from __future__ import annotations

import logging
from typing import Optional

from singularity.workspace.auth import WorkspaceAuth
from singularity.workspace.services.gmail import GmailService
from singularity.workspace.services.drive import DriveService
from singularity.workspace.services.docs import DocsService
from singularity.workspace.services.sheets import SheetsService
from singularity.workspace.services.slides import SlidesService
from singularity.workspace.services.calendar import CalendarService
from singularity.workspace.services.tasks import TasksService
from singularity.workspace.services.notebook import NotebookService

log = logging.getLogger("singularity.workspace.client")


class WorkspaceClient:
    """
    Unified client for all Google Workspace services.
    
    Usage:
        auth = WorkspaceAuth()
        client = WorkspaceClient(auth)
        
        # Gmail
        messages = client.gmail.search("from:someone@example.com")
        client.gmail.send("to@example.com", "Subject", "Body")
        
        # Drive
        files = client.drive.list()
        client.drive.upload("/path/to/file.pdf")
        
        # Docs
        doc = client.docs.create("My Document", "Initial content")
        
        # Sheets
        data = client.sheets.read("spreadsheet_id", "Sheet1!A1:D10")
        
        # Calendar
        events = client.calendar.events()
        
        # NotebookLM-style podcast
        audio = client.notebook.generate_podcast(["paper1.md", "paper2.md"])
    """

    def __init__(self, auth: Optional[WorkspaceAuth] = None):
        self._auth = auth or WorkspaceAuth()
        self._gmail: Optional[GmailService] = None
        self._drive: Optional[DriveService] = None
        self._docs: Optional[DocsService] = None
        self._sheets: Optional[SheetsService] = None
        self._slides: Optional[SlidesService] = None
        self._calendar: Optional[CalendarService] = None
        self._tasks: Optional[TasksService] = None
        self._notebook: Optional[NotebookService] = None

    @property
    def is_authenticated(self) -> bool:
        return self._auth.is_authenticated

    @property
    def email(self) -> Optional[str]:
        return self._auth.email

    def _get_creds(self):
        creds = self._auth.get_credentials()
        if not creds:
            raise RuntimeError(
                "Not authenticated. Run: singularity workspace setup"
            )
        return creds

    @property
    def gmail(self) -> GmailService:
        if not self._gmail:
            self._gmail = GmailService(self._get_creds())
        return self._gmail

    @property
    def drive(self) -> DriveService:
        if not self._drive:
            self._drive = DriveService(self._get_creds())
        return self._drive

    @property
    def docs(self) -> DocsService:
        if not self._docs:
            self._docs = DocsService(self._get_creds())
        return self._docs

    @property
    def sheets(self) -> SheetsService:
        if not self._sheets:
            self._sheets = SheetsService(self._get_creds())
        return self._sheets

    @property
    def slides(self) -> SlidesService:
        if not self._slides:
            self._slides = SlidesService(self._get_creds())
        return self._slides

    @property
    def calendar(self) -> CalendarService:
        if not self._calendar:
            self._calendar = CalendarService(self._get_creds())
        return self._calendar

    @property
    def tasks(self) -> TasksService:
        if not self._tasks:
            self._tasks = TasksService(self._get_creds())
        return self._tasks

    @property
    def notebook(self) -> NotebookService:
        if not self._notebook:
            self._notebook = NotebookService(self._get_creds())
        return self._notebook

    def status(self) -> dict:
        """Return authentication and service status."""
        result = {
            "authenticated": self._auth.is_authenticated,
            "email": self._auth.email,
            "services": {},
        }
        
        services = {
            "gmail": ("gmail", "v1"),
            "drive": ("drive", "v3"),
            "docs": ("docs", "v1"),
            "sheets": ("sheets", "v4"),
            "slides": ("slides", "v1"),
            "calendar": ("calendar", "v3"),
            "tasks": ("tasks", "v1"),
        }
        
        if self._auth.is_authenticated:
            creds = self._get_creds()
            from googleapiclient.discovery import build
            
            for name, (api, version) in services.items():
                try:
                    svc = build(api, version, credentials=creds)
                    # Quick ping test
                    if name == "gmail":
                        svc.users().getProfile(userId="me").execute()
                    elif name == "drive":
                        svc.about().get(fields="user").execute()
                    elif name == "calendar":
                        svc.calendarList().list(maxResults=1).execute()
                    elif name == "tasks":
                        svc.tasklists().list(maxResults=1).execute()
                    result["services"][name] = "✅ connected"
                except Exception as e:
                    result["services"][name] = f"❌ {str(e)[:60]}"
        
        return result
