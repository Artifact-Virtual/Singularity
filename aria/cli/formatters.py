"""
CLI — Formatters
==================

Terminal output formatting. Colors, tables, progress, box drawing.
Pure stdlib — no rich, no click, no dependencies.

Design: professional, terse, scannable. ANSI codes with
graceful fallback when stdout isn't a tty.
"""

from __future__ import annotations

import os
import sys
import shutil
from typing import Any, Optional

# ── ANSI Color Codes ──────────────────────────────────────────────

_FORCE_COLOR = os.environ.get("FORCE_COLOR", "")
_NO_COLOR = os.environ.get("NO_COLOR", "")
_IS_TTY = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
_COLOR_ENABLED = (_IS_TTY or _FORCE_COLOR) and not _NO_COLOR


class _C:
    """ANSI escape sequences. Empty strings when color is disabled."""
    RESET   = "\033[0m"   if _COLOR_ENABLED else ""
    BOLD    = "\033[1m"   if _COLOR_ENABLED else ""
    DIM     = "\033[2m"   if _COLOR_ENABLED else ""
    ITALIC  = "\033[3m"   if _COLOR_ENABLED else ""
    UNDER   = "\033[4m"   if _COLOR_ENABLED else ""

    # Standard
    BLACK   = "\033[30m"  if _COLOR_ENABLED else ""
    RED     = "\033[31m"  if _COLOR_ENABLED else ""
    GREEN   = "\033[32m"  if _COLOR_ENABLED else ""
    YELLOW  = "\033[33m"  if _COLOR_ENABLED else ""
    BLUE    = "\033[34m"  if _COLOR_ENABLED else ""
    MAGENTA = "\033[35m"  if _COLOR_ENABLED else ""
    CYAN    = "\033[36m"  if _COLOR_ENABLED else ""
    WHITE   = "\033[37m"  if _COLOR_ENABLED else ""

    # Bright
    BR_RED     = "\033[91m"  if _COLOR_ENABLED else ""
    BR_GREEN   = "\033[92m"  if _COLOR_ENABLED else ""
    BR_YELLOW  = "\033[93m"  if _COLOR_ENABLED else ""
    BR_BLUE    = "\033[94m"  if _COLOR_ENABLED else ""
    BR_MAGENTA = "\033[95m"  if _COLOR_ENABLED else ""
    BR_CYAN    = "\033[96m"  if _COLOR_ENABLED else ""

    # Backgrounds
    BG_RED     = "\033[41m"  if _COLOR_ENABLED else ""
    BG_GREEN   = "\033[42m"  if _COLOR_ENABLED else ""
    BG_YELLOW  = "\033[43m"  if _COLOR_ENABLED else ""
    BG_BLUE    = "\033[44m"  if _COLOR_ENABLED else ""
    BG_MAGENTA = "\033[45m"  if _COLOR_ENABLED else ""
    BG_CYAN    = "\033[46m"  if _COLOR_ENABLED else ""


# ── Public color reference ────────────────────────────────────────

fmt = _C


# ── Box Drawing Characters ───────────────────────────────────────

class _Box:
    """Unicode box-drawing characters."""
    TL = "┌"  # top-left
    TR = "┐"  # top-right
    BL = "└"  # bottom-left
    BR = "┘"  # bottom-right
    H  = "─"  # horizontal
    V  = "│"  # vertical
    LT = "├"  # left-tee
    RT = "┤"  # right-tee
    TT = "┬"  # top-tee
    BT = "┴"  # bottom-tee
    X  = "┼"  # cross

    # Heavy
    HH = "━"
    HV = "┃"
    HTL = "┏"
    HTR = "┓"
    HBL = "┗"
    HBR = "┛"


BOX = _Box


# ── Terminal Width ────────────────────────────────────────────────

def _term_width() -> int:
    """Get terminal width, default 80."""
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80


# ── Simple Formatters ─────────────────────────────────────────────

def success(msg: str) -> str:
    return f"{fmt.BR_GREEN}✓{fmt.RESET} {msg}"

def error(msg: str) -> str:
    return f"{fmt.BR_RED}✗{fmt.RESET} {msg}"

def warn(msg: str) -> str:
    return f"{fmt.BR_YELLOW}⚠{fmt.RESET} {msg}"

def info(msg: str) -> str:
    return f"{fmt.BR_CYAN}ℹ{fmt.RESET} {msg}"

def dim(msg: str) -> str:
    return f"{fmt.DIM}{msg}{fmt.RESET}"

def bold(msg: str) -> str:
    return f"{fmt.BOLD}{msg}{fmt.RESET}"


def kv(key: str, value: Any, key_width: int = 20) -> str:
    """Format a key-value pair with aligned columns."""
    k = f"{fmt.CYAN}{key}{fmt.RESET}"
    # Pad using visible length (strip ANSI for measurement)
    pad = " " * max(0, key_width - len(key))
    return f"  {k}{pad} {value}"


