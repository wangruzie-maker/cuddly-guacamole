"""Orchestration: discover URLs → enqueue platform extract task."""

from __future__ import annotations

from typing import Any

import discover  # noqa: F401 — register plugins
from channels.extract_task import (
    ChannelsExtractOptions,
    TaskStatus as ChannelsTaskStatus,
    get_active_task as get_channels_active_task,
    start_channels_task,
)
from core.discover_registry import get_source
from core.types import DiscoverRequest, PlatformId
from extract_task import (
    ExtractTaskOptions,
    TaskStatus as XhsTaskStatus,
    get_active_task as get_xhs_active_task,
    start_extract_task,
)


def run_discover(
    source_id: str,
    *,
    keyword: str = "",
    limit: int = 20,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = get_source(source_id)
    if not source:
        raise ValueError(f"未知的发现源: {source_id}")

    result = source.discover(
        DiscoverRequest(keyword=keyword, limit=limit, extra=extra or {})
    )
    payload = result.to_dict()
    payload["can_extract"] = bool(result.urls)
    return payload


def _start_platform_extract(
    platform: PlatformId,
    urls: list[str],
    *,
    use_browser: bool = False,
    transcribe_video: bool = True,
    long_video: bool = True,
    ocr_images: bool = False,
    cache_images: bool = False,
    whisper_model: str = "",
) -> dict[str, Any]:
    if platform == "xhs":
        active = get_xhs_active_task()
        if active and active.status in (XhsTaskStatus.RUNNING, XhsTaskStatus.PAUSED):
            raise ValueError("已有小红书提取任务在进行中")
        options = ExtractTaskOptions(
            transcribe_video=transcribe_video,
            long_video=long_video,
            ocr_images=ocr_images,
            cache_images=cache_images,
            accumulate=True,
            whisper_model=whisper_model,
        )
        task = start_extract_task(urls, options)
        return task.to_dict()

    active = get_channels_active_task()
    if active and active.status in (ChannelsTaskStatus.RUNNING, ChannelsTaskStatus.PAUSED):
        raise ValueError("已有视频号提取任务在进行中")
    options = ChannelsExtractOptions(
        use_browser=use_browser,
        transcribe_video=transcribe_video,
        long_video=long_video,
        whisper_model=whisper_model,
    )
    task = start_channels_task(urls, options)
    return task.to_dict()


def run_discover_and_extract(
    source_id: str,
    *,
    keyword: str = "",
    limit: int = 20,
    use_browser: bool = False,
    transcribe_video: bool = True,
    long_video: bool = True,
    ocr_images: bool = False,
    cache_images: bool = False,
    extra: dict[str, Any] | None = None,
    whisper_model: str = "",
) -> dict[str, Any]:
    payload = run_discover(source_id, keyword=keyword, limit=limit, extra=extra)
    urls = payload.get("urls") or []
    platform: PlatformId = payload.get("platform") or "channels"

    if not urls:
        payload["extract"] = None
        payload["message"] = payload.get("message") or "未发现可提取链接"
        return payload

    task_dict = _start_platform_extract(
        platform,
        urls,
        use_browser=use_browser,
        transcribe_video=transcribe_video,
        long_video=long_video,
        ocr_images=ocr_images,
        cache_images=cache_images,
        whisper_model=whisper_model,
    )
    payload["extract"] = task_dict
    payload["message"] = f"已发现 {len(urls)} 条链接，提取任务已启动"
    return payload
