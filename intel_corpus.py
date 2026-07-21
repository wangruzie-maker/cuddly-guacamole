"""Local corpus analysis for extracted XHS notes (OCR, captions, and video scripts)."""

from __future__ import annotations

import json
import re
from collections import Counter
from itertools import combinations
from typing import Any

import jieba

from channels import result_store as channels_result_store
from intel_db import get_conn
from result_store import load_results

STOPWORDS = {
    "一个", "一些", "这个", "那个", "我们", "你们", "他们", "自己", "就是", "可以",
    "已经", "没有", "什么", "怎么", "因为", "所以", "但是", "然后", "还是", "非常",
    "真的", "今天", "现在", "如果", "进行", "使用", "需要", "内容", "视频", "小红书",
    "大家", "觉得", "时候", "这样", "以及", "通过", "不是", "很多", "一下", "里面",
    "话题", "直接", "这里", "这些", "其实", "比如说", "ok", "之后", "看到", "还有",
    "打开", "选择", "信息", "操作", "东西", "感觉", "可能", "比较", "知道", "那么",
    "起来", "开始", "完成", "不同", "或者",
}


def _tokens(text: str) -> list[str]:
    words: list[str] = []
    for raw in jieba.lcut(text or ""):
        word = raw.strip().lower()
        if word in STOPWORDS or len(word) < 2:
            continue
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", word):
            continue
        words.append(word)
    return words


def _corpus_text(item: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get(key) or "")
        for key in ("title", "desc", "image_ocr_text", "video_script")
    )


def _allowed_urls(topic_id: str | None) -> set[str] | None:
    if not topic_id:
        return None
    rows = get_conn().execute(
        "SELECT url FROM intel_items WHERE watch_topic_id=?",
        (topic_id,),
    ).fetchall()
    return {str(row["url"]) for row in rows}


def _topic_seed_terms(topic_id: str | None) -> set[str]:
    if not topic_id:
        return set()
    row = get_conn().execute(
        "SELECT name, keywords FROM watch_topics WHERE id=?",
        (topic_id,),
    ).fetchone()
    if not row:
        return set()
    try:
        keywords = json.loads(row["keywords"] or "[]")
    except (json.JSONDecodeError, TypeError):
        keywords = []
    return set(_tokens(" ".join([str(row["name"] or ""), *map(str, keywords)])))


