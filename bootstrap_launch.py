"""
bootstrap_launch.py
Run this ONCE to permanently start the supervisor+watchdog chain.
Uses DETACHED_PROCESS so processes survive after this script exits.
"""
import subprocess
import os
import sys
import threading
from pathlib import Path
from typing import Optional, List, Union

# Dynamic resolution — no hardcoded paths
BASE = Path(__file__).resolve().parent
SUP  = BASE / "supervisor.py"

# Prefer pythonw.exe (no console) next to current interpreter; fall back to python.exe
_py_dir = Path(sys.executable).parent
PYTHONW = _py_dir / "pythonw.exe"
exe = str(PYTHONW) if PYTHONW.exists() else sys.executable

DETACHED_PROCESS         = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW         = 0x08000000

flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
_lock = threading.RLock()


def get_launch_flags() -> int:
    """Return process creation flags for detached background execution."""
    return flags


def get_supervisor_command(python_exe: Optional[str] = None, supervisor_script: Optional[Union[str, Path]] = None) -> List[str]:
    """Return command list for launching supervisor with optional parameter overrides."""
    with _lock:
        cmd_exe = str(python_exe) if python_exe is not None else exe
        cmd_sup = str(supervisor_script) if supervisor_script is not None else str(SUP)
        return [cmd_exe, cmd_sup]


def launch_supervisor(log_path: Optional[Union[str, Path]] = None, python_exe: Optional[str] = None, supervisor_script: Optional[Union[str, Path]] = None):
    """Launch supervisor as a detached background process."""
    with _lock:
        target_log = Path(log_path) if log_path is not None else (BASE / "supervisor.log")
        target_log.parent.mkdir(parents=True, exist_ok=True)
        with open(target_log, "a", encoding="utf-8") as log_f:
            proc = subprocess.Popen(
                get_supervisor_command(python_exe=python_exe, supervisor_script=supervisor_script),
                cwd=str(BASE),
                creationflags=get_launch_flags(),
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=subprocess.STDOUT,
            )
        return proc


def is_entry_blocked() -> bool:
    """Fail-closed risk guard: blocks if supervisor target script is missing."""
    with _lock:
        if not SUP.exists():
            return True
        return False


def is_blocked() -> bool:
    """Unified risk check alias."""
    return is_entry_blocked()


if __name__ == "__main__":
    print(f"Launching supervisor with {exe} ...")
    try:
        proc = launch_supervisor()
        print(f"Supervisor launched PID={proc.pid}")
        print("Bootstrap complete. Supervisor runs independently.")
    except Exception as e:
        print(f"[bootstrap_launch] Failed to launch supervisor: {e}")
        sys.exit(1)

