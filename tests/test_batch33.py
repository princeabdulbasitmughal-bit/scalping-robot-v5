"""
Tests for Batch 33 Hardening:
- wave57_hourly_pnl_map.py
- wave58_price_range_filter.py
- wave59_ma_trend_filter.py
- wave60_profit_streak_booster.py
- wave61_opening_range_breakout.py
- python_engine/risk_guard.py
- python_engine/storage.py
- python_engine/backtester.py
- trade_journal.py
- performance_monitor.py
"""

import math
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest

from wave57_hourly_pnl_map import HourlyPnLMap
from wave58_price_range_filter import PriceRangeFilter
from wave59_ma_trend_filter import MATrendFilter, BlockResult
from wave60_profit_streak_booster import ProfitStreakBooster
from wave61_opening_range_breakout import OpeningRangeBreakout
from python_engine.risk_guard import RiskGuard, Decision
from python_engine.storage import atomic_write_json
from python_engine.backtester import Backtester
from trade_journal import TradeJournal
from performance_monitor import calculate_grade, _safe_float


def test_wave57_hourly_pnl_map():
    hpnl = HourlyPnLMap(loss_threshold_usd=-30.0)
    hpnl.reset()

    # UTC 14:00 trade
    dt_14 = datetime(2026, 10, 19, 14, 30, tzinfo=timezone.utc)
    assert hpnl.get_lot_multiplier(now_dt=dt_14) == 1.0

    # Accumulate loss in hour 14 > $30 (e.g. -$45)
    hpnl.record_trade(pnl=-20.0, now_dt=dt_14)
    hpnl.record_trade(pnl=-25.0, now_dt=dt_14)
    assert hpnl.get_lot_multiplier(now_dt=dt_14) == 0.5

    # Other hours (e.g. UTC 15:00) retain full 1.0 lot multiplier
    dt_15 = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)
    assert hpnl.get_lot_multiplier(now_dt=dt_15) == 1.0

    # Info telemetry test
    info = hpnl.info(now_dt=dt_14)
    assert info["current_utc_hour"] == 14
    assert info["lot_multiplier"] == 0.5

    # Daily rollover resets hourly map
    dt_next_day = datetime(2026, 10, 20, 14, 30, tzinfo=timezone.utc)
    assert hpnl.get_lot_multiplier(now_dt=dt_next_day) == 1.0

    # Reentrant lock check
    with hpnl._lock:
        with hpnl._lock:
            hpnl.reset()
    assert hpnl._trade_count == 0


def test_wave58_price_range_filter():
    rf = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=10)
    rf.reset()
    dt0 = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)

    # First 9 ticks (< min_ticks 10) do not trigger flat-market block
    for i in range(9):
        rf.update(2000.0 + (i * 0.01), now_dt=dt0)
    assert not rf.is_entry_blocked(now_dt=dt0)

    # 10th tick arrives: range is 2000.09 - 2000.00 = 0.09 / 0.1 = 0.9 pips (< 5.0 min)
    rf.update(2000.05, now_dt=dt0)
    assert rf.is_entry_blocked(now_dt=dt0)
    allowed, reason = rf.is_trading_allowed(now_dt=dt0)
    assert not allowed
    assert "FLAT_MARKET" in reason

    # Volatility expands: high = 2001.0, low = 2000.0 -> range = 10.0 pips (>= 5.0)
    rf.update(2001.0, now_dt=dt0)
    assert not rf.is_entry_blocked(now_dt=dt0)
    assert rf.get_range_pips(now_dt=dt0) == 10.0

    # Reentrant lock check
    with rf._lock:
        with rf._lock:
            rf.reset()
    assert rf._ticks_today == 0


def test_wave59_ma_trend_filter():
    ma = MATrendFilter(period=10)
    ma.reset()

    # First 9 ticks: warm-up period, never blocks
    for i in range(9):
        ma.update(2000.0)
        res = ma.is_signal_blocked("BUY")
        assert not res
        assert not res.blocked

    # 10th tick completes SMA warm-up seed (EMA = 2000.0)
    ma.update(2000.0)
    assert ma.get_ema() == 2000.0

    # Price drops to 1990.0 (< EMA 2000.0) -> Bearish trend
    # BUY signal should be blocked, SELL signal should be allowed
    res_buy = ma.is_signal_blocked("BUY", price=1990.0)
    assert res_buy.blocked is True
    assert res_buy[0] is True
    assert "below_ema" in res_buy[1]
    assert bool(res_buy) is True

    res_sell = ma.is_signal_blocked("SELL", price=1990.0)
    assert res_sell.blocked is False
    assert not res_sell

    # Price surges to 2010.0 (> EMA) -> Bullish trend
    # SELL signal blocked, BUY signal allowed
    res_sell_high = ma.is_signal_blocked("SELL", price=2010.0)
    assert res_sell_high.blocked is True
    assert "above_ema" in res_sell_high[1]

    # Reentrant lock check
    with ma._lock:
        with ma._lock:
            ma.reset()
    assert ma.get_ema() == 0.0


