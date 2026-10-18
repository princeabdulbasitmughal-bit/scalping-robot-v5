"""
Test Suite for Batch 142:
- wave50_candle_pattern_filter.py (CandlePatternFilter: Doji/Hammer/Engulfing pattern direction filter)
- wave51_session_pnl_tracker.py (SessionPnLTracker: Tokyo/London/NY session PnL -$100 stop guard)
Zero regressions, continuing toward 1,667+ passed tests.
"""

import math
from datetime import datetime, timezone
import pytest

from wave50_candle_pattern_filter import (
    CandlePatternFilter,
    candle_pattern_filter,
    is_entry_blocked as w50_is_entry_blocked,
    is_blocked as w50_is_blocked,
    update as w50_update,
    update_candle as w50_update_candle,
    reset as w50_reset,
)
from wave51_session_pnl_tracker import (
    SessionPnLTracker,
    session_pnl_tracker,
    is_entry_blocked as w51_is_entry_blocked,
    is_blocked as w51_is_blocked,
    record_trade as w51_record_trade,
    reset as w51_reset,
)


# ---------------------------------------------------------------------
# Wave 50: Candle Pattern Filter Tests
# ---------------------------------------------------------------------

def test_wave50_initial_state():
    cpf = CandlePatternFilter()
    assert not cpf.is_signal_blocked("BUY")
    assert not cpf.is_signal_blocked("SELL")
    assert not cpf.is_entry_blocked("BUY")
    assert not cpf.is_blocked("SELL")
    assert cpf.get_bias() == "NEUTRAL"
    info = cpf.info()
    assert info["last_pattern"] == "NONE"
    assert info["last_bias"] == "NEUTRAL"
    assert info["total_blocks"] == 0


def test_wave50_invalid_inputs():
    cpf = CandlePatternFilter()
    # Invalid prices
    for bad in [None, True, False, -100.0, 0.0, float("nan"), float("inf"), "abc"]:
        cpf.update(bad)
    assert len(cpf._ticks) == 0

    # Invalid candles (high < low, non-finite, negative)
    cpf.update_candle(o=2000.0, h=1990.0, l=2010.0, c=2005.0)  # h < l
    cpf.update_candle(o=-10.0, h=2000.0, l=1990.0, c=1995.0)
    assert cpf.get_bias() == "NEUTRAL"


def test_wave50_doji_indecision_block():
    cpf = CandlePatternFilter()
    # Doji: range = 10.0, body = 0.1 (1% of range < 10%)
    cpf.update_candle(o=2000.0, h=2005.0, l=1995.0, c=2000.1)
    assert cpf.get_bias() == "INDECISION"
    assert cpf.info()["last_pattern"] == "DOJI"

    # Indecision blocks both BUY and SELL
    assert cpf.is_signal_blocked("BUY")
    assert cpf.is_signal_blocked("SELL")
    allowed_buy, reason_buy = cpf.is_trading_allowed("BUY")
    assert not allowed_buy
    assert "DOJI" in reason_buy


def test_wave50_hammer_and_inverted_hammer():
    cpf = CandlePatternFilter()
    # 1. Hammer: range 10.0, body 2.0 (20% >= 10%), lower wick 7.0 (> 2*2.0), upper wick 1.0 (< 2.0)
    cpf.update_candle(o=1997.0, h=2000.0, l=1990.0, c=1999.0)
    assert cpf.get_bias() == "BULLISH"
    assert cpf.info()["last_pattern"] == "HAMMER"
    # Bullish pattern allows BUY, blocks SELL
    assert not cpf.is_signal_blocked("BUY")
    assert cpf.is_signal_blocked("SELL")

    # 2. Inverted Hammer: range 10.0, body 2.0 (20% >= 10%), upper wick 7.0 (> 2*2.0), lower wick 1.0 (< 2.0)
    cpf.update_candle(o=1993.0, h=2000.0, l=1990.0, c=1991.0)
    assert cpf.get_bias() == "BEARISH"
    assert cpf.info()["last_pattern"] == "INV_HAMMER"
    # Bearish pattern allows SELL, blocks BUY
    assert cpf.is_signal_blocked("BUY")
    assert not cpf.is_signal_blocked("SELL")


