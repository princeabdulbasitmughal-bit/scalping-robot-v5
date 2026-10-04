"""
Tunnel Watchdog - Auto-restarts serveo.net SSH tunnel permanently
"""
import subprocess
import time
import re
from pathlib import Path
from datetime import datetime

BASE       = Path(__file__).parent
TUNNEL_OUT = BASE / 'serveo_out.log'
TUNNEL_ERR = BASE / 'serveo_err.log'
TUNNEL_URL = BASE / 'tunnel_url.txt'
LOG        = BASE / 'tunnel_watchdog.log'


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def start_tunnel():
    log('Starting serveo.net tunnel on port 8899...')
    try:
        out = open(TUNNEL_OUT, 'w', encoding='utf-8', errors='replace')
        err = open(TUNNEL_ERR, 'w', encoding='utf-8', errors='replace')
        p = subprocess.Popen(
            ['ssh', '-o', 'StrictHostKeyChecking=no',
             '-o', 'ServerAliveInterval=30',
             '-o', 'ServerAliveCountMax=5',
             '-R', '80:localhost:8899', 'serveo.net'],
            stdout=out, stderr=err
        )
        log(f'SSH PID={p.pid}')
        return p, out, err
    except Exception as e:
        log(f'ERROR starting tunnel: {e}')
        return None, None, None


def extract_url():
    """Extract tunnel URL from serveo stdout log."""
    try:
        content = TUNNEL_OUT.read_text(encoding='utf-8', errors='replace')
        m = re.search(r'https://[\w\-\.]+\.serveousercontent\.com', content)
        if m:
            url = m.group(0)
            TUNNEL_URL.write_text(url, encoding='utf-8')
            return url
    except Exception:
        pass
    return None


if __name__ == '__main__':
    log('=== TUNNEL WATCHDOG STARTED ===')
    p, out, err = start_tunnel()
    time.sleep(12)

    url = extract_url()
    if url:
        log(f'PUBLIC URL: {url}')
    else:
        log('URL not yet available — will check every 30s')

    while True:
        try:
            time.sleep(30)
            alive = p is not None and p.poll() is None
            if not alive:
                log('Tunnel died! Restarting...')
                try:
                    out.close()
                    err.close()
                except Exception:
                    pass
                time.sleep(3)
                p, out, err = start_tunnel()
                time.sleep(12)
                url = extract_url()
                if url:
                    log(f'NEW URL: {url}')
            else:
                url = extract_url()
                if url:
                    log(f'Alive: {url}')
        except KeyboardInterrupt:
            log('Stopped by user.')
            break
        except Exception as e:
            log(f'Exception (self-healing): {e}')
            time.sleep(5)
