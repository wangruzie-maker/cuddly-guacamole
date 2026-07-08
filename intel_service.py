"""Content Intelligence Hub — business logic.

Two feature sets, both additive to the existing extractor:

1. 热点雷达 (Hot-topic radar): "watch topics" describe a set of keywords/platforms to
   poll on an interval. Each run calls the existing discover plugins, records every
   result as an `intel_items` row (deduped by platform+feed_id/url) and appends a
   `metric_snapshots` row so trends can be charted over time.
2. 自有内容追踪 (Owned-content tracking): paste a URL for content you published; we
   fetch its current engagement metrics (lightweight, no ASR/OCR) and store a
   `tracked_metric_snapshots` row each time you refresh, so performance over time can
   be charted.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from core.metrics import parse_count
from core.pipeline import run_discover
from intel_db import get_conn, now_str

DEFAULT_LIMIT_PER_RUN = 20


def hot_score(liked: int, collected: int, comment: int, share: int, view: int = 0) -> float:
    return round(liked * 1.0 + collected * 1.5 + comment * 2.0 + share * 2.5 + view * 0.02, 2)


# ---------------------------------------------------------------------------
# Watch topics (CRUD)
# ---------------------------------------------------------------------------


def _topic_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    for key in ("platforms", "keywords", "filters"):
        try:
            d[key] = json.loads(d.get(key) or ("[]" if key != "filters" else "{}"))
        except (TypeError, ValueError):
            d[key] = [] if key != "filters" else {}
    return d


def list_watch_topics() -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM watch_topics ORDER BY created_at DESC").fetchall()
    return [_topic_to_dict(r) for r in rows]


def get_watch_topic(topic_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM watch_topics WHERE id=?", (topic_id,)).fetchone()
    return _topic_to_dict(row) if row else None


def create_watch_topic(
    *,
    name: str,
    platforms: list[str],
    keywords: list[str],
    filters: dict[str, Any] | None = None,
    limit_per_run: int = DEFAULT_LIMIT_PER_RUN,
    interval_minutes: int = 360,
    enabled: bool = True,
) -> dict[str, Any]:
    conn = get_conn()
    topic_id = uuid.uuid4().hex[:12]
    now = now_str()
    conn.execute(
        """INSERT INTO watch_topics
           (id, name, platforms, keywords, filters, limit_per_run, interval_minutes, enabled, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            topic_id,
            name.strip() or "未命名选题",
            json.dumps(platforms or ["xhs"], ensure_ascii=False),
            json.dumps(keywords or [], ensure_ascii=False),
            json.dumps(filters or {}, ensure_ascii=False),
            max(1, min(50, int(limit_per_run or DEFAULT_LIMIT_PER_RUN))),
            max(15, int(interval_minutes or 360)),
            1 if enabled else 0,
            now,
            now,
        ),
    )
    conn.commit()
    return get_watch_topic(topic_id)  # type: ignore[return-value]


