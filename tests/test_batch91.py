"""
tests/test_batch91.py
Batch 91 Unit Tests: Candle Pattern Filter (wave50) & Session PnL Tracker (wave51).
Expands test baseline beyond 1,147+ passing tests to 1,157+ passing tests.
Verifies:
1. wave50: CandlePatternFilter initialization defaults, tick buffer management, and reset() state clearing.
2. wave50: Doji pattern detection (body < 10% of range) inducing INDECISION bias and blocking both BUY and SELL.
3. wave50: Hammer (BULLISH bias blocking SELL) and Inverted Hammer (BEARISH bias blocking BUY) pattern identification.
4. wave50: Bullish and Bearish Engulfing dual-candle pattern classification and directional gating.
5. wave50: Synthetic tick-based candle building, info() telemetry diagnostics, and non-finite input resilience.
6. wave51: Session name normalization aliases and UTC hour session routing (Tokyo, London, NY).
7. wave51: SessionPnLTracker initialization defaults, sign negation (-abs), and memory retention constraints.
8. wave51: Trade PnL accumulation into correct session date keys and get_session_pnl() retrieval.
9. wave51: Session loss limit breach (-$100.00 default) triggering session-level entry lockout.
10. wave51: Manual session unblock override, tracker reset(), and info() telemetry diagnostics.
"""

import math
from datetime import datetime, timezone
import pytest

from wave50_candle_pattern_filter import CandlePatternFilter
from wave51_session_pnl_tracker import (
    SessionPnLTracker,
    _normalize_session,
    _current_session,
)


def test_wave50_initialization_defaults_and_reset():
    """Verify CandlePatternFilter initializes cleanly and reset() flushes state."""
    cpf = CandlePatternFilter()
    assert cpf._last_pattern == "NONE"
    assert cpf._last_bias == "NEUTRAL"
    assert cpf.get_bias() == "NEUTRAL"
    assert cpf._total_blocks == 0
    assert len(cpf._ticks) == 0

    # Feeding valid tick and resetting
    cpf.update(100.0, now_ts=1750000000.0)
    assert len(cpf._ticks) == 1
    assert cpf._last_update == 1750000000.0

    cpf.reset()
    assert cpf._last_pattern == "NONE"
    assert cpf._last_bias == "NEUTRAL"
    assert cpf._total_blocks == 0
    assert len(cpf._ticks) == 0
    assert cpf._last_update == 0.0


def test_wave50_update_candle_doji_indecision_blocks_both():
    """Verify DOJI pattern detection (body < 10% range) flags INDECISION and blocks both BUY and SELL."""
    cpf = CandlePatternFilter()

    # Candle with total range of 10.0 (high=105, low=95) and body of 0.2 (open=100.0, close=100.2)
    # body_ratio = 0.2 / 10.0 = 0.02 < 0.10 -> DOJI
    cpf.update_candle(o=100.0, h=105.0, l=95.0, c=100.2)

    assert cpf._last_pattern == "DOJI"
    assert cpf._last_bias == "INDECISION"
    assert cpf.get_bias() == "INDECISION"

    # Both BUY and SELL must be blocked
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is True
    assert cpf._total_blocks == 2

    allowed, reason = cpf.is_trading_allowed("BUY")
    assert allowed is False
    assert "DOJI contradicts BUY" in reason


def test_wave50_update_candle_hammer_and_inverted_hammer():
    """Verify Hammer blocks SELL (BULLISH bias) and Inverted Hammer blocks BUY (BEARISH bias)."""
    cpf = CandlePatternFilter()

    # Hammer: lower wick > 2x body, upper wick < body
    # Open=100, Close=101 (body=1.0), High=101.4 (upper=0.4 < 1.0), Low=97.5 (lower=2.5 > 2.0)
    cpf.update_candle(o=100.0, h=101.4, l=97.5, c=101.0)
    assert cpf._last_pattern == "HAMMER"
    assert cpf._last_bias == "BULLISH"
    assert cpf.is_signal_blocked("SELL") is True
    assert cpf.is_signal_blocked("BUY") is False

    # Inverted Hammer: upper wick > 2x body, lower wick < body
    # Open=100, Close=99.2 (body=0.8), High=102.5 (upper=2.5 > 1.6), Low=99.0 (lower=0.2 < 0.8)
    cpf.update_candle(o=100.0, h=102.5, l=99.0, c=99.2)
    assert cpf._last_pattern == "INV_HAMMER"
    assert cpf._last_bias == "BEARISH"
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is False


