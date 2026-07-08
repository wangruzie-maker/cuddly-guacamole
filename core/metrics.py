"""Parse XHS-style engagement count strings."""

from __future__ import annotations

import re
from typing import Any

_WAN_RE = re.compile(r"^([\d.]+)\s*万$")
_QIAN_RE = re.compile(r"^([\d.]+)\s*千$")


def parse_count(value: Any) -> int:
    """Parse counts like '1234', '1.2万', '10+' into integers."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)

    text = str(value).strip().replace(",", "").replace("，", "")
    if not text or text in ("-", "—"):
        return 0
    text = text.rstrip("+")

    m = _WAN_RE.match(text)
    if m:
        return int(float(m.group(1)) * 10000)
    m = _QIAN_RE.match(text)
    if m:
        return int(float(m.group(1)) * 1000)

    try:
        return max(int(float(text)), 0)
    except ValueError:
        return 0


def _threshold(extra: dict[str, Any], key: str) -> int | None:
    raw = extra.get(key)
    if raw is None or raw == "":
        return None
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return None
