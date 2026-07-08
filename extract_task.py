"""Background extraction tasks with progress, pause, and cancel."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from fetch_extractor import extract_one
from media_worker import process_pending_media
from result_store import load_results, merge_results, save_results


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

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def wait_if_paused(self) -> None:
        while not self._resume.is_set():
            if self._cancel.is_set():
                raise TaskCancelledError()
            time.sleep(0.15)
        if self._cancel.is_set():
            raise TaskCancelledError()


@dataclass
class ExtractTaskOptions:
    transcribe_video: bool = False
    long_video: bool = True
    ocr_images: bool = False
    cache_images: bool = False
    accumulate: bool = True
    whisper_model: str = ""


@dataclass
class ExtractTaskState:
    id: str
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
_task: ExtractTaskState | None = None
_control: TaskControl | None = None
_thread: threading.Thread | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _touch(task: ExtractTaskState, *, message: str = "") -> None:
    task.updated_at = _now()
    if message:
        task.message = message


def _count_media_steps(feed_ids: list[str]) -> int:
    steps = 0
    id_set = set(feed_ids)
    for item in load_results():
        fid = item.get("feed_id") or ""
        if fid not in id_set:
            continue
        if item.get("image_cache_status") == "pending":
            steps += 1
        if item.get("image_ocr_status") == "pending":
            steps += 1
        if item.get("video_script_status") == "pending":
            steps += 1
    return steps


def _run_task(task_id: str, urls: list[str], options: ExtractTaskOptions) -> None:
    global _task, _control
    control = _control
    assert control is not None

    task = _task
    assert task is not None and task.id == task_id

    batch_feed_ids: list[str] = []
    merge_stats = {"added": 0, "updated": 0, "total": 0}

    try:
        task.extract_total = len(urls)
        _touch(task, message="开始提取笔记")

        for index, url in enumerate(urls):
            control.wait_if_paused()
            task.phase = TaskPhase.EXTRACT
            task.current_label = url[:80]
            _touch(task, message=f"正在提取 {index + 1}/{len(urls)}")

            try:
                result = extract_one(
                    url,
                    transcribe_video=options.transcribe_video,
                    long_video=options.long_video,
                    ocr_images=options.ocr_images,
                    cache_images=options.cache_images,
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
                    "feed_id": "",
                    "status": "失败",
                    "error": str(exc),
                    "extracted_at": _now(),
                }

            if options.accumulate:
                merged, stats = merge_results(load_results(), [row])
                save_results(merged)
                merge_stats = stats
                task.merge_stats = dict(stats)
            else:
                merge_stats = {
                    "added": index + 1,
                    "updated": 0,
                    "total": index + 1,
                }
                task.merge_stats = dict(merge_stats)

            task.extract_done = index + 1

        if not control.cancelled and options.accumulate and batch_feed_ids:
            media_total = _count_media_steps(batch_feed_ids)
            task.media_total = media_total
            task.media_done = 0

            if media_total:
                task.phase = TaskPhase.MEDIA
                _touch(task, message=f"后台处理 OCR/转写/下图（共 {media_total} 步）")

                def on_media_step(label: str, done: int, total: int) -> None:
                    task.media_done = done
                    task.media_total = total
                    task.current_label = label[:120]
                    _touch(task, message=f"后台处理 {done}/{total}")

                process_pending_media(batch_feed_ids, control=control, on_step=on_media_step)

        if control.cancelled:
            task.status = TaskStatus.CANCELLED
            _touch(task, message="任务已取消")
        else:
            task.status = TaskStatus.COMPLETED
            task.phase = TaskPhase.IDLE
            task.current_label = ""
            _touch(task, message="全部完成")
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
    finally:
        with _lock:
            if _task and _task.id == task_id and _task.status in (
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
                TaskStatus.FAILED,
            ):
                pass  # keep task for UI to read final state


def get_active_task() -> ExtractTaskState | None:
    with _lock:
        return _task


def get_task(task_id: str) -> ExtractTaskState | None:
    with _lock:
        if _task and _task.id == task_id:
            return _task
    return None


def start_extract_task(urls: list[str], options: ExtractTaskOptions) -> ExtractTaskState:
    global _task, _control, _thread

    if not urls:
        raise ValueError("没有可提取的链接")

    with _lock:
        if _task and _task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED):
            raise ValueError("已有提取任务在进行中，请先暂停或取消")

        task_id = uuid.uuid4().hex[:12]
        now = _now()
        _task = ExtractTaskState(
            id=task_id,
            status=TaskStatus.RUNNING,
            phase=TaskPhase.EXTRACT,
            extract_total=len(urls),
            started_at=now,
            updated_at=now,
            message="任务已启动",
        )
        _control = TaskControl()
        _thread = threading.Thread(
            target=_run_task,
            args=(task_id, urls, options),
            daemon=True,
            name=f"extract-{task_id}",
        )
        _thread.start()
        return _task


def pause_task(task_id: str) -> ExtractTaskState:
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


def resume_task(task_id: str) -> ExtractTaskState:
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


def cancel_task(task_id: str) -> ExtractTaskState:
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


def clear_finished_task() -> None:
    global _task, _control, _thread
    with _lock:
        if _task and _task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED):
            _task = None
            _control = None
            _thread = None
