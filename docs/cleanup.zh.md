# 文件清理

ThinkParse 不永久保存上传文件、解析过程中的临时文件和解析结果。这些字节都在对象存储或 MinerU 容器的临时目录里，由协调器或 MinerU 在固定期限后删除。Postgres 里的任务行、上传行和空白 blob 行会留下来，它们不包含文件内容。

持续运行时，磁盘占用有上界：还没结束的任务原文，加上最近 24 小时内已结束任务的原文和结果，再加上最近 6 小时内 MinerU 尚未被主动删掉的草稿。提交速度长期高于解析速度时，未开始的任务会堆积，那是排队，不是清理失效。

协调器必须在跑。`RESULT_EXPIRES_SECONDS=0` 会留下已结束任务的结果。`MINERU_FILE_RETENTION_SECONDS=0` 会把 MinerU 草稿留到进程退出。生产环境保持默认值。改了清理逻辑之后要重建 `thinkparse-control:2.0` 和 `thinkparse-mineru`，正在跑的旧容器不会自己换上这段行为。

## 对象存储

Compose 默认把原文和结果放在卷 `thinkparse_objects`，网关和协调器挂的是同一目录。多机部署设置 `THINKPARSE_S3_ENDPOINT` 后改走外部 S3，桶名默认 `thinkparse`。本地目录剩余空间低于 `THINKPARSE_FREE_MIN_BYTES`（默认 8 GiB）时拒绝新提交（HTTP 507）。外部 S3 的容量由存储侧限制，提交时不探测本地剩余空间。

| 对象 | 键 | 保留 | 谁删除 |
|---|---|---|---|
| 未完成的 `/api/v2` 上传 | `uploads/{upload_id}` | 1 小时（`expires_at`） | 协调器每轮清理。完成上传时，字节拷进 `blobs/` 后立刻删掉这份暂存 |
| 原文 | `blobs/{sha256}` | 还有未过期任务引用它，就保留。全部任务过期后删除。没有任何任务的原文，满 1 小时删除 | 协调器。同一份内容只存一份；最后一个任务过期才删字节 |
| 解析结果 | `artifacts/{task_id}/` | 任务进入 `completed`、`failed` 或 `cancelled` 之后 24 小时（`RESULT_EXPIRES_SECONDS`，默认 86400） | 协调器按整个前缀删除，包括 `result.md`、`content_list.json`、`middle.json`、`images/`、投影缓存 `native.json` 和 `source-images/` |
| 失败任务的投影缓存 | `artifacts/{task_id}/native.json` 与 `source-images/` | 任务失败时立刻删 | 协调器。原文和已经写好的结果仍等到 24 小时 |

过期之后任务状态仍是原来的终态，读取结果会得到 `result expired`，正文为空。任务行还在。

`/api/v2` 上传完成之后如果一直不创建任务，原文只再留 1 小时。要解析就在这 1 小时内提交任务。

## MinerU 容器

MinerU 不把结果写进 ThinkParse 的对象目录。它在自己的临时目录里放两份东西：Router 为了跨进程重传而留的原文副本，以及每个 worker 上的原文 blob 和结果 zip。解析函数自己的工作目录在函数返回时删除。模型权重在镜像里，不随任务增长。

ThinkParse 在下面这些时刻调用 `DELETE /v1/files/{id}`，删掉原文、zip，以及 markdown / middle 的 file id：

- zip 已经写入对象存储之后
- 上游判定失败或取消之后
- 下载被拒绝、任务已失败之后
- ThinkParse 自己取消或超时时，先读出 file id，取消任务，再删除

下载失败但还要重试时不删，下次还能再取。重试若丢掉了旧的 job id，旧副本不再由这次 DELETE 覆盖，交给下面的期限。

官方 MinerU 4.0.10 的 `delete_file` 只从内存索引去掉记录，worker 上的字节还在；Router 的原文副本则是在 DELETE 时就删掉的。ThinkParse 的 MinerU 镜像在 site-packages 里安装了 `mineru_file_gc.py`，补上两件事：

- 删除最后一个引用时，unlink worker 上的 blob
- `MINERU_FILE_RETENTION_SECONDS`（compose 默认 21600，6 小时）到期后清扫没人删除的 worker 文件和 Router 原文副本

正在排队或解析的输入不会被清扫删掉。6 小时长于默认 7200 秒的任务超时，正常任务不会在解析中被清掉。客户端在 DELETE 之前崩溃、取消时没能读到 file id、或者重试留下的旧副本，都在这个期限里消失。进程退出时，临时目录仍会整目录删除。

外部 MinerU（`MINERU_BASE_URL` 指向本 compose 以外的服务）必须带同样的删除和清扫行为，并设置 `MINERU_FILE_RETENTION_SECONDS`。没有这个钩子的 4.0.10 不会因为 ThinkParse 的 DELETE 而释放 worker 磁盘。

## Docling

Docling 不在 ThinkParse 里落临时文件。结果投影进同一个 `artifacts/{task_id}/`，跟随 24 小时过期。Docling 服务自己的磁盘不在这条清理路径上。

## 要保持的条件

- 协调器进程在运行（compose 服务 `reconciler`，`restart: unless-stopped`）
- `RESULT_EXPIRES_SECONDS` 保持正数，默认 86400
- `MINERU_FILE_RETENTION_SECONDS` 保持正数，compose 默认 21600
- MinerU 镜像包含 `mineru_file_gc.py`（CPU 与 GPU Dockerfile 都会安装）
