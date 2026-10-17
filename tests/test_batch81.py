"""
tests/test_batch81.py
Batch 81 Unit Tests: Scalping Engine Indicator Pipeline, News Blackout Windows & Volatility Guards (python_engine/scalping_engine.py).
Expands test baseline beyond 1,057+ passing tests.
Verifies:
1. EconomicNewsFilter: Timestamp parsing across epoch, datetime, ISO 8601, and standard date strings.
2. EconomicNewsFilter: Pre-event (15m) and post-event (30m) blackout window gating.
3. EconomicNewsFilter: Currency filtering and event list thread-safe management.
4. ScalpingRobotV5: Wilder's RSI calculation with recursive smoothing and boundary behavior.
5. ScalpingRobotV5: Bollinger Bands calculation, symmetry, and width percentage.
6. ScalpingRobotV5: Dual EMA calculation and Bullish/Bearish trend determination.
7. ScalpingRobotV5: Market regime classification (LOW, NORMAL, HIGH, EXTREME_SPIKE).
8. ScalpingRobotV5: Entry gating for spread ceiling and max orders limits.
9. ScalpingRobotV5: Entry confluence for BUY and SELL signals.
10. ScalpingRobotV5: Dynamic ATR stop buffer calculation, position sizing, and engine reset.
"""

import math
import time
from datetime import datetime, timezone, timedelta
import pytest

from python_engine.scalping_engine import (
    EconomicNewsFilter,
    ScalpingRobotV5,
    ScalpingSignal,
    MarketRegime,
)


def test_news_filter_timestamp_parsing():
    """Verify _parse_timestamp handles int, float, datetime, ISO-8601, and standard format strings."""
    filter_inst = EconomicNewsFilter(pre_minutes=15, post_minutes=30)

    # 1. Float and Int epochs
    assert filter_inst._parse_timestamp(1700000000.5) == 1700000000.5
    assert filter_inst._parse_timestamp(1700000000) == 1700000000.0

    # 2. Datetime naive and UTC-aware
    dt_naive = datetime(2026, 10, 18, 12, 0, 0)
    expected_ts = dt_naive.replace(tzinfo=timezone.utc).timestamp()
    assert filter_inst._parse_timestamp(dt_naive) == expected_ts

    dt_aware = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
    assert filter_inst._parse_timestamp(dt_aware) == expected_ts

    # 3. ISO format strings
    iso_str_z = "2026-10-18T12:00:00Z"
    assert filter_inst._parse_timestamp(iso_str_z) == expected_ts

    iso_str_offset = "2026-10-18T12:00:00+00:00"
    assert filter_inst._parse_timestamp(iso_str_offset) == expected_ts

    # 4. Standard date/time strings
    std_str_sec = "2026-10-18 12:00:00"
    assert filter_inst._parse_timestamp(std_str_sec) == expected_ts

    std_str_min = "2026-10-18 12:00"
    assert filter_inst._parse_timestamp(std_str_min) == expected_ts

    # 5. Invalid input fallback to 0.0
    assert filter_inst._parse_timestamp("invalid-date-string") == 0.0
    assert filter_inst._parse_timestamp(None) == 0.0


def test_news_filter_blackout_window_pre_and_post_gating():
    """Verify is_blackout correctly gates within pre-event (15m) and post-event (30m) windows."""
    filter_inst = EconomicNewsFilter(pre_minutes=15, post_minutes=30)
    filter_inst.clear_events()

    event_time = 1750000000.0  # reference epoch
    filter_inst.add_event(
        event_time=event_time,
        event_name="US CPI Release",
        currency="USD",
        impact="HIGH",
    )

    # Outside before pre-window: 901 seconds before (15m = 900s)
    blackout, info = filter_inst.is_blackout(current_time=event_time - 901)
    assert not blackout
    assert info is None

    # Exactly at start of pre-window: 900 seconds before
    blackout, info = filter_inst.is_blackout(current_time=event_time - 900)
    assert blackout
    assert info is not None
    assert info["phase"] == "PRE_EVENT"
    assert info["seconds_to_event"] == 900.0
    assert info["event"] == "US CPI Release"

    # Mid-event: exactly at event time
    blackout, info = filter_inst.is_blackout(current_time=event_time)
    assert blackout
    assert info["phase"] == "POST_EVENT"
    assert info["seconds_to_event"] == 0.0

    # Inside post-window: 1800 seconds after (30m = 1800s)
    blackout, info = filter_inst.is_blackout(current_time=event_time + 1800)
    assert blackout
    assert info["phase"] == "POST_EVENT"
    assert info["seconds_to_event"] == -1800.0

    # Outside after post-window: 1801 seconds after
    blackout, info = filter_inst.is_blackout(current_time=event_time + 1801)
    assert not blackout
    assert info is None

    # Invalid timestamp returns False
    blackout, info = filter_inst.is_blackout(current_time=float("nan"))
    assert not blackout
    assert info is None