def test_wave50_engulfing_patterns():
    """Verify Bullish and Bearish Engulfing dual-candle classification."""
    cpf = CandlePatternFilter()

    # 1. Bullish Engulfing: c1 bearish (o=102, c=100, body=2), c2 bullish (o=99, c=103, body=4 > 2)
    c1 = {"o": 102.0, "h": 102.5, "l": 99.5, "c": 100.0}
    c2_bull = {"o": 99.0, "h": 103.5, "l": 98.5, "c": 103.0}
    cpf._classify_candle(c2_bull, c1)

    assert cpf._last_pattern == "BULL_ENGULF"
    assert cpf._last_bias == "BULLISH"
    assert cpf.is_signal_blocked("SELL") is True
    assert cpf.is_signal_blocked("BUY") is False

    # 2. Bearish Engulfing: c1 bullish (o=100, c=102, body=2), c2 bearish (o=103, c=98.5, body=4.5 > 2)
    c1_bull = {"o": 100.0, "h": 102.5, "l": 99.5, "c": 102.0}
    c2_bear = {"o": 103.0, "h": 103.5, "l": 98.0, "c": 98.5}
    cpf._classify_candle(c2_bear, c1_bull)

    assert cpf._last_pattern == "BEAR_ENGULF"
    assert cpf._last_bias == "BEARISH"
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is False


def test_wave50_tick_update_and_info_introspection():
    """Verify tick streaming synthetic candle construction, invalid input filtering, and info() reporting."""
    cpf = CandlePatternFilter()
    t0 = 1750000000.0

    # Invalid input filtering
    cpf.update(None)
    cpf.update(True)
    cpf.update(False)
    cpf.update(-5.0)
    cpf.update(float("nan"))
    assert len(cpf._ticks) == 0

    # Stream ticks across c1 window (30-60s ago) and c2 window (0-30s ago)
    # c1 ticks: 45s ago (bearish: 105 -> 100)
    cpf.update(105.0, now_ts=t0 - 45.0)
    cpf.update(100.0, now_ts=t0 - 40.0)

    # c2 ticks: 15s ago (bullish engulfing: 98 -> 108)
    cpf.update(98.0, now_ts=t0 - 15.0)
    cpf.update(108.0, now_ts=t0 - 5.0)

    # Trigger analysis at t0
    cpf._analyse(now_ts=t0)
    assert cpf._last_pattern in ("BULL_ENGULF", "NORMAL")
    assert cpf._last_bias == "BULLISH"

    info = cpf.info()
    assert info["wave"] == 50
    assert info["name"] == "CandlePatternFilter"
    assert "last_pattern" in info
    assert "last_bias" in info
    assert info["ticks_buffered"] == 4


def test_wave51_session_normalization_and_time_routing():
    """Verify session string normalization aliases and UTC hour session routing."""
    # Aliases
    assert _normalize_session("tokyo") == "Tokyo"
    assert _normalize_session("asia") == "Tokyo"
    assert _normalize_session("LONDON") == "London"
    assert _normalize_session("europe") == "London"
    assert _normalize_session("eu") == "London"
    assert _normalize_session("ny") == "NY"
    assert _normalize_session("new york") == "NY"
    assert _normalize_session("us") == "NY"
    assert _normalize_session(None) == "Unknown"

    # UTC hour routing
    # Tokyo: 00:00 - 08:00
    dt_tokyo = datetime(2026, 10, 18, 4, 30, 0, tzinfo=timezone.utc)
    assert _current_session(dt_tokyo) == "Tokyo"

    # London: 08:00 - 16:00
    dt_london = datetime(2026, 10, 18, 11, 0, 0, tzinfo=timezone.utc)
    assert _current_session(dt_london) == "London"

    # NY: 16:00 - 24:00
    dt_ny = datetime(2026, 10, 18, 19, 15, 0, tzinfo=timezone.utc)
    assert _current_session(dt_ny) == "NY"


