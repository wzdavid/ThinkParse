#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU Output Cleanup Script
Periodically clean up expired output files based on RESULT_EXPIRES configuration

Usage:
    # Preview mode (no actual deletion)
    python cleanup_outputs.py --dry-run
    
    # Actual cleanup
    python cleanup_outputs.py
    
    # Clean output directory only
    python cleanup_outputs.py --output-only
    
    # Clean temporary directory only
    python cleanup_outputs.py --temp-only
    
    # Extra retention of 2 hours
    python cleanup_outputs.py --extra-hours 2
"""
import os
import sys
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import argparse
import logging

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Add project path to import shared module
# cleanup_outputs.py is located in cleanup/ directory, needs to access parent directory's shared module
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from shared import celeryconfig
    from shared.storage import get_storage
except ImportError:
    print("Error: Cannot import shared.celeryconfig module")
    print(f"Please ensure running this script in {project_root} directory")
    sys.exit(1)


def format_size(size_bytes: int) -> str:
    """Format file size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def get_dir_size(path: Path) -> int:
    """Calculate total directory size (bytes)"""
    total = 0
    try:
        for item in path.rglob('*'):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except (OSError, FileNotFoundError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


def cleanup_expired_outputs(dry_run: bool = False, extra_hours: int = 0):
    """
    Clean up expired output files
    
    Args:
        dry_run: If True, only show files to be deleted without actually deleting
        extra_hours: Extra retention time (hours) for safety buffer
    """
    storage = get_storage()
    
    # Check storage type
    if storage.storage_type == 's3':
        # S3 storage cleanup
        _cleanup_s3_outputs(storage, dry_run, extra_hours)
    else:
        # Local storage cleanup
        output_dir = Path(celeryconfig.OUTPUT_DIR)
        if not output_dir.exists():
            print(f"Output directory does not exist: {output_dir}")
            return
        _cleanup_local_outputs(output_dir, dry_run, extra_hours)


def _cleanup_local_outputs(output_dir: Path, dry_run: bool, extra_hours: int):
    """Clean up local output files"""
    
    # Get result expiration time (seconds)
    result_expires = int(os.getenv('RESULT_EXPIRES', 86400))  # Default 1 day
    expire_seconds = result_expires + (extra_hours * 3600)
    expire_time = datetime.now() - timedelta(seconds=expire_seconds)
    
    print("=" * 60)
    print("Cleaning Output Directory (Local Storage)")
    print("=" * 60)
    print(f"Output directory: {output_dir}")
    print(f"Result expiration time: {result_expires} seconds ({result_expires/3600:.1f} hours)")
    if extra_hours > 0:
        print(f"Extra retention time: {extra_hours} hours")
    print(f"Cleanup threshold: {expire_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'Preview mode (no deletion)' if dry_run else 'Deletion mode'}")
    print()
    
    deleted_count = 0
    deleted_size = 0
    kept_count = 0
    error_count = 0
    
    # Iterate through all task directories in output directory
    task_dirs = list(output_dir.iterdir())
    if not task_dirs:
        print("Output directory is empty, no cleanup needed")
        return
    
    for task_dir in task_dirs:
        if not task_dir.is_dir():
            continue
        
        try:
            # Check directory modification time
            mtime = datetime.fromtimestamp(task_dir.stat().st_mtime)
            
            if mtime < expire_time:
                # Calculate directory size
                dir_size = get_dir_size(task_dir)
                
                if dry_run:
                    print(f"  [Will delete] {task_dir.name}")
                    print(f"            Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"            Size: {format_size(dir_size)}")
                else:
                    try:
                        shutil.rmtree(task_dir)
                        print(f"  [Deleted] {task_dir.name} ({format_size(dir_size)})")
                        deleted_count += 1
                        deleted_size += dir_size
                    except Exception as e:
                        print(f"  [Delete failed] {task_dir.name}: {e}")
                        error_count += 1
            else:
                kept_count += 1
        except (OSError, PermissionError) as e:
            print(f"  [Error] Cannot access {task_dir.name}: {e}")
            error_count += 1
    
    print()
    print("-" * 60)
    if dry_run:
        print(f"Preview completed:")
        print(f"  Will delete: {deleted_count} directories")
        print(f"  Will keep: {kept_count} directories")
    else:
        print(f"Cleanup completed:")
        print(f"  Deleted: {deleted_count} directories")
        print(f"  Freed: {format_size(deleted_size)}")
        print(f"  Kept: {kept_count} directories")
        if error_count > 0:
            print(f"  Errors: {error_count} directories failed to process")
    print("=" * 60)


def _cleanup_s3_outputs(storage, dry_run: bool, extra_hours: int):
    """Clean up S3 output files"""
    from shared.storage import S3_BUCKET_OUTPUT
    import s3fs
    
    # Get result expiration time (seconds)
    result_expires = int(os.getenv('RESULT_EXPIRES', 86400))  # Default 1 day
    expire_seconds = result_expires + (extra_hours * 3600)
    expire_time = datetime.now() - timedelta(seconds=expire_seconds)
    
    print("=" * 60)
    print("Cleaning Output Directory (S3 Storage)")
    print("=" * 60)
    print(f"S3 Bucket: {S3_BUCKET_OUTPUT}")
    print(f"Result expiration time: {result_expires} seconds ({result_expires/3600:.1f} hours)")
    if extra_hours > 0:
        print(f"Extra retention time: {extra_hours} hours")
    print(f"Cleanup threshold: {expire_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'Preview mode (no deletion)' if dry_run else 'Deletion mode'}")
    print()
    
    deleted_count = 0
    deleted_size = 0
    kept_count = 0
    error_count = 0
    
    try:
        # List all task directories (prefixes in S3)
        prefix = f"{S3_BUCKET_OUTPUT}/"
        all_files = storage.list_files(prefix)
        
        # Group by task ID
        task_dirs = {}
        for file_path in all_files:
            # Extract task ID (first path segment)
            parts = file_path.replace(prefix, "").split("/")
            if parts:
                task_id = parts[0]
                if task_id not in task_dirs:
                    task_dirs[task_id] = []
                task_dirs[task_id].append(file_path)
        
        if not task_dirs:
            print("Output directory is empty, no cleanup needed")
            return
        
        for task_id, files in task_dirs.items():
            try:
                # Get task directory's latest modification time (using first file's modification time as reference)
                # Note: S3 may not provide directory modification time, here we use file's latest modification time
                latest_mtime = None
                for file_path in files:
                    try:
                        # Get file info (requires s3fs support)
                        info = storage._fs.info(file_path)
                        # s3fs may return timestamp or datetime object
                        last_modified = info.get('LastModified', 0)
                        if isinstance(last_modified, datetime):
                            file_mtime = last_modified
                        else:
                            file_mtime = datetime.fromtimestamp(last_modified)
                        if latest_mtime is None or file_mtime > latest_mtime:
                            latest_mtime = file_mtime
                    except Exception as e:
                        # Ignore files that cannot get time
                        pass
                
                if latest_mtime and latest_mtime < expire_time:
                    # Calculate directory size
                    dir_size = sum(storage._fs.info(f).get('Size', 0) for f in files)
                    
                    if dry_run:
                        print(f"  [Will delete] {task_id}")
                        print(f"            Modified: {latest_mtime.strftime('%Y-%m-%d %H:%M:%S')}")
                        print(f"            Size: {format_size(dir_size)}")
                        print(f"            File count: {len(files)}")
                    else:
                        try:
                            # Delete all files
                            for file_path in files:
                                storage.delete_file(file_path)
                            print(f"  [Deleted] {task_id} ({format_size(dir_size)}, {len(files)} files)")
                            deleted_count += 1
                            deleted_size += dir_size
                        except Exception as e:
                            print(f"  [Delete failed] {task_id}: {e}")
                            error_count += 1
                else:
                    kept_count += 1
            except Exception as e:
                print(f"  [Error] Cannot access task {task_id}: {e}")
                error_count += 1
    
    except Exception as e:
        print(f"  [Error] Failed to clean S3 output: {e}")
        error_count += 1
    
    print()
    print("-" * 60)
    if dry_run:
        print(f"Preview completed:")
        print(f"  Will delete: {deleted_count} task directories")
        print(f"  Will keep: {kept_count} task directories")
    else:
        print(f"Cleanup completed:")
        print(f"  Deleted: {deleted_count} task directories")
        print(f"  Freed: {format_size(deleted_size)}")
        print(f"  Kept: {kept_count} task directories")
        if error_count > 0:
            print(f"  Errors: {error_count} task directories failed to process")
    print("=" * 60)


def cleanup_temp_dir(dry_run: bool = False, max_age_hours: int = 6):
    """
    Clean up temporary directory
    
    Args:
        dry_run: If True, only show files to be deleted without actually deleting
        max_age_hours: Maximum retention time for temporary files (hours).
            Default 6h stays above TASK_TIME_LIMIT (2h) with headroom for orphans.
    """
    storage = get_storage()
    
    # Check storage type
    if storage.storage_type == 's3':
        # S3 storage: temporary files handled by S3 lifecycle policy, no application-level cleanup needed
        print("=" * 60)
        print("Cleaning Temporary Directory (S3 Storage)")
        print("=" * 60)
        print("ℹ️  When using S3 storage, temporary files are automatically cleaned by S3 lifecycle policy")
        print("   Recommend aligning lifecycle expiration with TEMP_MAX_AGE_HOURS (default 6h);")
        print("   many S3 providers only support day-level rules (often 1 day).")
        print("   No application-level cleanup of temporary files needed")
        print("=" * 60)
        return
    
    # Local storage: execute cleanup
    temp_dir = Path(celeryconfig.TEMP_DIR)
    if not temp_dir.exists():
        print(f"Temporary directory does not exist: {temp_dir}")
        return
    
    expire_time = datetime.now() - timedelta(hours=max_age_hours)
    
    print("=" * 60)
    print("Cleaning Temporary Directory")
    print("=" * 60)
    print(f"Temporary directory: {temp_dir}")
    print(f"Maximum retention time: {max_age_hours} hours")
    print(f"Cleanup threshold: {expire_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'Preview mode (no deletion)' if dry_run else 'Deletion mode'}")
    print()
    
    deleted_count = 0
    deleted_size = 0
    kept_count = 0
    error_count = 0
    
    items = list(temp_dir.iterdir())
    if not items:
        print("Temporary directory is empty, no cleanup needed")
        return
    
    for item in items:
        try:
            if item.is_file():
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                size = item.stat().st_size
                
                if mtime < expire_time:
                    if dry_run:
                        print(f"  [Will delete] {item.name} ({format_size(size)})")
                    else:
                        try:
                            item.unlink()
                            print(f"  [Deleted] {item.name} ({format_size(size)})")
                            deleted_count += 1
                            deleted_size += size
                        except Exception as e:
                            print(f"  [Delete failed] {item.name}: {e}")
                            error_count += 1
                else:
                    kept_count += 1
            elif item.is_dir():
                # Clean directory
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                dir_size = get_dir_size(item)
                
                if mtime < expire_time:
                    if dry_run:
                        print(f"  [Will delete] {item.name}/ ({format_size(dir_size)})")
                    else:
                        try:
                            shutil.rmtree(item)
                            print(f"  [Deleted] {item.name}/ ({format_size(dir_size)})")
                            deleted_count += 1
                            deleted_size += dir_size
                        except Exception as e:
                            print(f"  [Delete failed] {item.name}/: {e}")
                            error_count += 1
                else:
                    kept_count += 1
        except (OSError, PermissionError) as e:
            print(f"  [Error] Cannot access {item.name}: {e}")
            error_count += 1
    
    print()
    print("-" * 60)
    if dry_run:
        print(f"Preview completed:")
        print(f"  Will delete: {deleted_count} items")
        print(f"  Will keep: {kept_count} items")
    else:
        print(f"Cleanup completed:")
        print(f"  Deleted: {deleted_count} items")
        print(f"  Freed: {format_size(deleted_size)}")
        print(f"  Kept: {kept_count} items")
        if error_count > 0:
            print(f"  Errors: {error_count} items failed to process")
    print("=" * 60)


def _env_int_temp_max_age() -> int:
    raw = os.getenv('TEMP_MAX_AGE_HOURS', '6')
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 6


def main():
    parser = argparse.ArgumentParser(
        description='Clean up MinerU expired output files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview mode (no actual deletion)
  python cleanup_outputs.py --dry-run
  
  # Actual cleanup of all directories
  python cleanup_outputs.py
  
  # Clean output directory only
  python cleanup_outputs.py --output-only
  
  # Clean temporary directory only
  python cleanup_outputs.py --temp-only
  
  # Extra retention of 2 hours (safer)
  python cleanup_outputs.py --extra-hours 2
        """
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview mode, do not actually delete files'
    )
    parser.add_argument(
        '--extra-hours',
        type=int,
        default=0,
        help='Extra retention time (hours) for safety buffer (default: 0)'
    )
    parser.add_argument(
        '--temp-only',
        action='store_true',
        help='Clean temporary directory only'
    )
    parser.add_argument(
        '--output-only',
        action='store_true',
        help='Clean output directory only'
    )
    parser.add_argument(
        '--temp-max-age',
        type=int,
        default=_env_int_temp_max_age(),
        help='Maximum retention time for temporary files (hours, default: 6)'
    )
    
    args = parser.parse_args()
    
    # Execute cleanup
    if args.temp_only:
        cleanup_temp_dir(dry_run=args.dry_run, max_age_hours=args.temp_max_age)
    elif args.output_only:
        cleanup_expired_outputs(dry_run=args.dry_run, extra_hours=args.extra_hours)
    else:
        cleanup_temp_dir(dry_run=args.dry_run, max_age_hours=args.temp_max_age)
        print()
        cleanup_expired_outputs(dry_run=args.dry_run, extra_hours=args.extra_hours)


if __name__ == '__main__':
    main()

