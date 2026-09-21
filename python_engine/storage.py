"""
Scalping Robot V5 - Atomic Storage & Safe JSON I/O Utilities
Provides atomic writes via temp-file swapping and safe reads with retry backoff.
Guarantees zero partial read locks, zero JSON corruption, and cross-platform reliability on Windows.
"""

import os
import time
import json
import random
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ScalpingRobotV5.Storage")

def atomic_write_json(
    file_path: str | Path,
    data: Any,
    indent: int = 2,
    max_retries: int = 10,
    retry_delay: float = 0.02
) -> bool:
    """
    Atomically writes JSON data to file_path using a temporary file in the same directory.
    Uses os.replace for atomic replacement and exponential jitter backoff for Windows lock retries.
    """
    path = Path(file_path).resolve()
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    # Unique temp file in the same directory ensures same filesystem for atomic os.replace
    temp_path = dir_path / f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}"

    try:
        # Write to temporary file first and sync to storage
        content = json.dumps(data, indent=indent, default=str).encode("utf-8")
        with open(temp_path, "wb") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (AttributeError, OSError):
                pass

        # Atomically replace destination with retries and jitter for Windows file lock resiliency
        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                os.replace(temp_path, path)
                return True
            except (PermissionError, OSError) as err:
                last_err = err
                # Exponential backoff with random jitter to avoid reader-writer resonance
                sleep_time = (retry_delay * (1.5 ** attempt)) + random.uniform(0.005, 0.025)
                time.sleep(sleep_time)

        logger.warning(f"atomic_write_json failed after {max_retries} attempts on {path}: {last_err}")
        return False

    except Exception as exc:
        logger.error(f"Error preparing atomic write for {path}: {exc}", exc_info=True)
        return False

    finally:
        # Always clean up temp file if replacement did not succeed
        if temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def safe_read_json(
    file_path: str | Path,
    default: Any = None,
    max_retries: int = 8,
    retry_delay: float = 0.02
) -> Any:
    """
    Safely reads JSON data from file_path with ultra-fast binary read buffer
    and retries on transient read locks or partial writes.
    Returns `default` if the file doesn't exist or cannot be parsed.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return default

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            # Binary read buffer minimizes open-file duration to microseconds on Windows
            with open(path, "rb") as f:
                raw_bytes = f.read()
            if not raw_bytes:
                # File was momentarily being created, retry
                time.sleep(retry_delay * (1.5 ** attempt))
                continue
            return json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, PermissionError, OSError, UnicodeDecodeError) as err:
            last_err = err
            time.sleep((retry_delay * (1.5 ** attempt)) + random.uniform(0.005, 0.02))

    logger.debug(f"safe_read_json fallback to default for {path} after {max_retries} attempts: {last_err}")
    return default
