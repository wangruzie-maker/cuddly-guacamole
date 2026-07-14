# 社媒内容提取 & 内容情报中心

本地运行的小红书 / 视频号内容提取工具，内置「内容情报」模块：选题采集、爆款分析、选题包导出。

## 3 步上手

```bash
cd xhs-note-extractor
cp .env.example .env
pip3 install -r requirements.txt
./open_app.sh
```

浏览器打开 `http://127.0.0.1:8765`，切换到 **内容情报** Tab：

1. **登录小红书** — 点击顶栏「登录小红书」，在 Chrome 扫码
2. **创建选题** — 填名称和关键词，或从「预设模板」一键创建 → 点「运行一次」
3. **查看爆款** — 每个选题卡片下独立展示爆款（每页 10 条），可导出选题包 / 生成选题方向

## 主要功能

| 模块 | 说明 |
|------|------|
| 小红书 Tab | 链接提取、OCR、视频转写、关键词发现 |
| 视频号 Tab | 链接提取、口播转写、关键词发现 |
| 内容情报 | 选题定时采集、爆款分页、类型分类、选题包导出、跨选题对标 |

## 内容情报 API（节选）

- `GET /api/intel/watch-topics/{id}/items?page=1&page_size=10` — 选题爆款分页
- `GET /api/intel/watch-topics/{id}/export.md` — 导出选题包 Markdown
- `GET /api/intel/watch-topics/{id}/directions` — 选题方向建议
- `GET /api/intel/templates/search-dimensions` — 预设搜索模板
- `GET /api/intel/analytics/benchmark` — 跨选题对标表

## 依赖说明

- **小红书 CDP**：需安装 [redbook-skills](https://github.com) 到 `~/.cursor/skills/redbook-skills`
- **视频号**：首次使用运行 `./setup_playwright.sh`

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
