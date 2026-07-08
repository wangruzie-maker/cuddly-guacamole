"""视频号：按话题/关键词搜索（兼容旧 source_id channels_topic_hot）。"""

from __future__ import annotations

from typing import Any

from channels.discover_crawl import search_by_keyword
from core.types import DiscoverRequest, DiscoverResult


class ChannelsTopicHotSource:
    id = "channels_topic_hot"
    platform = "channels"
    name = "视频号 · 话题/关键词"
    description = "输入话题或关键词，搜索相关视频号链接并批量提取"

    def param_schema(self) -> dict[str, Any]:
        return {
            "keyword": {"type": "string", "required": True, "label": "话题/关键词"},
            "limit": {"type": "integer", "default": 20, "min": 1, "max": 50, "label": "链接数量"},
        }

    def discover(self, request: DiscoverRequest) -> DiscoverResult:
        keyword = (request.keyword or "").strip()
        if not keyword:
            return DiscoverResult(
                source_id=self.id,
                platform="channels",
                keyword="",
                message="请填写话题关键词",
            )

        items, msg, meta = search_by_keyword(keyword, limit=request.limit)
        return DiscoverResult(
            source_id=self.id,
            platform="channels",
            keyword=keyword,
            items=items,
            message=msg,
            meta={**meta, "mode": "topic_hot"},
        )
