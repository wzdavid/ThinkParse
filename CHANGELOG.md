# Changelog

## Unreleased

- `/api/v2/jobs/{id}` lists `middle_native` (the unprojected MinerU middle, `middle_native.json`) and `content_list` (`content_list.json`, same array as the `/api/v1` response) in `output_files` for completed MinerU jobs. Download them with `GET /api/v2/files/{file_id}/content`. The `/api/v1` `middle_json` projection is unchanged. Jobs completed before this change do not list the new keys.

## 2.1.0

- Reconciler stays up when MinerU is unreachable, drops a connection, or returns a partial body. Those tasks wait and resume after the engine recovers. `THINKPARSE_MAX_ATTEMPTS` does not fail that wait. Cancelling a task still completes locally if the upstream cannot be reached.

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
