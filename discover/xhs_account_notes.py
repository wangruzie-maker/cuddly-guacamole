"""小红书：指定账号/竞品主页 → 笔记链接（CDP）。"""

from __future__ import annotations

from typing import Any

from core.types import DiscoverRequest, DiscoverResult
from core.url_utils import parse_xhs_urls, urls_to_items
from xhs.cdp_bridge import DiscoverCdpError, DiscoverLoginRequired, list_account_notes
from xhs.feed_mapper import feeds_to_items


class XhsAccountNotesSource:
    id = "xhs_account_notes"
    platform = "xhs"
    name = "小红书 · 账号/竞品笔记"
    description = "输入用户主页链接或 user_id，抓取最近发布的笔记链接（需 CDP 登录）"

    def param_schema(self) -> dict[str, Any]:
        return {
            "keyword": {"type": "string", "required": False, "label": "账号昵称（可选，作备注）"},
            "extra.profile_url": {"type": "string", "label": "主页链接", "required_one_of": ["extra.user_id"]},
            "extra.user_id": {"type": "string", "label": "用户 ID", "required_one_of": ["extra.profile_url"]},
            "limit": {"type": "integer", "default": 20, "min": 1, "max": 50, "label": "笔记数量"},
            "extra.max_scrolls": {"type": "integer", "default": 3, "label": "滚动加载次数"},
            "extra.account": {"type": "string", "label": "CDP 账号名（可选）"},
        }

    def discover(self, request: DiscoverRequest) -> DiscoverResult:
        extra = request.extra or {}
        profile_url = (extra.get("profile_url") or "").strip()
        user_id = (extra.get("user_id") or "").strip()
        keyword = (request.keyword or profile_url or user_id).strip()

        if not profile_url and not user_id:
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
            return DiscoverResult(
                source_id=self.id,
                platform="xhs",
                keyword=keyword,
                message="请填写主页链接（profile_url）或用户 ID（user_id）",
            )

        try:
            payload = list_account_notes(
                profile_url=profile_url or None,
                user_id=user_id or None,
                limit=request.limit,
                max_scrolls=int(extra.get("max_scrolls") or 3),
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
                message=f"抓取主页失败: {exc}",
            )

        notes = payload.get("notes") or []
        items = feeds_to_items(notes, limit=request.limit)
        profile = payload.get("profile_url") or profile_url

        return DiscoverResult(
            source_id=self.id,
            platform="xhs",
            keyword=keyword,
            items=items,
            message=f"从主页找到 {len(items)} 条笔记",
            meta={"profile_url": profile, "raw_count": payload.get("count", 0)},
        )
