"""MinerU Celery Tasks
MinerU document processing task definitions

Provides asynchronous MinerU document parsing tasks based on Celery
"""
import os
import sys
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Dict, Any, Optional, List
import uuid
from datetime import datetime
import traceback
from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv()

# Add path to import components
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from celery import Celery, states
from celery.utils.log import get_task_logger
from shared import celeryconfig
from shared.disk_space import StorageCapacityExceeded, raise_if_storage_full
from shared.storage import get_storage
from shared.observability import (
    TaskCancellationProbe,
    WorkerHeartbeat,
    is_task_cancellation_requested,
    resolve_legacy_pagination,
)
from shared.task_result import (
    apply_status_payload,
    hydrate_celery_result,
    slim_celery_result,
)
from worker.mineru_engine import (
    MinerUEngineCancelled,
    mineru_engine,
)

if os.getenv('MINERU_DEVICE_MODE') == None or os.getenv('MINERU_DEVICE_MODE') == '' or os.getenv('MINERU_DEVICE_MODE') == 'auto':
    # Delete empty or 'auto' value to let MinerU automatically detect device type
    os.environ.pop('MINERU_DEVICE_MODE', None)

import threading
# PyPDFium2 only supports single-threaded usage
pypdfium2_lock = threading.Lock()

# Initialize MinerU models config if missing
def _init_mineru_models_config():
    """Initialize MinerU models config file if it doesn't exist"""
    import json
    from pathlib import Path as P
    config_path = P.home() / '.mineru' / 'models_config.json'
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {'pipeline': {}, 'vlm': {}}
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"✅ Initialized MinerU models config at {config_path}")

_init_mineru_models_config()

# Celery application
celery_app = Celery('mineru_worker')
celery_app.config_from_object(celeryconfig)
worker_heartbeat = WorkerHeartbeat(
    celeryconfig.WORKER_NAME,
    on_watchdog_timeout=mineru_engine.force_stop,
)

# Read package metadata without importing CUDA/model modules in the Worker.
try:
    MINERU_VERSION = version('mineru')
    MINERU_AVAILABLE = True
except PackageNotFoundError:
    MINERU_VERSION = None
    MINERU_AVAILABLE = False

worker_heartbeat.set_metadata(
    mineru_version=MINERU_VERSION,
    concurrency=celeryconfig.WORKER_CONCURRENCY,
    pool=celeryconfig.WORKER_POOL or 'prefork',
    device_mode=os.getenv('MINERU_DEVICE_MODE', 'auto'),
    processing_window_size=int(os.getenv('MINERU_PROCESSING_WINDOW_SIZE', '64')),
)

# PyPDFium2 for PDF page detection
try:
    import pypdfium2
    PYPDFIUM2_AVAILABLE = True
except ImportError:
    PYPDFIUM2_AVAILABLE = False

# Note: Using pypdfium2 for both page detection and PDF splitting
# (MinerU already uses pypdfium2, so we reuse it to reduce dependencies)

# MarkItDown imports
try:
    from markitdown import MarkItDown
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MARKITDOWN_AVAILABLE = False

# MinIO imports
try:
    from minio import Minio
    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False

logger = get_task_logger(__name__)