def section(title: str, char: str = "─") -> str:
    """Section divider with title."""
    w = _term_width()
    title_part = f" {title} "
    remaining = max(0, w - len(title_part) - 2)
    left = remaining // 2
    right = remaining - left
    return f"{fmt.DIM}{char * left}{fmt.RESET}{fmt.BOLD}{title_part}{fmt.RESET}{fmt.DIM}{char * right}{fmt.RESET}"


def banner(lines: list[str], color: str = "") -> str:
    """Draw a box around lines of text."""
    w = _term_width()
    inner_w = min(w - 4, max((len(line) for line in lines), default=40) + 4)
    c = color or fmt.BR_MAGENTA

    parts = []
    parts.append(f"{c}{BOX.HTL}{BOX.HH * (inner_w + 2)}{BOX.HTR}{fmt.RESET}")
    for line in lines:
        pad = inner_w - len(line)
        parts.append(f"{c}{BOX.HV}{fmt.RESET} {line}{' ' * pad} {c}{BOX.HV}{fmt.RESET}")
    parts.append(f"{c}{BOX.HBL}{BOX.HH * (inner_w + 2)}{BOX.HBR}{fmt.RESET}")
    return "\n".join(parts)


# ── StatusBox ─────────────────────────────────────────────────────

class StatusBox:
    """
    A labeled status box for displaying system state.

    Usage:
        box = StatusBox("Runtime")
        box.add("Uptime", "4h 23m")
        box.add("Status", "HEALTHY", color=fmt.BR_GREEN)
        print(box.render())
    """

    def __init__(self, title: str, width: int = 0):
        self.title = title
        self.width = width or min(_term_width(), 60)
        self._rows: list[tuple[str, str, str]] = []

    def add(self, key: str, value: Any, color: str = "") -> "StatusBox":
        self._rows.append((key, str(value), color))
        return self

    def render(self) -> str:
        inner = self.width - 4  # 2 for border + 2 for padding
        key_w = max((len(k) for k, _, _ in self._rows), default=12) + 2

        parts = []
        # Title bar
        title_str = f" {self.title} "
        title_len = len(title_str)
        left_pad = 2
        right_pad = max(0, self.width - 2 - left_pad - title_len)
        parts.append(
            f"{fmt.BOLD}{fmt.BR_MAGENTA}"
            f"{BOX.TL}{BOX.H * left_pad}{fmt.RESET}"
            f"{fmt.BOLD} {self.title} {fmt.RESET}"
            f"{fmt.BR_MAGENTA}{BOX.H * right_pad}{BOX.TR}{fmt.RESET}"
        )

        for key, value, color in self._rows:
            k_str = f"{fmt.CYAN}{key}{fmt.RESET}"
            pad = " " * max(0, key_w - len(key))
            v_str = f"{color}{value}{fmt.RESET}" if color else value
            line = f"  {k_str}{pad}{v_str}"

            # Right-pad to fill box (approximate — ANSI codes mess up len)
            visible_len = len(key) + key_w - len(key) + 2 + len(value)
            r_pad = max(0, inner - visible_len)
            parts.append(
                f"{fmt.BR_MAGENTA}{BOX.V}{fmt.RESET}"
                f"{line}{' ' * r_pad}"
                f" {fmt.BR_MAGENTA}{BOX.V}{fmt.RESET}"
            )

        parts.append(
            f"{fmt.BR_MAGENTA}{BOX.BL}{BOX.H * (self.width - 2)}{BOX.BR}{fmt.RESET}"
        )

        return "\n".join(parts)


# ── Table ─────────────────────────────────────────────────────────

