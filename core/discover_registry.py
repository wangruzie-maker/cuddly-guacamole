"""Plugin registry for link discovery / crawler sources."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.types import DiscoverRequest, DiscoverResult


@runtime_checkable
class DiscoverSource(Protocol):
    """发现链路的插件接口：话题/热搜/账号 → URL 列表 → 再走提取任务。"""

    id: str
    platform: str
    name: str
    description: str

    def discover(self, request: DiscoverRequest) -> DiscoverResult: ...

    def param_schema(self) -> dict[str, Any]:
        """返回前端可展示的参数说明（可选字段）。"""
        ...


_REGISTRY: dict[str, DiscoverSource] = {}


def register(source: DiscoverSource) -> None:
    _REGISTRY[source.id] = source


def get_source(source_id: str) -> DiscoverSource | None:
    return _REGISTRY.get(source_id)


def list_sources(*, platform: str | None = None) -> list[DiscoverSource]:
    items = list(_REGISTRY.values())
    if platform:
        items = [s for s in items if s.platform == platform]
    return items


def list_sources_dict(*, platform: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for src in list_sources(platform=platform):
        out.append(
            {
                "id": src.id,
                "platform": src.platform,
                "name": src.name,
                "description": src.description,
                "param_schema": src.param_schema(),
            }
        )
    return out
