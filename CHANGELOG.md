# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Future changes will be documented here

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

- **1.2.0**: Slim Redis results (hydrate from storage); Redis/temp disk isolation; faster temp cleanup; multi-GPU and multi-node deploy templates
- **1.1.0**: Rebrand to ThinkParse; MinerU 3.4.0 upgrade with subprocess environment variable fix
- **1.0.0**: Initial release with decoupled architecture and comprehensive features

---

For detailed commit history, see [GitHub Commits](https://github.com/wzdavid/ThinkParse/commits/main).
