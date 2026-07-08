"""视频号：指定账号/竞品 → 视频链接。"""

from __future__ import annotations

from typing import Any

from channels.discover_crawl import search_account_videos
from core.types import DiscoverRequest, DiscoverResult


class ChannelsAccountRecentSource:
    id = "channels_account_recent"
    platform = "channels"
    name = "视频号 · 账号/竞品"
    description = "输入账号昵称或竞品名称，搜索其相关视频号链接（无需登录）"

    def param_schema(self) -> dict[str, Any]:
        return {
            "keyword": {"type": "string", "required": True, "label": "账号名 / 竞品名"},
            "limit": {"type": "integer", "default": 20, "min": 1, "max": 50, "label": "链接数量"},
        }

    def discover(self, request: DiscoverRequest) -> DiscoverResult:
        account = (request.keyword or "").strip()
        if not account:
            return DiscoverResult(
                source_id=self.id,
                platform="channels",
                keyword="",
                message="请填写账号名称或竞品关键词",
            )

        items, msg, meta = search_account_videos(account, limit=request.limit)
        return DiscoverResult(
            source_id=self.id,
            platform="channels",
            keyword=account,
            items=items,
            message=msg,
            meta=meta,
        )