def update_watch_topic(topic_id: str, **fields: Any) -> dict[str, Any] | None:
    existing = get_watch_topic(topic_id)
    if not existing:
        return None
    conn = get_conn()
    sets: list[str] = []
    params: list[Any] = []
    simple_fields = ("name", "limit_per_run", "interval_minutes")
    for key in simple_fields:
        if key in fields and fields[key] is not None:
            sets.append(f"{key}=?")
            params.append(fields[key])
    if "enabled" in fields and fields["enabled"] is not None:
        sets.append("enabled=?")
        params.append(1 if fields["enabled"] else 0)
    for key in ("platforms", "keywords", "filters"):
        if key in fields and fields[key] is not None:
            sets.append(f"{key}=?")
            params.append(json.dumps(fields[key], ensure_ascii=False))
    if not sets:
        return existing
    sets.append("updated_at=?")
    params.append(now_str())
    params.append(topic_id)
    conn.execute(f"UPDATE watch_topics SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    return get_watch_topic(topic_id)


def delete_watch_topic(topic_id: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM watch_topics WHERE id=?", (topic_id,))
    conn.commit()
    return cur.rowcount > 0


def _due_topics() -> list[dict[str, Any]]:
    due: list[dict[str, Any]] = []
    for topic in list_watch_topics():
        if not topic.get("enabled"):
            continue
        last = topic.get("last_run_at")
        if not last:
            due.append(topic)
            continue
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            due.append(topic)
            continue
        if datetime.now() >= last_dt + timedelta(minutes=int(topic.get("interval_minutes") or 360)):
            due.append(topic)
    return due


# ---------------------------------------------------------------------------
# Radar items
# ---------------------------------------------------------------------------


def upsert_intel_item(
    *,
    platform: str,
    feed_id: str,
    url: str,
    title: str = "",
    author: str = "",
    note_type: str = "",
    cover_url: str = "",
    video_url: str = "",
    liked: int = 0,
    collected: int = 0,
    comment: int = 0,
    share: int = 0,
    view: int = 0,
    watch_topic_id: str | None = None,
    keyword: str = "",
    source_type: str = "watch_topic",
) -> int:
    conn = get_conn()
    dedupe_key = f"{platform}:{feed_id}" if feed_id else f"{platform}:url:{url}"
    score = hot_score(liked, collected, comment, share, view)
    now = now_str()

    row = conn.execute("SELECT id FROM intel_items WHERE dedupe_key=?", (dedupe_key,)).fetchone()
    if row:
        item_id = int(row["id"])
        # First-attribution: keep the topic/keyword that originally surfaced this note even if a
        # different topic's keyword also matches it later (overlapping topics are common). This
        # keeps per-topic counts stable and avoids orphaning the item if that *other* topic gets
        # deleted afterwards.
        conn.execute(
            """UPDATE intel_items SET
                 title=COALESCE(NULLIF(?, ''), title),
                 author=COALESCE(NULLIF(?, ''), author),
                 note_type=COALESCE(NULLIF(?, ''), note_type),
                 cover_url=COALESCE(NULLIF(?, ''), cover_url),
                 video_url=COALESCE(NULLIF(?, ''), video_url),
                 liked_count=?, collected_count=?, comment_count=?, share_count=?, view_count=?,
                 hot_score=?, last_seen_at=?,
                 watch_topic_id=COALESCE(watch_topic_id, ?),
                 keyword=COALESCE(NULLIF(keyword, ''), ?)
               WHERE id=?""",
            (
                title, author, note_type, cover_url, video_url,
                liked, collected, comment, share, view,
                score, now, watch_topic_id, keyword, item_id,
            ),
        )
    else:
        cur = conn.execute(
            """INSERT INTO intel_items
               (platform, feed_id, url, dedupe_key, title, author, note_type, cover_url, video_url,
                watch_topic_id, keyword, source_type, liked_count, collected_count, comment_count,
                share_count, view_count, hot_score, first_seen_at, last_seen_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                platform, feed_id, url, dedupe_key, title, author, note_type, cover_url, video_url,
                watch_topic_id, keyword, source_type, liked, collected, comment, share, view,
                score, now, now,
            ),
        )
        item_id = int(cur.lastrowid)

    conn.execute(
        """INSERT INTO metric_snapshots
           (item_id, liked_count, collected_count, comment_count, share_count, view_count, hot_score, captured_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (item_id, liked, collected, comment, share, view, score, now),
    )
    conn.commit()
    return item_id


def run_watch_topic(topic_id: str) -> dict[str, Any]:
    topic = get_watch_topic(topic_id)
    if not topic:
        raise ValueError(f"未找到选题: {topic_id}")

    filters = topic.get("filters") or {}
    min_liked = int(filters.get("min_liked") or 0)
    min_collected = int(filters.get("min_collected") or 0)
    min_comments = int(filters.get("min_comments") or 0)
    min_views = int(filters.get("min_views") or 0)
    limit_per_run = int(topic.get("limit_per_run") or DEFAULT_LIMIT_PER_RUN)

    # 多轮采集：同一个关键词换不同排序方式（综合/最新/最多点赞…）各搜一遍。
    # 小红书搜索接口本身不支持翻页，这是在"围绕已有选题多次搜索爆款"上唯一能
    # 扩大覆盖面的办法——不同排序会把不同的爆款内容排到前面。
    sort_rounds = [str(s).strip() for s in (filters.get("sort_rounds") or []) if str(s).strip()]
    if not sort_rounds:
        sort_rounds = [str(filters.get("sort_by") or "").strip()]  # 单轮，兼容旧选题
    note_type_filter = filters.get("note_type") or None
    account = filters.get("account") or None

    added = 0
    updated = 0
    rounds_run = 0
    errors: list[str] = []
    notes: list[str] = []
    seen_keys: set[str] = set()

    for platform in topic.get("platforms") or ["xhs"]:
        source_id = "xhs_search_keyword" if platform == "xhs" else "channels_search_keyword"
        for keyword in topic.get("keywords") or []:
            keyword = str(keyword).strip()
            if not keyword:
                continue
            rounds = sort_rounds if platform == "xhs" else [""]
            for sort_by in rounds:
                extra = (
                    {
                        k: v
                        for k, v in {
                            "sort_by": sort_by or None,
                            "note_type": note_type_filter,
                            "account": account,
                        }.items()
                        if v
                    }
                    if platform == "xhs"
                    else {}
                )
                try:
                    payload = run_discover(source_id, keyword=keyword, limit=limit_per_run, extra=extra)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"[{platform}/{keyword}/{sort_by or '默认'}] discover 失败: {exc}")
                    continue
                rounds_run += 1

                items = payload.get("items") or []
                if not items and payload.get("message"):
                    # 发现源本身返回了提示（如「小红书未登录」），这类信息比"新增0条"
                    # 更能说明问题，必须透传给用户，而不是被静默吞掉。
                    notes.append(f"[{platform}/{keyword}] {payload['message']}")

                related = ((payload.get("meta") or {}).get("recommended_keywords")) or []
                if platform == "xhs" and related:
                    record_keyword_suggestions(platform, keyword, topic_id, related)

                for item in items:
                    item_url = str(item.get("url") or "")
                    item_title = str(item.get("title") or "")
                    meta = item.get("meta") or {}
                    if not item_url:
                        continue
                    try:
                        if platform == "xhs":
                            feed_id = str(meta.get("feed_id") or "")
                            liked = parse_count(meta.get("liked_count"))
                            collected = parse_count(meta.get("collected_count"))
                            comment = parse_count(meta.get("comment_count"))
                            view = parse_count(meta.get("view_count"))
                            share = 0
                            if min_liked and liked < min_liked:
                                continue
                            if min_collected and collected < min_collected:
                                continue
                            if min_comments and comment < min_comments:
                                continue
                            if min_views and view < min_views:
                                continue
                            key = f"xhs:{feed_id or item_url}"
                            if key in seen_keys:
                                continue
                            seen_keys.add(key)
                            is_new = _dedupe_missing("xhs", feed_id, item_url)
                            upsert_intel_item(
                                platform="xhs",
                                feed_id=feed_id,
                                url=item_url,
                                title=item_title,
                                author=str(meta.get("author") or ""),
                                note_type=str(meta.get("note_type") or ""),
                                cover_url=str(meta.get("cover_url") or ""),
                                liked=liked,
                                collected=collected,
                                comment=comment,
                                share=share,
                                view=view,
                                watch_topic_id=topic_id,
                                keyword=keyword,
                            )
                        else:
                            from channels.fetch import extract_one as channels_extract_one

                            feed_id = str(meta.get("feed_id") or "")
                            key = f"channels:{feed_id or item_url}"
                            if key in seen_keys:
                                continue
                            seen_keys.add(key)
                            try:
                                ch_result = channels_extract_one(item_url, transcribe_video=False)
                            except Exception as exc:  # noqa: BLE001
                                errors.append(f"[channels/{keyword}] 抓取指标失败 {item_url}: {exc}")
                                continue
                            if ch_result.status != "成功":
                                errors.append(f"[channels/{keyword}] {item_url}: {ch_result.error or '未知错误'}")
                                continue
                            liked = parse_count(ch_result.liked_count)
                            collected = parse_count(ch_result.collect_count)
                            comment = parse_count(ch_result.comment_count)
                            share = parse_count(ch_result.share_count)
                            if min_liked and liked < min_liked:
                                continue
                            if min_collected and collected < min_collected:
                                continue
                            if min_comments and comment < min_comments:
                                continue
                            is_new = _dedupe_missing(
                                "channels", ch_result.feed_id or feed_id, ch_result.url or item_url
                            )
                            upsert_intel_item(
                                platform="channels",
                                feed_id=ch_result.feed_id or feed_id,
                                url=ch_result.url or item_url,
                                title=ch_result.title,
                                author=ch_result.author,
                                note_type="视频",
                                cover_url=ch_result.cover_url,
                                video_url=ch_result.video_url,
                                liked=liked,
                                collected=collected,
                                comment=comment,
                                share=share,
                                watch_topic_id=topic_id,
                                keyword=keyword,
                            )

                        if is_new:
                            added += 1
                        else:
                            updated += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"[{platform}/{keyword}] 处理失败: {exc}")

    message = f"新增 {added} 条，更新 {updated} 条（共 {rounds_run} 轮搜索）"
    if errors:
        message += f"；{len(errors)} 个错误：{errors[0]}"
    elif notes:
        # 没有条目、也没有报错，通常是发现源本身给出的提示（如未登录）——必须让
        # 用户看到，否则「新增0条」看起来像是没有热点，而不是需要先登录。
        message += f"；{notes[0]}"
    conn = get_conn()
    conn.execute(
        "UPDATE watch_topics SET last_run_at=?, last_run_message=? WHERE id=?",
        (now_str(), message[:500], topic_id),
    )
    conn.commit()
    return {
        "topic_id": topic_id,
        "added": added,
        "updated": updated,
        "errors": errors[:10],
        "notes": notes[:10],
        "message": message,
    }


def _dedupe_missing(platform: str, feed_id: str, url: str) -> bool:
    """Return True if this (platform, feed_id/url) is not yet in intel_items (i.e. will be a new insert)."""
    conn = get_conn()
    dedupe_key = f"{platform}:{feed_id}" if feed_id else f"{platform}:url:{url}"
    row = conn.execute("SELECT id FROM intel_items WHERE dedupe_key=?", (dedupe_key,)).fetchone()
    return row is None


def run_due_watch_topics() -> list[dict[str, Any]]:
    results = []
    for topic in _due_topics():
        try:
            results.append(run_watch_topic(topic["id"]))
        except Exception as exc:  # noqa: BLE001
            results.append({"topic_id": topic["id"], "errors": [str(exc)], "message": f"运行失败: {exc}"})
    return results


def list_radar_items(
    *,
    topic_id: str | None = None,
    platform: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conn = get_conn()
    where = []
    params: list[Any] = []
    if topic_id:
        where.append("watch_topic_id=?")
        params.append(topic_id)
    if platform:
        where.append("platform=?")
        params.append(platform)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(500, limit)))
    rows = conn.execute(
        f"SELECT * FROM intel_items {clause} ORDER BY hot_score DESC LIMIT ?", params
    ).fetchall()
    return [dict(r) for r in rows]


