"""
Test Suite for Batch 146:
- wave58_price_range_filter.py (PriceRangeFilter: intraday price range flat-market filter)
- wave59_ma_trend_filter.py (MATrendFilter: EMA-50 trend alignment filter)
HISTORIC 1,700+ TESTS MILESTONE SUITE!
"""

import math
from datetime import datetime, timezone
import pytest

from wave58_price_range_filter import (
    PriceRangeFilter,
    price_range_filter,
    is_entry_blocked as w58_is_entry_blocked,
    is_blocked as w58_is_blocked,
    update as w58_update,
    get_range_pips as w58_get_range_pips,
    reset as w58_reset,
)
from wave59_ma_trend_filter import (
    MATrendFilter,
    ma_trend_filter,
    is_entry_blocked as w59_is_entry_blocked,
    is_blocked as w59_is_blocked,
    update as w59_update,
    get_ema as w59_get_ema,
    reset as w59_reset,
)


# ---------------------------------------------------------------------
# Wave 58: Price Range Filter Tests
# ---------------------------------------------------------------------

def test_wave58_initial_state():
    prf = PriceRangeFilter()
    assert prf.min_range_pips == 5.0
    assert prf.pip_value == 0.1
    assert prf.min_ticks == 50
    assert not prf.is_entry_blocked()
    assert not prf.is_blocked()
    allowed, reason = prf.is_trading_allowed()
    assert allowed
    assert reason == ""
    info = prf.info()
    assert info["range_pips"] == 0.0
    assert not info["is_blocked"]
    assert info["ticks_today"] == 0


def test_wave58_invalid_inputs():
    prf = PriceRangeFilter()
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    for bad in [None, True, False, -100.0, 0.0, float("nan"), float("inf"), "abc"]:
        prf.update(bad, now_dt=dt)

    assert prf._ticks_today == 0
    assert prf.get_range_pips(now_dt=dt) == 0.0


def test_wave58_warmup_insufficient_ticks():
    prf = PriceRangeFilter(min_range_pips=5.0, min_ticks=50)
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    # Feed 30 ticks (< 50) with narrow range (2000.0 to 2000.2 = 2 pips)
    for i in range(30):
        p = 2000.0 + (0.0 if i % 2 == 0 else 0.2)
        prf.update(p, now_dt=dt)

    # During warmup, entries are not blocked
    assert not prf.is_entry_blocked(now_dt=dt)
    assert prf.get_range_pips(now_dt=dt) == 2.0


def test_wave58_flat_market_blocked():
    prf = PriceRangeFilter(min_range_pips=5.0, min_ticks=50)
    dt = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    # Feed 60 ticks (>= 50) with flat range: 2000.0 to 2000.3 = 3 pips (< 5 pips)
    for i in range(60):
        p = 2000.0 + (0.3 if i % 2 == 0 else 0.0)
        prf.update(p, now_dt=dt)

    assert prf.is_entry_blocked(now_dt=dt)
    assert prf.is_blocked(now_dt=dt)
    allowed, reason = prf.is_trading_allowed(now_dt=dt)
    assert not allowed
    assert "FLAT_MARKET" in reason
    info = prf.info(now_dt=dt)
    assert info["is_blocked"]
    assert info["range_pips"] == 3.0


def test_wave58_wide_range_allowed_and_rollover():
    prf = PriceRangeFilter(min_range_pips=5.0, min_ticks=50)
    dt_day1 = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)
    for i in range(50):
        prf.update(2000.0, now_dt=dt_day1)
    # Expand range: 2000.0 to 2001.0 = 10 pips (>= 5.0)
    prf.update(2001.0, now_dt=dt_day1)
    assert not prf.is_entry_blocked(now_dt=dt_day1)
    assert prf.get_range_pips(now_dt=dt_day1) == 10.0

    # Midnight rollover to next day (2026-10-19)
    dt_day2 = datetime(2026, 10, 19, 0, 5, tzinfo=timezone.utc)
    assert not prf.is_entry_blocked(now_dt=dt_day2)
    assert prf.info(now_dt=dt_day2)["ticks_today"] == 0

    prf.reset()
    assert prf.get_range_pips() == 0.0

    # Module-level aliases
    w58_reset()
    assert not w58_is_entry_blocked()
    assert not w58_is_blocked()
    w58_update(2000.0)
    assert w58_get_range_pips() == 0.0
    w58_reset()


