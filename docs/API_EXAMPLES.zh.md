# API 使用示例

本文档提供了 ThinkParse 的各种使用示例。

ThinkParse 提供了两种 API 接口：

1. **MinerU 官方 API** (`/file_parse`) - 同步方式，兼容 MinerU 官方 API 格式
2. **异步队列 API** (`/api/v1/tasks/*`) - 异步方式，兼容 mineru-tianshu 项目格式

## 目录

- [MinerU 官方 API 示例](#mineru-官方-api-示例)
- [异步队列 API 示例](#异步队列-api-示例)
- [Python 客户端示例](#python-客户端示例)
- [cURL 命令示例](#curl-命令示例)
- [JavaScript/TypeScript 示例](#javascripttypescript-示例)
- [常见场景](#常见场景)

## MinerU 官方 API 示例

`/file_parse` 端点兼容 MinerU 官方 API。它提交任务并等待完成，直接返回结果。

### cURL 示例

```bash
curl -X POST "http://localhost:8000/file_parse" \
  -F "files=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang_list=ch" \
  -F "parse_method=auto" \
  -F "return_md=true" \
  -F "return_images=false"
```

### Python 示例

```python
import requests

# 提交并立即获取结果
files = {'files': open('document.pdf', 'rb')}
data = {
    'backend': 'pipeline',
    'lang_list': 'ch',
    'parse_method': 'auto',
    'return_md': 'true',
    'return_middle_json': 'false',
    'return_images': 'false'
}

response = requests.post('http://localhost:8000/file_parse', files=files, data=data)
result = response.json()

# 结果直接在响应中
for pdf_name, pdf_result in result['results'].items():
    print(f"文件: {pdf_name}")
    print(f"Markdown: {pdf_result.get('md_content', '')[:100]}...")
```

### 多文件处理

```bash
curl -X POST "http://localhost:8000/file_parse" \
  -F "files=@document1.pdf" \
  -F "files=@document2.pdf" \
  -F "backend=pipeline" \
  -F "lang_list=ch" \
  -F "lang_list=en"
```

## 异步队列 API 示例

异步队列 API 为生产环境部署和批量处理提供了更好的可扩展性。

## Python 客户端示例

### 基本使用（异步队列 API）

```python
import requests

# 提交任务
url = "http://localhost:8000/api/v1/tasks/submit"
files = {'file': open('document.pdf', 'rb')}
data = {
    'backend': 'pipeline',
    'lang': 'ch',
    'method': 'auto',
    'formula_enable': 'true',
    'table_enable': 'true',
    'priority': '0'
}

response = requests.post(url, files=files, data=data)
result = response.json()
task_id = result['task_id']
print(f"Task submitted: {task_id}")

# 查询任务状态
status_url = f"http://localhost:8000/api/v1/tasks/{task_id}"
while True:
    status_response = requests.get(status_url)
    status = status_response.json()
    
    if status['task']['status'] == 'completed':
        print("Task completed!")
        print(f"Markdown content: {status.get('markdown_content', '')[:100]}...")
        break
    elif status['task']['status'] == 'failed':
        print(f"Task failed: {status['task']['error_message']}")
        break
    
    import time
    time.sleep(2)
```

### 异步客户端（推荐）

参考 `examples/client_example.py` 获取完整的异步客户端示例。

```python
import asyncio
import aiohttp
from pathlib import Path

async def submit_and_wait(file_path: str):
    async with aiohttp.ClientSession() as session:
        # 提交任务
        data = aiohttp.FormData()
        data.add_field('file', open(file_path, 'rb'), filename=Path(file_path).name)
        data.add_field('backend', 'pipeline')
        data.add_field('lang', 'ch')
        
        async with session.post('http://localhost:8000/api/v1/tasks/submit', data=data) as resp:
            result = await resp.json()
            task_id = result['task_id']
        
        # 等待完成
        while True:
            async with session.get(f'http://localhost:8000/api/v1/tasks/{task_id}') as resp:
                status = await resp.json()
                if status['task']['status'] == 'completed':
                    return status
                elif status['task']['status'] == 'failed':
                    raise Exception(status['task']['error_message'])
            await asyncio.sleep(2)

# 使用
result = asyncio.run(submit_and_wait('document.pdf'))
```

## cURL 命令示例

### 提交任务

```bash
curl -X POST "http://localhost:8000/api/v1/tasks/submit" \
  -F "file=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang=ch" \
  -F "method=auto" \
  -F "formula_enable=true" \
  -F "table_enable=true" \
  -F "priority=0"
```

响应示例：
```json
{
  "success": true,
  "task_id": "abc123-def456-ghi789",
  "status": "pending",
  "message": "Task submitted successfully",
  "file_name": "document.pdf",
  "created_at": "2024-01-01T12:00:00",
  "backend": "pipeline",
  "priority": 0
}
```

### 查询任务状态

```bash
curl "http://localhost:8000/api/v1/tasks/abc123-def456-ghi789"
```

响应示例（进行中）：
```json
{
  "success": true,
  "task": {
    "task_id": "abc123-def456-ghi789",
    "status": "processing",
    "file_name": "document.pdf",
    "backend": "pipeline"
  },
  "timestamp": "2024-01-01T12:00:30"
}
```

响应示例（已完成）：
```json
{
  "success": true,
  "task": {
    "task_id": "abc123-def456-ghi789",
    "status": "completed",
    "file_name": "document.pdf",
    "backend": "pipeline",
    "completed_at": "2024-01-01T12:01:00"
  },
  "markdown_content": "# Document Title\n\nContent here...",
  "images": [],
  "timestamp": "2024-01-01T12:01:00"
}
```

### 取消任务

```bash
curl -X DELETE "http://localhost:8000/api/v1/tasks/abc123-def456-ghi789"
```

### 查询队列统计

```bash
curl "http://localhost:8000/api/v1/queue/stats"
```

### 健康检查

```bash
curl "http://localhost:8000/api/v1/health"
```

## JavaScript/TypeScript 示例

### 使用 Fetch API

```javascript
// 提交任务
async function submitTask(file, options = {}) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('backend', options.backend || 'pipeline');
  formData.append('lang', options.lang || 'ch');
  formData.append('method', options.method || 'auto');
  formData.append('formula_enable', options.formula_enable !== false);
  formData.append('table_enable', options.table_enable !== false);
  formData.append('priority', options.priority || 0);

  const response = await fetch('http://localhost:8000/api/v1/tasks/submit', {
    method: 'POST',
    body: formData
  });

  return await response.json();
}

// 查询任务状态
async function getTaskStatus(taskId) {
  const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}`);
  return await response.json();
}

// 等待任务完成
async function waitForTask(taskId, timeout = 600000) {
  const startTime = Date.now();
  
  while (Date.now() - startTime < timeout) {
    const status = await getTaskStatus(taskId);
    
    if (status.task.status === 'completed') {
      return status;
    } else if (status.task.status === 'failed') {
      throw new Error(status.task.error_message);
    }
    
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  
  throw new Error('Task timeout');
}

// 使用示例
const fileInput = document.querySelector('input[type="file"]');
fileInput.addEventListener('change', async (e) => {
  const file = e.target.files[0];
  const result = await submitTask(file);
  console.log('Task submitted:', result.task_id);
  
  try {
    const finalStatus = await waitForTask(result.task_id);
    console.log('Task completed:', finalStatus.markdown_content);
  } catch (error) {
    console.error('Task failed:', error);
  }
});
```

### 使用 Axios

```javascript
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api/v1'
});

// 提交任务
async function submitTask(file, options = {}) {
  const formData = new FormData();
  formData.append('file', file);
  Object.entries(options).forEach(([key, value]) => {
    formData.append(key, value);
  });

  const response = await api.post('/tasks/submit', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  });

  return response.data;
}

// 查询任务状态
async function getTaskStatus(taskId) {
  const response = await api.get(`/tasks/${taskId}`);
  return response.data;
}
```

## 常见场景

### 场景 1: 批量处理多个文件

```python
import asyncio
import aiohttp
from pathlib import Path

async def batch_process(files: list[str]):
    async with aiohttp.ClientSession() as session:
        # 提交所有任务
        tasks = []
        for file_path in files:
            data = aiohttp.FormData()
            data.add_field('file', open(file_path, 'rb'), filename=Path(file_path).name)
            data.add_field('backend', 'pipeline')
            data.add_field('lang', 'ch')
            
            async with session.post('http://localhost:8000/api/v1/tasks/submit', data=data) as resp:
                result = await resp.json()
                tasks.append(result['task_id'])
        
        # 等待所有任务完成
        results = []
        for task_id in tasks:
            while True:
                async with session.get(f'http://localhost:8000/api/v1/tasks/{task_id}') as resp:
                    status = await resp.json()
                    if status['task']['status'] == 'completed':
                        results.append(status)
                        break
                    elif status['task']['status'] == 'failed':
                        results.append({'task_id': task_id, 'error': status['task']['error_message']})
                        break
                await asyncio.sleep(2)
        
        return results

# 使用
files = ['doc1.pdf', 'doc2.pdf', 'doc3.pdf']
results = asyncio.run(batch_process(files))
```

### 场景 2: 使用优先级队列

```python
# 提交高优先级任务
high_priority_response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('urgent.pdf', 'rb')},
    data={'backend': 'pipeline', 'priority': '10'}  # 高优先级
)

