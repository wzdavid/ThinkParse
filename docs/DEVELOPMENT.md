# Development Environment Setup Guide

This document describes how to set up the ThinkParse project in a local development environment.

## Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- Redis (for Celery task queue)
- (Optional) Docker and Docker Compose

## Quick Start

### Method 1: Using Automated Script (Recommended)

```bash
# 1. Run setup script
chmod +x setup_venv.sh
./setup_venv.sh

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Configure environment variables
cp .env.example .env
# Edit .env file with necessary configuration

# 4. Start Redis (if not running)
docker run -d -p 6379:6379 redis:latest
# Or use local Redis: redis-server

# 5. Start services
# Terminal 1: API service
cd api && python app.py

# Terminal 2: Worker service
cd worker && python tasks.py
```

### Method 2: Manual Setup

#### 1. Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
# macOS/Linux:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate
```

#### 2. Upgrade pip

```bash
pip install --upgrade pip setuptools wheel
```

#### 3. Install Dependencies

The project contains multiple services, each with its own dependency file:

```bash
# Install API service dependencies (required)
pip install -r api/requirements.txt

# Install Worker service dependencies (required)
pip install -r worker/requirements.txt

# Install Cleanup service dependencies (optional)
pip install -r cleanup/requirements.txt
```

#### 4. Configure Environment Variables

```bash
# Copy environment variable template
cp .env.example .env

# Edit .env file with necessary configuration
# At minimum, configure:
# - REDIS_URL: Redis connection address
# - TEMP_DIR: Temporary file directory
# - OUTPUT_DIR: Output file directory
```

#### 5. Start Redis

Celery requires Redis as a message broker. Choose one of the following methods:

**Using Docker (Recommended):**
```bash
docker run -d -p 6379:6379 --name redis redis:latest
```

**Using Local Redis:**
```bash
# macOS (using Homebrew)
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# Or run directly
redis-server
```

#### 6. Start Services

**Start API Service:**
```bash
cd api
python app.py
```

API service runs on `http://localhost:8000` by default

**Start Worker Service (new terminal):**
```bash
# Ensure virtual environment is activated
source .venv/bin/activate

cd worker
python tasks.py
```

## Project Structure

```
ThinkParse/
├── api/                    # API service
│   ├── app.py             # FastAPI application
│   └── requirements.txt   # API dependencies
├── worker/                 # Worker service
│   ├── tasks.py           # Celery task definitions
│   └── requirements.txt   # Worker dependencies
├── cleanup/                # Cleanup service
│   ├── cleanup_scheduler.py
│   └── requirements.txt
├── shared/                 # Shared modules
│   ├── celeryconfig.py    # Celery configuration
│   └── storage.py         # Storage abstraction layer
├── .env.example           # Environment variable template
├── setup_venv.sh         # Virtual environment setup script
└── docs/
    └── DEVELOPMENT.md    # This document
```

## Development Workflow

### 1. Activate Virtual Environment

Activate the virtual environment before starting development:

```bash
source .venv/bin/activate
```

### 2. Install New Dependencies

If you add new dependency packages:

```bash
# Install to corresponding service's requirements.txt
pip install <package-name>

# Update requirements.txt
pip freeze > api/requirements.txt  # or worker/requirements.txt
```

### 3. Run Tests

```bash
# Test API service
curl http://localhost:8000/api/v1/health

# Submit test task
curl -X POST "http://localhost:8000/api/v1/tasks/submit" \
  -F "file=@test.pdf" \
  -F "backend=pipeline"
```

### 4. Code Checking

```bash
# Check Python syntax
python -m py_compile api/app.py worker/tasks.py

# Use linter (if installed)
# pylint api/app.py
# flake8 api/app.py
```

## Common Issues

### 1. Virtual Environment Activation Failed

**Issue:** `source .venv/bin/activate` reports error

**Solution:**
- Ensure using correct shell (bash/zsh)
- Windows use: `.venv\Scripts\activate`
- Check if virtual environment was created successfully: `ls .venv/bin/`

### 2. Dependency Installation Failed

**Issue:** `pip install` reports error

**Solution:**
- Upgrade pip: `pip install --upgrade pip`
- Use mirror source (if needed):
  ```bash
  pip install -r api/requirements.txt -i https://pypi.org/simple
  ```
- Check Python version: `python3 --version` (requires 3.10+)

### 3. Redis Connection Failed

**Issue:** `Connection refused` or `Cannot connect to Redis`

**Solution:**
- Check if Redis is running: `redis-cli ping` (should return `PONG`)
- Check Redis URL configuration: `REDIS_URL` in `.env` file
- Check firewall settings

### 4. MinerU Model Download Failed

**Issue:** Model download fails when Worker starts

**Solution:**
- Check network connection
- Set proxy (if needed):
  ```bash
  export HTTP_PROXY=http://proxy.example.com:8080
  export HTTPS_PROXY=http://proxy.example.com:8080
  ```
- Use mirror source (if MinerU supports)

### 5. pypdfium2 Installation Failed

**Issue:** Pagination feature requires pypdfium2, but installation failed

**Solution:**
- Install system dependencies (Ubuntu/Debian):
  ```bash
  sudo apt-get install build-essential
  ```
- macOS may need Xcode Command Line Tools:
  ```bash
  xcode-select --install
  ```
- If it still fails, pagination feature will be automatically disabled, other features are not affected

## Recommended Development Tools

### IDE Configuration

**VS Code:**
- Python extension
- Python interpreter: `.venv/bin/python`

**PyCharm:**
- Project interpreter: Select `.venv/bin/python`
- Enable code inspection

### Useful Commands

```bash
# View installed packages
pip list

# View virtual environment info
which python  # Should show .venv/bin/python

# Deactivate virtual environment
deactivate

# Recreate virtual environment
rm -rf .venv
./setup_venv.sh
```

## Next Steps

- View [API Documentation](http://localhost:8000/docs) (after starting API)
- Read [Configuration Guide](CONFIGURATION.md)
- View [API Examples](API_EXAMPLES.md)
- Read [Troubleshooting Guide](TROUBLESHOOTING.md)

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines.
