"""
tests/test_batch100.py
Batch 100 Grand Century Milestone Unit Tests: Gap Guard (wave32) & Partial Close Manager (wave33).
Expands test baseline beyond 1,237+ passing tests to 1,247+ passing tests across 100 complete test suites!
Verifies:
1. wave32: GapGuard initialization defaults, constants, and boolean parameter protection.
2. wave32: Normal tick-to-tick orderly flow clearance permitting trading without restriction.
3. wave32: Sudden price gap detection (>= 5.0 pips) triggering entry lockout and metric recording.
4. wave32: Lockout cooldown expiration (120s) and seamless trading recovery.
5. wave32: Fail-closed input handling on non-finite or boolean prices, reset(), and info() telemetry.
6. wave33: PartialCloseManager initialization defaults, clamping, and boolean parameter protection.
7. wave33: get_close_lot volume quantization, minimum split containment, and invalid input protection.
8. wave33: BUY position 50% TP progress trigger and single-fire deduplication.
9. wave33: SELL position 50% TP progress trigger and single-fire deduplication.
10. wave33: Ticket removal cleanup, reset(), fail-closed input handling, and info() telemetry.
"""

import math
import pytest

from wave32_gap_guard import GapGuard
from wave33_partial_close import PartialCloseManager


def test_wave32_gap_guard_initialization_defaults_and_constants():
    """Verify GapGuard initializes with standard defaults and guards boolean inputs."""
    gg = GapGuard()
    assert gg._gap_threshold_pips == 5.0
    assert gg._block_duration == 120.0
    assert gg._pip_size == 0.1
    assert abs(gg._gap_threshold - 0.5) < 1e-9
    assert gg._last_price == 0.0
    assert gg._gap_detected_at == 0.0
    assert gg._total_gaps == 0

    # Boolean input rejection in init
    gg_bool = GapGuard(gap_threshold_pips=True, block_duration_sec=False, pip_size=True)
    assert gg_bool._gap_threshold_pips == 5.0
    assert gg_bool._block_duration == 120.0
    assert gg_bool._pip_size == 0.1


def test_wave32_gap_guard_normal_tick_flow_clearance():
    """Verify normal continuous price progression does not trigger gap lockout."""
    gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=120.0, pip_size=0.1)
    t0 = 1000.0

    # First tick initializes _last_price
    gg.update_price(2400.0, now_ts=t0)
    allowed, reason = gg.is_trading_allowed(now_ts=t0)
    assert allowed is True
    assert reason == ""
    assert gg.is_entry_blocked(now_ts=t0) is False
    assert gg.is_blocked(now_ts=t0) is False

    # Second tick: +0.3 price movement = 3.0 pips (< 5.0 pips threshold)
    gg.update_price(2400.3, now_ts=t0 + 1.0)
    allowed, reason = gg.is_trading_allowed(now_ts=t0 + 1.0)
    assert allowed is True
    assert gg.is_entry_blocked(now_ts=t0 + 1.0) is False
    assert gg._total_gaps == 0


def test_wave32_gap_guard_gap_detection_and_lockout():
    """Verify sudden price jump >= 5.0 pips triggers entry lockout and records metrics."""
    gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=120.0, pip_size=0.1)
    t0 = 2000.0

    gg.update_price(2400.0, now_ts=t0)
    # Next tick jumps to 2400.8 (gap = 0.8 = 8.0 pips >= 5.0 pips)
    gg.update_price(2400.8, now_ts=t0 + 0.5)

    assert gg._total_gaps == 1
    assert gg._total_blocks == 1
    assert gg._last_gap_pips == 8.0
    assert gg._gap_detected_at == t0 + 0.5

    allowed, reason = gg.is_trading_allowed(now_ts=t0 + 1.0)
    assert allowed is False
    assert "GAP_GUARD: 8.0p gap active" in reason
    assert gg.is_entry_blocked(now_ts=t0 + 1.0) is True
    assert gg.is_blocked(now_ts=t0 + 1.0) is True


