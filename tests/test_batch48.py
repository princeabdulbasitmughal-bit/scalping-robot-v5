"""
Batch 48 Test Suite:
1. wave31_reversal_detector.py bar validation and RSI divergence detection
2. wave32_gap_guard.py tick-to-tick gap detection, lockout timer, and reset
3. wave33_partial_close.py lot quantization and 50% TP milestone execution
4. wave34_trailing_stop.py price/lot quantization and dynamic trailing SL moves
5. wave35_overnight_guard.py Friday cutoff, weekend block, and rollover window
6. wave36_spread_momentum.py rapid spread widening detection and entry lockout
7. wave37_entry_cooldown.py asymmetric win/loss cooldowns and reset behavior
8. wave38_volatility_breaker.py short vs baseline ATR ratio spike breaker
9. wave39_drawdown_pause.py 30-minute rolling equity peak drawdown pause
10. wave40_profit_target_shift.py dynamic TP factor shift on daily PnL targets
"""
import datetime
from datetime import timezone
import math
import time

import pytest

from wave31_reversal_detector import ReversalDetector
from wave32_gap_guard import GapGuard
from wave33_partial_close import PartialCloseManager
from wave34_trailing_stop import TrailingStopManager
from wave35_overnight_guard import OvernightGuard
from wave36_spread_momentum import SpreadMomentumGuard
from wave37_entry_cooldown import EntryCooldown
from wave38_volatility_breaker import VolatilityBreaker
from wave39_drawdown_pause import DrawdownPause
from wave40_profit_target_shift import ProfitTargetShift


# ── Test 1: Wave 31 Reversal Detector ─────────────────────────────────────────
def test_wave31_reversal_detector():
    """Verify ReversalDetector bar validation and indicator divergence logic."""
    rd = ReversalDetector(rsi_period=10, overbought=75.0, oversold=25.0)

    # Bar validation
    assert rd.validate_bar({"open": 2400.0, "high": 2405.0, "low": 2398.0, "close": 2403.0}) == (2400.0, 2405.0, 2398.0, 2403.0)
    assert rd.validate_bar((2400.0, 2405.0, 2398.0, 2403.0)) == (2400.0, 2405.0, 2398.0, 2403.0)
    assert rd.validate_bar(None) is None
    assert rd.validate_bar({"open": float("nan"), "high": 2405.0, "low": 2398.0, "close": 2403.0}) is None

    # Oversold price series feeding
    for i in range(15):
        rd.update_price(2410.0 - (i * 0.8))

    sig, conf, reason = rd.get_reversal_signal()
    assert sig in ("BUY", "HOLD")
    assert 0.0 <= conf <= 1.0


# ── Test 2: Wave 32 Gap Guard ─────────────────────────────────────────────────
def test_wave32_gap_guard():
    """Verify GapGuard detects abnormal price gaps and enforces entry lockout."""
    gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=60.0, pip_size=0.1)

    t0 = 10000.0
    gg.update_price(2400.0, now_ts=t0)
    assert gg.is_blocked(now_ts=t0) is False

    # Normal tick (0.2 price change = 2 pips < 5 pips)
    gg.update_price(2400.2, now_ts=t0 + 1)
    assert gg.is_blocked(now_ts=t0 + 1) is False

    # Large gap jump (1.0 price change = 10 pips >= 5 pips threshold)
    gg.update_price(2401.2, now_ts=t0 + 2)
    assert gg.is_blocked(now_ts=t0 + 2) is True
    allowed_g, reason_g = gg.is_trading_allowed(now_ts=t0 + 2)
    assert allowed_g is False and "GAP_GUARD" in reason_g

    # Halfway through lockout
    assert gg.is_blocked(now_ts=t0 + 30) is True

    # Lockout expires after 60s
    assert gg.is_blocked(now_ts=t0 + 65) is False

    # Reset clears state
    gg.update_price(2403.0, now_ts=t0 + 70)
    gg.reset()
    assert gg.is_blocked(now_ts=t0 + 70) is False


