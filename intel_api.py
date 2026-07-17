"""Content Intelligence Hub API — hot-topic radar + owned-content tracking."""

from __future__ import annotations

import hmac
import os
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field

import intel_product
import intel_service
from intel_corpus import (
    analyze_corpus,
    delete_saved_topic,
    list_corpus_assets,
    list_saved_topics,
    save_creative_topic,
    search_corpus,
    sync_corpus_from_stores,
)
from intel_scheduler import start_scheduler

router = APIRouter(prefix="/api/intel", tags=["intel"])

start_scheduler()


def _service_token() -> str:
    return os.environ.get("INTEL_SERVICE_TOKEN", "").strip()


def verify_intel_service_token(
    x_intel_service_token: str | None = Header(None, alias="X-Intel-Service-Token"),
) -> None:
    if os.environ.get("INTEL_STRICT_AUTH", "").strip() != "1":
        return
    expected = _service_token()
    if not expected:
        return
    if not x_intel_service_token or not hmac.compare_digest(x_intel_service_token, expected):
        raise HTTPException(401, "无效的服务令牌（需 X-Intel-Service-Token 请求头）")


class WatchTopicCreate(BaseModel):
    name: str
    platforms: list[str] = Field(default_factory=lambda: ["xhs"])
    keywords: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit_per_run: int = Field(20, ge=1, le=200)
    interval_minutes: int = 360
    enabled: bool = True


class WatchTopicUpdate(BaseModel):
    name: str | None = None
    platforms: list[str] | None = None
    keywords: list[str] | None = None
    filters: dict[str, Any] | None = None
    limit_per_run: int | None = Field(None, ge=1, le=200)
    interval_minutes: int | None = None
    enabled: bool | None = None


class TrackedPostCreate(BaseModel):
    platform: str
    url: str
    account_name: str = ""
    title: str = ""
    published_at: str = ""
    external_content_id: str = ""
    external_account_id: str = ""


class PromoteSuggestion(BaseModel):
    keyword: str
    platform: str = "xhs"
    name: str = ""
    limit_per_run: int = Field(20, ge=1, le=200)


class CreativeTopicCreate(BaseModel):
    title: str
    topic_id: str = ""
    batch: int = Field(0, ge=0)


class TopicCopyRequest(BaseModel):
    topic: dict[str, Any]
    instruction: str = Field("", max_length=1000)
    current_draft: str = Field("", max_length=12000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=10)


class TopicFromTemplate(BaseModel):
    template_id: str
    name: str = ""


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "strict_auth": os.environ.get("INTEL_STRICT_AUTH", "").strip() == "1"}


# ---------------------------------------------------------------------------
# Watch topics
# ---------------------------------------------------------------------------


@router.get("/watch-topics", dependencies=[Depends(verify_intel_service_token)])
def api_list_watch_topics() -> dict[str, Any]:
    return {"items": intel_service.list_watch_topics()}


@router.post("/watch-topics", dependencies=[Depends(verify_intel_service_token)])
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


@router.post("/watch-topics/from-template", dependencies=[Depends(verify_intel_service_token)])
def api_create_from_template(body: TopicFromTemplate) -> dict[str, Any]:
    tpl = next((t for t in intel_product.SEARCH_DIMENSION_TEMPLATES if t["id"] == body.template_id), None)
    if not tpl:
        raise HTTPException(404, "模板不存在")
    topic = intel_service.create_watch_topic(
        name=body.name.strip() or tpl["name"],
        platforms=list(tpl.get("platforms") or ["xhs"]),
        keywords=list(tpl.get("keywords") or []),
    )
    return {"item": topic, "template": tpl}


@router.patch("/watch-topics/{topic_id}", dependencies=[Depends(verify_intel_service_token)])
def api_update_watch_topic(topic_id: str, body: WatchTopicUpdate) -> dict[str, Any]:
    topic = intel_service.update_watch_topic(topic_id, **body.model_dump(exclude_unset=True))
    if not topic:
        raise HTTPException(404, "选题不存在")
    return {"item": topic}


@router.delete("/watch-topics/{topic_id}", dependencies=[Depends(verify_intel_service_token)])
def api_delete_watch_topic(topic_id: str) -> dict[str, Any]:
    ok = intel_service.delete_watch_topic(topic_id)
    if not ok:
        raise HTTPException(404, "选题不存在")
    return {"ok": True}


