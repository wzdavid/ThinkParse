# ThinkParse 完整文档

欢迎使用 ThinkParse 完整文档。本文档包含所有详细的使用说明和配置选项。

## 语言

- [English](README.md)
- [中文](README.zh.md) (当前)

## 目录

- [部署指南](DEPLOYMENT.zh.md) - 生产环境部署详细说明
- [大规模多机部署](PRODUCTION_MULTI_NODE.zh.md) - 多服务器 + 多 GPU Worker
- [单容器部署（天河 / HPC）](DEPLOYMENT_ALLINONE.zh.md) - Redis+API+Worker+Cleanup 一个容器
- [配置参考](CONFIGURATION.zh.md) - 所有环境变量和配置选项
- [API 示例](API_EXAMPLES.zh.md) - 多语言代码示例
- [故障排除](TROUBLESHOOTING.zh.md) - 常见问题和解决方案
- [存储配置](S3_STORAGE.zh.md) - S3 存储和清理配置
- [清理容器](CLEANUP_CONTAINER.zh.md) - 清理服务使用说明
- [S3 生命周期](S3_LIFECYCLE_SETUP.zh.md) - S3 生命周期策略配置

## 快速导航

### 新手入门
1. 阅读主 README 的快速开始部分
2. 查看 [API 示例](API_EXAMPLES.zh.md) 了解如何使用 API
3. 参考 [配置参考](CONFIGURATION.zh.md) 进行基本配置

### 生产部署
1. 阅读 [部署指南](DEPLOYMENT.zh.md)
2. 多机多 Worker：[大规模生产部署](PRODUCTION_MULTI_NODE.zh.md)
3. 单容器调度（天河）：[单容器部署](DEPLOYMENT_ALLINONE.zh.md)
4. 配置 [S3 存储](S3_STORAGE.zh.md)（推荐）
5. 设置 [清理服务](CLEANUP_CONTAINER.zh.md)

### 遇到问题
1. 查看 [故障排除](TROUBLESHOOTING.zh.md)
2. 检查日志输出
3. 查看 GitHub Issues

## 架构说明

### 组件说明

- **API Service** (`api/app.py`): 轻量级 FastAPI 服务，负责任务提交和状态查询
- **Worker Service** (`worker/tasks.py`): Celery Worker，执行文档解析任务
- **Redis**: Celery 消息代理和结果后端
- **Storage**: 支持本地文件系统和 S3 兼容存储

### 工作流程

1. 客户端通过 API 提交文档解析任务
2. API 将任务发送到 Celery 队列
3. Worker 从队列获取任务并执行解析
4. 解析结果存储在配置的存储后端
5. 客户端通过 API 查询任务状态和结果

## 更多资源

- [GitHub Repository](https://github.com/wzdavid/ThinkParse)
- [Issue Tracker](https://github.com/wzdavid/ThinkParse/issues)
- [Contributing Guide](../CONTRIBUTING.md)
