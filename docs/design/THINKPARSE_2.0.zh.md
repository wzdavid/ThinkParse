# ThinkParse 2.0 设计方案

状态：设计稿  
日期：2026-09-29  
读者：ThinkParse、ThinkExtract、ThinkDoc

ThinkParse 2.0 是全新的解析控制面。它对接 MinerU 4.0 做执行，用持久任务和对象存储补上 MinerU 明确不做的那一层，并用引擎端口为以后的 Docling 留出位置。对外继续提供现在的 `/api/v1/tasks`，ThinkExtract 和 ThinkDoc 不改代码。

本文按新产品设计。1.x 的 Celery、每卡多个 pipeline 进程、进程内 `do_parse()` 不进入 2.0。

## 1. 要解决的问题

现网把解析扩容理解成「再复制一个带模型的 worker」。在 2 路 5 核、64GB 内存、2 张 RTX PRO 6000 96GB 上，8 个这样的进程会打满内存和 CPU，GPU 仍然吃不饱。降到 6 个只是稳住，没有把 96GB 显存用起来。

原因不在显卡数量：

- MinerU 3.4.5 `pipeline` 的 batch 随「看到的整卡显存」放大。每张 96GB 卡上的每个进程都按整卡开 batch，宿主内存堆的是页面图和 NumPy 副本。
- 每个容器各自加载一整套模型。并行度等于模型份数。
- PDF 渲染和 OCR 的线程按机器核数放大，10 个物理核上会出现运行队列远大于核数的情况。
- pipeline 的 GPU 内核小、突发短，填不满 Blackwell。

MinerU 4.0 已经换成另一种拓扑：`mineru-router` 每张卡一个 `api-server`，进程内一份 VLM，多个文档共用。小模型 `BATCH_RATIO` 固定为 2。档位取代旧 backend：`basic` 对应原 pipeline，`standard` 对应 hybrid（小模型加 vLLM），`advanced` 对应整页 VLM。官方默认档是 `standard`。`basic` 仍是单篇更快的一档；公开评测里 `medium`（即 `basic`）相对 `high`（即 `standard`）综合分大约低 0.13，速度高 35% 到 220%。整页 `advanced` 就是此前判断为慢的那条路，2.0 不把它当默认。

MinerU 4.0 的 HTTP 也换了。`/file_parse` 和 `/tasks` 已移除，改为 `/v1/uploads`、`/v1/parse/jobs`、`/v1/files`。上传、任务、产物是三种资源，状态体不再内嵌整份 Markdown。任务索引在进程内存里，重启后旧 `job_id` 不作数。官方写明这不是可恢复的任务服务。

ThinkExtract 和 ThinkDoc 仍调用 ThinkParse 1.x：

| 调用方 | 提交 | 完成时读取 |
|---|---|---|
| ThinkExtract `document_parser.py` | `POST /api/v1/tasks/submit`，multipart 字段 `file` | `task.status`、`task.error_message`、顶层 `markdown_content`、`content_list`、`middle_json`、`images` |
| ThinkDoc MinerU 路径 | 同上，并带表单 `backend=pipeline`、`lang`、`method=auto`、`formula_enable`、`table_enable`、`f_dump_content_list` | 同上；`MinerUJsonConverter` 用 `content_list` 建 DoclingDocument，Markdown 只是回退 |
| ThinkDoc Docling 路径 | `POST {DOCLING_API_URL}/api/v1/tasks/submit` | 顶层 `docling_document` |

ThinkExtract 的公式物化只在 `content_list` v1 上为 `ready`。`middle.schema == docvortex.middle` 时标为 `unsupported`。DOI 页眉页脚读 `middle.pdf_info[].discarded_blocks`，缺了再扫 `content_list` 里的 discarded 块。2.0 必须在边界上交出这两种形状，不能把 4.0 原文直接透传。

