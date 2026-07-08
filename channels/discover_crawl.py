"""WeChat Channels discover: keyword / account → sph links."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote_plus

import requests

from core.types import DiscoverItem
from core.url_utils import parse_channels_urls, urls_to_items

# 与 setup_playwright.sh / open_app.sh 一致
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/Library/Caches/ms-playwright"))

SPH_LINK_RE = re.compile(
    r"https?://(?:www\.)?weixin\.qq\.com/sph/[A-Za-z0-9_-]+",
    re.IGNORECASE,
)
SPH_ID_RE = re.compile(r"/sph/([A-Za-z0-9_-]+)", re.IGNORECASE)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _unique_sph_urls(text: str, *, limit: int) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in SPH_LINK_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;)]}\"'")
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= limit:
            break

    if len(urls) < limit:
        for match in SPH_ID_RE.finditer(text or ""):
            feed_id = match.group(1)
            url = f"https://weixin.qq.com/sph/{feed_id}"
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= limit:
                break
    return urls


def _to_items(urls: list[str], *, source: str) -> list[DiscoverItem]:
    items: list[DiscoverItem] = []
    for url in urls:
        feed_id = url.rstrip("/").split("/")[-1]
        items.append(
            DiscoverItem(
                url=url,
                title=f"视频号 · {feed_id}",
                meta={"feed_id": feed_id, "source": source},
            )
        )
    return items


def _search_http_sogou(keyword: str, *, limit: int) -> list[DiscoverItem]:
    url = f"https://weixin.sogou.com/weixin?type=2&query={quote_plus(keyword)}&ie=utf8"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=25)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    urls = _unique_sph_urls(resp.text, limit=limit)
    return _to_items(urls, source="sogou_weixin")


def _search_http_bing(keyword: str, *, limit: int) -> list[DiscoverItem]:
    q = quote_plus(f"site:weixin.qq.com/sph {keyword}")
    url = f"https://www.bing.com/search?q={q}&count=30"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=25)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    urls = _unique_sph_urls(resp.text, limit=limit)
    return _to_items(urls, source="bing_http")


def _search_playwright_bing(keyword: str, *, limit: int) -> list[DiscoverItem]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright 未安装。请运行: pip3 install playwright && python3 -m playwright install chromium"
        ) from exc

    query = f"site:weixin.qq.com/sph {keyword}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=DEFAULT_HEADERS["User-Agent"],
            locale="zh-CN",
        )
        page = context.new_page()
        page.goto(
            f"https://www.bing.com/search?q={quote_plus(query)}&count=30",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        page.wait_for_timeout(2500)
        link_blob = page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]'))"
            ".map((a) => a.href).join(' ')"
        )
        html = page.content() + "\n" + str(link_blob or "")
        context.close()
        browser.close()

    urls = _unique_sph_urls(html, limit=limit)
    return _to_items(urls, source="bing_playwright")


def search_by_keyword(keyword: str, *, limit: int = 20) -> tuple[list[DiscoverItem], str, dict[str, Any]]:
    """Keyword search → sph video links."""
    keyword = keyword.strip()
    if not keyword:
        return [], "请填写搜索关键词", {}

    pasted = parse_channels_urls(keyword)
    if pasted:
        items = urls_to_items(pasted[:limit], platform="channels")
        return items, f"从输入中识别 {len(items)} 条视频号链接", {"engine": "pasted_url"}

    engines: list[tuple[str, Any]] = [
        ("bing_playwright", _search_playwright_bing),
        ("sogou_weixin", _search_http_sogou),
        ("bing_http", _search_http_bing),
    ]
    errors: list[str] = []
    for name, fn in engines:
        try:
            items = fn(keyword, limit=limit)
            if items:
                return items, f"通过 {name} 找到 {len(items)} 条视频链接", {"engine": name}
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    msg = "未找到视频链接（可尝试更具体的关键词，或安装 Playwright 提升成功率）"
    if errors:
        msg += f"（{'；'.join(errors[:2])}）"
    return [], msg, {"errors": errors}


def search_account_videos(account: str, *, limit: int = 20) -> tuple[list[DiscoverItem], str, dict[str, Any]]:
    """Search videos from a specific account / competitor."""
    account = account.strip()
    if not account:
        return [], "请填写账号名称或主页链接", {}

    if "weixin.qq.com/sph/" in account:
        return (
            _to_items([account.split()[0]], source="direct_url"),
            "已识别为单条视频链接",
            {},
        )

    query = account if "视频号" in account else f"{account} 视频号"
    items, msg, meta = search_by_keyword(query, limit=limit)
    meta = {**meta, "account_query": query}
    if items:
        return items, f"账号/竞品「{account}」→ {msg}", meta
    return [], f"未找到账号「{account}」相关视频（{msg}）", meta
