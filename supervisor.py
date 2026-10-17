"""
supervisor.py - Permanent keep-alive supervisor for scalping watchdog + uvicorn
Launched via bootstrap_launch.py with DETACHED_PROCESS flag.
Survives PowerShell session end. Checks every 10s.
"""
import subprocess
import sys
import time
import os
from datetime import datetime, timezone

# Use the same Python interpreter that is running this script — no hardcoded paths
PYTHON   = sys.executable
BASE     = os.path.dirname(os.path.abspath(__file__))
WATCHDOG = os.path.join(BASE, "watchdog_runner.py")
LOG      = os.path.join(BASE, "supervisor.log")

DETACHED_PROCESS      = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW      = 0x08000000

FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

_MAX_BACKOFF_SEC = 120        # Exponential backoff cap for crash loops
_MAX_CONSECUTIVE_FAILURES = 20  # Circuit breaker: halt after this many consecutive failures


def calculate_backoff(consecutive_failures: int) -> int:
    """Calculate exponential backoff seconds for consecutive failures.

    Exponential progression: 8s, 16s, 32s, 64s, 120s (capped at _MAX_BACKOFF_SEC).
    Returns 0 if consecutive_failures <= 0 or invalid.
    """
    if isinstance(consecutive_failures, bool) or not isinstance(consecutive_failures, (int, float)):
        return 0
    if consecutive_failures <= 0:
        return 0
    return int(min(8 * (2 ** (int(consecutive_failures) - 1)), _MAX_BACKOFF_SEC))


def check_circuit_breaker(consecutive_failures: int) -> bool:
    """Check if consecutive failures exceeded circuit breaker threshold."""
    if isinstance(consecutive_failures, bool) or not isinstance(consecutive_failures, (int, float)):
        return False
    return int(consecutive_failures) >= _MAX_CONSECUTIVE_FAILURES


def is_entry_blocked() -> bool:
    """Returns True if watchdog_runner is down or PID cannot be found."""
    try:
        pid = get_watchdog_pid()
        return pid is None
    except Exception as e:
        log(f"is_entry_blocked error: {e}")
        return True  # fail-closed


def is_blocked() -> bool:
    return is_entry_blocked()



def log(msg, log_file=None):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    line = "[{}] [SUP] {}".format(ts, msg)
    target = log_file or LOG
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_watchdog_pid():
    """Return PID of running watchdog_runner.py process, or None.

    Uses psutil instead of a PowerShell WMI call to avoid a 10-second subprocess
    spawn on every check cycle which was causing false-negative restarts.
    """
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = proc.info.get("cmdline") or []
                if "python" in name and any("watchdog_runner" in arg for arg in cmdline):
                    return proc.info["pid"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        log("PID check error: {}".format(e))
    return None


def start_watchdog(python_bin=None, watchdog_script=None, base_dir=None, creationflags=None):
    """Launch watchdog_runner.py as a fully detached process."""
    py_bin = python_bin or PYTHON
    wd_script = watchdog_script or WATCHDOG
    cwd_dir = base_dir or BASE
    flags = creationflags if creationflags is not None else FLAGS
    out_log = None
    err_log = None
    try:
        out_log = open(os.path.join(cwd_dir, "watchdog_out.log"), "a")
        err_log = open(os.path.join(cwd_dir, "watchdog_err.log"), "a")
        proc = subprocess.Popen(
            [py_bin, wd_script],
            cwd=cwd_dir,
            creationflags=flags,
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
    finally:
        # Close file handles after Popen — the child has its own file descriptor
        if out_log is not None:
            try:
                out_log.close()
            except Exception:
                pass
        if err_log is not None:
            try:
                err_log.close()
            except Exception:
                pass


if __name__ == "__main__":
    log("=== Supervisor started (PID={}) ===".format(os.getpid()))
    restart_count = 0
    consecutive_failures = 0

    while True:
        try:
            pid = get_watchdog_pid()
            if pid is None:
                restart_count += 1
                consecutive_failures += 1
                log("Watchdog DOWN. Restart #{} (consecutive={})".format(restart_count, consecutive_failures))

                # Circuit breaker: if watchdog keeps failing, stop hammering and alert
                if check_circuit_breaker(consecutive_failures):
                    log("CRITICAL: Exceeded {} consecutive failures — supervisor entering 1-hour sleep. Check watchdog_runner.py manually!".format(_MAX_CONSECUTIVE_FAILURES))
                    time.sleep(3600)
                    consecutive_failures = 0  # reset after long sleep to allow retry
                    continue

                start_watchdog()
                # Exponential backoff: 8s, 16s, 32s … capped at _MAX_BACKOFF_SEC
                backoff = calculate_backoff(consecutive_failures)
                log("Backoff {}s before next check".format(backoff))
                time.sleep(backoff)
            else:
                # Watchdog alive — reset consecutive failure counter
                consecutive_failures = 0
        except Exception as exc:
            log("Supervisor error: {}".format(exc))

        time.sleep(10)
