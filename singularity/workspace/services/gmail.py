"""
Gmail service — read, search, send, label, draft.

Usage:
    gmail = GmailService(creds)
    messages = gmail.search("from:ali@example.com is:unread", max_results=10)
    gmail.send("to@example.com", "Subject", "Body text")
    gmail.send("to@example.com", "Subject", "<h1>HTML</h1>", html=True)
    labels = gmail.labels()
    message = gmail.get("message_id")
    thread = gmail.get_thread("thread_id")
"""
from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional
from pathlib import Path

from googleapiclient.discovery import build

log = logging.getLogger("singularity.workspace.gmail")


class GmailService:
    """Gmail API wrapper."""

    def __init__(self, creds):
        self._service = build("gmail", "v1", credentials=creds)
        self._user = "me"

    def profile(self) -> dict:
        """Get user profile (email, messages total, threads total)."""
        return self._service.users().getProfile(userId=self._user).execute()

    def labels(self) -> list[dict]:
        """List all labels."""
        result = self._service.users().labels().list(userId=self._user).execute()
        return result.get("labels", [])

    def search(
        self,
        query: str = "",
        max_results: int = 10,
        label_ids: Optional[list[str]] = None,
        include_body: bool = False,
    ) -> list[dict]:
        """
        Search messages.
        
        Args:
            query: Gmail search query (same as Gmail search bar).
            max_results: Maximum messages to return.
            label_ids: Filter by label IDs.
            include_body: If True, fetch full message body for each result.
        
        Returns:
            List of message dicts with id, threadId, snippet, and optionally body.
        """
        kwargs = {"userId": self._user, "q": query, "maxResults": max_results}
        if label_ids:
            kwargs["labelIds"] = label_ids

        result = self._service.users().messages().list(**kwargs).execute()
        messages = result.get("messages", [])

        if not messages:
            return []

        detailed = []
        for msg in messages:
            if include_body:
                full = self.get(msg["id"])
                detailed.append(full)
            else:
                # Get metadata only
                meta = self._service.users().messages().get(
                    userId=self._user,
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                ).execute()
                headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
                detailed.append({
                    "id": meta["id"],
                    "threadId": meta["threadId"],
                    "snippet": meta.get("snippet", ""),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "labels": meta.get("labelIds", []),
                })

        return detailed

    def get(self, message_id: str) -> dict:
        """Get a full message by ID."""
        msg = self._service.users().messages().get(
            userId=self._user, id=message_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = self._extract_body(msg.get("payload", {}))

        return {
            "id": msg["id"],
            "threadId": msg["threadId"],
            "snippet": msg.get("snippet", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "labels": msg.get("labelIds", []),
            "body": body,
        }

    def get_thread(self, thread_id: str) -> dict:
        """Get a full thread by ID."""
        thread = self._service.users().threads().get(
            userId=self._user, id=thread_id
        ).execute()

        messages = []
        for msg in thread.get("messages", []):
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            body = self._extract_body(msg.get("payload", {}))
            messages.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "body": body,
            })

        return {"threadId": thread_id, "messages": messages}

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        attachments: Optional[list[str]] = None,
        reply_to: Optional[str] = None,
    ) -> dict:
        """
        Send an email.
        
        Args:
            to: Recipient email.
            subject: Email subject.
            body: Email body (plain text or HTML).
            html: If True, body is HTML.
            cc: CC recipients (comma-separated).
            bcc: BCC recipients (comma-separated).
            attachments: List of file paths to attach.
            reply_to: Message ID to reply to (sets In-Reply-To header).
        """
        if attachments:
            message = MIMEMultipart()
            message.attach(MIMEText(body, "html" if html else "plain"))
            for filepath in attachments:
                path = Path(filepath)
                if path.exists():
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(path.read_bytes())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={path.name}")
                    message.attach(part)
        else:
            message = MIMEText(body, "html" if html else "plain")

        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc
        if reply_to:
            message["In-Reply-To"] = reply_to
            message["References"] = reply_to

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = self._service.users().messages().send(
            userId=self._user, body={"raw": raw}
        ).execute()

        log.info(f"Email sent: {result['id']} → {to}")
        return result

    def draft(self, to: str, subject: str, body: str, html: bool = False) -> dict:
        """Create a draft email."""
        message = MIMEText(body, "html" if html else "plain")
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        result = self._service.users().drafts().create(
            userId=self._user, body={"message": {"raw": raw}}
        ).execute()
        log.info(f"Draft created: {result['id']}")
        return result

    def mark_read(self, message_id: str) -> dict:
        """Mark a message as read."""
        return self._service.users().messages().modify(
            userId=self._user,
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()

    def mark_unread(self, message_id: str) -> dict:
        """Mark a message as unread."""
        return self._service.users().messages().modify(
            userId=self._user,
            id=message_id,
            body={"addLabelIds": ["UNREAD"]},
        ).execute()

    def trash(self, message_id: str) -> dict:
        """Move a message to trash."""
        return self._service.users().messages().trash(
            userId=self._user, id=message_id
        ).execute()

    def unread_count(self) -> int:
        """Get count of unread messages in inbox."""
        result = self._service.users().messages().list(
            userId=self._user, q="is:unread is:inbox", maxResults=1
        ).execute()
        return result.get("resultSizeEstimate", 0)

    def _extract_body(self, payload: dict) -> str:
        """Extract readable body from a message payload."""
        if "body" in payload and payload["body"].get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        if "parts" in payload:
            for part in payload["parts"]:
                mime = part.get("mimeType", "")
                if mime == "text/plain" and part.get("body", {}).get("data"):
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                if mime == "text/html" and part.get("body", {}).get("data"):
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                # Recursive for multipart
                if "parts" in part:
                    result = self._extract_body(part)
                    if result:
                        return result

        return ""