def radar_summary(*, topic_id: str | None = None, platform: str | None = None) -> dict[str, Any]:
    conn = get_conn()
    where = []
    params: list[Any] = []
    if topic_id:
        where.append("watch_topic_id=?")
        params.append(topic_id)
    if platform:
        where.append("platform=?")
        params.append(platform)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    top_items = conn.execute(
        f"SELECT * FROM intel_items {clause} ORDER BY hot_score DESC LIMIT 10", params
    ).fetchall()
    platform_counts = conn.execute(
        f"SELECT platform, COUNT(*) as c FROM intel_items {clause} GROUP BY platform", params
    ).fetchall()

    author_where = where + ["author != ''"]
    author_clause = "WHERE " + " AND ".join(author_where)
    top_authors = conn.execute(
        f"""SELECT author, platform, COUNT(*) as cnt, SUM(hot_score) as total_score
            FROM intel_items {author_clause}
            GROUP BY author, platform ORDER BY total_score DESC LIMIT 10""",
        params,
    ).fetchall()

    total = conn.execute(f"SELECT COUNT(*) as c FROM intel_items {clause}", params).fetchone()["c"]

    return {
        "total": total,
        "top_items": [dict(r) for r in top_items],
        "platform_counts": {r["platform"]: r["c"] for r in platform_counts},
        "top_authors": [dict(r) for r in top_authors],
    }


