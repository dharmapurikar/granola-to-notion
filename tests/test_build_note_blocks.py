"""Unit tests for build_note_blocks."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.notion_client import build_note_blocks


SAMPLE_NOTE = {
    "id": "not_test123",
    "title": "Q1 Planning Review",
    "owner": {"name": "Sachin", "email": "sachin@example.com"},
    "created_at": "2026-01-15T10:00:00Z",
    "updated_at": "2026-01-15T11:00:00Z",
    "summary_text": "Reviewed Q1 goals.",
    "summary_markdown": "## Q1 Planning Review\n- Goal 1\n- Goal 2\n- spent **$100,000**",
    "transcript": [
        {"speaker": {"source": "microphone"}, "text": "Let's start the meeting.", "start_time": "2026-01-15T10:00:00Z", "end_time": "2026-01-15T10:01:00Z"},
        {"speaker": {"source": "speaker"}, "text": "Good morning everyone.", "start_time": "2026-01-15T10:01:00Z", "end_time": "2026-01-15T10:02:00Z"},
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


class TestBuildNoteBlocks(unittest.TestCase):
    def test_metadata_callout_is_first(self):
        blocks = build_note_blocks(SAMPLE_NOTE)
        self.assertEqual(blocks[0]["type"], "callout")
        content = blocks[0]["callout"]["rich_text"]
        full_text = "".join(c["text"]["content"] for c in content)
        self.assertIn("Q1 Planning Review", full_text)
        self.assertIn("sachin@example.com", full_text)

    def test_ai_summary_heading_present(self):
        blocks = build_note_blocks(SAMPLE_NOTE)
        heading_2_blocks = [b for b in blocks if b.get("type") == "heading_2"]
        self.assertTrue(any("AI Summary" in b["heading_2"]["rich_text"][0]["text"]["content"] for b in heading_2_blocks))

    def test_transcript_heading_present(self):
        blocks = build_note_blocks(SAMPLE_NOTE)
        heading_2_blocks = [b for b in blocks if b.get("type") == "heading_2"]
        self.assertTrue(any("Transcript" in b["heading_2"]["rich_text"][0]["text"]["content"] for b in heading_2_blocks))

    def test_transcript_entries(self):
        blocks = build_note_blocks(SAMPLE_NOTE)
        bullet_blocks = [b for b in blocks if b.get("type") == "bulleted_list_item"]
        bullet_texts = ["".join(r["text"]["content"] for r in b["bulleted_list_item"]["rich_text"]) for b in bullet_blocks]
        transcript_bullets = [t for t in bullet_texts if "Let's start" in t or "Good morning" in t]
        self.assertTrue(len(transcript_bullets) > 0)

    def test_bold_in_summary_preserved(self):
        blocks = build_note_blocks(SAMPLE_NOTE)
        bullet_blocks = [b for b in blocks if b.get("type") == "bulleted_list_item"]
        for b in bullet_blocks:
            rich = b["bulleted_list_item"]["rich_text"]
            for r in rich:
                if "$100,000" in r["text"]["content"]:
                    self.assertTrue(r.get("annotations", {}).get("bold"))

    def test_empty_note(self):
        blocks = build_note_blocks({"id": "not_empty"})
        # Should still have metadata callout
        self.assertEqual(blocks[0]["type"], "callout")

    def test_no_transcript(self):
        blocks = build_note_blocks({**SAMPLE_NOTE, "transcript": []})
        heading_2_blocks = [b for b in blocks if b.get("type") == "heading_2"]
        transcript_present = any("Transcript" in b["heading_2"]["rich_text"][0]["text"]["content"] for b in heading_2_blocks)
        self.assertFalse(transcript_present)

    def test_no_summary_falls_back_to_summary_text(self):
        # When summary_markdown is None, summary_text is used as fallback
        blocks = build_note_blocks({**SAMPLE_NOTE, "summary_markdown": None})
        heading_2_blocks = [b for b in blocks if b.get("type") == "heading_2"]
        summary_present = any("AI Summary" in b["heading_2"]["rich_text"][0]["text"]["content"] for b in heading_2_blocks)
        self.assertTrue(summary_present)  # Falls back to summary_text


if __name__ == "__main__":
    unittest.main()