class Table:
    """
    Simple table renderer with column alignment.

    Usage:
        t = Table(["Name", "Status", "Uptime"])
        t.add(["CTO", "active", "4h"])
        t.add(["COO", "idle", "4h"])
        print(t.render())
    """

    def __init__(self, headers: list[str], align: Optional[list[str]] = None):
        """
        Args:
            headers: Column header names
            align: Per-column alignment: 'l' (left), 'r' (right), 'c' (center).
                   Defaults to left-aligned.
        """
        self.headers = headers
        self.align = align or ["l"] * len(headers)
        self._rows: list[list[str]] = []

    def add(self, row: list[Any]) -> "Table":
        self._rows.append([str(v) for v in row])
        return self

    def add_separator(self) -> "Table":
        """Add a horizontal separator row."""
        self._rows.append(None)  # type: ignore
        return self

    def _col_widths(self) -> list[int]:
        """Calculate column widths from headers + data."""
        widths = [len(h) for h in self.headers]
        for row in self._rows:
            if row is None:
                continue
            for i, cell in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(cell))
        return widths

    def _align_cell(self, text: str, width: int, alignment: str) -> str:
        """Align a cell value within its column width."""
        if alignment == "r":
            return text.rjust(width)
        elif alignment == "c":
            return text.center(width)
        return text.ljust(width)

    def render(self) -> str:
        if not self.headers:
            return ""

        widths = self._col_widths()
        parts = []

        # Top border
        segs = [BOX.H * (w + 2) for w in widths]
        parts.append(f"{BOX.TL}{BOX.TT.join(segs)}{BOX.TR}")

        # Header row
        cells = []
        for i, h in enumerate(self.headers):
            w = widths[i] if i < len(widths) else len(h)
            cells.append(f" {fmt.BOLD}{self._align_cell(h, w, self.align[i])}{fmt.RESET} ")
        parts.append(BOX.V + BOX.V.join(cells) + BOX.V)

        # Header separator
        segs = [BOX.H * (w + 2) for w in widths]
        parts.append(f"{BOX.LT}{BOX.X.join(segs)}{BOX.RT}")

        # Data rows
        for row in self._rows:
            if row is None:
                # Separator
                segs = [BOX.H * (w + 2) for w in widths]
                parts.append(f"{BOX.LT}{BOX.X.join(segs)}{BOX.RT}")
                continue

            cells = []
            for i, cell in enumerate(row):
                w = widths[i] if i < len(widths) else len(cell)
                a = self.align[i] if i < len(self.align) else "l"
                cells.append(f" {self._align_cell(cell, w, a)} ")
            parts.append(f"{BOX.V}{BOX.V.join(cells)}{BOX.V}")

        # Bottom border
        segs = [BOX.H * (w + 2) for w in widths]
        parts.append(f"{BOX.BL}{BOX.BT.join(segs)}{BOX.BR}")

        return "\n".join(parts)


# ── Progress Bar ──────────────────────────────────────────────────

class ProgressBar:
    """
    Simple progress bar for terminal output.

    Usage:
        bar = ProgressBar(total=100, label="Processing")
        for i in range(100):
            bar.update(i + 1)
        bar.finish()
    """

    FILL = "█"
    EMPTY = "░"

    def __init__(
        self,
        total: int,
        label: str = "",
        width: int = 30,
        show_pct: bool = True,
        show_count: bool = True,
    ):
        self.total = max(total, 1)
        self.label = label
        self.width = width
        self.show_pct = show_pct
        self.show_count = show_count
        self._current = 0

    def update(self, current: int) -> None:
        """Update progress and redraw."""
        self._current = min(current, self.total)
        self._draw()

    def finish(self) -> None:
        """Mark complete and print newline."""
        self._current = self.total
        self._draw()
        print()

    def _draw(self) -> None:
        ratio = self._current / self.total
        filled = int(self.width * ratio)
        empty = self.width - filled

        bar = f"{fmt.BR_GREEN}{self.FILL * filled}{fmt.RESET}{fmt.DIM}{self.EMPTY * empty}{fmt.RESET}"

        parts = []
        if self.label:
            parts.append(f"{self.label} ")
        parts.append(f"{bar}")
        if self.show_pct:
            parts.append(f" {ratio * 100:5.1f}%")
        if self.show_count:
            parts.append(f" ({self._current}/{self.total})")

        line = "".join(parts)
        print(f"\r{line}", end="", flush=True)


# ── Spinner ───────────────────────────────────────────────────────

class Spinner:
    """
    Terminal spinner for indeterminate progress.

    Usage:
        spin = Spinner("Loading")
        spin.start()
        # ... do work ...
        spin.stop("Done!")
    """

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str = ""):
        self.label = label
        self._frame = 0

    def tick(self) -> str:
        """Return the next spinner frame as a formatted string."""
        frame = self.FRAMES[self._frame % len(self.FRAMES)]
        self._frame += 1
        return f"\r{fmt.BR_CYAN}{frame}{fmt.RESET} {self.label}"

    def done(self, msg: str = "Done") -> str:
        """Return a completion message."""
        return f"\r{success(msg)}"


# ── Utility ───────────────────────────────────────────────────────

def indent(text: str, spaces: int = 2) -> str:
    """Indent a multi-line string."""
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.split("\n"))


def truncate(text: str, max_len: int = 60, suffix: str = "…") -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix


def human_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 0:
        return "0s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s" if s else f"{m}m"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m" if m else f"{h}h"


def human_bytes(n: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024  # type: ignore
    return f"{n:.1f} PB"


def status_dot(healthy: bool) -> str:
    """Return a colored status indicator."""
    if healthy:
        return f"{fmt.BR_GREEN}●{fmt.RESET}"
    return f"{fmt.BR_RED}●{fmt.RESET}"

def header(title: str) -> None:
    """Print a section header."""
    print()
    print(banner([title]))
    print()

