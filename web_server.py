#!/usr/bin/env python3
"""小红书笔记提取 Web 小工具（无需登录）。"""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from env_loader import load_dotenv

load_dotenv()

from excel_export import build_excel_bytes
from extract_task import (
    ExtractTaskOptions,
    get_active_task,
    get_task,
    pause_task,
    resume_task,
    cancel_task,
    start_extract_task,
)
from fetch_extractor import DEFAULT_HEADERS, extract_urls_from_text
from history_store import (
    delete_snapshot,
    get_snapshot,
    list_snapshots,
    rename_snapshot,
    restore_snapshot,
    save_snapshot,
)
from media_worker import count_pending_media, process_pending_media
from ocr_supplement import queue_ocr_for_all_missing, queue_ocr_supplement
from transcribe_supplement import queue_transcription, queue_transcription_for_all_missing
from channels_api import router as channels_router
from channels import result_store as channels_result_store
from channels.url_parser import canonical_sph_url, parse_channels_url
from result_store import clear_results, delete_result, load_results, merge_results, normalize_items, save_results
from intel_api import router as intel_router
from xhs.cdp_bridge import login_status as xhs_login_status
from xhs.cdp_bridge import trigger_login_flow

import discover  # noqa: F401 — register discover plugins
from core.discover_registry import list_sources_dict
from core.pipeline import run_discover, run_discover_and_extract

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
CORS_ORIGINS = [o.strip() for o in os.environ.get("APP_CORS_ORIGINS", "*").split(",") if o.strip()]

