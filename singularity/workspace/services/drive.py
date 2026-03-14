"""
Google Drive service — list, search, upload, download, share, create folders.

Usage:
    drive = DriveService(creds)
    files = drive.list()
    files = drive.search("name contains 'report'")
    drive.upload("/path/to/file.pdf", folder_id="...")
    drive.download("file_id", "/path/to/save")
    drive.share("file_id", "user@example.com", role="reader")
    folder = drive.create_folder("My Folder")
"""
from __future__ import annotations

import io
import logging
import mimetypes
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

log = logging.getLogger("singularity.workspace.drive")

# Google Docs MIME type mapping for export
EXPORT_MIME = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


class DriveService:
    """Google Drive API wrapper."""

    def __init__(self, creds):
        self._service = build("drive", "v3", credentials=creds)

    def about(self) -> dict:
        """Get Drive storage info."""
        result = self._service.about().get(
            fields="user,storageQuota"
        ).execute()
        return result

    def list(
        self,
        folder_id: Optional[str] = None,
        max_results: int = 20,
        mime_type: Optional[str] = None,
        order_by: str = "modifiedTime desc",
    ) -> list[dict]:
        """
        List files in Drive.
        
        Args:
            folder_id: List files in a specific folder. None = root/all.
            max_results: Maximum files to return.
            mime_type: Filter by MIME type.
            order_by: Sort order.
        """
        query_parts = ["trashed = false"]
        if folder_id:
            query_parts.append(f"'{folder_id}' in parents")
        if mime_type:
            query_parts.append(f"mimeType = '{mime_type}'")

        query = " and ".join(query_parts)

        result = self._service.files().list(
            q=query,
            pageSize=max_results,
            orderBy=order_by,
            fields="files(id,name,mimeType,size,modifiedTime,owners,webViewLink,parents)",
        ).execute()

        return result.get("files", [])

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        """
        Search files with a custom query.
        
        Args:
            query: Drive search query (e.g., "name contains 'report'").
        """
        full_query = f"trashed = false and ({query})"
        result = self._service.files().list(
            q=full_query,
            pageSize=max_results,
            fields="files(id,name,mimeType,size,modifiedTime,webViewLink)",
        ).execute()
        return result.get("files", [])

    def get(self, file_id: str) -> dict:
        """Get file metadata by ID."""
        return self._service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,size,modifiedTime,owners,webViewLink,parents,description",
        ).execute()

    def upload(
        self,
        file_path: str,
        folder_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """
        Upload a file to Drive.
        
        Args:
            file_path: Local path to the file.
            folder_id: Target folder ID. None = root.
            name: Override filename.
            description: File description.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        metadata = {"name": name or path.name}
        if folder_id:
            metadata["parents"] = [folder_id]
        if description:
            metadata["description"] = description

        media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
        result = self._service.files().create(
            body=metadata, media_body=media, fields="id,name,webViewLink"
        ).execute()

        log.info(f"Uploaded: {result['name']} → {result['id']}")
        return result

    def download(self, file_id: str, save_path: str) -> Path:
        """
        Download a file from Drive.
        
        Handles Google Docs/Sheets/Slides by exporting to PDF/CSV.
        """
        meta = self.get(file_id)
        mime = meta.get("mimeType", "")
        target = Path(save_path)

        if mime in EXPORT_MIME:
            export_mime, ext = EXPORT_MIME[mime]
            if not target.suffix:
                target = target.with_suffix(ext)
            request = self._service.files().export_media(
                fileId=file_id, mimeType=export_mime
            )
        else:
            request = self._service.files().get_media(fileId=file_id)

        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        log.info(f"Downloaded: {meta['name']} → {target}")
        return target

    def create_folder(self, name: str, parent_id: Optional[str] = None) -> dict:
        """Create a folder in Drive."""
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        result = self._service.files().create(
            body=metadata, fields="id,name,webViewLink"
        ).execute()
        log.info(f"Folder created: {name} → {result['id']}")
        return result

    def share(
        self,
        file_id: str,
        email: str,
        role: str = "reader",
        send_notification: bool = True,
    ) -> dict:
        """
        Share a file with a user.
        
        Args:
            file_id: File to share.
            email: User email to share with.
            role: Permission role (reader, writer, commenter, owner).
            send_notification: Send email notification.
        """
        permission = {"type": "user", "role": role, "emailAddress": email}
        result = self._service.permissions().create(
            fileId=file_id,
            body=permission,
            sendNotificationEmail=send_notification,
        ).execute()
        log.info(f"Shared {file_id} with {email} as {role}")
        return result

    def delete(self, file_id: str) -> None:
        """Move a file to trash."""
        self._service.files().update(
            fileId=file_id, body={"trashed": True}
        ).execute()
        log.info(f"Trashed: {file_id}")

    def storage_usage(self) -> dict:
        """Get storage usage summary."""
        about = self.about()
        quota = about.get("storageQuota", {})
        return {
            "used": int(quota.get("usage", 0)),
            "limit": int(quota.get("limit", 0)),
            "used_in_drive": int(quota.get("usageInDrive", 0)),
            "used_in_trash": int(quota.get("usageInDriveTrash", 0)),
            "user": about.get("user", {}).get("emailAddress", "unknown"),
        }
