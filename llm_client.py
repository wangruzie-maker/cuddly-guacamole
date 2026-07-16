"""DeepSeek (OpenAI-compatible) LLM client for creative topic generation."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from env_loader import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://tokenhub.tencentmaas.com/v1"
DEFAULT_MODEL = "deepseek-v4-pro"


class DeepSeekError(RuntimeError):
    """DeepSeek / TokenHub API call failed."""


def _normalize_base_url(url: str) -> str:
    base = (url or "").strip().rstrip("/")
    if not base:
        return DEFAULT_BASE_URL
    # TokenHub 文档要求 …/v1；兼容用户漏写 /v1
    if "tokenhub.tencentmaas.com" in base and not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def llm_config() -> dict[str, str]:
    load_dotenv()
    return {
        "api_key": (os.environ.get("DEEPSEEK_API_KEY") or "").strip(),
        "base_url": _normalize_base_url(os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL),
        "model": (os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
    }


def is_llm_configured() -> bool:
    return bool(llm_config()["api_key"])


def llm_status(*, include_secret: bool = False) -> dict[str, Any]:
    from env_loader import mask_secret

    cfg = llm_config()
    key = cfg["api_key"]
    provider = "tokenhub" if "tokenhub.tencentmaas.com" in cfg["base_url"] else "deepseek"
    payload: dict[str, Any] = {
        "configured": bool(key),
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "provider": provider if key else "",
        "api_key_masked": mask_secret(key) if key else "",
        "api_key_set": bool(key),
    }
    if include_secret:
        payload["api_key"] = key
    return payload


def save_llm_config(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Persist LLM settings to .env and process env."""
    from env_loader import upsert_env_values

    updates: dict[str, str] = {}
    if api_key is not None:
        updates["DEEPSEEK_API_KEY"] = api_key.strip()
    if model is not None and model.strip():
        updates["DEEPSEEK_MODEL"] = model.strip()
    if base_url is not None and base_url.strip():
        updates["DEEPSEEK_BASE_URL"] = _normalize_base_url(base_url)
    if not updates:
        return llm_status()
    upsert_env_values(updates)
    return llm_status()


