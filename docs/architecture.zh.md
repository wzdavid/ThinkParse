# 架构

ThinkParse 是企业级文档解析**服务**：对外提供统一 API 与任务生命周期，对内把重活交给可水平扩展的解析引擎节点。服务层进程不加载 CUDA；GPU 只出现在 MinerU（或你外部提供的同类引擎）上——这是分布式与多 GPU 扩展的基础，而不是产品定义本身。

产品定位见 [概述](overview.zh.md)。

## 总览

```text
业务应用（RAG / 知识库 / 抽取 / Agent）
        │  /api/v1/*  or  /api/v2/*
        ▼
┌──────────────────────────────────────────────┐
│ ThinkParse 服务层                              │
│  网关  →  任务库  →  协调器                     │
│            对象存储    引擎端口                  │
└──────────────────────────────┬───────────────┘
                               │ HTTP
              ┌────────────────┴────────────────┐
              ▼                                 ▼
     MinerU 4.0（多 GPU）                   Docling Serve
     每卡一个解析进程                        可选，非 PDF
```

### 进程角色

| 角色 | 职责 | 不做什么 |
|---|---|---|
| 网关 | 鉴权、`/api/v1`、`/api/v2`、健康检查 | 不解析、不持有模型、不暴露引擎内部 `/v1` |
| 协调器 | 领取任务、调用引擎、下载产物、投影、重试、取消 | 不对外提供上传以外的长连接解析 |
| MinerU Router | 每卡一个解析进程，进程内共享模型，支撑多 GPU 并行 | 不作为任务真相来源 |
| PostgreSQL | 任务状态、引擎引用、取消、尝试次数 | — |
| 对象存储 | 按 SHA-256 存原文；按任务存产物（MinIO / S3 / 本地目录） | — |

多个协调器可水平扩展：领取任务时用条件更新认领（取消路径另用 `FOR UPDATE SKIP LOCKED`）。GPU 节点可只跑引擎，与 API 机通过共享库与对象存储组成分布式集群。

## 部署模式

服务层三种部署模式相同，都不装 CUDA。差别在是否随 compose 带上 MinerU，以及 MinerU 能接哪些档。`cpu` 与 `gpu` 只能二选一。

| 模式 | `COMPOSE_PROFILES` | MinerU | `/api/v2/tiers` |
|---|---|---|---|
| `external` | 不启用引擎 profile | `MINERU_BASE_URL(S)` 指向已有服务 | 该 MinerU 报告的档位 |
| `cpu` | `cpu` | 一个 CPU worker（ONNX `basic`） | `flash`、`basic` |
| `gpu` | `gpu` | 每张可见 GPU 一个进程；档由 `MINERU_GPU_TIER` 决定 | `standard`：四档；`basic`：`flash`、`basic` |

档位不由部署模式写死。网关定期读每个 MinerU 的 `/v1/tiers`，取可达上游并集，再与 `THINKPARSE_ACCEPTED_TIERS` 求交（缓存约 30 秒）。上游全不可达时退回允许列表，并标 `discovered: false`；任务仍可排队，恢复后再投递。

内存水位：协调器限制已提交给引擎、尚未取回产物的任务；**本地**对象目录空闲过低时拒绝新提交（HTTP 507）。S3/MinIO 由存储侧容量约束，服务层不做本地盘水位检查。

## 档位与兼容参数

`/api/v1` 仍接受旧表单字段，并映射到 MinerU 4.0：

| 旧字段 | 行为 |
|---|---|
| 未传 `backend`，或 `backend=pipeline` | `tier=basic`；`ocr_mode` 取 `method`（默认 `auto`） |
| `method=auto\|txt\|ocr` | `ocr_mode` 同值 |
| `lang` | 传给引擎；引擎忽略时记在任务上，不因此失败 |
| `formula_enable` / `table_enable` | 尽量下传；引擎不支持单独关闭时记警告并继续 |
| `f_dump_content_list` | 忽略开关语义；完成响应始终带 `content_list` |
| `enable_pagination` | 接受但不起作用（不做物理切 PDF） |
| 显式 `tier=flash\|basic\|standard\|advanced` | 仅显式传入才偏离默认；不在当前 `tiers` 中则 400 |

约定：

- `/api/v1` 默认档始终是 `basic`。GPU 能跑 `standard` 不代表兼容客户端应改默认。
- `advanced` 仅 `/api/v2`；`/api/v1` 拒绝。
- `flash` 在 `/api/v1` 需 `LEGACY_ALLOW_FLASH=true`；其块结构未必满足依赖完整 `content_list` 的调用方。

## 数据模型