def test_news_filter_currency_and_impact_filtering():
    """Verify currency filtering isolates target currency events and clear_events empties schedule."""
    filter_inst = EconomicNewsFilter(pre_minutes=10, post_minutes=20)
    filter_inst.clear_events()

    t_base = 1750000000.0
    filter_inst.add_event(t_base, "US NFP", currency="USD", impact="HIGH")
    filter_inst.add_event(t_base, "ECB Rate", currency="EUR", impact="HIGH")

    # Querying USD only matches USD
    blackout_usd, info_usd = filter_inst.is_blackout(current_time=t_base, currency="USD")
    assert blackout_usd
    assert info_usd["currency"] == "USD"
    assert info_usd["event"] == "US NFP"

    # Querying EUR only matches EUR
    blackout_eur, info_eur = filter_inst.is_blackout(current_time=t_base, currency="EUR")
    assert blackout_eur
    assert info_eur["currency"] == "EUR"
    assert info_eur["event"] == "ECB Rate"

    # Querying GBP matches nothing
    blackout_gbp, info_gbp = filter_inst.is_blackout(current_time=t_base, currency="GBP")
    assert not blackout_gbp
    assert info_gbp is None

    # Querying without currency matches the first active event (USD)
    blackout_any, info_any = filter_inst.is_blackout(current_time=t_base, currency=None)
    assert blackout_any
    assert info_any is not None

    # Clear events
    filter_inst.clear_events()
    assert len(filter_inst.events) == 0
    blackout_cleared, _ = filter_inst.is_blackout(current_time=t_base)
    assert not blackout_cleared


def test_scalping_engine_wilder_rsi_calculation():
    """Verify Wilder's smoothed RSI adheres to bounds, boundary cases, and recursive smoothing."""
    robot = ScalpingRobotV5()

    # 1. Insufficient data -> 50.0 neutral
    assert robot._calc_rsi([], 14) == 50.0
    assert robot._calc_rsi([100.0] * 10, 14) == 50.0
    assert robot._calc_rsi([100.0] * 20, 0) == 50.0

    # 2. Constant series (all gains and losses 0.0) -> 50.0
    assert robot._calc_rsi([100.0] * 25, 14) == 50.0

    # 3. Strictly increasing series -> 100.0
    upward = [100.0 + i * 2.0 for i in range(25)]
    assert robot._calc_rsi(upward, 14) == 100.0

    # 4. Strictly decreasing series -> 0.0
    downward = [200.0 - i * 2.0 for i in range(25)]
    assert robot._calc_rsi(downward, 14) == 0.0

    # 5. Alternating series produces realistic bounded RSI (0 < RSI < 100)
    alternating = [100.0 + (i % 2) * 5.0 for i in range(30)]
    rsi_alt = robot._calc_rsi(alternating, 14)
    assert 0.0 < rsi_alt < 100.0


def test_scalping_engine_bollinger_bands_and_width():
    """Verify Bollinger Bands calculate upper, mid, lower, and width percentage correctly."""
    robot = ScalpingRobotV5({"bb_period": 20, "bb_std": 2.0})

    # Minimum required is max(20, 21, 14, 14) + 5 = 26 bars
    bars = []
    base_price = 2650.0
    for i in range(30):
        bars.append({
            "open": base_price,
            "high": base_price + 2.0,
            "low": base_price - 2.0,
            "close": base_price + (1.0 if i % 2 == 0 else -1.0),
            "volume": 100,
            "timestamp": 1700000000 + i * 60,
        })

    ind = robot.calculate_indicators(bars)
    assert ind != {}
    assert "bb_upper" in ind
    assert "bb_mid" in ind
    assert "bb_lower" in ind
    assert "bb_width_pct" in ind

    # Symmetrical bands
    assert ind["bb_upper"] > ind["bb_mid"] > ind["bb_lower"]
    assert pytest.approx(ind["bb_upper"] - ind["bb_mid"], abs=1e-5) == (ind["bb_mid"] - ind["bb_lower"])
    assert ind["bb_width_pct"] > 0

    # Insufficient bars returns empty dict
    assert robot.calculate_indicators(bars[:15]) == {}


