"""
tests/test_batch90.py
Batch 90 Unit Tests: RSI Overbought/Oversold Filter (wave52) & Tick Reversal Guard (wave53).
Expands test baseline beyond 1,137+ passing tests to 1,147+ passing tests.
Verifies:
1. wave52: RSIOverboughtOversold initialization defaults, threshold validation, and parameter sanitization.
2. wave52: Warmup buffer requirement (period + 1 prices) and fail-open uninitialized trading state.
3. wave52: Overbought boundary detection (RSI > 75) blocking BUY signals while allowing SELL signals.
4. wave52: Oversold boundary detection (RSI < 25) blocking SELL signals while allowing BUY signals.
5. wave52: RSIOverboughtOversold reset() clearing and info() telemetry introspection.
6. wave53: TickReversalGuard initialization defaults, parameter bounds, and input sanitization.
7. wave53: Consecutive adverse falling ticks triggering BUY block and cooldown lockout.
8. wave53: Consecutive adverse rising ticks triggering SELL block and cooldown lockout.
9. wave53: Cooldown timer expiration, trend-aligned signal clearance, and mixed ticks immunity.
10. wave53: TickReversalGuard reset(), info() telemetry reporting, and non-finite input resilience.
"""

import math
import time
import pytest

from wave52_rsi_ob_os_filter import RSIOverboughtOversold
from wave53_tick_reversal_guard import TickReversalGuard


def test_wave52_initialization_defaults_and_validation():
    """Verify RSIOverboughtOversold initializes with defaults and sanitizes invalid parameters."""
    # Defaults: period=14, ob_block=75.0, os_block=25.0
    filter_rsi = RSIOverboughtOversold()
    assert filter_rsi._period == 14
    assert filter_rsi._ob_block == 75.0
    assert filter_rsi._os_block == 25.0
    assert filter_rsi.get_rsi() == 50.0
    assert filter_rsi.rsi == 50.0

    # Custom valid configuration
    custom = RSIOverboughtOversold(period=10, ob_block=80.0, os_block=20.0)
    assert custom._period == 10
    assert custom._ob_block == 80.0
    assert custom._os_block == 20.0

    # Invalid period (< 2 or invalid type) clamped to default
    assert RSIOverboughtOversold(period=1)._period == 14
    assert RSIOverboughtOversold(period=-5)._period == 14
    assert RSIOverboughtOversold(period="invalid")._period == 14

    # Invalid block thresholds (os >= ob, negative, non-finite) fall back to defaults
    bad_thresh = RSIOverboughtOversold(ob_block=30.0, os_block=70.0)
    assert bad_thresh._ob_block == 75.0
    assert bad_thresh._os_block == 25.0

    bad_nan = RSIOverboughtOversold(ob_block=float("nan"), os_block=float("nan"))
    assert bad_nan._ob_block == 75.0
    assert bad_nan._os_block == 25.0


def test_wave52_warmup_and_uninitialized_fail_open():
    """Verify filter permits signals during warmup before period + 1 prices are ingested."""
    filter_rsi = RSIOverboughtOversold(period=5)  # Needs 6 prices

    # Feed 4 prices (fewer than 6)
    for price in [100.0, 101.0, 102.0, 103.0]:
        filter_rsi.update(price)

    assert filter_rsi._initialized is False
    assert filter_rsi.get_rsi() == 50.0

    # Uninitialized state allows both BUY and SELL (fail-open)
    assert filter_rsi.is_signal_blocked("BUY") is False
    assert filter_rsi.is_signal_blocked("SELL") is False
    assert filter_rsi.is_entry_blocked("BUY") is False
    assert filter_rsi.is_blocked("SELL") is False


def test_wave52_rsi_overbought_blocks_buy():
    """Verify sustained upward momentum pushes RSI into overbought territory (> 75), blocking BUY."""
    filter_rsi = RSIOverboughtOversold(period=5, ob_block=75.0, os_block=25.0)

    # Feed steadily increasing prices to establish high RSI
    base = 100.0
    for i in range(12):
        filter_rsi.update(base + (i * 2.0))

    assert filter_rsi._initialized is True
    current_rsi = filter_rsi.get_rsi()
    assert current_rsi > 75.0

    # Overbought blocks BUY but permits SELL
    assert filter_rsi.is_signal_blocked("BUY") is True
    assert filter_rsi.is_signal_blocked("SELL") is False

    info = filter_rsi.info()
    assert info["status"] == "OVERBOUGHT"
    assert info["rsi"] == current_rsi