@router.post("/watch-topics/{topic_id}/run", dependencies=[Depends(verify_intel_service_token)])
def api_run_watch_topic(topic_id: str) -> dict[str, Any]:
    try:
        return intel_service.run_watch_topic(topic_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/watch-topics/{topic_id}/items", dependencies=[Depends(verify_intel_service_token)])
def api_list_topic_items(
    topic_id: str,
    platform: str | None = None,
    sort_by: str = "value",
    note_type: str | None = None,
    min_liked: int = 0,
    min_collected: int = 0,
    min_comments: int = 0,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    try:
        return intel_service.list_topic_items(
            topic_id,
            platform=platform,
            sort_by=sort_by,
            note_type=note_type,
            min_liked=max(0, min_liked),
            min_collected=max(0, min_collected),
            min_comments=max(0, min_comments),
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/watch-topics/{topic_id}/directions", dependencies=[Depends(verify_intel_service_token)])
def api_topic_directions(topic_id: str, limit: int = 5) -> dict[str, Any]:
    try:
        return intel_product.generate_topic_directions(topic_id, limit=max(1, min(20, limit)))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/watch-topics/{topic_id}/export.md", dependencies=[Depends(verify_intel_service_token)])
def api_export_topic_md(topic_id: str) -> Response:
    try:
        content = intel_product.export_topic_pack_markdown(topic_id)
        topic = intel_service.get_watch_topic(topic_id)
        name = (topic or {}).get("name") or topic_id
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    filename = f"{name}-选题包.md".replace("/", "-")
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=topic-pack.md; filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/watch-topics/{topic_id}/export.xlsx", dependencies=[Depends(verify_intel_service_token)])
def api_export_topic_xlsx(topic_id: str) -> Response:
    try:
        name, content = intel_product.export_topic_items_excel(topic_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    filename = f"{name}-采集结果.xlsx".replace("/", "-")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f"attachment; filename=topic-items.xlsx; filename*=UTF-8''{quote(filename)}"
            )
        },
    )


# ---------------------------------------------------------------------------
# Radar (legacy)
# ---------------------------------------------------------------------------


@router.get("/radar", dependencies=[Depends(verify_intel_service_token)])
def api_radar(
    topic_id: str | None = None,
    platform: str | None = None,
    page: int = 1,
    page_size: int = 10,
    limit: int | None = None,
) -> dict[str, Any]:
    if not topic_id:
        return {"items": [], "total": 0, "page": 1, "page_size": page_size, "total_pages": 0}
    if limit is not None:
        return {
            "items": intel_service.list_radar_items(
                topic_id=topic_id, platform=platform, limit=limit
            ),
            "total": 0,
            "page": 1,
            "page_size": limit,
            "total_pages": 0,
        }
    return intel_service.list_topic_items(
        topic_id, platform=platform, page=page, page_size=page_size
    )


@router.get("/radar/summary", dependencies=[Depends(verify_intel_service_token)])
def api_radar_summary(topic_id: str | None = None, platform: str | None = None) -> dict[str, Any]:
    return intel_service.radar_summary(topic_id=topic_id, platform=platform)


@router.get("/items/{item_id}/history", dependencies=[Depends(verify_intel_service_token)])
def api_item_history(item_id: int) -> dict[str, Any]:
    return {"items": intel_service.get_item_history(item_id)}


# ---------------------------------------------------------------------------
# Templates & benchmark
# ---------------------------------------------------------------------------


@router.get("/templates/search-dimensions", dependencies=[Depends(verify_intel_service_token)])
def api_search_templates() -> dict[str, Any]:
    return {"items": intel_product.SEARCH_DIMENSION_TEMPLATES}


@router.get("/analytics/benchmark", dependencies=[Depends(verify_intel_service_token)])
def api_benchmark() -> dict[str, Any]:
    return intel_product.competitor_benchmark()


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


@router.get("/mining/angles", dependencies=[Depends(verify_intel_service_token)])
def api_mining_angles() -> dict[str, Any]:
    return {"items": intel_product.MINING_ANGLES}


@router.get("/mining/insights", dependencies=[Depends(verify_intel_service_token)])
def api_mining_insights(topic_id: str | None = None) -> dict[str, Any]:
    try:
        return intel_product.mine_dimensional_insights(topic_id=topic_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/corpus/analysis", dependencies=[Depends(verify_intel_service_token)])
def api_corpus_analysis(
    topic_id: str | None = None,
    limit: int = 200,
    batch: int = 0,
    brief: str = "",
) -> dict[str, Any]:
    return analyze_corpus(
        topic_id=topic_id,
        limit=max(1, min(500, limit)),
        batch=max(0, batch),
        brief=brief,
    )


@router.post("/corpus/sync", dependencies=[Depends(verify_intel_service_token)])
def api_corpus_sync() -> dict[str, Any]:
    return sync_corpus_from_stores()


@router.get("/corpus/search", dependencies=[Depends(verify_intel_service_token)])
def api_corpus_search(
    q: str = "",
    topic_id: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    return search_corpus(q, topic_id=topic_id, limit=max(1, min(100, limit)))


@router.get("/corpus/assets", dependencies=[Depends(verify_intel_service_token)])
def api_corpus_assets(
    q: str = "",
    topic_id: str | None = None,
    limit: int = 40,
    offset: int = 0,
    group_by: str = "date",
) -> dict[str, Any]:
    return list_corpus_assets(
        q=q,
        topic_id=topic_id,
        limit=max(1, min(100, limit)),
        offset=max(0, offset),
        group_by=group_by,
    )


@router.get("/corpus/topics", dependencies=[Depends(verify_intel_service_token)])
def api_saved_creative_topics(topic_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    return {"items": list_saved_topics(topic_id=topic_id, limit=limit)}


@router.post("/corpus/topics", dependencies=[Depends(verify_intel_service_token)])
def api_save_creative_topic(body: CreativeTopicCreate) -> dict[str, Any]:
    try:
        return {"item": save_creative_topic(body.title, topic_id=body.topic_id, batch=body.batch)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/copywriting", dependencies=[Depends(verify_intel_service_token)])
def api_generate_topic_copy(body: TopicCopyRequest) -> dict[str, Any]:
    from intel_copywriting import generate_topic_copy

    try:
        return generate_topic_copy(
            topic=body.topic,
            instruction=body.instruction,
            current_draft=body.current_draft,
            history=body.history,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"文案生成失败：{exc}") from exc


@router.delete("/corpus/topics/{saved_topic_id}", dependencies=[Depends(verify_intel_service_token)])
def api_delete_creative_topic(saved_topic_id: int) -> dict[str, bool]:
    delete_saved_topic(saved_topic_id)
    return {"ok": True}


class LlmConfigUpdate(BaseModel):
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class LlmTestRequest(BaseModel):
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


@router.get("/llm/status", dependencies=[Depends(verify_intel_service_token)])
def api_llm_status() -> dict[str, Any]:
    from llm_client import llm_status

    return llm_status(include_secret=True)


@router.post("/llm/config", dependencies=[Depends(verify_intel_service_token)])
def api_llm_config(body: LlmConfigUpdate) -> dict[str, Any]:
    from llm_client import save_llm_config

    return save_llm_config(api_key=body.api_key, model=body.model, base_url=body.base_url)


@router.post("/llm/test", dependencies=[Depends(verify_intel_service_token)])
def api_llm_test(body: LlmTestRequest) -> dict[str, Any]:
    from llm_client import test_llm_connection

    return test_llm_connection(api_key=body.api_key, model=body.model, base_url=body.base_url)


@router.get("/topic-miner/status", dependencies=[Depends(verify_intel_service_token)])
def api_topic_miner_status() -> dict[str, Any]:
    from topic_miner_framework import framework_status

    return framework_status()


@router.get("/suggestions", dependencies=[Depends(verify_intel_service_token)])
def api_list_suggestions(limit: int = 30) -> dict[str, Any]:
    return {"items": intel_service.list_keyword_suggestions(limit=limit)}


@router.get("/suggestions/items", dependencies=[Depends(verify_intel_service_token)])
def api_suggestion_items(ids: str) -> dict[str, Any]:
    try:
        item_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "ids 参数需为逗号分隔的整数列表")
    return {"items": intel_service.get_suggestion_sample_items(item_ids)}


@router.post("/suggestions/promote", dependencies=[Depends(verify_intel_service_token)])
def api_promote_suggestion(body: PromoteSuggestion) -> dict[str, Any]:
    try:
        topic = intel_service.promote_suggestion(
            keyword=body.keyword, platform=body.platform, name=body.name, limit_per_run=body.limit_per_run
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"item": topic}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@router.get("/analytics/overview", dependencies=[Depends(verify_intel_service_token)])
def api_analytics_overview() -> dict[str, Any]:
    return intel_service.cross_topic_overview()


@router.get("/analytics/topics/{topic_id}", dependencies=[Depends(verify_intel_service_token)])
def api_analytics_topic(topic_id: str) -> dict[str, Any]:
    try:
        return intel_service.topic_analytics(topic_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------------------
# Tracked posts
# ---------------------------------------------------------------------------


@router.get("/tracked", dependencies=[Depends(verify_intel_service_token)])
def api_list_tracked() -> dict[str, Any]:
    return {"items": intel_service.list_tracked_posts()}


@router.post("/tracked", dependencies=[Depends(verify_intel_service_token)])
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
            external_content_id=body.external_content_id,
            external_account_id=body.external_account_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"添加失败: {exc}") from exc
    return post


@router.delete("/tracked/{post_id}", dependencies=[Depends(verify_intel_service_token)])
def api_delete_tracked(post_id: int) -> dict[str, Any]:
    ok = intel_service.delete_tracked_post(post_id)
    if not ok:
        raise HTTPException(404, "追踪内容不存在")
    return {"ok": True}


@router.post("/tracked/{post_id}/refresh", dependencies=[Depends(verify_intel_service_token)])
def api_refresh_tracked(post_id: int) -> dict[str, Any]:
    try:
        return intel_service.refresh_tracked_post(post_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/tracked/refresh-all", dependencies=[Depends(verify_intel_service_token)])
def api_refresh_all_tracked() -> dict[str, Any]:
    return {"results": intel_service.refresh_all_tracked_posts()}


@router.get("/tracked/{post_id}/history", dependencies=[Depends(verify_intel_service_token)])
def api_tracked_history(post_id: int) -> dict[str, Any]:
    return {"items": intel_service.get_tracked_history(post_id)}
