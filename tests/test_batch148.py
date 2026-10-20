"""
Unit tests for Batch 148:
- wave62_vwap_filter.py (VWAP Deviation Filter)
- wave63_spread_spike_guard.py (Tick Spread Spike Guard)
"""

import math
import time
import pytest

from wave62_vwap_filter import (
    VWAPFilter,
    vwap_filter,
    update as w62_update,
    get_vwap,
    is_signal_blocked as w62_signal_blocked,
    is_entry_blocked as w62_is_entry_blocked,
    is_blocked as w62_is_blocked,
    reset as w62_reset,
    info as w62_info,
)

from wave63_spread_spike_guard import (
    SpreadSpikeGuard,
    spread_spike_guard,
    update as w63_update,
    is_entry_blocked as w63_is_entry_blocked,
    is_blocked as w63_is_blocked,
    seconds_remaining,
    reset as w63_reset,
    info as w63_info,
)


# ======================================================================
# Wave 62: VWAP Filter Tests
# ======================================================================

def test_wave62_initial_state():
    """Verify default initialization and initial properties."""
    f = VWAPFilter()
    assert f._window == 50
    assert f._min_ticks == 20
    assert f._threshold_pips == 10.0
    assert f.get_vwap() == 0.0
    inf = f.info()
    assert inf["wave"] == 62
    assert inf["tick_count"] == 0
    assert inf["total_blocks"] == 0


def test_wave62_invalid_constructor_and_inputs():
    """Verify constructor fallbacks and bad update inputs are rejected."""
    f_bad = VWAPFilter(window="bad", min_ticks="bad", threshold_pips="bad")
    assert f_bad._window == 50
    assert f_bad._min_ticks == 20
    assert f_bad._threshold_pips == 10.0

    f_clamp = VWAPFilter(window=1, min_ticks=0, threshold_pips=-5.0)
    assert f_clamp._window == 2
    assert f_clamp._min_ticks == 1
    assert f_clamp._threshold_pips == 0.1  # clamped to 0.1

    f = VWAPFilter()
    # Bad prices ignored
    f.update(None)
    f.update(True)
    f.update(False)
    f.update(-100.0)
    f.update(0.0)
    f.update(float("nan"))
    f.update(float("inf"))
    f.update("not_a_price")
    assert f.info()["tick_count"] == 0
    assert f.get_vwap() == 0.0


def test_wave62_warmup_no_block():
    """Verify no blocking during warmup (fewer than min_ticks)."""
    f = VWAPFilter(window=50, min_ticks=20, threshold_pips=5.0)
    # Feed only 10 ticks (below min_ticks=20)
    for _ in range(10):
        f.update(2650.0)
    # No blocking during warmup regardless of price
    assert not f.is_signal_blocked("BUY", price=2700.0)
    assert not f.is_signal_blocked("SELL", price=2600.0)
    assert not f.is_entry_blocked("BUY", price=2700.0)


def test_wave62_vwap_computation():
    """Verify VWAP equals mean of last N prices (uniform weight)."""
    f = VWAPFilter(window=5, min_ticks=3, threshold_pips=100.0)
    prices = [2640.0, 2650.0, 2660.0, 2670.0, 2680.0]
    for p in prices:
        f.update(p)
    expected_vwap = sum(prices) / len(prices)  # 2660.0
    assert abs(f.get_vwap() - expected_vwap) < 0.01


def test_wave62_block_overextended_buy_and_sell():
    """Verify BUY blocked above VWAP+threshold, SELL blocked below VWAP-threshold."""
    f = VWAPFilter(window=20, min_ticks=5, threshold_pips=10.0)
    # Seed VWAP at ~2650.0
    for _ in range(20):
        f.update(2650.0)
    vwap = f.get_vwap()
    assert abs(vwap - 2650.0) < 0.1

    # BUY blocked: price is 15 pips above VWAP (15 > threshold=10)
    overextended_buy = vwap + 15 * 0.1  # 2651.5
    assert f.is_signal_blocked("BUY", price=overextended_buy)
    assert f.is_entry_blocked("BUY", price=overextended_buy)

    # SELL blocked: price is 15 pips below VWAP
    overextended_sell = vwap - 15 * 0.1  # 2648.5
    assert f.is_signal_blocked("SELL", price=overextended_sell)

    # BUY allowed: price is only 5 pips above VWAP (5 < threshold=10)
    normal_buy = vwap + 5 * 0.1  # 2650.5
    assert not f.is_signal_blocked("BUY", price=normal_buy)

    # SELL allowed: price is only 5 pips below VWAP
    normal_sell = vwap - 5 * 0.1  # 2649.5
    assert not f.is_signal_blocked("SELL", price=normal_sell)

    # Non-directional signal never blocked
    assert not f.is_signal_blocked("HOLD", price=2700.0)
    assert not f.is_signal_blocked(None, price=2600.0)


