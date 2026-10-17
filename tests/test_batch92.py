"""
tests/test_batch92.py
Batch 92 Unit Tests: Equity High Watermark (wave48) & Spread Cost Tracker (wave49).
Expands test baseline beyond 1,157+ passing tests to 1,167+ passing tests.
Verifies:
1. wave48: EquityHighWatermark initialization defaults, threshold bounds, and non-finite sanitization.
2. wave48: Watermark tracking dynamics, peak equity updates, and non-breaching drawdown calculations.
3. wave48: Drawdown breach (> 2.0%) triggering 30-minute entry block and diagnostic reason formatting.
4. wave48: Cooldown timer expiration unblocking trading and persistent block during active lockout.
5. wave48: EquityHighWatermark reset() clearing, info() diagnostics, and non-finite input filtering.
6. wave49: SpreadCostTracker initialization defaults, daily cap sanitization, and property getters.
7. wave49: Trade spread cost calculation (spread * lot / 0.01) and cumulative daily/total accumulation.
8. wave49: Daily spread cost cap breach ($50.00 default) triggering entry blocking and reason formatting.
9. wave49: UTC midnight rollover resetting daily spread cost while preserving lifetime total cost.
10. wave49: SpreadCostTracker reset() clearing, info() diagnostic telemetry, and invalid input filtering.
"""

import math
from datetime import datetime, timezone
import pytest

from wave48_equity_high_watermark import EquityHighWatermark
from wave49_spread_cost_tracker import SpreadCostTracker


def test_wave48_initialization_defaults_and_clamping():
    """Verify EquityHighWatermark initializes with defaults and clamps invalid arguments."""
    # Defaults: threshold=2.0%, block_sec=1800s
    ehw = EquityHighWatermark()
    assert ehw._threshold_pct == 2.0
    assert ehw._block_sec == 1800.0
    assert ehw._watermark == 0.0
    assert ehw._block_until == 0.0
    assert ehw._total_triggers == 0

    # Custom valid configuration
    custom = EquityHighWatermark(threshold_pct=3.5, block_sec=900.0)
    assert custom._threshold_pct == 3.5
    assert custom._block_sec == 900.0

    # Clamping negative, zero, or non-finite inputs to defaults
    assert EquityHighWatermark(threshold_pct=-1.0)._threshold_pct == 2.0
    assert EquityHighWatermark(threshold_pct=0.0)._threshold_pct == 2.0
    assert EquityHighWatermark(threshold_pct=float("nan"))._threshold_pct == 2.0
    assert EquityHighWatermark(block_sec=-50.0)._block_sec == 1800.0
    assert EquityHighWatermark(block_sec="bad")._block_sec == 1800.0


def test_wave48_watermark_tracking_and_drawdown_calculation():
    """Verify watermark advances with equity peaks and calculates drawdown percentages without premature blocks."""
    ehw = EquityHighWatermark(threshold_pct=2.0)
    t0 = 1750000000.0

    # First equity update establishes initial watermark
    ehw.update(10000.0, now_ts=t0)
    assert ehw._watermark == 10000.0
    assert ehw._last_equity == 10000.0
    assert ehw._dd_pct == 0.0
    assert ehw.is_entry_blocked(now_ts=t0) is False

    # Equity rises: watermark advances
    ehw.update(10500.0, now_ts=t0 + 60.0)
    assert ehw._watermark == 10500.0
    assert ehw._last_equity == 10500.0
    assert ehw._dd_pct == 0.0

    # Equity dips slightly: 10,400 (dd = (10500-10400)/10500 * 100 = 0.9524% < 2.0%)
    ehw.update(10400.0, now_ts=t0 + 120.0)
    assert ehw._watermark == 10500.0
    assert ehw._last_equity == 10400.0
    assert ehw._dd_pct == pytest.approx(0.9524, abs=0.001)
    assert ehw.is_entry_blocked(now_ts=t0 + 120.0) is False


