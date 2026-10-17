"""
tests/test_batch103.py
Batch 103 Unit Tests: Time Filter (wave26) & Correlation Guard (wave27).
Expands test baseline beyond 1,267+ passing tests to 1,277+ passing tests across 103 test suites!
Verifies:
1. wave26: TimeFilter initialization defaults, release schedules, and boolean parameter protection.
2. wave26: Normal midday non-release window trading clearance.
3. wave26: Major economic release window entry lockout (30m before and after 12:30 UTC).
4. wave26: Rollover window lockout and circular midnight seconds diff calculation.
5. wave26: Datetime normalization (str, timestamp, tz-naive/aware, bool), reset(), and info() telemetry.
6. wave27: compute_pearson_correlation edge cases (perfect, inverse, flat, zero-variance, invalid).
7. wave27: CorrelationGuard initialization defaults, parameter bounds, and boolean rejection.
8. wave27: Rapid signal cluster density detection triggering choppy market cooldown lockout.
9. wave27: Cooldown lockout expiration and seamless trading recovery.
10. wave27: Cross-asset price correlation matrix calculation, is_correlation_too_high(), reset(), and info().
"""

from datetime import datetime, timezone
import math
import pytest

from wave26_time_filter import TimeFilter
from wave27_correlation_guard import CorrelationGuard, compute_pearson_correlation


def test_wave26_time_filter_initialization_defaults_and_constants():
    """Verify TimeFilter initializes with defaults, default release times, and guards booleans."""
    tf = TimeFilter()
    assert len(tf._release_times) == 7
    assert (12, 30) in tf._release_times
    assert (18, 0) in tf._release_times
    assert tf._block_before == 30
    assert tf._block_after == 30
    assert tf._total_blocks == 0
    assert tf._was_blocked is False

    # Boolean parameter rejection in init
    tf_bool = TimeFilter(block_before=True, block_after=False)
    assert tf_bool._block_before == 30
    assert tf_bool._block_after == 30


def test_wave26_time_filter_normal_midday_trading_clearance():
    """Verify normal trading hours far from any scheduled releases allow execution."""
    tf = TimeFilter()
    # 10:00 UTC is well clear of 12:30 UTC release
    dt_clear = datetime(2026, 10, 21, 10, 0, 0, tzinfo=timezone.utc)

    allowed, reason = tf.is_trading_allowed(dt_clear)
    assert allowed is True
    assert reason == ""
    assert tf.is_entry_blocked(dt_clear) is False
    assert tf.is_blocked(dt_clear) is False


def test_wave26_time_filter_release_window_blocking():
    """Verify 30m window surrounding economic release blocks entries and reports remaining time."""
    tf = TimeFilter()

    # 1. 12:15 UTC (15m before 12:30 release) -> Blocked
    dt_before = datetime(2026, 10, 21, 12, 15, 0, tzinfo=timezone.utc)
    allowed_before, reason_before = tf.is_trading_allowed(dt_before)
    assert allowed_before is False
    assert "TIME_FILTER: 15m before major release at 12:30 UTC" in reason_before
    assert tf.is_entry_blocked(dt_before) is True
    assert tf._total_blocks == 1

    # 2. 12:45 UTC (15m after 12:30 release) -> Blocked
    dt_after = datetime(2026, 10, 21, 12, 45, 0, tzinfo=timezone.utc)
    allowed_after, reason_after = tf.is_trading_allowed(dt_after)
    assert allowed_after is False
    assert "TIME_FILTER: 15m after major release at 12:30 UTC" in reason_after

    # 3. 15:00 UTC (no release nearby) -> Allowed
    dt_post = datetime(2026, 10, 21, 15, 0, 0, tzinfo=timezone.utc)
    allowed_post, reason_post = tf.is_trading_allowed(dt_post)
    assert allowed_post is True
    assert reason_post == ""


def test_wave26_time_filter_rollover_window_lockout():
    """Verify broker rollover liquidity gap window (21:45 UTC) blocks trades."""
    tf = TimeFilter()

    # 22:00 UTC (15m after 21:45 rollover) -> Blocked
    dt_rollover = datetime(2026, 10, 21, 22, 0, 0, tzinfo=timezone.utc)
    allowed, reason = tf.is_trading_allowed(dt_rollover)
    assert allowed is False
    assert "at 21:45 UTC" in reason

    # 22:20 UTC (35m after 21:45) -> Clear
    dt_clear = datetime(2026, 10, 21, 22, 20, 0, tzinfo=timezone.utc)
    assert tf.is_entry_blocked(dt_clear) is False


def test_wave26_time_filter_normalization_reset_and_telemetry():
    """Verify input datetime normalization, release time modification, reset, and telemetry."""
    tf = TimeFilter()

    # Normalization of string ISO, timestamp, and boolean
    dt_iso = tf._normalize_datetime("2026-10-21T10:00:00+00:00")
    assert dt_iso.tzinfo == timezone.utc
    assert dt_iso.hour == 10

    dt_ts = tf._normalize_datetime(1700000000.0)
    assert dt_ts.tzinfo == timezone.utc

    # Boolean input safely handled by defaulting to current time
    dt_bool = tf._normalize_datetime(True)
    assert dt_bool.tzinfo == timezone.utc

    # Dynamic release time update
    tf.add_release_time(8, 0)
    assert (8, 0) in tf._release_times

    # Telemetry
    dt_blocked = datetime(2026, 10, 21, 12, 20, 0, tzinfo=timezone.utc)
    info = tf.info(dt_blocked)
    assert info["wave"] == 26
    assert info["name"] == "TimeFilter"
    assert info["trading_allowed"] is False
    assert info["remaining_block_min"] > 0

    # Reset
    tf.reset()
    assert tf._total_blocks == 0
    assert tf._was_blocked is False


