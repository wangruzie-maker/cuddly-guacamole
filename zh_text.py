"""Chinese text normalization — Traditional → Simplified."""

from __future__ import annotations

_CONVERTER = None


def _get_converter():
    global _CONVERTER
    if _CONVERTER is not False and _CONVERTER is not None:
        return _CONVERTER
    if _CONVERTER is False:
        return None
    try:
        import zhconv

        _CONVERTER = zhconv.convert
    except ImportError:
        _CONVERTER = False
    return _CONVERTER if _CONVERTER is not False else None


def to_simplified_chinese(text: str) -> str:
    """Convert Chinese text to Simplified (zh-CN). Non-Chinese content unchanged."""
    if not text or not text.strip():
        return text
    convert = _get_converter()
    if not convert:
        return text
    try:
        return convert(text, "zh-cn")
    except Exception:
        return text
