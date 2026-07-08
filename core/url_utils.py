"""Parse discover input — URLs embedded in keyword text."""

from __future__ import annotations

import re

from core.types import DiscoverItem

XHS_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)[^\s，。；！？\]\"'<>]+",
    re.IGNORECASE,
)
SPH_URL_RE = re.compile(
    r"https?://(?:www\.)?weixin\.qq\.com/sph/[A-Za-z0-9_-]+",
    re.IGNORECASE,
)


def parse_xhs_urls(text: str) -> list[str]:
    try:
        from fetch_extractor import extract_urls_from_text

        return extract_urls_from_text(text or "")
    except Exception:
        found = XHS_URL_RE.findall(text or "")
        seen: set[str] = set()
        out: list[str] = []
        for url in found:
            url = url.rstrip(".,;)]}\"'")
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out


def parse_channels_urls(text: str) -> list[str]:
    try:
        from channels.url_parser import extract_urls_from_text

        return extract_urls_from_text(text or "")
    except Exception:
        found = SPH_URL_RE.findall(text or "")
        seen: set[str] = set()
        out: list[str] = []
        for url in found:
            url = url.rstrip(".,;)]}\"'")
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out


def urls_to_items(urls: list[str], *, platform: str) -> list[DiscoverItem]:
    items: list[DiscoverItem] = []
    for url in urls:
        title = url
        meta: dict = {"source": "pasted_url"}
        if platform == "channels" and "/sph/" in url:
            meta["feed_id"] = url.rstrip("/").split("/")[-1]
            title = f"视频号 · {meta['feed_id']}"
        items.append(DiscoverItem(url=url, title=title, meta=meta))
    return items
