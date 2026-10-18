"""
Test Suite for Batch 144:
- wave54_max_spread_per_trade.py (MaxSpreadPerTrade: per-tick 2.5-pip spread cap guard)
- wave55_balance_floor_guard.py (BalanceFloorGuard: hard $9,500 balance floor & hysteresis recovery)
Zero regressions, continuing toward 1,687+ passed tests.
"""

import math
from datetime import datetime, timezone
import pytest

from wave54_max_spread_per_trade import (
    MaxSpreadPerTrade,
    max_spread_per_trade,
    is_entry_blocked as w54_is_entry_blocked,
    is_blocked as w54_is_blocked,
    update as w54_update,
    reset as w54_reset,
)
from wave55_balance_floor_guard import (
    BalanceFloorGuard,
    balance_floor_guard,
    is_entry_blocked as w55_is_entry_blocked,
    is_blocked as w55_is_blocked,
    update as w55_update,
    reset as w55_reset,
)


# ---------------------------------------------------------------------
# Wave 54: Max Spread Cost Per Trade Tests
# ---------------------------------------------------------------------

def test_wave54_initial_state():
    mspt = MaxSpreadPerTrade()
    assert not mspt.is_entry_blocked()
    assert not mspt.is_blocked()
    allowed, reason = mspt.is_trading_allowed()
    assert allowed
    assert reason == ""
    info = mspt.info()
    assert info["max_spread_pips"] == 2.5
    assert info["current_spread_pips"] == 0.0
    assert not info["is_blocked"]
    assert info["block_count"] == 0


def test_wave54_invalid_inputs():
    mspt = MaxSpreadPerTrade()
    # Invalid updates ignored
    for bad in [None, True, False, -1.0, float("nan"), float("inf"), "abc"]:
        mspt.update(bad)
    assert mspt.get_spread() == 0.0

    # Invalid candidate spread parameter in query fails closed
    assert mspt.is_entry_blocked(spread_pips=-5.0)
    assert mspt.is_entry_blocked(spread_pips=float("nan"))
    assert mspt.is_entry_blocked(spread_pips="wide")


def test_wave54_acceptable_spread():
    mspt = MaxSpreadPerTrade(max_spread_pips=2.5)
    # Feed 1.8 pips (< 2.5 cap)
    mspt.update(1.8)
    assert mspt.get_spread() == 1.8
    assert not mspt.is_entry_blocked()
    assert not mspt.is_blocked()
    allowed, reason = mspt.is_trading_allowed()
    assert allowed
    assert reason == ""
    assert mspt.info()["allow_count"] >= 1


def test_wave54_wide_spread_blocks_trade():
    mspt = MaxSpreadPerTrade(max_spread_pips=2.5)
    # Feed 3.2 pips (> 2.5 cap)
    mspt.update(3.2)
    assert mspt.get_spread() == 3.2
    assert mspt.is_entry_blocked()
    assert mspt.is_blocked()
    allowed, reason = mspt.is_trading_allowed()
    assert not allowed
    assert "SPREAD_TOO_HIGH" in reason
    info = mspt.info()
    assert info["is_blocked"]
    assert info["block_count"] >= 1


def test_wave54_reset_and_module_aliases():
    mspt = MaxSpreadPerTrade(max_spread_pips=2.5)
    mspt.update(3.0)
    assert mspt.is_entry_blocked()

    mspt.reset()
    assert mspt.get_spread() == 0.0
    assert not mspt.is_entry_blocked()

    # Module-level aliases
    w54_reset()
    assert not w54_is_entry_blocked()
    assert not w54_is_blocked()
    w54_update(1.5)
    assert not w54_is_entry_blocked()
    assert w54_is_blocked(spread_pips=4.0)
    w54_reset()


# ---------------------------------------------------------------------
# Wave 55: Balance Floor Guard Tests
# ---------------------------------------------------------------------

def test_wave55_initial_state():
    bfg = BalanceFloorGuard()
    assert bfg.floor_usd == 9500.0
    assert bfg.min_balance == 9500.0
    assert not bfg.is_halted
    assert not bfg.is_entry_blocked()
    assert not bfg.is_blocked()
    allowed, reason = bfg.is_trading_allowed()
    assert allowed
    assert reason == ""
    info = bfg.info()
    assert info["floor_usd"] == 9500.0
    assert info["hysteresis_usd"] == 50.0
    assert not info["is_halted"]
    assert info["halt_count"] == 0


def test_wave55_invalid_balance_inputs():
    bfg = BalanceFloorGuard()
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    for bad in [None, True, False, float("nan"), float("inf"), "abc"]:
        bfg.update(bad, now_dt=dt)

    assert bfg.current_balance == 0.0
    assert not bfg.is_halted


def test_wave55_balance_floor_breach_halts_trading():
    bfg = BalanceFloorGuard(floor_usd=9500.0)
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)

    # Balance healthy: $10,000
    bfg.update(10000.0, now_dt=dt)
    assert not bfg.is_entry_blocked(now_dt=dt)
    assert not bfg.is_halted

    # Balance breaches floor: $9,400 (< $9,500)
    bfg.update(9400.0, now_dt=dt)
    assert bfg.is_halted
    assert bfg.is_entry_blocked(now_dt=dt)
    assert bfg.is_blocked(now_dt=dt)
    allowed, reason = bfg.is_trading_allowed(now_dt=dt)
    assert not allowed
    assert "BALANCE_FLOOR" in reason
    info = bfg.info()
    assert info["is_halted"]
    assert info["halt_count"] == 1


def test_wave55_hysteresis_and_midnight_recovery():
    bfg = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)
    dt_day1 = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)

    bfg.update(9400.0, now_dt=dt_day1)
    assert bfg.is_halted

    # Recovery attempt 1: $9,520 (above floor 9500, but < 9500 + 50 = 9550 hysteresis ceiling)
    bfg.update(9520.0, now_dt=dt_day1)
    assert bfg.is_halted
    assert bfg.is_entry_blocked(now_dt=dt_day1)

    # Recovery attempt 2: $9,560 (>= 9550 hysteresis ceiling)
    bfg.update(9560.0, now_dt=dt_day1)
    assert not bfg.is_halted
    assert not bfg.is_entry_blocked(now_dt=dt_day1)

    # Breach again at end of day
    bfg.update(9450.0, now_dt=dt_day1)
    assert bfg.is_halted

    # Next UTC day (2026-10-19): balance recovers above floor ($9,510 >= 9500)
    dt_day2 = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)
    bfg.update(9510.0, now_dt=dt_day2)
    assert not bfg.is_halted
    assert not bfg.is_entry_blocked(now_dt=dt_day2)


def test_wave55_catastrophic_zero_balance_and_module_aliases():
    bfg = BalanceFloorGuard(floor_usd=9500.0)
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    # Catastrophic blowout
    bfg.update(0.0, now_dt=dt)
    assert bfg.is_halted
    assert bfg.is_entry_blocked(now_dt=dt)

    bfg.reset()
    assert not bfg.is_halted

    # Module-level aliases
    w55_reset()
    assert not w55_is_entry_blocked()
    assert not w55_is_blocked()
    w55_update(10000.0, now_dt=dt)
    assert not w55_is_entry_blocked(now_dt=dt)
    w55_update(9200.0, now_dt=dt)
    assert w55_is_blocked(now_dt=dt)
    w55_reset()
