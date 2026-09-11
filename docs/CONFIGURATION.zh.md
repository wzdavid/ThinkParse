# 配置参考

本文档详细说明所有可用的配置选项。

## 环境变量

### Redis 配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `REDIS_URL` | Redis 连接地址 | `redis://localhost:6379/0` | `redis://:password@redis:6379/0` |

单容器镜像（`mineru-allinone`）会在启动时把 `REDIS_URL` 设为 `redis://127.0.0.1:6379/0`，使用容器内 Redis。详见 [单容器部署](DEPLOYMENT_ALLINONE.zh.md)。

### API 服务配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `API_HOST` | API 监听地址 | `0.0.0.0` | `0.0.0.0` |
| `API_PORT` | API 监听端口 | `8000` | `8000` |
| `HEALTH_DEPENDENCY_TIMEOUT_SECONDS` | 每个 readiness 依赖探针的超时时间 | `5` | `5` |
| `CORS_ALLOWED_ORIGINS` | 允许的 CORS 来源（逗号分隔） | 开发环境默认值 | `https://app.example.com` |
| `ENVIRONMENT` | 运行环境 | `development` | `production` |
| `MAX_FILE_SIZE` | 最大文件大小（字节） | `104857600` (100MB) | `209715200` |

### 存储配置

#### 本地存储

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `MINERU_STORAGE_TYPE` | 存储类型 | `local` | `local` |
| `TEMP_DIR` | 临时文件目录 | `/tmp/mineru_temp` | `/tmp/mineru_temp` |
| `OUTPUT_DIR` | 输出文件目录 | `/tmp/mineru_output` | `/tmp/mineru_output` |

#### S3 存储

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `MINERU_STORAGE_TYPE` | 存储类型 | `local` | `s3` |
| `MINERU_S3_ENDPOINT` | S3 服务地址 | - | `http://minio:9000` |
| `MINERU_S3_ACCESS_KEY` | S3 访问密钥 | - | `minioadmin` |
| `MINERU_S3_SECRET_KEY` | S3 密钥 | - | `minioadmin` |
| `MINERU_S3_BUCKET_TEMP` | 临时文件 bucket | `mineru-temp` | `mineru-temp` |
| `MINERU_S3_BUCKET_OUTPUT` | 输出文件 bucket | `mineru-output` | `mineru-output` |
| `MINERU_S3_SECURE` | 是否使用 HTTPS | `false` | `true` |
| `MINERU_S3_REGION` | S3 区域 | - | `us-east-1` |

### Celery 配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `MINERU_QUEUE` | 任务队列名称 | `mineru-tasks` | `mineru-tasks` |
| `MINERU_EXCHANGE` | 交换器名称 | `mineru` | `mineru` |
| `MINERU_ROUTING_KEY` | 路由键 | `mineru.tasks` | `mineru.tasks` |
| `BROKER_VISIBILITY_TIMEOUT_SECONDS` | Redis 投递可见性超时；必须高于 Worker watchdog 超时 | `9000` | `9000` |
| `RESULT_EXPIRES` | 结果/取消标记保留时间；必须高于 broker visibility timeout | `86400` (1天) | `172800` |
| `TASK_TIME_LIMIT` | 任务硬超时（秒） | `7200` (2小时) | `10800` |
| `TASK_SOFT_TIME_LIMIT` | 任务软超时（秒） | `6000` (100分钟) | `9000` |
| `MINERU_ENGINE_TIMEOUT_SECONDS` | 隔离 MinerU 进程的强制终止超时 | `7200` (2小时) | `7200` |
| `TASK_MAX_RETRIES` | 最大重试次数 | `0` | `3` |
| `TASK_RETRY_DELAY` | 重试延迟（秒） | `300` | `600` |

