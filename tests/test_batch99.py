"""
tests/test_batch99.py
Batch 99 Unit Tests: Trailing Stop Manager (wave34) & Overnight/Weekend Guard (wave35).
Expands test baseline beyond 1,227+ passing tests to 1,237+ passing tests.
Verifies:
1. wave34: TrailingStopManager initialization defaults, lot quantization, and price quantization.
2. wave34: BUY trailing stop activation at threshold (15 pips) and dynamic SL ratcheting behind peak price.
3. wave34: SELL trailing stop activation at threshold (15 pips) and dynamic SL ratcheting behind trough price.
4. wave34: Ticket closure state cleanup and fail-closed handling on non-finite, boolean, or invalid inputs.
5. wave34: TrailingStopManager reset() clearing and info() diagnostic telemetry reporting.
6. wave35: OvernightGuard initialization defaults, constants, and deterministic UTC datetime injection.
7. wave35: Midweek normal session clearance (Wednesday afternoon) permitting entries without restriction.
8. wave35: Friday market close pre-gap entry block and position force-close trigger (Friday >= 20:30 UTC).
9. wave35: Saturday/Sunday weekend market closure blocking and daily rollover window lockout (21:45-22:15 UTC).
10. wave35: OvernightGuard reset() state flushing and info() telemetry diagnostics introspection.
"""

from datetime import datetime, timezone
import pytest

from wave34_trailing_stop import TrailingStopManager
from wave35_overnight_guard import OvernightGuard


def test_wave34_initialization_and_quantization_helpers():
    """Verify TrailingStopManager initializes with defaults and correctly quantizes lots and prices."""
    tsm = TrailingStopManager()
    assert tsm.profit_trigger_pips == 15.0
    assert tsm.trail_pips == 10.0
    assert tsm.trail_step_pips == 1.0
    assert len(tsm._best_prices) == 0
    assert len(tsm._trailing_active) == 0

    # Lot quantization
    assert tsm.quantize_lot(0.024) == 0.02
    assert tsm.quantize_lot(0.026) == 0.02
    assert tsm.quantize_lot(-0.05) == 0.0
    assert tsm.quantize_lot(0.005, min_lot=0.01) == 0.01

    # Price quantization
    assert tsm.quantize_price(2400.1234, pip_size=0.1) == 2400.123
    assert tsm.quantize_price(2400.1234, digits=2) == 2400.12
    assert tsm.quantize_price(1.085432, digits=5) == 1.08543


def test_wave34_buy_trailing_stop_activation_and_advancement():
    """Verify BUY trailing stop activates once in profit >= 15 pips and ratchets SL upward."""
    tsm = TrailingStopManager(profit_trigger_pips=15.0, trail_pips=10.0, trail_step_pips=1.0)
    ticket = 1001
    entry_price = 2400.0
    initial_sl = 2395.0
    pip_size = 0.1  # 1 pip = 0.10 price units (XAUUSD)

    # 1. Price rises to 2401.0 (profit = 1.0 = 10 pips < 15 pips trigger) -> None
    sl_1 = tsm.update(ticket, "BUY", entry_price, 2401.0, initial_sl, pip_size=pip_size)
    assert sl_1 is None
    assert ticket not in tsm._trailing_active

    # 2. Price rises to 2401.8 (profit = 1.8 = 18 pips >= 15 pips trigger)
    # Trail distance = 10 pips * 0.1 = 1.0. New SL = 2401.8 - 1.0 = 2400.8
    sl_2 = tsm.update(ticket, "BUY", entry_price, 2401.8, initial_sl, pip_size=pip_size)
    assert sl_2 == 2400.8
    assert ticket in tsm._trailing_active
    assert tsm._best_prices[ticket] == 2401.8

    # 3. Price retraces to 2401.4 -> Best price remains 2401.8, SL not moved
    sl_3 = tsm.update(ticket, "BUY", entry_price, 2401.4, sl_2, pip_size=pip_size)
    assert sl_3 is None

    # 4. Price surges to 2402.5 -> New best = 2402.5, New SL = 2402.5 - 1.0 = 2401.5
    sl_4 = tsm.update(ticket, "BUY", entry_price, 2402.5, sl_2, pip_size=pip_size)
    assert sl_4 == 2401.5
    assert tsm._best_prices[ticket] == 2402.5