Docling 的 PDF 流水线与 MinerU `basic` 同类，模型目录里还有 `mineru2_pro` 预设。多引擎的价值是按格式分流：PDF 走 MinerU；JATS、LaTeX 源稿、专利、XBRL、邮件以后走 Docling。两个 PDF 引擎不要同时常驻在这台 64GB 机器上。`docling-serve` 自带异步接口和 Redis RQ，2.0 不把 Docling 模型载入 ThinkParse 进程。

## 2. 目标与非目标

目标：

1. 旧客户端不改代码。`/api/v1/tasks`、`/file_parse`、`/api/v1/queue/*`、`/api/v1/health*` 的行为保持可替换。
2. 解析执行只通过 MinerU 4.0 HTTP。ThinkParse 进程不加载 CUDA 模型。
3. 任务、原文、产物在 ThinkParse 侧持久化。MinerU 进程重启后，控制面用已保存的原文重新提交，而不是让客户端看到任务消失。
4. 引擎端口可增加第二个实现。2.0 交付 MinerU 适配器；Docling 适配器留接口和路由表，不在首发加载模型。
5. 在目标机器上，每张 GPU 一个 MinerU worker，在途任务共享这一份模型。并发由显存预算、窗口大小和内存水位决定，不再用「每卡 N 个引擎容器」当旋钮。

非目标：

- 不在 ThinkParse 内重写版面、OCR、公式、表格或 VLM。
- 不把 `advanced`（整页 VLM）设为旧接口的默认档。
- 不在 2.0 首发用 Docling 解析 PDF，也不承诺 Docling 与 MinerU 对同一篇论文做在线打分。
- 不改 ThinkExtract / ThinkDoc 的解析客户端。公式与 DOI 对 4.0 原生 middle 的正式适配留在抽取侧的后续版本；2.0 用投影层挡住这个缺口。
- 不保留 1.x 的物理 PDF 切块合并。长文窗口是 MinerU 的 `MINERU_PROCESSING_WINDOW_SIZE`。

## 3. 总体架构

```text
ThinkExtract / ThinkDoc
        │  POST /api/v1/tasks/submit
        │  GET  /api/v1/tasks/{task_id}
        ▼
┌──────────────────────────────────────────────┐
│ ThinkParse 控制面（无 GPU）                      │
│  兼容网关  →  任务库  →  协调器                   │
│                  │         │                  │
│                  ▼         ▼                  │
│            对象存储      引擎端口                 │
└──────────────────────────┬───────────────────┘
                           │ HTTP
           ┌───────────────┴────────────────┐
           ▼                                ▼
  MinerU 4.0 Router（2.0 交付）          Docling Serve（端口预留）
  GPU0 一个 api-server                 不与 MinerU 共用模型进程
  GPU1 一个 api-server
```

控制面三个进程角色，可以同机，也可以拆开：

| 角色 | 职责 | 不做什么 |
|---|---|---|
| 网关 | 鉴权、`/api/v1` 兼容、`/api/v2` 产品接口、健康检查 | 不解析、不持有模型、不暴露 MinerU 的 `/v1` |
| 协调器 | 领取任务、调用引擎、下载产物、写投影、重试、取消 | 不对外服务大文件上传以外的长连接解析 |
| MinerU Router | 每卡一个解析进程，进程内共享模型 | 不作为任务真相来源 |

数据放在两处：

- **任务库**用 PostgreSQL。任务状态、引擎引用、取消、尝试次数、投影是否就绪，都以此为准。单机开发可以用同一套 schema 跑在容器里的 Postgres，不另做一套 SQLite 语义。
- **对象存储**单机用本地目录，多机对接外部 S3。Compose 不另起对象服务。原文按 SHA-256 存一份。产物按任务存放。不使用 Redis。多个协调器同时跑时，靠任务行上的 `SKIP LOCKED` 分工。

1.x 的 Celery 队列、线程池 worker、`MinerUEngineProcess` 删除。协调器是一个进程里的循环，只做 HTTP 和落盘。解析并发由 MinerU 的 `--worker-concurrency` 和 ThinkParse 的每台上游槽位一起限制。

