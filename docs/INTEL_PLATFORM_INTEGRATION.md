# 内容情报中心 — 接入物料生产平台设计（暂缓实施）

> 本文档只描述设计，当前不实施。目标是在不返工的前提下，把 `xhs-note-extractor`
> 已经跑通的本地"内容情报中心"（热点雷达 + 自有内容追踪）未来平滑接入物料生产
> 平台（下文简称"主平台"）。

## 1. 现状（已在本地实现）

```
xhs-note-extractor/
├── intel_db.py          # SQLite schema + 连接管理（output/intel.db）
├── intel_service.py     # 业务逻辑：选题 CRUD、抓取、指标快照、追踪刷新
├── intel_scheduler.py   # 后台线程轮询，按 interval_minutes 触发选题抓取
├── intel_api.py         # FastAPI 路由，挂载在 /api/intel/* 下
└── static/intel.js      # "内容情报" Tab 前端（选题管理 / 雷达 / 自有内容追踪）
```

数据表：

- `watch_topics`：热点选题（关键词 + 平台 + 抓取频率）
- `intel_items` + `metric_snapshots`：雷达抓到的第三方内容 + 历史指标快照
- `tracked_posts` + `tracked_metric_snapshots`：自己发布的内容 + 历史表现快照

这套东西目前是**单机单进程**、**无鉴权**、**无租户隔离**的本地工具，服务于"先跑
通"的目标。以下设计是把它接入主平台时需要补的部分。

## 2. 接入方式：优先"作为服务被调用"，而非"重写"

不建议把 `intel_service.py` 的逻辑搬进主平台重写一遍。推荐把当前 FastAPI 服务
原样部署为主平台的一个内部微服务（"content-intel-service"），主平台通过 HTTP
调用它，原因：

- 抓取逻辑强依赖 CDP 登录态 / Playwright / Whisper 本地模型，这些运行时依赖跟
  主平台（很可能是纯后端 + 前端的 Web 服务）分离更干净。
- 现有 API 已经是平台无关的 JSON 接口，天然适合作为内部服务。

## 3. 需要新增/调整的接口（当前未实现）

### 3.1 发布回调：自动登记追踪内容

主平台发布一篇小红书笔记 / 视频号内容成功后，调用：

```
POST /api/intel/tracked
{
  "platform": "xhs" | "channels",
  "url": "...",                 // 发布后可访问的链接
  "account_name": "...",
  "title": "...",
  "published_at": "2026-07-07 12:00:00",
  "external_content_id": "主平台内容库的 content_id",   // 待新增字段
  "external_account_id": "主平台账号库的 account_id"     // 待新增字段
}
```

`tracked_posts` 表已预留 `external_content_id` / `external_account_id` 两列，
用于跟主平台的内容 ID / 账号 ID 做映射，避免在情报侧重复维护一套账号体系。
目前这两个字段建库时预留，`intel_api.py` 尚未在请求体中收字段——接入时只需在
`TrackedPostCreate` 增加这两个可选字段并透传到 `register_tracked_post`。

### 3.2 主平台拉取雷达数据（选题灵感）

```
GET /api/intel/radar?platform=xhs&limit=20
GET /api/intel/radar/summary?topic_id=xxx
```

已经实现，可直接给主平台的选题/生成模块使用。建议主平台侧做一层轻量缓存
（如 5 分钟），避免选题页面每次刷新都直连本服务。

### 3.3 主平台推送"内容库热词"作为选题种子（可选，反向数据流）

主平台如果已经有一套内容策略 / 关键词库，可以调用：

```
POST /api/intel/watch-topics
{ "name": "...", "platforms": [...], "keywords": [...], ... }
```

把主平台的选题策略同步为本服务的抓取任务，替代人工在情报中心手工建选题。

## 4. 鉴权 / 多租户（当前完全没有，需要在接入前补）

现状：`intel_api.py` 没有任何鉴权，任何能访问 8765 端口的请求都能读写。接入
主平台前至少要做：

1. **服务间鉴权**：在 `intel_api.py` 加一个基于共享 Secret 的请求头校验
   （如 `X-Intel-Service-Token`），主平台调用时携带；本地开发环境可用环境变量
   `INTEL_SERVICE_TOKEN` 关闭校验。
2. **租户隔离**（如果主平台是多租户/多账号体系）：`watch_topics` /
   `tracked_posts` 需要加 `tenant_id` 列，所有查询按 `tenant_id` 过滤。当前
   schema 未加这一列，属于一次性迁移工作，建议在真正接入前、数据量还小的时候
   做，避免以后大表迁移。

## 5. 部署形态（建议，暂不实施）

短期（仍是单机，接入验证阶段）：

- 主平台通过内网 HTTP 直接调用 `http://intel-host:8765/api/intel/*`。
- `output/intel.db`（SQLite）足够支撑单机场景；不需要现在就上 Postgres。

中期（数据量 / 并发上来之后再做，不是现在的优先级）：

- SQLite → Postgres：`intel_db.py` 里所有 SQL 都是标准 SQL，迁移主要是连接层
  换成 `psycopg`/SQLAlchemy，业务逻辑（`intel_service.py`）基本不用动。
- 抓取任务从"进程内线程轮询"（`intel_scheduler.py`）换成独立 worker /
  消息队列，避免和 Web 服务抢资源。

## 6. 明确不做的事情（Non-goals，当前阶段）

- 不做多租户 / 权限系统（除非主平台明确要求先做）。
- 不迁移数据库引擎（SQLite 在当前数据量下完全够用）。
- 不把 `intel_service.py` 的抓取逻辑拆成独立可水平扩展的微服务（抓取量级还
  没到需要扩容的程度）。

## 7. 落地顺序建议

1. 先在本地把"热点雷达 + 自有内容追踪"跑顺（已完成，见本仓库 `v1.7.9`）。
2. 主平台侧确定"发布成功后要不要自动追踪"的产品决策 → 若要，实现第 3.1 节的
   回调对接（工作量：约半天，主要是给 `TrackedPostCreate` 加两个字段 + 联调）。
3. 视主平台安全要求，决定是否需要第 4 节的服务间鉴权（如果只是内网调用，可以
   先跳过，等真正暴露公网接口前再补）。
4. 数据量 / 团队规模明显增长后，再评估第 5 节的中期部署形态调整。
