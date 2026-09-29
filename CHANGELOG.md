# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.2] - 2026-09-29

Stop local parse storage from filling the disk and halting Redis.

### Added
- Free-space watermarks for the filesystem that holds temp and output data.
  Defaults keep an absolute reserve (16 GiB reclaim, 8 GiB floor), capped to a
  percentage of small disks
- Cleanup runs as soon as the process starts, then checks disk headroom on
  `DISK_CHECK_INTERVAL_MINUTES` even when `CLEANUP_INTERVAL_HOURS` is long
- New submissions return HTTP 507, and queued tasks wait, while free space is
  under the reclaim line. `/health/ready` reports storage unavailable; liveness
  does not restart the API for a full disk

### Fixed
- The scheduler no longer waits a full cleanup interval before the first deletion
- Pressure deletion skips symlinks and paths outside the configured directories,
  and never removes data younger than `TASK_TIME_LIMIT`

## [1.4.1] - 2026-09-27

Productized multi-GPU and multi-worker deployment. Operators set card count and
workers per card; Compose service blocks no longer need to be copied by hand.

### Added
- `docker/gpu-up.sh` and `docker/render-gpu-workers.py` generate
  `docker-compose.gpus.yml` from `MINERU_GPU_COUNT` and `MINERU_WORKERS_PER_GPU`
- Profile `mineru-multi-gpu` starts every generated worker; optional
  `MINERU_GPU_WORKER_ONLY=1` for dedicated GPU hosts
- CI check that validates the renderer and `gpu-up.sh` shell syntax

### Changed
- Document `GPU_WORKER_CONCURRENCY=1` as per-process; scale with more containers
  on the same card rather than raising Celery concurrency
- Point deployment docs at `sh gpu-up.sh`; keep `docker-compose.multi-gpu.yml`
  as the legacy one-container-per-card template

### Fixed
- Stop stale GPU worker containers (legacy names and extra slots after shrinking
  `MINERU_WORKERS_PER_GPU`) before starting the generated set, after validating
  Compose and confirming `mineru-worker:latest` exists

## [1.4.0] - 2026-09-11

Single-container deployment for schedulers that accept only one container
(Tianhe / HPC). The four-container Compose stack remains the default.

### Added
- GPU and CPU all-in-one images (`mineru-allinone`, `mineru-allinone-cpu`)
- Supervisord process tree that runs Redis, API, Worker, and cleanup in one container
- `docker-compose.allinone.yml` and `build.sh --allinone` / `--allinone-cpu`
- English and Chinese single-container deployment guides
- CI check that validates all-in-one entrypoint, supervisor programs, and Docker files

## [1.3.0] - 2026-09-02

Production stability and observability upgrade with MinerU 3.4.5, native
long-document processing, cancellable engine isolation, and layered health
diagnostics.

### Added
- Document MinerU processing-window configuration and single-GPU recovery guidance
- Add liveness, readiness, and deep diagnostic health endpoints
- Publish Worker/task heartbeat state to Redis for operational visibility
- Report actual Redis broker queue depth and active-task runtime
- Run MinerU in a persistent isolated process so models are reused while active parses remain killable
- Sample GPU identity, driver, utilization, memory, and temperature metrics
- Add a Worker watchdog that exits overdue tasks for supervisor-driven recovery
- Persist watchdog cancellation before exit so late-ack task redelivery terminates safely
- Probe configured S3 buckets during readiness checks with a bounded API wait
- Set Redis broker visibility above the task/watchdog limits to prevent duplicate long-task delivery

### Changed
- Default Worker concurrency to one active task per GPU
- Use MinerU's built-in processing windows for long PDFs by default
- Keep ThinkParse physical PDF splitting as a deprecated compatibility fallback
- Align Compose, environment examples, and deployment documentation with the stable single-GPU profile
- Move blocking Celery waits and inspections off the FastAPI event loop
- Store cancellation requests in Redis and terminate the active isolated MinerU engine
- Enforce MinerU wall-clock timeout independently of unsupported Celery thread time limits
- Restart the isolated engine automatically after cancellation, timeout, crash, or parse failure
- Keep `live` and `ready` health payloads aggregate while exposing full runtime diagnostics through `deep`
- Upgrade MinerU from **3.4.0** to **3.4.5**
- Pin `mineru[pipeline]==3.4.5` in `worker/requirements.txt`
- Pin `mineru[core]==3.4.5` in GPU base Docker image (`docker/Dockerfile.base`)
- Add `--rebuild-base` to prevent MinerU upgrades from reusing a stale GPU base image

### Upgrade notes
- Updating the repository or container images does not modify an existing `.env`;
  compare it with `.env.example` and apply the new settings explicitly
- Rebuild the MinerU base and Worker images after upgrading
  (`cd docker && sh build.sh --worker-gpu --rebuild-base`)
- Restart API + Worker + cleanup containers so all nodes run 3.4.5
- Existing task submission and result response shapes remain compatible with
  ThinkExtract / ThinkDoc
- Cancellation now acknowledges with `cancel_requested`; clients should poll
  until the task reaches `cancelled` or another terminal state
- `/api/v1/health` and `/health/ready` return HTTP 503 while dependencies are
  unavailable; `/health/deep` contains deployment details and must be restricted
- MinerU 3.4.5 fixes: PDFium page bounds, Latin/CJK font detection, duplicate character rendering, DOCX table special characters, Unicode surrogate pairs
- Existing deployments must explicitly set the new Worker concurrency,
  processing-window, heartbeat, and engine-timeout environment values

## [1.2.0] - 2026-07-15

Production hardening: keep Redis as a slim Celery queue (no parse bodies), isolate Redis disk from temp/output, shorten temp cleanup defaults, and document single-host multi-GPU plus multi-node scale-out.

