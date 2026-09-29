# Configuration Reference

This document details all available configuration options.

## Environment Variables

### Redis Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` | `redis://:password@redis:6379/0` |

The all-in-one image (`mineru-allinone`) forces `REDIS_URL=redis://127.0.0.1:6379/0` at startup so it uses the in-container Redis. See [Single-container deployment](DEPLOYMENT_ALLINONE.md).

### API Service Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `API_HOST` | API listen address | `0.0.0.0` | `0.0.0.0` |
| `API_PORT` | API listen port | `8000` | `8000` |
| `HEALTH_DEPENDENCY_TIMEOUT_SECONDS` | Timeout for each readiness dependency probe | `5` | `5` |
| `CORS_ALLOWED_ORIGINS` | Allowed CORS origins (comma-separated) | Development default | `https://app.example.com` |
| `ENVIRONMENT` | Runtime environment | `development` | `production` |
| `MAX_FILE_SIZE` | Maximum file size (bytes) | `104857600` (100MB) | `209715200` |

### Storage Configuration

#### Local Storage

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `MINERU_STORAGE_TYPE` | Storage type | `local` | `local` |
| `TEMP_DIR` | Temporary files directory | `/tmp/mineru_temp` | `/tmp/mineru_temp` |
| `OUTPUT_DIR` | Output files directory | `/tmp/mineru_output` | `/tmp/mineru_output` |

#### S3 Storage

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `MINERU_STORAGE_TYPE` | Storage type | `local` | `s3` |
| `MINERU_S3_ENDPOINT` | S3 service endpoint | - | `http://minio:9000` |
| `MINERU_S3_ACCESS_KEY` | S3 access key | - | `minioadmin` |
| `MINERU_S3_SECRET_KEY` | S3 secret key | - | `minioadmin` |
| `MINERU_S3_BUCKET_TEMP` | Temporary files bucket | `mineru-temp` | `mineru-temp` |
| `MINERU_S3_BUCKET_OUTPUT` | Output files bucket | `mineru-output` | `mineru-output` |
| `MINERU_S3_SECURE` | Use HTTPS | `false` | `true` |
| `MINERU_S3_REGION` | S3 region | - | `us-east-1` |

### Celery Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `MINERU_QUEUE` | Task queue name | `mineru-tasks` | `mineru-tasks` |
| `MINERU_EXCHANGE` | Exchange name | `mineru` | `mineru` |
| `MINERU_ROUTING_KEY` | Routing key | `mineru.tasks` | `mineru.tasks` |
| `BROKER_VISIBILITY_TIMEOUT_SECONDS` | Redis delivery visibility; keep above the Worker watchdog timeout | `9000` | `9000` |
| `RESULT_EXPIRES` | Result/cancellation retention; keep above broker visibility timeout | `86400` (1 day) | `172800` |
| `TASK_TIME_LIMIT` | Task hard timeout (seconds) | `7200` (2 hours) | `10800` |
| `TASK_SOFT_TIME_LIMIT` | Task soft timeout (seconds) | `6000` (100 minutes) | `9000` |
| `MINERU_ENGINE_TIMEOUT_SECONDS` | Force-termination timeout for the isolated MinerU process | `7200` (2 hours) | `7200` |
| `TASK_MAX_RETRIES` | Maximum retry count | `0` | `3` |
| `TASK_RETRY_DELAY` | Retry delay (seconds) | `300` | `600` |

### Worker Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `WORKER_NAME` | Worker name | `mineru-worker` | `mineru-worker-1` |
| `WORKER_CONCURRENCY` | Concurrency inside one worker process; keep 1 on GPU and add containers to parallelize | `1` | `1` |
| `WORKER_POOL` | Worker pool type | `threads` | `threads` |
| `WORKER_MAX_TASKS_PER_CHILD` | Max tasks per child process | `100` | `50` |
| `WORKER_PREFETCH_MULTIPLIER` | Prefetch multiplier | `1` | `1` |
| `WORKER_MAX_MEMORY_PER_CHILD` | Max memory per child (KB) | `2000000` (2GB) | `4000000` |
| `WORKER_HEARTBEAT_SECONDS` | Interval for publishing Worker runtime state to Redis | `15` | `15` |
| `GPU_METRICS_INTERVAL_SECONDS` | Interval for GPU identity and utilization sampling in Worker heartbeats | `30` | `30` |
| `WORKER_WATCHDOG_TIMEOUT_SECONDS` | Exit an overdue Worker task so the process supervisor can restart it; `0` disables | `7500` | `7500` |

