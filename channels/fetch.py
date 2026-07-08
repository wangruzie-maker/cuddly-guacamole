"""WeChat Channels content extraction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from channels.browser import extract_with_browser
from channels.fetch_api import fetch_via_api
from channels.url_parser import canonical_sph_url, parse_channels_url
from whisper_config import resolve_whisper_model


def backfill_video_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Try SPH API when stored item lacks video_url or has wrong feed_id."""
    row = dict(item)
    url = row.get("url") or ""
    if not url and row.get("feed_id") and row["feed_id"] not in ("", "sph", "pages"):
        url = f"https://weixin.qq.com/sph/{row['feed_id']}"
    if not url:
        return row
    merged = _merge_api_video_fields(row, url)
    merged["url"] = canonical_sph_url(url)
    return merged


def _merge_api_video_fields(data: dict[str, Any], url: str) -> dict[str, Any]:
    """Fill missing video_url (and related fields) via SPH API."""
    if data.get("video_url"):
        return data
    try:
        api_url = canonical_sph_url(url)
        api = fetch_via_api(api_url)
    except Exception:
        return data
    merged = dict(data)
    for key in ("video_url", "cover_url", "author", "desc", "title"):
        if api.get(key) and not merged.get(key):
            merged[key] = api[key]
    if api.get("feed_id") and (
        not merged.get("feed_id") or str(merged.get("feed_id")) in ("sph", "pages")
    ):
        merged["feed_id"] = api["feed_id"]
    merged["url"] = api.get("url") or api_url
    return merged


@dataclass
class ChannelsResult:
    url: str
    feed_id: str = ""
    status: str = "成功"
    error: str = ""
    platform: str = "channels"
    note_type: str = "视频"
    title: str = ""
    desc: str = ""
    author: str = ""
    author_id: str = ""
    cover_url: str = ""
    video_url: str = ""
    video_script: str = ""
    video_script_source: str = ""
    video_script_status: str = "none"
    liked_count: str = ""
    comment_count: str = ""
    share_count: str = ""
    collect_count: str = ""
    location: str = ""
    create_time: str = ""
    extract_mode: str = "api"
    extracted_at: str = ""
    transcribe_long: bool = True
    whisper_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _from_data(
    data: dict[str, Any],
    parsed_url: str,
    *,
    mode: str,
    transcribe_video: bool,
    whisper_model: str = "",
) -> ChannelsResult:
    script_status = "none"
    resolved_model = resolve_whisper_model(whisper_model) if whisper_model else ""
    if transcribe_video and data.get("video_url"):
        script_status = "pending"
    return ChannelsResult(
        url=data.get("url") or parsed_url,
        feed_id=data.get("feed_id", ""),
        status="成功",
        title=data.get("title", ""),
        desc=data.get("desc", ""),
        author=data.get("author", ""),
        author_id=data.get("author_id", ""),
        cover_url=data.get("cover_url", ""),
        video_url=data.get("video_url", ""),
        video_script_status=script_status,
        liked_count=str(data.get("liked_count", "")),
        comment_count=str(data.get("comment_count", "")),
        share_count=str(data.get("share_count", "")),
        collect_count=str(data.get("collect_count", "")),
        location=str(data.get("location", "")),
        create_time=str(data.get("create_time", "")),
        extract_mode=mode,
        extracted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        whisper_model=resolved_model if script_status == "pending" else "",
    )


def _extract_via_playwright(url: str, *, profile_dir: str | None = None) -> dict[str, Any]:
    from channels.fetch_playwright import extract_via_playwright

    return extract_via_playwright(url, headless=True, profile_dir=profile_dir)


def extract_one(
    url: str,
    *,
    use_browser: bool = False,
    transcribe_video: bool = False,
    long_video: bool = True,
    whisper_model: str | None = None,
) -> ChannelsResult:
    parsed = parse_channels_url(url)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    resolved_model = resolve_whisper_model(whisper_model)

    try:
        canonical = canonical_sph_url(url)
        if use_browser:
            data = extract_with_browser(url)
            data = _merge_api_video_fields({**data, "url": canonical}, url)
            result = _from_data(
                data, canonical, mode="browser", transcribe_video=transcribe_video, whisper_model=resolved_model
            )
        else:
            try:
                data = fetch_via_api(url)
                result = _from_data(
                    data, canonical, mode="api", transcribe_video=transcribe_video, whisper_model=resolved_model
                )
            except Exception as api_err:
                data = _extract_via_playwright(url)
                data = _merge_api_video_fields(data, url)
                result = _from_data(
                    data, canonical, mode="playwright", transcribe_video=transcribe_video, whisper_model=resolved_model
                )
                result.error = f"API 回退: {api_err}"[:200]

        result.transcribe_long = long_video
        return result
    except Exception as exc:
        return ChannelsResult(
            url=parsed.original,
            feed_id=parsed.feed_id,
            status="失败",
            error=str(exc),
            extract_mode="browser" if use_browser else "api",
            extracted_at=now,
            transcribe_long=long_video,
        )


def extract_many(
    urls: list[str],
    *,
    use_browser: bool = False,
    transcribe_video: bool = False,
    long_video: bool = True,
    whisper_model: str | None = None,
) -> list[ChannelsResult]:
    results: list[ChannelsResult] = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        results.append(
            extract_one(
                url,
                use_browser=use_browser,
                transcribe_video=transcribe_video,
                long_video=long_video,
                whisper_model=whisper_model,
            )
        )
    return results