def test_scalping_engine_ema_and_trend_determination():
    """Verify _calc_ema calculation and bullish/bearish trend determination in indicators."""
    robot = ScalpingRobotV5({"fast_ema": 8, "slow_ema": 21})

    # Empty or zero period
    assert robot._calc_ema([], 8) == 0.0
    assert robot._calc_ema([10.0, 20.0], 0) == 0.0
    assert robot._calc_ema([10.0, 20.0], 5) == 20.0  # len < period returns last

    # Constant series EMA equals the constant value
    const_series = [2650.0] * 30
    assert pytest.approx(robot._calc_ema(const_series, 8), abs=1e-6) == 2650.0

    # Upward trending bars -> Bullish trend
    bullish_bars = []
    for i in range(35):
        p = 2600.0 + i * 3.0
        bullish_bars.append({
            "open": p - 1.0, "high": p + 2.0, "low": p - 2.0, "close": p,
            "volume": 100, "timestamp": 1700000000 + i * 60
        })
    ind_bull = robot.calculate_indicators(bullish_bars)
    assert ind_bull["fast_ema"] > ind_bull["slow_ema"]
    assert ind_bull["trend"] == "BULLISH"

    # Downward trending bars -> Bearish trend
    bearish_bars = []
    for i in range(35):
        p = 2700.0 - i * 3.0
        bearish_bars.append({
            "open": p + 1.0, "high": p + 2.0, "low": p - 2.0, "close": p,
            "volume": 100, "timestamp": 1700000000 + i * 60
        })
    ind_bear = robot.calculate_indicators(bearish_bars)
    assert ind_bear["fast_ema"] < ind_bear["slow_ema"]
    assert ind_bear["trend"] == "BEARISH"


def test_scalping_engine_market_regime_classification():
    """Verify market regime classifies NORMAL, LOW, HIGH, and EXTREME_SPIKE based on volatility ratio."""
    robot = ScalpingRobotV5({"volatility_spike_threshold": 2.2})

    # Generate baseline bars with moderate fluctuation (range ~2.0)
    bars = []
    base = 2650.0
    for i in range(35):
        bars.append({
            "open": base, "high": base + 1.0, "low": base - 1.0, "close": base,
            "volume": 100, "timestamp": 1700000000 + i * 60
        })

    # 1. Normal volatility
    ind_normal = robot.calculate_indicators(bars)
    assert ind_normal["volatility_regime"] in (MarketRegime.NORMAL_VOLATILITY, MarketRegime.LOW_VOLATILITY)

    # 2. Extreme spike on the last bar: high - low = 15.0 vs normal ~2.0
    spike_bars = list(bars)
    spike_bars[-1] = {
        "open": base, "high": base + 10.0, "low": base - 5.0, "close": base + 8.0,
        "volume": 500, "timestamp": 1700000000 + 35 * 60
    }
    ind_spike = robot.calculate_indicators(spike_bars)
    assert ind_spike["volatility_ratio"] >= 2.2
    assert ind_spike["volatility_regime"] == MarketRegime.EXTREME_SPIKE


def test_scalping_engine_entry_spread_and_order_guards():
    """Verify evaluate_entry halts on wide spread or reaching maximum open positions."""
    robot = ScalpingRobotV5({"max_spread_pips": 3.0, "max_orders": 1})

    dummy_indicators = {
        "close": 2650.0,
        "bb_lower": 2645.0,
        "bb_upper": 2655.0,
        "fast_ema": 2650.0,
        "slow_ema": 2650.0,
        "rsi": 50.0,
        "volatility_ratio": 1.0,
    }

    # 1. Empty indicators -> HOLD
    assert robot.evaluate_entry({}) == ScalpingSignal.HOLD

    # 2. Spread exceeds limit (3.5 > 3.0)
    sig_spread = robot.evaluate_entry(dummy_indicators, current_spread_pips=3.5)
    assert sig_spread == ScalpingSignal.HOLD
    assert robot.shield_status["status"] == "SPREAD_PROTECTION"
    assert robot.shield_status["halted"] is True

    # 3. Open orders exceed limit
    robot.open_positions.append({"ticket": 12345, "type": "BUY", "price": 2650.0})
    sig_orders = robot.evaluate_entry(dummy_indicators, current_spread_pips=1.0)
    assert sig_orders == ScalpingSignal.HOLD
    assert robot.shield_status["status"] == "MAX_ORDERS_REACHED"
    assert robot.shield_status["halted"] is True


