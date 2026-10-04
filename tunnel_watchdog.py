"""
Tunnel Watchdog - Auto-restarts serveo.net SSH tunnel permanently
Requirements:
1. Tunnel must use serveo.net ONLY (NOT ngrok or cloudflare - they are BLOCKED)
2. SSH command: ssh -R 80:localhost:8899 serveo.net
3. On URL rotation, write new URL to E:\scalping-robot-v5\tunnel_url.txt
4. Also update live_status.json 'tunnel_url' field
5. Reconnect within 60 seconds of drop
"""
import subprocess
import time
import re
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

BASE        = Path(r'E:\scalping-robot-v5')
TUNNEL_OUT  = BASE / 'serveo_out.log'
TUNNEL_ERR  = BASE / 'serveo_err.log'
TUNNEL_URL  = BASE / 'tunnel_url.txt'
STATUS_FILE = BASE / 'live_status.json'
LOG         = BASE / 'tunnel_watchdog.log'

# SSH tunnel configuration - serveo.net ONLY
SSH_CMD = [
    'ssh',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'ServerAliveInterval=15',
    '-o', 'ServerAliveCountMax=3',
    '-R', '80:localhost:8899',
    'serveo.net'
]

CHECK_INTERVAL_SEC = 15   # Reconnect check interval (< 60s drop requirement)


def _hidden_startupinfo():
    if sys.platform == 'win32':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    return None


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def update_live_status(url: str):
    """Update live_status.json 'tunnel_url' field atomically."""
    if not url:
        return
    try:
        data = {}
        if STATUS_FILE.exists():
            try:
                data = json.loads(STATUS_FILE.read_text(encoding='utf-8'))
            except Exception:
                data = {}
        if data.get('tunnel_url') != url:
            data['tunnel_url'] = url
            tmp = STATUS_FILE.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
            tmp.replace(STATUS_FILE)
            log(f'Updated live_status.json tunnel_url: {url}')
    except Exception as e:
        log(f'Error updating live_status.json: {e}')


def set_tunnel_url(url: str):
    """Write URL to tunnel_url.txt and update live_status.json."""
    if not url:
        return
    try:
        TUNNEL_URL.write_text(url.strip(), encoding='utf-8')
        update_live_status(url.strip())
    except Exception as e:
        log(f'Error saving tunnel URL: {e}')


def start_tunnel():
    log('Starting serveo.net tunnel on port 8899 (ssh -R 80:localhost:8899 serveo.net)...')
    try:
        out = open(TUNNEL_OUT, 'w', encoding='utf-8', errors='replace')
        err = open(TUNNEL_ERR, 'w', encoding='utf-8', errors='replace')
        p = subprocess.Popen(
            SSH_CMD,
            cwd=str(BASE),
            stdout=out,
            stderr=err,
            startupinfo=_hidden_startupinfo()
        )
        log(f'SSH PID={p.pid}')
        return p, out, err
    except Exception as e:
        log(f'ERROR starting tunnel: {e}')
        return None, None, None


def safe_kill(p):
    if p is None:
        return
    try:
        p.terminate()
        p.wait(timeout=2)
    except Exception:
        try:
            p.kill()
            p.wait(timeout=2)
        except Exception:
            pass


def safe_close(f):
    if f is None:
        return
    try:
        f.close()
    except Exception:
        pass


def extract_url() -> Optional[str]:
    """Extract latest active tunnel URL from serveo stdout log."""
    try:
        if not TUNNEL_OUT.exists():
            return None
        content = TUNNEL_OUT.read_text(encoding='utf-8', errors='replace')
        lower = content.lower()
        if 'expired' in lower or 'connection closed' in lower:
            return None
        # Primary match: 'Forwarding HTTP traffic from <url>'
        matches = re.findall(r'Forwarding HTTP traffic from (https?://\S+)', content)
        if matches:
            return matches[-1].rstrip('.')
        # Secondary fallback: *.serveousercontent.com
        matches = re.findall(r'https?://[a-zA-Z0-9\-\.]+\.serveousercontent\.com', content)
        if matches:
            return matches[-1]
    except Exception:
        pass
    return None


def is_tunnel_alive(p) -> bool:
    """
    Check if tunnel process is alive and not expired or dropped.
    Returns False if process terminated or session expired/disconnected.
    """
    if p is None or p.poll() is not None:
        return False
    try:
        if TUNNEL_OUT.exists():
            content = TUNNEL_OUT.read_text(encoding='utf-8', errors='replace').lower()
            if 'expired' in content or 'connection closed' in content or 'session closed' in content:
                return False
    except Exception:
        pass
    return True


def wait_for_url(max_wait_sec: int = 15) -> Optional[str]:
    """Poll TUNNEL_OUT until a valid URL appears or timeout."""
    start = time.time()
    while time.time() - start < max_wait_sec:
        url = extract_url()
        if url:
            return url
        time.sleep(1)
    return None


if __name__ == '__main__':
    log('=== TUNNEL WATCHDOG STARTED ===')
    p, out, err = start_tunnel()
    current_url = wait_for_url(15)

    if current_url:
        set_tunnel_url(current_url)
        log(f'PUBLIC URL: {current_url}')
    else:
        log('URL not yet available -- will poll in loop')

    while True:
        try:
            time.sleep(CHECK_INTERVAL_SEC)
            alive = is_tunnel_alive(p)

            if not alive:
                log('Tunnel dropped or expired! Reconnecting within 60s...')
                safe_kill(p)
                safe_close(out)
                safe_close(err)
                time.sleep(2)
                p, out, err = start_tunnel()
                new_url = wait_for_url(15)
                if new_url:
                    if new_url != current_url:
                        log(f'[ROTATION] NEW URL: {new_url}')
                        current_url = new_url
                    else:
                        log(f'Reconnected URL: {new_url}')
                    set_tunnel_url(new_url)
            else:
                new_url = extract_url()
                if new_url:
                    if new_url != current_url:
                        log(f'[ROTATION] URL changed from {current_url} to {new_url}')
                        current_url = new_url
                        set_tunnel_url(current_url)
                    else:
                        # Ensure live_status.json and tunnel_url.txt stay in sync
                        update_live_status(current_url)
                        log(f'Alive: {current_url}')
        except KeyboardInterrupt:
            log('Stopped by user.')
            safe_kill(p)
            safe_close(out)
            safe_close(err)
            break
        except Exception as e:
            log(f'Exception (self-healing): {e}')
            time.sleep(5)
