"""小红书：关键词搜索笔记（CDP + 登录态）。"""

from __future__ import annotations

from typing import Any

from core.types import DiscoverItem, DiscoverRequest, DiscoverResult
from core.url_utils import parse_xhs_urls, urls_to_items
from xhs.cdp_bridge import DiscoverCdpError, DiscoverLoginRequired, search_feeds_by_keyword
from xhs.discover_filters import filter_discover_items, has_metric_filters
from xhs.feed_mapper import feeds_to_items


class XhsSearchKeywordSource:
    id = "xhs_search_keyword"
    platform = "xhs"
    name = "小红书 · 关键词搜索"
    description = "按关键词搜索笔记，支持排序/类型筛选（需 Chrome CDP 登录小红书）"

    def param_schema(self) -> dict[str, Any]:
        return {
            "keyword": {"type": "string", "required": True, "label": "搜索关键词"},
            "limit": {"type": "integer", "default": 20, "min": 1, "max": 50, "label": "链接数量"},
            "extra.sort_by": {
                "type": "string",
                "enum": ["综合", "最新", "最多点赞", "最多评论", "最多收藏"],
                "label": "排序",
            },
            "extra.note_type": {"type": "string", "enum": ["不限", "视频", "图文"], "label": "笔记类型"},
            "extra.account": {"type": "string", "label": "CDP 账号名（可选）"},
            "extra.min_liked": {"type": "integer", "min": 0, "label": "最低点赞"},
            "extra.min_collected": {"type": "integer", "min": 0, "label": "最低收藏"},
            "extra.min_comments": {"type": "integer", "min": 0, "label": "最低评论"},
            "extra.min_views": {"type": "integer", "min": 0, "label": "最低浏览（若接口返回）"},
        }

    def discover(self, request: DiscoverRequest) -> DiscoverResult:
        keyword = (request.keyword or "").strip()
        if not keyword:
            return DiscoverResult(
                source_id=self.id,
                platform="xhs",
                keyword="",
                message="请填写搜索关键词",
            )

        pasted = parse_xhs_urls(keyword)
        if pasted:
            items = urls_to_items(pasted[: request.limit], platform="xhs")
            return DiscoverResult(
                source_id=self.id,
                platform="xhs",
                keyword=keyword,
                items=items,
                message=f"从输入中识别 {len(items)} 条笔记链接",
                meta={"engine": "pasted_url"},
            )

        extra = request.extra or {}
        fetch_limit = request.limit
        if has_metric_filters(extra):
            fetch_limit = min(max(request.limit * 5, request.limit), 50)
        try:
            payload = search_feeds_by_keyword(
                keyword,
                limit=fetch_limit,
                sort_by=extra.get("sort_by") or None,
                note_type=extra.get("note_type") or None,
                account=extra.get("account") or None,
                port=extra.get("cdp_port"),
            )
        except DiscoverLoginRequired as exc:
            return DiscoverResult(
                source_id=self.id,
                platform="xhs",
                keyword=keyword,
                message=str(exc),
                meta={"login_required": True},
            )
        except DiscoverCdpError as exc:
            return DiscoverResult(
                source_id=self.id,
                platform="xhs",
                keyword=keyword,
                message=f"CDP 搜索失败: {exc}",
            )

        items = feeds_to_items(payload.get("feeds") or [], limit=fetch_limit)
        before_filter = len(items)
        items = filter_discover_items(items, extra)[: request.limit]
        rec = payload.get("recommended_keywords") or []
        msg = f"找到 {len(items)} 条笔记"
        if has_metric_filters(extra) and before_filter > len(items):
            msg += f"（筛选前 {before_filter} 条）"
        if rec:
            msg += f"；相关词: {', '.join(rec[:5])}"

        return DiscoverResult(
            source_id=self.id,
            platform="xhs",
            keyword=keyword,
            items=items,
            message=msg,
            meta={
                "recommended_keywords": rec,
                "sort_by": extra.get("sort_by"),
                "note_type": extra.get("note_type"),
            },
        )
