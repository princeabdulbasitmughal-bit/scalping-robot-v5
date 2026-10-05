# 🤖 World-Class Gold Scalping Robot — 20-Agent Plan

## Repo: `aroob100100-commits/tradebot`
## Owner: aroob100100-commits
## Coordinator: Antigravity (BasitLoop)

---

## 📋 Rules for ALL Agents

1. **NEVER push to `main` directly** — always use your assigned branch + PR
2. **Default mode = `paper`** — `trading_mode` must never be changed to `live` in code
3. **No broker credentials in code** — use `.env` only (gitignored)
4. **No hardcoded paths** — use `Path(__file__).parent` or `BASE_DIR`
5. **Tests required** — every PR must include tests for new code
6. **Backtest evidence required** — new strategies need out-of-sample results
7. **Claude reviews before merge** — Risk/Safety PRs need Claude approval

---

## 👥 Agent Assignments

| # | Agent | Branch | Responsibility |
|---|-------|--------|----------------|
| 01 | Manus #1 | `agent/01-data` | Data Engineer — XAUUSD tick data pipeline |
| 02 | Manus #2 | `agent/02-backtest` | Backtest Engine — realistic fills, metrics |
| 03 | Manus #3 | `agent/03-walkforward` | Walk-Forward + Monte Carlo validation |
| 04 | Manus #4 | `agent/04-signals` | Signal Engine — BB/RSI/MACD/EMA refinement |
| 05 | Manus #5 | `agent/05-filters` | Wave Filters — all 61 waves optimization |
| 06 | Manus #6 | `agent/06-risk` | Risk Engine — position sizing, SL enforcement |
| 07 | Manus #7 | `agent/07-execution` | Order Execution — slippage, retries, partial fills |
| 08 | Manus #8 | `agent/08-regime` | Market Regime — trending/ranging/volatile detection |
| 09 | Manus #9 | `agent/09-sessions` | Session Manager — Tokyo/London/NY optimization |
| 10 | Manus #10 | `agent/10-ml` | ML Layer — XGBoost/LightGBM signal scoring |
| 11 | Manus #11 | `agent/11-dashboard` | Dashboard — real-time web UI |
| 12 | Manus #12 | `agent/12-alerts` | Alert System — Telegram/Email/SMS |
| 13 | **Claude** | `claude/review-*` | **Lead Reviewer + Safety Owner** |
| 14 | Manus #13 | `agent/13-journal` | Trade Journal — SQLite + reporting |
| 15 | Manus #14 | `agent/14-news` | News Filter — economic calendar integration |
| 16 | Manus #15 | `agent/15-optimizer` | Parameter Optimizer — Optuna/grid search |
| 17 | Manus #16 | `agent/16-monitoring` | System Monitor — health checks, uptime |
| 18 | Manus #17 | `agent/17-api` | REST API — OmniCommand enhancements |
| 19 | Manus #18 | `agent/18-docs` | Documentation — README, guides, API docs |
| 20 | Manus #19 | `agent/19-ci` | CI/CD — GitHub Actions, linting, coverage |
| 21 | **Antigravity** | `agent/coordinator` | **Master Coordinator + Integration** |

---

## 🔐 Claude's Role — Lead Reviewer + Safety Owner

### Branch: `claude/safety-*`, `claude/risk-*`

### PR Review Checklist (Claude verifies before any merge):
- [ ] `trading_mode` default is `paper`
- [ ] No live credentials or broker login in code
- [ ] New features have backtest evidence (out-of-sample)
- [ ] All tests pass + new tests for new code
- [ ] No hardcoded Windows paths (`E:\...`)
- [ ] No secrets in repo (`.env` only)
- [ ] Risk limits not weakened

### Verdict options: **Approve** / **Changes Needed** / **Block (Safety)**

---

## 📁 File Ownership (CODEOWNERS)

```
python_engine/          @aroob100100-commits
python_engine/risk*     @claude-reviewer
omnicommand_server.py   @claude-reviewer
config.json             @aroob100100-commits @claude-reviewer
.github/                @aroob100100-commits
docs/                   @aroob100100-commits
```

---

## 🏗️ Agent #1 — Data Engineer

**Branch:** `agent/01-data`  
**Goal:** Real XAUUSD market data pipeline

### Deliverables:
- `tools/data/download_dukascopy.py` — resumable tick download
- `tools/data/validate.py` — quality checks (gaps, spikes, DST, rollover)
- `python_engine/data_loader.py` — `load_ticks(symbol, start, end)`, `load_bars(symbol, tf, start, end)`
- `data/MANIFEST.json` — checksums, source, date ranges
- `docs/data_quality.md` — coverage report
- Parquet format, partitioned by year/month
- **Schema:** `time_utc, bid, ask, bid_vol, ask_vol`

### Done when:
- 3-5 years XAUUSD M1 data loaded
- < 0.1% bad ticks, all rejections logged
- Single command rebuild on fresh machine

---

## 🏗️ Agent #2 — Backtest Engine

**Branch:** `agent/02-backtest`  
**Goal:** Trustworthy backtester using live code

### Deliverables:
- `python_engine/backtester.py` — production-grade
- Same signal + risk logic as live (no duplicates)
- Realistic fills: bid/ask spread, slippage, commission
- Pessimistic rule: if SL + TP in same bar → SL wins
- No lookahead bias (closed bars only)
- Circuit breakers active in backtest too
- Output: `reports/backtests/<run_id>/trades.csv`, `equity_curve.png`, `summary.json`
- Cost sensitivity: spread ×2, slippage ×2 must still be profitable

---

## 🔒 Claude's Safety Package #1

**Branch:** `claude/safety-1`

- [ ] OmniCommand API → bind to `127.0.0.1`, remove `CORS *`
- [ ] `tunnel_url.txt`, `.tmp`, `.coverage`, `backups/` → gitignored
- [ ] All `E:\scalping-robot-v5` hardcoded paths → `Path(__file__).parent`
- [ ] `requirements.txt` → add `MetaTrader5`, `numpy`, `pandas`
- [ ] `telegram_config.json` → token always empty in repo

---

## 📊 "Done" Definition — World Class

- [ ] 3+ years real tick data, validated
- [ ] Backtest Sharpe > 1.5, Profit Factor > 1.8
- [ ] Walk-forward OOS results consistent with IS
- [ ] Live paper trading matches backtest within 15%
- [ ] 95%+ test coverage
- [ ] Zero hardcoded secrets or paths
- [ ] Dashboard live on mobile
- [ ] Telegram alerts working
- [ ] CI/CD green on every push
