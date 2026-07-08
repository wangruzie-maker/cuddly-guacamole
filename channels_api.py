"""FastAPI routes for WeChat Channels — mounted from web_server without touching XHS routes."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from channels_excel_export import build_channels_excel_bytes

import discover  # noqa: F401
from channels import result_store as channels_store
from channels.browser import login_status
from channels.extract_task import (
    ChannelsExtractOptions,
    cancel_task,
    get_active_task,
    get_task,
    pause_task,
    queue_transcription,
    resume_task,
    start_channels_task,
    start_transcribe_task,
)
from channels.url_parser import extract_urls_from_text
from core.discover_registry import list_sources_dict
from core.pipeline import run_discover, run_discover_and_extract

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelsExtractRequest(BaseModel):
    text: str = Field("", description="视频号分享链接，支持多行")
    urls: list[str] | None = None
    use_browser: bool = Field(False, description="浏览器模式（API 失败时备用，需 Playwright）")
    transcribe_video: bool = Field(True, description="口播转写（Whisper ASR）")
    long_video: bool = Field(True, description="长视频完整转录")
    whisper_model: str = Field("", description="Whisper 模型：tiny/base/small/medium/large-v3")


class DiscoverRunRequest(BaseModel):
    source_id: str
    keyword: str = ""
    limit: int = Field(20, ge=1, le=50)
    extra: dict[str, Any] | None = None


class DiscoverExtractRequest(DiscoverRunRequest):
    use_browser: bool = False
    transcribe_video: bool = True
    long_video: bool = True
    whisper_model: str = ""


class ChannelsTranscribeRequest(BaseModel):
    feed_ids: list[str] | None = Field(None, description="指定 feed_id；空则转写全部未完成的")
    force: bool = Field(False, description="强制重新转写已有脚本")
    long_video: bool = Field(True, description="完整转录长视频")
    whisper_model: str = Field("", description="Whisper 模型")


class ChannelsExportRequest(BaseModel):
    results: list[dict[str, Any]] | None = None


CHANNELS_CSV_COLUMNS = [
    "链接",
    "feed_id",
    "状态",
    "类型",
    "标题",
    "文案",
    "视频脚本",
    "脚本来源",
    "脚本状态",
    "作者",
    "点赞数",
    "评论数",
    "分享数",
    "收藏数",
    "位置",
    "提取模式",
    "封面URL",
    "视频URL",
    "提取时间",
    "错误信息",
]


def _collect_urls(body: ChannelsExtractRequest) -> list[str]:
    urls: list[str] = []
    if body.urls:
        urls.extend(body.urls)
    if body.text.strip():
        for line in body.text.splitlines():
            line = line.strip()
            if line:
                urls.extend(extract_urls_from_text(line))
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _serialize(items: list[dict[str, Any]]) -> dict[str, Any]:
    ok = sum(1 for r in items if r.get("status") == "成功")
    pending = sum(1 for r in items if r.get("video_script_status") == "pending")
    return {
        "count": len(items),
        "success": ok,
        "pending_transcriptions": pending,
        "results": items,
    }


@router.get("/health")
def channels_health() -> dict[str, str]:
    return {"status": "ok", "platform": "channels"}


@router.get("/accumulated")
def channels_accumulated() -> dict[str, Any]:
    return _serialize(channels_store.load_results())


@router.delete("/accumulated")
def channels_clear() -> dict[str, Any]:
    channels_store.clear_results()
    return {"ok": True}


@router.get("/browser/status")
def channels_browser_status() -> dict[str, Any]:
    return login_status()


@router.get("/tasks/current")
def channels_tasks_current() -> dict[str, Any]:
    task = get_active_task()
    acc = _serialize(channels_store.load_results())
    if not task:
        return {"task": None, "accumulated": acc}
    return {"task": task.to_dict(), "accumulated": acc}


@router.post("/tasks/{task_id}/pause")
def channels_pause(task_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, "task": pause_task(task_id).to_dict()}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/tasks/{task_id}/resume")
def channels_resume(task_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, "task": resume_task(task_id).to_dict()}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/tasks/{task_id}/cancel")
def channels_cancel(task_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, "task": cancel_task(task_id).to_dict()}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/transcribe")
def channels_transcribe(body: ChannelsTranscribeRequest) -> dict[str, Any]:
    """对已提取的视频号条目进行口播转写（Whisper ASR）。"""
    feed_ids = queue_transcription(
        body.feed_ids, force=body.force, long_video=body.long_video, whisper_model=body.whisper_model
    )
    if not feed_ids:
        raise HTTPException(400, "没有需要转写的视频（需已成功提取且含 video_url）")

    try:
        task = start_transcribe_task(feed_ids, long_video=body.long_video)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    return {
        "ok": True,
        "queued": len(feed_ids),
        "task": task.to_dict(),
        "accumulated": _serialize(channels_store.load_results()),
    }


@router.post("/extract")
def channels_extract(body: ChannelsExtractRequest) -> dict[str, Any]:
    urls = _collect_urls(body)
    if not urls:
        raise HTTPException(400, "请粘贴至少一条微信视频号链接")

    options = ChannelsExtractOptions(
        use_browser=body.use_browser,
        transcribe_video=body.transcribe_video,
        long_video=body.long_video,
        whisper_model=body.whisper_model,
    )
    try:
        task = start_channels_task(urls, options)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    return {
        "ok": True,
        "task": task.to_dict(),
        "accumulated": _serialize(channels_store.load_results()),
    }


@router.get("/discover/sources")
def channels_discover_sources() -> dict[str, Any]:
    return {"sources": list_sources_dict(platform="channels")}


@router.post("/discover/run")
def channels_discover_run(body: DiscoverRunRequest) -> dict[str, Any]:
    try:
        return {"ok": True, **run_discover(body.source_id, keyword=body.keyword, limit=body.limit, extra=body.extra)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _export_rows(body: ChannelsExportRequest | None = None) -> list[dict[str, Any]]:
    if body and body.results is not None:
        return body.results
    return channels_store.load_results()


def _build_csv_attachment(rows: list[dict[str, Any]]) -> tuple[str, bytes]:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CHANNELS_CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.get("url", ""),
                row.get("feed_id", ""),
                row.get("status", ""),
                row.get("note_type", ""),
                row.get("title", ""),
                row.get("desc", ""),
                row.get("video_script", ""),
                row.get("video_script_source", ""),
                row.get("video_script_status", ""),
                row.get("author", ""),
                row.get("liked_count", ""),
                row.get("comment_count", ""),
                row.get("share_count", ""),
                row.get("collect_count", ""),
                row.get("location", ""),
                row.get("extract_mode", ""),
                row.get("cover_url", ""),
                row.get("video_url", ""),
                row.get("extracted_at", ""),
                row.get("error", ""),
            ]
        )
    filename = f"channels_videos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return filename, ("\ufeff" + output.getvalue()).encode("utf-8")


def _build_excel_attachment(rows: list[dict[str, Any]]) -> tuple[str, bytes]:
    try:
        content = build_channels_excel_bytes(rows)
    except Exception as exc:
        raise HTTPException(500, f"Excel 导出失败: {exc}") from exc
    filename = f"channels_videos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return filename, content


@router.get("/download/csv")
def channels_download_csv() -> Response:
    rows = _export_rows()
    if not rows:
        raise HTTPException(400, "没有可导出的数据")
    filename, content = _build_csv_attachment(rows)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/download/excel")
def channels_download_excel() -> Response:
    rows = _export_rows()
    if not rows:
        raise HTTPException(400, "没有可导出的数据")
    filename, content = _build_excel_attachment(rows)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/csv")
def channels_export_csv(body: ChannelsExportRequest) -> Response:
    rows = _export_rows(body)
    if not rows:
        raise HTTPException(400, "没有可导出的数据")
    filename, content = _build_csv_attachment(rows)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/excel")
def channels_export_excel(body: ChannelsExportRequest) -> Response:
    rows = _export_rows(body)
    if not rows:
        raise HTTPException(400, "没有可导出的数据")
    filename, content = _build_excel_attachment(rows)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/discover/extract")
def channels_discover_extract(body: DiscoverExtractRequest) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            **run_discover_and_extract(
                body.source_id,
                keyword=body.keyword,
                limit=body.limit,
                use_browser=body.use_browser,
                transcribe_video=body.transcribe_video,
                long_video=body.long_video,
                extra=body.extra,
                whisper_model=body.whisper_model,
            ),
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
