# Docker 配置

本目录包含所有 Docker 相关配置文件。

## 语言

- [English](README.md)
- [中文](README.zh.md) (当前)

## 文件说明

- `Dockerfile.api` - API 服务镜像
- `Dockerfile.worker` - GPU Worker 镜像（基于 Dockerfile.base）
- `Dockerfile.worker.cpu` - CPU Worker 镜像
- `Dockerfile.cleanup` - 清理服务镜像
- `Dockerfile.base` - 基础镜像（MinerU vLLM）
- `Dockerfile.allinone` - 单容器 GPU 镜像（Redis + API + Worker + Cleanup）
- `Dockerfile.allinone.cpu` - 单容器 CPU 镜像
- `entrypoint-allinone.sh` / `supervisord.allinone.conf` - 单容器进程编排
- `docker-compose.yml` - 默认四容器 Docker Compose
- `docker-compose.allinone.yml` - 单容器 Compose（天河 / HPC）

调度系统只能提交一个容器时，不要用上面的四容器 Compose。构建并运行 all-in-one 镜像，说明见 [单容器部署](../docs/DEPLOYMENT_ALLINONE.zh.md)。

## 使用方法

### 最简单的方式（推荐）

**首次使用**：

1. **复制配置文件**：
   ```bash
   cd docker
   cp .env.example .env
   ```

2. **构建镜像**:
   ```bash
   cd docker
   # 最简单：直接运行（会根据 COMPOSE_PROFILES 自动选择构建 CPU 或 GPU Worker）
   sh build.sh
   
   # 或者手动指定（build.sh 支持参数方式）
   # GPU Worker:
   sh build.sh --api --worker-gpu
   # CPU Worker:
   sh build.sh --api --worker-cpu
   ```

3. **配置并启动服务**：
   ```bash
   cd docker
   # 编辑 docker/.env，设置 COMPOSE_PROFILES
   # 方式 1: GPU Worker + 内部 Redis（默认值，需要 NVIDIA GPU）
   COMPOSE_PROFILES=redis,mineru-gpu
   
   # 方式 2: CPU Worker + 内部 Redis（推荐开发环境）
   # COMPOSE_PROFILES=redis,mineru-cpu
   
   # 然后一键启动所有服务（API 会自动启动，无需指定）
   docker compose up -d
   ```

4. **验证服务**：
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

完成！服务已启动。

> 💡 **说明**：
> - `mineru-api` 和 `mineru-cleanup` 服务没有 profile，会**自动启动**（必需服务）
> - 通过 `COMPOSE_PROFILES` 控制启动 Redis 和 Worker
> - 使用 `docker compose up -d` 一键启动所有配置的服务
> - 无需手动指定每个服务，更简单！

### 服务配置说明

**推荐方式：使用 `COMPOSE_PROFILES` 环境变量**（在 `docker/.env` 中配置）：

```bash
# 在 docker/.env 中设置（选择一种）
COMPOSE_PROFILES=redis,mineru-gpu      # GPU Worker + 内部 Redis（默认值）
COMPOSE_PROFILES=redis,mineru-cpu      # CPU Worker + 内部 Redis

# 使用外部 Redis（不包含 redis profile）
COMPOSE_PROFILES=mineru-gpu
COMPOSE_PROFILES=mineru-cpu

# 然后一键启动
cd docker && docker compose up -d
```

**说明**：
- `mineru-api` 服务**没有 profile，会自动启动**（必需服务）
- `mineru-cleanup` 服务**没有 profile，会自动启动**（自动清理服务）
- `redis` 服务需要 `redis` profile
- `mineru-worker-cpu` 需要 `mineru-cpu` profile
- `mineru-worker-gpu` 需要 `mineru-gpu` profile
- **请始终在 `docker/` 目录下运行 `docker compose`**（先执行 `cd docker`），以确保 `docker/.env`（含 `COMPOSE_PROFILES`）被正确加载

**手动指定 Profile**（命令行方式，不推荐）：

