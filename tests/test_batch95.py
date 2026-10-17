"""
tests/test_batch95.py
Batch 95 Unit Tests: Tick Volume Filter (wave42) & Win Rate Guard (wave43).
Expands test baseline beyond 1,187+ passing tests to 1,197+ passing tests.
Verifies:
1. wave42: TickVolumeFilter initialization defaults, window seconds, and parameter bounds sanitization.
2. wave42: Dead market detection (< min_ticks in rolling window) blocking entry with diagnostic explanation.
3. wave42: Healthy normal tick arrival rate (min_ticks <= count < max_ticks) allowing entry.
4. wave42: Volume spike detection (>= max_ticks ceiling) triggering cooldown lockout period.
5. wave42: Tick arrival rate and interval calculations, reset() clearing, and info() telemetry diagnostics.
6. wave43: WinRateGuard initialization defaults, parameter alias mapping, and property accessors.
7. wave43: Sample size accumulation requirement (sample < min_trades) preventing premature guard trips.
8. wave43: Sub-threshold win rate breach (< 30% across rolling window) triggering 20-minute pause lockout.
9. wave43: Pause duration countdown, active block persistence, and post-cooldown auto-reset.
10. wave43: WinRateGuard reset() state flushing and info() diagnostic telemetry introspection.
"""

import math
import time
import pytest

from wave42_tick_volume_filter import TickVolumeFilter
from wave43_win_rate_guard import WinRateGuard


def test_wave42_initialization_defaults_and_clamping():
    """Verify TickVolumeFilter initializes with defaults and clamps invalid arguments."""
    # Defaults: window_sec=10.0s, min_ticks=4, max_ticks=50, spike_ratio=3.5, cooldown=30.0s
    tvf = TickVolumeFilter()
    assert tvf._window_sec == 10.0
    assert tvf._min_ticks == 4
    assert tvf._max_ticks == 50
    assert tvf._spike_ratio_threshold == 3.5
    assert tvf._spike_cooldown_sec == 30.0
    assert tvf._baseline_sec == 60.0
    assert len(tvf._tick_times) == 0

    # Custom valid configuration
    custom = TickVolumeFilter(window_sec=5.0, min_ticks=2, max_ticks=30)
    assert custom._window_sec == 5.0
    assert custom._min_ticks == 2
    assert custom._max_ticks == 30

    # Clamping invalid inputs to defaults
    bad = TickVolumeFilter(window_sec=0.0, baseline_sec=-10.0)
    assert bad._window_sec == 10.0
    assert bad._baseline_sec == 60.0


def test_wave42_dead_market_blocks_entry():
    """Verify insufficient tick arrivals (< min_ticks in window) flags dead market and blocks entry."""
    tvf = TickVolumeFilter(window_sec=10.0, min_ticks=4)
    t0 = 1750000000.0

    # Feed only 2 ticks within 10s window (2 < 4 min_ticks)
    tvf.update(now_ts=t0 - 5.0)
    tvf.update(now_ts=t0 - 2.0)

    assert tvf.is_entry_blocked(now_ts=t0) is True
    assert tvf._blocked_count == 1
    assert "DEAD_MARKET (2/4 ticks in 10s)" in tvf.get_block_reason()


def test_wave42_normal_tick_flow_allows_entry():
    """Verify normal tick velocity (min_ticks <= count < max_ticks) allows entries freely."""
    tvf = TickVolumeFilter(window_sec=10.0, min_ticks=4, max_ticks=50)
    t0 = 1750000000.0

    # Feed 8 ticks within 10s window
    for i in range(8):
        tvf.update(now_ts=t0 - 9.0 + i)

    assert tvf.is_entry_blocked(now_ts=t0) is False
    assert tvf.get_block_reason() == ""


def test_wave42_volume_spike_blocks_with_cooldown():
    """Verify volume spike (>= max_ticks in window) blocks entry and enforces cooldown lockout."""
    tvf = TickVolumeFilter(window_sec=10.0, min_ticks=4, max_ticks=30, spike_cooldown_sec=25.0)
    t0 = 1750000000.0

    # Feed 35 ticks in the last 5 seconds (35 >= 30 max_ticks ceiling)
    for i in range(35):
        tvf.update(now_ts=t0 - 5.0 + (i * 0.1))

    # Immediate volume spike trigger at t0
    assert tvf.is_entry_blocked(now_ts=t0) is True
    assert tvf._spike_blocked_count == 1
    assert tvf._cooldown_until == t0 + 25.0
    assert "VOLUME_SPIKE (35 >= max 30)" in tvf.get_block_reason()

    # 10s into the 25s cooldown: still blocked
    assert tvf.is_entry_blocked(now_ts=t0 + 10.0) is True
    assert "SPIKE_COOLDOWN" in tvf.get_block_reason()

    # 26s in: cooldown expired, feed 10 normal ticks -> unblocked
    tvf.reset()
    for i in range(10):
        tvf.update(now_ts=t0 + 26.0 - 5.0 + i * 0.5)
    assert tvf.is_entry_blocked(now_ts=t0 + 26.0) is False


