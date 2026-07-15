# -*- coding: utf-8 -*-
"""
MinerU Storage Adapter
Unified storage abstraction layer supporting local filesystem and S3-compatible storage

Supports two storage modes:
- local: Use local filesystem (shared via Docker volume)
- s3: Use S3-compatible storage (e.g., MinIO), supports distributed deployment
"""
import os
import tempfile
from pathlib import Path
from typing import Optional, BinaryIO, Union, List
from contextlib import contextmanager
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

# Storage type: local or s3
STORAGE_TYPE = os.getenv('MINERU_STORAGE_TYPE', 'local').lower()

# S3 configuration (only used when STORAGE_TYPE=s3)
S3_ENDPOINT = os.getenv('MINERU_S3_ENDPOINT', '')
S3_ACCESS_KEY = os.getenv('MINERU_S3_ACCESS_KEY', '')
S3_SECRET_KEY = os.getenv('MINERU_S3_SECRET_KEY', '')
S3_BUCKET_TEMP = os.getenv('MINERU_S3_BUCKET_TEMP', 'mineru-temp')
S3_BUCKET_OUTPUT = os.getenv('MINERU_S3_BUCKET_OUTPUT', 'mineru-output')
S3_SECURE = os.getenv('MINERU_S3_SECURE', 'false').lower() == 'true'
S3_REGION = os.getenv('MINERU_S3_REGION', '')

# Export S3 configuration constants for use by other modules
__all__ = ['STORAGE_TYPE', 'S3_ENDPOINT', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 
           'S3_BUCKET_TEMP', 'S3_BUCKET_OUTPUT', 'S3_SECURE', 'S3_REGION',
           'TEMP_DIR', 'OUTPUT_DIR', 'StorageAdapter', 'get_storage']

# Local path configuration (only used when STORAGE_TYPE=local)
TEMP_DIR = os.getenv('TEMP_DIR', '/tmp/mineru_temp')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', '/tmp/mineru_output')


