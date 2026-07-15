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

**[📖 Deployment Guide](docs/DEPLOYMENT.md)** • **[⚙️ Configuration](docs/CONFIGURATION.md)** • **[💡 API Examples](docs/API_EXAMPLES.md)** • **[🔧 Troubleshooting](docs/TROUBLESHOOTING.md)**

</div>

Enterprise-grade document parsing service with asynchronous queue processing based on Celery, featuring a fully decoupled API/Worker architecture.

Part of the **Think** product family — alongside [ThinkWiki](https://github.com/wzdavid/ThinkWiki) (personal knowledge base), ThinkDoc (enterprise knowledge base), and ThinkExtract (data extraction). ThinkParse is the open-source parsing layer: pluggable backends (MinerU today; Docling and others planned) behind a stable HTTP API.

Repository: **https://github.com/wzdavid/ThinkParse**

## Features

- 🚀 **Asynchronous Processing**: Distributed task queue based on Celery
- 📄 **Multi-format Support**: PDF, Office, images, and various document formats
- 🔄 **High Availability**: Supports task retry and fault recovery
- 📊 **Real-time Monitoring**: Task status tracking and queue statistics
- 🎯 **Priority Queue**: Supports task priority scheduling
- 🔧 **Easy to Extend**: Modular design, easy to add new parsing engines

## Quick Start

### Prerequisites

- Docker and Docker Compose
- (Optional) NVIDIA GPU for GPU worker

### Simplest Way (Recommended)

**4 steps to start**:

1. **Copy configuration files**:
   ```bash
   # Project root
   cp .env.example .env
   cd docker && cp .env.example .env
   ```

2. **Configure service selection** (in `docker/.env`):
   ```bash
   cd docker
   # Edit .env file, set COMPOSE_PROFILES (choose one)
   
   # Option 1: GPU Worker + internal Redis (default, requires NVIDIA GPU)
   COMPOSE_PROFILES=redis,mineru-gpu
   
   # Option 2: CPU Worker + internal Redis (recommended for development)
   # COMPOSE_PROFILES=redis,mineru-cpu
   ```
   
   > 💡 **Notes**:
   > - Default: `COMPOSE_PROFILES=redis,mineru-gpu` (GPU Worker)
   > - Control which services start via `COMPOSE_PROFILES` (Redis and Worker)
   > - API and Cleanup services start automatically (no profile, required services)

3. **Build images**:
   ```bash
   cd docker
   # Simplest: run directly (automatically selects CPU or GPU Worker based on COMPOSE_PROFILES)
   sh build.sh
   
   # Or manually specify (build.sh supports parameters to build only needed services)
   # GPU Worker:
   sh build.sh --api --worker-gpu
   # CPU Worker:
   sh build.sh --api --worker-cpu
   ```

4. **Start services**:
   ```bash
   cd docker
   # Simplest: start directly (automatically starts configured services based on COMPOSE_PROFILES)
   docker compose up -d
   
   # Or manually specify (equivalent ways)
   # GPU Worker:
   docker compose --profile redis --profile mineru-gpu up -d
   # CPU Worker:
   docker compose --profile redis --profile mineru-cpu up -d
   ```

5. **Verify services**:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

That's it! The API is now running at `http://localhost:8000`.

> 💡 **Tips**:
> - After configuring `COMPOSE_PROFILES`, both `sh build.sh` and `docker compose up -d` will automatically recognize it
> - `sh build.sh` without parameters automatically selects CPU or GPU Worker based on `COMPOSE_PROFILES`
> - You can also use parameters to explicitly specify: `sh build.sh --api --worker-gpu` or `sh build.sh --api --worker-cpu`
> - See [docker/README.md](docker/README.md) for more configuration options

## API Usage

ThinkParse provides two API interfaces to suit different use cases:

### 1. Official MinerU API (Synchronous)

The `/file_parse` endpoint is compatible with the official MinerU API format. It submits tasks to the worker and waits for completion, returning results directly in the response.

> Note: `/file_parse` is a compatibility interface intended for single-host or simple integration scenarios. In S3 storage, multi-worker, or multi-node production deployments, use `/api/v1/tasks/submit` + status polling instead.

**Reference**: [MinerU Official API](https://github.com/opendatalab/MinerU/blob/master/mineru/cli/fast_api.py)

```bash
curl -X POST "http://localhost:8000/file_parse" \
  -F "files=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang_list=ch" \
  -F "parse_method=auto" \
  -F "return_md=true"
```

**Use cases**: Simple integration, immediate results needed, compatible with existing MinerU clients on single-host deployments.

### 2. Async Queue API (Asynchronous)

The `/api/v1/tasks/submit` and `/api/v1/tasks/{task_id}` endpoints provide an asynchronous queue-based API, compatible with the mineru-tianshu project format.

**Reference**: [mineru-tianshu API](https://github.com/magicyuan876/mineru-tianshu/blob/main/backend/README.md)

**Submit a Task**:
```bash
curl -X POST "http://localhost:8000/api/v1/tasks/submit" \
  -F "file=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang=ch"
```

**Query Task Status**:
```bash
curl "http://localhost:8000/api/v1/tasks/{task_id}"
```

**Use cases**: Production deployments, batch processing, long-running tasks, S3 storage, multi-worker, and better scalability.

### View API Documentation

Visit `http://localhost:8000/docs` for interactive API documentation with full parameter details.

## Basic Configuration

### Environment Variables

The most important configuration options (see `.env.example` for all options):

```bash
# Redis Configuration
REDIS_URL=redis://redis:6379/0

# Storage Type: local or s3
MINERU_STORAGE_TYPE=local

# For S3 storage (distributed deployment)
MINERU_S3_ENDPOINT=http://minio:9000
MINERU_S3_ACCESS_KEY=minioadmin
MINERU_S3_SECRET_KEY=minioadmin

# CORS Configuration (production)
CORS_ALLOWED_ORIGINS=http://localhost:3000
ENVIRONMENT=production

# File Upload Limits
MAX_FILE_SIZE=104857600  # 100MB
```

## Documentation

- [📖 Full Documentation](docs/README.md) - Complete guide and configuration (English | [中文](docs/README.zh.md))
- [🚀 Deployment Guide](docs/DEPLOYMENT.md) - Production deployment ([中文](docs/DEPLOYMENT.zh.md))
- [⚙️ Configuration Reference](docs/CONFIGURATION.md) - All configuration options ([中文](docs/CONFIGURATION.zh.md))
- [💡 API Examples](docs/API_EXAMPLES.md) - Code examples in multiple languages ([中文](docs/API_EXAMPLES.zh.md))
- [🔧 Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions ([中文](docs/TROUBLESHOOTING.zh.md))
- [🧹 Storage & Cleanup](docs/S3_STORAGE.md) - Storage configuration and cleanup ([中文](docs/S3_STORAGE.zh.md))

## Architecture

- **API Service**: Handles task submission and status queries (`api/app.py`)
- **Worker Service**: Processes documents using MinerU/MarkItDown (`worker/tasks.py`)
- **Redis**: Message queue and result storage
- **Shared Config**: Unified configuration in `shared/celeryconfig.py`

## Development

### Setting Up Development Environment

For detailed development environment setup instructions, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

**Quick Start:**
```bash
# Use the automated setup script (recommended)
chmod +x setup_venv.sh
./setup_venv.sh

# Or manually:
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r api/requirements.txt
pip install -r worker/requirements.txt
pip install -r cleanup/requirements.txt
```

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Acknowledgments

This project is built on top of the following excellent open-source projects:

- **[MinerU](https://github.com/opendatalab/MinerU)** - The core document parsing engine that powers this service (v3.4.x)
- **[mineru-tianshu](https://github.com/magicyuan876/mineru-tianshu)** - Inspiration and reference for the API architecture

We are grateful to the developers and contributors of these projects for their valuable work.

## License

MIT License - see [LICENSE](LICENSE) file for details.

### Third-Party Licenses

This project uses the following open-source libraries:

- **MinerU** - Licensed under the [MinerU Open Source License](https://github.com/opendatalab/MinerU/blob/master/LICENSE) (Apache 2.0-based; upgraded from AGPL-3.0 in MinerU 3.1+)
- **MarkItDown** - Licensed under [MIT](https://github.com/microsoft/markitdown)

MinerU is used as an external library and its source code is not included in this repository.
