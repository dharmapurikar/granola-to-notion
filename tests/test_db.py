"""Unit tests for db.py using an in-memory SQLite database."""
import unittest
import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import GranolaStore


SAMPLE_NOTE = {
    "id": "not_test123",
    "title": "Q1 Planning Review",
    "owner": {"name": "Sachin", "email": "sachin@example.com"},
    "created_at": "2026-01-15T10:00:00Z",
    "updated_at": "2026-01-15T11:00:00Z",
    "summary_text": "Reviewed Q1 goals.",
    "summary_markdown": "## Q1 Planning Review\n- Goal 1\n- Goal 2",
    "transcript": [
        {"speaker": {"source": "microphone"}, "text": "Let's start.", "start_time": "2026-01-15T10:00:00Z", "end_time": "2026-01-15T10:01:00Z"},
        {"speaker": {"source": "speaker"}, "text": "Agreed.", "start_time": "2026-01-15T10:01:00Z", "end_time": "2026-01-15T10:02:00Z"},
    ],
    "attendees": [
        {"name": "Sachin", "email": "sachin@example.com"},
        {"name": "Alice", "email": "alice@example.com"},
    ],
    "calendar_event": {
        "event_title": "Q1 Planning Review",
        "organiser": "sachin@example.com",
        "scheduled_start_time": "2026-01-15T10:00:00Z",
        "scheduled_end_time": "2026-01-15T11:00:00Z",
    },
}


class TestGranolaStore(unittest.TestCase):
    def setUp(self):
        self.db = GranolaStore(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_upsert_and_get(self):
        self.db.upsert_note(SAMPLE_NOTE)
        result = self.db.get_note("not_test123")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Q1 Planning Review")
        self.assertEqual(result["owner_name"], "Sachin")

    def test_upsert_idempotent(self):
        self.db.upsert_note(SAMPLE_NOTE)
        self.db.upsert_note({**SAMPLE_NOTE, "title": "Updated Title"})
        result = self.db.get_note("not_test123")
        self.assertEqual(result["title"], "Updated Title")

    def test_note_exists(self):
        self.assertFalse(self.db.note_exists("not_test123"))
        self.db.upsert_note(SAMPLE_NOTE)
        self.assertTrue(self.db.note_exists("not_test123"))

    def test_get_unsynced(self):
        self.db.upsert_note(SAMPLE_NOTE)
        unsynced = self.db.get_unsynced_notes()
        self.assertEqual(len(unsynced), 1)
        # _row_to_note maps granola_id → id (Granola-compatible)
        self.assertEqual(unsynced[0]["id"], "not_test123")
        # JSON fields should be deserialized
        self.assertIsInstance(unsynced[0]["transcript"], list)
        self.assertIsInstance(unsynced[0]["attendees"], list)
        self.assertIsInstance(unsynced[0]["calendar_event"], dict)

    def test_mark_synced(self):
        self.db.upsert_note(SAMPLE_NOTE)
        self.db.mark_synced("not_test123", "notion_page_abc")
        result = self.db.get_note("not_test123")
        self.assertEqual(result["notion_page_id"], "notion_page_abc")
        self.assertIsNotNone(result["synced_at"])

    def test_get_notion_page_id(self):
        self.db.upsert_note(SAMPLE_NOTE)
        self.assertIsNone(self.db.get_notion_page_id("not_test123"))
        self.db.mark_synced("not_test123", "notion_page_abc")
        self.assertEqual(self.db.get_notion_page_id("not_test123"), "notion_page_abc")

    def test_get_all_notes(self):
        notes = [
            {**SAMPLE_NOTE, "id": "not_1"},
            {**SAMPLE_NOTE, "id": "not_2"},
        ]
        for n in notes:
            self.db.upsert_note(n)
        all_notes = self.db.get_all_notes()
        self.assertEqual(len(all_notes), 2)

    def test_stats(self):
        self.db.upsert_note({**SAMPLE_NOTE, "id": "not_1"})
        self.db.upsert_note({**SAMPLE_NOTE, "id": "not_2"})
        self.db.mark_synced("not_1", "page_1")
        s = self.db.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["synced"], 1)
        self.assertEqual(s["pending"], 1)


if __name__ == "__main__":
    unittest.main()