## 4. 部署模式

ThinkParse 不按某一台机器定死。控制面三种模式都一样，不装 CUDA。差别在要不要带上 MinerU，以及 MinerU 能接哪些档。`cpu` 和 `gpu` 只选一个。

| 模式 | `COMPOSE_PROFILES` | MinerU | 镜像 | `/api/v2/tiers` |
|---|---|---|---|---|
| `external` | 不启用引擎 profile | 不带。`MINERU_BASE_URL(S)` 指向已有服务 | 只有 ThinkParse | 该 MinerU 报告的档位 |
| `cpu` | `cpu` | 一个 CPU worker，档位 `basic` | ONNX 小模型，无 CUDA | `flash`、`basic` |
| `gpu` | `gpu` | 每张可见 GPU 一个进程，档位 `MINERU_GPU_TIER`（默认 `standard`） | CUDA、Torch 小模型；`standard` 另含 VLM 权重 | `standard`：四档；`basic`：`flash`、`basic` |

档位不由部署模式写死。网关定期读每个 MinerU 的 `/v1/tiers`，取所有可达 MinerU 的并集，再与 `THINKPARSE_ACCEPTED_TIERS` 求交，缓存 30 秒。这样 `external` 接的是什么 MinerU、GPU 选了哪一档，都不需要再在 ThinkParse 里重复配置一遍。一个 MinerU 都连不上时退回允许列表，并在 `tiers` 里标 `discovered: false`，任务照常排队，等 MinerU 恢复。多台 MinerU 能力不同时，公布的是并集，投递只送到声明了该档的上游。槽位、在途字节和批次见 [operations.zh.md](../operations.zh.md)。

`cpu` 和 `gpu` 两个服务共用容器名 `thinkparse-mineru`，同时启用时 `docker compose` 直接报错。

构建源（vLLM / Python 基础镜像、PyPI 索引、模型源）都是参数，默认是全球源。国内镜像只是 `.env` 里的一组取值，不写进 Dockerfile。PostgreSQL 口令从 `.env` 读取。外部 S3 的 endpoint 与密钥也从 `.env` 读取，未设置时用本地目录。

`standard` 这个 worker 档包含四档请求，GPU 默认因此能接 MinerU 的全部请求。显存小的卡设 `MINERU_GPU_TIER=basic`，不下载 VLM 权重。CPU 模式没有 VLM。

`/api/v1` 的默认档在三种模式下都是 `basic`。GPU 上的 worker 能做 `standard`，不表示旧客户端改发这个档。做不到的档，两条接口都返回 400。

GPU 的可见卡、每卡在途（`MINERU_GPU_CONCURRENCY`）、窗口和线程是参数。CPU 在途是 `MINERU_CPU_CONCURRENCY`，默认 1。默认使用容器里全部可见 GPU，每卡在途 2，窗口 8，渲染线程 1，数值库线程 1。卡多、内存紧时再把在途降下来。MinerU 在大于 8GB 显存上仍按约 6GB 给 VLM 做预算；ThinkParse 不另造一个未支持的开关。

Docling 是可选引擎，只接 `.xml`、`.tex`、`.eml`，不是第四种硬件模式。

内存水位：协调器限制已提交给 MinerU、尚未取回产物的任务数。对象存储所在盘空闲过低时拒绝新提交（HTTP 507）。

## 5. 档位与旧参数的映射

旧表单仍然接受，映射到 MinerU 4.0 的任务字段。

