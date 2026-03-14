"""
Google Docs service — create, read, edit, append, export.

Usage:
    docs = DocsService(creds)
    doc = docs.create("My Document")
    content = docs.read("document_id")
    docs.append("document_id", "New paragraph text")
    docs.export("document_id", "/path/to/output.pdf")
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build

log = logging.getLogger("singularity.workspace.docs")


class DocsService:
    """Google Docs API wrapper."""

    def __init__(self, creds):
        self._service = build("docs", "v1", credentials=creds)
        self._drive = build("drive", "v3", credentials=creds)

    def create(self, title: str, body: Optional[str] = None, folder_id: Optional[str] = None) -> dict:
        """
        Create a new Google Doc.
        
        Args:
            title: Document title.
            body: Initial text content.
            folder_id: Drive folder to create in.
        """
        doc = self._service.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        # Move to folder if specified
        if folder_id:
            self._drive.files().update(
                fileId=doc_id,
                addParents=folder_id,
                fields="id,parents",
            ).execute()

        # Insert initial content
        if body:
            self.append(doc_id, body)

        log.info(f"Doc created: {title} → {doc_id}")
        return {
            "id": doc_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    def read(self, document_id: str) -> dict:
        """
        Read a document's content.
        
        Returns dict with title, body (plain text), and raw structure.
        """
        doc = self._service.documents().get(documentId=document_id).execute()
        
        # Extract plain text from structural elements
        text_parts = []
        for element in doc.get("body", {}).get("content", []):
            if "paragraph" in element:
                for elem in element["paragraph"].get("elements", []):
                    if "textRun" in elem:
                        text_parts.append(elem["textRun"]["content"])

        return {
            "id": document_id,
            "title": doc.get("title", ""),
            "body": "".join(text_parts),
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
        }

    def append(self, document_id: str, text: str) -> dict:
        """Append text to the end of a document."""
        # Get current document to find end index
        doc = self._service.documents().get(documentId=document_id).execute()
        content = doc.get("body", {}).get("content", [])
        
        if content:
            end_index = content[-1].get("endIndex", 1) - 1
        else:
            end_index = 1

        requests = [
            {
                "insertText": {
                    "location": {"index": max(1, end_index)},
                    "text": text,
                }
            }
        ]

        result = self._service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()

        log.info(f"Appended {len(text)} chars to doc {document_id}")
        return result

    def replace(self, document_id: str, find: str, replace_with: str) -> dict:
        """Find and replace text in a document."""
        requests = [
            {
                "replaceAllText": {
                    "containsText": {"text": find, "matchCase": True},
                    "replaceText": replace_with,
                }
            }
        ]

        result = self._service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()

        log.info(f"Replaced '{find}' in doc {document_id}")
        return result

    def export(self, document_id: str, output_path: str, mime_type: str = "application/pdf") -> Path:
        """
        Export a document to a file.
        
        Args:
            document_id: Document ID.
            output_path: Where to save.
            mime_type: Export format (application/pdf, text/plain, text/html, 
                       application/vnd.openxmlformats-officedocument.wordprocessingml.document).
        """
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        content = self._drive.files().export(
            fileId=document_id, mimeType=mime_type
        ).execute()

        target.write_bytes(content)
        log.info(f"Exported doc {document_id} → {target}")
        return target

    def list_recent(self, max_results: int = 10) -> list[dict]:
        """List recently modified Google Docs."""
        result = self._drive.files().list(
            q="mimeType='application/vnd.google-apps.document' and trashed=false",
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id,name,modifiedTime,webViewLink)",
        ).execute()
        return result.get("files", [])
