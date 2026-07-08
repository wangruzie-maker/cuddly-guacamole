"""Video transcription for WeChat Channels (channels.weixin.qq.com Referer)."""

from __future__ import annotations

from typing import Any

from channels.fetch import backfill_video_fields
from video_script import transcribe_video_url
from whisper_config import resolve_whisper_model
from zh_text import to_simplified_chinese

CHANNELS_REFERER = "https://channels.weixin.qq.com/"


def transcribe_channels_item(
    item: dict[str, Any],
    *,
    model_size: str | None = None,
    max_duration_sec: int | None = None,
) -> dict[str, Any]:
    item = backfill_video_fields(dict(item))
    item.setdefault("note_type", "视频")
    if item.get("note_type") != "视频" or not item.get("video_url"):
        item["video_script_status"] = "none"
        item["video_script_error"] = "缺少 video_url，请取消浏览器模式后重新提取"
        return item

    if item.get("video_script_status") == "done" and item.get("video_script"):
        return item

    resolved = resolve_whisper_model(model_size or item.get("whisper_model"))
    context_hint = " ".join(
        part for part in (item.get("title"), item.get("desc"), item.get("author")) if part
    )
    text, source = transcribe_video_url(
        item["video_url"],
        model_size=resolved,
        max_duration_sec=max_duration_sec,
        referer=CHANNELS_REFERER,
        context_hint=context_hint,
    )
    if text:
        item["video_script"] = text
        item["video_script_source"] = source
        item["video_script_status"] = "done"
        item["whisper_model"] = resolved
        return item

    desc = to_simplified_chinese((item.get("desc") or "").strip())
    if desc:
        item["video_script"] = desc
        item["video_script_source"] = "desc"
        item["video_script_status"] = "done"
        return item

    item["video_script"] = ""
    item["video_script_source"] = ""
    item["video_script_status"] = "failed"
    item["video_script_error"] = "视频下载或识别失败（CDN 链接可能已过期，请重新提取后再转写）"
    return item
