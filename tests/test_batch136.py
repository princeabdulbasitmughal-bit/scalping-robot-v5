"""
Test Suite for Batch 136:
- wave38_volatility_breaker.py (VolatilityBreaker: short vs long ATR spike ratio lockout)
- wave39_drawdown_pause.py (DrawdownPause: rolling 30-min peak equity drawdown pause)
Historic 1,600+ tests milestone suite!
"""

import math
import time
import pytest

from wave38_volatility_breaker import (
    VolatilityBreaker,
    volatility_breaker,
    is_entry_blocked as w38_is_entry_blocked,
    is_blocked as w38_is_blocked,
    update as w38_update,
    reset as w38_reset,
)
from wave39_drawdown_pause import (
    DrawdownPause,
    drawdown_pause,
    is_entry_blocked as w39_is_entry_blocked,
    is_blocked as w39_is_blocked,
    update as w39_update,
    reset as w39_reset,
)


# ---------------------------------------------------------------------
# Wave 38: Volatility Breaker Tests
# ---------------------------------------------------------------------

def test_wave38_initial_state():
    vb = VolatilityBreaker()
    assert not vb.is_entry_blocked()
    assert not vb.is_blocked()
    assert vb.seconds_remaining() == 0.0
    info = vb.info()
    assert not info["currently_blocked"]
    assert info["current_atr"] == 0.0
    assert info["baseline_atr"] == 0.0
    assert info["total_spikes"] == 0
    assert info["total_blocks"] == 0


def test_wave38_invalid_prices():
    vb = VolatilityBreaker()
    t0 = 1000.0
    invalid_inputs = [None, True, False, "123.4", -50.0, 0.0, float("nan"), float("inf")]
    for val in invalid_inputs:
        vb.update(val, now_ts=t0)
    
    assert vb._tick_count == 0
    assert len(vb._short_prices) == 0
    assert not vb.is_entry_blocked(now_ts=t0)


def test_wave38_normal_volatility_no_block():
    vb = VolatilityBreaker()
    t0 = 1000.0
    price = 2000.0
    # Feed 40 ticks with consistent small 0.1 movements
    for i in range(40):
        price += 0.1 if i % 2 == 0 else -0.1
        vb.update(price, now_ts=t0 + i)

    assert not vb.is_entry_blocked(now_ts=t0 + 40)
    assert not vb.is_blocked(now_ts=t0 + 40)
    info = vb.info(now_ts=t0 + 40)
    assert not info["currently_blocked"]
    assert info["total_spikes"] == 0


def test_wave38_spike_triggers_block():
    vb = VolatilityBreaker()
    t0 = 1000.0
    price = 2000.0
    # Baseline: 100 ticks with small volatility (0.05 step)
    for i in range(100):
        price += 0.05 if i % 2 == 0 else -0.05
        vb.update(price, now_ts=t0 + i)

    # Spike: 25 ticks with massive volatility (2.0 step, 40x baseline)
    for i in range(100, 125):
        price += 2.0 if i % 2 == 0 else -2.0
        vb.update(price, now_ts=t0 + i)

    current_t = t0 + 124
    assert vb.is_entry_blocked(now_ts=current_t)
    assert vb.is_blocked(now_ts=current_t)
    assert vb.seconds_remaining(now_ts=current_t) > 0.0
    assert vb.total_spikes >= 1
    assert vb.total_blocks >= 1

    info = vb.info(now_ts=current_t)
    assert info["currently_blocked"]
    assert info["last_ratio"] >= vb.SPIKE_RATIO


def test_wave38_cooldown_expiry_and_reset():
    vb = VolatilityBreaker()
    t0 = 1000.0
    price = 2000.0
    for i in range(100):
        price += 0.05 if i % 2 == 0 else -0.05
        vb.update(price, now_ts=t0 + i)
    for i in range(100, 125):
        price += 2.0 if i % 2 == 0 else -2.0
        vb.update(price, now_ts=t0 + i)

    current_t = t0 + 124
    assert vb.is_entry_blocked(now_ts=current_t)

    # After 91 seconds, cooldown should expire
    future_t = current_t + 91.0
    assert not vb.is_entry_blocked(now_ts=future_t)
    assert vb.seconds_remaining(now_ts=future_t) == 0.0

    # Reset clears everything
    vb.reset()
    assert not vb.is_entry_blocked(now_ts=current_t)
    assert vb.total_spikes == 0
    assert vb._tick_count == 0

    # Test module-level singleton helpers
    w38_reset()
    assert not w38_is_entry_blocked()
    assert not w38_is_blocked()
    w38_update(2000.0)
    w38_reset()


