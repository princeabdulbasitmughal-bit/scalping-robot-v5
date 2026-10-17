"""
tests/test_batch98.py
Batch 98 Unit Tests: Spread Momentum Guard (wave36) & Entry Cooldown (wave37).
Expands test baseline beyond 1,217+ passing tests to 1,227+ passing tests.
Verifies:
1. wave36: SpreadMomentumGuard initialization defaults, spike ratio (3.0x), and window constants.
2. wave36: Warmup threshold requirement (MIN_TICKS=3) and non-finite/boolean spread input rejection.
3. wave36: Orderly spread fluctuation (< 3.0x baseline) allowing entries without restriction.
4. wave36: Rapid spread widening (>= 3.0x baseline) triggering 60-second entry lockout.
5. wave36: SpreadMomentumGuard reset() state flushing and info() diagnostic telemetry reporting.
6. wave37: EntryCooldown initialization defaults (60s win cooldown, 120s loss cooldown).
7. wave37: Winning trade close triggering 60-second post-exit cooldown and counter increments.
8. wave37: Losing trade close triggering 120-second revenge-prevention cooldown and counter increments.
9. wave37: Cooldown overlap protection ensuring shorter cooldowns never truncate active longer lockouts.
10. wave37: EntryCooldown force_reset(), reset(), and info() telemetry diagnostics introspection.
"""

import math
import time
import pytest

from wave36_spread_momentum import SpreadMomentumGuard
from wave37_entry_cooldown import EntryCooldown


def test_wave36_initialization_defaults_and_constants():
    """Verify SpreadMomentumGuard initializes with defaults and proper window constants."""
    guard = SpreadMomentumGuard()
    assert guard.SPIKE_RATIO == 3.0
    assert guard.WINDOW == 5
    assert guard.BLOCK_SECONDS == 60
    assert guard.MIN_TICKS == 3
    assert len(guard._spread_history) == 0
    assert guard._block_until == 0.0
    assert guard.total_spikes_detected == 0
    assert guard.total_blocks == 0
    assert guard.last_spread == 0.0


def test_wave36_warmup_and_invalid_inputs():
    """Verify minimum ticks warmup requirement and rejection of invalid spread inputs."""
    guard = SpreadMomentumGuard()
    t0 = 1750000000.0

    # Feed 2 ticks (fewer than MIN_TICKS 3)
    guard.update(1.5, now_ts=t0)
    guard.update(1.6, now_ts=t0 + 1.0)
    assert len(guard._spread_history) == 2
    assert guard.is_entry_blocked(now_ts=t0 + 1.0) is False

    # Feed invalid spreads: None, boolean, string, <= 0, NaN, inf
    guard.update(None, now_ts=t0 + 2.0)
    guard.update(True, now_ts=t0 + 2.0)
    guard.update(False, now_ts=t0 + 2.0)
    guard.update(-1.5, now_ts=t0 + 2.0)
    guard.update(0.0, now_ts=t0 + 2.0)
    guard.update(float("nan"), now_ts=t0 + 2.0)
    guard.update(float("inf"), now_ts=t0 + 2.0)
    guard.update("invalid", now_ts=t0 + 2.0)

    # History length remains unchanged at 2
    assert len(guard._spread_history) == 2


def test_wave36_normal_spread_allows_trading():
    """Verify normal spread variations (< 3.0x baseline) allow entry clearance."""
    guard = SpreadMomentumGuard()
    t0 = 1750000000.0

    # Feed 5 ticks with normal spreads around 1.5 pips
    spreads = [1.5, 1.6, 1.4, 1.5, 1.6]
    for i, s in enumerate(spreads):
        guard.update(s, now_ts=t0 + i)

    assert guard.last_spike_ratio < 3.0
    assert guard.is_entry_blocked(now_ts=t0 + 5.0) is False
    assert guard.total_spikes_detected == 0


def test_wave36_spread_spike_triggers_60s_block():
    """Verify rapid spread widening (>= 3.0x baseline) triggers 60-second entry lockout."""
    guard = SpreadMomentumGuard()
    t0 = 1750000000.0

    # Feed 4 baseline ticks at 1.0 pip
    for i in range(4):
        guard.update(1.0, now_ts=t0 + i)

    # Feed sudden spread blowout to 3.5 pips (ratio = 3.5 / 1.0 = 3.5 >= 3.0)
    guard.update(3.5, now_ts=t0 + 4.0)

    assert guard.last_spike_ratio == 3.5
    assert guard.is_entry_blocked(now_ts=t0 + 4.0) is True
    assert guard.total_spikes_detected == 1
    assert guard.total_blocks == 1
    assert guard._block_until == t0 + 4.0 + 60.0
    assert guard.seconds_remaining(now_ts=t0 + 4.0) == 60.0

    # 30s in: still blocked
    assert guard.is_entry_blocked(now_ts=t0 + 34.0) is True
    assert guard.seconds_remaining(now_ts=t0 + 34.0) == 30.0

    # 61s in: block expired -> unblocked
    assert guard.is_entry_blocked(now_ts=t0 + 65.0) is False
    assert guard.seconds_remaining(now_ts=t0 + 65.0) == 0.0


