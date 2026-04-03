"""SQLite store for Granola notes — enables incremental / idempotent syncs."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import CONFIG


class GranolaStore:
    """Persist Granola notes locally in SQLite.

    Schema
    ------
    notes
    ├── granola_id   TEXT PRIMARY KEY  — Granola's note ID (e.g. "not_xxx")
    ├── title         TEXT
    ├── owner_name    TEXT
    ├── owner_email   TEXT
    ├── created_at    TEXT              — ISO 8601
    ├── updated_at    TEXT              — ISO 8601
    ├── summary_text  TEXT
    ├── summary_md    TEXT              — raw markdown from Granola
    ├── transcript    TEXT              — JSON string of transcript entries
    ├── attendees     TEXT              — JSON list of {name, email}
    ├── calendar_event TEXT             — JSON of calendar event details
    ├── notion_page_id TEXT             — set after successful Notion push
    ├── synced_at     TEXT              — ISO 8601 of last Notion push
    └── UNIQUE(granola_id)
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path: Path = Path(db_path or CONFIG["database"]["path"])
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._ensure_schema()
        return self._conn

    def _ensure_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                granola_id    TEXT PRIMARY KEY,
                title         TEXT,
                owner_name    TEXT,
                owner_email   TEXT,
                created_at    TEXT,
                updated_at    TEXT,
                summary_text  TEXT,
                summary_md    TEXT,
                transcript    TEXT,
                attendees     TEXT,
                calendar_event TEXT,
                notion_page_id TEXT,
                synced_at     TEXT
            )
        """)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------
    def upsert_note(self, note: dict[str, Any]) -> None:
        """Insert or replace a Granola note."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO notes (
                granola_id, title, owner_name, owner_email,
                created_at, updated_at,
                summary_text, summary_md, transcript,
                attendees, calendar_event,
                notion_page_id, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            note.get("id"),
            note.get("title"),
            note.get("owner", {}).get("name"),
            note.get("owner", {}).get("email"),
            note.get("created_at"),
            note.get("updated_at"),
            note.get("summary_text"),
            note.get("summary_markdown"),
            json.dumps(note.get("transcript", [])),
            json.dumps(note.get("attendees", [])),
            json.dumps(note.get("calendar_event", {})),
            note.get("notion_page_id"),
            note.get("synced_at"),
        ))
        conn.commit()

    def mark_synced(self, granola_id: str, notion_page_id: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE notes SET notion_page_id = ?, synced_at = ? WHERE granola_id = ?",
            (notion_page_id, datetime.now(timezone.utc).isoformat(), granola_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_note(self, granola_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM notes WHERE granola_id = ?", (granola_id,)
        ).fetchone()
        return dict(row) if row else None

    def _row_to_note(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a DB row back into a Granola-compatible note dict.

        JSON fields (transcript, attendees, calendar_event) are deserialized.
        The granola_id column is mapped to the 'id' key expected by downstream code.
        """
        d = dict(row)
        d["id"] = d.pop("granola_id")
        d["summary_markdown"] = d.pop("summary_md", None)
        for json_field in ("transcript", "attendees", "calendar_event"):
            raw = d.get(json_field)
            if isinstance(raw, str):
                try:
                    d[json_field] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d[json_field] = [] if json_field != "calendar_event" else {}
        return d

    def get_all_notes(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()
        return [self._row_to_note(r) for r in rows]

    def get_unsynced_notes(self) -> list[dict[str, Any]]:
        """Return notes that have not been pushed to Notion."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM notes WHERE notion_page_id IS NULL OR notion_page_id = '' "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_note(r) for r in rows]

    def note_exists(self, granola_id: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM notes WHERE granola_id = ?", (granola_id,)
        ).fetchone()
        return row is not None

    def get_notion_page_id(self, granola_id: str) -> str | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT notion_page_id FROM notes WHERE granola_id = ?", (granola_id,)
        ).fetchone()
        return row["notion_page_id"] if row else None

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, int]:
        conn = self._get_conn()
        cur = conn.execute
        total = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        synced = conn.execute(
            "SELECT COUNT(*) FROM notes WHERE notion_page_id IS NOT NULL AND notion_page_id != ''"
        ).fetchone()[0]
        return {"total": total, "synced": synced, "pending": total - synced}