def test_wave52_rsi_oversold_blocks_sell():
    """Verify sustained downward momentum pushes RSI into oversold territory (< 25), blocking SELL."""
    filter_rsi = RSIOverboughtOversold(period=5, ob_block=75.0, os_block=25.0)

    # Feed steadily decreasing prices to establish low RSI
    base = 150.0
    for i in range(12):
        filter_rsi.update(base - (i * 2.0))

    assert filter_rsi._initialized is True
    current_rsi = filter_rsi.get_rsi()
    assert current_rsi < 25.0

    # Oversold blocks SELL but permits BUY
    assert filter_rsi.is_signal_blocked("SELL") is True
    assert filter_rsi.is_signal_blocked("BUY") is False

    info = filter_rsi.info()
    assert info["status"] == "OVERSOLD"
    assert info["rsi"] == current_rsi


def test_wave52_reset_and_info_introspection():
    """Verify reset() clears internal state and info() outputs diagnostic telemetry."""
    filter_rsi = RSIOverboughtOversold(period=5)
    for i in range(8):
        filter_rsi.update(100.0 + i)

    info = filter_rsi.info()
    assert info["wave"] == 52
    assert info["name"] == "RSIOverboughtOversold"
    assert info["period"] == 5
    assert info["initialized"] is True
    assert info["update_count"] == 8

    # Non-standard signal names return False (not blocked)
    assert filter_rsi.is_signal_blocked("HOLD") is False
    assert filter_rsi.is_signal_blocked("") is False
    assert filter_rsi.is_signal_blocked(None) is False

    filter_rsi.reset()
    info_reset = filter_rsi.info()
    assert info_reset["rsi"] == 50.0
    assert info_reset["initialized"] is False
    assert info_reset["update_count"] == 0
    assert info_reset["status"] == "NEUTRAL"


def test_wave53_initialization_defaults_and_clamping():
    """Verify TickReversalGuard initializes with defaults and clamps invalid constructor arguments."""
    guard = TickReversalGuard()
    assert guard._n == 5
    assert guard._block_duration == 30.0

    # Custom valid configuration
    custom = TickReversalGuard(n_ticks=7, block_duration=45.0)
    assert custom._n == 7
    assert custom._block_duration == 45.0

    # Clamping: minimum n_ticks is 2
    assert TickReversalGuard(n_ticks=1)._n == 2
    assert TickReversalGuard(n_ticks=-3)._n == 2
    assert TickReversalGuard(n_ticks="bad")._n == 5

    # Clamping negative duration to default
    assert TickReversalGuard(block_duration=-10.0)._block_duration == 30.0
    assert TickReversalGuard(block_duration=float("nan"))._block_duration == 30.0


def test_wave53_falling_ticks_block_buy_with_cooldown():
    """Verify consecutive falling ticks detect adverse momentum and block BUY entries."""
    guard = TickReversalGuard(n_ticks=3, block_duration=25.0)
    t0 = 1750000000.0

    # Feed 4 prices resulting in 3 consecutive down ticks: 100 -> 99 -> 98 -> 97
    prices = [100.0, 99.0, 98.0, 97.0]
    for p in prices:
        guard.update(p)

    assert guard._consecutive_direction() == "DOWN"

    # BUY is blocked because momentum is strongly falling
    assert guard.is_signal_blocked("BUY", now_ts=t0) is True
    assert guard._block_count == 1
    assert guard._block_until == t0 + 25.0
    assert guard._last_reversal_direction == "DOWN"

    # is_trading_allowed returns diagnostic message
    allowed, reason = guard.is_trading_allowed("BUY", now_ts=t0)
    assert allowed is False
    assert "TICK_REVERSAL: DOWN momentum contradicts BUY" in reason

    # SELL is not blocked (aligns with falling momentum)
    assert guard.is_signal_blocked("SELL", now_ts=t0) is False
    allowed, reason = guard.is_trading_allowed("SELL", now_ts=t0)
    assert allowed is True