```bash
# 启动 GPU Worker 和内部 Redis（默认方式）
cd docker && docker compose --profile redis --profile mineru-gpu up -d

# 启动 CPU Worker 和内部 Redis
cd docker && docker compose --profile redis --profile mineru-cpu up -d

# 启动 GPU Worker（不包含内部 Redis，使用外部 Redis）
cd docker && docker compose --profile mineru-gpu up -d

# 仅启动 API（不启动 Worker）
cd docker && docker compose up -d

# 启动 API 和内部 Redis（重要：必须使用 --profile redis）
cd docker && docker compose --profile redis up -d redis mineru-api

# 同时启动 API、Redis 和 GPU Worker
cd docker && docker compose --profile redis --profile mineru-gpu up -d redis mineru-api mineru-worker-gpu

# 同时启动 API、Redis 和 CPU Worker
cd docker && docker compose --profile redis --profile mineru-cpu up -d redis mineru-api mineru-worker-cpu
```

**重要提示**：
- `redis` 服务使用了 profile，启动时必须使用 `--profile redis`
- `mineru-worker-gpu` 服务使用 `--profile mineru-gpu`
- `mineru-worker-cpu` 服务使用 `--profile mineru-cpu`
- 可以组合多个 profiles：`--profile redis --profile mineru-gpu`
- 如果遇到网络错误，请参阅下面的[网络问题故障排除](#网络问题故障排除)部分

### 查看日志和停止服务

```bash
# 查看日志
cd docker && docker compose logs -f

# 停止服务
cd docker && docker compose down
```

### 网络问题故障排除

如果遇到网络设置错误（例如："failed to set up container networking"）：

**步骤 1：先尝试简单重启**（如果容器是正常停止的）：
```bash
cd docker
docker compose down
docker compose --profile redis up -d redis mineru-api
```

**步骤 2：如果简单重启失败，手动清理**：
```bash
cd docker
# 停止并删除容器
docker compose down

# 强制删除任何剩余的容器
docker rm -f mineru-api mineru-redis mineru-worker-gpu mineru-worker-cpu 2>/dev/null || true

# 删除网络（网络名称可能因项目目录而异）
docker network rm docker_mineru-network 2>/dev/null || true
docker network rm mineru-api_mineru-network 2>/dev/null || true
docker network rm "$(basename "$(pwd)")_mineru-network" 2>/dev/null || true

# 检查是否有剩余的 mineru 网络
docker network ls | grep mineru

# 使用正确的 profiles 重启
# 仅启动 API + Redis：
docker compose --profile redis up -d redis mineru-api

# 启动 API + Redis + GPU Worker（默认）：
docker compose --profile redis --profile mineru-gpu up -d redis mineru-api mineru-worker-gpu

# 启动 API + Redis + CPU Worker：
docker compose --profile redis --profile mineru-cpu up -d redis mineru-api mineru-worker-cpu
```

**步骤 3：检查服务状态**：
```bash
docker compose ps
docker compose logs mineru-api
docker compose logs redis
```

**何时需要手动清理**：
- 网络存在但容器无法连接
- 容器处于异常状态（Exited、Dead 等）
- 简单的 `docker compose down` 无法完全清理
- 即使使用了正确的 `--profile` 标志仍然出现持续的网络错误

更多故障排除信息，请参阅 [TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md)。

### Redis 配置

#### 选项 1：使用内部 Redis（推荐用于开发环境）

**方法 1：在 `docker/.env` 中使用 COMPOSE_PROFILES**：
```bash
# 在 docker/.env 中（默认值）
COMPOSE_PROFILES=redis,mineru-gpu
# 或使用 CPU Worker
# COMPOSE_PROFILES=redis,mineru-cpu
```

然后启动服务：
```bash
cd docker && docker compose up -d
```

**方法 2：使用命令行**：
```bash
cd docker && docker compose --profile redis up -d
```

在项目根目录的 `.env` 文件中配置：
```bash
REDIS_URL=redis://redis:6379/0
```

#### 选项 2：使用主机上的外部 Redis

如果您的主机或其他容器上已有 Redis 运行：

1. **在项目根目录的 `.env` 文件中配置**：
   ```bash
   # Docker Desktop (Mac/Windows)
   REDIS_URL=redis://host.docker.internal:6379/0
   
   # Linux 系统，使用主机网络或实际 IP
   REDIS_URL=redis://172.17.0.1:6379/0
   # 或者如果 Redis 在另一台机器上
   REDIS_URL=redis://192.168.1.100:6379/0
   ```

2. **在 `docker/.env` 中配置（不包含 redis profile）**：
   ```bash
   # 只包含 worker profile，不包含 redis
   COMPOSE_PROFILES=mineru-gpu
   # 或使用 CPU Worker
   # COMPOSE_PROFILES=mineru-cpu
   ```

3. **启动服务**：
   ```bash
   cd docker && docker compose up -d
   ```

#### 选项 3：解决端口冲突

如果端口 6379 已被其他 Redis 实例使用：

1. **在 `docker/.env` 中修改 Redis 端口**：
   ```bash
   REDIS_PORT=6380
   ```

2. **在项目根目录的 `.env` 中更新 `REDIS_URL`**：
   ```bash
   REDIS_URL=redis://redis:6379/0  # 容器内部端口仍然是 6379
   # 或者对于不同端口的外部 Redis
   REDIS_URL=redis://host.docker.internal:6380/0
   ```

#### 带认证的 Redis

如果您的外部 Redis 需要认证：

```bash
# 仅密码
REDIS_URL=redis://:password@host.docker.internal:6379/0

# 用户名和密码
REDIS_URL=redis://username:password@host.docker.internal:6379/0
```

## 构建镜像

### 使用构建脚本（推荐，最简单）

构建脚本会自动处理所有依赖关系，包括基础镜像，并支持根据 `COMPOSE_PROFILES` 自动选择：

```bash
cd docker

# ===== 最简单：根据 COMPOSE_PROFILES 自动选择 =====
# 如果 docker/.env 中配置了 COMPOSE_PROFILES，会自动选择构建对应的 Worker
sh build.sh

# ===== 手动指定（build.sh 仍支持参数方式）=====
# GPU Worker:
sh build.sh --api --worker-gpu
# CPU Worker:
sh build.sh --api --worker-cpu

# ===== 其他选项 =====
sh build.sh --all              # 构建所有镜像（忽略 COMPOSE_PROFILES）
sh build.sh --api              # 仅构建 API
sh build.sh --worker-cpu       # 仅构建 CPU Worker
sh build.sh --worker-gpu       # 构建 GPU Worker（缺少基础镜像时自动构建）
sh build.sh --cleanup          # 仅构建清理服务
sh build.sh --allinone         # 构建 GPU 单容器镜像（天河）
sh build.sh --allinone-cpu     # 构建 CPU 单容器镜像
sh build.sh --worker-gpu --rebuild-base  # MinerU 升级后强制重建基础镜像
```

> 💡 **提示**：
> - 不带参数运行 `sh build.sh` 时，会自动读取 `docker/.env` 中的 `COMPOSE_PROFILES`，选择构建对应的 Worker
> - 构建脚本会检查 GPU Worker 所需的 `mineru-vllm:latest`，缺失时自动构建
> - 修改 MinerU 版本后应使用 `--rebuild-base`；否则会复用已有基础镜像
> - CPU 和 GPU Worker 是互斥的，选择一种即可
> - 如果 `COMPOSE_PROFILES` 未设置或 `.env` 文件不存在，会构建所有服务

### 手动构建（高级用户）

如果您需要手动控制构建过程：

```bash
cd docker

# 1. 构建 GPU Worker 需要先构建基础镜像
docker build -f Dockerfile.base \
    --build-arg PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple} \
    -t mineru-vllm:latest ..

# 2. 构建其他镜像
docker compose build mineru-api
docker compose build mineru-worker-gpu  # 需要 mineru-vllm:latest
docker compose build mineru-worker-cpu
```

## 环境变量

### Docker 构建配置

对于 Docker 构建配置（例如用于 pip 镜像源的 `PIP_INDEX_URL`），请在 `docker/` 目录创建 `.env` 文件：

```bash
cd docker
cp .env.example .env
# 编辑 .env 并设置 PIP_INDEX_URL 为您偏好的 pip 镜像源
```

此 `.env` 文件用于 Docker Compose 的构建参数（例如 `PIP_INDEX_URL`）。`build.sh --rebuild-base` 也会读取同一个 `PIP_INDEX_URL`；不要只依赖环境变量，裸 `docker build Dockerfile.base` 必须显式加 `--build-arg`。

### 应用运行时配置

对于应用运行时配置，请确保在项目根目录有 `.env` 文件（从项目根目录的 `.env.example` 复制）。

Docker Compose 会自动读取 `../.env` 文件作为运行时环境变量。

## 注意事项

- 所有 Dockerfile 的构建上下文（context）是项目根目录（`..`）
- 文件路径相对于项目根目录
- 卷挂载路径也相对于项目根目录
