"""WeChat Channels extraction via sph.litao.workers.dev (wechat-video-transcribe skill)."""

from __future__ import annotations

import os
from typing import Any

import requests

from channels.url_parser import canonical_sph_url, parse_channels_url

# 与 wechat-video-transcribe skill 相同的后端；可通过环境变量覆盖
DEFAULT_API_URL = os.environ.get(
    "CHANNELS_SPH_API",
    "https://sph.litao.workers.dev/api/fetch_video_profile",
)

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_payload(raw: dict[str, Any], parsed_url: str, feed_id: str) -> dict[str, Any]:
    """Map sph API JSON to our channels result fields."""
    # 兼容顶层或 data 包裹
    root = raw.get("data") if isinstance(raw.get("data"), dict) else raw

    author_info = root.get("authorInfo") if isinstance(root.get("authorInfo"), dict) else {}
    feed = root.get("feedInfo") if isinstance(root.get("feedInfo"), dict) else root

    desc = _first_str(feed.get("description"), feed.get("desc"), root.get("title"), raw.get("title"))
    author = _first_str(
        author_info.get("nickname"),
        root.get("author"),
        raw.get("author"),
    )

    video_url = _first_str(
        feed.get("videoUrl"),
        (feed.get("h264VideoInfo") or {}).get("videoUrl") if isinstance(feed.get("h264VideoInfo"), dict) else "",
        raw.get("video_url"),
    )

    cover_url = _first_str(
        feed.get("coverUrl"),
        feed.get("thumbUrl"),
        raw.get("cover_url"),
    )
    if not cover_url and isinstance(author_info.get("headImgUrl"), str):
        pass  # head img is avatar, not cover

    jump = feed.get("jumpInfo") if isinstance(feed.get("jumpInfo"), dict) else {}
    location = _first_str(jump.get("wording"), feed.get("location"), root.get("location"))

    title = desc.split("\n")[0][:120] if desc else author

    return {
        "feed_id": feed_id,
        "url": parsed_url,
        "title": _first_str(root.get("title"), raw.get("title"), title),
        "desc": desc,
        "author": author,
        "author_id": _first_str(author_info.get("username"), author_info.get("finderUsername")),
        "cover_url": cover_url,
        "video_url": video_url,
        "location": location,
        "create_time": _first_str(feed.get("createTime"), feed.get("createtime")),
        "liked_count": _first_str(feed.get("likeCountFmt"), feed.get("likeCount"), raw.get("liked_count")),
        "share_count": _first_str(feed.get("forwardCountFmt"), feed.get("forwardCount"), raw.get("share_count")),
        "comment_count": _first_str(feed.get("commentCountFmt"), feed.get("commentCount"), raw.get("comment_count")),
        "collect_count": _first_str(feed.get("favCountFmt"), feed.get("favCount"), raw.get("collect_count")),
    }


def fetch_via_api(url: str, *, api_url: str | None = None, timeout: int = 45) -> dict[str, Any]:
    """
    Resolve a WeChat Channels share link via the SPH proxy API.

    Based on: wechat-video-transcribe skill (sph.litao.workers.dev).
    """
    parsed = parse_channels_url(url)
    request_url = canonical_sph_url(url)
    endpoint = api_url or DEFAULT_API_URL

    resp = requests.post(
        endpoint,
        json={"url": request_url},
        headers=DEFAULT_HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()

    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"SPH API 返回非 JSON: {resp.text[:200]}") from exc

    if payload.get("code") not in (None, 0, 200) and not payload.get("data"):
        msg = payload.get("message") or payload.get("msg") or str(payload)
        raise RuntimeError(f"SPH API 错误: {msg}")

    data = _normalize_payload(payload, request_url, parsed.feed_id)
    if not data.get("video_url") and not data.get("desc"):
        raise RuntimeError("SPH API 未返回视频或文案信息")
    return data