### Worker 配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `WORKER_NAME` | Worker 名称 | `mineru-worker` | `mineru-worker-1` |
| `WORKER_CONCURRENCY` | Worker 并发数；GPU 建议一卡一个任务 | `1` | `1` |
| `WORKER_POOL` | Worker 池类型 | `threads` | `threads` |
| `WORKER_MAX_TASKS_PER_CHILD` | 每个子进程最大任务数 | `100` | `50` |
| `WORKER_PREFETCH_MULTIPLIER` | 预取倍数 | `1` | `1` |
| `WORKER_MAX_MEMORY_PER_CHILD` | 每个子进程最大内存（KB） | `2000000` (2GB) | `4000000` |
| `WORKER_HEARTBEAT_SECONDS` | Worker 运行状态写入 Redis 的间隔（秒） | `15` | `15` |
| `GPU_METRICS_INTERVAL_SECONDS` | Worker 心跳中的 GPU 身份和利用率采样间隔 | `30` | `30` |
| `WORKER_WATCHDOG_TIMEOUT_SECONDS` | 任务超期后退出 Worker，由进程管理器重启；设为 `0` 可禁用 | `7500` | `7500` |

### MinerU 配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `MINERU_DEVICE_MODE` | 设备模式 | `auto` | `cpu`, `cuda`, `mps` |
| `MINERU_FORMULA_ENABLE` | 启用公式识别 | `true` | `true` |
| `MINERU_TABLE_ENABLE` | 启用表格识别 | `true` | `true` |
| `MINERU_PARSE_METHOD` | 解析方法 | `auto` | `auto`, `txt`, `ocr` |
| `MINERU_LANG` | 语言 | `ch` | `ch`, `en` |
| `MINERU_EMBED_IMAGES_IN_MD` | 在 Markdown 中嵌入图片 | `true` | `true` |
| `MINERU_RETURN_IMAGES_BASE64` | 返回 Base64 图片 | `true` | `true` |
| `MINERU_PROCESSING_WINDOW_SIZE` | MinerU 内置长文档处理窗口页数 | `64` | `64`, `96` |
| `MINERU_ENABLE_PAGINATION` | 启用旧版 ThinkParse 物理拆分 PDF（兼容逃生开关） | `false` | `false` |
| `MINERU_PAGINATION_THRESHOLD` | 启用旧版拆分时的页数阈值 | `100` | `100` |
| `MINERU_PAGE_CHUNK_SIZE` | 启用旧版拆分时的每块页数 | `50` | `50` |
| `MINERU_MODEL_SOURCE` | 模型源 | `modelscope` | `modelscope`, `huggingface`, `local` |
| `MINERU_MODEL_TYPE` | 模型类型 | `pipeline` | `pipeline`, `vlm`, `all` |

生产环境建议保留 `MINERU_ENABLE_PAGINATION=false`。MinerU 3.x 会使用
processing window 处理完整 PDF，可避免物理切分造成的跨页段落/表格损失以及
chunk/merge 调度阻塞。旧版拆分仅用于明确的兼容回退。

### MinIO 配置（可选）

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `MINIO_ENDPOINT` | MinIO 服务地址 | - | `http://minio:9000` |
| `MINIO_ACCESS_KEY` | MinIO 访问密钥 | - | `minioadmin` |
| `MINIO_SECRET_KEY` | MinIO 密钥 | - | `minioadmin` |
| `MINIO_BUCKET` | MinIO bucket 名称 | - | `documents` |
| `MINIO_SECURE` | 是否使用 HTTPS | `false` | `true` |

### 清理服务配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `CLEANUP_INTERVAL_HOURS` | 清理间隔（小时） | `6` | `12` |
| `CLEANUP_EXTRA_HOURS` | 输出文件额外保留时间（小时） | `2` | `4` |
| `TEMP_MAX_AGE_HOURS` | 本地 `TEMP_DIR` 孤儿文件最长保留（小时）；需大于 `TASK_TIME_LIMIT` | `6` | `4` |

## 配置示例

### 开发环境

```bash
# .env
REDIS_URL=redis://localhost:6379/0
MINERU_STORAGE_TYPE=local
ENVIRONMENT=development
CORS_ALLOWED_ORIGINS=
```

### 生产环境（本地存储）

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

### 生产环境（S3 存储）

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

## 配置验证

使用以下命令验证配置：

```bash
# 检查环境变量
docker compose exec mineru-api env | grep MINERU

# 检查 API 就绪状态和详细运行配置
curl http://localhost:8000/api/v1/health/ready
curl http://localhost:8000/api/v1/health/deep

# 检查 Worker 状态
docker compose exec mineru-worker-cpu env | grep WORKER
```

## 更多信息

- [部署指南](DEPLOYMENT.md)
- [存储配置](S3_STORAGE.md)
- [故障排除](TROUBLESHOOTING.md)
