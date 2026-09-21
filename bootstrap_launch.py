"""
bootstrap_launch.py
Run this ONCE to permanently start the supervisor+watchdog chain.
Uses DETACHED_PROCESS so processes survive after this script exits.
"""
import subprocess
import os
import sys

PYTHON   = r"C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe"
PYTHONW  = r"C:\Users\absh5\AppData\Local\Programs\Python\Python311\pythonw.exe"
BASE     = r"E:\scalping-robot-v5"
SUP      = os.path.join(BASE, "supervisor.py")

DETACHED_PROCESS      = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW      = 0x08000000

flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

# Use pythonw.exe if available (no console window), else python.exe
exe = PYTHONW if os.path.exists(PYTHONW) else PYTHON

print(f"Launching supervisor with {exe} ...")
proc = subprocess.Popen(
    [exe, SUP],
    cwd=BASE,
    creationflags=flags,
    close_fds=True,
    stdin=subprocess.DEVNULL,
    stdout=open(os.path.join(BASE, "supervisor.log"), "a"),
    stderr=subprocess.STDOUT,
)
print(f"Supervisor launched PID={proc.pid}")
print("Bootstrap complete. Supervisor runs independently.")