def test_scalping_engine_entry_signals_confluence():
    """Verify evaluate_entry generates BUY and SELL signals when technical confluence is met."""
    robot = ScalpingRobotV5({
        "max_spread_pips": 5.0,
        "news_filter_enabled": False,
        "volatility_shield_enabled": False,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
    })

    # BUY confluence:
    # price <= bb_lower * 1.0005 AND rsi <= 33 AND fast_ema >= slow_ema * 0.9998
    buy_indicators = {
        "close": 2640.0,
        "bb_lower": 2640.0,
        "bb_upper": 2660.0,
        "fast_ema": 2645.0,
        "slow_ema": 2645.0,
        "rsi": 28.0,
        "volatility_ratio": 1.0,
    }
    assert robot.evaluate_entry(buy_indicators, current_spread_pips=1.0) == ScalpingSignal.BUY

    # SELL confluence:
    # price >= bb_upper * 0.9995 AND rsi >= 67 AND fast_ema <= slow_ema * 1.0002
    sell_indicators = {
        "close": 2660.0,
        "bb_lower": 2640.0,
        "bb_upper": 2660.0,
        "fast_ema": 2655.0,
        "slow_ema": 2655.0,
        "rsi": 72.0,
        "volatility_ratio": 1.0,
    }
    assert robot.evaluate_entry(sell_indicators, current_spread_pips=1.0) == ScalpingSignal.SELL

    # Neutral conditions -> HOLD
    neutral_indicators = {
        "close": 2650.0,
        "bb_lower": 2640.0,
        "bb_upper": 2660.0,
        "fast_ema": 2650.0,
        "slow_ema": 2650.0,
        "rsi": 50.0,
        "volatility_ratio": 1.0,
    }
    assert robot.evaluate_entry(neutral_indicators, current_spread_pips=1.0) == ScalpingSignal.HOLD


def test_scalping_engine_dynamic_stops_and_sizing():
    """Verify dynamic stops calculation, position sizing, and engine state reset."""
    robot = ScalpingRobotV5({
        "symbol": "XAUUSD",
        "pip_size": 0.1,
        "pip_value": 1.0,
        "min_sl_pips": 15.0,
        "max_sl_pips": 120.0,
        "sl_atr_multiplier": 2.0,
        "tp_atr_multiplier": 1.5,
        "risk_percent": 1.0,
        "min_lot_size": 0.01,
        "max_lot_size": 5.0,
        "lot_step": 0.01,
    })

    indicators = {"atr": 1.5}  # ATR = 1.5 -> atr_pips = 1.5 / 0.1 = 15.0 pips

    # Dynamic stops: sl_pips = max(15.0, min(120.0, 15.0 * 2.0)) = 30.0 pips
    # tp_pips = max(15.0, 15.0 * 1.5) = 22.5 pips
    stops_buy = robot.calculate_dynamic_stops(indicators, price=2650.0, signal=ScalpingSignal.BUY)
    assert stops_buy["sl_pips"] == 30.0
    assert stops_buy["tp_pips"] == 22.5
    assert stops_buy["sl_price"] == round(2650.0 - (30.0 * 0.1), 2)
    assert stops_buy["tp_price"] == round(2650.0 + (22.5 * 0.1), 2)

    # Position sizing:
    # Balance = $10,000, risk = 1.0% -> $100 risk
    # effective_sl_pips = 30.0, pip_value = 1.0 -> risk_per_lot = 30.0 * 1.0 = $30
    # lots = $100 / $30 = 3.3333 -> quantized to 3.33 lots
    lots = robot.calculate_position_size(10000.0, indicators, sl_pips=30.0)
    assert lots == 3.33

    # Invalid / non-finite balance returns 0.0
    assert robot.calculate_position_size(0.0, indicators) == 0.0
    assert robot.calculate_position_size(-100.0, indicators) == 0.0
    assert robot.calculate_position_size(float("nan"), indicators) == 0.0

    # Reset lifecycle clears state
    robot.volatility_halt_counter = 4
    robot.shield_status = {"status": "VOLATILITY_HALT", "halted": True}
    robot.open_positions.append({"ticket": 1})
    robot.reset()
    assert robot.volatility_halt_counter == 0
    assert robot.shield_status["halted"] is False
    assert len(robot.open_positions) == 0
