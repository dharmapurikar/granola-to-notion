"""Notion API client — database creation, page creation, and markdown-to-blocks."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from typing import Any

import requests

from src.config import CONFIG

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TIMEOUT = 60


# ---------------------------------------------------------------------------
# Markdown → Notion blocks
# ---------------------------------------------------------------------------

def parse_markdown_bold(text: str) -> list[dict[str, Any]]:
    """Parse **bold** syntax into Notion rich_text with annotations.

    WRONG:  {"text": {"content": "**text**"}}  — shows asterisks literally
    RIGHT:  {"text": {"content": "text"}, "annotations": {"bold": true}}
    """
    if not text:
        return [{"type": "text", "text": {"content": ""}}]

    parts: list[dict[str, Any]] = []
    last_end = 0

    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        if match.start() > last_end:
            before = text[last_end : match.start()].strip()
            if before:
                parts.append({"type": "text", "text": {"content": before}})
        bold_content = match.group(1).strip()
        if bold_content:
            parts.append({
                "type": "text",
                "text": {"content": bold_content},
                "annotations": {
                    "bold": True, "italic": False, "strikethrough": False,
                    "underline": False, "code": False, "color": "default",
                },
            })
        last_end = match.end()

    remaining = text[last_end:].strip()
    if remaining:
        parts.append({"type": "text", "text": {"content": remaining}})

    return parts if parts else [{"type": "text", "text": {"content": text}}]


def _safe_rich_text(text: str) -> list[dict[str, Any]]:
    """Chunk text into 2000-char segments for Notion's per-block limit."""
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    return [
        {"type": "text", "text": {"content": text[i : i + 2000]}}
        for i in range(0, len(text), 2000)
    ]


def _h_block(block_type: str, text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": _safe_rich_text(text)},
    }


def _paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": parse_markdown_bold(text)},
    }


def _bulleted(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": parse_markdown_bold(text)},
    }


def _numbered(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": parse_markdown_bold(text)},
    }


def _quote(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": parse_markdown_bold(text)},
    }


def _code_block(code: str, language: str = "markdown") -> list[dict[str, Any]]:
    """Yield code blocks, splitting on 2000-char limit."""
    return [
        {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}],
                "language": language,
            },
        }
        for i in range(0, len(code), 2000)
        for chunk in [code[i : i + 2000]]
    ]


def _callout(text: str, emoji: str = "📋") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": _safe_rich_text(text),
            "icon": {"emoji": emoji},
            "color": "default",
        },
    }


