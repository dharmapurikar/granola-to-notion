#!/usr/bin/env python3
"""Full sync: Granola -> SQLite -> Notion.

Usage:
    python sync_all.py                    # normal run (fetch + push new notes)
    python sync_all.py --overwrite        # re-push already-synced notes
    python sync_all.py --fetch-only       # only fetch from Granola, skip Notion push
    python sync_all.py --push-only        # only push already-fetched notes
    python sync_all.py --stats            # print DB stats and exit
    python sync_all.py --verify           # cross-check SQLite vs Notion, fix mismatches
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.db import GranolaStore
from src.granola_client import GranolaClient, GranolaError
from src.notion_client import NotionClient
from src.sync import SyncEngine


def verify_against_notion(store: GranolaStore, engine: SyncEngine) -> None:
    """Cross-check SQLite sync state against actual Notion database.

    Finds pages that are in Notion but unmarked in SQLite (marks them synced),
    and pages marked synced in SQLite but missing from Notion (resets them to pending).
    """
    print("=== Verifying SQLite vs Notion ===\n")

    # 1. Fetch all Granola IDs actually present in Notion
    notion_granola_ids: dict[str, str] = {}  # granola_id -> notion_page_id
    engine.ensure_database()
    db_id = engine.database_id
    start_cursor = None

    while True:
        body: dict = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        data = engine.notion._post(f"/databases/{db_id}/query", body)
        for page in data.get("results", []):
            gid_prop = page.get("properties", {}).get("Granola ID", {}).get("rich_text", [])
            gid = gid_prop[0].get("plain_text", "") if gid_prop else ""
            if gid:
                notion_granola_ids[gid] = page["id"]
        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")

    # 2. Get SQLite state
    conn = store._get_conn()
    all_rows = conn.execute("SELECT granola_id, title FROM notes").fetchall()
    sql_ids = {r[0]: r[1] for r in all_rows}
    synced_rows = conn.execute(
        "SELECT granola_id, notion_page_id FROM notes "
        "WHERE notion_page_id IS NOT NULL AND notion_page_id != ''"
    ).fetchall()
    synced_ids = {r[0]: r[1] for r in synced_rows}

    # 3. Classify
    in_notion_unmarked = [gid for gid in notion_granola_ids if gid in sql_ids and gid not in synced_ids]
    fake_synced = [gid for gid in synced_ids if gid not in notion_granola_ids]
    truly_pending = [gid for gid in sql_ids if gid not in synced_ids and gid not in notion_granola_ids]

    print(f"  Total in SQLite:          {len(sql_ids)}")
    print(f"  Total in Notion:          {len(notion_granola_ids)}")
    print(f"  Marked synced in SQLite:  {len(synced_ids)}")
    print()
    print(f"  In Notion but unmarked:   {len(in_notion_unmarked)}")
    print(f"  Marked synced but missing: {len(fake_synced)}")
    print(f"  Truly pending:            {len(truly_pending)}")

    # 4. Fix unmarked (present in Notion, not tracked)
    if in_notion_unmarked:
        print(f"\n  Fixing {len(in_notion_unmarked)} unmarked pages...")
        for gid in in_notion_unmarked:
            notion_pid = notion_granola_ids[gid]
            conn.execute(
                "UPDATE notes SET notion_page_id = ?, synced_at = ? WHERE granola_id = ?",
                (notion_pid, datetime.now(timezone.utc).isoformat(), gid),
            )
            print(f"    Marked synced: {gid} -> {notion_pid}")
        conn.commit()

    # 5. Fix fake-synced (not in Notion, reset to pending)
    if fake_synced:
        print(f"\n  Resetting {len(fake_synced)} stale sync markers...")
        for gid in fake_synced:
            conn.execute(
                "UPDATE notes SET notion_page_id = NULL, synced_at = NULL WHERE granola_id = ?",
                (gid,),
            )
            print(f"    Reset to pending: {gid}")
        conn.commit()

    print("\nDone. Updated stats:")
    s = store.stats()
    print(f"  Total: {s['total']}, Synced: {s['synced']}, Pending: {s['pending']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Granola notes to Notion")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Notion pages")
    parser.add_argument("--fetch-only", action="store_true", help="Only fetch from Granola, skip Notion push")
    parser.add_argument("--push-only", action="store_true", help="Only push already-fetched notes")
    parser.add_argument("--stats", action="store_true", help="Show SQLite stats and exit")
    parser.add_argument("--verify", action="store_true", help="Cross-check SQLite sync state against Notion and fix mismatches")
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

        # Verify mode (before ensure_database — verify calls it internally)
        if args.verify:
            verify_against_notion(store, engine)
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
