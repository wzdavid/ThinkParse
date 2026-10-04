<div align="center">

# ThinkParse

**企业级文档解析系统 —— 从单机到分布式多 GPU 集群。**

开源项目：通过一套可用于生产的 HTTP API，将 PDF、扫描件等复杂文档转为干净的 Markdown 与结构化结果。
面向 RAG、知识库、科研文献与长时间大批量任务，而不是「在解析模型外包一层演示脚本」。

[![CI](https://github.com/wzdavid/ThinkParse/workflows/CI/badge.svg)](https://github.com/wzdavid/ThinkParse/actions)
[![Release](https://img.shields.io/github/v/release/wzdavid/ThinkParse)](https://github.com/wzdavid/ThinkParse/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

[English](README.md) · [简体中文](README.zh.md)

[快速开始](#快速开始) · [为什么选择 ThinkParse](#为什么选择-thinkparse) · [文档](docs/README.zh.md) · [贡献](CONTRIBUTING.md)

</div>

## 为什么选择 ThinkParse？

[MinerU](https://github.com/opendatalab/MinerU) 等引擎解决的是「一篇文档怎么解析好」。真正做成业务系统时，还要回答：

- 文档是几千、几万甚至上百万份时，如何稳定排队、异步完成，而不是同步接口超时？
- 机器上有多张 GPU，如何真正并行，而不是只吃到 `cuda:0`？
- 协调器 / 引擎重启后，任务会不会丢？能否取消、重试、可观测？
- API 与解析算力如何拆开，单机不够时如何分布式扩展？

ThinkParse 就是补这一层的**企业级文档解析系统**：稳定 API、持久任务、共享对象存储、多 GPU 并行与分布式部署。

| 竞争力 | 你得到什么 |
|---|---|
| **大批量稳定可靠解析** | 提交 / 轮询 / 取消；任务可恢复；`priority`（0–9，越大越优先）可插队，不打断已在解析的任务 |
| **多 GPU 并行处理** | 引擎侧每张可见 GPU 一个解析进程；ThinkParse 用槽位与在途字节控并发，并可向多台引擎分摊 |
| **分布式部署** | API 与协调器可在 CPU 机；GPU 机只跑引擎；共享 Postgres + 外部 S3 |
| **生产级 API** | `/api/v1` 异步任务；`/api/v2` 上传 / 任务 / 文件 / 批次 |
| **可运维** | 分层健康检查、档位发现、统计、批次、排队 / 解析 / 投影耗时 |
| **高质量输出** | Markdown、表格、公式、图片、`content_list`、中间 JSON |

解析质量来自 MinerU 4.0（可选 Docling 处理部分非 PDF 格式）。ThinkParse 负责**服务层**：调度、持久化、容量，以及业务侧调用的稳定 API。

> 偶尔解析几份 PDF：直接用引擎即可。  
> 做 RAG、知识库、文献流水线或持续批量转换：用 ThinkParse。

## 工作原理

```text
你的应用
   │  POST /api/v1/tasks/submit   或   /api/v2/uploads + /api/v2/jobs
   ▼
┌──────────────────────────────────────────────┐
│ ThinkParse（API + 任务编排）                    │
│  网关 · PostgreSQL · 对象存储 · 协调循环         │
└──────────────────┬───────────────────────────┘
                   │ HTTP
        ┌──────────┴──────────┐
        ▼                     ▼
  MinerU 4.0（多 GPU）      Docling Serve（可选）
```

API 保持轻量，重活在引擎节点。增加 GPU 或机器时，客户端提交方式不变。

## 快速开始

**环境：** Docker。GPU 模式还需 NVIDIA 驱动与 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)。

```bash
git clone https://github.com/wzdavid/ThinkParse.git
cd ThinkParse
cp .env.example .env
# 三选一：COMPOSE_PROFILES=gpu | cpu | （留空接外部 MinerU）
# 修改 POSTGRES_PASSWORD（请只用字母和数字）

docker compose --env-file .env -f docker/docker-compose.yml up -d --build
curl -fsS http://127.0.0.1:8000/api/v1/health/live
curl -sS http://127.0.0.1:8000/api/v1/health/ready
curl -sS http://127.0.0.1:8000/api/v2/tiers
```

异步提交（批量与生产推荐）：

```bash
curl -sS \
  -F "file=@document.pdf" \
  -F "backend=pipeline" \
  http://127.0.0.1:8000/api/v1/tasks/submit
```

轮询 `GET /api/v1/tasks/{task_id}` 直至 `completed` / `failed` / `cancelled`。

完整步骤：[快速开始](docs/quickstart.zh.md) · [部署](docs/deployment.zh.md)。

## 部署方式

| 模式 | 场景 | 说明 |
|---|---|---|
| **CPU** | 本机试用 | `COMPOSE_PROFILES=cpu`，档位 `flash` / `basic` |
| **GPU（单卡 / 多卡）** | 生产吞吐 | 单卡：`COMPOSE_PROFILES=gpu`；双卡：`gpu,gpu1` 并配置 `MINERU_BASE_URLS` / `THINKPARSE_SLOTS`；调节 `MINERU_GPU_CONCURRENCY` |
| **外部引擎** | 已有 MinerU | 清空 profile，配置 `MINERU_BASE_URL(S)` |
| **分布式** | API 与 GPU 分机 | 共享 Postgres + 外部 S3；多 MinerU 地址；用槽位与在途字节控容量 |

不要同时开 `cpu` 与 `gpu`。网关端口 **8000**。详见 [部署](docs/deployment.zh.md) 与 [运维与算力](docs/operations.zh.md)。

## API 一览

| API | 用途 |
|---|---|
| `/api/v1/tasks/*` | 生产异步流程（提交 / 轮询 / 取消） |
| `/file_parse` | 同步便捷接口，批量请优先异步 |
| `/api/v2/*` | 上传、任务、文件、档位、统计、批次 |

引擎原生路由不对外。接口约定见 [API 参考](docs/api.zh.md)。

## 谁适合用

- **RAG / 知识库团队** —— 切片与向量化前的统一 Markdown 与结构
- **科研与数据平台** —— 批量论文、研报、合同，无需长时间占着 HTTP
- **AI 应用团队** —— 把文档解析做成微服务，业务侧不装引擎依赖
- **中台 / 基础设施** —— 多 GPU、多节点解析农场，共享存储与清晰健康信号

## 文档

| 文档 | 说明 |
|---|---|
| [产品概述](docs/overview.zh.md) | 定位、目标与非目标 |
| [架构](docs/architecture.zh.md) | 系统设计、引擎、数据模型 |
| [快速开始](docs/quickstart.zh.md) | 第一次完整解析 |
| [部署](docs/deployment.zh.md) | 模式、验收、排障 |
| [API](docs/api.zh.md) | `/api/v1` 与 `/api/v2` |
| [运维与算力](docs/operations.zh.md) | 统计、容量、多 GPU 调参 |

## 开发

```bash
pip install -r control/requirements-dev.txt
PYTHONPATH=. python -m unittest discover -s tests -p 'test_control_*.py'
ruff check control tests
```

## 致谢

ThinkParse 基于 [MinerU](https://github.com/opendatalab/MinerU)、可选 [Docling](https://github.com/docling-project/docling)、FastAPI、PostgreSQL 与 S3 兼容存储等开源组件构建。

## 许可证

[MIT](LICENSE)。第三方引擎仍遵循各自许可证。