def test_wave27_compute_pearson_correlation():
    """Verify Pearson correlation calculation handles linear, inverse, and edge cases safely."""
    # Perfect positive correlation -> 1.0
    assert abs(compute_pearson_correlation([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) - 1.0) < 1e-9

    # Perfect negative correlation -> -1.0
    assert abs(compute_pearson_correlation([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]) - (-1.0)) < 1e-9

    # Zero variance (flat series) -> 0.0 (zero-division safe)
    assert compute_pearson_correlation([5, 5, 5, 5], [1, 2, 3, 4]) == 0.0
    assert compute_pearson_correlation([1, 2, 3, 4], [0, 0, 0, 0]) == 0.0

    # Length mismatch or insufficient items -> 0.0
    assert compute_pearson_correlation([1, 2], [1, 2, 3]) == 0.0
    assert compute_pearson_correlation([1], [1]) == 0.0

    # Non-finite or boolean values safely handled
    assert compute_pearson_correlation([1, float("nan"), 3], [1, 2, 3]) == 0.0
    assert compute_pearson_correlation([True, False, True], [1, 2, 3]) == 0.0


def test_wave27_correlation_guard_initialization_defaults():
    """Verify CorrelationGuard initializes with defaults and guards boolean inputs."""
    cg = CorrelationGuard()
    assert cg._window_sec == 30.0
    assert cg._max_signals == 3
    assert cg._cooldown_sec == 60.0
    assert cg._max_corr_threshold == 0.85
    assert len(cg._signal_times) == 0
    assert cg._blocked_until == 0.0
    assert cg._total_triggers == 0

    # Boolean parameter rejection
    cg_bool = CorrelationGuard(
        window_sec=True,
        max_signals_in_window=False,
        cooldown_sec=True,
        max_corr_threshold=False,
    )
    assert cg_bool._window_sec == 30.0
    assert cg_bool._max_signals == 3
    assert cg_bool._cooldown_sec == 60.0


def test_wave27_correlation_guard_cluster_density_cooldown():
    """Verify cluster of rapid-fire signals exceeds window limit and triggers choppy market cooldown."""
    cg = CorrelationGuard(window_sec=30.0, max_signals_in_window=3, cooldown_sec=60.0)
    t0 = 1000.0

    # Pacing: 3 signals at t0, t0+5, t0+10 (allowed up to 3)
    cg.record_signal(now_ts=t0)
    cg.record_signal(now_ts=t0 + 5.0)
    cg.record_signal(now_ts=t0 + 10.0)

    allowed, reason = cg.is_trading_allowed(now_ts=t0 + 10.0)
    assert allowed is True
    assert reason == ""

    # 4th signal at t0+15 within 30s window exceeds max_signals -> triggers 60s cooldown!
    cg.record_signal(now_ts=t0 + 15.0)
    assert cg._total_triggers == 1
    assert cg._blocked_until == t0 + 15.0 + 60.0

    allowed, reason = cg.is_trading_allowed(now_ts=t0 + 20.0)
    assert allowed is False
    assert "CORR_GUARD: choppy market cooldown active" in reason


def test_wave27_correlation_guard_cooldown_expiration_and_recovery():
    """Verify choppy market cooldown expires and restores trading permission."""
    cg = CorrelationGuard(window_sec=30.0, max_signals_in_window=3, cooldown_sec=60.0)
    t0 = 2000.0

    # Fire 4 signals in burst
    for dt in [0.0, 1.0, 2.0, 3.0]:
        cg.record_signal(now_ts=t0 + dt)

    assert cg._blocked_until == t0 + 3.0 + 60.0  # 2063.0

    # At 2062.0 -> still blocked
    assert cg.is_trading_allowed(now_ts=2062.0)[0] is False

    # At 2063.5 -> unblocked
    allowed, reason = cg.is_trading_allowed(now_ts=2063.5)
    assert allowed is True
    assert reason == ""


def test_wave27_correlation_guard_matrix_and_telemetry():
    """Verify asset price tracking, correlation matrix, is_correlation_too_high, reset, and info."""
    cg = CorrelationGuard(max_corr_threshold=0.85)

    # Register correlated assets
    for val in range(1, 10):
        cg.update_asset_price("XAUUSD", float(val))
        cg.update_asset_price("EURUSD", float(val * 2))

    # Compute correlation matrix
    matrix = cg.compute_correlation_matrix()
    assert "XAUUSD" in matrix and "EURUSD" in matrix
    assert matrix["XAUUSD"]["XAUUSD"] == 1.0
    assert abs(matrix["XAUUSD"]["EURUSD"] - 1.0) < 1e-9
    assert abs(matrix["EURUSD"]["XAUUSD"] - 1.0) < 1e-9

    # Check high correlation flag
    too_high, corr = cg.is_correlation_too_high("XAUUSD", "EURUSD")
    assert too_high is True
    assert abs(corr - 1.0) < 1e-9

    # Telemetry
    info = cg.info(now_ts=5000.0)
    assert info["wave"] == 27
    assert info["name"] == "CorrelationGuard"
    assert info["in_cooldown"] is False

    # Reset
    cg.reset()
    assert len(cg._asset_buffers) == 0
    assert cg._total_triggers == 0
