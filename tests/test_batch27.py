"""
Unit tests for Batch 27: Wave Modules Hardening
Covers:
- wave55_balance_floor_guard
- wave58_price_range_filter
- wave59_ma_trend_filter
- wave60_profit_streak_booster
- wave61_opening_range_breakout
- wave44_price_velocity_filter
- wave47_atr_position_sizer
- wave48_equity_high_watermark
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from wave55_balance_floor_guard import BalanceFloorGuard
from wave58_price_range_filter import PriceRangeFilter
from wave59_ma_trend_filter import MATrendFilter, BlockResult as MABlockResult
from wave60_profit_streak_booster import ProfitStreakBooster
from wave61_opening_range_breakout import OpeningRangeBreakout, BlockResult as ORBBlockResult
from wave44_price_velocity_filter import PriceVelocityFilter
from wave47_atr_position_sizer import ATRPositionSizer
from wave48_equity_high_watermark import EquityHighWatermark


# ==============================================================================
# Wave 55: BalanceFloorGuard
# ==============================================================================
def test_wave55_balance_floor_guard():
    guard = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)

    # 1. Properties
    assert guard.floor_usd == 9500.0
    assert guard.min_balance == 9500.0
    assert guard.is_halted is False

    dt1 = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)

    # 2. Normal balance above floor
    guard.update(10000.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is False
    assert guard.is_trading_allowed(now_dt=dt1)[0] is True

    # 3. Breach floor: $9400 < $9500 -> HALT
    guard.update(9400.0, now_dt=dt1)
    assert guard.is_halted is True
    assert guard.is_entry_blocked(now_dt=dt1) is True
    allowed, reason = guard.is_trading_allowed(now_dt=dt1)
    assert allowed is False
    assert "BALANCE_FLOOR" in reason

    # 4. Intraday hysteresis: rising to $9520 (< floor + 50 = $9550) keeps halt active
    guard.update(9520.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is True

    # Rising to $9560 (>= $9550) lifts halt
    guard.update(9560.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is False
    assert guard.is_halted is False

    # 5. Catastrophic blowout guard: balance <= 0
    guard.update(-50.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is True

    # 6. Reset & Info
    guard.reset()
    assert guard.is_halted is False
    info = guard.info()
    assert info["wave"] == 55
    assert info["name"] == "BalanceFloorGuard"


# ==============================================================================
# Wave 58: PriceRangeFilter
# ==============================================================================
def test_wave58_price_range_filter():
    prf = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=5)

    # 1. Invalid input guards
    prf.update(None)
    prf.update(True)
    prf.update(float("nan"))
    prf.update(-100.0)
    assert prf._ticks_today == 0

    dt_day1 = datetime(2026, 10, 17, 8, 0, tzinfo=timezone.utc)

    # 2. Flat market: 5 ticks spanning only 2000.0 to 2000.2 (2 pips < 5 pips)
    for p in [2000.0, 2000.1, 2000.15, 2000.05, 2000.2]:
        prf.update(p, now_dt=dt_day1)

    assert prf.get_range_pips(now_dt=dt_day1) == 2.0
    assert prf.is_entry_blocked(now_dt=dt_day1) is True
    allowed, reason = prf.is_trading_allowed(now_dt=dt_day1)
    assert allowed is False
    assert "FLAT_MARKET" in reason

    # 3. Active market: price reaches 2001.0 (range 10 pips >= 5 pips)
    prf.update(2001.0, now_dt=dt_day1)
    assert prf.get_range_pips(now_dt=dt_day1) == 10.0
    assert prf.is_entry_blocked(now_dt=dt_day1) is False

    # 4. UTC Midnight rollover
    dt_day2 = datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc)
    prf.update(2005.0, now_dt=dt_day2)
    assert prf._ticks_today == 1

    prf.reset()
    assert prf._ticks_today == 0
    info = prf.info()
    assert info["wave"] == 58
    assert info["name"] == "PriceRangeFilter"


# ==============================================================================
# Wave 59: MATrendFilter
# ==============================================================================
def test_wave59_ma_trend_filter():
    maf = MATrendFilter(period=5)

    # 1. BlockResult subscripting and interface check
    res = MABlockResult(True, "test_reason")
    assert res.blocked is True
    assert res.reason == "test_reason"
    assert res[0] is True
    assert res[1] == "test_reason"
    assert bool(res) is True
    b_val, r_val = res
    assert b_val is True and r_val == "test_reason"

    # 2. Warm-up period (< 5 ticks) does not block
    for p in [2000.0, 2001.0, 2002.0]:
        maf.update(p)
    assert maf.is_signal_blocked("BUY")[0] is False
    assert maf.is_signal_blocked("SELL")[0] is False

    # 3. Complete warmup: feed 2 more ticks
    maf.update(2003.0)
    maf.update(2004.0)
    ema = maf.get_ema()
    assert ema > 0.0

    # Feed rising price: 2010.0 > EMA -> Bullish trend
    maf.update(2010.0)
    # BUY is trend-aligned
    assert maf.is_signal_blocked("BUY")[0] is False
    # SELL is counter-trend -> blocked!
    res_sell = maf.is_signal_blocked("SELL")
    assert res_sell[0] is True
    assert res_sell.blocked is True
    assert "price_above_ema" in res_sell[1]

    # Feed dropping price: 1980.0 < EMA -> Bearish trend
    for _ in range(5):
        maf.update(1980.0)
    assert maf.is_signal_blocked("SELL")[0] is False
    assert maf.is_signal_blocked("BUY")[0] is True

    maf.reset()
    assert maf.get_ema() == 0.0
    info = maf.info()
    assert info["wave"] == 59
    assert info["name"] == "MATrendFilter"


# ==============================================================================
# Wave 60: ProfitStreakBooster
# ==============================================================================
def test_wave60_profit_streak_booster():
    booster = ProfitStreakBooster(streak_length=3, tp_multiplier=1.2)

    # 1. Normal state
    assert booster.is_in_streak() is False
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(15.0) == 15.0

    # 2. Record 2 wins (not yet 3)
    booster.record_trade(True)
    booster.record_trade(15.5)  # numeric pnl > 0
    assert booster.is_in_streak() is False
    assert booster.get_tp_multiplier() == 1.0

    # 3. 3rd consecutive win triggers confidence mode!
    booster.record_trade(True)
    assert booster.is_in_streak() is True
    assert booster.get_tp_multiplier() == 1.2
    assert booster.adjust_tp(15.0) == 18.0

    # 4. Losing trade breaks the streak
    booster.record_trade(False)
    assert booster.is_in_streak() is False
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(15.0) == 15.0

    # 5. Reset & Info
    booster.reset()
    assert booster._current_streak == 0
    info = booster.info()
    assert info["wave"] == 60
    assert info["name"] == "ProfitStreakBooster"


# ==============================================================================
# Wave 61: OpeningRangeBreakout
# ==============================================================================
def test_wave61_opening_range_breakout():
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)

    # 1. BlockResult subscripting
    res = ORBBlockResult(False, "ok")
    assert res[0] is False
    assert res[1] == "ok"

    # London Open: 08:05 UTC (within 15m grace)
    dt_open = datetime(2026, 10, 17, 8, 5, tzinfo=timezone.utc)
    for p in [2000.0, 2005.0, 1995.0, 2002.0, 2001.0]:
        orb.update(p, now_dt=dt_open)

    # In window: window not complete yet -> no blocking
    assert orb.is_signal_blocked("BUY", now_dt=dt_open)[0] is False

    # 35 minutes later: 08:35 UTC -> window completed!
    dt_post = datetime(2026, 10, 17, 8, 35, tzinfo=timezone.utc)
    orb.update(2003.0, now_dt=dt_post)  # triggers window completion
    assert orb._window_complete is True
    assert orb._or_high == 2005.0
    assert orb._or_low == 1995.0

    # Price inside range (2002.0): BUY blocked (not above 2005.0), SELL blocked (not below 1995.0)
    assert orb.is_signal_blocked("BUY", price=2002.0, now_dt=dt_post)[0] is True
    assert orb.is_signal_blocked("SELL", price=2002.0, now_dt=dt_post)[0] is True

    # Breakout UP: price 2008.0 > OR_high 2005.0 -> BUY allowed!
    assert orb.is_signal_blocked("BUY", price=2008.0, now_dt=dt_post)[0] is False

    # Breakout DOWN: price 1990.0 < OR_low 1995.0 -> SELL allowed!
    assert orb.is_signal_blocked("SELL", price=1990.0, now_dt=dt_post)[0] is False

    orb.reset()
    assert orb._window_complete is False
    info = orb.info()
    assert info["wave"] == 61
    assert info["name"] == "OpeningRangeBreakout"


# ==============================================================================
# Wave 44: PriceVelocityFilter
# ==============================================================================
def test_wave44_price_velocity_filter():
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)

    t0 = 1000.0
    # Normal velocity: 2 pips in 2s
    pvf.update(2000.0, now_ts=t0)
    pvf.update(2000.2, now_ts=t0 + 2.0)
    assert pvf.is_entry_blocked(now_ts=t0 + 2.0) is False
    assert pvf.is_trading_allowed(now_ts=t0 + 2.0)[0] is True

    # Velocity spike: price moves 6 pips in 1s (> 5.0 pip limit)
    pvf.update(2000.8, now_ts=t0 + 2.5)
    assert pvf.is_entry_blocked(now_ts=t0 + 2.5) is True
    allowed, reason = pvf.is_trading_allowed(now_ts=t0 + 2.5)
    assert allowed is False
    assert "VELOCITY_LIMIT" in reason

    # After window passes (t0 + 10s): old ticks outside 3s window
    assert pvf.is_entry_blocked(now_ts=t0 + 10.0) is False

    pvf.reset()
    assert len(pvf._history) == 0
    info = pvf.info()
    assert info["wave"] == 44
    assert info["name"] == "PriceVelocityFilter"


# ==============================================================================
# Wave 47: ATRPositionSizer
# ==============================================================================
def test_wave47_atr_position_sizer():
    sizer = ATRPositionSizer(period=5)

    # 1. Invalid input guards
    sizer.update(2000.0, 2005.0)  # high < low -> rejected
    sizer.update(None, 1990.0)
    assert len(sizer._closes) == 0

    # 2. Feed 6 bars with 2-pip ranges
    for i in range(6):
        sizer.update(high=2000.0 + i + 2.0, low=2000.0 + i, close=2000.0 + i + 1.0)

    atr = sizer.get_atr()
    assert atr > 0.0
    sl, tp = sizer.get_sl_tp(base_sl=30.0, base_tp=45.0)
    assert 15.0 <= sl <= 60.0
    assert 22.0 <= tp <= 90.0

    # 3. Position sizing helper
    lot = sizer.get_lot_size(account_balance=10000.0, risk_pct=0.01, sl_pips=30.0, pip_value=10.0)
    # Risk USD = 10000 * 0.01 = $100. Risk per lot = 30 * 10 = $300. Lot = 100 / 300 = 0.33 lots
    assert 0.30 <= lot <= 0.35

    sizer.reset()
    assert sizer.get_atr() == 0.0
    info = sizer.info()
    assert info["wave"] == 47
    assert info["name"] == "ATRPositionSizer"


# ==============================================================================
# Wave 48: EquityHighWatermark
# ==============================================================================
def test_wave48_equity_high_watermark():
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=60.0)

    t0 = 1000.0
    # 1. Normal equity progression
    ehw.update(10000.0, now_ts=t0)
    assert ehw._watermark == 10000.0
    assert ehw.is_entry_blocked(now_ts=t0) is False

    ehw.update(10500.0, now_ts=t0 + 10)
    assert ehw._watermark == 10500.0

    # 2. Drawdown: drop to 10200.0 (300 drop / 10500 = 2.85% > 2.0%) -> triggers block!
    ehw.update(10200.0, now_ts=t0 + 20)
    assert ehw.is_entry_blocked(now_ts=t0 + 20) is True
    allowed, reason = ehw.is_trading_allowed(now_ts=t0 + 20)
    assert allowed is False
    assert "WATERMARK_DD" in reason

    # 3. After block_sec (60s): unblocks
    assert ehw.is_entry_blocked(now_ts=t0 + 90) is False
    assert ehw.is_trading_allowed(now_ts=t0 + 90)[0] is True

    ehw.reset()
    assert ehw._watermark == 0.0
    info = ehw.info(now_ts=t0 + 90)
    assert info["wave"] == 48
    assert info["name"] == "EquityHighWatermark"
