"""
Scalping Robot V5 - BULLETPROOF Watchdog v10
Intelligent restart logic, exponential backoff, and self-healing supervisor.
"""
import time
import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import deque
from typing import Optional, Tuple, Any

try:
    import psutil
except ImportError:
    psutil = None

BASE         = Path(r'E:\scalping-robot-v5')
STATUS_FILE  = BASE / 'live_status.json'
TRADER_OUT   = BASE / 'trader_out.log'
TRADER_ERR   = BASE / 'trader_err.log'
UVICORN_OUT  = BASE / 'uvicorn_out.log'
UVICORN_ERR  = BASE / 'uvicorn_err.log'
WATCHDOG_LOG = BASE / 'watchdog.log'

# Detection / health
STALE_SEC  = 120   # status.json max age before trader is considered hung
CHECK_SEC  = 20    # loop interval -- crash detected within 20 s (< 30 s requirement)
PORT       = 8899

# Backoff configuration
BACKOFF_MAX_RESTARTS = 3
BACKOFF_WINDOW_SEC   = 600   # 10 minutes
BACKOFF_WAIT_SEC     = 300   # 5 minutes


def _hidden_startupinfo():
    if sys.platform == 'win32':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    return None


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(WATCHDOG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def log_restart(target: str, reason: str, restart_count: int = 0, backoff_seconds: int = 0):
    """
    Send restart notification to watchdog.log with:
    timestamp, reason, restart_count, backoff_seconds
    """
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] [RESTART] {target} restart triggered -- reason: {reason} | restart_count={restart_count} | backoff_seconds={backoff_seconds}'
    print(line, flush=True)
    try:
        with open(WATCHDOG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def calculate_backoff(consecutive_restarts: int) -> int:
    """
    Exponential backoff:
    restart_delay = min(300, 30 * (2 ** consecutive_restarts))
    """
    return min(300, int(30 * (2 ** consecutive_restarts)))


def _memory_check(proc=None) -> float:
    """
    Use psutil if available, check process memory in MB.
    Returns memory in megabytes (MB) as a float, or 0.0 if psutil is unavailable or on error.
    """
    if psutil is None:
        return 0.0
    if proc is None:
        return 0.0
    try:
        if hasattr(proc, 'poll') and proc.poll() is not None:
            return 0.0
        pid = proc.pid if hasattr(proc, 'pid') else int(proc)
        p = psutil.Process(pid)
        return p.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def status_age(status_file: Path = STATUS_FILE) -> float:
    """Return age of live_status.json in seconds based on file modification time or content."""
    try:
        if not status_file.exists():
            return 9999.0
        return time.time() - status_file.stat().st_mtime
    except Exception:
        return 9999.0


def health_check(status_file: Path = STATUS_FILE) -> bool:
    """
    Health check before restart: read live_status.json,
    if ok=true and timestamp < 60s ago, DON'T restart (returns True).
    Otherwise returns False.
    """
    try:
        if not status_file.exists():
            return False
        with open(status_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check ok field
        # If 'ok' explicitly present, honor it (True / 'true')
        # If 'ok' not present, check status field for active/healthy states
        is_ok = False
        if "ok" in data:
            val = data.get("ok")
            is_ok = (val is True or str(val).strip().lower() == "true")
        else:
            status_str = str(data.get("status", "")).strip().lower()
            is_ok = status_str in ("ok", "healthy", "active_scalping")

        if not is_ok:
            return False

        # Check timestamp
        now = time.time()
        age_sec = None

        for key in ("timestamp", "ts", "time", "updated_at"):
            val = data.get(key)
            if val is not None:
                if isinstance(val, (int, float)):
                    age_sec = now - float(val)
                    break
                elif isinstance(val, str):
                    val_str = val.strip()
                    try:
                        age_sec = now - float(val_str)
                        break
                    except ValueError:
                        try:
                            dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
                            if dt.tzinfo is None:
                                age_sec = (datetime.now() - dt).total_seconds()
                            else:
                                age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
                            break
                        except Exception:
                            pass

        if age_sec is None:
            try:
                age_sec = now - status_file.stat().st_mtime
            except Exception:
                return False

        if age_sec < 60:
            return True

        return False
    except Exception:
        return False


def detect_restart_reason(proc, age: Optional[float] = None) -> Optional[str]:
    """
    Restart reason detection:
      - 'CRASH: process exited with code N'
      - 'OOM: memory > 500MB'
      - 'FREEZE: no status update for 120+ seconds'
    Returns reason string if restart is required, else None.
    """
    # 1. Crash check: process terminated
    if proc is None or proc.poll() is not None:
        code = proc.poll() if proc is not None else -1
        return f"CRASH: process exited with code {code}"

    # 2. OOM check: memory > 500MB
    mem_mb = _memory_check(proc)
    if mem_mb > 500.0:
        return "OOM: memory > 500MB"

    # 3. Freeze check: no status update for 120+ seconds
    if age is None:
        age = status_age()
    if age > STALE_SEC:
        return "FREEZE: no status update for 120+ seconds"

    return None


def start_trader():
    cmd = [
        'python.exe', '-m', 'python_engine.mt5_live_trader',
        '--symbol', 'XAUUSD', '--lot', '0.02',
        '--iterations', '999999', '--interval', '0.5'
    ]
    log(f"[TRADER] Starting -- cmd: {' '.join(cmd)}")
    try:
        out = open(TRADER_OUT, 'w', encoding='utf-8', errors='replace')
        err = open(TRADER_ERR, 'w', encoding='utf-8', errors='replace')
        p = subprocess.Popen(
            cmd,
            cwd=str(BASE),
            stdout=out,
            stderr=err,
            startupinfo=_hidden_startupinfo()
        )
        log(f'[TRADER] Started PID={p.pid}')
        return p, out, err
    except Exception as e:
        log(f'[TRADER] Start FAILED: {e}')
        return None, None, None


def start_uvicorn():
    cmd = [
        'python.exe', '-m', 'uvicorn', 'omnicommand_server:app',
        '--host', '0.0.0.0', '--port', str(PORT), '--log-level', 'warning'
    ]
    log(f"[UVICORN] Starting -- cmd: {' '.join(cmd)}")
    try:
        out = open(UVICORN_OUT, 'w', encoding='utf-8', errors='replace')
        err = open(UVICORN_ERR, 'w', encoding='utf-8', errors='replace')
        p = subprocess.Popen(
            cmd,
            cwd=str(BASE),
            stdout=out,
            stderr=err,
            startupinfo=_hidden_startupinfo()
        )
        log(f'[UVICORN] Started PID={p.pid}')
        return p, out, err
    except Exception as e:
        log(f'[UVICORN] Start FAILED: {e}')
        return None, None, None


def safe_kill(p):
    if p is None:
        return
    try:
        p.kill()
    except Exception:
        pass
    try:
        p.wait(timeout=5)
    except Exception:
        pass


def safe_close(f):
    if f is None:
        return
    try:
        f.close()
    except Exception:
        pass


def apply_backoff_if_needed(restart_times: deque) -> bool:
    """
    Legacy rolling window backoff for backwards compatibility.
    """
    now = time.time()
    while restart_times and (now - restart_times[0]) > BACKOFF_WINDOW_SEC:
        restart_times.popleft()

    restart_times.append(now)

    if len(restart_times) >= BACKOFF_MAX_RESTARTS:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log(f'[BACKOFF][{ts}] {len(restart_times)} restarts in '
            f'{BACKOFF_WINDOW_SEC // 60} min -- waiting '
            f'{BACKOFF_WAIT_SEC // 60} min before next restart.')
        time.sleep(BACKOFF_WAIT_SEC)
        restart_times.clear()
        return True
    return False


def restart_trader(p, out, err, reason: str, consecutive_restarts: Any = 0, restart_count: int = 0):
    """
    Standalone restart_trader with intelligent health check and exponential backoff.
    """
    # Step 2.b: Health check before restart
    if health_check():
        log(f"[HEALTH CHECK] Trader reported ok=true within <60s. Skipping restart for reason: {reason}")
        return p, out, err

    consec = len(consecutive_restarts) if isinstance(consecutive_restarts, deque) else int(consecutive_restarts)
    backoff_sec = calculate_backoff(consec)
    restart_count += 1
    log_restart('Trader', reason, restart_count=restart_count, backoff_seconds=backoff_sec)

    safe_kill(p)
    safe_close(out)
    safe_close(err)

    if backoff_sec > 0:
        log(f"[BACKOFF] Sleeping {backoff_sec}s before starting Trader (consecutive={consec})...")
        time.sleep(backoff_sec)
    else:
        time.sleep(3)

    return start_trader()


def restart_uvicorn(p, out, err, reason: str = 'process exited / crashed'):
    log_restart('Uvicorn', reason, 0, 3)
    safe_kill(p)
    safe_close(out)
    safe_close(err)
    time.sleep(3)
    return start_uvicorn()


class WatchdogRunner:
    """
    Watchdog v2 Systems Engineer - Intelligent restart logic & self-healing supervisor.
    """
    def __init__(self):
        self.tr_p = None
        self.tr_out = None
        self.tr_err = None
        self.uv_p = None
        self.uv_out = None
        self.uv_err = None
        self.consecutive_restarts: int = 0
        self.restart_count: int = 0
        self.last_restart_time: float = time.time()
        self.cycle: int = 0

    def _memory_check(self, proc=None) -> float:
        """Use psutil if available, check process memory in MB."""
        target = proc if proc is not None else self.tr_p
        return _memory_check(target)

    def health_check(self) -> bool:
        """
        Health check before restart: read live_status.json,
        if ok=true and timestamp < 60s ago, DON'T restart (returns True).
        """
        return health_check(STATUS_FILE)

    def _check_health(self) -> bool:
        """Alias for health_check()."""
        return self.health_check()

    def status_age(self) -> float:
        """Return age of live_status.json in seconds."""
        return status_age(STATUS_FILE)

    def detect_restart_reason(self, proc=None) -> Optional[str]:
        """
        Detect restart reason for trader process:
          - 'CRASH: process exited with code N'
          - 'FREEZE: no status update for 120+ seconds'
          - 'OOM: memory > 500MB'
        """
        target = proc if proc is not None else self.tr_p
        age = self.status_age()
        return detect_restart_reason(target, age)

    def calculate_backoff(self, consecutive: Optional[int] = None) -> int:
        """
        Exponential backoff:
        restart_delay = min(300, 30 * (2 ** consecutive_restarts))
        """
        count = self.consecutive_restarts if consecutive is None else consecutive
        return calculate_backoff(count)

    def log_restart(self, target: str, reason: str, backoff_seconds: int = 0):
        """Send restart notification to watchdog.log with: timestamp, reason, restart_count, backoff_seconds."""
        log_restart(target, reason, self.restart_count, backoff_seconds)

    def restart_trader(self, reason: str) -> Tuple[Any, Any, Any]:
        """
        Restart trader process with:
          - Health check before restart: if ok=true and timestamp < 60s ago, DON'T restart
          - Exponential backoff: restart_delay = min(300, 30 * (2 ** consecutive_restarts))
          - Logging notification to watchdog.log
        """
        # Step 2.b: Health check before restart
        if self.health_check():
            log(f"[HEALTH CHECK] Trader reported ok=true within <60s. Skipping restart for reason: {reason}")
            return self.tr_p, self.tr_out, self.tr_err

        # Step 2.a: Exponential backoff
        restart_delay = self.calculate_backoff()
        self.restart_count += 1
        self.consecutive_restarts += 1

        # Step 2.d: Send restart notification to watchdog.log
        self.log_restart("Trader", reason, backoff_seconds=restart_delay)

        safe_kill(self.tr_p)
        safe_close(self.tr_out)
        safe_close(self.tr_err)

        if restart_delay > 0:
            log(f"[BACKOFF] Sleeping {restart_delay}s before starting Trader (consecutive={self.consecutive_restarts})...")
            time.sleep(restart_delay)
        else:
            time.sleep(3)

        self.tr_p, self.tr_out, self.tr_err = start_trader()
        self.last_restart_time = time.time()
        return self.tr_p, self.tr_out, self.tr_err

    def restart_uvicorn(self, reason: str = "process exited / crashed") -> Tuple[Any, Any, Any]:
        """Restart uvicorn process."""
        log_restart("Uvicorn", reason, 0, 3)
        safe_kill(self.uv_p)
        safe_close(self.uv_out)
        safe_close(self.uv_err)
        time.sleep(3)
        self.uv_p, self.uv_out, self.uv_err = start_uvicorn()
        return self.uv_p, self.uv_out, self.uv_err

    def run(self):
        """Main monitoring loop."""
        log("=== WATCHDOG v10 STARTING ===")
        self.uv_p, self.uv_out, self.uv_err = start_uvicorn()
        time.sleep(6)
        self.tr_p, self.tr_out, self.tr_err = start_trader()
        self.last_restart_time = time.time()

        while True:
            try:
                time.sleep(CHECK_SEC)
                self.cycle += 1
                age = self.status_age()
                tr_alive = self.tr_p is not None and self.tr_p.poll() is None
                uv_alive = self.uv_p is not None and self.uv_p.poll() is None
                mem_mb = round(self._memory_check(self.tr_p), 1) if tr_alive else 0.0

                log(f"[C={self.cycle}] trader={tr_alive} uvicorn={uv_alive} age={round(age, 1)}s mem={mem_mb}MB")

                # Self-healing: if trader has run stably for >300s, reset consecutive backoff counter
                if tr_alive and age <= STALE_SEC and (time.time() - self.last_restart_time) > 300:
                    if self.consecutive_restarts > 0:
                        log(f"[STABILITY] Trader healthy for >300s. Resetting consecutive_restarts ({self.consecutive_restarts} -> 0).")
                        self.consecutive_restarts = 0

                # Detect trader restart reason
                reason = self.detect_restart_reason(self.tr_p)
                if reason is not None:
                    self.restart_trader(reason)

                # Monitor uvicorn
                if not uv_alive:
                    uv_code = self.uv_p.poll() if self.uv_p is not None else -1
                    uv_reason = f"CRASH: process exited with code {uv_code}"
                    self.restart_uvicorn(uv_reason)

            except KeyboardInterrupt:
                log("Stopped by user.")
                safe_kill(self.tr_p)
                safe_kill(self.uv_p)
                break
            except Exception as e:
                log(f"[WATCHDOG EXCEPTION - self healing]: {e}")
                time.sleep(5)


if __name__ == '__main__':
    runner = WatchdogRunner()
    runner.run()
