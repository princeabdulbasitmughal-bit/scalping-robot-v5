"""
tests/test_batch88.py
Batch 88 Unit Tests: Consecutive Loss Guard (wave56) & Hourly PnL Heatmap (wave57).
Expands test baseline beyond 1,127+ passing tests.
Verifies:
1. wave56: ConsecutiveLossGuard initialization defaults, parameter bounds, and state clamping.
2. wave56: Consecutive losing trade tracking, tripwire activation, and 30-minute pause lockout.
3. wave56: Winning trade streak resetting (clearing loss accumulator before reaching threshold).
4. wave56: Pause duration expiration, auto-reset upon cooldown expiry, and fail-closed gate.
5. wave56: ConsecutiveLossGuard reset() clearing and info() telemetry introspection.
6. wave57: HourlyPnLMap initialization, negative threshold enforcement, and 24-hour map scaffolding.
7. wave57: Hourly trade PnL bucketing across distinct UTC hours (0-23).
8. wave57: Bad hour detection triggering advisory 50% lot multiplier reduction (0.5x vs 1.0x).
9. wave57: Automatic daily UTC rollover clearing all hourly bins for the new session.
10. wave57: HourlyPnLMap reset() clearing and info() telemetry introspection.
"""

from datetime import datetime, timezone
import pytest

from wave56_consecutive_loss_guard import ConsecutiveLossGuard
from wave57_hourly_pnl_map import HourlyPnLMap


def test_wave56_initialization_defaults_and_clamping():
    """Verify ConsecutiveLossGuard initializes with defaults and clamps invalid inputs."""
    # Defaults
    guard = ConsecutiveLossGuard()
    assert guard.max_losses == 3
    assert guard.pause_seconds == 1800.0

    # Custom clamped
    guard_clamped = ConsecutiveLossGuard(max_losses=-5, pause_seconds=-100.0)
    assert guard_clamped.max_losses == 1
    assert guard_clamped.pause_seconds == 0.0


def test_wave56_record_trade_losses_and_pause_trigger():
    """Verify recording consecutive losses trips the lockout pause upon hitting max_losses."""
    guard = ConsecutiveLossGuard(max_losses=3, pause_seconds=1800.0)
    t0 = 1750000000.0

    # Loss 1
    guard.record_trade(won=False, now_ts=t0)
    assert guard._consecutive_losses == 1
    assert guard.is_entry_blocked(now_ts=t0) is False

    # Loss 2
    guard.record_trade(won=False, now_ts=t0 + 60.0)
    assert guard._consecutive_losses == 2
    assert guard.is_entry_blocked(now_ts=t0 + 60.0) is False

    # Loss 3 -> Triggers Pause!
    guard.record_trade(won=False, now_ts=t0 + 120.0)
    assert guard._consecutive_losses == 3
    assert guard._pause_until == t0 + 120.0 + 1800.0
    assert guard._total_pauses == 1
    assert guard.is_entry_blocked(now_ts=t0 + 120.0) is True


def test_wave56_win_resets_loss_streak():
    """Verify any winning trade immediately resets the consecutive loss accumulator to 0."""
    guard = ConsecutiveLossGuard(max_losses=3)
    t0 = 1750000000.0

    # 2 losses
    guard.record_trade(won=False, now_ts=t0)
    guard.record_trade(won=False, now_ts=t0 + 60.0)
    assert guard._consecutive_losses == 2

    # 1 win resets streak
    guard.record_trade(won=True, now_ts=t0 + 120.0)
    assert guard._consecutive_losses == 0
    assert guard.is_entry_blocked(now_ts=t0 + 120.0) is False

    # Another single loss does not trigger pause
    guard.record_trade(won=False, now_ts=t0 + 180.0)
    assert guard._consecutive_losses == 1
    assert guard.is_entry_blocked(now_ts=t0 + 180.0) is False


def test_wave56_pause_expiration_and_cooldown_reset():
    """Verify entry is blocked during pause and automatically re-enables after pause expires."""
    guard = ConsecutiveLossGuard(max_losses=2, pause_seconds=600.0)  # 10 min
    t0 = 1750000000.0

    guard.record_trade(won=False, now_ts=t0)
    guard.record_trade(won=False, now_ts=t0 + 10.0)
    assert guard.is_entry_blocked(now_ts=t0 + 10.0) is True

    # Mid-pause (5 min in): Still blocked
    assert guard.is_entry_blocked(now_ts=t0 + 310.0) is True

    # Exactly when pause expires (10 min in = 600s): Unblocked and reset
    assert guard.is_entry_blocked(now_ts=t0 + 611.0) is False
    assert guard._consecutive_losses == 0
    assert guard._pause_until == 0.0