def _divider() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def _split_long_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Post-process: split any block whose rich_text exceeds 2000 chars.

    Notion enforces a 2000-char limit per rich_text content. Instead of
    truncating, we split long blocks into multiple blocks of the same type.
    """
    CHUNK = 1990  # 10-char safety margin below Notion's 2000 limit
    result: list[dict[str, Any]] = []

    for block in blocks:
        block_type = block.get("type")
        inner = block.get(block_type, {})
        rich_text = inner.get("rich_text", [])

        # Calculate total content length across all rich_text parts
        total_len = sum(part.get("text", {}).get("content", "").__len__() for part in rich_text)

        if total_len <= CHUNK or not rich_text:
            result.append(block)
            continue

        # Rebuild rich_text parts, splitting at the 2000-char boundary
        chunks: list[list[dict[str, Any]]] = []
        current_chunk: list[dict[str, Any]] = []
        current_len = 0

        for part in rich_text:
            content = part.get("text", {}).get("content", "")
            part_len = len(content)
            remaining_base = dict(part)
            remaining_base.pop("text", None)

            if not content:
                current_chunk.append(part)
                continue

            offset = 0
            while offset < part_len:
                available = CHUNK - current_len
                take = min(available, part_len - offset)

                new_part: dict[str, Any] = {
                    "type": part.get("type", "text"),
                    "text": {"content": content[offset : offset + take]},
                }
                if "annotations" in part:
                    new_part["annotations"] = part["annotations"]

                current_chunk.append(new_part)
                current_len += take
                offset += take

                if current_len >= CHUNK:
                    chunks.append(current_chunk)
                    current_chunk = []
                    current_len = 0

        if current_chunk:
            chunks.append(current_chunk)

        # Emit one block per chunk
        for i, chunk_rich in enumerate(chunks):
            new_block: dict[str, Any] = {"object": "block", "type": block_type}
            new_block[block_type] = {**inner, "rich_text": chunk_rich}
            # Don't carry over code language or other nested fields that are
            # already set on the inner dict — keep them as-is via **inner
            result.append(new_block)

    return result


def markdown_to_notion_blocks(markdown: str) -> list[dict[str, Any]]:
    """Convert a markdown string into a list of Notion block dicts.

    Handles: headings, bold, bullets, numbered lists, quotes, code blocks,
    tables (as bullet lists with em-dash separator), and paragraphs.
    """
    blocks: list[dict[str, Any]] = []
    lines = markdown.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        # Code fences
        if line.strip().startswith("```"):
            lang = line.strip()[3:] or "markdown"
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].rstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            blocks.extend(_code_block("\n".join(code_lines), lang))
            i += 1
            continue

        # Headings
        if line.startswith("# ") and not line.startswith("##"):
            blocks.append(_h_block("heading_1", line[2:].strip()))
        elif line.startswith("## ") and not line.startswith("###"):
            blocks.append(_h_block("heading_2", line[3:].strip()))
        elif line.startswith("### "):
            blocks.append(_h_block("heading_3", line[4:].strip()))

        # Quote
        elif line.startswith("> "):
            blocks.append(_quote(line[2:].strip()))

        # Horizontal rule
        elif re.match(r"^---+$", line.strip()):
            blocks.append(_divider())

        # Table row — skip separator lines, render as bullet with em-dash
        elif line.startswith("|"):
            if re.match(r"^\|[-:|\s]+\|$", line):
                i += 1
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if cells:
                blocks.append(_bulleted(" — ".join(cells)))

        # Bullet
        elif re.match(r"^[-*]\s", line):
            blocks.append(_bulleted(line[2:].strip()))

        # Numbered list
        elif re.match(r"^\d+\.\s", line):
            blocks.append(_numbered(re.sub(r"^\d+\.\s", "", line, count=1)))

        # Empty line
        elif not line:
            pass

        # Fallback: paragraph
        else:
            blocks.append(_paragraph(line))

        i += 1

    return _split_long_blocks(blocks)


# ---------------------------------------------------------------------------
# Granola note → Notion page builder
# ---------------------------------------------------------------------------

def _fmt_time(iso: str) -> str:
    """Convert ISO 8601 datetime to human-readable HH:MM."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        return iso


