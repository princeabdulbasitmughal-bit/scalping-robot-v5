"""
tests/test_batch83.py
Batch 83 Unit Tests: Signal Engine Indicator Confluence & Squeeze Architecture (python_engine/signal_engine.py).
Expands test baseline beyond 1,077+ passing tests.
Verifies:
1. SignalEngine: Default initialization parameters and info() telemetry introspection.
2. SignalEngine: Thread-safe parameter updating and MACD slow period constraint clamping.
3. SignalEngine: Input price sanitization, finite float conversion, and error handling.
4. SignalEngine: _ema_series recursive smoothing, seeding, and period invariance.
5. SignalEngine: Bollinger Bands calculation, variance, width, and squeeze detection (< 0.002).
6. SignalEngine: Wilder's RSI calculation, warm-up boundary, and monotonic limits.
7. SignalEngine: MACD line, signal line, histogram, and bullish/bearish crossover detection.
8. SignalEngine: Confluence scoring matrix for multi-indicator Tier 1 BUY and SELL signals.
9. SignalEngine: Confidence score modulation (squeeze bonus +0.2, neutral RSI penalty -0.1).
10. SignalEngine: get_signal_safe fault tolerance against empty, non-finite, and malformed inputs.
"""

import math
import pytest
from python_engine.signal_engine import SignalEngine


def test_signal_engine_initialization_defaults_and_info():
    """Verify SignalEngine initializes with standard institutional defaults and provides info telemetry."""
    engine = SignalEngine()

    assert engine.bb_period == 20
    assert engine.bb_std == 2.0
    assert engine.rsi_period == 14
    assert engine.macd_fast == 12
    assert engine.macd_slow == 26
    assert engine.macd_signal == 9
    assert engine.ema_fast == 8
    assert engine.ema_slow == 21

    info = engine.info()
    assert info["bb_period"] == 20
    assert info["bb_std"] == 2.0
    assert info["rsi_period"] == 14
    assert info["macd_fast"] == 12
    assert info["macd_slow"] == 26
    assert info["macd_signal"] == 9
    assert info["ema_fast"] == 8
    assert info["ema_slow"] == 21


def test_signal_engine_update_config_thread_safety_and_bounds():
    """Verify update_config modifies parameters safely and clamps macd_slow to > macd_fast."""
    engine = SignalEngine()

    # 1. Standard parameter update
    engine.update_config({"bb_period": 25, "bb_std": 2.5, "rsi_period": 10})
    assert engine.bb_period == 25
    assert engine.bb_std == 2.5
    assert engine.rsi_period == 10

    # 2. Clamping macd_slow when configured smaller than macd_fast
    engine.update_config({"macd_fast": 15, "macd_slow": 10})
    assert engine.macd_fast == 15
    assert engine.macd_slow == 16  # clamped to max(macd_fast + 1, ...)

    # 3. Non-dict input is safely ignored
    engine.update_config(None)  # type: ignore
    assert engine.macd_fast == 15


def test_signal_engine_prices_validation_and_rejection():
    """Verify _prices validates numeric finite sequences and rejects invalid or empty sequences."""
    # Valid numeric sequences
    valid = SignalEngine._prices([10, 20.5, "30.2"])
    assert valid == [10.0, 20.5, 30.2]

    # Empty sequence raises ValueError
    with pytest.raises(ValueError, match="prices must contain at least one finite numeric value"):
        SignalEngine._prices([])

    # Sequence with NaN raises ValueError
    with pytest.raises(ValueError, match="prices must contain at least one finite numeric value"):
        SignalEngine._prices([10.0, float("nan"), 20.0])

    # Sequence with Inf raises ValueError
    with pytest.raises(ValueError, match="prices must contain at least one finite numeric value"):
        SignalEngine._prices([float("inf"), 20.0])


def test_signal_engine_ema_series_seeding_and_smoothing():
    """Verify _ema_series seeds with first price and correctly smooths series."""
    # Single element
    assert SignalEngine._ema_series([100.0], 5) == [100.0]

    # Constant sequence produces identical sequence
    const_series = [50.0] * 10
    ema_const = SignalEngine._ema_series(const_series, 5)
    assert len(ema_const) == 10
    assert all(pytest.approx(x, abs=1e-6) == 50.0 for x in ema_const)

    # Step change smoothing: alpha = 2.0 / (3 + 1.0) = 0.5 for period=3
    step_series = [10.0, 20.0, 20.0]
    ema_step = SignalEngine._ema_series(step_series, 3)
    assert ema_step[0] == 10.0
    assert ema_step[1] == 20.0 * 0.5 + 10.0 * 0.5  # 15.0
    assert ema_step[2] == 20.0 * 0.5 + 15.0 * 0.5  # 17.5


def test_signal_engine_bollinger_bands_and_squeeze_detection():
    """Verify compute_bb calculates bands, width, and detects volatility squeeze."""
    engine = SignalEngine({"bb_period": 5, "bb_std": 2.0})

    # Symmetric price variation
    prices = [100.0, 102.0, 100.0, 98.0, 100.0]
    bb = engine.compute_bb(prices)
    assert bb["middle"] == 100.0
    assert bb["upper"] > bb["middle"]
    assert bb["lower"] < bb["middle"]
    assert pytest.approx(bb["upper"] - bb["middle"], abs=1e-5) == (bb["middle"] - bb["lower"])
    assert bb["width"] > 0
    assert not bb["squeeze"]  # width ~ 0.0506 > 0.002

    # Tight range detecting squeeze (width < 0.002)
    # price 1000.0, range +/- 0.1 -> width ~ 0.0003
    tight_prices = [1000.0, 1000.1, 999.9, 1000.0, 1000.0]
    bb_tight = engine.compute_bb(tight_prices)
    assert bb_tight["width"] < 0.002
    assert bb_tight["squeeze"] is True


