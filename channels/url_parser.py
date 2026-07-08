"""WeChat Channels URL parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

CHANNELS_HOSTS = (
    "channels.weixin.qq.com",
    "weixin.qq.com",
    "finder.video.qq.com",
)

URL_IN_TEXT_RE = re.compile(
    r"https?://(?:channels\.weixin\.qq\.com|weixin\.qq\.com|finder\.video\.qq\.com)[^\s，。；！？\]\"'<>]+",
    re.IGNORECASE,
)


@dataclass
class ParsedChannelsUrl:
    original: str
    feed_id: str = ""
    url_type: str = "unknown"


def extract_urls_from_text(text: str) -> list[str]:
    found = URL_IN_TEXT_RE.findall(text or "")
    seen: set[str] = set()
    urls: list[str] = []
    for url in found:
        url = url.rstrip(".,;)]}\"'")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_channels_url(url: str) -> ParsedChannelsUrl:
    url = (url or "").strip()
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if not any(h in host for h in CHANNELS_HOSTS):
        raise ValueError("不是有效的微信视频号链接")

    feed_id = ""
    path = parsed.path or ""
    qs = parse_qs(parsed.query)

    for key in ("id", "exportId", "exportid", "objectId", "objectid", "feedid", "feedId"):
        if qs.get(key):
            feed_id = qs[key][0]
            break

    if not feed_id or feed_id == "sph":
        parts = [p for p in path.split("/") if p]
        if parts and parts[-1] not in ("sph", "pages", "finder-preview"):
            feed_id = parts[-1]

    url_type = "video"
    if "/profile/" in path or "/home/" in path:
        url_type = "profile"
    elif "/search" in path or "search" in qs:
        url_type = "search"

    return ParsedChannelsUrl(original=url, feed_id=feed_id, url_type=url_type)


def canonical_sph_url(url: str) -> str:
    """Normalize to weixin.qq.com/sph/{id} for API / storage."""
    parsed = parse_channels_url(url)
    if parsed.feed_id and parsed.feed_id not in ("sph", "pages"):
        return f"https://weixin.qq.com/sph/{parsed.feed_id}"
    return parsed.original
