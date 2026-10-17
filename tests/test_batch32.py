"""
Tests for Batch 32 Hardening:
- wave47_atr_position_sizer.py
- wave48_equity_high_watermark.py
- wave49_spread_cost_tracker.py
- wave50_candle_pattern_filter.py
- wave51_session_pnl_tracker.py
- wave52_rsi_ob_os_filter.py
- wave53_tick_reversal_guard.py
- wave54_max_spread_per_trade.py
- wave55_balance_floor_guard.py
- wave56_consecutive_loss_guard.py
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave47_atr_position_sizer import ATRPositionSizer
from wave48_equity_high_watermark import EquityHighWatermark
from wave49_spread_cost_tracker import SpreadCostTracker
from wave50_candle_pattern_filter import CandlePatternFilter
from wave51_session_pnl_tracker import SessionPnLTracker
from wave52_rsi_ob_os_filter import RSIOverboughtOversold
from wave53_tick_reversal_guard import TickReversalGuard
from wave54_max_spread_per_trade import MaxSpreadPerTrade
from wave55_balance_floor_guard import BalanceFloorGuard
from wave56_consecutive_loss_guard import ConsecutiveLossGuard


def test_wave47_atr_position_sizer():
    sizer = ATRPositionSizer(period=14)
    sizer.reset()

    # Feed price updates
    base_p = 2000.0
    for i in range(30):
        h = base_p + 2.0
        l = base_p - 2.0
        c = base_p + (0.5 if i % 2 == 0 else -0.5)
        sizer.update(high=h, low=l, close=c)

    atr = sizer.get_atr()
    assert atr > 0.0

    # Test dynamic SL/TP bounds
    sl, tp = sizer.get_sl_tp(base_sl=30.0, base_tp=45.0)
    assert 15.0 <= sl <= 60.0
    assert 22.0 <= tp <= 90.0

    # Test position lot sizing
    lot = sizer.get_lot_size(account_balance=10000.0, risk_pct=0.01, sl_pips=30.0, pip_value=10.0)
    assert 0.01 <= lot <= 100.0

    # Invalid balance fails safely to min_lot
    assert sizer.get_lot_size(account_balance=-500.0) == 0.01
    assert sizer.get_lot_size(account_balance=None) == 0.01

    # Reentrant lock check
    with sizer._lock:
        with sizer._lock:
            sizer.reset()
    assert sizer.get_atr() == 0.0


def test_wave48_equity_high_watermark():
    wm = EquityHighWatermark(threshold_pct=2.0, block_sec=1800)
    wm.reset()
    t0 = 1000.0

    # Feed rising equity
    wm.update(10000.0, now_ts=t0)
    wm.update(12000.0, now_ts=t0 + 10)
    assert not wm.is_entry_blocked(now_ts=t0 + 10)

    # Drawdown 2.5% ($12,000 -> $11,700) triggers block for 1800s
    wm.update(11700.0, now_ts=t0 + 20)
    assert wm.is_entry_blocked(now_ts=t0 + 20)
    assert wm.is_blocked(now_ts=t0 + 20)

    allowed, reason = wm.is_trading_allowed(now_ts=t0 + 20)
    assert not allowed
    assert "WATERMARK_DD" in reason

    info = wm.info(now_ts=t0 + 20)
    assert info["entry_blocked"] is True
    assert info["watermark"] == 12000.0

    # Expiry after 1801s clears block
    assert not wm.is_entry_blocked(now_ts=t0 + 20 + 1801)

    # Reentrant lock check
    with wm._lock:
        with wm._lock:
            wm.reset()
    assert not wm.is_entry_blocked(now_ts=t0 + 20)


def test_wave49_spread_cost_tracker():
    tracker = SpreadCostTracker(max_daily_usd=50.0)
    tracker.reset()

    # UTC Monday 10:00
    dt_day1 = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    # 2.0 pips spread on 0.10 lot: 2.0 * (0.10 / 0.01) * $1.00 = $20.00 cost
    tracker.record_trade(spread_pips=2.0, lot_size=0.10, now_dt=dt_day1)
    assert tracker.get_daily_cost(now_dt=dt_day1) == 20.0
    assert not tracker.is_entry_blocked(now_dt=dt_day1)

    # Another trade of $20.00 -> $40.00 total
    tracker.record_trade(spread_pips=2.0, lot_size=0.10, now_dt=dt_day1)
    assert tracker.get_daily_cost(now_dt=dt_day1) == 40.0
    assert not tracker.is_entry_blocked(now_dt=dt_day1)

    # Another trade of $20.00 -> $60.00 total (exceeds $50.00 cap)
    tracker.record_trade(spread_pips=2.0, lot_size=0.10, now_dt=dt_day1)
    assert tracker.is_entry_blocked(now_dt=dt_day1)
    allowed, reason = tracker.is_trading_allowed(now_dt=dt_day1)
    assert not allowed
    assert "SPREAD_CAP" in reason

    # New day (Tuesday 01:00 UTC) automatically resets daily cost
    dt_day2 = datetime(2026, 10, 20, 1, 0, tzinfo=timezone.utc)
    assert not tracker.is_entry_blocked(now_dt=dt_day2)
    assert tracker.get_daily_cost(now_dt=dt_day2) == 0.0

    # Reentrant lock check
    with tracker._lock:
        with tracker._lock:
            tracker.reset()
    assert tracker.get_daily_cost() == 0.0


def test_wave50_candle_pattern_filter():
    filter_ = CandlePatternFilter()
    filter_.reset()

    # Doji candle: open 2000.0, high 2005.0, low 1995.0, close 2000.2 (body 0.2 < 10% of range 10.0)
    filter_.update_candle(o=2000.0, h=2005.0, l=1995.0, c=2000.2)
    assert filter_._last_pattern == "DOJI"
    assert filter_.is_signal_blocked("BUY")
    assert filter_.is_signal_blocked("SELL")

    # Hammer candle: body >= 10% range, lower wick > 2x body, upper wick small (Bullish)
    # open 2000.0, close 2003.0 (body 3.0), high 2004.0 (upper wick 1.0 < 3.0), low 1985.0 (lower wick 15.0 > 6.0)
    filter_.update_candle(o=2000.0, h=2004.0, l=1985.0, c=2003.0)
    assert filter_._last_pattern == "HAMMER"
    assert not filter_.is_signal_blocked("BUY")
    assert filter_.is_signal_blocked("SELL")  # Hammer blocks SELL

    # Inverted hammer candle: body >= 10% range, upper wick > 2x body, lower wick small (Bearish)
    # open 2000.0, close 1997.0 (body 3.0), high 2015.0 (upper wick 15.0 > 6.0), low 1996.0 (lower wick 1.0 < 3.0)
    filter_.update_candle(o=2000.0, h=2015.0, l=1996.0, c=1997.0)
    assert filter_._last_pattern == "INV_HAMMER"
    assert filter_.is_signal_blocked("BUY")  # Inv Hammer blocks BUY
    assert not filter_.is_signal_blocked("SELL")

    # Reentrant lock check
    with filter_._lock:
        with filter_._lock:
            filter_.reset()
    assert filter_._last_pattern == "NONE"


def test_wave51_session_pnl_tracker():
    tracker = SessionPnLTracker(loss_limit=-100.0)
    tracker.reset()

    # Tokyo session (03:00 UTC)
    dt_tokyo = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)
    tracker.record_trade(pnl=-60.0, now_dt=dt_tokyo)
    assert not tracker.is_entry_blocked(now_dt=dt_tokyo)

    # Accumulate loss to -$120.0 (exceeds -$100.0 limit)
    tracker.record_trade(pnl=-60.0, now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo)
    allowed, reason = tracker.is_trading_allowed(now_dt=dt_tokyo)
    assert not allowed
    assert "Tokyo" in reason

    # London session (09:00 UTC) is a separate session and is not blocked
    dt_london = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
    assert not tracker.is_entry_blocked(now_dt=dt_london)

    # Reentrant lock check
    with tracker._lock:
        with tracker._lock:
            tracker.reset()
    assert not tracker.is_entry_blocked(now_dt=dt_tokyo)


def test_wave52_rsi_ob_os_filter():
    rsi_filter = RSIOverboughtOversold(period=14, ob_block=75.0, os_block=25.0)
    rsi_filter.reset()

    # Feed rising price ticks to push RSI into overbought territory
    price = 2000.0
    for i in range(25):
        price += 1.5
        rsi_filter.update(price)

    rsi = rsi_filter.get_rsi()
    assert rsi > 70.0
    assert rsi_filter.is_entry_blocked("BUY")
    assert not rsi_filter.is_entry_blocked("SELL")

    # Feed falling price ticks to push RSI into oversold territory
    for i in range(40):
        price -= 3.0
        rsi_filter.update(price)

    rsi_low = rsi_filter.get_rsi()
    assert rsi_low < 30.0
    assert rsi_filter.is_entry_blocked("SELL")
    assert not rsi_filter.is_entry_blocked("BUY")

    # Reentrant lock check
    with rsi_filter._lock:
        with rsi_filter._lock:
            rsi_filter.reset()
    assert rsi_filter.get_rsi() == 50.0


def test_wave53_tick_reversal_guard():
    guard = TickReversalGuard(n_ticks=5, block_duration=30.0)
    guard.reset()
    t0 = 2000.0

    # 5 consecutive falling ticks: adverse momentum against BUY
    p = 2050.0
    for i in range(6):
        p -= 0.5
        guard.update(p)

    # Consecutive direction is DOWN -> blocks BUY, allows SELL
    assert guard._consecutive_direction() == "DOWN"
    assert guard.is_entry_blocked("BUY", now_ts=t0)
    assert not guard.is_entry_blocked("SELL", now_ts=t0)

    # 5 consecutive rising ticks: adverse momentum against SELL
    guard.reset()
    p = 2000.0
    for i in range(6):
        p += 0.5
        guard.update(p)

    assert guard._consecutive_direction() == "UP"
    assert guard.is_entry_blocked("SELL", now_ts=t0)
    assert not guard.is_entry_blocked("BUY", now_ts=t0)

    # Reentrant lock check
    with guard._lock:
        with guard._lock:
            guard.reset()
    assert guard._consecutive_direction() == "MIXED"


def test_wave54_max_spread_per_trade():
    guard = MaxSpreadPerTrade(max_spread_pips=2.5)
    guard.reset()

    # Normal spread <= 2.5 pips
    guard.update(1.8)
    assert not guard.is_entry_blocked()
    assert not guard.is_blocked()

    # Direct query with acceptable spread
    assert not guard.is_entry_blocked(spread_pips=2.4)

    # High spread > 2.5 pips
    guard.update(2.8)
    assert guard.is_entry_blocked()
    allowed, reason = guard.is_trading_allowed()
    assert not allowed
    assert "SPREAD_TOO_HIGH" in reason

    # Direct query with high spread
    assert guard.is_entry_blocked(spread_pips=3.2)

    # Invalid spread fails closed
    assert guard.is_entry_blocked(spread_pips=-1.0)
    assert guard.is_entry_blocked(spread_pips=float("nan"))

    # Reentrant lock check
    with guard._lock:
        with guard._lock:
            guard.reset()
    assert guard.get_spread() == 0.0


def test_wave55_balance_floor_guard():
    floor_guard = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)
    floor_guard.reset()
    dt0 = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    # Normal balance > 9500
    floor_guard.update(10000.0, now_dt=dt0)
    assert not floor_guard.is_entry_blocked(now_dt=dt0)
    assert not floor_guard.is_halted

    # Balance drops below floor ($9,400) -> HALT triggered
    floor_guard.update(9400.0, now_dt=dt0)
    assert floor_guard.is_entry_blocked(now_dt=dt0)
    assert floor_guard.is_halted

    # Small recovery to $9,520 is below hysteresis ($9,500 + $50 = $9,550) -> remains halted
    floor_guard.update(9520.0, now_dt=dt0)
    assert floor_guard.is_entry_blocked(now_dt=dt0)

    # Recovery to $9,600 (> $9,550) -> automatically unlocks
    floor_guard.update(9600.0, now_dt=dt0)
    assert not floor_guard.is_entry_blocked(now_dt=dt0)
    assert not floor_guard.is_halted

    # Reentrant lock check
    with floor_guard._lock:
        with floor_guard._lock:
            floor_guard.reset()
    assert not floor_guard.is_halted


def test_wave56_consecutive_loss_guard():
    guard = ConsecutiveLossGuard(max_losses=3, pause_seconds=1800.0)
    guard.reset()
    t0 = 3000.0

    # 1st loss
    guard.record_trade(won=False, now_ts=t0)
    assert not guard.is_entry_blocked(now_ts=t0)
    assert guard._consecutive_losses == 1

    # 2nd loss
    guard.record_trade(won=False, now_ts=t0 + 10)
    assert not guard.is_entry_blocked(now_ts=t0 + 10)
    assert guard._consecutive_losses == 2

    # 3rd consecutive loss -> triggers 1800s entry block
    guard.record_trade(won=False, now_ts=t0 + 20)
    assert guard.is_entry_blocked(now_ts=t0 + 20)
    info = guard.info(now_ts=t0 + 20)
    assert info["paused"] is True
    assert info["consecutive_losses"] == 3

    # Win clears streak and resets
    guard.record_trade(won=True, now_ts=t0 + 30)
    assert guard._consecutive_losses == 0

    # Test expiry after 1800s
    guard.record_trade(won=False, now_ts=t0 + 40)
    guard.record_trade(won=False, now_ts=t0 + 50)
    guard.record_trade(won=False, now_ts=t0 + 60)
    assert guard.is_entry_blocked(now_ts=t0 + 60)
    assert not guard.is_entry_blocked(now_ts=t0 + 60 + 1801)

    # Reentrant lock check
    with guard._lock:
        with guard._lock:
            guard.reset()
    assert not guard.is_entry_blocked(now_ts=t0)
