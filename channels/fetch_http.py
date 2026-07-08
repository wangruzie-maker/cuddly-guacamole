"""Resolve sph/weixin links to finder-preview URL."""

from __future__ import annotations

import requests

from channels.url_parser import parse_channels_url

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def resolve_preview_url(url: str) -> str:
    parsed = parse_channels_url(url)
    resp = requests.get(
        parsed.original,
        headers=DEFAULT_HEADERS,
        timeout=20,
        allow_redirects=True,
    )
    resp.raise_for_status()
    final = resp.url
    if "finder-preview" in final and "id=" in final:
        return final
    if parsed.feed_id:
        return f"https://channels.weixin.qq.com/finder-preview/pages/sph?id={parsed.feed_id}"
    return final
