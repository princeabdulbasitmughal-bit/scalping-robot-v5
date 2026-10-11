"""
bootstrap_launch.py
Run this ONCE to permanently start the supervisor+watchdog chain.
Uses DETACHED_PROCESS so processes survive after this script exits.
"""
import subprocess
import os
import sys
from pathlib import Path

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

print(f"Launching supervisor with {exe} ...")
try:
    with open(BASE / "supervisor.log", "a") as log_f:
        proc = subprocess.Popen(
            [exe, str(SUP)],
            cwd=str(BASE),
            creationflags=flags,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )
    print(f"Supervisor launched PID={proc.pid}")
    print("Bootstrap complete. Supervisor runs independently.")
except Exception as e:
    print(f"[bootstrap_launch] Failed to launch supervisor: {e}")
    sys.exit(1)
