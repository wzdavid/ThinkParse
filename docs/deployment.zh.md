# 部署指南

ThinkParse 支持 CPU 试用、单机多 GPU，以及 API 与引擎分机的分布式部署。先选一种模式再启动；`cpu` 与 `gpu` 不要同时开。产品背景见 [概述](overview.zh.md)；架构见 [架构](architecture.zh.md)。

对外只有 `/api/v1` 与 `/api/v2`。引擎原生 `/v1` 不对外。

## 进程与端口

| 进程 | 启动方式 | 地址 | 作用 |
|---|---|---|---|
| ThinkParse 网关 | `docker/docker-compose.yml` | `0.0.0.0:8000` | 客户端入口 |
| ThinkParse 协调器 | 同一 compose | 不对外 | 投递、轮询引擎、投影 |
| PostgreSQL | 同一 compose | 仅 compose 网络 | 任务状态 |
| 对象目录 | 同一 compose 的卷 `thinkparse_objects` | 不映射宿主机 | 原文与结果。多机改为外部 S3，compose 不另起对象服务 |
| MinerU | `cpu`，或 `gpu` / `gpu,gpu1` | 一张卡：`mineru-router:8002`。两张卡：`mineru-gpu0:8002` 与 `mineru-gpu1:8002` | 每个容器只看见一张卡。`external` 模式不启动 |

客户端只访问 **8000**。MinerU `8002` 不映射到宿主机。

## 1. 选择模式并启动

在仓库根目录：`cp .env.example .env`，然后只选一种：

| 模式 | `.env` | 宿主机要求 | 档位 |
|---|---|---|---|
| `gpu` | 一张卡：`COMPOSE_PROFILES=gpu`。两张卡：`COMPOSE_PROFILES=gpu,gpu1`，并设置下面的 `MINERU_BASE_URLS` 与 `THINKPARSE_SLOTS` | Docker、CUDA 可用的 NVIDIA 驱动、NVIDIA Container Toolkit | `MINERU_GPU_TIER=standard`：四档；`=basic`：`flash`、`basic`（不下载 VLM，适合小显存） |
| `cpu` | `COMPOSE_PROFILES=cpu` | Docker | `flash`、`basic` |
| `external` | 清空 `COMPOSE_PROFILES`，设置 `MINERU_BASE_URL(S)` | Docker | 该 MinerU 报告的档位 |

`external` 下不要保留 `http://mineru-router:8002`（该名只在 cpu/gpu profile 存在）。同机 MinerU 可用 `http://host.docker.internal:<端口>`。多台用 `MINERU_BASE_URLS`，逗号分隔。

同时写 `cpu,gpu` 时 compose 会因容器名冲突拒绝启动——这是故意的。

启动前修改 `POSTGRES_PASSWORD`。密码拼进连接串时请只用字母数字。

单机不设 `THINKPARSE_S3_ENDPOINT`。网关和协调器共用卷 `thinkparse_objects`。多机时网关与协调器必须设同一个外部 S3 的 endpoint、密钥和桶名；本地卷在设了 endpoint 之后不再被使用。

构建源默认 Docker Hub / PyPI。国内可按 `.env.example` 设置 `MINERU_*_BASE_IMAGE`、`CONTROL_BASE_IMAGE`、`PIP_INDEX_URL`。模型默认 `modelscope`，海外可设 `MINERU_DOWNLOAD_SOURCE=huggingface`。

```bash
docker compose --env-file .env -f docker/docker-compose.yml config --services
docker compose --env-file .env -f docker/docker-compose.yml up -d --build
```

先用 `config --services` 确认：一张卡有 `mineru-gpu0`，两张卡还有 `mineru-gpu1`，`cpu` 有 `mineru-cpu`，`external` 没有这些引擎。

第一次构建：

- `gpu` 镜像下载 `MINERU_GPU_TIER` 所需模型；`standard` 含 VLM。
- `cpu` 镜像只下载 ONNX `basic`。

`up` 会等 MinerU 健康后再起网关（`start_period` 约 600 秒）。

### 并发起点

- `gpu`：每个 MinerU 容器只绑定一张卡，容器内 `--local-gpus auto` 只会看到这一张。`MINERU_GPU_CONCURRENCY` 是这一张卡上的在途数，默认 2。两张卡要同时写 `COMPOSE_PROFILES=gpu,gpu1`。
- `cpu`：单 worker；`MINERU_CPU_CONCURRENCY` 默认 1。
- 窗口默认 8；PDF 渲染与数值库线程默认 1。