| 旧字段 | 2.0 行为 |
|---|---|
| 未传 `backend`，或 `backend=pipeline` | `tier=basic`，`ocr_mode` 取 `method`（缺省 `auto`） |
| `method=auto\|txt\|ocr` | `ocr_mode` 同值 |
| `lang` | 传给 MinerU 的语言字段；4.0 `basic` 若忽略语言，协调器记录在任务上，不因此失败 |
| `formula_enable=false` | `basic` 下关闭公式。`standard` 不承诺能关掉 VLM 公式，旧客户端默认不会进这一档 |
| `table_enable=false` | 传给引擎；引擎不支持单独关闭时，任务记警告并继续，不改变 HTTP 成功语义 |
| `f_dump_content_list` | 忽略其开关语义。完成响应始终带 `content_list`，因为两个调用方都依赖它 |
| `enable_pagination` | 接受但不起作用。不切 PDF |
| 新可选字段 `tier=flash\|basic\|standard\|advanced` | 只有显式传入才偏离默认。旧客户端不传。不在本次部署的 `tiers` 里则 400 |

`/api/v2/jobs` 可以选 `flash`。有文字层的 PDF 走 `flash` 时不进入整页推理窗口。这条路径不作为 `/api/v1` 的默认：`flash` 的块结构和公式不一定满足 ThinkExtract 的 `content_list`。要在旧接口上开，必须先有投影黄金样本，并用环境变量 `LEGACY_ALLOW_FLASH=true` 显式打开。

`advanced` 在 `/api/v2` 可用。`/api/v1` 拒绝它。默认拒绝未知 `backend` 值，返回 400，避免静默改质量。

## 6. 兼容契约

以下响应是冻结的 API 约定。实现用契约测试锁住，样本来自现网 ThinkParse 1.x 的完成响应，以及 ThinkExtract、ThinkDoc 的读取字段。

### 6.1 提交

`POST /api/v1/tasks/submit`

- 请求：`multipart/form-data`，文件字段名 `file`。其余表单字段见第 5 节。
- 成功：`200`，JSON 至少包含 `success: true`、`task_id`（非空字符串）、`status: "pending"`、`file_name`、`created_at`、`backend`。
- 文件过大：`413`。磁盘或对象存储水位不足：`507`。
- `task_id` 由 ThinkParse 生成，不是 MinerU 的 `job_id`。MinerU 重启换掉上游 ID 时，客户端手里的 ID 仍然有效。

`POST /file_parse` 保留。它在内部创建同一个任务并等待终态，然后返回与 `GET /api/v1/tasks/{id}` 相同的 JSON。等待上限沿用任务超时。新集成不要用这个入口。

### 6.2 状态

`GET /api/v1/tasks/{task_id}`

进行中：

```json
{
  "success": true,
  "task": {
    "task_id": "...",
    "status": "pending",
    "file_name": "paper.pdf",
    "backend": "pipeline",
    "error_message": null,
    "started_at": null,
    "completed_at": null
  }
}
```

`status` 只使用调用方已经判断的值：`pending`、`processing`、`completed`、`failed`、`cancelled`。MinerU 的 `queued` 映射为 `pending`。`partial` 在旧接口的单文件任务上映射为 `failed`，错误写在 `task.error_message`。

完成时，除 `task.status=completed` 外，顶层必须有：

| 字段 | 要求 |
|---|---|
| `markdown_content` | 字符串。图片使用相对路径或可解析的图片名，不把页面图嵌成 `data:` URL。ThinkExtract 另存图片文件 |
| `content_list` | JSON 数组，元素为对象。ThinkDoc 读取 `type`、`text`、`page_idx`、`text_level`、`bbox`、表格和图片字段。废弃块使用它已经识别的 `discarded` / `abandon` |
| `middle_json` | 对象。至少提供 `pdf_info` 数组；每页含 `page_size` 与 `discarded_blocks`（可为空数组）。这是 ThinkExtract DOI 的读取路径 |
| `images` | 数组，元素含文件名。没有图片时为 `[]`，不要省略键 |
| `data.content` | 与 `markdown_content` 相同。ThinkDoc 在顶层缺失时读这里 |