# ---------------------------------------------------------------------
# Wave 39: Drawdown Pause Tests
# ---------------------------------------------------------------------

def test_wave39_initial_state():
    dp = DrawdownPause()
    assert not dp.is_entry_blocked()
    assert not dp.is_blocked()
    assert dp.seconds_remaining() == 0.0
    info = dp.info()
    assert not info["blocked"]
    assert info["peak_equity"] == 0.0
    assert info["current_equity"] == 0.0
    assert info["drawdown_pct"] == 0.0


def test_wave39_invalid_equity():
    dp = DrawdownPause()
    t0 = 1000.0
    invalid_inputs = [None, True, False, "10000", -100.0, 0.0, float("nan"), float("inf")]
    for val in invalid_inputs:
        dp.update(val, now_ts=t0)
        dp.is_entry_blocked(balance=val, now_ts=t0)

    assert len(dp._equity_history) == 0
    assert not dp.is_entry_blocked(now_ts=t0)


def test_wave39_drawdown_trigger():
    dp = DrawdownPause()
    t0 = 1000.0
    # Peak equity: 10,000.0
    dp.update(10000.0, now_ts=t0)
    # Small fluctuation: 9,900.0 (1.0% drawdown, < 1.5% threshold)
    dp.update(9900.0, now_ts=t0 + 60)
    assert not dp.is_entry_blocked(now_ts=t0 + 60)

    # Significant drop: 9,800.0 (2.0% drawdown, >= 1.5% threshold)
    blocked = dp.is_entry_blocked(balance=9800.0, now_ts=t0 + 120)
    assert blocked
    assert dp.is_blocked(now_ts=t0 + 120)
    assert dp.seconds_remaining(now_ts=t0 + 120) == dp.PAUSE_SEC
    assert "drawdown=2.00%" in dp._last_trigger_reason

    info = dp.info(now_ts=t0 + 120)
    assert info["blocked"]
    assert info["drawdown_pct"] == 2.0
    assert info["peak_equity"] == 10000.0
    assert info["current_equity"] == 9800.0


def test_wave39_window_pruning_and_expiry():
    dp = DrawdownPause()
    t0 = 1000.0
    # Peak equity at t0: 10,000.0
    dp.update(10000.0, now_ts=t0)
    # 2.0% drop at t0 + 100 triggers 900s pause (until t0 + 1000)
    assert dp.is_entry_blocked(balance=9800.0, now_ts=t0 + 100)
    assert dp.is_entry_blocked(now_ts=t0 + 500)

    # At t0 + 1001, the pause period (900s) has expired
    t_after_pause = t0 + 1001
    # But peak 10000 is still in the 1800s (30m) window, so checking new balance triggers again if still down
    # However, if equity has recovered to 9,900 (1.0% dd < 1.5%), it should not re-trigger
    dp.update(9900.0, now_ts=t_after_pause)
    assert not dp.is_entry_blocked(now_ts=t_after_pause)

    # Now simulate passing beyond 1800s window (e.g. t0 + 1850)
    # The old 10000 peak gets pruned, so only recent values remain
    dp.update(9700.0, now_ts=t0 + 1850)
    # Current history will have pruned t0 (10000). Peak among [9900, 9700] is 9900.
    # 9700 vs 9900 is 2.02% drawdown -> triggers pause again
    assert dp.is_entry_blocked(now_ts=t0 + 1850)


def test_wave39_reset_and_module_aliases():
    dp = DrawdownPause()
    t0 = 1000.0
    dp.update(10000.0, now_ts=t0)
    dp.update(9800.0, now_ts=t0 + 50)
    assert dp.is_entry_blocked(now_ts=t0 + 50)

    dp.reset()
    assert not dp.is_entry_blocked(now_ts=t0 + 50)
    assert len(dp._equity_history) == 0

    # Module-level aliases
    w39_reset()
    assert not w39_is_entry_blocked()
    assert not w39_is_blocked()
    w39_update(5000.0, now_ts=t0)
    assert not w39_is_entry_blocked(now_ts=t0)
    w39_reset()