def build_note_blocks(note: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the full list of Notion blocks for a Granola note.

    Includes:
      1. Meeting metadata callout (title, date, attendees, organizer)
      2. AI Summary (from summary_markdown, rendered as markdown blocks)
      3. Divider
      4. Raw Transcript (speaker labels + timestamps + line-by-line text)
    """
    blocks: list[dict[str, Any]] = []

    # ---- 1. Metadata callout ----
    title = note.get("title") or "Untitled Meeting"
    cal = note.get("calendar_event") or {}
    attendees = note.get("attendees") or []
    owner = note.get("owner") or {}

    start = cal.get("scheduled_start_time", "")
    end = cal.get("scheduled_end_time", "")
    date_str = _fmt_time(start) if start else ""
    if end:
        date_str = f"{date_str} – {_fmt_time(end)}" if date_str else _fmt_time(end)

    attendee_names = ", ".join(a.get("name", a.get("email", "")) for a in attendees) or "—"
    organizer = cal.get("organiser", owner.get("email", "—"))

    meta_lines = [
        f"**Title:** {title}",
        f"**Date:** {date_str}",
        f"**Organizer:** {organizer}",
        f"**Attendees:** {attendee_names}",
    ]
    blocks.append(_callout("\n".join(meta_lines), emoji="📅"))

    # ---- 2. AI Summary ----
    summary_md = note.get("summary_markdown") or note.get("summary_text")
    if summary_md:
        blocks.append(_h_block("heading_2", "AI Summary"))
        blocks.append(_divider())
        blocks.extend(markdown_to_notion_blocks(summary_md))

    # ---- 3. Transcript ----
    transcript = note.get("transcript") or []
    if transcript:
        blocks.append(_h_block("heading_2", "Transcript"))
        blocks.append(_divider())

        for entry in transcript:
            speaker = entry.get("speaker", {}) or {}
            source = speaker.get("source", "unknown")  # "microphone" | "speaker"
            label = "🟢 You" if source == "microphone" else "🔵 Speaker"
            start_t = entry.get("start_time", "")
            end_t = entry.get("end_time", "")
            time_str = f"[{_fmt_time(start_t)} – {_fmt_time(end_t)}]" if start_t and end_t else ""
            text = entry.get("text", "").strip()

            if time_str:
                blocks.append(_bulleted(f"{label} {time_str}: {text}"))
            else:
                blocks.append(_bulleted(f"{label}: {text}"))

    return _split_long_blocks(blocks)


# ---------------------------------------------------------------------------
# Notion API client
# ---------------------------------------------------------------------------

class NotionClient:
    """Client for the Notion API.

    Handles: database creation, page creation, block appending, and page searching.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or CONFIG["notion"].get("api_key") or os.getenv("NOTION_API_KEY")
        if not self.api_key:
            raise ValueError("NOTION_API_KEY is required")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(f"{BASE_URL}{path}", headers=self._headers(), json=data, timeout=TIMEOUT)
        if not resp.ok:
            raise NotionError(f"Notion API error {resp.status_code}: {resp.text}", resp)
        return resp.json()

    def _patch(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        resp = requests.patch(f"{BASE_URL}{path}", headers=self._headers(), json=data, timeout=TIMEOUT)
        if not resp.ok:
            raise NotionError(f"Notion API error {resp.status_code}: {resp.text}", resp)
        return resp.json()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = requests.get(f"{BASE_URL}{path}", headers=self._headers(), params=params, timeout=TIMEOUT)
        if not resp.ok:
            raise NotionError(f"Notion API error {resp.status_code}: {resp.text}", resp)
        return resp.json()

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------
    def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
            "is_inline": True,
        }
        return self._post("/databases", payload)

    def search_databases(self, query: str) -> list[dict[str, Any]]:
        data = self._post("/search", {
            "query": query,
            "filter": {"value": "database", "property": "object"},
        })
        return data.get("results", [])

    def search_pages(self, query: str) -> list[dict[str, Any]]:
        data = self._post("/search", {"query": query})
        return data.get("results", [])

    # ------------------------------------------------------------------
    # Page operations
    # ------------------------------------------------------------------
    def create_page(
        self,
        database_id: str,
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a page inside a database, optionally with block children."""
        payload: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if children:
            payload["children"] = children[:100]  # API limit per request

        result = self._post("/pages", payload)

        if children and len(children) > 100:
            self._append_blocks_recursive(result["id"], children[100:])

        return result

    def _append_blocks_recursive(self, page_id: str, blocks: list[dict[str, Any]]) -> None:
        """Append blocks in batches of 100 to a page's children."""
        while blocks:
            batch, blocks = blocks[:100], blocks[100:]
            self._patch(f"/blocks/{page_id}/children", {"children": batch})
            time.sleep(0.15)  # Rate limiting

    def append_blocks(self, page_id: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        if not blocks:
            return {}
        result = self._patch(f"/blocks/{page_id}/children", {"children": blocks[:100]})
        if len(blocks) > 100:
            self._append_blocks_recursive(page_id, blocks[100:])
        return result

    def get_page(self, page_id: str) -> dict[str, Any]:
        return self._get(f"/pages/{page_id}")

    def get_page_blocks(self, page_id: str) -> dict[str, Any]:
        return self._get(f"/blocks/{page_id}/children")

    def archive_page(self, page_id: str) -> dict[str, Any]:
        return self._patch(f"/pages/{page_id}", {"archived": True})

    def delete_blocks(self, page_id: str) -> None:
        """Delete all existing children of a page (for overwrite mode)."""
        while True:
            data = self._get(f"/blocks/{page_id}/children")
            children = data.get("results", [])
            if not children:
                break
            for block in children:
                requests.delete(
                    f"{BASE_URL}/blocks/{block['id']}",
                    headers=self._headers(),
                    timeout=TIMEOUT,
                )
                time.sleep(0.1)
            if not data.get("has_more"):
                break


class NotionError(Exception):
    def __init__(self, message: str, response: requests.Response | None = None) -> None:
        super().__init__(message)
        self.response = response