ThinkParse 按**每个 MinerU 地址**的槽位放行。未写 `THINKPARSE_SLOTS` 时，每个地址用 `THINKPARSE_MAX_INFLIGHT`（默认 4）。两张卡时写成和 `MINERU_BASE_URLS` 等长的列表，每一项等于 `MINERU_GPU_CONCURRENCY`，例如并发 2 则 `THINKPARSE_SLOTS=2,2`。在途原文另有字节闸：`THINKPARSE_INFLIGHT_BYTE_LIMIT`（默认 1 GiB）。占用见 `GET /api/v2/stats`。

两张卡的 `.env`：

```bash
COMPOSE_PROFILES=gpu,gpu1
MINERU_BASE_URLS=http://mineru-gpu0:8002,http://mineru-gpu1:8002
MINERU_GPU_CONCURRENCY=2
THINKPARSE_SLOTS=2,2
```

`MINERU_BASE_URL` 不要写成逗号列表。同一个 Router 看见两张卡时，协调器的上传会固定落在其中一张卡上，另一张卡的利用率会一直是 0。

```bash
docker compose --env-file .env -f docker/docker-compose.yml ps
curl -sS http://127.0.0.1:8000/api/v2/tiers
```

- `discovered: true`：已从上游读到档位。
- `discovered: false`：上游尚未可达，列表只是配置允许值；先排障再压测。

同一台机器上的两张卡用两个 MinerU 地址。多台机器同样用 `MINERU_BASE_URLS`，每台机器上的每张卡各一个地址。

`/api/v1` 默认档始终是 `basic`。GPU 能跑 `standard` 不等于应改兼容客户端的默认档。

## 2. 健康检查

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/live
curl -sS -D - http://127.0.0.1:8000/api/v1/health/ready -o /tmp/thinkparse-ready.json
cat /tmp/thinkparse-ready.json
```

`live` 应为 200。`ready` 在 MinerU 可达时为 200，否则 503。两种情况下 `components.task_store` 与 `components.object_store` 都应为 `true`。`components.mineru` 为 `false` 时不要提交作业。

负载均衡探活推荐 `GET /api/v2/health`（可不带 API key）。更深信息见 `/api/v1/health/deep`。

## 3. 整篇 PDF 往返

用仓库样例 `tests/files/2604.04771v2.pdf`（43 页）做验收。开发机上不要用「只解析几页」代替整篇 GPU 验收。

```bash
curl -sS \
  -F "file=@tests/files/2604.04771v2.pdf" \
  -F "backend=pipeline" \
  http://127.0.0.1:8000/api/v1/tasks/submit
```

响应应为 `pending` 并返回 `task_id`。不要传 `tier=standard` 或 `backend=vlm` 做第一轮兼容验收。

```bash
TASK_ID=<task_id>
while true; do
  BODY=$(curl -sS "http://127.0.0.1:8000/api/v1/tasks/${TASK_ID}")
  STATUS=$(printf '%s' "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["task"]["status"])')
  echo "$STATUS"
  case "$STATUS" in
    completed|failed|cancelled) printf '%s\n' "$BODY" > /tmp/thinkparse-task.json; break ;;
  esac
  sleep 5
done
```

默认超时 7200 秒。内部 `projecting` 对外仍是 `processing`。

建议同时记录资源基线（在途为 1 时）：

```bash
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv
free -h
curl -sS http://127.0.0.1:8000/api/v1/health/deep
```

## 4. 完成响应核对

第 3 步结束时，整份响应在 `/tmp/thinkparse-task.json`。不要直接打开这个文件：`images[].data_url` 是图片字节，样例论文大约几十张图，文件会到数十 MB。用下面的脚本看摘要。

```bash
python3 - <<'PY'
import json
from pathlib import Path

body = json.loads(Path("/tmp/thinkparse-task.json").read_text())
task = body["task"]
middle = body.get("middle_json") or {}
info = middle.get("pdf_info") or []
content = body.get("content_list") or []
images = body.get("images") or []
markdown = body.get("markdown_content") or ""
equations = [item for item in content if item.get("type") == "equation" and item.get("text")]
tables = [item for item in content if item.get("type") == "table" and "<table" in (item.get("table_body") or "")]
header = ""
for page in info:
    for block in page.get("discarded_blocks") or []:
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                text = span.get("content") or ""
                if "2604.04771" in text:
                    header = text