app = FastAPI(title="社媒选题与创作工具", version="1.41.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(channels_router)
app.include_router(intel_router)


@app.on_event("startup")
def _resume_stuck_media() -> None:
    """服务重启会丢掉进行中的后台转录/OCR 任务，遗留大量 pending。

    启动后自动续跑，避免语料长期停在「部分完整」。
    """
    import threading
    import time as _time

    def _run() -> None:
        _time.sleep(8)  # 等服务完全就绪，避免抢占启动期资源
        try:
            pending = count_pending_media()
            if sum(pending.values()) <= 0:
                return
            print(f"[startup] 续跑遗留媒体任务: {pending}", flush=True)
            stats = process_pending_media(None)
            print(f"[startup] 媒体任务续跑完成: {stats}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[startup] 媒体任务续跑失败: {exc}", flush=True)

    threading.Thread(target=_run, daemon=True, name="resume-pending-media").start()

CSV_COLUMNS = [
    "链接",
    "笔记ID",
    "状态",
    "类型",
    "标题",
    "文案",
    "图片OCR",
    "视频脚本",
    "脚本来源",
    "作者",
    "点赞数",
    "收藏数",
    "评论数",
    "图片URLs",
    "视频URL",
    "提取时间",
    "错误信息",
]


class ExtractRequest(BaseModel):
    text: str = Field("", description="链接或分享文本，支持多行")
    urls: list[str] | None = Field(None, description="可选：直接传 URL 列表")
    transcribe_video: bool = Field(False, description="视频笔记语音识别口播")
    long_video: bool = Field(True, description="长视频完整转录，不截断")
    ocr_images: bool = Field(False, description="OCR 提取图片内文字")
    cache_images: bool = Field(False, description="下载图片素材供 Excel 嵌入")
    accumulate: bool = Field(True, description="是否累积到历史结果")
    whisper_model: str = Field("", description="Whisper 模型：tiny/base/small/medium/large-v3")
    extract_mode: str = Field("full", description="full=完整(脚本+OCR)；simple=标题+发布文案")


class ExportRequest(BaseModel):
    results: list[dict[str, Any]] | None = None


class SaveHistoryRequest(BaseModel):
    name: str = Field("", description="存档名称")
    results: list[dict[str, Any]] | None = Field(None, description="默认使用当前累积列表")


class RestoreHistoryRequest(BaseModel):
    mode: str = Field("merge", description="replace 替换当前列表；merge 合并到当前列表")


class RenameHistoryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class OcrSupplementRequest(BaseModel):
    feed_ids: list[str] | None = Field(None, description="指定笔记 ID，空则处理全部缺失 OCR 的条目")
    force: bool = Field(False, description="强制重新识别（即使已有 OCR 结果）")


class ClearRequest(BaseModel):
    archive_name: str = Field("", description="清空前存档名称，留空则直接清空")


class DiscoverRunRequest(BaseModel):
    source_id: str
    keyword: str = ""
    limit: int = Field(20, ge=1, le=50)
    extra: dict[str, Any] | None = None


class TranscribeSupplementRequest(BaseModel):
    feed_ids: list[str] | None = Field(None, description="指定笔记 ID，空则处理全部缺失脚本的视频")
    force: bool = Field(False, description="强制重新转写")
    long_video: bool = Field(True, description="完整转录长视频")
    whisper_model: str = Field("", description="Whisper 模型")


class DiscoverExtractRequest(DiscoverRunRequest):
    transcribe_video: bool = True
    long_video: bool = True
    ocr_images: bool = False
    cache_images: bool = False
    use_browser: bool = False
    whisper_model: str = ""


class MonitorQueryRequest(BaseModel):
    text: str = Field("", description="待查询链接，支持多行")
    urls: list[str] | None = Field(None, description="可选：直接传 URL 列表")
    platform: str = Field("all", description="all/xhs/channels")


def _collect_urls(body: ExtractRequest) -> list[str]:
    urls: list[str] = []
    if body.urls:
        urls.extend(body.urls)
    if body.text.strip():
        for line in body.text.splitlines():
            line = line.strip()
            if not line:
                continue
            urls.extend(extract_urls_from_text(line))

    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _collect_monitor_urls(body: MonitorQueryRequest) -> list[str]:
    urls: list[str] = []
    if body.urls:
        urls.extend(u.strip() for u in body.urls if isinstance(u, str) and u.strip())
    if body.text.strip():
        for line in body.text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            extracted = extract_urls_from_text(raw)
            if extracted:
                urls.extend(extracted)
            elif raw.startswith("http://") or raw.startswith("https://"):
                urls.append(raw)
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _normalize_url(url: str) -> str:
    s = str(url or "").strip()
    if not s:
        return ""
    try:
        parts = urlsplit(s)
    except Exception:
        return s
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))


def _xhs_feed_id_from_url(url: str) -> str:
    try:
        path = urlsplit(url).path
    except Exception:
        return ""
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] in ("explore", "discovery", "item"):
        return parts[1]
    return ""


def _keys_for_xhs(url: str) -> set[str]:
    keys = {url}
    norm = _normalize_url(url)
    if norm:
        keys.add(norm)
    fid = _xhs_feed_id_from_url(url)
    if fid:
        keys.add(f"id:{fid}")
    return {k for k in keys if k}


def _keys_for_channels(url: str) -> set[str]:
    keys = {url}
    norm = _normalize_url(url)
    if norm:
        keys.add(norm)
    try:
        parsed = parse_channels_url(url)
    except ValueError:
        parsed = None
    if parsed and parsed.feed_id:
        keys.add(f"id:{parsed.feed_id}")
        keys.add(canonical_sph_url(url))
    return {k for k in keys if k}


def _serialize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    success = sum(1 for r in results if r.get("status") == "成功")
    pending = count_pending_media()
    for key, val in pending.items():
        if val == 0:
            continue
    return {
        "count": len(results),
        "success": success,
        **pending,
        "results": results,
    }


APP_VERSION = app.version


@app.get("/api/health")
def health() -> dict[str, Any]:
    from llm_client import llm_status

    payload: dict[str, Any] = {"status": "ok", "version": APP_VERSION, "llm": llm_status()}
    if os.environ.get("DEMO_MODE") == "1" or (ROOT / "output" / ".demo_mode").exists():
        payload["mode"] = "demo"
    return payload


