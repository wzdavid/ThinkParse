# Contributing

Thanks for helping improve ThinkParse. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) first.

## What this project is

ThinkParse is an open-source **enterprise document parsing system**: durable jobs, multi-GPU parallelism, distributed deployment, and a stable HTTP API. Parsing quality comes from external engines (MinerU 4.0, optional Docling). The Python package under `control/` does not load CUDA.

Product docs: [`docs/`](docs/README.md). Prefer those over archived drafts in [`docs/design/`](docs/design/).

## Setup

- Python 3.12 recommended (3.10+ supported)
- Docker when you need PostgreSQL. Object bytes use a local directory unless `THINKPARSE_S3_ENDPOINT` points at an external S3

```bash
pip install -r control/requirements-dev.txt
PYTHONPATH=. python -m unittest discover -s tests -p 'test_control_*.py'
ruff check control tests
```

## Pull requests

- Keep changes focused; match existing style in `control/`
- Add or update tests under `tests/test_control_*.py` when behavior changes
- Update docs when you change public API, deploy modes, or capacity knobs
- Do not commit secrets (`.env`, credentials)

## Useful links

- [Overview](docs/overview.zh.md)
- [Architecture](docs/architecture.zh.md)
- [API](docs/api.zh.md)
- [Security policy](SECURITY.md)
