"""
OmniCommand Pro — FastAPI Status Server for Scalping Robot V5
Port: 8899
Serves live_status.json and system health metrics
"""
import json
import os
import signal
import subprocess
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

try:
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, HTMLResponse
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    import uvicorn
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn[standard]", "-q"])
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, HTMLResponse
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    import uvicorn

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [OmniCommand] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("omnicommand")

START_TIME = time.time()
STATUS_FILE = Path(__file__).parent / "live_status.json"

# File read cache — avoids hammering disk on every 2s poll
_status_cache: dict = {}
_status_cache_ts: float = 0.0
_STATUS_CACHE_TTL: float = 2.0  # seconds

app = FastAPI(title="OmniCommand Pro", version="5.0.0")

# ---------------------------------------------------------------------------
# CORS — allow web dashboard on any origin
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.info("REQUEST  %s  %s  client=%s", request.method, request.url.path,
             request.client.host if request.client else "unknown")
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        log.error("ERROR    %s  %s  %.1fms  %s", request.method, request.url.path, elapsed, exc)
        return JSONResponse({"ok": False, "error": "Internal server error", "detail": str(exc)}, status_code=500)
    elapsed = round((time.perf_counter() - start) * 1000, 1)
    log.info("RESPONSE %s  %s  status=%d  %.1fms", request.method, request.url.path,
             response.status_code, elapsed)
    return response

