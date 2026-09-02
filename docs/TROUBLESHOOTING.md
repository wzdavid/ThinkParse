# Troubleshooting

This document lists common issues and solutions.

## Table of Contents

- [GPU container fails to start (NVIDIA driver/library version mismatch)](#gpu-container-fails-to-start-nvidia-driverlibrary-version-mismatch)
- [RTX 5090 / Blackwell: CUDA error in flash-attention](#rtx-5090--blackwell-cuda-error-in-flash-attention-invalid-argument)
- [Connection Issues](#connection-issues)
- [Task Execution Issues](#task-execution-issues)
- [Performance Issues](#performance-issues)
- [Storage Issues](#storage-issues)

## Docker Build Issues

### Base Image Not Found When Building Worker

**Symptoms**: Error when building `mineru-worker-gpu`: "failed to solve: failed to fetch ... mineru-vllm:latest"

**Cause**: The `mineru-worker-gpu` service depends on the base image `mineru-vllm:latest`, which must be built first.

**Solutions**:

1. **Use the build script (Recommended)**:
   ```bash
   cd docker && sh build.sh --worker-gpu
   ```
   The script automatically checks and builds the base image if needed.

2. **Build base image manually first**:
   ```bash
   cd docker
   docker build -f Dockerfile.base \
       --build-arg PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple} \
       -t mineru-vllm:latest ..
   
   # Then build the worker
   docker compose build mineru-worker-gpu
   ```

3. **Build all images using the script**:
   ```bash
   cd docker && sh build.sh
   ```

### Base Image Build Fails

**Symptoms**: Error when building `mineru-vllm:latest` base image

**Possible Causes**:
1. Network issues downloading models
2. Insufficient disk space
3. Docker build context issues

**Solutions**:
1. Check network connection and pip mirror configuration
2. Check available disk space: `df -h`
3. Ensure you're running the build command from the correct directory:
   ```bash
   # From docker/ directory
   docker build -f Dockerfile.base -t mineru-vllm:latest ..
   ```
4. Check build logs for specific error messages
5. Try building with `--no-cache` if there are caching issues:
   ```bash
   docker build --no-cache -f docker/Dockerfile.base -t mineru-vllm:latest .
   ```

## GPU container fails to start (NVIDIA driver/library version mismatch)

**Symptoms**: When starting `mineru-worker-gpu` you see:
```text
OCI runtime create failed: ... nvidia-container-cli: initialization error: nvml error: driver/library version mismatch
```

**Cause**: The **NVIDIA kernel driver** on the host does not match the currently loaded driver (or userspace libraries). This often happens when:
- The NVIDIA driver or kernel was recently updated but the **machine was not rebooted** (old driver still in memory), or
- Multiple driver/library versions are installed and the version used by nvidia-container-toolkit does not match the loaded kernel driver.

**Steps to fix**:

1. **First try: Reboot the server**  
   If you recently updated the driver or kernel, a reboot usually restores consistency:
   ```bash
   sudo reboot
   ```
   After reboot, run:
   ```bash
   nvidia-smi
   ```
   If `nvidia-smi` works, start the GPU container again.

2. **Verify driver vs library (if you cannot reboot yet)**  
   ```bash
   # Currently loaded kernel driver version (should match userspace)
   cat /proc/driver/nvidia/version

   # Userspace driver version (if nvidia-driver is installed)
   nvidia-smi
   ```
   If `nvidia-smi` already reports `driver/library version mismatch`, the kernel and userspace versions do not match; you **must reboot** or reinstall/switch to a matching driver version.

3. **Optional: Use CPU worker temporarily**  
   Until the GPU environment is fixed, you can run the CPU worker instead:
   ```bash
   docker compose --profile redis --profile mineru-cpu up -d
   ```

### RTX 5090 / Blackwell: CUDA error in flash-attention (invalid argument)

**Symptoms**: On NVIDIA RTX 5090 (Blackwell, compute capability 12.0), the VLM engine fails with:
```text
CUDA error (.../xformers/.../hopper/flash_fwd_launch_template.h:188): invalid argument
Engine core initialization failed. See root cause above.
```

**Cause**: The **v0.10.1.1** vLLM base image only supports Ampere, Ada Lovelace, and Hopper (CC 8.0–9.0). Its flash-attention kernels are not built for **Blackwell** (SM 12.0), so the CUDA launch returns "invalid argument". MinerU 2.6.2+ (through 2.7.4) supports Blackwell by using a **vLLM 0.11.0** base image.

**Recommended fix (Docker)**:

1. **Use the v0.11.0 base image**  
   In `docker/Dockerfile.base`, the default is now `vllm/vllm-openai:v0.11.0`. If you still have an older build using v0.10.1.1, rebuild the base image and GPU worker:
   ```bash
   cd docker && sh build.sh --worker-gpu
   ```
   Or manually: ensure the `FROM` line in `Dockerfile.base` is `FROM vllm/vllm-openai:v0.11.0` (or the DaoCloud mirror equivalent), then rebuild the base image and `mineru-worker-gpu`.

2. **Alternative: use CPU worker** (no GPU required):
   ```bash
   docker compose --profile redis --profile mineru-cpu up -d redis mineru-api mineru-worker-cpu
   ```
   PDF parsing runs on CPU (slower but works on any host).

3. **Non-Docker**  
   Install vLLM ≥0.11.0 (`pip install -U "vllm>=0.11.0"`), or use the **vlm-lmdeploy-engine** backend (supports multiple architectures including Blackwell and Windows).

**Note**: If you use **vlm-http-client** to connect to a remote VLM server, the client machine does not need a compatible GPU; ensure the server runs vLLM ≥0.11.0 (or lmdeploy) for Blackwell.

**References**: [MinerU Docker deployment (v0.11.0 for Blackwell)](https://github.com/opendatalab/MinerU/blob/master/docs/zh/quick_start/docker_deployment.md), [vLLM RTX 5090 discussion](https://discuss.vllm.ai/t/errors-when-running-vllm-deepseek-on-rtx-5090-existing-solutions-not-working/651).

## Docker Network Issues

### Container Networking Setup Failed

**Symptoms**: Error message like "failed to set up container networking: network ... not found" or similar network errors when starting services

**Possible Causes**:
1. Existing network in abnormal state
2. Container name conflicts
3. Incomplete cleanup from previous runs
4. Docker network driver issues

**Solutions**:

1. **Clean up existing containers and networks**:
   ```bash
   cd docker
   # Stop and remove all containers
   docker compose down
   
   # Remove the specific network if it exists
   docker network rm docker_mineru-network 2>/dev/null || true
   docker network rm mineru-api_mineru-network 2>/dev/null || true
   
   # Remove any orphaned containers
   docker rm -f mineru-api mineru-redis mineru-worker-gpu mineru-worker-cpu 2>/dev/null || true
   ```

2. **Check for network conflicts**:
   ```bash
   # List all networks
   docker network ls
   
   # Inspect existing network (if found)
   docker network inspect docker_mineru-network
   ```

3. **Clean up all Docker resources** (if above doesn't work):
   ```bash
   cd docker
   docker compose down -v  # Remove volumes too
   docker system prune -f  # Clean up unused resources
   ```

4. **Restart Docker daemon** (if on Linux):
   ```bash
   sudo systemctl restart docker
   ```

5. **Rebuild and start services**:
   ```bash
   cd docker
   # For API + Redis only:
   docker compose --profile redis up -d --build redis mineru-api
   
   # For API + Redis + GPU Worker:
   docker compose --profile redis --profile mineru-gpu up -d --build redis mineru-api mineru-worker-gpu
   
   # For API + Redis + CPU Worker:
   docker compose --profile redis --profile mineru-cpu up -d --build redis mineru-api mineru-worker-cpu
   ```

6. **If using profiles, ensure correct command**:
   ```bash
   cd docker
   # API + Redis only:
   docker compose --profile redis up -d redis mineru-api
   
   # API + Redis + GPU Worker:
   docker compose --profile redis --profile mineru-gpu up -d redis mineru-api mineru-worker-gpu
   
   # API + Redis + CPU Worker:
   docker compose --profile redis --profile mineru-cpu up -d redis mineru-api mineru-worker-cpu
   ```

### Network Name Conflicts

**Symptoms**: Network creation fails with "network already exists" error

**Solutions**:
1. Remove conflicting network:
   ```bash
   docker network rm docker_mineru-network
   # Or if using different project name
   docker network rm <project-name>_mineru-network
   ```

2. Use a different network name in `docker-compose.yml`:
   ```yaml
   networks:
     mineru-network:
       name: mineru-custom-network
       driver: bridge
   ```

## Connection Issues

### Redis Connection Failed

**Symptoms**: API or Worker cannot connect to Redis. You may see:
- `Error -5 connecting to redis:6379. No address associated with hostname`

**Cause (No address associated with hostname)**: The container is configured to use hostname `redis` (e.g. `REDIS_URL=redis://redis:6379/0`), but that hostname is not resolvable. This usually means the Redis service is **not** running in the same Compose stack—for example you started only `mineru-api` without the `redis` profile, so no container named `redis` exists on the network.

**Solutions**:
1. **Start Redis in the same Compose run** (recommended if using Compose Redis):
   ```bash
   cd docker && docker compose --profile redis up -d redis mineru-api
   ```
   For GPU worker: `docker compose --profile redis --profile mineru-gpu up -d redis mineru-api mineru-worker-gpu`

2. **Or use an external Redis** and set `REDIS_URL` in `.env` to a reachable address (e.g. `redis://host.docker.internal:6379/0` on Docker Desktop, or your Redis host IP).

3. Check if Redis service is running:
   ```bash
   cd docker && docker compose ps redis
   ```

2. Verify Redis connection address:
   - Docker Compose: `redis://redis:6379/0`
   - Local development: `redis://localhost:6379/0`

3. Check network connection:
   ```bash
   cd docker && docker compose exec mineru-api ping redis
   ```

4. View Redis logs:
   ```bash
   cd docker && docker compose logs redis
   ```

### API Not Accessible

**Symptoms**: Cannot access `http://localhost:8000`

**Solutions**:
1. Check API service status:
   ```bash
   cd docker && docker compose ps mineru-api
   ```

2. Check if port is occupied:
   ```bash
   lsof -i :8000
   ```

3. View API logs:
   ```bash
   cd docker && docker compose logs mineru-api
   ```

4. Check firewall settings

## Task Execution Issues

### Task Stuck in Pending State

**Symptoms**: Task status remains `pending` after submission

**Possible Causes**:
1. Worker not running
2. Worker not connected to correct queue
3. Redis connection issues

**Solutions**:
1. Check if Worker is running:
   ```bash
   cd docker && docker compose ps mineru-worker-cpu
   ```

2. Check Worker logs:
   ```bash
   cd docker && docker compose logs mineru-worker-cpu
   ```

3. Verify queue configuration:
   ```bash
   cd docker && docker compose exec mineru-worker-cpu env | grep MINERU_QUEUE
   ```

### Task Execution Failed

**Symptoms**: Task status is `failed`

**Solutions**:
1. View task error information:
   ```bash
   curl http://localhost:8000/api/v1/tasks/{task_id}
   ```

2. View Worker logs:
   ```bash
   cd docker && docker compose logs mineru-worker-cpu | grep ERROR
   ```

3. Check if file format is supported
4. Check if storage space is sufficient

### "daemonic processes are not allowed to have children"

**Symptoms**: Worker error, cannot execute tasks

**Cause**: MinerU internally uses `ProcessPoolExecutor`, while Celery's `prefork` pool child processes are daemon processes and cannot create child processes

**Solution**: **Must use `WORKER_POOL=threads`**

Verify configuration:
```bash
cd docker && docker compose exec mineru-worker-cpu env | grep WORKER_POOL
```

Should display: `WORKER_POOL=threads`

## Performance Issues

### Out of Memory (OOM Killed)

**Symptoms**: Container exit code 137

**Solutions**:
1. Increase Docker memory limit (Docker Desktop → Settings → Resources → Memory)
2. Reduce Worker concurrency: `WORKER_CONCURRENCY=1`
3. Limit container memory:
   ```yaml
   deploy:
     resources:
       limits:
         memory: 4g
   ```
4. Check system memory: `docker stats`

### Slow Task Processing

**Solutions**:
1. Increase Worker count:
   ```bash
   cd docker && docker compose up -d --scale mineru-worker-cpu=4
   ```

2. Use GPU Worker (if GPU available):
   ```bash
   cd docker && docker compose --profile mineru-gpu up -d
   ```

3. Optimize Worker configuration:
   ```bash
   # GPU: one active task per card; only raise this gradually for CPU workers
   WORKER_CONCURRENCY=1
   WORKER_PREFETCH_MULTIPLIER=1
   MINERU_ENABLE_PAGINATION=false
   MINERU_PROCESSING_WINDOW_SIZE=64
   ```

4. Check Redis performance

### GPU Worker Is Alive but Tasks Stop Progressing

**Symptoms**: The Worker container is running, a task remains `processing` for
an unusually long time, and a cancellation request does not stop GPU work.

**Causes**:
- Older deployments ran MinerU directly in a Celery thread, which could not
  be force-terminated.
- Concurrency above one makes tasks compete for the same GPU.
- Legacy physical PDF splitting can occupy Worker slots during chunk/merge scheduling.

**Actions**:
1. Set `WORKER_CONCURRENCY=1` and `MINERU_ENABLE_PAGINATION=false`.
2. Check GPU activity, Worker logs, and free disk space.
3. Request cancellation through the API. ThinkParse terminates the isolated
   MinerU engine and starts a fresh engine for the next task.
4. If the Worker heartbeat itself is absent, restart the GPU Worker:
   ```bash
   docker restart mineru-worker-gpu
   ```

`MINERU_ENGINE_TIMEOUT_SECONDS` enforces the same recovery path automatically
for an engine call that exceeds its wall-clock limit. The Worker watchdog
persists a cancellation marker before exiting so a late-ack redelivery
terminates instead of repeating the failing task. Keep timeout ordering as:

```text
MINERU_ENGINE_TIMEOUT_SECONDS
  < WORKER_WATCHDOG_TIMEOUT_SECONDS
  < BROKER_VISIBILITY_TIMEOUT_SECONDS
  < RESULT_EXPIRES
```

### Queue Backlog

**Symptoms**: Large number of pending tasks in queue

**Solutions**:
1. Increase Worker instances
2. Use priority queue for important tasks
3. Check if Worker is running normally
4. Consider using more powerful hardware

## Storage Issues

### File Upload Failed

**Symptoms**: Returns 413 error when uploading files

**Cause**: File size exceeds limit

**Solutions**:
1. Increase file size limit:
   ```bash
   MAX_FILE_SIZE=209715200  # 200MB
   ```

2. Check if file actually exceeds limit

### Insufficient Storage Space

**Symptoms**: Task fails, prompts insufficient storage space

**Solutions**:
1. Clean old files:
   ```bash
   cd docker && docker compose exec mineru-cleanup python cleanup/cleanup_outputs.py
   ```

2. Configure automatic cleanup:
   ```bash
   cd docker && docker compose --profile mineru-cleanup up -d
   ```

3. Increase storage space or use S3 storage

### S3 Connection Issues

**Symptoms**: Connection failed when using S3 storage

**Solutions**:
1. Verify S3 configuration:
   ```bash
   cd docker && docker compose exec mineru-api env | grep MINERU_S3
   ```

2. Check if S3 service is accessible:
   ```bash
   curl http://minio:9000
   ```

3. Verify access key and secret key are correct
4. Check network connection and firewall

## Viewing Logs

### View All Service Logs

```bash
cd docker && docker compose logs -f
```

### View Specific Service Logs

```bash
# API logs
cd docker && docker compose logs -f mineru-api

# Worker logs
cd docker && docker compose logs -f mineru-worker-cpu

# Redis logs
cd docker && docker compose logs -f redis
```

### View Error Logs

```bash
cd docker && docker compose logs | grep -i error
cd docker && docker compose logs mineru-worker-cpu | grep -i error
```

## Debugging Tips

### Enter Container for Debugging

```bash
# Enter API container
cd docker && docker compose exec mineru-api bash

# Enter Worker container
cd docker && docker compose exec mineru-worker-cpu bash
```

### Check Environment Variables

```bash
# Check API environment variables
cd docker && docker compose exec mineru-api env

# Check Worker environment variables
cd docker && docker compose exec mineru-worker-cpu env
```

### Test Redis Connection

```bash
cd docker && docker compose exec mineru-api python -c "import redis; r = redis.from_url('redis://redis:6379/0'); print(r.ping())"
```

### Test Storage Connection

```bash
# Test local storage
cd docker && docker compose exec mineru-api ls -la /tmp/mineru_temp

# Test S3 storage (inside container)
cd docker && docker compose exec mineru-api python -c "from shared.storage import get_storage; s = get_storage(); print(s.storage_type)"
```

## Getting Help

If the above solutions cannot resolve the issue:

1. View complete logs: `cd docker && docker compose logs > logs.txt`
2. Check system resources: `docker stats`
3. View GitHub Issues: [Issues](https://github.com/wzdavid/ThinkParse/issues)
4. Submit a new Issue, including:
   - Error information
   - Log output
   - Configuration information (hide sensitive information)
   - Reproduction steps

## More Information

- [Deployment Guide](DEPLOYMENT.md)
- [Configuration Reference](CONFIGURATION.md)
- [Storage Configuration](S3_STORAGE.md)
