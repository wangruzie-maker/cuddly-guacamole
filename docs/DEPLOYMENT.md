# 部署与本地运行

本项目默认支持两种形态：

- 本地开发/自用（默认）
- 线上部署（同事可通过公网地址访问）

## 1) 本地运行（推荐先验证）

```bash
cd xhs-note-extractor
cp .env.example .env
# 本地建议改回 127.0.0.1，避免暴露到局域网
sed -i '' 's/^APP_HOST=.*/APP_HOST=127.0.0.1/' .env
sed -i '' 's/^APP_RELOAD=.*/APP_RELOAD=1/' .env
./run_web.sh
```

打开 `http://127.0.0.1:8765`。

## 2) 线上部署（云服务器）

### 环境变量

```bash
cp .env.example .env
```

建议线上值：

- `APP_HOST=0.0.0.0`
- `APP_PORT=8765`
- `APP_RELOAD=0`
- `APP_CORS_ORIGINS=https://your-domain.com`

> 可先用 `*` 验证，稳定后改成你的前端域名列表（英文逗号分隔）。

### 启动命令

```bash
cd xhs-note-extractor
pip3 install -r requirements.txt
set -a && source .env && set +a
python3 -m uvicorn web_server:app --host "$APP_HOST" --port "$APP_PORT"
```

## 3) 给同事 GitHub 下载即用

同事拿到仓库后：

1. `cp .env.example .env`
2. 按本地场景把 `APP_HOST` 改为 `127.0.0.1`，`APP_RELOAD=1`
3. `./run_web.sh`

无需配置“远程采集小助手”，每个人都在自己机器上使用同一套主应用流程即可。
