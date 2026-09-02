# Deployment Guide

This document provides detailed instructions on how to deploy ThinkParse in production environments.

## Table of Contents

- [Docker Deployment](#docker-deployment)
- [Production Configuration](#production-configuration)
- [Version 1.3.0 Trial Rollout](#version-130-trial-rollout)
- [Scaling and Optimization](#scaling-and-optimization)
- [Monitoring and Logging](#monitoring-and-logging)
- [Large-scale multi-node](PRODUCTION_MULTI_NODE.md) — S3 + shared Redis + multi-GPU hosts

## Docker Deployment

### Basic Deployment

```bash
# 1. Copy environment configuration file
cp .env.example .env

# 2. Edit .env file and configure production parameters
vim .env

# 3. Start services
cd docker && docker compose up -d redis mineru-api

# 4. Start Worker
cd docker && docker compose --profile mineru-cpu up -d
# or
cd docker && docker compose --profile mineru-gpu up -d
```

**Multi-GPU (one worker per card)**: default `mineru-gpu` is a single worker (usually `cuda:0` only). Use the override template:

```bash
# docker/.env
COMPOSE_FILE=docker-compose.yml:docker-compose.multi-gpu.yml
COMPOSE_PROFILES=redis,mineru-gpu-0,mineru-gpu-1
GPU_WORKER_CONCURRENCY=1
```

```bash
cd docker && docker compose up -d
```

Do not enable `mineru-gpu` together with `mineru-gpu-N`. Details: [docker/README.md](../docker/README.md#multi-gpu-one-worker-per-card).

### Building Custom Images

```bash
# Build all images
cd docker && docker compose build

# Build specific service
cd docker && docker compose build mineru-api
cd docker && docker compose build mineru-worker-cpu
cd docker && docker compose build mineru-worker-gpu
```

## Production Configuration

### 1. Redis Configuration

**Security Configuration**:
```bash
# .env (project root)
REDIS_URL=redis://:your-strong-password@redis:6379/0
```

**Data path isolation (required for production / bulk parsing)**:

Bulk document parsing can fill the disk used by `mineru_temp` / `mineru_output`. If Redis AOF/RDB lives on the same disk, Redis may enter `MISCONF` (stop-writes) and task submit fails with HTTP 500.

Set `REDIS_DATA_PATH` in `docker/.env` to a **dedicated host directory on a different disk** from temp/output:

```bash
# docker/.env
# Use a path on a separate disk/partition from Docker volumes for mineru_temp / mineru_output
REDIS_DATA_PATH=/data/redis

# Example: Redis on /data, parsing temp/output on another mount
# REDIS_DATA_PATH=/mnt/ssd-redis/mineru-redis
```

Then recreate the Redis container so the bind mount takes effect:

```bash
mkdir -p /data/redis
cd docker && docker compose --profile redis up -d redis
```

If unset, Compose falls back to the named volume `redis_data` (often still on the same Docker data disk as temp/output — **not recommended for bulk workloads**).

**Redis Cluster**:
- Configure Redis Sentinel or Cluster
- Update `REDIS_URL` to point to cluster address

### 2. Storage Configuration

**Recommended: Use S3 Storage** (supports distributed deployment):

```bash
MINERU_STORAGE_TYPE=s3
MINERU_S3_ENDPOINT=https://s3.example.com
MINERU_S3_ACCESS_KEY=your-access-key
MINERU_S3_SECRET_KEY=your-secret-key
MINERU_S3_BUCKET_TEMP=mineru-temp
MINERU_S3_BUCKET_OUTPUT=mineru-output
MINERU_S3_SECURE=true
```

### 3. CORS Configuration

**Production environment must restrict allowed origins**:

```bash
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
ENVIRONMENT=production
HEALTH_DEPENDENCY_TIMEOUT_SECONDS=5
```

### 4. File Size Limits

```bash
MAX_FILE_SIZE=104857600  # 100MB, adjust as needed
```

### 5. Worker Configuration

```bash
# GPU worker: run one active MinerU task per card
WORKER_CONCURRENCY=1

# Worker pool type (must use threads)
WORKER_POOL=threads

# Use MinerU 3.x built-in processing windows for long documents
MINERU_ENABLE_PAGINATION=false
MINERU_PROCESSING_WINDOW_SIZE=64

# Engine recovery and observability
MINERU_ENGINE_TIMEOUT_SECONDS=7200
WORKER_WATCHDOG_TIMEOUT_SECONDS=7500
BROKER_VISIBILITY_TIMEOUT_SECONDS=9000
WORKER_HEARTBEAT_SECONDS=15
GPU_METRICS_INTERVAL_SECONDS=30

# Memory limit (KB)
WORKER_MAX_MEMORY_PER_CHILD=2000000  # 2GB
```

Do not scale a single GPU by raising `WORKER_CONCURRENCY`; concurrent parses
compete for the same device. Add GPU workers instead. Legacy ThinkParse
physical splitting can lose cross-page context and introduce chunk/merge
scheduling stalls, so it remains an explicit compatibility fallback only.

Keep `WORKER_WATCHDOG_TIMEOUT_SECONDS` greater than
`MINERU_ENGINE_TIMEOUT_SECONDS`, and keep
`BROKER_VISIBILITY_TIMEOUT_SECONDS` greater than the watchdog timeout. This
prevents Redis from redelivering a valid long-running task. `RESULT_EXPIRES`
must be greater again so cancellation survives any redelivery. Downstream
request timeouts should include enough additional margin for the engine to
report its terminal state.

## Version 1.3.0 Trial Rollout

Version 1.3.0 is suitable for a controlled server trial. Before deployment:

1. Back up the current `.env`, Redis persistence data, and output storage.
2. Compare the existing `.env` with `.env.example`; repository updates do not
   add new variables to an existing environment file.
3. Retain the previous API, Worker, and cleanup images plus the matching source
   revision for rollback. The default Compose file bind-mounts `api/`,
   `worker/`, and `shared/`, so images alone do not restore application code.
4. Restrict `/api/v1/health/deep` to operators.
5. Validate the rendered configuration:
   ```bash
   cd docker && docker compose --profile mineru-gpu config --quiet
   ```

Build and start the trial:

```bash
cd docker
sh build.sh --api --worker-gpu --cleanup --rebuild-base
docker compose --profile redis --profile mineru-gpu up -d
```

Acceptance checks:

1. `/health/live` and `/health/ready` return HTTP 200.
2. `/health/deep` reports version `1.3.0`, available Redis/storage/Worker
   components, a recent Worker heartbeat, and expected GPU/engine state.
3. A first parse completes after model initialization; a second parse confirms
   engine reuse.
4. Cancelling an active task returns `cancel_requested`, the task reaches
   `cancelled`, and the next task succeeds with a new engine generation.
5. Representative text, scanned, formula-heavy, table-heavy, and long PDFs
   complete without a stale active task or continuously growing queue.
6. Observe the trial for at least one normal workload cycle and review Worker
   restarts, engine restart counts, queue depth, task runtime, memory, and disk.

Stop the rollout and restore the retained images, matching source revision, and
`.env` backup if Worker restart loops, repeated engine crashes, incorrect
output, persistent queue growth, or downstream API incompatibility is observed.
Recreate the containers after restoring both images and source. Do not delete
Redis or output data as part of rollback.

## Scaling and Optimization

### Horizontal Worker Scaling

**Method 1: Docker Compose Scale**

```bash
cd docker && docker compose up -d --scale mineru-worker-cpu=4
```

**Method 2: Kubernetes**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mineru-worker
spec:
  replicas: 4
  template:
    spec:
      containers:
      - name: worker
        image: mineru-worker-cpu:latest
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379/0"
```

### Load Balancing

**Using Nginx**:

```nginx
upstream mineru_api {
    server mineru-api:8000;
}

server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://mineru_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Resource Limits

Add resource limits in `docker/docker-compose.yml`:

```yaml
services:
  mineru-worker-cpu:
    deploy:
      resources:
        limits:
          memory: 4g
          cpus: '2'
        reservations:
          memory: 2g
          cpus: '1'
```

## Monitoring and Logging

### Log Configuration

**View Logs**:
```bash
# View all service logs
cd docker && docker compose logs -f

# View specific service logs
cd docker && docker compose logs -f mineru-api
cd docker && docker compose logs -f mineru-worker-cpu
```

**Log Persistence**:
```yaml
services:
  mineru-api:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Health Checks

The API provides layered health endpoints:
```bash
curl http://localhost:8000/api/v1/health/live   # API process liveness
curl http://localhost:8000/api/v1/health/ready  # Redis, storage, and Worker readiness
curl http://localhost:8000/api/v1/health/deep   # Queue, active tasks, heartbeats, effective config
```

`ready` returns HTTP 503 when a dependency is unavailable; use `live` only for
container liveness. The compatible `/api/v1/health` endpoint remains available
and also returns HTTP 503 while the service is not ready. In S3 mode, readiness
performs read-only existence checks for both configured buckets; each dependency
probe is bounded by `HEALTH_DEPENDENCY_TIMEOUT_SECONDS`.

`live` and `ready` expose only aggregate diagnostics. The `deep` endpoint is
intended for operators and includes runtime details such as storage paths,
task identifiers and file names, Worker names, GPU model/UUID/driver data,
utilization, memory, temperature, engine state, and overdue tasks. Restrict
`deep` to a trusted network or protect it at the API gateway; do not expose it
directly to the public Internet.

Set `WORKER_WATCHDOG_TIMEOUT_SECONDS` above the longest supported task timeout.
When that limit is exceeded, the Worker exits so Docker or another process
supervisor can restart it. Set it to `0` only when an external watchdog provides
equivalent recovery.

### Monitoring Metrics

**Queue Statistics**:
```bash
curl http://localhost:8000/api/v1/queue/stats
```

**Task List**:
```bash
curl http://localhost:8000/api/v1/queue/tasks
```

## Backup and Recovery

### Redis Data Backup

```bash
# Backup
docker exec mineru-redis redis-cli SAVE
docker cp mineru-redis:/data/dump.rdb ./backup/

# Restore
docker cp ./backup/dump.rdb mineru-redis:/data/
docker restart mineru-redis
```

### Storage Backup

**S3 Storage**: Use S3 versioning and backup features

**Local Storage**: Regularly backup `OUTPUT_DIR` directory

## Security Recommendations

1. **Use HTTPS**: Configure reverse proxy with TLS
2. **Redis Password**: Production environment must set Redis password
3. **CORS Restrictions**: Only allow trusted domains
4. **File Size Limits**: Prevent malicious large file attacks
5. **Regular Updates**: Keep Docker images and dependencies updated

## Performance Optimization

1. **Worker Count**: Adjust worker count based on CPU/GPU resources
2. **Redis Optimization**: Configure Redis persistence and memory limits; keep `REDIS_DATA_PATH` on a disk separate from temp/output
3. **Storage Optimization**: Use SSD or high-performance S3 service
4. **Network Optimization**: Deploy API and Worker on the same network

## Failure Recovery

### Service Restart

```bash
# Restart all services
cd docker && docker compose restart

# Restart specific service
cd docker && docker compose restart mineru-api
cd docker && docker compose restart mineru-worker-cpu
```

### Data Recovery

- Redis: Restore dump.rdb from backup
- Storage: Restore files from S3 or local backup

## More Information

- [Configuration Reference](CONFIGURATION.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Storage Configuration](S3_STORAGE.md)