def test_wave48_drawdown_breach_triggers_30min_block():
    """Verify equity drawdown >= threshold triggers entry lockout for configured duration."""
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800.0)
    t0 = 1750000000.0

    ehw.update(10000.0, now_ts=t0)

    # Equity drops to 9,750 (dd = 2.5% >= 2.0% threshold)
    ehw.update(9750.0, now_ts=t0 + 30.0)
    assert ehw._dd_pct == 2.5
    assert ehw._total_triggers == 1
    assert ehw._block_until == t0 + 30.0 + 1800.0
    assert ehw.is_entry_blocked(now_ts=t0 + 30.0) is True
    assert ehw.is_blocked(now_ts=t0 + 30.0) is True

    allowed, reason = ehw.is_trading_allowed(now_ts=t0 + 30.0)
    assert allowed is False
    assert "WATERMARK_DD: 2.5% drawdown active" in reason


def test_wave48_cooldown_expiration_and_recovery():
    """Verify trading remains locked during block duration and automatically unblocks once cooldown expires."""
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800.0)
    t0 = 1750000000.0

    ehw.update(10000.0, now_ts=t0)
    ehw.update(9700.0, now_ts=t0 + 10.0)  # 3.0% dd -> block until t0 + 1810.0

    # 15 minutes in (900s elapsed): still blocked
    assert ehw.is_entry_blocked(now_ts=t0 + 910.0) is True

    # Exactly when cooldown expires (1800s elapsed): unblocked
    assert ehw.is_entry_blocked(now_ts=t0 + 1811.0) is False
    allowed, reason = ehw.is_trading_allowed(now_ts=t0 + 1811.0)
    assert allowed is True
    assert reason == ""


def test_wave48_reset_and_info_telemetry():
    """Verify reset() clears state, info() provides telemetry, and invalid inputs are filtered."""
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800.0)
    t0 = 1750000000.0

    # Filter invalid inputs
    ehw.update(None)
    ehw.update(True)
    ehw.update(False)
    ehw.update(-100.0)
    ehw.update(0.0)
    ehw.update(float("nan"))
    ehw.update(float("inf"))
    assert ehw._watermark == 0.0

    # Establish state
    ehw.update(10000.0, now_ts=t0)
    ehw.update(9750.0, now_ts=t0 + 10.0)

    info = ehw.info(now_ts=t0 + 10.0)
    assert info["wave"] == 48
    assert info["name"] == "EquityHighWatermark"
    assert info["watermark"] == 10000.0
    assert info["last_equity"] == 9750.0
    assert info["drawdown_pct"] == 2.5
    assert info["entry_blocked"] is True
    assert info["total_triggers"] == 1
    assert info["block_remaining_sec"] == 1800.0

    ehw.reset()
    info_reset = ehw.info(now_ts=t0 + 10.0)
    assert info_reset["watermark"] == 0.0
    assert info_reset["entry_blocked"] is False
    assert info_reset["total_triggers"] == 0


def test_wave49_initialization_defaults_and_clamping():
    """Verify SpreadCostTracker initializes with defaults and clamps invalid constructor values."""
    sct = SpreadCostTracker()
    assert sct._max_daily_usd == 50.0
    assert sct.daily_cost_usd == 0.0
    assert sct.total_cost_usd == 0.0
    assert sct._trade_count == 0
    assert sct._total_blocks == 0

    # Custom valid configuration
    custom = SpreadCostTracker(max_daily_usd=75.0)
    assert custom._max_daily_usd == 75.0

    # Clamping invalid inputs to 50.0
    assert SpreadCostTracker(max_daily_usd=-10.0)._max_daily_usd == 50.0
    assert SpreadCostTracker(max_daily_usd=0.0)._max_daily_usd == 50.0
    assert SpreadCostTracker(max_daily_usd=float("nan"))._max_daily_usd == 50.0
    assert SpreadCostTracker(max_daily_usd="invalid")._max_daily_usd == 50.0


