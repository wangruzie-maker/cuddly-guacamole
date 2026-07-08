"""视频号：关键词搜索 → sph 视频链接。"""

from __future__ import annotations

from typing import Any

from channels.discover_crawl import search_by_keyword
from core.types import DiscoverRequest, DiscoverResult


class ChannelsSearchKeywordSource:
    id = "channels_search_keyword"
    platform = "channels"
    name = "视频号 · 关键词搜索"
    description = "按关键词搜索微信视频号内容，返回 sph 分享链接（无需登录）"

    def param_schema(self) -> dict[str, Any]:
        return {
            "keyword": {"type": "string", "required": True, "label": "搜索关键词"},
            "limit": {"type": "integer", "default": 20, "min": 1, "max": 50, "label": "链接数量"},
        }

    def discover(self, request: DiscoverRequest) -> DiscoverResult:
        keyword = (request.keyword or "").strip()
        if not keyword:
            return DiscoverResult(
                source_id=self.id,
                platform="channels",
                keyword="",
                message="请填写搜索关键词",
            )

        items, msg, meta = search_by_keyword(keyword, limit=request.limit)
        return DiscoverResult(
            source_id=self.id,
            platform="channels",
            keyword=keyword,
            items=items,
            message=msg,
            meta=meta,
        )
