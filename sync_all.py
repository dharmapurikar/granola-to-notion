#!/usr/bin/env python3
"""Full sync: Granola -> SQLite -> Notion.

Usage:
    python sync_all.py                    # normal run (fetch + push new notes)
    python sync_all.py --overwrite        # re-push already-synced notes
    python sync_all.py --fetch-only       # only fetch from Granola, skip Notion push
    python sync_all.py --push-only        # only push already-fetched notes
    python sync_all.py --stats            # print DB stats and exit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.db import GranolaStore
from src.granola_client import GranolaClient, GranolaError
from src.notion_client import NotionClient
from src.sync import SyncEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Granola notes to Notion")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Notion pages")
    parser.add_argument("--fetch-only", action="store_true", help="Only fetch from Granola, skip Notion push")
    parser.add_argument("--push-only", action="store_true", help="Only push already-fetched notes")
    parser.add_argument("--stats", action="store_true", help="Show SQLite stats and exit")
    args = parser.parse_args()

    store = GranolaStore()
    granola = GranolaClient()
    notion = NotionClient()
    engine = SyncEngine(db=store, granola_client=granola, notion_client=notion)

    try:
        # Stats mode
        if args.stats:
            s = store.stats()
            print(f"SQLite stats:")
            print(f"  Total notes : {s['total']}")
            print(f"  Synced      : {s['synced']}")
            print(f"  Pending     : {s['pending']}")
            return

        # Ensure database
        engine.ensure_database()

        # Fetch only
        if args.push_only:
            print("\n=== Push-only mode (no new fetch) ===")
            result = engine.push_all(overwrite=args.overwrite)
        elif args.fetch_only:
            print("\n=== Fetch-only mode ===")
            count = engine.fetch_from_granola()
            print(f"\nFetched {count} notes. Run without --fetch-only to push them.")
        else:
            print("\n=== Full sync: Granola → SQLite → Notion ===")
            result = engine.sync(overwrite=args.overwrite)
            s = result.get("store_stats", {})
            p = result.get("push", {})
            print(f"\nFinal SQLite stats — Total: {s.get('total')}, Synced: {s.get('synced')}, Pending: {s.get('pending')}")
            print(f"Push result — Attempted: {p.get('attempted')}, Succeeded: {p.get('succeeded')}, Failed: {p.get('failed')}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