def test_wave34_sell_trailing_stop_activation_and_advancement():
    """Verify SELL trailing stop activates once in profit >= 15 pips and ratchets SL downward."""
    tsm = TrailingStopManager(profit_trigger_pips=15.0, trail_pips=10.0, trail_step_pips=1.0)
    ticket = 2002
    entry_price = 2400.0
    initial_sl = 2405.0
    pip_size = 0.1

    # 1. Price drops to 2399.0 (profit = 10 pips < 15 pips trigger) -> None
    sl_1 = tsm.update(ticket, "SELL", entry_price, 2399.0, initial_sl, pip_size=pip_size)
    assert sl_1 is None

    # 2. Price drops to 2398.2 (profit = 1.8 = 18 pips >= 15 pips trigger)
    # New SL = 2398.2 + 1.0 = 2399.2
    sl_2 = tsm.update(ticket, "SELL", entry_price, 2398.2, initial_sl, pip_size=pip_size)
    assert sl_2 == 2399.2
    assert ticket in tsm._trailing_active

    # 3. Retracement to 2398.6 -> SL not moved
    sl_3 = tsm.update(ticket, "SELL", entry_price, 2398.6, sl_2, pip_size=pip_size)
    assert sl_3 is None

    # 4. Price plunges to 2397.0 -> New SL = 2397.0 + 1.0 = 2398.0
    sl_4 = tsm.update(ticket, "SELL", entry_price, 2397.0, sl_2, pip_size=pip_size)
    assert sl_4 == 2398.0


def test_wave34_close_ticket_and_invalid_inputs():
    """Verify close_ticket cleans up ticket tracking and invalid inputs return None."""
    tsm = TrailingStopManager()
    ticket = 3003
    tsm.update(ticket, "BUY", 2400.0, 2402.0, 2395.0)
    assert ticket in tsm._trailing_active

    tsm.close_ticket(ticket)
    assert ticket not in tsm._trailing_active
    assert ticket not in tsm._best_prices

    # Invalid inputs return None
    assert tsm.update(None, "BUY", 2400.0, 2402.0, 2395.0) is None
    assert tsm.update(ticket, "HOLD", 2400.0, 2402.0, 2395.0) is None
    assert tsm.update(ticket, "BUY", None, 2402.0, 2395.0) is None
    assert tsm.update(ticket, "BUY", 2400.0, float("nan"), 2395.0) is None
    assert tsm.update(ticket, "BUY", 2400.0, 2402.0, True) is None


def test_wave34_reset_and_info_introspection():
    """Verify reset() clears trailing state and info() outputs diagnostic telemetry."""
    tsm = TrailingStopManager()
    tsm.update(4004, "BUY", 2400.0, 2402.0, 2395.0)

    info = tsm.info()
    assert info["wave"] == 34
    assert info["name"] == "TrailingStopManager"
    assert info["profit_trigger_pips"] == 15.0
    assert info["trail_pips"] == 10.0
    assert info["currently_trailing"] == 1
    assert info["total_trails_activated"] == 1

    tsm.reset()
    info_reset = tsm.info()
    assert info_reset["currently_trailing"] == 0
    assert info_reset["total_trails_activated"] == 0
    assert info_reset["total_sl_moves"] == 0


def test_wave35_initialization_defaults_and_constants():
    """Verify OvernightGuard initializes with defaults and standard time constants."""
    og = OvernightGuard()
    assert og.FRIDAY_BLOCK_HOUR == 20
    assert og.FRIDAY_BLOCK_MINUTE == 30
    assert og.ROLLOVER_START_HOUR == 21
    assert og.ROLLOVER_START_MIN == 45
    assert og.ROLLOVER_END_HOUR == 22
    assert og.ROLLOVER_END_MIN == 15
    assert og.friday_block_active is False
    assert og.rollover_block_active is False
    assert og.force_close_triggered is False


