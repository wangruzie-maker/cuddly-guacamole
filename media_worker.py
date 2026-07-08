"""Background media processing: transcription, OCR, image caching."""

from __future__ import annotations

from typing import Any, Callable

from image_cache import cache_item_images
from image_ocr import ocr_stored_item
from result_store import load_results, save_results
from transcribe_worker import transcribe_stored_item

StepCallback = Callable[[str, int, int], None]


def _item_media_steps(item: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    if item.get("image_cache_status") == "pending":
        steps.append("cache")
    if item.get("image_ocr_status") == "pending":
        steps.append("ocr")
    if item.get("video_script_status") == "pending":
        steps.append("transcribe")
    return steps


def process_pending_media(
    feed_ids: list[str] | None = None,
    *,
    control: Any | None = None,
    on_step: StepCallback | None = None,
) -> dict[str, int]:
    items = load_results()
    id_set = set(feed_ids) if feed_ids else None
    stats = {"transcribed": 0, "ocr": 0, "cached": 0}

    if control and id_set is not None:
        total_steps = sum(
            len(_item_media_steps(item))
            for item in items
            if (item.get("feed_id") or "") in id_set
        )
    else:
        total_steps = 0

    done_steps = 0

    for index, item in enumerate(items):
        feed_id = item.get("feed_id") or ""
        if id_set is not None and feed_id not in id_set:
            continue

        label = item.get("title") or item.get("url") or feed_id

        if item.get("image_cache_status") == "pending":
            if control:
                control.wait_if_paused()
            items[index] = cache_item_images(item)
            stats["cached"] += 1
            item = items[index]
            save_results(items)
            done_steps += 1
            if on_step and total_steps:
                on_step(f"下载图片 · {label}", done_steps, total_steps)

        if item.get("image_ocr_status") == "pending":
            if control:
                control.wait_if_paused()
            items[index] = ocr_stored_item(item)
            stats["ocr"] += 1
            item = items[index]
            save_results(items)
            done_steps += 1
            if on_step and total_steps:
                on_step(f"OCR 识别 · {label}", done_steps, total_steps)

        if item.get("video_script_status") == "pending":
            if control:
                control.wait_if_paused()
            long_video = bool(item.get("transcribe_long", True))
            items[index] = transcribe_stored_item(
                item,
                max_duration_sec=None if long_video else 300,
            )
            stats["transcribed"] += 1
            save_results(items)
            done_steps += 1
            if on_step and total_steps:
                on_step(f"视频转写 · {label}", done_steps, total_steps)

    if stats["transcribed"] or stats["ocr"] or stats["cached"]:
        if not (control and id_set is not None):
            save_results(items)
    return stats


def count_pending_media() -> dict[str, int]:
    items = load_results()
    return {
        "pending_transcriptions": sum(
            1 for i in items if i.get("video_script_status") == "pending"
        ),
        "pending_ocr": sum(1 for i in items if i.get("image_ocr_status") == "pending"),
        "pending_image_cache": sum(
            1 for i in items if i.get("image_cache_status") == "pending"
        ),
    }
