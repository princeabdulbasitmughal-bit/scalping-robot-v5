"""
OmniCommand Pro — FastAPI Status Server for Scalping Robot V5
Port: 8899
Serves live_status.json and system health metrics
"""
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, HTMLResponse
    import uvicorn
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn[standard]", "-q"])
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, HTMLResponse
    import uvicorn

START_TIME = time.time()
STATUS_FILE = Path(__file__).parent / "live_status.json"

# File read cache — avoids hammering disk on every 2s poll
_status_cache: dict = {}
_status_cache_ts: float = 0.0
_STATUS_CACHE_TTL: float = 2.0  # seconds

app = FastAPI(title="OmniCommand Pro", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_live_status() -> dict:
    """Safely read live_status.json with in-memory TTL cache (2s) to reduce disk I/O."""
    global _status_cache, _status_cache_ts
    now = time.monotonic()
    if now - _status_cache_ts < _STATUS_CACHE_TTL and _status_cache:
        return _status_cache
    try:
        if STATUS_FILE.exists():
            raw = STATUS_FILE.read_bytes()
            _status_cache = json.loads(raw.decode("utf-8", errors="replace"))
            _status_cache_ts = now
            return _status_cache
    except Exception as e:
        return {"error": str(e), "status": "READ_ERROR"}
    return {"status": "NO_DATA"}


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    dash_path = Path(__file__).parent / "dashboard.html"
    if dash_path.exists():
        return HTMLResponse(content=dash_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>OmniCommand Pro Trading Server is Active</h1>")


@app.get("/health")
async def health():
    uptime = round(time.time() - START_TIME, 1)
    live = read_live_status()
    # Check actual trader staleness (>5 min = likely dead)
    trader_alive = False
    try:
        updated_str = live.get("updated_at", "")
        if updated_str:
            updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            age_sec = (datetime.now(timezone.utc) - updated_dt).total_seconds()
            trader_alive = age_sec < 300  # 5 min threshold
    except Exception:
        trader_alive = live.get("status", "") != ""

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
    return JSONResponse(read_live_status())


@app.get("/metrics")
async def metrics():
    live = read_live_status()
    balance = live.get("balance", 10000)
    equity = live.get("equity", 10000)
    pnl = live.get("daily_pnl", 0)
    trades = live.get("total_trades", 0)
    win_rate = live.get("win_rate_pct", 0)
    return JSONResponse({
        "balance_usd": balance,
        "equity_usd": equity,
        "daily_pnl_usd": pnl,
        "daily_pnl_pct": round((pnl / 10000) * 100, 4) if pnl else 0,
        "total_trades": trades,
        "win_rate_pct": win_rate,
        "open_positions": len(live.get("open_positions", [])),
        "risk_status": "SAFE" if equity > 9500 else "WARNING" if equity > 9000 else "CRITICAL",
    })


@app.get("/trader/restart")
async def restart_trader():
    """Manually trigger trader restart via watchdog signal."""
    try:
        signal_file = Path(__file__).parent / "restart_signal.txt"
        signal_file.write_text(str(time.time()))
        return JSONResponse({"ok": True, "message": "Restart signal sent"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


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


@app.get("/ping")
async def ping():
    """Liveness probe."""
    return JSONResponse({"pong": True, "ts": time.time()})


if __name__ == "__main__":
    print("[OmniCommand Pro] Starting on http://0.0.0.0:8899")
    uvicorn.run(app, host="0.0.0.0", port=8899, log_level="warning")
