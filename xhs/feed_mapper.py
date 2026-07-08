"""Map Xiaohongshu CDP feed payloads to discover items."""

from __future__ import annotations

from typing import Any

from core.types import DiscoverItem

try:
    from feed_explorer import make_feed_detail_url
except ImportError:
    def make_feed_detail_url(feed_id: str, xsec_token: str) -> str:
        return f"https://www.xiaohongshu.com/explore/{feed_id}?xsec_token={xsec_token}&xsec_source=pc_feed"


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text:
                return text
    return ""


def feed_to_discover_item(raw: dict[str, Any]) -> DiscoverItem | None:
    """Normalize search feed / profile note dict → DiscoverItem."""
    if not isinstance(raw, dict):
        return None

    feed_id = _first_str(raw.get("id"), raw.get("noteId"), raw.get("note_id"))
    xsec_token = _first_str(raw.get("xsecToken"), raw.get("xsec_token"))

    note_card = raw.get("noteCard") if isinstance(raw.get("noteCard"), dict) else {}
    if not note_card and isinstance(raw.get("note_card"), dict):
        note_card = raw["note_card"]

    if not feed_id:
        feed_id = _first_str(_dig(note_card, "noteId"), _dig(note_card, "id"))

    if not xsec_token:
        xsec_token = _first_str(_dig(note_card, "xsecToken"), _dig(note_card, "xsec_token"))

    url = _first_str(raw.get("note_url"), raw.get("url"))
    if not url and feed_id and xsec_token:
        try:
            url = make_feed_detail_url(feed_id, xsec_token)
        except Exception:
            url = f"https://www.xiaohongshu.com/explore/{feed_id}?xsec_token={xsec_token}&xsec_source=pc_feed"
    if not url:
        return None

    title = _first_str(
        raw.get("title"),
        note_card.get("displayTitle"),
        note_card.get("display_title"),
        note_card.get("title"),
        _dig(note_card, "note", "title"),
    )
    author = _first_str(
        raw.get("author"),
        _dig(note_card, "user", "nickname"),
        _dig(note_card, "user", "nickName"),
    )
    interact = note_card.get("interactInfo") if isinstance(note_card.get("interactInfo"), dict) else {}
    liked = _first_str(
        raw.get("liked_count"),
        interact.get("likedCount"),
        interact.get("liked_count"),
    )
    collected = _first_str(
        raw.get("collected_count"),
        interact.get("collectedCount"),
        interact.get("collected_count"),
    )
    commented = _first_str(
        raw.get("comment_count"),
        interact.get("commentCount"),
        interact.get("comment_count"),
    )
    views = _first_str(
        raw.get("view_count"),
        interact.get("viewCount"),
        interact.get("readCount"),
        interact.get("displayCount"),
    )

    raw_type = _first_str(raw.get("type"), note_card.get("type"), note_card.get("noteType"))
    note_type = "视频" if raw_type.lower() in ("video",) else ("图文" if raw_type else "")

    cover_obj = note_card.get("cover") if isinstance(note_card.get("cover"), dict) else {}
    image_list = note_card.get("imageList") if isinstance(note_card.get("imageList"), list) else []
    first_image = image_list[0] if image_list and isinstance(image_list[0], dict) else {}
    cover_url = _first_str(
        raw.get("cover_url"),
        cover_obj.get("urlDefault"),
        cover_obj.get("url_default"),
        cover_obj.get("url"),
        first_image.get("urlDefault"),
        first_image.get("url_default"),
        first_image.get("url"),
    )

    score_parts: list[str] = []
    if liked:
        score_parts.append(f"赞 {liked}")
    if collected:
        score_parts.append(f"藏 {collected}")
    if commented:
        score_parts.append(f"评 {commented}")
    if views:
        score_parts.append(f"阅 {views}")

    return DiscoverItem(
        url=url,
        title=title,
        score=" · ".join(score_parts),
        meta={
            "feed_id": feed_id,
            "author": author,
            "xsec_token": xsec_token,
            "liked_count": liked,
            "collected_count": collected,
            "comment_count": commented,
            "view_count": views,
            "note_type": note_type,
            "cover_url": cover_url,
        },
    )


def feeds_to_items(feeds: list[Any], *, limit: int) -> list[DiscoverItem]:
    items: list[DiscoverItem] = []
    seen: set[str] = set()
    for raw in feeds:
        item = feed_to_discover_item(raw if isinstance(raw, dict) else {})
        if not item or item.url in seen:
            continue
        seen.add(item.url)
        items.append(item)
        if len(items) >= limit:
            break
    return items
