#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU Cleanup Scheduler
Scheduled cleanup service running in container, uses schedule library for scheduled tasks
"""
import os
import sys
import time
import signal
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project path to import shared module
# cleanup_scheduler.py is located in cleanup/ directory, needs to access parent directory's shared module
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import schedule
except ImportError:
    print("Error: schedule library is required")
    print("Please run: pip install schedule")
    sys.exit(1)

import argparse
import subprocess


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Warning: invalid {name}={raw!r}, using default {default}")
        return default


# Defaults keep orphaned temps short while staying above TASK_TIME_LIMIT (2h).
DEFAULT_CLEANUP_INTERVAL_HOURS = 6
DEFAULT_CLEANUP_EXTRA_HOURS = 2
DEFAULT_TEMP_MAX_AGE_HOURS = 6


class CleanupScheduler:
    """Cleanup task scheduler"""
    
    def __init__(
        self,
        cleanup_hours: int = DEFAULT_CLEANUP_INTERVAL_HOURS,
        extra_hours: int = DEFAULT_CLEANUP_EXTRA_HOURS,
        temp_max_age_hours: int = DEFAULT_TEMP_MAX_AGE_HOURS,
    ):
        """
        Initialize scheduler
        
        Args:
            cleanup_hours: Cleanup task execution interval (hours)
            extra_hours: Extra retention time (hours) for output files
            temp_max_age_hours: Max age for local temporary files (hours)
        """
        self.cleanup_hours = cleanup_hours
        self.extra_hours = extra_hours
        self.temp_max_age_hours = temp_max_age_hours
        self.running = True
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _build_cleanup_cmd(self) -> list:
        script_path = Path(__file__).parent / 'cleanup_outputs.py'
        storage_type = os.getenv('MINERU_STORAGE_TYPE', 'local').lower()
        cmd = [
            sys.executable,
            str(script_path),
            '--extra-hours',
            str(self.extra_hours),
            '--temp-max-age',
            str(self.temp_max_age_hours),
        ]
        if storage_type == 's3':
            # Temporary files handled by S3 lifecycle policy
            cmd.append('--output-only')
            print(
                "Detected S3 storage mode, only cleaning output files "
                "(temporary files handled by S3 lifecycle policy)"
            )
        else:
            print("Detected local storage mode, cleaning temporary files and output files")
        return cmd
    
    def _signal_handler(self, signum, frame):
        """Handle exit signal"""
        print(f"\nReceived signal {signum}, stopping scheduler...")
        self.running = False
    
    def _run_cleanup(self):
        """Execute cleanup task"""
        print(f"\n{'='*60}")
        print(f"Executing scheduled cleanup task - {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        cmd = self._build_cleanup_cmd()
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=False,
                text=True
            )
            if result.returncode == 0:
                print("Cleanup task executed successfully")
            else:
                print(f"Cleanup task execution failed, exit code: {result.returncode}")
        except Exception as e:
            print(f"Cleanup task execution failed: {e}")
    
    def start(self):
        """Start scheduler"""
        # Set scheduled task
        schedule.every(self.cleanup_hours).hours.do(self._run_cleanup)
        
        # Execute once immediately (optional)
        print(f"Cleanup scheduler started")
        print(f"Cleanup interval: every {self.cleanup_hours} hours")
        print(f"Extra retention time (outputs): {self.extra_hours} hours")
        print(f"Temp file max age: {self.temp_max_age_hours} hours")
        print(f"First cleanup will execute in {self.cleanup_hours} hours")
        print("Press Ctrl+C to stop scheduler\n")
        
        # Main loop
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
        
        print("\nScheduler stopped")


def main():
    parser = argparse.ArgumentParser(
        description='MinerU Cleanup Task Scheduler',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=_env_int('CLEANUP_INTERVAL_HOURS', DEFAULT_CLEANUP_INTERVAL_HOURS),
        help=f'Cleanup task execution interval (hours, default: {DEFAULT_CLEANUP_INTERVAL_HOURS})'
    )
    parser.add_argument(
        '--extra-hours',
        type=int,
        default=_env_int('CLEANUP_EXTRA_HOURS', DEFAULT_CLEANUP_EXTRA_HOURS),
        help=f'Extra retention time for outputs (hours, default: {DEFAULT_CLEANUP_EXTRA_HOURS})'
    )
    parser.add_argument(
        '--temp-max-age',
        type=int,
        default=_env_int('TEMP_MAX_AGE_HOURS', DEFAULT_TEMP_MAX_AGE_HOURS),
        help=f'Maximum retention for local temp files (hours, default: {DEFAULT_TEMP_MAX_AGE_HOURS})'
    )
    parser.add_argument(
        '--run-once',
        action='store_true',
        help='Execute cleanup task once only, do not start scheduler'
    )
    
    args = parser.parse_args()
    
    if args.run_once:
        # Execute once only
        print("Executing single cleanup task...")
        scheduler = CleanupScheduler(
            cleanup_hours=args.interval,
            extra_hours=args.extra_hours,
            temp_max_age_hours=args.temp_max_age,
        )
        cmd = scheduler._build_cleanup_cmd()
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=False,
                text=True
            )
            sys.exit(result.returncode)
        except Exception as e:
            print(f"Cleanup task execution failed: {e}")
            sys.exit(1)
    else:
        # Start scheduler
        scheduler = CleanupScheduler(
            cleanup_hours=args.interval,
            extra_hours=args.extra_hours,
            temp_max_age_hours=args.temp_max_age,
        )
        scheduler.start()


if __name__ == '__main__':
    main()

