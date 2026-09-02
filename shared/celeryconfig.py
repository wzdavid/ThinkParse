# -*- coding: utf-8 -*-
"""
MinerU Celery Shared Configuration
Used by both API and Worker services to ensure consistent settings.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Redis configuration
broker_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
result_backend = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
broker_visibility_timeout = int(
    os.getenv('BROKER_VISIBILITY_TIMEOUT_SECONDS', 9000)
)
broker_transport_options = {
    'visibility_timeout': broker_visibility_timeout,
}

# Serialization
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']

# Timezone
timezone = 'UTC'
enable_utc = True

# Task tracking
task_track_started = True

# Execution settings
task_time_limit = int(os.getenv('TASK_TIME_LIMIT', 7200))          # 2 hours hard timeout
task_soft_time_limit = int(os.getenv('TASK_SOFT_TIME_LIMIT', 6000))  # 100 minutes soft timeout
mineru_engine_timeout = float(os.getenv('MINERU_ENGINE_TIMEOUT_SECONDS', task_time_limit))
worker_watchdog_timeout = float(os.getenv('WORKER_WATCHDOG_TIMEOUT_SECONDS', 7500))
if worker_watchdog_timeout > 0 and worker_watchdog_timeout <= mineru_engine_timeout:
    raise ValueError(
        "WORKER_WATCHDOG_TIMEOUT_SECONDS must be greater than "
        "MINERU_ENGINE_TIMEOUT_SECONDS, or 0 to disable"
    )
if broker_visibility_timeout <= max(
    task_time_limit,
    mineru_engine_timeout,
    worker_watchdog_timeout,
):
    raise ValueError(
        "BROKER_VISIBILITY_TIMEOUT_SECONDS must be greater than "
        "TASK_TIME_LIMIT, MINERU_ENGINE_TIMEOUT_SECONDS, and "
        "WORKER_WATCHDOG_TIMEOUT_SECONDS"
    )

# Result settings
result_expires = int(os.getenv('RESULT_EXPIRES', 86400))           # 1 day
if result_expires <= broker_visibility_timeout:
    raise ValueError(
        "RESULT_EXPIRES must be greater than BROKER_VISIBILITY_TIMEOUT_SECONDS "
        "so cancellation markers survive task redelivery"
    )

# Queue configuration
_task_queue = os.getenv('MINERU_QUEUE', 'mineru-tasks')
_task_exchange = os.getenv('MINERU_EXCHANGE', 'mineru')
_task_routing_key = os.getenv('MINERU_ROUTING_KEY', 'mineru.tasks')

task_default_queue = _task_queue
task_default_exchange = _task_exchange
task_default_routing_key = _task_routing_key
task_queues = {
    _task_queue: {
        'exchange': _task_exchange,
        'routing_key': _task_routing_key,
    }
}

# Worker behaviour
worker_max_tasks_per_child = int(os.getenv('WORKER_MAX_TASKS_PER_CHILD', 100))
worker_prefetch_multiplier = int(os.getenv('WORKER_PREFETCH_MULTIPLIER', 1))
worker_max_memory_per_child = int(os.getenv('WORKER_MAX_MEMORY_PER_CHILD', 800000))  # KB => ~800MB

# Reliability
task_acks_late = True
task_reject_on_worker_lost = True
task_acks_on_failure_or_timeout = True

# Retry configuration
task_default_retry_delay = int(os.getenv('TASK_RETRY_DELAY', 300))  # seconds
task_max_retries = int(os.getenv('TASK_MAX_RETRIES', 0))

# API server settings
API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', 8000))

# Worker settings
WORKER_NAME = os.getenv('WORKER_NAME', 'mineru-worker')
WORKER_CONCURRENCY = int(os.getenv('WORKER_CONCURRENCY', 1))
WORKER_POOL = os.getenv('WORKER_POOL', '').strip()

# Paths
TEMP_DIR = os.getenv('TEMP_DIR', '/tmp/mineru_temp')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', '/tmp/mineru_output')

# Additional helper exports
MINERU_QUEUE = _task_queue
MINERU_EXCHANGE = _task_exchange
MINERU_ROUTING_KEY = _task_routing_key
