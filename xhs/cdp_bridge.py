"""Bridge to redbook-skills CDP for Xiaohongshu discover/crawl."""

from __future__ import annotations

import os
import subprocess
import sys
import time
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

# 进程内登录状态缓存：UI 轮询命中缓存时完全不触碰浏览器，
# 避免状态检测把用户正在看的标签页频繁跳走。
_LOGIN_STATUS_OK_TTL = 300.0
_LOGIN_STATUS_BAD_TTL = 20.0
_login_status_memo: dict[str, tuple[float, bool]] = {}


def _login_memo_key(account: str | None = None, port: int | None = None) -> str:
    return f"{account or ''}@{int(port or DEFAULT_CDP_PORT)}"


def _remember_login_status(logged_in: bool, *, account: str | None = None, port: int | None = None) -> None:
    _login_status_memo[_login_memo_key(account, port)] = (time.time(), bool(logged_in))


def _recall_login_status(account: str | None = None, port: int | None = None) -> bool | None:
    entry = _login_status_memo.get(_login_memo_key(account, port))
    if not entry:
        return None
    at, logged_in = entry
    ttl = _LOGIN_STATUS_OK_TTL if logged_in else _LOGIN_STATUS_BAD_TTL
    if time.time() - at > ttl:
        return None
    return logged_in


def _forget_login_status(account: str | None = None, port: int | None = None) -> None:
    _login_status_memo.pop(_login_memo_key(account, port), None)


class DiscoverLoginRequired(RuntimeError):
    """XHS CDP session not logged in."""


class DiscoverCdpError(RuntimeError):
    pass


