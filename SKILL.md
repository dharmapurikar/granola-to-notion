---
name: notion-markdown
description: Convert markdown documents to Notion pages via the Notion API — bold text, headings, bullets, tables, callouts, batched block creation, and idempotent page updates.
triggers: ["convert markdown to notion", "push markdown to notion", "create notion page from markdown", "notion block API"]
---

# Notion Markdown Skill

Convert markdown documents to structured Notion pages using the Notion API.

---

## Core Concepts

- Notion pages are created via `POST /pages` with a `parent` and `properties`
- Page **content** (text, headings, bullets) is added as **blocks** via `POST /blocks/{block_id}/children`
- Each block type has its own schema (e.g. `heading_2`, `bulleted_list_item`)
- Rich text uses `rich_text` arrays with `text` objects — markdown annotations (`**bold**`, `_italic_`) become `annotations` dicts
- API limit: **100 blocks per request**, **2000 characters per code block**
- Notion API version must be `2022-06-28` — newer versions (`2025-09-03`) silently drop properties on `create_database`

---

## Block Type Mapping

| Markdown | Notion Block Type |
|----------|-------------------|
| `# H1` | `heading_1` |
| `## H2` | `heading_2` |
| `### H3` | `heading_3` |
| `- item` | `bulleted_list_item` |
| `1. item` | `numbered_list_item` |
| `> quote` | `quote` |
| `---` | `divider` |
| ` ```lang\ncode\n``` ` | `code` (lang: python/js/bash/etc.) |
| `\| col1 \| col2 \|` | `bulleted_list_item` (cells joined by ` — `) |
| plain paragraph | `paragraph` |

---

## Bold Text Parsing (Key Function)

Markdown `**bold**` must become Notion `annotations.bold = true`, not raw text:

```python
import re

def parse_markdown_bold(text: str) -> list[dict]:
    """Convert **bold** markdown to Notion rich_text with bold annotation."""
    parts = []
    for segment in re.split(r'(\*\*[^*]+\*\*)', text):
        if segment.startswith('**') and segment.endswith('**'):
            content = segment[2:-2]
            parts.append({
                "type": "text",
                "text": {"content": content},
                "annotations": {"bold": True, "italic": False, "code": False,
                               "strikethrough": False, "underline": False, "color": "default"}
            })
        elif segment:
            parts.append({
                "type": "text",
                "text": {"content": segment},
                "annotations": {"bold": False, "italic": False, "code": False,
                               "strikethrough": False, "underline": False, "color": "default"}
            })
    return parts
```

---

## Building Notion Blocks from Markdown

```python
def markdown_to_notion_blocks(md: str) -> list[dict]:
    blocks = []
    lines = md.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Headings
        if stripped.startswith('### '):
            blocks.append(_h_block('heading_3', stripped[4:]))
        elif stripped.startswith('## '):
            blocks.append(_h_block('heading_2', stripped[3:]))
        elif stripped.startswith('# '):
            blocks.append(_h_block('heading_1', stripped[2:]))

        # Horizontal rule
        elif stripped == '---':
            blocks.append({"type": "divider", "divider": {}})

        # Bulleted list items
        elif stripped.startswith('- '):
            content = stripped[2:]
            rich = parse_markdown_bold(content)
            blocks.append({
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": rich, "color": "default"}
            })

        # Numbered list items
        elif re.match(r'^\d+\.\s', stripped):
            content = re.sub(r'^\d+\.\s', '', stripped)
            rich = parse_markdown_bold(content)
            blocks.append({
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": rich, "color": "default"}
            })

        # Quote
        elif stripped.startswith('> '):
            content = stripped[2:]
            rich = parse_markdown_bold(content)
            blocks.append({
                "type": "quote",
                "quote": {"rich_text": rich, "color": "default"}
            })

        # Code fence
        elif stripped.startswith('```'):
            lang = stripped[3:].strip() or "plain text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            code_text = '\n'.join(code_lines)
            # 2000 char limit per code block
            if len(code_text) > 2000:
                code_text = code_text[:2000] + "\n# ... (truncated)"
            blocks.append({
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": code_text}}],
                    "language": lang
                }
            })

        # Table rows — skip separator lines (|---|---|), render data rows as bullets
        elif stripped.startswith('|') and '|' in stripped:
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            if not any(re.match(r'^[-:]+$', c) for c in cells):
                row_text = ' — '.join(cells)
                rich = parse_markdown_bold(row_text)
                blocks.append({
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": rich, "color": "default"}
                })
            # Skip separator rows entirely

        # Paragraph (skip empty)
        elif stripped:
            rich = parse_markdown_bold(stripped)
            blocks.append({
                "type": "paragraph",
                "paragraph": {"rich_text": rich, "color": "default"}
            })

        i += 1
    return blocks