def list_saved_topics(topic_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if topic_id:
        where = "WHERE source_topic_id=?"
        params.append(topic_id)
    params.append(max(1, min(300, limit)))
    rows = get_conn().execute(
        f"""SELECT id, title, source_topic_id, source_batch, created_at
            FROM saved_creative_topics {where}
            ORDER BY created_at DESC, id DESC LIMIT ?""",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def save_creative_topic(title: str, topic_id: str = "", batch: int = 0) -> dict[str, Any]:
    clean_title = re.sub(r"\s+", " ", title or "").strip()
    if not clean_title:
        raise ValueError("选题标题不能为空")
    conn = get_conn()
    conn.execute(
        """INSERT INTO saved_creative_topics(title, source_topic_id, source_batch, created_at)
           VALUES(?,?,?,datetime('now','localtime'))
           ON CONFLICT(title, source_topic_id) DO UPDATE SET
             source_batch=excluded.source_batch""",
        (clean_title, topic_id or "", max(0, int(batch))),
    )
    conn.commit()
    row = conn.execute(
        """SELECT id, title, source_topic_id, source_batch, created_at
           FROM saved_creative_topics WHERE title=? AND source_topic_id=?""",
        (clean_title, topic_id or ""),
    ).fetchone()
    return dict(row)


def delete_saved_topic(topic_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM saved_creative_topics WHERE id=?", (topic_id,))
    conn.commit()


def _corpus_dedupe_key(platform: str, item: dict[str, Any]) -> str:
    feed_id = str(item.get("feed_id") or "").strip()
    if feed_id:
        return f"{platform}:id:{feed_id}"
    return f"{platform}:url:{str(item.get('url') or '').strip()}"


def _url_topic_map() -> dict[str, str]:
    rows = get_conn().execute(
        "SELECT url, watch_topic_id FROM intel_items WHERE url IS NOT NULL AND url != ''"
    ).fetchall()
    mapping: dict[str, str] = {}
    for row in rows:
        url = str(row["url"] or "")
        topic = str(row["watch_topic_id"] or "")
        if url and topic and url not in mapping:
            mapping[url] = topic
    return mapping


def _safe_int_count(value: Any) -> int:
    if value is None or value is False:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    try:
        if text.endswith("万"):
            return int(float(text[:-1]) * 10000)
        if text.endswith("w") or text.endswith("W"):
            return int(float(text[:-1]) * 10000)
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def sync_corpus_from_stores() -> dict[str, int]:
    """Upsert extracted notes from JSON stores into corpus_items."""
    url_topics = _url_topic_map()
    conn = get_conn()
    synced = 0
    sources = [
        ("xhs", load_results()),
        ("channels", channels_result_store.load_results()),
    ]
    for platform, rows in sources:
        for raw in rows:
            url = str(raw.get("url") or "").strip()
            if not url and not str(raw.get("feed_id") or "").strip():
                continue
            key = _corpus_dedupe_key(platform, raw)
            conn.execute(
                """INSERT INTO corpus_items(
                     platform, feed_id, url, dedupe_key, title, author, note_type,
                     desc_text, image_ocr_text, video_script, status, watch_topic_id,
                     liked_count, source_updated_at, synced_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))
                   ON CONFLICT(dedupe_key) DO UPDATE SET
                     feed_id=excluded.feed_id,
                     url=excluded.url,
                     title=excluded.title,
                     author=excluded.author,
                     note_type=excluded.note_type,
                     desc_text=excluded.desc_text,
                     image_ocr_text=excluded.image_ocr_text,
                     video_script=excluded.video_script,
                     status=excluded.status,
                     watch_topic_id=CASE
                       WHEN excluded.watch_topic_id != '' THEN excluded.watch_topic_id
                       ELSE corpus_items.watch_topic_id
                     END,
                     liked_count=excluded.liked_count,
                     source_updated_at=excluded.source_updated_at,
                     synced_at=excluded.synced_at""",
                (
                    platform,
                    str(raw.get("feed_id") or ""),
                    url,
                    key,
                    str(raw.get("title") or ""),
                    str(raw.get("author") or ""),
                    str(raw.get("note_type") or ""),
                    str(raw.get("desc") or ""),
                    str(raw.get("image_ocr_text") or ""),
                    str(raw.get("video_script") or ""),
                    str(raw.get("status") or ""),
                    url_topics.get(url, ""),
                    _safe_int_count(raw.get("liked_count") if raw.get("liked_count") is not None else raw.get("liked")),
                    str(raw.get("updated_at") or raw.get("extracted_at") or ""),
                ),
            )
            synced += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) AS c FROM corpus_items").fetchone()["c"]
    return {"synced": synced, "total": int(total)}


def load_corpus_items(
    *,
    topic_id: str | None = None,
    limit: int = 200,
    only_success: bool = True,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if only_success:
        clauses.append("(status='' OR status='成功')")
    if topic_id:
        clauses.append("watch_topic_id=?")
        params.append(topic_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(500, limit)))
    rows = get_conn().execute(
        f"""SELECT platform, feed_id, url, title, author, note_type,
                   desc_text, image_ocr_text, video_script, status,
                   watch_topic_id, liked_count
            FROM corpus_items {where}
            ORDER BY synced_at DESC, id DESC
            LIMIT ?""",
        params,
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "_platform": row["platform"],
                "feed_id": row["feed_id"],
                "url": row["url"],
                "title": row["title"],
                "author": row["author"],
                "note_type": row["note_type"],
                "desc": row["desc_text"],
                "image_ocr_text": row["image_ocr_text"],
                "video_script": row["video_script"],
                "status": row["status"] or "成功",
                "watch_topic_id": row["watch_topic_id"],
                "liked_count": row["liked_count"],
            }
        )
    return items


def search_corpus(
    query: str,
    *,
    topic_id: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    sync = sync_corpus_from_stores()
    q = re.sub(r"\s+", " ", query or "").strip()
    if not q:
        return {"query": "", "items": [], "sync": sync, "total": 0}
    like = f"%{q}%"
    clauses = [
        "(title LIKE ? OR desc_text LIKE ? OR image_ocr_text LIKE ? OR video_script LIKE ? OR author LIKE ?)"
    ]
    params: list[Any] = [like, like, like, like, like]
    if topic_id:
        clauses.append("watch_topic_id=?")
        params.append(topic_id)
    params.append(max(1, min(100, limit)))
    rows = get_conn().execute(
        f"""SELECT id, platform, url, title, author, note_type,
                   substr(desc_text,1,160) AS desc_preview,
                   length(image_ocr_text) AS ocr_len,
                   length(video_script) AS script_len,
                   liked_count, watch_topic_id
            FROM corpus_items
            WHERE {' AND '.join(clauses)}
            ORDER BY liked_count DESC, id DESC
            LIMIT ?""",
        params,
    ).fetchall()
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "platform": row["platform"],
                "url": row["url"],
                "title": row["title"] or "(无标题)",
                "author": row["author"] or "",
                "note_type": row["note_type"] or "",
                "desc_preview": row["desc_preview"] or "",
                "has_ocr": int(row["ocr_len"] or 0) > 0,
                "has_script": int(row["script_len"] or 0) > 0,
                "liked_count": row["liked_count"] or 0,
                "watch_topic_id": row["watch_topic_id"] or "",
            }
        )
    return {"query": q, "items": items, "total": len(items), "sync": sync}