def test_wave56_reset_and_info_introspection():
    """Verify reset() clears internal state and info() outputs diagnostic status."""
    guard = ConsecutiveLossGuard(max_losses=2, pause_seconds=600.0)
    t0 = 1750000000.0
    guard.record_trade(won=False, now_ts=t0)
    guard.record_trade(won=False, now_ts=t0 + 10.0)

    info = guard.info(now_ts=t0 + 10.0)
    assert info["wave"] == 56
    assert info["name"] == "ConsecutiveLossGuard"
    assert info["consecutive_losses"] == 2
    assert info["paused"] is True
    assert info["total_pauses"] == 1
    assert info["pause_remaining_sec"] > 0

    guard.reset()
    info_reset = guard.info(now_ts=t0 + 10.0)
    assert info_reset["consecutive_losses"] == 0
    assert info_reset["paused"] is False
    assert info_reset["total_pauses"] == 0


def test_wave57_initialization_defaults_and_threshold():
    """Verify HourlyPnLMap enforces negative loss threshold and scaffolds 24 hourly bins."""
    pnl_map = HourlyPnLMap()
    assert pnl_map.loss_threshold_usd == -30.0
    assert len(pnl_map._hour_pnl) == 24
    assert all(pnl_map._hour_pnl[h] == 0.0 for h in range(24))

    # Passing positive value is automatically negated
    pnl_map_custom = HourlyPnLMap(loss_threshold_usd=50.0)
    assert pnl_map_custom.loss_threshold_usd == -50.0


def test_wave57_record_trade_hourly_bucketing():
    """Verify record_trade aggregates PnL into the correct UTC hour bin."""
    pnl_map = HourlyPnLMap()

    # Hour 14 (14:15 UTC)
    dt1 = datetime(2026, 10, 18, 14, 15, 0, tzinfo=timezone.utc)
    pnl_map.record_trade(15.5, now_dt=dt1)

    # Hour 14 again (14:45 UTC)
    dt2 = datetime(2026, 10, 18, 14, 45, 0, tzinfo=timezone.utc)
    pnl_map.record_trade(-5.0, now_dt=dt2)

    # Hour 8 (08:30 UTC)
    dt3 = datetime(2026, 10, 18, 8, 30, 0, tzinfo=timezone.utc)
    pnl_map.record_trade(-25.0, now_dt=dt3)

    assert pnl_map._hour_pnl[14] == 10.5
    assert pnl_map._hour_pnl[8] == -25.0
    assert pnl_map._trade_count == 3

    # Non-finite PnL is ignored safely
    pnl_map.record_trade(float("nan"), now_dt=dt1)
    assert pnl_map._trade_count == 3


def test_wave57_loss_threshold_advisory_lot_multiplier():
    """Verify get_lot_multiplier scales lot to 0.5 when hour loss breaches threshold."""
    pnl_map = HourlyPnLMap(loss_threshold_usd=-30.0)
    dt_bad_hour = datetime(2026, 10, 18, 10, 15, 0, tzinfo=timezone.utc)

    # Accumulate -$35.0 loss in hour 10 (exceeds -$30.0 threshold)
    pnl_map.record_trade(-35.0, now_dt=dt_bad_hour)
    assert pnl_map.get_lot_multiplier(now_dt=dt_bad_hour) == 0.5

    # Hour 11 has no losses -> normal 1.0 multiplier
    dt_good_hour = datetime(2026, 10, 18, 11, 0, 0, tzinfo=timezone.utc)
    assert pnl_map.get_lot_multiplier(now_dt=dt_good_hour) == 1.0


def test_wave57_daily_utc_rollover_resets_map():
    """Verify daily UTC change automatically flushes hourly PnL map for the new session."""
    pnl_map = HourlyPnLMap()
    day1_dt = datetime(2026, 10, 18, 23, 45, 0, tzinfo=timezone.utc)
    pnl_map.record_trade(-50.0, now_dt=day1_dt)
    assert pnl_map._hour_pnl[23] == -50.0

    # Day 2 rollover
    day2_dt = datetime(2026, 10, 19, 0, 15, 0, tzinfo=timezone.utc)
    pnl_map.record_trade(10.0, now_dt=day2_dt)

    # Hour 23 from previous day was reset, hour 0 has 10.0
    assert pnl_map._hour_pnl[23] == 0.0
    assert pnl_map._hour_pnl[0] == 10.0


def test_wave57_reset_and_info_telemetry():
    """Verify reset() flushes map and info() outputs diagnostic telemetry."""
    pnl_map = HourlyPnLMap(loss_threshold_usd=-30.0)
    dt = datetime(2026, 10, 18, 15, 30, 0, tzinfo=timezone.utc)
    pnl_map.record_trade(-40.0, now_dt=dt)

    info = pnl_map.info(now_dt=dt)
    assert info["wave"] == 57
    assert info["name"] == "HourlyPnLMap"
    assert info["current_utc_hour"] == 15
    assert info["current_hour_pnl_usd"] == -40.0
    assert info["lot_multiplier"] == 0.5
    assert info["total_trades_recorded"] == 1
    assert "15" in info["hour_pnl_map"]

    pnl_map.reset()
    info_reset = pnl_map.info(now_dt=dt)
    assert info_reset["current_hour_pnl_usd"] == 0.0
    assert info_reset["lot_multiplier"] == 1.0
    assert info_reset["total_trades_recorded"] == 0
