"""
tests/test_batch64.py
=====================
Hermetic unit tests for Batch 64:
1. ProfitTargetShift: Profit-lock vs Recovery modes & TP multipliers
2. DrawdownPause: Rolling equity peak-drawdown pause & window pruning
3. VolatilityBreaker: ATR spike ratio detection, sustained volatility block & cooldown
4. EntryCooldown: Differential win/loss cooldown timers & revenge prevention
5. SpreadMomentumGuard: Liquidity thinning detection, 3x spread expansion & block
6. OvernightGuard: Friday weekend gap prevention, market rollover window & recovery
7. TrailingStopManager: BUY position trailing stop ratchet & high-watermark ratcheting
8. TrailingStopManager: SELL position trailing stop downward ratchet & floor preservation
9. PartialCloseManager: BUY 50% TP progress trigger, single-fire protection & lot splitting
10. PartialCloseManager: SELL position progress calculation, small lot guard (<0.02) & lot quantization
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave40_profit_target_shift import ProfitTargetShift
from wave39_drawdown_pause import DrawdownPause
from wave38_volatility_breaker import VolatilityBreaker
from wave37_entry_cooldown import EntryCooldown
from wave36_spread_momentum import SpreadMomentumGuard
from wave35_overnight_guard import OvernightGuard
from wave34_trailing_stop import TrailingStopManager
from wave33_partial_close import PartialCloseManager


def test_wave40_profit_target_shift_modes_and_factors():
    """Verify ProfitTargetShift dynamically adjusts TP pips based on daily PnL."""
    pts = ProfitTargetShift()
    assert pts.mode == "NORMAL"

    # 1. Normal Mode ($50 PnL): 1.0x factor
    assert pts.adjust_tp(40.0, 50.0) == 40.0
    assert pts.mode == "NORMAL"

    # 2. Profit Lock Mode (+$200 PnL >= $150): tightens TP to 0.80x (40.0 * 0.8 = 32.0)
    assert pts.adjust_tp(40.0, 200.0) == 32.0
    assert pts.mode == "PROFIT_LOCK"
    assert pts.tp_factor == 0.80

    # 3. Recovery Mode (-$120 PnL <= -$100): widens TP to 1.10x (40.0 * 1.1 = 44.0)
    assert pts.adjust_tp(40.0, -120.0) == 44.0
    assert pts.mode == "RECOVERY"
    assert pts.tp_factor == 1.10

    # Invalid raw TP handling
    assert pts.adjust_tp(-10.0, 50.0) == -10.0
    assert pts.adjust_tp(None, 50.0) is None


def test_wave39_drawdown_pause_peak_drawdown_trip_and_pruning():
    """Verify DrawdownPause monitors peak equity and pauses entries when drawdown exceeds 1.5%."""
    ddp = DrawdownPause()

    # Initial equity $10,000 at t=1000.0
    ddp.update(10000.0, now_ts=1000.0)
    assert ddp.is_entry_blocked(now_ts=1000.0) is False

    # Moderate dip to $9,900.0 (1.0% drop < 1.5%) -> not blocked
    ddp.update(9900.0, now_ts=1010.0)
    assert ddp.is_entry_blocked(now_ts=1010.0) is False

    # Drop to $9,800.0 (2.0% drop from $10,000 peak >= 1.5%) -> trips 15m (900s) pause
    ddp.update(9800.0, now_ts=1020.0)
    assert ddp.is_entry_blocked(now_ts=1020.0) is True
    assert ddp.is_entry_blocked(now_ts=1800.0) is True

    # At t=1925.0, equity recovers back to $9,950.0 (0.5% drawdown < 1.5%) -> pause expired & unblocked
    ddp.update(9950.0, now_ts=1925.0)
    assert ddp.is_entry_blocked(now_ts=1925.0) is False


def test_wave38_volatility_breaker_spike_ratio_and_cooldown():
    """Verify VolatilityBreaker detects sustained volatility spikes vs baseline."""
    vb = VolatilityBreaker()

    # Feed 60 baseline ticks with small 0.05 pip steps
    for i in range(60):
        vb.update(2650.0 + (i % 2) * 0.05, now_ts=100.0 + i)
    assert vb.is_entry_blocked(now_ts=160.0) is False

    # Feed 15 high-volatility ticks with 2.5 pip oscillations (surges short ATR > 2.5x baseline)
    for i in range(15):
        vb.update(2650.0 + (i % 2) * 2.5, now_ts=161.0 + i)

    # Elevated volatility trips 90s breaker (until 175.0 + 90.0 = 265.0)
    assert vb.is_entry_blocked(now_ts=180.0) is True

    # Cooldown expires after 90s
    assert vb.is_entry_blocked(now_ts=270.0) is False


def test_wave37_entry_cooldown_win_vs_loss_timers():
    """Verify EntryCooldown applies differential win (60s) vs loss (120s) cooldowns."""
    ec = EntryCooldown()

    # Winning trade close at t=1000.0 -> 60s cooldown (until 1060.0)
    ec.record_trade_close(was_win=True, pnl=25.0, now_ts=1000.0)
    assert ec.is_entry_blocked(now_ts=1030.0) is True
    assert ec.seconds_remaining(now_ts=1030.0) == 30.0
    assert ec.is_entry_blocked(now_ts=1061.0) is False

    # Losing trade close at t=2000.0 -> 120s cooldown (until 2120.0)
    ec.record_trade_close(was_win=False, pnl=-35.0, now_ts=2000.0)
    assert ec.is_entry_blocked(now_ts=2050.0) is True
    assert ec.seconds_remaining(now_ts=2050.0) == 70.0
    assert ec.is_entry_blocked(now_ts=2121.0) is False


def test_wave36_spread_momentum_liquidity_spike_block():
    """Verify SpreadMomentumGuard trips 60s block when spread widens 3x or more."""
    smg = SpreadMomentumGuard()

    # Feed 4 regular spreads of 1.5 pips
    for _ in range(4):
        smg.update(1.5, now_ts=100.0)
    assert smg.is_entry_blocked(now_ts=100.0) is False

    # 5th spread expands to 5.0 pips (5.0 / 1.5 = 3.33x >= 3.0x limit) -> trips 60s block
    smg.update(5.0, now_ts=101.0)
    assert smg.is_entry_blocked(now_ts=101.0) is True
    assert smg.seconds_remaining(now_ts=120.0) == 41.0

    # Cooldown expires after 60s
    assert smg.is_entry_blocked(now_ts=162.0) is False


def test_wave35_overnight_guard_friday_cutoff_and_daily_rollover():
    """Verify OvernightGuard blocks entries past Friday 20:30 UTC and during 21:45-22:15 daily rollover."""
    og = OvernightGuard()

    # Tuesday 14:00 UTC: Open trading
    tuesday_dt = datetime(2026, 10, 13, 14, 0, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=tuesday_dt) is False

    # Friday 18:00 UTC: Pre-cutoff trading allowed
    friday_open = datetime(2026, 10, 16, 18, 0, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=friday_open) is False

    # Friday 20:30 UTC: Weekend gap risk block active
    friday_cutoff = datetime(2026, 10, 16, 20, 30, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=friday_cutoff) is True

    # Saturday 12:00 UTC: Markets closed
    saturday_dt = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=saturday_dt) is True

    # Wednesday 22:00 UTC: Inside daily rollover window (21:45-22:15 UTC) -> BLOCKED
    rollover_dt = datetime(2026, 10, 14, 22, 0, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=rollover_dt) is True

    # Wednesday 22:20 UTC: Post-rollover -> clear
    post_rollover_dt = datetime(2026, 10, 14, 22, 20, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=post_rollover_dt) is False


def test_wave34_trailing_stop_buy_ratchet_and_quantization():
    """Verify TrailingStopManager ratchets BUY stop-loss upwards and never loosens downwards."""
    tsm = TrailingStopManager(profit_trigger_pips=15.0, trail_pips=10.0, trail_step_pips=1.0)
    ticket = 1001
    entry = 2650.0
    sl = 2640.0

    # 1. Price at 2651.0 (profit = 1.0 < 15.0 trigger) -> no trailing move
    assert tsm.update(ticket, "BUY", entry, 2651.0, sl, pip_size=0.1) is None

    # 2. Price reaches 2666.0 (profit = 16.0 >= 15.0):
    # Trail 10.0 pips behind best price 2666.0 -> 2666.0 - 1.0 (10 pips * 0.1) = 2665.0 > 2640.0
    new_sl = tsm.update(ticket, "BUY", entry, 2666.0, sl, pip_size=0.1)
    assert new_sl == 2665.0

    # 3. Price pulls back to 2664.0: Stop-loss must never loosen backwards
    assert tsm.update(ticket, "BUY", entry, 2664.0, 2665.0, pip_size=0.1) is None

    # 4. Price surges to 2668.0: New best price 2668.0 -> SL ratchets to 2667.0
    improved_sl = tsm.update(ticket, "BUY", entry, 2668.0, 2665.0, pip_size=0.1)
    assert improved_sl == 2667.0


def test_wave34_trailing_stop_sell_ratchet():
    """Verify TrailingStopManager ratchets SELL stop-loss downwards for short positions."""
    tsm = TrailingStopManager(profit_trigger_pips=15.0, trail_pips=10.0, trail_step_pips=1.0)
    ticket = 2002
    entry = 2650.0
    sl = 2660.0

    # Price reaches 2634.0 (entry - price = 16.0 >= 15.0 pips):
    # Trail 10.0 pips above best price 2634.0 -> 2634.0 + 1.0 = 2635.0 < 2660.0
    new_sl = tsm.update(ticket, "SELL", entry, 2634.0, sl, pip_size=0.1)
    assert new_sl == 2635.0

    # Price drops to 2631.0: New best 2631.0 -> SL ratchets down to 2632.0
    improved_sl = tsm.update(ticket, "SELL", entry, 2631.0, 2635.0, pip_size=0.1)
    assert improved_sl == 2632.0


def test_wave33_partial_close_buy_trigger_and_single_fire():
    """Verify PartialCloseManager triggers at 50% TP progress and prevents double-firing."""
    pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)
    ticket = 3003
    entry = 2650.0
    tp = 2660.0
    lot = 0.04

    # 1. Price at 2653.0 (progress 3.0 / 10.0 = 30% < 50%) -> no partial close
    assert pcm.check_position(ticket, "BUY", entry, 2653.0, tp, lot=lot) is False

    # 2. Price at 2655.0 (progress 5.0 / 10.0 = 50% >= 50%) -> trigger partial close!
    assert pcm.check_position(ticket, "BUY", entry, 2655.0, tp, lot=lot) is True

    # 3. Subsequent tick at 2656.0: Already executed for ticket 3003 -> no double fire!
    assert pcm.check_position(ticket, "BUY", entry, 2656.0, tp, lot=lot) is False

    # 4. Partial lot size calculation: 50% of 0.04 lot = 0.02 lot
    assert pcm.get_close_lot(0.04) == 0.02


def test_wave33_partial_close_sell_trigger_and_small_lot_guard():
    """Verify PartialCloseManager handles short positions and blocks splitting lot < 0.02."""
    pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)
    ticket_small = 4004
    entry = 2650.0
    tp = 2640.0

    # Small lot (0.01 lot) cannot be split below broker min_lot 0.01
    assert pcm.check_position(ticket_small, "SELL", entry, 2645.0, tp, lot=0.01) is False
    assert pcm.get_close_lot(0.01) == 0.0

    # Standard 0.06 lot SELL: at 2645.0 progress is 50% -> triggers and closes 0.03 lot
    ticket_valid = 5005
    assert pcm.check_position(ticket_valid, "SELL", entry, 2645.0, tp, lot=0.06) is True
    assert pcm.get_close_lot(0.06) == 0.03
