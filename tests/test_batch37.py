"""
tests/test_batch37.py - Comprehensive Unit Tests for Batch 37 Components:
1. wave8_signal_optimizer scoring logic, patterns, and entry gates
2. wave8_signal_optimizer ATR-adaptive SL/TP scaling and reset
3. wave9_risk_manager equity curve EMA and filter gates
4. wave9_risk_manager drawdown tracking and dynamic lot scaling
5. wave10_session_optimizer session classification (London, Overlap, Tokyo, Weekend, Rollover)
6. wave10_session_optimizer target adjustment and trading allowed interface
7. wave11_profit_optimizer win/loss streaks and recovery lot modifiers
8. wave11_profit_optimizer peak floating PnL reversal and partial profit closing
9. wave19_volatility_tpsl dynamic ATR and session index adjustments
10. wave20_spike_filter abnormal single-tick spike detection, cluster limits, and cooldown
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave8_signal_optimizer import SignalScorer
from wave9_risk_manager import RiskManager
from wave10_session_optimizer import SessionOptimizer
from wave11_profit_optimizer import ProfitOptimizer
from wave19_volatility_tpsl import VolatilityTPSLAdjuster
from wave20_spike_filter import SpikeFilter


def test_wave8_signal_optimizer_scoring():
    """Verify SignalScorer composite scoring across indicators and patterns."""
    scorer = SignalScorer()
    scorer.reset()

    closes = [2400.0 + i * 0.1 for i in range(35)]
    bars = [
        {"open": 2403.0, "high": 2403.5, "low": 2402.0, "close": 2403.4, "volume": 100},
        {"open": 2403.4, "high": 2404.0, "low": 2403.2, "close": 2403.9, "volume": 120},  # bullish hammer
    ]

    # Strong BUY setup
    score = scorer.score_signal(
        signal="BUY",
        closes=closes,
        bars=bars,
        rsi=28.0,            # oversold
        bb_squeeze=True,     # squeeze bonus
        market_regime="TRENDING_UP",
        ema_cross="BUY"
    )

    assert score >= 60
    assert scorer.is_trading_allowed(score, threshold=55)[0] is True
    assert scorer.is_entry_blocked(score, threshold=55) is False

    # Low score test (opposing market / overbought BUY)
    low_score = scorer.score_signal(
        signal="BUY",
        closes=closes,
        bars=bars,
        rsi=75.0,
        bb_squeeze=False,
        market_regime="VOLATILE",
        ema_cross="SELL"
    )
    assert low_score < 55
    allowed, reason = scorer.is_trading_allowed(low_score, threshold=55)
    assert allowed is False
    assert "LOW_SIGNAL_SCORE" in reason


def test_wave8_signal_optimizer_adaptive_tpsl():
    """Verify ATR-adaptive SL and TP scaling and bounds clamping."""
    scorer = SignalScorer()
    scorer.reset()

    # High volatility bars: ATR ~ 2.0 (20 pips)
    high_vol_bars = [
        {"open": 2400.0, "high": 2402.5, "low": 2399.5, "close": 2402.0},
        {"open": 2402.0, "high": 2404.5, "low": 2401.5, "close": 2404.0},
    ] * 8

    sl, tp = scorer.get_adaptive_sl_tp(high_vol_bars, base_sl_pips=30.0, rr_ratio=1.5)
    assert sl > 30.0  # widened
    assert sl <= 60.0 # clamped
    assert tp == round(sl * 1.5, 1)

    scorer.reset()
    info = scorer.info()
    assert info["wave"] == 8
    assert info["vol_proxy_len"] == 0


def test_wave9_risk_manager_equity_filter():
    """Verify RiskManager equity curve EMA and stop trading gate."""
    rm = RiskManager({"starting_balance": 10000.0})
    rm.reset()

    # Steady equity growth: 10000 -> 10100
    for eq in [10000.0, 10020.0, 10050.0, 10080.0, 10100.0]:
        rm.update_equity(eq)

    assert rm.equity_curve_ok(10100.0) is True

    # Severe equity drop below EMA
    assert rm.equity_curve_ok(9800.0) is False

    # Invalid input handling
    assert rm.equity_curve_ok(float("nan")) is False
    assert rm.equity_curve_ok(None) is False


def test_wave9_risk_manager_drawdown_guard():
    """Verify drawdown calculation and dynamic lot scaling."""
    rm = RiskManager({
        "starting_balance": 10000.0,
        "max_daily_loss_usd": 200.0,
        "max_drawdown_pct": 10.0
    })
    rm.reset()

    # Peak balance is 10000.0
    assert rm.drawdown_pct(9500.0) == 5.0
    assert rm.drawdown_pct(9000.0) == 10.0

    # Daily loss gate: loss = -$250 > $200 limit -> trade blocked
    allowed, reason = rm.can_open_trade(
        balance=9750.0,
        equity=9750.0,
        open_positions=[],
        new_direction="BUY",
        daily_pnl=-250.0
    )
    assert allowed is False
    assert "Daily loss limit" in reason

    # Dynamic lot scaling by daily loss (< 25% limit -> 1.0x)
    assert rm.scale_lot_by_daily_pnl(0.04, daily_pnl=-20.0) == 0.04
    # Daily loss >= 25% limit ($50) -> 0.75x -> 0.03
    assert rm.scale_lot_by_daily_pnl(0.04, daily_pnl=-50.0) == 0.03
    # Daily loss >= 50% limit ($100) -> 0.50x -> 0.02
    assert rm.scale_lot_by_daily_pnl(0.04, daily_pnl=-110.0) == 0.02


def test_wave10_session_optimizer_schedule():
    """Verify session classification and tradeability across UTC hours and days."""
    so = SessionOptimizer()
    so.reset()

    # 1. London/NY Overlap (Tuesday 14:30 UTC) -> PREMIUM
    dt_overlap = datetime(2026, 10, 20, 14, 30, tzinfo=timezone.utc)
    info_overlap = so.get_current_session_info(dt_overlap)
    assert info_overlap["session"] == "OVERLAP"
    assert info_overlap["quality"] == "PREMIUM"
    assert info_overlap["pip_multiplier"] == 1.3
    assert info_overlap["tradeable"] is True

    # 2. Tokyo session (Tuesday 03:00 UTC)
    dt_tokyo = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
    info_tokyo = so.get_current_session_info(dt_tokyo)
    assert info_tokyo["session"] == "TOKYO"
    assert info_tokyo["pip_multiplier"] == 0.7

    # 3. Rollover window (Tuesday 22:30 UTC) -> blocked
    dt_rollover = datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc)
    info_rollover = so.get_current_session_info(dt_rollover)
    assert info_rollover["session"] == "ROLLOVER"
    assert info_rollover["tradeable"] is False

    # 4. Weekend (Saturday 12:00 UTC) -> blocked
    dt_weekend = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    info_weekend = so.get_current_session_info(dt_weekend)
    assert info_weekend["session"] == "CLOSED"
    assert info_weekend["tradeable"] is False


def test_wave10_session_optimizer_targets():
    """Verify session target adjustment and standard interface."""
    so = SessionOptimizer()
    dt_overlap = datetime(2026, 10, 20, 14, 30, tzinfo=timezone.utc)

    # Base SL = 30.0, overlap mult = 1.3 -> 39.0 pips
    sl, tp = so.get_adjusted_targets(30.0, 45.0, rr_ratio=1.5, now_dt=dt_overlap)
    assert sl == 39.0
    assert tp == round(39.0 * 1.5, 1)

    allowed, reason = so.is_trading_allowed(now_dt=dt_overlap)
    assert allowed is True
    assert reason == "OK"
    assert so.is_entry_blocked(now_dt=dt_overlap) is False


def test_wave11_profit_optimizer_streaks():
    """Verify win/loss streak lot scaling and recovery mode."""
    po = ProfitOptimizer()
    po.reset()

    # Win streak of 3 -> 1.1x confidence multiplier
    po.record_result(True)
    po.record_result(True)
    po.record_result(True)
    assert po.streak_lot_modifier() == 1.1
    assert po.is_recovery_mode() is False

    # Loss streak of 3 -> 0.5x recovery multiplier
    po.record_result(False)
    po.record_result(False)
    po.record_result(False)
    assert po.streak_lot_modifier() == 0.5
    assert po.is_recovery_mode() is True

    # Loss streak of 5 -> 0.1x ultra-conservative multiplier
    po.record_result(False)
    po.record_result(False)
    assert po.streak_lot_modifier() == 0.10

    po.reset()
    assert po.streak_lot_modifier() == 1.0


def test_wave11_profit_optimizer_reversal_guard():
    """Verify peak floating PnL tracking, reversal detection, and partial close."""
    po = ProfitOptimizer()
    po.reset()

    ticket = "ORDER_1001"
    po.update_peak_float(ticket, 30.0)

    # Reversal of 40% (float = 18.0) -> below 50% threshold -> False
    assert po.should_close_reversal(ticket, 18.0, threshold=0.5) is False

    # Reversal of 60% (float = 12.0) -> above 50% threshold -> True
    assert po.should_close_reversal(ticket, 12.0, threshold=0.5) is True

    # Partial close: pips_profit = 20 on tp = 40 (50% progress >= 40% level 1)
    partial_lot = po.get_partial_close_level(ticket, pips_profit=20.0, tp_pips=40.0, lot_size=0.06)
    assert partial_lot == 0.02  # 33% of 0.06

    # Subsequent call returns None (already partially closed)
    assert po.get_partial_close_level(ticket, pips_profit=20.0, tp_pips=40.0, lot_size=0.06) is None

    po.cleanup_ticket(ticket)


def test_wave19_volatility_tpsl_adjustment():
    """Verify VolatilityTPSLAdjuster dynamically scales TP and SL."""
    adjuster = VolatilityTPSLAdjuster()

    # High volatility closes (large swings) + high vol session (vol_index=1.8)
    high_vol_closes = [2400.0, 2403.0, 2399.0, 2404.0, 2398.0, 2405.0] * 5
    tp_high, sl_high = adjuster.adjusted_tpsl(
        closes=high_vol_closes,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 1.8}
    )
    assert tp_high > 45.0
    assert tp_high <= 120.0
    assert 15.0 <= sl_high <= 60.0

    # Low volatility closes (tight consolidation) + low vol session (vol_index=0.3)
    low_vol_closes = [2400.0, 2400.1, 2400.05, 2400.15, 2400.08] * 5
    tp_low, sl_low = adjuster.adjusted_tpsl(
        closes=low_vol_closes,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 0.3}
    )
    assert tp_low < 45.0
    assert sl_low < 30.0


def test_wave20_spike_filter_cooldown():
    """Verify SpikeFilter detects single-tick spikes and enforces cooldown."""
    sf = SpikeFilter(spike_ratio_threshold=4.0, cooldown_sec=90.0)
    sf.reset()

    now = 1000.0
    # Feed 10 steady ticks with 0.1 pip change (avg = 0.1)
    for i in range(10):
        sf.check(2400.0 + i * 0.1, 2400.0 + (i - 1) * 0.1, now_ts=now + i)

    # Sudden 2.0 pip spike (20x average!)
    allowed, reason = sf.check(2403.0, 2401.0, now_ts=now + 11)
    assert allowed is False
    assert "SPIKE_DETECTED" in reason
    assert sf.is_blocked(now_ts=now + 12) is True

    # Inside cooldown (now + 50s) -> blocked
    allowed_cd, reason_cd = sf.check(2403.1, 2403.0, now_ts=now + 50)
    assert allowed_cd is False
    assert "SPIKE_COOLDOWN" in reason_cd

    # Outside cooldown (now + 110s > 90s cooldown) -> unblocked
    allowed_recovered, _ = sf.check(2403.1, 2403.0, now_ts=now + 110)
    assert allowed_recovered is True
    assert sf.is_blocked(now_ts=now + 110) is False

    sf.reset()
    assert sf.info(now_ts=now)["blocked"] is False
