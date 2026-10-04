# 快速开始

目标：在本机用 Docker 拉起 ThinkParse（企业级文档解析服务），提交一篇 PDF，拿到 `completed` 结果。这是单机入口；多 GPU 与分布式见 [部署](deployment.zh.md) 与 [运维与算力](operations.zh.md)。

## 1. 准备

- Docker / Docker Compose
- GPU 模式：能跑 CUDA 的 NVIDIA 驱动 + NVIDIA Container Toolkit
- 仓库样例 PDF：`tests/files/2604.04771v2.pdf`（43 页）

```bash
git clone https://github.com/wzdavid/ThinkParse.git
cd ThinkParse
cp .env.example .env
```

编辑 `.env`，只选一种模式：

| 你有什么 | 设置 |
|---|---|
| NVIDIA GPU | `COMPOSE_PROFILES=gpu` |
| 只有 CPU | `COMPOSE_PROFILES=cpu` |
| 已有 MinerU 4.0 | 删掉 / 清空 `COMPOSE_PROFILES`，把 `MINERU_BASE_URL` 改成可达地址 |

启动前修改 `POSTGRES_PASSWORD`。密码会拼进连接串，请只用字母和数字。

国内构建可按 `.env.example` 注释设置镜像与 PyPI 源；模型默认 `modelscope`，海外可设 `MINERU_DOWNLOAD_SOURCE=huggingface`。

## 2. 启动

```bash
docker compose --env-file .env -f docker/docker-compose.yml config --services
docker compose --env-file .env -f docker/docker-compose.yml up -d --build
```

`config --services` 应看到：

- `gpu` → 含 `mineru-gpu0`（双卡再开 `gpu1` 时还有 `mineru-gpu1`）
- `cpu` → 含 `mineru-cpu`
- `external` → 没有上述引擎服务

第一次构建会下载模型，GPU `standard` 档还包含 VLM 权重，耗时可能较长。`up` 会等 MinerU 健康（`start_period` 最长约 600 秒）再起网关。

## 3. 确认就绪

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/live
curl -sS http://127.0.0.1:8000/api/v1/health/ready
curl -sS http://127.0.0.1:8000/api/v2/tiers
```

期望：

- `live` → HTTP 200
- `ready` → MinerU 可达时 200；`components.task_store` 与 `components.object_store` 为 `true`
- `tiers` → `discovered: true`，且列表与模式匹配（`cpu` 通常只有 `flash`、`basic`）

## 4. 提交并轮询

```bash
curl -sS \
  -F "file=@tests/files/2604.04771v2.pdf" \
  -F "backend=pipeline" \
  http://127.0.0.1:8000/api/v1/tasks/submit
```

记下返回的 `task_id`。`backend=pipeline` 映射到 MinerU `basic`，这是兼容接口的默认质量档。

```bash
TASK_ID=<task_id>
while true; do
  BODY=$(curl -sS "http://127.0.0.1:8000/api/v1/tasks/${TASK_ID}")
  STATUS=$(printf '%s' "$BODY" | python -c 'import json,sys; print(json.load(sys.stdin)["task"]["status"])')
  echo "$STATUS"
  case "$STATUS" in
    completed|failed|cancelled) printf '%s\n' "$BODY" > /tmp/thinkparse-task.json; break ;;
  esac
  sleep 5
done
```

对外状态：`pending`、`processing`、`completed`、`failed`、`cancelled`。内部投影阶段对外仍显示 `processing`，请继续等。

完成时响应顶层应包含 `markdown_content`、`content_list`、`middle_json`、`images`。字段约定见 [API 参考](api.zh.md)。

## 5. 用产品接口（可选）

`/api/v2` 把上传、任务、产物拆开。若设置了 `THINKPARSE_API_KEY`，请求需带 `Authorization: Bearer <key>`。

典型顺序：

1. `POST /api/v2/uploads` → `PUT .../content` → `POST .../complete`
2. `POST /api/v2/jobs`（返回 202）
3. `GET /api/v2/jobs/{id}` 直到完成
4. `GET /api/v2/files/{id}/content` 取产物

## 常见问题

| 现象 | 处理 |
|---|---|
| `ready` 503，`mineru` 为 false | 看 MinerU 日志；`external` 时检查 URL 是否仍是 compose 内网名 |
| `tiers.discovered` 为 false | 网关读不到上游 `/v1/tiers`，任务会排队但不该继续压测 |
| 提交 400，`not available in this deployment` | 当前部署没有该档（例如 CPU 上没有 `standard`） |
| 任务一直 `processing` | 查看 `reconciler` 日志；确认协调器容器在跑 |

```bash
docker compose --env-file .env -f docker/docker-compose.yml logs -f gateway reconciler
```

停止服务（保留数据卷）：

```bash
docker compose --env-file .env -f docker/docker-compose.yml down
```

加 `-v` 会删除任务库与对象存储数据。
