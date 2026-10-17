"""
tests/test_batch89.py
Batch 89 Unit Tests: Max Spread Cost Per Trade (wave54) & Balance Floor Guard (wave55).
Expands test baseline beyond 1,127+ passing tests to 1,137+ passing tests.
Verifies:
1. wave54: MaxSpreadPerTrade initialization defaults, parameter bounds, and input sanitization.
2. wave54: Live tick spread ingestion, staleness tracking, and non-finite/negative input rejection.
3. wave54: Entry gating logic, block/allow counters, and is_trading_allowed diagnostic messages.
4. wave54: Direct candidate spread argument override evaluation and fail-closed handling.
5. wave54: MaxSpreadPerTrade reset() clearing and info() telemetry introspection.
6. wave55: BalanceFloorGuard initialization defaults, parameter aliases, and property getters.
7. wave55: Catastrophic balance blowout halt on balance <= 0.0 with fail-closed gating.
8. wave55: Hard floor breach halt and intraday hysteresis recovery mechanism (floor + hysteresis).
9. wave55: Next-day UTC midnight auto-unlock when transitioning to a new session date.
10. wave55: BalanceFloorGuard reset(), info() telemetry reporting, and thread-safe concurrent updates.
"""

import math
import threading
import time
from datetime import datetime, timezone
import pytest

from wave54_max_spread_per_trade import MaxSpreadPerTrade
from wave55_balance_floor_guard import BalanceFloorGuard


def test_wave54_initialization_defaults_and_sanitization():
    """Verify MaxSpreadPerTrade initializes with default 2.5 pips and sanitizes invalid caps."""
    # Default 2.5 pips
    guard = MaxSpreadPerTrade()
    assert guard._max_spread == 2.5
    assert guard.get_spread() == 0.0

    # Custom valid float
    guard_custom = MaxSpreadPerTrade(max_spread_pips=3.2)
    assert guard_custom._max_spread == 3.2

    # Sanitization of invalid, negative, or non-finite inputs falls back to 2.5
    assert MaxSpreadPerTrade(max_spread_pips=-1.0)._max_spread == 2.5
    assert MaxSpreadPerTrade(max_spread_pips=0.0)._max_spread == 2.5
    assert MaxSpreadPerTrade(max_spread_pips=float("nan"))._max_spread == 2.5
    assert MaxSpreadPerTrade(max_spread_pips=float("inf"))._max_spread == 2.5
    assert MaxSpreadPerTrade(max_spread_pips="invalid")._max_spread == 2.5


def test_wave54_update_valid_and_rejection_of_invalid():
    """Verify update() ingests valid spread floats and safely rejects non-finite/negative/invalid types."""
    guard = MaxSpreadPerTrade(max_spread_pips=2.5)

    # Valid spread update
    guard.update(1.8)
    assert guard.get_spread() == 1.8
    assert guard._update_count == 1
    assert guard._last_update > 0

    # Subsequent valid update
    guard.update(2.1)
    assert guard.get_spread() == 2.1
    assert guard._update_count == 2

    # Reject None, booleans, negative numbers, non-finite floats, strings
    guard.update(None)
    guard.update(True)
    guard.update(False)
    guard.update(-0.5)
    guard.update(float("nan"))
    guard.update(float("inf"))
    guard.update("not_a_number")

    # Spread and counter remain unchanged
    assert guard.get_spread() == 2.1
    assert guard._update_count == 2


def test_wave54_is_entry_blocked_and_is_trading_allowed():
    """Verify entry blocking gating, allow/block counters, and is_trading_allowed responses."""
    guard = MaxSpreadPerTrade(max_spread_pips=2.5)

    # Initially zero spread -> fail open before first tick
    assert guard.is_entry_blocked() is False
    assert guard.is_blocked() is False
    allowed, reason = guard.is_trading_allowed()
    assert allowed is True
    assert reason == ""

    # Normal acceptable spread (1.4 pips <= 2.5 pips)
    guard.update(1.4)
    assert guard.is_entry_blocked() is False
    assert guard._allow_count == 1
    assert guard._block_count == 0
    allowed, reason = guard.is_trading_allowed()
    assert allowed is True
    assert reason == ""

    # Excessive spread (3.1 pips > 2.5 pips) -> blocked!
    guard.update(3.1)
    assert guard.is_entry_blocked() is True
    assert guard._block_count == 1
    allowed, reason = guard.is_trading_allowed()
    assert allowed is False
    assert "SPREAD_TOO_HIGH" in reason
    assert "3.10p > 2.50p limit" in reason