### MinerU Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `MINERU_DEVICE_MODE` | Device mode | `auto` | `cpu`, `cuda`, `mps` |
| `MINERU_FORMULA_ENABLE` | Enable formula recognition | `true` | `true` |
| `MINERU_TABLE_ENABLE` | Enable table recognition | `true` | `true` |
| `MINERU_PARSE_METHOD` | Parse method | `auto` | `auto`, `txt`, `ocr` |
| `MINERU_LANG` | Language | `ch` | `ch`, `en` |
| `MINERU_EMBED_IMAGES_IN_MD` | Embed images in Markdown | `true` | `true` |
| `MINERU_RETURN_IMAGES_BASE64` | Return Base64 images | `true` | `true` |
| `MINERU_PROCESSING_WINDOW_SIZE` | MinerU built-in long-document window size in pages | `64` | `64`, `96` |
| `MINERU_ENABLE_PAGINATION` | Enable legacy ThinkParse physical PDF splitting (compatibility escape hatch) | `false` | `false` |
| `MINERU_PAGINATION_THRESHOLD` | Page threshold for legacy splitting | `100` | `100` |
| `MINERU_PAGE_CHUNK_SIZE` | Pages per legacy split chunk | `50` | `50` |
| `MINERU_MODEL_SOURCE` | Model source | `modelscope` | `modelscope`, `huggingface`, `local` |
| `MINERU_MODEL_TYPE` | Model type | `pipeline` | `pipeline`, `vlm`, `all` |

Keep `MINERU_ENABLE_PAGINATION=false` in production. MinerU 3.x processes the
complete PDF with bounded processing windows, preserving cross-page context
and avoiding chunk/merge scheduling stalls. Use legacy splitting only as an
explicit compatibility fallback.

### MinIO Configuration (Optional)

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `MINIO_ENDPOINT` | MinIO service endpoint | - | `http://minio:9000` |
| `MINIO_ACCESS_KEY` | MinIO access key | - | `minioadmin` |
| `MINIO_SECRET_KEY` | MinIO secret key | - | `minioadmin` |
| `MINIO_BUCKET` | MinIO bucket name | - | `documents` |
| `MINIO_SECURE` | Use HTTPS | `false` | `true` |

### Cleanup Service Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `CLEANUP_INTERVAL_HOURS` | Cleanup interval (hours). The scheduler also runs once as soon as it starts | `6` | `12` |
| `CLEANUP_EXTRA_HOURS` | Extra retention time for outputs (hours), added to `RESULT_EXPIRES` | `2` | `4` |
| `TEMP_MAX_AGE_HOURS` | Local `TEMP_DIR` orphan max age (hours); keep above `TASK_TIME_LIMIT` | `6` | `4` |
| `DISK_FREE_MIN_BYTES` | Refuse new tasks when free space on the data filesystem is below this many bytes | `8589934592` (8 GiB) | `4294967296` |
| `DISK_FREE_MIN_PERCENT` | Cap the refuse reserve at this percent of the filesystem. `0` disables the cap | `10` | `5` |
| `DISK_FREE_TARGET_BYTES` | Delete the oldest eligible results until at least this many bytes are free | `17179869184` (16 GiB) | `8589934592` |
| `DISK_FREE_TARGET_PERCENT` | Cap the reclaim target at this percent of the filesystem. `0` disables the cap | `20` | `15` |
| `DISK_PRESSURE_MIN_AGE_HOURS` | Under disk pressure, do not delete data newer than this. Keep above `TASK_TIME_LIMIT` | `3` | `4` |
| `DISK_CHECK_INTERVAL_MINUTES` | How often to apply the disk watermarks | `1` | `5` |