def test_wave49_record_trade_cost_accumulation():
    """Verify trade spread cost calculation (spread * lot / 0.01) and daily/total aggregation."""
    sct = SpreadCostTracker(max_daily_usd=50.0)
    dt = datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)

    # Trade 1: spread=1.5 pips, lot=0.01 -> cost = 1.5 * (0.01/0.01) * $1 = $1.50
    sct.record_trade(spread_pips=1.5, lot_size=0.01, now_dt=dt)
    assert sct.daily_cost_usd == 1.50
    assert sct.total_cost_usd == 1.50
    assert sct._trade_count == 1

    # Trade 2: spread=2.0 pips, lot=0.02 -> cost = 2.0 * (0.02/0.01) * $1 = $4.00
    sct.record_trade(spread_pips=2.0, lot_size=0.02, now_dt=dt)
    assert sct.daily_cost_usd == 5.50
    assert sct.total_cost_usd == 5.50
    assert sct._trade_count == 2
    assert sct.get_daily_cost(now_dt=dt) == 5.50

    # Invalid trade inputs are safely ignored
    sct.record_trade(spread_pips=None, lot_size=0.01, now_dt=dt)
    sct.record_trade(spread_pips=1.5, lot_size=None, now_dt=dt)
    sct.record_trade(spread_pips=True, lot_size=0.01, now_dt=dt)
    sct.record_trade(spread_pips=1.5, lot_size=-0.01, now_dt=dt)
    sct.record_trade(spread_pips=-1.0, lot_size=0.01, now_dt=dt)
    sct.record_trade(spread_pips=float("nan"), lot_size=0.01, now_dt=dt)
    assert sct._trade_count == 2


def test_wave49_daily_cost_cap_breach_blocks_entry():
    """Verify cumulative daily spread cost exceeding max_daily_usd blocks entry."""
    sct = SpreadCostTracker(max_daily_usd=50.0)
    dt = datetime(2026, 10, 18, 14, 0, 0, tzinfo=timezone.utc)

    # Trade costing $30: 1.5 pips * 0.20 lots -> $30.00
    sct.record_trade(spread_pips=1.5, lot_size=0.20, now_dt=dt)
    assert sct.is_entry_blocked(now_dt=dt) is False
    assert sct.is_blocked(now_dt=dt) is False

    # Second trade costing $25: 1.25 pips * 0.20 lots -> $25.00
    # Total daily = $55.00 >= $50.00 cap -> BLOCKED!
    sct.record_trade(spread_pips=1.25, lot_size=0.20, now_dt=dt)
    assert sct.is_entry_blocked(now_dt=dt) is True
    assert sct._total_blocks == 1

    allowed, reason = sct.is_trading_allowed(now_dt=dt)
    assert allowed is False
    assert "SPREAD_CAP: daily cost $55.00 >= $50.00" in reason


def test_wave49_utc_midnight_rollover_resets_daily_cost():
    """Verify transition to a new UTC date flushes daily spread cost while retaining lifetime total cost."""
    sct = SpreadCostTracker(max_daily_usd=50.0)
    dt_day1 = datetime(2026, 10, 18, 23, 45, 0, tzinfo=timezone.utc)
    dt_day2 = datetime(2026, 10, 19, 0, 15, 0, tzinfo=timezone.utc)

    # Day 1: Trade costing $55.00 -> blocked
    sct.record_trade(spread_pips=2.75, lot_size=0.20, now_dt=dt_day1)
    assert sct.daily_cost_usd == 55.00
    assert sct.total_cost_usd == 55.00
    assert sct.is_entry_blocked(now_dt=dt_day1) is True

    # Day 2 rollover: daily cost resets to $0.00, unblocking entry
    assert sct.is_entry_blocked(now_dt=dt_day2) is False
    assert sct.daily_cost_usd == 0.0
    assert sct.total_cost_usd == 55.00  # Total preserved


def test_wave49_reset_and_info_introspection():
    """Verify reset() flushes state and info() outputs diagnostic telemetry."""
    sct = SpreadCostTracker(max_daily_usd=50.0)
    dt = datetime(2026, 10, 18, 16, 0, 0, tzinfo=timezone.utc)
    sct.record_trade(spread_pips=2.0, lot_size=0.10, now_dt=dt)  # $20.00 cost

    info = sct.info(now_dt=dt)
    assert info["wave"] == 49
    assert info["name"] == "SpreadCostTracker"
    assert info["daily_spread_cost_usd"] == 20.0
    assert info["total_spread_cost_usd"] == 20.0
    assert info["max_daily_usd"] == 50.0
    assert info["trade_count"] == 1
    assert info["entry_blocked"] is False
    assert info["current_day"] == "2026-10-18"

    sct.reset()
    info_reset = sct.info(now_dt=dt)
    assert info_reset["daily_spread_cost_usd"] == 0.0
    assert info_reset["total_spread_cost_usd"] == 0.0
    assert info_reset["trade_count"] == 0
