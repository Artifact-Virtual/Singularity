"""
SINEW — Sandbox & Safety
===========================

Path validation, command filtering, and safety enforcement.
Separated from executor for clarity and testability.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("singularity.sinew.sandbox")

# ── Allowed path prefixes ──
ALLOWED_PATHS = [
    "/home/adam",
    "/tmp",
    "/var/log",
    "/etc",  # read-only access patterns
]

# ── Blocked command patterns ──
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/\s*$",           # rm -rf /
    r"rm\s+-rf\s+/\w",             # rm -rf /anything (root level)
    r"mkfs\b",                      # filesystem formatting
    r"dd\s+if=.*of=/dev",          # raw device writes
    r":\(\)\s*\{\s*:\|:&\s*\};:",  # fork bomb
    r"shutdown\b",                  # system shutdown
    r"reboot\b",                    # system reboot
    r"init\s+[06]",                # init shutdown/reboot
    r"chmod\s+.*777\s+/",          # chmod 777 on root paths
    r"chown\s+.*root",             # chown to root
    r"passwd\b",                    # password changes
    r"userdel\b",                   # user deletion
]

_blocked_re = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS]


def validate_path(path: str) -> str | None:
    """Validate a file path. Returns violation message or None if OK.
    
    Rules:
    - Must be under an allowed prefix
    - No path traversal (.. resolution checked against allowed paths)
    - No /proc, /sys, /dev writes
    """
    try:
        resolved = str(Path(path).resolve())
    except Exception as e:
        return f"Invalid path: {e}"
    
    # Check allowed prefixes
    allowed = any(resolved.startswith(p) for p in ALLOWED_PATHS)
    if not allowed:
        return f"Path outside allowed directories: {resolved}"
    
    # Block sensitive paths even within allowed dirs
    sensitive = [
        ".ssh/", ".gnupg/", ".aws/", ".kube/",
        "id_rsa", "id_ed25519", ".env",
    ]
    for s in sensitive:
        if s in resolved and "workspace" not in resolved:
            return f"Sensitive path blocked: {resolved}"
    
    return None


def validate_command(command: str) -> str | None:
    """Validate a shell command. Returns violation message or None if OK.
    
    Rules:
    - No destructive system commands
    - No fork bombs
    - No password/user manipulation
    """
    for pattern in _blocked_re:
        if pattern.search(command):
            return f"Destructive command blocked: matches {pattern.pattern}"
    
    return None