- **blobs** — `sha256`、字节数、存储键；相同内容只存一份。
- **tasks** — 对外 ID、blob、文件名、选项、档位、引擎、状态、错误、时间戳、尝试次数、上游 job、取消标记等。
- **artifacts** — 按任务存 `markdown`、`content_list_v1`、`middle_pdf_info`、`middle_native`、`image`、`docling_document` 等。
- **engine_routes** — 按后缀 / 引擎名路由到适配器。

任务状态机（内部）：

```text
accepted → dispatching → running → projecting → completed
                │            │          │
                │            │          └→ failed
                │            └→ failed（上游失败且尝试用尽）
                └→ cancelled
         running → dispatching（上游 ID 失效且原文仍在）
```

`projecting` 在 `/api/v1` 上仍报告 `processing`，避免客户端在投影未完成时读到空结果。

## 协调循环

每个协调器循环大致为：

1. 从待投递队列选出可放入的任务并条件认领（取消待处理任务另走 `SKIP LOCKED`）。
2. 上游槽位或在途字节已满则留下任务。
3. 按 SHA-256 创建或复用上传（引擎侧秒传不可靠；ThinkParse 侧去重是持久的）。
4. `POST` 上游 parse job，保存 `upstream_job_id`，进入 `running`。
5. 轮询终态，把产物写入对象存储。
6. 运行投影器；成功才标 `completed`。
7. 上游 ID 丢失 / 连接失败 / 健康检查失败且未超重试：清空上游 ID，退避后重投。
8. `cancel_requested` 时取消上游并标 `cancelled`。

MinerU 明确拒绝的请求（多数 HTTP 4xx）直接失败，不重试；连不上、5xx、限流才退避重试。

## 投影器

投影器是兼容层的核心。输入是引擎原生产物，输出是 `/api/v1` 完成响应所需字段，并写入 `artifacts`。

MinerU 投影要点：

1. MinerU 的完整结果是 zip。协调器只下载这一份，解出 `markdown.md`、`middle_json.json` 和 `images/`。Markdown 与表格 HTML 引用这些文件名，不能残留 `data:image`。缺文件或仍内嵌 data URL 时任务失败。
2. `content_list` 映射为调用方可消费的 v1 元素（正文、标题、图片、表格、公式、废弃块等）。黄金样本在 `tests/fixtures/legacy_projection/`。
3. `middle_json` 对外只输出投影后的 `pdf_info` 形状（含 `page_size`、`discarded_blocks`），**不**带 `schema: docvortex.middle` 信封。原生 middle 存为 `middle_native` 产物。
4. 投影失败即任务失败，不允许 `completed` + 残缺 JSON。

Docling 投影：原生 JSON 存为 `docling_document`；不把 DoclingDocument 伪装成 MinerU `content_list`。

## 引擎端口

```text
EngineAdapter
  health() / submit() / poll() / fetch() / cancel()

Projector
  project(native) -> LegacyView
```

路由规则（种子）：

| 输入 | 适配器 |
|---|---|
| `.pdf`、常见图片 | `mineru` |
| `.xml`（JATS）、`.tex`、`.eml` | `docling`（需 `DOCLING_BASE_URL`） |

同一篇 PDF 不扇出到两个引擎。需要对比时，对同一 blob 再提交一次并指定引擎，用两个任务 ID 分开存。

## 可靠性

| 事件 | 行为 |
|---|---|
| 网关重启 | 无状态；任务在数据库 |
| 协调器重启 | 锁过期后其他协调器接手，用上游 ID 继续轮询 |
| MinerU 重启 | 上游 ID 失效则用对象存储原文重投，对外 ID 不变 |
| 投影崩溃 | 停在 `projecting`，重跑投影，尽量不重新解析 |
| 取消 | 持久标记；重投前检查，避免取消后又解析 |
| 磁盘满 | 本地目录对象存储拒绝新提交（HTTP 507）。MinIO 由卷容量限制，提交时不探测剩余空间 |

单任务超时默认可覆盖长论文（默认 7200 秒，可配置）。上传、临时文件和解析结果都有期限，ThinkParse 不永久保存这些字节。期限、存放位置和清理动作见 [文件清理](cleanup.zh.md)。

## 分布式与多 GPU

- **多 GPU（单机）**：MinerU Router 的 `--local-gpus auto` 为每张可见卡起一个解析进程；ThinkParse **不**按 device id 绑核，只用 `THINKPARSE_SLOTS`（建议 = 卡数 × 每卡在途）与在途字节闸放行任务。
- **多机 / 多引擎**：网关与协调器连接同一 Postgres 与同一对象存储；每台 GPU 机器只跑引擎。配置多个 `MINERU_BASE_URLS` 时，按在途数与档位能力分摊。
- **大批量**：用 `/api/v2` 批次与 `/api/v2/stats` 看吞吐与积压，而不是逐任务盯日志。

观测与槽位细节见 [运维与算力](operations.zh.md)。API 约定见 [API 参考](api.zh.md)。
