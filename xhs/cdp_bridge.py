"""Bridge to redbook-skills CDP for Xiaohongshu discover/crawl."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_raw_root = os.environ.get("REDBOOK_SKILLS_ROOT", "").strip()
SKILL_ROOT = Path(_raw_root) if _raw_root else None
if not SKILL_ROOT or not SKILL_ROOT.is_dir():
    SKILL_ROOT = None
    for candidate in (
        Path(__file__).resolve().parent.parent / ".cursor/skills/redbook-skills",
        Path.home() / ".cursor/skills/redbook-skills",
    ):
        if candidate.is_dir():
            SKILL_ROOT = candidate
            break
if not SKILL_ROOT:
    SKILL_ROOT = Path.home() / ".cursor/skills/redbook-skills"
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

DEFAULT_CDP_PORT = int(os.environ.get("XHS_CDP_PORT", "9222"))
DEFAULT_CDP_HOST = os.environ.get("XHS_CDP_HOST", "127.0.0.1")


class DiscoverLoginRequired(RuntimeError):
    """XHS CDP session not logged in."""


class DiscoverCdpError(RuntimeError):
    pass


def _get_publisher(
    *,
    account: str | None = None,
    port: int | None = None,
    host: str | None = None,
    headless: bool = True,
):
    if not SCRIPTS_DIR.is_dir():
        raise DiscoverCdpError(
            f"未找到 redbook-skills（{SKILL_ROOT}）。请设置 REDBOOK_SKILLS_ROOT 或安装 skill。"
        )

    from cdp_publish import CDPError, XiaohongshuPublisher
    from chrome_launcher import ensure_chrome

    port = port or DEFAULT_CDP_PORT
    host = host or DEFAULT_CDP_HOST
    if not ensure_chrome(port=port, headless=headless, account=account):
        raise DiscoverCdpError(
            f"无法启动 Chrome CDP（port={port}）。请先运行 redbook-skills 登录：\n"
            f"  python3 {SCRIPTS_DIR / 'cdp_publish.py'} --port {port} login"
        )

    publisher = XiaohongshuPublisher(
        host=host,
        port=port,
        account_name=account,
    )
    try:
        publisher.connect(reuse_existing_tab=True)
        if not publisher.check_home_login():
            raise DiscoverLoginRequired(
                "小红书未登录。请先运行：\n"
                f"  python3 {SCRIPTS_DIR / 'cdp_publish.py'} --port {port} login"
            )
        return publisher
    except DiscoverLoginRequired:
        raise
    except CDPError as exc:
        raise DiscoverCdpError(str(exc)) from exc


def search_feeds_by_keyword(
    keyword: str,
    *,
    limit: int = 20,
    sort_by: str | None = None,
    note_type: str | None = None,
    account: str | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    from feed_explorer import SearchFilters

    publisher = _get_publisher(account=account, port=port)
    filters = SearchFilters(
        sort_by=sort_by or None,
        note_type=note_type or None,
    )
    result = publisher.search_feeds(keyword=keyword, filters=filters)
    feeds = result.get("feeds") or []
    if limit and len(feeds) > limit:
        feeds = feeds[:limit]
    return {
        "keyword": keyword,
        "feeds": feeds,
        "recommended_keywords": result.get("recommended_keywords") or [],
        "count": len(feeds),
    }


def list_account_notes(
    *,
    profile_url: str | None = None,
    user_id: str | None = None,
    limit: int = 20,
    max_scrolls: int = 3,
    account: str | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    publisher = _get_publisher(account=account, port=port)
    payload = publisher.list_profile_notes(
        profile_url=profile_url,
        user_id=user_id,
        limit=limit,
        max_scrolls=max_scrolls,
    )
    notes = payload.get("notes") or []
    if limit and len(notes) > limit:
        notes = notes[:limit]
    payload["notes"] = notes
    payload["count"] = len(notes)
    return payload


def trigger_login_flow(*, port: int | None = None) -> dict[str, Any]:
    """Start redbook-skills login flow in background.

    This replaces manual CLI usage:
      python3 ~/.cursor/skills/redbook-skills/scripts/cdp_publish.py --port 9222 login
    """
    if not SCRIPTS_DIR.is_dir():
        raise DiscoverCdpError(
            f"未找到 redbook-skills（{SKILL_ROOT}）。请设置 REDBOOK_SKILLS_ROOT 或安装 skill。"
        )
    login_port = int(port or DEFAULT_CDP_PORT)
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "cdp_publish.py"),
        "--port",
        str(login_port),
        "login",
    ]
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(SCRIPTS_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "started": True,
        "pid": proc.pid,
        "port": login_port,
        "message": "已触发小红书登录流程，请在弹出的 Chrome 窗口内完成登录。",
    }


def _cdp_reachable(*, port: int, host: str) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/json/version", timeout=1.2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def login_status(*, account: str | None = None, port: int | None = None) -> dict[str, Any]:
    """Check whether current CDP session is logged in."""
    login_port = int(port or DEFAULT_CDP_PORT)
    login_host = DEFAULT_CDP_HOST
    if not _cdp_reachable(port=login_port, host=login_host):
        return {
            "logged_in": None,
            "reason": "cdp_unavailable",
            "session_reusable": True,
            "message": "Chrome 调试会话未连接，本机已登录的 Cookie 仍可复用。",
        }
    try:
        publisher = _get_publisher(account=account, port=login_port, host=login_host)
        try:
            publisher.close()
        except Exception:
            pass
        return {"logged_in": True, "reason": "connected", "message": "小红书登录状态正常"}
    except DiscoverLoginRequired as exc:
        return {"logged_in": False, "reason": "not_logged_in", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {
            "logged_in": None,
            "reason": "probe_failed",
            "session_reusable": True,
            "message": f"登录状态检测失败: {exc}",
        }
