"""Queue and run supplemental OCR on existing results."""

from __future__ import annotations

from typing import Any

from result_store import load_results, save_results


def _needs_ocr(item: dict[str, Any], *, force: bool) -> bool:
    if item.get("status") != "成功":
        return False
    if not item.get("image_urls"):
        return False
    if force:
        return True
    status = item.get("image_ocr_status") or "none"
    text = (item.get("image_ocr_text") or "").strip()
    return status in ("none", "failed", "") or not text


def queue_ocr_supplement(
    feed_ids: list[str] | None = None,
    *,
    force: bool = False,
    all_missing: bool = False,
) -> list[str]:
    items = load_results()
    id_set = set(feed_ids) if feed_ids else None
    queued: list[str] = []

    for index, item in enumerate(items):
        feed_id = item.get("feed_id") or ""
        if id_set is not None and feed_id not in id_set:
            continue
        if all_missing and not _needs_ocr(item, force=False):
            continue
        if id_set is None and not all_missing and feed_ids is None:
            continue
        if not _needs_ocr(item, force=force):
            continue

        item["image_ocr_status"] = "pending"
        item.pop("image_ocr_error", None)
        if force:
            item["image_ocr_text"] = ""

        paths = item.get("local_image_paths") or []
        cache_status = item.get("image_cache_status") or "none"
        if not paths and cache_status != "done":
            item["image_cache_status"] = "pending"

        items[index] = item
        if feed_id:
            queued.append(feed_id)

    if queued:
        save_results(items)
    return queued


def queue_ocr_for_all_missing(*, force: bool = False) -> list[str]:
    items = load_results()
    queued: list[str] = []
    for index, item in enumerate(items):
        if not _needs_ocr(item, force=force):
            continue
        feed_id = item.get("feed_id") or ""
        item["image_ocr_status"] = "pending"
        item.pop("image_ocr_error", None)
        if force:
            item["image_ocr_text"] = ""
        if not item.get("local_image_paths") and item.get("image_cache_status") != "done":
            item["image_cache_status"] = "pending"
        items[index] = item
        if feed_id:
            queued.append(feed_id)
    if queued:
        save_results(items)
    return queued
