"""Browser session for WeChat Channels (Playwright persistent profile)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from channels.fetch_playwright import extract_via_playwright
from channels.url_parser import parse_channels_url

PROFILE_DIR = Path(__file__).resolve().parent.parent / "output" / "channels" / "browser_profile"
CDP_PORT = 9333


def login_status() -> dict[str, Any]:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "ready": True,
        "logged_in": PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir()),
        "profile_dir": str(PROFILE_DIR),
        "cdp_port": CDP_PORT,
        "message": "浏览器模式为 Playwright 备用；默认 API 模式无需登录。",
    }


def extract_with_browser(url: str) -> dict[str, Any]:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    parsed = parse_channels_url(url)
    data = extract_via_playwright(url, headless=True, profile_dir=str(PROFILE_DIR))
    data["url"] = parsed.original
    return data
