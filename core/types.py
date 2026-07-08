"""Shared types for multi-platform extractor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PlatformId = Literal["xhs", "channels"]


@dataclass
class DiscoverRequest:
    keyword: str
    limit: int = 20
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoverItem:
    url: str
    title: str = ""
    score: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoverResult:
    source_id: str
    platform: PlatformId
    keyword: str
    items: list[DiscoverItem] = field(default_factory=list)
    message: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def urls(self) -> list[str]:
        return [item.url for item in self.items if item.url]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "platform": self.platform,
            "keyword": self.keyword,
            "message": self.message,
            "meta": self.meta,
            "count": len(self.items),
            "items": [
                {
                    "url": i.url,
                    "title": i.title,
                    "score": i.score,
                    "meta": i.meta,
                }
                for i in self.items
            ],
            "urls": self.urls,
        }