def get_item_history(item_id: int) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM metric_snapshots WHERE item_id=? ORDER BY captured_at ASC", (item_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 选题建议 (keyword / topic suggestions)
#
# Two independent signals, merged at read time:
#   1. "xhs_related" — 小红书搜索接口本身返回的"相关搜索词"，每次选题运行都会
#      顺带拿到，跨多次运行累积命中次数，存进 keyword_suggestions 表。
#   2. "mined"       — 对已抓到的爆款标题做关键词提取（jieba TF-IDF），按热度
#      加权聚合，纯粹从本地已收集数据里挖，不依赖任何额外接口调用。
# ---------------------------------------------------------------------------


def _existing_topic_keywords() -> set[str]:
    conn = get_conn()
    rows = conn.execute("SELECT keywords FROM watch_topics").fetchall()
    out: set[str] = set()
    for r in rows:
        try:
            for kw in json.loads(r["keywords"] or "[]"):
                out.add(str(kw).strip().lower())
        except (TypeError, ValueError):
            continue
    return out


def record_keyword_suggestions(
    platform: str, source_keyword: str, topic_id: str, keywords: list[Any]
) -> None:
    conn = get_conn()
    now = now_str()
    tracked = _existing_topic_keywords()
    for raw_kw in keywords:
        kw = str(raw_kw).strip()
        if not kw or kw.lower() == source_keyword.strip().lower():
            continue
        is_tracked = 1 if kw.lower() in tracked else 0
        conn.execute(
            """INSERT INTO keyword_suggestions
               (platform, keyword, source_topic_id, source_keyword, hit_count, is_tracked,
                first_seen_at, last_seen_at)
               VALUES (?,?,?,?,1,?,?,?)
               ON CONFLICT(platform, keyword) DO UPDATE SET
                 hit_count = hit_count + 1,
                 is_tracked = ?,
                 source_topic_id = excluded.source_topic_id,
                 source_keyword = excluded.source_keyword,
                 last_seen_at = excluded.last_seen_at""",
            (platform, kw, topic_id, source_keyword, is_tracked, now, now, is_tracked),
        )
    conn.commit()


