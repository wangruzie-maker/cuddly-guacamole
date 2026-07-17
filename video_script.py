"""Video script extraction: embedded subtitles + optional ASR."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import requests

from whisper_config import resolve_whisper_model
from zh_text import to_simplified_chinese

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.xiaohongshu.com/",
}

_WHISPER_MODEL = None
_WHISPER_MODEL_SIZE = ""


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _parse_srt(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        lines.append(line)
    return "\n".join(lines)


def _parse_vtt(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line or line.isdigit():
            continue
        if line.startswith("NOTE"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _fetch_text_url(url: str) -> str:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
    resp.raise_for_status()
    if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _find_subtitle_urls(video_obj: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_lower = key.lower()
                if isinstance(value, str) and value.startswith("http"):
                    if any(x in key_lower for x in ("subtitle", "caption", "srt", "vtt")):
                        if value not in seen:
                            seen.add(value)
                            urls.append(value)
                    if value.endswith((".srt", ".vtt")) and value not in seen:
                        seen.add(value)
                        urls.append(value)
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(video_obj)
    return urls


def extract_embedded_subtitle(video_obj: dict[str, Any] | None) -> tuple[str, str]:
    """Return (text, source) from embedded subtitle tracks if present."""
    if not isinstance(video_obj, dict):
        return "", ""

    chapters = _dig(video_obj, "consumer", "chapters")
    if isinstance(chapters, list) and chapters:
        parts = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            text = _first_str(chapter.get("text"), chapter.get("title"), chapter.get("name"))
            if text:
                parts.append(text)
        if parts:
            return to_simplified_chinese("\n".join(parts)), "chapters"

    for url in _find_subtitle_urls(video_obj):
        try:
            raw = _fetch_text_url(url)
        except Exception:
            continue
        lower = url.lower()
        if lower.endswith(".vtt") or "vtt" in lower:
            text = _parse_vtt(raw)
        else:
            text = _parse_srt(raw)
        if text.strip():
            return to_simplified_chinese(text.strip()), "subtitle"

    return "", ""


def _dig(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _whisper_cache_dir(model_size: str) -> Path:
    return Path.home() / ".cache/huggingface/hub" / f"models--Systran--faster-whisper-{model_size}"


def get_whisper_status(model_size: str | None = None) -> dict[str, Any]:
    """Report local Whisper cache and in-memory load state."""
    resolved = resolve_whisper_model(model_size)
    cache_dir = _whisper_cache_dir(resolved)
    ready = cache_dir.exists() and any(cache_dir.rglob("model.bin"))
    loaded = _WHISPER_MODEL is not None and _WHISPER_MODEL_SIZE == resolved
    return {
        "model": resolved,
        "ready": ready,
        "loaded": loaded,
    }


def _get_whisper_model(model_size: str):
    global _WHISPER_MODEL, _WHISPER_MODEL_SIZE
    if _WHISPER_MODEL is not None and _WHISPER_MODEL_SIZE == model_size:
        return _WHISPER_MODEL

    from faster_whisper import WhisperModel

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            _WHISPER_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
            _WHISPER_MODEL_SIZE = model_size
            return _WHISPER_MODEL
        except RuntimeError as exc:
            last_error = exc
            if attempt == 0 and "model.bin" in str(exc):
                shutil.rmtree(_whisper_cache_dir(model_size), ignore_errors=True)
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Failed to load Whisper model")


def _extract_audio_wav(video_path: Path) -> Path | None:
    """Extract mono 16kHz WAV via ffmpeg when available."""
    if not shutil.which("ffmpeg"):
        return None
    wav_path = video_path.with_suffix(".wav")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav_path),
        ],
        capture_output=True,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0 or not wav_path.exists():
        wav_path.unlink(missing_ok=True)
        return None
    return wav_path


def _build_initial_prompt(context_hint: str = "") -> str:
    base = "以下是普通话口语内容，请使用简体中文输出，正确识别专业术语与英文品牌名。"
    hint = (context_hint or "").strip()
    if hint:
        return f"{base}\n视频主题：{hint[:300]}"
    return base


def transcribe_video_url(
    video_url: str,
    *,
    model_size: str | None = None,
    max_duration_sec: int | None = None,
    referer: str | None = None,
    context_hint: str = "",
) -> tuple[str, str]:
    """
    Download video and run speech-to-text.

    max_duration_sec: None means no truncation (supports long videos).
    referer: optional Referer header (WeChat Channels CDN requires channels.weixin.qq.com).
    """
    if not video_url:
        return "", ""

    headers = dict(DEFAULT_HEADERS)
    if referer:
        headers["Referer"] = referer

    suffix = ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    audio_path: Path | None = None

    try:
        # 视频号 CDN 链接会过期；连接/读取分设超时，避免一直卡在「转写中」
        download_timeout = (30, 180)
        max_bytes = 250 * 1024 * 1024
        downloaded = 0
        print(f"[video_script] downloading video ({'channels' if referer else 'xhs'})…", flush=True)
        with requests.get(
            video_url, headers=headers, timeout=download_timeout, stream=True
        ) as resp:
            resp.raise_for_status()
            with tmp_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise RuntimeError(f"视频过大（>{max_bytes // (1024*1024)}MB），请取消「完整转录长视频」后重试")
                    f.write(chunk)
        print(f"[video_script] downloaded {downloaded // 1024}KB, transcribing…", flush=True)

        audio_path = _extract_audio_wav(tmp_path)
        source_path = audio_path or tmp_path
        resolved_model = resolve_whisper_model(model_size)
        model = _get_whisper_model(resolved_model)
        segments, _info = model.transcribe(
            str(source_path),
            language="zh",
            vad_filter=True,
            condition_on_previous_text=True,
            beam_size=5,
            temperature=0.0,
            initial_prompt=_build_initial_prompt(context_hint),
        )

        lines: list[str] = []
        for segment in segments:
            lines.append(to_simplified_chinese(segment.text.strip()))
            if max_duration_sec and (segment.end or 0.0) > max_duration_sec:
                lines.append("…（已达时长上限，口播脚本已截断）")
                break

        text = to_simplified_chinese("\n".join(line for line in lines if line).strip())
        return text, ("asr" if text else "")
    except Exception as exc:
        print(f"[video_script] ASR failed: {exc}", flush=True)
        return "", ""
    finally:
        if audio_path:
            audio_path.unlink(missing_ok=True)
        tmp_path.unlink(missing_ok=True)


def build_video_script(
    *,
    note_type: str,
    desc: str,
    video_obj: dict[str, Any] | None,
    video_url: str,
    transcribe: bool,
    model_size: str | None = None,
) -> tuple[str, str]:
    """
    Build video script text and its source label.

    source: chapters | subtitle | asr | desc | empty
    """
    if note_type != "视频":
        return "", ""

    embedded, source = extract_embedded_subtitle(video_obj)
    if embedded:
        return to_simplified_chinese(embedded), source

    if transcribe and video_url:
        text, asr_source = transcribe_video_url(video_url, model_size=model_size)
        if text:
            return text, asr_source
        # Do not fall back to publish copy as if it were ASR.
        return "", ""

    return "", ""
