# Single-container deployment (Tianhe / HPC)

The four-container Compose stack (Redis, API, Worker, Cleanup) remains the default production topology.  
Use the all-in-one image when the scheduler can **submit only one container**. Supervisord starts all four roles in that container.

- GPU image: `mineru-allinone:latest` (`docker/Dockerfile.allinone`)
- CPU image: `mineru-allinone-cpu:latest` (`docker/Dockerfile.allinone.cpu`)
- 中文: [DEPLOYMENT_ALLINONE.zh.md](DEPLOYMENT_ALLINONE.zh.md)

## When to use this

| Situation | Deploy with |
|-----------|-------------|
| Normal server / Docker Compose | [DEPLOYMENT.md](DEPLOYMENT.md) four-container stack |
| Multi-host multi-GPU | [PRODUCTION_MULTI_NODE.md](PRODUCTION_MULTI_NODE.md) |
| Tianhe or any single-container compute pool | **This all-in-one image** |

Redis listens on `127.0.0.1:6379` inside the container. Only port **8000** is published. If the Worker watchdog exits the Worker process, supervisord restarts that program without recycling the whole container.

## Build

```bash
cd docker

# GPU (typical Tianhe GPU queue)
sh build.sh --allinone

# CPU (no GPU / CPU queue)
sh build.sh --allinone-cpu
```

`--allinone` builds `mineru-vllm:latest` first when the base image is missing. Expect the same cost as a GPU Worker build.

## Tianhe / single-container run

Point the scheduler at **one image**, one GPU, port 8000, and data mounts. Equivalent to:

```bash
docker run --rm --gpus all \
  --name thinkparse \
  -p 8000:8000 \
  --env-file .env \
  -e MINERU_DEVICE_MODE=cuda \
  -e WORKER_CONCURRENCY=1 \
  -v /data/thinkparse/output:/tmp/mineru_output \
  -v /data/thinkparse/temp:/tmp/mineru_temp \
  -v /data/thinkparse/redis:/data/redis \
  mineru-allinone:latest
```

For a CPU queue, drop `--gpus all`, use `mineru-allinone-cpu:latest`, and set `-e MINERU_DEVICE_MODE=cpu`.

### Scheduler fields

| Field | Value |
|-------|--------|
| Image | `mineru-allinone:latest` |
| Replica / container count | **1** |
| GPU | 1 (`WORKER_CONCURRENCY=1`) |
| Port | `8000` |
| Env | See below; **do not** set `REDIS_URL=redis://redis:6379/0` |
| Volumes | output + temp; also `/data/redis` if the queue must survive restarts |

The entrypoint **forces** `REDIS_URL=redis://127.0.0.1:6379/0` so a four-container `.env` that still says hostname `redis` cannot break DNS inside this image.

### Environment

Same variables as the four-container stack; see [CONFIGURATION.md](CONFIGURATION.md). For all-in-one:

| Variable | Suggestion |
|----------|------------|
| `MINERU_DEVICE_MODE` | `cuda` on GPU; `cpu` on CPU |
| `WORKER_CONCURRENCY` | keep `1` on GPU |
| `TEMP_DIR` / `OUTPUT_DIR` | defaults `/tmp/mineru_temp`, `/tmp/mineru_output` |
| `CLEANUP_INTERVAL_HOURS` | default `6`; cleanup runs in the same container |

Parse options (`backend`, language, formula/table flags) are still submitted through the API.

## Local Compose smoke test

Do not start this file together with `docker-compose.yml` (port 8000 will clash).

```bash
cd docker

# GPU
docker compose -f docker-compose.allinone.yml --profile allinone-gpu up -d

# CPU
docker compose -f docker-compose.allinone.yml --profile allinone-cpu up -d
```

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

`ready` returns 503 until the Worker heartbeat is in Redis. GPU startup can take several minutes. `live` only requires the API process.

```bash
docker logs -f thinkparse-allinone
```

## Behavior notes

- **Scale-out**: add more single-container jobs, not extra Workers in one container. One GPU still runs one MinerU task.
- **Redis**: port 6379 is not published. In-flight tasks are lost if the container is removed without a `/data/redis` volume.
- **Source**: the image contains the code; it does not bind-mount `../api` like the development Compose stack.
- **Healthcheck**: `/api/v1/health/live`; GPU start-period is about 180 seconds.

## Troubleshooting

`ModuleNotFoundError: No module named 'asynchat'`: the image still has Debian apt `supervisor` 4.2.1. Rebuild from 1.4.3+ so pip installs `supervisor>=4.2.5`.  
`ready` stays 503: check `program:worker` logs and model download.  
Redis connection errors: all-in-one must use `127.0.0.1`; the entrypoint overrides compose hostnames.  
Watchdog stops the Worker: expected; supervisord restarts `program:worker`.