def test_wave50_reset_and_module_aliases():
    cpf = CandlePatternFilter()
    cpf.update_candle(o=2000.0, h=2005.0, l=1995.0, c=2000.1)
    assert cpf.get_bias() == "INDECISION"

    cpf.reset()
    assert cpf.get_bias() == "NEUTRAL"
    assert not cpf.is_signal_blocked("BUY")

    # Module-level aliases
    w50_reset()
    assert not w50_is_entry_blocked("BUY")
    assert not w50_is_blocked("SELL")
    w50_update_candle(2000.0, 2005.0, 1995.0, 2000.1)
    assert w50_is_blocked("BUY")
    w50_reset()


# ---------------------------------------------------------------------
# Wave 51: Session PnL Tracker Tests
# ---------------------------------------------------------------------

def test_wave51_initial_state():
    spt = SessionPnLTracker()
    assert not spt.is_entry_blocked()
    assert not spt.is_blocked()
    allowed, reason = spt.is_trading_allowed()
    assert allowed
    assert reason == ""
    info = spt.info()
    assert info["loss_limit"] == -100.0
    assert info["current_session_pnl"] == 0.0
    assert not info["is_blocked"]
    assert info["total_trades_recorded"] == 0


def test_wave51_invalid_pnl_inputs():
    spt = SessionPnLTracker()
    dt = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
    for bad in [None, True, False, float("nan"), float("inf"), "abc"]:
        spt.record_trade(bad, now_dt=dt)

    assert spt.get_session_pnl(now_dt=dt) == 0.0
    assert spt.info(now_dt=dt)["total_trades_recorded"] == 0


def test_wave51_session_resolution():
    spt = SessionPnLTracker()
    # Tokyo: 00:00 - 08:00 UTC
    dt_tokyo = datetime(2026, 10, 18, 4, 0, tzinfo=timezone.utc)
    assert spt.info(now_dt=dt_tokyo)["current_session"] == "Tokyo"

    # London: 08:00 - 16:00 UTC
    dt_london = datetime(2026, 10, 18, 11, 0, tzinfo=timezone.utc)
    assert spt.info(now_dt=dt_london)["current_session"] == "London"

    # NY: 16:00 - 24:00 UTC
    dt_ny = datetime(2026, 10, 18, 19, 0, tzinfo=timezone.utc)
    assert spt.info(now_dt=dt_ny)["current_session"] == "NY"


def test_wave51_session_loss_limit_block():
    spt = SessionPnLTracker(loss_limit=-100.0)
    dt_london = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)

    # Trade 1: -$50.0 loss -> session PnL = -$50.0 (> -100)
    spt.record_trade(-50.0, now_dt=dt_london)
    assert not spt.is_entry_blocked(now_dt=dt_london)
    assert spt.get_session_pnl(now_dt=dt_london) == -50.0

    # Trade 2: -$60.0 loss -> session PnL = -$110.0 (< -100 limit)
    spt.record_trade(-60.0, now_dt=dt_london)
    assert spt.is_entry_blocked(now_dt=dt_london)
    assert spt.is_blocked(now_dt=dt_london)
    allowed, reason = spt.is_trading_allowed(now_dt=dt_london)
    assert not allowed
    assert "SESSION_LOSS_LIMIT" in reason
    info = spt.info(now_dt=dt_london)
    assert info["is_blocked"]
    assert info["current_session_pnl"] == -110.0


def test_wave51_session_rollover_and_module_aliases():
    spt = SessionPnLTracker(loss_limit=-100.0)
    dt_london = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)
    spt.record_trade(-120.0, now_dt=dt_london)
    assert spt.is_entry_blocked(now_dt=dt_london)

    # Rollover to NY session (17:00 UTC)
    dt_ny = datetime(2026, 10, 18, 17, 0, tzinfo=timezone.utc)
    # NY session has 0.0 PnL and is clean/unblocked
    assert not spt.is_entry_blocked(now_dt=dt_ny)
    assert spt.get_session_pnl(now_dt=dt_ny) == 0.0
    # London still records -$120
    assert spt.get_session_pnl("London", now_dt=dt_ny) == -120.0

    # Admin unblock override
    assert spt.unblock_session("London", now_dt=dt_london)
    assert not spt.is_entry_blocked(now_dt=dt_london)

    spt.reset()
    assert spt.get_session_pnl(now_dt=dt_london) == 0.0

    # Module-level aliases
    w51_reset()
    assert not w51_is_entry_blocked(now_dt=dt_london)
    assert not w51_is_blocked(now_dt=dt_london)
    w51_record_trade(15.0, now_dt=dt_london)
    w51_reset()
