# API 参考

ThinkParse 作为企业级文档解析服务，对外只暴露两套产品接口。引擎原生 `/v1/*` 仅出现在协调器发往上游的内部调用里，不挂到网关公网路由。

| 前缀 | 角色 |
|---|---|
| `/api/v1` | 异步任务风格；兼容既有 `submit` / 轮询客户端 |
| `/api/v2` | 产品接口：上传、任务、文件、档位、统计、批次 |

鉴权：`/api/v2` 在配置了 `THINKPARSE_API_KEY` 时使用 `Authorization: Bearer`。`/api/v1` 默认不强制 key（适合内网）；若暴露到更广网络，请用网关或网络策略保护。

---

## `/api/v1` 兼容接口

### 提交

`POST /api/v1/tasks/submit`

- 请求：`multipart/form-data`，文件字段名 `file`。档位等可选表单见 [架构 · 档位映射](architecture.zh.md#档位与兼容参数)。
- 可选表单 `priority`：整数 `0`–`9`，越大越优先，默认 `0`。同优先级按提交时间。只影响还在排队、尚未交给引擎的任务；已在解析的任务不会被打断。超出范围返回 `400`。
- 成功：`200`，JSON 至少含 `success: true`、`task_id`、`status: "pending"`、`file_name`、`created_at`、`backend`、`priority`。
- 文件过大：`413`。本地对象目录水位不足：`507`（S3/MinIO 不做此项本地检查）。
- `task_id` 由 ThinkParse 生成，不是 MinerU 的 `job_id`。

`POST /file_parse`：内部创建同一任务并等待终态，返回与 `GET /api/v1/tasks/{id}` 相同的 JSON。新集成请勿使用；超时后等待结束，任务仍可在后台继续。

### 状态

`GET /api/v1/tasks/{task_id}`

进行中示例：

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

`status` 仅使用：`pending`、`processing`、`completed`、`failed`、`cancelled`。上游 `queued` 映射为 `pending`。单文件任务上的 `partial` 映射为 `failed`。

完成时除 `task.status=completed` 外，顶层必须有：

| 字段 | 要求 |
|---|---|
| `markdown_content` | 字符串；图片用相对路径或可解析文件名，不要嵌 `data:` URL |
| `content_list` | JSON 数组；元素为对象（`type`、`text`、`page_idx`、表格 / 图片字段等） |
| `middle_json` | 对象；至少 `pdf_info[]`，每页含 `page_size` 与 `discarded_blocks`（可为空数组）。**不**输出 `schema: docvortex.middle` |
| `images` | 数组。每项含 `filename`、`mime_type`、`size_bytes`、`data_url`（读响应时由已存图片字节编码，库内不保存 base64）。无图时为 `[]`，不要省略键 |
| `data.content` | 与 `markdown_content` 相同 |

失败时 `task.status=failed`，错误在 `task.error_message`（不是顶层 `error`）。未知任务：`404`。

### 取消、队列、健康

| 方法 | 说明 |
|---|---|
| `DELETE /api/v1/tasks/{task_id}` | `success: true`，`status: "cancel_requested"`；已完成保持 `completed` |
| `GET /api/v1/queue/stats` | `stats.pending` / `processing` 等来自任务库 |
| `GET /api/v1/queue/tasks` | `tasks[]`：`task_id`、`status`、`file_name` |
| `GET /api/v1/health/live` | 网关进程存活 |
| `GET /api/v1/health/ready` | 任务库、对象存储、至少一个 MinerU 健康时 200，否则 503 |
| `GET /api/v1/health/deep` | 上游详情、在途等，供运维 |

Docling 路由的完成响应可带顶层 `docling_document`；MinerU 路由不带该键。

---

## `/api/v2` 产品接口

资源模型贴近「上传 → 任务 → 文件」：状态体给引用，不内嵌整份 Markdown。建任务返回 **202**；客户端轮询后再取产物。

### 上传

- `POST /api/v2/uploads`
- `PUT /api/v2/uploads/{id}/content`
- `POST /api/v2/uploads/{id}/complete`
- `GET /api/v2/uploads/{id}`

同一份原文按 SHA-256 只存一份。

### 任务与批次

- `POST /api/v2/jobs` — body 含 `file_id`（或 MinerU 风格的 `files[].source.file_id`），可选 `tier`、`ocr_mode`、`batch_id`、`priority`（`0`–`9`，越大越优先）
- `GET /api/v2/jobs?status=&limit=`
- `GET /api/v2/jobs/{id}` — 含 `timing`（`queue_ms`、`parse_ms`、`project_ms`）、`attempt`、`pages`、`batch_id`、`priority`
- `DELETE /api/v2/jobs/{id}` — 取消（ThinkParse 任务号，引擎重启后仍有效）
- `GET /api/v2/batches/{id}`
- `GET /api/v2/batches/{id}/jobs`
- `DELETE /api/v2/batches/{id}` — 取消该批未终态任务

`batch_id`：字母、数字、`-`、`_`，最长 64。批次是任务标签，不是独立工作流。

部署做不到的档位在提交时直接 400，不会排队后才失败。

### 文件

- `GET /api/v2/files/{id}`
- `GET /api/v2/files/{id}/content`

完成的 MinerU 任务在 `output_files` 里给出 `markdown`、`middle_json`，以及 `images[]`（`file_id`、`filename`、`bytes`）。图片字节用文件接口下载，不放进任务 JSON。`/api/v1` 的 `data_url` 只在兼容响应里现编码。

### 发现与观测

| 端点 | 说明 |
|---|---|
| `GET /api/v2/tiers` | `data[].id` 与 `discovered`；不暴露引擎模型仓库名 |
| `GET /api/v2/stats` | 队列、槽位、在途字节、时间窗内完成数等（通常需 API key） |
| `GET /api/v2/health` | 任务库、对象存储、每个上游健康与档位；任一 MinerU 可达即 200；可不带 key，适合负载均衡探活 |

`/api/v1` 与 `/api/v2` 共用同一张 `tasks` 表。兼容接口是投影翻译器，不是第二套队列。上游 `job_id` 不返回给客户端。

统计字段语义见 [运维与算力](operations.zh.md)。