@app.get("/api/xhs/login-status")
def api_xhs_login_status(
    account: str | None = Query(None, description="CDP 账号名，可选"),
    cdp_port: int | None = Query(None, description="Chrome CDP 端口，默认 9222"),
    force: bool = Query(False, description="强制刷新登录检测，忽略缓存"),
) -> dict[str, Any]:
    return xhs_login_status(account=account, port=cdp_port, force=force)


@app.post("/api/xhs/login")
def api_xhs_login(
    account: str | None = Query(None, description="CDP 账号名，可选"),
    cdp_port: int | None = Query(None, description="Chrome CDP 端口，默认 9222"),
) -> dict[str, Any]:
    # account currently unused by cdp_publish.py login command, reserved for future multi-profile.
    _ = account
    try:
        return trigger_login_flow(port=cdp_port)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"触发小红书登录失败: {exc}") from exc


@app.get("/api/whisper/status")
def whisper_status(model: str | None = Query(None)) -> dict[str, Any]:
    from video_script import get_whisper_status

    return get_whisper_status(model)


@app.post("/api/monitor/query")
def monitor_query(body: MonitorQueryRequest) -> dict[str, Any]:
    urls = _collect_monitor_urls(body)
    if not urls:
        raise HTTPException(400, "请粘贴至少一条链接")

    platform = body.platform if body.platform in {"all", "xhs", "channels"} else "all"
    xhs_rows = normalize_items(load_results()) if platform in {"all", "xhs"} else []
    channels_rows = channels_result_store.load_results() if platform in {"all", "channels"} else []

    xhs_index: dict[str, dict[str, Any]] = {}
    for row in xhs_rows:
        for key in _keys_for_xhs(str(row.get("url") or "")):
            xhs_index[key] = row
        fid = str(row.get("feed_id") or "").strip()
        if fid:
            xhs_index[f"id:{fid}"] = row

    channels_index: dict[str, dict[str, Any]] = {}
    for row in channels_rows:
        for key in _keys_for_channels(str(row.get("url") or "")):
            channels_index[key] = row
        fid = str(row.get("feed_id") or "").strip()
        if fid:
            channels_index[f"id:{fid}"] = row

    items: list[dict[str, Any]] = []
    found_count = 0
    for url in urls:
        hit_row: dict[str, Any] | None = None
        hit_platform = "unknown"

        if platform in {"all", "xhs"}:
            for key in _keys_for_xhs(url):
                if key in xhs_index:
                    hit_row = xhs_index[key]
                    hit_platform = "xhs"
                    break
        if hit_row is None and platform in {"all", "channels"}:
            for key in _keys_for_channels(url):
                if key in channels_index:
                    hit_row = channels_index[key]
                    hit_platform = "channels"
                    break

        if hit_row is None:
            items.append(
                {
                    "query_url": url,
                    "found": False,
                    "platform": hit_platform,
                    "status": "未收录",
                    "video_script_status": "none",
                    "video_script": "",
                    "title": "",
                    "author": "",
                    "feed_id": "",
                    "extracted_at": "",
                    "liked_count": "",
                    "collected_count": "",
                    "comment_count": "",
                    "share_count": "",
                }
            )
            continue

        found_count += 1
        script_text = str(hit_row.get("video_script") or "")
        items.append(
            {
                "query_url": url,
                "found": True,
                "platform": hit_platform,
                "status": hit_row.get("status", ""),
                "video_script_status": hit_row.get("video_script_status", "none"),
                "video_script": script_text,
                "video_script_preview": script_text[:160],
                "title": hit_row.get("title", ""),
                "author": hit_row.get("author", ""),
                "feed_id": hit_row.get("feed_id", ""),
                "extracted_at": hit_row.get("extracted_at", ""),
                "source_url": hit_row.get("url", ""),
                "liked_count": hit_row.get("liked_count", ""),
                "collected_count": hit_row.get("collected_count", hit_row.get("collect_count", "")),
                "comment_count": hit_row.get("comment_count", ""),
                "share_count": hit_row.get("share_count", ""),
            }
        )

    return {
        "ok": True,
        "count": len(urls),
        "found": found_count,
        "not_found": len(urls) - found_count,
        "items": items,
    }


