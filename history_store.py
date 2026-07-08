"""Named history snapshots for extraction results."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from result_store import load_results, merge_results, normalize_items, save_results

HISTORY_DIR = Path(__file__).resolve().parent / "output" / "history"
INDEX_FILE = HISTORY_DIR / "index.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_index() -> list[dict[str, Any]]:
    if not INDEX_FILE.exists():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save_index(entries: list[dict[str, Any]]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot_path(snapshot_id: str) -> Path:
    return HISTORY_DIR / f"{snapshot_id}.json"


def list_snapshots() -> list[dict[str, Any]]:
    entries = _load_index()
    result: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda x: x.get("updated_at", ""), reverse=True):
        sid = entry.get("id")
        if not sid:
            continue
        path = _snapshot_path(sid)
        count = entry.get("count", 0)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload.get("results"), list):
                    count = len(payload["results"])
            except (json.JSONDecodeError, OSError):
                pass
        result.append(
            {
                "id": sid,
                "name": entry.get("name") or "未命名存档",
                "created_at": entry.get("created_at", ""),
                "updated_at": entry.get("updated_at", ""),
                "count": count,
            }
        )
    return result


def get_snapshot(snapshot_id: str) -> dict[str, Any]:
    path = _snapshot_path(snapshot_id)
    if not path.exists():
        raise FileNotFoundError("存档不存在")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("存档格式无效")
    return payload


def save_snapshot(name: str, results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = normalize_items(results if results is not None else load_results())
    if not items:
        raise ValueError("没有可存档的内容")

    name = (name or "").strip() or f"存档 {_now()}"
    snapshot_id = uuid.uuid4().hex[:12]
    now = _now()

    payload = {
        "id": snapshot_id,
        "name": name,
        "created_at": now,
        "updated_at": now,
        "results": items,
    }
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    _snapshot_path(snapshot_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    entries = _load_index()
    entries.append(
        {
            "id": snapshot_id,
            "name": name,
            "created_at": now,
            "updated_at": now,
            "count": len(items),
        }
    )
    _save_index(entries)
    return {"id": snapshot_id, "name": name, "count": len(items), "created_at": now}


def delete_snapshot(snapshot_id: str) -> None:
    path = _snapshot_path(snapshot_id)
    if path.exists():
        path.unlink()
    entries = [e for e in _load_index() if e.get("id") != snapshot_id]
    _save_index(entries)


def restore_snapshot(snapshot_id: str, *, mode: str = "replace") -> dict[str, Any]:
    payload = get_snapshot(snapshot_id)
    results = payload.get("results") or []
    if not isinstance(results, list):
        raise ValueError("存档内容无效")

    if mode == "merge":
        merged, stats = merge_results(load_results(), results)
        save_results(merged)
        return {"mode": "merge", "count": len(merged), "merge": stats}

    save_results(results)
    return {"mode": "replace", "count": len(results)}


def rename_snapshot(snapshot_id: str, name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("名称不能为空")

    payload = get_snapshot(snapshot_id)
    payload["name"] = name
    payload["updated_at"] = _now()
    _snapshot_path(snapshot_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    entries = _load_index()
    for entry in entries:
        if entry.get("id") == snapshot_id:
            entry["name"] = name
            entry["updated_at"] = payload["updated_at"]
    _save_index(entries)
    return {"id": snapshot_id, "name": name}
