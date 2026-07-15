# 部署指南

本文档详细说明如何在生产环境部署 ThinkParse。

## 目录

- [Docker 部署](#docker-部署)
- [生产环境配置](#生产环境配置)
- [扩展和优化](#扩展和优化)
- [监控和日志](#监控和日志)
- [大规模多机部署](PRODUCTION_MULTI_NODE.zh.md) — S3 + 共享 Redis + 多 GPU 节点

## Docker 部署

### 基本部署

```bash
# 1. 复制环境配置文件
cp .env.example .env

# 2. 编辑 .env 文件，配置生产环境参数
vim .env

# 3. 启动服务
cd docker && docker compose up -d redis mineru-api

# 4. 启动 Worker
cd docker && docker compose --profile mineru-cpu up -d
# 或
cd docker && docker compose --profile mineru-gpu up -d
```

**多卡（每卡一个 Worker）**：默认 `mineru-gpu` 是单个 Worker（通常只用 `cuda:0`）。使用多卡模板：

```bash
# docker/.env
COMPOSE_FILE=docker-compose.yml:docker-compose.multi-gpu.yml
COMPOSE_PROFILES=redis,mineru-gpu-0,mineru-gpu-1
GPU_WORKER_CONCURRENCY=1
```

```bash
cd docker && docker compose up -d
```

不要同时启用 `mineru-gpu` 与 `mineru-gpu-N`。详见 [docker/README.md](../docker/README.md#multi-gpu-one-worker-per-card)。

### 构建自定义镜像

```bash
# 构建所有镜像
cd docker && docker compose build

# 构建特定服务
cd docker && docker compose build mineru-api
cd docker && docker compose build mineru-worker-cpu
cd docker && docker compose build mineru-worker-gpu
```

## 生产环境配置

### 1. Redis 配置

**安全配置**:
```bash
# .env（项目根目录）
REDIS_URL=redis://:your-strong-password@redis:6379/0
```

**数据目录隔离（生产 / 大批量解析必做）**:

大批量文档解析会占满 `mineru_temp` / `mineru_output` 所在磁盘。若 Redis 的 AOF/RDB 与之同盘，可能触发 `MISCONF`（stop-writes），任务提交返回 HTTP 500。

在 `docker/.env` 中设置 `REDIS_DATA_PATH`，指向与 temp/output **不同磁盘**上的独立宿主机目录：

```bash
# docker/.env
# 必须与 mineru_temp / mineru_output 所在 Docker 卷不在同一块磁盘
REDIS_DATA_PATH=/data/redis

# 示例：Redis 放 /data，解析临时/输出文件放另一块盘
# REDIS_DATA_PATH=/mnt/ssd-redis/mineru-redis
```

创建目录后重建 Redis 容器使挂载生效：

```bash
mkdir -p /data/redis
cd docker && docker compose --profile redis up -d redis
```

未设置时回退为命名卷 `redis_data`（通常仍与 temp/output 同在 Docker 数据盘上，**不适合大批量场景**）。

**Redis 集群**:
- 配置 Redis Sentinel 或 Cluster
- 更新 `REDIS_URL` 指向集群地址

### 2. 存储配置

**推荐使用 S3 存储**（支持分布式部署）:

```bash
MINERU_STORAGE_TYPE=s3
MINERU_S3_ENDPOINT=https://s3.example.com
MINERU_S3_ACCESS_KEY=your-access-key
MINERU_S3_SECRET_KEY=your-secret-key
MINERU_S3_BUCKET_TEMP=mineru-temp
MINERU_S3_BUCKET_OUTPUT=mineru-output
MINERU_S3_SECURE=true
```

### 3. CORS 配置

**生产环境必须限制允许的来源**:

```bash
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
ENVIRONMENT=production
```

### 4. 文件大小限制

```bash
MAX_FILE_SIZE=104857600  # 100MB，根据需求调整
```

### 5. Worker 配置

```bash
# Worker 并发数（根据服务器资源调整）
WORKER_CONCURRENCY=2

# Worker 池类型（必须使用 threads）
WORKER_POOL=threads

# 内存限制（KB）
WORKER_MAX_MEMORY_PER_CHILD=2000000  # 2GB
```

## 扩展和优化

### 水平扩展 Worker

**方法 1: Docker Compose Scale**

```bash
docker compose up -d --scale mineru-worker-cpu=4
```

**方法 2: Kubernetes**

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

### 负载均衡

**使用 Nginx**:

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

### 资源限制

在 `docker/docker-compose.yml` 中添加资源限制:

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

## 监控和日志

### 日志配置

**查看日志**:
```bash
# 查看所有服务日志
cd docker && docker compose logs -f

# 查看特定服务日志
cd docker && docker compose logs -f mineru-api
cd docker && docker compose logs -f mineru-worker-cpu
```

**日志持久化**:
```yaml
services:
  mineru-api:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 健康检查

API 提供健康检查端点:
```bash
curl http://localhost:8000/api/v1/health
```

### 监控指标

**队列统计**:
```bash
curl http://localhost:8000/api/v1/queue/stats
```

**任务列表**:
```bash
curl http://localhost:8000/api/v1/queue/tasks
```

## 备份和恢复

### Redis 数据备份

```bash
# 备份
docker exec mineru-redis redis-cli SAVE
docker cp mineru-redis:/data/dump.rdb ./backup/

# 恢复
docker cp ./backup/dump.rdb mineru-redis:/data/
docker restart mineru-redis
```

### 存储备份

**S3 存储**: 使用 S3 的版本控制和备份功能

**本地存储**: 定期备份 `OUTPUT_DIR` 目录

## 安全建议

1. **使用 HTTPS**: 配置反向代理使用 TLS
2. **Redis 密码**: 生产环境必须设置 Redis 密码
3. **CORS 限制**: 只允许信任的域名
4. **文件大小限制**: 防止恶意大文件攻击
5. **定期更新**: 保持 Docker 镜像和依赖更新

## 性能优化

1. **Worker 数量**: 根据 CPU/GPU 资源调整 Worker 数量
2. **Redis 优化**: 配置 Redis 持久化和内存限制；`REDIS_DATA_PATH` 必须与 temp/output 分盘
3. **存储优化**: 使用 SSD 或高性能 S3 服务
4. **网络优化**: API 和 Worker 部署在同一网络

## 故障恢复

### 服务重启

```bash
# 重启所有服务
cd docker && docker compose restart

# 重启特定服务
cd docker && docker compose restart mineru-api
cd docker && docker compose restart mineru-worker-cpu
```

### 数据恢复

- Redis: 从备份恢复 dump.rdb
- 存储: 从 S3 或本地备份恢复文件

## 更多信息

- [配置参考](CONFIGURATION.md)
- [故障排除](TROUBLESHOOTING.md)
- [存储配置](S3_STORAGE.md)