# ---------------------------------------------------------------------
# Wave 59: MA Trend Filter Tests
# ---------------------------------------------------------------------

def test_wave59_initial_state():
    mtf = MATrendFilter(period=50)
    assert not mtf.is_warmed_up
    assert mtf.get_ema() == 0.0
    assert not mtf.is_signal_blocked("BUY")
    assert not mtf.is_signal_blocked("SELL")
    assert not mtf.is_entry_blocked("BUY")
    assert not mtf.is_blocked("SELL")
    allowed, reason = mtf.is_trading_allowed("BUY")
    assert allowed
    info = mtf.info()
    assert info["trend"] == "NEUTRAL"
    assert info["ema50"] is None


def test_wave59_invalid_inputs():
    mtf = MATrendFilter(period=50)
    for bad in [None, True, False, -100.0, 0.0, float("nan"), float("inf"), "abc"]:
        mtf.update(bad)

    assert mtf._tick_count == 0
    assert not mtf.is_warmed_up


def test_wave59_warmup_and_seeding():
    mtf = MATrendFilter(period=50)
    # Feed 49 ticks at 2000.0 (< 50) -> not warmed up
    for _ in range(49):
        mtf.update(2000.0)
    assert not mtf.is_warmed_up
    assert mtf.get_ema() == 0.0

    # 50th tick seeds the EMA at 2000.0
    mtf.update(2000.0)
    assert mtf.is_warmed_up
    assert mtf.get_ema() == 2000.0
    # At exact equality, trend evaluates to BEARISH (not > ema)
    assert mtf.info()["trend"] == "BEARISH"
    # Price above EMA gives BULLISH
    mtf.update(2005.0)
    assert mtf.info()["trend"] == "BULLISH"


def test_wave59_trend_alignment_blocks():
    mtf = MATrendFilter(period=50)
    for _ in range(50):
        mtf.update(2000.0)
    assert mtf.get_ema() == 2000.0

    # Case 1: Bearish trend — current price 1990.0 < EMA 2000.0
    # BUY should be blocked, SELL allowed
    res_buy = mtf.is_signal_blocked("BUY", price=1990.0)
    assert res_buy.blocked
    assert res_buy.reason == "price_below_ema"
    assert mtf.is_entry_blocked("BUY", price=1990.0)
    assert not mtf.is_signal_blocked("SELL", price=1990.0).blocked

    # Case 2: Bullish trend — current price 2010.0 > EMA 2000.0
    # SELL should be blocked, BUY allowed
    res_sell = mtf.is_signal_blocked("SELL", price=2010.0)
    assert res_sell.blocked
    assert res_sell.reason == "price_above_ema"
    assert mtf.is_entry_blocked("SELL", price=2010.0)
    assert not mtf.is_signal_blocked("BUY", price=2010.0).blocked


def test_wave59_block_result_and_module_aliases():
    mtf = MATrendFilter(period=50)
    for _ in range(50):
        mtf.update(2000.0)

    # Test BlockResult subscripting and iteration
    res = mtf.is_signal_blocked("BUY", price=1980.0)
    assert res[0] is True
    assert "price_below_ema" in res[1]
    blocked, reason = res
    assert blocked is True
    assert reason == "price_below_ema"

    mtf.reset()
    assert not mtf.is_warmed_up
    assert mtf.get_ema() == 0.0

    # Module-level aliases
    w59_reset()
    assert not w59_is_entry_blocked("BUY")
    assert not w59_is_blocked("SELL")
    assert w59_get_ema() == 0.0
    w59_update(2000.0)
    w59_reset()