def test_wave32_gap_guard_cooldown_expiration_and_recovery():
    """Verify gap lockout automatically clears once block duration (120s) elapses."""
    gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=120.0, pip_size=0.1)
    t0 = 3000.0

    gg.update_price(2400.0, now_ts=t0)
    gg.update_price(2401.0, now_ts=t0 + 1.0)  # 10.0 pips gap -> blocked until t0 + 1.0 + 120.0 = 3121.0

    # At 3120.0 (119s elapsed): still blocked
    assert gg.is_entry_blocked(now_ts=3120.0) is True

    # At 3121.5 (120.5s elapsed): lockout expired
    allowed, reason = gg.is_trading_allowed(now_ts=3121.5)
    assert allowed is True
    assert reason == ""
    assert gg.is_entry_blocked(now_ts=3121.5) is False


def test_wave32_gap_guard_fail_closed_inputs_and_reset():
    """Verify invalid inputs are rejected safely, reset clears state, and info outputs telemetry."""
    gg = GapGuard()
    t0 = 4000.0

    gg.update_price(2400.0, now_ts=t0)
    # Invalid prices are ignored without corrupting last price
    gg.update_price(None, now_ts=t0)
    gg.update_price(True, now_ts=t0)
    gg.update_price(float("nan"), now_ts=t0)
    gg.update_price(-2400.0, now_ts=t0)
    gg.update_price("invalid", now_ts=t0)
    assert gg._last_price == 2400.0

    # Trigger a gap
    gg.update_price(2401.0, now_ts=t0 + 1.0)
    assert gg.is_entry_blocked(now_ts=t0 + 2.0) is True

    info = gg.info(now_ts=t0 + 2.0)
    assert info["wave"] == 32
    assert info["name"] == "GapGuard"
    assert info["trading_allowed"] is False
    assert info["is_blocked"] is True
    assert info["total_gaps_detected"] == 1
    assert info["cooldown_remaining_sec"] > 0

    # Reset flushes state
    gg.reset()
    assert gg._last_price == 0.0
    assert gg._gap_detected_at == 0.0
    assert gg._total_gaps == 0
    assert gg.is_entry_blocked(now_ts=t0 + 2.0) is False


def test_wave33_partial_close_initialization_defaults():
    """Verify PartialCloseManager initializes with defaults and clamps ratio boundaries."""
    pcm = PartialCloseManager()
    assert pcm.trigger_pct == 0.50
    assert pcm.close_ratio == 0.50
    assert len(pcm._closed_tickets) == 0
    assert pcm._total_partials == 0
    assert pcm._total_pips_locked == 0.0

    # Custom bounded parameters
    pcm_clamped = PartialCloseManager(trigger_pct=0.99, close_ratio=0.01)
    assert pcm_clamped.trigger_pct == 0.90  # clamped to max 0.90
    assert pcm_clamped.close_ratio == 0.10  # clamped to min 0.10

    # Boolean rejection defaults
    pcm_bool = PartialCloseManager(trigger_pct=True, close_ratio=False)
    assert pcm_bool.trigger_pct == 0.50
    assert pcm_bool.close_ratio == 0.50


def test_wave33_partial_close_lot_quantization():
    """Verify get_close_lot quantizes volume correctly and enforces minimum lot split."""
    pcm = PartialCloseManager(close_ratio=0.50)

    # 0.04 lot split by 50% = 0.02
    assert pcm.get_close_lot(0.04) == 0.02
    assert pcm.get_partial_lot(0.04) == 0.02

    # 0.05 lot split by 50% = 0.025 -> floor to step 0.01 = 0.02
    assert pcm.get_close_lot(0.05) == 0.02

    # 0.02 lot split by 50% = 0.01 (min_lot boundary)
    assert pcm.get_close_lot(0.02) == 0.01

    # Cannot split less than 2x min_lot (0.01 lot cannot be split)
    assert pcm.get_close_lot(0.01) == 0.0
    assert pcm.get_close_lot(0.005) == 0.0

    # Invalid lots return 0.0
    assert pcm.get_close_lot(None) == 0.0
    assert pcm.get_close_lot(True) == 0.0
    assert pcm.get_close_lot(float("nan")) == 0.0
    assert pcm.get_close_lot(-0.04) == 0.0


