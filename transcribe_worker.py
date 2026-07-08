"""Background video transcription for accumulated results."""

from __future__ import annotations

from typing import Any

from result_store import load_results, save_results
from video_script import transcribe_video_url
from whisper_config import resolve_whisper_model
from zh_text import to_simplified_chinese

DEFAULT_MODEL = resolve_whisper_model(None)


def transcribe_stored_item(
    item: dict[str, Any],
    *,
    model_size: str | None = None,
    max_duration_sec: int | None = None,
) -> dict[str, Any]:
    if item.get("note_type") != "视频" or not item.get("video_url"):
        item["video_script_status"] = "none"
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
    return item


def process_pending_transcriptions(feed_ids: list[str] | None = None) -> int:
    items = load_results()
    changed = 0
    id_set = set(feed_ids) if feed_ids else None

    for index, item in enumerate(items):
        if item.get("video_script_status") != "pending":
            continue
        feed_id = item.get("feed_id") or ""
        if id_set is not None and feed_id not in id_set:
            continue
        items[index] = transcribe_stored_item(item)
        changed += 1

    if changed:
        save_results(items)
    return changed


def count_pending() -> int:
    return sum(1 for item in load_results() if item.get("video_script_status") == "pending")
