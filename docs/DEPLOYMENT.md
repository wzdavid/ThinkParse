# Deployment Guide

This document provides detailed instructions on how to deploy ThinkParse in production environments.

## Table of Contents

- [Docker Deployment](#docker-deployment)
- [Production Configuration](#production-configuration)
- [Scaling and Optimization](#scaling-and-optimization)
- [Monitoring and Logging](#monitoring-and-logging)

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
# .env
REDIS_URL=redis://:your-strong-password@redis:6379/0
```

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
```

### 4. File Size Limits

```bash
MAX_FILE_SIZE=104857600  # 100MB, adjust as needed
```

### 5. Worker Configuration

```bash
# Worker concurrency (adjust based on server resources)
WORKER_CONCURRENCY=2

# Worker pool type (must use threads)
WORKER_POOL=threads

# Memory limit (KB)
WORKER_MAX_MEMORY_PER_CHILD=2000000  # 2GB
```

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

API provides health check endpoint:
```bash
curl http://localhost:8000/api/v1/health
```

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
2. **Redis Optimization**: Configure Redis persistence and memory limits
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
