# Configuration Reference

This document details all available configuration options.

## Environment Variables

### Redis Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` | `redis://:password@redis:6379/0` |

### API Service Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `API_HOST` | API listen address | `0.0.0.0` | `0.0.0.0` |
| `API_PORT` | API listen port | `8000` | `8000` |
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
| `RESULT_EXPIRES` | Result expiration time (seconds) | `86400` (1 day) | `172800` |
| `TASK_TIME_LIMIT` | Task hard timeout (seconds) | `7200` (2 hours) | `10800` |
| `TASK_SOFT_TIME_LIMIT` | Task soft timeout (seconds) | `6000` (100 minutes) | `9000` |
| `TASK_MAX_RETRIES` | Maximum retry count | `0` | `3` |
| `TASK_RETRY_DELAY` | Retry delay (seconds) | `300` | `600` |

### Worker Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `WORKER_NAME` | Worker name | `mineru-worker` | `mineru-worker-1` |
| `WORKER_CONCURRENCY` | Worker concurrency | `2` | `4` |
| `WORKER_POOL` | Worker pool type | `threads` | `threads` |
| `WORKER_MAX_TASKS_PER_CHILD` | Max tasks per child process | `100` | `50` |
| `WORKER_PREFETCH_MULTIPLIER` | Prefetch multiplier | `1` | `1` |
| `WORKER_MAX_MEMORY_PER_CHILD` | Max memory per child (KB) | `2000000` (2GB) | `4000000` |

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
| `MINERU_MODEL_SOURCE` | Model source | `modelscope` | `modelscope`, `huggingface`, `local` |
| `MINERU_MODEL_TYPE` | Model type | `pipeline` | `pipeline`, `vlm`, `all` |

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
| `CLEANUP_INTERVAL_HOURS` | Cleanup interval (hours) | `6` | `12` |
| `CLEANUP_EXTRA_HOURS` | Extra retention time for outputs (hours) | `2` | `4` |
| `TEMP_MAX_AGE_HOURS` | Local `TEMP_DIR` orphan max age (hours); keep above `TASK_TIME_LIMIT` | `6` | `4` |

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
WORKER_CONCURRENCY=4
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
WORKER_CONCURRENCY=4
```

## Configuration Validation

Use the following commands to validate configuration:

```bash
# Check environment variables
cd docker && docker compose exec mineru-api env | grep MINERU

# Check API configuration
curl http://localhost:8000/api/v1/health

# Check Worker status
cd docker && docker compose exec mineru-worker-cpu env | grep WORKER
```

## More Information

- [Deployment Guide](DEPLOYMENT.md)
- [Storage Configuration](S3_STORAGE.md)
- [Troubleshooting](TROUBLESHOOTING.md)
