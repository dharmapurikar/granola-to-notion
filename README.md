# Granola → Notion Sync

Migrate meeting notes from [Granola](https://granola.ai) to Notion with a local SQLite checkpoint for idempotent, resumable syncs.

**Pipeline:** `Granola API` → `SQLite (local)` → `Notion API`

Each note lands in Notion as a structured page containing:
- **Metadata callout** — title, date/time, organizer, attendees
- **AI Summary** — Granola's `summary_markdown` rendered as proper Notion blocks
- **Raw Transcript** — full speaker-by-speaker transcript with timestamps

---

## Project Structure

```
granola-to-notion/
├── config.example.yaml  # Template — copy to config.yaml
├── .env.example         # Template for API keys
├── .gitignore
├── requirements.txt
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── config.py         # Loads config.yaml + .env overrides
│   ├── db.py             # SQLite GranolaStore
│   ├── granola_client.py  # Granola API client
│   ├── notion_client.py   # Notion API client + markdown→blocks converter
│   └── sync.py            # Sync engine (pipeline orchestrator)
│
├── tests/
│   └── __init__.py
│
├── test_single.py        # Fetch 1 note → push → validate (dev use)
└── sync_all.py            # Full production sync
```

---

## Setup

### 1. Clone / enter the project

```bash
cd ~/hermes-workspace/personal/granola-to-notion
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API keys

```bash
cp .env.example .env
# Edit .env with your actual keys
```

| Key | Where to get it |
|-----|----------------|
| `NOTION_API_KEY` | [notion.so/my-integrations](https://www.notion.so/my-integrations) — create an integration, copy the token |
| `GRANOLA_API_KEY` | Granola account settings |

### 4. Configure the destination

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your Notion parent page ID
```

```yaml
notion:
  parent_page_id: "336916a5-3018-8016-98d0-c105d579134f"
  database_name: "Granola Meeting Imports"
```

The `parent_page_id` is the 32-char hex ID from your Notion page URL:
```
https://notion.so/Granola-Meeting-Notes-{PARENT_PAGE_ID}
```

Share the parent page with your Notion integration: open the page → `...` → **Connect to** → your integration name.

---

## Usage

### Quick start

```bash
# 1. Test with the most recent note
python test_single.py

# 2. Inspect the Notion page, fix any formatting issues
# 3. Run the full sync
python sync_all.py
```

### Scripts

#### `test_single.py`

Fetch 1 (or N) notes from Granola, push to Notion, and run a quality check on the result.

```bash
# Most recent note
python test_single.py

# Specific note by ID
python test_single.py not_1d3tmYTlCICgjy

# 3 most recent notes
python test_single.py --latest 3
```

**Validation checks:**
- Page was created in Notion
- Metadata callout is present
- "AI Summary" heading + content is present
- "Transcript" heading + entries is present

#### `sync_all.py`

Production sync — fetches everything from Granola and pushes new notes to Notion.

```bash
# Normal run (idempotent — skips already-synced notes)
python sync_all.py

# Re-fetch from Granola (after new meetings) and push new notes
python sync_all.py

# Replace already-synced pages in Notion with fresh content
python sync_all.py --overwrite

# Only pull from Granola (no Notion push — useful for a dry run)
python sync_all.py --fetch-only

# Only push already-fetched notes to Notion (skip Granola fetch)
python sync_all.py --push-only

# Check how many notes are in SQLite
python sync_all.py --stats
```

---

## Database Schema

### Notion database properties

| Property | Type | Source |
|----------|------|--------|
| `Meeting name` | title | Granola `title` |
| `Date` | date | `calendar_event.scheduled_start_time` |
| `Attendees` | rich_text | `attendees[*].name` |
| `Organizer` | rich_text | `calendar_event.organiser` |
| `Summary` | rich_text | `summary_text` (first 2000 chars) |
| `Category` | select | inferred from title keywords |
| `Source URL` | url | Granola app link |
| `Granola ID` | rich_text | Granola note ID |
| `Synced At` | date | sync timestamp |

### SQLite schema (`granola_import.db`)

```sql
CREATE TABLE notes (
    granola_id    TEXT PRIMARY KEY,
    title         TEXT,
    owner_name    TEXT,
    owner_email   TEXT,
    created_at    TEXT,
    updated_at    TEXT,
    summary_text  TEXT,
    summary_md    TEXT,
    transcript    TEXT,      -- JSON array
    attendees     TEXT,      -- JSON array
    calendar_event TEXT,      -- JSON object
    notion_page_id TEXT,
    synced_at     TEXT
);
```

---

## Page Content Structure

Each Notion page contains these blocks in order:

```
📅 [Metadata Callout]
   Title: Quarterly yoghurt budget review
   Date: 15:30 – 16:30
   Organizer: oat@granola.ai
   Attendees: Oat Benson, Raisin Patel

## AI Summary
──────────────────────────────────────
[Markdown blocks from summary_markdown:
 headings, bullets, bold text, etc.]

## Transcript
──────────────────────────────────────
🟢 You [15:30 – 15:31]: I'm done pretending...
🔵 Speaker [15:31 – 15:32]: Finally. Regular yoghurt is just milk...
...
```

---

## Validation Checklist

After `test_single.py`, manually check the Notion page:

- [ ] Title renders correctly
- [ ] Bold text (`**bold**`) renders as **bold**, not `**bold**`
- [ ] Bullets and numbered lists are properly formatted
- [ ] Headings are correct levels
- [ ] Transcript entries show speaker label + timestamp + text
- [ ] No duplicate blocks or truncated content
- [ ] Category was inferred correctly

If formatting issues are found, patch `src/notion_client.py` (the `markdown_to_notion_blocks` function) and re-run with `--overwrite`.

---

## Common Issues

### 400 Bad Request from Notion
- Check the property schema — type mismatches (e.g. `rich_text` vs `title`) cause this
- Make sure the parent page is shared with your integration

### Notes not appearing in Notion
- Run `python sync_all.py --stats` to see if notes are in SQLite but not pushed
- Check `granola_import.db` directly: `sqlite3 granola_import.db "SELECT * FROM notes LIMIT 5;"`

### Duplicate pages in Notion
- Set `sync.skip_existing: true` in `config.yaml` (default)
- Or run `python sync_all.py` which respects the SQLite `notion_page_id` checkpoint

### Overwrite mode doesn't update content
- The current overwrite implementation deletes the old page and creates a new one
- The new page will get a new `page_id` — this is expected

---

## Extending

### Add more properties to the Notion database
1. Add the property to `NOTION_PROPERTIES` in `src/sync.py`
2. Add the mapping in `_build_notion_properties()` in `src/sync.py`
3. Update `config.yaml` properties section

### Change the page content structure
- Edit `build_note_blocks()` in `src/notion_client.py`
- This function converts a Granola note dict into a list of Notion blocks

### Switch transcript format
- The transcript is currently rendered as `bulleted_list_item` blocks
- You could switch to `paragraph` blocks or a nested structure by editing the `for entry in transcript:` loop in `build_note_blocks()`
