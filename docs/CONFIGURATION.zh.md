# 配置参考

本文档详细说明所有可用的配置选项。

## 环境变量

### Redis 配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `REDIS_URL` | Redis 连接地址 | `redis://localhost:6379/0` | `redis://:password@redis:6379/0` |

### API 服务配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `API_HOST` | API 监听地址 | `0.0.0.0` | `0.0.0.0` |
| `API_PORT` | API 监听端口 | `8000` | `8000` |
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
| `RESULT_EXPIRES` | 结果过期时间（秒） | `86400` (1天) | `172800` |
| `TASK_TIME_LIMIT` | 任务硬超时（秒） | `7200` (2小时) | `10800` |
| `TASK_SOFT_TIME_LIMIT` | 任务软超时（秒） | `6000` (100分钟) | `9000` |
| `TASK_MAX_RETRIES` | 最大重试次数 | `0` | `3` |
| `TASK_RETRY_DELAY` | 重试延迟（秒） | `300` | `600` |

### Worker 配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `WORKER_NAME` | Worker 名称 | `mineru-worker` | `mineru-worker-1` |
| `WORKER_CONCURRENCY` | Worker 并发数 | `2` | `4` |
| `WORKER_POOL` | Worker 池类型 | `threads` | `threads` |
| `WORKER_MAX_TASKS_PER_CHILD` | 每个子进程最大任务数 | `100` | `50` |
| `WORKER_PREFETCH_MULTIPLIER` | 预取倍数 | `1` | `1` |
| `WORKER_MAX_MEMORY_PER_CHILD` | 每个子进程最大内存（KB） | `2000000` (2GB) | `4000000` |

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
| `MINERU_MODEL_SOURCE` | 模型源 | `modelscope` | `modelscope`, `huggingface`, `local` |
| `MINERU_MODEL_TYPE` | 模型类型 | `pipeline` | `pipeline`, `vlm`, `all` |

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
WORKER_CONCURRENCY=4
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
WORKER_CONCURRENCY=4
```

## 配置验证

使用以下命令验证配置：

```bash
# 检查环境变量
docker compose exec mineru-api env | grep MINERU

# 检查 API 配置
curl http://localhost:8000/api/v1/health

# 检查 Worker 状态
docker compose exec mineru-worker-cpu env | grep WORKER
```

## 更多信息

- [部署指南](DEPLOYMENT.md)
- [存储配置](S3_STORAGE.md)
- [故障排除](TROUBLESHOOTING.md)
