# 🤖 Scalping Robot V5 Pro — XAUUSD Gold Trading System

> **Autonomous, session-aware, self-healing scalping robot for XAUUSD (Gold) with a live FastAPI dashboard, bulletproof watchdog orchestration, and remote public access via serveo.net.**

---

## 📑 Table of Contents

1. [System Overview](#-system-overview)
2. [Architecture](#-architecture)
3. [Quick Start](#-quick-start)
4. [API Endpoints](#-api-endpoints)
5. [Trading Parameters](#-trading-parameters)
6. [Session Filter](#-session-filter)
7. [Balance Milestones & Lot Scaling](#-balance-milestones--lot-scaling)
8. [Signal Confluence Logic](#-signal-confluence-logic)
9. [File Reference](#-file-reference)
10. [Logs & Monitoring](#-logs--monitoring)
11. [Public Access (serveo.net)](#-public-access-servoenet)
12. [MT4 / MT5 Installation](#-mt4--mt5-installation)
13. [Presets](#-presets)
14. [Testing](#-testing)
15. [Troubleshooting](#-troubleshooting)

---

## 🌐 System Overview

| Feature | Detail |
|---|---|
| **Symbol** | XAUUSD (Gold vs USD) |
| **Timeframe** | M1 / M5 scalping |
| **Engine** | Python 3.11 + MetaTrader 5 API |
| **Dashboard** | OmniCommand FastAPI + live HTML UI |
| **Resilience** | Bulletproof watchdog auto-restart (process + tunnel) |
| **Session Filter** | London 07:00–16:00 UTC · NY 13:00–22:00 UTC |
| **Lot Scaling** | Auto-scales lot size at balance milestones |
| **Signals** | MACD + EMA + RSI triple-confluence |
| **Public Access** | serveo.net SSH reverse tunnel (auto-restarts) |
| **Deployment** | Windows Task Scheduler / VBS silent launch |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  PROCESS ORCHESTRATION                  │
│                                                         │
│   ┌──────────────────────┐                              │
│   │   Windows Task       │  ← Boots on system start     │
│   │   Scheduler /        │                              │
│   │   launch_watchdog.vbs│                              │
│   └──────────┬───────────┘                              │
│              │ spawns                                   │
│   ┌──────────▼───────────────────────────────────────┐  │
│   │           watchdog_runner.py  🐕                  │  │
│   │  Monitors & auto-restarts crashed processes       │  │
│   └────┬──────────────────┬──────────────────┬───────┘  │
│        │ spawns           │ spawns           │ spawns    │
│   ┌────▼────┐      ┌──────▼──────┐   ┌──────▼───────┐  │
│   │ trader  │      │   uvicorn   │   │   tunnel_    │  │
│   │(mt5_    │      │  (FastAPI)  │   │  watchdog.py │  │
│   │live_    │      │  port 8899  │   │  (serveo.net)│  │
│   │trader)  │      └──────┬──────┘   └──────────────┘  │
│   └────┬────┘             │                             │
│        │ trades           │ serves                      │
│   ┌────▼────┐      ┌──────▼──────┐                      │
│   │  MT5    │      │  /dashboard │                      │
│   │ Terminal│      │  FastAPI    │                      │
│   │(XAUUSD) │      │  REST API   │                      │
│   └─────────┘      └─────────────┘                      │
└─────────────────────────────────────────────────────────┘
```

### Component Roles

| Component | File | Role |
|---|---|---|
| 🐕 **Watchdog** | `watchdog_runner.py` | Master orchestrator — keeps trader + uvicorn alive |
| 📈 **Trader** | `python_engine/mt5_live_trader.py` | Core scalping logic, order management |
| ⚡ **Engine** | `python_engine/scalping_engine.py` | Signal generation (MACD/EMA/RSI) |
| 🏃 **Live Runner** | `python_engine/live_runner.py` | Real-time trade loop coordinator |
| 🌐 **API Server** | `omnicommand_server.py` | FastAPI + Uvicorn dashboard backend |
| 🔁 **Tunnel WD** | `tunnel_watchdog.py` | Auto-restarts serveo.net SSH tunnel |
| 🖥️ **Dashboard** | `dashboard.html` | Live browser-based monitoring UI |
| 💾 **Storage** | `python_engine/storage.py` | Trade history persistence |
| 🔬 **Backtester** | `python_engine/backtester.py` | Historical strategy testing |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11 at `C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe`
- MetaTrader 5 terminal installed and logged in
- `pip install fastapi uvicorn MetaTrader5 pandas numpy ta`

### Option 1 — Recommended: Silent Background Launch (PowerShell)

```powershell
$py = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'

# Launch watchdog (spawns trader + uvicorn automatically)
Start-Process -FilePath $py `
  -ArgumentList 'watchdog_runner.py' `
  -WorkingDirectory 'E:\scalping-robot-v5' `
  -WindowStyle Hidden
```

### Option 2 — Batch File Launch

```powershell
# Double-click or run from terminal:
E:\scalping-robot-v5\START_WATCHDOG.bat
```

### Option 3 — Windows Task Scheduler (Boot-on-Startup)

```powershell
# Register the scheduled task (run once as Administrator):
E:\scalping-robot-v5\register_task.ps1
# Or import directly:
schtasks /Create /XML "E:\scalping-robot-v5\watchdog_task.xml" /TN "ScalpingRobotV5"
```

### Option 4 — VBS Silent Launch (No Console Window)

```powershell
wscript.exe "E:\scalping-robot-v5\launch_watchdog.vbs"
```

### Verify Everything is Running

```powershell
# Quick health check
Invoke-RestMethod http://localhost:8899/health

# Or run the built-in health check script
E:\scalping-robot-v5\health_check.ps1
```

---

## 🔌 API Endpoints

Base URL: `http://localhost:8899` (local) · `https://<tunnel>.serveo.net` (remote)

| Method | Endpoint | Description | Response |
|---|---|---|---|
| `GET` | `/` | Root — system info & links | JSON: name, version, status |
| `GET` | `/health` | Health check — all subsystems | JSON: trader, uvicorn, tunnel status |
| `GET` | `/ping` | Liveness probe (lightweight) | `{"pong": true, "ts": "..."}` |
| `GET` | `/history` | Trade history (last N trades) | JSON array of closed trades |
| `GET` | `/metrics` | Live P&L, win rate, drawdown, equity | JSON metrics object |
| `POST` | `/trader/restart` | Gracefully restart the trader process | `{"restarted": true}` |
| `GET` | `/dashboard` | Serves `dashboard.html` live UI | HTML page |

### Example Requests

```powershell
# Health check
curl http://localhost:8899/health

# Trade history
curl http://localhost:8899/history

# Live metrics
curl http://localhost:8899/metrics

# Restart trader
curl -X POST http://localhost:8899/trader/restart
```

---

## 📊 Trading Parameters

| Parameter | Value | Notes |
|---|---|---|
| **Symbol** | `XAUUSD` | Gold vs US Dollar |
| **Default Lot Size** | `0.02` | Starting lot (micro-scalp) |
| **Take Profit** | `30 pips` | ~\$0.30/pip for 0.02 lots |
| **Stop Loss** | `40 pips` | Max risk per trade |
| **Trailing Stop** | `18 pips` | Activates after breakeven |
| **Breakeven Trigger** | `12 pips` | Move SL to entry at +12 pips |
| **Max Open Trades** | `3` | Simultaneous position limit |
| **Magic Number** | `20250605` | Identifies robot's orders in MT5 |
| **Slippage** | `3 pips` | Max allowed entry slippage |

---

## 🕐 Session Filter

The robot **only trades during high-liquidity sessions** — no trades are placed during off-hours or Asian consolidation.

```
UTC Timeline:
  00:00 ──── 07:00 ════════════════════ 16:00 ──── 22:00 ──── 00:00
              │◄─── London Session ───►│
                              │◄──── NY Session ─────►│
                              │◄── Overlap (Peak) ───►│
                           13:00                    22:00
```

| Session | UTC Open | UTC Close | Characteristics |
|---|---|---|---|
| 🇬🇧 **London** | 07:00 | 16:00 | High volume, strong XAUUSD moves |
| 🇺🇸 **New York** | 13:00 | 22:00 | US data releases, continuation |
| ⚡ **Overlap** | 13:00 | 16:00 | Peak liquidity, highest pip movement |

> **Outside these windows**: All new order placements are blocked. Open positions are still managed (TP/SL/trailing remain active).

---

## 🎯 Balance Milestones & Lot Scaling

The system **automatically scales lot size** as the account grows — compounding gains without manual intervention.

| Balance Level | Lot Size | Risk Profile |
|---|---|---|
| \$10,000 → \$10,149 | **0.02 lots** | Base (conservative entry) |
| \$10,150 → \$10,199 | **0.03 lots** | Scale-up tier 1 (+50% size) |
| \$10,200 → \$10,299 | **0.04 lots** | Scale-up tier 2 (+100% size) |
| **\$10,300+** | 🏆 **Target Reached** | Mission complete — pause or reset |

```
$10,000 ──► $10,150 ──► $10,200 ──► $10,300
  0.02 lots   0.03 lots   0.04 lots   🎯 TARGET
```

> **Milestone target**: Grow \$10,000 → \$10,300 (+3%) with controlled compounding.

---

## 📡 Signal Confluence Logic

A trade is only opened when **all three indicators agree**:

```
┌─────────────────────────────────────────────────────┐
│              ENTRY SIGNAL CONFLUENCE                │
│                                                     │
│  MACD ──► Bullish/Bearish crossover confirmed       │
│    +                                                │
│  EMA  ──► Price above/below EMA (trend filter)      │
│    +                                                │
│  RSI  ──► Not overbought/oversold (40–60 zone entry)│
│                                                     │
│  ══════════════════════════════════════════════     │
│  ALL THREE = ✅  →  PLACE ORDER                     │
│  ANY MISSING = ❌ →  SKIP (no trade noise)          │
└─────────────────────────────────────────────────────┘
```

| Indicator | BUY Signal | SELL Signal |
|---|---|---|
| **MACD** | MACD line crosses above signal | MACD line crosses below signal |
| **EMA** | Price > EMA (uptrend confirmed) | Price < EMA (downtrend confirmed) |
| **RSI** | RSI between 40–60 (not overbought) | RSI between 40–60 (not oversold) |

---

## 📁 File Reference

### Core Python Files

| File | Purpose |
|---|---|
| [`watchdog_runner.py`](watchdog_runner.py) | 🐕 Master watchdog — spawns & monitors trader + uvicorn |
| [`omnicommand_server.py`](omnicommand_server.py) | 🌐 FastAPI REST API server (OmniCommand dashboard backend) |
| [`tunnel_watchdog.py`](tunnel_watchdog.py) | 🔁 Keeps serveo.net SSH tunnel alive, auto-restarts |
| [`supervisor.py`](supervisor.py) | 🔧 Alternative supervisor orchestrator |
| [`escape_launch.py`](escape_launch.py) | 🚀 Isolated launch helper for clean process spawning |
| [`python_engine/mt5_live_trader.py`](python_engine/mt5_live_trader.py) | 📈 Core MT5 trading logic, order placement & management |
| [`python_engine/scalping_engine.py`](python_engine/scalping_engine.py) | ⚡ Signal generation engine (MACD + EMA + RSI) |
| [`python_engine/live_runner.py`](python_engine/live_runner.py) | 🏃 Real-time trading loop coordinator |
| [`python_engine/backtester.py`](python_engine/backtester.py) | 🔬 Historical backtest runner |
| [`python_engine/storage.py`](python_engine/storage.py) | 💾 Trade history storage & retrieval |

### Launch & Automation

| File | Purpose |
|---|---|
| [`START_WATCHDOG.bat`](START_WATCHDOG.bat) | 🟢 One-click watchdog launcher (batch) |
| [`START_MT5_LIVE_TRADER.bat`](START_MT5_LIVE_TRADER.bat) | 🟢 Direct MT5 trader launcher (batch) |
| [`launch_watchdog.vbs`](launch_watchdog.vbs) | 🔇 Silent VBS launcher (no console window) |
| [`supervisor.vbs`](supervisor.vbs) | 🔇 Silent VBS supervisor launcher |
| [`register_task.ps1`](register_task.ps1) | 📅 Registers Windows Task Scheduler boot task |
| [`watchdog_task.xml`](watchdog_task.xml) | 📅 Task Scheduler XML definition |
| [`INSTALL_MT5.bat`](INSTALL_MT5.bat) | 📦 MT5 installation helper |
| [`install_to_mt4.bat`](install_to_mt4.bat) | 📦 MT4 EA/indicator installation helper |

### Dashboard & Monitoring

| File | Purpose |
|---|---|
| [`dashboard.html`](dashboard.html) | 🖥️ Live browser-based trading dashboard |
| [`live_status.json`](live_status.json) | 📊 Real-time status file (read by dashboard) |
| [`health_check.ps1`](health_check.ps1) | ✅ PowerShell health verification script |
| [`verify_launch.ps1`](verify_launch.ps1) | ✅ Post-launch process verification |
| [`verify2.ps1`](verify2.ps1) | ✅ Secondary verification script |
| [`diagnose_jobs.ps1`](diagnose_jobs.ps1) | 🔍 Job diagnostics PowerShell script |
| [`diag2.ps1`](diag2.ps1) | 🔍 Extended diagnostics script |

### Diagnostics & Signals

| File | Purpose |
|---|---|
| [`restart_signal.txt`](restart_signal.txt) | 🔄 Trigger file — watchdog polls for manual restart |
| [`pytest.ini`](pytest.ini) | 🧪 pytest configuration |
| [`tests/test_scalping_robot.py`](tests/test_scalping_robot.py) | 🧪 Unit & integration test suite |

### Log Files

| Log File | Process Logged |
|---|---|
| `watchdog_out.log` / `watchdog_err.log` | Watchdog stdout / stderr |
| `trader_out.log` / `trader_err.log` | MT5 trader stdout / stderr |
| `uvicorn_out.log` / `uvicorn_err.log` | FastAPI/Uvicorn stdout / stderr |
| `live_runner_out.log` / `live_runner_err.log` | Live runner stdout / stderr |
| `serveo_out.log` / `serveo_err.log` | serveo.net tunnel stdout / stderr |
| `cf_out.log` / `cf_err.log` | Cloudflare tunnel stdout / stderr |
| `cf_tunnel.log` / `cf_tunnel_err.log` | Cloudflare tunnel events |
| `lhr_tunnel.log` / `lhr_err.log` | LHR tunnel logs |
| `supervisor.log` | Supervisor process log |
| `watchdog_launcher.log` | Launcher bootstrap log |

### Presets

| File | Use Case |
|---|---|
| [`Presets/Safe_Scalper_XAUUSD_M1.set`](Presets/Safe_Scalper_XAUUSD_M1.set) | ✅ Main XAUUSD M1 preset (recommended) |
| [`Presets/Conservative_EURUSD_M5.set`](Presets/Conservative_EURUSD_M5.set) | Conservative EURUSD M5 alternative |
| [`Presets/High_Yield_Recovery_M5.set`](Presets/High_Yield_Recovery_M5.set) | Aggressive recovery mode preset |

---

## 📋 Logs & Monitoring

### Real-time Log Tailing (PowerShell)

```powershell
# Watch all logs simultaneously
Get-Content "E:\scalping-robot-v5\watchdog_out.log" -Wait -Tail 20
Get-Content "E:\scalping-robot-v5\trader_out.log"   -Wait -Tail 20
Get-Content "E:\scalping-robot-v5\uvicorn_out.log"  -Wait -Tail 20
```

### Check Live Status JSON

```powershell
Get-Content "E:\scalping-robot-v5\live_status.json" | ConvertFrom-Json
```

### Run Diagnostics

```powershell
# Full diagnostic suite
& "E:\scalping-robot-v5\diagnose_jobs.ps1"

# Health check
& "E:\scalping-robot-v5\health_check.ps1"
```

---

## 🌍 Public Access (serveo.net)

The robot exposes its dashboard publicly through a **serveo.net SSH reverse tunnel**, managed by `tunnel_watchdog.py`.

```
Internet Browser
      │
      ▼ https://<random>.serveo.net
  serveo.net SSH Gateway
      │
      ▼ SSH reverse tunnel
  localhost:8899  (OmniCommand FastAPI)
      │
      ▼
  dashboard.html  (Live UI)
```

### How it Works

1. `tunnel_watchdog.py` runs `ssh -R 80:localhost:8899 serveo.net`
2. serveo assigns a public HTTPS URL (logged to `serveo_out.log`)
3. If the tunnel drops, `tunnel_watchdog.py` auto-restarts it within seconds
4. The watchdog (`watchdog_runner.py`) also monitors `tunnel_watchdog.py` and restarts it if needed

### Get Your Public URL

```powershell
# Read the assigned serveo URL from log
Select-String -Path "E:\scalping-robot-v5\serveo_out.log" -Pattern "serveo.net"
```

### Manual Tunnel Test

```powershell
ssh -R 80:localhost:8899 serveo.net
```

---

## 🔧 MT4 / MT5 Installation

### MT5 Python Engine (Recommended)

```powershell
# Install MT5 Python package
C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe -m pip install MetaTrader5

# Run installer batch
E:\scalping-robot-v5\INSTALL_MT5.bat
```

### MT4 EA Installation

```powershell
# Copy MQL4 files to MT4 data folder
E:\scalping-robot-v5\install_to_mt4.bat
```

MQL4 source files are in:
```
E:\scalping-robot-v5\Scalping Robot V5\MQL4\
```

---

## 🎛️ Presets

Load presets directly into MT4/MT5 via **File → Load → .set file**:

| Preset | Symbol | Timeframe | Risk | Description |
|---|---|---|---|---|
| `Safe_Scalper_XAUUSD_M1.set` | XAUUSD | M1 | Low | Recommended production config |
| `Conservative_EURUSD_M5.set` | EURUSD | M5 | Low | Conservative alternative |
| `High_Yield_Recovery_M5.set` | Any | M5 | High | Aggressive drawdown recovery |

---

## 🧪 Testing

```powershell
$py = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'

# Run full test suite
& $py -m pytest E:\scalping-robot-v5\tests\ -v

# Run backtester
& $py E:\scalping-robot-v5\python_engine\backtester.py

# Single test file
& $py -m pytest E:\scalping-robot-v5\tests\test_scalping_robot.py -v
```

---

## 🛠️ Troubleshooting

### Watchdog Won't Start

```powershell
# Check if Python path is correct
Test-Path 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'

# Run manually to see errors
C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe E:\scalping-robot-v5\watchdog_runner.py
```

### API Not Responding (port 8899)

```powershell
# Check if uvicorn is running
netstat -ano | findstr :8899

# Check uvicorn logs
Get-Content "E:\scalping-robot-v5\uvicorn_err.log" -Tail 30
```

### MT5 Connection Issues

```powershell
# Verify MT5 terminal is running and logged in
# Check trader error log
Get-Content "E:\scalping-robot-v5\trader_err.log" -Tail 30
```

### Tunnel Not Working

```powershell
# Check serveo log for assigned URL
Get-Content "E:\scalping-robot-v5\serveo_out.log" -Tail 20

# Check for SSH in running processes
Get-Process ssh -ErrorAction SilentlyContinue
```

### Force Restart Trader

```powershell
# Via API (recommended)
curl -X POST http://localhost:8899/trader/restart

# Via signal file (watchdog polls this)
"restart" | Out-File "E:\scalping-robot-v5\restart_signal.txt"
```

### Run Full Diagnostics

```powershell
& "E:\scalping-robot-v5\diagnose_jobs.ps1"
& "E:\scalping-robot-v5\diag2.ps1"
```

---

## ⚠️ Risk Disclaimer

> **Trading forex and gold involves significant risk of loss. This software is provided for educational and research purposes. Past performance does not guarantee future results. Never risk money you cannot afford to lose. Always test in a demo environment before going live.**

---

## 📌 Version Info

| Property | Value |
|---|---|
| **Version** | V5 Pro |
| **Python** | 3.11 |
| **FastAPI** | Latest |
| **MT5 API** | MetaTrader5 (official Python package) |
| **Working Directory** | `E:\scalping-robot-v5` |
| **API Port** | `8899` |
| **Author** | absh5 |
| **Last Updated** | September 2026 |

---

*Built with ❤️ for autonomous gold scalping — stay disciplined, let the bot do the work.*