### Added
- `shared/task_result.py`: slim Celery/Redis results; hydrate markdown / `images[]` / JSON from storage for the status API (response shape unchanged for ThinkDoc / ThinkExtract)
- `docker/docker-compose.multi-gpu.yml`: one worker per GPU (`mineru-gpu-0` … `mineru-gpu-7`)
- `docker/docker-compose.worker-only.yml`: disable local API/cleanup on dedicated GPU hosts
- Docs: multi-node production guide (`docs/PRODUCTION_MULTI_NODE.md` / `.zh.md`); Redis `REDIS_DATA_PATH` guidance in deployment docs
- `TEMP_MAX_AGE_HOURS` (default 6) wired through cleanup scheduler / Compose

### Changed
- Celery task results no longer store full markdown, base64 `images[]`, or inline `content_list` / `middle_json` in Redis (AOF/memory grow only with queue metadata)
- Default cleanup interval `CLEANUP_INTERVAL_HOURS`: 24 → **6**; temp orphan age: 24 → **6** (above `TASK_TIME_LIMIT=2h`)
- Docker Redis volume can bind via `REDIS_DATA_PATH` (keep off the temp/output disk)

### Fixed
- S3 `download_to_local`: preserve remote file suffix so `get_file_type()` still selects MinerU for PDFs/images

### Upgrade notes
- Rebuild/restart **API + Worker + cleanup** images/containers so slim-result + hydrate code is live
- Production: set `REDIS_DATA_PATH` on a disk separate from `mineru_temp` / `mineru_output`
- Multi-GPU single host: `COMPOSE_FILE=docker-compose.yml:docker-compose.multi-gpu.yml` and profiles `mineru-gpu-0,...` (do not also enable `mineru-gpu`)
- Multi-node GPU hosts: also load `docker-compose.worker-only.yml`; point `REDIS_URL` / S3 at shared services
- Configure S3 temp bucket lifecycle when using `MINERU_STORAGE_TYPE=s3`
- Public HTTP API fields are unchanged; clients need no code change

## [1.1.0] - 2026-06-24

Upgrade the parsing engine to **MinerU 3.4.0** and rebrand the project as **ThinkParse**.

### Changed
- Rebrand project from MinerU-API to **ThinkParse** (repository: `wzdavid/ThinkParse`). Docker service and image names (`mineru-api`, `mineru-worker`, etc.) are unchanged for deployment compatibility
- Upgrade MinerU parsing engine from 2.x to `3.4.0` (`mineru[pipeline]==3.4.0`)
- Pin `mineru[core]==3.4.0` in GPU base Docker image for version consistency
- Update README third-party license for MinerU (Apache 2.0-based MinerU Open Source License, formerly AGPL-3.0)

### Fixed
- Fix `KeyError` on `MINERU_DEVICE_MODE` when MinerU 3.4.0 spawns subprocesses that re-import `worker/tasks.py` (use `os.environ.pop` instead of `del`)

### Upgrade notes
- Rebuild Worker Docker images after upgrading (`cd docker && sh build.sh`)
- MinerU 3.4.0 includes new models (e.g. PP-OCRv6); model download runs automatically during image build

## [1.0.0] - 2026-01-08

### Added
- Initial release
- Asynchronous document parsing service based on Celery
- Decoupled API/Worker architecture
- Support for multiple document formats (PDF, Office, images)
- MinerU and MarkItDown parsing backends
- Local and S3-compatible storage support
- Task priority queue
- Real-time task status tracking
- Queue statistics and monitoring
- Docker Compose deployment
- CPU and GPU worker support
- Automatic cleanup service
- Health check endpoints
- Comprehensive API documentation (FastAPI/Swagger)
- Comprehensive documentation (README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY)
- CI/CD pipeline with GitHub Actions

### Features
- **API Service**: Lightweight FastAPI service for task submission and querying
- **Worker Service**: Celery-based worker for document parsing
- **Storage Abstraction**: Unified interface for local filesystem and S3 storage
- **Task Management**: Submit, query, cancel, and monitor parsing tasks
- **Multi-format Support**: PDF, images (PNG, JPG, etc.), Office documents (Word, Excel, PowerPoint)
- **Language Support**: Chinese, English, and other languages
- **Image Processing**: Base64 encoding and MinIO upload support
- **Cleanup Service**: Automatic cleanup of expired output files

### Technical Details
- Python 3.10+ support
- FastAPI for API layer
- Celery 5.3+ for task queue
- Redis for message broker and result backend
- Docker containerization
- S3-compatible storage (MinIO, AWS S3)

### Documentation
- Comprehensive README (English and Chinese)
- API documentation
- Deployment guides
- Storage configuration guides
- Troubleshooting guides

---

## Types of Changes

- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for any bug fixes
- **Security** for vulnerability fixes

---

## Version History

- **1.4.2**: Disk headroom watermarks so local temp/output cannot fill the disk and stop Redis
- **1.4.1**: Productized multi-GPU workers via `gpu-up.sh` (`MINERU_GPU_COUNT` × `MINERU_WORKERS_PER_GPU`)
- **1.4.0**: Single-container GPU/CPU images for Tianhe/HPC; four-container Compose remains default
- **1.3.0**: MinerU 3.4.5, cancellable engine isolation, native long-document windows, and layered health diagnostics
- **1.2.0**: Slim Redis results (hydrate from storage); Redis/temp disk isolation; faster temp cleanup; multi-GPU and multi-node deploy templates
- **1.1.0**: Rebrand to ThinkParse; MinerU 3.4.0 upgrade with subprocess environment variable fix
- **1.0.0**: Initial release with decoupled architecture and comprehensive features

---

For detailed commit history, see [GitHub Commits](https://github.com/wzdavid/ThinkParse/commits/main).