def mine_keyword_suggestions(limit: int = 20, sample_size: int = 300) -> list[dict[str, Any]]:
    """Extract candidate topic keywords from already-collected 爆款 titles.

    Weighted TF-IDF keyword extraction (jieba) over the highest hot_score items,
    aggregated so a phrase that recurs across many different viral posts (not
    just a long single title) ranks higher.
    """
    try:
        import jieba.analyse
    except ImportError:
        return []

    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, hot_score FROM intel_items WHERE title != '' ORDER BY hot_score DESC LIMIT ?",
        (sample_size,),
    ).fetchall()
    if not rows:
        return []

    tracked = _existing_topic_keywords()
    max_score = max((r["hot_score"] or 0) for r in rows) or 1.0
    agg: dict[str, dict[str, Any]] = {}
    stopwords = {"教程", "分享", "推荐", "合集", "干货", "必看", "揭秘", "神器", "测评", "真的"}
    for row in rows:
        title = row["title"]
        weight_factor = 0.4 + 0.6 * ((row["hot_score"] or 0) / max_score)  # 0.4~1.0
        try:
            tags = jieba.analyse.extract_tags(title, topK=6, withWeight=True)
        except Exception:  # noqa: BLE001
            continue
        for word, weight in tags:
            word = word.strip()
            if len(word) < 2 or word.lower() in stopwords or word.isdigit():
                continue
            key = word.lower()
            if key in tracked:
                continue
            bucket = agg.setdefault(key, {"display": word, "score": 0.0, "item_ids": [], "count": 0})
            bucket["score"] += weight * weight_factor
            bucket["count"] += 1
            if len(bucket["item_ids"]) < 6:
                bucket["item_ids"].append(row["id"])

    ranked = sorted(agg.items(), key=lambda kv: kv[1]["score"], reverse=True)
    out = []
    for _key, info in ranked[:limit]:
        if info["count"] < 2:
            continue  # 至少在两条不同爆款里出现过，避免偶然的单篇长尾词
        out.append(
            {
                "keyword": info["display"],
                "platform": "xhs",
                "source": "mined",
                "score": round(info["score"], 3),
                "hit_count": info["count"],
                "sample_item_ids": info["item_ids"],
            }
        )
    return out


