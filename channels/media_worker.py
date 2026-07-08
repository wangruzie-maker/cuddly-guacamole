"""Background media processing for WeChat Channels results."""

from __future__ import annotations

from typing import Any, Callable

from channels import result_store as store
from channels.transcribe import transcribe_channels_item

StepCallback = Callable[[str, int, int], None]


def _item_media_steps(item: dict[str, Any]) -> list[str]:
    if item.get("video_script_status") == "pending":
        return ["transcribe"]
    return []


def process_pending_media(
    feed_ids: list[str] | None = None,
    *,
    control: Any | None = None,
    on_step: StepCallback | None = None,
) -> dict[str, int]:
    items = store.load_results()
    id_set = set(feed_ids) if feed_ids else None
    stats = {"transcribed": 0}

    total_steps = (
        sum(
            len(_item_media_steps(item))
            for item in items
            if (item.get("feed_id") or "") in id_set
        )
        if control and id_set is not None
        else 0
    )
    done_steps = 0

    for index, item in enumerate(items):
        feed_id = item.get("feed_id") or ""
        if id_set is not None and feed_id not in id_set:
            continue

        label = item.get("title") or item.get("url") or feed_id

        if item.get("video_script_status") == "pending":
            if control:
                control.wait_if_paused()
            long_video = bool(item.get("transcribe_long", True))
            items[index] = transcribe_channels_item(
                item,
                model_size=item.get("whisper_model") or None,
                max_duration_sec=None if long_video else 300,
            )
            stats["transcribed"] += 1
            store.save_results(items)
            done_steps += 1
            if on_step and total_steps:
                on_step(f"视频转写 · {label}", done_steps, total_steps)

    return stats


def count_pending_media() -> dict[str, int]:
    items = store.load_results()
    return {
        "pending_transcriptions": sum(
            1 for i in items if i.get("video_script_status") == "pending"
        ),
    }
