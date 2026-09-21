"""
escape_launch.py
Uses CREATE_BREAKAWAY_FROM_JOB to escape the PowerShell task's Job Object.
This is the ONLY way to launch a truly persistent process from a task runner.
"""
import subprocess
import os
import sys

PYTHON   = r"C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe"
BASE     = r"E:\scalping-robot-v5"
WATCHDOG = os.path.join(BASE, "watchdog_runner.py")

# Windows process creation flags
DETACHED_PROCESS         = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW         = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000   # <-- KEY: escape the job object

FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB

print(f"[escape_launch] Launching watchdog with BREAKAWAY flag...")

try:
    out_f = open(os.path.join(BASE, "watchdog_out.log"), "a")
    err_f = open(os.path.join(BASE, "watchdog_err.log"), "a")
    proc = subprocess.Popen(
        [PYTHON, WATCHDOG],
        cwd=BASE,
        creationflags=FLAGS,
        stdin=subprocess.DEVNULL,
        stdout=out_f,
        stderr=err_f,
        close_fds=True,
    )
    print(f"[escape_launch] Watchdog PID={proc.pid} launched with BREAKAWAY_FROM_JOB")
    print(f"[escape_launch] This process will survive task exit.")
except PermissionError as e:
    print(f"[escape_launch] PermissionError (job may not allow breakaway): {e}")
    print("[escape_launch] Trying WITHOUT breakaway flag...")
    flags2 = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    try:
        out_f2 = open(os.path.join(BASE, "watchdog_out.log"), "a")
        err_f2 = open(os.path.join(BASE, "watchdog_err.log"), "a")
        proc2 = subprocess.Popen(
            [PYTHON, WATCHDOG],
            cwd=BASE,
            creationflags=flags2,
            stdin=subprocess.DEVNULL,
            stdout=out_f2,
            stderr=err_f2,
            close_fds=True,
        )
        print(f"[escape_launch] Fallback launch PID={proc2.pid}")
    except Exception as e2:
        print(f"[escape_launch] Fallback also failed: {e2}")
except Exception as e:
    print(f"[escape_launch] Error: {e}")
