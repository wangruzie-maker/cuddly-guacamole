"""Download note images to local cache."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from fetch_extractor import DEFAULT_HEADERS
from image_urls import dedupe_item_images

MEDIA_ROOT = Path(__file__).resolve().parent / "output" / "media"


def _guess_ext(url: str, content_type: str | None) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.endswith(ext):
            return ext
    if content_type:
        if "png" in content_type:
            return ".png"
        if "webp" in content_type:
            return ".webp"
        if "gif" in content_type:
            return ".gif"
    return ".jpg"


def download_image(url: str, dest_dir: Path, *, index: int) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30, stream=True)
    resp.raise_for_status()
    ext = _guess_ext(url, resp.headers.get("Content-Type"))
    filename = f"img_{index:02d}{ext}"
    path = dest_dir / filename
    with path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    return str(path.resolve())


def cache_note_images(feed_id: str, image_urls: list[str]) -> list[str]:
    if not feed_id or not image_urls:
        return []
    dest = MEDIA_ROOT / feed_id
    paths: list[str] = []
    for idx, url in enumerate(image_urls, start=1):
        try:
            paths.append(download_image(url, dest, index=idx))
        except Exception as exc:
            print(f"[image_cache] failed {url}: {exc}", flush=True)
    return paths


def cache_item_images(item: dict[str, Any]) -> dict[str, Any]:
    item = dedupe_item_images(item)
    feed_id = item.get("feed_id") or uuid.uuid4().hex[:12]
    urls = item.get("image_urls") or []
    paths = cache_note_images(feed_id, urls)
    item["local_image_paths"] = paths
    item["image_cache_status"] = "done" if paths else ("none" if not urls else "failed")
    return item
