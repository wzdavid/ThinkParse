# -*- coding: utf-8 -*-
"""
ThinkParse API Server - Fully Decoupled Architecture
Handles task submission and status queries only.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import sys
import json
import re
import tempfile
import zipfile
import glob
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from starlette.background import BackgroundTask
from celery import Celery
from celery.result import AsyncResult
from loguru import logger

# Ensure project root on path for shared configuration
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from shared import celeryconfig
from shared.storage import get_storage

# Create FastAPI application
app = FastAPI(
    title="ThinkParse API Server",
    description="Document parsing service — handles task submission and querying only",
    version="1.1.0"
)

# Enable CORS
# Get allowed origins from environment variable
cors_origins_str = os.getenv('CORS_ALLOWED_ORIGINS', '')
if cors_origins_str:
    cors_origins = [origin.strip() for origin in cors_origins_str.split(',') if origin.strip()]
else:
    # Default: allow all in development, empty in production
    if os.getenv('ENVIRONMENT', 'development').lower() == 'development':
        cors_origins = ['http://localhost:3000', 'http://localhost:8000', 'http://127.0.0.1:8000']
    else:
        cors_origins = []  # Production must explicitly configure CORS

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],  # Fallback to * if empty (backward compatibility)
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# Celery application (no task modules imported)
celery_app = Celery('mineru_api')
celery_app.config_from_object(celeryconfig)

# Ensure directories exist
os.makedirs(celeryconfig.TEMP_DIR, exist_ok=True)
Path(celeryconfig.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    """
    Format zip file filename
    Remove path traversal characters, keep Unicode letters, numbers, ._-
    Prohibit hidden files
    """
    sanitized = re.sub(r'[/\\\.]{2,}|[/\\]', '', filename)
    sanitized = re.sub(r'[^\w.-]', '_', sanitized, flags=re.UNICODE)
    if sanitized.startswith('.'):
        sanitized = '_' + sanitized[1:]
    return sanitized or 'unnamed'


def cleanup_file(file_path: str) -> None:
    """Clean up temporary zip file"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.warning(f"fail clean file {file_path}: {e}")


