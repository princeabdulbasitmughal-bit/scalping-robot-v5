#!/usr/bin/env python3
"""
Auto-Backup & Git Sync Daemon for Scalping Robot V5.

Key Features:
1. Runs in an infinite loop with 30-minute sleep between backups.
2. Creates E:\\scalping-robot-v5\\backups\\ directory if not exists.
3. Every 30 minutes, copies the following files with timestamp suffix YYYYMMDD_HHMMSS:
   - python_engine\\mt5_live_trader.py
   - live_status.json (if exists)
   - analytics.json (if exists)
4. Keeps only the last 10 backups (deletes oldest).
5. Every 2 hours (every 4th cycle), runs git commit and push:
   - git add -A
   - git commit -m "Auto-backup {timestamp}"
   - git push
6. Logs all operations to E:\\scalping-robot-v5\\backup.log.
7. Handles all errors with try/except blocks.
"""

import os
import sys
import time
import shutil
import logging
import argparse
import subprocess
from datetime import datetime
from collections import defaultdict

# Base paths
REPO_DIR = r"E:\scalping-robot-v5"
BACKUPS_DIR = os.path.join(REPO_DIR, "backups")
LOG_FILE = os.path.join(REPO_DIR, "backup.log")

# Configuration
BACKUP_INTERVAL_SECONDS = 30 * 60  # 30 minutes
GIT_SYNC_EVERY_N_CYCLES = 4        # Every 4th cycle = 2 hours
MAX_BACKUPS_TO_KEEP = 10           # Keep only last 10 backups

# Target files to backup (relative to REPO_DIR)
FILES_TO_BACKUP = [
    os.path.join("python_engine", "mt5_live_trader.py"),
    "live_status.json",
    "analytics.json",
]

# Configure logging
handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if sys.stdout is not None:
    handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=handlers
)
logger = logging.getLogger("AutoBackup")


def ensure_backup_dir():
    """Ensure backups directory exists."""
    try:
        if not os.path.exists(BACKUPS_DIR):
            os.makedirs(BACKUPS_DIR, exist_ok=True)
            logger.info(f"Created backups directory: {BACKUPS_DIR}")
    except Exception as e:
        logger.error(f"Error creating backups directory {BACKUPS_DIR}: {e}", exc_info=True)


def cleanup_old_backups(backups_dir=BACKUPS_DIR, keep_last=MAX_BACKUPS_TO_KEEP):
    """
    Keep only the last `keep_last` backups (delete oldest).
    Groups files by timestamp suffix YYYYMMDD_HHMMSS.
    """
    try:
        if not os.path.exists(backups_dir):
            return

        import re
        ts_pattern = re.compile(r"(\d{8}_\d{6})")
        timestamp_groups = defaultdict(list)

        for item in os.listdir(backups_dir):
            item_path = os.path.join(backups_dir, item)
            match = ts_pattern.search(item)
            if match:
                ts = match.group(1)
                timestamp_groups[ts].append(item_path)

        sorted_timestamps = sorted(timestamp_groups.keys())
        total_snapshots = len(sorted_timestamps)

        if total_snapshots > keep_last:
            excess_count = total_snapshots - keep_last
            old_timestamps = sorted_timestamps[:excess_count]
            logger.info(f"Total backup snapshots ({total_snapshots}) exceeds limit ({keep_last}). Purging {excess_count} oldest snapshot(s)...")

            for ts in old_timestamps:
                for file_path in timestamp_groups[ts]:
                    try:
                        if os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                        else:
                            os.remove(file_path)
                        logger.info(f"Deleted old backup: {os.path.basename(file_path)}")
                    except Exception as e:
                        logger.error(f"Error deleting old backup file {file_path}: {e}")
        else:
            logger.info(f"Backup retention check: {total_snapshots}/{keep_last} snapshots stored. No purging needed.")
    except Exception as e:
        logger.error(f"Error during backup cleanup: {e}", exc_info=True)


def run_git_sync(repo_dir=REPO_DIR, timestamp=""):
    """
    Run git sync operations:
    1. git add -A
    2. git commit -m "Auto-backup {timestamp}"
    3. git push
    """
    try:
        logger.info(f"Starting Git synchronization for commit 'Auto-backup {timestamp}'...")

        # 1. git add -A
        logger.info("Executing: git add -A")
        res_add = subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_dir,
            capture_output=True,
            text=True
        )
        logger.info(f"git add exit code: {res_add.returncode}")
        if res_add.stdout.strip():
            logger.info(f"git add stdout: {res_add.stdout.strip()}")
        if res_add.stderr.strip():
            logger.warning(f"git add stderr: {res_add.stderr.strip()}")

        # 2. git commit -m f"Auto-backup {timestamp}"
        commit_msg = f"Auto-backup {timestamp}"
        logger.info(f"Executing: git commit -m \"{commit_msg}\"")
        res_commit = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo_dir,
            capture_output=True,
            text=True
        )
        logger.info(f"git commit exit code: {res_commit.returncode}")
        if res_commit.stdout.strip():
            logger.info(f"git commit stdout: {res_commit.stdout.strip()}")
        if res_commit.stderr.strip():
            logger.warning(f"git commit stderr: {res_commit.stderr.strip()}")

        # 3. git push
        logger.info("Executing: git push")
        res_push = subprocess.run(
            ["git", "push"],
            cwd=repo_dir,
            capture_output=True,
            text=True
        )
        logger.info(f"git push exit code: {res_push.returncode}")
        if res_push.stdout.strip():
            logger.info(f"git push stdout: {res_push.stdout.strip()}")
        if res_push.stderr.strip():
            logger.warning(f"git push stderr: {res_push.stderr.strip()}")

        logger.info("Git synchronization completed successfully.")
    except Exception as e:
        logger.error(f"Error during git sync: {e}", exc_info=True)


