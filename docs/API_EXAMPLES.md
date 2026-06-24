# API Usage Examples

This document provides various usage examples for ThinkParse.

ThinkParse provides two API interfaces:

1. **Official MinerU API** (`/file_parse`) - Synchronous, compatible with official MinerU API format
2. **Async Queue API** (`/api/v1/tasks/*`) - Asynchronous, compatible with mineru-tianshu project format

## Table of Contents

- [Official MinerU API Examples](#official-mineru-api-examples)
- [Async Queue API Examples](#async-queue-api-examples)
- [Python Client Examples](#python-client-examples)
- [cURL Command Examples](#curl-command-examples)
- [JavaScript/TypeScript Examples](#javascripttypescript-examples)
- [Common Scenarios](#common-scenarios)

## Official MinerU API Examples

The `/file_parse` endpoint is compatible with the official MinerU API. It submits tasks and waits for completion, returning results directly.

### cURL Example

```bash
curl -X POST "http://localhost:8000/file_parse" \
  -F "files=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang_list=ch" \
  -F "parse_method=auto" \
  -F "return_md=true" \
  -F "return_images=false"
```

### Python Example

```python
import requests

# Submit and get results immediately
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

# Results are directly in the response
for pdf_name, pdf_result in result['results'].items():
    print(f"File: {pdf_name}")
    print(f"Markdown: {pdf_result.get('md_content', '')[:100]}...")
```

### Multiple Files

```bash
curl -X POST "http://localhost:8000/file_parse" \
  -F "files=@document1.pdf" \
  -F "files=@document2.pdf" \
  -F "backend=pipeline" \
  -F "lang_list=ch" \
  -F "lang_list=en"
```

## Async Queue API Examples

The async queue API provides better scalability for production deployments and batch processing.

## Python Client Examples

### Basic Usage (Async Queue API)

```python
import requests

# Submit task
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

# Query task status
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

### Async Client (Recommended)

Refer to `examples/client_example.py` for a complete async client example.

```python
import asyncio
import aiohttp
from pathlib import Path

async def submit_and_wait(file_path: str):
    async with aiohttp.ClientSession() as session:
        # Submit task
        data = aiohttp.FormData()
        data.add_field('file', open(file_path, 'rb'), filename=Path(file_path).name)
        data.add_field('backend', 'pipeline')
        data.add_field('lang', 'ch')
        
        async with session.post('http://localhost:8000/api/v1/tasks/submit', data=data) as resp:
            result = await resp.json()
            task_id = result['task_id']
        
        # Wait for completion
        while True:
            async with session.get(f'http://localhost:8000/api/v1/tasks/{task_id}') as resp:
                status = await resp.json()
                if status['task']['status'] == 'completed':
                    return status
                elif status['task']['status'] == 'failed':
                    raise Exception(status['task']['error_message'])
            await asyncio.sleep(2)

# Usage
result = asyncio.run(submit_and_wait('document.pdf'))
```

## cURL Command Examples

### Submit Task

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

Response example:
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

### Query Task Status

```bash
curl "http://localhost:8000/api/v1/tasks/abc123-def456-ghi789"
```

Response example (in progress):
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

Response example (completed):
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

### Cancel Task

```bash
curl -X DELETE "http://localhost:8000/api/v1/tasks/abc123-def456-ghi789"
```

### Query Queue Statistics

```bash
curl "http://localhost:8000/api/v1/queue/stats"
```

### Health Check

```bash
curl "http://localhost:8000/api/v1/health"
```

## JavaScript/TypeScript Examples

### Using Fetch API

```javascript
// Submit task
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

// Query task status
async function getTaskStatus(taskId) {
  const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}`);
  return await response.json();
}

// Wait for task completion
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

// Usage example
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

### Using Axios

```javascript
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api/v1'
});

// Submit task
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

// Query task status
async function getTaskStatus(taskId) {
  const response = await api.get(`/tasks/${taskId}`);
  return response.data;
}
```

## Common Scenarios

### Scenario 1: Batch Processing Multiple Files

```python
import asyncio
import aiohttp
from pathlib import Path

async def batch_process(files: list[str]):
    async with aiohttp.ClientSession() as session:
        # Submit all tasks
        tasks = []
        for file_path in files:
            data = aiohttp.FormData()
            data.add_field('file', open(file_path, 'rb'), filename=Path(file_path).name)
            data.add_field('backend', 'pipeline')
            data.add_field('lang', 'ch')
            
            async with session.post('http://localhost:8000/api/v1/tasks/submit', data=data) as resp:
                result = await resp.json()
                tasks.append(result['task_id'])
        
        # Wait for all tasks to complete
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

# Usage
files = ['doc1.pdf', 'doc2.pdf', 'doc3.pdf']
results = asyncio.run(batch_process(files))
```

### Scenario 2: Using Priority Queue

```python
# Submit high priority task
high_priority_response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('urgent.pdf', 'rb')},
    data={'backend': 'pipeline', 'priority': '10'}  # High priority
)

# Submit low priority task
low_priority_response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('normal.pdf', 'rb')},
    data={'backend': 'pipeline', 'priority': '0'}  # Low priority
)
```

### Scenario 3: Handling Different File Formats

```python
# PDF file - Use MinerU
response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('document.pdf', 'rb')},
    data={'backend': 'pipeline', 'lang': 'ch'}
)

# Office document - Automatically use MarkItDown
response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('document.docx', 'rb')},
    data={'backend': 'pipeline', 'lang': 'ch'}
)

# Image file - Use MinerU OCR
response = requests.post(
    'http://localhost:8000/api/v1/tasks/submit',
    files={'file': open('image.png', 'rb')},
    data={'backend': 'pipeline', 'method': 'ocr', 'lang': 'ch'}
)
```

### Scenario 4: Error Handling

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

### Scenario 5: Monitoring Queue Status

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

# Usage
monitor_queue()
```

## Error Handling

### Common Error Codes

- `400 Bad Request`: Invalid request parameters
- `413 Payload Too Large`: File size exceeds limit
- `422 Unprocessable Entity`: Unsupported file format or parameter validation failed
- `500 Internal Server Error`: Internal server error
- `503 Service Unavailable`: Service unavailable (e.g., Worker not running)

### Error Handling Example

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

## More Examples

For more example code, please refer to:
- `examples/client_example.py` - Complete Python async client example
- API Documentation: `http://localhost:8000/docs` (Swagger UI)
- API Documentation (ReDoc): `http://localhost:8000/redoc`
