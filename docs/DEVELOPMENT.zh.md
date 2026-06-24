# 开发环境设置指南

本文档介绍如何在本地开发环境中设置 ThinkParse 项目。

## 前置要求

- Python 3.10 或更高版本
- pip（Python 包管理器）
- Redis（用于 Celery 任务队列）
- （可选）Docker 和 Docker Compose

## 快速开始

### 方法一：使用自动化脚本（推荐）

```bash
# 1. 运行设置脚本
chmod +x setup_venv.sh
./setup_venv.sh

# 2. 激活虚拟环境
source .venv/bin/activate

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，设置必要的配置

# 4. 启动 Redis（如果未运行）
docker run -d -p 6379:6379 redis:latest
# 或使用本地 Redis: redis-server

# 5. 启动服务
# 终端 1: API 服务
cd api && python app.py

# 终端 2: Worker 服务
cd worker && python tasks.py
```

### 方法二：手动设置

#### 1. 创建虚拟环境

```bash
# 创建虚拟环境
python3 -m venv .venv

# 激活虚拟环境
# macOS/Linux:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate
```

#### 2. 升级 pip

```bash
pip install --upgrade pip setuptools wheel
```

#### 3. 安装依赖

项目包含多个服务，每个服务有独立的依赖文件：

```bash
# 安装 API 服务依赖（必需）
pip install -r api/requirements.txt

# 安装 Worker 服务依赖（必需）
pip install -r worker/requirements.txt

# 安装 Cleanup 服务依赖（可选）
pip install -r cleanup/requirements.txt
```

#### 4. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，设置必要的配置
# 至少需要配置：
# - REDIS_URL: Redis 连接地址
# - TEMP_DIR: 临时文件目录
# - OUTPUT_DIR: 输出文件目录
```

#### 5. 启动 Redis

Celery 需要 Redis 作为消息代理。可以选择以下方式之一：

**使用 Docker（推荐）：**
```bash
docker run -d -p 6379:6379 --name redis redis:latest
```

**使用本地 Redis：**
```bash
# macOS (使用 Homebrew)
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# 或直接运行
redis-server
```

#### 6. 启动服务

**启动 API 服务：**
```bash
cd api
python app.py
```

API 服务默认运行在 `http://localhost:8000`

**启动 Worker 服务（新终端）：**
```bash
# 确保虚拟环境已激活
source .venv/bin/activate

cd worker
python tasks.py
```

## 项目结构

```
ThinkParse/
├── api/                    # API 服务
│   ├── app.py             # FastAPI 应用
│   └── requirements.txt   # API 依赖
├── worker/                 # Worker 服务
│   ├── tasks.py           # Celery 任务定义
│   └── requirements.txt   # Worker 依赖
├── cleanup/                # 清理服务
│   ├── cleanup_scheduler.py
│   └── requirements.txt
├── shared/                 # 共享模块
│   ├── celeryconfig.py    # Celery 配置
│   └── storage.py         # 存储抽象层
├── .env.example           # 环境变量模板
├── setup_venv.sh         # 虚拟环境设置脚本
└── docs/
    └── DEVELOPMENT.zh.md # 本文档
```

## 开发工作流

### 1. 激活虚拟环境

每次开始开发前，激活虚拟环境：

```bash
source .venv/bin/activate
```

### 2. 安装新依赖

如果添加了新的依赖包：

```bash
# 安装到对应服务的 requirements.txt
pip install <package-name>

# 更新 requirements.txt
pip freeze > api/requirements.txt  # 或 worker/requirements.txt
```

### 3. 运行测试

```bash
# 测试 API 服务
curl http://localhost:8000/api/v1/health

# 提交测试任务
curl -X POST "http://localhost:8000/api/v1/tasks/submit" \
  -F "file=@test.pdf" \
  -F "backend=pipeline"
```

### 4. 代码检查

```bash
# 检查 Python 语法
python -m py_compile api/app.py worker/tasks.py

# 使用 linter（如果已安装）
# pylint api/app.py
# flake8 api/app.py
```

## 常见问题

### 1. 虚拟环境激活失败

**问题：** `source .venv/bin/activate` 报错

**解决：**
- 确保使用正确的 shell（bash/zsh）
- Windows 使用：`.venv\Scripts\activate`
- 检查虚拟环境是否创建成功：`ls .venv/bin/`

### 2. 依赖安装失败

**问题：** `pip install` 报错

**解决：**
- 升级 pip：`pip install --upgrade pip`
- 使用国内镜像源：
  ```bash
  pip install -r api/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```
- 检查 Python 版本：`python3 --version`（需要 3.10+）

### 3. Redis 连接失败

**问题：** `Connection refused` 或 `Cannot connect to Redis`

**解决：**
- 检查 Redis 是否运行：`redis-cli ping`（应返回 `PONG`）
- 检查 Redis URL 配置：`.env` 文件中的 `REDIS_URL`
- 检查防火墙设置

### 4. MinerU 模型下载失败

**问题：** Worker 启动时模型下载失败

**解决：**
- 检查网络连接
- 设置代理（如需要）：
  ```bash
  export HTTP_PROXY=http://proxy.example.com:8080
  export HTTPS_PROXY=http://proxy.example.com:8080
  ```
- 使用国内镜像（如果 MinerU 支持）

### 5. pypdfium2 安装失败

**问题：** 分页功能需要 pypdfium2，但安装失败

**解决：**
- 安装系统依赖（Ubuntu/Debian）：
  ```bash
  sudo apt-get install build-essential
  ```
- macOS 可能需要 Xcode Command Line Tools：
  ```bash
  xcode-select --install
  ```
- 如果仍然失败，分页功能会自动禁用，不影响其他功能

## 开发工具推荐

### IDE 配置

**VS Code:**
- Python 扩展
- Python 解释器选择：`.venv/bin/python`

**PyCharm:**
- 项目解释器：选择 `.venv/bin/python`
- 启用代码检查

### 有用的命令

```bash
# 查看已安装的包
pip list

# 查看虚拟环境信息
which python  # 应显示 .venv/bin/python

# 退出虚拟环境
deactivate

# 重新创建虚拟环境
rm -rf .venv
./setup_venv.sh
```

## 下一步

- 查看 [API 文档](http://localhost:8000/docs)（启动 API 后）
- 阅读 [配置指南](CONFIGURATION.zh.md)
- 查看 [API 示例](API_EXAMPLES.zh.md)
- 阅读 [故障排除指南](TROUBLESHOOTING.zh.md)

## 贡献

欢迎贡献代码！请查看 [../CONTRIBUTING.md](../CONTRIBUTING.md) 了解贡献指南。