# 提交低优先级任务
low_priority_response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('normal.pdf', 'rb')},
    data={'backend': 'pipeline', 'priority': '0'}  # 低优先级
)
```

### 场景 3: 处理不同文件格式

```python
# PDF 文件 - 使用 MinerU
response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('document.pdf', 'rb')},
    data={'backend': 'pipeline', 'lang': 'ch'}
)

# Office 文档 - 自动使用 MarkItDown
response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('document.docx', 'rb')},
    data={'backend': 'pipeline', 'lang': 'ch'}
)

# 图片文件 - 使用 MinerU OCR
response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('image.png', 'rb')},
    data={'backend': 'pipeline', 'method': 'ocr', 'lang': 'ch'}
)
```

### 场景 4: 错误处理

```python
import requests
from requests.exceptions import RequestException

def submit_task_safe(file_path: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            with open(file_path, 'rb') as f:
                response = requests.post(
                    'http://localhost:8000/api/v1/tasks/submit',
                    files={'file': f},
                    data={'backend': 'pipeline', 'lang': 'ch'},
                    timeout=30
                )
                response.raise_for_status()
                return response.json()
        except RequestException as e:
            if attempt == max_retries - 1:
                raise
            print(f"Attempt {attempt + 1} failed: {e}, retrying...")
            import time
            time.sleep(2 ** attempt)  # Exponential backoff
    return None
```

### 场景 5: 监控队列状态

```python
import requests
import time

def monitor_queue(interval: int = 5):
    while True:
        response = requests.get('http://localhost:8000/api/v1/queue/stats')
        stats = response.json()
        
        print(f"Pending: {stats['stats']['pending']}")
        print(f"Processing: {stats['stats']['processing']}")
        print(f"Active Workers: {stats['workers']['active_workers']}")
        print("-" * 40)
        
        time.sleep(interval)

# 使用
monitor_queue()
```

## 错误处理

### 常见错误码

- `400 Bad Request`: 请求参数错误
- `413 Payload Too Large`: 文件大小超过限制
- `422 Unprocessable Entity`: 文件格式不支持或参数验证失败
- `500 Internal Server Error`: 服务器内部错误
- `503 Service Unavailable`: 服务不可用（如 Worker 未运行）

### 错误处理示例

```python
import requests

try:
    response = requests.post(
        'http://localhost:8000/api/v1/tasks/submit',
        files={'file': open('document.pdf', 'rb')},
        data={'backend': 'pipeline'}
    )
    response.raise_for_status()
    result = response.json()
except requests.exceptions.HTTPError as e:
    if e.response.status_code == 413:
        print("File too large. Maximum size: 100MB")
    elif e.response.status_code == 422:
        print("Invalid file format or parameters")
        print(e.response.json())
    else:
        print(f"HTTP Error: {e}")
except requests.exceptions.RequestException as e:
    print(f"Request failed: {e}")
```

## 更多示例

更多示例代码请参考：
- `examples/client_example.py` - Python 异步客户端完整示例
- API 文档: `http://localhost:8000/docs` (Swagger UI)
- API 文档 (ReDoc): `http://localhost:8000/redoc`