def test_wave36_reset_and_info_introspection():
    """Verify reset() flushes state and info() outputs diagnostic telemetry."""
    guard = SpreadMomentumGuard()
    t0 = 1750000000.0
    for s in [1.0, 1.0, 1.0, 3.5]:
        guard.update(s, now_ts=t0)

    info = guard.info(now_ts=t0)
    assert info["spike_ratio_threshold"] == 3.0
    assert info["window_ticks"] == 5
    assert info["block_seconds"] == 60
    assert info["currently_blocked"] is True
    assert info["seconds_remaining"] == 60.0
    assert info["last_spread_pips"] == 3.5
    assert info["last_spike_ratio"] == 3.5
    assert info["total_spikes_detected"] == 1
    assert info["total_blocks"] == 1

    guard.reset()
    info_reset = guard.info(now_ts=t0)
    assert info_reset["currently_blocked"] is False
    assert info_reset["seconds_remaining"] == 0.0
    assert info_reset["total_spikes_detected"] == 0
    assert info_reset["total_blocks"] == 0
    assert info_reset["last_spread_pips"] == 0.0


def test_wave37_initialization_defaults_and_constants():
    """Verify EntryCooldown initializes with defaults and proper cooldown duration constants."""
    ec = EntryCooldown()
    assert ec.COOLDOWN_WIN_SEC == 60
    assert ec.COOLDOWN_LOSS_SEC == 120
    assert ec._cooldown_until == 0.0
    assert ec._last_cooldown_reason == "NONE"
    assert ec.last_trade_result == "NONE"
    assert ec.total_cooldowns_triggered == 0
    assert ec.total_win_cooldowns == 0
    assert ec.total_loss_cooldowns == 0


def test_wave37_winning_trade_triggers_60s_cooldown():
    """Verify winning trade close triggers 60-second cooldown and updates win metrics."""
    ec = EntryCooldown()
    t0 = 1750000000.0

    ec.record_trade_close(was_win=True, pnl=25.5, now_ts=t0)
    assert ec._cooldown_until == t0 + 60.0
    assert ec.last_trade_result == "WIN"
    assert ec.total_win_cooldowns == 1
    assert ec.total_cooldowns_triggered == 1
    assert "WIN trade (PnL=+25.50): 60s cooldown" in ec._last_cooldown_reason

    # Blocked during cooldown
    assert ec.is_entry_blocked(now_ts=t0) is True
    assert ec.seconds_remaining(now_ts=t0) == 60.0

    # 30s in: still blocked
    assert ec.is_entry_blocked(now_ts=t0 + 30.0) is True
    assert ec.seconds_remaining(now_ts=t0 + 30.0) == 30.0

    # 61s in: cooldown expired
    assert ec.is_entry_blocked(now_ts=t0 + 61.0) is False
    assert ec.seconds_remaining(now_ts=t0 + 61.0) == 0.0


def test_wave37_losing_trade_triggers_120s_cooldown():
    """Verify losing trade close triggers 120-second revenge-prevention cooldown."""
    ec = EntryCooldown()
    t0 = 1750000000.0

    ec.record_trade_close(was_win=False, pnl=-45.0, now_ts=t0)
    assert ec._cooldown_until == t0 + 120.0
    assert ec.last_trade_result == "LOSS"
    assert ec.total_loss_cooldowns == 1
    assert ec.total_cooldowns_triggered == 1
    assert "LOSS trade (PnL=-45.00): 120s cooldown" in ec._last_cooldown_reason

    # Blocked during cooldown
    assert ec.is_entry_blocked(now_ts=t0) is True
    assert ec.seconds_remaining(now_ts=t0) == 120.0

    # 90s in: still blocked
    assert ec.is_entry_blocked(now_ts=t0 + 90.0) is True
    assert ec.seconds_remaining(now_ts=t0 + 90.0) == 30.0

    # 121s in: cooldown expired
    assert ec.is_entry_blocked(now_ts=t0 + 121.0) is False
    assert ec.seconds_remaining(now_ts=t0 + 121.0) == 0.0


def test_wave37_cooldown_overlap_preserves_longer_lockout():
    """Verify that shorter subsequent cooldown does not truncate an active longer cooldown."""
    ec = EntryCooldown()
    t0 = 1750000000.0

    # Loss triggers 120s cooldown until t0 + 120.0
    ec.record_trade_close(was_win=False, pnl=-30.0, now_ts=t0)
    assert ec._cooldown_until == t0 + 120.0

    # 10s later, a win triggers 60s cooldown (would end at t0 + 70.0)
    ec.record_trade_close(was_win=True, pnl=10.0, now_ts=t0 + 10.0)
    # The active cooldown until t0 + 120.0 must be preserved via max()
    assert ec._cooldown_until == t0 + 120.0
    assert ec.total_cooldowns_triggered == 2
    assert ec.total_loss_cooldowns == 1
    assert ec.total_win_cooldowns == 1


def test_wave37_force_reset_and_info_introspection():
    """Verify force_reset() unblocks immediately, reset() flushes counters, and info() provides status."""
    ec = EntryCooldown()
    t0 = 1750000000.0

    ec.record_trade_close(was_win=True, pnl=20.0, now_ts=t0)
    assert ec.is_entry_blocked(now_ts=t0) is True

    # force_reset unblocks immediately
    ec.force_reset()
    assert ec.is_entry_blocked(now_ts=t0) is False
    assert ec._last_cooldown_reason == "RESET"

    info = ec.info(now_ts=t0)
    assert info["cooldown_win_sec"] == 60
    assert info["cooldown_loss_sec"] == 120
    assert info["currently_blocked"] is False
    assert info["seconds_remaining"] == 0.0
    assert info["total_cooldowns_triggered"] == 1
    assert info["total_win_cooldowns"] == 1

    # Full reset clears counters
    ec.reset()
    info_reset = ec.info(now_ts=t0)
    assert info_reset["total_cooldowns_triggered"] == 0
    assert info_reset["total_win_cooldowns"] == 0
    assert info_reset["total_loss_cooldowns"] == 0
    assert info_reset["last_trade_result"] == "NONE"
