"""
Test Suite for Batch 141:
- wave48_equity_high_watermark.py (EquityHighWatermark: all-time high watermark 2% drawdown block)
- wave49_spread_cost_tracker.py (SpreadCostTracker: cumulative daily spread cost $50 cap)
Zero regressions, continuing toward 1,657+ passed tests.
"""

import math
from datetime import datetime, timezone
import pytest

from wave48_equity_high_watermark import (
    EquityHighWatermark,
    equity_high_watermark,
    is_entry_blocked as w48_is_entry_blocked,
    is_blocked as w48_is_blocked,
    update as w48_update,
    reset as w48_reset,
)
from wave49_spread_cost_tracker import (
    SpreadCostTracker,
    spread_cost_tracker,
    is_entry_blocked as w49_is_entry_blocked,
    is_blocked as w49_is_blocked,
    record_trade as w49_record_trade,
    reset as w49_reset,
)


# ---------------------------------------------------------------------
# Wave 48: Equity High Watermark Tests
# ---------------------------------------------------------------------

def test_wave48_initial_state():
    ehw = EquityHighWatermark()
    assert not ehw.is_entry_blocked()
    assert not ehw.is_blocked()
    allowed, reason = ehw.is_trading_allowed()
    assert allowed
    assert reason == ""
    info = ehw.info()
    assert info["watermark"] == 0.0
    assert info["last_equity"] == 0.0
    assert info["drawdown_pct"] == 0.0
    assert not info["entry_blocked"]
    assert info["total_triggers"] == 0


def test_wave48_invalid_inputs():
    ehw = EquityHighWatermark()
    t0 = 1000.0
    invalid_equities = [None, True, False, -100.0, 0.0, float("nan"), float("inf"), "abc"]
    for eq in invalid_equities:
        ehw.update(eq, now_ts=t0)

    assert ehw._watermark == 0.0
    assert not ehw.is_entry_blocked(now_ts=t0)


def test_wave48_watermark_tracking():
    ehw = EquityHighWatermark(threshold_pct=2.0)
    t0 = 1000.0
    # Set watermark at 10,000
    ehw.update(10000.0, now_ts=t0)
    assert ehw._watermark == 10000.0

    # Small dip to 9,900 (1.0% dd < 2.0% threshold)
    ehw.update(9900.0, now_ts=t0 + 10)
    assert not ehw.is_entry_blocked(now_ts=t0 + 10)
    allowed, reason = ehw.is_trading_allowed(now_ts=t0 + 10)
    assert allowed
    assert reason == ""
    assert ehw.info(now_ts=t0 + 10)["drawdown_pct"] == 1.0


def test_wave48_drawdown_block():
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800.0)
    t0 = 1000.0
    ehw.update(10000.0, now_ts=t0)
    # Significant drop to 9,750 (2.5% dd >= 2.0% threshold)
    ehw.update(9750.0, now_ts=t0 + 100)

    assert ehw.is_entry_blocked(now_ts=t0 + 100)
    assert ehw.is_blocked(now_ts=t0 + 100)
    allowed, reason = ehw.is_trading_allowed(now_ts=t0 + 100)
    assert not allowed
    assert "WATERMARK_DD" in reason
    info = ehw.info(now_ts=t0 + 100)
    assert info["entry_blocked"]
    assert info["drawdown_pct"] == 2.5
    assert info["total_triggers"] == 1


def test_wave48_cooldown_expiry_and_module_aliases():
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800.0)
    t0 = 1000.0
    ehw.update(10000.0, now_ts=t0)
    ehw.update(9700.0, now_ts=t0 + 100)
    assert ehw.is_entry_blocked(now_ts=t0 + 100)

    # 1801 seconds later, the block has expired
    t_after_block = t0 + 100 + 1801.0
    assert not ehw.is_entry_blocked(now_ts=t_after_block)
    assert ehw.info(now_ts=t_after_block)["block_remaining_sec"] == 0.0

    ehw.reset()
    assert ehw._watermark == 0.0
    assert not ehw.is_entry_blocked()

    # Module-level aliases
    w48_reset()
    assert not w48_is_entry_blocked()
    assert not w48_is_blocked()
    w48_update(5000.0)
    w48_reset()