def test_wave62_module_aliases_and_reset():
    """Verify module-level singleton, aliases, and reset."""
    w62_reset()
    assert get_vwap() == 0.0
    assert not w62_signal_blocked("BUY")
    assert not w62_is_entry_blocked("SELL")
    assert not w62_is_blocked("BUY")

    # Feed prices to the singleton
    for p in [2650.0] * 25:
        w62_update(p)

    inf = w62_info()
    assert inf["wave"] == 62
    assert inf["tick_count"] == 25
    assert abs(get_vwap() - 2650.0) < 0.01

    w62_reset()
    assert w62_info()["tick_count"] == 0


# ======================================================================
# Wave 63: Spread Spike Guard Tests
# ======================================================================

def test_wave63_initial_state():
    """Verify default initialization and initial state."""
    g = SpreadSpikeGuard()
    assert g._spike_ratio == 3.0
    assert g._cooldown_seconds == 45.0
    assert g._min_ticks == 10
    assert not g.is_entry_blocked()
    assert g.seconds_remaining() == 0.0
    inf = g.info()
    assert inf["wave"] == 63
    assert inf["spike_active"] is False
    assert inf["total_spikes"] == 0


def test_wave63_invalid_constructor_and_bad_spreads():
    """Verify constructor fallbacks and invalid spread handling."""
    g_bad = SpreadSpikeGuard(spike_ratio="bad", cooldown_seconds="bad", min_ticks="bad")
    assert g_bad._spike_ratio == 3.0
    assert g_bad._cooldown_seconds == 45.0
    assert g_bad._min_ticks == 10

    g_clamp = SpreadSpikeGuard(spike_ratio=1.0, cooldown_seconds=0.5)
    assert g_clamp._spike_ratio == 1.1   # clamped min 1.1
    assert g_clamp._cooldown_seconds == 1.0  # clamped min 1.0

    # Invalid spreads trigger fail-closed lock
    g = SpreadSpikeGuard(cooldown_seconds=1.0)
    now_ts = time.monotonic()
    g.update(None, now=now_ts)
    assert g.is_entry_blocked(now=now_ts)  # locked by invalid spread
    assert g.info()["total_spikes"] == 1

    # After cooldown expires, unlocks
    g2 = SpreadSpikeGuard(cooldown_seconds=1.0)
    g2.update(-1.0, now=0.0)   # invalid spread at t=0 -> deadline=1.0
    assert g2.is_entry_blocked(now=0.5)   # still within cooldown
    assert not g2.is_entry_blocked(now=1.5)  # past deadline -> unlocked


def test_wave63_normal_spread_no_block():
    """Verify stable spreads build baseline without triggering spike."""
    g = SpreadSpikeGuard(spike_ratio=3.0, cooldown_seconds=45.0, min_ticks=5)
    now_ts = time.monotonic()
    # Feed 15 normal ticks at 1.5 pips
    for i in range(15):
        g.update(1.5, now=now_ts + i)
    assert not g.is_entry_blocked(now=now_ts + 15)
    assert g.info()["total_spikes"] == 0
    assert g.info()["ema_spread_pips"] > 0


def test_wave63_spike_triggers_cooldown():
    """Verify spread spike (>=3x baseline) locks entries for cooldown period."""
    g = SpreadSpikeGuard(spike_ratio=3.0, cooldown_seconds=30.0, min_ticks=5)
    now_ts = 1000.0
    # Build baseline: 10 ticks at 1.0 pip
    for i in range(10):
        g.update(1.0, now=now_ts + i)

    assert not g.is_entry_blocked(now=now_ts + 10)

    # Fire a spike: 4.0 pips = 4x baseline (>= 3x threshold)
    g.update(4.0, now=now_ts + 11)
    assert g.is_entry_blocked(now=now_ts + 12)
    assert g.info()["total_spikes"] >= 1
    assert g.seconds_remaining(now=now_ts + 12) > 0.0

    # During cooldown still blocked
    assert g.is_entry_blocked(now=now_ts + 30)

    # After cooldown (30s from spike at t=11 -> deadline=41), should unlock
    assert not g.is_entry_blocked(now=now_ts + 42)
    assert g.seconds_remaining(now=now_ts + 42) == 0.0


def test_wave63_module_aliases_and_reset():
    """Verify module-level singleton aliases and reset()."""
    w63_reset()
    assert not w63_is_entry_blocked()
    assert not w63_is_blocked()
    assert seconds_remaining() == 0.0

    inf = w63_info()
    assert inf["wave"] == 63
    assert inf["spike_active"] is False

    # Feed a spike via module alias
    now_ts = time.monotonic()
    # Build baseline
    for _ in range(10):
        w63_update(1.0, now=now_ts)
    # Spike
    w63_update(5.0, now=now_ts + 1)
    assert w63_is_entry_blocked(now=now_ts + 2)
    assert w63_is_blocked(now=now_ts + 2)
    assert seconds_remaining(now=now_ts + 2) > 0.0

    w63_reset()
    assert not w63_is_entry_blocked()
    assert w63_info()["total_spikes"] == 0
