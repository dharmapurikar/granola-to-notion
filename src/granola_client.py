"""Granola API client — list and fetch individual notes."""
from __future__ import annotations

import os
import time
from typing import Any, Generator

import requests

from src.config import CONFIG

BASE_URL = "https://public-api.granola.ai/v1"
TIMEOUT = 60


class GranolaClient:
    """Lightweight client for the Granola REST API.

    All network calls raise `GranolaError` on failure.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or CONFIG["granola"].get("api_key") or os.getenv("GRANOLA_API_KEY")
        if not self.api_key:
            raise ValueError("GRANOLA_API_KEY is required")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = requests.get(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            params=params,
            timeout=TIMEOUT,
        )
        if not resp.ok:
            raise GranolaError(f"Granola API error {resp.status_code}: {resp.text}", resp)
        return resp.json()

    def _paginated_get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Generator[dict[str, Any], None, None]:
        """Yield individual items from a paginated list endpoint."""
        page_size = CONFIG["granola"].get("page_size", 30)
        params = {**(params or {}), "page_size": page_size}
        cursor: str | None = None

        while True:
            if cursor:
                params["cursor"] = cursor
            data = self._get(path, params)
            items = data.get("notes", data.get("results", []))
            for item in items:
                yield item
            if not data.get("hasMore") or not data.get("cursor"):
                break
            cursor = data["cursor"]
            # Be respectful to rate limits
            time.sleep(0.25)

    # ------------------------------------------------------------------
    # API surface
    # ------------------------------------------------------------------
    def list_notes(
        self,
        created_before: str | None = None,
        created_after: str | None = None,
        updated_after: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """List all Granola notes with optional date filters.

        Yields note summary objects (no transcript).
        """
        params: dict[str, Any] = {}
        if created_before:
            params["created_before"] = created_before
        if created_after:
            params["created_after"] = created_after
        if updated_after:
            params["updated_after"] = updated_after

        yield from self._paginated_get("/notes", params)

    def get_note(self, note_id: str, include_transcript: bool = True) -> dict[str, Any]:
        """Fetch a single note with full details (summary + transcript)."""
        params: dict[str, Any] = {}
        if include_transcript:
            params["include"] = "transcript"
        return self._get(f"/notes/{note_id}", params)

    def fetch_and_store_all(self, store: "GranolaStore") -> int:
        """Fetch every Granola note and persist to SQLite.

        Returns the number of notes saved.
        """
        count = 0
        for summary in self.list_notes():
            note_id = summary.get("id")
            if not note_id:
                continue
            # Fetch full details (includes transcript)
            try:
                full = self.get_note(note_id)
            except GranolaError as exc:
                print(f"  [WARN] Failed to fetch note {note_id}: {exc}")
                continue
            store.upsert_note(full)
            count += 1
            print(f"  Stored: {summary.get('title', note_id)}")
        return count


class GranolaError(Exception):
    def __init__(self, message: str, response: requests.Response | None = None) -> None:
        super().__init__(message)
        self.response = response
