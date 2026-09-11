#!/bin/sh
# Start Redis + API + Worker + Cleanup in one process tree (Tianhe / HPC).
# The four-container Compose stack remains the default for normal deployments.
set -eu

export PYTHONPATH="${PYTHONPATH:-/app}"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-local}"
export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"
# Always use the in-container Redis. A copied compose .env often has
# redis://redis:6379/0, which has no DNS name in this image.
export REDIS_URL="redis://127.0.0.1:6379/0"

mkdir -p \
    /data/redis \
    "${TEMP_DIR:-/tmp/mineru_temp}" \
    "${OUTPUT_DIR:-/tmp/mineru_output}" \
    /var/log/supervisor \
    /var/run

echo "ThinkParse all-in-one starting"
echo "  REDIS_URL=${REDIS_URL}"
echo "  API=${API_HOST}:${API_PORT}"
echo "  MINERU_MODEL_SOURCE=${MINERU_MODEL_SOURCE}"

exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.allinone.conf
