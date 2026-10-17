"""
Tests for Batch 31 Hardening:
- wave36_spread_momentum.py
- wave37_entry_cooldown.py
- wave38_volatility_breaker.py
- wave39_drawdown_pause.py
- wave40_profit_target_shift.py
- wave41_session_spread_limiter.py
- wave42_tick_volume_filter.py
- wave43_win_rate_guard.py
- wave45_london_open_booster.py
- wave46_lot_recovery_ladder.py
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave36_spread_momentum import SpreadMomentumGuard
from wave37_entry_cooldown import EntryCooldown
from wave38_volatility_breaker import VolatilityBreaker
from wave39_drawdown_pause import DrawdownPause
from wave40_profit_target_shift import ProfitTargetShift
from wave41_session_spread_limiter import SessionSpreadLimiter
from wave42_tick_volume_filter import TickVolumeFilter
from wave43_win_rate_guard import WinRateGuard
from wave45_london_open_booster import LondonOpenBooster
from wave46_lot_recovery_ladder import LotRecoveryLadder


def test_wave36_spread_momentum_guard():
    guard = SpreadMomentumGuard()
    guard.reset()
    t0 = 1000.0

    # Feed normal baseline spreads
    for i in range(5):
        guard.update(1.0, now_ts=t0 + i)
    assert not guard.is_entry_blocked(now_ts=t0 + 5)
    assert guard.seconds_remaining(now_ts=t0 + 5) == 0.0

    # Feed a 3.5x spike (baseline is 1.0, current 3.5)
    guard.update(3.5, now_ts=t0 + 6)
    assert guard.is_entry_blocked(now_ts=t0 + 6)
    assert guard.seconds_remaining(now_ts=t0 + 6) == 60.0

    # Deterministic telemetry info check
    info = guard.info(now_ts=t0 + 6)
    assert info["currently_blocked"] is True
    assert info["total_spikes_detected"] == 1

    # After 61 seconds, block has expired
    assert not guard.is_entry_blocked(now_ts=t0 + 67)

    # Reentrant lock verification
    with guard._lock:
        with guard._lock:
            guard.reset()
    assert not guard.is_entry_blocked(now_ts=t0 + 6)


def test_wave37_entry_cooldown():
    ec = EntryCooldown()
    ec.reset()
    t0 = 2000.0

    # Winning trade sets 60s cooldown
    ec.record_trade_close(was_win=True, pnl=15.0, now_ts=t0)
    assert ec.is_entry_blocked(now_ts=t0)
    assert ec.is_entry_blocked(now_ts=t0 + 59)
    assert not ec.is_entry_blocked(now_ts=t0 + 61)
    assert ec.total_win_cooldowns == 1

    # Losing trade sets 120s cooldown
    ec.record_trade_close(was_win=False, pnl=-25.0, now_ts=t0 + 100)
    assert ec.is_entry_blocked(now_ts=t0 + 150)
    assert not ec.is_entry_blocked(now_ts=t0 + 221)
    assert ec.total_loss_cooldowns == 1

    # Force reset clears active cooldown
    ec.record_trade_close(was_win=False, pnl=-10.0, now_ts=t0 + 300)
    assert ec.is_entry_blocked(now_ts=t0 + 310)
    ec.force_reset()
    assert not ec.is_entry_blocked(now_ts=t0 + 310)

    # Comprehensive reset clears counts too
    info = ec.info(now_ts=t0 + 310)
    assert info["currently_blocked"] is False
    ec.reset()
    assert ec.total_cooldowns_triggered == 0

    # Reentrant lock verification
    with ec._lock:
        with ec._lock:
            ec.force_reset()


def test_wave38_volatility_breaker():
    vb = VolatilityBreaker()
    vb.reset()
    t0 = 3000.0

    # Feed 100 baseline prices with small fluctuations (0.10)
    p = 2000.0
    for i in range(100):
        p += 0.10 if (i % 2 == 0) else -0.10
        vb.update(p, now_ts=t0 + i)

    assert not vb.is_entry_blocked(now_ts=t0 + 100)

    # Now create extreme volatility in the short window (changes of 5.0)
    for i in range(15):
        p += 5.0 if (i % 2 == 0) else -5.0
        vb.update(p, now_ts=t0 + 101 + i)

    # Surge ratio should trigger block for 90s
    assert vb.is_entry_blocked(now_ts=t0 + 116)
    info = vb.info(now_ts=t0 + 116)
    assert info["currently_blocked"] is True
    assert info["total_spikes"] >= 1

    # Reset clears block
    with vb._lock:
        with vb._lock:
            vb.reset()
    assert not vb.is_entry_blocked(now_ts=t0 + 116)


def test_wave39_drawdown_pause():
    dp = DrawdownPause()
    dp.reset()
    t0 = 4000.0

    # Feed steady equity of $10,000
    dp.update(10000.0, now_ts=t0)
    dp.update(10000.0, now_ts=t0 + 100)
    assert not dp.is_entry_blocked(now_ts=t0 + 100)

    # Drop equity by 2.0% ($10,000 -> $9,800), exceeding 1.5% threshold
    blocked = dp.is_entry_blocked(balance=9800.0, now_ts=t0 + 200)
    assert blocked is True
    assert dp.is_entry_blocked(now_ts=t0 + 200)
    assert dp.seconds_remaining(now_ts=t0 + 200) == 900.0

    info = dp.info(now_ts=t0 + 200)
    assert info["blocked"] is True
    assert info["drawdown_pct"] == pytest.approx(2.0, rel=1e-2)

    # Equity recovers to $10,000 and pause expires after 900s
    dp.update(10000.0, now_ts=t0 + 1101)
    assert not dp.is_entry_blocked(now_ts=t0 + 1101)

    # Reentrant lock check
    with dp._lock:
        with dp._lock:
            dp.reset()
    assert not dp.is_entry_blocked(now_ts=t0 + 200)


def test_wave40_profit_target_shift():
    pts = ProfitTargetShift()
    pts.reset()

    # Normal mode (pnl between -100 and +150)
    adjusted_normal = pts.adjust_tp(raw_tp_pips=20.0, daily_pnl=50.0)
    assert adjusted_normal == 20.0
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0

    # Profit lock mode (pnl >= +150) -> TP tightened to 80% (20.0 * 0.8 = 16.0)
    adjusted_profit = pts.adjust_tp(raw_tp_pips=20.0, daily_pnl=180.0)
    assert adjusted_profit == 16.0
    assert pts.mode == "PROFIT_LOCK"
    assert pts.tp_factor == 0.8

    # Recovery mode (pnl <= -100) -> TP widened to 110% (20.0 * 1.1 = 22.0)
    adjusted_recovery = pts.adjust_tp(raw_tp_pips=20.0, daily_pnl=-120.0)
    assert adjusted_recovery == 22.0
    assert pts.mode == "RECOVERY"
    assert pts.tp_factor == 1.1

    # Edge cases: invalid raw TP pips or non-finite daily pnl
    assert pts.adjust_tp(raw_tp_pips=None, daily_pnl=100.0) is None
    assert pts.adjust_tp(raw_tp_pips=-5.0, daily_pnl=100.0) == -5.0
    assert pts.adjust_tp(raw_tp_pips=20.0, daily_pnl=float("nan")) == 20.0

    # Reentrant lock verification
    with pts._lock:
        with pts._lock:
            pts.reset()
    assert pts.mode == "NORMAL"


def test_wave41_session_spread_limiter():
    limiter = SessionSpreadLimiter()
    limiter.reset()

    # Tokyo session: UTC 03:00, threshold is 1.5 pips
    dt_tokyo = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
    assert not limiter.is_entry_blocked(spread_pips=1.2, now_dt=dt_tokyo)
    assert limiter.is_entry_blocked(spread_pips=1.8, now_dt=dt_tokyo)

    # London pre-open: UTC 06:30, threshold is 2.0 pips
    dt_pre = datetime(2026, 10, 17, 6, 30, tzinfo=timezone.utc)
    assert not limiter.is_entry_blocked(spread_pips=1.9, now_dt=dt_pre)
    assert limiter.is_entry_blocked(spread_pips=2.2, now_dt=dt_pre)

    # Default / London / NY session: UTC 14:00, threshold is 3.0 pips
    dt_ny = datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)
    assert not limiter.is_entry_blocked(spread_pips=2.8, now_dt=dt_ny)
    assert limiter.is_entry_blocked(spread_pips=3.2, now_dt=dt_ny)

    # Fail-closed invalid inputs
    assert limiter.is_entry_blocked(spread_pips=None, now_dt=dt_ny)
    assert limiter.is_entry_blocked(spread_pips=-1.0, now_dt=dt_ny)
    assert limiter.is_entry_blocked(spread_pips=float("nan"), now_dt=dt_ny)

    # Custom limits and reentrant lock
    with limiter._lock:
        with limiter._lock:
            limiter.update_limits({"tokyo": 1.0})
    assert limiter.is_entry_blocked(spread_pips=1.2, now_dt=dt_tokyo)


def test_wave42_tick_volume_filter():
    tvf = TickVolumeFilter(window_sec=10.0, min_ticks=3, max_ticks=20, spike_cooldown_sec=30.0)
    tvf.reset()
    t0 = 5000.0

    # Dead market: only 1 tick in 10s window (min is 3)
    tvf.update(now_ts=t0)
    assert tvf.is_entry_blocked(now_ts=t0 + 1)
    assert "DEAD_MARKET" in tvf.get_block_reason()

    # Normal market: 5 ticks in 10s window
    for i in range(1, 6):
        tvf.update(now_ts=t0 + i)
    assert not tvf.is_entry_blocked(now_ts=t0 + 6)
    assert tvf.get_tick_rate(window_sec=10.0, now_ts=t0 + 6) > 0.0

    # Volume spike: flood 25 ticks (ceiling is 20)
    for i in range(25):
        tvf.update(now_ts=t0 + 7)
    assert tvf.is_entry_blocked(now_ts=t0 + 7)
    assert "VOLUME_SPIKE" in tvf.get_block_reason()

    # Cooldown holds for 30s
    info = tvf.info(now_ts=t0 + 15)
    assert info["blocked"] is True
    assert info["is_volume_spike"] is True

    # After cooldown expires (30s), feed active healthy ticks to avoid dead-market block
    for i in range(5):
        tvf.update(now_ts=t0 + 38 + i)
    assert not tvf.is_entry_blocked(now_ts=t0 + 43)

    # Reentrant lock check
    with tvf._lock:
        with tvf._lock:
            tvf.reset()
    assert tvf._blocked_count == 0


def test_wave43_win_rate_guard():
    wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.30, pause_duration_sec=1200)
    wrg.reset()
    t0 = 6000.0

    # 4 losses: sample size < min_trades (5), not yet blocked
    for _ in range(4):
        wrg.record_trade(won=False, now_ts=t0)
    assert not wrg.is_entry_blocked(now_ts=t0)

    # 5th loss: win rate = 0/5 = 0% < 30% threshold -> pause triggered for 1200s
    wrg.record_trade(won=False, now_ts=t0)
    assert wrg.is_entry_blocked(now_ts=t0)
    info = wrg.info(now_ts=t0)
    assert info["paused"] is True
    assert info["win_rate_pct"] == 0.0

    # Pause remains active for 1200s
    assert wrg.is_entry_blocked(now_ts=t0 + 1199)
    # Pause expires after 1200s
    assert not wrg.is_entry_blocked(now_ts=t0 + 1201)

    # Reentrant lock check
    with wrg._lock:
        with wrg._lock:
            wrg.reset()
    assert not wrg.is_entry_blocked(now_ts=t0)


def test_wave45_london_open_booster():
    booster = LondonOpenBooster(start_hour_utc=7, end_hour_utc=8, score_discount=0.10)
    booster.reset()

    # Outside London Open (e.g. UTC 05:00) -> no score discount
    dt_outside = datetime(2026, 10, 17, 5, 0, tzinfo=timezone.utc)
    assert not booster.is_active(now_dt=dt_outside)
    assert booster.adjust_min_score(min_score=80.0, now_dt=dt_outside) == 80.0

    # Inside London Open (e.g. UTC 07:30) -> 10% discount: 80 * 0.9 = 72.0
    dt_inside = datetime(2026, 10, 17, 7, 30, tzinfo=timezone.utc)
    assert booster.is_active(now_dt=dt_inside)
    adjusted = booster.adjust_min_score(min_score=80.0, now_dt=dt_inside)
    assert adjusted == 72.0

    info = booster.info(now_dt=dt_inside)
    assert info["london_open_active"] is True
    assert info["score_multiplier"] == 0.9

    # Reentrant lock check
    with booster._lock:
        with booster._lock:
            booster.reset()
    assert booster._total_boosts == 0


def test_wave46_lot_recovery_ladder():
    ladder = LotRecoveryLadder(
        base_lot=0.02,
        max_lot=0.10,
        multiplier=1.5,
        consecutive_trigger=2,
        min_lot=0.01,
        max_recovery_steps=4
    )
    ladder.reset()

    # 1 loss: below trigger (2) -> lot remains base_lot
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.02

    # 2nd consecutive loss: trigger met -> 0.02 * 1.5 = 0.03
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.03

    # 3rd consecutive loss: 0.03 * 1.5 = 0.045 -> rounded 0.04 (banker's rounding)
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.04

    # Win resets lot back to base_lot
    ladder.record_trade(won=True)
    assert ladder.get_lot() == 0.02
    assert ladder._consecutive_losses == 0

    # Discrete ladder steps support
    ladder_discrete = LotRecoveryLadder(
        base_lot=0.02,
        consecutive_trigger=1,
        ladder_steps=[0.03, 0.05, 0.08, 0.10]
    )
    ladder_discrete.record_trade(won=False)
    assert ladder_discrete.get_lot() == 0.03
    ladder_discrete.record_trade(won=False)
    assert ladder_discrete.get_lot() == 0.05

    # Reentrant lock check
    with ladder._lock:
        with ladder._lock:
            ladder.reset()
    assert ladder.get_lot() == 0.02
