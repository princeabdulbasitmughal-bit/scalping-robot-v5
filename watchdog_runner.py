"""
Scalping Robot V5 - BULLETPROOF Watchdog v10
Fixes: backoff on rapid restarts, structured restart logging
"""
import time
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from collections import deque

BASE         = Path(__file__).parent
STATUS_FILE  = BASE / 'live_status.json'
TRADER_OUT   = BASE / 'trader_out.log'
TRADER_ERR   = BASE / 'trader_err.log'
UVICORN_OUT  = BASE / 'uvicorn_out.log'
UVICORN_ERR  = BASE / 'uvicorn_err.log'
WATCHDOG_LOG = BASE / 'watchdog_out.log'

# Detection / health
STALE_SEC  = 120   # status.json max age before trader is considered hung
CHECK_SEC  = 20    # loop interval — crash detected within 20 s (< 30 s requirement)
PORT       = 8899
PY         = sys.executable

# Backoff: if trader restarts >= BACKOFF_MAX_RESTARTS times within
# BACKOFF_WINDOW_SEC seconds, pause for BACKOFF_WAIT_SEC before next restart.
BACKOFF_MAX_RESTARTS = 3
BACKOFF_WINDOW_SEC   = 600   # 10 minutes
BACKOFF_WAIT_SEC     = 300   # 5 minutes

FLAGS = 0  # no special flags — use STARTUPINFO to hide window instead


def _hidden_startupinfo():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(WATCHDOG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def status_age():
    try:
        if not STATUS_FILE.exists():
            return 9999
        return time.time() - STATUS_FILE.stat().st_mtime
    except Exception:
        return 9999


def start_trader():
    log('[TRADER] Starting — cmd: python.exe -m python_engine.mt5_live_trader '
        '--symbol XAUUSD --lot 0.02 --iterations 999999 --interval 0.5')
    try:
        out = open(TRADER_OUT, 'w', encoding='utf-8', errors='replace')
        err = open(TRADER_ERR, 'w', encoding='utf-8', errors='replace')
        p = subprocess.Popen(
            [PY, '-m', 'python_engine.mt5_live_trader',
             '--symbol', 'XAUUSD', '--lot', '0.02',
             '--iterations', '999999', '--interval', '0.5'],
            cwd=str(BASE), stdout=out, stderr=err,
            startupinfo=_hidden_startupinfo()
        )
        log(f'[TRADER] Started PID={p.pid}')
        return p, out, err
    except Exception as e:
        log(f'[TRADER] Start FAILED: {e}')
        return None, None, None


def start_uvicorn():
    log('[UVICORN] Starting...')
    try:
        out = open(UVICORN_OUT, 'w', encoding='utf-8', errors='replace')
        err = open(UVICORN_ERR, 'w', encoding='utf-8', errors='replace')
        p = subprocess.Popen(
            [PY, '-m', 'uvicorn', 'omnicommand_server:app',
             '--host', '0.0.0.0', '--port', str(PORT), '--log-level', 'warning'],
            cwd=str(BASE), stdout=out, stderr=err,
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
    Record a restart timestamp. If BACKOFF_MAX_RESTARTS restarts occurred within
    BACKOFF_WINDOW_SEC, sleep for BACKOFF_WAIT_SEC and return True.
    Returns False if no backoff was applied.
    """
    now = time.time()
    restart_times.append(now)

    # Prune timestamps outside the rolling window
    while restart_times and now - restart_times[0] > BACKOFF_WINDOW_SEC:
        restart_times.popleft()

    if len(restart_times) >= BACKOFF_MAX_RESTARTS:
        log(f'[BACKOFF] {BACKOFF_MAX_RESTARTS} restarts in '
            f'{BACKOFF_WINDOW_SEC // 60} min — waiting '
            f'{BACKOFF_WAIT_SEC // 60} min before next restart.')
        time.sleep(BACKOFF_WAIT_SEC)
        restart_times.clear()   # reset counter after backoff
        return True
    return False


def restart_trader(p, out, err, reason: str, restart_times: deque):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log(f'[RESTART][{ts}] Trader restart triggered — reason: {reason}')
    safe_kill(p)
    safe_close(out)
    safe_close(err)
    apply_backoff_if_needed(restart_times)
    time.sleep(3)
    return start_trader()


def restart_uvicorn(p, out, err):
    log('[RESTART] Uvicorn restart triggered.')
    safe_kill(p)
    safe_close(out)
    safe_close(err)
    time.sleep(3)
    return start_uvicorn()


if __name__ == '__main__':
    log('=== WATCHDOG v10 STARTING ===')

    uv_p, uv_out, uv_err = start_uvicorn()
    time.sleep(6)
    tr_p, tr_out, tr_err = start_trader()

    # Rolling deque of trader restart timestamps for backoff tracking
    trader_restart_times: deque = deque()

    cycle = 0
    while True:
        try:
            time.sleep(CHECK_SEC)
            cycle += 1
            age = status_age()
            tr_alive = tr_p is not None and tr_p.poll() is None
            uv_alive = uv_p is not None and uv_p.poll() is None
            log(f'[C={cycle}] trader={tr_alive} uvicorn={uv_alive} age={round(age, 1)}s')

            if not tr_alive:
                reason = 'process exited / crashed'
                tr_p, tr_out, tr_err = restart_trader(
                    tr_p, tr_out, tr_err, reason, trader_restart_times)

            elif age > STALE_SEC:
                reason = f'status.json stale for {round(age, 1)}s (>{STALE_SEC}s)'
                tr_p, tr_out, tr_err = restart_trader(
                    tr_p, tr_out, tr_err, reason, trader_restart_times)

            if not uv_alive:
                uv_p, uv_out, uv_err = restart_uvicorn(uv_p, uv_out, uv_err)

        except KeyboardInterrupt:
            log('Stopped by user.')
            safe_kill(tr_p)
            safe_kill(uv_p)
            break
        except Exception as e:
            log(f'[WATCHDOG EXCEPTION - self healing]: {e}')
            time.sleep(5)