def list_keyword_suggestions(limit: int = 30) -> list[dict[str, Any]]:
    conn = get_conn()
    tracked = _existing_topic_keywords()
    related_rows = conn.execute(
        """SELECT * FROM keyword_suggestions WHERE is_tracked=0
           ORDER BY hit_count DESC, last_seen_at DESC LIMIT ?""",
        (limit * 2,),
    ).fetchall()

    merged: dict[str, dict[str, Any]] = {}
    for r in related_rows:
        kw = str(r["keyword"]).strip()
        if not kw or kw.lower() in tracked:
            continue
        merged[kw.lower()] = {
            "keyword": kw,
            "platform": r["platform"],
            "sources": ["xhs_related"],
            "score": float(r["hit_count"]),
            "hit_count": r["hit_count"],
            "source_keyword": r["source_keyword"],
            "source_topic_id": r["source_topic_id"],
            "sample_item_ids": [],
        }

    for m in mine_keyword_suggestions(limit=limit):
        key = m["keyword"].lower()
        if key in merged:
            merged[key]["sources"].append("mined")
            merged[key]["score"] += m["score"]
            merged[key]["sample_item_ids"] = m["sample_item_ids"]
        else:
            merged[key] = {
                "keyword": m["keyword"],
                "platform": m["platform"],
                "sources": ["mined"],
                "score": m["score"],
                "hit_count": m["hit_count"],
                "source_keyword": "",
                "source_topic_id": None,
                "sample_item_ids": m["sample_item_ids"],
            }

    ranked = sorted(merged.values(), key=lambda v: v["score"], reverse=True)[:limit]
    for entry in ranked:
        if not entry["sample_item_ids"]:
            like_rows = conn.execute(
                "SELECT id FROM intel_items WHERE title LIKE ? ORDER BY hot_score DESC LIMIT 6",
                (f"%{entry['keyword']}%",),
            ).fetchall()
            entry["sample_item_ids"] = [r["id"] for r in like_rows]
    return ranked


def get_suggestion_sample_items(item_ids: list[int]) -> list[dict[str, Any]]:
    if not item_ids:
        return []
    conn = get_conn()
    placeholders = ",".join("?" for _ in item_ids)
    rows = conn.execute(
        f"SELECT * FROM intel_items WHERE id IN ({placeholders}) ORDER BY hot_score DESC",
        item_ids,
    ).fetchall()
    return [dict(r) for r in rows]


def promote_suggestion(
    *, keyword: str, platform: str = "xhs", name: str = "", limit_per_run: int = DEFAULT_LIMIT_PER_RUN
) -> dict[str, Any]:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("关键词不能为空")
    topic = create_watch_topic(
        name=name.strip() or keyword,
        platforms=[platform],
        keywords=[keyword],
        limit_per_run=limit_per_run,
    )
    conn = get_conn()
    conn.execute(
        "UPDATE keyword_suggestions SET is_tracked=1 WHERE platform=? AND keyword=?",
        (platform, keyword),
    )
    conn.commit()
    return topic


# ---------------------------------------------------------------------------
# Tracked (owned) posts
# ---------------------------------------------------------------------------


def list_tracked_posts() -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.*,
             (SELECT liked_count FROM tracked_metric_snapshots s WHERE s.tracked_post_id = t.id
              ORDER BY captured_at DESC LIMIT 1) as latest_liked,
             (SELECT collected_count FROM tracked_metric_snapshots s WHERE s.tracked_post_id = t.id
              ORDER BY captured_at DESC LIMIT 1) as latest_collected,
             (SELECT comment_count FROM tracked_metric_snapshots s WHERE s.tracked_post_id = t.id
              ORDER BY captured_at DESC LIMIT 1) as latest_comment,
             (SELECT share_count FROM tracked_metric_snapshots s WHERE s.tracked_post_id = t.id
              ORDER BY captured_at DESC LIMIT 1) as latest_share
           FROM tracked_posts t ORDER BY t.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def _refresh_tracked_row(post: dict[str, Any]) -> dict[str, Any]:
    conn = get_conn()
    platform = post["platform"]
    url = post["url"]
    now = now_str()
    try:
        if platform == "channels":
            from channels.fetch import extract_one as channels_extract_one

            result = channels_extract_one(url, transcribe_video=False)
            if result.status != "成功":
                raise RuntimeError(result.error or "抓取失败")
            liked = parse_count(result.liked_count)
            collected = parse_count(result.collect_count)
            comment = parse_count(result.comment_count)
            share = parse_count(result.share_count)
            title = result.title
            feed_id = result.feed_id
        else:
            from fetch_extractor import extract_one as xhs_extract_one

            result = xhs_extract_one(url, transcribe_video=False, ocr_images=False, cache_images=False)
            liked = parse_count(result.liked_count)
            collected = parse_count(result.collected_count)
            comment = parse_count(result.comment_count)
            share = 0
            title = result.title
            feed_id = result.feed_id

        conn.execute(
            """INSERT INTO tracked_metric_snapshots
               (tracked_post_id, liked_count, collected_count, comment_count, share_count, captured_at)
               VALUES (?,?,?,?,?,?)""",
            (post["id"], liked, collected, comment, share, now),
        )
        conn.execute(
            """UPDATE tracked_posts SET
                 title=COALESCE(NULLIF(?, ''), title), feed_id=COALESCE(NULLIF(?, ''), feed_id),
                 last_refreshed_at=?, last_error=''
               WHERE id=?""",
            (title, feed_id, now, post["id"]),
        )
        conn.commit()
        return {"id": post["id"], "ok": True, "liked": liked, "collected": collected, "comment": comment, "share": share}
    except Exception as exc:  # noqa: BLE001
        conn.execute(
            "UPDATE tracked_posts SET last_refreshed_at=?, last_error=? WHERE id=?",
            (now, str(exc)[:300], post["id"]),
        )
        conn.commit()
        return {"id": post["id"], "ok": False, "error": str(exc)}


