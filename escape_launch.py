"""
escape_launch.py
Uses CREATE_BREAKAWAY_FROM_JOB to escape the PowerShell task's Job Object.
This is the ONLY way to launch a truly persistent process from a task runner.
"""
import subprocess
import os
import sys
from pathlib import Path

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


def get_breakaway_flags() -> int:
    """Return process flags with CREATE_BREAKAWAY_FROM_JOB."""
    return FLAGS


def get_fallback_flags() -> int:
    """Return process flags without breakaway."""
    return FALLBACK_FLAGS


def get_watchdog_command() -> list:
    """Return command list for launching watchdog."""
    return [PYTHON, str(WATCHDOG)]


def launch_watchdog(out_path: Path = None, err_path: Path = None):
    """
    Launch watchdog attempting breakaway flag first, then fallback flags.
    """
    out_file = out_path if out_path is not None else (BASE / "watchdog_out.log")
    err_file = err_path if err_path is not None else (BASE / "watchdog_err.log")

    try:
        with open(out_file, "a", encoding="utf-8") as out_f, \
             open(err_file, "a", encoding="utf-8") as err_f:
            proc = subprocess.Popen(
                get_watchdog_command(),
                cwd=str(BASE),
                creationflags=get_breakaway_flags(),
                stdin=subprocess.DEVNULL,
                stdout=out_f,
                stderr=err_f,
                close_fds=True,
            )
        return proc, "BREAKAWAY"
    except PermissionError:
        with open(out_file, "a", encoding="utf-8") as out_f2, \
             open(err_file, "a", encoding="utf-8") as err_f2:
            proc2 = subprocess.Popen(
                get_watchdog_command(),
                cwd=str(BASE),
                creationflags=get_fallback_flags(),
                stdin=subprocess.DEVNULL,
                stdout=out_f2,
                stderr=err_f2,
                close_fds=True,
            )
        return proc2, "FALLBACK"


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

