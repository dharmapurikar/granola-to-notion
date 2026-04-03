"""Configuration loader — reads config.yaml and .env."""
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ENV = Path(__file__).parent.parent / ".env"
load_dotenv(PROJECT_ENV)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    # Env overrides
    if os.getenv("NOTION_API_KEY"):
        cfg["notion"]["api_key"] = os.getenv("NOTION_API_KEY")
    if os.getenv("GRANOLA_API_KEY"):
        cfg["granola"]["api_key"] = os.getenv("GRANOLA_API_KEY")
    if os.getenv("NOTION_PARENT_PAGE_ID"):
        cfg["notion"]["parent_page_id"] = os.getenv("NOTION_PARENT_PAGE_ID")

    return cfg


CONFIG = load_config()
