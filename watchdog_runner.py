"""
Scalping Robot V5 - BULLETPROOF Watchdog v8
Windows-safe. File-only logging. No DETACHED_PROCESS + file handle conflict.
Uses CREATE_NEW_PROCESS_GROUP (0x200) which IS compatible with stdout redirect.
"""
import time
import sys
import os
import socket
import subprocess
from pathlib import Path
from datetime import datetime

BASE                = Path(__file__).parent
STATUS_FILE         = BASE / 'live_status.json'
TRADER_OUT          = BASE / 'trader_out.log'
TRADER_ERR          = BASE / 'trader_err.log'
UVICORN_OUT         = BASE / 'uvicorn_out.log'
UVICORN_ERR         = BASE / 'uvicorn_err.log'
WATCHDOG_LOG        = BASE / 'watchdog_out.log'

STALE_THRESHOLD_SEC = 90
CHECK_INTERVAL_SEC  = 15
UVICORN_HOST        = '127.0.0.1'
UVICORN_PORT        = 8899
MY_PID              = os.getpid()

# Windows process creation flags
CREATE_NEW_PROCESS_GROUP = 0x00000200   # Safe with stdout redirect
CREATE_NO_WINDOW         = 0x08000000   # No console window


def log(msg):
    ts   = datetime.now().strftime('%H:%M:%S')
    line = '[{}] [WDv8] {}'.format(ts, msg)
    try:
        with open(str(WATCHDOG_LOG), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
            f.flush()
    except Exception:
        pass


def status_age_sec():
    try:
        if not STATUS_FILE.exists():
            return 9999
        return datetime.now().timestamp() - STATUS_FILE.stat().st_mtime
    except Exception:
        return 9999


def port_open(host, port, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def kill_proc(proc):
    if proc is None:
        return
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def close_files(*files):
    for f in files:
        try:
            if f:
                f.close()
        except Exception:
            pass


def start_trader():
    log('Starting mt5_live_trader...')
    try:
        out_f = open(str(TRADER_OUT), 'a', encoding='utf-8')
        err_f = open(str(TRADER_ERR), 'a', encoding='utf-8')
        proc  = subprocess.Popen(
            [sys.executable, '-m', 'python_engine.mt5_live_trader',
             '--symbol', 'XAUUSD', '--lot', '0.02',
             '--iterations', '999999', '--interval', '0.05'],
            cwd=str(BASE),
            stdout=out_f,
            stderr=err_f,
            creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        )
        log('Trader started PID={}'.format(proc.pid))
        return proc, out_f, err_f
    except Exception as e:
        log('ERROR starting trader: {}'.format(e))
        return None, None, None


def start_uvicorn():
    log('Starting uvicorn:{}...'.format(UVICORN_PORT))
    try:
        out_f = open(str(UVICORN_OUT), 'a', encoding='utf-8')
        err_f = open(str(UVICORN_ERR), 'a', encoding='utf-8')
        proc  = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn',
             'omnicommand_server:app',
             '--host', '0.0.0.0',
             '--port', str(UVICORN_PORT)],
            cwd=str(BASE),
            stdout=out_f,
            stderr=err_f,
            creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        )
        log('Uvicorn started PID={}'.format(proc.pid))
        return proc, out_f, err_f
    except Exception as e:
        log('ERROR starting uvicorn: {}'.format(e))
        return None, None, None


# ==================================================
# MAIN
# ==================================================
if __name__ == '__main__':
    log('=== WATCHDOG v8 ACTIVE PID={} ==='.format(MY_PID))
    log('Stale={}s Check={}s flags=CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW'.format(
        STALE_THRESHOLD_SEC, CHECK_INTERVAL_SEC))

    trader_proc = uv_proc = None
    trader_out  = trader_err = uv_out = uv_err = None
    cycle       = 0

    # Grace period: don't kill trader for staleness right after start
    GRACE_END = time.time() + 30

    while True:
        try:
            cycle += 1

            # --- Trader check ---
            trader_alive = trader_proc is not None and trader_proc.poll() is None
            age          = status_age_sec()

            in_grace  = time.time() < GRACE_END
            is_stale  = (not in_grace) and (age > STALE_THRESHOLD_SEC)

            if not trader_alive or is_stale:
                reason = 'poll={}'.format(trader_proc.poll() if trader_proc else 'None')
                if is_stale and trader_alive:
                    reason = 'STALE {}s'.format(round(age, 1))
                log('Trader restart ({})'.format(reason))
                kill_proc(trader_proc)
                close_files(trader_out, trader_err)
                time.sleep(2)
                trader_proc, trader_out, trader_err = start_trader()
                GRACE_END = time.time() + 30

            # --- Uvicorn check ---
            uv_dead = uv_proc is None or uv_proc.poll() is not None
            uv_up   = not uv_dead  # Prefer process check over port check

            if uv_dead:
                log('Uvicorn:8899 DOWN -> restarting')
                kill_proc(uv_proc)
                close_files(uv_out, uv_err)
                uv_proc, uv_out, uv_err = start_uvicorn()
                # Wait up to 10s for port
                uv_up = False
                for _ in range(10):
                    time.sleep(1)
                    if port_open(UVICORN_HOST, UVICORN_PORT):
                        log('Uvicorn port OPEN OK')
                        uv_up = True
                        break
                if not uv_up:
                    log('Uvicorn port still DOWN after 10s')

            # --- Heartbeat ---
            trader_alive = trader_proc is not None and trader_proc.poll() is None
            age          = status_age_sec()
            log('C={} trader={} age={}s stale={} uv={}'.format(
                cycle, trader_alive, round(age, 1),
                age > STALE_THRESHOLD_SEC, uv_up))

            time.sleep(CHECK_INTERVAL_SEC)

        except KeyboardInterrupt:
            log('Stopped by user.')
            kill_proc(trader_proc)
            kill_proc(uv_proc)
            break
        except Exception as exc:
            log('OUTER EXCEPTION: {}'.format(exc))
            time.sleep(5)
