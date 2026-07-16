"""Product-layer helpers: content typing, topic pack export, directions, benchmarks."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

import intel_service

# ---------------------------------------------------------------------------
# 内容类型（标题结构）
# ---------------------------------------------------------------------------

CONTENT_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("入门教程", ["教程", "入门", "指南", "学会", "零基础", "小白", "手把手"]),
    ("真实测评", ["用了", "体验", "实测", "感受", "一个月", "亲测", "使用"]),
    ("对比选型", ["vs", "VS", "对比", "选哪个", "还是", "怎么选", "一篇讲清楚", "区别"]),
    ("争议讨论", ["千万别", "大实话", "智商税", "太难用", "踩坑", "为啥", "到底", "别买"]),
    ("清单合集", ["合集", "建议收藏", "个工具", "个AI", "推荐", "盘点", "必备"]),
    ("场景共鸣", ["打工人", "效率", "办公", "周报", "摸鱼", "职场", "加班"]),
]

DIRECTION_MECHANISMS: dict[str, str] = {
    "入门教程": "降低门槛，满足「我想学会」的搜索意图",
    "真实测评": "第一人称真实感，种草转化最高",
    "对比选型": "决策辅助，收藏/赞比通常更高",
    "争议讨论": "好奇+评论互动，利于推流",
    "清单合集": "收藏驱动，适合工具类产品",
    "场景共鸣": "痛点场景代入，引发共鸣转发",
    "其他": "观察标题结构，替换产品名与差异化卖点",
}

# ---------------------------------------------------------------------------
# 选题挖掘维度（综合方法论，参考 IDEA/KFS/人群×场景×需求矩阵）
# 来源：xuanti-skill + 小红书运营 SOP（泛流量/干货/营销/信任）+ 场景化搜索布局
# ---------------------------------------------------------------------------

MINING_ANGLES: list[dict[str, Any]] = [
    {
        "id": "feature_scene",
        "name": "功能场景化",
        "description": "什么人 + 什么场景 + 解决什么痛点（场景化营销核心）",
        "mechanism": "命中具体使用场景，平台会把内容推给有同样处境的用户",
        "signals": [
            "周报", "日报", "Excel", "PPT", "表格", "会议", "汇报", "写稿", "排版", "翻译",
            "邮件", "文档", "备课", "论文", "代码", "debug", "需求", "运营", "剪辑", "做图",
            "加班", "摸鱼", "通勤", "居家办公", "自由职业",
        ],
        "search_templates": ["{base} 周报", "{base} Excel", "{base} 办公场景", "{base} 写PPT"],
    },
    {
        "id": "product_compare",
        "name": "同类产品对比",
        "description": "A vs B、怎么选、一篇讲清楚（决策辅助型）",
        "mechanism": "用户处于比价决策阶段，收藏率高，适合截流竞品搜索",
        "signals": [
            "vs", "VS", "对比", "还是", "怎么选", "哪个好", "一篇讲清楚", "区别", "平替",
            "替代", "选哪个", "优缺点", "横评", "评测对比",
        ],
        "search_templates": ["{base} vs", "{base} 对比", "{base} 怎么选", "{base} 还是"],
    },
    {
        "id": "tool_combo",
        "name": "多工具联动",
        "description": "产品 A + 产品 B、搭建工作流/知识库（双流量覆盖）",
        "mechanism": "叠加两个搜索词流量池，适合展示组合用法与生态位",
        "signals": [
            "联动", "组合", "搭配", "一起用", "工作流", "搭建", "套件", "配", "打通",
            "知识库", "自动化", "串联", "协作", "+", "结合",
        ],
        "search_templates": ["{base} 联动", "{base} 工作流", "{base} 知识库", "{base} 搭配"],
    },
    {
        "id": "pain_relief",
        "name": "痛点解决",
        "description": "戳痛点、找共鸣、解决具体烦恼（激发欲望阶段）",
        "mechanism": "强情绪共鸣带来评论互动，利于冷启动推流",
        "signals": [
            "痛点", "烦恼", "崩溃", "救命", "终于", "再也不", "解放", "省时", "熬夜",
            "头秃", "内卷", "焦虑", "效率低", "重复劳动",
        ],
        "search_templates": ["{base} 痛点", "{base} 省时", "{base} 效率"],
    },
    {
        "id": "pain_callout",
        "name": "吐槽避坑",
        "description": "千万别、踩坑、智商税、大实话（争议好奇型）",
        "mechanism": "否定式标题提升点击率，评论区争议带来二次分发",
        "signals": [
            "千万别", "踩坑", "智商税", "大实话", "太难用", "别买", "劝退", "翻车",
            "避雷", "坑", "不成熟", "鸡肋",
        ],
        "search_templates": ["{base} 踩坑", "{base} 难用", "{base} 避雷"],
    },
    {
        "id": "tutorial_entry",
        "name": "教程入门",
        "description": "零基础、手把手、装好就能用（干货科普型）",
        "mechanism": "满足「我想学会」的信息搜索意图，适合新号起量",
        "signals": [
            "教程", "入门", "指南", "学会", "零基础", "小白", "手把手", "一分钟", "秒懂",
            "攻略", "怎么玩", "第一次",
        ],
        "search_templates": ["{base} 教程", "{base} 入门", "{base} 零基础"],
    },
    {
        "id": "list_roundup",
        "name": "清单合集",
        "description": "X 个工具、建议收藏、年度盘点（收藏驱动型）",
        "mechanism": "清单类藏/赞比高，适合品类词占位",
        "signals": [
            "合集", "盘点", "必备", "建议收藏", "个工具", "个AI", "清单", "大全",
            "宝藏", "封神", "年度",
        ],
        "search_templates": ["{base} 合集", "{base} 推荐", "{base} 工具清单"],
    },
    {
        "id": "honest_review",
        "name": "真实测评",
        "description": "用了 X 天、亲测、真实感受（信任背书型）",
        "mechanism": "第一人称叙事降低营销感，转化率高",
        "signals": [
            "用了", "亲测", "实测", "体验", "感受", "一个月", "一周", "真实", "深度使用",
        ],
        "search_templates": ["{base} 实测", "{base} 体验", "{base} 用了"],
    },
    {
        "id": "decision_guide",
        "name": "购买决策",
        "description": "值不值得买、适合谁、购买指南（方案评估阶段）",
        "mechanism": "承接高意向用户，适合成熟期账号转化",
        "signals": [
            "值不值", "值得买", "适合谁", "购买", "选购", "指南", "建议", "要不要",
            "值得入", "闭眼入",
        ],
        "search_templates": ["{base} 值得买吗", "{base} 适合谁", "{base} 购买指南"],
    },
]

_ANGLE_BY_ID = {a["id"]: a for a in MINING_ANGLES}

# 常见工具/产品名（用于识别联动类标题中的第二主体）
_TOOL_NAME_PATTERN = re.compile(
    r"(Cursor|Copilot|ChatGPT|Claude|Notion|飞书|钉钉|Excel|WPS|Obsidian|WorkBuddy|Codex|"
    r"OpenClaw|秒哒|搭子|DuMate|MCP|DeepSeek|Kimi|豆包|通义)",
    re.I,
)

SEARCH_DIMENSION_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "ai-efficiency",
        "name": "AI 效率工具",
        "description": "桌面 Agent / 办公效率赛道基础调研",
        "keywords": ["AI效率工具", "桌面Agent", "AI办公"],
        "platforms": ["xhs"],
    },
    {
        "id": "competitor-tutorial",
        "name": "竞品教程向",
        "description": "看竞品教程类内容占比与爆款标题",
        "keywords": ["WorkBuddy 教程", "Codex 入门", "AI工具 教程"],
        "platforms": ["xhs"],
    },
    {
        "id": "competitor-pain",
        "name": "竞品吐槽向",
        "description": "挖掘竞品弱点与用户真实痛点",
        "keywords": ["AI工具 踩坑", "Agent 难用", "效率工具 吐槽"],
        "platforms": ["xhs"],
    },
    {
        "id": "scene-worker",
        "name": "打工人场景",
        "description": "场景共鸣型选题：周报、摸鱼、加班",
        "keywords": ["打工人 AI", "办公效率", "周报 AI"],
        "platforms": ["xhs"],
    },
    {
        "id": "compare-pick",
        "name": "对比选型",
        "description": "决策辅助型：vs、怎么选、一篇讲清楚",
        "keywords": ["AI工具 对比", "Agent 怎么选", "效率工具 推荐"],
        "platforms": ["xhs"],
    },
    {
        "id": "channels-hot",
        "name": "视频号热点",
        "description": "视频号关键词热点采集",
        "keywords": ["AI工具", "效率", "科技"],
        "platforms": ["channels"],
    },
]


def classify_content_type(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return "其他"
    for label, keywords in CONTENT_TYPE_RULES:
        for kw in keywords:
            if kw in text:
                return label
    return "其他"


def classify_mining_angle(title: str, keyword: str = "") -> tuple[str, int]:
    """Return (angle_id, score). Higher score = stronger match."""
    text = f"{title} {keyword}".strip()
    if not text:
        return "feature_scene", 0
    best_id = "feature_scene"
    best_score = 0
    for angle in MINING_ANGLES:
        score = 0
        for sig in angle.get("signals") or []:
            if sig.lower() in text.lower():
                score += 2 if len(sig) >= 3 else 1
        if angle["id"] == "tool_combo" and len(_TOOL_NAME_PATTERN.findall(title)) >= 2:
            score += 4
        if score > best_score:
            best_score = score
            best_id = angle["id"]
    return best_id, best_score


def enrich_item(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    title = str(item.get("title") or "")
    keyword = str(item.get("keyword") or "")
    out["content_type"] = classify_content_type(title)
    angle_id, angle_score = classify_mining_angle(title, keyword)
    out["mining_angle"] = angle_id
    out["mining_angle_name"] = _ANGLE_BY_ID.get(angle_id, {}).get("name", angle_id)
    out["mining_angle_score"] = angle_score
    return out


def _base_keywords_from_items(items: list[dict[str, Any]], topic_keywords: list[str] | None = None) -> list[str]:
    bases: list[str] = []
    for kw in topic_keywords or []:
        kw = str(kw).strip()
        if kw and kw not in bases:
            bases.append(kw)
    for item in items[:20]:
        kw = str(item.get("keyword") or "").strip()
        if kw and kw not in bases:
            bases.append(kw)
    if not bases:
        bases = ["AI工具"]
    return bases[:3]


def mine_dimensional_insights(*, topic_id: str | None = None, evidence_limit: int = 5) -> dict[str, Any]:
    """Multi-dimensional topic mining across collected viral items."""
    topic = intel_service.get_watch_topic(topic_id) if topic_id else None
    if topic_id and not topic:
        raise ValueError("选题不存在")

    if topic_id:
        payload = intel_service.list_topic_items(topic_id, page=1, page_size=100)
        items = [enrich_item(i) for i in payload.get("items") or []]
        topic_keywords = topic.get("keywords") or []
        scope_name = topic.get("name") or topic_id
    else:
        items = []
        topic_keywords = []
        for t in intel_service.list_watch_topics():
            p = intel_service.list_topic_items(t["id"], page=1, page_size=50)
            items.extend(enrich_item(i) for i in p.get("items") or [])
        scope_name = "全部选题"

    bases = _base_keywords_from_items(items, topic_keywords)

    angle_buckets: dict[str, list[dict[str, Any]]] = {a["id"]: [] for a in MINING_ANGLES}
    for item in items:
        aid = item.get("mining_angle") or "feature_scene"
        angle_buckets.setdefault(aid, []).append(item)

    angles_out: list[dict[str, Any]] = []
    for angle in MINING_ANGLES:
        aid = angle["id"]
        bucket = sorted(
            angle_buckets.get(aid) or [],
            key=lambda x: float(x.get("hot_score") or 0),
            reverse=True,
        )
        cnt = len(bucket)
        avg_liked = round(sum(int(i.get("liked_count") or 0) for i in bucket) / cnt, 1) if cnt else 0
        max_liked = max((int(i.get("liked_count") or 0) for i in bucket), default=0)
        top = bucket[0] if bucket else {}
        suggested_keywords = [
            tpl.format(base=bases[0]) for tpl in (angle.get("search_templates") or [])[:3]
        ]
        angles_out.append(
            {
                "id": aid,
                "name": angle["name"],
                "description": angle["description"],
                "mechanism": angle["mechanism"],
                "item_count": cnt,
                "avg_liked": avg_liked,
                "max_liked": max_liked,
                "coverage": round(cnt / max(len(items), 1) * 100, 1),
                "suggested_keywords": suggested_keywords,
                "suggested_title": _rewrite_title(str(top.get("title") or ""), angle["name"]) if top else "",
                "top_evidence": [
                    {
                        "title": i.get("title"),
                        "url": i.get("url"),
                        "author": i.get("author"),
                        "liked_count": i.get("liked_count"),
                        "content_type": i.get("content_type"),
                        "keyword": i.get("keyword"),
                    }
                    for i in bucket[:evidence_limit]
                ],
                "opportunity": "high" if cnt == 0 else ("medium" if cnt <= 2 else "covered"),
            }
        )

    angles_out.sort(key=lambda x: (-x["item_count"], -x["max_liked"]))

    # 人群×场景×需求 简版矩阵：从场景类爆款标题抽场景词
    scene_tags: dict[str, int] = {}
    scene_signals = _ANGLE_BY_ID["feature_scene"]["signals"]
    for item in items:
        title = str(item.get("title") or "")
        for sig in scene_signals:
            if sig in title:
                scene_tags[sig] = scene_tags.get(sig, 0) + 1
    scene_matrix = [
        {"scene": k, "count": v, "suggestion": f"{bases[0]} {k}"}
        for k, v in sorted(scene_tags.items(), key=lambda x: -x[1])[:8]
    ]

    return {
        "scope": scope_name,
        "topic_id": topic_id,
        "total_items": len(items),
        "base_keywords": bases,
        "angles": angles_out,
        "scene_matrix": scene_matrix,
        "methodology_note": (
            "综合 IDEA 模型（洞察-定义-执行）、场景化营销（人群×场景×痛点）、"
            "以及竞品内容六维拆解（教程/测评/对比/联动/清单/争议）从已采集爆款中归纳。"
        ),
    }


def _search_link(keyword: str) -> str:
    return f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}"


def _rewrite_title(title: str, topic_name: str) -> str:
    t = (title or "").strip()
    if not t:
        return f"【待写】围绕「{topic_name}」的爆款仿写标题"
    # Light rewrite: prepend topic hook if title is generic
    if len(t) < 12:
        return f"{topic_name}｜{t}"
    return t


def generate_topic_directions(topic_id: str, *, limit: int = 5) -> dict[str, Any]:
    topic = intel_service.get_watch_topic(topic_id)
    if not topic:
        raise ValueError("选题不存在")
    payload = intel_service.list_topic_items(topic_id, page=1, page_size=30)
    items = [enrich_item(i) for i in payload.get("items") or []]
    if not items:
        return {"topic": topic, "directions": [], "content_type_stats": {}}

    type_stats: dict[str, int] = {}
    for item in items:
        ct = item["content_type"]
        type_stats[ct] = type_stats.get(ct, 0) + 1

    # Pick representative items: prefer unique mining angles, then unique content types
    seen_angles: set[str] = set()
    seen_types: set[str] = set()
    picks: list[dict[str, Any]] = []
    for item in items:
        aid = str(item.get("mining_angle") or "feature_scene")
        ct = item["content_type"]
        if aid in seen_angles:
            continue
        seen_angles.add(aid)
        seen_types.add(ct)
        picks.append(item)
        if len(picks) >= limit:
            break
    if len(picks) < limit:
        for item in items:
            ct = item["content_type"]
            if item in picks:
                continue
            if ct in seen_types and len(picks) >= max(3, limit - 1):
                continue
            seen_types.add(ct)
            picks.append(item)
            if len(picks) >= limit:
                break

    directions: list[dict[str, Any]] = []
    used_angle_names: set[str] = set()
    for item in picks[:limit]:
        aid = item.get("mining_angle") or "feature_scene"
        angle_meta = _ANGLE_BY_ID.get(aid, {})
        ct = item["content_type"]
        angle_name = angle_meta.get("name") or item.get("mining_angle_name") or ct
        # Avoid identical angle cards back-to-back: if same angle already used, fall back to content type label
        if angle_name in used_angle_names:
            angle_name = f"{ct}" if ct and ct != "其他" else f"{angle_name}·补充"
        used_angle_names.add(angle_name)
        directions.append(
            {
                "angle_id": aid,
                "angle_name": angle_name,
                "content_type": ct,
                "mechanism": angle_meta.get("mechanism") or DIRECTION_MECHANISMS.get(ct, DIRECTION_MECHANISMS["其他"]),
                "reference_title": item.get("title") or "",
                "reference_url": item.get("url") or "",
                "reference_author": item.get("author") or "",
                "reference_liked": item.get("liked_count") or 0,
                "suggested_title": _rewrite_title(str(item.get("title") or ""), topic.get("name") or ""),
                "keyword": item.get("keyword") or "",
                "suggested_search_keywords": [
                    tpl.format(base=(topic.get("keywords") or ["AI工具"])[0])
                    for tpl in (angle_meta.get("search_templates") or [])[:2]
                ],
            }
        )

    mining = mine_dimensional_insights(topic_id=topic_id, evidence_limit=3)

    return {
        "topic": topic,
        "directions": directions,
        "content_type_stats": type_stats,
        "mining_angles": mining.get("angles") or [],
    }


def export_topic_pack_markdown(topic_id: str) -> str:
    topic = intel_service.get_watch_topic(topic_id)
    if not topic:
        raise ValueError("选题不存在")
    analytics = intel_service.topic_analytics(topic_id)
    directions_data = generate_topic_directions(topic_id, limit=8)
    items_raw = intel_service.list_topic_items(topic_id, page=1, page_size=25)["items"]
    items = [enrich_item(i) for i in items_raw]

    name = topic.get("name") or "未命名选题"
    today = datetime.now().strftime("%m%d")
    keywords = "、".join(topic.get("keywords") or [])
    lines: list[str] = [
        f"# {today}{name}选题包",
        "",
        "## 创作方向",
        f"围绕「{name}」({keywords})，从已采集爆款中提炼可复用选题方向。",
        "",
        "## 数据概览",
    ]
    summary = analytics.get("summary") or {}
    if summary.get("cnt"):
        lines.extend(
            [
                f"- 爆款条数：{int(summary['cnt'])}",
                f"- 平均点赞：{int(summary.get('avg_liked') or 0)}",
                f"- 最高点赞：{int(summary.get('max_liked') or 0)}",
                f"- 平均热度：{round(float(summary.get('avg_hot') or 0), 1)}",
                "",
            ]
        )
    else:
        lines.extend(["- 暂无数据，请先运行选题采集。", ""])

    type_stats = directions_data.get("content_type_stats") or {}
    if type_stats:
        lines.append("### 内容类型分布")
        for ct, cnt in sorted(type_stats.items(), key=lambda x: -x[1]):
            lines.append(f"- {ct}：{cnt} 条")
        lines.append("")

    lines.append("## 参考竞品概览")
    lines.append("")
    lines.append("| 标题 | 类型 | 赞 | 藏 | 评 | 作者 | 链接 |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- | --- |")
    for item in items[:15]:
        title = (item.get("title") or "").replace("|", "\\|")[:60]
        lines.append(
            f"| {title} | {item.get('content_type', '-')} | {item.get('liked_count', 0)} "
            f"| {item.get('collected_count', 0)} | {item.get('comment_count', 0)} "
            f"| {item.get('author') or '-'} | [打开]({item.get('url') or '#'}) |"
        )
    lines.append("")

    lines.append("## 选题方向建议（多维角度）")
    lines.append("")
    for idx, d in enumerate(directions_data.get("directions") or [], 1):
        lines.extend(
            [
                f"### 方向 {idx}：{d.get('angle_name') or d.get('content_type')}",
                "",
                f"- **机制**：{d.get('mechanism')}",
                f"- **竞品标杆**：{d.get('reference_title')}（赞 {d.get('reference_liked')} · {d.get('reference_author') or '未知作者'}）",
                f"- **仿写标题**：{d.get('suggested_title')}",
                f"- **建议搜索词**：{', '.join(d.get('suggested_search_keywords') or [])}",
                f"- **参考链接**：[链接]({d.get('reference_url') or '#'})",
                "",
            ]
        )

    mining_angles = directions_data.get("mining_angles") or []
    if mining_angles:
        lines.append("## 维度覆盖分析")
        lines.append("")
        lines.append("| 角度 | 爆款数 | 最高赞 | 机会 | 建议搜索词 |")
        lines.append("| --- | ---: | ---: | --- | --- |")
        for a in mining_angles:
            kws = "、".join(a.get("suggested_keywords") or [])[:40]
            lines.append(
                f"| {a.get('name')} | {a.get('item_count')} | {a.get('max_liked')} "
                f"| {a.get('opportunity')} | {kws} |"
            )
        lines.append("")

    lines.append("## 分类总览")
    lines.append("")
    for ct, cnt in sorted(type_stats.items(), key=lambda x: -x[1]):
        mech = DIRECTION_MECHANISMS.get(ct, "")
        lines.append(f"- **{ct}**（{cnt} 条）：{mech}")
    lines.append("")

    lines.append("## 建议发布排期（按周）")
    lines.append("")
    week_types = [ct for ct, _ in sorted(type_stats.items(), key=lambda x: -x[1])]
    if not week_types:
        week_types = ["场景共鸣", "入门教程", "对比选型"]
    for i, ct in enumerate(week_types[:4], 1):
        lines.append(f"- 第 {i} 周：{ct}（{DIRECTION_MECHANISMS.get(ct, '')}）")
    lines.append("")
    lines.append(f"_导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    return "\n".join(lines)


def competitor_benchmark() -> dict[str, Any]:
    overview = intel_service.cross_topic_overview()
    topics_out: list[dict[str, Any]] = []
    for t in overview.get("topics") or []:
        topic_id = t["id"]
        payload = intel_service.list_topic_items(topic_id, page=1, page_size=50)
        items = [enrich_item(i) for i in payload.get("items") or []]
        type_stats: dict[str, int] = {}
        wan_like = 0
        max_liked = 0
        for item in items:
            ct = item["content_type"]
            type_stats[ct] = type_stats.get(ct, 0) + 1
            liked = int(item.get("liked_count") or 0)
            max_liked = max(max_liked, liked)
            if liked >= 10000:
                wan_like += 1
        dominant = max(type_stats, key=type_stats.get) if type_stats else ""
        top = items[0] if items else {}
        topics_out.append(
            {
                "id": topic_id,
                "name": t.get("name"),
                "enabled": t.get("enabled"),
                "item_count": t.get("item_count") or 0,
                "avg_hot_score": round(float(t.get("avg_hot_score") or 0), 1),
                "max_hot_score": round(float(t.get("max_hot_score") or 0), 1),
                "max_liked": max_liked,
                "wan_like_count": wan_like,
                "dominant_content_type": dominant,
                "content_type_breakdown": type_stats,
                "top_title": top.get("title") or "",
                "top_liked": top.get("liked_count") or 0,
                "last_run_at": t.get("last_run_at"),
            }
        )
    return {
        "topics": topics_out,
        "total_items": overview.get("total_items", 0),
        "total_topics": len(topics_out),
    }


def export_topic_items_excel(topic_id: str) -> tuple[str, bytes]:
    topic = intel_service.get_watch_topic(topic_id)
    if not topic:
        raise ValueError("选题不存在")
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = intel_service.list_topic_items(topic_id, page=page, page_size=100)
        items.extend(batch["items"])
        total_pages = int(batch.get("total_pages") or 0)
        if page >= total_pages:
            break
        page += 1
    from intel_excel_export import build_topic_items_excel_bytes

    name = str(topic.get("name") or topic_id).replace("/", "-")
    return name, build_topic_items_excel_bytes(name, items)
