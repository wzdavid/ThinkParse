<div align="center">

# ThinkParse

**Enterprise-grade document parsing — from one machine to distributed multi-GPU clusters.**

Open-source system that turns PDFs, scans, and more into clean Markdown and structured results through one production-ready API.
Built for RAG, knowledge bases, research pipelines, and long-running batch jobs — not just a demo script around a parsing model.

[![CI](https://github.com/wzdavid/ThinkParse/workflows/CI/badge.svg)](https://github.com/wzdavid/ThinkParse/actions)
[![Release](https://img.shields.io/github/v/release/wzdavid/ThinkParse)](https://github.com/wzdavid/ThinkParse/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

[English](README.md) · [简体中文](README.zh.md)

[Quick start](#quick-start) · [Why ThinkParse](#why-thinkparse) · [Docs](docs/README.md) · [Contributing](CONTRIBUTING.md)

</div>

## Why ThinkParse?

High-quality engines such as [MinerU](https://github.com/opendatalab/MinerU) solve *how to parse a document*. Production systems still need to answer:

- How do we parse **tens of thousands to millions** of files without client timeouts?
- How do we use **every GPU**, not just `cuda:0`?
- How do we keep jobs recoverable when a worker or engine restarts?
- How do we cancel, retry, observe, and clean up at scale?

ThinkParse is the **enterprise document parsing service** for that gap: a stable HTTP API, durable tasks, shared object storage, multi-GPU parallelism, and distributed deployment.

| Capability | What you get |
|---|---|
| **Reliable batch parsing** | Submit, poll, cancel; jobs survive restarts; higher `priority` (0–9) runs first without preempting work already on a GPU |
| **Multi-GPU parallelism** | MinerU runs one process per visible GPU; ThinkParse admits work via slots / in-flight bytes and can spread jobs across multiple engine URLs |
| **Distributed deployment** | API / reconciler on CPU hosts; GPU nodes only run engines; shared Postgres + external S3 |
| **Production API** | Async `/api/v1` for existing clients; resource-oriented `/api/v2` for new integrations |
| **Operational visibility** | Live / ready / deep health, tiers, stats, batches, timing (queue / parse / project) |
| **Quality outputs** | Markdown, tables, formulas, images, `content_list`, intermediate JSON |

Parsing quality comes from MinerU 4.0 (optional Docling for selected non-PDF formats). ThinkParse owns the **service layer**: scheduling, durability, capacity, and the stable API your apps call.

> Occasional one-off PDFs? Run MinerU alone.  
> RAG, knowledge bases, literature pipelines, or continuous batch conversion? Use ThinkParse.

## How it works

```text
Your apps
   │  POST /api/v1/tasks/submit   or   /api/v2/uploads + /api/v2/jobs
   ▼
┌──────────────────────────────────────────────┐
│ ThinkParse  (API + task orchestration)       │
│  Gateway · PostgreSQL · Object store · Loop  │
└──────────────────┬───────────────────────────┘
                   │ HTTP
        ┌──────────┴──────────┐
        ▼                     ▼
  MinerU 4.0 (multi-GPU)   Docling Serve (optional)
```

The API stays light. Heavy parsing runs on engine nodes. Scale GPUs or hosts without changing how clients submit work.

## Quick start

**Requirements:** Docker. For GPU mode: NVIDIA driver + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/).

```bash
git clone https://github.com/wzdavid/ThinkParse.git
cd ThinkParse
cp .env.example .env
# Pick one: COMPOSE_PROFILES=gpu | cpu | (empty → external MinerU)
# Change POSTGRES_PASSWORD (letters and digits only)

docker compose --env-file .env -f docker/docker-compose.yml up -d --build
curl -fsS http://127.0.0.1:8000/api/v1/health/live
curl -sS http://127.0.0.1:8000/api/v1/health/ready
curl -sS http://127.0.0.1:8000/api/v2/tiers
```

Submit a document (async — recommended for batch and production):

```bash
curl -sS \
  -F "file=@document.pdf" \
  -F "backend=pipeline" \
  http://127.0.0.1:8000/api/v1/tasks/submit
```

Poll `GET /api/v1/tasks/{task_id}` until `completed`, `failed`, or `cancelled`.

Full walkthrough: [Quick start](docs/quickstart.zh.md) · [Deployment](docs/deployment.zh.md).

## Deployment options

| Mode | When to use | Notes |
|---|---|---|
| **CPU** | Local trial, no GPU | `COMPOSE_PROFILES=cpu` — `flash` / `basic` |
| **GPU (single or multi)** | Production throughput | One GPU: `COMPOSE_PROFILES=gpu`. Two GPUs: `gpu,gpu1` plus `MINERU_BASE_URLS` / `THINKPARSE_SLOTS`. Tune `MINERU_GPU_CONCURRENCY` |
| **External engines** | You already run MinerU | Unset profile; set `MINERU_BASE_URL(S)` |
| **Distributed** | Separate API and GPU fleets | Shared Postgres + external S3; multiple MinerU URLs; capacity via slots and in-flight bytes |

Do not enable `cpu` and `gpu` together. Gateway listens on **8000**. See [Deployment](docs/deployment.zh.md) and [Operations](docs/operations.zh.md).

## API at a glance

| API | Use |
|---|---|
| `/api/v1/tasks/*` | Production async workflow (submit / poll / cancel) |
| `/file_parse` | Sync convenience only — prefer async in batch |
| `/api/v2/*` | Uploads, jobs, files, tiers, stats, batches |

Engine-native routes stay internal. See the [API reference](docs/api.zh.md).

## Who is it for?

- **RAG / knowledge-base teams** — uniform Markdown + structure before chunking and embedding
- **Research & data platforms** — batch papers, reports, contracts without holding HTTP open
- **AI product teams** — document parsing as a microservice, without shipping engine deps into every app
- **Infra / mid-platform** — multi-GPU and multi-node farms with shared storage and clear health signals

## Documentation

| Doc | Description |
|---|---|
| [Overview](docs/overview.zh.md) | Positioning, goals, non-goals |
| [Architecture](docs/architecture.zh.md) | System design, engines, data model |
| [Quick start](docs/quickstart.zh.md) | First successful parse |
| [Deployment](docs/deployment.zh.md) | Modes, acceptance, troubleshooting |
| [API](docs/api.zh.md) | `/api/v1` and `/api/v2` |
| [Operations](docs/operations.zh.md) | Stats, capacity, multi-GPU tuning |

## Development

```bash
pip install -r control/requirements-dev.txt
PYTHONPATH=. python -m unittest discover -s tests -p 'test_control_*.py'
ruff check control tests
```

## Acknowledgments

ThinkParse builds on [MinerU](https://github.com/opendatalab/MinerU), optional [Docling](https://github.com/docling-project/docling), FastAPI, PostgreSQL, and S3-compatible storage.

## License

[MIT](LICENSE). Third-party engines remain under their own licenses.
