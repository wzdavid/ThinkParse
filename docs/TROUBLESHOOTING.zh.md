# 故障排除

本文档列出常见问题和解决方案。

## 目录

- [GPU 容器启动失败（NVIDIA 驱动/库版本不匹配）](#gpu-容器启动失败nvidia-驱动库版本不匹配)
- [RTX 5090 / Blackwell：Flash Attention CUDA 报错](#rtx-5090--blackwellflash-attention-cuda-报错invalid-argument)
- [Docker 网络问题](#docker-网络问题)
- [连接问题](#连接问题)
- [任务执行问题](#任务执行问题)
- [性能问题](#性能问题)
- [存储问题](#存储问题)

## Docker 构建问题

### 构建 Worker 时找不到基础镜像

**症状**: 构建 `mineru-worker-gpu` 时出错："failed to solve: failed to fetch ... mineru-vllm:latest"

**原因**: `mineru-worker-gpu` 服务依赖于基础镜像 `mineru-vllm:latest`，必须先构建该基础镜像。

**解决方案**:

1. **使用构建脚本（推荐）**:
   ```bash
   cd docker && sh build.sh --worker-gpu
   ```
   脚本会自动检查并在需要时构建基础镜像。

2. **手动先构建基础镜像**:
   ```bash
   cd docker
   docker build -f Dockerfile.base \
       --build-arg PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple} \
       -t mineru-vllm:latest ..
   
   # 然后构建 worker
   docker compose build mineru-worker-gpu
   ```

3. **使用脚本构建所有镜像**:
   ```bash
   cd docker && sh build.sh
   ```

### 基础镜像构建失败

**症状**: 构建 `mineru-vllm:latest` 基础镜像时出错

**可能原因**:
1. 下载模型时网络问题
2. 磁盘空间不足
3. Docker 构建上下文问题

**解决方案**:
1. 检查网络连接和 pip 镜像源配置
2. 检查可用磁盘空间：`df -h`
3. 确保从正确的目录运行构建命令：
   ```bash
   # 从 docker/ 目录
   docker build -f Dockerfile.base -t mineru-vllm:latest ..
   ```
4. 检查构建日志以获取具体错误信息
5. 如果有缓存问题，尝试使用 `--no-cache` 构建：
   ```bash
   docker build --no-cache -f docker/Dockerfile.base -t mineru-vllm:latest .
   ```

## GPU 容器启动失败（NVIDIA 驱动/库版本不匹配）

**症状**: 启动 `mineru-worker-gpu` 时报错：
```text
OCI runtime create failed: ... nvidia-container-cli: initialization error: nvml error: driver/library version mismatch
```

**原因**: 宿主机上的 **NVIDIA 内核驱动** 与当前加载的驱动（或用户态库）版本不一致。常见于：
- 刚更新过 NVIDIA 驱动或内核，但**尚未重启**，内存里仍是旧驱动；
- 多版本驱动/库混装，nvidia-container-toolkit 使用的库与当前加载的内核驱动不匹配。

**解决步骤**:

1. **优先尝试：重启服务器**  
   若最近有过驱动或内核更新，直接重启通常即可恢复一致：
   ```bash
   sudo reboot
   ```
   重启后再执行：
   ```bash
   nvidia-smi
   ```
   若 `nvidia-smi` 正常，再启动 GPU 容器。

2. **确认驱动与库一致（不重启时排查）**  
   ```bash
   # 当前加载的内核驱动版本（需与用户态一致）
   cat /proc/driver/nvidia/version

   # 用户态驱动/库版本（如已安装 nvidia-driver）
   nvidia-smi
   ```
   若 `nvidia-smi` 已报 `driver/library version mismatch`，说明内核驱动与用户态不匹配，**必须重启**或重新安装/切换匹配版本的驱动。

3. **可选：临时改用 CPU Worker**  
   在修好 GPU 环境前，可先用 CPU 版 Worker 保证服务可用：
   ```bash
   # 使用 mineru-cpu profile，不启动 mineru-worker-gpu
   docker compose --profile redis --profile mineru-cpu up -d
   ```

### RTX 5090 / Blackwell：Flash Attention CUDA 报错（invalid argument）

**症状**：在 NVIDIA RTX 5090（Blackwell，计算能力 12.0）上，VLM 引擎启动失败，报错类似：
```text
CUDA error (.../xformers/.../hopper/flash_fwd_launch_template.h:188): invalid argument
Engine core initialization failed. See root cause above.
```

**原因**：**v0.10.1.1** 的 vLLM 基础镜像仅支持 Ampere、Ada Lovelace、Hopper（CC 8.0–9.0），其 flash-attention 内核未为 **Blackwell**（SM 12.0）编译，因此在 5090 上会报 “invalid argument”。MinerU 2.6.2 起（至 2.7.4）通过使用 **vLLM 0.11.0** 基础镜像支持 Blackwell。

**推荐解决方式（Docker）**：

1. **使用 v0.11.0 基础镜像**  
   本仓库 `docker/Dockerfile.base` 已默认使用 `vllm/vllm-openai:v0.11.0`。若你仍在使用旧构建（v0.10.1.1），请重新构建基础镜像与 GPU worker：
   ```bash
   cd docker && sh build.sh --worker-gpu
   ```
   或手动确保 `Dockerfile.base` 的 `FROM` 为 `vllm/vllm-openai:v0.11.0`（或 DaoCloud 镜像等价版本），然后重新构建基础镜像与 `mineru-worker-gpu`。

2. **备选：使用 CPU Worker**（不依赖 GPU）：
   ```bash
   docker compose --profile redis --profile mineru-cpu up -d redis mineru-api mineru-worker-cpu
   ```
   PDF 解析在 CPU 上执行（较慢但任意环境可用）。

3. **非 Docker 环境**  
   安装 vLLM ≥0.11.0（`pip install -U "vllm>=0.11.0"`），或使用 **vlm-lmdeploy-engine** 后端（支持多架构含 Blackwell 与 Windows）。

**说明**：若使用 **vlm-http-client** 连接远程 VLM 服务，客户端机器无需兼容 GPU；确保服务端使用 vLLM ≥0.11.0（或 lmdeploy）即可在 Blackwell 上运行。

**参考**：[MinerU Docker 部署（v0.11.0 支持 Blackwell）](https://github.com/opendatalab/MinerU/blob/master/docs/zh/quick_start/docker_deployment.md)、[vLLM RTX 5090 讨论](https://discuss.vllm.ai/t/errors-when-running-vllm-deepseek-on-rtx-5090-existing-solutions-not-working/651)。

## Docker 网络问题

### 容器网络设置失败

**症状**: 启动服务时出现类似 "failed to set up container networking: network ... not found" 或类似的网络错误

**可能原因**:
1. 现有网络处于异常状态
2. 容器名称冲突
3. 之前运行未完全清理
4. Docker 网络驱动问题

**解决方案**:

1. **清理现有容器和网络**:
   ```bash
   cd docker
   # 停止并删除所有容器
   docker compose down
   
   # 删除特定网络（如果存在）
   docker network rm docker_mineru-network 2>/dev/null || true
   docker network rm mineru-api_mineru-network 2>/dev/null || true
   
   # 删除任何孤立的容器
   docker rm -f mineru-api mineru-redis mineru-worker-gpu mineru-worker-cpu 2>/dev/null || true
   ```

2. **检查网络冲突**:
   ```bash
   # 列出所有网络
   docker network ls
   
   # 检查现有网络（如果找到）
   docker network inspect docker_mineru-network
   ```

3. **清理所有 Docker 资源**（如果上述方法不起作用）:
   ```bash
   cd docker
   docker compose down -v  # 同时删除卷
   docker system prune -f  # 清理未使用的资源
   ```

4. **重启 Docker 守护进程**（如果在 Linux 上）:
   ```bash
   sudo systemctl restart docker
   ```

5. **重建并启动服务**:
   ```bash
   cd docker
   # 仅启动 API + Redis：
   docker compose --profile redis up -d --build redis mineru-api
   
   # 启动 API + Redis + GPU Worker：
   docker compose --profile redis --profile mineru-gpu up -d --build redis mineru-api mineru-worker-gpu
   
   # 启动 API + Redis + CPU Worker：
   docker compose --profile redis --profile mineru-cpu up -d --build redis mineru-api mineru-worker-cpu
   ```

6. **如果使用 profiles，确保使用正确的命令**:
   ```bash
   cd docker
   # 仅启动 API + Redis：
   docker compose --profile redis up -d redis mineru-api
   
   # 启动 API + Redis + GPU Worker：
   docker compose --profile redis --profile mineru-gpu up -d redis mineru-api mineru-worker-gpu
   
   # 启动 API + Redis + CPU Worker：
   docker compose --profile redis --profile mineru-cpu up -d redis mineru-api mineru-worker-cpu
   ```

### 网络名称冲突

**症状**: 网络创建失败，提示 "network already exists" 错误

**解决方案**:
1. 删除冲突的网络:
   ```bash
   docker network rm docker_mineru-network
   # 或如果使用不同的项目名称
   docker network rm <项目名称>_mineru-network
   ```

2. 在 `docker-compose.yml` 中使用不同的网络名称:
   ```yaml
   networks:
     mineru-network:
       name: mineru-custom-network
       driver: bridge
   ```

## 连接问题

### Redis 连接失败

**症状**: API 或 Worker 无法连接到 Redis。可能看到：
- `Error -5 connecting to redis:6379. No address associated with hostname`

**原因（No address associated with hostname）**：容器配置使用主机名 `redis`（如 `REDIS_URL=redis://redis:6379/0`），但该主机名无法解析。通常表示 **未在同一 Compose 栈中启动 Redis 服务**——例如只启动了 `mineru-api` 而未使用 `redis` profile，网络中不存在名为 `redis` 的容器。

**解决方案**：
1. **在同一 Compose 中启动 Redis**（若使用 Compose 内 Redis，推荐）：
   ```bash
   cd docker && docker compose --profile redis up -d redis mineru-api
   ```
   使用 GPU Worker 时：`docker compose --profile redis --profile mineru-gpu up -d redis mineru-api mineru-worker-gpu`

2. **或使用外部 Redis**：在 `.env` 中设置 `REDIS_URL` 为可访问地址（如 Docker Desktop 下 `redis://host.docker.internal:6379/0`，或宿主机 Redis IP）。

3. 检查 Redis 服务是否运行:
   ```bash
   docker compose ps redis
   ```

2. 验证 Redis 连接地址:
   - Docker Compose: `redis://redis:6379/0`
   - 本地开发: `redis://localhost:6379/0`

3. 检查网络连接:
   ```bash
   docker compose exec mineru-api ping redis
   ```

4. 查看 Redis 日志:
   ```bash
   docker compose logs redis
   ```

### API 无法访问

**症状**: 无法访问 `http://localhost:8000`

**解决方案**:
1. 检查 API 服务状态:
   ```bash
   docker compose ps mineru-api
   ```

2. 检查端口是否被占用:
   ```bash
   lsof -i :8000
   ```

3. 查看 API 日志:
   ```bash
   docker compose logs mineru-api
   ```

4. 检查防火墙设置

## 任务执行问题

### 任务一直处于 pending 状态

**症状**: 提交任务后，任务状态一直是 `pending`

**可能原因**:
1. Worker 未运行
2. Worker 未连接到正确的队列
3. Redis 连接问题

**解决方案**:
1. 检查 Worker 是否运行:
   ```bash
   docker compose ps mineru-worker-cpu
   ```

2. 检查 Worker 日志:
   ```bash
   docker compose logs mineru-worker-cpu
   ```

3. 验证队列配置:
   ```bash
   docker compose exec mineru-worker-cpu env | grep MINERU_QUEUE
   ```

### 任务执行失败

**症状**: 任务状态为 `failed`

**解决方案**:
1. 查看任务错误信息:
   ```bash
   curl http://localhost:8000/api/v1/tasks/{task_id}
   ```

2. 查看 Worker 日志:
   ```bash
   docker compose logs mineru-worker-cpu | grep ERROR
   ```

3. 检查文件格式是否支持
4. 检查存储空间是否充足

### "daemonic processes are not allowed to have children"

**症状**: Worker 报错，无法执行任务

**原因**: MinerU 内部使用 `ProcessPoolExecutor`，而 Celery 的 `prefork` 池子进程是 daemon，无法创建子进程

**解决方案**: **必须使用 `WORKER_POOL=threads`**

验证配置:
```bash
docker compose exec mineru-worker-cpu env | grep WORKER_POOL
```

应该显示: `WORKER_POOL=threads`

## 性能问题

### 内存不足（OOM Killed）

**症状**: 容器退出码 137

**解决方案**:
1. 增加 Docker 内存限制（Docker Desktop → Settings → Resources → Memory）
2. 减少 Worker 并发数: `WORKER_CONCURRENCY=1`
3. 限制容器内存:
   ```yaml
   deploy:
     resources:
       limits:
         memory: 4g
   ```
4. 检查系统内存: `docker stats`

### 任务处理缓慢

**解决方案**:
1. 增加 Worker 数量:
   ```bash
   docker compose up -d --scale mineru-worker-cpu=4
   ```

2. 使用 GPU Worker（如果有 GPU）:
   ```bash
   docker compose --profile mineru-gpu up -d
   ```

3. 优化 Worker 配置:
   ```bash
   WORKER_CONCURRENCY=4
   WORKER_PREFETCH_MULTIPLIER=1
   ```

4. 检查 Redis 性能

### 队列堆积

**症状**: 队列中有大量待处理任务

**解决方案**:
1. 增加 Worker 实例
2. 使用优先级队列处理重要任务
3. 检查 Worker 是否正常运行
4. 考虑使用更强大的硬件

## 存储问题

### 文件上传失败

**症状**: 上传文件时返回 413 错误

**原因**: 文件大小超过限制

**解决方案**:
1. 增加文件大小限制:
   ```bash
   MAX_FILE_SIZE=209715200  # 200MB
   ```

2. 检查文件是否真的超过限制

### 存储空间不足

**症状**: 任务失败，提示存储空间不足

**解决方案**:
1. 清理旧文件:
   ```bash
   docker compose exec mineru-cleanup python cleanup/cleanup_outputs.py
   ```

2. 配置自动清理:
   ```bash
   docker compose --profile mineru-cleanup up -d
   ```

3. 增加存储空间或使用 S3 存储

### S3 连接问题

**症状**: 使用 S3 存储时连接失败

**解决方案**:
1. 验证 S3 配置:
   ```bash
   docker compose exec mineru-api env | grep MINERU_S3
   ```

2. 检查 S3 服务是否可访问:
   ```bash
   curl http://minio:9000
   ```

3. 验证访问密钥和密钥是否正确
4. 检查网络连接和防火墙

## 日志查看

### 查看所有服务日志

```bash
docker compose logs -f
```

### 查看特定服务日志

```bash
# API 日志
docker compose logs -f mineru-api

# Worker 日志
docker compose logs -f mineru-worker-cpu

# Redis 日志
docker compose logs -f redis
```

### 查看错误日志

```bash
docker compose logs | grep -i error
docker compose logs mineru-worker-cpu | grep -i error
```

## 调试技巧

### 进入容器调试

```bash
# 进入 API 容器
docker compose exec mineru-api bash

# 进入 Worker 容器
docker compose exec mineru-worker-cpu bash
```

### 检查环境变量

```bash
# 检查 API 环境变量
docker compose exec mineru-api env

# 检查 Worker 环境变量
docker compose exec mineru-worker-cpu env
```

### 测试 Redis 连接

```bash
docker compose exec mineru-api python -c "import redis; r = redis.from_url('redis://redis:6379/0'); print(r.ping())"
```

### 测试存储连接

```bash
# 测试本地存储
docker compose exec mineru-api ls -la /tmp/mineru_temp

# 测试 S3 存储（在容器内）
docker compose exec mineru-api python -c "from shared.storage import get_storage; s = get_storage(); print(s.storage_type)"
```

## 获取帮助

如果以上方案都无法解决问题：

1. 查看完整日志: `docker compose logs > logs.txt`
2. 检查系统资源: `docker stats`
3. 查看 GitHub Issues: [Issues](https://github.com/wzdavid/ThinkParse/issues)
4. 提交新 Issue，包含：
   - 错误信息
   - 日志输出
   - 配置信息（隐藏敏感信息）
   - 复现步骤

## 更多信息

- [部署指南](DEPLOYMENT.md)
- [配置参考](CONFIGURATION.md)
- [存储配置](S3_STORAGE.md)