`middle_json` 里可以同时带 MinerU 4.0 的 `schema: docvortex.middle`，但只要这个键存在，ThinkExtract 会把整次物化标为 `unsupported`。因此旧接口上的 `middle_json` **只输出投影后的 `pdf_info` 形状**，不输出 4.0 信封。4.0 原文放在对象存储，供以后的抽取侧直接读取，不放进这份兼容 JSON。

失败时 `task.status=failed`，`task.error_message` 为字符串。ThinkExtract 读的是 `error_message`，不是顶层 `error`。

未知任务：`404`。

### 6.3 取消、队列、健康

- `DELETE /api/v1/tasks/{task_id}`：返回 `success: true` 和 `status: "cancel_requested"`。协调器停止提交或调用 MinerU 的取消接口。已完成的任务保持 `completed`。
- `GET /api/v1/queue/stats`：`stats.pending`、`stats.processing` 来自任务库，不再调用 Celery inspect。`completed` / `failed` 改为真实计数，调用方忽略这两项也不受影响。
- `GET /api/v1/queue/tasks`：仍返回 `tasks[]`，元素含 `task_id`、`status`、`file_name`。
- `GET /api/v1/health/live`、`/ready`、`/deep`、`/api/v1/health`：`live` 只表示网关进程。`ready` 在任务库、对象存储、MinerU `/v1/health` 都可用时为 200，否则 503。`deep` 给出每张卡的 worker、在途数、最近一次投影失败，仅供运维。

ThinkDoc 的 Docling 客户端还要顶层 `docling_document`。2.0 的 MinerU 兼容响应不带这个键。将来 Docling 路由完成时，该路由的完成响应带 `docling_document`（DoclingDocument 的 JSON），并仍带 `task.status`。这不改变 MinerU 路由的响应。

## 7. 控制面数据模型

### 7.1 对象

- `blobs`：`sha256`、字节数、存储键、创建时间。相同内容只存一份。
- `tasks`：`id`（对外 `task_id`）、`blob_sha256`、`file_name`、`legacy_options`、`tier`、`ocr_mode`、`engine`、`status`、`error_message`、时间戳、`attempt`、`upstream_job_id`、`cancel_requested`。
- `artifacts`：`task_id`、`kind`（`markdown`、`content_list_v1`、`middle_pdf_info`、`middle_native`、`image`、`docling_document`）、存储键、字节数。
- `engine_routes`：后缀、显式引擎名、适配器名、是否启用。种子数据只有 MinerU。

任务状态机：

```text
accepted → dispatching → running → projecting → completed
                │            │          │
                │            │          └→ failed
                │            └→ failed（上游失败，且尝试次数用尽）
                └→ cancelled
         running → dispatching（上游 ID 失效且原文仍在）
```

`projecting` 在旧接口上仍报告 `processing`，避免客户端把「MinerU 已完成、投影未写完」当成 `completed` 后读到空的 `content_list`。

### 7.2 协调循环

每个协调器循环：

1. 用 `FOR UPDATE SKIP LOCKED` 领取一条 `accepted` 或需要重新投递的任务。
2. 若 MinerU 在途数已达上限，把任务留在 `accepted`。
3. 按 SHA-256 创建或复用上传。MinerU 的秒传只在其进程内存里有效，所以重启后的上传仍从对象存储读字节。ThinkParse 侧的去重是持久的。
4. `POST /v1/parse/jobs`，保存 `upstream_job_id`，状态改为 `running`。
5. 轮询上游。终态后把产物下载到对象存储。
6. 运行该引擎的投影器。投影成功才标 `completed`。
7. 若上游返回未知 `job_id`、连接拒绝或 `/v1/health` 失败，且尝试次数未用尽：清空 `upstream_job_id`，回到 `dispatching`。间隔指数退避，上限 5 次。超过则 `failed`，`error_message` 说明上游丢失。
8. `cancel_requested` 时，若上游 ID 仍有效则 `DELETE /v1/parse/jobs/{id}`，然后标 `cancelled`。

网关进程不跑这个循环。协调器可水平扩展，锁在任务行上。

