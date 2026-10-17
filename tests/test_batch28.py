"""
Unit tests for Batch 28: Wave Modules Hardening
Covers:
- wave49_spread_cost_tracker
- wave50_candle_pattern_filter
- wave53_tick_reversal_guard
- wave54_max_spread_per_trade
- wave32_gap_guard
- wave33_partial_close
- wave35_overnight_guard
- wave10_session_optimizer
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from wave49_spread_cost_tracker import SpreadCostTracker
from wave50_candle_pattern_filter import CandlePatternFilter
from wave53_tick_reversal_guard import TickReversalGuard
from wave54_max_spread_per_trade import MaxSpreadPerTrade
from wave32_gap_guard import GapGuard
from wave33_partial_close import PartialCloseManager
from wave35_overnight_guard import OvernightGuard
from wave10_session_optimizer import SessionOptimizer


# ==============================================================================
# Wave 49: SpreadCostTracker
# ==============================================================================
def test_wave49_spread_cost_tracker():
    tracker = SpreadCostTracker(max_daily_usd=50.0)

    # 1. Invalid input guards
    tracker.record_trade(None, 0.01)
    tracker.record_trade(1.5, -0.01)
    tracker.record_trade(float("nan"), 0.01)
    assert tracker.get_daily_cost() == 0.0

    dt_day1 = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)

    # 2. Record trade: 2.0 pips spread on 0.05 lot = 2.0 * 5 * $1.00 = $10.00
    tracker.record_trade(2.0, 0.05, now_dt=dt_day1)
    assert tracker.get_daily_cost(now_dt=dt_day1) == 10.0
    assert tracker.is_entry_blocked(now_dt=dt_day1) is False

    # 3. Breach daily limit ($50.00): add 4.0 pips on 0.11 lot = 4.0 * 11 = $44.00 (total $54.00)
    tracker.record_trade(4.0, 0.11, now_dt=dt_day1)
    assert tracker.get_daily_cost(now_dt=dt_day1) == 54.0
    assert tracker.is_entry_blocked(now_dt=dt_day1) is True
    allowed, reason = tracker.is_trading_allowed(now_dt=dt_day1)
    assert allowed is False
    assert "SPREAD_CAP" in reason

    # 4. Midnight rollover resets daily cost
    dt_day2 = datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc)
    assert tracker.get_daily_cost(now_dt=dt_day2) == 0.0
    assert tracker.is_entry_blocked(now_dt=dt_day2) is False

    tracker.reset()
    assert tracker.get_daily_cost() == 0.0
    info = tracker.info()
    assert info["wave"] == 49
    assert info["name"] == "SpreadCostTracker"


# ==============================================================================
# Wave 50: CandlePatternFilter
# ==============================================================================
def test_wave50_candle_pattern_filter():
    cpf = CandlePatternFilter()

    # 1. DOJI candle (small body < 10% range) -> blocks both BUY and SELL
    cpf.update_candle(o=2000.0, h=2010.0, l=1990.0, c=2000.5)
    assert cpf.get_bias() == "INDECISION"
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is True

    # 2. HAMMER candle (long lower wick > 2x body) -> BULLISH bias, blocks SELL, allows BUY
    cpf.update_candle(o=2008.0, h=2010.0, l=1990.0, c=2010.0)
    assert cpf.get_bias() == "BULLISH"
    assert cpf.is_signal_blocked("BUY") is False
    assert cpf.is_signal_blocked("SELL") is True

    # 3. INVERTED HAMMER candle (long upper wick > 2x body) -> BEARISH bias, blocks BUY, allows SELL
    cpf.update_candle(o=1992.0, h=2010.0, l=1990.0, c=1990.0)
    assert cpf.get_bias() == "BEARISH"
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is False

    cpf.reset()
    assert cpf.get_bias() == "NEUTRAL"
    info = cpf.info()
    assert info["wave"] == 50
    assert info["name"] == "CandlePatternFilter"


# ==============================================================================
# Wave 53: TickReversalGuard
# ==============================================================================
def test_wave53_tick_reversal_guard():
    trg = TickReversalGuard(n_ticks=5, block_duration=30.0)

    # 1. Rejection of invalid inputs
    trg.update(None)
    trg.update(True)
    trg.update(float("nan"))
    trg.update(-10.0)
    assert trg._update_count == 0

    t0 = 1000.0
    # 2. Falling market: 6 ticks, 5 consecutive down moves
    for i, p in enumerate([2010.0, 2008.0, 2006.0, 2004.0, 2002.0, 2000.0]):
        trg.update(p)

    # BUY is blocked into falling market
    assert trg.is_signal_blocked("BUY", now_ts=t0) is True
    allowed, reason = trg.is_trading_allowed("BUY", now_ts=t0)
    assert allowed is False
    assert "TICK_REVERSAL" in reason

    # SELL is allowed
    assert trg.is_signal_blocked("SELL", now_ts=t0) is False

    # 3. Cooldown duration expires at t0 + 35s
    assert trg.is_signal_blocked("BUY", now_ts=t0 + 35.0) is False

    trg.reset()
    assert len(trg._prices) == 0
    info = trg.info(now_ts=t0)
    assert info["wave"] == 53
    assert info["name"] == "TickReversalGuard"


# ==============================================================================
# Wave 54: MaxSpreadPerTrade
# ==============================================================================
def test_wave54_max_spread_per_trade():
    mspt = MaxSpreadPerTrade(max_spread_pips=2.5)

    # 1. Invalid input guards
    mspt.update(None)
    mspt.update(True)
    mspt.update(-1.0)
    assert mspt.get_spread() == 0.0

    # 2. Normal spread <= 2.5 pips -> allowed
    mspt.update(1.8)
    assert mspt.get_spread() == 1.8
    assert mspt.is_entry_blocked() is False
    assert mspt.is_trading_allowed()[0] is True

    # 3. High spread > 2.5 pips -> blocked
    mspt.update(3.2)
    assert mspt.is_entry_blocked() is True
    allowed, reason = mspt.is_trading_allowed()
    assert allowed is False
    assert "SPREAD_TOO_HIGH" in reason

    # 4. Direct candidate spread testing
    assert mspt.is_entry_blocked(spread_pips=1.5) is False
    assert mspt.is_entry_blocked(spread_pips=4.0) is True

    mspt.reset()
    assert mspt.get_spread() == 0.0
    info = mspt.info()
    assert info["wave"] == 54
    assert info["name"] == "MaxSpreadPerTrade"


# ==============================================================================
# Wave 32: GapGuard
# ==============================================================================
def test_wave32_gap_guard():
    gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=120.0, pip_size=0.1)

    t0 = 1000.0
    # 1. Normal ticks: 0.2 pip move (within 5.0 pip threshold)
    gg.update_price(2000.0, now_ts=t0)
    gg.update_price(2000.2, now_ts=t0 + 1)
    assert gg.is_entry_blocked(now_ts=t0 + 1) is False
    assert gg.is_trading_allowed(now_ts=t0 + 1)[0] is True

    # 2. Price gap: 0.8 price change = 8.0 pips (> 5.0 pips) -> triggers block!
    gg.update_price(2001.0, now_ts=t0 + 2)
    assert gg.is_entry_blocked(now_ts=t0 + 2) is True
    allowed, reason = gg.is_trading_allowed(now_ts=t0 + 2)
    assert allowed is False
    assert "GAP_GUARD" in reason

    # 3. After block_duration (120s): unblocks at t0 + 130s
    assert gg.is_entry_blocked(now_ts=t0 + 130.0) is False
    assert gg.is_trading_allowed(now_ts=t0 + 130.0)[0] is True

    gg.reset()
    assert gg._total_gaps == 0
    info = gg.info(now_ts=t0)
    assert info["wave"] == 32
    assert info["name"] == "GapGuard"


# ==============================================================================
# Wave 33: PartialCloseManager
# ==============================================================================
def test_wave33_partial_close():
    pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)

    # 1. Lot quantization helper
    assert pcm.get_close_lot(0.04) == 0.02
    assert pcm.get_close_lot(0.02) == 0.01
    assert pcm.get_close_lot(0.01) == 0.0  # cannot split < 0.02

    # 2. BUY position progress
    ticket = 5001
    # Entry: 2000.0, TP: 2020.0 (dist 20.0). Current: 2005.0 (+5.0 -> 25% < 50%)
    assert pcm.check_position(ticket, "BUY", entry_price=2000.0, current_price=2005.0, tp_price=2020.0, lot=0.04) is False

    # Current: 2012.0 (+12.0 -> 60% >= 50%) -> triggers partial close!
    assert pcm.check_position(ticket, "BUY", entry_price=2000.0, current_price=2012.0, tp_price=2020.0, lot=0.04) is True

    # Ticket idempotency: second call returns False
    assert pcm.check_position(ticket, "BUY", entry_price=2000.0, current_price=2014.0, tp_price=2020.0, lot=0.04) is False

    # 3. Cleanup & Reset
    pcm.remove_ticket(ticket)
    assert ticket not in pcm._closed_tickets
    pcm.reset()
    assert pcm._total_partials == 0
    info = pcm.info()
    assert info["wave"] == 33
    assert info["name"] == "PartialCloseManager"


# ==============================================================================
# Wave 35: OvernightGuard
# ==============================================================================
def test_wave35_overnight_guard():
    og = OvernightGuard()

    # 1. Normal trading hours (Wednesday 14:00 UTC)
    dt_wed = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_wed) is False
    assert og.should_force_close_all(now_dt=dt_wed) is False
    assert og.is_trading_allowed(now_dt=dt_wed)[0] is True

    # 2. Friday close window: Friday 20:45 UTC (>= 20:30 UTC)
    dt_fri_close = datetime(2026, 10, 16, 20, 45, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_fri_close) is True
    assert og.should_force_close_all(now_dt=dt_fri_close) is True
    allowed, reason = og.is_trading_allowed(now_dt=dt_fri_close)
    assert allowed is False
    assert "weekend holding" in reason

    # 3. Weekend (Saturday 12:00 UTC)
    dt_sat = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_sat) is True

    # 4. Daily rollover window: 21:50 UTC (between 21:45 and 22:15)
    dt_rollover = datetime(2026, 10, 14, 21, 50, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_rollover) is True
    assert "rollover" in og.is_trading_allowed(now_dt=dt_rollover)[1]

    og.reset()
    assert og.total_force_closes == 0
    info = og.info(now_dt=dt_wed)
    assert info["wave"] == 35
    assert info["name"] == "OvernightGuard"


# ==============================================================================
# Wave 10: SessionOptimizer
# ==============================================================================
def test_wave10_session_optimizer():
    so = SessionOptimizer()

    # 1. London-NY overlap window (14:00 UTC): PREMIUM quality, multiplier 1.3
    dt_overlap = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
    info_overlap = so.get_current_session_info(now_dt=dt_overlap)
    assert info_overlap["session"] == "OVERLAP"
    assert info_overlap["quality"] == "PREMIUM"
    assert info_overlap["pip_multiplier"] == 1.3
    assert info_overlap["tradeable"] is True
    assert so.is_entry_blocked(now_dt=dt_overlap) is False
    assert so.is_trading_allowed(now_dt=dt_overlap)[0] is True

    # 2. Rollover window (22:00 UTC): tradeable False
    dt_rollover = datetime(2026, 10, 14, 22, 0, tzinfo=timezone.utc)
    assert so.is_entry_blocked(now_dt=dt_rollover) is True

    # 3. Weekend (Saturday 12:00 UTC): CLOSED
    dt_sat = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    assert so.is_entry_blocked(now_dt=dt_sat) is True

    # 4. Target adjustment
    sl, tp = so.get_adjusted_targets(base_sl=30.0, base_tp=45.0, rr_ratio=1.5, now_dt=dt_overlap)
    # 30.0 * 1.3 = 39.0 SL, 39.0 * 1.5 = 58.5 TP
    assert sl == 39.0
    assert tp == 58.5

    so.reset()
    assert so._total_optimizations == 0
    info = so.info(now_dt=dt_overlap)
    assert info["wave"] == 10
    assert info["name"] == "SessionOptimizer"
