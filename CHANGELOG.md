# Changelog

## 2.0.1

- Reconciler admits every free MinerU slot in one cycle. Polling and submission run in parallel, bounded by `THINKPARSE_SLOTS` and a 32-thread cap.
- A claim records its target MinerU URL before submission, so one address cannot take another address's slots.
- Chinese deployment guide, security and operations notes. Dependabot configuration removed.

## 2.0.0

Enterprise document parsing system rebuilt for MinerU 4.0 and durable orchestration.

- Persistent jobs in PostgreSQL; sources and artifacts on a local directory, or external S3 when several hosts share them
- Gateway + reconciler (no Celery / Redis task bus)
- Multi-GPU and distributed-friendly deploy modes: `gpu`, `cpu`, `external`
- Public `/api/v1` (async tasks) and `/api/v2` (uploads, jobs, files, tiers, stats, batches)
- MinerU 4.0 adapter with stable projection for `content_list` / `middle_json`
- Optional Docling adapter for `.xml` / `.tex` / `.eml`

Earlier 1.x releases remain on the `1.x` branch and git tags through `v1.4.3`.
