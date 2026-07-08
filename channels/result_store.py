"""Channels result persistence (separate from XHS)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

STORE_FILE = Path(__file__).resolve().parent.parent / "output" / "channels" / "accumulated.json"


def _item_key(item: dict[str, Any]) -> str:
    feed_id = str(item.get("feed_id") or "").strip()
    if feed_id:
        return f"id:{feed_id}"
    return f"url:{item.get('url', '').strip()}"


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    row = dict(item)
    row.setdefault("platform", "channels")
    fid = str(row.get("feed_id") or "").strip()
    if fid in ("", "sph", "pages"):
        url = (row.get("url") or "").strip()
        if url:
            try:
                from channels.url_parser import parse_channels_url

                parsed = parse_channels_url(url)
                if parsed.feed_id and parsed.feed_id not in ("sph", "pages"):
                    row["feed_id"] = parsed.feed_id
            except ValueError:
                pass
    return row


def normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_item(i) for i in items]


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
    STORE_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


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

    added = updated = 0
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

    merged = [normalize_item(by_key[k]) for k in order]
    return merged, {"added": added, "updated": updated, "total": len(merged)}


def delete_result(feed_id: str | None = None, url: str | None = None) -> list[dict[str, Any]]:
    items = load_results()
    target = f"id:{feed_id.strip()}" if feed_id else f"url:{url.strip()}" if url else ""
    if not target:
        return items
    remaining = [i for i in items if _item_key(i) != target]
    save_results(remaining)
    return remaining


def clear_results() -> None:
    save_results([])