def test_llm_connection(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Probe TokenHub/DeepSeek with a tiny completion; optionally use unsaved values."""
    cfg = llm_config()
    key = (api_key if api_key is not None else cfg["api_key"]).strip()
    use_model = (model if model is not None else cfg["model"]).strip() or DEFAULT_MODEL
    use_base = _normalize_base_url(base_url if base_url is not None else cfg["base_url"])
    if not key:
        return {"ok": False, "error": "未填写 API Key", "model": use_model, "base_url": use_base}
    url = f"{use_base}/chat/completions"
    payload: dict[str, Any] = {
        "model": use_model,
        "messages": [{"role": "user", "content": "只回复ok"}],
        "max_tokens": 64,
        "stream": False,
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=45.0,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"网络失败: {exc}", "model": use_model, "base_url": use_base}
    if resp.status_code >= 400:
        detail = resp.text[:240]
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}: {detail}",
            "model": use_model,
            "base_url": use_base,
        }
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        content = resp.text[:120]
    return {
        "ok": True,
        "model": use_model,
        "base_url": use_base,
        "reply": str(content or "").strip()[:80],
    }


def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: float = 60.0,
) -> str:
    cfg = llm_config()
    if not cfg["api_key"]:
        raise DeepSeekError("未配置 DEEPSEEK_API_KEY（腾讯云 TokenHub）")
    url = f"{cfg['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        # TokenHub DeepSeek：显式关闭思考，加快结构化选题输出
        "thinking": {"type": "disabled"},
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise DeepSeekError(f"TokenHub 网络请求失败: {exc}") from exc
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise DeepSeekError(f"TokenHub HTTP {resp.status_code}: {detail}")
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError(f"TokenHub 响应格式异常: {str(data)[:200]}") from exc
    return str(content or "").strip()


def _extract_json_array(text: str) -> list[Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("topics"), list):
            return parsed["topics"]
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if not match:
        raise DeepSeekError("模型未返回可用的 JSON 数组")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise DeepSeekError("模型 JSON 不是数组")
    return parsed


def generate_suggested_topics_llm(
    *,
    brief: str,
    anchors: list[str],
    mining_angles: list[dict[str, Any]],
    batch: int = 0,
    count: int = 6,
) -> tuple[list[dict[str, Any]] | None, str]:
    """Return (topics, error). topics is None when unavailable/failed."""
    if not is_llm_configured():
        return None, "未配置 DEEPSEEK_API_KEY"
    if not brief and not anchors:
        return None, "缺少创作需求与语料关键词"

    usable_angles = [
        a for a in (mining_angles or [])
        if a.get("id") and (int(a.get("item_count") or 0) > 0 or a.get("top_evidence"))
    ]
    if not usable_angles:
        usable_angles = list(mining_angles or [])[:6]
    if not usable_angles:
        return None, "暂无可用挖掘维度"

    # Rotate angle order by batch so「换一批」有差异
    start = max(0, int(batch)) % max(1, len(usable_angles))
    rotated = usable_angles[start:] + usable_angles[:start]
    angle_payload = []
    for angle in rotated[:8]:
        evidence = []
        for ev in (angle.get("top_evidence") or [])[:3]:
            evidence.append(
                {
                    "title": (ev.get("title") or "")[:60],
                    "liked": ev.get("liked_count") or 0,
                    "url": ev.get("url") or "",
                }
            )
        angle_payload.append(
            {
                "angle_id": angle.get("id"),
                "angle_name": angle.get("name"),
                "description": angle.get("description"),
                "mechanism": angle.get("mechanism"),
                "item_count": angle.get("item_count") or 0,
                "max_liked": angle.get("max_liked") or 0,
                "opportunity": angle.get("opportunity"),
                "evidence": evidence,
            }
        )

    system = (
        "你是小红书内容策略顾问，服务市场部同事。"
        "根据创作需求和已采集爆款证据，产出可直接发布的选题标题。"
        "要求：理解需求语义，禁止把无关产品标题硬替换成需求词；"
        "每条选题必须绑定一个给定维度 angle_id；标题彼此有差异；"
        "只输出 JSON 数组，不要 Markdown。"
    )
    user = {
        "creative_brief": brief or "(未填写，请根据语料热点发挥)",
        "corpus_keywords": anchors[:20],
        "batch": max(0, int(batch)),
        "need_count": count,
        "dimensions": angle_payload,
        "output_schema": [
            {
                "title": "短标题，口语化，可直接发",
                "angle_id": "必须来自 dimensions[].angle_id",
                "angle": "一句话说明切入角度与依据",
                "structure": "怎么写（人设/场景/结构）",
                "why_viral": "为什么会爆（结合该维度机制）",
            }
        ],
        "rules": [
            "title 不要复读整句 creative_brief",
            "若 brief 是场景词（如健身/设计），把它当场景，产品从语料关键词里选真实产品",
            "优先复用 evidence 里的爆款结构，但改写成符合 brief 的新标题",
            "同一批内 angle_id 尽量分散到不同维度",
            f"这是第 {batch} 批，请与常见模板拉开差异",
        ],
    }
    try:
        content = chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            temperature=0.85,
            max_tokens=2200,
            timeout=75.0,
        )
        raw_items = _extract_json_array(content)
    except Exception as exc:  # noqa: BLE001
        print(f"[deepseek] topic generation failed: {exc}", flush=True)
        return None, str(exc)

    angle_by_id = {str(a.get("id")): a for a in (mining_angles or []) if a.get("id")}
    results: list[dict[str, Any]] = []
    used_titles: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = re.sub(r"\s+", " ", str(item.get("title") or "").strip())
        if not title or title in used_titles:
            continue
        used_titles.add(title)
        angle_id = str(item.get("angle_id") or "").strip()
        mining = angle_by_id.get(angle_id) or {}
        if not mining and angle_by_id:
            # fuzzy match by name
            name = str(item.get("angle_name") or "")
            for aid, meta in angle_by_id.items():
                if name and name in str(meta.get("name") or ""):
                    angle_id = aid
                    mining = meta
                    break
        if not mining:
            mining = rotated[len(results) % len(rotated)]
            angle_id = str(mining.get("id") or angle_id)
        evidence = [
            {
                "title": ev.get("title") or "",
                "url": ev.get("url") or "",
                "liked_count": ev.get("liked_count") or 0,
                "author": ev.get("author") or "",
            }
            for ev in (mining.get("top_evidence") or [])[:3]
            if ev.get("url")
        ]
        results.append(
            {
                "title": title[:48],
                "angle": str(item.get("angle") or "").strip()
                or f"DeepSeek 生成 → 下方「{mining.get('name') or angle_id}」",
                "angle_id": angle_id,
                "angle_name": mining.get("name") or str(item.get("angle_name") or angle_id),
                "structure": str(item.get("structure") or mining.get("description") or "").strip(),
                "why_viral": str(item.get("why_viral") or mining.get("mechanism") or "").strip(),
                "source_title": "",
                "coverage": {
                    "item_count": mining.get("item_count") or 0,
                    "avg_liked": mining.get("avg_liked") or 0,
                    "max_liked": mining.get("max_liked") or 0,
                    "opportunity": mining.get("opportunity")
                    or ("covered" if mining.get("item_count") else "high"),
                },
                "evidence": evidence,
                "llm": True,
            }
        )
        if len(results) >= count:
            break
    if not results:
        return None, "模型未产出可用选题"
    return results, ""
