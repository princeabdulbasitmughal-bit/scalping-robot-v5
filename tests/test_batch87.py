"""
tests/test_batch87.py
Batch 87 Unit Tests: Flat Market Price Range Filter & EMA Trend Alignment (wave58 & wave59).
Expands test baseline beyond 1,117+ passing tests.
Verifies:
1. wave58: PriceRangeFilter initialization defaults, pip value, and parameter sanitization.
2. wave58: Intraday high/low tracking, tick counting, and range pips calculation.
3. wave58: UTC midnight day rollover and automatic metric resets.
4. wave58: Flat market entry blocking when range < min_range_pips after min_ticks threshold.
5. wave58: Active market clearance, is_trading_allowed tuple, and advisory warm-up behavior.
6. wave58: PriceRangeFilter reset() and info() telemetry introspection.
7. wave59: BlockResult subclass duality (boolean, tuple, indexable sequence, integer).
8. wave59: MATrendFilter warmup period, SMA initial seeding, and warmup immunity.
9. wave59: Trend alignment filtering (blocking counter-trend BUY below EMA and SELL above EMA).
10. wave59: MATrendFilter reset() clearing and info() telemetry introspection.
"""

import math
from datetime import datetime, timezone
import pytest

from wave58_price_range_filter import PriceRangeFilter
from wave59_ma_trend_filter import MATrendFilter, BlockResult


def test_wave58_initialization_defaults_and_clamping():
    """Verify PriceRangeFilter initializes with valid defaults and clamps invalid inputs."""
    # Default initialization
    prf = PriceRangeFilter()
    assert prf.min_range_pips == 5.0
    assert prf.pip_value == 0.1
    assert prf.min_ticks == 50

    # Custom clamped initialization
    prf_custom = PriceRangeFilter(min_range_pips=-1.0, pip_value=-0.5, min_ticks=-10)
    assert prf_custom.min_range_pips == 5.0
    assert prf_custom.pip_value == 0.1
    assert prf_custom.min_ticks == 1


def test_wave58_update_high_low_and_range_pips():
    """Verify update tracks high and low and get_range_pips calculates accurate pip span."""
    prf = PriceRangeFilter(pip_value=0.1)
    base_dt = datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)

    # Feed ticks: min 2645.0, max 2655.0
    for p in [2650.0, 2645.0, 2655.0, 2648.0]:
        prf.update(p, now_dt=base_dt)

    assert prf._day_high == 2655.0
    assert prf._day_low == 2645.0
    assert prf._ticks_today == 4

    # Range pips: (2655.0 - 2645.0) / 0.1 = 100.0 pips
    assert prf.get_range_pips(now_dt=base_dt) == 100.0

    # Ignore invalid prices
    prf.update(None, now_dt=base_dt)
    prf.update(True, now_dt=base_dt)
    prf.update(float("nan"), now_dt=base_dt)
    prf.update(-2650.0, now_dt=base_dt)
    assert prf._ticks_today == 4


def test_wave58_day_rollover_resets_high_low():
    """Verify UTC day change resets high/low and tick counters."""
    prf = PriceRangeFilter()
    day1 = datetime(2026, 10, 18, 23, 50, 0, tzinfo=timezone.utc)
    prf.update(2650.0, now_dt=day1)
    assert prf._ticks_today == 1
    assert prf._day_high == 2650.0

    # Day 2 rollover
    day2 = datetime(2026, 10, 19, 0, 5, 0, tzinfo=timezone.utc)
    prf.update(2660.0, now_dt=day2)
    assert prf._ticks_today == 1
    assert prf._day_high == 2660.0
    assert prf._day_low == 2660.0


def test_wave58_flat_market_entry_blocking():
    """Verify market is blocked when daily range < min_range_pips after min_ticks threshold."""
    prf = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=10)
    now_dt = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)

    # Feed 10 ticks in a dead range: 2650.0 to 2650.2 (range 0.2 / 0.1 = 2.0 pips < 5.0 pips)
    for i in range(10):
        p = 2650.0 + (0.2 if i % 2 == 0 else 0.0)
        prf.update(p, now_dt=now_dt)

    assert prf.get_range_pips(now_dt=now_dt) == 2.0
    assert prf.is_entry_blocked(now_dt=now_dt) is True
    assert prf.is_blocked(now_dt=now_dt) is True

    allowed, reason = prf.is_trading_allowed(now_dt=now_dt)
    assert allowed is False
    assert "FLAT_MARKET" in reason


def test_wave58_active_market_allows_trading():
    """Verify active market above min_range_pips is allowed and pre-threshold ticks do not block."""
    prf = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=10)
    now_dt = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Under min_ticks (e.g. 5 ticks) -> not blocked yet
    for _ in range(5):
        prf.update(2650.0, now_dt=now_dt)
    assert prf.is_entry_blocked(now_dt=now_dt) is False

    # 2. Add ticks expanding range to 10.0 pips (2650.0 to 2651.0)
    for _ in range(10):
        prf.update(2651.0, now_dt=now_dt)

    assert prf.get_range_pips(now_dt=now_dt) == 10.0
    assert prf.is_entry_blocked(now_dt=now_dt) is False
    allowed, reason = prf.is_trading_allowed(now_dt=now_dt)
    assert allowed is True
    assert reason == ""