Output directories are removed when their modification time is older than `RESULT_EXPIRES` + `CLEANUP_EXTRA_HOURS`. With the defaults that is 24 hours + 2 hours. To keep outputs for about 12 hours, set `RESULT_EXPIRES=43200` and `CLEANUP_EXTRA_HOURS=0`. For about 8 hours, set `RESULT_EXPIRES=28800` and `CLEANUP_EXTRA_HOURS=0`. `RESULT_EXPIRES` must stay greater than `BROKER_VISIBILITY_TIMEOUT_SECONDS`.

Disk watermarks use free bytes, not a fixed used-percent of one machine. The refuse line is `min(DISK_FREE_MIN_BYTES, filesystem size × DISK_FREE_MIN_PERCENT / 100)`. The reclaim line is the same formula with the target settings, and is never lower than the refuse line. On a large disk the 8 GiB / 16 GiB reserves apply. On a 20 GiB disk the 10% / 20% caps apply instead, so the process does not demand 16 GiB free. While free space is under the reclaim line, the oldest entries older than `max(DISK_PRESSURE_MIN_AGE_HOURS, TASK_TIME_LIMIT)` are deleted, new submissions receive HTTP 507, and queued tasks wait. That leaves the reclaim reserve for parses already running and for Redis. `/health/ready` reports storage unavailable in that state. Liveness does not, so the API process is not restarted for a full disk. The disk check runs as soon as the cleanup process starts, and again on `DISK_CHECK_INTERVAL_MINUTES`, including when `CLEANUP_INTERVAL_HOURS` is long.

## Configuration Examples

### Development Environment

```bash
# .env
REDIS_URL=redis://localhost:6379/0
MINERU_STORAGE_TYPE=local
ENVIRONMENT=development
CORS_ALLOWED_ORIGINS=
```

### Production Environment (Local Storage)

```bash
# .env
REDIS_URL=redis://:strong-password@redis:6379/0
MINERU_STORAGE_TYPE=local
TEMP_DIR=/data/mineru/temp
OUTPUT_DIR=/data/mineru/output
ENVIRONMENT=production
CORS_ALLOWED_ORIGINS=https://app.example.com
MAX_FILE_SIZE=104857600
WORKER_CONCURRENCY=1
MINERU_ENABLE_PAGINATION=false
MINERU_PROCESSING_WINDOW_SIZE=64
MINERU_ENGINE_TIMEOUT_SECONDS=7200
WORKER_WATCHDOG_TIMEOUT_SECONDS=7500
BROKER_VISIBILITY_TIMEOUT_SECONDS=9000
```

### Production Environment (S3 Storage)

```bash
# .env
REDIS_URL=redis://:strong-password@redis:6379/0
MINERU_STORAGE_TYPE=s3
MINERU_S3_ENDPOINT=https://s3.example.com
MINERU_S3_ACCESS_KEY=your-access-key
MINERU_S3_SECRET_KEY=your-secret-key
MINERU_S3_BUCKET_TEMP=mineru-temp
MINERU_S3_BUCKET_OUTPUT=mineru-output
MINERU_S3_SECURE=true
ENVIRONMENT=production
CORS_ALLOWED_ORIGINS=https://app.example.com
MAX_FILE_SIZE=104857600
WORKER_CONCURRENCY=1
MINERU_ENABLE_PAGINATION=false
MINERU_PROCESSING_WINDOW_SIZE=64
MINERU_ENGINE_TIMEOUT_SECONDS=7200
WORKER_WATCHDOG_TIMEOUT_SECONDS=7500
BROKER_VISIBILITY_TIMEOUT_SECONDS=9000
```

## Configuration Validation

Use the following commands to validate configuration:

```bash
# Check environment variables
cd docker && docker compose exec mineru-api env | grep MINERU

# Check API readiness and detailed runtime configuration
curl http://localhost:8000/api/v1/health/ready
curl http://localhost:8000/api/v1/health/deep

# Check Worker status
cd docker && docker compose exec mineru-worker-cpu env | grep WORKER
```

## More Information

- [Deployment Guide](DEPLOYMENT.md)
- [Storage Configuration](S3_STORAGE.md)
- [Troubleshooting](TROUBLESHOOTING.md)