def test_wave33_partial_close_buy_position_trigger_and_deduplication():
    """Verify BUY position triggers partial close at 50% TP distance and prevents double-firing."""
    pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)
    ticket = 5001
    entry = 2400.0
    tp = 2410.0  # 10.0 points TP distance, 50% trigger = 5.0 points (2405.0)

    # 1. Price moved to 2403.0 (moved 3.0 < 5.0) -> False
    assert pcm.check_position(ticket, "BUY", entry, 2403.0, tp, lot=0.04) is False
    assert ticket not in pcm._closed_tickets

    # 2. Price moved to 2405.5 (moved 5.5 >= 5.0) -> True (trigger partial close)
    assert pcm.check_position(ticket, "BUY", entry, 2405.5, tp, lot=0.04) is True
    assert ticket in pcm._closed_tickets
    assert pcm._total_partials == 1
    assert pcm._total_pips_locked == 5.5

    # 3. Next tick price at 2407.0 -> False (already partially closed)
    assert pcm.check_position(ticket, "BUY", entry, 2407.0, tp, lot=0.02) is False


def test_wave33_partial_close_sell_position_trigger_and_deduplication():
    """Verify SELL position triggers partial close at 50% TP distance and prevents double-firing."""
    pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)
    ticket = 6002
    entry = 2400.0
    tp = 2390.0  # 10.0 points TP distance, 50% trigger = 5.0 points (2395.0)

    # 1. Price moved to 2397.0 (moved 3.0 < 5.0) -> False
    assert pcm.check_position(ticket, "SELL", entry, 2397.0, tp, lot=0.04) is False

    # 2. Price dropped to 2394.0 (moved 6.0 >= 5.0) -> True
    assert pcm.check_position(ticket, "SELL", entry, 2394.0, tp, lot=0.04) is True
    assert ticket in pcm._closed_tickets
    assert pcm._total_partials == 1

    # 3. Next tick at 2392.0 -> False
    assert pcm.check_position(ticket, "SELL", entry, 2392.0, tp, lot=0.02) is False


def test_wave33_partial_close_ticket_cleanup_and_telemetry():
    """Verify ticket removal, reset state flushing, invalid input handling, and info telemetry."""
    pcm = PartialCloseManager()
    ticket = 7003

    # Position trigger
    pcm.check_position(ticket, "BUY", 2400.0, 2406.0, 2410.0, lot=0.04)
    assert ticket in pcm._closed_tickets

    # remove_ticket / close_ticket cleanup
    pcm.close_ticket(ticket)
    assert ticket not in pcm._closed_tickets

    # Invalid input guards return False
    assert pcm.check_position(None, "BUY", 2400.0, 2406.0, 2410.0) is False
    assert pcm.check_position(ticket, "HOLD", 2400.0, 2406.0, 2410.0) is False
    assert pcm.check_position(ticket, "BUY", None, 2406.0, 2410.0) is False
    assert pcm.check_position(ticket, "BUY", 2400.0, float("nan"), 2410.0) is False
    assert pcm.check_position(ticket, "BUY", 2400.0, 2406.0, 2410.0, lot=True) is False
    assert pcm.check_position(ticket, "BUY", 2400.0, 2406.0, 2410.0, lot=0.01) is False  # lot < 0.02

    info = pcm.info()
    assert info["wave"] == 33
    assert info["name"] == "PartialCloseManager"
    assert info["total_partials"] == 1
    assert info["active_closed_tickets_count"] == 0

    pcm.reset()
    info_reset = pcm.info()
    assert info_reset["total_partials"] == 0
    assert info_reset["total_pips_locked"] == 0.0
