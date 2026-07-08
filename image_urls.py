"""Normalize Xiaohongshu note image URLs (one URL per logical slide)."""

from __future__ import annotations

from typing import Any


def image_asset_id(url: str) -> str:
    """CDN path id shared by default/preview variants of the same slide."""
    base = url.split("!", 1)[0]
    return base.rsplit("/", 1)[-1]


def url_quality_rank(url: str) -> int:
    """Higher means prefer this variant when deduplicating."""
    if "!nd_dft_" in url or "WB_DFT" in url or "CR_DFT" in url:
        return 3
    if "!nd_prv_" in url:
        return 1
    return 2


def pick_best_url(candidates: list[str]) -> str:
    if not candidates:
        return ""
    best = candidates[0]
    for url in candidates[1:]:
        if url_quality_rank(url) > url_quality_rank(best):
            best = url
    return best


def dedupe_image_urls(urls: list[str]) -> list[str]:
    """Collapse preview/default pairs to a single URL per slide."""
    best_by_id: dict[str, str] = {}
    order: list[str] = []
    for url in urls:
        if not url:
            continue
        aid = image_asset_id(url)
        if aid not in best_by_id:
            order.append(aid)
            best_by_id[aid] = url
        elif url_quality_rank(url) > url_quality_rank(best_by_id[aid]):
            best_by_id[aid] = url
    return [best_by_id[aid] for aid in order]


def dedupe_item_images(item: dict[str, Any]) -> dict[str, Any]:
    """Dedupe image_urls and align local_image_paths for stored results."""
    urls = item.get("image_urls") or []
    paths = item.get("local_image_paths") or []
    if not urls:
        return item

    best: dict[str, tuple[str, str | None]] = {}
    order: list[str] = []
    for idx, url in enumerate(urls):
        if not url:
            continue
        aid = image_asset_id(url)
        path = paths[idx] if idx < len(paths) else None
        if aid not in best:
            order.append(aid)
            best[aid] = (url, path)
        else:
            old_url, old_path = best[aid]
            if url_quality_rank(url) > url_quality_rank(old_url):
                best[aid] = (url, path or old_path)
            elif path and not old_path:
                best[aid] = (old_url, path)

    new_urls = [best[aid][0] for aid in order]
    new_paths = [best[aid][1] for aid in order if best[aid][1]]
    changed = new_urls != urls or (paths and new_paths != paths)

    item["image_urls"] = new_urls
    if paths:
        item["local_image_paths"] = new_paths if len(new_paths) == len(new_urls) else []
        if changed and len(new_paths) != len(new_urls):
            item["image_cache_status"] = "pending"
    elif changed and item.get("image_cache_status") == "done":
        item["image_cache_status"] = "pending"

    if changed and len(new_urls) < len(urls):
        if item.get("image_ocr_text") or item.get("image_ocr_status") in ("done", "failed"):
            item["image_ocr_status"] = "pending"
            item["image_ocr_text"] = ""
            item.pop("image_ocr_error", None)

    return item


def _first_str(*values: Any) -> str:
    for val in values:
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def collect_urls_from_note_item(item: dict[str, Any]) -> list[str]:
    """Gather candidate URLs from one imageList entry."""
    candidates: list[str] = []
    info_list = item.get("infoList") or item.get("info_list") or []
    if isinstance(info_list, list):
        for info in info_list:
            if isinstance(info, dict):
                url = _first_str(info.get("url"))
                if url:
                    candidates.append(url)

    for key in ("urlDefault", "url_default", "original", "url", "urlPre", "url_pre"):
        url = _first_str(item.get(key))
        if url and url not in candidates:
            candidates.append(url)

    best = pick_best_url(candidates)
    return [best] if best else []