def test_wave35_normal_midweek_trading_clearance():
    """Verify normal midweek session (Wednesday afternoon) allows trading without restriction."""
    og = OvernightGuard()
    dt_wednesday = datetime(2026, 10, 21, 14, 30, 0, tzinfo=timezone.utc)

    assert og.is_entry_blocked(now_dt=dt_wednesday) is False
    assert og.is_blocked(now_dt=dt_wednesday) is False
    allowed, reason = og.is_trading_allowed(now_dt=dt_wednesday)
    assert allowed is True
    assert reason == ""
    assert og.get_reason(now_dt=dt_wednesday) == "CLEAR"
    assert og.should_force_close_all(now_dt=dt_wednesday) is False


def test_wave35_friday_market_close_block_and_force_close():
    """Verify Friday market close triggers weekend gap block and force-close signal at 20:30 UTC."""
    og = OvernightGuard()

    # Friday 20:15 UTC (before cutoff) -> Allowed
    dt_fri_early = datetime(2026, 10, 23, 20, 15, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_fri_early) is False
    assert og.should_force_close_all(now_dt=dt_fri_early) is False

    # Friday 20:30 UTC (cutoff reached) -> Blocked & Force-close triggered
    dt_fri_cutoff = datetime(2026, 10, 23, 20, 30, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_fri_cutoff) is True
    assert og.friday_block_active is True
    assert og.should_force_close_all(now_dt=dt_fri_cutoff) is True
    assert og.total_force_closes == 1
    assert og.total_weekend_blocks == 1

    allowed, reason = og.is_trading_allowed(now_dt=dt_fri_cutoff)
    assert allowed is False
    assert "weekend holding protection active" in reason
    assert "FRIDAY_CLOSE_BLOCK: weekend gap risk" in og.get_reason(now_dt=dt_fri_cutoff)


def test_wave35_weekend_and_daily_rollover_blocking():
    """Verify entry blocking across Saturday/Sunday weekend and daily rollover window."""
    og = OvernightGuard()

    # Saturday 12:00 UTC -> Blocked
    dt_sat = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_sat) is True

    # Sunday 18:00 UTC -> Blocked
    dt_sun = datetime(2026, 10, 25, 18, 0, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_sun) is True

    # Tuesday 22:00 UTC (inside daily rollover 21:45-22:15 UTC) -> Blocked
    dt_rollover = datetime(2026, 10, 20, 22, 0, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_rollover) is True
    assert og.rollover_block_active is True
    assert "ROLLOVER_BLOCK: 21:45-22:15 UTC daily rollover" in og.get_reason(now_dt=dt_rollover)

    # Tuesday 22:20 UTC (after rollover window) -> Unblocked
    dt_post_rollover = datetime(2026, 10, 20, 22, 20, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_post_rollover) is False
    assert og.rollover_block_active is False


def test_wave35_reset_and_info_introspection():
    """Verify reset() flushes state and info() outputs diagnostic telemetry."""
    og = OvernightGuard()
    dt_fri = datetime(2026, 10, 23, 20, 45, 0, tzinfo=timezone.utc)
    og.is_entry_blocked(now_dt=dt_fri)
    og.should_force_close_all(now_dt=dt_fri)

    info = og.info(now_dt=dt_fri)
    assert info["wave"] == 35
    assert info["name"] == "OvernightGuard"
    assert info["friday_block_active"] is True
    assert info["force_close_active"] is True
    assert info["is_blocked"] is True
    assert info["total_weekend_blocks"] == 1
    assert info["total_force_closes"] == 1

    og.reset()
    info_reset = og.info(now_dt=datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc))
    assert info_reset["friday_block_active"] is False
    assert info_reset["force_close_active"] is False
    assert info_reset["is_blocked"] is False
    assert info_reset["total_weekend_blocks"] == 0
    assert info_reset["total_force_closes"] == 0
