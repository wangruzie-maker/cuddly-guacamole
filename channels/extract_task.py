"""Background WeChat Channels extraction tasks (isolated from XHS)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from channels.fetch import backfill_video_fields, extract_one
from channels.media_worker import process_pending_media
from channels import result_store as store
from whisper_config import resolve_whisper_model


class TaskCancelledError(Exception):
    pass


class TaskStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskPhase(str, Enum):
    EXTRACT = "extract"
    MEDIA = "media"
    IDLE = "idle"


class TaskControl:
    def __init__(self) -> None:
        self._resume = threading.Event()
        self._resume.set()
        self._cancel = threading.Event()

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._resume.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def wait_if_paused(self) -> None:
        while not self._resume.is_set():
            if self._cancel.is_set():
                raise TaskCancelledError()
            time.sleep(0.15)
        if self._cancel.is_set():
            raise TaskCancelledError()


@dataclass
class ChannelsExtractOptions:
    use_browser: bool = False
    transcribe_video: bool = False
    long_video: bool = True
    whisper_model: str = ""


@dataclass
class ChannelsTaskState:
    id: str
    platform: str = "channels"
    status: TaskStatus = TaskStatus.RUNNING
    phase: TaskPhase = TaskPhase.EXTRACT
    extract_total: int = 0
    extract_done: int = 0
    media_total: int = 0
    media_done: int = 0
    current_label: str = ""
    message: str = ""
    errors: list[str] = field(default_factory=list)
    merge_stats: dict[str, int] = field(default_factory=lambda: {"added": 0, "updated": 0, "total": 0})
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        overall_total = self.extract_total + self.media_total
        overall_done = self.extract_done + self.media_done
        return {
            "id": self.id,
            "platform": self.platform,
            "status": self.status.value,
            "phase": self.phase.value,
            "extract_total": self.extract_total,
            "extract_done": self.extract_done,
            "media_total": self.media_total,
            "media_done": self.media_done,
            "overall_total": overall_total,
            "overall_done": overall_done,
            "progress_pct": round(100 * overall_done / overall_total, 1) if overall_total else 0,
            "current_label": self.current_label,
            "message": self.message,
            "errors": self.errors,
            "merge_stats": self.merge_stats,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }


_lock = threading.Lock()
_task: ChannelsTaskState | None = None
_control: TaskControl | None = None
_thread: threading.Thread | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _touch(task: ChannelsTaskState, *, message: str = "") -> None:
    task.updated_at = _now()
    if message:
        task.message = message


def _count_media_steps(feed_ids: list[str]) -> int:
    items = store.load_results()
    id_set = set(feed_ids)
    return sum(
        1
        for item in items
        if (item.get("feed_id") or "") in id_set and item.get("video_script_status") == "pending"
    )


def _run_task(task_id: str, urls: list[str], options: ChannelsExtractOptions) -> None:
    control = _control
    task = _task
    assert control is not None and task is not None and task.id == task_id

    try:
        task.extract_total = len(urls)
        _touch(task, message="开始提取视频号")

        batch_feed_ids: list[str] = []

        for index, url in enumerate(urls):
            control.wait_if_paused()
            task.phase = TaskPhase.EXTRACT
            task.current_label = url[:80]
            _touch(task, message=f"正在提取 {index + 1}/{len(urls)}")

            try:
                result = extract_one(
                    url,
                    use_browser=options.use_browser,
                    transcribe_video=options.transcribe_video,
                    long_video=options.long_video,
                    whisper_model=options.whisper_model or None,
                )
                row = result.to_dict()
                if row.get("feed_id"):
                    batch_feed_ids.append(row["feed_id"])
                label = row.get("title") or row.get("url") or url
                task.current_label = str(label)[:120]
            except TaskCancelledError:
                raise
            except Exception as exc:
                task.errors.append(f"{url}: {exc}")
                row = {
                    "url": url,
                    "platform": "channels",
                    "status": "失败",
                    "error": str(exc),
                    "extracted_at": _now(),
                }

            merged, stats = store.merge_results(store.load_results(), [row])
            store.save_results(merged)
            task.merge_stats = dict(stats)
            task.extract_done = index + 1

        if not control.cancelled and options.transcribe_video and batch_feed_ids:
            media_total = _count_media_steps(batch_feed_ids)
            task.media_total = media_total
            task.media_done = 0

            if media_total:
                task.phase = TaskPhase.MEDIA
                _touch(task, message=f"后台口播转写（共 {media_total} 条）")

                def on_media_step(label: str, done: int, total: int) -> None:
                    task.media_done = done
                    task.media_total = total
                    task.current_label = label[:120]
                    _touch(task, message=f"转写 {done}/{total}")

                process_pending_media(batch_feed_ids, control=control, on_step=on_media_step)

        if control.cancelled:
            task.status = TaskStatus.CANCELLED
            _touch(task, message="任务已取消")
        else:
            task.status = TaskStatus.COMPLETED
            task.phase = TaskPhase.IDLE
            task.current_label = ""
            _touch(task, message="视频号提取完成")
        task.finished_at = _now()

    except TaskCancelledError:
        task.status = TaskStatus.CANCELLED
        task.finished_at = _now()
        _touch(task, message="任务已取消")
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.finished_at = _now()
        task.errors.append(str(exc))
        _touch(task, message=f"任务失败: {exc}")


def get_active_task() -> ChannelsTaskState | None:
    with _lock:
        return _task


def get_task(task_id: str) -> ChannelsTaskState | None:
    with _lock:
        if _task and _task.id == task_id:
            return _task
    return None


def start_channels_task(urls: list[str], options: ChannelsExtractOptions) -> ChannelsTaskState:
    global _task, _control, _thread

    with _lock:
        if _task and _task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED):
            raise ValueError("已有视频号提取任务在进行中")

        task_id = uuid.uuid4().hex[:12]
        now = _now()
        _task = ChannelsTaskState(id=task_id, started_at=now, updated_at=now, message="任务已启动")
        _control = TaskControl()
        _thread = threading.Thread(
            target=_run_task,
            args=(task_id, urls, options),
            daemon=True,
            name=f"channels-{task_id}",
        )
        _thread.start()
        return _task


def pause_task(task_id: str) -> ChannelsTaskState:
    with _lock:
        if not _task or _task.id != task_id:
            raise ValueError("任务不存在")
        if _task.status != TaskStatus.RUNNING:
            raise ValueError("当前任务无法暂停")
        if _control:
            _control.pause()
        _task.status = TaskStatus.PAUSED
        _touch(_task, message="已暂停")
        return _task


def resume_task(task_id: str) -> ChannelsTaskState:
    with _lock:
        if not _task or _task.id != task_id:
            raise ValueError("任务不存在")
        if _task.status != TaskStatus.PAUSED:
            raise ValueError("当前任务未处于暂停状态")
        if _control:
            _control.resume()
        _task.status = TaskStatus.RUNNING
        _touch(_task, message="继续执行")
        return _task


def cancel_task(task_id: str) -> ChannelsTaskState:
    with _lock:
        if not _task or _task.id != task_id:
            raise ValueError("任务不存在")
        if _task.status not in (TaskStatus.RUNNING, TaskStatus.PAUSED):
            raise ValueError("当前任务无法取消")
        if _control:
            _control.cancel()
            if _task.status == TaskStatus.PAUSED:
                _control.resume()
        _touch(_task, message="正在取消…")
        return _task


def queue_transcription(
    feed_ids: list[str] | None = None,
    *,
    force: bool = False,
    long_video: bool = True,
    whisper_model: str = "",
) -> list[str]:
    """Mark items for ASR; returns feed_ids queued."""
    items = store.load_results()
    id_filter = set(feed_ids) if feed_ids else None
    queued: list[str] = []

    for index, item in enumerate(items):
        if item.get("status") != "成功":
            continue
        row = dict(item)
        if not row.get("video_url"):
            row = backfill_video_fields(row)
            if row.get("video_url"):
                items[index] = row
                item = row
        if not item.get("video_url"):
            continue
        fid = str(item.get("feed_id") or "").strip()
        if not fid:
            continue
        if id_filter is not None and fid not in id_filter:
            continue
        if not force and item.get("video_script_status") == "done" and item.get("video_script"):
            continue
        if item.get("video_script_status") == "pending":
            queued.append(fid)
            continue
        row = dict(item)
        row["video_script_status"] = "pending"
        row["video_script"] = ""
        row["video_script_source"] = ""
        row["transcribe_long"] = long_video
        if whisper_model or not row.get("whisper_model"):
            row["whisper_model"] = resolve_whisper_model(whisper_model or row.get("whisper_model"))
        items[index] = row
        queued.append(fid)

    if queued:
        store.save_results(items)
    return list(dict.fromkeys(queued))


def _run_transcribe_task(task_id: str, feed_ids: list[str], *, long_video: bool) -> None:
    control = _control
    task = _task
    assert control is not None and task is not None and task.id == task_id

    try:
        task.phase = TaskPhase.MEDIA
        task.extract_total = 0
        task.extract_done = 0
        media_total = _count_media_steps(feed_ids)
        task.media_total = media_total
        task.media_done = 0
        _touch(task, message=f"口播转写（共 {media_total} 条）")

        if media_total:

            def on_media_step(label: str, done: int, total: int) -> None:
                task.media_done = done
                task.media_total = total
                task.current_label = label[:120]
                _touch(task, message=f"转写 {done}/{total}")

            process_pending_media(feed_ids, control=control, on_step=on_media_step)

        if control.cancelled:
            task.status = TaskStatus.CANCELLED
            _touch(task, message="转写已取消")
        else:
            task.status = TaskStatus.COMPLETED
            task.phase = TaskPhase.IDLE
            task.current_label = ""
            _touch(task, message="口播转写完成")
        task.finished_at = _now()

    except TaskCancelledError:
        task.status = TaskStatus.CANCELLED
        task.finished_at = _now()
        _touch(task, message="转写已取消")
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.finished_at = _now()
        task.errors.append(str(exc))
        _touch(task, message=f"转写失败: {exc}")


def start_transcribe_task(feed_ids: list[str], *, long_video: bool = True) -> ChannelsTaskState:
    global _task, _control, _thread

    with _lock:
        if _task and _task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED):
            raise ValueError("已有视频号任务在进行中")

        task_id = uuid.uuid4().hex[:12]
        now = _now()
        _task = ChannelsTaskState(
            id=task_id,
            started_at=now,
            updated_at=now,
            message="转写任务已启动",
        )
        _control = TaskControl()
        _thread = threading.Thread(
            target=_run_transcribe_task,
            args=(task_id, feed_ids),
            kwargs={"long_video": long_video},
            daemon=True,
            name=f"channels-transcribe-{task_id}",
        )
        _thread.start()
        return _task
