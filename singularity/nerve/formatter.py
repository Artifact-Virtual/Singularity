"""
NERVE — Outbound Formatter
=============================

Converts agent markdown output to platform-native formatting.
Each platform has its own dialect. We preserve intent, not syntax.

Ported from Mach6's formatter.ts.
"""

from __future__ import annotations

import re
from typing import Optional

from .types import ChannelCapabilities, FormattingDialect


# ── Split Utility ────────────────────────────────────────────────────

def split_on_boundaries(
    text: str,
    max_length: int,
    boundaries: Optional[list[str]] = None,
) -> list[str]:
    """
    Split text on natural boundaries (paragraphs, sentences, words)
    without breaking mid-word or mid-code-block.
    """
    if len(text) <= max_length:
        return [text]

    boundaries = boundaries or ["\n\n", "\n", ". ", " "]
    chunks: list[str] = []
    remaining = text

    while len(remaining) > max_length:
        split_at = -1

        for boundary in boundaries:
            search_area = remaining[:max_length]
            last_idx = search_area.rfind(boundary)
            if last_idx > int(max_length * 0.3):
                split_at = last_idx + len(boundary)
                break

        if split_at <= 0:
            split_at = max_length

        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


# ── Platform Formatters ─────────────────────────────────────────────

def _format_discord(markdown: str) -> str:
    """Discord supports standard markdown. Just strip HTML and fix tables."""
    result = markdown

    # Strip HTML tags
    result = re.sub(r"<[^>]+>", "", result)

    # Convert markdown tables to code blocks (Discord doesn't render tables)
    result = re.sub(
        r"(\|[^\n]+\|\n)((?:\|[-:| ]+\|\n))((?:\|[^\n]+\|\n?)+)",
        lambda m: f"```\n{m.group(1)}{m.group(2)}{m.group(3)}```\n",
        result,
    )

    return result.strip()


def _format_whatsapp(markdown: str) -> str:
    """Convert markdown to WhatsApp-native formatting."""
    result = markdown

    # Headers → bold (WhatsApp has no headers)
    result = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", result, flags=re.MULTILINE)

    # Bold **text** → *text*
    result = re.sub(r"\*\*(.+?)\*\*", r"*\1*", result)

    # Strikethrough ~~text~~ → ~text~
    result = re.sub(r"~~(.+?)~~", r"~\1~", result)

    # Strip HTML
    result = re.sub(r"<[^>]+>", "", result)

    # Links [text](url) → text: url
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1: \2", result)

    # Image markdown ![alt](url) → url
    result = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\2", result)

    # Tables → bullet lists
    def _table_to_bullets(m):
        header_cells = _parse_pipe_row(m.group(1))
        rows = m.group(3).strip().split("\n")
        lines = []
        for row in rows:
            cells = _parse_pipe_row(row)
            parts = []
            for i, cell in enumerate(cells):
                if i < len(header_cells) and header_cells[i]:
                    parts.append(f"*{header_cells[i]}:* {cell}")
                else:
                    parts.append(cell)
            lines.append("• " + ", ".join(parts))
        return "\n".join(lines) + "\n"

    result = re.sub(
        r"(\|[^\n]+\|\n)((?:\|[-:| ]+\|\n))((?:\|[^\n]+\|\n?)+)",
        _table_to_bullets,
        result,
    )

    return result.strip()


def _format_plain(markdown: str) -> str:
    """Strip all markdown formatting."""
    result = markdown
    result = re.sub(r"^#{1,6}\s+", "", result, flags=re.MULTILINE)
    result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)
    result = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"\1", result)
    result = re.sub(r"~~(.+?)~~", r"\1", result)
    result = re.sub(r"`([^`]+)`", r"\1", result)
    result = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).replace("```", "").strip(), result)
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", result)
    result = re.sub(r"<[^>]+>", "", result)
    return result.strip()


def _parse_pipe_row(row: str) -> list[str]:
    """Parse a markdown table row into cells."""
    return [cell.strip() for cell in row.split("|") if cell.strip()]


# ── Formatter Registry ──────────────────────────────────────────────

_FORMATTERS = {
    FormattingDialect.MARKDOWN: (_format_discord, 2000),
    FormattingDialect.WHATSAPP: (_format_whatsapp, 4096),
    FormattingDialect.PLAIN: (_format_plain, 4096),
}


def format_for_channel(
    markdown: str,
    capabilities: ChannelCapabilities,
) -> list[str]:
    """
    Format and split a message for a specific channel.
    
    Returns a list of chunks, each within the platform's message length limit.
    """
    fmt_fn, default_max = _FORMATTERS.get(
        capabilities.formatting, (_format_plain, 4096)
    )
    formatted = fmt_fn(markdown)
    max_len = capabilities.max_message_length or default_max
    return split_on_boundaries(formatted, max_len)