### 7.3 投影器

投影器是兼容层的核心，也是引擎端口的一半。输入是引擎原生产物，输出是第 6 节的字段，并写入 `artifacts`。

MinerU 投影：

1. Markdown 来自请求的 `markdown` 产物。图片链接改写成与 `images[]` 一致的文件名，去掉 `data:` URL。
2. `content_list`：若某次 4.0 响应里仍有与 3.x 同构的列表，经校验后使用。否则从 4.0 的内容列表或 structured content 映射为 v1 元素。映射至少覆盖正文、标题、图片、表格、公式（公式保留 LaTeX 文本和 `page_idx`）、废弃块。映射表和黄金文件放在 `tests/fixtures/legacy_projection/`，缺一类块就不能把该档标为对旧客户端可用。
3. `middle_json.pdf_info`：按页生成。`page_size` 来自页面尺寸。`discarded_blocks` 来自页眉、页脚、页码、`discarded` 类块的文本。没有这类块时给空数组，键仍在。
4. `images[]`：每个导出的图片一个元素，含 `filename`。二进制在对象存储，不进状态 JSON。
5. 原生 `docvortex.middle` 整包写入 `kind=middle_native`，不出现在旧状态响应里。

投影失败是任务失败，不允许返回 `completed` 加残缺 JSON。ThinkExtract 会把残缺结果写进文档库。

Docling 投影（接口先定义，实现后置）：

- 原生 JSON 存为 `docling_document`。
- 若该任务走 Docling 路由，完成响应带这个对象。
- 不把 DoclingDocument 伪装成 MinerU `content_list`。两条路由的调用方不同。

## 8. 引擎端口

```text
EngineAdapter
  name: str
  health() -> Health
  submit(blob, filename, options) -> UpstreamRef
  poll(ref) -> UpstreamState
  fetch(ref) -> NativeArtifacts
  cancel(ref) -> None

Projector
  project(native) -> LegacyView
```

路由只看两件事：文件后缀，以及旧表单里将来可能出现的 `engine`（2.0 不要求客户端传递）。种子规则：

| 输入 | 适配器 | 2.0 |
|---|---|---|
| `.pdf`、图片 | `mineru` | 启用 |
| `.docx` 等 Office、HTML | `mineru` 的 `flash`，投影必须单独过黄金样本；不过则返回与 1.x MarkItDown 同级的失败，不把半成品标完成 | 启用与否由样本决定 |
| `.xml`（JATS）、`.tex`、`.eml` | `docling` | 端口在，适配器未注册则 400，错误说明该格式尚未接入 |

适配器进程外运行。ThinkParse 只保存 base URL、超时、API key、在途上限。Docling 接入时新增一个进程内无模型的 `DoclingAdapter`，指向已部署的 `docling-serve`（其 RQ worker 自行扩容）。不把 `docling` 包安装进 MinerU 镜像，也不共享 GPU 进程。

同一篇 PDF 不扇出到两个引擎。需要对比时，用离线任务对同一 `blob` 再提交一次并指定引擎，结果用两个 `task_id` 分开存。

## 9. 产品接口

ThinkParse 对外只有两套自己的接口。MinerU 的 `/v1/*` 只出现在协调器发往 MinerU 的内部调用里，不挂到网关的公网路由上。

| 前缀 | 角色 |
|---|---|
| `/api/v1` | 1.x 兼容。ThinkExtract、ThinkDoc 不改代码 |
| `/api/v2` | 2.0 产品接口。新客户端只走这里 |

`/api/v2` 吸收 MinerU 4.0 的资源模型，路径和字段归 ThinkParse：

