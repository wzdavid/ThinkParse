# ThinkParse

<div align="center">

[![CI](https://github.com/wzdavid/ThinkParse/workflows/CI/badge.svg)](https://github.com/wzdavid/ThinkParse/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com)
[![Celery](https://img.shields.io/badge/Celery-5.3+-green.svg)](https://docs.celeryq.dev)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/wzdavid/ThinkParse)

[English](README.md) | [简体中文](README.zh.md)

**[📖 部署指南](docs/DEPLOYMENT.zh.md)** • **[⚙️ 配置参考](docs/CONFIGURATION.zh.md)** • **[💡 API 示例](docs/API_EXAMPLES.zh.md)** • **[🔧 故障排除](docs/TROUBLESHOOTING.zh.md)**

</div>

企业级文档解析服务，基于 Celery 实现异步队列处理，采用完全解耦的 API/Worker 架构。

**Think** 系列产品之一 —— 与 [ThinkWiki](https://github.com/wzdavid/ThinkWiki)（个人知识库）、ThinkDoc（企业知识库）、ThinkExtract（数据抽取平台）并列。ThinkParse 是开源解析层：可插拔后端（当前为 MinerU，后续计划支持 Docling 等），对外提供稳定的 HTTP API。

仓库地址：**https://github.com/wzdavid/ThinkParse**

## 功能特性

- 🚀 **异步处理**: 基于 Celery 的分布式任务队列
- 📄 **多格式支持**: PDF、Office、图片等多种文档格式
- 🔄 **高可用性**: 支持任务重试和故障恢复
- 📊 **实时监控**: 任务状态跟踪和队列统计
- 🎯 **优先级队列**: 支持任务优先级调度
- 🔧 **易于扩展**: 模块化设计，易于添加新的解析引擎

## 快速开始

### 前置准备

- Docker 和 Docker Compose
- （可选）NVIDIA GPU（用于 GPU Worker）

### 最简单的方式（推荐）

**4 步启动服务**：

1. **复制配置文件**:
   ```bash
   # 项目根目录
   cp .env.example .env
   cd docker && cp .env.example .env
   ```

2. **配置服务选择**（在 `docker/.env` 中）:
   ```bash
   cd docker
   # 编辑 .env 文件，设置 COMPOSE_PROFILES（选择一种）
   
   # 方式 1: GPU Worker + 内部 Redis（默认值，需要 NVIDIA GPU）
   COMPOSE_PROFILES=redis,mineru-gpu
   
   # 方式 2: CPU Worker + 内部 Redis（推荐开发环境）
   # COMPOSE_PROFILES=redis,mineru-cpu
   ```
   
   > 💡 **说明**：
   > - 默认值：`COMPOSE_PROFILES=redis,mineru-gpu`（GPU Worker）
   > - 通过 `COMPOSE_PROFILES` 控制启动 Redis 和 Worker
   > - API 和 Cleanup 服务会自动启动（没有 profile，必需服务）

3. **构建镜像**:
   ```bash
   cd docker
   # 最简单：直接运行（会根据 COMPOSE_PROFILES 自动选择构建 CPU 或 GPU Worker）
   sh build.sh
   
   # 或者手动指定（build.sh 支持参数方式，只构建需要的服务）
   # GPU Worker:
   sh build.sh --api --worker-gpu
   # CPU Worker:
   sh build.sh --api --worker-cpu
   ```

4. **启动服务**:
   ```bash
   cd docker
   # 最简单：直接启动（会根据 COMPOSE_PROFILES 自动启动配置的服务）
   docker compose up -d
   
   # 或者手动指定（等价方式）
   # GPU Worker:
   docker compose --profile redis --profile mineru-gpu up -d
   # CPU Worker:
   docker compose --profile redis --profile mineru-cpu up -d
   ```

5. **验证服务**:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

完成！API 现在运行在 `http://localhost:8000`。

> 💡 **提示**：
> - 使用 `COMPOSE_PROFILES` 配置后，`sh build.sh` 和 `docker compose up -d` 都会自动识别
> - `sh build.sh` 不带参数时会根据 `COMPOSE_PROFILES` 自动选择构建 CPU 或 GPU Worker
> - 也可以使用参数明确指定：`sh build.sh --api --worker-gpu` 或 `sh build.sh --api --worker-cpu`
> - 更多配置选项见 [docker/README.zh.md](docker/README.zh.md)

## API 使用

ThinkParse 提供了两种 API 接口，以适应不同的使用场景：

### 1. MinerU 官方 API（同步）

`/file_parse` 端点兼容 MinerU 官方 API 格式。它将任务提交到 worker 并等待完成，直接在响应中返回结果。

> 说明：`/file_parse` 是兼容接口，适合单机部署或简单集成场景。对于 S3 存储、多 worker、多机等生产环境，建议使用 `/api/v1/tasks/submit` + 状态轮询。

**参考**: [MinerU 官方 API](https://github.com/opendatalab/MinerU/blob/master/mineru/cli/fast_api.py)

```bash
curl -X POST "http://localhost:8000/file_parse" \
  -F "files=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang_list=ch" \
  -F "parse_method=auto" \
  -F "return_md=true"
```

**适用场景**: 单机部署下的简单集成、需要立即获取结果、兼容现有 MinerU 客户端。

### 2. 异步队列 API（异步）

`/api/v1/tasks/submit` 和 `/api/v1/tasks/{task_id}` 端点提供基于异步队列的 API，兼容 mineru-tianshu 项目格式。

**参考**: [mineru-tianshu API](https://github.com/magicyuan876/mineru-tianshu/blob/main/backend/README.md)

**提交任务**:
```bash
curl -X POST "http://localhost:8000/api/v1/tasks/submit" \
  -F "file=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang=ch"
```

**查询任务状态**:
```bash
curl "http://localhost:8000/api/v1/tasks/{task_id}"
```

**适用场景**: 生产环境部署、批量处理、长时间运行任务、S3 存储、多 worker、多机与更好的可扩展性。

### 查看 API 文档

访问 `http://localhost:8000/docs` 查看包含完整参数详情的交互式 API 文档。

## 基本配置

### 环境变量

最重要的配置选项（查看 `.env.example` 获取所有选项）：

```bash
# Redis 配置
REDIS_URL=redis://redis:6379/0

# 存储类型：local 或 s3
MINERU_STORAGE_TYPE=local

# S3 存储配置（分布式部署）
MINERU_S3_ENDPOINT=http://minio:9000
MINERU_S3_ACCESS_KEY=minioadmin
MINERU_S3_SECRET_KEY=minioadmin

# CORS 配置（生产环境）
CORS_ALLOWED_ORIGINS=http://localhost:3000
ENVIRONMENT=production

# 文件上传限制
MAX_FILE_SIZE=104857600  # 100MB
```

## 文档

- [📖 完整文档](docs/README.zh.md) - 完整指南和配置说明 ([English](docs/README.md))
- [🚀 部署指南](docs/DEPLOYMENT.zh.md) - 生产环境部署 ([English](docs/DEPLOYMENT.md))
- [⚙️ 配置参考](docs/CONFIGURATION.zh.md) - 所有配置选项 ([English](docs/CONFIGURATION.md))
- [💡 API 示例](docs/API_EXAMPLES.zh.md) - 多语言代码示例 ([English](docs/API_EXAMPLES.md))
- [🔧 故障排除](docs/TROUBLESHOOTING.zh.md) - 常见问题和解决方案 ([English](docs/TROUBLESHOOTING.md))
- [🧹 存储与清理](docs/S3_STORAGE.zh.md) - 存储配置和清理 ([English](docs/S3_STORAGE.md))

## 架构

- **API 服务**: 处理任务提交和状态查询 (`api/app.py`)
- **Worker 服务**: 使用 MinerU/MarkItDown 处理文档 (`worker/tasks.py`)
- **Redis**: 消息队列和结果存储
- **共享配置**: 统一配置在 `shared/celeryconfig.py`

## 开发

### 设置开发环境

详细的开发环境设置说明，请查看 [docs/DEVELOPMENT.zh.md](docs/DEVELOPMENT.zh.md)。

**快速开始：**
```bash
# 使用自动化设置脚本（推荐）
chmod +x setup_venv.sh
./setup_venv.sh

# 或手动设置：
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r api/requirements.txt
pip install -r worker/requirements.txt
pip install -r cleanup/requirements.txt
```

## 贡献

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解指南。

## 致谢

本项目基于以下优秀的开源项目构建：

- **[MinerU](https://github.com/opendatalab/MinerU)** - 提供核心文档解析引擎（v3.4.x）
- **[mineru-tianshu](https://github.com/magicyuan876/mineru-tianshu)** - API 架构的参考和灵感来源

我们感谢这些项目的开发者和贡献者的宝贵工作。

## 许可证

MIT License - 查看 [LICENSE](LICENSE) 文件了解详情。

### 第三方许可证

本项目使用以下开源库：

- **MinerU** - 使用基于 [Apache 2.0](https://github.com/opendatalab/MinerU/blob/master/LICENSE) 的 [MinerU 开源许可证](https://github.com/opendatalab/MinerU/blob/master/LICENSE)（自 MinerU 3.1 起由 AGPL-3.0 升级）
- **MarkItDown** - 使用 [MIT](https://github.com/microsoft/markitdown) 许可证

MinerU 作为外部库使用，其源代码未包含在本仓库中。
