<div align="center">

<h1>ThinkParse</h1>

<p><strong>Turn complex documents into clean, structured content through one production-ready API.</strong></p>

<p>
  An open-source document parsing service powered by MinerU, FastAPI, Celery, and Redis.<br />
  Built for reliable PDF, image, and Office document processing—from one machine to distributed GPU workers.
</p>

[![CI](https://github.com/wzdavid/ThinkParse/workflows/CI/badge.svg)](https://github.com/wzdavid/ThinkParse/actions)
[![Release](https://img.shields.io/github/v/release/wzdavid/ThinkParse)](https://github.com/wzdavid/ThinkParse/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

[English](README.md) · [简体中文](README.zh.md)

[Quick start](#quick-start) · [API usage](#api-usage) · [Deployment](docs/DEPLOYMENT.md) · [Configuration](docs/CONFIGURATION.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)

</div>

## Why ThinkParse?

Document parsing becomes difficult when workloads grow beyond a local script. Large PDFs take time, GPU processes can fail, results may exceed queue storage limits, and production deployments need observable, recoverable workers.

ThinkParse packages the parsing engine behind a stable HTTP API and an asynchronous worker architecture:

- **High-quality document parsing** — extracts Markdown, tables, formulas, images, and structured intermediate results with MinerU 3.4.5.
- **Multiple document formats** — routes PDF and image files through MinerU, and Office, HTML, and text formats through MarkItDown.
- **Production task workflow** — submit, poll, prioritize, cancel, and inspect parsing jobs without holding client connections open.
- **CPU and GPU deployment** — start locally with a CPU worker, use one or multiple GPUs on a server, scale workers across nodes, or run Redis+API+Worker+Cleanup in **one container** for schedulers such as Tianhe.
- **Reliable long-document processing** — reuses the parsing engine between jobs while isolating it for cancellation, timeout recovery, and automatic restart.
- **Storage that scales** — use local volumes for a single host or S3-compatible storage for distributed deployments.
- **Operational visibility** — layered health checks expose readiness, queue depth, worker heartbeats, task runtime, and GPU status.

## How it works

```text
Client → FastAPI → Redis queue → Celery worker → MinerU / MarkItDown
   ↑                                              ↓
   └──────────── status and results ───── local or S3 storage
```

The API stays lightweight while workers perform the expensive parsing. Add workers without changing the client integration.

## Quick start

### Requirements

- Docker with Docker Compose
- Optional: NVIDIA GPU, NVIDIA Container Toolkit, and sufficient VRAM for GPU parsing

> The first build or first CPU parse may take longer while dependencies and models are downloaded.

### 1. Clone and configure

```bash
git clone https://github.com/wzdavid/ThinkParse.git
cd ThinkParse
cp .env.example .env
cp docker/.env.example docker/.env
```

For the easiest local trial, open `docker/.env` and select the CPU profile:

```dotenv
COMPOSE_PROFILES=redis,mineru-cpu
```

For an NVIDIA GPU host, use:

```dotenv
COMPOSE_PROFILES=redis,mineru-gpu
```

### 2. Build and start

```bash
cd docker
sh build.sh
docker compose up -d
```

### 3. Verify

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

When readiness returns HTTP `200`, open:

- Interactive API documentation: <http://localhost:8000/docs>
- Service metadata: <http://localhost:8000/>

View logs or stop the stack:

```bash
docker compose logs -f
docker compose down
```

## API usage

ThinkParse provides an asynchronous API for production workloads and a synchronous MinerU-compatible endpoint for simple integrations.

### Recommended: asynchronous task API

Submit a document:

```bash
curl -X POST "http://localhost:8000/api/v1/tasks/submit" \
  -F "file=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang=en"
```

The response contains a `task_id`:

```json
{
  "success": true,
  "task_id": "abc123",
  "status": "pending"
}
```

Poll until the task reaches `completed`, `failed`, or `cancelled`:

```bash
curl "http://localhost:8000/api/v1/tasks/abc123"
```

Cancel a task:

```bash
curl -X DELETE "http://localhost:8000/api/v1/tasks/abc123"
```

The asynchronous API is the right choice for batch processing, long-running documents, S3 storage, multiple workers, and multi-node deployments.

### Synchronous compatibility API

For a simple single-host integration that should wait for the result:

```bash
curl -X POST "http://localhost:8000/file_parse" \
  -F "files=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang_list=en" \
  -F "parse_method=auto" \
  -F "return_md=true"
```

This endpoint follows the MinerU `/file_parse` request style. Prefer the asynchronous API in production because a synchronous request remains open for the entire parse.

See [API Examples](docs/API_EXAMPLES.md) for Python, JavaScript, batch processing, priorities, and error handling.

## Deployment options

### Single host

- **CPU:** `COMPOSE_PROFILES=redis,mineru-cpu`
- **Single GPU:** `COMPOSE_PROFILES=redis,mineru-gpu`
- **Multiple GPUs:** use `docker-compose.multi-gpu.yml` to bind one worker to each GPU

### Distributed deployment

Use shared Redis and S3-compatible storage, then run API and worker services on separate hosts. See [Large-scale multi-node deployment](docs/PRODUCTION_MULTI_NODE.md).

### Production checklist

- Set `ENVIRONMENT=production` and restrict `CORS_ALLOWED_ORIGINS`.
- Protect Redis with authentication and keep its persistence data on a disk separate from parsing output.
- Use S3-compatible storage when workers do not share a filesystem.
- Keep one active MinerU task per GPU; scale by adding workers rather than increasing per-GPU concurrency.
- Restrict `/api/v1/health/deep` to operators because it exposes detailed runtime diagnostics.

## Health and operations

- `GET /api/v1/health/live` — API process liveness
- `GET /api/v1/health/ready` — Redis, storage, and worker readiness
- `GET /api/v1/health/deep` — detailed queue, task, engine, and GPU diagnostics
- `GET /api/v1/queue/stats` — current queue and worker counts
- `GET /api/v1/queue/tasks` — active and reserved tasks

## Documentation

- [Documentation index](docs/README.md)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Single-container deployment (Tianhe)](docs/DEPLOYMENT_ALLINONE.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [API examples](docs/API_EXAMPLES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [S3 storage and cleanup](docs/S3_STORAGE.md)
- [Development guide](docs/DEVELOPMENT.md)

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before contributing, and report security issues according to [SECURITY.md](SECURITY.md).

## Acknowledgments

ThinkParse is built with:

- [MinerU](https://github.com/opendatalab/MinerU) — document parsing engine
- [MarkItDown](https://github.com/microsoft/markitdown) — Office, HTML, and text conversion
- [FastAPI](https://fastapi.tiangolo.com/), [Celery](https://docs.celeryq.dev/), and [Redis](https://redis.io/) — API and distributed task infrastructure

## License

ThinkParse is released under the [MIT License](LICENSE). Third-party components remain subject to their respective licenses, including the [MinerU Open Source License](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md) and the [MarkItDown MIT License](https://github.com/microsoft/markitdown/blob/main/LICENSE).
