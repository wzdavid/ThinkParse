<div align="center">

<h1>ThinkParse</h1>

<p><strong>通过一个可用于生产环境的 API，将复杂文档转化为干净、结构化的内容。</strong></p>

<p>
  基于 MinerU、FastAPI、Celery 与 Redis 构建的开源文档解析服务。<br />
  可靠处理 PDF、图片和 Office 文档，可从单机平滑扩展至分布式 GPU Worker。
</p>

[![CI](https://github.com/wzdavid/ThinkParse/workflows/CI/badge.svg)](https://github.com/wzdavid/ThinkParse/actions)
[![Release](https://img.shields.io/github/v/release/wzdavid/ThinkParse)](https://github.com/wzdavid/ThinkParse/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

[English](README.md) · [简体中文](README.zh.md)

[快速开始](#快速开始) · [API 使用](#api-使用) · [部署指南](docs/DEPLOYMENT.zh.md) · [配置参考](docs/CONFIGURATION.zh.md) · [故障排除](docs/TROUBLESHOOTING.zh.md)

</div>

## 为什么选择 ThinkParse？

当文档处理超出本地脚本的能力范围，解析就会变得复杂：大文件耗时较长、GPU 进程可能异常、结果可能挤占队列存储，而生产部署还需要可观测、可恢复的 Worker。

ThinkParse 将解析引擎封装在稳定的 HTTP API 和异步 Worker 架构之后：

- **高质量文档解析** —— 基于 MinerU 3.4.5 提取 Markdown、表格、公式、图片和结构化中间结果。
- **支持多种文档格式** —— PDF 与图片交由 MinerU 解析，Office、HTML 和文本格式交由 MarkItDown 转换。
- **完整的生产任务流程** —— 无需长时间保持客户端连接，即可提交、轮询、设置优先级、取消和检查解析任务。
- **支持 CPU 与 GPU 部署** —— 可用 CPU Worker 本地启动，也可在单台服务器使用一张或多张 GPU，或跨节点扩展 Worker；天河等只允许一个容器的调度环境可使用 **all-in-one 单容器**。
- **可靠处理长文档** —— 在任务之间复用解析引擎，并通过进程隔离实现取消、超时恢复和自动重启。
- **可扩展存储** —— 单机使用本地卷，分布式部署使用 S3 兼容存储。
- **清晰的运行状态** —— 分层健康检查提供就绪状态、队列深度、Worker 心跳、任务耗时和 GPU 状态。

## 工作原理

```text
客户端 → FastAPI → Redis 队列 → Celery Worker → MinerU / MarkItDown
  ↑                                               ↓
  └────────────── 状态与结果 ──────────── 本地或 S3 存储
```

API 保持轻量，耗时的解析工作由 Worker 完成。增加 Worker 时无需修改客户端集成。

## 快速开始

### 环境要求

- Docker 与 Docker Compose
- 可选：NVIDIA GPU、NVIDIA Container Toolkit，以及满足解析模型要求的显存

> 首次构建或首次使用 CPU 解析时，可能需要下载依赖和模型，因此耗时会更长。

### 1. 克隆并配置

```bash
git clone https://github.com/wzdavid/ThinkParse.git
cd ThinkParse
cp .env.example .env
cp docker/.env.example docker/.env
```

如需最简单的本地体验，请打开 `docker/.env` 并选择 CPU 配置：

```dotenv
COMPOSE_PROFILES=redis,mineru-cpu
```

在 NVIDIA GPU 主机上使用：

```dotenv
COMPOSE_PROFILES=redis,mineru-gpu
```

### 2. 构建并启动

```bash
cd docker
sh build.sh
docker compose up -d
```

### 3. 验证服务

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

就绪检查返回 HTTP `200` 后，可访问：

- 交互式 API 文档：<http://localhost:8000/docs>
- 服务信息：<http://localhost:8000/>

查看日志或停止服务：

```bash
docker compose logs -f
docker compose down
```

## API 使用

ThinkParse 提供适合生产负载的异步 API，以及适合简单集成的 MinerU 同步兼容接口。

### 推荐：异步任务 API

提交文档：

```bash
curl -X POST "http://localhost:8000/api/v1/tasks/submit" \
  -F "file=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang=ch"
```

响应中会包含 `task_id`：

```json
{
  "success": true,
  "task_id": "abc123",
  "status": "pending"
}
```

轮询任务，直至状态变为 `completed`、`failed` 或 `cancelled`：

```bash
curl "http://localhost:8000/api/v1/tasks/abc123"
```

取消任务：

```bash
curl -X DELETE "http://localhost:8000/api/v1/tasks/abc123"
```

批量处理、长耗时文档、S3 存储、多 Worker 和多节点部署都应优先使用异步 API。

### 同步兼容 API

如果是简单的单机集成，并希望等待接口直接返回结果：

```bash
curl -X POST "http://localhost:8000/file_parse" \
  -F "files=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang_list=ch" \
  -F "parse_method=auto" \
  -F "return_md=true"
```

此端点沿用 MinerU `/file_parse` 请求形式。生产环境建议使用异步 API，因为同步请求会在整个解析过程中保持连接。

Python、JavaScript、批处理、优先级和错误处理示例请参阅 [API 示例](docs/API_EXAMPLES.zh.md)。

## 部署方式

### 单机部署

- **CPU：** `COMPOSE_PROFILES=redis,mineru-cpu`
- **单 GPU：** `COMPOSE_PROFILES=redis,mineru-gpu`
- **多 GPU：** 使用 `docker-compose.multi-gpu.yml`，将每个 Worker 绑定到一张 GPU

### 分布式部署

使用共享 Redis 和 S3 兼容存储，即可将 API 与 Worker 部署在不同主机上。详见[大规模多节点部署](docs/PRODUCTION_MULTI_NODE.zh.md)。

### 生产环境检查

- 设置 `ENVIRONMENT=production` 并限制 `CORS_ALLOWED_ORIGINS`。
- 为 Redis 启用身份验证，并将其持久化数据与解析输出存放在不同磁盘。
- Worker 不共享文件系统时，请使用 S3 兼容存储。
- 每张 GPU 保持一个活跃 MinerU 任务；通过增加 Worker 扩容，而不是提高单卡并发。
- `/api/v1/health/deep` 会暴露详细运行信息，应仅对运维人员开放。

## 健康检查与运维

- `GET /api/v1/health/live` —— API 进程存活检查
- `GET /api/v1/health/ready` —— Redis、存储和 Worker 就绪检查
- `GET /api/v1/health/deep` —— 详细的队列、任务、引擎和 GPU 诊断
- `GET /api/v1/queue/stats` —— 当前队列与 Worker 数量
- `GET /api/v1/queue/tasks` —— 活跃和已预留任务

## 文档

- [文档索引](docs/README.zh.md)
- [部署指南](docs/DEPLOYMENT.zh.md)
- [单容器部署（天河）](docs/DEPLOYMENT_ALLINONE.zh.md)
- [配置参考](docs/CONFIGURATION.zh.md)
- [API 示例](docs/API_EXAMPLES.zh.md)
- [故障排除](docs/TROUBLESHOOTING.zh.md)
- [S3 存储与清理](docs/S3_STORAGE.zh.md)
- [开发指南](docs/DEVELOPMENT.zh.md)

## 参与贡献

欢迎提交 Issue 和 Pull Request。贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题请按照 [SECURITY.md](SECURITY.md) 中的方式报告。

## 致谢

ThinkParse 基于以下开源项目构建：

- [MinerU](https://github.com/opendatalab/MinerU) —— 文档解析引擎
- [MarkItDown](https://github.com/microsoft/markitdown) —— Office、HTML 和文本转换
- [FastAPI](https://fastapi.tiangolo.com/)、[Celery](https://docs.celeryq.dev/) 与 [Redis](https://redis.io/) —— API 与分布式任务基础设施

## 许可证

ThinkParse 使用 [MIT License](LICENSE) 发布。第三方组件仍遵循各自许可证，包括 [MinerU 开源许可证](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)与 [MarkItDown MIT License](https://github.com/microsoft/markitdown/blob/main/LICENSE)。