def test_wave58_reset_and_info_introspection():
    """Verify reset() clears internal state and info() outputs diagnostic status."""
    prf = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=5)
    now_dt = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)

    for p in [2648.0, 2652.0]:
        prf.update(p, now_dt=now_dt)

    info = prf.info(now_dt=now_dt)
    assert info["wave"] == 58
    assert info["name"] == "PriceRangeFilter"
    assert info["day_high"] == 2652.0
    assert info["day_low"] == 2648.0
    assert info["range_pips"] == 40.0
    assert info["ticks_today"] == 2

    prf.reset()
    info_reset = prf.info(now_dt=now_dt)
    assert info_reset["day_high"] is None
    assert info_reset["day_low"] is None
    assert info_reset["ticks_today"] == 0


def test_wave59_block_result_duality_and_subclassing():
    """Verify wave59 BlockResult behaves as boolean, tuple, indexable, and integer."""
    res_block = BlockResult(True, "price_below_ema")
    assert bool(res_block) is True
    assert res_block.blocked is True
    assert res_block.reason == "price_below_ema"
    assert res_block[0] is True
    assert res_block[1] == "price_below_ema"
    assert int(res_block) == 1
    assert "BlockResult(True" in repr(res_block)

    # Tuple unpack
    blk, rsn = res_block
    assert blk is True
    assert rsn == "price_below_ema"

    with pytest.raises(IndexError):
        _ = res_block[2]

    res_allow = BlockResult(False, "trend_aligned")
    assert bool(res_allow) is False
    assert int(res_allow) == 0


def test_wave59_initialization_and_warmup_seeding():
    """Verify MATrendFilter initialization, warmup period immunity, and SMA seeding."""
    filter_inst = MATrendFilter(period=5)
    assert filter_inst.period == 5
    assert filter_inst.is_warmed_up is False

    # Feed 4 prices (under period=5)
    for p in [2650.0, 2652.0, 2648.0, 2650.0]:
        filter_inst.update(p)
        assert filter_inst.is_warmed_up is False
        # During warmup, never blocks
        res = filter_inst.is_signal_blocked("BUY")
        assert bool(res) is False
        assert res.reason == "warmup_or_zero_ema"

    # 5th price -> completes warmup and seeds with SMA
    filter_inst.update(2650.0)
    assert filter_inst.is_warmed_up is True
    expected_sma = (2650.0 + 2652.0 + 2648.0 + 2650.0 + 2650.0) / 5.0
    assert pytest.approx(filter_inst.get_ema(), abs=1e-4) == expected_sma


def test_wave59_trend_alignment_blocking():
    """Verify counter-trend signals are blocked (BUY < EMA, SELL > EMA) and aligned signals pass."""
    filter_inst = MATrendFilter(period=3)

    # Seed with 2650.0
    for _ in range(3):
        filter_inst.update(2650.0)
    assert filter_inst.is_warmed_up is True
    assert filter_inst.get_ema() == 2650.0

    # 1. Price < EMA (2648.0 < 2650.0): Bearish trend
    # BUY should be blocked
    res_buy_block = filter_inst.is_signal_blocked("BUY", price=2648.0)
    assert bool(res_buy_block) is True
    assert res_buy_block.reason == "price_below_ema"
    assert filter_inst.is_entry_blocked("BUY", price=2648.0) is True

    allowed, reason = filter_inst.is_trading_allowed("BUY", price=2648.0)
    assert allowed is False
    assert reason == "price_below_ema"

    # SELL should be allowed
    res_sell_pass = filter_inst.is_signal_blocked("SELL", price=2648.0)
    assert bool(res_sell_pass) is False
    assert res_sell_pass.reason == "trend_aligned"

    # 2. Price > EMA (2652.0 > 2650.0): Bullish trend
    # SELL should be blocked
    res_sell_block = filter_inst.is_signal_blocked("SELL", price=2652.0)
    assert bool(res_sell_block) is True
    assert res_sell_block.reason == "price_above_ema"

    # BUY should be allowed
    res_buy_pass = filter_inst.is_signal_blocked("BUY", price=2652.0)
    assert bool(res_buy_pass) is False
    assert res_buy_pass.reason == "trend_aligned"

    # 3. Non-directional signal
    assert filter_inst.is_signal_blocked("HOLD").reason == "non_directional_signal"


def test_wave59_reset_and_info_telemetry():
    """Verify reset() clears internal EMA state and info() outputs diagnostic telemetry."""
    filter_inst = MATrendFilter(period=3)
    for p in [2650.0, 2652.0, 2654.0]:
        filter_inst.update(p)

    info = filter_inst.info()
    assert info["wave"] == 59
    assert info["name"] == "MATrendFilter"
    assert info["period"] == 3
    assert info["warmed_up"] is True
    assert info["trend"] == "BULLISH"  # last price 2654.0 > ema ~2652.0

    filter_inst.reset()
    info_reset = filter_inst.info()
    assert info_reset["warmed_up"] is False
    assert info_reset["ema50"] is None
    assert info_reset["trend"] == "NEUTRAL"
