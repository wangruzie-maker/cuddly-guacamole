"""SQLite storage for the Content Intelligence Hub (hot-topic radar + owned-content tracking).

This is intentionally a separate, additive data layer — it does not touch the existing
accumulated.json stores used by the XHS / Channels extraction tabs. It backs the new
"内容情报" tab: watch topics (定时抓热点), the resulting radar items + historical metric
snapshots, and manually tracked "自有内容" posts + their performance history.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "output" / "intel.db"

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_topics (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  platforms TEXT NOT NULL,
  keywords TEXT NOT NULL,
  filters TEXT NOT NULL DEFAULT '{}',
  limit_per_run INTEGER NOT NULL DEFAULT 20,
  interval_minutes INTEGER NOT NULL DEFAULT 360,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_run_at TEXT,
  last_run_message TEXT
);

CREATE TABLE IF NOT EXISTS intel_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  feed_id TEXT DEFAULT '',
  url TEXT NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE,
  title TEXT DEFAULT '',
  author TEXT DEFAULT '',
  note_type TEXT DEFAULT '',
  cover_url TEXT DEFAULT '',
  video_url TEXT DEFAULT '',
  watch_topic_id TEXT,
  keyword TEXT DEFAULT '',
  source_type TEXT DEFAULT 'watch_topic',
  liked_count INTEGER DEFAULT 0,
  collected_count INTEGER DEFAULT 0,
  comment_count INTEGER DEFAULT 0,
  share_count INTEGER DEFAULT 0,
  view_count INTEGER DEFAULT 0,
  hot_score REAL DEFAULT 0,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intel_items_topic ON intel_items(watch_topic_id);
CREATE INDEX IF NOT EXISTS idx_intel_items_hot ON intel_items(hot_score DESC);
CREATE INDEX IF NOT EXISTS idx_intel_items_platform ON intel_items(platform);

CREATE TABLE IF NOT EXISTS metric_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES intel_items(id) ON DELETE CASCADE,
  liked_count INTEGER DEFAULT 0,
  collected_count INTEGER DEFAULT 0,
  comment_count INTEGER DEFAULT 0,
  share_count INTEGER DEFAULT 0,
  view_count INTEGER DEFAULT 0,
  hot_score REAL DEFAULT 0,
  captured_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_item ON metric_snapshots(item_id, captured_at);

CREATE TABLE IF NOT EXISTS tracked_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  account_name TEXT DEFAULT '',
  title TEXT DEFAULT '',
  url TEXT NOT NULL,
  feed_id TEXT DEFAULT '',
  note_type TEXT DEFAULT '',
  published_at TEXT DEFAULT '',
  external_content_id TEXT DEFAULT '',
  external_account_id TEXT DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_refreshed_at TEXT,
  last_error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tracked_metric_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tracked_post_id INTEGER NOT NULL REFERENCES tracked_posts(id) ON DELETE CASCADE,
  liked_count INTEGER DEFAULT 0,
  collected_count INTEGER DEFAULT 0,
  comment_count INTEGER DEFAULT 0,
  share_count INTEGER DEFAULT 0,
  captured_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracked_snapshots_post ON tracked_metric_snapshots(tracked_post_id, captured_at);

-- 选题建议：小红书"相关搜索"接口在选题运行时顺带返回的关联词，跨多次运行累积
-- 命中次数，用于给"围绕已有选题继续挖选题"提供真实数据依据（而不是瞎猜）。
CREATE TABLE IF NOT EXISTS keyword_suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  keyword TEXT NOT NULL,
  source_topic_id TEXT,
  source_keyword TEXT DEFAULT '',
  hit_count INTEGER NOT NULL DEFAULT 1,
  is_tracked INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(platform, keyword)
);
CREATE INDEX IF NOT EXISTS idx_keyword_suggestions_hit ON keyword_suggestions(hit_count DESC);

CREATE TABLE IF NOT EXISTS saved_creative_topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  source_topic_id TEXT DEFAULT '',
  source_batch INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(title, source_topic_id)
);
CREATE INDEX IF NOT EXISTS idx_saved_creative_topics_created
ON saved_creative_topics(created_at DESC);
"""


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def get_conn() -> sqlite3.Connection:
    """Thread-local SQLite connection (sqlite3 connections aren't thread-safe to share).

    Schema init runs once per new connection object (cheap: CREATE TABLE IF NOT EXISTS),
    rather than gated by a single process-wide flag — that would leave freshly-opened
    connections in other threads pointed at an uninitialized/recreated database file.
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(conn)
        _local.conn = conn
    return conn


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
