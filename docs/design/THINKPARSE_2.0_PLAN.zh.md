# ThinkParse 2.0 开发计划

状态：控制面可在 GPU 机器上联调；双卡部署和现网切换未做  
设计依据：[THINKPARSE_2.0.zh.md](THINKPARSE_2.0.zh.md)  
日期：2026-09-30

代码只保留 2.0 控制面 `control/`。1.x 的 Celery、worker 和部署文档已删除，旧发布仍在 git 标签 `v1.4.2`。对外任务路径与旧客户端相同。

## 里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M1 控制面 | 兼容网关、投影器、MinerU 4.0 HTTP 客户端、协调器、契约测试 | 已实现 |
| M2 持久化部署 | PostgreSQL 任务库、MinIO 对象存储、网关与协调器分进程 | 已实现，本机 Postgres 与 MinIO 测试通过 |
| M3 投影夹具 | 用真实 MinerU 4.0 产物核对 ThinkExtract 要读的字段 | CPU 上已用 `basic`（第 10/15/27 页）和 `flash`（前 3 页）跑过 `2604.04771v2.pdf`。GPU 上的整篇 `basic` 还未跑 |
| M4 部署模式 | `external` / `cpu` / `gpu`。GPU 用全部可见卡和 `standard` 权重 | compose 已拆成两个 profile。GPU 整机实测还没做 |
| M5 `/api/v2` | 产品接口：上传、任务、文件、档位、统计、批次。内部再调用 MinerU `/v1` | 已挂到 `/api/v2`。网关不暴露 MinerU `/v1`。档位是各 MinerU 的并集，再与 `THINKPARSE_ACCEPTED_TIERS` 求交 |
| M6 Docling | `.xml` / `.tex` / `.eml` 走外部 docling-serve，PDF 仍走 MinerU | 已实现 |
| M7 切换 | ThinkExtract / ThinkDoc 把 base URL 指到 2.0 网关 | 未开始。仓库里的 Celery 已经删除 |
| M8 观测与算力 | 任务三段耗时、`/api/v2/stats`、批次、按上游槽位和在途字节放行、档位改并集 | 已实现，见 [OPERATIONS.zh.md](OPERATIONS.zh.md) |

旧接口默认档是 `basic`（表单 `backend=pipeline`）。`flash` 要设 `LEGACY_ALLOW_FLASH=true` 才接受。`advanced` 在旧接口上返回 400。显式 `tier=standard` 会被接受，ThinkExtract 默认不会传这个字段。

## 本轮代码

```text
control/                 2.0 控制面，不加载 CUDA
  gateway.py             /api/v1 兼容与 /api/v2 产品接口。MinerU /v1 只在协调器内部调用
  reconciler.py          独立进程入口
  reconcile.py           投递、轮询、重试、取消、投影、超时、清理
  mineru.py              MinerU 4.0 HTTP
  docling.py             docling-serve HTTP，只接非 PDF
  project.py             MinerU middle → 3.x 形状；Docling 保留 docling_document
  store.py               PostgreSQL 与内存任务库
  objects.py             本地目录或 S3/MinIO
docker/docker-compose.yml    cpu 与 gpu 两个 profile，别名都是 mineru-router
docker/mineru.Dockerfile      GPU，默认下载 standard
docker/mineru-cpu.Dockerfile  CPU，ONNX basic
tests/test_control_*.py
tests/fixtures/legacy_projection/
```

网关监听 `8000`。启用 `gpu` profile 时，MinerU Router 在 compose 网络内的 `mineru-router:8002`，不映射到宿主机。启动命令、健康检查和整篇论文的字段核对写在 [DEPLOYMENT.zh.md](DEPLOYMENT.zh.md)。网关不跑协调循环。`/file_parse` 只等待协调器把任务写到终态。

## GPU 机器上先做的事

按 [DEPLOYMENT.zh.md](DEPLOYMENT.zh.md) 做。第一轮用 `basic`，每张卡一个推理进程、在途 2。不要把旧客户端默认档改成 `standard`。

本机 CPU 已经核对过的样本：

- `tests/fixtures/legacy_projection/mineru_flash_p1-3.json`
- `tests/fixtures/legacy_projection/mineru_basic_p10_15_27.json`（38 条公式、3 张表）

## 验证

```bash
cd /Users/david/Blue/ThinkParse
PYTHONPATH=. python -m unittest discover -s tests -p 'test_control_*.py'
```

M3 的手工检查：对一篇论文走完 `submit` → 协调器 → `GET`，确认响应里有 `content_list`、`middle_json.pdf_info`，且 `middle_json` 没有 `schema`。

## 明确留到后面的事

- 不在本仓库改 ThinkExtract / ThinkDoc 的 base URL。这是 M7，要等 GPU 上整篇 `basic` 的字段核对通过。
- `gpu` 镜像默认带 `standard` 权重。`/api/v1` 仍默认 `basic`。步骤在 [DEPLOYMENT.zh.md](DEPLOYMENT.zh.md)。
- `.xml` / `.tex` / `.eml` 只有配置了 `DOCLING_BASE_URL` 才走 Docling；没配时返回 400。PDF 不走 Docling。
- `formula_enable=false` 在 `basic` 上只记警告，MinerU 4.0 任务接口没有单独的公式开关。设计第 5 节写的「basic 下关闭公式」还没有引擎侧开关。
