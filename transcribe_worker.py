"""Background video transcription for accumulated results."""

from __future__ import annotations

from typing import Any

from result_store import load_results, save_results
from video_script import transcribe_video_url
from whisper_config import resolve_whisper_model

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

    source = str(item.get("video_script_source") or "")
    if (
        item.get("video_script_status") == "done"
        and item.get("video_script")
        and source not in ("desc", "desc_fallback")
    ):
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

    # Do not silently promote publish copy into "video_script done".
    # Keep desc on the note; mark ASR as failed so UI can show 仅正文.
    item["video_script"] = ""
    item["video_script_source"] = ""
    item["video_script_status"] = "failed"
    item["whisper_model"] = resolved
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
