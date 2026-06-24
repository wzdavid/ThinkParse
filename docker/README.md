# Docker Configuration

This directory contains all Docker-related configuration files.

## Language

- [English](README.md) (Current)
- [中文](README.zh.md)

## File Description

- `Dockerfile.api` - API service image
- `Dockerfile.worker` - GPU Worker image (based on Dockerfile.base)
- `Dockerfile.worker.cpu` - CPU Worker image
- `Dockerfile.cleanup` - Cleanup service image
- `Dockerfile.base` - Base image (MinerU vLLM)
- `docker-compose.yml` - Docker Compose configuration

## Usage

### Simplest Way (Recommended)

**First time use**:

1. **Copy configuration files**:
   ```bash
   cd docker
   cp .env.example .env
   ```

2. **Build images**:
   ```bash
   cd docker
   # Simplest: run directly (automatically selects CPU or GPU Worker based on COMPOSE_PROFILES)
   sh build.sh
   
   # Or manually specify (build.sh supports parameters)
   # GPU Worker:
   sh build.sh --api --worker-gpu
   # CPU Worker:
   sh build.sh --api --worker-cpu
   ```

3. **Configure and start services**:
   ```bash
   cd docker
   # Edit docker/.env, set COMPOSE_PROFILES
   # Option 1: GPU Worker + internal Redis (default, requires NVIDIA GPU)
   COMPOSE_PROFILES=redis,mineru-gpu
   
   # Option 2: CPU Worker + internal Redis (recommended for development)
   # COMPOSE_PROFILES=redis,mineru-cpu
   
   # Then start all services with one command (API starts automatically)
   docker compose up -d
   ```

4. **Verify services**:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

Done! Services are now running.

> 💡 **Notes**:
> - `mineru-api` and `mineru-cleanup` services **start automatically** (no profile, required services)
> - Control which services start via `COMPOSE_PROFILES` (Redis and Worker)
> - Use `docker compose up -d` to start all configured services with one command
> - No need to manually specify each service, simpler!

### Service Configuration

**Recommended: Use `COMPOSE_PROFILES` environment variable** (configure in `docker/.env`):

```bash
# Set in docker/.env (choose one)
COMPOSE_PROFILES=redis,mineru-gpu      # GPU Worker + internal Redis (default)
COMPOSE_PROFILES=redis,mineru-cpu      # CPU Worker + internal Redis

# Using external Redis (without redis profile)
COMPOSE_PROFILES=mineru-gpu
COMPOSE_PROFILES=mineru-cpu

# Then start with one command
cd docker && docker compose up -d
```

**Notes**:
- `mineru-api` service **starts automatically** (no profile, required service)
- `mineru-cleanup` service **starts automatically** (no profile, cleanup service)
- `redis` service requires `redis` profile
- `mineru-worker-cpu` requires `mineru-cpu` profile
- `mineru-worker-gpu` requires `mineru-gpu` profile
- **Always run `docker compose` from the `docker/` directory** (`cd docker` first) so that `docker/.env` (including `COMPOSE_PROFILES`) is loaded correctly

**Manual Profile Selection** (command line, not recommended):

```bash
# Start with GPU Worker and internal Redis (default)
cd docker && docker compose --profile redis --profile mineru-gpu up -d

# Start with CPU Worker and internal Redis
cd docker && docker compose --profile redis --profile mineru-cpu up -d

# Start with GPU Worker (without internal Redis, using external Redis)
cd docker && docker compose --profile mineru-gpu up -d

# Start only API (no worker)
cd docker && docker compose up -d

# Start API with internal Redis (IMPORTANT: must use --profile redis)
cd docker && docker compose --profile redis up -d redis mineru-api

# Start API, Redis, and GPU Worker together
cd docker && docker compose --profile redis --profile mineru-gpu up -d redis mineru-api mineru-worker-gpu

# Start API, Redis, and CPU Worker together
cd docker && docker compose --profile redis --profile mineru-cpu up -d redis mineru-api mineru-worker-cpu
```

