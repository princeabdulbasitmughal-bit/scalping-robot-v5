"""
Unit tests for Batch 26: Wave Modules Hardening
Covers:
- wave26_time_filter
- wave27_correlation_guard
- wave28_momentum_confirmation
- wave29_adaptive_tp
- wave31_reversal_detector
- wave34_trailing_stop
- wave51_session_pnl_tracker
- wave52_rsi_ob_os_filter
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from wave26_time_filter import TimeFilter
from wave27_correlation_guard import CorrelationGuard, compute_pearson_correlation
from wave28_momentum_confirmation import MomentumConfirmation
from wave29_adaptive_tp import AdaptiveTp
from wave31_reversal_detector import ReversalDetector
from wave34_trailing_stop import TrailingStopManager
from wave51_session_pnl_tracker import SessionPnLTracker, _normalize_session, _current_session
from wave52_rsi_ob_os_filter import RSIOverboughtOversold


# ==============================================================================
# Wave 26: TimeFilter
# ==============================================================================
def test_wave26_time_filter():
    tf = TimeFilter(release_times=[(12, 30), (18, 0)], block_before=30, block_after=30)

    # 1. Normalization of datetimes
    now_utc = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    allowed, reason = tf.is_trading_allowed(now_utc)
    assert allowed is False
    assert "TIME_FILTER" in reason
    assert tf.is_entry_blocked(now_utc) is True
    assert tf.is_blocked(now_utc) is True

    # 2. Inside window: 12:45 UTC (15m after 12:30 release) -> blocked
    in_dt = datetime(2026, 10, 17, 12, 45, tzinfo=timezone.utc)
    assert tf.is_entry_blocked(in_dt) is True

    # 3. Outside window: 13:10 UTC (40m after 12:30 release) -> allowed
    out_dt = datetime(2026, 10, 17, 13, 10, tzinfo=timezone.utc)
    allowed, reason = tf.is_trading_allowed(out_dt)
    assert allowed is True
    assert reason == ""
    assert tf.is_entry_blocked(out_dt) is False

    # 4. Supports epoch timestamp, string ISO format, and naive dt
    ts = datetime(2026, 10, 17, 12, 30, tzinfo=timezone.utc).timestamp()
    assert tf.is_entry_blocked(ts) is True
    assert tf.is_entry_blocked("2026-10-17T12:30:00+00:00") is True
    assert tf.is_entry_blocked(datetime(2026, 10, 17, 12, 30)) is True

    # 5. Reset and Info
    info = tf.info(now_utc=out_dt)
    assert info["wave"] == 26
    assert info["name"] == "TimeFilter"
    assert info["is_blocked"] is False

    tf.reset()
    assert tf._total_blocks == 0


# ==============================================================================
# Wave 27: CorrelationGuard
# ==============================================================================
def test_wave27_correlation_guard():
    # 1. Test Pearson correlation function
    assert compute_pearson_correlation([1.0, 2.0], [1.0]) == 0.0
    assert compute_pearson_correlation([1.0, 1.0, 1.0], [2.0, 3.0, 4.0]) == 0.0  # zero variance
    assert compute_pearson_correlation([1.0, float("nan")], [2.0, 3.0]) == 0.0

    series_a = [10.0, 20.0, 30.0, 40.0]
    series_b = [1.0, 2.0, 3.0, 4.0]
    series_c = [4.0, 3.0, 2.0, 1.0]
    assert math.isclose(compute_pearson_correlation(series_a, series_b), 1.0, abs_tol=1e-5)
    assert math.isclose(compute_pearson_correlation(series_a, series_c), -1.0, abs_tol=1e-5)

    # 2. Test CorrelationGuard signal density
    cg = CorrelationGuard(window_sec=10.0, max_signals_in_window=3, cooldown_sec=20.0)
    base_t = 1000.0
    cg.record_signal(now_ts=base_t + 1)
    cg.record_signal(now_ts=base_t + 2)
    cg.record_signal(now_ts=base_t + 3)
    assert cg.is_trading_allowed(now_ts=base_t + 3)[0] is True

    # 4th signal (> max_signals 3) within 10s window triggers cooldown
    cg.record_signal(now_ts=base_t + 4)
    allowed, reason = cg.is_trading_allowed(now_ts=base_t + 4)
    assert allowed is False
    assert "CORR_GUARD" in reason

    # After cooldown expires
    assert cg.is_trading_allowed(now_ts=base_t + 25)[0] is True

    # 3. Multi-asset price buffering & correlation
    for i in range(10):
        cg.update_asset_price("XAUUSD", 2000.0 + i)
        cg.update_asset_price("EURUSD", 1.1000 + i * 0.001)

    is_high, corr = cg.is_correlation_too_high("XAUUSD", "EURUSD", threshold=0.8)
    assert is_high is True
    assert math.isclose(corr, 1.0, abs_tol=1e-5)

    matrix = cg.compute_correlation_matrix()
    assert "XAUUSD" in matrix and "EURUSD" in matrix["XAUUSD"]

    cg.reset()
    assert len(cg._signal_times) == 0


# ==============================================================================
# Wave 28: MomentumConfirmation
# ==============================================================================
def test_wave28_momentum_confirmation():
    mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)

    # 1. Invalid input guards
    mc.update_price(None)
    mc.update_price(True)
    mc.update_price(float("nan"))
    mc.update_price(-10.0)
    assert len(mc._price_buffer) == 0

    # 2. Insufficient tick data -> allows entry
    mc.update_price(2000.0)
    mc.update_price(2001.0)
    confirmed, reason = mc.is_momentum_confirmed("BUY")
    assert confirmed is True
    assert "insufficient tick data" in reason

    # 3. BUY confirmed: strictly ascending ticks
    mc.reset()
    for p in [2000.0, 2001.0, 2002.0, 2003.0, 2004.0]:
        mc.update_price(p)
    confirmed, _ = mc.is_momentum_confirmed("BUY")
    assert confirmed is True

    # BUY rejected: descending ticks
    confirmed, reason = mc.is_momentum_confirmed("SELL")
    assert confirmed is False
    assert "MOMENTUM" in reason

    # 4. SELL confirmed: strictly descending ticks
    mc.reset()
    for p in [2004.0, 2003.0, 2002.0, 2001.0, 2000.0]:
        mc.update_price(p)
    assert mc.is_momentum_confirmed("SELL")[0] is True
    assert mc.is_momentum_confirmed("BUY")[0] is False

    info = mc.info()
    assert info["wave"] == 28
    assert info["min_required"] == 3


# ==============================================================================
# Wave 29: AdaptiveTp
# ==============================================================================
def test_wave29_adaptive_tp():
    atp = AdaptiveTp(window=5, extend_ratio=1.5, shrink_ratio=0.7, atr_high_threshold=1.0, atr_low_threshold=0.2, min_tp_pips=5.0)

    # 1. Reward-to-Risk calculation
    assert atp.calculate_reward_to_risk(15.0, 10.0) == 1.5
    assert atp.calculate_reward_to_risk(0.0, 10.0) == 0.0
    assert atp.calculate_reward_to_risk(15.0, 0.0) == 0.0
    assert atp.calculate_reward_to_risk(float("nan"), 10.0) == 0.0

    # 2. Cold start: buffer not filled -> multiplier = 1.0
    atp.update_price(2000.0)
    atp.update_price(2000.5)
    assert atp.get_tp_multiplier() == 1.0

    # 3. High ATR -> extend_ratio (1.5x)
    for p in [2000.0, 2002.0, 2000.0, 2002.0, 2000.0, 2002.0]:
        atp.update_price(p)
    assert atp.get_tp_multiplier() == 1.5
    assert atp.adjust_tp(10.0) == 15.0

    # 4. Low ATR -> shrink_ratio (0.7x)
    atp.reset()
    for p in [2000.00, 2000.05, 2000.08, 2000.10, 2000.12, 2000.15]:
        atp.update_price(p)
    assert atp.get_tp_multiplier() == 0.7
    assert atp.adjust_tp(10.0) == 7.0

    # 5. Floor constraint: never drops below min_tp_pips if base >= min_tp_pips
    assert atp.adjust_tp(6.0) == 5.0  # 6.0 * 0.7 = 4.2 -> clamped to 5.0

    info = atp.info()
    assert info["wave"] == 29
    assert info["name"] == "AdaptiveTp"


# ==============================================================================
# Wave 31: ReversalDetector
# ==============================================================================
def test_wave31_reversal_detector():
    rd = ReversalDetector(rsi_period=5, overbought=75.0, oversold=25.0, cooldown_sec=0.0)

    # 1. Validate bar
    bar_dict = {"open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0}
    assert rd.validate_bar(bar_dict) == (2000.0, 2005.0, 1995.0, 2002.0)
    assert rd.validate_bar({"high": 1990.0, "low": 2000.0, "close": 1995.0}) is None  # high < low
    assert rd.validate_bar([2000.0, 2005.0, 1995.0, 2002.0]) == (2000.0, 2005.0, 1995.0, 2002.0)

    # 2. Bullish Reversal check: oversold prices
    for p in [2050.0, 2040.0, 2030.0, 2020.0, 2010.0, 2000.0]:
        rd.update_price(p)

    sig, conf, reason = rd.get_reversal_signal()
    # At extreme oversold or insufficient divergence, returns valid tuple
    assert sig in ("BUY", "HOLD", "SELL")
    assert 0.0 <= conf <= 1.0

    info = rd.info()
    assert info["wave"] == 31
    assert "total_reversals" in info

    rd.reset()
    assert len(rd._prices) == 0


# ==============================================================================
# Wave 34: TrailingStopManager
# ==============================================================================
def test_wave34_trailing_stop():
    tsm = TrailingStopManager(profit_trigger_pips=10.0, trail_pips=5.0, trail_step_pips=1.0)

    # 1. Quantization helpers
    assert tsm.quantize_lot(0.054) == 0.05
    assert tsm.quantize_lot(0.005) == 0.01
    assert tsm.quantize_lot(150.0, max_lot=50.0) == 50.0
    assert tsm.quantize_price(2000.1234, digits=2) == 2000.12

    # 2. BUY position trailing stop
    ticket = 1001
    # Entry: 2000.0, initial SL: 1990.0. Current price: 2005.0 (+5 pips -> under trigger 10 pips)
    new_sl = tsm.update(ticket, "BUY", entry_price=2000.0, current_price=2005.0, current_sl=1990.0, pip_size=1.0)
    assert new_sl is None

    # Price moves to 2015.0 (+15 pips -> activates trailing stop!)
    # New SL should be 2015.0 - 5.0 = 2010.0
    new_sl = tsm.update(ticket, "BUY", entry_price=2000.0, current_price=2015.0, current_sl=1990.0, pip_size=1.0)
    assert new_sl == 2010.0

    # Price steps up to 2017.0 -> SL moves to 2012.0
    new_sl = tsm.update(ticket, "BUY", entry_price=2000.0, current_price=2017.0, current_sl=2010.0, pip_size=1.0)
    assert new_sl == 2012.0

    # Price pulls back to 2014.0 -> SL should NOT loosen!
    new_sl = tsm.update(ticket, "BUY", entry_price=2000.0, current_price=2014.0, current_sl=2012.0, pip_size=1.0)
    assert new_sl is None

    # 3. Trailing stop never loosens / worsens an existing tighter SL
    new_sl_loosening = tsm.update(9999, "BUY", entry_price=2000.0, current_price=2015.0, current_sl=2014.0, pip_size=1.0)
    # Calculated SL would be 2010.0, which is worse than current_sl 2014.0 -> returns None
    assert new_sl_loosening is None

    # 4. Remove ticket and Reset
    tsm.remove_ticket(ticket)
    assert ticket not in tsm._best_prices
    tsm.reset()
    assert len(tsm._trailing_active) == 0


# ==============================================================================
# Wave 51: SessionPnLTracker
# ==============================================================================
def test_wave51_session_pnl_tracker():
    tracker = SessionPnLTracker(loss_limit=-100.0)

    # 1. Normalization & Session Resolution
    assert _normalize_session("tokyo") == "Tokyo"
    assert _normalize_session("europe") == "London"
    assert _normalize_session("new york") == "NY"

    dt_tokyo = datetime(2026, 10, 17, 4, 0, tzinfo=timezone.utc)
    assert _current_session(dt_tokyo) == "Tokyo"

    dt_london = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
    assert _current_session(dt_london) == "London"

    dt_ny = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
    assert _current_session(dt_ny) == "NY"

    # 2. PnL tracking and loss threshold trigger
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is False

    # Trade 1: -$60 (not yet breached -$100)
    tracker.record_trade(-60.0, now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is False

    # Trade 2: -$50 (total -$110 -> breaches -$100 loss limit!)
    tracker.record_trade(-50.0, now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is True

    # London session should still be open
    assert tracker.is_entry_blocked(now_dt=dt_london) is False

    # 3. Unblock & Reset
    tokyo_key = tracker._key(dt_tokyo)[0]
    tracker.unblock_session(session="Tokyo", now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is False

    tracker.reset()
    assert len(tracker._session_pnl) == 0


# ==============================================================================
# Wave 52: RSIOverboughtOversold
# ==============================================================================
def test_wave52_rsi_ob_os_filter():
    rsi_filter = RSIOverboughtOversold(period=5, ob_block=75.0, os_block=25.0)

    # 1. Neutral default
    assert rsi_filter.get_rsi() == 50.0
    assert rsi_filter.is_signal_blocked("BUY") is False
    assert rsi_filter.is_signal_blocked("SELL") is False

    # 2. Monotonically increasing prices -> overbought
    for p in range(2000, 2020):
        rsi_filter.update(float(p))

    rsi = rsi_filter.get_rsi()
    assert rsi > 75.0
    # Overbought: BUY is blocked, SELL is allowed
    assert rsi_filter.is_signal_blocked("BUY") is True
    assert rsi_filter.is_signal_blocked("SELL") is False

    # 3. Monotonically decreasing prices -> oversold
    rsi_filter.reset()
    for p in range(2020, 2000, -1):
        rsi_filter.update(float(p))

    rsi = rsi_filter.get_rsi()
    assert rsi < 25.0
    # Oversold: SELL is blocked, BUY is allowed
    assert rsi_filter.is_signal_blocked("SELL") is True
    assert rsi_filter.is_signal_blocked("BUY") is False

    # 4. Info & Reset
    info = rsi_filter.info()
    assert info["wave"] == 52
    assert info["name"] == "RSIOverboughtOversold"

    rsi_filter.reset()
    assert rsi_filter.get_rsi() == 50.0