# ── Test 3: Wave 33 Partial Close Manager ─────────────────────────────────────
def test_wave33_partial_close():
    """Verify PartialCloseManager lot quantization and 50% TP milestone execution."""
    pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)

    # Lot quantization
    assert pcm.get_close_lot(0.04) == 0.02
    assert pcm.get_close_lot(0.05) == 0.02
    assert pcm.get_close_lot(0.01) == 0.0  # too small to split

    # BUY position: entry 2400.0, TP 2410.0 (10.0 points total)
    # At 2405.0, it reaches exactly 50% TP distance
    assert pcm.check_position("TICKET_1", "BUY", 2400.0, 2402.0, 2410.0, lot=0.04) is False
    assert pcm.check_position("TICKET_1", "BUY", 2400.0, 2405.0, 2410.0, lot=0.04) is True

    # Second check returns False (already closed)
    assert pcm.check_position("TICKET_1", "BUY", 2400.0, 2406.0, 2410.0, lot=0.04) is False

    # Cleanup ticket
    pcm.remove_ticket("TICKET_1")
    assert pcm.check_position("TICKET_1", "BUY", 2400.0, 2405.0, 2410.0, lot=0.04) is True


# ── Test 4: Wave 34 Trailing Stop Manager ─────────────────────────────────────
def test_wave34_trailing_stop():
    """Verify TrailingStopManager price/lot quantization and dynamic trailing stop movement."""
    tsm = TrailingStopManager(profit_trigger_pips=15.0, trail_pips=10.0, trail_step_pips=1.0)

    # Quantization helpers
    assert tsm.quantize_lot(0.0345) == 0.03
    assert tsm.quantize_price(2400.1264, pip_size=0.1) == 2400.126

    # BUY position: entry 2400.0, current SL 2397.0 (pip_size=0.1 -> 15 pips = 1.5 price points)
    # Price 2401.0 is 10 pips in profit -> trailing not active (< 15 pips)
    assert tsm.update("TICKET_2", "BUY", 2400.0, 2401.0, 2397.0, pip_size=0.1) is None

    # Price moves to 2402.0 (20 pips profit >= 15 pips trigger)
    # Trail SL should be 10 pips behind current price: 2402.0 - 1.0 = 2401.0
    new_sl = tsm.update("TICKET_2", "BUY", 2400.0, 2402.0, 2397.0, pip_size=0.1)
    assert new_sl == 2401.0

    # Price drops to 2401.5 -> SL must NEVER loosen
    assert tsm.update("TICKET_2", "BUY", 2400.0, 2401.5, 2401.0, pip_size=0.1) is None


# ── Test 5: Wave 35 Overnight Guard ───────────────────────────────────────────
def test_wave35_overnight_guard():
    """Verify OvernightGuard blocks weekend entries, Friday cutoffs, and rollover windows."""
    og = OvernightGuard()

    # Friday 20:35 UTC (after 20:30 cutoff) -> blocked and should force close
    dt_fri_block = datetime.datetime(2026, 10, 16, 20, 35, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_fri_block) is True
    assert og.should_force_close_all(now_dt=dt_fri_block) is True

    # Saturday (weekend) -> blocked
    dt_sat = datetime.datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_sat) is True

    # Wednesday 22:00 UTC (inside daily rollover 21:45-22:15) -> blocked
    dt_rollover = datetime.datetime(2026, 10, 14, 22, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_rollover) is True
    assert og.should_force_close_all(now_dt=dt_rollover) is False  # rollover does not force close

    # Wednesday 14:00 UTC (normal trading hours) -> allowed
    dt_normal = datetime.datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_normal) is False


# ── Test 6: Wave 36 Spread Momentum Guard ─────────────────────────────────────
def test_wave36_spread_momentum():
    """Verify SpreadMomentumGuard triggers entry lockout on 3x spread expansion."""
    smg = SpreadMomentumGuard()

    t0 = 20000.0
    # Baseline spreads: 1.0, 1.0, 1.0
    smg.update(1.0, now_ts=t0)
    smg.update(1.0, now_ts=t0 + 1)
    smg.update(1.0, now_ts=t0 + 2)
    assert smg.is_entry_blocked(now_ts=t0 + 2) is False

    # Spread explodes to 3.5 (3.5x baseline >= 3.0 threshold)
    smg.update(3.5, now_ts=t0 + 3)
    assert smg.is_entry_blocked(now_ts=t0 + 3) is True
    assert smg.seconds_remaining(now_ts=t0 + 3) == 60.0

    # Lockout expires after 60s
    assert smg.is_entry_blocked(now_ts=t0 + 65) is False