class StorageAdapter:
    """Unified storage adapter interface"""
    
    def __init__(self):
        self.storage_type = STORAGE_TYPE
        self._fs = None
        self._init_storage()
    
    def _init_storage(self):
        """Initialize storage backend"""
        if self.storage_type == 's3':
            try:
                import s3fs
                s3_kwargs = {
                    'key': S3_ACCESS_KEY,
                    'secret': S3_SECRET_KEY,
                    'endpoint_url': S3_ENDPOINT,
                }
                client_kwargs = {}
                if S3_REGION:
                    client_kwargs['region_name'] = S3_REGION
                if S3_ENDPOINT.startswith('https'):
                    client_kwargs['use_ssl'] = True
                else:
                    client_kwargs['use_ssl'] = S3_SECURE
                if client_kwargs:
                    s3_kwargs['client_kwargs'] = client_kwargs
                
                self._fs = s3fs.S3FileSystem(**s3_kwargs)
                # Ensure buckets exist
                self._ensure_bucket_exists(S3_BUCKET_TEMP)
                self._ensure_bucket_exists(S3_BUCKET_OUTPUT)
            except ImportError:
                raise ImportError("s3fs is required for S3 storage. Install with: pip install s3fs")
            except Exception as e:
                raise RuntimeError(f"Failed to initialize S3 storage: {e}")
        elif self.storage_type == 'local':
            # Ensure local directories exist
            Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
            Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        else:
            raise ValueError(f"Unsupported storage type: {self.storage_type}")
    
    def _ensure_bucket_exists(self, bucket_name: str):
        """Ensure S3 bucket exists"""
        if self.storage_type != 's3':
            return
        try:
            if not self._fs.exists(bucket_name):
                self._fs.mkdir(bucket_name)
        except Exception as e:
            # Ignore if bucket already exists or other errors
            pass
    
    def _get_temp_path(self, key: str) -> str:
        """Get temporary file path (S3 key or local path)"""
        if self.storage_type == 's3':
            return f"{S3_BUCKET_TEMP}/{key}"
        else:
            return str(Path(TEMP_DIR) / key)
    
    def _get_output_path(self, key: str) -> str:
        """Get output file path (S3 key or local path)"""
        if self.storage_type == 's3':
            return f"{S3_BUCKET_OUTPUT}/{key}"
        else:
            return str(Path(OUTPUT_DIR) / key)
    
    def save_temp_file(self, key: str, data: Union[bytes, BinaryIO]) -> str:
        """
        Save temporary file
        
        Args:
            key: File identifier (e.g., task_id/filename)
            data: File data (bytes or file object)
            
        Returns:
            File path (for subsequent operations)
        """
        path = self._get_temp_path(key)
        
        if self.storage_type == 's3':
            if isinstance(data, bytes):
                self._fs.write_bytes(path, data)
            else:
                # File object
                data.seek(0)
                with self._fs.open(path, 'wb') as f:
                    f.write(data.read())
        else:
            # Local filesystem
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                file_path.write_bytes(data)
            else:
                # File object
                data.seek(0)
                with open(file_path, 'wb') as f:
                    f.write(data.read())
        
        return path
    
    def save_output_file(self, key: str, data: Union[bytes, BinaryIO]) -> str:
        """
        Save output file
        
        Args:
            key: File identifier (e.g., task_id/filename)
            data: File data (bytes or file object)
            
        Returns:
            File path (for subsequent operations)
        """
        path = self._get_output_path(key)
        
        if self.storage_type == 's3':
            if isinstance(data, bytes):
                self._fs.write_bytes(path, data)
            else:
                # File object
                data.seek(0)
                with self._fs.open(path, 'wb') as f:
                    f.write(data.read())
        else:
            # Local filesystem
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                file_path.write_bytes(data)
            else:
                # File object
                data.seek(0)
                with open(file_path, 'wb') as f:
                    f.write(data.read())
        
        return path
    
    def read_file(self, path: str) -> bytes:
        """
        Read file
        
        Args:
            path: File path (S3 key or local path)
            
        Returns:
            File content (bytes)
        """
        if self.storage_type == 's3':
            return self._fs.read_bytes(path)
        else:
            return Path(path).read_bytes()
    
    @contextmanager
    def open_file(self, path: str, mode: str = 'rb'):
        """
        Open file (context manager)
        
        Args:
            path: File path (S3 key or local path)
            mode: Open mode ('rb' or 'wb')
        """
        if self.storage_type == 's3':
            with self._fs.open(path, mode) as f:
                yield f
        else:
            with open(path, mode) as f:
                yield f
    
    def file_exists(self, path: str) -> bool:
        """Check if file exists"""
        if self.storage_type == 's3':
            return self._fs.exists(path)
        else:
            return Path(path).exists()
    
    def delete_file(self, path: str) -> bool:
        """
        Delete file
        
        Returns:
            Whether deletion was successful
        """
        try:
            if self.storage_type == 's3':
                self._fs.rm(path, recursive=False)
            else:
                Path(path).unlink()
            return True
        except Exception:
            return False
    
    def delete_directory(self, path: str) -> bool:
        """
        Delete directory (recursive)
        
        Returns:
            Whether deletion was successful
        """
        try:
            if self.storage_type == 's3':
                # Delete all objects with path as prefix in S3
                if self._fs.exists(path):
                    self._fs.rm(path, recursive=True)
            else:
                import shutil
                if Path(path).exists():
                    shutil.rmtree(path)
            return True
        except Exception:
            return False
    
    def list_files(self, prefix: str) -> List[str]:
        """
        List files matching prefix
        
        Args:
            prefix: Path prefix
            
        Returns:
            List of file paths
        """
        if self.storage_type == 's3':
            return [f for f in self._fs.find(prefix) if self._fs.isfile(f)]
        else:
            prefix_path = Path(prefix)
            if prefix_path.is_dir():
                return [str(p) for p in prefix_path.rglob('*') if p.is_file()]
            else:
                return []
    
    def download_to_local(self, remote_path: str, local_path: Optional[str] = None) -> str:
        """
        Download file to local temporary file (for operations requiring local file path)
        
        Args:
            remote_path: Remote file path (S3 key or local path)
            local_path: Local save path (optional, defaults to temporary file)
            
        Returns:
            Local file path
        """
        if self.storage_type == 'local':
            # Local storage directly returns path
            return remote_path
        
        # S3 storage needs to download to local. Preserve the remote suffix so
        # callers that inspect Path(...).suffix (e.g. get_file_type) still work.
        if local_path is None:
            suffix = Path(remote_path).suffix
            fd, local_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
        
        data = self.read_file(remote_path)
        Path(local_path).write_bytes(data)
        return local_path
    
    def upload_from_local(self, local_path: str, remote_path: str):
        """
        Upload from local file to storage
        
        Args:
            local_path: Local file path
            remote_path: Remote file path (S3 key or local path)
        """
        data = Path(local_path).read_bytes()
        if self.storage_type == 's3':
            self._fs.write_bytes(remote_path, data)
        else:
            # Local storage directly copies
            remote_file = Path(remote_path)
            remote_file.parent.mkdir(parents=True, exist_ok=True)
            remote_file.write_bytes(data)


# Global storage adapter instance
_storage_adapter: Optional[StorageAdapter] = None


def get_storage() -> StorageAdapter:
    """Get storage adapter instance (singleton pattern)"""
    global _storage_adapter
    if _storage_adapter is None:
        _storage_adapter = StorageAdapter()
    return _storage_adapter

