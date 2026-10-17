import time
import math
import pytest
from unittest.mock import MagicMock

from python_engine.signal_engine import SignalEngine
import python_engine.signal_engine as signal_engine
from python_engine.scalping_engine import (
    ScalpingRobotV5,
    ScalpingSignal,
    MarketRegime,
    EconomicNewsFilter,
)
import python_engine.scalping_engine as scalping_engine


def test_signal_engine_bollinger_bands():
    engine = SignalEngine({"bb_period": 10, "bb_std": 2.0})
    prices = [2650.0 + (i * 0.5) for i in range(20)]
    bb = engine.compute_bb(prices)
    assert bb["upper"] > bb["middle"]
    assert bb["middle"] > bb["lower"]
    assert bb["width"] > 0.0
    assert isinstance(bb["squeeze"], bool)


def test_signal_engine_rsi():
    engine = SignalEngine({"rsi_period": 14})

    # Strongly rising prices -> RSI high (>70)
    rising = [2600.0 + (i * 2.0) for i in range(30)]
    rsi_high = engine.compute_rsi(rising)
    assert rsi_high > 70.0

    # Strongly falling prices -> RSI low (<30)
    falling = [2700.0 - (i * 2.0) for i in range(30)]
    rsi_low = engine.compute_rsi(falling)
    assert rsi_low < 30.0

    # Flat prices -> RSI 50.0
    flat = [2650.0] * 30
    assert engine.compute_rsi(flat) == 50.0


def test_signal_engine_macd_and_ema():
    engine = SignalEngine({"macd_fast": 5, "macd_slow": 10, "macd_signal": 4})
    prices = [100.0 + (i % 3) * 2.0 for i in range(25)]

    macd = engine.compute_macd(prices)
    assert "macd_line" in macd
    assert "signal_line" in macd
    assert "histogram" in macd
    assert macd["cross"] in ("BUY", "SELL", "NONE")

    ema10 = engine.compute_ema(prices, 10)
    assert math.isfinite(ema10)


def test_signal_engine_get_signal_confluence():
    engine = SignalEngine({"bb_period": 10, "rsi_period": 10, "ema_fast": 5, "ema_slow": 10})
    # Oscillating series with sharp drop at the end (triggers oversold buy conditions)
    base = [2650.0] * 20
    dip = base + [2640.0, 2630.0, 2620.0, 2610.0]
    sig = engine.get_signal(dip)
    assert sig["signal"] in ("BUY", "SELL", "HOLD")
    assert 0.0 <= sig["confidence"] <= 1.0
    assert sig["tier"] in (1, 2, 3)
    assert isinstance(sig["reasons"], list)


def test_signal_engine_get_signal_safe_and_aliases():
    engine = SignalEngine()

    # Empty list -> safe fallback HOLD
    res_empty = engine.get_signal_safe([])
    assert res_empty["signal"] == "HOLD"
    assert res_empty["confidence"] == 0.0

    # Non-finite prices -> safe fallback HOLD
    res_nan = engine.get_signal_safe([float("nan"), 2650.0])
    assert res_nan["signal"] == "HOLD"

    # Risk aliases
    assert engine.is_entry_blocked() is False
    assert engine.is_blocked() is False
    assert signal_engine.is_entry_blocked() is False
    assert signal_engine.is_blocked() is False


def test_scalping_engine_signals_and_regimes():
    assert ScalpingSignal.BUY == "BUY"
    assert ScalpingSignal.SELL == "SELL"
    assert ScalpingSignal.HOLD == "HOLD"
    assert ScalpingSignal.CLOSE_BUY == "CLOSE_BUY"
    assert ScalpingSignal.CLOSE_SELL == "CLOSE_SELL"

    assert MarketRegime.LOW_VOLATILITY == "LOW_VOLATILITY"
    assert MarketRegime.NORMAL_VOLATILITY == "NORMAL_VOLATILITY"
    assert MarketRegime.HIGH_VOLATILITY == "HIGH_VOLATILITY"
    assert MarketRegime.EXTREME_SPIKE == "EXTREME_SPIKE"


def test_scalping_engine_news_filter_blackout():
    news_filter = EconomicNewsFilter(pre_minutes=15, post_minutes=30)
    now = time.time()
    event_time = now + 600  # Event in 10 minutes (within 15-minute pre-event window)

    news_filter.clear_events()
    news_filter.add_event(event_time, "US Non-Farm Payrolls (NFP)", "USD", "HIGH")

    # Inside blackout pre-event
    is_blk, ev = news_filter.is_blackout(now, currency="USD")
    assert is_blk is True
    assert ev["phase"] == "PRE_EVENT"
    assert "NFP" in ev["event"]

    # Inside blackout post-event (10 minutes after event)
    is_blk_post, ev_post = news_filter.is_blackout(event_time + 600, currency="USD")
    assert is_blk_post is True
    assert ev_post["phase"] == "POST_EVENT"

    # Outside blackout (45 minutes after event)
    is_blk_out, _ = news_filter.is_blackout(event_time + 2700, currency="USD")
    assert is_blk_out is False


def test_scalping_engine_position_sizing_van_tharp():
    robot = ScalpingRobotV5({
        "risk_percent": 1.0,
        "pip_value": 1.0,
        "min_lot_size": 0.01,
        "max_lot_size": 2.0,
        "lot_step": 0.01,
    })
    # Balance $10,000, 1% risk = $100 budget
    # SL = 20 pips -> risk per lot = 20 * $1.0 = $20 -> lots = 100 / 20 = 5.0 -> capped at max 2.0
    lots = robot.calculate_lot_size(sl_pips=20.0, account_balance=10000.0)
    assert lots == 2.0

    # SL = 50 pips -> risk per lot = 50 * $1.0 = $50 -> lots = 100 / 50 = 2.0
    lots2 = robot.calculate_lot_size(sl_pips=50.0, account_balance=10000.0)
    assert lots2 == 2.0

    # Negative / zero SL returns 0.0
    assert robot.calculate_lot_size(sl_pips=0.0, account_balance=10000.0) == 0.0
    assert robot.calculate_lot_size(sl_pips=-10.0, account_balance=10000.0) == 0.0


def test_scalping_engine_volatility_shield_and_reset():
    robot = ScalpingRobotV5()
    assert robot.is_entry_blocked() is False

    # Simulate volatility circuit breaker trip
    robot.volatility_halt_counter = 4
    robot.shield_status = {"status": "SPIKE", "reason": "Extreme ATR spike", "halted": True}

    assert robot.is_entry_blocked() is True
    assert robot.is_blocked() is True

    # Reset
    robot.reset()
    assert robot.volatility_halt_counter == 0
    assert robot.shield_status["halted"] is False
    assert robot.is_entry_blocked() is False


def test_scalping_engine_news_filter_blocks_entry():
    robot = ScalpingRobotV5({"news_filter_enabled": True})
    now = time.time()
    robot.news_filter.clear_events()
    robot.news_filter.add_event(now + 300, "FOMC Rate Decision", "USD", "HIGH")

    # Blocked during blackout
    assert robot.is_entry_blocked(current_time=now) is True

    # Disabled news filter allows trading
    robot.config["news_filter_enabled"] = False
    assert robot.is_entry_blocked(current_time=now) is False

    # Unified module risk aliases
    assert scalping_engine.is_entry_blocked() is False
    assert scalping_engine.is_blocked() is False
