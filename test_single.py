#!/usr/bin/env python3
"""Fetch one Granola note, push to Notion, and validate the result.

Usage:
    python test_single.py                    # fetch & push the most recent note
    python test_single.py <note_id>          # push a specific note
    python test_single.py --latest N         # push the N most recent notes
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from src.config import CONFIG
from src.db import GranolaStore
from src.granola_client import GranolaClient, GranolaError
from src.notion_client import NotionClient
from src.sync import SyncEngine


def validate_page(notion: NotionClient, page_id: str, note_id: str) -> dict[str, Any]:
    """Fetch the Notion page blocks and validate structure."""
    blocks = notion.get_page_blocks(page_id).get("results", [])
    validation = {
        "page_id": page_id,
        "note_id": note_id,
        "total_blocks": len(blocks),
        "has_summary": False,
        "has_transcript": False,
        "has_metadata_callout": False,
        "block_types": [],
    }

    for b in blocks:
        btype = b.get("type", "unknown")
        validation["block_types"].append(btype)

        if btype == "callout":
            validation["has_metadata_callout"] = True
        elif btype == "heading_2":
            rich = b.get("heading_2", {}).get("rich_text", [])
            for r in rich:
                txt = r.get("text", {}).get("content", "")
                if "summary" in txt.lower():
                    validation["has_summary"] = True
                if "transcript" in txt.lower():
                    validation["has_transcript"] = True

    return validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Test: fetch 1 Granola note -> push to Notion")
    parser.add_argument("note_id", nargs="?", help="Specific Granola note ID to push")
    parser.add_argument("--latest", "-n", type=int, default=1, help="Push N most recent notes")
    parser.add_argument("--force-db", action="store_true", help="Force re-create the Notion database")
    args = parser.parse_args()

    store = GranolaStore()
    granola = GranolaClient()
    notion = NotionClient()
    engine = SyncEngine(db=store, granola_client=granola, notion_client=notion)

    # Ensure database exists
    engine.ensure_database(force=args.force_db)

    # --- Fetch from Granola ---
    if args.note_id:
        print(f"\nFetching specific note: {args.note_id}")
        try:
            note = granola.get_note(args.note_id)
        except GranolaError as exc:
            print(f"Failed to fetch note: {exc}")
            sys.exit(1)
        store.upsert_note(note)
        notes_to_push = [note]
    else:
        print(f"\nFetching {args.latest} most recent note(s) from Granola...")
        all_notes = list(granola.list_notes())
        recent = all_notes[: args.latest]
        notes_to_push = []
        for summary in recent:
            nid = summary.get("id")
            if not nid:
                continue
            try:
                full = granola.get_note(nid)
                store.upsert_note(full)
                notes_to_push.append(full)
                print(f"  Fetched: {summary.get('title', nid)}")
            except GranolaError as exc:
                print(f"  [WARN] Skipping {nid}: {exc}")

    if not notes_to_push:
        print("No notes to push.")
        sys.exit(0)

    # --- Push to Notion ---
    print(f"\nPushing {len(notes_to_push)} note(s) to Notion...")
    for note in notes_to_push:
        note_id = note.get("id")
        page_id = engine.push_note(note, overwrite=False)
        if not page_id:
            print(f"  Failed to push {note_id}")
            continue

        # --- Validate ---
        print(f"\nValidating Notion page: {page_id}")
        v = validate_page(notion, page_id, note_id)
        print(f"  Total blocks          : {v['total_blocks']}")
        print(f"  Metadata callout      : {'PASS' if v['has_metadata_callout'] else 'FAIL'}")
        print(f"  AI Summary section    : {'PASS' if v['has_summary'] else 'FAIL'}")
        print(f"  Transcript section    : {'PASS' if v['has_transcript'] else 'FAIL'}")
        print(f"  Block types          : {v['block_types'][:10]}")

        page_url = f"https://notion.so/{page_id.replace('-', '')}"
        print(f"\n  Notion page URL: {page_url}")

        all_pass = v["has_metadata_callout"] and v["has_summary"] and v["has_transcript"]
        if all_pass:
            print("\n  [OK] All checks passed")
        else:
            print("\n  [WARN] Some checks failed -- review the page manually")

    store.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
