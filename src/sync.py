"""Sync engine — orchestrates Granola → SQLite → Notion pipeline."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

from src.config import CONFIG
from src.db import GranolaStore
from src.granola_client import GranolaClient
from src.notion_client import NotionClient, build_note_blocks


# ---------------------------------------------------------------------------
# Notion database schema for "Granola Meeting Imports"
# ---------------------------------------------------------------------------

NOTION_PROPERTIES = {
    "Meeting name": {"title": {}},
    "Date": {"date": {}},
    "Attendees": {"rich_text": {}},
    "Organizer": {"rich_text": {}},
    "Summary": {"rich_text": {}},
    "Category": {
        "select": {
            "options": [
                {"name": "Meeting", "color": "blue"},
                {"name": "Standup", "color": "red"},
                {"name": "1:1", "color": "orange"},
                {"name": "Customer call", "color": "green"},
                {"name": "Retro", "color": "yellow"},
                {"name": "Planning", "color": "purple"},
                {"name": "Presentation", "color": "pink"},
                {"name": "Discussion", "color": "gray"},
                {"name": "Other", "color": "default"},
            ]
        }
    },
    "Source URL": {"url": {}},
    "Granola ID": {"rich_text": {}},
    "Synced At": {"date": {}},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_category(title: str | None) -> str:
    """Simple keyword-based category inference."""
    if not title:
        return "Meeting"
    t = title.lower()
    if "standup" in t or "daily" in t:
        return "Standup"
    if "1:1" in t or "one-on-one" in t or "1on1" in t:
        return "1:1"
    if "customer" in t or "client" in t:
        return "Customer call"
    if "retro" in t or "retrospective" in t:
        return "Retro"
    if "planning" in t:
        return "Planning"
    if "present" in t:
        return "Presentation"
    if "discussion" in t:
        return "Discussion"
    return "Meeting"


def _fmt_date(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return iso[:10]  # YYYY-MM-DD
    except Exception:
        return None


def _attendees_str(note: dict[str, Any]) -> str:
    attendees = note.get("attendees") or []
    return ", ".join(a.get("name", a.get("email", "")) for a in attendees) or ""


def _organizer(note: dict[str, Any]) -> str:
    cal = note.get("calendar_event") or {}
    owner = note.get("owner") or {}
    return cal.get("organiser") or owner.get("email") or ""


# ---------------------------------------------------------------------------
# SyncEngine
# ---------------------------------------------------------------------------

class SyncEngine:
    """Orchestrates the full Granola → SQLite → Notion sync."""

    def __init__(
        self,
        db: GranolaStore | None = None,
        granola_client: GranolaClient | None = None,
        notion_client: NotionClient | None = None,
    ) -> None:
        self.store = db or GranolaStore()
        self.granola = granola_client or GranolaClient()
        self.notion = notion_client or NotionClient()
        self.cfg = CONFIG
        self._database_id: str | None = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def ensure_database(self, force: bool = False) -> str:
        """Create (or find) the Notion database. Returns the database_id."""
        db_name = self.cfg["notion"]["database_name"]
        parent_id = self.cfg["notion"]["parent_page_id"]

        if not force:
            existing = self.notion.search_databases(db_name)
            for db in existing:
                if db.get("title"):
                    title_text = db["title"][0].get("plain_text", "") if db["title"] else ""
                    if title_text == db_name:
                        self._database_id = db["id"]
                        print(f"Found existing database: {db_name} ({self._database_id})")
                        return self._database_id

        print(f"Creating new database: {db_name}")
        result = self.notion.create_database(parent_id, db_name, NOTION_PROPERTIES)
        self._database_id = result["id"]
        print(f"Created database: {db_name} ({self._database_id})")
        return self._database_id

    @property
    def database_id(self) -> str:
        if not self._database_id:
            self.ensure_database()
        return self._database_id  # type: ignore

    # ------------------------------------------------------------------
    # Fetch & store
    # ------------------------------------------------------------------
    def fetch_from_granola(self) -> int:
        """Fetch all notes from Granola and persist to SQLite. Returns count."""
        count = self.granola.fetch_and_store_all(self.store)
        print(f"\nStored {count} notes from Granola to SQLite.")
        return count

    # ------------------------------------------------------------------
    # Push to Notion
    # ------------------------------------------------------------------
    def _build_notion_properties(self, note: dict[str, Any]) -> dict[str, Any]:
        """Map a Granola note to Notion database page properties."""
        title = note.get("title") or "Untitled Meeting"
        cal = note.get("calendar_event") or {}
        start = cal.get("scheduled_start_time") or note.get("created_at")
        summary = note.get("summary_text") or ""

        return {
            "Meeting name": {"title": [{"text": {"content": title}}]},
            "Date": {"date": {"start": _fmt_date(start)}},
            "Attendees": {"rich_text": [{"text": {"content": _attendees_str(note)}}]},
            "Organizer": {"rich_text": [{"text": {"content": _organizer(note)}}]},
            "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]},
            "Category": {"select": {"name": _infer_category(title)}},
            "Source URL": {"url": f"https://app.granola.ai/notes/{note.get('id')}"},
            "Granola ID": {"rich_text": [{"text": {"content": note.get("id", "")}}]},
            "Synced At": {"date": {"start": datetime.now(timezone.utc).isoformat()[:10]}},
        }

    def push_note(self, note: dict[str, Any], overwrite: bool = False) -> str | None:
        """Push a single note to Notion. Returns the new page_id or None on failure."""
        granola_id = note.get("id")
        if not granola_id:
            return None

        # Check if already pushed
        existing_page_id = self.store.get_notion_page_id(granola_id)
        if existing_page_id and not overwrite:
            print(f"  [{granola_id}] Already synced as {existing_page_id} — skipping (use --overwrite to replace)")
            return existing_page_id

        # Build blocks (summary + full transcript)
        blocks = build_note_blocks(note)
        notion_props = self._build_notion_properties(note)

        try:
            if overwrite and existing_page_id:
                print(f"  [{granola_id}] Overwriting existing Notion page {existing_page_id}")
                self.notion.delete_blocks(existing_page_id)
                page = self.notion.create_page(self.database_id, notion_props, blocks)
            else:
                page = self.notion.create_page(self.database_id, notion_props, blocks)

            page_id = page["id"]
            self.store.mark_synced(granola_id, page_id)
            print(f"  [{granola_id}] Pushed → {page_id}")
            return page_id

        except Exception as exc:
            print(f"  [{granola_id}] ERROR pushing to Notion: {exc}")
            return None

    def push_all(self, overwrite: bool = False) -> dict[str, int]:
        """Push all unsynced notes to Notion. Returns stats dict."""
        notes = self.store.get_unsynced_notes()
        if not notes:
            stats = self.store.stats()
            print(f"\nNo new notes to push. Total in DB: {stats['total']}, Synced: {stats['synced']}")
            return {"attempted": 0, "succeeded": 0, "failed": 0}

        succeeded, failed = 0, 0
        for note in notes:
            result = self.push_note(note, overwrite=overwrite)
            if result:
                succeeded += 1
            else:
                failed += 1

        print(f"\nPush complete — Succeeded: {succeeded}, Failed: {failed}")
        return {"attempted": len(notes), "succeeded": succeeded, "failed": failed}

    # ------------------------------------------------------------------
    # Full sync pipeline
    # ------------------------------------------------------------------
    def sync(self, fetch: bool = True, push: bool = True, overwrite: bool = False) -> dict[str, Any]:
        """Run the full pipeline: fetch from Granola → push to Notion."""
        self.ensure_database()

        if fetch:
            self.fetch_from_granola()

        result = {"store_stats": self.store.stats()}
        if push:
            result["push"] = self.push_all(overwrite=overwrite)

        result["store_stats"] = self.store.stats()
        return result

    def close(self) -> None:
        self.store.close()
