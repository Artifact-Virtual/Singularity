"""
CLI — Singularity Command Line Interface
============================================

Bootstrap, configure, inspect, and operate a Singularity
autonomous enterprise from the terminal.

Usage:
    singularity init                    # Interactive setup wizard
    singularity audit                   # Run workspace audit
    singularity status                  # Runtime status
    singularity spawn-exec ROLE         # Propose a new executive
    singularity poa create PRODUCT      # Create a Product Owner Agent
    singularity poa list                # List active POAs
    singularity poa audit PRODUCT       # Audit a product
    singularity scale-report            # Scaling analysis
"""

from .main import main
from .wizard import InitWizard
from .formatters import (
    fmt,
    Table,
    StatusBox,
    ProgressBar,
    banner,
    section,
    kv,
    success,
    error,
    warn,
    info,
    dim,
)

__all__ = [
    "main",
    "InitWizard",
    "fmt",
    "Table",
    "StatusBox",
    "ProgressBar",
    "banner",
    "section",
    "kv",
    "success",
    "error",
    "warn",
    "info",
    "dim",
]
