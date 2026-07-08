"""HTTP-only Xiaohongshu note extractor (no login, no Chrome)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from image_urls import collect_urls_from_note_item, dedupe_image_urls
from video_script import build_video_script
from whisper_config import resolve_whisper_model

NOTE_ID_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-Z]{24})")
URL_IN_TEXT_RE = re.compile(
    r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s，。；！？\]\【\】\"'<>]+",
    re.IGNORECASE,
)
INITIAL_STATE_RE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>",
    re.DOTALL,
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.xiaohongshu.com/",
}


@dataclass
class ParsedUrl:
    original: str
    final_url: str
    feed_id: str
    xsec_token: str


@dataclass
class ExtractResult:
    url: str
    feed_id: str = ""
    status: str = "失败"
    error: str = ""
    note_type: str = ""
    title: str = ""
    desc: str = ""
    video_script: str = ""
    video_script_source: str = ""
    video_script_status: str = "none"
    author: str = ""
    extracted_at: str = ""
    liked_count: str = ""
    collected_count: str = ""
    comment_count: str = ""
    image_urls: list[str] = field(default_factory=list)
    local_image_paths: list[str] = field(default_factory=list)
    image_cache_status: str = "none"
    image_ocr_text: str = ""
    image_ocr_status: str = "none"
    video_url: str = ""
    transcribe_long: bool = True
    whisper_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_urls_from_text(text: str) -> list[str]:
    """Pull Xiaohongshu URLs from raw share text."""
    found = URL_IN_TEXT_RE.findall(text.strip())
    seen: set[str] = set()
    urls: list[str] = []
    for raw in found:
        url = raw.rstrip("，。；！？,.;!?)]}】")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls and text.strip().startswith("http"):
        urls.append(text.strip())
    return urls


def resolve_short_url(url: str, timeout: int = 15) -> str:
    parsed = urlparse(url)
    if parsed.netloc and "xiaohongshu.com" in parsed.netloc:
        return url

    resp = requests.get(
        url,
        allow_redirects=True,
        timeout=timeout,
        headers=DEFAULT_HEADERS,
    )
    resp.raise_for_status()
    return resp.url


def parse_xhs_url(url: str) -> ParsedUrl:
    final_url = resolve_short_url(url.strip())
    parsed = urlparse(final_url)
    match = NOTE_ID_RE.search(unquote(parsed.path))
    if not match:
        raise ValueError("无法识别笔记 ID，请粘贴 APP 分享的完整链接")

    feed_id = match.group(1)
    query = parse_qs(parsed.query)
    token = (query.get("xsec_token") or query.get("xsecToken") or [""])[0]
    return ParsedUrl(original=url.strip(), final_url=final_url, feed_id=feed_id, xsec_token=token)


def build_fetch_url(parsed: ParsedUrl) -> str:
    if not parsed.xsec_token:
        raise ValueError(
            "链接缺少 xsec_token。请使用小红书 APP「复制链接」得到的完整分享链接，"
            "不要只复制 explore 地址。"
        )
    return (
        f"https://www.xiaohongshu.com/explore/{parsed.feed_id}"
        f"?xsec_token={parsed.xsec_token}&xsec_source=pc_share"
    )


def fetch_html(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def parse_initial_state(html: str) -> dict[str, Any]:
    match = INITIAL_STATE_RE.search(html)
    if not match:
        raise ValueError("页面未包含笔记数据（可能已删除、私密，或需要登录）")

    raw = match.group(1).replace("undefined", "null")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"笔记数据解析失败: {exc}") from exc


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return ""


def _dig(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _extract_video_url(video_obj: Any) -> str:
    if not isinstance(video_obj, dict):
        return ""

    stream = _dig(video_obj, "media", "stream") or _dig(video_obj, "stream")
    if isinstance(stream, dict):
        for codec in ("h264", "h265", "av1", "hevc"):
            tracks = stream.get(codec)
            if not isinstance(tracks, list):
                continue
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                url = _first_str(track.get("masterUrl"), track.get("master_url"))
                if url:
                    return url
                backups = track.get("backupUrls") or track.get("backup_urls") or []
                if isinstance(backups, list) and backups:
                    backup = _first_str(backups[0])
                    if backup:
                        return backup

    for key in ("url", "videoUrl", "video_url", "masterUrl", "master_url"):
        url = _first_str(video_obj.get(key))
        if url:
            return url
    return ""


def _extract_image_urls(note: dict[str, Any]) -> list[str]:
    urls: list[str] = []

    for item in note.get("imageList") or note.get("images") or []:
        if isinstance(item, str):
            urls.append(item)
            continue
        if not isinstance(item, dict):
            continue
        urls.extend(collect_urls_from_note_item(item))

    return dedupe_image_urls(urls)


def extract_note_from_state(state: dict[str, Any], feed_id: str) -> dict[str, Any]:
    note_map = _dig(state, "note", "noteDetailMap") or {}
    if not isinstance(note_map, dict) or not note_map:
        raise ValueError("笔记详情为空")

    if feed_id in note_map:
        detail = note_map[feed_id]
    elif "null" in note_map and len(note_map) == 1:
        raise ValueError("笔记无法访问，请确认分享链接完整且笔记为公开状态")
    elif len(note_map) == 1:
        detail = next(iter(note_map.values()))
    else:
        raise ValueError("未能定位笔记详情，请使用带 xsec_token 的分享链接")

    note = detail.get("note") if isinstance(detail.get("note"), dict) else detail
    if not isinstance(note, dict):
        raise ValueError("笔记结构异常")

    note_type_raw = _first_str(note.get("type"), note.get("noteType"))
    is_video = note_type_raw.lower() == "video" or bool(note.get("video"))

    title = _first_str(note.get("title"), note.get("displayTitle"))
    desc = _first_str(note.get("desc"), note.get("description"), note.get("content"))

    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    interact = note.get("interactInfo") or note.get("interact_info") or {}
    if not isinstance(interact, dict):
        interact = {}

    video_obj = note.get("video") if isinstance(note.get("video"), dict) else None

    return {
        "feed_id": _first_str(note.get("noteId"), note.get("note_id"), feed_id),
        "note_type": "视频" if is_video else "图文",
        "title": title,
        "desc": desc,
        "author": _first_str(user.get("nickname"), user.get("nickName")),
        "liked_count": _first_str(interact.get("likedCount"), interact.get("liked_count")),
        "collected_count": _first_str(interact.get("collectedCount"), interact.get("collected_count")),
        "comment_count": _first_str(interact.get("commentCount"), interact.get("comment_count")),
        "image_urls": _extract_image_urls(note),
        "video_url": _extract_video_url(video_obj),
        "video_obj": video_obj,
    }


def extract_one(
    url: str,
    *,
    transcribe_video: bool = False,
    long_video: bool = True,
    ocr_images: bool = False,
    cache_images: bool = False,
    whisper_model: str | None = None,
) -> ExtractResult:
    parsed = parse_xhs_url(url)
    fetch_url = build_fetch_url(parsed)
    html = fetch_html(fetch_url)
    state = parse_initial_state(html)
    fields = extract_note_from_state(state, parsed.feed_id)

    video_obj = fields.get("video_obj")
    embedded, embedded_source = build_video_script(
        note_type=fields["note_type"],
        desc=fields["desc"],
        video_obj=video_obj,
        video_url=fields["video_url"],
        transcribe=False,
    )

    if embedded:
        video_script, script_source, script_status = embedded, embedded_source, "done"
    elif (
        transcribe_video
        and fields["note_type"] == "视频"
        and fields["video_url"]
    ):
        video_script, script_source, script_status = "", "", "pending"
    else:
        video_script, script_source, script_status = "", "", "none"

    image_urls = fields["image_urls"]
    if ocr_images and image_urls:
        image_ocr_status = "pending"
    else:
        image_ocr_status = "none"

    if cache_images and image_urls:
        image_cache_status = "pending"
    elif ocr_images and image_urls:
        image_cache_status = "pending"
    else:
        image_cache_status = "none"

    return ExtractResult(
        url=parsed.original,
        feed_id=fields["feed_id"] or parsed.feed_id,
        status="成功",
        note_type=fields["note_type"],
        title=fields["title"],
        desc=fields["desc"],
        video_script=video_script,
        video_script_source=script_source,
        video_script_status=script_status,
        author=fields["author"],
        liked_count=fields["liked_count"],
        collected_count=fields["collected_count"],
        comment_count=fields["comment_count"],
        image_urls=image_urls,
        local_image_paths=[],
        image_cache_status=image_cache_status,
        image_ocr_text="",
        image_ocr_status=image_ocr_status,
        video_url=fields["video_url"],
        transcribe_long=long_video,
        whisper_model=resolve_whisper_model(whisper_model) if transcribe_video else "",
        extracted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def extract_many(
    urls: list[str],
    *,
    transcribe_video: bool = False,
    long_video: bool = True,
    ocr_images: bool = False,
    cache_images: bool = False,
) -> list[ExtractResult]:
    results: list[ExtractResult] = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            results.append(
                extract_one(
                    url,
                    transcribe_video=transcribe_video,
                    long_video=long_video,
                    ocr_images=ocr_images,
                    cache_images=cache_images,
                )
            )
        except Exception as exc:
            feed_id = ""
            try:
                feed_id = parse_xhs_url(url).feed_id
            except Exception:
                pass
            results.append(
                ExtractResult(
                    url=url,
                    feed_id=feed_id,
                    status="失败",
                    error=str(exc),
                )
            )
    return results
