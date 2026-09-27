#!/bin/sh
# Start one MinerU worker container per GPU slot.
#
# Configure in docker/.env (or pass flags):
#   MINERU_GPU_COUNT=2            # omit to use nvidia-smi -L
#   MINERU_WORKERS_PER_GPU=4      # engines on each card; default 1
#   GPU_WORKER_CONCURRENCY=1      # keep 1; the engine lock is per process
#   MINERU_GPU_WORKER_ONLY=1      # dedicated GPU host: do not start API/cleanup
#
# From docker/:
#   sh gpu-up.sh
#   sh gpu-up.sh --render-only
#   sh gpu-up.sh --gpu-count 2 --workers-per-gpu 4
#
# Do not also enable profile mineru-gpu. That service sees every card and
# usually uses only cuda:0, and it would compete for the same Celery queue.

set -eu

cd "$(dirname "$0")"

RENDER_ONLY=0
WORKER_ONLY=""
GPU_COUNT_ARG=""
WORKERS_ARG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --render-only)
      RENDER_ONLY=1
      shift
      ;;
    --worker-only)
      WORKER_ONLY=1
      shift
      ;;
    --gpu-count)
      GPU_COUNT_ARG="${2:?--gpu-count needs a value}"
      shift 2
      ;;
    --workers-per-gpu)
      WORKERS_ARG="${2:?--workers-per-gpu needs a value}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

read_env() {
  key="$1"
  default="$2"
  if [ -f .env ]; then
    line=$(grep -E "^[[:space:]]*${key}=" .env | tail -n 1 || true)
    if [ -n "$line" ]; then
      val=${line#*=}
      val=$(printf '%s' "$val" | sed -e 's/[[:space:]]*#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
      if [ -n "$val" ]; then
        printf '%s' "$val"
        return
      fi
    fi
  fi
  printf '%s' "$default"
}

if [ -n "$GPU_COUNT_ARG" ]; then
  GPU_COUNT="$GPU_COUNT_ARG"
else
  GPU_COUNT=$(read_env MINERU_GPU_COUNT "")
fi

if [ -n "$WORKERS_ARG" ]; then
  WORKERS_PER_GPU="$WORKERS_ARG"
else
  WORKERS_PER_GPU=$(read_env MINERU_WORKERS_PER_GPU "1")
fi

if [ -z "$WORKER_ONLY" ]; then
  WORKER_ONLY=$(read_env MINERU_GPU_WORKER_ONLY "0")
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "gpu-up.sh needs python3 on the host to write the compose file." >&2
  exit 1
fi

if [ -z "$GPU_COUNT" ]; then
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "Set MINERU_GPU_COUNT or install nvidia-smi so the card count can be detected." >&2
    exit 1
  fi
  GPU_COUNT=$(nvidia-smi -L | wc -l | tr -d ' ')
  if [ -z "$GPU_COUNT" ] || [ "$GPU_COUNT" -eq 0 ]; then
    echo "nvidia-smi -L reported no GPUs. Set MINERU_GPU_COUNT." >&2
    exit 1
  fi
fi

OUTPUT="docker-compose.gpus.yml"
python3 render-gpu-workers.py \
  --gpu-count "$GPU_COUNT" \
  --workers-per-gpu "$WORKERS_PER_GPU" \
  -o "$OUTPUT"

if [ "$RENDER_ONLY" -eq 1 ]; then
  exit 0
fi

COMPOSE_FILE="docker-compose.yml:${OUTPUT}"
if [ "$WORKER_ONLY" = "1" ] || [ "$WORKER_ONLY" = "true" ]; then
  COMPOSE_FILE="${COMPOSE_FILE}:docker-compose.worker-only.yml"
  COMPOSE_PROFILES="mineru-multi-gpu"
else
  COMPOSE_PROFILES="redis,mineru-multi-gpu"
fi
export COMPOSE_FILE COMPOSE_PROFILES

profiles=$(read_env COMPOSE_PROFILES "")
case ",${profiles}," in
  *,mineru-gpu,*)
    echo "Note: docker/.env COMPOSE_PROFILES includes mineru-gpu." >&2
    echo "This run overrides that. A later plain 'docker compose up' can start the single shared GPU worker again." >&2
    echo "Keep using sh gpu-up.sh for this multi-worker stack." >&2
    ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to start workers. The compose file is at ${OUTPUT}." >&2
  exit 1
fi

# Validate before stopping anything. A bad compose file must leave running workers alone.
docker compose config --quiet

# Drop GPU workers that are not in this render: the single mineru-worker-gpu,
# legacy mineru-worker-gpu-0 / mineru-worker-gpu-0b names, and extra slots from
# a previous MINERU_WORKERS_PER_GPU. Match the whole container_name so
# mineru-worker-gpu-0 does not count as mineru-worker-gpu-0-0.
all_names=$(docker ps -a --format '{{.Names}}') || exit 1
stale=""
for name in $all_names; do
  case "$name" in
    mineru-worker-gpu|mineru-worker-gpu-*)
      if ! grep -Eq "^[[:space:]]*container_name: ${name}$" "$OUTPUT"; then
        stale="${stale} ${name}"
      fi
      ;;
  esac
done

if [ -n "$stale" ]; then
  if ! docker image inspect mineru-worker:latest >/dev/null 2>&1; then
    echo "mineru-worker:latest is not built. Refusing to stop existing workers:" >&2
    echo "$stale" >&2
    echo "Build it first (sh build.sh --worker-gpu), then re-run sh gpu-up.sh." >&2
    exit 1
  fi
  for name in $stale; do
    echo "Stopping worker ${name} (not in ${OUTPUT})" >&2
    docker rm -f "$name" >/dev/null
  done
fi

docker compose up -d
echo "Multi-GPU workers: ${GPU_COUNT} cards x ${WORKERS_PER_GPU} processes. Profile: ${COMPOSE_PROFILES}" >&2
