# 单容器部署（天河 / HPC）

四容器 Compose（Redis、API、Worker、Cleanup）仍是默认生产拓扑。  
当调度系统**只能提交一个容器**时，使用 all-in-one 镜像：四个角色在同一容器内由 supervisord 拉起。

- GPU 镜像：`mineru-allinone:latest`（`docker/Dockerfile.allinone`）
- CPU 镜像：`mineru-allinone-cpu:latest`（`docker/Dockerfile.allinone.cpu`）
- English: [DEPLOYMENT_ALLINONE.md](DEPLOYMENT_ALLINONE.md)

## 适用与不适用

| 场景 | 部署方式 |
|------|----------|
| 普通服务器 / Docker Compose | 继续用 [DEPLOYMENT.zh.md](DEPLOYMENT.zh.md) 四容器 |
| 多机多 GPU | [PRODUCTION_MULTI_NODE.zh.md](PRODUCTION_MULTI_NODE.zh.md) |
| 天河等只允许一个容器的算力池 | **本文 all-in-one** |

单容器模式内置本机 Redis（`127.0.0.1:6379`），只对外暴露 **8000**。Worker watchdog 退出后由 supervisord 拉起 Worker，不必重启整个容器。

## 构建镜像

```bash
cd docker

# GPU（客户天河算力池）
sh build.sh --allinone

# CPU（无 GPU 验证 / CPU 队列）
sh build.sh --allinone-cpu
```

`--allinone` 会在缺少 `mineru-vllm:latest` 时先构建基础镜像，耗时与 GPU Worker 同量级。

## 天河 / 单容器运行

调度器填写 **一个镜像**、GPU、端口 8000，以及数据盘挂载。等价于：

```bash
docker run --rm --gpus all \
  --name thinkparse \
  -p 8000:8000 \
  --env-file .env \
  -e MINERU_DEVICE_MODE=cuda \
  -e WORKER_CONCURRENCY=1 \
  -v /data/thinkparse/output:/tmp/mineru_output \
  -v /data/thinkparse/temp:/tmp/mineru_temp \
  -v /data/thinkparse/redis:/data/redis \
  mineru-allinone:latest
```

CPU 队列把 `--gpus all` 去掉，镜像换成 `mineru-allinone-cpu:latest`，并设置 `-e MINERU_DEVICE_MODE=cpu`。

### 调度器表单建议

| 项 | 值 |
|----|----|
| 镜像 | `mineru-allinone:latest` |
| 容器数量 | **1** |
| GPU | 1（一卡一任务，`WORKER_CONCURRENCY=1`） |
| 端口 | `8000` |
| 环境变量 | 见下表；**不要**把 `REDIS_URL` 设成 `redis://redis:6379/0` |
| 数据卷 | 输出、临时目录；需要任务队列在重启后保留时再挂 `/data/redis` |

入口脚本会把 `REDIS_URL` **强制**为 `redis://127.0.0.1:6379/0`，避免从四容器 `.env` 拷来的 `redis` 主机名在单容器里无法解析。

### 常用环境变量

与四容器模式相同，见 [CONFIGURATION.zh.md](CONFIGURATION.zh.md)。单容器特别注意：

| 变量 | 建议 |
|------|------|
| `MINERU_DEVICE_MODE` | GPU 用 `cuda`；CPU 用 `cpu` |
| `WORKER_CONCURRENCY` | GPU 保持 `1` |
| `TEMP_DIR` / `OUTPUT_DIR` | 默认 `/tmp/mineru_temp`、`/tmp/mineru_output`，与挂载一致 |
| `CLEANUP_INTERVAL_HOURS` | 默认 `6`，cleanup 进程在同一容器内运行 |

解析参数（`backend`、语言、公式/表格开关等）仍通过 API 提交，不因单容器改变。

## 本地用 Compose 验证单容器

不要和四容器 `docker-compose.yml` 一起启动（端口 8000 冲突）。

```bash
cd docker

# GPU
docker compose -f docker-compose.allinone.yml --profile allinone-gpu up -d

# CPU
docker compose -f docker-compose.allinone.yml --profile allinone-cpu up -d
```

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

`ready` 在 Worker 心跳写入 Redis 之前会返回 503，GPU 首次拉起可能需要数分钟。`live` 只要 API 进程在即可。

查看同一容器内四个进程的日志：

```bash
docker logs -f thinkparse-allinone
```

## 行为差异

- **扩容**：加容器台数，而不是在同一容器里加多个 Worker。一卡仍只跑一个 MinerU 任务。
- **Redis**：不对外暴露 6379；容器删除且未挂载 `/data/redis` 时，未完成任务会丢失。
- **源码**：镜像内已包含代码，不再像开发 Compose 那样挂载 `../api`。
- **健康检查**：镜像 HEALTHCHECK 打 `/api/v1/health/live`，start-period GPU 约 180 秒。

## 故障排除

`ModuleNotFoundError: No module named 'asynchat'`：镜像仍在用 Debian apt 的 supervisor 4.2.1。请用 1.4.3+ 重新构建（pip 安装 `supervisor>=4.2.5`）。  
容器已起但 `ready` 一直 503：看日志里 `program:worker` 是否在跑、是否在下载模型。  
API 报 Redis 连接失败：确认没有覆盖入口脚本之前的进程环境；单容器必须用 `127.0.0.1`。  
Worker 解析中被 watchdog 杀掉：属预期，supervisord 会重启 `program:worker`，不必整容器重启。