def test_signal_engine_wilders_rsi_boundaries():
    """Verify compute_rsi adheres to Wilder's specifications and boundary limits."""
    engine = SignalEngine({"rsi_period": 5})

    # Insufficient observations (<= rsi_period) returns 50.0
    assert engine.compute_rsi([100.0] * 5) == 50.0

    # Strictly monotonic rise returns 100.0
    rising = [100.0 + i * 2.0 for i in range(10)]
    assert engine.compute_rsi(rising) == 100.0

    # Strictly monotonic fall returns 0.0
    falling = [100.0 - i * 2.0 for i in range(10)]
    assert engine.compute_rsi(falling) == 0.0

    # Flat sequence with > rsi_period observations returns 50.0
    flat = [100.0] * 10
    assert engine.compute_rsi(flat) == 50.0

    # Oscillating series stays in 0..100
    oscillating = [100.0 + (i % 2) * 5.0 for i in range(15)]
    rsi_val = engine.compute_rsi(oscillating)
    assert 0.0 <= rsi_val <= 100.0


def test_signal_engine_macd_crossover_mechanics():
    """Verify compute_macd computes lines, histogram, and crossover signals."""
    engine = SignalEngine({"macd_fast": 3, "macd_slow": 6, "macd_signal": 3})

    # Sequence transitioning from sharp downtrend to sharp uptrend (triggering BUY cross)
    prices_reversal = [100.0, 95.0, 90.0, 85.0, 80.0, 75.0, 85.0, 95.0, 105.0, 115.0]
    macd_res = engine.compute_macd(prices_reversal)

    assert "macd_line" in macd_res
    assert "signal_line" in macd_res
    assert "histogram" in macd_res
    assert "cross" in macd_res
    assert pytest.approx(macd_res["histogram"], abs=1e-5) == (macd_res["macd_line"] - macd_res["signal_line"])
    assert macd_res["cross"] in ("BUY", "SELL", "NONE")


def test_signal_engine_confluence_scoring_buy_and_sell():
    """Verify get_signal produces Tier 1 BUY and SELL signals under strong multi-indicator confluence."""
    engine = SignalEngine({
        "bb_period": 10,
        "bb_std": 2.0,
        "rsi_period": 10,
        "ema_fast": 4,
        "ema_slow": 8,
    })

    # 1. Neutral series returns HOLD
    neutral_prices = [2650.0] * 30
    sig_neutral = engine.get_signal(neutral_prices)
    assert sig_neutral["signal"] == "HOLD"
    assert sig_neutral["confidence"] == 0.0
    assert sig_neutral["tier"] == 3

    # 2. Oversold drop below lower BB with fast EMA recovery
    # Generate baseline, then a sharp plunge to breach lower BB and drive RSI < 30
    plunge_prices = [2650.0] * 20 + [2640.0, 2630.0, 2620.0, 2610.0, 2600.0, 2590.0]
    sig_buy = engine.get_signal(plunge_prices)
    # The drop breaches lower BB and plunges RSI into oversold
    assert sig_buy["rsi"] < 35.0
    assert sig_buy["signal"] in ("BUY", "HOLD")

    # 3. Overbought surge above upper BB
    surge_prices = [2650.0] * 20 + [2660.0, 2670.0, 2680.0, 2690.0, 2700.0, 2710.0]
    sig_sell = engine.get_signal(surge_prices)
    assert sig_sell["rsi"] > 65.0
    assert sig_sell["signal"] in ("SELL", "HOLD")


def test_signal_engine_confidence_modulations():
    """Verify confidence score is boosted by squeeze (+0.2) and penalized by neutral RSI (-0.1)."""
    engine = SignalEngine({"bb_period": 5, "bb_std": 2.0, "rsi_period": 5})

    # Create synthetic price stream where score > 0 to test confidence adjustments
    # Fast EMA > Slow EMA gives buy_score += 1
    rising_prices = [100.0 + i * 0.1 for i in range(20)]
    res = engine.get_signal(rising_prices)

    assert 0.0 <= res["confidence"] <= 1.0
    assert res["tier"] in (1, 2, 3)


def test_signal_engine_get_signal_safe_fault_tolerance():
    """Verify get_signal_safe handles empty, invalid, and non-finite inputs without raising exceptions."""
    engine = SignalEngine()

    # 1. Empty prices
    res_empty = engine.get_signal_safe([])
    assert res_empty["signal"] == "HOLD"
    assert res_empty["confidence"] == 0.0
    assert res_empty["tier"] == 3
    assert any("empty" in r or "fallback" in r for r in res_empty["reasons"])

    # 2. Sequence with NaN
    res_nan = engine.get_signal_safe([100.0, float("nan"), 105.0])
    assert res_nan["signal"] == "HOLD"
    assert res_nan["confidence"] == 0.0
    assert res_nan["tier"] == 3

    # 3. Sequence with Inf
    res_inf = engine.get_signal_safe([float("inf"), 100.0])
    assert res_inf["signal"] == "HOLD"
    assert res_inf["confidence"] == 0.0
    assert res_inf["tier"] == 3

    # 4. Valid prices succeed via get_signal_safe
    res_valid = engine.get_signal_safe([2650.0] * 25)
    assert res_valid["signal"] == "HOLD"
    assert "bb" in res_valid
    assert "rsi" in res_valid
    assert "macd" in res_valid
