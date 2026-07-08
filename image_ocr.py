"""OCR text extraction from note images."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import requests
from PIL import Image  # noqa: F401 - optional validation

from fetch_extractor import DEFAULT_HEADERS
from image_urls import dedupe_item_images
from zh_text import to_simplified_chinese

_OCR_ENGINE = None


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
        return _OCR_ENGINE
    except ImportError as exc:
        raise RuntimeError(
            "OCR 依赖未安装，请运行: pip3 install rapidocr-onnxruntime"
        ) from exc


def ocr_image_bytes(data: bytes) -> str:
    engine = _get_ocr_engine()
    result, _ = engine(data)
    if not result:
        return ""
    lines = [str(item[1]).strip() for item in result if len(item) > 1 and str(item[1]).strip()]
    return to_simplified_chinese("\n".join(lines))


def ocr_image_url(url: str) -> str:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()
    return ocr_image_bytes(resp.content)


def ocr_image_path(path: str) -> str:
    with open(path, "rb") as f:
        return ocr_image_bytes(f.read())


def ocr_note_images(
    image_urls: list[str] | None = None,
    local_paths: list[str] | None = None,
) -> str:
    parts: list[str] = []
    paths = local_paths or []
    urls = image_urls or []

    if paths:
        for idx, path in enumerate(paths, start=1):
            try:
                text = ocr_image_path(path)
                if text:
                    parts.append(f"【图{idx}】\n{text}")
            except Exception as exc:
                print(f"[image_ocr] path failed {path}: {exc}", flush=True)
    else:
        for idx, url in enumerate(urls, start=1):
            try:
                text = ocr_image_url(url)
                if text:
                    parts.append(f"【图{idx}】\n{text}")
            except Exception as exc:
                print(f"[image_ocr] url failed {url}: {exc}", flush=True)

    return to_simplified_chinese("\n\n".join(parts))


def ocr_stored_item(item: dict[str, Any]) -> dict[str, Any]:
    item = dedupe_item_images(item)
    urls = item.get("image_urls") or []
    if not urls:
        item["image_ocr_text"] = ""
        item["image_ocr_status"] = "none"
        return item

    paths = item.get("local_image_paths") or []
    if not paths and item.get("image_cache_status") != "done":
        from image_cache import cache_item_images

        item = cache_item_images(item)
        paths = item.get("local_image_paths") or []

    try:
        text = ocr_note_images(image_urls=urls if not paths else None, local_paths=paths or None)
        item["image_ocr_text"] = text
        item["image_ocr_status"] = "done" if text else "failed"
    except Exception as exc:
        item["image_ocr_text"] = ""
        item["image_ocr_status"] = "failed"
        item["image_ocr_error"] = str(exc)
        print(f"[image_ocr] item failed: {exc}", flush=True)
    return item