# ---------------------------------------------------------------------------
# Global exception handlers — ensure every error returns valid JSON
# ---------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"ok": False, "error": exc.detail, "status_code": exc.status_code},
                        status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse({"ok": False, "error": "Validation error", "detail": str(exc)}, status_code=422)

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse({"ok": False, "error": "Internal server error", "detail": str(exc)}, status_code=500)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def read_live_status() -> dict:
    """Safely read live_status.json with:
    - in-memory TTL cache (2s) to reduce disk I/O
    - up to 3 retry attempts (handles Windows file-lock / temporary absence)
    - returns a safe fallback dict if file is unreadable
    """
    global _status_cache, _status_cache_ts
    now = time.monotonic()
    if now - _status_cache_ts < _STATUS_CACHE_TTL and _status_cache:
        return _status_cache

    last_exc: str = ""
    for attempt in range(3):
        try:
            if STATUS_FILE.exists():
                raw = STATUS_FILE.read_bytes()
                if not raw.strip():
                    time.sleep(0.05 * (attempt + 1))
                    continue
                data = json.loads(raw.decode("utf-8", errors="replace"))
                _status_cache = data
                _status_cache_ts = now
                return _status_cache
            else:
                # File temporarily absent — return stale cache if available
                if _status_cache:
                    return _status_cache
                return {"status": "NO_DATA", "error": "live_status.json not found"}
        except (json.JSONDecodeError, OSError) as exc:
            last_exc = str(exc)
            time.sleep(0.05 * (attempt + 1))

    # All attempts failed — return stale cache or error sentinel
    if _status_cache:
        return _status_cache
    return {"status": "READ_ERROR", "error": last_exc}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    dash_path = Path(__file__).parent / "dashboard.html"
    if dash_path.exists():
        return HTMLResponse(content=dash_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>OmniCommand Pro Trading Server is Active</h1>")


@app.get("/ping")
async def ping():
    """Liveness probe."""
    return JSONResponse({"pong": True, "ts": time.time()})


@app.get("/health")
async def health():
    """Returns current live_status.json data plus server uptime / staleness check."""
    uptime = round(time.time() - START_TIME, 1)
    live = read_live_status()

    # Detect trader staleness (>5 min since last status write = likely dead)
    trader_alive = False
    try:
        updated_str = live.get("updated_at", "")
        if updated_str:
            updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            age_sec = (datetime.now(timezone.utc) - updated_dt).total_seconds()
            trader_alive = age_sec < 300  # 5-minute threshold
    except Exception:
        trader_alive = bool(live.get("status", ""))

    return JSONResponse({
        "ok": True,
        "service": "OmniCommand Pro",
        "port": 8899,
        "supersender_port": 5051,
        "uptime_sec": uptime,
        "trader_status": live.get("status", "UNKNOWN"),
        "trader_alive": trader_alive,
        "balance": live.get("balance", 0),
        "equity": live.get("equity", 0),
        "daily_pnl": live.get("daily_pnl", 0),
        "net_pnl": round(live.get("balance", 10000) - 10000, 2),
        "total_trades": live.get("total_trades", 0),
        "win_rate_pct": live.get("win_rate_pct", 0),
        "open_positions": len(live.get("open_positions", [])),
        "symbol": live.get("symbol", "XAUUSD"),
        "last_signal": live.get("last_signal", "NONE"),
        "spread_pips": live.get("spread_pips", 0),
        "rolling_spread_ema": live.get("rolling_spread_ema", 0),
        "current_price": live.get("current_price", 0),
        "latency_metrics": live.get("latency_metrics", {}),
        "updated_at": live.get("updated_at", ""),
    })


@app.get("/status")
async def status():
    """Full raw live_status.json payload."""
    return JSONResponse(read_live_status())


@app.get("/metrics")
async def metrics():
    """Key performance metrics: win_rate, total_trades, balance, daily_pnl, equity, current_price."""
    live = read_live_status()
    balance = live.get("balance", 10000)
    equity = live.get("equity", 10000)
    pnl = live.get("daily_pnl", 0)
    trades = live.get("total_trades", 0)
    win_rate = live.get("win_rate_pct", 0)
    current_price = live.get("current_price", 0)

    return JSONResponse({
        "win_rate": win_rate,            # alias used by dashboard
        "win_rate_pct": win_rate,
        "total_trades": trades,
        "balance": balance,
        "balance_usd": balance,
        "equity": equity,
        "equity_usd": equity,
        "daily_pnl": pnl,
        "daily_pnl_usd": pnl,
        "daily_pnl_pct": round((pnl / 10000) * 100, 4) if pnl else 0,
        "current_price": current_price,
        "open_positions": len(live.get("open_positions", [])),
        "risk_status": "SAFE" if equity > 9500 else "WARNING" if equity > 9000 else "CRITICAL",
        "updated_at": live.get("updated_at", ""),
    })


@app.get("/positions")
async def positions():
    """Return open_positions list from live_status.json."""
    live = read_live_status()
    open_pos = live.get("open_positions", [])
    return JSONResponse({
        "ok": True,
        "count": len(open_pos),
        "open_positions": open_pos,
        "updated_at": live.get("updated_at", ""),
    })


@app.get("/history")
async def trade_history():
    """Return recent trade history from live_status.json."""
    live = read_live_status()
    return JSONResponse({
        "total_trades": live.get("total_trades", 0),
        "win_rate_pct": live.get("win_rate_pct", 0),
        "daily_pnl": live.get("daily_pnl", 0),
        "balance": live.get("balance", 0),
        "open_positions": live.get("open_positions", []),
        "mt5_connected": live.get("mt5_connected", False),
        "latency_metrics": live.get("latency_metrics", {}),
    })


@app.get("/trader/restart")
async def restart_trader():
    """Manually trigger trader restart via watchdog signal file."""
    try:
        signal_file = Path(__file__).parent / "restart_signal.txt"
        signal_file.write_text(str(time.time()))
        log.info("Restart signal written to %s", signal_file)
        return JSONResponse({"ok": True, "message": "Restart signal sent", "ts": time.time()})
    except Exception as exc:
        log.error("Failed to write restart signal: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/trader/stop")
async def stop_trader():
    """Gracefully stop the trader by writing a stop signal file and (optionally) killing
    the trader process by PID if recorded in live_status.json."""
    try:
        # Write a stop signal file for the watchdog / trader to pick up
        stop_file = Path(__file__).parent / "stop_signal.txt"
        stop_file.write_text(str(time.time()))
        log.info("Stop signal written to %s", stop_file)

        # Attempt graceful SIGTERM / taskkill if PID is recorded
        live = read_live_status()
        trader_pid = live.get("pid") or live.get("trader_pid")
        killed = False
        if trader_pid:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(trader_pid), "/F"],
                        capture_output=True, timeout=5
                    )
                else:
                    os.kill(int(trader_pid), signal.SIGTERM)
                killed = True
                log.info("Sent kill signal to trader PID %s", trader_pid)
            except Exception as kill_exc:
                log.warning("Could not kill PID %s: %s", trader_pid, kill_exc)

        return JSONResponse({
            "ok": True,
            "message": "Stop signal sent",
            "pid_killed": killed,
            "trader_pid": trader_pid,
            "ts": time.time(),
        })
    except Exception as exc:
        log.error("Failed to stop trader: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/system")
async def system_health():
    """Full system health: RAM, CPU, disk, all services."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1)
        disk = psutil.disk_usage("E:\\")
        live = read_live_status()
        return JSONResponse({
            "ram_used_gb": round(mem.used / 1e9, 2),
            "ram_total_gb": round(mem.total / 1e9, 2),
            "ram_pct": mem.percent,
            "cpu_pct": cpu,
            "disk_free_gb": round(disk.free / 1e9, 2),
            "disk_used_pct": disk.percent,
            "trader_status": live.get("status", "UNKNOWN"),
            "balance": live.get("balance", 0),
            "current_price": live.get("current_price", 0),
            "uptime_sec": round(time.time() - START_TIME, 1),
        })
    except ImportError:
        return JSONResponse({"error": "psutil not installed — run: pip install psutil"}, status_code=501)
    except Exception as exc:
        log.error("system_health error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Starting OmniCommand Pro on http://0.0.0.0:8899")
    uvicorn.run(app, host="0.0.0.0", port=8899, log_level="warning")