def test_wave54_candidate_spread_override_and_fail_closed():
    """Verify direct candidate spread argument override and fail-closed behavior on invalid candidates."""
    guard = MaxSpreadPerTrade(max_spread_pips=2.0)
    guard.update(1.0)  # Current internal spread is low (1.0)

    # Override with acceptable candidate spread
    assert guard.is_entry_blocked(spread_pips=1.5) is False
    allowed, reason = guard.is_trading_allowed(spread_pips=1.5)
    assert allowed is True

    # Override with excessive candidate spread
    assert guard.is_entry_blocked(spread_pips=2.8) is True
    allowed, reason = guard.is_trading_allowed(spread_pips=2.8)
    assert allowed is False
    assert "2.80p > 2.00p limit" in reason

    # Invalid candidate spreads fail closed
    assert guard.is_entry_blocked(spread_pips=0.0) is True
    assert guard.is_entry_blocked(spread_pips=-1.2) is True
    assert guard.is_entry_blocked(spread_pips=float("nan")) is True
    assert guard.is_entry_blocked(spread_pips="corrupt") is True


def test_wave54_reset_and_info_telemetry():
    """Verify reset() clears all counters and info() provides serializable diagnostic telemetry."""
    guard = MaxSpreadPerTrade(max_spread_pips=2.5)
    guard.update(3.5)
    guard.is_entry_blocked()

    info = guard.info()
    assert info["wave"] == 54
    assert info["name"] == "MaxSpreadPerTrade"
    assert info["max_spread_pips"] == 2.5
    assert info["current_spread_pips"] == 3.5
    assert info["is_blocked"] is True
    assert info["block_count"] == 1
    assert info["update_count"] == 1
    assert info["data_staleness_sec"] is not None

    guard.reset()
    info_reset = guard.info()
    assert info_reset["current_spread_pips"] == 0.0
    assert info_reset["is_blocked"] is False
    assert info_reset["block_count"] == 0
    assert info_reset["allow_count"] == 0
    assert info_reset["update_count"] == 0
    assert info_reset["data_staleness_sec"] is None


def test_wave55_initialization_defaults_aliases_and_clamping():
    """Verify BalanceFloorGuard initializes with defaults, aliases, and property getters."""
    # Defaults: floor=$9,500, hysteresis=$50
    guard = BalanceFloorGuard()
    assert guard.floor_usd == 9500.0
    assert guard.min_balance == 9500.0
    assert guard.current_balance == 0.0
    assert guard.is_halted is False

    # Custom aliases
    guard_alias1 = BalanceFloorGuard(min_balance=9000.0, hysteresis_usd=75.0)
    assert guard_alias1.floor_usd == 9000.0
    assert guard_alias1._hysteresis == 75.0

    guard_alias2 = BalanceFloorGuard(min_balance_usd=8800.0)
    assert guard_alias2.floor_usd == 8800.0

    # Non-finite fallbacks
    guard_bad = BalanceFloorGuard(floor_usd=float("nan"), hysteresis_usd=-10.0)
    assert guard_bad.floor_usd == 9500.0
    assert guard_bad._hysteresis == 50.0


def test_wave55_catastrophic_blowout_halt():
    """Verify catastrophic halt triggered immediately when balance drops to zero or below."""
    guard = BalanceFloorGuard(floor_usd=9500.0)
    now_dt = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)

    # Catastrophic zero balance
    guard.update(0.0, now_dt=now_dt)
    assert guard.is_halted is True
    assert guard._halt_count == 1
    assert guard.is_entry_blocked(now_dt=now_dt) is True
    allowed, reason = guard.is_trading_allowed(now_dt=now_dt)
    assert allowed is False
    assert "BALANCE_FLOOR: balance $0.00 < floor $9500.00" in reason

    # Negative balance
    guard.reset()
    guard.update(-250.0, now_dt=now_dt)
    assert guard.is_halted is True
    assert guard.is_entry_blocked(now_dt=now_dt) is True


