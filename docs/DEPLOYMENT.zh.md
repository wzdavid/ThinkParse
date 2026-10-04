# 部署指南

本文档详细说明如何在生产环境部署 ThinkParse。

## 目录

- [Docker 部署](#docker-部署)
- [生产环境配置](#生产环境配置)
- [1.4.3 版本试运行](#143-版本试运行)
- [扩展和优化](#扩展和优化)
- [监控和日志](#监控和日志)
- [大规模多机部署](PRODUCTION_MULTI_NODE.zh.md) — S3 + 共享 Redis + 多 GPU 节点
- [单容器部署（天河 / HPC）](DEPLOYMENT_ALLINONE.zh.md) — 四角色一个容器

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

**多卡**：默认 `mineru-gpu` 是单个 Worker（通常只用 `cuda:0`）。按卡数和每卡进程数生成容器：

```bash
# docker/.env
MINERU_GPU_COUNT=2
MINERU_WORKERS_PER_GPU=4
GPU_WORKER_CONCURRENCY=1
```

```bash
cd docker && sh gpu-up.sh
```

`GPU_WORKER_CONCURRENCY` 保持 1。不要同时启用 `mineru-gpu`。详见 [docker/README.md](../docker/README.md#multi-gpu-workers)。

**天河 / 只允许一个容器**：不要拆成 Redis、API、Worker、Cleanup 四个容器。构建 `mineru-allinone` 镜像，由调度器只提交这一只容器。见 [单容器部署](DEPLOYMENT_ALLINONE.zh.md)。

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
HEALTH_DEPENDENCY_TIMEOUT_SECONDS=5
```

### 4. 文件大小限制

```bash
MAX_FILE_SIZE=104857600  # 100MB，根据需求调整
```

### 5. Worker 配置

```bash
# GPU Worker：一卡只运行一个 MinerU 任务
WORKER_CONCURRENCY=1

# Worker 池类型（必须使用 threads）
WORKER_POOL=threads

# 使用 MinerU 3.x 内置 processing window 处理长文档
MINERU_ENABLE_PAGINATION=false
MINERU_PROCESSING_WINDOW_SIZE=64

# 引擎恢复与可观测性
MINERU_ENGINE_TIMEOUT_SECONDS=7200
WORKER_WATCHDOG_TIMEOUT_SECONDS=7500
BROKER_VISIBILITY_TIMEOUT_SECONDS=9000
WORKER_HEARTBEAT_SECONDS=15
GPU_METRICS_INTERVAL_SECONDS=30

# 内存限制（KB）
WORKER_MAX_MEMORY_PER_CHILD=2000000  # 2GB
```

不要通过提高 `WORKER_CONCURRENCY` 或 `GPU_WORKER_CONCURRENCY` 扩容。
一个进程里的 MinerU 引擎有锁，提高并发不会在 GPU 上并行解析。
用 `MINERU_WORKERS_PER_GPU`（`sh gpu-up.sh`）增加容器。
旧版 ThinkParse 物理分页会切断跨页上下文，并增加 chunk/merge 调度阻塞风险，
因此仅作为兼容回退。

保持 `WORKER_WATCHDOG_TIMEOUT_SECONDS` 大于
`MINERU_ENGINE_TIMEOUT_SECONDS`，并保持
`BROKER_VISIBILITY_TIMEOUT_SECONDS` 大于 watchdog 超时，避免 Redis
重复投递仍在正常执行的长任务。`RESULT_EXPIRES` 还必须更大，以保证
取消标记覆盖重投周期。下游请求超时还应预留额外时间，以便引擎上报
最终状态。

## 1.4.3 版本试运行

1.4.3 已适合在服务器上进行受控试运行。部署前：

1. 备份当前 `.env`、Redis 持久化数据和输出存储。
2. 对比现有 `.env` 与 `.env.example`；更新代码不会自动向已有环境文件
   添加新变量。
3. 保留上一版本的 API、Worker、cleanup 镜像及匹配的源码版本。默认
   Compose 会挂载 `api/`、`worker/` 和 `shared/`，仅恢复镜像不能回滚
   应用代码。
4. 将 `/api/v1/health/deep` 限制为仅运维人员可访问。
5. 验证最终 Compose 配置：
   ```bash
   # 单卡：
   cd docker && docker compose --profile mineru-gpu config --quiet
   # 多卡：
   cd docker && sh gpu-up.sh --render-only && \
     docker compose -f docker-compose.yml -f docker-compose.gpus.yml \
       --profile redis --profile mineru-multi-gpu config --quiet
   ```

构建并启动试运行版本：

```bash
cd docker
sh build.sh --api --worker-gpu --cleanup --rebuild-base
# 单卡：
docker compose --profile redis --profile mineru-gpu up -d
# 多卡（在 docker/.env 设置 MINERU_GPU_COUNT / MINERU_WORKERS_PER_GPU）：
sh gpu-up.sh
```

天河等只允许一个容器的环境改为构建 all-in-one 镜像，见 [单容器部署](DEPLOYMENT_ALLINONE.zh.md)：

```bash
cd docker
sh build.sh --allinone
```

验收检查：

1. `/health/live` 和 `/health/ready` 返回 HTTP 200。
2. `/health/deep` 显示版本 `1.4.3`，Redis、存储和 Worker 均可用，
   Worker 心跳时间正常，并显示预期的 GPU 与引擎状态。
3. 首次解析在模型初始化后成功完成；再次解析可确认引擎复用。
4. 取消活动任务后接口返回 `cancel_requested`，任务最终变为
   `cancelled`，且下一任务能够在新的引擎代次上成功完成。
5. 代表性的文本型、扫描型、公式密集、表格密集及长 PDF 均能完成，
   不出现长期残留的活动任务或持续增长的队列。
6. 至少观察一个正常业务负载周期，并检查 Worker 重启、引擎重启次数、
   队列深度、任务耗时、内存和磁盘状态。

如果出现 Worker 重启循环、引擎反复崩溃、结果错误、队列持续增长或
下游 API 不兼容，应停止扩大试运行范围，并恢复保留的镜像、匹配的
源码版本和 `.env` 备份，随后重新创建容器。回滚时不要删除 Redis 或
输出数据。

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

API 提供分层健康检查端点:
```bash
curl http://localhost:8000/api/v1/health/live   # API 进程存活
curl http://localhost:8000/api/v1/health/ready  # Redis、存储与 Worker 就绪
curl http://localhost:8000/api/v1/health/deep   # 队列、活动任务、心跳与有效配置
```

`ready` 在依赖不可用时返回 HTTP 503；`live` 仅用于容器存活检查。
兼容端点 `/api/v1/health` 保留，并在服务未就绪时返回 HTTP 503。S3
模式会以只读方式检查两个已配置 bucket 是否存在；每个依赖探针受
`HEALTH_DEPENDENCY_TIMEOUT_SECONDS` 限制。

`live` 和 `ready` 仅返回聚合诊断数据。面向运维人员的 `deep` 会返回
存储路径、任务标识和文件名、Worker 名称、GPU 型号/UUID/驱动信息、
利用率、显存、温度、引擎状态及超期任务。应通过可信网络或 API 网关
限制 `deep` 的访问，不要直接暴露到公网。

`WORKER_WATCHDOG_TIMEOUT_SECONDS` 应高于系统允许的最长任务超时。超过该
时限后 Worker 会主动退出，由 Docker 或其他进程管理器重启。仅当外部
watchdog 提供等效恢复能力时才建议设为 `0`。

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
