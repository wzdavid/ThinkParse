# 运维与算力

ThinkParse 作为企业级解析服务，本身不加载 CUDA；GPU、显存和 PDF 渲染在引擎节点。运维侧要做好两件事：**看见大批量任务卡在哪**，以及**按每台上游的真实槽位与内存预算放行**，从而稳住多 GPU / 分布式吞吐。

相关接口字段见 [API 参考](api.zh.md)。

## 原则

- **单机多 GPU 靠引擎 Router。** MinerU `--local-gpus auto` 每张可见卡一个进程；ThinkParse 只控槽位与在途字节，不按 device id 绑任务。
- **每卡在途起点是 2。** 加大时每次加 1，看显存、宿主内存和吞吐；顶满就停。
- ThinkParse **不读** `nvidia-smi`，也不在运行中改 MinerU `--worker-concurrency`。观测告诉你该不该改 `.env` 后重建引擎容器。
- 日志与统计不含文档正文，不返回上游 `job_id`。
- `/api/v1` 已有字段不改；新能力只加在 `/api/v2`。
- 不为填满 GPU 把 `/api/v1` 默认档改成 `standard` / `advanced`。
- 数值库线程与 PDF 渲染线程保持 1；吃 CPU 靠提高 worker 在途，不靠把线程改回核数。
- 排队按 `priority` 降序，同优先级按创建时间。只调度尚未交给引擎的任务，不打断正在解析的任务。在途字节闸只在同一优先级内跳过过大文件，低优先级小文件不能插到被挡住的高优先级任务前面。

## 观测

### 任务三段时间

`GET /api/v2/jobs/{id}`：

| 字段 | 含义 |
|---|---|
| `timing.queue_ms` | `started_at - created_at`；仍在排队则为空 |
| `timing.parse_ms` | 上游解析耗时 |
| `timing.project_ms` | 投影写回耗时 |
| `attempt` | 已重试次数 |
| `pages` | 投影得到的页数 |
| `batch_id` | 客户端批次标签 |

排队久、解析短 → 槽位不够。解析久、页数多 → 文档重。投影久 → ThinkParse 写回慢，不是 GPU。

### 机群快照

`GET /api/v2/stats`（通常需 API key）。数字来自当前状态与最近时间窗（默认 900 秒，`window_seconds` 可调，上限 3600），不是进程启动以来的累计。

关注：

- `queue.*` — `accepted` / `dispatching` / `running` / `projecting`
- `slots.used` / `slots.total`
- `inflight_bytes` / `inflight_byte_limit`
- `oldest_queued_seconds`
- `completed_in_window` / `pages_in_window` / `by_tier`
- `upstreams[]` — 健康、档位、在途、槽位（不暴露内部 URL，按下标对应配置顺序）
- `reconciler_heartbeat_age_seconds` — 心跳年龄持续变大且 `accepted` 在涨，说明协调循环停了

大批量看 `/api/v2/stats` 和批次，不要逐个轮询。`/api/v2/health` 只回答能不能接流量。

### 批次

`POST /api/v2/jobs` 可带 `batch_id`（字母数字 `-` `_`，最长 64）。

- `GET /api/v2/batches/{id}` — 计数与排队年龄
- `GET /api/v2/batches/{id}/jobs?status=failed` — 待重跑
- `DELETE /api/v2/batches/{id}` — 取消未终态任务；已完成保持 `completed`

### 日志

协调器在状态变化时打 JSON 行：`task_id`、`batch_id`、前后状态、`attempt`、`tier`、上游下标、分段毫秒、失败原因。stdout 交给 `docker logs`。本期不捆绑 Prometheus；同一份聚合以后可原样暴露。

## 算力闸门

放行在协调器领任务时发生。网关负责拒绝不可用档位；本地对象目录空间不足时返回 HTTP 507。

### 槽位

| 部署 | 槽位 |
|---|---|
| `gpu`，一个 Router | 可见 GPU 数 × `MINERU_GPU_CONCURRENCY`；由 `.env` 的 `THINKPARSE_SLOTS` 写出。不写则用 `THINKPARSE_MAX_INFLIGHT`（默认 4） |
| `cpu`，一个 Router | `MINERU_CPU_CONCURRENCY`（默认 1）；compose 里 `THINKPARSE_SLOTS` 与之对齐 |
| `external`，多地址 | `THINKPARSE_SLOTS` 逗号列表，与 `MINERU_BASE_URLS` 一一对应；缺省每台用 `THINKPARSE_MAX_INFLIGHT` |

某台 `inflight < slots` 才向它投递。任务停在 `accepted`，不失败。

`oldest_queued_seconds` 升高，同时每台 `inflight < slots` 且 `healthy` → 先查协调器心跳。`inflight` 顶满且排队涨 → 才考虑把每卡在途从 2 调到 3，重建 MinerU，并重复 [部署](deployment.zh.md) 中的资源记录。

### 在途字节

第二道闸：`THINKPARSE_INFLIGHT_BYTE_LIMIT`（默认 1 GiB），用**原文字节**近似渲染内存。再领一篇会超限时，留下这篇，优先更小的；都挑不动则本轮不领。这不是 cgroup 上限，也读不到显存。

### 档位路由

公布档位 = 可达上游并集 ∩ `THINKPARSE_ACCEPTED_TIERS`。投递只选声明了该档的上游，再选在途最少且字节限额够的一台。`standard` / `advanced` 不会送到只有 `flash`/`basic` 的 CPU。全部上游暂时不可达时，`discovered: false`，任务排队，恢复后按当时档位重选。

## 调参检查清单

1. `/api/v2/health` 上游 healthy，`tiers.discovered` true。
2. 单任务在途 1 跑通，记录 `nvidia-smi` 与 `free`。
3. 需要更高吞吐时：`MINERU_*_CONCURRENCY` 与 `THINKPARSE_SLOTS` 同步 +1。
4. 观察 `stats.slots`、`inflight_bytes`、`oldest_queued_seconds`、失败原因。
5. 内存或显存顶满 → 回退，而不是加第三个模型进程。

## 明确不做

- 不在 ThinkParse 里按 device id 绑任务
- 不根据利用率自动改 MinerU 并发或重启容器
- 不把默认每卡在途拉到 12
- 不加 Prometheus / Grafana 等新依赖作为硬性要求