def test_wave55_floor_breach_halt_and_hysteresis_recovery():
    """Verify normal floor breach halts trading and intraday recovery requires floor + hysteresis."""
    guard = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)
    now_dt = datetime(2026, 10, 18, 14, 0, 0, tzinfo=timezone.utc)

    # Healthy balance: $10,000 -> clear
    guard.update(10000.0, now_dt=now_dt)
    assert guard.is_halted is False
    assert guard.is_entry_blocked(now_dt=now_dt) is False

    # Breach floor: $9,450 < $9,500 -> HALT!
    guard.update(9450.0, now_dt=now_dt)
    assert guard.is_halted is True
    assert guard._halt_balance == 9450.0
    assert guard._halt_count == 1
    assert guard.is_entry_blocked(now_dt=now_dt) is True

    # Partial bounce to $9,520: Above floor ($9,500) but below floor + hysteresis ($9,550) -> Still HALTED
    guard.update(9520.0, now_dt=now_dt)
    assert guard.is_halted is True
    assert guard.is_entry_blocked(now_dt=now_dt) is True

    # Complete recovery to $9,555: >= $9,500 + $50 = $9,550 -> Halt LIFTED!
    guard.update(9555.0, now_dt=now_dt)
    assert guard.is_halted is False
    assert guard.is_entry_blocked(now_dt=now_dt) is False
    allowed, reason = guard.is_trading_allowed(now_dt=now_dt)
    assert allowed is True
    assert reason == ""


def test_wave55_utc_midnight_auto_unlock():
    """Verify trading halt automatically unlocks upon rollover to a new UTC day if balance is >= floor."""
    guard = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)
    dt_day1 = datetime(2026, 10, 18, 22, 30, 0, tzinfo=timezone.utc)
    dt_day2 = datetime(2026, 10, 19, 0, 15, 0, tzinfo=timezone.utc)

    # Halt on day 1 at $9,400
    guard.update(9400.0, now_dt=dt_day1)
    assert guard.is_halted is True
    assert guard._halt_day == "2026-10-18"

    # Day 2 arrives with balance at $9,510 (above floor, even though below floor + hysteresis)
    # The new UTC day auto-unblocks via update()
    guard.update(9510.0, now_dt=dt_day2)
    assert guard.is_halted is False
    assert guard.is_entry_blocked(now_dt=dt_day2) is False

    # Also test auto-unlock directly inside is_entry_blocked()
    guard._is_halted = True
    guard._halt_day = "2026-10-18"
    assert guard.is_entry_blocked(now_dt=dt_day2) is False
    assert guard.is_halted is False


def test_wave55_reset_info_and_thread_safety():
    """Verify reset() clearing, info() telemetry reporting, and thread-safe concurrent updates."""
    guard = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)
    dt = datetime(2026, 10, 18, 16, 0, 0, tzinfo=timezone.utc)
    guard.update(9300.0, now_dt=dt)

    info = guard.info()
    assert info["wave"] == 55
    assert info["name"] == "BalanceFloorGuard"
    assert info["floor_usd"] == 9500.0
    assert info["current_balance"] == 9300.0
    assert info["is_halted"] is True
    assert info["halt_count"] == 1
    assert info["halt_balance"] == 9300.0
    assert info["halt_day_utc"] == "2026-10-18"

    # Reset clears all state
    guard.reset()
    assert guard.is_halted is False
    assert guard.current_balance == 0.0
    assert guard._halt_count == 0

    # Thread safety verification
    threads = []
    for i in range(10):
        t = threading.Thread(target=lambda val=9600.0 + i: guard.update(val, now_dt=dt))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    assert guard._update_count == 10
    assert guard.current_balance >= 9600.0
    assert guard.is_halted is False