def test_wave60_profit_streak_booster():
    booster = ProfitStreakBooster(streak_length=3, tp_multiplier=1.2)
    booster.reset()

    # 2 consecutive wins: target is 3 -> confidence mode not yet active
    booster.record_trade(True)
    booster.record_trade(True)
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(base_tp_pips=30.0) == 30.0

    # 3rd consecutive win -> confidence mode activated!
    booster.record_trade(True)
    assert booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.2
    assert booster.adjust_tp(base_tp_pips=30.0) == 36.0

    info = booster.info()
    assert info["in_confidence_mode"] is True
    assert info["tp_multiplier"] == 1.2

    # A loss immediately deactivates confidence mode
    booster.record_trade(False)
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0

    # Reentrant lock check
    with booster._lock:
        with booster._lock:
            booster.reset()
    assert booster._current_streak == 0


def test_wave61_opening_range_breakout():
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)
    orb.reset()

    # London Open: 08:05 UTC (within 30m window)
    dt_window = datetime(2026, 10, 19, 8, 5, tzinfo=timezone.utc)
    # Feed 6 ticks in range [2000.0, 2010.0]
    orb.update(2005.0, now_dt=dt_window)
    orb.update(2010.0, now_dt=dt_window)
    orb.update(2000.0, now_dt=dt_window)
    orb.update(2004.0, now_dt=dt_window)
    orb.update(2008.0, now_dt=dt_window)
    orb.update(2002.0, now_dt=dt_window)

    # During opening window, no breakout blocks are issued
    res_during = orb.is_signal_blocked("BUY", price=2005.0, now_dt=dt_window)
    assert not res_during.blocked

    # After opening window: 08:35 UTC (elapsed > 30m)
    dt_after = datetime(2026, 10, 19, 8, 35, tzinfo=timezone.utc)
    orb.update(2005.0, now_dt=dt_after)  # finalizes window

    # Inside range price (2005.0): not a breakout
    # BUY is blocked because price <= OR_high (2010.0)
    res_buy_inside = orb.is_signal_blocked("BUY", price=2005.0, now_dt=dt_after)
    assert res_buy_inside.blocked is True
    assert "price_not_above_or_high" in res_buy_inside.reason

    # Bullish breakout price (2015.0 > 2010.0): BUY allowed!
    res_buy_breakout = orb.is_signal_blocked("BUY", price=2015.0, now_dt=dt_after)
    assert res_buy_breakout.blocked is False

    # Bearish breakout price (1995.0 < 2000.0): SELL allowed!
    res_sell_breakout = orb.is_signal_blocked("SELL", price=1995.0, now_dt=dt_after)
    assert res_sell_breakout.blocked is False

    # Reentrant lock check
    with orb._lock:
        with orb._lock:
            orb.reset()
    assert orb._session_start is None


def test_python_engine_risk_guard():
    config = {
        "max_lot": 0.10,
        "max_daily_loss": 200.0,
        "balance_floor": 9000.0,
    }
    rg = RiskGuard(config)
    with rg._lock:
        with rg._lock:
            decision = Decision(allowed=True, reason="OK", lot=0.02)
    assert bool(decision) is True
    assert decision.allowed is True
    assert decision["allowed"] is True
    assert decision.lot == 0.02


def test_python_engine_storage(tmp_path):
    target = tmp_path / "test_data.json"
    payload = {"bot": "ScalpingRobotV5", "status": "active", "trades": 42}
    success = atomic_write_json(target, payload)
    assert success is True
    assert target.exists()
    assert (tmp_path / "test_data.json.bak").exists()


def test_python_engine_backtester():
    bt = Backtester({"symbol": "XAUUSD", "lot_size": 0.02})
    assert bt.symbol == "XAUUSD"
    assert bt.lot_size == 0.02

    # Session volatility check
    assert bt.get_session_volatility("TOKYO") == 0.02
    assert bt.get_session_volatility("LONDON") == 0.08
    assert bt.get_session_volatility("NY") == 0.12

    # Tick session determination
    session_tokyo, vol_tokyo = bt.determine_session(10, 100)
    assert session_tokyo == "TOKYO"
    assert vol_tokyo == 0.02

    session_ny, vol_ny = bt.determine_session(80, 100)
    assert session_ny == "NY"
    assert vol_ny == 0.12


def test_trade_journal_rlock(tmp_path):
    db_file = str(tmp_path / "test_trades.db")
    journal = TradeJournal(db_path=db_file)

    # Reentrant lock check
    with journal._lock:
        with journal._lock:
            success = journal.log_trade({
                "symbol": "XAUUSD",
                "direction": "BUY",
                "entry_price": 2000.0,
                "exit_price": 2005.0,
                "lot_size": 0.02,
                "pnl": 10.0,
                "exit_reason": "TP",
            })
    assert success is True


def test_performance_monitor_grading():
    assert calculate_grade(95.0) == "A+"
    assert calculate_grade(88.0) == "A"
    assert calculate_grade(78.0) == "B"
    assert calculate_grade(65.0) == "C"

    assert _safe_float(42.5) == 42.5
    assert _safe_float(None, 10.0) == 10.0
    assert _safe_float(float("nan"), 0.0) == 0.0
    assert _safe_float(float("inf"), 0.0) == 0.0
    assert _safe_float("corrupt", 5.0) == 5.0