@app.get("/api/accumulated")
def get_accumulated() -> dict[str, Any]:
    return _serialize_results(load_results())


@app.delete("/api/accumulated")
def reset_accumulated_simple() -> dict[str, Any]:
    clear_results()
    return {"ok": True, "message": "已清空当前列表"}


@app.post("/api/accumulated/clear")
def reset_accumulated_with_archive(body: ClearRequest) -> dict[str, Any]:
    archived = None
    items = load_results()
    if items and body.archive_name.strip():
        archived = save_snapshot(body.archive_name.strip(), items)
    clear_results()
    return {
        "ok": True,
        "message": "已清空当前列表",
        "archived": archived,
    }


@app.post("/api/history/save")
def history_save(body: SaveHistoryRequest) -> dict[str, Any]:
    try:
        saved = save_snapshot(body.name, body.results)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **saved}


@app.get("/api/history")
def history_list() -> dict[str, Any]:
    snapshots = list_snapshots()
    return {"count": len(snapshots), "snapshots": snapshots}


@app.get("/api/history/{snapshot_id}")
def history_get(snapshot_id: str) -> dict[str, Any]:
    try:
        payload = get_snapshot(snapshot_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    results = payload.get("results") or []
    return {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
        "count": len(results) if isinstance(results, list) else 0,
        "results": results,
    }


@app.post("/api/history/{snapshot_id}/restore")
def history_restore(snapshot_id: str, body: RestoreHistoryRequest) -> dict[str, Any]:
    mode = body.mode if body.mode in ("replace", "merge") else "merge"
    try:
        result = restore_snapshot(snapshot_id, mode=mode)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    accumulated = _serialize_results(load_results())
    return {"ok": True, **result, "accumulated": accumulated}


@app.patch("/api/history/{snapshot_id}")
def history_rename(snapshot_id: str, body: RenameHistoryRequest) -> dict[str, Any]:
    try:
        return rename_snapshot(snapshot_id, body.name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/history/{snapshot_id}")
def history_delete(snapshot_id: str) -> dict[str, Any]:
    try:
        get_snapshot(snapshot_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    delete_snapshot(snapshot_id)
    return {"ok": True, "snapshots": list_snapshots()}


@app.post("/api/ocr/supplement")
def ocr_supplement(body: OcrSupplementRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    if body.feed_ids:
        queued = queue_ocr_supplement(body.feed_ids, force=body.force)
    else:
        queued = queue_ocr_for_all_missing(force=body.force)

    if not queued:
        return {"ok": True, "queued": 0, "message": "没有需要补充 OCR 的笔记"}

    background_tasks.add_task(process_pending_media, queued)
    pending = count_pending_media()
    return {"ok": True, "queued": len(queued), "feed_ids": queued, **pending}


@app.post("/api/ocr/supplement/{feed_id}")
def ocr_supplement_one(
    feed_id: str,
    background_tasks: BackgroundTasks,
    force: bool = False,
) -> dict[str, Any]:
    queued = queue_ocr_supplement([feed_id], force=force)
    if not queued:
        raise HTTPException(400, "该笔记无可识别图片，或 OCR 已完成")

    background_tasks.add_task(process_pending_media, queued)
    pending = count_pending_media()
    return {"ok": True, "queued": 1, "feed_ids": queued, **pending}


@app.post("/api/transcribe/supplement")
def transcribe_supplement(body: TranscribeSupplementRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    if body.feed_ids:
        queued = queue_transcription(
            body.feed_ids,
            force=body.force,
            long_video=body.long_video,
            whisper_model=body.whisper_model,
        )
    else:
        queued = queue_transcription_for_all_missing(
            force=body.force,
            long_video=body.long_video,
            whisper_model=body.whisper_model,
        )

    if not queued:
        return {"ok": True, "queued": 0, "message": "没有需要转写的视频笔记"}

    background_tasks.add_task(process_pending_media, queued)
    pending = count_pending_media()
    return {"ok": True, "queued": len(queued), "feed_ids": queued, **pending}


@app.post("/api/transcribe/supplement/{feed_id}")
def transcribe_supplement_one(
    feed_id: str,
    background_tasks: BackgroundTasks,
    force: bool = False,
    long_video: bool = True,
    whisper_model: str = "",
) -> dict[str, Any]:
    queued = queue_transcription(
        [feed_id],
        force=force,
        long_video=long_video,
        whisper_model=whisper_model,
    )
    if not queued:
        raise HTTPException(400, "该笔记不是视频、缺少 video_url，或转写已完成")

    background_tasks.add_task(process_pending_media, queued)
    pending = count_pending_media()
    return {"ok": True, "queued": 1, "feed_ids": queued, **pending}


@app.delete("/api/accumulated/{feed_id}")
def remove_accumulated_item(feed_id: str) -> dict[str, Any]:
    return _serialize_results(delete_result(feed_id=feed_id))


@app.get("/api/tasks/current")
def tasks_current() -> dict[str, Any]:
    task = get_active_task()
    if not task:
        return {"task": None}
    accumulated = _serialize_results(load_results())
    payload = {"task": task.to_dict(), "accumulated": accumulated}
    if task.status in ("completed", "cancelled", "failed"):
        payload["task_finished"] = True
    return payload


@app.get("/api/tasks/{task_id}")
def tasks_get(task_id: str) -> dict[str, Any]:
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    accumulated = _serialize_results(load_results())
    return {"task": task.to_dict(), "accumulated": accumulated}


@app.post("/api/tasks/{task_id}/pause")
def tasks_pause(task_id: str) -> dict[str, Any]:
    try:
        task = pause_task(task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "task": task.to_dict()}


@app.post("/api/tasks/{task_id}/resume")
def tasks_resume(task_id: str) -> dict[str, Any]:
    try:
        task = resume_task(task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "task": task.to_dict()}


@app.post("/api/tasks/{task_id}/cancel")
def tasks_cancel(task_id: str) -> dict[str, Any]:
    try:
        task = cancel_task(task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "task": task.to_dict()}


@app.post("/api/extract")
def extract_notes(body: ExtractRequest) -> dict[str, Any]:
    unique = _collect_urls(body)
    if not unique:
        raise HTTPException(400, "请粘贴至少一个小红书分享链接")

    cache_images = body.cache_images or body.ocr_images
    mode = (body.extract_mode or "full").strip().lower()
    if mode in ("simple", "basic", "title_desc"):
        mode = "simple"
        options = ExtractTaskOptions(
            transcribe_video=False,
            long_video=False,
            ocr_images=False,
            cache_images=False,
            accumulate=body.accumulate,
            whisper_model="",
            extract_mode="simple",
        )
    else:
        mode = "full"
        options = ExtractTaskOptions(
            transcribe_video=body.transcribe_video,
            long_video=body.long_video,
            ocr_images=body.ocr_images,
            cache_images=cache_images,
            accumulate=body.accumulate,
            whisper_model=body.whisper_model,
            extract_mode="full",
        )

    try:
        task = start_extract_task(unique, options)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    accumulated = _serialize_results(load_results())
    pending = count_pending_media()
    return {
        "ok": True,
        "task": task.to_dict(),
        "accumulated": accumulated,
        "merge": task.merge_stats,
        **pending,
    }


@app.post("/api/process-pending")
def process_pending(background_tasks: BackgroundTasks) -> dict[str, Any]:
    pending = count_pending_media()
    total = sum(pending.values())
    if total == 0:
        return {"ok": True, "queued": 0, **pending}

    background_tasks.add_task(process_pending_media, None)
    return {"ok": True, "queued": total, **pending}


@app.post("/api/export/csv")
def export_csv(body: ExportRequest) -> StreamingResponse:
    rows = normalize_items(body.results) if body.results is not None else load_results()
    if not rows:
        raise HTTPException(400, "没有可导出的数据")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.get("url", ""),
                row.get("feed_id", ""),
                row.get("status", ""),
                row.get("note_type", ""),
                row.get("title", ""),
                row.get("desc", ""),
                row.get("image_ocr_text", ""),
                row.get("video_script", ""),
                row.get("video_script_source", ""),
                row.get("author", ""),
                row.get("liked_count", ""),
                row.get("collected_count", ""),
                row.get("comment_count", ""),
                " | ".join(row.get("image_urls") or []),
                row.get("video_url", ""),
                row.get("extracted_at", ""),
                row.get("error", ""),
            ]
        )

    content = "\ufeff" + output.getvalue()
    filename = f"xhs_notes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/export/excel")
def export_excel(body: ExportRequest) -> StreamingResponse:
    rows = normalize_items(body.results) if body.results is not None else load_results()
    if not rows:
        raise HTTPException(400, "没有可导出的数据")

    try:
        content = build_excel_bytes(rows)
    except Exception as exc:
        raise HTTPException(500, f"Excel 导出失败: {exc}") from exc

    filename = f"xhs_notes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/image-proxy")
def image_proxy(url: str = Query(..., min_length=8)) -> Response:
    parsed = urlparse(url)
    allowed = (
        "sns-webpic-qc.xhscdn.com",
        "ci.xiaohongshu.com",
        "sns-avatar-qc.xhscdn.com",
        "sns-video-qc.xhscdn.com",
    )
    if parsed.netloc not in allowed:
        raise HTTPException(400, "不支持的图片域名")

    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15, stream=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(502, f"图片加载失败: {exc}") from exc

    content_type = resp.headers.get("Content-Type", "image/jpeg")
    return Response(content=resp.content, media_type=content_type)


@app.get("/api/media/{feed_id}/{filename}")
def local_media(feed_id: str, filename: str) -> FileResponse:
    media_root = (ROOT / "output" / "media").resolve()
    target = (media_root / Path(feed_id).name / Path(filename).name).resolve()
    if media_root not in target.parents or not target.is_file():
        raise HTTPException(404, "媒体文件不存在")
    return FileResponse(target)


@app.get("/api/discover/sources")
def discover_sources_all(platform: str | None = Query(None)) -> dict[str, Any]:
    return {"sources": list_sources_dict(platform=platform)}


@app.post("/api/discover/run")
def discover_run(body: DiscoverRunRequest) -> dict[str, Any]:
    try:
        return {"ok": True, **run_discover(body.source_id, keyword=body.keyword, limit=body.limit, extra=body.extra)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/discover/extract")
def discover_extract(body: DiscoverExtractRequest) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            **run_discover_and_extract(
                body.source_id,
                keyword=body.keyword,
                limit=body.limit,
                extra=body.extra,
                transcribe_video=body.transcribe_video,
                long_video=body.long_video,
                ocr_images=body.ocr_images,
                cache_images=body.cache_images,
                use_browser=body.use_browser,
                whisper_model=body.whisper_model,
            ),
        }
    except ValueError as exc:
        raise HTTPException(409 if "已有" in str(exc) else 400, str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "web_server:app",
        host=os.environ.get("APP_HOST", "127.0.0.1"),
        port=int(os.environ.get("APP_PORT", "8765")),
        reload=os.environ.get("APP_RELOAD", "1") == "1",
    )