def register_tracked_post(
    *, platform: str, url: str, account_name: str = "", title: str = "", published_at: str = ""
) -> dict[str, Any]:
    conn = get_conn()
    now = now_str()
    cur = conn.execute(
        """INSERT INTO tracked_posts
           (platform, account_name, title, url, published_at, created_at)
           VALUES (?,?,?,?,?,?)""",
        (platform, account_name.strip(), title.strip(), url.strip(), published_at.strip(), now),
    )
    conn.commit()
    post_id = int(cur.lastrowid)
    post = conn.execute("SELECT * FROM tracked_posts WHERE id=?", (post_id,)).fetchone()
    _refresh_tracked_row(dict(post))
    return get_tracked_post_with_metrics(post_id)  # type: ignore[return-value]


def get_tracked_post(post_id: int) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM tracked_posts WHERE id=?", (post_id,)).fetchone()
    return dict(row) if row else None


def get_tracked_post_with_metrics(post_id: int) -> dict[str, Any] | None:
    """Same shape as list_tracked_posts() rows (includes latest_* fields), for a single post.

    Used by the create/refresh API responses so the frontend can show immediate,
    concrete feedback (current counts or the error) without a second round trip.
    """
    conn = get_conn()
    row = conn.execute(
        """SELECT t.*,
             (SELECT liked_count FROM tracked_metric_snapshots s WHERE s.tracked_post_id = t.id
              ORDER BY captured_at DESC LIMIT 1) as latest_liked,
             (SELECT collected_count FROM tracked_metric_snapshots s WHERE s.tracked_post_id = t.id
              ORDER BY captured_at DESC LIMIT 1) as latest_collected,
             (SELECT comment_count FROM tracked_metric_snapshots s WHERE s.tracked_post_id = t.id
              ORDER BY captured_at DESC LIMIT 1) as latest_comment,
             (SELECT share_count FROM tracked_metric_snapshots s WHERE s.tracked_post_id = t.id
              ORDER BY captured_at DESC LIMIT 1) as latest_share
           FROM tracked_posts t WHERE t.id=?""",
        (post_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_tracked_post(post_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM tracked_posts WHERE id=?", (post_id,))
    conn.commit()
    return cur.rowcount > 0


def refresh_tracked_post(post_id: int) -> dict[str, Any]:
    post = get_tracked_post(post_id)
    if not post:
        raise ValueError(f"未找到追踪内容: {post_id}")
    _refresh_tracked_row(post)
    return get_tracked_post_with_metrics(post_id)  # type: ignore[return-value]


def refresh_all_tracked_posts() -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tracked_posts WHERE enabled=1").fetchall()
    return [_refresh_tracked_row(dict(r)) for r in rows]


def get_tracked_history(post_id: int) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM tracked_metric_snapshots WHERE tracked_post_id=? ORDER BY captured_at ASC",
        (post_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 数据分析 (analytics) — 围绕单个选题的深度分析，以及全部选题的横向对比总览。
# 这里只做本地聚合查询，不额外请求任何外部接口。
# ---------------------------------------------------------------------------


def topic_analytics(topic_id: str) -> dict[str, Any]:
    topic = get_watch_topic(topic_id)
    if not topic:
        raise ValueError(f"未找到选题: {topic_id}")
    conn = get_conn()

    summary_row = conn.execute(
        """SELECT COUNT(*) as cnt, AVG(liked_count) as avg_liked, AVG(collected_count) as avg_collected,
                  AVG(comment_count) as avg_comment, AVG(view_count) as avg_view, AVG(hot_score) as avg_hot,
                  MAX(liked_count) as max_liked, MAX(hot_score) as max_hot
           FROM intel_items WHERE watch_topic_id=?""",
        (topic_id,),
    ).fetchone()

    note_type_rows = conn.execute(
        """SELECT COALESCE(NULLIF(note_type, ''), '未知') as note_type, COUNT(*) as cnt
           FROM intel_items WHERE watch_topic_id=? GROUP BY note_type""",
        (topic_id,),
    ).fetchall()

    top_authors = conn.execute(
        """SELECT author, COUNT(*) as cnt, SUM(hot_score) as total_score, AVG(hot_score) as avg_score
           FROM intel_items WHERE watch_topic_id=? AND author != ''
           GROUP BY author ORDER BY total_score DESC LIMIT 10""",
        (topic_id,),
    ).fetchall()

    top_items = conn.execute(
        "SELECT * FROM intel_items WHERE watch_topic_id=? ORDER BY hot_score DESC LIMIT 12",
        (topic_id,),
    ).fetchall()

    daily_trend = conn.execute(
        """SELECT substr(captured_at, 1, 10) as day, AVG(hot_score) as avg_hot, COUNT(*) as cnt
           FROM metric_snapshots
           WHERE item_id IN (SELECT id FROM intel_items WHERE watch_topic_id=?)
           GROUP BY day ORDER BY day ASC""",
        (topic_id,),
    ).fetchall()

    keyword_breakdown = conn.execute(
        """SELECT keyword, COUNT(*) as cnt, AVG(hot_score) as avg_hot
           FROM intel_items WHERE watch_topic_id=? GROUP BY keyword ORDER BY cnt DESC""",
        (topic_id,),
    ).fetchall()

    return {
        "topic": topic,
        "summary": dict(summary_row) if summary_row else {},
        "note_type_breakdown": [dict(r) for r in note_type_rows],
        "top_authors": [dict(r) for r in top_authors],
        "top_items": [dict(r) for r in top_items],
        "daily_trend": [dict(r) for r in daily_trend],
        "keyword_breakdown": [dict(r) for r in keyword_breakdown],
    }


def cross_topic_overview() -> dict[str, Any]:
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.id, t.name, t.platforms, t.enabled, t.last_run_at, t.last_run_message,
                  COUNT(i.id) as item_count,
                  AVG(i.hot_score) as avg_hot_score,
                  MAX(i.hot_score) as max_hot_score,
                  SUM(CASE WHEN i.note_type='视频' THEN 1 ELSE 0 END) as video_count
           FROM watch_topics t
           LEFT JOIN intel_items i ON i.watch_topic_id = t.id
           GROUP BY t.id
           ORDER BY (avg_hot_score IS NULL) ASC, avg_hot_score DESC"""
    ).fetchall()
    topics = []
    for r in rows:
        d = dict(r)
        try:
            d["platforms"] = json.loads(d.get("platforms") or "[]")
        except (TypeError, ValueError):
            d["platforms"] = []
        topics.append(d)

    total_items = conn.execute("SELECT COUNT(*) as c FROM intel_items").fetchone()["c"]
    # Same merged (xhs_related + mined) list the "选题建议" panel shows, so this stat card
    # never looks inconsistent with what the user sees just above it.
    total_suggestions = len(list_keyword_suggestions(limit=100))
    total_tracked_posts = conn.execute("SELECT COUNT(*) as c FROM tracked_posts").fetchone()["c"]

    return {
        "topics": topics,
        "total_items": total_items,
        "total_suggestions": total_suggestions,
        "total_tracked_posts": total_tracked_posts,
    }
