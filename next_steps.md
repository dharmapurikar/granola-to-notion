# Next Steps — Granola → Notion Sync

## Current Status

**Project:** `~/hermes-workspace/personal/granola-to-notion/`

All bugs fixed, all 37 unit tests pass, integration test verified. The full sync of 247 notes is ready to run.

**QA PASSED** — single note push validated:
- Metadata callout with title, date, organizer, attendees
- AI Summary rendered with proper bold, headings, bullets
- Transcript with speaker labels (🟢 You / 🔵 Speaker) + timestamps
- All 9 database properties populated correctly
- 3348 blocks written for a large meeting (3265 transcript entries)

---

## Bugs Fixed (3 Apr 2026)

1. **`search_databases` filter** — was using `"data_source"` (wrong for API 2022-06-28), changed to `"database"`
2. **`_append_blocks_recursive`** — tried to use block IDs before they existed; now always appends to page children
3. **`_row_to_note` deserialization** — SQLite stored transcript/attendees/calendar_event as JSON strings but `get_unsynced_notes` returned them raw; added `_row_to_note()` to deserialize and map `granola_id` → `id`

---

## Running the Full Sync

The 247 notes are already fetched into SQLite. To push them all:

```bash
cd ~/hermes-workspace/personal/granola-to-notion
python sync_all.py --push-only
```

This will take a while (many notes have large transcripts = thousands of Notion blocks each). The sync is idempotent — if it's interrupted, re-run and it picks up where it left off.

For a fresh sync (fetch + push):
```bash
rm -f granola_import.db
python sync_all.py
```

To check progress:
```bash
python sync_all.py --stats
```

---

## Notion Database

- **Name:** "Granola Meeting Imports"
- **ID:** `336916a5-3018-81f6-8bf9-df3b222c055b`
- **Parent page:** `336916a5-3018-8016-98d0-c105d579134f`
- **Properties (9):** Meeting name, Date, Attendees, Organizer, Summary, Category, Source URL, Granola ID, Synced At

## Archived Test Artifacts

- 2 extra "Granola Meeting Imports" databases (archived)
- 1 "Test DB v2" (archived)
- 1 test page for "Yugesh 2" (archived)
