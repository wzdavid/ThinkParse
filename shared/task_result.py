# -*- coding: utf-8 -*-
"""
Celery result helpers: keep Redis payloads small; hydrate content from storage.

Celery/Redis stores only metadata + storage keys. Status API and merge rebuild
markdown / images / content_list from OUTPUT storage so the public API is unchanged.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.storage import OUTPUT_DIR, S3_BUCKET_OUTPUT, get_storage

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff'}
_MIME_FALLBACK = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.tif': 'image/tiff',
    '.tiff': 'image/tiff',
}


def _output_storage_path(key: str) -> str:
    """Turn an output relative key into a storage path usable by StorageAdapter."""
    storage = get_storage()
    if storage.storage_type == 's3':
        return f"{S3_BUCKET_OUTPUT}/{key}"
    return str(Path(OUTPUT_DIR) / key)


def _task_id_from_result(result: Dict[str, Any]) -> Optional[str]:
    markdown_key = result.get('markdown_key')
    if isinstance(markdown_key, str) and markdown_key:
        return markdown_key.split('/', 1)[0]
    result_path = result.get('result_path')
    if isinstance(result_path, str) and result_path:
        return result_path.strip('/').split('/', 1)[0]
    json_files = result.get('json_files') or {}
    for key in json_files.values():
        if isinstance(key, str) and key:
            return key.split('/', 1)[0]
    return None


def slim_celery_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Drop large fields before Celery stores the result in Redis.

    Keeps metadata and storage keys; status handlers rehydrate for the public API.
    """
    if not isinstance(result, dict):
        return result
    if result.get('status') != 'completed':
        return result

    slim = {
        k: v
        for k, v in result.items()
        if k not in ('content_list', 'middle_json')
    }
    data = result.get('data') if isinstance(result.get('data'), dict) else {}
    slim['data'] = {
        'images_uploaded': bool(data.get('images_uploaded', False)),
        'images_as_base64': bool(data.get('images_as_base64', False)),
        'has_images': bool(data.get('has_images', False)),
    }
    return slim


def _load_text_from_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    try:
        storage = get_storage()
        path = _output_storage_path(key)
        if not storage.file_exists(path):
            return None
        return storage.read_file(path).decode('utf-8')
    except Exception as exc:
        logger.debug("Failed to load text key=%s: %s", key, exc)
        return None


def _load_json_from_key(key: Optional[str]) -> Any:
    if not key:
        return None
    try:
        storage = get_storage()
        path = _output_storage_path(key)
        if not storage.file_exists(path):
            return None
        return json.loads(storage.read_file(path).decode('utf-8'))
    except Exception as exc:
        logger.debug("Failed to load JSON key=%s: %s", key, exc)
        return None


def _discover_markdown_key(task_id: str) -> Optional[str]:
    storage = get_storage()
    prefix = _output_storage_path(task_id)
    try:
        files = storage.list_files(prefix)
    except Exception as exc:
        logger.debug("Failed to list output for task %s: %s", task_id, exc)
        return None

    md_files = sorted(f for f in files if f.lower().endswith('.md'))
    if not md_files:
        return None

    chosen = md_files[0]
    if storage.storage_type == 's3':
        prefix_len = len(S3_BUCKET_OUTPUT.rstrip('/')) + 1
        return chosen[prefix_len:] if chosen.startswith(S3_BUCKET_OUTPUT) else chosen
    try:
        return str(Path(chosen).relative_to(OUTPUT_DIR))
    except ValueError:
        return chosen


def _load_images_for_task(task_id: str) -> List[Dict[str, Any]]:
    storage = get_storage()
    prefix = _output_storage_path(task_id)
    try:
        files = storage.list_files(prefix)
    except Exception as exc:
        logger.debug("Failed to list images for task %s: %s", task_id, exc)
        return []

    images: List[Dict[str, Any]] = []
    for path in sorted(files):
        normalized = path.replace('\\', '/')
        if '/images/' not in normalized:
            continue
        name = Path(normalized).name
        suffix = Path(name).suffix.lower()
        if suffix not in _IMAGE_EXTENSIONS:
            continue
        try:
            img_data = storage.read_file(path)
        except Exception as exc:
            logger.warning("Failed to read image %s: %s", path, exc)
            continue
        mime_type, _ = mimetypes.guess_type(name)
        if not mime_type or not mime_type.startswith('image/'):
            mime_type = _MIME_FALLBACK.get(suffix, 'image/png')
        data_url = f"data:{mime_type};base64,{base64.b64encode(img_data).decode('utf-8')}"
        images.append({
            'filename': name,
            'mime_type': mime_type,
            'size_bytes': len(img_data),
            'data_url': data_url,
        })
    return images


def hydrate_celery_result(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Rebuild full payloads expected by status API / merge from storage keys.

    Supports legacy results that already contain data.content (no-op for body).
    Returns a deep copy so Redis-backed objects are not mutated in place.
    """
    if not isinstance(result, dict):
        return {}
    hydrated = deepcopy(result)
    if hydrated.get('status') != 'completed':
        return hydrated

    data = hydrated.get('data') if isinstance(hydrated.get('data'), dict) else {}
    hydrated['data'] = data

    if not data.get('content'):
        markdown_key = hydrated.get('markdown_key')
        task_id = _task_id_from_result(hydrated)
        if not markdown_key and task_id:
            markdown_key = _discover_markdown_key(task_id)
            if markdown_key:
                hydrated['markdown_key'] = markdown_key
        content = _load_text_from_key(markdown_key)
        if content is not None:
            data['content'] = content

    # ThinkExtract / ThinkDoc expect independent images[] with data_url
    if 'images' not in data or data.get('images') is None:
        task_id = _task_id_from_result(hydrated)
        if task_id:
            images = _load_images_for_task(task_id)
            data['images'] = images
            data['has_images'] = bool(images) or bool(data.get('has_images'))
        else:
            data.setdefault('images', [])

    json_files = hydrated.get('json_files') if isinstance(hydrated.get('json_files'), dict) else {}
    if 'content_list' not in hydrated and json_files.get('content_list_json'):
        content_list = _load_json_from_key(json_files.get('content_list_json'))
        if content_list is not None:
            hydrated['content_list'] = content_list
    if 'middle_json' not in hydrated and json_files.get('middle_json_json'):
        middle_json = _load_json_from_key(json_files.get('middle_json_json'))
        if middle_json is not None:
            hydrated['middle_json'] = middle_json

    return hydrated


def apply_status_payload(response: Dict[str, Any], task_result: Dict[str, Any]) -> None:
    """Fill public status fields from a (possibly slim) Celery result."""
    hydrated = hydrate_celery_result(task_result)
    data = hydrated.get('data') if isinstance(hydrated.get('data'), dict) else {}

    if data.get('content') is not None:
        response['markdown_content'] = data.get('content')

    return_images = os.getenv('MINERU_RETURN_IMAGES_BASE64', 'true').lower() == 'true'
    response['images'] = (data.get('images') or []) if return_images else []

    if 'content_list' in hydrated:
        response['content_list'] = hydrated['content_list']
    if 'middle_json' in hydrated:
        response['middle_json'] = hydrated['middle_json']
    if 'json_files' in hydrated:
        response['json_files'] = hydrated['json_files']
