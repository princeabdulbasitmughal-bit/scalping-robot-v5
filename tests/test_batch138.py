"""
Test Suite for Batch 138:
- wave42_tick_volume_filter.py (TickVolumeFilter: dead market guard & volume surge breaker)
- wave43_win_rate_guard.py (WinRateGuard: rolling 10-trade win rate drawdown pause)
Zero regressions, continuing toward 1,627+ passed tests.
"""

import time
import pytest

from wave42_tick_volume_filter import (
    TickVolumeFilter,
    tick_volume_filter,
    is_entry_blocked as w42_is_entry_blocked,
    is_blocked as w42_is_blocked,
    update as w42_update,
    reset as w42_reset,
)
from wave43_win_rate_guard import (
    WinRateGuard,
    win_rate_guard,
    is_entry_blocked as w43_is_entry_blocked,
    is_blocked as w43_is_blocked,
    record_trade as w43_record_trade,
    reset as w43_reset,
)


# ---------------------------------------------------------------------
# Wave 42: Tick Volume Filter Tests
# ---------------------------------------------------------------------

def test_wave42_initial_state():
    tvf = TickVolumeFilter()
    t0 = 1000.0
    # No ticks arrived yet -> dead market
    assert tvf.is_entry_blocked(now_ts=t0)
    assert tvf.is_blocked(now_ts=t0)
    assert "DEAD_MARKET" in tvf.get_block_reason()
    info = tvf.info(now_ts=t0)
    assert info["is_dead_market"]
    assert info["blocked"]
    assert info["ticks_in_window"] == 0


def test_wave42_normal_tick_flow():
    tvf = TickVolumeFilter()
    t0 = 1000.0
    # 10 ticks evenly spaced in 10s window (1 tick/sec >= 4 min_ticks and < 50 max_ticks)
    for i in range(10):
        tvf.update(now_ts=t0 + i)

    current_t = t0 + 9.5
    assert not tvf.is_entry_blocked(now_ts=current_t)
    assert not tvf.is_blocked(now_ts=current_t)
    assert tvf.get_block_reason() == ""
    info = tvf.info(now_ts=current_t)
    assert not info["blocked"]
    assert not info["is_dead_market"]
    assert not info["is_volume_spike"]
    assert info["ticks_in_window"] == 10


def test_wave42_dead_market_block():
    tvf = TickVolumeFilter(min_ticks=4, window_sec=10.0)
    t0 = 1000.0
    # Feed only 2 ticks in 10s (< 4)
    tvf.update(now_ts=t0 + 1.0)
    tvf.update(now_ts=t0 + 5.0)

    current_t = t0 + 9.0
    assert tvf.is_entry_blocked(now_ts=current_t)
    assert "DEAD_MARKET" in tvf.get_block_reason()
    info = tvf.info(now_ts=current_t)
    assert info["is_dead_market"]
    assert info["ticks_in_window"] == 2


def test_wave42_volume_spike_ceiling():
    tvf = TickVolumeFilter(max_ticks=50, window_sec=10.0, spike_cooldown_sec=30.0)
    t0 = 1000.0
    # Feed 55 ticks in 10s
    for i in range(55):
        tvf.update(now_ts=t0 + (i * 0.1))

    current_t = t0 + 8.0
    assert tvf.is_entry_blocked(now_ts=current_t)
    assert "VOLUME_SPIKE" in tvf.get_block_reason()
    info = tvf.info(now_ts=current_t)
    assert info["is_volume_spike"]
    assert info["spike_cooldown_remaining_sec"] > 0.0


def test_wave42_cooldown_expiry_and_module_aliases():
    tvf = TickVolumeFilter(max_ticks=50, window_sec=10.0, spike_cooldown_sec=30.0)
    t0 = 1000.0
    for i in range(55):
        tvf.update(now_ts=t0 + (i * 0.1))

    current_t = t0 + 8.0
    assert tvf.is_entry_blocked(now_ts=current_t)

    # Cooldown expires after 31s
    t_after_cooldown = current_t + 31.0
    # Also feed healthy ticks at the new time so it doesn't fail on dead-market
    for i in range(6):
        tvf.update(now_ts=t_after_cooldown - i)

    assert not tvf.is_entry_blocked(now_ts=t_after_cooldown)

    tvf.reset()
    assert tvf.info(now_ts=t0)["ticks_in_window"] == 0

    # Module-level aliases
    w42_reset()
    assert w42_is_entry_blocked(now_ts=t0)
    assert w42_is_blocked(now_ts=t0)
    w42_update(now_ts=t0)
    w42_reset()


# ---------------------------------------------------------------------
# Wave 43: Win Rate Guard Tests
# ---------------------------------------------------------------------

def test_wave43_initial_state():
    wrg = WinRateGuard()
    assert not wrg.is_entry_blocked()
    assert not wrg.is_blocked()
    assert wrg.seconds_remaining() == 0.0
    info = wrg.info()
    assert not info["paused"]
    assert info["sample_size"] == 0
    assert not info["sufficient_sample"]
    assert info["win_rate_pct"] == 100.0


def test_wave43_insufficient_sample_no_block():
    wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.30)
    t0 = 1000.0
    # Record 4 consecutive losses (< min_trades=5)
    for i in range(4):
        wrg.record_trade(won=False, now_ts=t0 + i)

    assert not wrg.is_entry_blocked(now_ts=t0 + 4)
    info = wrg.info(now_ts=t0 + 4)
    assert not info["paused"]
    assert info["sample_size"] == 4
    assert not info["sufficient_sample"]


def test_wave43_low_win_rate_triggers_pause():
    wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.30, pause_duration_sec=1200.0)
    t0 = 1000.0
    # Record 5 consecutive losses (0% win rate < 30%)
    for i in range(5):
        wrg.record_trade(won=False, now_ts=t0 + i)

    current_t = t0 + 4.0
    assert wrg.is_entry_blocked(now_ts=current_t)
    assert wrg.is_blocked(now_ts=current_t)
    assert wrg.seconds_remaining(now_ts=current_t) == 1200.0

    info = wrg.info(now_ts=current_t)
    assert info["paused"]
    assert info["win_rate_pct"] == 0.0
    assert info["sufficient_sample"]
    assert info["pause_remaining_sec"] == 1200.0


def test_wave43_pause_expiry_resets_streak():
    wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.30, pause_duration_sec=1200.0)
    t0 = 1000.0
    for i in range(5):
        wrg.record_trade(won=False, now_ts=t0 + i)

    current_t = t0 + 5.0
    assert wrg.is_entry_blocked(now_ts=current_t)

    # 1201s later, pause has expired
    t_after_pause = current_t + 1201.0
    assert not wrg.is_entry_blocked(now_ts=t_after_pause)
    assert wrg.seconds_remaining(now_ts=t_after_pause) == 0.0

    # Old streak was cleared upon pause expiry
    info = wrg.info(now_ts=t_after_pause)
    assert not info["paused"]
    assert info["sample_size"] == 0


def test_wave43_reset_and_module_aliases():
    wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.30)
    t0 = 1000.0
    for i in range(5):
        wrg.record_trade(won=False, now_ts=t0 + i)
    assert wrg.is_entry_blocked(now_ts=t0 + 5)

    wrg.reset()
    assert not wrg.is_entry_blocked(now_ts=t0 + 5)
    assert wrg.info()["sample_size"] == 0

    # Module-level aliases
    w43_reset()
    assert not w43_is_entry_blocked()
    assert not w43_is_blocked()
    w43_record_trade(won=True)
    w43_reset()