def test_wave51_initialization_defaults_and_loss_limit_negation():
    """Verify SessionPnLTracker initializes defaults, negates positive loss limits, and clamps history."""
    tracker = SessionPnLTracker()
    assert tracker._loss_limit == -100.0
    assert tracker._max_history == 30
    assert tracker._total_trades == 0

    # Enforces negative loss limit regardless of sign passed
    tracker_pos = SessionPnLTracker(loss_limit=75.0, max_history_sessions=2)
    assert tracker_pos._loss_limit == -75.0
    assert tracker_pos._max_history == 3  # min clamped to 3

    # Non-finite falls back to default
    tracker_nan = SessionPnLTracker(loss_limit=float("nan"))
    assert tracker_nan._loss_limit == -100.0


def test_wave51_record_trade_session_bucketing():
    """Verify record_trade aggregates PnL into the correct session and date buckets."""
    tracker = SessionPnLTracker(loss_limit=-100.0)
    dt_london = datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)
    dt_tokyo = datetime(2026, 10, 18, 3, 0, 0, tzinfo=timezone.utc)

    # Record 2 trades in London
    tracker.record_trade(45.5, now_dt=dt_london)
    tracker.record_trade(-15.0, now_dt=dt_london)

    # Record 1 trade in Tokyo
    tracker.record_trade(-30.0, now_dt=dt_tokyo)

    assert tracker.get_session_pnl("London", now_dt=dt_london) == 30.5
    assert tracker.get_session_pnl("Tokyo", now_dt=dt_tokyo) == -30.0
    assert tracker._total_trades == 3

    # Invalid PnL inputs are safely ignored
    tracker.record_trade(None, now_dt=dt_london)
    tracker.record_trade(True, now_dt=dt_london)
    tracker.record_trade(float("nan"), now_dt=dt_london)
    tracker.record_trade("bad", now_dt=dt_london)
    assert tracker._total_trades == 3


def test_wave51_loss_limit_breach_blocks_session():
    """Verify session accumulating losses beyond loss limit blocks entries for that session."""
    tracker = SessionPnLTracker(loss_limit=-100.0)
    dt_london = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)

    # Initial modest loss: -$40 -> not blocked
    tracker.record_trade(-40.0, now_dt=dt_london)
    assert tracker.is_entry_blocked(now_dt=dt_london) is False
    assert tracker.is_blocked(now_dt=dt_london) is False

    # Second severe loss: -$70 -> total -$110.0 (< -$100.0 limit) -> BLOCKED!
    tracker.record_trade(-70.0, now_dt=dt_london)
    assert tracker.is_entry_blocked(now_dt=dt_london) is True

    allowed, reason = tracker.is_trading_allowed(now_dt=dt_london)
    assert allowed is False
    assert "SESSION_LOSS_LIMIT: London loss $-110.00 < $-100.00" in reason

    # Different session (e.g. NY session on the same day) is unblocked
    dt_ny = datetime(2026, 10, 18, 17, 0, 0, tzinfo=timezone.utc)
    assert tracker.is_entry_blocked(now_dt=dt_ny) is False
    allowed_ny, _ = tracker.is_trading_allowed(now_dt=dt_ny)
    assert allowed_ny is True


def test_wave51_unblock_session_reset_and_info_telemetry():
    """Verify unblock_session overrides lockout, reset() clears state, and info() reports diagnostics."""
    tracker = SessionPnLTracker(loss_limit=-50.0)
    dt = datetime(2026, 10, 18, 14, 0, 0, tzinfo=timezone.utc)
    tracker.record_trade(-60.0, now_dt=dt)
    assert tracker.is_entry_blocked(now_dt=dt) is True

    # Manual unblock
    success = tracker.unblock_session(session="London", now_dt=dt)
    assert success is True
    assert tracker.is_entry_blocked(now_dt=dt) is False
    assert tracker.get_session_pnl("London", now_dt=dt) == 0.0

    # Diagnostics info
    info = tracker.info(now_dt=dt)
    assert info["wave"] == 51
    assert info["name"] == "SessionPnLTracker"
    assert info["current_session"] == "London"
    assert info["loss_limit"] == -50.0
    assert info["is_blocked"] is False
    assert info["total_trades_recorded"] == 1

    # Reset flushes tracker
    tracker.reset()
    assert tracker._total_trades == 0
    assert len(tracker._session_pnl) == 0
    assert len(tracker._blocked_sessions) == 0