- 上传、任务、产物是三种资源。状态体给 `file_id`，不内嵌整份 Markdown。
- 上传可以先登记字节数和校验和，再 `PUT` 内容，完成后再建任务。同一份原文按 SHA-256 只存一份。
- 建任务返回 202。客户端轮询任务，完成后再取产物。
- 任务显式带 `tier` 和 `ocr_mode`。部署做不到的档位直接拒绝。
- `GET /api/v2/tiers` 公布这一次安装能接的档，不把 MinerU 的模型仓库名暴露成产品接口。
- 取消是对任务的 `DELETE`。任务号是 ThinkParse 的，MinerU 重启后仍然有效。

路径：

- `POST /api/v2/uploads`、`PUT /api/v2/uploads/{id}/content`、`POST /api/v2/uploads/{id}/complete`
- `GET /api/v2/uploads/{id}`
- `POST /api/v2/jobs`（`file_id`，或 MinerU 风格的 `files[].source.file_id`，可选 `batch_id`）、`GET /api/v2/jobs?status=&limit=`、`GET /api/v2/jobs/{id}`、`DELETE /api/v2/jobs/{id}`
- `GET /api/v2/jobs/{id}` 带 `timing`（`queue_ms`、`parse_ms`、`project_ms`）、`attempt`、`pages`、`batch_id`
- `GET /api/v2/batches/{id}`、`GET /api/v2/batches/{id}/jobs`、`DELETE /api/v2/batches/{id}`
- `GET /api/v2/files/{id}`、`GET /api/v2/files/{id}/content`
- `GET /api/v2/tiers`（`data[].id`，以及 `discovered`）
- `GET /api/v2/stats`：当前队列、槽位、在途字节、最近一个时间窗的完成数。要 API key
- `GET /api/v2/health`：任务库、对象存储、每个 MinerU 的健康、当前档位、在途数。任一 MinerU 可达即 200。不要求 API key，供负载均衡探活

MinerU 明确拒绝的请求（HTTP 4xx，408/409/425/429 除外）直接把任务标 `failed` 并带上 MinerU 的原因，不重试。连不上、5xx、限流才按退避重试。

`/api/v1` 和 `/api/v2` 共用一张 `tasks` 表。兼容接口是投影翻译器，不是第二套队列。协调器拿到任务后才调用 MinerU 的 `/v1/uploads` 和 `/v1/parse/jobs`，上游 `job_id` 不返回给客户端。

鉴权：`/api/v2` 使用 `Authorization: Bearer`。`/api/v1` 在 2.0 首发保持与 1.x 相同的网络边界（内网、不强制 key），避免 ThinkExtract 未带 key 的请求失败。若部署暴露到内网以外，用网关或网络策略挡住，不在首发改变旧请求头要求。

## 10. 可靠性

| 事件 | 行为 |
|---|---|
| 网关重启 | 无状态。任务在数据库里 |
| 协调器重启 | 锁过期后其他协调器接手 `running` 任务，用 `upstream_job_id` 继续轮询 |
| MinerU worker 重启 | 上游 ID 失效则用对象存储中的原文重新提交，同一对外 `task_id` |
| 投影进程崩溃 | 任务停在 `projecting`，协调器重跑投影，不重新解析，除非原生产物缺失 |
| 客户端轮询中断 | 产物按 `RESULT_EXPIRES` 保留。默认与 1.x 一样可配置，且必须长于一次解析超时 |
| 取消 | 持久标记。重新投递前检查标记，避免取消后又解析 |
| 磁盘满 | 拒绝新提交。已在跑的任务继续写完或失败，不杀 MinerU 进程 |

超时：单任务默认仍覆盖长论文（数小时量级，具体秒数做成配置，默认 7200）。超时后取消上游并标 `failed`。

清理：按产物完成时间删除对象，不依赖「扫 Celery 结果键」。任务行可保留更久的元数据。

## 11. 部署形态

单机（当前这台服务器）：

```text
thinkparse-gateway
thinkparse-reconciler
postgres
本地对象目录（多机改为外部 S3）
mineru-router
  └─ api-server @ GPU0
  └─ api-server @ GPU1
```