def encode_image(image_path: str) -> str:
    """Encode image using base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def get_infer_result(file_suffix_identifier: str, pdf_name: str, parse_dir: str) -> Optional[str]:
    """Read inference result from result file"""
    result_file_path = os.path.join(parse_dir, f"{pdf_name}{file_suffix_identifier}")
    if os.path.exists(result_file_path):
        with open(result_file_path, "r", encoding="utf-8") as fp:
            return fp.read()
    return None


@app.get("/")
async def root():
    """Root endpoint with service metadata."""
    return {
        "service": "ThinkParse API Server",
        "version": "1.1.0",
        "description": "Document parsing service",
        "endpoints": {
            "submit": "/api/v1/tasks/submit",
            "status": "/api/v1/tasks/{task_id}",
            "cancel": "/api/v1/tasks/{task_id}",
            "stats": "/api/v1/queue/stats",
            "tasks": "/api/v1/queue/tasks",
            "health": "/api/v1/health",
            "docs": "/docs"
        }
    }


@app.post("/api/v1/tasks/submit")
async def submit_task(
    file: UploadFile = File(..., description="Document file: PDF/image (MinerU parsing) or Office/HTML/text (MarkItDown parsing)"),
    backend: str = Form('pipeline', description="Processing backend: pipeline/vlm-transformers/vlm-vllm-engine"),
    lang: str = Form('ch', description="Language: ch/en/korean/japan etc"),
    method: str = Form('auto', description="Parsing method: auto/txt/ocr"),
    formula_enable: bool = Form(True, description="Enable formula recognition"),
    table_enable: bool = Form(True, description="Enable table recognition"),
    priority: int = Form(0, description="Priority, higher number means higher priority"),
    enable_pagination: Optional[bool] = Form(None, description="Enable pagination for large PDFs (auto-detect if None)"),
):
    """Submit MinerU parsing task with automatic pagination for large PDFs."""
    try:
        storage = get_storage()
        
        # File size limit (default: 100MB)
        max_file_size = int(os.getenv('MAX_FILE_SIZE', 100 * 1024 * 1024))  # 100MB default
        
        # Generate temporary file key
        file_key = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{Path(file.filename).suffix}"
        
        # Read file content with size check
        file_data = BytesIO()
        total_size = 0
        while True:
            chunk = await file.read(1 << 23)  # 8MB chunks
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > max_file_size:
                max_size_mb = max_file_size / (1024 * 1024)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size: {max_size_mb:.0f}MB"
                )
            file_data.write(chunk)
        
        # Save to storage (temporary file)
        temp_file_path = storage.save_temp_file(file_key, file_data.getvalue())
        
        # Submit task - worker will automatically determine if splitting is needed
        # Pass enable_pagination in options so worker can respect user's explicit choice
        task_result = celery_app.send_task(
            'mineru.parse_document',  # Unified task - worker handles all logic (splitting, parsing, merging)
            args=[
                temp_file_path,  # Storage path (S3 key or local path)
                file.filename,
                backend,
                {
                    'lang': lang,
                    'method': method,
                    'formula_enable': formula_enable,
                    'table_enable': table_enable,
                    'enable_pagination': enable_pagination,  # Pass user's choice to worker
                },
                False,  # upload_images
            ],
            queue=celeryconfig.MINERU_QUEUE,
            exchange=celeryconfig.MINERU_EXCHANGE,
            routing_key=celeryconfig.MINERU_ROUTING_KEY,
            priority=priority,
        )

        task_id = task_result.id
        logger.info(f"✅ Task submitted: {task_id} - {file.filename} (priority: {priority})")

        return {
            'success': True,
            'task_id': task_id,
            'status': 'pending',
            'message': 'Task submitted successfully',
            'file_name': file.filename,
            'created_at': datetime.now().isoformat(),
            'backend': backend,
            'priority': priority,
        }

    except Exception as exc:
        logger.error(f"❌ Failed to submit task: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/file_parse")
async def parse_pdf(
        files: List[UploadFile] = File(...),
        output_dir: str = Form("./output"),
        lang_list: List[str] = Form(["ch"]),
        backend: str = Form("pipeline"),
        parse_method: str = Form("auto"),
        formula_enable: bool = Form(True),
        table_enable: bool = Form(True),
        server_url: Optional[str] = Form(None),
        return_md: bool = Form(True),
        return_middle_json: bool = Form(False),
        return_model_output: bool = Form(False),
        return_content_list: bool = Form(False),
        return_images: bool = Form(False),
        response_format_zip: bool = Form(False),
        start_page_id: int = Form(0),
        end_page_id: int = Form(99999),
):
    """
    Parse PDF/image files using MinerU (compatible with official MinerU API format).
    This endpoint submits tasks to worker and waits for completion.
    Worker handles all splitting and merging logic - API layer just submits and collects results.
    """
    try:

        # Create unique output directory
        unique_dir = os.path.join(output_dir, str(datetime.now().strftime('%Y%m%d_%H%M%S_%f')))
        os.makedirs(unique_dir, exist_ok=True)

        # Process uploaded files
        pdf_file_names = []
        temp_file_paths = []
        task_results = []

        for file in files:
            content = await file.read()
            file_path = Path(file.filename)

            # Create temporary file
            temp_path = os.path.join(
                celeryconfig.TEMP_DIR,
                f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{file_path.suffix}"
            )
            with open(temp_path, "wb") as f:
                f.write(content)

            temp_file_paths.append(temp_path)
            pdf_file_names.append(file_path.stem)

            # Set language list, ensure consistency with file count
            actual_lang_list = lang_list
            if len(actual_lang_list) != len(pdf_file_names):
                actual_lang_list = [actual_lang_list[0] if actual_lang_list else "ch"] * len(pdf_file_names)

            # Submit task to worker (unified task - worker handles splitting automatically)
            task_result = celery_app.send_task(
                'mineru.parse_document',
                args=[
                    temp_path,
                    file.filename,
                    backend,
                    {
                        'lang': actual_lang_list[len(task_results)] if len(actual_lang_list) > len(task_results) else actual_lang_list[0],
                        'method': parse_method,
                        'formula_enable': formula_enable,
                        'table_enable': table_enable,
                    },
                    return_images,  # upload_images parameter
                ],
                queue=celeryconfig.MINERU_QUEUE,
                exchange=celeryconfig.MINERU_EXCHANGE,
                routing_key=celeryconfig.MINERU_ROUTING_KEY,
            )
            task_results.append(task_result)

        # Wait for all tasks to complete
        # Note: Worker layer handles all splitting and merging, so results are already merged
        completed_results = {}
        for i, (pdf_name, task_result) in enumerate(zip(pdf_file_names, task_results)):
            try:
                # Wait for task completion (synchronous wait)
                result = task_result.get(timeout=7200)  # 2 hours timeout
                
                if result.get('status') == 'failed':
                    completed_results[pdf_name] = {
                        'error': result.get('error_message', 'Unknown error')
                    }
                    continue

                # Get task output directory
                task_id = task_result.id
                output_path = Path(celeryconfig.OUTPUT_DIR) / task_id

                # Collect results
                file_result = {}
                
                if return_md:
                    # Get markdown content from task result
                    if 'data' in result and 'content' in result['data']:
                        file_result['md_content'] = result['data']['content']
                    else:
                        # Try to read from file
                        md_files = list(output_path.rglob('*.md'))
                        if md_files:
                            with open(md_files[0], 'r', encoding='utf-8') as f:
                                file_result['md_content'] = f.read()

                if return_middle_json:
                    # Try to read middle_json from file
                    if backend.startswith("pipeline"):
                        parse_dir = output_path / pdf_name / parse_method
                    else:
                        parse_dir = output_path / pdf_name / "vlm"
                    middle_json = get_infer_result("_middle.json", pdf_name, str(parse_dir))
                    if middle_json:
                        file_result['middle_json'] = middle_json

                if return_model_output:
                    # Try to read model_output from file
                    if backend.startswith("pipeline"):
                        parse_dir = output_path / pdf_name / parse_method
                    else:
                        parse_dir = output_path / pdf_name / "vlm"
                    model_output = get_infer_result("_model.json", pdf_name, str(parse_dir))
                    if model_output:
                        file_result['model_output'] = model_output

                if return_content_list:
                    # Get content_list from task result (as JSON string, consistent with middle_json and model_output)
                    if 'json_files' in result:
                        json_files = result['json_files']
                        if isinstance(json_files, dict) and 'content_list_json' in json_files:
                            content_list_path = json_files['content_list_json']
                            if content_list_path and os.path.exists(content_list_path):
                                with open(content_list_path, 'r', encoding='utf-8') as f:
                                    file_result['content_list'] = f.read()
                    if 'content_list' in result and 'content_list' not in file_result:
                        try:
                            file_result['content_list'] = json.dumps(result['content_list'], ensure_ascii=False)
                        except Exception:
                            pass
                    else:
                        # Try to read from file system
                        if backend.startswith("pipeline"):
                            parse_dir = output_path / pdf_name / parse_method
                        else:
                            parse_dir = output_path / pdf_name / "vlm"
                        content_list_json = get_infer_result("_content_list.json", pdf_name, str(parse_dir))
                        if content_list_json:
                            file_result['content_list'] = content_list_json

                if return_images:
                    # Get images from task result
                    if 'data' in result and 'images' in result['data']:
                        images_dict = {}
                        for img_info in result['data']['images']:
                            if 'data_url' in img_info:
                                images_dict[img_info.get('filename', 'unknown.jpg')] = img_info['data_url']
                        if images_dict:
                            file_result['images'] = images_dict
                    else:
                        # Read images from file system
                        md_files = list(output_path.rglob('*.md'))
                        if md_files:
                            images_dir = md_files[0].parent / 'images'
                            if images_dir.exists():
                                safe_pattern = os.path.join(glob.escape(str(images_dir)), "*.jpg")
                                image_paths = glob.glob(safe_pattern)
                                images_dict = {}
                                for image_path in image_paths:
                                    images_dict[os.path.basename(image_path)] = f"data:image/jpeg;base64,{encode_image(image_path)}"
                                if images_dict:
                                    file_result['images'] = images_dict
                
                # Worker already handles merging, so just add result directly
                completed_results[pdf_name] = file_result

            except Exception as e:
                logger.exception(f"Failed to process file {pdf_name}: {e}")
                completed_results[pdf_name] = {
                    'error': f"Failed to process file: {str(e)}"
                }

        # Build result entries (worker already handles merging, so no need to check for chunks)
        result_entries = []
        for pdf_name, task_result in zip(pdf_file_names, task_results):
            if pdf_name in completed_results:
                result_entries.append({"name": pdf_name, "task_id": task_result.id})

        # Determine return type based on response_format_zip
        if response_format_zip:
            zip_fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="mineru_results_")
            os.close(zip_fd)
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for entry in result_entries:
                    pdf_name = entry["name"]
                    if pdf_name not in completed_results:
                        continue
                    
                    safe_pdf_name = sanitize_filename(pdf_name)
                    result = completed_results[pdf_name]
                    
                    if 'error' in result:
                        continue

                    # Find corresponding task result to get output directory
                    task_id = entry["task_id"]
                    output_path = Path(celeryconfig.OUTPUT_DIR) / task_id

                    # Write text-type results
                    if return_md and 'md_content' in result:
                        # Create temporary md file
                        md_temp = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
                        md_temp.write(result['md_content'])
                        md_temp.close()
                        zf.write(md_temp.name, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}.md"))
                        os.unlink(md_temp.name)
                    elif return_md:
                        # Try to read from file system
                        md_files = list(output_path.rglob('*.md'))
                        if md_files:
                            zf.write(str(md_files[0]), arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}.md"))

                    if return_middle_json and 'middle_json' in result:
                        json_temp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
                        json_temp.write(result['middle_json'])
                        json_temp.close()
                        zf.write(json_temp.name, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_middle.json"))
                        os.unlink(json_temp.name)
                    elif return_middle_json:
                        # Try to read from file system
                        if backend.startswith("pipeline"):
                            parse_dir = output_path / pdf_name / parse_method
                        else:
                            parse_dir = output_path / pdf_name / "vlm"
                        middle_json_path = parse_dir / f"{pdf_name}_middle.json"
                        if middle_json_path.exists():
                            zf.write(str(middle_json_path), arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_middle.json"))

                    if return_model_output and 'model_output' in result:
                        json_temp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
                        json_temp.write(result['model_output'])
                        json_temp.close()
                        zf.write(json_temp.name, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_model.json"))
                        os.unlink(json_temp.name)
                    elif return_model_output:
                        # Try to read from file system
                        if backend.startswith("pipeline"):
                            parse_dir = output_path / pdf_name / parse_method
                        else:
                            parse_dir = output_path / pdf_name / "vlm"
                        model_output_path = parse_dir / f"{pdf_name}_model.json"
                        if model_output_path.exists():
                            zf.write(str(model_output_path), arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_model.json"))

                    if return_content_list and 'content_list' in result:
                        # content_list is now a JSON string, write directly
                        json_temp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
                        json_temp.write(result['content_list'])
                        json_temp.close()
                        zf.write(json_temp.name, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_content_list.json"))
                        os.unlink(json_temp.name)
                    elif return_content_list:
                        # Try to read from file system
                        auto_dir = output_path / pdf_name / "auto"
                        content_list_path = auto_dir / f"{pdf_name}_content_list.json"
                        if content_list_path.exists():
                            zf.write(str(content_list_path), arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_content_list.json"))

                    # Write images
                    if return_images:
                        md_files = list(output_path.rglob('*.md'))
                        if md_files:
                            images_dir = md_files[0].parent / 'images'
                            if images_dir.exists():
                                image_paths = glob.glob(os.path.join(glob.escape(str(images_dir)), "*.jpg"))
                                for image_path in image_paths:
                                    zf.write(image_path, arcname=os.path.join(safe_pdf_name, "images", os.path.basename(image_path)))

            return FileResponse(
                path=zip_path,
                media_type="application/zip",
                filename="results.zip",
                background=BackgroundTask(cleanup_file, zip_path)
            )
        else:
            # Build JSON result
            result_dict = {}
            for entry in result_entries:
                pdf_name = entry["name"]
                if pdf_name in completed_results:
                    result_dict[pdf_name] = completed_results[pdf_name]

            # Get version information (import from MinerU or use default)
            try:
                from mineru.version import __version__
                version = __version__
            except:
                version = "1.0.0"

            return JSONResponse(
                status_code=200,
                content={
                    "backend": backend,
                    "version": version,
                    "results": result_dict
                }
            )

    except Exception as e:
        logger.exception(e)
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process file: {str(e)}"}
        )


@app.get("/api/v1/tasks/{task_id}")
async def get_task_status(task_id: str, upload_images: bool = Query(False, description="Whether to upload images to MinIO")):
    """Query task status and result."""
    try:
        result = AsyncResult(task_id, app=celery_app)

        status_mapping = {
            'PENDING': 'pending',
            'STARTED': 'processing',
            'SUCCESS': 'completed',
            'FAILURE': 'failed',
            'RETRY': 'processing',
            'REVOKED': 'cancelled'
        }

        api_status = status_mapping.get(result.status, result.status.lower())

        response: Dict[str, Any] = {
            'success': True,
            'task': {
                'task_id': task_id,
                'status': api_status,
                'created_at': None,
                'started_at': None,
                'completed_at': None,
                'file_name': None,
                'backend': None,
                'result_path': None,
                'error_message': None,
                'retry_count': getattr(result, 'retries', 0)
            },
            'timestamp': datetime.now().isoformat()
        }

        if result.successful():
            task_result = result.result or {}
            response['task'].update({
                'result_path': task_result.get('result_path'),
                'file_name': task_result.get('file_name'),
                'backend': task_result.get('backend'),
                'completed_at': task_result.get('completed_at')
            })

            if 'data' in task_result and isinstance(task_result['data'], dict):
                response['markdown_content'] = task_result['data'].get('content')
                response['images'] = task_result['data'].get('images', [])

            # Priority 1: Use content_list/middle_json directly from task_result (for merged results)
            if 'content_list' in task_result:
                response['content_list'] = task_result['content_list']
            if 'middle_json' in task_result:
                response['middle_json'] = task_result['middle_json']

            # Priority 2: Load JSON from storage when only json_files keys are present
            if 'json_files' in task_result and isinstance(task_result['json_files'], dict):
                json_info = task_result['json_files']

                def _safe_load_json_from_storage(key: str | None) -> Any | None:
                    if not key:
                        return None
                    try:
                        storage = get_storage()
                        # Resolve path: worker stores output_key_prefix + key; storage uses OUTPUT_DIR (local) or bucket (s3)
                        if storage.storage_type == 'local':
                            from shared.storage import OUTPUT_DIR
                            read_path = str(Path(OUTPUT_DIR) / key)
                        else:
                            from shared.storage import S3_BUCKET_OUTPUT
                            read_path = f"{S3_BUCKET_OUTPUT}/{key}"
                        if storage.file_exists(read_path):
                            data_bytes = storage.read_file(read_path)
                            return json.loads(data_bytes.decode('utf-8'))
                    except Exception as exc:
                        logger.debug(
                            "Could not load JSON from storage for task %s key=%s: %s",
                            task_id,
                            key,
                            exc,
                        )
                    return None

                # content_list
                if 'content_list' not in response:
                    content_list_key = json_info.get('content_list_json')
                    content_list = _safe_load_json_from_storage(content_list_key)
                    if content_list is not None:
                        response['content_list'] = content_list

                # middle_json
                if 'middle_json' not in response:
                    middle_json_key = json_info.get('middle_json_json')
                    middle_json = _safe_load_json_from_storage(middle_json_key)
                    if middle_json is not None:
                        response['middle_json'] = middle_json

        elif result.failed():
            error_info = result.result if result.result else result.traceback
            response['task'].update({
                'error_message': str(error_info) if error_info else 'Unknown error',
                'completed_at': datetime.now().isoformat()
            })

        elif api_status == 'processing':
            if hasattr(result, 'info') and result.info and isinstance(result.info, dict):
                progress_info = result.info
                response['task'].update({
                    'file_name': progress_info.get('file_name'),
                    'backend': progress_info.get('backend'),
                    'started_at': progress_info.get('started_at')
                })

        if response.get('success'):
            return response
        raise HTTPException(status_code=404, detail=response.get('error', 'Task not found'))

    except Exception as exc:
        logger.error(f"❌ Failed to get task status for {task_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to query task: {str(exc)}")


@app.delete("/api/v1/tasks/{task_id}")
async def cancel_task(task_id: str):
    """Cancel an active task."""
    try:
        celery_app.control.revoke(task_id, terminate=True)
        return {
            'success': True,
            'message': f'Task {task_id} has been cancelled',
            'task_id': task_id,
            'timestamp': datetime.now().isoformat()
        }
    except Exception as exc:
        logger.error(f"❌ Failed to cancel task {task_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {str(exc)}")


@app.get("/api/v1/queue/stats")
async def get_queue_stats():
    """Retrieve queue statistics."""
    try:
        inspect = celery_app.control.inspect()
        active_tasks = inspect.active() or {}
        scheduled_tasks = inspect.scheduled() or {}
        reserved_tasks = inspect.reserved() or {}

        active_count = sum(len(tasks) for tasks in active_tasks.values())
        pending_count = sum(len(tasks) for tasks in scheduled_tasks.values())
        reserved_count = sum(len(tasks) for tasks in reserved_tasks.values())

        return {
            'success': True,
            'stats': {
                'pending': pending_count + reserved_count,
                'processing': active_count,
                'completed': 0,
                'failed': 0,
                'total_active': active_count,
                'total_scheduled': pending_count
            },
            'workers': {
                'active_workers': len(active_tasks),
                'total_workers': len(inspect.stats() or {})
            },
            'timestamp': datetime.now().isoformat(),
            'note': 'Completed/failed counts not available in Celery. Only active tasks are tracked.'
        }
    except Exception as exc:
        logger.error(f"❌ Failed to get queue stats: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to get queue stats: {str(exc)}")


@app.get("/api/v1/queue/tasks")
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter status: pending/processing/completed/failed"),
    limit: int = Query(100, description="Return count limit", le=1000)
):
    """List active and scheduled tasks."""
    try:
        inspect = celery_app.control.inspect()
        tasks = []

        if not status or status == 'processing':
            active_tasks = inspect.active() or {}
            for worker_name, worker_tasks in active_tasks.items():
                for task in worker_tasks:
                    tasks.append({
                        'task_id': task['id'],
                        'status': 'processing',
                        'worker_id': worker_name,
                        'file_name': task.get('kwargs', {}).get('file_name'),
                        'backend': task.get('kwargs', {}).get('backend'),
                        'started_at': task.get('time_start'),
                        'created_at': None,
                        'priority': 0
                    })

        if not status or status == 'pending':
            scheduled_tasks = inspect.scheduled() or {}
            for _, worker_tasks in scheduled_tasks.items():
                for task in worker_tasks:
                    tasks.append({
                        'task_id': task['request']['id'],
                        'status': 'pending',
                        'worker_id': None,
                        'file_name': task['request'].get('kwargs', {}).get('file_name'),
                        'backend': task['request'].get('kwargs', {}).get('backend'),
                        'created_at': None,
                        'started_at': None,
                        'priority': task.get('priority', 0),
                        'eta': task.get('eta')
                    })

        tasks = tasks[:limit]

        return {
            'success': True,
            'tasks': tasks,
            'count': len(tasks),
            'limit': limit,
            'status_filter': status,
            'timestamp': datetime.now().isoformat(),
            'note': 'Only active and scheduled tasks are shown. Historical tasks are not stored by default.'
        }
    except Exception as exc:
        logger.error(f"❌ Failed to list tasks: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to list tasks: {str(exc)}")


@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    try:
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active_workers = len(stats) if stats else 0

        return {
            'success': True,
            'status': 'healthy',
            'service': 'ThinkParse API Server',
            'version': '1.1.0',
            'workers': {
                'active': active_workers,
                'available': active_workers > 0
            },
            'timestamp': datetime.now().isoformat()
        }
    except Exception as exc:
        logger.error(f"❌ Health check failed: {exc}")
        return {
            'success': False,
            'status': 'unhealthy',
            'error': str(exc),
            'timestamp': datetime.now().isoformat()
        }


if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 Starting ThinkParse API Server on {celeryconfig.API_HOST}:{celeryconfig.API_PORT}")
    logger.info(f"📚 API Documentation: http://{celeryconfig.API_HOST}:{celeryconfig.API_PORT}/docs")
    uvicorn.run(app, host=celeryconfig.API_HOST, port=celeryconfig.API_PORT, log_level="info")
