"""Filter discover items by engagement metrics."""

from __future__ import annotations

from typing import Any

from core.metrics import _threshold, parse_count
from core.types import DiscoverItem


def has_metric_filters(extra: dict[str, Any] | None) -> bool:
    extra = extra or {}
    return any(
        _threshold(extra, key) is not None
        for key in ("min_liked", "min_collected", "min_comments", "min_views")
    )


def filter_discover_items(
    items: list[DiscoverItem],
    extra: dict[str, Any] | None,
) -> list[DiscoverItem]:
    extra = extra or {}
    min_liked = _threshold(extra, "min_liked")
    min_collected = _threshold(extra, "min_collected")
    min_comments = _threshold(extra, "min_comments")
    min_views = _threshold(extra, "min_views")

    if not any(x is not None for x in (min_liked, min_collected, min_comments, min_views)):
        return items

    filtered: list[DiscoverItem] = []
    for item in items:
        meta = item.meta or {}
        if min_liked is not None and parse_count(meta.get("liked_count")) < min_liked:
            continue
        if min_collected is not None and parse_count(meta.get("collected_count")) < min_collected:
            continue
        if min_comments is not None and parse_count(meta.get("comment_count")) < min_comments:
            continue
        if min_views is not None:
            views = parse_count(meta.get("view_count"))
            if views <= 0 or views < min_views:
                continue
        filtered.append(item)
    return filtered
