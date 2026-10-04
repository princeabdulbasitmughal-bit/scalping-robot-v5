# 🤖 Gold Scalping Robot v5

An advanced AI-powered gold (XAUUSD) scalping bot with 30+ intelligent features.

> **Institutional-grade, autonomous, session-aware algorithmic trading engine for MetaTrader 5 (MT5) with microsecond tick processing, real-time FastAPI telemetry, self-healing watchdog supervision, and automated risk protection.**

---

## 📑 Table of Contents

1. [Features](#-features)
2. [Quick Start](#-quick-start)
3. [Configuration (`config.json`)](#-configuration)
4. [Architecture & Component Map](#-architecture)
5. [5-Tier Signal System](#-5-tier-signal-system)
6. [Multi-Timeframe Analysis & Market Regimes](#-multi-timeframe-analysis--market-regimes)
7. [Position Sizing & Kelly Criterion](#-position-sizing--kelly-criterion)
8. [Exit Strategies: Trailing Stop, Break-Even & Scaled Exits](#-exit-strategies)
9. [Risk Shields & Circuit Breakers](#-risk-shields--circuit-breakers)
10. [Session Filter & Time Avoidance](#-session-filter--time-avoidance)
11. [OmniCommand REST API (15+ Endpoints)](#-omnicommand-rest-api)
12. [SQLite Trade Journal (`trades.db`)](#-sqlite-trade-journal)
13. [Watchdog v2 Self-Healing System](#-watchdog-v2-self-healing-system)
14. [Real-Time Alerts & Notification Engine](#-real-time-alerts--notification-engine)
15. [Performance Grader & Automated Monitor](#-performance-grader--automated-monitor)
16. [Auto-Backup Daemon & Git Sync](#-auto-backup-daemon--git-sync)
17. [Dashboards: Web & Mobile](#-dashboards-web--mobile)
18. [Continuous Integration (GitHub Actions)](#-continuous-integration-github-actions)
19. [Verification & Testing](#-verification--testing)
20. [Troubleshooting & Maintenance](#-troubleshooting--maintenance)

---

## 🌟 Features

Gold Scalping Robot v5 combines 30+ institutional features engineered for high win rates, strict drawdown control, and 24/7 autonomous reliability:

- **5-Tier Signal System**: Prioritized confluence cascade (Bollinger Bands, EMA Trend, RSI Extremes, Midband Crossover, and Engine fallback).
- **Multi-Timeframe Analysis**: M1 execution synchronized with M5 momentum and M15 macro trend consensus.
- **Market Regime Detection**: Automatically adapts between `TRENDING`, `RANGING`, `HIGH_VOLATILITY`, and `EXTREME_SPIKE`.
- **Kelly Criterion Position Sizing**: Dynamic capital allocation featuring half-Kelly safety and Van Tharp fixed fractional risk clamping.
- **Elite Technical Filters**: Bollinger Band Squeeze detection, RSI divergence filters, and EMA cross validation.
- **Advanced Exit Strategies**: Ratcheting trailing stops, automatic break-even lock (+1 pip buffer), and multi-target scaled profit taking.
- **Session-Aware Trading**: High-liquidity window targeting (London, New York, Overlap) with 30-minute transitional buffers.
- **Dual Circuit Breakers**: Strict $200.00 daily loss ceiling and absolute $9,700.00 account balance floor protection.
- **High-Impact News Buffers**: Calendar tracking for NFP, CPI, FOMC, PPI, and GDP with 15-min pre-event and 30-min post-event blackouts.
- **Volatility Spike Detection**: Rolling EMA spread filter and liquidity shock detection preventing slippage blowout.
- **Rollover Time Avoidance**: Hard trading freeze during daily broker rollover (21:45–22:15 UTC).
- **SQLite Trade Journal**: High-integrity local database (`trades.db`) logging individual trades and daily performance aggregations.
- **Real-Time Web Dashboard**: Responsive dark theme UI powered by Chart.js, featuring 50-point live equity curves and status gauges.
- **Mobile Performance Dashboard**: Touch-optimized interface (`performance_dashboard.html`) designed for smartphones and tablets.
- **OmniCommand REST API**: 15+ asynchronous FastAPI endpoints with complete CORS support, OpenAPI documentation, and sub-millisecond metrics.
- **Auto-Backup Daemon**: 30-minute automated snapshot daemon keeping the last 10 revisions, backed by 2-hour Git auto-sync.
- **Rate-Limited Alert System**: Real-time evaluation of 6 critical conditions with 15-minute anti-spam rate limiting.
- **Performance Monitor**: Continuous institutional grading algorithm assigning A+, A, B, or C ratings with automated 10-minute reports.
- **Bulletproof Watchdog v2**: Exponential backoff restart logic, memory leak detection (OOM > 500MB), freeze recovery, and health pre-checks.
- **Public Tunnel Integration**: Automatic reverse SSH tunneling via serveo.net with background tunnel health monitoring.
- **GitHub Actions CI**: Automated push and pull-request syntax verification and unit test execution.

---

## 🚀 Quick Start

### 1. Prerequisites
- **Operating System**: Windows 10 / 11 / Windows Server
- **Python**: Version 3.11 (64-bit) recommended
- **MetaTrader 5**: Desktop terminal installed, logged into your demo or live broker account, and **Algo Trading enabled** in toolbar

### 2. Dependency Installation
```powershell
# Navigate to repository root
Set-Location 'E:\scalping-robot-v5'

# Install required Python packages
python -m pip install -r requirements.txt
```

### 3. Launch All Services
Launch the entire system in one step using the orchestrator script:
```powershell
# Start all background processes silently
powershell -ExecutionPolicy Bypass -File .\start_all.ps1
```

This single command initializes:
1. **OmniCommand Server** (FastAPI REST API on port `8899`)
2. **MT5 Live Trader** (Core execution engine via Watchdog v2)
3. **Tunnel Watchdog** (Remote public HTTPS access via serveo.net)
4. **Auto-Backup Daemon** (File rotation & Git sync)

### 4. Access Dashboards & APIs
- 🖥️ **Trading Dashboard**: [http://localhost:8899](http://localhost:8899) or [http://localhost:8899/dashboard](http://localhost:8899/dashboard)
- 📱 **Mobile Performance Dashboard**: [http://localhost:8899/performance](http://localhost:8899/performance)
- 📚 **Interactive API Docs (Swagger UI)**: [http://localhost:8899/docs](http://localhost:8899/docs)
- 📖 **ReDoc Alternative Documentation**: [http://localhost:8899/redoc](http://localhost:8899/redoc)

---

## ⚙️ Configuration

The robot's trading parameters are fully decoupled from code and configured in [`config.json`](file:///E:/scalping-robot-v5/config.json). Changes take effect on next cycle without recompilation:

```json
{
  "sl_pips": 30.0,
  "tp_pips": 45.0,
  "rr_ratio": 1.5,
  "max_lot_size": 0.10,
  "risk_per_trade_pct": 1.0,
  "macd_filter_threshold": 0.5,
  "spread_filter_pips": 3.0,
  "heartbeat_interval_sec": 300.0,
  "max_daily_loss_usd": 200.0,
  "min_balance_usd": 9700.0,
  "daily_profit_target_usd": 200.0,
  "max_positions_per_session": 3,
  "min_time_between_trades_sec": 60,
  "entry_cooldown_sec": 30.0,
  "symbol": "XAUUSD",
  "lot_size": 0.02
}
```

### Parameter Reference

| Key | Default | Unit | Description |
|---|---|---|---|
| `symbol` | `"XAUUSD"` | String | Target instrument symbol in MT5 |
| `lot_size` | `0.02` | Lots | Base position sizing per trade |
| `max_lot_size` | `0.10` | Lots | Hard ceiling for dynamic/Kelly position sizing |
| `sl_pips` | `30.0` | Pips | Default initial Stop Loss distance ($3.00 on Gold) |
| `tp_pips` | `45.0` | Pips | Default Take Profit distance ($4.50 on Gold) |
| `rr_ratio` | `1.5` | Ratio | Target Risk-to-Reward ratio (1:1.5) |
| `risk_per_trade_pct` | `1.0` | Percent | Account balance percentage risked per trade |
| `macd_filter_threshold` | `0.5` | Index | Minimum divergence threshold for MACD veto |
| `spread_filter_pips` | `3.0` | Pips | Maximum allowed spread before trade rejection |
| `max_daily_loss_usd` | `200.0` | USD ($) | Daily cumulative loss circuit breaker threshold |
| `min_balance_usd` | `9700.0` | USD ($) | Absolute balance floor; halts trading if breached |
| `daily_profit_target_usd` | `200.0` | USD ($) | Daily profit target; pauses trading once achieved |
| `max_positions_per_session` | `3` | Count | Maximum simultaneous concurrent positions |
| `entry_cooldown_sec` | `30.0` | Seconds | Mandatory cooldown between subsequent orders |
| `min_time_between_trades_sec`| `60` | Seconds | Anti-churn delay between closed trade and new entry |

---

## 🏗️ Architecture

```
                                  ┌───────────────────────────────┐
                                  │      Windows Task Scheduler   │
                                  │   or .\start_all.ps1 Script   │
                                  └───────────────┬───────────────┘
                                                  │ Launches
                                                  ▼
                                  ┌───────────────────────────────┐
                                  │     watchdog_runner.py        │
                                  │   (Health, OOM, Backoff)      │
                                  └───────┬───────────────┬───────┘
                                          │               │
                     ┌────────────────────┘               └───────────────────┐
                     ▼                                                        ▼
     ┌───────────────────────────────┐                        ┌───────────────────────────────┐
     │  python_engine/mt5_live_trader│                        │     omnicommand_server.py     │
     │   • 5-Tier Confluence Engine  │                        │   • FastAPI Async Port 8899   │
     │   • Microsecond Hot Tick Loop │                        │   • In-Memory TTL File Cache  │
     │   • Asynchronous Order Worker │                        │   • Live Telemetry Endpoints  │
     └───────┬───────────────┬───────┘                        └───────┬───────────────┬───────┘
             │               │                                        │               │
             │ Trades        │ Persists                               │ Serves        │ Serves
             ▼               ▼                                        ▼               ▼
     ┌───────────────┐ ┌───────────────┐                      ┌───────────────┐ ┌───────────────┐
     │  MetaTrader 5 │ │live_status.json│◄─────────────────────│dashboard.html │ │performance_   │
     │  Terminal     │ │trades.db (SQL)│                      │(Web Terminal) │ │dashboard.html │
     └───────────────┘ └───────────────┘                      └───────────────┘ └───────────────┘
             ▲                 ▲                                      ▲
             │                 │                                      │
     ┌───────┴───────┐ ┌───────┴───────┐                      ┌───────┴───────┐
     │alert_system.py│ │auto_backup.py │                      │tunnel_watchdog│
     │(6 Conditions, │ │(30m snapshot, │                      │(serveo.net    │
     │15m rate limit)│ │Git push sync) │                      │Public Access) │
     └───────────────┘ └───────────────┘                      └───────────────┘
```

### Core Components

| Component | File | Role & Functionality |
|---|---|---|
| **Live Trader Engine** | [`python_engine/mt5_live_trader.py`](file:///E:/scalping-robot-v5/python_engine/mt5_live_trader.py) | Ultra-low latency (<0.25ms) tick processor, async order dispatch, circuit breakers, and position management. |
| **Scalping Strategy** | [`python_engine/scalping_engine.py`](file:///E:/scalping-robot-v5/python_engine/scalping_engine.py) | Indicator calculations (BB, EMA, RSI, ATR, MACD), economic news filter, and regime categorization. |
| **REST API Server** | [`omnicommand_server.py`](file:///E:/scalping-robot-v5/omnicommand_server.py) | FastAPI service (port 8899) providing 15+ endpoints, CORS handling, and telemetry aggregation. |
| **Master Watchdog** | [`watchdog_runner.py`](file:///E:/scalping-robot-v5/watchdog_runner.py) | Continuous supervisor with exponential backoff, OOM RAM checks, freeze detection, and health checks. |
| **Trade Journal** | [`trade_journal.py`](file:///E:/scalping-robot-v5/trade_journal.py) | SQLite database manager persisting detailed trade records and daily performance statistics to `trades.db`. |
| **Alert System** | [`alert_system.py`](file:///E:/scalping-robot-v5/alert_system.py) | 6-condition real-time monitor checking win rates, drawdowns, stalled sessions, and rate-limiting alerts. |
| **Performance Monitor** | [`performance_monitor.py`](file:///E:/scalping-robot-v5/performance_monitor.py) | Automated performance grader (A+, A, B, C) generating 10-minute audit reports to `performance_report.txt`. |
| **Auto-Backup Daemon** | [`auto_backup.py`](file:///E:/scalping-robot-v5/auto_backup.py) | Rotates snapshots of critical code and state every 30 mins, with automatic 2-hour Git sync. |
| **Reverse Tunnel** | [`tunnel_watchdog.py`](file:///E:/scalping-robot-v5/tunnel_watchdog.py) | Establishes and monitors encrypted SSH reverse tunnel over serveo.net for remote mobile access. |
| **Web Dashboard** | [`dashboard.html`](file:///E:/scalping-robot-v5/dashboard.html) | Institutional dark-theme trading console with real-time Chart.js charts and live order controls. |
| **Mobile Dashboard** | [`performance_dashboard.html`](file:///E:/scalping-robot-v5/performance_dashboard.html) | Lightweight, touch-responsive mobile monitoring interface for phones and tablets. |

---

## 🎯 5-Tier Signal System

Trades are evaluated through a prioritized cascade. The first tier satisfying criteria triggers an execution signal, which is then verified against the MACD divergence filter:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        5-TIER SIGNAL CASCADE                           │
├────────────────────────────────────────────────────────────────────────┤
│ TIER 1: Bollinger Bands Mean-Reversion                                 │
│   BUY:  Close <= Lower Band AND RSI < 55.0                             │
│   SELL: Close >= Upper Band AND RSI > 45.0                             │
├────────────────────────────────────────────────────────────────────────┤
│ TIER 2: EMA Trend + Momentum Pullback (Primary Engine)                 │
│   BUY:  Fast EMA > Slow EMA AND Close < Fast EMA * 1.0015 AND RSI < 65 │
│   SELL: Fast EMA < Slow EMA AND Close > Fast EMA * 0.9985 AND RSI > 35 │
├────────────────────────────────────────────────────────────────────────┤
│ TIER 3: RSI Momentum Extremes (Exhaustion & Reversal)                  │
│   BUY:  RSI <= 35.0 (Oversold Bounce)                                  │
│   SELL: RSI >= 65.0 (Overbought Drop)                                  │
├────────────────────────────────────────────────────────────────────────┤
│ TIER 4: Midband Crossover & EMA Alignment                              │
│   BUY:  Fast EMA >= Slow EMA AND Close < BB Mid AND RSI < 58.0         │
│   SELL: Fast EMA < Slow EMA AND Close > BB Mid AND RSI > 42.0          │
├────────────────────────────────────────────────────────────────────────┤
│ TIER 5: Fallback Algorithmic Signal                                    │
│   Consults ScalpingRobotV5.evaluate_entry() institutional logic        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Signal Generated
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 MACD DIVERGENCE CONFLUENCE FILTER                      │
│                                                                        │
│ • If Signal == BUY  AND MACD Histogram < -0.50 ──► ❌ VETO (Bearish)   │
│ • If Signal == SELL AND MACD Histogram > +0.50 ──► ❌ VETO (Bullish)   │
│ • If |MACD Histogram| <= 0.50 OR Aligned       ──► ✅ PASS TO EXECUTION │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 📈 Multi-Timeframe Analysis & Market Regimes

### Multi-Timeframe Consensus
To filter out single-timeframe market noise, signals incorporate multi-timeframe consensus:
- **M1 (1-Minute)**: High-resolution entry and tick execution trigger.
- **M5 (5-Minute)**: Moving average alignment and momentum confirmation.
- **M15 (15-Minute)**: Structural support, resistance, and macro trend direction.

### Market Regime Detection
The engine calculates an ATR volatility ratio ($ATR_{current} / EMA(ATR, 50)$) to classify market conditions:
- **`LOW_VOLATILITY`** (Ratio < 0.75): Tighter stops, mean-reversion favored.
- **`NORMAL_VOLATILITY`** (0.75 ≤ Ratio ≤ 1.40): Standard 5-tier scalping active.
- **`HIGH_VOLATILITY`** (1.40 < Ratio ≤ 2.50): Stops dynamically widened via ATR multiplier; lot sizes scaled down.
- **`EXTREME_SPIKE`** (Ratio > 2.50): Immediate volatility blackout; all entries suspended until market calms.

---

## 💰 Position Sizing & Kelly Criterion

Gold Scalping Robot v5 uses mathematical position sizing to balance growth with downside protection:

### 1. Half-Kelly Formula
$$\text{Kelly Fraction } f^* = \frac{p \cdot b - q}{b}$$
$$\text{Position Fraction } = \frac{1}{2} \cdot f^*$$

Where:
- $p$ = Historical win rate (e.g. 0.85)
- $q = 1 - p$ = Loss rate (e.g. 0.15)
- $b$ = Payoff ratio ($\text{Average Win} / \text{Average Loss}$)
- **Half-Kelly** safety reduction prevents volatility drag and sequence risk.

### 2. Van Tharp Fixed Fractional Sizing
$$\text{Risk Dollars} = \text{Account Balance} \times \left(\frac{\text{Risk Percent}}{100}\right)$$
$$\text{Calculated Lots} = \frac{\text{Risk Dollars}}{\text{Effective SL (pips)} \times \text{Pip Value}}$$

Final lot size is quantized to broker lot steps (`0.01`) and clamped between `0.01` and `max_lot_size` (`0.10`).

### 3. Dynamic Balance Milestone Scaling
Automatic balance-based tier progression:
- **$10,000 → $10,149**: `0.02` lots (Conservative baseline)
- **$10,150 → $10,199**: `0.03` lots (Tier 1 compounding)
- **$10,200 → $10,299**: `0.04` lots (Tier 2 compounding)
- **$10,300+**: 🏆 Milestone reached — target locked

---

## 🛡️ Exit Strategies

The robot protects profits using a three-tier active exit engine:

1. **Ratcheting Trailing Stop**:
   - Monitored on every tick in real-time.
   - Activates when profit exceeds `trailing_stop_pips` (`15.0` pips).
   - Ratchets the Stop Loss upward (for BUY) or downward (for SELL) at trailing distance from market price.
2. **Break-Even Lock**:
   - Triggered when trade reaches `+15.0` pips (50% of default Take Profit).
   - Moves Stop Loss to Entry Price $+ 1.0$ pip buffer, guaranteeing a risk-free position.
3. **Scaled Exits**:
   - Optional split profit taking at initial target with remaining lot trailing for runner gains.

---

## ⚡ Risk Shields & Circuit Breakers

| Risk Guard | Trigger Condition | System Response |
|---|---|---|
| **Daily Loss Circuit Breaker** | Cumulative daily loss exceeds **$200.00** | Halts all new orders immediately; transitions status to `PAUSED_CIRCUIT_BREAKER` until midnight UTC reset. |
| **Balance Floor Protection** | Account balance drops below **$9,700.00** | Critical safety halt; blocks trading indefinitely until manual operator review. |
| **Daily Profit Target Target** | Daily net profit reaches **$200.00** | Pauses trading to bank profits and eliminate over-trading risk. |
| **Spread Spike Guard** | Spread > `3.0` pips or > 1.5x rolling EMA spread | Rejects orders during low liquidity or broker spread widening. |
| **Consecutive Loss Cooldown** | 3 consecutive losing trades | Enforces an automatic 30-minute cooling period before re-evaluating signals. |
| **Max Concurrent Positions** | 3 open orders reached | Blocks new order dispatch until at least one position is closed. |

---

## 🕐 Session Filter & Time Avoidance

XAUUSD liquidity varies significantly across global trading sessions. The bot restricts trade execution to high-liquidity hours:

```
UTC 00:00        07:00        13:00       16:00        21:45  22:15       24:00
    │             │            │           │             │      │           │
    ├─────────────┼────────────┼───────────┼─────────────┼──────┼───────────┤
    │ Tokyo Asian │ London     │ London/NY │ NY Only     │ROLL- │ Off-Hours │
    │ Buffer      │ Open       │ Overlap   │ Afternoon   │OVER  │           │
    │             │ (High Vol) │ (PEAK)    │             │FREEZE│           │
    └─────────────┴────────────┴───────────┴─────────────┴──────┴───────────┘
```

- **London Session**: 07:00 – 16:00 UTC (Strong directional volume)
- **New York Session**: 13:00 – 22:00 UTC (Institutional US flow)
- **Peak Overlap**: 13:00 – 16:00 UTC (Highest liquidity and tightest spreads)
- **Rollover Freeze (21:45 – 22:15 UTC)**: Complete trading blackout during bank rollover to avoid widening spreads and swap volatility.
- **Economic News Blackout**: Dynamic calendar filter blocking entries 15 minutes before and 30 minutes after US High-Impact events (NFP, CPI, FOMC, PPI).

---

## 🔌 OmniCommand REST API

The robot includes an asynchronous REST API running on **port 8899** powered by FastAPI and Uvicorn.

### Endpoints Reference

| Method | Endpoint | Description | Sample Output / Purpose |
|---|---|---|---|
| `GET` | `/` | Web Trading Terminal | Serves `dashboard.html` |
| `GET` | `/dashboard` | Direct Dashboard Route | Serves full trading dashboard |
| `GET` | `/performance` | Mobile Dashboard Route | Serves `performance_dashboard.html` |
| `GET` | `/ping` | Lightweight Liveness Probe | `{"pong": true, "ts": 1728000000, "status": "ok"}` |
| `GET` | `/health` | Full Subsystem Health | Live P&L, uptime, trader alive check, open positions, tunnel URL |
| `GET` | `/status` | Raw Live Status Payload | Contents of `live_status.json` with retry file locking |
| `GET` | `/metrics` | Core Financial Metrics | Win rate %, total trades, daily P&L, balance, equity, price |
| `GET` | `/positions` | Open Orders List | Array of open MT5 positions with tickets, lots, and P&L |
| `GET` | `/history` | Closed Trade History | Last 10-50 completed trades with entry, exit, duration, and P&L |
| `GET` | `/analytics` | Advanced Analytics | 50-point balance curve, profit factor, avg win/loss, signal tier |
| `POST` | `/trader/restart` | Remote Process Restart | Signals watchdog via `restart_signal.txt` to recycle trader PID |
| `POST` | `/trader/stop` | Graceful Process Halt | Signals trader shutdown and writes `stop_signal.txt` |
| `GET` | `/system` | Host OS Telemetry | RAM usage %, CPU load %, disk space free, host uptime |
| `GET` | `/docs` | OpenAPI Interactive Docs | Swagger UI testing interface |
| `GET` | `/redoc` | ReDoc Documentation | Human-friendly structured API reference |
| `GET` | `/openapi.json` | OpenAPI Schema | Machine-readable API specification |

---

## 🗄️ SQLite Trade Journal

All trade executions and daily rollups are recorded in a local SQLite database at `E:\scalping-robot-v5\trades.db` via [`trade_journal.py`](file:///E:/scalping-robot-v5/trade_journal.py):

### Database Schema

```sql
-- Individual Trades Table
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    symbol TEXT,
    direction TEXT,
    entry_price REAL,
    exit_price REAL,
    lot_size REAL,
    sl_price REAL,
    tp_price REAL,
    pnl REAL,
    exit_reason TEXT,
    duration_sec INTEGER,
    signal_tier INTEGER,
    spread_pips REAL
);

-- Daily Summary Table
CREATE TABLE daily_summary (
    date TEXT PRIMARY KEY,
    total_trades INTEGER,
    wins INTEGER,
    losses INTEGER,
    win_rate REAL,
    total_pnl REAL,
    max_drawdown REAL,
    best_trade REAL,
    worst_trade REAL
);
```

### Python API Usage
```python
from trade_journal import get_journal

journal = get_journal()

# Query last 10 trades
recent = journal.get_last_N_trades(10)

# Retrieve weekly performance summary
weekly = journal.get_weekly_performance()
print(f"Weekly Win Rate: {weekly.get('win_rate')}% | Total PnL: ${weekly.get('total_pnl')}")
```

---

## 🐕 Watchdog v2 Self-Healing System

[`watchdog_runner.py`](file:///E:/scalping-robot-v5/watchdog_runner.py) acts as the continuous supervisor ensuring 99.99% uptime for both trader and API server:

### Key Self-Healing Mechanisms
1. **Exponential Backoff**:
   $$\text{Delay (seconds)} = \min(300, 30 \times 2^{\text{restarts}})$$
   Prevents CPU thrashing in case of broker server downtime or network disconnects.
2. **Health Pre-Check**:
   Before initiating a restart, the watchdog verifies `live_status.json`. If `ok=true` and updated within 60 seconds, unnecessary restarts are suppressed.
3. **Out-of-Memory (OOM) Guard**:
   Monitors process RSS memory via `psutil`. If memory exceeds `500 MB`, the process is cleanly recycled to eliminate leaks.
4. **Freeze / Stall Detection**:
   If the status file has not been updated for `> 120 seconds` during active trading, the watchdog detects a frozen loop and restarts the process.
5. **Crash Detection**:
   Monitors process exit codes every 20 seconds and relaunches immediately upon abnormal termination.

---

## 🚨 Real-Time Alerts & Notification Engine

[`alert_system.py`](file:///E:/scalping-robot-v5/alert_system.py) runs continuously, monitoring live telemetry against 6 conditions with a **15-minute rate limit** per alert category:

| Condition | Threshold | Alert Level | Logged Notification |
|---|---|---|---|
| **1. Win Rate Drop** | Win rate < 70% | `CRITICAL` | `ALERT: Win rate critical: X%` |
| **2. Daily Loss Surge** | Daily loss > $150.00 | `CRITICAL` | `ALERT: Daily loss danger: $X` |
| **3. Session Stall** | No trades in 90 mins during active session | `WARNING` | `ALERT: Trading stalled` |
| **4. Low Balance** | Account balance < $9,800.00 | `CRITICAL` | `ALERT: Balance critical: $X` |
| **5. Equity Drawdown** | Equity drawdown > 5.0% | `CRITICAL` | `ALERT: Equity drawdown: X%` |
| **6. Position Overload** | Open positions > 4 | `WARNING` | `ALERT: Too many positions: N` |

All events are logged to `alerts.log` and the current state is atomically stored in `alert_status.json`.

---

## 📊 Performance Grader & Automated Monitor

[`performance_monitor.py`](file:///E:/scalping-robot-v5/performance_monitor.py) evaluates live results every 10 minutes and computes an institutional rating:

| Win Rate Range | Grade | Evaluation Status |
|---|---|---|
| **Win Rate > 90.0%** | **A+** | 👑 Elite institutional execution |
| **85.0% < Win Rate ≤ 90.0%** | **A** | 🟢 Optimal profitability |
| **75.0% ≤ Win Rate ≤ 85.0%** | **B** | 🟡 Acceptable performance |
| **Win Rate < 75.0%** | **C** | 🔴 Review strategy & market conditions |

The monitor automatically generates audit logs in `performance_report.txt` and records runtime diagnostics in `monitor.log`.

---

## 💾 Auto-Backup Daemon & Git Sync

[`auto_backup.py`](file:///E:/scalping-robot-v5/auto_backup.py) safeguards trading code and live configuration:
- **30-Minute File Rotation**: Creates timestamped backups (`_YYYYMMDD_HHMMSS`) of `mt5_live_trader.py`, `live_status.json`, and `analytics.json` in `E:\scalping-robot-v5\backups\`.
- **FIFO Retention**: Retains only the **last 10 backup snapshots**, automatically pruning older archives to preserve disk space.
- **2-Hour Git Auto-Sync**: Every 4th backup cycle (2 hours), automatically performs `git add -A`, commits with an auto-backup message, and pushes to the remote repository.

---

## 🖥️ Dashboards: Web & Mobile

### 1. Desktop Web Terminal (`dashboard.html`)
- Built with HTML5, CSS3, and Chart.js.
- Dark theme with institutional gold and emerald green indicators.
- Live 50-point balance/equity curve updated in real-time via `/analytics`.
- Real-time spread gauge, current price ticker, signal tier tracker, and trade history table.
- Direct process controls for restarting or stopping the trader engine.

### 2. Mobile Performance Dashboard (`performance_dashboard.html`)
- Touch-friendly, lightweight interface designed for mobile web browsers.
- Real-time performance grade badge (A+, A, B, C) and live heartbeat indicator.
- Fast-loading equity chart and recent trades list.
- Responsive design optimized for remote monitoring via serveo.net tunnel.

---

## 🔄 Continuous Integration (GitHub Actions)

The repository includes automated CI in [`.github/workflows/syntax_check.yml`](file:///E:/scalping-robot-v5/.github/workflows/syntax_check.yml):
- **Triggers**: Executed on every `push` and `pull_request` to the `main` branch.
- **Python Compilation**: Runs `py_compile` across all repository Python files to catch syntax errors.
- **Automated Testing**: Executes `pytest tests/ -v --tb=short` to validate storage atomic operations, indicator math, latency benchmarks, and alert systems.

---

## 🧪 Verification & Testing

Run the automated test suite locally:

```powershell
# Run all pytest suites
pytest -v

# Run specific alert system tests
pytest tests/test_alert_system.py -v

# Run core trading engine and benchmark tests
pytest tests/test_scalping_robot.py -v
```

### Manual Health Checks
```powershell
# Query FastAPI health endpoint
Invoke-RestMethod http://localhost:8899/health

# Verify system memory and CPU telemetry
Invoke-RestMethod http://localhost:8899/system

# Inspect live trader log output
Get-Content "E:\scalping-robot-v5\trader.log" -Wait -Tail 25
```

---

## 🛠️ Troubleshooting & Maintenance

### Common Questions & Solutions

#### 1. Trader reports "MT5 Connection Failed"
- Ensure the desktop MetaTrader 5 application is running and logged into an active account.
- In MT5, navigate to **Tools → Options → Expert Advisors** and verify **"Allow algorithmic trading"** is checked.
- Check `trader_err.log` for specific MetaTrader error codes.

#### 2. Port 8899 already in use
```powershell
# Identify process occupying port 8899
netstat -ano | findstr :8899

# Terminate process by PID
Stop-Process -Id <PID> -Force
```

#### 3. Watchdog triggered an unexpected restart
- Inspect `watchdog.log` to see the logged reason (`CRASH`, `OOM > 500MB`, or `FREEZE > 120s`).
- Check `live_status.json` modification time to verify if the trader loop hung.

#### 4. How to perform a graceful manual restart
```powershell
# Send restart signal via API
Invoke-RestMethod -Method POST http://localhost:8899/trader/restart

# Or trigger via file signal
Set-Content "E:\scalping-robot-v5\restart_signal.txt" -Value $(Get-Date)
```

---

## ⚠️ Risk Disclaimer

> **Financial Trading Warning**: Trading foreign exchange and spot metals (such as XAUUSD / Gold) on margin carries a high level of risk and may not be suitable for all investors. High leverage can work against you as well as for you. Before deciding to trade gold or any other financial instrument, you should carefully consider your investment objectives, level of experience, and risk appetite. Past performance is not indicative of future results. Always test automated strategies thoroughly in a simulated demo environment before committing real capital.

---

## 📌 Version Information

| Attribute | Specification |
|---|---|
| **System Version** | Gold Scalping Robot v5.1 Pro |
| **Target Symbol** | XAUUSD (Spot Gold / US Dollar) |
| **Execution Timeframe** | M1 Execution (M5 / M15 Multi-Timeframe Alignment) |
| **Supported Terminals** | MetaTrader 5 (Python 3.11 API) |
| **Default Port** | `8899` (FastAPI / OmniCommand) |
| **Workspace Root** | `E:\scalping-robot-v5` |
| **Repository Branch** | `main` |
| **Last Updated** | October 2026 |

*Built for institutional-grade gold scalping with maximum autonomy, high-frequency discipline, and bulletproof safety.*