def perform_backup_cycle(cycle_count):
    """Perform a single backup cycle."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info(f"========== Starting Backup Cycle #{cycle_count} [{timestamp}] ==========")

    ensure_backup_dir()

    # Copy files with timestamp suffix
    copied_count = 0
    for rel_path in FILES_TO_BACKUP:
        src_path = os.path.join(REPO_DIR, rel_path)
        if os.path.exists(src_path):
            try:
                base_name = os.path.basename(rel_path)
                stem, ext = os.path.splitext(base_name)
                dst_name = f"{stem}_{timestamp}{ext}"
                dst_path = os.path.join(BACKUPS_DIR, dst_name)

                shutil.copy2(src_path, dst_path)
                size_kb = os.path.getsize(dst_path) / 1024.0
                logger.info(f"Successfully copied: {rel_path} -> backups\\{dst_name} ({size_kb:.2f} KB)")
                copied_count += 1
            except Exception as e:
                logger.error(f"Error copying {rel_path}: {e}", exc_info=True)
        else:
            logger.info(f"File skipped (not found): {rel_path}")

    logger.info(f"Copied {copied_count} file(s) for cycle #{cycle_count}.")

    # Cleanup old backups (keep only last 10)
    cleanup_old_backups(BACKUPS_DIR, keep_last=MAX_BACKUPS_TO_KEEP)

    # Every 2 hours (every 4th cycle): run git commit
    if cycle_count % GIT_SYNC_EVERY_N_CYCLES == 0:
        logger.info(f"Cycle #{cycle_count} reached 2-hour interval (every {GIT_SYNC_EVERY_N_CYCLES}th cycle). Triggering git commit & push.")
        run_git_sync(REPO_DIR, timestamp)
    else:
        remaining = GIT_SYNC_EVERY_N_CYCLES - (cycle_count % GIT_SYNC_EVERY_N_CYCLES)
        logger.info(f"Git sync scheduled in {remaining} cycle(s).")

    logger.info(f"========== Completed Backup Cycle #{cycle_count} ==========")


def main():
    parser = argparse.ArgumentParser(description="Auto-Backup & Git Sync Daemon for Scalping Robot V5")
    parser.add_argument("--once", action="store_true", help="Run a single backup cycle and exit immediately (useful for testing)")
    args = parser.parse_args()

    logger.info("Auto-Backup & Git Sync Daemon initializing...")
    logger.info(f"Target repository: {REPO_DIR}")
    logger.info(f"Backups directory: {BACKUPS_DIR}")
    logger.info(f"Backup interval: {BACKUP_INTERVAL_SECONDS / 60:.0f} minutes")
    logger.info(f"Git sync interval: every {GIT_SYNC_EVERY_N_CYCLES} cycles ({GIT_SYNC_EVERY_N_CYCLES * BACKUP_INTERVAL_SECONDS / 3600:.1f} hours)")
    logger.info(f"Retention limit: keep last {MAX_BACKUPS_TO_KEEP} backups")

    cycle_count = 1

    if args.once:
        logger.info("Running in single-execution mode (--once)...")
        try:
            perform_backup_cycle(cycle_count)
        except Exception as e:
            logger.error(f"Fatal error in single backup cycle: {e}", exc_info=True)
            sys.exit(1)
        logger.info("Single backup cycle finished successfully.")
        return

    logger.info("Entering continuous backup loop...")
    while True:
        try:
            perform_backup_cycle(cycle_count)
        except KeyboardInterrupt:
            logger.info("Auto-backup daemon interrupted by user (KeyboardInterrupt). Exiting.")
            break
        except Exception as e:
            logger.error(f"Unhandled exception in backup cycle #{cycle_count}: {e}", exc_info=True)

        cycle_count += 1
        logger.info(f"Sleeping for {BACKUP_INTERVAL_SECONDS} seconds ({BACKUP_INTERVAL_SECONDS / 60:.0f} minutes)...")
        try:
            time.sleep(BACKUP_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("Auto-backup daemon interrupted during sleep. Exiting.")
            break


if __name__ == "__main__":
    main()
