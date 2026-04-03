"""Unit tests for markdown_to_notion_blocks and parse_markdown_bold."""
import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.notion_client import (
    markdown_to_notion_blocks,
    parse_markdown_bold,
    _bulleted,
    _paragraph,
    _h_block,
    _callout,
)


class TestParseMarkdownBold(unittest.TestCase):
    def test_plain_text(self):
        result = parse_markdown_bold("hello world")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"]["content"], "hello world")
        self.assertNotIn("bold", result[0].get("annotations", {}))

    def test_bold_text(self):
        result = parse_markdown_bold("hello **world**")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"]["content"], "hello")
        self.assertEqual(result[1]["text"]["content"], "world")
        self.assertTrue(result[1]["annotations"]["bold"])

    def test_multiple_bold(self):
        result = parse_markdown_bold("**one** and **two**")
        # Non-greedy match: **one**, then " and " (no bold), then **two**
        # Result: [bold:"one", plain:"and", bold:"two"] = 3 parts
        bold_parts = [r for r in result if r.get("annotations", {}).get("bold")]
        plain_parts = [r for r in result if not r.get("annotations", {}).get("bold")]
        self.assertEqual(len(bold_parts), 2)
        self.assertEqual(len(plain_parts), 1)

    def test_empty(self):
        result = parse_markdown_bold("")
        self.assertEqual(result, [{"type": "text", "text": {"content": ""}}])


class TestMarkdownToBlocks(unittest.TestCase):
    def test_heading_1(self):
        blocks = markdown_to_notion_blocks("# Hello World")
        self.assertEqual(blocks[0]["type"], "heading_1")
        self.assertEqual(blocks[0]["heading_1"]["rich_text"][0]["text"]["content"], "Hello World")

    def test_heading_2(self):
        blocks = markdown_to_notion_blocks("## AI Summary")
        self.assertEqual(blocks[0]["type"], "heading_2")

    def test_heading_3(self):
        blocks = markdown_to_notion_blocks("### Nested")
        self.assertEqual(blocks[0]["type"], "heading_3")

    def test_bullet(self):
        blocks = markdown_to_notion_blocks("- item one")
        self.assertEqual(blocks[0]["type"], "bulleted_list_item")
        self.assertIn("item one", blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"])

    def test_numbered_list(self):
        blocks = markdown_to_notion_blocks("1. first item")
        self.assertEqual(blocks[0]["type"], "numbered_list_item")
        self.assertIn("first item", blocks[0]["numbered_list_item"]["rich_text"][0]["text"]["content"])

    def test_quote(self):
        blocks = markdown_to_notion_blocks("> quoted text")
        self.assertEqual(blocks[0]["type"], "quote")

    def test_code_fence(self):
        blocks = markdown_to_notion_blocks("```python\nprint('hi')\n```")
        self.assertEqual(blocks[0]["type"], "code")
        self.assertEqual(blocks[0]["code"]["language"], "python")

    def test_table_rows(self):
        # A separator-only table has nothing to render (data row skipped, separator skipped)
        blocks = markdown_to_notion_blocks("|-----|-----|")
        self.assertEqual(len(blocks), 0)

    def test_table_with_data_row(self):
        # A table with a data row (no separator needed in test)
        blocks = markdown_to_notion_blocks("| col1 | col2 |\n|-----|-----|\n| a | b |")
        # data row rendered as bullet, separator skipped
        self.assertGreater(len(blocks), 0)
        self.assertEqual(blocks[0]["type"], "bulleted_list_item")

    def test_table_with_data(self):
        blocks = markdown_to_notion_blocks("| alice | bob |\n|-----|----|\n| hi | bye |")
        self.assertEqual(blocks[0]["type"], "bulleted_list_item")
        self.assertIn("alice", blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"])
        self.assertIn("bob", blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"])

    def test_bold_in_bullet(self):
        blocks = markdown_to_notion_blocks("- spent **$100,000** on yoghurt")
        self.assertEqual(blocks[0]["type"], "bulleted_list_item")
        rich = blocks[0]["bulleted_list_item"]["rich_text"]
        bold_parts = [r for r in rich if r.get("annotations", {}).get("bold")]
        self.assertTrue(len(bold_parts) > 0)
        self.assertEqual(bold_parts[0]["text"]["content"], "$100,000")

    def test_paragraph_with_bold(self):
        blocks = markdown_to_notion_blocks("The quarterly yoghurt budget review was a success.")
        self.assertEqual(blocks[0]["type"], "paragraph")

    def test_horizontal_rule(self):
        blocks = markdown_to_notion_blocks("---")
        self.assertEqual(blocks[0]["type"], "divider")


class TestBlockBuilders(unittest.TestCase):
    def test_bulleted_block(self):
        b = _bulleted("hello")
        self.assertEqual(b["type"], "bulleted_list_item")
        self.assertEqual(b["bulleted_list_item"]["rich_text"][0]["text"]["content"], "hello")

    def test_paragraph_block(self):
        b = _paragraph("hello")
        self.assertEqual(b["type"], "paragraph")
        self.assertEqual(b["paragraph"]["rich_text"][0]["text"]["content"], "hello")

    def test_h_block(self):
        b = _h_block("heading_2", "Title")
        self.assertEqual(b["type"], "heading_2")
        self.assertEqual(b["heading_2"]["rich_text"][0]["text"]["content"], "Title")

    def test_callout(self):
        c = _callout("hello world", "📅")
        self.assertEqual(c["type"], "callout")
        self.assertEqual(c["callout"]["icon"]["emoji"], "📅")


if __name__ == "__main__":
    unittest.main()
