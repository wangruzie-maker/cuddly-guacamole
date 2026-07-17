"""Viral topic miner framework adapter for intel topic generation.

Wraps RedSkill `viral-topic-miner` methodology as an in-process layer for
选题分析, with a light awareness of 百度搭子、秒哒 and relevant current events.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

# Product awareness is a weak prior, never a mandatory topic constraint.
BAIDU_CONTENT_HINT_PROFILE: dict[str, Any] = {
    "org": "百度产品内容线索（弱偏好）",
    "preference_strength": "light",
    "platforms": ["小红书", "短视频"],
    "track": "商业/产品 · 工具/教程 · 科技",
    "audiences": [
        "AI 工具尝鲜者与职场人",
        "内容创作者与市场运营",
        "零代码做应用的个人与业务团队",
        "企业数字化与 AI 落地关注者",
    ],
    "product_aliases": [
        "百度搭子",
        "DuMate",
        "秒哒",
        "MIAODA",
    ],
    "content_goals": [
        "百度搭子：办公、创作、资料处理、浏览器执行等真实任务的交付体验",
        "秒哒：自然语言生成网站/H5/小程序/APP与原型验证",
        "热点事件：先判断受众相关性，再寻找产品可验证的参与角度",
        "真实体验：前后对比、失败避坑、竞品选型与可复用工作流",
    ],
    "tone_rules": [
        "产品只作潜在线索；主题不相关时不要硬塞百度搭子或秒哒",
        "先讲用户问题与场景，再自然出现产品名，避免硬广",
        "每条选题落到具体人群 + 情绪/问题 + 可拍结果",
        "不编造实测数据、客户名或未公开商业材料",
        "热点可独立成题，不要求必须绑定百度产品",
        "区分已证实事实、外部观点、合理推断、仍需实测",
    ],
}

PRODUCT_KNOWLEDGE: dict[str, dict[str, Any]] = {
    "百度搭子": {
        "aliases": ["百度搭子", "DuMate", "搭子"],
        "positioning": "通用执行式 AI 智能体，强调从回答问题走向完成任务。",
        "verified_capabilities": [
            "办公与创作任务、资料整理和文件处理",
            "浏览器操作与跨应用任务执行",
            "PPT、方案、报告等办公成品交付",
            "个人版与企业协作/治理方向",
        ],
        "content_angles": [
            "它究竟交付了什么，而不只是回答了什么",
            "PPT/研究/内容创作的真实前后对比",
            "与其他桌面 Agent 的任务路径和适用人群差异",
            "执行稳定性、速度、权限确认和结果可编辑性",
        ],
        "public_signals": [
            "小红书讨论集中在竞品对比、DAA/干活指标、发布升级和拥堵体验",
            "公开报道强调办公、创作、信息处理与浏览器执行场景",
        ],
        "sources": [
            "https://www.dumate.cn/",
            "https://cloud.baidu.com/doc/Dumate/s/xmmu7qrvo",
            "http://sc.people.com.cn/n2/2026/0710/c345167-41635480.html",
            "https://m.tech.china.com/articles/20260615/202606151893999.html",
        ],
    },
    "秒哒": {
        "aliases": ["秒哒", "MIAODA", "秒搭"],
        "positioning": "自然语言驱动的无代码应用开发平台，面向个人创意和企业业务应用。",
        "verified_capabilities": [
            "对话生成 H5、网站、小程序、小游戏和轻应用",
            "自然语言生成原生 APP，支持 Android 打包与在线调试",
            "多智能体协作、插件/Skill、后端与数据库能力",
            "快速开发用于原型，深度开发用于更完整的正式场景",
        ],
        "content_angles": [
            "不会代码的人能否从想法做到可用应用",
            "3分钟原型与真正上线之间还差什么",
            "营销 H5、活动报名、表单、内部工具等可拍案例",
            "Vibe Coding 工具横评、成本/秒点/发布限制和失败修复",
        ],
        "public_signals": [
            "小红书较强话题包括：一句话做应用、工具横评、能否赚钱、真实踩坑",
            "官方文档强调无代码、多智能体、多工具调用和多端应用生成",
        ],
        "risk_boundaries": [
            "官方速度数据属于产品宣称，选题中应标为待本人实测",
            "支付、iOS 打包等能力需以最新文档和实际账户权限为准",
        ],
        "sources": [
            "https://cloud.baidu.com/doc/MIAODA/s/Sm88db6er",
            "https://cloud.baidu.com/doc/MIAODA/s/Zmm32qp8x",
            "https://cloud.baidu.com/doc/MIAODA/s/Amoy50baf",
        ],
    },
}


def resolve_viral_topic_miner_dir() -> Path | None:
    """Locate installed viral-topic-miner skill directory."""
    env = (os.environ.get("VIRAL_TOPIC_MINER_ROOT") or "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates.extend(
        [
            here.parent.parent / "skills" / "viral-topic-miner",
            here.parent.parent / ".cursor" / "skills" / "viral-topic-miner",
            Path.home() / ".cursor" / "skills" / "viral-topic-miner",
            Path.cwd() / "skills" / "viral-topic-miner",
        ]
    )
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if (resolved / "SKILL.md").is_file():
            return resolved
    return None


def framework_status() -> dict[str, Any]:
    skill_dir = resolve_viral_topic_miner_dir()
    cli = (skill_dir / "anysearch_cli.js") if skill_dir else None
    return {
        "skill": "viral-topic-miner",
        "installed": bool(skill_dir),
        "skill_dir": str(skill_dir) if skill_dir else "",
        "anysearch_cli": bool(cli and cli.is_file()),
        "profile": BAIDU_CONTENT_HINT_PROFILE["org"],
        "preference_strength": BAIDU_CONTENT_HINT_PROFILE["preference_strength"],
        "version_hint": "1.0.0",
    }


def _need_live_search(brief: str) -> bool:
    text = brief or ""
    if os.environ.get("TOPIC_MINER_SEARCH", "").strip().lower() in ("1", "true", "yes"):
        return True
    return bool(
        re.search(
            r"(最近|今天|刚发布|现在|热点|更新|发布会|版本|政策|价格|榜单|搜一下|查证)",
            text,
        )
    )


def search_public_evidence(
    brief: str,
    *,
    max_results: int = 4,
    timeout_sec: float = 18.0,
) -> dict[str, Any]:
    """Optional AnySearch evidence pack. Failures are soft (empty pack)."""
    skill_dir = resolve_viral_topic_miner_dir()
    if not skill_dir:
        return {
            "status": "skill_missing",
            "facts": [],
            "reactions": [],
            "note": "未找到 viral-topic-miner，跳过外搜",
        }
    if not _need_live_search(brief):
        return {
            "status": "skipped",
            "facts": [],
            "reactions": [],
            "note": "非时效/热点需求，默认不外搜",
        }

    cli = skill_dir / "anysearch_cli.js"
    if not cli.is_file():
        return {
            "status": "cli_missing",
            "facts": [],
            "reactions": [],
            "note": "AnySearch CLI 缺失",
        }

    # De-sensitize: keep public product / category terms only.
    query = re.sub(r"\s+", " ", brief or "").strip()[:80]
    for secretish in ("客户", "内部", "未公开", "合同", "密钥", "密码"):
        if secretish in query:
            return {
                "status": "blocked_privacy",
                "facts": [],
                "reactions": [],
                "note": "疑似含敏感词，已跳过外搜",
            }

    queries = [
        f"{query} 百度搭子 秒哒",
        f"{query} AI Agent 无代码应用 落地 场景",
        f"{query} 用户反馈 OR 吐槽 OR 怎么选",
    ]
    facts: list[dict[str, str]] = []
    reactions: list[dict[str, str]] = []
    errors: list[str] = []

    for idx, q in enumerate(queries[:3]):
        try:
            proc = subprocess.run(
                [
                    "node",
                    str(cli),
                    "search",
                    q,
                    "--max_results",
                    str(max(1, min(5, max_results))),
                ],
                cwd=str(skill_dir),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
            continue
        if proc.returncode != 0:
            errors.append((proc.stderr or proc.stdout or "search failed")[:200])
            continue
        text = (proc.stdout or "").strip()
        if not text:
            continue
        # CLI may print markdown or JSON; keep short snippets either way.
        snippet = re.sub(r"\s+", " ", text)[:280]
        item = {"query": q, "snippet": snippet}
        if idx == 2:
            reactions.append(item)
        else:
            facts.append(item)

    status = "searched" if (facts or reactions) else "search_failed"
    return {
        "status": status,
        "facts": facts[:4],
        "reactions": reactions[:3],
        "note": "；".join(errors[:2]) if errors and status != "searched" else "",
        "credibility": "中" if facts else "低",
    }


def build_topic_generation_context(
    *,
    brief: str,
    anchors: list[str] | None = None,
    enable_search: bool | None = None,
) -> dict[str, Any]:
    """Context injected into LLM / rule topic generation."""
    profile = BAIDU_CONTENT_HINT_PROFILE
    status = framework_status()
    do_search = _need_live_search(brief) if enable_search is None else bool(enable_search)
    evidence = (
        search_public_evidence(brief)
        if do_search
        else {
            "status": "skipped",
            "facts": [],
            "reactions": [],
            "note": "未启用外搜",
            "credibility": "—",
        }
    )

    methodology = [
        "热点/素材 → 时间节点 → 集体情绪 → 谁+何时+要什么结果 → 可拍场景 → 内容形态",
        "强选题 = 具体人群 + 当前问题/情绪 + 可拍场景 + 可见结果 + 创作者独特资产",
        "先判断账号与受众适配，再追热点；不把热词列表当选题",
        "评分维度参考：情绪命中、人群清晰、时效势能、可拍性、独特性、收藏转发、评论缺口、包装空间",
        "等级只用方向性：入库级 / 可做级 / 小爆候选 / 优先押注（非流量保证）",
    ]
    product_context = _select_product_context(brief=brief, anchors=anchors or [])

    return {
        "framework": "viral-topic-miner",
        "framework_installed": status["installed"],
        "profile": profile,
        "product_context": product_context,
        "methodology": methodology,
        "corpus_anchors": (anchors or [])[:16],
        "evidence_pack": evidence,
        "system_addendum": _system_addendum(profile),
        "user_addendum": {
            "org_profile": {
                "org": profile["org"],
                "preference_strength": profile["preference_strength"],
                "audiences": profile["audiences"],
                "product_aliases": profile["product_aliases"],
                "content_goals": profile["content_goals"],
            },
            "product_context": product_context,
            "tone_rules": profile["tone_rules"],
            "methodology_bullets": methodology,
            "evidence_pack": evidence,
        },
    }


def _system_addendum(profile: dict[str, Any]) -> str:
    return (
        "你同时遵循 viral-topic-miner 选题雷达方法论。"
        "选题必须可拍、有人群、有场景结果；先用户问题后产品；"
        "对百度搭子、秒哒及相关热点保持轻量意识，但这只是弱偏好："
        "仅当创作需求、语料或热点自然相关时才采用，禁止强行植入产品；"
        "可参考证据包，但禁止编造客户实测与未公开信息；"
        "输出仍是可直接发的小红书标题，并绑定给定 angle_id。"
    )


def enrich_brief_with_profile(brief: str) -> str:
    """Normalize only; never rewrite user intent with a mandatory product tag."""
    return re.sub(r"\s+", " ", brief or "").strip()


def _select_product_context(*, brief: str, anchors: list[str]) -> dict[str, Any]:
    """Expose relevant product knowledge without forcing it into every topic."""
    haystack = " ".join([brief, *anchors]).lower()
    selected: dict[str, Any] = {}
    for name, product in PRODUCT_KNOWLEDGE.items():
        aliases = [str(alias) for alias in product.get("aliases") or []]
        if any(alias.lower() in haystack for alias in aliases):
            selected[name] = product

    # Keep awareness in the background when no product is mentioned.
    if not selected:
        return {
            "mode": "background_awareness",
            "instruction": "仅在语料或热点自然关联时考虑百度搭子/秒哒；否则正常生成其他热点选题。",
            "available_products": ["百度搭子", "秒哒"],
        }
    return {
        "mode": "relevant",
        "instruction": "可使用以下已核验产品信息，但产品宣称仍需实测，且不得覆盖用户原始意图。",
        "products": selected,
    }


def dump_context_preview(ctx: dict[str, Any]) -> str:
    """Short debug string for logs / API meta."""
    evid = ctx.get("evidence_pack") or {}
    return json.dumps(
        {
            "framework": ctx.get("framework"),
            "installed": ctx.get("framework_installed"),
            "org": (ctx.get("profile") or {}).get("org"),
            "evidence_status": evid.get("status"),
            "facts": len(evid.get("facts") or []),
        },
        ensure_ascii=False,
    )