print("status", task.get("status"))
print("error_message", task.get("error_message"))
print("pages", len(info), "page_size", info[0].get("page_size") if info else None)
print("schema_key", "schema" in middle)
print("equations", len(equations), "html_tables", len(tables))
print("markdown_chars", len(markdown), "same_as_data.content", markdown == (body.get("data") or {}).get("content"))
print("data_image_in_markdown", markdown.count("data:image"))
print("images", len(images), "first", None if not images else {k: images[0][k] for k in ("filename", "mime_type", "size_bytes")})
print("header", header or "(样例页眉未找到)")
PY
```

样例 `tests/files/2604.04771v2.pdf` 在 `basic` 档通过时，大致应看到：

- `status` 为 `completed`，`error_message` 为 `None`
- `pages` 为 43，`page_size` 不是 `[0, 0]`，`schema_key` 为 `False`
- `equations`、`html_tables` 都大于 0
- `same_as_data.content` 为 `True`，`data_image_in_markdown` 为 0
- `images` 大于 0；每项在 JSON 里还有 `data_url`，脚本故意不打印它
- `header` 含 `arXiv:2604.04771`

正文在 `markdown_content`。要阅读而不是核对时，另存成 Markdown：

```bash
python3 -c 'import json; from pathlib import Path; body=json.loads(Path("/tmp/thinkparse-task.json").read_text()); Path("/tmp/thinkparse-result.md").write_text(body["markdown_content"])'
```

图片不要从 `data_url` 里肉眼看。`/api/v2` 的完成任务给出 `output_files.images[].file_id`，用 `GET /api/v2/files/{file_id}/content` 下载单张。任务 JSON 本身不含 base64。

投影形状的夹具在 `tests/fixtures/legacy_projection/`。

## 5. 接到业务系统

验收通过、且显存 / 内存未顶满后，再把上游应用的解析 base URL 指到 `http://<host>:8000`。不要为了「填满 GPU」一次性把并发拉到很高：每次只加 1，并重复第 3 节的资源记录；内存先顶满就停。

加大并发时同时关注 `MINERU_GPU_CONCURRENCY`（或 CPU 对应项）与 `THINKPARSE_SLOTS` / `THINKPARSE_MAX_INFLIGHT`。详见 [运维与算力](operations.zh.md)。

## 6. 排障

| 现象 | 含义 |
|---|---|
| `ready` 503，`mineru` false | MinerU 未健康、未启用 profile，或 `external` URL 错误。看 `logs mineru-gpu` / `mineru-cpu` |
| `tiers.discovered` false | 读不到任何上游 `/v1/tiers` |
| 提交 400，`not available in this deployment` | 当前部署无该档 |
| `failed`，错误来自上游拒绝 | MinerU 4xx；不重试 |
| `failed`，upstream unavailable | 解析中途上游退出或 URL 错误；compose 内应为 `http://mineru-router:8002` |
| 一直 `processing` | 协调器未跑或仍在解析：`logs -f reconciler` |
| `completed` 但缺 `content_list` | 投影异常；应标失败。若仍 completed，保留响应 JSON |
| 提到 advanced / flash 的 400 | `/api/v1` 拒 `advanced`；`flash` 需 `LEGACY_ALLOW_FLASH=true` |
| `.xml` / `.tex` / `.eml` 400 | 未配置 `DOCLING_BASE_URL` |

```bash
docker compose --env-file .env -f docker/docker-compose.yml logs -f gateway reconciler mineru-gpu
docker compose --env-file .env -f docker/docker-compose.yml down      # 保留卷
# down -v 会删除任务与产物
```

## 7. 第一轮不要做的事

- 不要把 `/api/v1` 默认档改成 `standard` 或 `advanced`
- 不要同时启用 `cpu` 和 `gpu`
- 不要用 `LEGACY_ALLOW_FLASH` 代替 `basic` 做首轮验收（`flash` 公式文本可能为空）
- 不要把每卡在途或全局槽位默认拉到 12；起点是每卡 2
- Docling 不在 PDF 首轮验收路径里
