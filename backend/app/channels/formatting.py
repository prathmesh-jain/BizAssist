"""Turn the assistant's Markdown into what each app displays, and split long replies."""
from __future__ import annotations

import html
import re

WHATSAPP_LIMIT = 4096
TELEGRAM_LIMIT = 4096
_SAFETY = 200  # headroom for markup added after splitting

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)
_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)([^*\n]+?)\*(?![*\w])|(?<![_\w])_(?!\s)([^_\n]+?)_(?![_\w])")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_BULLET = re.compile(r"^(\s*)[-*+]\s+", re.M)
_CODE_BLOCK = re.compile(r"```[a-zA-Z0-9_-]*\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_CITATION = re.compile(r"\s*\[Source:\s*[^\]]+\]")


def _common(text: str) -> str:
    text = _CITATION.sub("", text or "")
    text = _BULLET.sub(lambda m: f"{m.group(1)}• ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_whatsapp(markdown: str) -> str:
    """WhatsApp: *bold*, _italic_, ```code```; no links or headings."""
    text = _common(markdown)
    text = _ITALIC.sub(lambda m: f"_{m.group(1) or m.group(2)}_", text)
    text = _BOLD.sub(lambda m: f"*{m.group(1) or m.group(2)}*", text)
    text = _HEADING.sub(lambda m: f"*{m.group(1).strip('*')}*", text)  # last, so it isn't read as italic
    text = _LINK.sub(lambda m: m.group(2) if m.group(1) == m.group(2) else f"{m.group(1)}: {m.group(2)}", text)
    return text


def to_telegram_html(markdown: str) -> str:
    """Telegram HTML parse mode: escape everything, then add the few tags it supports."""
    text = _common(markdown)
    blocks: list[str] = []

    def stash_block(m: re.Match) -> str:
        blocks.append(f"<pre>{html.escape(m.group(1).rstrip())}</pre>")
        return f"\x00{len(blocks) - 1}\x00"

    text = _CODE_BLOCK.sub(stash_block, text)
    text = html.escape(text, quote=False)
    text = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', text)
    text = _HEADING.sub(lambda m: f"<b>{m.group(1).strip('*')}</b>", text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)
    return re.sub("\x00(\\d+)\x00", lambda m: blocks[int(m.group(1))], text)


def split_message(text: str, limit: int) -> list[str]:
    """Split on paragraph, then line, then word boundaries so each part fits `limit`."""
    limit = max(limit - _SAFETY, 100)
    text = (text or "").strip()
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 3:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 3:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 3:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts
