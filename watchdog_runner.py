"""
Scalping Robot V5 - BULLETPROOF Watchdog v6
Monitors mt5_live_trader + uvicorn:8899.
No WMIC (not in PATH on this machine).
No kill_port_owner (was killing running uvicorn on restart).
Outer safety loop never crashes.
"""
import time
import sys
import os
import socket
from pathlib import Path
from datetime import datetime

BASE           = Path(__file__).parent
STATUS_FILE    = BASE / 'live_status.json'
TRADER_OUT     = BASE / 'trader_out.log'
TRADER_ERR     = BASE / 'trader_err.log'
UVICORN_OUT    = BASE / 'uvicorn_out.log'
UVICORN_ERR    = BASE / 'uvicorn_err.log'
WATCHDOG_LOG   = BASE / 'watchdog_out.log'

STALE_THRESHOLD_SEC = 90
CHECK_INTERVAL_SEC  = 15
UVICORN_HOST        = '127.0.0.1'
UVICORN_PORT        = 8899
MY_PID              = os.getpid()


def log(msg):
    ts   = datetime.now().strftime('%H:%M:%S')
    line = '[{}] [WDv6] {}'.format(ts, msg)
    try:
        with open(WATCHDOG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass
    try:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()
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


def start_trader():
    import subprocess
    log('Starting mt5_live_trader...')
    try:
        out_f = open(TRADER_OUT, 'a', encoding='utf-8')
        err_f = open(TRADER_ERR, 'a', encoding='utf-8')
        proc  = subprocess.Popen(
            [sys.executable, '-m', 'python_engine.mt5_live_trader',
             '--symbol', 'XAUUSD', '--lot', '0.02',
             '--iterations', '999999', '--interval', '0.05'],
            cwd=str(BASE), stdout=out_f, stderr=err_f
        )
        log('Trader started PID={}'.format(proc.pid))
        return proc, out_f, err_f
    except Exception as e:
        log('ERROR starting trader: {}'.format(e))
        return None, None, None


def start_uvicorn():
    import subprocess
    log('Starting uvicorn:8899...')
    try:
        out_f = open(UVICORN_OUT, 'a', encoding='utf-8')
        err_f = open(UVICORN_ERR, 'a', encoding='utf-8')
        proc  = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn',
             'omnicommand_server:app',
             '--host', '0.0.0.0', '--port', str(UVICORN_PORT)],
            cwd=str(BASE), stdout=out_f, stderr=err_f
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
    log('=== WATCHDOG v6 ACTIVE PID={} ==='.format(MY_PID))
    log('Stale={}s Check={}s'.format(STALE_THRESHOLD_SEC, CHECK_INTERVAL_SEC))

    trader_proc = uv_proc = None
    trader_out  = trader_err = uv_out = uv_err = None
    cycle       = 0

    # On startup: check if uvicorn already running
    if port_open(UVICORN_HOST, UVICORN_PORT):
        log('Uvicorn:8899 already UP on startup - adopting')
        # uv_proc stays None but port is open, so we won't restart it

    while True:
        try:
            cycle += 1

            # --- Trader check ---
            trader_alive = trader_proc is not None and trader_proc.poll() is None
            age          = status_age_sec()
            is_stale     = age > STALE_THRESHOLD_SEC

            if not trader_alive or is_stale:
                reason = 'poll={}'.format(trader_proc.poll() if trader_proc else 'None')
                if is_stale and trader_alive:
                    reason = 'STALE {}s'.format(round(age, 1))
                log('Trader restart ({})'.format(reason))
                kill_proc(trader_proc)
                try:
                    if trader_out: trader_out.close()
                    if trader_err: trader_err.close()
                except Exception:
                    pass
                time.sleep(2)
                trader_proc, trader_out, trader_err = start_trader()

            # --- Uvicorn check ---
            uv_up = port_open(UVICORN_HOST, UVICORN_PORT)
            if not uv_up:
                log('Uvicorn:8899 DOWN -> restarting')
                kill_proc(uv_proc)
                try:
                    if uv_out: uv_out.close()
                    if uv_err: uv_err.close()
                except Exception:
                    pass
                uv_proc, uv_out, uv_err = start_uvicorn()
                # Wait up to 8s for port
                for _ in range(8):
                    time.sleep(1)
                    if port_open(UVICORN_HOST, UVICORN_PORT):
                        log('Uvicorn port OPEN OK')
                        uv_up = True
                        break

            # --- Heartbeat ---
            trader_alive = trader_proc is not None and trader_proc.poll() is None
            age          = status_age_sec()
            log('C={} trader={} age={}s stale={} uv={}'.format(
                cycle, trader_alive, round(age, 1), age > STALE_THRESHOLD_SEC, uv_up))

            time.sleep(CHECK_INTERVAL_SEC)

        except KeyboardInterrupt:
            log('Stopped by user.')
            kill_proc(trader_proc)
            kill_proc(uv_proc)
            break
        except Exception as exc:
            log('OUTER EXCEPTION: {}'.format(exc))
            time.sleep(5)