# Configuration constants
OUTPUT_DIR = Path(celeryconfig.OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Pagination configuration is read directly from environment variables when needed
# No need to pre-load constants as they may change between tasks

# Supported file formats
PDF_IMAGE_FORMATS = {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp'}

# MIME type mapping
MIME_TYPE_MAP = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
    '.webp': 'image/webp',
    '.tiff': 'image/tiff',
    '.tif': 'image/tiff'
}

# MinIO configuration
MINIO_CONFIG = {
    'endpoint': os.getenv('MINIO_ENDPOINT', 'localhost:9000'),
    'access_key': os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
    'secret_key': os.getenv('MINIO_SECRET_KEY', 'minioadmin'),
    'secure': os.getenv('MINIO_SECURE', 'false').lower() == 'true',
    'bucket_name': os.getenv('MINIO_BUCKET', 'documents')
}


def get_minio_client():
    """Get MinIO client"""
    if not MINIO_AVAILABLE or not all(MINIO_CONFIG.values()):
        return None
    
    return Minio(
        MINIO_CONFIG['endpoint'],
        access_key=MINIO_CONFIG['access_key'],
        secret_key=MINIO_CONFIG['secret_key'],
        secure=MINIO_CONFIG['secure']
    )


def get_file_type(file_path: str) -> str:
    """
    Determine file type
    
    Returns:
        'pdf_image': PDF or image format, use MinerU parsing
        'markitdown': All other formats, use markitdown parsing
    """
    suffix = Path(file_path).suffix.lower()
    
    if suffix in PDF_IMAGE_FORMATS:
        return 'pdf_image'
    else:
        return 'markitdown'


def get_pdf_page_count(file_path: Path) -> int:
    """
    Get the total number of pages in a PDF file
    
    Args:
        file_path: Path to PDF file
        
    Returns:
        Total number of pages, or 0 if unable to determine
    """
    if not PYPDFIUM2_AVAILABLE:
        logger.warning("pypdfium2 not available, cannot detect PDF page count")
        return 0
    
    try:
        with pypdfium2_lock:
            pdf = pypdfium2.PdfDocument(file_path)
            page_count = len(pdf)
            pdf.close()
            return page_count
    except Exception as e:
        logger.error(f"Failed to get PDF page count for {file_path}: {e}")
        return 0


def split_pdf_file(
    pdf_path: Path, 
    output_dir: Path, 
    chunk_size: int = 500, 
    parent_task_id: str = None
) -> List[Dict[str, Any]]:
    """
    Split PDF file into multiple chunks using pypdfium2
    
    Args:
        pdf_path: Path to PDF file
        output_dir: Output directory for chunk files
        chunk_size: Number of pages per chunk
        parent_task_id: Parent task ID (for generating filenames)
        
    Returns:
        List of chunk info dicts, each containing:
        - path: Chunk file path (storage path)
        - start_page: Start page number (1-based)
        - end_page: End page number (1-based)
        - page_count: Number of pages in chunk
    """
    if not PYPDFIUM2_AVAILABLE:
        raise RuntimeError("pypdfium2 is required for PDF splitting. Install with: pip install pypdfium2")
    
    try:
        chunks = []
        output_dir.mkdir(parents=True, exist_ok=True)
        storage = get_storage()
        
        # Open PDF and get page count (within lock for thread safety)
        with pypdfium2_lock:
            pdf = pypdfium2.PdfDocument(pdf_path)
            total_pages = len(pdf)
        
        logger.info(f"✂️  Splitting PDF: {pdf_path.name} ({total_pages} pages)")
        logger.info(f"   Chunk size: {chunk_size} pages")
        logger.info("   Using pypdfium2 for PDF splitting")
        
        import tempfile
        import io
        
        for i in range(0, total_pages, chunk_size):
            end_page = min(i + chunk_size, total_pages)
            chunk_page_count = end_page - i
            
            # Generate chunk filename
            if parent_task_id:
                chunk_filename = f"{parent_task_id}_chunk_{i+1}_{end_page}.pdf"
            else:
                chunk_filename = f"{pdf_path.stem}_chunk_{i+1}_{end_page}.pdf"
            
            # Create chunk PDF and save to bytes (within lock for thread safety)
            with pypdfium2_lock:
                chunk_pdf = pypdfium2.PdfDocument.new()
                page_indices = list(range(i, end_page))
                chunk_pdf.import_pages(pdf, pages=page_indices)
                
                # Save to bytes buffer
                pdf_buffer = io.BytesIO()
                chunk_pdf.save(pdf_buffer)
                pdf_bytes = pdf_buffer.getvalue()
                pdf_buffer.close()
                chunk_pdf.close()
            
            # File I/O operations outside lock (no pypdfium2 operations)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_chunk:
                tmp_chunk.write(pdf_bytes)
                chunk_local_path = Path(tmp_chunk.name)
            
            # Upload chunk to storage
            chunk_storage_key = f"splits/{parent_task_id}/{chunk_filename}" if parent_task_id else f"splits/{chunk_filename}"
            chunk_storage_path = storage.save_temp_file(chunk_storage_key, chunk_local_path.read_bytes())
            
            # Clean up local temporary file
            try:
                chunk_local_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to cleanup temp chunk file: {e}")
            
            chunk_info = {
                "path": chunk_storage_path,  # Storage path
                "start_page": i + 1,  # 1-based
                "end_page": end_page,  # 1-based
                "page_count": chunk_page_count,
            }
            chunks.append(chunk_info)
            
            logger.info(f"   ✅ Created chunk {len(chunks)}: pages {i+1}-{end_page} ({chunk_page_count} pages)")
        
        # Close PDF (within lock for thread safety)
        with pypdfium2_lock:
            pdf.close()
        
        logger.info(f"✅ Split into {len(chunks)} chunks")
        return chunks
        
    except ImportError:
        logger.error("❌ pypdfium2 not installed. Install with: pip install pypdfium2")
        raise RuntimeError("pypdfium2 is required for PDF splitting")
    except Exception as e:
        logger.error(f"❌ Failed to split PDF: {e}")
        raise


def process_markdown_images_base64(md_content: str, image_dir: Path) -> str:
    """Convert images in Markdown to base64 format"""
    logger.info(f"🔄 Converting images to base64: image_dir={image_dir}")
    
    if not image_dir.exists():
        logger.warning(f"Image directory does not exist for base64 conversion: {image_dir}")
        return md_content
    
    import re
    import base64
    import mimetypes
    
    # Find all image links
    image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    matches = re.findall(image_pattern, md_content)
    
    if not matches:
        return md_content
    
    # MIME type mapping uses global constant
    mime_map = MIME_TYPE_MAP
    
    # Replace image links with base64
    for alt_text, image_path in matches:
        # Build full image path
        # If image_path starts with images/, remove this prefix
        if image_path.startswith('images/'):
            image_filename = image_path[7:]  # Remove 'images/' prefix
        else:
            image_filename = image_path
        
        full_image_path = image_dir / image_filename
        
        if full_image_path.exists():
            try:
                # Read image file
                with open(full_image_path, 'rb') as img_file:
                    img_data = img_file.read()
                
                # Get MIME type
                mime_type, _ = mimetypes.guess_type(str(full_image_path))
                if not mime_type or not mime_type.startswith('image/'):
                    # Set default MIME type based on file extension
                    ext = full_image_path.suffix.lower()
                    mime_type = mime_map.get(ext, 'image/png')
                
                # Convert to base64
                img_base64 = base64.b64encode(img_data).decode('utf-8')
                
                # Create data URL
                data_url = f"data:{mime_type};base64,{img_base64}"
                
                # Replace link in Markdown
                old_link = f"![{alt_text}]({image_path})"
                new_link = f"![{alt_text}]({data_url})"
                md_content = md_content.replace(old_link, new_link)
                
                logger.info(f"Converted image to base64: {image_path} ({len(img_data)} bytes)")
                
            except Exception as e:
                logger.error(f"Failed to convert image to base64 {image_path}: {e}")
    
    return md_content


def process_markdown_images(md_content: str, image_dir: Path, upload_images: bool = False) -> str:
    """Process image links in Markdown"""
    logger.info(f"🖼️ Processing images: upload_images={upload_images}, image_dir={image_dir}")
    
    if not image_dir.exists():
        logger.warning(f"Image directory does not exist: {image_dir}")
        return md_content
    
    if upload_images:
        # Original logic for uploading to MinIO
        import re
        
        # Find all image links
        image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        matches = re.findall(image_pattern, md_content)
        
        if not matches:
            return md_content
        
        minio_client = get_minio_client()
        if not minio_client:
            logger.warning("MinIO not configured, skipping image upload")
            return md_content
        
        # Replace image links
        for alt_text, image_path in matches:
            # Build full image path
            full_image_path = image_dir / image_path
            
            if full_image_path.exists():
                try:
                    # Generate unique object name
                    object_name = f"mineru/{uuid.uuid4()}/{full_image_path.name}"
                    
                    # Upload to MinIO
                    minio_client.fput_object(
                        MINIO_CONFIG['bucket_name'],
                        object_name,
                        str(full_image_path)
                    )
                    
                    # Generate access URL
                    image_url = f"https://{MINIO_CONFIG['endpoint']}/{MINIO_CONFIG['bucket_name']}/{object_name}"
                    
                    # Replace link in Markdown
                    old_link = f"![{alt_text}]({image_path})"
                    new_link = f"![{alt_text}]({image_url})"
                    md_content = md_content.replace(old_link, new_link)
                    
                    logger.info(f"Uploaded image: {image_path} -> {image_url}")
                    
                except Exception as e:
                    logger.error(f"Failed to upload image {image_path}: {e}")
    else:
        # Default: convert to base64 format
        md_content = process_markdown_images_base64(md_content, image_dir)
    
    return md_content


@celery_app.task(
    name='mineru.parse_document',
    bind=True,
    max_retries=0,
    soft_time_limit=6000,
    time_limit=7200,
    track_started=True
)
def parse_document_task(
    self,
    file_path: str,
    file_name: str,
    backend: str = 'pipeline',
    options: Optional[Dict[str, Any]] = None,
    upload_images: bool = False,
) -> Dict[str, Any]:
    """
    MinerU document parsing task with automatic splitting for large PDFs
    
    This task handles the complete flow:
    1. Check if PDF needs splitting (based on page count and configuration)
    2. If yes: split -> parse chunks -> merge
    3. If no: parse directly
    
    All logic is handled in worker layer - API layer just submits this task.
    """
    if options is None:
        options = {}
    
    task_id = self.request.id
    try:
        raise_if_storage_full()
    except StorageCapacityExceeded as exc:
        logger.warning("Delaying task %s until disk headroom recovers: %s", task_id, exc)
        raise self.retry(countdown=60, max_retries=1440, exc=exc)

    if is_task_cancellation_requested(task_id):
        logger.warning(f"🛑 Task {task_id} was cancelled before processing started")
        return {
            'status': 'cancelled',
            'file_name': file_name,
            'backend': backend,
            'error_message': 'Cancellation requested before processing started',
            'traceback': '',
            'completed_at': datetime.now().isoformat(),
        }

    storage = get_storage()
    worker_heartbeat.set_task(task_id, file_name)
    local_input_path: Optional[Path] = None
    
    try:
        # Download file to check if splitting is needed.
        local_file = storage.download_to_local(file_path)
        local_input_path = Path(local_file)
        if not local_input_path.exists():
            import time
            wait_seconds = float(os.getenv('MINERU_WAIT_FOR_INPUT_SECONDS', '5'))
            deadline = time.time() + wait_seconds
            while not local_input_path.exists() and time.time() < deadline:
                time.sleep(0.2)
            if not local_input_path.exists():
                return {
                    'status': 'failed',
                    'file_name': file_name,
                    'backend': backend,
                    'error_message': f'Input file not found: {local_input_path}',
                    'traceback': '',
                    'completed_at': datetime.now().isoformat()
                }

        # Legacy compatibility path. A request-level value overrides the
        # deployment default; otherwise MinerU's built-in processing windows
        # are used unless legacy physical splitting is explicitly enabled.
        requested_pagination = options.get('enable_pagination')
        pagination_enabled = resolve_legacy_pagination(requested_pagination)
        
        # Determine if splitting is needed
        use_pagination = False
        total_pages = 0
        
        if pagination_enabled:
            if PYPDFIUM2_AVAILABLE and file_name.lower().endswith('.pdf'):
                total_pages = get_pdf_page_count(local_input_path)
                pagination_threshold = int(os.getenv('MINERU_PAGINATION_THRESHOLD', 100))
                
                if total_pages > pagination_threshold:
                    use_pagination = True
                    logger.info(f"🔀 Large PDF detected ({total_pages} pages), will split and parse in chunks")
        
        if use_pagination:
            # Split and parse in chunks
            return _handle_split_and_parse(
                self,
                local_input_path,
                file_path,
                file_name,
                backend,
                options,
                upload_images,
                task_id
            )
        else:
            # Parse directly (no splitting needed)
            # Update task state
            self.update_state(
                state=states.STARTED,
                meta={
                    'status': 'processing',
                    'file_name': file_name,
                    'backend': backend,
                    'started_at': datetime.now().isoformat()
                }
            )
            
            # Execute parsing logic
            return _execute_parse_document(
                file_path=file_path,
                file_name=file_name,
                task_id=task_id,
                backend=backend,
                options=options,
                upload_images=upload_images
            )
    finally:
        # Clean up local file
        try:
            if (
                local_input_path is not None
                and local_input_path.exists()
                and str(local_input_path) != file_path
            ):
                local_input_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup local temp file: {e}")
        worker_heartbeat.clear_task()


def _handle_split_and_parse(
    self,
    local_input_path: Path,
    storage_file_path: str,
    file_name: str,
    backend: str,
    options: Dict[str, Any],
    upload_images: bool,
    parent_task_id: str
) -> Dict[str, Any]:
    """Handle splitting, parsing chunks, and merging results"""
    storage = get_storage()
    chunk_size = int(os.getenv('MINERU_PAGE_CHUNK_SIZE', 50))
    
    # Create splits directory
    import tempfile
    splits_dir = Path(tempfile.gettempdir()) / "mineru_splits" / parent_task_id
    splits_dir.mkdir(parents=True, exist_ok=True)
    
    # Split PDF
    chunks = split_pdf_file(
        pdf_path=local_input_path,
        output_dir=splits_dir,
        chunk_size=chunk_size,
        parent_task_id=parent_task_id
    )
    logger.info(f"✂️  PDF split into {len(chunks)} chunks")

    if storage.storage_type == 'local':
        self.update_state(
            state=states.STARTED,
            meta={
                'status': 'splitting_and_parsing',
                'file_name': file_name,
                'backend': backend,
                'chunk_count': len(chunks),
                'started_at': datetime.now().isoformat()
            }
        )

        chunk_results: List[Dict[str, Any]] = []
        failed_chunks: List[Dict[str, Any]] = []

        for chunk in chunks:
            chunk_file_path = chunk['path']
            chunk_start_page = chunk.get('start_page', 1)
            chunk_end_page = chunk.get('end_page', 1)

            chunk_options = options.copy()
            chunk_options['chunk_info'] = {
                'start_page': chunk_start_page,
                'end_page': chunk_end_page,
                'page_count': chunk.get('page_count', chunk_end_page - chunk_start_page + 1),
            }

            chunk_task_id = f"{parent_task_id}_{chunk_start_page}_{chunk_end_page}_{uuid.uuid4().hex[:8]}"
            chunk_result = _execute_parse_document(
                file_path=chunk_file_path,
                file_name=f"{Path(file_name).stem}_pages_{chunk_start_page}-{chunk_end_page}.pdf",
                task_id=chunk_task_id,
                backend=backend,
                options=chunk_options,
                upload_images=upload_images,
            )

            if chunk_result.get('status') == 'failed':
                failed_chunks.append({
                    'file_name': chunk_result.get('file_name'),
                    'start_page': chunk_start_page,
                    'end_page': chunk_end_page,
                    'error': chunk_result.get('error_message', 'Unknown error'),
                })
                continue

            chunk_result['start_page'] = chunk_start_page
            chunk_result['end_page'] = chunk_end_page
            chunk_results.append(chunk_result)

        try:
            storage.delete_file(storage_file_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup storage temp file {storage_file_path}: {e}")

        if not chunk_results:
            first_error = failed_chunks[0]['error'] if failed_chunks else 'Unknown'
            return {
                'status': 'failed',
                'file_name': file_name,
                'backend': backend,
                'error_message': f"All {len(chunks)} chunks failed. First error: {first_error}",
                'completed_at': datetime.now().isoformat()
            }

        return _merge_chunk_results_from_results(
            chunk_results=chunk_results,
            file_name=file_name,
            backend=backend,
            task_id=parent_task_id,
        )
    
    # Submit parse tasks for each chunk
    chunk_task_ids = []
    for chunk in chunks:
        chunk_file_path = chunk['path']  # Storage path
        chunk_start_page = chunk.get('start_page', 1)
        chunk_end_page = chunk.get('end_page', 1)
        
        chunk_options = options.copy()
        chunk_options['chunk_info'] = {
            'start_page': chunk_start_page,
            'end_page': chunk_end_page,
            'page_count': chunk.get('page_count', chunk_end_page - chunk_start_page + 1),
        }
        
        chunk_task = celery_app.send_task(
            'mineru.parse_document',
            args=[
                chunk_file_path,
                f"{Path(file_name).stem}_pages_{chunk_start_page}-{chunk_end_page}.pdf",
                backend,
                chunk_options,
                upload_images,
            ],
            queue=celeryconfig.MINERU_QUEUE,
            exchange=celeryconfig.MINERU_EXCHANGE,
            routing_key=celeryconfig.MINERU_ROUTING_KEY,
        )
        chunk_task_ids.append(chunk_task.id)
    
    # Submit merge task and return its ID
    # The merge task will handle waiting for all chunks and merging results
    merge_task = celery_app.send_task(
        'mineru.merge_chunk_results',
        args=[chunk_task_ids, file_name, backend],
        queue=celeryconfig.MINERU_QUEUE,
        exchange=celeryconfig.MINERU_EXCHANGE,
        routing_key=celeryconfig.MINERU_ROUTING_KEY,
    )
    
    # Update parent task state to indicate it's waiting for merge
    self.update_state(
        state=states.STARTED,
        meta={
            'status': 'splitting_and_parsing',
            'file_name': file_name,
            'backend': backend,
            'chunk_count': len(chunks),
            'merge_task_id': merge_task.id,
            'started_at': datetime.now().isoformat()
        }
    )
    
    # Wait for merge task to complete and return its result
    from celery.result import AsyncResult
    result = AsyncResult(merge_task.id, app=celery_app)
    
    # Poll for completion
    import time
    timeout = 7200  # 2 hours
    start_time = time.time()
    while not result.ready() and (time.time() - start_time) < timeout:
        time.sleep(1)
    
    if not result.ready():
        raise Exception(f"Merge task timed out after {timeout} seconds")
    
    if result.successful():
        try:
            storage.delete_file(storage_file_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup storage temp file {storage_file_path}: {e}")
        return result.result
    else:
        raise Exception(f"Merge task failed: {result.result}")


def _merge_chunk_results_from_results(
    chunk_results: List[Dict[str, Any]],
    file_name: str,
    backend: str,
    task_id: str,
) -> Dict[str, Any]:
    chunk_results.sort(key=lambda x: x.get('start_page', 1))

    merged_md_parts = []
    merged_images = []
    merged_content_list = []
    total_images = 0
    content_list_format = None
    content_list_meta = None

    for idx, chunk_result in enumerate(chunk_results):
        # Chunk Celery results are slim (keys only); load bodies from storage.
        chunk_result = hydrate_celery_result(chunk_result)
        chunk_data = chunk_result.get('data', {})
        chunk_md = chunk_data.get('content') or ''
        chunk_start_page = chunk_result.get('start_page', 1)
        chunk_end_page = chunk_result.get('end_page', 1)

        logger.info(f"📦 Merging chunk {idx+1}/{len(chunk_results)}: pages {chunk_start_page}-{chunk_end_page}, content_length={len(chunk_md)}, has_content_list={chunk_result.get('content_list') is not None}, has_images={len(chunk_data.get('images', []))}")

        merged_md_parts.append(chunk_md)

        chunk_images = chunk_data.get('images', [])
        merged_images.extend(chunk_images)
        total_images += len(chunk_images)

        chunk_content_list = chunk_result.get('content_list')
        if chunk_content_list:
            if content_list_format is None:
                if isinstance(chunk_content_list, dict):
                    if 'pages' in chunk_content_list:
                        content_list_format = 'pages'
                        content_list_meta = {k: v for k, v in chunk_content_list.items() if k != 'pages'}
                    elif 'items' in chunk_content_list:
                        content_list_format = 'items'
                        content_list_meta = {k: v for k, v in chunk_content_list.items() if k != 'items'}
                    else:
                        content_list_format = 'list'
                else:
                    content_list_format = 'list'

            page_offset = chunk_start_page - 1

            if isinstance(chunk_content_list, list):
                for item in chunk_content_list:
                    if isinstance(item, dict):
                        merged_item = item.copy()
                        if 'page_idx' in merged_item:
                            merged_item['page_idx'] += page_offset
                        if 'page_number' in merged_item:
                            merged_item['page_number'] += page_offset
                        if 'page' in merged_item:
                            merged_item['page'] += page_offset
                        if 'page_index' in merged_item:
                            merged_item['page_index'] += page_offset
                        if 'page_num' in merged_item:
                            merged_item['page_num'] += page_offset
                    else:
                        merged_item = item
                    merged_content_list.append(merged_item)
            elif isinstance(chunk_content_list, dict):
                if 'pages' in chunk_content_list:
                    for page in chunk_content_list['pages']:
                        if isinstance(page, dict):
                            merged_page = page.copy()
                            if 'page_idx' in merged_page:
                                merged_page['page_idx'] += page_offset
                            if 'page_number' in merged_page:
                                merged_page['page_number'] += page_offset
                            if 'page' in merged_page:
                                merged_page['page'] += page_offset
                            merged_content_list.append(merged_page)
                        else:
                            merged_content_list.append(page)
                elif 'items' in chunk_content_list:
                    for item in chunk_content_list['items']:
                        if isinstance(item, dict):
                            merged_item = item.copy()
                            if 'page_idx' in merged_item:
                                merged_item['page_idx'] += page_offset
                            if 'page_number' in merged_item:
                                merged_item['page_number'] += page_offset
                            if 'page' in merged_item:
                                merged_item['page'] += page_offset
                            merged_content_list.append(merged_item)
                        else:
                            merged_content_list.append(item)
                else:
                    logger.warning(f"Unexpected content_list structure in chunk pages {chunk_start_page}-{chunk_end_page}: {type(chunk_content_list)}")
        else:
            logger.warning(f"⚠️ Chunk pages {chunk_start_page}-{chunk_end_page} has no content_list")

    merged_md = ''.join(merged_md_parts)
    has_base64_images = 'data:image' in merged_md

    logger.info(f"✅ Merged {len(chunk_results)} chunks successfully")
    logger.info(f"📊 Merge statistics: total_content_length={len(merged_md)}, total_images={total_images}, total_content_list_items={len(merged_content_list)}")

    parse_method = chunk_results[0].get('parse_method', 'MinerU') if chunk_results else 'MinerU'

    storage = get_storage()
    import tempfile

    with tempfile.TemporaryDirectory() as temp_output_dir:
        output_path = Path(temp_output_dir) / task_id
        output_path.mkdir(parents=True, exist_ok=True)

        md_output = output_path / "result.md"
        md_output.write_text(merged_md, encoding='utf-8')

        output_key_prefix = f"{task_id}/"

        if merged_images:
            merged_images.sort(key=lambda img: img.get('filename', '') if isinstance(img, dict) else '')
            images_dir = output_path / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            for img in merged_images:
                if not isinstance(img, dict):
                    continue
                filename = img.get('filename')
                data_url = img.get('data_url')
                if not filename or not data_url or ',' not in str(data_url):
                    continue
                try:
                    import base64
                    encoded = str(data_url).split(',', 1)[1]
                    (images_dir / Path(filename).name).write_bytes(base64.b64decode(encoded))
                except Exception as e:
                    logger.warning(f"Failed to persist merged image {filename}: {e}")

        if merged_content_list:
            if content_list_format == 'pages':
                final_content_list = {**(content_list_meta or {}), 'pages': merged_content_list}
            elif content_list_format == 'items':
                final_content_list = {**(content_list_meta or {}), 'items': merged_content_list}
            else:
                final_content_list = merged_content_list
        else:
            final_content_list = None

        images_uploaded = chunk_results[0].get('data', {}).get('images_uploaded', False) if chunk_results else False

        markdown_key = f"{output_key_prefix}result.md"
        result = {
            'status': 'completed',
            'file_name': file_name,
            'backend': backend,
            'parse_method': parse_method,
            'completed_at': datetime.now().isoformat(),
            'result_path': output_key_prefix,
            'markdown_key': markdown_key,
            'data': {
                'images_uploaded': images_uploaded,
                'images_as_base64': has_base64_images,
                'has_images': total_images > 0,
            }
        }

        if final_content_list is not None:
            base_name = Path(file_name).stem
            content_list_json = output_path / f"{base_name}/auto/{base_name}_content_list.json"
            content_list_json.parent.mkdir(parents=True, exist_ok=True)
            content_list_json.write_text(json.dumps(final_content_list, indent=2, ensure_ascii=False), encoding='utf-8')

            content_list_storage_key = f"{output_key_prefix}{base_name}/auto/{base_name}_content_list.json"
            result['json_files'] = {
                'content_list_json': content_list_storage_key
            }

        # Upload all local outputs (md / images / json) once at the end.
        for file_path_obj in output_path.rglob('*'):
            if file_path_obj.is_file():
                relative_path = file_path_obj.relative_to(output_path)
                storage_key = f"{output_key_prefix}{relative_path}"
                storage.save_output_file(storage_key, file_path_obj.read_bytes())

    logger.info(
        f"✅ Merge completed: content_length={len(merged_md)}, "
        f"content_list_items={len(merged_content_list)}, "
        f"has_json_files={'json_files' in result}"
    )

    return slim_celery_result(result)



def _execute_parse_document(
    file_path: str,
    file_name: str,
    task_id: str,
    backend: str,
    options: Dict[str, Any],
    upload_images: bool,
) -> Dict[str, Any]:
    """
    Execute document parsing (core parsing logic)
    
    This function contains the core parsing logic used by parse_document_task
    """
    # Prepare options
    options = options.copy() if options else {}
    options.update({
        'f_dump_content_list': True
    })
    options.setdefault('formula_enable', os.getenv('MINERU_FORMULA_ENABLE', 'true').lower() == 'true')
    options.setdefault('table_enable', os.getenv('MINERU_TABLE_ENABLE', 'true').lower() == 'true')
    options.setdefault('method', os.getenv('MINERU_PARSE_METHOD', 'auto'))
    options.setdefault('lang', os.getenv('MINERU_LANG', 'ch'))
    
    logger.info(f"Starting MinerU document parsing task: {file_name}")
    
    try:
        storage = get_storage()
        
        # Download input file to local (if S3 storage, need local file path for MinerU)
        local_input_file = storage.download_to_local(file_path)
        local_input_path = Path(local_input_file)
        
        try:
            # Prepare output directory (local temporary directory, upload to storage after processing)
            import tempfile
            with tempfile.TemporaryDirectory() as temp_output_dir:
                output_path = Path(temp_output_dir) / task_id
                output_path.mkdir(parents=True, exist_ok=True)
                
                # Determine file type and select parsing method
                file_type = get_file_type(str(local_input_path))
                
                if file_type == 'pdf_image':
                    # Use MinerU to parse PDF and images
                    logger.info(f"📄 Using MinerU parser for {file_name}")
                    result = _parse_with_mineru(
                        file_path=local_input_path,
                        file_name=file_name,
                        task_id=task_id,
                        backend=backend,
                        options=options,
                        output_path=output_path,
                    )
                    parse_method = 'MinerU'
                else:
                    # Use MarkItDown to parse other formats
                    logger.info(f"📊 Using MarkItDown parser for {file_name}")
                    result = _parse_with_markitdown(
                        file_path=local_input_path,
                        file_name=file_name,
                        output_path=output_path
                    )
                    parse_method = 'MarkItDown'
                
                # Read parsing results
                md_files = list(output_path.rglob('*.md'))
                if not md_files:
                    raise Exception("No markdown files generated")
                
                md_file = md_files[0]
                with open(md_file, 'r', encoding='utf-8') as f:
                    md_content = f.read()
                
                # Process images (always process, default to base64 conversion)
                image_dir = md_file.parent / 'images'
                if image_dir.exists():
                    embed_images = os.getenv('MINERU_EMBED_IMAGES_IN_MD', 'true').lower() == 'true'
                    if embed_images or upload_images:
                        logger.info(f"🖼️ Processing images for task {task_id}")
                        md_content = process_markdown_images(md_content, image_dir, upload_images)
                        with open(md_file, 'w', encoding='utf-8') as f:
                            f.write(md_content)
                        logger.info(f"✅ Updated markdown file with processed images: {md_file}")
                
                # Upload all output files to storage
                output_key_prefix = f"{task_id}/"
                markdown_relative = md_file.relative_to(output_path)
                markdown_key = f"{output_key_prefix}{markdown_relative}"
                for file_path_obj in output_path.rglob('*'):
                    if file_path_obj.is_file():
                        relative_path = file_path_obj.relative_to(output_path)
                        storage_key = f"{output_key_prefix}{relative_path}"
                        storage.save_output_file(storage_key, file_path_obj.read_bytes())
                        logger.debug(f"Uploaded output file: {storage_key}")
                
                # Image binaries stay on disk/storage; status API rebuilds images[] from files.
                # Avoid building large base64 lists into the Celery/Redis result.
                has_image_files = bool(image_dir.exists() and any(image_dir.iterdir()))
                
                # Collect JSON file paths (if they exist)
                json_files: dict[str, str] = {}
                if parse_method == 'MinerU':
                    # Find JSON files generated by MinerU
                    base_name = Path(file_name).stem
                    auto_dir = output_path / base_name / "auto"

                    # 1) content_list.json (rich text content list)
                    content_list_json = auto_dir / f"{base_name}_content_list.json"
                    if content_list_json.exists():
                        json_storage_key = f"{output_key_prefix}{base_name}/auto/{content_list_json.name}"
                        # Already uploaded via rglob; keep key for status hydrate
                        json_files["content_list_json"] = json_storage_key

                    # 2) middle.json (layout analysis with discarded_blocks: header/footer/page_number)
                    middle_json = auto_dir / f"{base_name}_middle.json"
                    if middle_json.exists():
                        middle_storage_key = f"{output_key_prefix}{base_name}/auto/{middle_json.name}"
                        json_files["middle_json_json"] = middle_storage_key
                
                # Check if markdown content contains Base64 images
                has_base64_images = 'data:image' in md_content
                
        finally:
            # Clean up temporary input file
            try:
                if local_input_path.exists() and str(local_input_path) != file_path:
                    local_input_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to cleanup local temp file {local_input_path}: {e}")
            
            # Clean up temporary file in storage
            try:
                storage.delete_file(file_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup storage temp file {file_path}: {e}")
        
        # Return slim metadata only; status/merge hydrate bodies from storage.
        result = {
            'status': 'completed',
            'file_name': file_name,
            'backend': backend,
            'parse_method': parse_method,
            'completed_at': datetime.now().isoformat(),
            'result_path': output_key_prefix,
            'markdown_key': markdown_key,
            'data': {
                'images_uploaded': upload_images,
                'images_as_base64': has_base64_images,
                'has_images': has_image_files or has_base64_images,
            }
        }
        
        if json_files:
            result['json_files'] = json_files
        
        # Propagate page range for pagination chunks (used by merge)
        chunk_info = options.get('chunk_info') if isinstance(options, dict) else None
        if isinstance(chunk_info, dict):
            if 'start_page' in chunk_info:
                result['start_page'] = chunk_info['start_page']
            if 'end_page' in chunk_info:
                result['end_page'] = chunk_info['end_page']
        
        logger.info(f"✅ Task {task_id} completed successfully (Redis result slimmed)")
        return slim_celery_result(result)
        
    except Exception as e:
        cancelled = isinstance(e, MinerUEngineCancelled)
        if cancelled:
            logger.warning(f"🛑 Task {task_id} cancelled")
        else:
            logger.exception(f"❌ Task {task_id} failed")
        
        # Clean up temporary files
        try:
            if Path(file_path).exists():
                Path(file_path).unlink()
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup temp file {file_path}: {cleanup_error}")
        
        return {
            'status': 'cancelled' if cancelled else 'failed',
            'file_name': file_name,
            'backend': backend,
            'error_message': str(e),
            'traceback': traceback.format_exc(),
            'completed_at': datetime.now().isoformat()
        }


def _parse_with_mineru(
    file_path: Path,
    file_name: str,
    task_id: str,
    backend: str,
    options: dict,
    output_path: Path,
) -> dict:
    """
    Parse PDF and image formats using MinerU
    
    Args:
        file_path: Path to PDF file (already split if it's a chunk)
        file_name: Original file name
        task_id: Task ID
        backend: MinerU backend
        options: Parsing options
        output_path: Output directory
    """
    if not MINERU_AVAILABLE:
        raise RuntimeError("MinerU is not available. Please install it.")
    
    logger.info(f"📄 Using MinerU to parse: {file_name}")
    logger.debug(f"MinerU options: {options}")
    timeout_seconds = celeryconfig.mineru_engine_timeout
    cancellation = TaskCancellationProbe(task_id)
    try:
        worker_heartbeat.set_stage("mineru_parse")
        mineru_engine.parse(
            file_path=file_path,
            file_name=file_name,
            backend=backend,
            options=options,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
            is_cancel_requested=cancellation.is_requested,
            on_state_change=lambda state: worker_heartbeat.set_metadata(engine=state),
        )
        worker_heartbeat.set_stage("persisting")
        return {'parser': 'MinerU', 'success': True}
    finally:
        cancellation.close()


def _parse_with_markitdown(
    file_path: Path,
    file_name: str,
    output_path: Path
) -> dict:
    """Parse documents using MarkItDown"""
    if not MARKITDOWN_AVAILABLE:
        raise RuntimeError("MarkItDown is not available. Please install it: pip install markitdown")
    
    logger.info(f"📊 Using MarkItDown to parse: {file_name}")
    
    # Create MarkItDown instance
    markitdown = MarkItDown()
    
    # Convert document using markitdown
    result = markitdown.convert(str(file_path))
    
    # Save as markdown file
    output_file = output_path / f"{Path(file_name).stem}.md"
    output_file.write_text(result.text_content, encoding='utf-8')
    
    logger.info(f"📝 Markdown saved to: {output_file}")
    
    return {'parser': 'MarkItDown', 'success': True}


# Task status query helper function
def get_task_result(task_id: str, upload_images: bool = False) -> Dict[str, Any]:
    """
    Query task result (compatible with original MinerU API format)
    
    Args:
        task_id: Celery task ID
        upload_images: Whether to upload images to MinIO
        
    Returns:
        dict: Task status and result information, compatible with original API format
    """
    try:
        # Get Celery task result
        from celery.result import AsyncResult
        result = AsyncResult(task_id, app=celery_app)
        
        # Map Celery status to original API status
        status_mapping = {
            'PENDING': 'pending',
            'STARTED': 'processing', 
            'SUCCESS': 'completed',
            'FAILURE': 'failed',
            'RETRY': 'processing',
            'REVOKED': 'cancelled'
        }
        
        api_status = status_mapping.get(result.status, result.status.lower())
        
        # Build base response (compatible with original API format)
        response = {
            'success': True,
            'task': {
                'task_id': task_id,
                'status': api_status,
                'created_at': None,  # Celery does not directly provide creation time
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
            # Task completed successfully
            task_result = result.result or {}
            response['task'].update({
                'result_path': task_result.get('result_path'),
                'file_name': task_result.get('file_name'),
                'backend': task_result.get('backend'),
                'completed_at': task_result.get('completed_at')
            })
            # Rebuild markdown/images/json from storage (Redis holds slim metadata only).
            apply_status_payload(response, task_result)
                
            # If image upload needs to be reprocessed
            if upload_images and 'data' in task_result and not task_result['data'].get('images_uploaded', False):
                # Reprocess image upload logic
                pass
                
        elif result.failed():
            # Task failed
            error_info = result.result if result.result else result.traceback
            response['task'].update({
                'error_message': str(error_info) if error_info else 'Unknown error',
                'completed_at': datetime.now().isoformat()
            })
            
        elif api_status == 'processing':
            # Task in progress, try to get progress information
            if hasattr(result, 'info') and result.info:
                progress_info = result.info
                if isinstance(progress_info, dict):
                    response['task'].update({
                        'file_name': progress_info.get('file_name'),
                        'backend': progress_info.get('backend'),
                        'started_at': progress_info.get('started_at')
                    })
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to get task result for {task_id}: {e}")
        return {
            'success': False,
            'error': f'Failed to query task: {str(e)}',
            'task': {
                'task_id': task_id,
                'status': 'unknown',
                'error_message': str(e)
            },
            'timestamp': datetime.now().isoformat()
        }


def get_queue_stats():
    """
    Get queue statistics (compatible with original API format)
    
    Returns:
        dict: Queue statistics
    """
    try:
        inspect = celery_app.control.inspect()
        
        # Get active tasks
        active_tasks = inspect.active() or {}
        active_count = sum(len(tasks) for tasks in active_tasks.values())
        
        # Get waiting tasks
        scheduled_tasks = inspect.scheduled() or {}
        pending_count = sum(len(tasks) for tasks in scheduled_tasks.values())
        
        # Get reserved tasks
        reserved_tasks = inspect.reserved() or {}
        reserved_count = sum(len(tasks) for tasks in reserved_tasks.values())
        
        return {
            'success': True,
            'stats': {
                'pending': pending_count + reserved_count,
                'processing': active_count,
                'completed': 0,  # Celery does not save completed task statistics
                'failed': 0,     # Celery does not save failed task statistics
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
        
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        return {
            'success': False,
            'error': str(e),
            'stats': {
                'pending': 0,
                'processing': 0, 
                'completed': 0,
                'failed': 0
            },
            'timestamp': datetime.now().isoformat()
        }


def list_tasks(status_filter: str = None, limit: int = 100):
    """
    Get task list (compatible with original API format)
    
    Args:
        status_filter: Status filter
        limit: Return count limit
        
    Returns:
        dict: Task list
    """
    try:
        inspect = celery_app.control.inspect()
        tasks = []
        
        # Get active tasks
        if not status_filter or status_filter == 'processing':
            active_tasks = inspect.active() or {}
            for worker, worker_tasks in active_tasks.items():
                for task in worker_tasks:
                    task_info = {
                        'task_id': task['id'],
                        'status': 'processing',
                        'worker_id': worker,
                        'file_name': task.get('kwargs', {}).get('file_name'),
                        'backend': task.get('kwargs', {}).get('backend'),
                        'started_at': task.get('time_start'),
                        'created_at': None,
                        'priority': 0
                    }
                    tasks.append(task_info)
        
        # Get waiting tasks
        if not status_filter or status_filter == 'pending':
            scheduled_tasks = inspect.scheduled() or {}
            for worker, worker_tasks in scheduled_tasks.items():
                for task in worker_tasks:
                    task_info = {
                        'task_id': task['request']['id'],
                        'status': 'pending',
                        'worker_id': None,
                        'file_name': task['request'].get('kwargs', {}).get('file_name'),
                        'backend': task['request'].get('kwargs', {}).get('backend'),
                        'created_at': None,
                        'started_at': None,
                        'priority': task.get('priority', 0),
                        'eta': task.get('eta')
                    }
                    tasks.append(task_info)
        
        # Limit return count
        tasks = tasks[:limit]
        
        return {
            'success': True,
            'tasks': tasks,
            'count': len(tasks),
            'limit': limit,
            'status_filter': status_filter,
            'timestamp': datetime.now().isoformat(),
            'note': 'Only active and scheduled tasks are shown. Historical tasks are not stored by default.'
        }
        
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        return {
            'success': False,
            'error': str(e),
            'tasks': [],
            'count': 0,
            'timestamp': datetime.now().isoformat()
        }

@celery_app.task(
    name='mineru.merge_chunk_results',
    bind=True,
    track_started=True
)
def merge_chunk_results_task(
    self,
    chunk_task_ids: List[str],
    file_name: str,
    backend: str = 'pipeline',
) -> Dict[str, Any]:
    """
    Merge results from multiple chunk parsing tasks
    
    Args:
        chunk_task_ids: List of chunk task IDs to merge
        file_name: Original file name
        backend: Parsing backend
        
    Returns:
        Merged parsing result dictionary
    """
    task_id = self.request.id
    logger.info(f"Starting merge task for {len(chunk_task_ids)} chunks: {file_name}")
    
    self.update_state(
        state=states.STARTED,
        meta={
            'status': 'merging',
            'file_name': file_name,
            'backend': backend,
            'chunk_count': len(chunk_task_ids),
            'started_at': datetime.now().isoformat()
        }
    )
    
    try:
        from celery.result import AsyncResult
        
        # Wait for all chunk tasks to complete
        chunk_results = []
        failed_chunks = []
        
        import time
        for chunk_task_id in chunk_task_ids:
            result = AsyncResult(chunk_task_id, app=celery_app)
            
            # Poll for result completion (avoiding result.get() which causes deadlock)
            # Use ready() check with timeout
            timeout = 3600  # 1 hour timeout per chunk
            start_time = time.time()
            while not result.ready() and (time.time() - start_time) < timeout:
                time.sleep(0.5)  # Poll every 0.5 seconds
            
            if not result.ready():
                failed_chunks.append({
                    'task_id': chunk_task_id,
                    'error': f'Task timeout after {timeout} seconds'
                })
                logger.error(f"Chunk task {chunk_task_id} timed out")
                continue
            
            # Task is ready, check result
            try:
                if result.successful():
                    chunk_result = hydrate_celery_result(result.result or {})
                    if chunk_result.get('status') == 'failed':
                        failed_chunks.append({
                            'task_id': chunk_task_id,
                            'error': chunk_result.get('error_message', 'Unknown error')
                        })
                        logger.error(f"Chunk task {chunk_task_id} failed: {chunk_result.get('error_message')}")
                    else:
                        # Verify chunk result has required fields
                        chunk_data = chunk_result.get('data', {})
                        chunk_content = chunk_data.get('content', '')
                        
                        # Get page range from task metadata (chunk_info in options)
                        chunk_start = -1
                        chunk_end = -1
                        
                        # Try to get from task metadata
                        task_info = result.info if hasattr(result, 'info') else {}
                        if isinstance(task_info, dict):
                            # Check if chunk_info is in options
                            task_kwargs = task_info.get('kwargs', {})
                            options = task_kwargs.get('options', {})
                            chunk_info = options.get('chunk_info', {})
                            if chunk_info:
                                chunk_start = chunk_info.get('start_page', 1)
                                chunk_end = chunk_info.get('end_page', 1)
                                # Update chunk_result with page info for consistency
                                chunk_result['start_page'] = chunk_start
                                chunk_result['end_page'] = chunk_end
                        
                        # If still not found, try to get from result (backward compatibility)
                        if chunk_start == -1 or chunk_end == -1:
                            chunk_start = chunk_result.get('start_page', 1)
                            chunk_end = chunk_result.get('end_page', 1)
                        
                        # Verify content is not None and not empty
                        if chunk_content is None:
                            logger.error(f"❌ CRITICAL: Chunk {chunk_task_id} (pages {chunk_start}-{chunk_end}) has None content!")
                        elif not chunk_content:
                            logger.warning(f"⚠️ Chunk {chunk_task_id} (pages {chunk_start}-{chunk_end}) has empty content")
                        else:
                            # Log content preview for verification
                            if len(chunk_content) > 200:
                                preview = chunk_content[:100] + "..." + chunk_content[-100:]
                            else:
                                preview = chunk_content
                            logger.debug(f"📄 Chunk {chunk_task_id} content preview: '{preview}'")
                        
                        logger.info(f"✅ Chunk {chunk_task_id} (pages {chunk_start}-{chunk_end}): content_length={len(chunk_content) if chunk_content else 0}, has_content_list={chunk_result.get('content_list') is not None}, has_images={len(chunk_data.get('images', []))}")
                        # Keep hydrated payload for merge (avoids a second storage reload).
                        chunk_result['start_page'] = chunk_start
                        chunk_result['end_page'] = chunk_end
                        chunk_results.append(chunk_result)
                elif result.failed():
                    error_msg = str(result.result) if result.result else 'Unknown error'
                    failed_chunks.append({
                        'task_id': chunk_task_id,
                        'error': error_msg
                    })
                    logger.error(f"Chunk task {chunk_task_id} failed: {error_msg}")
                else:
                    # Task is in an unexpected state
                    failed_chunks.append({
                        'task_id': chunk_task_id,
                        'error': f'Task in state: {result.state}'
                    })
                    logger.error(f"Chunk task {chunk_task_id} in unexpected state: {result.state}")
            except Exception as e:
                failed_chunks.append({
                    'task_id': chunk_task_id,
                    'error': str(e)
                })
                logger.error(f"Failed to process result for chunk task {chunk_task_id}: {e}")
        
        if not chunk_results:
            raise Exception(f"All {len(chunk_task_ids)} chunks failed. First error: {failed_chunks[0]['error'] if failed_chunks else 'Unknown'}")

        return _merge_chunk_results_from_results(
            chunk_results=chunk_results,
            file_name=file_name,
            backend=backend,
            task_id=task_id,
        )
        
    except Exception as e:
        logger.exception(f"❌ Merge task {task_id} failed")
        return {
            'status': 'failed',
            'file_name': file_name,
            'backend': backend,
            'error_message': str(e),
            'traceback': traceback.format_exc(),
            'completed_at': datetime.now().isoformat()
        }


if __name__ == "__main__":
    worker_heartbeat.start()
    print("🚀 Starting MinerU Celery Worker...")
    print(f"🏷️  Worker Name: {celeryconfig.WORKER_NAME}")
    print(f"📋 Queue: {celeryconfig.task_default_queue}")
    print(f"🔗 Broker: {celeryconfig.broker_url}")
    print(f"💾 Backend: {celeryconfig.result_backend}")
    print(f"⚙️  Concurrency: {celeryconfig.WORKER_CONCURRENCY}")
    worker_pool = celeryconfig.WORKER_POOL or 'prefork'
    print(f"🧵 Pool: {worker_pool}")
    print(f"⚠️  Note: This worker does NOT provide API")
    print()

    worker_args = [
        'worker',
        '--loglevel=INFO',
        '-n', f'{celeryconfig.WORKER_NAME}@%h',
        '-Q', celeryconfig.task_default_queue,
        f'--concurrency={celeryconfig.WORKER_CONCURRENCY}',
        f'--max-memory-per-child={celeryconfig.worker_max_memory_per_child}'
    ]

    if celeryconfig.WORKER_POOL:
        worker_args.append(f'--pool={celeryconfig.WORKER_POOL}')

    celery_app.worker_main(worker_args)
