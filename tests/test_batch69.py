"""
tests/test_batch69.py
Batch 69 Unit Tests: Scalping Sovereign Engine & Volatility Shield (scalping_engine.py),
Economic News Calendar Filter, Auto-Backup Retention & Lock Guards (auto_backup.py),
Log Analyzer Metrics Extraction (log_analyzer.py), and Backtester Simulation (run_backtest.py).
"""

import math
import time
import os
from pathlib import Path
import pytest
from datetime import datetime, timezone, timedelta

from python_engine.scalping_engine import ScalpingRobotV5, EconomicNewsFilter, MarketRegime, ScalpingSignal
from auto_backup import cleanup_old_backups, _acquire_instance_lock, _release_instance_lock, _LOCK_FILE
from log_analyzer import parse_trader_log
from run_backtest import simulate_price, bb_signal, run_backtest


def test_scalping_engine_indicators_calculation():
    """Verify ScalpingRobotV5 calculates EMAs, Bollinger Bands, RSI, and ATR accurately."""
    bot = ScalpingRobotV5({
        "bb_period": 10,
        "fast_ema": 5,
        "slow_ema": 10,
        "rsi_period": 10,
        "atr_period": 10,
    })

    # Generate 30 bars of valid OHLC data
    bars = []
    for i in range(30):
        c = 2650.0 + (i * 0.4)
        bars.append({
            "open": c - 0.2,
            "high": c + 0.8,
            "low": c - 0.7,
            "close": c,
            "volume": 100,
            "timestamp": time.time() + i * 60,
        })

    ind = bot.calculate_indicators(bars)
    assert ind["close"] == bars[-1]["close"]
    assert ind["fast_ema"] > 0.0
    assert ind["slow_ema"] > 0.0
    assert ind["bb_upper"] > ind["bb_mid"] > ind["bb_lower"]
    assert 0.0 <= ind["rsi"] <= 100.0
    assert ind["atr"] > 0.0
    assert ind["volatility_regime"] in (
        MarketRegime.LOW_VOLATILITY,
        MarketRegime.NORMAL_VOLATILITY,
        MarketRegime.HIGH_VOLATILITY,
        MarketRegime.EXTREME_SPIKE,
    )


def test_scalping_engine_volatility_regime_and_spike_detection():
    """Verify ScalpingRobotV5 classifies volatility regimes and detects extreme spikes."""
    bot = ScalpingRobotV5({
        "bb_period": 10,
        "fast_ema": 5,
        "slow_ema": 10,
        "rsi_period": 10,
        "atr_period": 10,
        "volatility_spike_threshold": 2.2,
    })

    # 1. Low volatility flat bars
    flat_bars = [
        {"open": 2650.0, "high": 2650.1, "low": 2649.9, "close": 2650.0, "timestamp": 100 + i * 60}
        for i in range(25)
    ]
    ind_flat = bot.calculate_indicators(flat_bars)
    assert ind_flat["volatility_regime"] in (MarketRegime.LOW_VOLATILITY, MarketRegime.NORMAL_VOLATILITY)

    # 2. Add an extreme spike bar (huge range)
    spike_bar = {"open": 2650.0, "high": 2665.0, "low": 2640.0, "close": 2660.0, "timestamp": 100 + 26 * 60}
    flat_bars.append(spike_bar)
    ind_spike = bot.calculate_indicators(flat_bars)
    assert ind_spike["volatility_regime"] == MarketRegime.EXTREME_SPIKE


def test_scalping_engine_economic_news_filter_blackout_windows():
    """Verify EconomicNewsFilter identifies pre-event and post-event blackout windows."""
    filter = EconomicNewsFilter(pre_minutes=15, post_minutes=30)
    filter.clear_events()

    # Event scheduled at t = 10,000 (epoch)
    event_time = 10000.0
    filter.add_event(event_time=event_time, event_name="US Non-Farm Payrolls", currency="USD")

    # 20 minutes before event (t = 8800) -> Outside blackout (pre_window is 15m = 900s -> 9100 to 10000)
    is_bo1, _ = filter.is_blackout(current_time=8800.0)
    assert is_bo1 is False

    # 5 minutes before event (t = 9700) -> Inside PRE_EVENT blackout
    is_bo2, ev2 = filter.is_blackout(current_time=9700.0)
    assert is_bo2 is True
    assert ev2["event"] == "US Non-Farm Payrolls"
    assert ev2["phase"] == "PRE_EVENT"
    assert ev2["seconds_to_event"] == 300.0

    # 10 minutes after event (t = 10600) -> Inside POST_EVENT blackout
    is_bo3, ev3 = filter.is_blackout(current_time=10600.0)
    assert is_bo3 is True
    assert ev3["phase"] == "POST_EVENT"

    # 35 minutes after event (t = 12100) -> Outside blackout (post_window is 30m = 1800s)
    is_bo4, _ = filter.is_blackout(current_time=12100.0)
    assert is_bo4 is False


def test_scalping_engine_evaluate_entry_confluence_and_shields():
    """Verify ScalpingRobotV5 entry evaluation respects spread caps and shield state."""
    bot = ScalpingRobotV5({
        "max_spread_pips": 3.0,
        "volatility_shield_enabled": True,
        "news_filter_enabled": False,
    })

    indicators = {
        "close": 2648.0,
        "fast_ema": 2652.0,
        "slow_ema": 2650.0,
        "bb_upper": 2655.0,
        "bb_lower": 2649.0,
        "rsi": 25.0,  # oversold
        "volatility_regime": MarketRegime.NORMAL_VOLATILITY,
    }

    # Normal entry allowed
    sig = bot.evaluate_entry(indicators, current_spread_pips=1.5)
    assert sig in (ScalpingSignal.BUY, ScalpingSignal.HOLD)

    # Spread exceeded (> 3.0 pips) -> signal suppressed to HOLD
    sig_spread = bot.evaluate_entry(indicators, current_spread_pips=4.2)
    assert sig_spread == ScalpingSignal.HOLD


