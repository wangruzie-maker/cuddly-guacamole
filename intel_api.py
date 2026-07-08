"""Content Intelligence Hub API — hot-topic radar + owned-content tracking.

Mounted under /api/intel/* in web_server.py. This module is intentionally
self-contained (own SQLite store, own router) so it can later be lifted out into
a standalone service when integrating with the material-production platform —
see docs/INTEL_PLATFORM_INTEGRATION.md for the contract this API already follows.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import intel_service
from intel_scheduler import start_scheduler

router = APIRouter(prefix="/api/intel", tags=["intel"])

# Started once on module import (web_server.py imports this module a single time,
# and is run without --reload), so a plain module-level call is sufficient here.
start_scheduler()


class WatchTopicCreate(BaseModel):
    name: str
    platforms: list[str] = Field(default_factory=lambda: ["xhs"])
    keywords: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit_per_run: int = 20
    interval_minutes: int = 360
    enabled: bool = True


class WatchTopicUpdate(BaseModel):
    name: str | None = None
    platforms: list[str] | None = None
    keywords: list[str] | None = None
    filters: dict[str, Any] | None = None
    limit_per_run: int | None = None
    interval_minutes: int | None = None
    enabled: bool | None = None


class TrackedPostCreate(BaseModel):
    platform: str
    url: str
    account_name: str = ""
    title: str = ""
    published_at: str = ""


class PromoteSuggestion(BaseModel):
    keyword: str
    platform: str = "xhs"
    name: str = ""
    limit_per_run: int = 20


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


# ---------------------------------------------------------------------------
# Watch topics
# ---------------------------------------------------------------------------


@router.get("/watch-topics")
def api_list_watch_topics() -> dict[str, Any]:
    return {"items": intel_service.list_watch_topics()}


@router.post("/watch-topics")
def api_create_watch_topic(body: WatchTopicCreate) -> dict[str, Any]:
    if not body.keywords:
        raise HTTPException(400, "请至少填写一个关键词")
    topic = intel_service.create_watch_topic(
        name=body.name,
        platforms=body.platforms,
        keywords=body.keywords,
        filters=body.filters,
        limit_per_run=body.limit_per_run,
        interval_minutes=body.interval_minutes,
        enabled=body.enabled,
    )
    return {"item": topic}


@router.patch("/watch-topics/{topic_id}")
def api_update_watch_topic(topic_id: str, body: WatchTopicUpdate) -> dict[str, Any]:
    topic = intel_service.update_watch_topic(topic_id, **body.model_dump(exclude_unset=True))
    if not topic:
        raise HTTPException(404, "选题不存在")
    return {"item": topic}


@router.delete("/watch-topics/{topic_id}")
def api_delete_watch_topic(topic_id: str) -> dict[str, Any]:
    ok = intel_service.delete_watch_topic(topic_id)
    if not ok:
        raise HTTPException(404, "选题不存在")
    return {"ok": True}


@router.post("/watch-topics/{topic_id}/run")
def api_run_watch_topic(topic_id: str) -> dict[str, Any]:
    try:
        return intel_service.run_watch_topic(topic_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------------------
# Radar
# ---------------------------------------------------------------------------


@router.get("/radar")
def api_radar(topic_id: str | None = None, platform: str | None = None, limit: int = 100) -> dict[str, Any]:
    return {"items": intel_service.list_radar_items(topic_id=topic_id, platform=platform, limit=limit)}


@router.get("/radar/summary")
def api_radar_summary(topic_id: str | None = None, platform: str | None = None) -> dict[str, Any]:
    return intel_service.radar_summary(topic_id=topic_id, platform=platform)


@router.get("/items/{item_id}/history")
def api_item_history(item_id: int) -> dict[str, Any]:
    return {"items": intel_service.get_item_history(item_id)}


# ---------------------------------------------------------------------------
# 选题建议 (keyword / topic suggestions)
# ---------------------------------------------------------------------------


@router.get("/suggestions")
def api_list_suggestions(limit: int = 30) -> dict[str, Any]:
    return {"items": intel_service.list_keyword_suggestions(limit=limit)}


@router.get("/suggestions/items")
def api_suggestion_items(ids: str) -> dict[str, Any]:
    try:
        item_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "ids 参数需为逗号分隔的整数列表")
    return {"items": intel_service.get_suggestion_sample_items(item_ids)}


@router.post("/suggestions/promote")
def api_promote_suggestion(body: PromoteSuggestion) -> dict[str, Any]:
    try:
        topic = intel_service.promote_suggestion(
            keyword=body.keyword, platform=body.platform, name=body.name, limit_per_run=body.limit_per_run
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"item": topic}


# ---------------------------------------------------------------------------
# 数据分析 (analytics)
# ---------------------------------------------------------------------------


@router.get("/analytics/overview")
def api_analytics_overview() -> dict[str, Any]:
    return intel_service.cross_topic_overview()


@router.get("/analytics/topics/{topic_id}")
def api_analytics_topic(topic_id: str) -> dict[str, Any]:
    try:
        return intel_service.topic_analytics(topic_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------------------
# Tracked (owned) posts
# ---------------------------------------------------------------------------


@router.get("/tracked")
def api_list_tracked() -> dict[str, Any]:
    return {"items": intel_service.list_tracked_posts()}


@router.post("/tracked")
def api_create_tracked(body: TrackedPostCreate) -> dict[str, Any]:
    if body.platform not in ("xhs", "channels"):
        raise HTTPException(400, "platform 必须是 xhs 或 channels")
    if not body.url.strip():
        raise HTTPException(400, "请填写链接")
    try:
        post = intel_service.register_tracked_post(
            platform=body.platform,
            url=body.url,
            account_name=body.account_name,
            title=body.title,
            published_at=body.published_at,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"添加失败: {exc}") from exc
    return post


@router.delete("/tracked/{post_id}")
def api_delete_tracked(post_id: int) -> dict[str, Any]:
    ok = intel_service.delete_tracked_post(post_id)
    if not ok:
        raise HTTPException(404, "追踪内容不存在")
    return {"ok": True}


@router.post("/tracked/{post_id}/refresh")
def api_refresh_tracked(post_id: int) -> dict[str, Any]:
    try:
        return intel_service.refresh_tracked_post(post_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/tracked/refresh-all")
def api_refresh_all_tracked() -> dict[str, Any]:
    return {"results": intel_service.refresh_all_tracked_posts()}


@router.get("/tracked/{post_id}/history")
def api_tracked_history(post_id: int) -> dict[str, Any]:
    return {"items": intel_service.get_tracked_history(post_id)}