def test_wave42_reset_and_info_introspection():
    """Verify tick rates, intervals, reset() state clearing, and info() diagnostics."""
    tvf = TickVolumeFilter(window_sec=10.0, min_ticks=4)
    t0 = 1750000000.0

    # Feed 10 ticks across 10s
    for i in range(10):
        tvf.update(now_ts=t0 - 9.0 + i)

    rate = tvf.get_tick_rate(window_sec=10.0, now_ts=t0)
    assert rate == 1.0  # 10 ticks / 10s = 1.0 ticks/s

    interval = tvf.get_avg_tick_interval(now_ts=t0)
    assert interval == 1.0  # 10s / 10 ticks = 1.0s/tick

    info = tvf.info(now_ts=t0)
    assert info["blocked"] is False
    assert info["is_dead_market"] is False
    assert info["is_volume_spike"] is False
    assert info["ticks_in_window"] == 10
    assert info["tick_rate_per_sec"] == 1.0

    tvf.reset()
    info_reset = tvf.info(now_ts=t0)
    assert info_reset["blocked"] is True  # 0 ticks < 4 min_ticks -> dead market
    assert info_reset["is_dead_market"] is True
    assert info_reset["ticks_in_window"] == 0


def test_wave43_initialization_defaults_and_aliases():
    """Verify WinRateGuard initializes with defaults and supports constructor aliases."""
    # Defaults: min_trades=5, threshold=0.30, pause_duration_sec=1200.0, window=10
    guard = WinRateGuard()
    assert guard._min_trades == 5
    assert guard._threshold == 0.30
    assert guard._pause_sec == 1200.0
    assert guard._window == 10
    assert len(guard._results) == 0

    # Custom aliases
    custom = WinRateGuard(min_win_rate=0.40, pause_seconds=900.0, window=15)
    assert custom._threshold == 0.40
    assert custom._pause_sec == 900.0
    assert custom._window == 15


def test_wave43_insufficient_sample_size_does_not_block():
    """Verify insufficient trade sample size (< min_trades) does not trigger guard."""
    guard = WinRateGuard(min_trades=5, win_rate_threshold=0.30)
    t0 = 1750000000.0

    # Record 3 losing trades (sample size 3 < 5 min_trades)
    guard.record_trade(won=False, now_ts=t0)
    guard.record_trade(won=False, now_ts=t0 + 60.0)
    guard.record_trade(won=False, now_ts=t0 + 120.0)

    assert len(guard._results) == 3
    assert guard._pause_until == 0.0
    assert guard.is_entry_blocked(now_ts=t0 + 120.0) is False
    assert guard.seconds_remaining(now_ts=t0 + 120.0) == 0.0


def test_wave43_low_win_rate_triggers_20min_pause():
    """Verify win rate below threshold across sufficient sample size trips 20-minute pause."""
    guard = WinRateGuard(min_trades=5, win_rate_threshold=0.30, pause_duration_sec=1200.0)
    t0 = 1750000000.0

    # 1 win and 4 losses across 5 trades: win rate = 1/5 = 20% < 30% threshold
    guard.record_trade(won=True, now_ts=t0)
    guard.record_trade(won=False, now_ts=t0 + 10.0)
    guard.record_trade(won=False, now_ts=t0 + 20.0)
    guard.record_trade(won=False, now_ts=t0 + 30.0)
    guard.record_trade(won=False, now_ts=t0 + 40.0)

    assert len(guard._results) == 5
    assert guard._current_win_rate() == 0.20
    assert guard._pause_until == t0 + 40.0 + 1200.0

    # Entry is blocked
    assert guard.is_entry_blocked(now_ts=t0 + 40.0) is True
    assert guard.seconds_remaining(now_ts=t0 + 40.0) == 1200.0


def test_wave43_pause_expiration_clears_stale_streak():
    """Verify pause persists through duration and auto-clears loss history upon expiration."""
    guard = WinRateGuard(min_trades=5, win_rate_threshold=0.30, pause_duration_sec=600.0)
    t0 = 1750000000.0

    # Trip the guard with 5 losses
    for i in range(5):
        guard.record_trade(won=False, now_ts=t0 + i)

    # Midway through pause (300s in): still blocked
    assert guard.is_entry_blocked(now_ts=t0 + 305.0) is True
    assert guard.seconds_remaining(now_ts=t0 + 305.0) > 0.0

    # Pause expires (601s in): unblocks and clears stale streak
    assert guard.is_entry_blocked(now_ts=t0 + 606.0) is False
    assert len(guard._results) == 0
    assert guard._pause_until == 0.0


def test_wave43_reset_and_info_introspection():
    """Verify reset() flushes results and info() provides diagnostic telemetry."""
    guard = WinRateGuard(min_trades=5, win_rate_threshold=0.30)
    t0 = 1750000000.0

    for i in range(5):
        guard.record_trade(won=(i < 2), now_ts=t0 + i)  # 2 wins, 3 losses = 40% win rate

    info = guard.info(now_ts=t0 + 10.0)
    assert info["wave"] == 43
    assert info["name"] == "WinRateGuard"
    assert info["win_rate_pct"] == 40.0
    assert info["sample_size"] == 5
    assert info["min_trades"] == 5
    assert info["sufficient_sample"] is True
    assert info["threshold_pct"] == 30.0
    assert info["paused"] is False

    guard.reset()
    info_reset = guard.info(now_ts=t0 + 10.0)
    assert info_reset["sample_size"] == 0
    assert info_reset["sufficient_sample"] is False
    assert info_reset["paused"] is False