def test_auto_backup_cleanup_retention(tmp_path):
    """Verify cleanup_old_backups retains only the latest N snapshots and purges older ones."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Create 5 snapshot timestamps
    timestamps = [
        "20261017_100000",
        "20261017_103000",
        "20261017_110000",
        "20261017_113000",
        "20261017_120000",
    ]

    for ts in timestamps:
        (backup_dir / f"mt5_live_trader_{ts}.py").write_text("code", encoding="utf-8")
        (backup_dir / f"live_status_{ts}.json").write_text("{}", encoding="utf-8")

    assert len(list(backup_dir.glob("*.py"))) == 5

    # Retain only last 3 snapshots
    cleanup_old_backups(backups_dir=str(backup_dir), keep_last=3)

    remaining_py = sorted([f.name for f in backup_dir.glob("*.py")])
    assert len(remaining_py) == 3
    # Earliest two (100000 and 103000) should be purged
    assert "20261017_100000" not in remaining_py[0]
    assert "20261017_110000" in remaining_py[0]
    assert "20261017_120000" in remaining_py[2]


def test_auto_backup_single_instance_lock(tmp_path, monkeypatch):
    """Verify atomic single-instance lock acquisition and release."""
    lock_file = tmp_path / "backup.lock"
    monkeypatch.setattr("auto_backup._LOCK_FILE", str(lock_file))

    # First acquisition succeeds
    assert _acquire_instance_lock() is True
    assert lock_file.exists()

    # Second acquisition fails (lock held)
    assert _acquire_instance_lock() is False

    # Release lock
    _release_instance_lock()
    assert not lock_file.exists()

    # Re-acquire succeeds
    assert _acquire_instance_lock() is True
    _release_instance_lock()


def test_log_analyzer_parse_trader_log_metrics(tmp_path):
    """Verify parse_trader_log extracts line counts, signals, balances, and PnL records."""
    log_file = tmp_path / "trader.log"
    sample_lines = [
        "2026-10-17 12:00:00 [INFO] Trader: === HEARTBEAT === balance=$10,050.00 signal=BUY",
        "2026-10-17 12:01:00 [INFO] Trader: [SIGNAL FIRED] → BUY entry=2650.00",
        "2026-10-17 12:02:00 [INFO] Trader: [NEW POSITION - SIM] BUY 0.02 lots",
        "2026-10-17 12:05:00 [INFO] Trader: [TRADE CLOSED] BUY | TP_HIT | PnL: $+65.00 | Balance: $10,115.00",
        "2026-10-17 12:06:00 [WARNING] Trader: Spread widened to 3.2 pips",
        "2026-10-17 12:07:00 [ERROR] Trader: Requote from broker",
        "2026-10-17 12:10:00 [INFO] Trader: === HEARTBEAT === balance=$10,115.00 signal=HOLD",
    ]
    log_file.write_text("\n".join(sample_lines), encoding="utf-8")

    stats = parse_trader_log(log_path=log_file)
    assert stats["counts"]["HEARTBEAT"] == 2
    assert stats["counts"]["SIGNAL"] >= 1
    assert stats["counts"]["ERROR"] == 1
    assert stats["counts"]["WARNING"] == 1
    assert stats["max_balance"] == 10115.00
    assert stats["min_balance"] == 10050.00
    assert stats["trade_breakdown"]["trades_closed"] == 1
    assert len(stats["trade_breakdown"]["closed_trades_pnl"]) == 1
    assert stats["trade_breakdown"]["closed_trades_pnl"][0]["pnl"] == 65.00


def test_run_backtest_price_simulation():
    """Verify simulate_price generates requested length series with positive bounds."""
    prices = simulate_price(n_ticks=100, start_price=2650.0)
    assert len(prices) == 100
    assert prices[0] == 2650.0
    assert all(math.isfinite(p) and p >= 100.0 for p in prices)


def test_run_backtest_bb_signal_and_bounds():
    """Verify bb_signal identifies Bollinger Band breakout signals and holds inside bands."""
    # Flat series: inside bands -> HOLD
    flat_series = [2650.0] * 30
    assert bb_signal(flat_series, i=25, period=20) == "HOLD"

    # Extreme low price at target index -> BUY
    low_series = [2650.0 + (i % 2) * 2.0 for i in range(25)]
    low_series.append(2620.0)  # sharp drop at index 25
    assert bb_signal(low_series, i=25, period=20) == "BUY"

    # Extreme high price at target index -> SELL
    high_series = [2650.0 + (i % 2) * 2.0 for i in range(25)]
    high_series.append(2680.0)  # sharp surge at index 25
    assert bb_signal(high_series, i=25, period=20) == "SELL"


def test_run_backtest_execution_and_summary():
    """Verify run_backtest simulates price series and outputs standard statistical summary."""
    results = run_backtest(
        n_ticks=150,
        sl_pips=25.0,
        tp_pips=40.0,
        lot=0.02,
        start_balance=10000.0,
        save_results=False,
        quiet=True,
    )
    assert isinstance(results, dict)
    assert "final_balance" in results
    assert "total_pnl" in results
    assert "total_trades" in results
    assert "win_rate_pct" in results
    assert "max_drawdown_pct" in results