# ---------------------------------------------------------------------
# Wave 49: Spread Cost Tracker Tests
# ---------------------------------------------------------------------

def test_wave49_initial_state():
    sct = SpreadCostTracker()
    assert sct.daily_cost_usd == 0.0
    assert sct.total_cost_usd == 0.0
    assert not sct.is_entry_blocked()
    assert not sct.is_blocked()
    allowed, reason = sct.is_trading_allowed()
    assert allowed
    assert reason == ""
    info = sct.info()
    assert info["daily_spread_cost_usd"] == 0.0
    assert info["trade_count"] == 0
    assert not info["entry_blocked"]


def test_wave49_invalid_inputs():
    sct = SpreadCostTracker()
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    for bad in [None, True, False, -1.0, float("nan"), float("inf"), "abc"]:
        sct.record_trade(spread_pips=bad, lot_size=0.02, now_dt=dt)
        sct.record_trade(spread_pips=2.0, lot_size=bad, now_dt=dt)

    assert sct.daily_cost_usd == 0.0
    assert sct.total_cost_usd == 0.0
    assert sct.info()["trade_count"] == 0


def test_wave49_trade_cost_accumulation():
    sct = SpreadCostTracker()
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    # Trade 1: spread 2.0 pips, lot 0.02 -> 2.0 * (0.02 / 0.01) * 1.0 = $4.00
    sct.record_trade(2.0, 0.02, now_dt=dt)
    assert sct.daily_cost_usd == 4.00
    assert sct.total_cost_usd == 4.00
    assert sct.get_daily_cost(now_dt=dt) == 4.00

    # Trade 2: spread 1.5 pips, lot 0.04 -> 1.5 * 4 * 1.0 = $6.00
    sct.record_trade(1.5, 0.04, now_dt=dt)
    assert sct.daily_cost_usd == 10.00
    assert sct.total_cost_usd == 10.00
    assert sct.info(now_dt=dt)["trade_count"] == 2


def test_wave49_daily_cap_exceeded():
    sct = SpreadCostTracker(max_daily_usd=50.0)
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    # 13 trades with $4.00 cost each = $52.00 >= $50.0 cap
    for _ in range(13):
        sct.record_trade(2.0, 0.02, now_dt=dt)

    assert sct.is_entry_blocked(now_dt=dt)
    assert sct.is_blocked(now_dt=dt)
    allowed, reason = sct.is_trading_allowed(now_dt=dt)
    assert not allowed
    assert "SPREAD_CAP" in reason
    info = sct.info(now_dt=dt)
    assert info["entry_blocked"]
    assert info["daily_spread_cost_usd"] == 52.00


def test_wave49_midnight_rollover_and_module_aliases():
    sct = SpreadCostTracker(max_daily_usd=50.0)
    dt_day1 = datetime(2026, 10, 18, 23, 50, tzinfo=timezone.utc)
    for _ in range(13):
        sct.record_trade(2.0, 0.02, now_dt=dt_day1)
    assert sct.is_entry_blocked(now_dt=dt_day1)

    # Rollover to next day (2026-10-19 00:05 UTC)
    dt_day2 = datetime(2026, 10, 19, 0, 5, tzinfo=timezone.utc)
    # Daily cost resets to 0.0 on new day, total cost remains 52.00
    assert not sct.is_entry_blocked(now_dt=dt_day2)
    assert sct.daily_cost_usd == 0.0
    assert sct.total_cost_usd == 52.00

    sct.reset()
    assert sct.total_cost_usd == 0.0

    # Module-level aliases
    w49_reset()
    assert not w49_is_entry_blocked(now_dt=dt_day1)
    assert not w49_is_blocked(now_dt=dt_day1)
    w49_record_trade(1.0, 0.01, now_dt=dt_day1)
    w49_reset()
