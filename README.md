# 社媒内容提取 & 市场能力工作台

本地运行的小红书 / 视频号工具，围绕「获取选题依据 → 选择性转录 → 语料分析 → 得出创作选题 → 发布追踪」组织操作。

## 3 步上手

```bash
cd xhs-note-extractor
cp .env.example .env   # 可选：仅 AI 文案需要填 DEEPSEEK_API_KEY
./ensure_capabilities.sh --manual   # 创建 .venv 并安装依赖（避开系统/uv 托管限制）
./open_app.sh                       # 能力齐全时不会再弹安装提示
```

推荐 Python **3.10–3.12**。依赖一律进入项目 `.venv`，不会改系统/uv 的 Python。

也可双击 **`检测并安装能力.command`**，再双击 **`打开小红书提取工具.command`**。  
发给同事的完整包：`./pack_full.sh`（含 Whisper + redbook-skills）。

浏览器打开 `http://127.0.0.1:8765` 后：

1. **登录小红书** — 点击顶栏「登录小红书」，在 Chrome 扫码
2. **获取依据** — 设置采集深度及互动阈值，按数据筛选参考内容
3. **转录与分析** — 勾选样本批量 OCR/视频转录，查看高频主题、共现和创作选题

## 主要功能

| 模块 | 说明 |
|------|------|
| 获取选题与依据 | 小红书/视频号关键词采集、阈值筛选、依据勾选 |
| 转录与选题分析 | 两个平台手动链接补充、OCR/口播转写、语料可视化、创作选题 |
| 数据追踪 | 跨平台语料资产概览、已发布作品趋势追踪 |

## 内容情报 API（节选）

- `GET /api/intel/watch-topics/{id}/items?page=1&page_size=10` — 选题爆款分页
- `GET /api/intel/watch-topics/{id}/export.md` — 导出选题包 Markdown
- `GET /api/intel/watch-topics/{id}/directions` — 选题方向建议
- `GET /api/intel/templates/search-dimensions` — 预设搜索模板
- `GET /api/intel/analytics/benchmark` — 跨选题对标表

## 依赖说明

- **小红书采集**：已内置 `vendor/redbook-skills`，首次启动同意安装依赖即可；无需再单独装 Cursor skill
- **视频号**：可选运行 `./setup_playwright.sh`
- **定时采集**：默认关闭以减少平台风控；需要时在 `.env` 设置 `INTEL_SCHEDULER_ENABLED=1`

## 线上部署

见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

服务间鉴权（可选）：

```bash
INTEL_SERVICE_TOKEN=your-secret
INTEL_STRICT_AUTH=1   # 仅 API 集成时开启；本地浏览器使用请勿开启
```

## 数据存储

- 提取结果：`output/accumulated.json`
- 情报数据：`output/intel.db`（SQLite）