ThinkParse 镜像不含 vLLM、不含 MinerU 权重。MinerU 使用其 4.0 官方镜像和 `mineru-kit router`。版本钉死到已用黄金样本验证过的 `mineru` 版本，不用 `>=4.0,<5` 这种浮动区间上生产。

多机：网关和协调器连同一 Postgres 与同一对象存储。每台 GPU 机器只跑 MinerU Router。协调器配置多个 MinerU base URL 时，按在途数选择，不在 ThinkParse 里再做一套 device id 编排。

观测与算力见 [operations.zh.md](../operations.zh.md)。每个任务有排队、解析、投影三段耗时。放行按每台 MinerU 的槽位和在途原文体积，不再用一个全局在途总数卡住所有地址。

## 12. 交付顺序

1. **API 契约与投影夹具**  
   冻结第 6 节。用 1.x 的真实完成 JSON 做消费方夹具（ThinkExtract 能读到 `content_list` 和 `pdf_info`；ThinkDoc 转换器能读到 `content_list`）。用 MinerU 4.0 `basic` 解析同一批论文，写出投影器。这一阶段不过，不切换默认档，也不接 `standard`。

2. **控制面**  
   网关、任务库、对象存储、协调器、MinerU 适配器。旧路径打到新控制面。本机 MinerU 先用一个 `basic` worker 证明往返。删除对 Celery 的依赖。

3. **双卡 Router**  
   按第 4 节的起点部署。用内存、load、GPU 利用率和每小时页数决定是否把每卡在途从 2 调到 3。调参不改客户端。

4. **`/api/v2`**  
   与 `/api/v1` 共用存储。新调用方走 ThinkParse 自己的上传、任务和文件资源。不暴露 MinerU 路径。

5. **Docling 端口落地**  
   仅当有 JATS 或同类格式的调用需求时实现适配器，并单独部署 `docling-serve`。PDF 默认路由保持 MinerU。

`standard` 作为可选档，放在步骤 1 的投影夹具覆盖公式和表格之后。未覆盖前，配置项存在但旧接口不可达。

## 13. 风险

| 风险 | 处理 |
|---|---|
| 4.0 的块类型无法无损映射到 `content_list` v1，公式或表格在 ThinkDoc 里变空 | 该档不得对旧接口开放。先补映射和夹具 |
| 投影出的 `pdf_info` 没有真实废弃块，DOI 召回下降 | 从 4.0 页眉页脚映射；映射为空时在夹具里单列，不假装与 3.4.5 等价 |
| `basic` 在这台机器上 GPU 仍然不满 | 接受。这是小模型流水线的形态。不用 `advanced` 换利用率 |
| `standard` 冷启动和显存默认值导致「vLLM 很慢」的错觉 | 独立 profile，写明 `gpu-memory-utilization`，不作为旧默认 |
| 协调器重试把已经取消的任务再次提交 | 重试前读 `cancel_requested` |
| 对象存储与 MinerU 临时目录各存一份，磁盘翻倍 | 协调器取回后不要求 MinerU 长期保留；ThinkParse 是产物主人 |
| 旧 `/file_parse` 同步等待被误用成长连接 | 保留但文档标明超时即结束等待，任务仍在后台 |

## 14. 成功标准

- ThinkExtract 现有 `document_parser.py`、ThinkDoc 现有 MinerU 提交与 `MinerUJsonConverter` 在不改代码的情况下，对夹具论文完成一轮解析。
- 杀掉 MinerU 进程再拉起后，已提交未完成的 `task_id` 最终到达 `completed` 或明确的 `failed`，不会一直 `processing`，也不会 404。
- 网关进程内存不随并发解析线性增长到数 GB 模型权重。GPU 上 MinerU 进程数为 2。
- 在 64GB 上，每卡在途 2、窗口 8 或 16 时，解析期间不发生整机 OOM。若发生，先降并发，而不是加第三个模型进程。
- 增加引擎时，新增的是一个适配器模块和一条路由，不改任务表，不改旧 MinerU 响应字段。
