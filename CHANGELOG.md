# Changelog

## 2.0.0

Enterprise document parsing system rebuilt for MinerU 4.0 and durable orchestration.

- Persistent jobs in PostgreSQL; sources and artifacts on a local directory, or external S3 when several hosts share them
- Gateway + reconciler (no Celery / Redis task bus)
- Multi-GPU and distributed-friendly deploy modes: `gpu`, `cpu`, `external`
- Public `/api/v1` (async tasks) and `/api/v2` (uploads, jobs, files, tiers, stats, batches)
- MinerU 4.0 adapter with stable projection for `content_list` / `middle_json`
- Optional Docling adapter for `.xml` / `.tex` / `.eml`

Earlier 1.x releases remain on git tags through `v1.4.2`.
