# ThinkParse Documentation

Welcome to the ThinkParse documentation. This documentation contains all detailed usage instructions and configuration options.

## Language

- [English](README.md) (Current)
- [中文](README.zh.md)

## Table of Contents

- [Deployment Guide](DEPLOYMENT.md) - Production deployment instructions
- [Configuration Reference](CONFIGURATION.md) - All environment variables and configuration options
- [API Examples](API_EXAMPLES.md) - Code examples in multiple languages
- [Troubleshooting](TROUBLESHOOTING.md) - Common issues and solutions
- [Storage Configuration](S3_STORAGE.md) - S3 storage and cleanup configuration
- [Cleanup Container](CLEANUP_CONTAINER.md) - Cleanup service usage guide
- [S3 Lifecycle Setup](S3_LIFECYCLE_SETUP.md) - S3 lifecycle policy configuration

## Quick Navigation

### Getting Started
1. Read the Quick Start section in the main README
2. Check [API Examples](API_EXAMPLES.md) to learn how to use the API
3. Refer to [Configuration Reference](CONFIGURATION.md) for basic configuration

### Production Deployment
1. Read the [Deployment Guide](DEPLOYMENT.md)
2. Configure [S3 Storage](S3_STORAGE.md) (recommended)
3. Set up the [Cleanup Service](CLEANUP_CONTAINER.md)

### Troubleshooting
1. Check [Troubleshooting](TROUBLESHOOTING.md)
2. Check log output
3. View GitHub Issues

## Architecture Overview

### Components

- **API Service** (`api/app.py`): Lightweight FastAPI service for task submission and status queries
- **Worker Service** (`worker/tasks.py`): Celery Worker that executes document parsing tasks
- **Redis**: Celery message broker and result backend
- **Storage**: Supports local filesystem and S3-compatible storage

### Workflow

1. Client submits a document parsing task through the API
2. API sends the task to the Celery queue
3. Worker retrieves the task from the queue and executes parsing
4. Parsing results are stored in the configured storage backend
5. Client queries task status and results through the API

## More Resources

- [GitHub Repository](https://github.com/wzdavid/ThinkParse)
- [Issue Tracker](https://github.com/wzdavid/ThinkParse/issues)
- [Contributing Guide](../CONTRIBUTING.md)