def _use_headless(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return os.environ.get("XHS_CDP_HEADLESS", "0").strip().lower() in ("1", "true", "yes")


# 每个 host:port 维护一个「专用自动化标签页」的 targetId。
# 之前 connect(reuse_existing_tab=True) 会挑 /json 列表第一个页面——
# 恰好是用户当前正在看的活跃标签页，任何探测/搜索导航都会把用户页面跳走。
_dedicated_tab_ids: dict[str, str] = {}


def _cdp_http_json(url: str, *, method: str = "GET") -> Any:
    import json as _json
    import urllib.request

    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return _json.loads(resp.read().decode("utf-8"))


def _dedicated_tab_ws_url(host: str, port: int) -> str:
    """Get (or create once) a dedicated automation tab; never touch the user's tab."""
    key = f"{host}:{port}"
    base = f"http://{host}:{port}"
    try:
        targets = _cdp_http_json(f"{base}/json")
    except Exception as exc:  # noqa: BLE001
        raise DiscoverCdpError(f"无法读取 Chrome 调试目标列表: {exc}") from exc

    tab_id = _dedicated_tab_ids.get(key, "")
    entry = None
    if tab_id and isinstance(targets, list):
        entry = next(
            (t for t in targets if t.get("id") == tab_id and t.get("type") == "page"),
            None,
        )
    ws_url = (entry or {}).get("webSocketDebuggerUrl") or ""
    if not ws_url:
        try:
            created = _cdp_http_json(
                f"{base}/json/new?https://www.xiaohongshu.com/explore",
                method="PUT",
            )
        except Exception as exc:  # noqa: BLE001
            raise DiscoverCdpError(f"无法创建自动化专用标签页: {exc}") from exc
        _dedicated_tab_ids[key] = str(created.get("id") or "")
        ws_url = str(created.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise DiscoverCdpError("自动化专用标签页没有可用的调试连接（可能被其他调试器占用）。")
    return ws_url


def _get_publisher(
    *,
    account: str | None = None,
    port: int | None = None,
    host: str | None = None,
    headless: bool | None = None,
):
    if not SCRIPTS_DIR.is_dir():
        raise DiscoverCdpError(
            f"未找到 redbook-skills（{SKILL_ROOT}）。请设置 REDBOOK_SKILLS_ROOT 或安装 skill。"
        )

    import cdp_publish
    from cdp_publish import CDPError, XiaohongshuPublisher
    from chrome_launcher import ensure_chrome

    port = port or DEFAULT_CDP_PORT
    host = host or DEFAULT_CDP_HOST
    use_headless = _use_headless(headless)
    # 采集/搜索默认用有界面 Chrome，与用户登录窗口共用 Cookie 配置
    if not ensure_chrome(port=port, headless=use_headless, account=account):
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
        ws_url = _dedicated_tab_ws_url(host, port)
        publisher.ws = cdp_publish.ws_client.connect(ws_url)
        return publisher
    except CDPError as exc:
        raise DiscoverCdpError(str(exc)) from exc


def _quick_logged_in_signal(publisher: Any, *, allow_navigate: bool = False) -> bool | None:
    """Read login state from __INITIAL_STATE__ without relying on the modal probe.

    比「首页弹窗关键词」检测更稳：站点任何页面的 __INITIAL_STATE__.user.loggedIn
    直接反映会话状态，不会因弹窗渲染时机而误报未登录。

    allow_navigate=False 时绝不改变当前页面（用于被动状态轮询，
    避免用户正在浏览时标签页被强行跳走）。
    """
    try:
        url = publisher._evaluate("window.location.href")
        if not (isinstance(url, str) and "xiaohongshu.com" in url):
            if not allow_navigate:
                return None
            publisher._navigate("https://www.xiaohongshu.com/explore")
        result = publisher._evaluate(
            """
            (() => {
                try {
                    const s = window.__INITIAL_STATE__;
                    if (!s || !s.user) return "unknown";
                    let v = s.user.loggedIn;
                    if (v && typeof v === "object" && "_value" in v) v = v._value;
                    if (v && typeof v === "object" && "_rawValue" in v) v = v._rawValue;
                    if (typeof v === "boolean") return v ? "yes" : "no";
                    return "unknown";
                } catch (e) { return "unknown"; }
            })()
            """
        )
        if result == "yes":
            return True
        if result == "no":
            return False
        return None
    except Exception:  # noqa: BLE001
        return None


def _ensure_session_logged_in(publisher: Any) -> None:
    """Verify login before discover; ignore stale positive cache."""
    memo_kw = {
        "account": getattr(publisher, "account_name", None),
        "port": getattr(publisher, "port", None),
    }
    if _quick_logged_in_signal(publisher, allow_navigate=True) is True:
        _remember_login_status(True, **memo_kw)
        return

    def _modal_probe() -> bool:
        if hasattr(publisher, "_clear_login_cache"):
            publisher._clear_login_cache(scope="home")
        return bool(publisher.check_home_login())

    # 弹窗关键词检测偶发误报（渲染时机），失败后短暂等待重试一次再下结论。
    if _modal_probe():
        _remember_login_status(True, **memo_kw)
        return
    time.sleep(2)
    if _quick_logged_in_signal(publisher, allow_navigate=True) is True or _modal_probe():
        _remember_login_status(True, **memo_kw)
        return
    _remember_login_status(False, **memo_kw)
    raise DiscoverLoginRequired(
        "小红书未登录。请先在 Chrome 窗口完成登录（扫码/手机号），再运行采集。"
    )


def _feed_dedupe_key(raw: dict[str, Any]) -> str:
    if not isinstance(raw, dict):
        return ""
    for key in ("id", "noteId", "note_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text:
                return text
    note_card = raw.get("noteCard") if isinstance(raw.get("noteCard"), dict) else None
    if note_card is None and isinstance(raw.get("note_card"), dict):
        note_card = raw["note_card"]
    if isinstance(note_card, dict):
        for key in ("noteId", "id"):
            value = note_card.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _merge_search_feeds(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    merged = list(existing)
    seen = {_feed_dedupe_key(item) for item in merged}
    seen.discard("")
    added = 0
    for item in incoming:
        if not isinstance(item, dict):
            continue
        key = _feed_dedupe_key(item)
        if key:
            if key in seen:
                continue
            seen.add(key)
        merged.append(item)
        added += 1
    return merged, added


def _scroll_load_search_feeds(
    publisher: Any,
    feeds: list[dict[str, Any]],
    *,
    limit: int,
    max_scrolls: int,
) -> list[dict[str, Any]]:
    """Scroll the search results page to load more feeds into __INITIAL_STATE__."""
    safe_limit = max(1, int(limit or 20))
    safe_scrolls = max(0, min(12, int(max_scrolls or 0)))
    if safe_scrolls <= 0 or len(feeds) >= safe_limit:
        return feeds

    from feed_explorer import FeedExplorer

    explorer = FeedExplorer(publisher._evaluate, publisher._sleep)
    merged = list(feeds)
    stagnant = 0
    for _ in range(safe_scrolls):
        if len(merged) >= safe_limit:
            break
        try:
            publisher._evaluate("window.scrollTo(0, document.body.scrollHeight); true;")
        except Exception:
            break
        try:
            publisher._sleep(1.2, minimum_seconds=0.4)
        except TypeError:
            publisher._sleep(1.2)
        try:
            more = explorer._extract_search_feeds()
        except Exception:
            more = []
        merged, added = _merge_search_feeds(merged, more if isinstance(more, list) else [])
        if added <= 0:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
    return merged


def search_feeds_by_keyword(
    keyword: str,
    *,
    limit: int = 20,
    sort_by: str | None = None,
    note_type: str | None = None,
    account: str | None = None,
    port: int | None = None,
    max_scrolls: int | None = None,
    verify_login: bool = True,
) -> dict[str, Any]:
    from feed_explorer import SearchFilters

    safe_limit = max(1, min(200, int(limit or 20)))
    # ~15-20 cards/screen; scroll a bit past target since dedupe/thresholds
    # will drop a chunk of results. At least 1 scroll even for small limits.
    if max_scrolls is None:
        max_scrolls = min(12, max(1, (safe_limit + 14) // 15))
    else:
        max_scrolls = max(0, min(12, int(max_scrolls)))

    publisher = _get_publisher(account=account, port=port, headless=False)
    try:
        # 一次采集运行只需在开头验证一次登录；上层已验证时跳过，
        # 避免每个关键词/排序轮次都跳回首页做重复判断。
        if verify_login:
            _ensure_session_logged_in(publisher)
        filters = SearchFilters(
            sort_by=sort_by or None,
            note_type=note_type or None,
        )
        result = publisher.search_feeds(keyword=keyword, filters=filters)
        feeds = list(result.get("feeds") or [])
        feeds = _scroll_load_search_feeds(
            publisher,
            feeds,
            limit=safe_limit,
            max_scrolls=max_scrolls,
        )
        if len(feeds) > safe_limit:
            feeds = feeds[:safe_limit]
        return {
            "keyword": keyword,
            "feeds": feeds,
            "recommended_keywords": result.get("recommended_keywords") or [],
            "count": len(feeds),
            "max_scrolls": max_scrolls,
        }
    finally:
        try:
            publisher.disconnect()
        except Exception:
            pass


def list_account_notes(
    *,
    profile_url: str | None = None,
    user_id: str | None = None,
    limit: int = 20,
    max_scrolls: int = 3,
    account: str | None = None,
    port: int | None = None,
    verify_login: bool = True,
) -> dict[str, Any]:
    publisher = _get_publisher(account=account, port=port, headless=False)
    try:
        if verify_login:
            _ensure_session_logged_in(publisher)
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
    finally:
        try:
            publisher.disconnect()
        except Exception:
            pass


def trigger_login_flow(*, port: int | None = None) -> dict[str, Any]:
    """Start redbook-skills login flow in background."""
    # 用户主动去登录了，丢弃缓存的旧状态，登录完成后立刻能读到新状态。
    _forget_login_status(None, port)
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


def login_status(
    *,
    account: str | None = None,
    port: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Check whether current CDP session is logged in.

    force=False（UI 轮询）走被动路径：命中进程内缓存直接返回；
    未命中也只读取当前页面状态，绝不导航，避免用户浏览中的标签页被跳走。
    force=True（点「刷新状态」/ 采集运行开头）才允许导航做完整校验。
    """
    login_port = int(port or DEFAULT_CDP_PORT)
    login_host = DEFAULT_CDP_HOST
    if not force:
        cached = _recall_login_status(account, login_port)
        if cached is not None:
            return {
                "logged_in": cached,
                "reason": "cached" if cached else "not_logged_in",
                "session_reusable": cached,
                "message": "小红书登录状态正常（缓存）" if cached else "小红书未登录，请在 Chrome 窗口完成登录后再采集。",
            }
    if not _cdp_reachable(port=login_port, host=login_host):
        return {
            "logged_in": None,
            "reason": "cdp_unavailable",
            "session_reusable": False,
            "message": "Chrome 调试未连接。请先点击「登录小红书」完成扫码。",
        }
    publisher = None
    try:
        publisher = _get_publisher(account=account, port=login_port, host=login_host, headless=False)
        if not force:
            # 被动探测：只读当前页面，不导航。读不出来就返回未知，
            # 状态交给「刷新状态」按钮或采集运行时的一次性完整校验。
            signal = _quick_logged_in_signal(publisher, allow_navigate=False)
            if signal is None:
                return {
                    "logged_in": None,
                    "reason": "passive_unknown",
                    "session_reusable": True,
                    "message": "未主动探测（避免打断浏览器）。点「刷新状态」或运行采集时会完整校验。",
                }
            _remember_login_status(signal, account=account, port=login_port)
            return {
                "logged_in": signal,
                "reason": "connected" if signal else "not_logged_in",
                "session_reusable": signal,
                "message": "小红书登录状态正常" if signal else "小红书未登录，请在 Chrome 窗口完成登录后再采集。",
            }
        try:
            _ensure_session_logged_in(publisher)
        except DiscoverLoginRequired:
            return {
                "logged_in": False,
                "reason": "not_logged_in",
                "session_reusable": False,
                "message": "小红书未登录，请在 Chrome 窗口完成登录后再采集。",
            }
        return {
            "logged_in": True,
            "reason": "connected",
            "session_reusable": True,
            "message": "小红书登录状态正常",
        }
    except DiscoverLoginRequired as exc:
        return {
            "logged_in": False,
            "reason": "not_logged_in",
            "session_reusable": False,
            "message": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "logged_in": None,
            "reason": "probe_failed",
            "session_reusable": False,
            "message": f"登录状态检测失败: {exc}",
        }
    finally:
        if publisher is not None:
            try:
                publisher.disconnect()
            except Exception:
                pass
