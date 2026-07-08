"""Playwright-based WeChat Channels page extraction."""

from __future__ import annotations

import re
from typing import Any

from channels.fetch_http import resolve_preview_url
from channels.url_parser import parse_channels_url

_NUM_RE = re.compile(r"^\d+$")


def _parse_stats(text_lines: list[str]) -> dict[str, str]:
    """Heuristic: after author line, up to 4 numeric stats = like/comment/share/fav."""
    nums: list[str] = []
    for line in text_lines:
        t = line.strip()
        if _NUM_RE.match(t):
            nums.append(t)
        if len(nums) >= 4:
            break
    keys = ["liked_count", "share_count", "comment_count", "collect_count"]
    return {keys[i]: nums[i] for i in range(min(len(nums), len(keys)))}


def extract_via_playwright(url: str, *, headless: bool = True, profile_dir: str | None = None) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright 未安装，请运行: pip3 install playwright && python3 -m playwright install chromium"
        ) from exc

    parsed = parse_channels_url(url)
    preview_url = resolve_preview_url(url)

    with sync_playwright() as p:
        if profile_dir:
            context = p.chromium.launch_persistent_context(
                profile_dir,
                headless=headless,
                locale="zh-CN",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(locale="zh-CN")
            page = context.new_page()

        try:
            page.goto(preview_url, wait_until="networkidle", timeout=45000)
            page.wait_for_selector(".feed-desc-wrap, .feed-create-time-wrap, .author", timeout=20000)

            desc = page.locator(".feed-desc-wrap").first.inner_text(timeout=5000).strip()
            author = page.locator(".author .nickname, .author .name, .author").first.inner_text(timeout=5000).strip()
            # nickname often nested — prefer smaller text node
            try:
                author = page.locator(".author .nickname").first.inner_text(timeout=2000).strip() or author
            except Exception:
                pass

            create_time = ""
            try:
                create_time = page.locator(".feed-create-time-wrap").first.inner_text(timeout=2000).strip()
            except Exception:
                pass

            location = ""
            try:
                location = page.locator(".feed-location-text").first.inner_text(timeout=2000).strip()
            except Exception:
                pass

            cover_url = page.locator("img.video-player").first.get_attribute("src") or ""
            video_url = ""
            try:
                video_url = page.locator("video source, video").first.get_attribute("src") or ""
            except Exception:
                pass

            body_lines = [ln.strip() for ln in page.locator("body").inner_text().splitlines() if ln.strip()]
            stats = _parse_stats(body_lines)

            title = desc.split("\n")[0][:120] if desc else author

            return {
                "feed_id": parsed.feed_id,
                "url": parsed.original,
                "preview_url": preview_url,
                "title": title,
                "desc": desc,
                "author": author,
                "cover_url": cover_url,
                "video_url": video_url,
                "location": location,
                "create_time": create_time,
                **stats,
            }
        finally:
            context.close()