**Important Notes**:
- The `redis` service uses a profile, so you **must** use `--profile redis` when starting it
- The `mineru-worker-gpu` service uses `--profile mineru-gpu`
- The `mineru-worker-cpu` service uses `--profile mineru-cpu`
- You can combine multiple profiles: `--profile redis --profile mineru-gpu`
- If you see network errors, see the [Troubleshooting Network Issues](#troubleshooting-network-issues) section below

### View Logs and Stop Services

```bash
# View logs
cd docker && docker compose logs -f

# Stop services
cd docker && docker compose down
```

### Troubleshooting Network Issues

If you encounter network setup errors (e.g., "failed to set up container networking"):

**Step 1: Try simple restart first** (if containers were stopped cleanly):
```bash
cd docker
docker compose down
docker compose --profile redis up -d redis mineru-api
```

**Step 2: If simple restart fails, clean up manually**:
```bash
cd docker
# Stop and remove containers
docker compose down

# Force remove any remaining containers
docker rm -f mineru-api mineru-redis mineru-worker-gpu mineru-worker-cpu 2>/dev/null || true

# Remove networks (may have different names depending on project directory)
docker network rm docker_mineru-network 2>/dev/null || true
docker network rm mineru-api_mineru-network 2>/dev/null || true
docker network rm "$(basename "$(pwd)")_mineru-network" 2>/dev/null || true

# Check for any remaining mineru networks
docker network ls | grep mineru

# Restart with correct profiles
# For API + Redis only:
docker compose --profile redis up -d redis mineru-api

# For API + Redis + GPU Worker (default):
docker compose --profile redis --profile mineru-gpu up -d redis mineru-api mineru-worker-gpu

# For API + Redis + CPU Worker:
docker compose --profile redis --profile mineru-cpu up -d redis mineru-api mineru-worker-cpu
```

**Step 3: Check service status**:
```bash
docker compose ps
docker compose logs mineru-api
docker compose logs redis
```

**When to use manual cleanup**:
- Network exists but containers can't connect
- Containers are in an abnormal state (Exited, Dead, etc.)
- Simple `docker compose down` doesn't fully clean up
- You see persistent network errors even with correct `--profile` flags

For more troubleshooting information, see [TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md).

### Redis Configuration

#### Option 1: Use Internal Redis (Recommended for Development)

**Method 1: Using COMPOSE_PROFILES in `docker/.env`**:
```bash
# In docker/.env (default)
COMPOSE_PROFILES=redis,mineru-gpu
# Or use CPU Worker
# COMPOSE_PROFILES=redis,mineru-cpu
```

Then start services:
```bash
cd docker && docker compose up -d
```

**Method 2: Using command line**:
```bash
cd docker && docker compose --profile redis up -d
```

Configure in `.env` (project root):
```bash
REDIS_URL=redis://redis:6379/0
```

#### Option 2: Use External Redis on Host Machine

If you have Redis running on your host machine or another container:

1. **Configure in `.env` (project root)**:
   ```bash
   # For Docker Desktop (Mac/Windows)
   REDIS_URL=redis://host.docker.internal:6379/0
   
   # For Linux, use host network or actual IP
   REDIS_URL=redis://172.17.0.1:6379/0
   # Or if Redis is on another machine
   REDIS_URL=redis://192.168.1.100:6379/0
   ```

2. **Configure in `docker/.env` (don't include redis profile)**:
   ```bash
   # Only include worker profile, not redis
   COMPOSE_PROFILES=mineru-gpu
   # Or use CPU Worker
   # COMPOSE_PROFILES=mineru-cpu
   ```

3. **Start services**:
   ```bash
   cd docker && docker compose up -d
   ```

#### Option 3: Resolve Port Conflicts

If port 6379 is already in use by another Redis instance:

1. **Change Redis port in `docker/.env`**:
   ```bash
   REDIS_PORT=6380
   ```

2. **Update `REDIS_URL` in project root `.env`**:
   ```bash
   REDIS_URL=redis://redis:6379/0  # Internal port is still 6379
   # Or for external Redis on different port
   REDIS_URL=redis://host.docker.internal:6380/0
   ```

#### Redis with Authentication

If your external Redis requires authentication:

```bash
# With password only
REDIS_URL=redis://:password@host.docker.internal:6379/0

# With username and password
REDIS_URL=redis://username:password@host.docker.internal:6379/0
```

## Building Images

### Using Build Script (Recommended, Simplest)

The build script automatically handles all dependencies, including base images, and supports auto-selection based on `COMPOSE_PROFILES`:

```bash
cd docker

# ===== Simplest: Auto-select based on COMPOSE_PROFILES =====
# If COMPOSE_PROFILES is configured in docker/.env, automatically selects the corresponding Worker
sh build.sh

# ===== Manual specification (build.sh still supports parameters) =====
# GPU Worker:
sh build.sh --api --worker-gpu
# CPU Worker:
sh build.sh --api --worker-cpu

# ===== Other Options =====
sh build.sh --all              # Build all images (ignores COMPOSE_PROFILES)
sh build.sh --api              # Build API only
sh build.sh --worker-cpu       # Build CPU Worker only
sh build.sh --worker-gpu       # Build GPU Worker only (auto-builds base image first)
sh build.sh --cleanup         # Build cleanup service only
```

> 💡 **Tips**:
> - Running `sh build.sh` without parameters automatically reads `COMPOSE_PROFILES` from `docker/.env` and selects the corresponding Worker
> - The build script automatically checks and builds the base image `mineru-vllm:latest` required for GPU Worker, no manual handling needed
> - CPU and GPU Workers are mutually exclusive, choose one
> - If `COMPOSE_PROFILES` is not set or `.env` file doesn't exist, builds all services

### Manual Build (Advanced Users)

If you need manual control over the build process:

```bash
cd docker

# 1. GPU Worker requires base image first
docker build -f Dockerfile.base \
    --build-arg PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple} \
    -t mineru-vllm:latest ..

# 2. Build other images
docker compose build mineru-api
docker compose build mineru-worker-gpu  # Requires mineru-vllm:latest
docker compose build mineru-worker-cpu
```

## Environment Variables

### Docker Build Configuration

For Docker build configuration (e.g., `PIP_INDEX_URL` for pip mirror), create a `.env` file in the `docker/` directory:

```bash
cd docker
cp .env.example .env
# Edit .env and set PIP_INDEX_URL to your preferred pip mirror
```

This `.env` file is used by Docker Compose for build arguments (e.g., `PIP_INDEX_URL`).

### Application Runtime Configuration

For application runtime configuration, ensure you have a `.env` file in the project root directory (copy from `.env.example` in the project root).

Docker Compose will automatically read the `../.env` file for runtime environment variables.

## Notes

- All Dockerfiles' build context is the project root directory (`..`)
- File paths are relative to the project root directory
- Volume mount paths are also relative to the project root directory
