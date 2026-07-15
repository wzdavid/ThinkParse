# Cleanup 容器使用指南

## 概述

`mineru-cleanup` 容器是一个独立的清理服务，用于定期清理 MinerU 的临时文件和输出文件。

## 功能特性

- **自动检测存储类型**：根据 `MINERU_STORAGE_TYPE` 环境变量自动调整清理策略
- **定时执行**：可配置清理间隔，默认每 6 小时执行一次
- **灵活配置**：支持预览模式、额外保留时间等配置

## 存储模式适配

### 本地存储模式（`MINERU_STORAGE_TYPE=local`）

清理服务会清理：
- ✅ **临时文件**：`TEMP_DIR` 中的过期文件（默认 `TEMP_MAX_AGE_HOURS=6`）
- ✅ **输出文件**：`OUTPUT_DIR` 中的过期任务目录（基于 `RESULT_EXPIRES` 配置）

### S3 存储模式（`MINERU_STORAGE_TYPE=s3`）

清理服务会清理：
- ❌ **临时文件**：由 S3 生命周期策略自动处理，无需应用层清理
- ✅ **输出文件**：`mineru-output` bucket 中的过期任务目录（基于 `RESULT_EXPIRES` 配置）

> 💡 **推荐配置**：使用 S3 存储时，建议在 S3 侧为 temp bucket 配置生命周期。若支持亚天级规则，可与 `TEMP_MAX_AGE_HOURS` 对齐；多数云厂商仅支持按天（常见 1 天）。清理容器只负责输出文件清理。

## 启动方式

### 使用 Docker Compose

```bash
# 启动清理服务
docker compose --profile mineru-cleanup up -d mineru-cleanup

# 查看日志
docker compose logs -f mineru-cleanup
```

### 环境变量配置

在 `.env` 文件中配置：

```bash
# 存储类型（影响清理策略）
MINERU_STORAGE_TYPE=s3  # 或 local

# 清理服务配置
CLEANUP_INTERVAL_HOURS=6     # 清理间隔（小时）
CLEANUP_EXTRA_HOURS=2        # 输出文件额外保留时间（小时）
TEMP_MAX_AGE_HOURS=6         # 本地 TEMP_DIR 孤儿文件最长保留（需大于 TASK_TIME_LIMIT）

# S3 存储配置（如果使用 S3 存储）
MINERU_S3_ENDPOINT=http://minio:9000
# NOTE: These are example values. In production, use strong, unique credentials.
MINERU_S3_ACCESS_KEY=minioadmin  # Replace with your actual access key
MINERU_S3_SECRET_KEY=minioadmin  # Replace with your actual secret key
MINERU_S3_BUCKET_TEMP=mineru-temp
MINERU_S3_BUCKET_OUTPUT=mineru-output
```

## 手动执行清理

### 在容器内执行

```bash
# 执行单次清理（自动检测存储类型）
docker compose exec mineru-cleanup python cleanup/cleanup_scheduler.py --run-once

# 预览模式（查看将要删除的文件）
docker compose exec mineru-cleanup python cleanup/cleanup_outputs.py --dry-run

# 只清理输出文件（推荐用于 S3 存储）
docker compose exec mineru-cleanup python cleanup/cleanup_outputs.py --output-only
```

### 本地执行

```bash
cd engines/mineru

# 执行清理
python cleanup/cleanup_outputs.py

# 预览模式
python cleanup/cleanup_outputs.py --dry-run

# 只清理输出文件
python cleanup/cleanup_outputs.py --output-only
```

## 清理策略说明

### 输出文件清理

- **清理依据**：基于 `RESULT_EXPIRES` 环境变量（默认 86400 秒/1 天）
- **清理逻辑**：删除修改时间早于 `RESULT_EXPIRES + extra_hours` 的任务目录
- **适用场景**：本地存储和 S3 存储都需要

### 临时文件清理

- **本地存储**：清理 `TEMP_DIR` 中超过 `TEMP_MAX_AGE_HOURS`（默认 6 小时）的文件。成功任务会立即删除上传 temp，此扫尾主要针对孤儿文件。
- **S3 存储**：由 S3 生命周期策略处理，清理容器不处理
- **安全边界**：默认 6 小时大于 `TASK_TIME_LIMIT`（2 小时），避免误删仍在解析中的输入文件

## 日志和监控

### 查看清理日志

```bash
# 实时查看日志
docker compose logs -f mineru-cleanup

# 查看最近 100 行日志
docker compose logs --tail=100 mineru-cleanup
```

### 日志内容示例

**本地存储模式**：
```
执行定时清理任务 - 2024-01-15 02:00:00
检测到本地存储模式，清理临时文件和输出文件
清理临时目录
清理输出目录（本地存储）
清理完成: 已删除 5 个目录，已释放 1.2 GB
```

**S3 存储模式**：
```
执行定时清理任务 - 2024-01-15 02:00:00
检测到 S3 存储模式，只清理输出文件（临时文件由 S3 生命周期策略处理）
清理输出目录（S3存储）
清理完成: 已删除 3 个任务目录，已释放 800 MB
```

## 故障排除

### 清理服务无法启动

检查：
- 环境变量配置是否正确
- 网络连接是否正常（S3 存储需要）
- 存储服务是否可用

### S3 存储清理失败

检查：
- S3 服务是否运行
- 访问密钥是否正确
- 网络连接是否正常
- Bucket 是否存在

### 清理不彻底

检查：
- `RESULT_EXPIRES` 配置是否合理
- `CLEANUP_EXTRA_HOURS` 是否设置过大
- 清理服务是否正常运行

## 最佳实践

1. **使用 S3 存储时**：
   - 配置 S3 生命周期策略处理临时文件（尽量与 `TEMP_MAX_AGE_HOURS` 对齐；按天粒度时常用 1 天）
   - 清理容器只负责输出文件的清理
   - 定期检查清理日志，确保清理正常执行

2. **使用本地存储时**：
   - 清理容器负责临时文件和输出文件的清理
   - 确保有足够的磁盘空间
   - 定期检查清理日志

3. **监控建议**：
   - 设置清理服务的健康检查
   - 监控清理日志，及时发现异常
   - 定期检查存储使用情况

## 相关文档

- [S3 存储支持方案](./S3_STORAGE.md)
- [S3 生命周期策略配置](./S3_LIFECYCLE_SETUP.md)