def _corpus_asset_clauses(
    *,
    q: str = "",
    topic_id: str | None = None,
) -> tuple[str, list[Any], str]:
    clauses: list[str] = ["(status='' OR status='成功')"]
    params: list[Any] = []
    query = re.sub(r"\s+", " ", q or "").strip()
    if query:
        like = f"%{query}%"
        clauses.append(
            "(title LIKE ? OR desc_text LIKE ? OR image_ocr_text LIKE ? OR video_script LIKE ? OR author LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    if topic_id:
        clauses.append("watch_topic_id=?")
        params.append(topic_id)
    where = f"WHERE {' AND '.join(clauses)}"
    return where, params, query


def _row_to_asset(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "platform": row["platform"],
        "url": row["url"],
        "title": row["title"] or "(无标题)",
        "author": row["author"] or "",
        "note_type": row["note_type"] or "",
        "desc_preview": row["desc_preview"] or "",
        "ocr_preview": row["ocr_preview"] or "",
        "script_preview": row["script_preview"] or "",
        "has_ocr": int(row["ocr_len"] or 0) > 0,
        "has_script": int(row["script_len"] or 0) > 0,
        "liked_count": row["liked_count"] or 0,
        "watch_topic_id": row["watch_topic_id"] or "",
        "synced_date": row["synced_date"] or "",
    }


def _topic_name_map() -> dict[str, str]:
    rows = get_conn().execute("SELECT id, name FROM watch_topics").fetchall()
    return {str(row["id"]): str(row["name"] or "") for row in rows}


def list_corpus_assets(
    *,
    q: str = "",
    topic_id: str | None = None,
    limit: int = 40,
    offset: int = 0,
    group_by: str = "topic_date",
) -> dict[str, Any]:
    sync = sync_corpus_from_stores()
    where, params, query = _corpus_asset_clauses(q=q, topic_id=topic_id)
    total = int(
        get_conn().execute(f"SELECT COUNT(*) AS c FROM corpus_items {where}", params).fetchone()["c"]
    )
    group_key = group_by if group_by in ("date", "topic", "type", "topic_date") else "topic_date"
    topic_names = _topic_name_map()
    select_sql = """SELECT id, platform, url, title, author, note_type,
                   substr(desc_text,1,200) AS desc_preview,
                   substr(image_ocr_text,1,120) AS ocr_preview,
                   substr(video_script,1,120) AS script_preview,
                   length(image_ocr_text) AS ocr_len,
                   length(video_script) AS script_len,
                   liked_count, watch_topic_id,
                   substr(synced_at,1,10) AS synced_date
            FROM corpus_items"""

    summary_row = get_conn().execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN length(image_ocr_text)>0 THEN 1 ELSE 0 END) AS with_ocr,
                  SUM(CASE WHEN length(video_script)>0 THEN 1 ELSE 0 END) AS with_script
           FROM corpus_items WHERE status='' OR status='成功'"""
    ).fetchone()
    summary = {
        "total": int(summary_row["total"] or 0),
        "with_ocr": int(summary_row["with_ocr"] or 0),
        "with_script": int(summary_row["with_script"] or 0),
    }

    # Nested topic → date folds: return the full matched set so folds stay intact.
    if group_key == "topic_date":
        rows = get_conn().execute(
            f"""{select_sql} {where}
                ORDER BY watch_topic_id, substr(synced_at,1,10) DESC, liked_count DESC, id DESC
                LIMIT ?""",
            [*params, max(1, min(500, max(limit, total or 1)))],
        ).fetchall()
        items = [_row_to_asset(row) for row in rows]
        for item in items:
            item["topic_name"] = topic_names.get(item["watch_topic_id"], "") or (
                "未关联选题" if not item["watch_topic_id"] else "其他选题"
            )
        nested: dict[str, dict[str, Any]] = {}
        for item in items:
            tid = item["watch_topic_id"] or ""
            if tid not in nested:
                nested[tid] = {
                    "topic_id": tid,
                    "topic_name": item["topic_name"],
                    "count": 0,
                    "dates": {},
                }
            date_key = item["synced_date"] or "未知日期"
            date_bucket = nested[tid]["dates"].setdefault(
                date_key, {"date": date_key, "count": 0, "items": []}
            )
            date_bucket["items"].append(item)
            date_bucket["count"] += 1
            nested[tid]["count"] += 1
        groups = []
        for topic_group in nested.values():
            dates = sorted(
                topic_group["dates"].values(),
                key=lambda d: d["date"] or "",
                reverse=True,
            )
            groups.append(
                {
                    "topic_id": topic_group["topic_id"],
                    "topic_name": topic_group["topic_name"],
                    "count": topic_group["count"],
                    "dates": dates,
                }
            )
        groups.sort(key=lambda g: (-g["count"], g["topic_name"] or ""))
        return {
            "query": query,
            "items": items,
            "groups": groups,
            "total": total,
            "offset": 0,
            "limit": len(items),
            "group_by": group_key,
            "sync": sync,
            "summary": summary,
            "topics": [{"id": k, "name": v} for k, v in topic_names.items()],
        }

    order_sql = {
        "date": "ORDER BY substr(synced_at,1,10) DESC, liked_count DESC, id DESC",
        "topic": "ORDER BY watch_topic_id, substr(synced_at,1,10) DESC, liked_count DESC, id DESC",
        "type": "ORDER BY note_type, substr(synced_at,1,10) DESC, liked_count DESC, id DESC",
    }[group_key]
    page_params = [*params, max(1, min(100, limit)), max(0, offset)]
    rows = get_conn().execute(
        f"{select_sql} {where} {order_sql} LIMIT ? OFFSET ?",
        page_params,
    ).fetchall()
    items = [_row_to_asset(row) for row in rows]
    for item in items:
        item["topic_name"] = topic_names.get(item["watch_topic_id"], "") or (
            "未关联选题" if not item["watch_topic_id"] else "其他选题"
        )
    return {
        "query": query,
        "items": items,
        "groups": [],
        "total": total,
        "offset": offset,
        "limit": limit,
        "group_by": group_key,
        "sync": sync,
        "summary": summary,
        "topics": [{"id": k, "name": v} for k, v in topic_names.items()],
    }


def get_corpus_asset(asset_id: int) -> dict[str, Any] | None:
    row = get_conn().execute(
        """SELECT id, platform, url, title, author, note_type,
                  substr(desc_text,1,200) AS desc_preview,
                  substr(image_ocr_text,1,120) AS ocr_preview,
                  substr(video_script,1,120) AS script_preview,
                  length(image_ocr_text) AS ocr_len,
                  length(video_script) AS script_len,
                  liked_count, watch_topic_id,
                  substr(synced_at,1,10) AS synced_date
           FROM corpus_items WHERE id=?""",
        (asset_id,),
    ).fetchone()
    if not row:
        return None
    item = _row_to_asset(row)
    names = _topic_name_map()
    item["topic_name"] = names.get(item["watch_topic_id"], "") or (
        "未关联选题" if not item["watch_topic_id"] else "其他选题"
    )
    return item


def update_corpus_asset(
    asset_id: int,
    *,
    title: str | None = None,
    author: str | None = None,
    watch_topic_id: str | None = None,
) -> dict[str, Any]:
    row = get_conn().execute("SELECT id FROM corpus_items WHERE id=?", (asset_id,)).fetchone()
    if not row:
        raise ValueError("语料不存在")
    sets: list[str] = []
    params: list[Any] = []
    if title is not None:
        clean = re.sub(r"\s+", " ", title).strip()
        if not clean:
            raise ValueError("标题不能为空")
        sets.append("title=?")
        params.append(clean[:200])
    if author is not None:
        sets.append("author=?")
        params.append(re.sub(r"\s+", " ", author).strip()[:120])
    if watch_topic_id is not None:
        topic = str(watch_topic_id).strip()
        if topic:
            exists = get_conn().execute(
                "SELECT id FROM watch_topics WHERE id=?", (topic,)
            ).fetchone()
            if not exists:
                raise ValueError("所属选题不存在")
        sets.append("watch_topic_id=?")
        params.append(topic)
    if not sets:
        raise ValueError("没有可更新的字段")
    params.append(asset_id)
    conn = get_conn()
    conn.execute(f"UPDATE corpus_items SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    item = get_corpus_asset(asset_id)
    if not item:
        raise ValueError("语料不存在")
    return item


def delete_corpus_asset(asset_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM corpus_items WHERE id=?", (asset_id,))
    conn.commit()
    return cur.rowcount > 0


def delete_corpus_assets(asset_ids: list[int]) -> dict[str, Any]:
    ids = sorted({int(x) for x in asset_ids if int(x) > 0})
    if not ids:
        return {"ok": True, "deleted": 0}
    conn = get_conn()
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(f"DELETE FROM corpus_items WHERE id IN ({placeholders})", ids)
    conn.commit()
    return {"ok": True, "deleted": int(cur.rowcount or 0)}


def add_corpus_asset_from_url(
    url: str,
    *,
    platform: str = "xhs",
    watch_topic_id: str = "",
) -> dict[str, Any]:
    clean_url = re.sub(r"\s+", "", url or "").strip()
    if not clean_url.startswith("http"):
        raise ValueError("请填写有效链接")
    platform = "channels" if platform == "channels" else "xhs"
    topic = str(watch_topic_id or "").strip()
    if topic:
        exists = get_conn().execute("SELECT id FROM watch_topics WHERE id=?", (topic,)).fetchone()
        if not exists:
            raise ValueError("所属选题不存在")

    if platform == "channels":
        from channels.fetch import extract_one as channels_extract_one

        result = channels_extract_one(clean_url, transcribe_video=False)
        if getattr(result, "status", "") != "成功":
            raise ValueError(getattr(result, "error", None) or "视频号提取失败")
        payload = {
            "platform": "channels",
            "feed_id": getattr(result, "feed_id", "") or "",
            "url": getattr(result, "url", "") or clean_url,
            "title": getattr(result, "title", "") or "",
            "author": getattr(result, "author", "") or "",
            "note_type": "视频",
            "desc": getattr(result, "desc", "") or "",
            "image_ocr_text": "",
            "video_script": getattr(result, "video_script", "") or "",
            "status": "成功",
            "liked_count": getattr(result, "liked_count", 0) or 0,
        }
    else:
        from fetch_extractor import extract_one as xhs_extract_one

        result = xhs_extract_one(clean_url, transcribe_video=False, ocr_images=False)
        if result.status != "成功":
            raise ValueError(result.error or "小红书提取失败")
        payload = {
            "platform": "xhs",
            "feed_id": result.feed_id or "",
            "url": result.url or clean_url,
            "title": result.title or "",
            "author": result.author or "",
            "note_type": result.note_type or "",
            "desc": result.desc or "",
            "image_ocr_text": result.image_ocr_text or "",
            "video_script": result.video_script or "",
            "status": "成功",
            "liked_count": result.liked_count or 0,
        }

    feed_id = str(payload.get("feed_id") or "")
    dedupe_key = f"{platform}:{feed_id}" if feed_id else f"{platform}:url:{payload['url']}"
    conn = get_conn()
    conn.execute(
        """INSERT INTO corpus_items(
             platform, feed_id, url, dedupe_key, title, author, note_type,
             desc_text, image_ocr_text, video_script, status, watch_topic_id,
             liked_count, source_updated_at, synced_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))
           ON CONFLICT(dedupe_key) DO UPDATE SET
             title=excluded.title,
             author=excluded.author,
             note_type=excluded.note_type,
             desc_text=excluded.desc_text,
             image_ocr_text=CASE
               WHEN length(excluded.image_ocr_text)>0 THEN excluded.image_ocr_text
               ELSE corpus_items.image_ocr_text END,
             video_script=CASE
               WHEN length(excluded.video_script)>0 THEN excluded.video_script
               ELSE corpus_items.video_script END,
             status=excluded.status,
             watch_topic_id=CASE
               WHEN excluded.watch_topic_id!='' THEN excluded.watch_topic_id
               ELSE corpus_items.watch_topic_id END,
             liked_count=excluded.liked_count,
             synced_at=excluded.synced_at""",
        (
            platform,
            feed_id,
            payload["url"],
            dedupe_key,
            payload["title"],
            payload["author"],
            payload["note_type"],
            payload["desc"],
            payload["image_ocr_text"],
            payload["video_script"],
            "成功",
            topic,
            _safe_int_count(payload.get("liked_count")),
            "",
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM corpus_items WHERE dedupe_key=?", (dedupe_key,)
    ).fetchone()
    item = get_corpus_asset(int(row["id"])) if row else None
    if not item:
        raise RuntimeError("入库后未能读取语料")
    return item


def _extract_brief_entities(brief: str) -> dict[str, Any]:
    """Parse creative brief into short entities + intent (not paste-whole-brief titles)."""
    text = re.sub(r"\s+", " ", brief or "").strip()
    products: list[str] = []
    for match in re.finditer(
        r"(WorkBuddy|workbuddy|Codex|codex|Claude|claude|Cursor|ChatGPT|百度搭子|搭子|"
        r"秒哒|秒搭|MIAODA|miaoda|DuMate|dumate|"
        r"百度智能云|千帆大模型|千帆|文心一言|文心快码|文心|AppBuilder|"
        r"Agent|agent|DeepSeek|Kimi|豆包|通义|Notion|飞书)",
        text,
        re.I,
    ):
        token = match.group(0)
        normalized = token if any("\u4e00" <= ch <= "\u9fff" for ch in token) else token.lower()
        if normalized == "搭子" and "百度搭子" in text:
            normalized = "百度搭子"
        if normalized not in products:
            products.append(normalized)
    compare = re.split(r"\s*(?:和|与|vs|VS|对比|横评)\s*", text)
    # Only treat split parts as products when there is an explicit compare structure.
    if len(compare) >= 2:
        for part in compare:
            part = re.sub(r"(对比|评测|测评|怎么选|值不值得|推广|种草|能做啥|干什么).*$", "", part).strip()
            if 1 < len(part) <= 16 and part not in products and re.search(r"[\u4e00-\u9fffA-Za-z]", part):
                if part not in ("推广", "选哪个", "一篇", "做", "用"):
                    products.append(part)
    products = [p for p in products if p and p not in ("做设计", "做", "设计")][:4]

    intent = "general"
    scene_hint = ""
    if any(k in text for k in ("对比", "vs", "VS", "横评", "测评", "评测", "区别", "怎么选")):
        intent = "compare"
    elif any(k in text for k in ("能做啥", "能干嘛", "做什么", "能力", "用法")):
        intent = "capability"
    elif any(k in text for k in ("教程", "入门", "怎么用", "安装", "上手")):
        intent = "tutorial"
    elif any(k in text for k in ("避坑", "踩坑", "别买", "劝退")):
        intent = "pitfall"
    elif any(k in text for k in ("推广", "种草", "传播", "获客")):
        intent = "promotion"
    elif re.match(r"^(做|写|画|剪|用|搞).{1,12}$", text) or any(
        k in text for k in ("设计", "周报", "PPT", "办公", "剪辑", "编程", "健身", "减肥", "旅行")
    ):
        intent = "capability"
        scene_hint = re.sub(r"^(做|写|画|剪|用|搞)", "", text).strip() or text

    # If brief is a short scene word without known products, never treat the brief itself as product.
    if not products and text and len(text) <= 8 and not _PRODUCT_SWAP_PATTERN.search(text):
        scene_hint = scene_hint or text
        if intent == "general":
            intent = "capability"

    subject = products[0] if products else ""
    peer = products[1] if len(products) > 1 else ""
    return {
        "intent": intent,
        "products": products,
        "subject": subject,
        "peer": peer,
        "scene_hint": scene_hint,
        "raw": text,
    }


def _pick_scene_term(anchors: list[str], entities: dict[str, Any], offset: int = 0) -> str:
    if entities.get("scene_hint"):
        return str(entities["scene_hint"])
    blocked = {
        str(entities.get("subject") or "").lower(),
        str(entities.get("peer") or "").lower(),
        *[str(p).lower() for p in entities.get("products") or []],
        "ai", "工具", "产品", "生成", "教程", "模型",
        "codex", "workbuddy", "claude", "cursor", "chatgpt", "agent",
        "百度搭子", "搭子", "deepseek", "kimi", "豆包", "通义",
    }
    preferred = ("周报", "Excel", "办公", "文档", "安装", "文件", "代码", "任务", "项目", "表格", "汇报", "写稿", "设计")
    candidates = [
        a for a in anchors
        if a and a.lower() not in blocked and not re.fullmatch(r"[A-Za-z0-9_+.-]{2,}", a)
    ]
    ranked = [a for a in preferred if a in candidates] + [a for a in candidates if a not in preferred]
    if not ranked:
        ranked = list(preferred)
    return ranked[offset % len(ranked)]


_PRODUCT_SWAP_PATTERN = re.compile(
    r"(WorkBuddy|workbuddy|Codex|codex|Claude|claude|Cursor|ChatGPT|百度搭子|"
    r"OpenAI|openai|Claude Code|agent|Agent|DeepSeek|Kimi|豆包|通义)",
    re.I,
)


def _adapt_evidence_title(raw_title: str, entities: dict[str, Any], scene: str) -> str:
    """Rewrite a real viral title toward the creative brief instead of blank templates."""
    title = re.sub(r"\s+", " ", (raw_title or "").strip())
    title = re.sub(r"[#＠@].*$", "", title).strip(" |-·｜")
    if not title:
        return ""
    subject = entities.get("subject") or ""
    peer = entities.get("peer") or ""
    found = list(dict.fromkeys(_PRODUCT_SWAP_PATTERN.findall(title)))
    if not found:
        return ""
    out = title
    if subject:
        out = re.sub(re.escape(found[0]), subject, out, count=1, flags=re.I)
    if peer and len(found) > 1:
        out = re.sub(re.escape(found[1]), peer, out, count=1, flags=re.I)
    if scene and scene not in out and len(out) < 30:
        out = f"{out}｜{scene}"
    return re.sub(r"\s+", " ", out).strip(" ：:")[:42]


def _evidence_relevance(title: str, entities: dict[str, Any], scene: str) -> int:
    text_l = (title or "").lower()
    score = 0
    for p in entities.get("products") or []:
        if str(p).lower() in text_l:
            score += 4
    subject = str(entities.get("subject") or "").lower()
    if subject and subject in text_l:
        score += 3
    if scene and scene.lower() in text_l:
        score += 3
    if _PRODUCT_SWAP_PATTERN.search(title or ""):
        score += 2
    if any(k in text_l for k in ("教程", "入门", "对比", "vs", "实测", "怎么", "周报", "办公", "安装", "设计")):
        score += 2
    if any(k in text_l for k in ("被封", "退款", "智商税", "穷人", "放弃吧", "费用不清")):
        score -= 3
    return score


def _template_fallback_title(angle_id: str, entities: dict[str, Any], scene: str, variant: int) -> tuple[str, str]:
    subject = entities.get("subject") or scene or "选题"
    peer = entities.get("peer") or ""
    templates = {
        "product_compare": [
            (f"{subject} vs {peer or '同类'}：{scene or '办公'}党怎么选", "对照下方「同类产品对比」的决策结构"),
            (f"{subject}换完才懂：以前在{scene or '旧方案'}上浪费什么", "对照下方「同类产品对比」的前后落差写法"),
        ],
        "feature_scene": [
            (f"{subject}做{scene or '周报'}我只留这三步", "对照下方「功能场景化」的人+场景+痛点"),
            (f"{scene or '加班'}场景里，{subject}真正能接手的部分", "对照下方「功能场景化」的具体处境推送逻辑"),
        ],
        "tutorial_entry": [
            (f"零基础跑通{subject}：从安装到第一个{scene or '任务'}", "对照下方「教程入门」的学会意图"),
            (f"{subject}上手顺序别反了：先做这 3 件", "对照下方「教程入门」的门槛降低结构"),
        ],
        "honest_review": [
            (f"一周用{subject}做{scene or '工作'}：留下的只有这些", "对照下方「真实测评」的体验证据"),
            (f"{subject}实测实话：适合谁，不适合谁", "对照下方「真实测评」的去营销感叙事"),
        ],
        "pain_callout": [
            (f"{subject}别先冲：{scene or '新手'}最容易踩的 3 个坑", "对照下方「吐槽避坑」的否定式点击结构"),
            (f"劝你别误会{subject}：边界比卖点更重要", "对照下方「吐槽避坑」的争议讨论结构"),
        ],
        "pain_relief": [
            (f"{scene or '重复劳动'}搞崩时，{subject}怎么救急", "对照下方「痛点解决」的情绪共鸣开篇"),
            (f"再也不用半夜改{scene or '材料'}：{subject}这笔账", "对照下方「痛点解决」的痛点-方案结构"),
        ],
        "tool_combo": [
            (f"{subject}+{peer or '搭档工具'}：{scene or '办公'}少开窗口的搭法", "对照下方「多工具联动」的双流量覆盖"),
            (f"单点用{subject}不够，和{peer or '周边工具'}串起来才完整", "对照下方「多工具联动」的工作流写法"),
        ],
        "list_roundup": [
            (f"{subject}相关{scene or '能力'}清单：先把这 5 项配齐", "对照下方「清单合集」的收藏驱动"),
            (f"围着{subject}怎么配工具？这份够用了", "对照下方「清单合集」的盘点结构"),
        ],
        "decision_guide": [
            (f"{subject}值不值得上？先看你是不是这类人", "对照下方「购买决策」的适合谁判断"),
            (f"团队要推{subject}：给决策者看的 3 点", "对照下方「购买决策」的评估口径"),
        ],
    }
    options = templates.get(angle_id) or templates["feature_scene"]
    return options[variant % len(options)]


_INTENT_ANGLE_ORDER = {
    "compare": ["product_compare", "honest_review", "pain_callout", "decision_guide", "feature_scene", "tool_combo"],
    "capability": ["feature_scene", "honest_review", "list_roundup", "tutorial_entry", "tool_combo", "pain_relief"],
    "tutorial": ["tutorial_entry", "feature_scene", "pain_callout", "honest_review", "list_roundup"],
    "pitfall": ["pain_callout", "honest_review", "decision_guide", "product_compare"],
    "promotion": ["feature_scene", "product_compare", "honest_review", "decision_guide", "pain_relief"],
    "general": ["feature_scene", "tutorial_entry", "honest_review", "product_compare", "pain_callout", "tool_combo"],
}


def _build_suggested_topics(
    *,
    brief: str,
    anchors: list[str],
    structures: list[dict[str, Any]],
    mining_angles: list[dict[str, Any]] | None,
    batch: int,
    count: int = 6,
) -> list[dict[str, Any]]:
    """Evidence-first topics mapped 1:1 onto mining dimensions."""
    del structures
    entities = _extract_brief_entities(brief)
    if not entities.get("subject"):
        toolish = [a for a in anchors if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,20}", a or "")]
        preferred_tools = ("codex", "workbuddy", "claude", "cursor", "chatgpt", "openai")
        toolish = sorted(
            toolish,
            key=lambda x: (0 if x.lower() in preferred_tools else 1, 0 if len(x) > 2 else 1, -len(x)),
        )
        entities["subject"] = (toolish[0] if toolish else (anchors[0] if anchors else "选题"))
        if len(toolish) > 1 and not entities.get("peer"):
            entities["peer"] = toolish[1]
    angle_by_id = {a.get("id"): a for a in (mining_angles or []) if a.get("id")}
    order = list(_INTENT_ANGLE_ORDER.get(entities["intent"], _INTENT_ANGLE_ORDER["general"]))
    ranked_ids = list(order)
    for angle in sorted(mining_angles or [], key=lambda a: -int(a.get("item_count") or 0)):
        aid = angle.get("id")
        if aid and aid not in ranked_ids:
            ranked_ids.append(aid)
    if not ranked_ids:
        ranked_ids = ["feature_scene", "tutorial_entry", "honest_review"]

    batch = max(0, int(batch))
    results: list[dict[str, Any]] = []
    used_titles: set[str] = set()
    used_evidence: set[str] = set()
    start_angle = (batch * 2) % len(ranked_ids)

    for slot in range(count):
        angle_id = ranked_ids[(start_angle + slot) % len(ranked_ids)]
        mining = angle_by_id.get(angle_id) or {}
        scene = _pick_scene_term(anchors, entities, batch * count + slot)
        evidence_rows = [
            {
                "title": ev.get("title") or "",
                "url": ev.get("url") or "",
                "liked_count": ev.get("liked_count") or 0,
                "author": ev.get("author") or "",
            }
            for ev in (mining.get("top_evidence") or [])
            if ev.get("url")
        ]
        ranked_evidence = sorted(
            evidence_rows,
            key=lambda ev: (
                -_evidence_relevance(ev.get("title") or "", entities, scene),
                -int(ev.get("liked_count") or 0),
            ),
        )
        title = ""
        source_title = ""
        for pick in ranked_evidence:
            if pick["url"] in used_evidence:
                continue
            if _evidence_relevance(pick.get("title") or "", entities, scene) < 2:
                continue
            adapted = _adapt_evidence_title(pick.get("title") or "", entities, scene)
            if adapted and adapted not in used_titles:
                title = adapted
                source_title = pick.get("title") or ""
                used_evidence.add(pick["url"])
                break
        if not title or title in used_titles:
            title, _note = _template_fallback_title(angle_id, entities, scene, batch + slot)
            source_title = ""
        if title in used_titles:
            title = f"{title}（角度{slot + 1}）"
        used_titles.add(title)

        angle_name = mining.get("name") or angle_id
        if source_title:
            angle_note = f"依据爆款「{source_title[:28]}」结构改写 → 下方「{angle_name}」"
        else:
            angle_note = f"该维度缺少可直接改写样本 → 下方「{angle_name}」建议先补采"
        opportunity = mining.get("opportunity") or ("covered" if mining.get("item_count") else "high")
        results.append(
            {
                "title": title,
                "angle": angle_note,
                "angle_id": angle_id,
                "angle_name": angle_name,
                "structure": mining.get("description") or "",
                "why_viral": mining.get("mechanism") or "",
                "source_title": source_title,
                "coverage": {
                    "item_count": mining.get("item_count") or 0,
                    "avg_liked": mining.get("avg_liked") or 0,
                    "max_liked": mining.get("max_liked") or 0,
                    "opportunity": opportunity,
                },
                "evidence": evidence_rows[:3],
            }
        )

    try:
        from intel_product import _ANGLE_BY_ID
    except Exception:
        _ANGLE_BY_ID = {}
    for item in results:
        meta = _ANGLE_BY_ID.get(item["angle_id"]) or {}
        if not item.get("angle_name"):
            item["angle_name"] = meta.get("name") or item["angle_id"]
        if not item.get("structure"):
            item["structure"] = meta.get("description") or ""
        if not item.get("why_viral"):
            item["why_viral"] = meta.get("mechanism") or ""
    return results



def analyze_corpus(
    topic_id: str | None = None,
    limit: int = 200,
    batch: int = 0,
    brief: str = "",
) -> dict[str, Any]:
    """Summarize extracted corpus and produce evidence-backed creative topic prompts."""
    sync_info = sync_corpus_from_stores()
    items = load_corpus_items(topic_id=topic_id, limit=limit, only_success=True)
    # Fallback: raw JSON if DB empty (first run / sync miss)
    if not items:
        allowed = _allowed_urls(topic_id)
        combined = [
            {**item, "_platform": "xhs"} for item in load_results()
        ] + [
            {**item, "_platform": "channels"} for item in channels_result_store.load_results()
        ]
        items = [
            item
            for item in combined
            if item.get("status") == "成功"
            and (allowed is None or str(item.get("url") or "") in allowed)
        ][-max(1, min(500, limit)) :]
    else:
        items = items[-max(1, min(500, limit)) :]

    word_counts: Counter[str] = Counter()
    title_counts: Counter[str] = Counter()
    document_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    structure_counts: Counter[str] = Counter()
    previews: list[dict[str, Any]] = []

    for item in items:
        title = str(item.get("title") or "")
        tokens = _tokens(_corpus_text(item))
        title_tokens = _tokens(title)
        word_counts.update(tokens)
        title_counts.update(title_tokens)
        unique = list(dict.fromkeys(tokens))[:30]
        document_counts.update(unique)
        pair_counts.update(tuple(sorted(pair)) for pair in combinations(unique, 2))

        if re.search(r"\d", title):
            structure_counts["数字清单"] += 1
        if any(mark in title for mark in ("？", "?", "怎么", "如何")):
            structure_counts["问题切入"] += 1
        if any(word in title for word in ("对比", "还是", "vs", "VS")):
            structure_counts["对比选择"] += 1
        if any(word in title for word in ("建议", "一定", "千万", "别再", "必看")):
            structure_counts["强提醒"] += 1
        if any(word in title for word in ("实测", "体验", "测评", "用完")):
            structure_counts["真实体验"] += 1

        previews.append(
            {
                "url": item.get("url") or "",
                "title": title or "(无标题)",
                "note_type": item.get("note_type") or "",
                "platform": item.get("_platform") or "xhs",
                "has_ocr": bool(str(item.get("image_ocr_text") or "").strip()),
                "has_script": bool(str(item.get("video_script") or "").strip()),
            }
        )

    seed_terms = _topic_seed_terms(topic_id)
    brief = re.sub(r"\s+", " ", brief or "").strip()[:120]
    brief_terms = set(_tokens(brief))
    suggestion_params: tuple[Any, ...] = ()
    suggestion_where = ""
    if topic_id:
        suggestion_where = "WHERE source_topic_id=?"
        suggestion_params = (topic_id,)
    suggestion_rows = get_conn().execute(
        f"""SELECT keyword, hit_count FROM keyword_suggestions
            {suggestion_where} ORDER BY hit_count DESC LIMIT 80""",
        suggestion_params,
    ).fetchall()
    for row in suggestion_rows:
        related_tokens = list(dict.fromkeys(_tokens(str(row["keyword"] or ""))))
        weight = max(1, int(row["hit_count"] or 1))
        word_counts.update({word: weight for word in related_tokens})
        document_counts.update({word: weight for word in related_tokens})
        for word in related_tokens:
            for seed in seed_terms:
                if word != seed:
                    pair_counts[tuple(sorted((word, seed)))] += weight

    relevance_scores: dict[str, float] = {}
    for word, count in word_counts.items():
        score = float(count) + title_counts[word] * 2.5 + document_counts[word] * 1.2
        if any(word in seed or seed in word for seed in seed_terms):
            score += max(8.0, count * 1.5)
        if any(word in term or term in word for term in brief_terms):
            score += max(12.0, count * 2.0)
        for seed in seed_terms:
            score += pair_counts.get(tuple(sorted((word, seed))), 0) * 2.0
        relevance_scores[word] = score
    ranked_words = sorted(
        word_counts,
        key=lambda word: (relevance_scores.get(word, 0), word_counts[word]),
        reverse=True,
    )[:30]
    top_terms = [
        {
            "term": word,
            "count": word_counts[word],
            "document_count": document_counts[word],
            "relevance": round(relevance_scores[word], 1),
        }
        for word in ranked_words
    ]
    top_term_set = set(ranked_words)
    cooccurrence = [
        {"source": pair[0], "target": pair[1], "count": count}
        for pair, count in pair_counts.most_common()
        if pair[0] in top_term_set and pair[1] in top_term_set and count >= 1
    ][:80]
    cluster_count = min(4, max(1, len(ranked_words) // 7))
    cluster_anchors = ranked_words[:cluster_count]
    pair_weight = {
        tuple(sorted((entry["source"], entry["target"]))): int(entry["count"])
        for entry in cooccurrence
    }
    cluster_terms: dict[int, list[str]] = {index: [] for index in range(cluster_count)}
    for index, word in enumerate(ranked_words):
        if word in cluster_anchors:
            cluster_id = cluster_anchors.index(word)
        else:
            weighted = [
                pair_weight.get(tuple(sorted((word, anchor))), 0)
                for anchor in cluster_anchors
            ]
            cluster_id = weighted.index(max(weighted)) if max(weighted, default=0) > 0 else index % cluster_count
        cluster_terms[cluster_id].append(word)
    word_clusters = {
        word: cluster_id
        for cluster_id, words in cluster_terms.items()
        for word in words
    }
    for item in top_terms:
        item["cluster"] = word_clusters.get(item["term"], 0)
    topic_clusters = [
        {
            "id": cluster_id,
            "label": cluster_anchors[cluster_id],
            "terms": words[:7],
            "total_frequency": sum(word_counts[word] for word in words),
            "insight": f"围绕「{cluster_anchors[cluster_id]}」形成，关联词包括{'、'.join(words[1:5]) or '暂无'}。",
        }
        for cluster_id, words in cluster_terms.items()
        if words
    ]
    structures = [
        {"name": name, "count": count}
        for name, count in structure_counts.most_common()
    ]

    anchors = [entry["term"] for entry in top_terms if entry.get("term")]
    mining_angles: list[dict[str, Any]] = []
    try:
        from intel_product import mine_dimensional_insights

        mining = mine_dimensional_insights(topic_id=topic_id, evidence_limit=5)
        mining_angles = mining.get("angles") or []
    except Exception:
        mining_angles = []
    suggestions = None
    llm_used = False
    llm_error = ""
    topic_miner_meta: dict[str, Any] = {}
    try:
        from topic_miner_framework import build_topic_generation_context, framework_status

        topic_miner_meta = {
            **framework_status(),
            "context_preview": build_topic_generation_context(
                brief=brief,
                anchors=[],
                enable_search=False,
            ).get("system_addendum", "")[:160],
        }
    except Exception as exc:  # noqa: BLE001
        topic_miner_meta = {"skill": "viral-topic-miner", "installed": False, "error": str(exc)}

    # DeepSeek only when user provided a creative brief（按需求生成 / 换一批）
    if str(brief or "").strip():
        try:
            from llm_client import generate_suggested_topics_llm

            suggestions, llm_error = generate_suggested_topics_llm(
                brief=brief,
                anchors=anchors,
                mining_angles=mining_angles,
                batch=max(0, int(batch)),
                count=6,
            )
            if suggestions:
                llm_used = True
                llm_error = ""
        except Exception as exc:  # noqa: BLE001
            llm_error = str(exc)
            print(f"[corpus] llm suggestions unavailable: {exc}", flush=True)
            suggestions = None
    if not suggestions:
        suggestions = _build_suggested_topics(
            brief=brief,
            anchors=anchors,
            structures=structures,
            mining_angles=mining_angles,
            batch=max(0, int(batch)),
            count=6,
        )
        for item in suggestions:
            item.setdefault("topic_miner", "viral-topic-miner")
            item.setdefault("content_preference", "百度搭子/秒哒/热点（弱偏好）")

    return {
        "scope": "topic" if topic_id else "all",
        "topic_id": topic_id,
        "batch": batch,
        "brief": brief,
        "llm_used": llm_used,
        "llm_error": llm_error,
        "topic_miner": topic_miner_meta,
        "corpus_sync": sync_info,
        "summary": {
            "items": len(items),
            "with_ocr": sum(bool(str(item.get("image_ocr_text") or "").strip()) for item in items),
            "with_script": sum(bool(str(item.get("video_script") or "").strip()) for item in items),
            "videos": sum(str(item.get("note_type") or "") == "视频" for item in items),
            "graphics": sum(str(item.get("note_type") or "") == "图文" for item in items),
            "xhs": sum(item.get("_platform") == "xhs" for item in items),
            "channels": sum(item.get("_platform") == "channels" for item in items),
        },
        "top_terms": top_terms,
        "cooccurrence": cooccurrence,
        "topic_clusters": topic_clusters,
        "structures": structures,
        "suggested_topics": suggestions,
        "saved_topics": list_saved_topics(topic_id=topic_id),
        "items": list(reversed(previews[-20:])),
    }
