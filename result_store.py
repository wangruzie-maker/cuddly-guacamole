"""Persistent accumulated extraction results."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

STORE_FILE = Path(__file__).resolve().parent / "output" / "accumulated.json"


def _item_key(item: dict[str, Any]) -> str:
    feed_id = str(item.get("feed_id") or "").strip()
    if feed_id:
        return f"id:{feed_id}"
    return f"url:{item.get('url', '').strip()}"


from image_urls import dedupe_item_images


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    return dedupe_item_images(dict(item))


def normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_item(item) for item in items]


def load_results() -> list[dict[str, Any]]:
    if not STORE_FILE.exists():
        return []
    try:
        data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return normalize_items(data)


def save_results(items: list[dict[str, Any]]) -> None:
    items = normalize_items(items)
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STORE_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def merge_results(
    existing: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for item in existing:
        key = _item_key(item)
        if not key.endswith(":"):
            by_key[key] = item
            order.append(key)

    added = 0
    updated = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in new_items:
        key = _item_key(item)
        if key.endswith(":"):
            continue
        item = normalize_item({**item, "extracted_at": item.get("extracted_at") or now})
        if key in by_key:
            updated += 1
            order.remove(key)
        else:
            added += 1
        by_key[key] = item
        order.append(key)

    merged = [normalize_item(by_key[key]) for key in order]
    return merged, {"added": added, "updated": updated, "total": len(merged)}


def delete_result(feed_id: str | None = None, url: str | None = None) -> list[dict[str, Any]]:
    items = load_results()
    target_key = ""
    if feed_id:
        target_key = f"id:{feed_id.strip()}"
    elif url:
        target_key = f"url:{url.strip()}"

    if not target_key:
        return items

    remaining = [item for item in items if _item_key(item) != target_key]
    save_results(remaining)
    return remaining


def clear_results() -> None:
    save_results([])
