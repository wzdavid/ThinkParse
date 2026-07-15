# Cleanup Container Usage Guide

## Overview

The `mineru-cleanup` container is an independent cleanup service for regularly cleaning MinerU's temporary and output files.

## Features

- **Automatic Storage Type Detection**: Automatically adjusts cleanup strategy based on `MINERU_STORAGE_TYPE` environment variable
- **Scheduled Execution**: Configurable cleanup interval, default is every 6 hours
- **Flexible Configuration**: Supports preview mode, extra retention time, and other configurations

## Storage Mode Adaptation

### Local Storage Mode (`MINERU_STORAGE_TYPE=local`)

Cleanup service will clean:
- ✅ **Temporary Files**: Expired files in `TEMP_DIR` (default `TEMP_MAX_AGE_HOURS=6`)
- ✅ **Output Files**: Expired task directories in `OUTPUT_DIR` (based on `RESULT_EXPIRES` configuration)

### S3 Storage Mode (`MINERU_STORAGE_TYPE=s3`)

Cleanup service will clean:
- ❌ **Temporary Files**: Handled by S3 lifecycle policy automatically, no application-layer cleanup needed
- ✅ **Output Files**: Expired task directories in `mineru-output` bucket (based on `RESULT_EXPIRES` configuration)

> 💡 **Recommended Configuration**: When using S3 storage, configure an S3 lifecycle policy for the temp bucket. Align with `TEMP_MAX_AGE_HOURS` when the provider supports sub-day rules; many providers only support day-level expiration (often 1 day). The cleanup container only handles output file cleanup.

## Startup Methods

### Using Docker Compose

```bash
# Start cleanup service
cd docker && docker compose --profile mineru-cleanup up -d mineru-cleanup

# View logs
cd docker && docker compose logs -f mineru-cleanup
```

### Environment Variable Configuration

Configure in `.env` file:

```bash
# Storage type (affects cleanup strategy)
MINERU_STORAGE_TYPE=s3  # or local

# Cleanup service configuration
CLEANUP_INTERVAL_HOURS=6     # Cleanup interval (hours)
CLEANUP_EXTRA_HOURS=2        # Extra retention time for outputs (hours)
TEMP_MAX_AGE_HOURS=6         # Local TEMP_DIR orphan max age (keep > TASK_TIME_LIMIT)

# S3 storage configuration (if using S3 storage)
MINERU_S3_ENDPOINT=http://minio:9000
# NOTE: These are example values. In production, use strong, unique credentials.
MINERU_S3_ACCESS_KEY=minioadmin  # Replace with your actual access key
MINERU_S3_SECRET_KEY=minioadmin  # Replace with your actual secret key
MINERU_S3_BUCKET_TEMP=mineru-temp
MINERU_S3_BUCKET_OUTPUT=mineru-output
```

## Manual Cleanup Execution

### Execute in Container

```bash
# Execute single cleanup (automatically detects storage type)
cd docker && docker compose exec mineru-cleanup python cleanup/cleanup_scheduler.py --run-once

# Preview mode (view files to be deleted)
cd docker && docker compose exec mineru-cleanup python cleanup/cleanup_outputs.py --dry-run

# Only cleanup output files (recommended for S3 storage)
cd docker && docker compose exec mineru-cleanup python cleanup/cleanup_outputs.py --output-only
```

### Local Execution

```bash
# Execute cleanup
python cleanup/cleanup_outputs.py

# Preview mode
python cleanup/cleanup_outputs.py --dry-run

# Only cleanup output files
python cleanup/cleanup_outputs.py --output-only
```

## Cleanup Strategy

### Output File Cleanup

- **Cleanup Basis**: Based on `RESULT_EXPIRES` environment variable (default 86400 seconds/1 day)
- **Cleanup Logic**: Delete task directories modified earlier than `RESULT_EXPIRES + extra_hours`
- **Applicable Scenarios**: Both local storage and S3 storage need this

### Temporary File Cleanup

- **Local Storage**: Clean temporary files in `TEMP_DIR` older than `TEMP_MAX_AGE_HOURS` (default 6 hours). Successful tasks delete their upload temps immediately; this sweep is mainly for orphans.
- **S3 Storage**: Handled by S3 lifecycle policy, cleanup container does not handle
- **Safety**: Default 6h stays above `TASK_TIME_LIMIT` (2h) so in-flight parses are not deleted mid-task

## Logs and Monitoring

### View Cleanup Logs

```bash
# Real-time log viewing
cd docker && docker compose logs -f mineru-cleanup

# View last 100 lines of logs
cd docker && docker compose logs --tail=100 mineru-cleanup
```

### Log Content Examples

**Local Storage Mode**:
```
Executing scheduled cleanup task - 2024-01-15 02:00:00
Detected local storage mode, cleaning temporary and output files
Cleaning temporary directory
Cleaning output directory (local storage)
Cleanup completed: Deleted 5 directories, freed 1.2 GB
```

**S3 Storage Mode**:
```
Executing scheduled cleanup task - 2024-01-15 02:00:00
Detected S3 storage mode, only cleaning output files (temporary files handled by S3 lifecycle policy)
Cleaning output directory (S3 storage)
Cleanup completed: Deleted 3 task directories, freed 800 MB
```

## Troubleshooting

### Cleanup Service Cannot Start

Check:
- Are environment variables configured correctly
- Is network connection normal (S3 storage requires)
- Is storage service available

### S3 Storage Cleanup Failed

Check:
- Is S3 service running
- Are access keys correct
- Is network connection normal
- Do buckets exist

### Incomplete Cleanup

Check:
- Is `RESULT_EXPIRES` configuration reasonable
- Is `CLEANUP_EXTRA_HOURS` set too large
- Is cleanup service running normally

## Best Practices

1. **When Using S3 Storage**:
   - Configure S3 lifecycle policy to handle temporary files (align with `TEMP_MAX_AGE_HOURS` when possible; day-level rules often use 1 day)
   - Cleanup container only handles output file cleanup
   - Regularly check cleanup logs to ensure cleanup executes normally

2. **When Using Local Storage**:
   - Cleanup container handles both temporary and output file cleanup
   - Ensure sufficient disk space
   - Regularly check cleanup logs

3. **Monitoring Recommendations**:
   - Set up health checks for cleanup service
   - Monitor cleanup logs to detect anomalies in time
   - Regularly check storage usage

## Related Documentation

- [S3 Storage Support](./S3_STORAGE.md)
- [S3 Lifecycle Policy Configuration](./S3_LIFECYCLE_SETUP.md)
