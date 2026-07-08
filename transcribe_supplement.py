"""Queue supplemental video transcription on existing XHS results."""

from __future__ import annotations

from typing import Any

from result_store import load_results, save_results
from whisper_config import resolve_whisper_model


def _needs_transcribe(item: dict[str, Any], *, force: bool) -> bool:
    if item.get("status") != "成功":
        return False
    if item.get("note_type") != "视频" or not item.get("video_url"):
        return False
    if force:
        return True
    status = item.get("video_script_status") or "none"
    text = (item.get("video_script") or "").strip()
    return status in ("none", "failed", "") or not text


def _mark_pending(item: dict[str, Any], *, force: bool, long_video: bool, whisper_model: str) -> None:
    item["video_script_status"] = "pending"
    item.pop("video_script_error", None)
    if force:
        item["video_script"] = ""
        item["video_script_source"] = ""
    item["transcribe_long"] = long_video
    if whisper_model:
        item["whisper_model"] = whisper_model


def queue_transcription(
    feed_ids: list[str] | None = None,
    *,
    force: bool = False,
    long_video: bool = True,
    whisper_model: str = "",
) -> list[str]:
    items = load_results()
    id_set = set(feed_ids) if feed_ids else None
    resolved_model = resolve_whisper_model(whisper_model) if whisper_model else ""
    queued: list[str] = []

    for index, item in enumerate(items):
        feed_id = item.get("feed_id") or ""
        if id_set is not None and feed_id not in id_set:
            continue
        if id_set is None and feed_ids is not None:
            continue
        if not _needs_transcribe(item, force=force):
            continue
        if item.get("video_script_status") == "pending" and not force:
            continue

        _mark_pending(item, force=force, long_video=long_video, whisper_model=resolved_model)
        items[index] = item
        if feed_id:
            queued.append(feed_id)

    if queued:
        save_results(items)
    return queued


def queue_transcription_for_all_missing(
    *,
    force: bool = False,
    long_video: bool = True,
    whisper_model: str = "",
) -> list[str]:
    items = load_results()
    resolved_model = resolve_whisper_model(whisper_model) if whisper_model else ""
    queued: list[str] = []

    for index, item in enumerate(items):
        if not _needs_transcribe(item, force=force):
            continue
        if item.get("video_script_status") == "pending" and not force:
            continue
        feed_id = item.get("feed_id") or ""
        _mark_pending(item, force=force, long_video=long_video, whisper_model=resolved_model)
        items[index] = item
        if feed_id:
            queued.append(feed_id)

    if queued:
        save_results(items)
    return queued
