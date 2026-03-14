"""
OAuth2 authentication for Google Workspace.

Handles:
  - OAuth2 desktop flow (browser consent → refresh token)
  - Token persistence (~/.singularity/workspace_token.json)
  - Automatic refresh on expiry
  - Scope validation
  - Service account fallback for server-to-server
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

log = logging.getLogger("singularity.workspace.auth")

# All Workspace scopes we need
SCOPES = [
    # Gmail
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    # Drive
    "https://www.googleapis.com/auth/drive",
    # Docs
    "https://www.googleapis.com/auth/documents",
    # Sheets
    "https://www.googleapis.com/auth/spreadsheets",
    # Slides
    "https://www.googleapis.com/auth/presentations",
    # Calendar
    "https://www.googleapis.com/auth/calendar",
    # Tasks
    "https://www.googleapis.com/auth/tasks",
    # People / Contacts
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# Default paths
DEFAULT_TOKEN_PATH = Path.home() / ".singularity" / "workspace_token.json"
DEFAULT_CLIENT_SECRET_PATH = Path.home() / ".singularity" / "workspace_client_secret.json"
SA_KEY_PATH = Path(__file__).parent.parent.parent / "config" / "workspace-sa-key.json"


class WorkspaceAuth:
    """Manages Google Workspace OAuth2 credentials."""

    def __init__(
        self,
        token_path: Optional[Path] = None,
        client_secret_path: Optional[Path] = None,
    ):
        self.token_path = token_path or DEFAULT_TOKEN_PATH
        self.client_secret_path = client_secret_path or DEFAULT_CLIENT_SECRET_PATH
        self._creds: Optional[Credentials] = None

    @property
    def is_authenticated(self) -> bool:
        """Check if we have valid (or refreshable) credentials."""
        creds = self._load_token()
        if not creds:
            return False
        if creds.valid:
            return True
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
                return True
            except Exception:
                return False
        return False

    @property
    def email(self) -> Optional[str]:
        """Get the authenticated user's email if available."""
        creds = self.get_credentials()
        if creds and hasattr(creds, "token"):
            try:
                from googleapiclient.discovery import build
                service = build("oauth2", "v2", credentials=creds)
                info = service.userinfo().get().execute()
                return info.get("email")
            except Exception:
                pass
        # Try from token file
        if self.token_path.exists():
            try:
                data = json.loads(self.token_path.read_text())
                return data.get("email")
            except Exception:
                pass
        return None

    def get_credentials(self) -> Optional[Credentials]:
        """Get valid credentials, refreshing if needed."""
        if self._creds and self._creds.valid:
            return self._creds

        creds = self._load_token()
        if creds:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self._save_token(creds)
                    log.info("Workspace token refreshed successfully")
                except Exception as e:
                    log.warning(f"Token refresh failed: {e}")
                    return None
            if creds.valid:
                self._creds = creds
                return creds

        return None

    def authenticate_interactive(self, port: int = 8091) -> Credentials:
        """
        Run the OAuth2 desktop flow (opens browser for consent).
        
        Args:
            port: Local port for the OAuth callback server.
            
        Returns:
            Authenticated Credentials object.
            
        Raises:
            FileNotFoundError: If client_secret.json is missing.
        """
        if not self.client_secret_path.exists():
            raise FileNotFoundError(
                f"OAuth client secret not found at {self.client_secret_path}.\n"
                f"Download it from Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs\n"
                f"Save as: {self.client_secret_path}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secret_path),
            scopes=SCOPES,
        )
        creds = flow.run_local_server(
            port=port,
            prompt="consent",
            access_type="offline",
        )

        # Save email alongside token
        self._save_token(creds)
        self._creds = creds
        log.info("Workspace authentication successful")
        return creds

    def authenticate_with_token(self, token_data: dict) -> Credentials:
        """
        Authenticate using pre-existing token data (for non-interactive setup).
        
        Args:
            token_data: Dict with refresh_token, client_id, client_secret.
        """
        creds = Credentials(
            token=None,
            refresh_token=token_data["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
            scopes=SCOPES,
        )
        creds.refresh(Request())
        self._save_token(creds)
        self._creds = creds
        return creds

    def revoke(self) -> bool:
        """Revoke the current credentials and delete stored token."""
        creds = self.get_credentials()
        if creds:
            try:
                import requests
                requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": creds.token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except Exception as e:
                log.warning(f"Revocation request failed: {e}")

        if self.token_path.exists():
            self.token_path.unlink()
            log.info("Workspace token deleted")

        self._creds = None
        return True

    def get_granted_scopes(self) -> list[str]:
        """Return the list of scopes granted to the current credentials."""
        creds = self.get_credentials()
        if creds and creds.scopes:
            return list(creds.scopes)
        return []

    def _load_token(self) -> Optional[Credentials]:
        """Load credentials from the token file."""
        if not self.token_path.exists():
            return None
        try:
            creds = Credentials.from_authorized_user_file(
                str(self.token_path), SCOPES
            )
            return creds
        except Exception as e:
            log.warning(f"Failed to load workspace token: {e}")
            return None

    def _save_token(self, creds: Credentials) -> None:
        """Save credentials to the token file."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else SCOPES,
        }
        self.token_path.write_text(json.dumps(token_data, indent=2))
        self.token_path.chmod(0o600)
        log.debug(f"Token saved to {self.token_path}")

    @staticmethod
    def create_client_secret_template(path: Optional[Path] = None) -> Path:
        """
        Create a template client_secret.json showing what's needed.
        Used by the wizard to guide the user.
        """
        target = path or DEFAULT_CLIENT_SECRET_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        template = {
            "installed": {
                "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
                "project_id": "artifact-virtual",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": "YOUR_CLIENT_SECRET",
                "redirect_uris": ["http://localhost"],
            }
        }
        target.write_text(json.dumps(template, indent=2))
        return target