```

---

## Creating a Page with Blocks

```python
import requests

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"  # Critical: not 2025-09-03
BASE_URL = "https://api.notion.com/v1"

def _headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

def create_page(parent_page_id: str, title: str, blocks: list[dict]) -> str:
    """Create a Notion page and append blocks. Returns page_id."""
    # 1. Create page
    page_payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        }
    }
    resp = requests.post(f"{BASE_URL}/pages", headers=_headers(), json=page_payload, timeout=30)
    resp.raise_for_status()
    page_id = resp.json()["id"]

    # 2. Append blocks (batch 100 at a time)
    for i in range(0, len(blocks), 100):
        batch = blocks[i:i + 100]
        children_payload = {"children": batch}
        # For top-level blocks, append to page directly
        if i == 0:
            block_resp = requests.patch(
                f"{BASE_URL}/pages/{page_id}/blocks",
                headers=_headers(),
                json=children_payload,
                timeout=30
            )
        else:
            # Append to last block in previous batch
            block_resp = requests.patch(
                f"{BASE_URL}/blocks/{last_block_id}/children",
                headers=_headers(),
                json=children_payload,
                timeout=30
            )
        block_resp.raise_for_status()
        if batch:
            last_block_id = block_resp.json()["results"][-1]["id"]

    return page_id
```

---

## Idempotent Page Updates (Prevent Duplicates)

**Problem:** Re-running a script creates duplicate blocks on the same page.

**Solution 1 — Clear before rebuild:**
```python
def clear_page_blocks(page_id: str):
    """Delete all children of a page."""
    resp = requests.get(f"{BASE_URL}/blocks/{page_id}/children?page_size=100", headers=_headers())
    blocks = resp.json().get("results", [])
    for b in blocks:
        requests.delete(f"{BASE_URL}/blocks/{b['id']}", headers=_headers())
```

**Solution 2 — SQLite checkpoint (preferred for sync tools):**
```python
# Track (granola_id -> notion_page_id) in SQLite
cur.execute("SELECT notion_page_id FROM notes WHERE granola_id = ?", (note_id,))
row = cur.fetchone()
if row and row[0]:
    print(f"Already synced: {note_id} -> {row[0]}")
    return row[0]  # Skip, or offer --overwrite flag
```

---

## Common Pitfalls

1. **Wrong API version** — `2025-09-03` drops properties on `create_database`. Use `2022-06-28`.
2. **Parent object missing `type`** — must be `{"type": "page_id", "page_id": "..."}`, not just `{"page_id": "..."}`.
3. **`create_database` properties not persisting** — works in curl but not Python requests. Check headers and JSON serialization. May need `json=` parameter (not `data=json.dumps(...)`).
4. **Duplicate blocks on re-run** — always clear page or check SQLite checkpoint before creating.
5. **Code blocks > 2000 chars** — truncate with `\n# ... (truncated)` message.
6. **Bold text renders as `**text**` in Notion** — means annotations weren't set. Must use `rich_text` array with `annotations.bold = True`, not plain text.
7. **Table separator rows `|---|` rendered as bullets** — skip any cell matching regex `^[-:]+$`.
8. **Search filter `value: "database"` returns 400** — use `value: "data_source"` for API v2025+.
9. **Batched block append — after first 100 blocks** — use the last block ID from the previous response, not the page ID.

---

## Testing

```python
def test_bold():
    result = parse_markdown_bold("spent **$100,000** on yoghurt")
    bold_parts = [r for r in result if r["annotations"]["bold"]]
    assert bold_parts[0]["text"]["content"] == "$100,000"

def test_table_skip_separator():
    blocks = markdown_to_notion_blocks("| col1 | col2 |\n|-----|-----|\n| a | b |")
    assert len(blocks) == 1  # separator skipped
    assert blocks[0]["type"] == "bulleted_list_item"

def test_heading_2():
    blocks = markdown_to_notion_blocks("## AI Summary")
    assert blocks[0]["type"] == "heading_2"
```