def test_wave53_rising_ticks_block_sell_with_cooldown():
    """Verify consecutive rising ticks detect adverse momentum and block SELL entries."""
    guard = TickReversalGuard(n_ticks=3, block_duration=25.0)
    t0 = 1750000000.0

    # Feed 4 prices resulting in 3 consecutive up ticks: 100 -> 101 -> 102 -> 103
    prices = [100.0, 101.0, 102.0, 103.0]
    for p in prices:
        guard.update(p)

    assert guard._consecutive_direction() == "UP"

    # SELL is blocked because momentum is strongly rising
    assert guard.is_signal_blocked("SELL", now_ts=t0) is True
    assert guard._block_count == 1
    assert guard._block_until == t0 + 25.0
    assert guard._last_reversal_direction == "UP"

    # is_trading_allowed returns diagnostic message
    allowed, reason = guard.is_trading_allowed("SELL", now_ts=t0)
    assert allowed is False
    assert "TICK_REVERSAL: UP momentum contradicts SELL" in reason

    # BUY is not blocked (aligns with rising momentum)
    assert guard.is_signal_blocked("BUY", now_ts=t0) is False
    allowed, reason = guard.is_trading_allowed("BUY", now_ts=t0)
    assert allowed is True


def test_wave53_cooldown_expiration_and_mixed_ticks():
    """Verify cooldown timer persists blocks and expires properly, and mixed ticks do not block."""
    guard = TickReversalGuard(n_ticks=3, block_duration=30.0)
    t0 = 1750000000.0

    for p in [100.0, 99.0, 98.0, 97.0]:
        guard.update(p)

    # Initial block triggered at t0
    assert guard.is_signal_blocked("BUY", now_ts=t0) is True

    # 15 seconds in (halfway through 30s cooldown): still blocked
    assert guard.is_signal_blocked("BUY", now_ts=t0 + 15.0) is True

    # 31 seconds in (cooldown expired): unblocked
    assert guard.is_signal_blocked("BUY", now_ts=t0 + 31.0) is False

    # Mixed ticks do not trigger a reversal block
    guard.reset()
    for p in [100.0, 101.0, 99.5, 102.0]:  # Up, Down, Up
        guard.update(p)

    assert guard._consecutive_direction() == "MIXED"
    assert guard.is_signal_blocked("BUY", now_ts=t0 + 50.0) is False
    assert guard.is_signal_blocked("SELL", now_ts=t0 + 50.0) is False


def test_wave53_reset_info_and_invalid_inputs():
    """Verify update() ignores corrupt inputs, reset() flushes state, and info() provides status."""
    guard = TickReversalGuard(n_ticks=3, block_duration=30.0)
    t0 = 1750000000.0

    # Feeding invalid inputs does not increment update_count
    guard.update(None)
    guard.update(True)
    guard.update(False)
    guard.update(-10.0)
    guard.update(0.0)
    guard.update(float("nan"))
    guard.update(float("inf"))
    assert guard._update_count == 0

    # Feed valid ticks and trigger block
    for p in [50.0, 51.0, 52.0, 53.0]:
        guard.update(p)

    guard.is_signal_blocked("SELL", now_ts=t0)

    info = guard.info(now_ts=t0)
    assert info["wave"] == 53
    assert info["name"] == "TickReversalGuard"
    assert info["n_ticks_threshold"] == 3
    assert info["block_duration_sec"] == 30.0
    assert info["is_blocked"] is True
    assert info["cooldown_remaining_sec"] == 30.0
    assert info["last_reversal_direction"] == "UP"
    assert info["block_count"] == 1
    assert info["update_count"] == 4
    assert info["prices_in_buffer"] == 4

    # Reset flushes state
    guard.reset()
    info_reset = guard.info(now_ts=t0)
    assert info_reset["is_blocked"] is False
    assert info_reset["cooldown_remaining_sec"] == 0.0
    assert info_reset["last_reversal_direction"] == ""
    assert info_reset["block_count"] == 0
    assert info_reset["update_count"] == 0
    assert info_reset["prices_in_buffer"] == 0
