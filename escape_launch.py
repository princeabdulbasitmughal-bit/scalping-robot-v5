"""
escape_launch.py
Uses CREATE_BREAKAWAY_FROM_JOB to escape the PowerShell task's Job Object.
This is the ONLY way to launch a truly persistent process from a task runner.
"""
import subprocess
import os
import sys
import threading
from pathlib import Path
from typing import Optional, List, Union, Tuple

# Dynamic resolution — no hardcoded paths
PYTHON = sys.executable
BASE = Path(__file__).resolve().parent
WATCHDOG = BASE / "watchdog_runner.py"

# Windows process creation flags
DETACHED_PROCESS          = 0x00000008
CREATE_NEW_PROCESS_GROUP  = 0x00000200
CREATE_NO_WINDOW          = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000   # KEY: escape the job object

FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB
FALLBACK_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
_lock = threading.RLock()


def get_breakaway_flags() -> int:
    """Return process flags with CREATE_BREAKAWAY_FROM_JOB."""
    return FLAGS


def get_fallback_flags() -> int:
    """Return process flags without breakaway."""
    return FALLBACK_FLAGS


def get_watchdog_command(python_exe: Optional[str] = None, watchdog_script: Optional[Union[str, Path]] = None) -> List[str]:
    """Return command list for launching watchdog with optional parameter overrides."""
    with _lock:
        cmd_py = str(python_exe) if python_exe is not None else PYTHON
        cmd_wd = str(watchdog_script) if watchdog_script is not None else str(WATCHDOG)
        return [cmd_py, cmd_wd]


def launch_watchdog(out_path: Optional[Union[str, Path]] = None,
                    err_path: Optional[Union[str, Path]] = None,
                    python_exe: Optional[str] = None,
                    watchdog_script: Optional[Union[str, Path]] = None) -> Tuple[subprocess.Popen, str]:
    """
    Launch watchdog attempting breakaway flag first, then fallback flags.
    """
    with _lock:
        out_file = Path(out_path) if out_path is not None else (BASE / "watchdog_out.log")
        err_file = Path(err_path) if err_path is not None else (BASE / "watchdog_err.log")

        out_file.parent.mkdir(parents=True, exist_ok=True)
        err_file.parent.mkdir(parents=True, exist_ok=True)

        cmd = get_watchdog_command(python_exe=python_exe, watchdog_script=watchdog_script)

        try:
            with open(out_file, "a", encoding="utf-8") as out_f, \
                 open(err_file, "a", encoding="utf-8") as err_f:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(BASE),
                    creationflags=get_breakaway_flags(),
                    stdin=subprocess.DEVNULL,
                    stdout=out_f,
                    stderr=err_f,
                    close_fds=True,
                )
            return proc, "BREAKAWAY"
        except (PermissionError, OSError):
            with open(out_file, "a", encoding="utf-8") as out_f2, \
                 open(err_file, "a", encoding="utf-8") as err_f2:
                proc2 = subprocess.Popen(
                    cmd,
                    cwd=str(BASE),
                    creationflags=get_fallback_flags(),
                    stdin=subprocess.DEVNULL,
                    stdout=out_f2,
                    stderr=err_f2,
                    close_fds=True,
                )
            return proc2, "FALLBACK"


def is_entry_blocked() -> bool:
    """Fail-closed risk guard: blocks if watchdog target script is missing."""
    with _lock:
        if not WATCHDOG.exists():
            return True
        return False


def is_blocked() -> bool:
    """Unified risk check alias."""
    return is_entry_blocked()


if __name__ == "__main__":
    print(f"[escape_launch] Launching watchdog with BREAKAWAY flag...")
    try:
        proc, mode = launch_watchdog()
        if mode == "BREAKAWAY":
            print(f"[escape_launch] Watchdog PID={proc.pid} launched with BREAKAWAY_FROM_JOB")
            print(f"[escape_launch] This process will survive task exit.")
        else:
            print(f"[escape_launch] Fallback launch PID={proc.pid}")
    except Exception as e:
        print(f"[escape_launch] Error: {e}")
        sys.exit(1)

