"""
supervisor.py - Permanent keep-alive supervisor for scalping watchdog + uvicorn
Launched via bootstrap_launch.py with DETACHED_PROCESS flag.
Survives PowerShell session end. Checks every 10s.
"""
import subprocess
import time
import os
import datetime

PYTHON   = r"C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe"
BASE     = r"E:\scalping-robot-v5"
WATCHDOG = os.path.join(BASE, "watchdog_runner.py")
LOG      = os.path.join(BASE, "supervisor.log")

DETACHED_PROCESS      = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW      = 0x08000000

FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = "[{}] [SUP] {}".format(ts, msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_watchdog_pid():
    """Return PID of running watchdog_runner.py process, or None."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'watchdog_runner' } | "
                "Select-Object -First 1 -ExpandProperty ProcessId"
            ],
            capture_output=True, text=True, timeout=10, cwd=BASE
        )
        pid_str = result.stdout.strip()
        if pid_str.isdigit():
            return int(pid_str)
    except Exception as e:
        log("PID check error: {}".format(e))
    return None


def start_watchdog():
    """Launch watchdog_runner.py as a fully detached process."""
    try:
        out_log = open(os.path.join(BASE, "watchdog_out.log"), "a")
        err_log = open(os.path.join(BASE, "watchdog_err.log"), "a")
        proc = subprocess.Popen(
            [PYTHON, WATCHDOG],
            cwd=BASE,
            creationflags=FLAGS,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=out_log,
            stderr=err_log,
        )
        log("Watchdog started PID={}".format(proc.pid))
        return proc.pid
    except Exception as e:
        log("Start watchdog error: {}".format(e))
        return None


if __name__ == "__main__":
    log("=== Supervisor started (PID={}) ===".format(os.getpid()))
    restart_count = 0

    while True:
        try:
            pid = get_watchdog_pid()
            if pid is None:
                restart_count += 1
                log("Watchdog DOWN. Restart #{}".format(restart_count))
                start_watchdog()
                time.sleep(8)  # Give watchdog time to init
            else:
                # Watchdog alive — log every 60s (every 6 cycles)
                if restart_count == 0 or True:
                    pass  # Silent when healthy (logs fill up fast)
        except Exception as exc:
            log("Supervisor error: {}".format(exc))

        time.sleep(10)