# ── Test 7: Wave 37 Entry Cooldown ────────────────────────────────────────────
def test_wave37_entry_cooldown():
    """Verify EntryCooldown enforces 60s win cooldown and 120s loss cooldown."""
    ec = EntryCooldown()

    t0 = 30000.0
    # Winning trade close -> 60s cooldown
    ec.record_trade_close(was_win=True, pnl=50.0, now_ts=t0)
    assert ec.is_entry_blocked(now_ts=t0 + 30) is True
    assert ec.seconds_remaining(now_ts=t0 + 30) == 30.0
    assert ec.is_entry_blocked(now_ts=t0 + 61) is False

    # Losing trade close -> 120s cooldown (revenge trading prevention)
    ec.record_trade_close(was_win=False, pnl=-40.0, now_ts=t0 + 100)
    assert ec.is_entry_blocked(now_ts=t0 + 150) is True
    assert ec.seconds_remaining(now_ts=t0 + 100) == 120.0

    # Manual force reset
    ec.force_reset()
    assert ec.is_entry_blocked(now_ts=t0 + 150) is False


# ── Test 8: Wave 38 Volatility Breaker ─────────────────────────────────────────
def test_wave38_volatility_breaker():
    """Verify VolatilityBreaker blocks trading during sustained elevated volatility."""
    vb = VolatilityBreaker()

    t0 = 40000.0
    # Seed baseline prices with low volatility (step 0.05) over 100 ticks
    price = 2400.0
    for i in range(100):
        price += 0.05 if i % 2 == 0 else -0.05
        vb.update(price, now_ts=t0 + i)

    assert vb.is_entry_blocked(now_ts=t0 + 100) is False

    # Inject sharp volatility surge over short window (step 1.5)
    for i in range(20):
        price += 1.5 if i % 2 == 0 else -1.5
        vb.update(price, now_ts=t0 + 101 + i)

    # Volatility ratio should exceed 2.5x triggering block
    assert vb.is_entry_blocked(now_ts=t0 + 121) is True
    assert vb.seconds_remaining(now_ts=t0 + 121) <= 90.0


# ── Test 9: Wave 39 Drawdown Pause ────────────────────────────────────────────
def test_wave39_drawdown_pause():
    """Verify DrawdownPause blocks entries when 30-minute equity drop exceeds 1.5%."""
    dp = DrawdownPause()

    t0 = 50000.0
    # Peak equity: $10,000.0
    dp.update(10000.0, now_ts=t0)
    dp.update(10000.0, now_ts=t0 + 60)
    assert dp.is_entry_blocked(now_ts=t0 + 60) is False

    # 1.0% drop ($9,900.0) -> below 1.5% threshold -> allowed
    dp.update(9900.0, now_ts=t0 + 120)
    assert dp.is_entry_blocked(now_ts=t0 + 120) is False

    # 2.0% drop ($9,800.0 vs peak $10,000.0) -> triggers 15-min (900s) pause
    dp.update(9800.0, now_ts=t0 + 180)
    assert dp.is_entry_blocked(now_ts=t0 + 180) is True

    # 5 minutes later still paused
    assert dp.is_entry_blocked(now_ts=t0 + 480) is True

    # Equity recovers to $9,950.0 (drawdown 0.5% < 1.5% threshold)
    dp.update(9950.0, now_ts=t0 + 1100)
    assert dp.is_entry_blocked(now_ts=t0 + 1100) is False


# ── Test 10: Wave 40 Profit Target Shift ───────────────────────────────────────
def test_wave40_profit_target_shift():
    """Verify ProfitTargetShift dynamically adjusts TP pips based on daily PnL."""
    pts = ProfitTargetShift()

    # Normal mode: 1.0x factor
    assert pts.adjust_tp(raw_tp_pips=40.0, daily_pnl=50.0) == 40.0
    assert pts.mode == "NORMAL"

    # Profit lock mode: daily PnL >= +$150.0 -> 0.80x factor
    assert pts.adjust_tp(raw_tp_pips=40.0, daily_pnl=160.0) == 32.0
    assert pts.mode == "PROFIT_LOCK"

    # Recovery mode: daily PnL <= -$100.0 -> 1.10x factor
    assert pts.adjust_tp(raw_tp_pips=40.0, daily_pnl=-120.0) == 44.0
    assert pts.mode == "RECOVERY"

    # Reset clears to NORMAL
    pts.reset()
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0
