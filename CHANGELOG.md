# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Future changes will be documented here

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

- **1.1.0**: Rebrand to ThinkParse; MinerU 3.4.0 upgrade with subprocess environment variable fix
- **1.0.0**: Initial release with decoupled architecture and comprehensive features

---

For detailed commit history, see [GitHub Commits](https://github.com/wzdavid/ThinkParse/commits/main).
