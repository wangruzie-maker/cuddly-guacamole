#!/usr/bin/env python3
"""
从小红书链接提取标题、文案、图片/视频素材，并写入 CSV 表格。

依赖 redbook-skills（Chrome CDP + 小红书登录态）。

用法:
  python extract_notes.py "https://www.xiaohongshu.com/explore/xxx?xsec_token=..."
  python extract_notes.py --urls-file links.txt --download --csv ./output/notes.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

def _resolve_skill_root() -> Path:
    env = (os.environ.get("REDBOOK_SKILLS_ROOT") or "").strip()
    if env and Path(env).is_dir():
        return Path(env)
    project = Path(__file__).resolve().parent
    for candidate in (
        project / "vendor" / "redbook-skills",
        project / ".cursor" / "skills" / "redbook-skills",
        Path.home() / ".cursor" / "skills" / "redbook-skills",
    ):
        if candidate.is_dir() and (candidate / "scripts" / "cdp_publish.py").is_file():
            return candidate
    return project / "vendor" / "redbook-skills"


SKILL_ROOT = _resolve_skill_root()
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if SCRIPTS_DIR.is_dir() and str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cdp_publish import CDPError, XiaohongshuPublisher  # noqa: E402
from feed_explorer import FeedExplorer, make_feed_detail_url  # noqa: E402
from image_downloader import ImageDownloader  # noqa: E402

NOTE_ID_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-zA-Z]{24})")
DEFAULT_CSV = Path(__file__).resolve().parent / "output" / "notes.csv"
DEFAULT_MEDIA_DIR = Path(__file__).resolve().parent / "output" / "media"

CSV_COLUMNS = [
    "链接",
    "笔记ID",
    "类型",
    "标题",
    "文案",
    "视频脚本",
    "图片URLs",
    "视频URL",
    "本地图片路径",
    "本地视频路径",
    "作者",
    "点赞数",
    "收藏数",
    "评论数",
    "提取时间",
    "状态",
    "错误信息",
]


@dataclass
class ParsedUrl:
    original: str
    final_url: str
    feed_id: str
    xsec_token: str


@dataclass
class ExtractedNote:
    feed_id: str
    note_type: str = ""
    title: str = ""
    desc: str = ""
    image_urls: list[str] = field(default_factory=list)
    video_url: str = ""
    author: str = ""
    liked_count: str = ""
    collected_count: str = ""
    comment_count: str = ""


def resolve_short_url(url: str, timeout: int = 15) -> str:
    """Follow redirects for xhslink.com and similar short links."""
    parsed = urlparse(url)
    if parsed.netloc and "xiaohongshu.com" in parsed.netloc:
        return url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, allow_redirects=True, timeout=timeout, headers=headers)
    resp.raise_for_status()
    return resp.url


def parse_xhs_url(url: str) -> ParsedUrl:
    """Parse note id and xsec_token from a Xiaohongshu URL."""
    final_url = resolve_short_url(url.strip())
    parsed = urlparse(final_url)
    match = NOTE_ID_RE.search(unquote(parsed.path))
    if not match:
        raise ValueError(f"无法从链接解析笔记 ID: {url}")

    feed_id = match.group(1)
    query = parse_qs(parsed.query)
    token = (query.get("xsec_token") or query.get("xsecToken") or [""])[0]
    return ParsedUrl(original=url.strip(), final_url=final_url, feed_id=feed_id, xsec_token=token)


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return ""


def _dig(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _extract_video_url(video_obj: Any) -> str:
    if not isinstance(video_obj, dict):
        return ""

    stream = _dig(video_obj, "media", "stream") or _dig(video_obj, "stream")
    if isinstance(stream, dict):
        for codec in ("h264", "h265", "av1", "hevc"):
            tracks = stream.get(codec)
            if not isinstance(tracks, list):
                continue
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                url = _first_str(track.get("masterUrl"), track.get("master_url"))
                if url:
                    return url
                backups = track.get("backupUrls") or track.get("backup_urls") or []
                if isinstance(backups, list) and backups:
                    backup = _first_str(backups[0])
                    if backup:
                        return backup

    for key in ("url", "videoUrl", "video_url", "masterUrl", "master_url"):
        url = _first_str(video_obj.get(key))
        if url:
            return url

    consumer = video_obj.get("consumer")
    if isinstance(consumer, dict):
        for key in ("originVideoKey", "origin_video_key"):
            val = _first_str(consumer.get(key))
            if val.startswith("http"):
                return val

    return ""


from image_urls import collect_urls_from_note_item, dedupe_image_urls


def _extract_image_urls(note: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for item in note.get("imageList") or note.get("images") or []:
        if isinstance(item, str):
            urls.append(item)
            continue
        if isinstance(item, dict):
            urls.extend(collect_urls_from_note_item(item))
    return dedupe_image_urls(urls)


def extract_from_detail(detail: dict[str, Any]) -> ExtractedNote:
    """Normalize noteDetailMap payload into flat fields."""
    note = detail.get("note") if isinstance(detail.get("note"), dict) else detail
    if not isinstance(note, dict):
        raise ValueError("笔记详情结构无法识别")

    feed_id = _first_str(note.get("noteId"), note.get("note_id"), note.get("id"))
    note_type_raw = _first_str(note.get("type"), note.get("noteType"), note.get("note_type"))
    is_video = note_type_raw.lower() == "video" or bool(note.get("video"))

    title = _first_str(note.get("title"), note.get("displayTitle"), note.get("display_title"))
    desc = _first_str(note.get("desc"), note.get("description"), note.get("content"))

    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    author = _first_str(user.get("nickname"), user.get("nickName"), user.get("name"))

    interact = note.get("interactInfo") or note.get("interact_info") or {}
    if not isinstance(interact, dict):
        interact = {}

    return ExtractedNote(
        feed_id=feed_id,
        note_type="视频" if is_video else "图文",
        title=title,
        desc=desc,
        image_urls=_extract_image_urls(note),
        video_url=_extract_video_url(note.get("video")),
        author=author,
        liked_count=_first_str(interact.get("likedCount"), interact.get("liked_count")),
        collected_count=_first_str(interact.get("collectedCount"), interact.get("collected_count")),
        comment_count=_first_str(interact.get("commentCount"), interact.get("comment_count")),
    )


def fetch_note_detail(
    publisher: XiaohongshuPublisher,
    parsed: ParsedUrl,
) -> dict[str, Any]:
    """Open note page via CDP and read noteDetailMap."""
    if parsed.xsec_token:
        target = make_feed_detail_url(parsed.feed_id, parsed.xsec_token)
    else:
        target = f"https://www.xiaohongshu.com/explore/{parsed.feed_id}"

    publisher._navigate(target)
    publisher._sleep(2, minimum_seconds=1.0)
    publisher._check_feed_page_accessible()

    explorer = FeedExplorer(publisher._evaluate, publisher._sleep)
    return explorer.get_feed_detail(parsed.feed_id)


def ensure_chrome(port: int) -> None:
    try:
        requests.get(f"http://127.0.0.1:{port}/json", timeout=3)
        return
    except Exception:
        pass

    from chrome_launcher import ensure_chrome

    ensure_chrome(port=port)


def download_media(
    note: ExtractedNote,
    media_root: Path,
    *,
    download_images: bool,
    download_video: bool,
) -> tuple[list[str], str]:
    media_root.mkdir(parents=True, exist_ok=True)
    note_dir = media_root / (note.feed_id or "unknown")
    note_dir.mkdir(parents=True, exist_ok=True)

    local_images: list[str] = []
    local_video = ""

    referer = "https://www.xiaohongshu.com/"
    downloader = ImageDownloader(temp_dir=str(note_dir))

    if download_images and note.image_urls:
        for idx, url in enumerate(note.image_urls, start=1):
            try:
                path = downloader.download(url, referer=referer)
                target = note_dir / f"image_{idx:02d}{Path(path).suffix}"
                if Path(path).resolve() != target.resolve():
                    Path(path).rename(target)
                local_images.append(str(target.resolve()))
            except Exception as exc:
                print(f"[extract] 图片下载失败 {url}: {exc}", file=sys.stderr)

    if download_video and note.video_url:
        try:
            path = downloader.download_video(note.video_url, referer=referer)
            target = note_dir / f"video{Path(path).suffix}"
            if Path(path).resolve() != target.resolve():
                Path(path).rename(target)
            local_video = str(target.resolve())
        except Exception as exc:
            print(f"[extract] 视频下载失败 {note.video_url}: {exc}", file=sys.stderr)

    downloader._owns_dir = False
    return local_images, local_video


def append_csv_row(csv_path: Path, row: dict[str, str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists()
    with csv_path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def build_row(
    parsed: ParsedUrl,
    note: ExtractedNote | None,
    *,
    status: str,
    error: str = "",
    local_images: list[str] | None = None,
    local_video: str = "",
) -> dict[str, str]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if note is None:
        note = ExtractedNote(feed_id=parsed.feed_id)

    script_text = note.desc if note.note_type == "视频" else ""

    return {
        "链接": parsed.original,
        "笔记ID": note.feed_id or parsed.feed_id,
        "类型": note.note_type,
        "标题": note.title,
        "文案": note.desc,
        "视频脚本": script_text,
        "图片URLs": " | ".join(note.image_urls),
        "视频URL": note.video_url,
        "本地图片路径": " | ".join(local_images or []),
        "本地视频路径": local_video,
        "作者": note.author,
        "点赞数": note.liked_count,
        "收藏数": note.collected_count,
        "评论数": note.comment_count,
        "提取时间": now,
        "状态": status,
        "错误信息": error,
    }


def process_urls(
    urls: list[str],
    *,
    csv_path: Path,
    media_dir: Path,
    download: bool,
    download_video: bool,
    host: str,
    port: int,
    account: str | None,
    delay: float,
) -> list[dict[str, str]]:
    ensure_chrome(port)

    publisher = XiaohongshuPublisher(host=host, port=port, account_name=account)
    publisher.connect(reuse_existing_tab=True)

    if not publisher.check_home_login():
        print("未登录小红书。请先运行:", file=sys.stderr)
        print(f'  python3 "{SCRIPTS_DIR}/cdp_publish.py" login', file=sys.stderr)
        sys.exit(1)

    results: list[dict[str, str]] = []

    for index, url in enumerate(urls, start=1):
        url = url.strip()
        if not url or url.startswith("#"):
            continue

        print(f"\n[extract] ({index}/{len(urls)}) {url}")
        parsed: ParsedUrl | None = None
        try:
            parsed = parse_xhs_url(url)
            detail = fetch_note_detail(publisher, parsed)
            note = extract_from_detail(detail)

            local_images: list[str] = []
            local_video = ""
            if download:
                local_images, local_video = download_media(
                    note,
                    media_dir,
                    download_images=True,
                    download_video=download_video,
                )

            row = build_row(
                parsed,
                note,
                status="成功",
                local_images=local_images,
                local_video=local_video,
            )
            print(f"[extract] OK: {note.title[:40] or note.feed_id} ({note.note_type})")
        except Exception as exc:
            parsed = parsed or ParsedUrl(original=url, final_url=url, feed_id="", xsec_token="")
            row = build_row(parsed, None, status="失败", error=str(exc))
            print(f"[extract] FAIL: {exc}", file=sys.stderr)

        append_csv_row(csv_path, row)
        results.append(row)

        if index < len(urls) and delay > 0:
            time.sleep(delay)

    return results


def load_urls_from_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def main() -> None:
    parser = argparse.ArgumentParser(description="从小红书链接提取笔记内容并写入 CSV")
    parser.add_argument("urls", nargs="*", help="小红书笔记链接（可多个）")
    parser.add_argument("--urls-file", help="从文本文件读取链接，一行一个")
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help=f"输出 CSV 路径（默认 {DEFAULT_CSV}）",
    )
    parser.add_argument(
        "--media-dir",
        default=str(DEFAULT_MEDIA_DIR),
        help=f"素材下载目录（默认 {DEFAULT_MEDIA_DIR}）",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="下载图片到本地（默认只记录 URL）",
    )
    parser.add_argument(
        "--download-video",
        action="store_true",
        help="同时下载视频（需配合 --download）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Chrome CDP host")
    parser.add_argument("--port", type=int, default=9222, help="Chrome CDP port")
    parser.add_argument("--account", default=None, help="redbook-skills 账号名")
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="批量提取时每条链接之间的间隔秒数",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="提取完成后打印 JSON 摘要",
    )
    args = parser.parse_args()

    urls = list(args.urls)
    if args.urls_file:
        urls.extend(load_urls_from_file(Path(args.urls_file)))

    urls = [u for u in urls if u.strip()]
    if not urls:
        parser.error("请提供至少一个小红书链接，或使用 --urls-file")

    csv_path = Path(args.csv).expanduser().resolve()
    media_dir = Path(args.media_dir).expanduser().resolve()

    print(f"[extract] 共 {len(urls)} 条链接")
    print(f"[extract] CSV 输出: {csv_path}")
    if args.download:
        print(f"[extract] 素材目录: {media_dir}")

    rows = process_urls(
        urls,
        csv_path=csv_path,
        media_dir=media_dir,
        download=args.download,
        download_video=args.download_video,
        host=args.host,
        port=args.port,
        account=args.account,
        delay=args.delay,
    )

    ok = sum(1 for r in rows if r["状态"] == "成功")
    print(f"\n[extract] 完成: 成功 {ok}/{len(rows)}")
    print(f"[extract] 表格已写入: {csv_path}")

    if args.print_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
