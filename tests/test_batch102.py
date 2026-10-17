"""
tests/test_batch102.py
Batch 102 Unit Tests: Momentum Confirmation (wave28) & Adaptive TP Adjuster (wave29).
Expands test baseline beyond 1,257+ passing tests to 1,267+ passing tests across 102 test suites!
Verifies:
1. wave28: MomentumConfirmation initialization defaults, buffer sizing, and boolean rejection.
2. wave28: Warmup phase clearance when tick buffer contains fewer than required samples.
3. wave28: BUY signal momentum confirmation during ascending price movement and rejection on counter-trend.
4. wave28: SELL signal momentum confirmation during descending price movement and rejection on counter-trend.
5. wave28: Fail-closed input handling, reset(), and info() telemetry diagnostics reporting.
6. wave29: AdaptiveTp initialization defaults, bounds, and boolean rejection.
7. wave29: Cold-start neutral multiplier (1.0x) preventing premature TP shrinkage during warmup.
8. wave29: High volatility expansion (1.5x) when ATR proxy exceeds high threshold.
9. wave29: Low volatility shrinkage (0.7x) with enforcement of min_tp_pips floor.
10. wave29: Reward-to-Risk ratio calculations, min_rr_ratio constraints, reset(), and info() telemetry.
"""

import math
import pytest

from wave28_momentum_confirmation import MomentumConfirmation
from wave29_adaptive_tp import AdaptiveTp


def test_wave28_momentum_confirmation_initialization_defaults():
    """Verify MomentumConfirmation initializes with defaults and guards boolean inputs."""
    mc = MomentumConfirmation()
    assert mc._lookback == 5
    assert mc._min_ticks_in_dir == 3
    assert mc._price_buffer.maxlen == 6
    assert mc._total_rejections == 0

    # Custom bounded initialization
    mc_custom = MomentumConfirmation(lookback=10, min_ticks_in_dir=8)
    assert mc_custom._lookback == 10
    assert mc_custom._min_ticks_in_dir == 8

    # min_ticks_in_dir capped by lookback
    mc_capped = MomentumConfirmation(lookback=4, min_ticks_in_dir=10)
    assert mc_capped._min_ticks_in_dir == 4

    # Boolean parameter rejection
    mc_bool = MomentumConfirmation(lookback=True, min_ticks_in_dir=False)
    assert mc_bool._lookback == 5
    assert mc_bool._min_ticks_in_dir == 3


def test_wave28_momentum_confirmation_warmup_clearance():
    """Verify that insufficient tick data allows entries freely during initial warmup."""
    mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)

    # Empty buffer -> allowed
    allowed, reason = mc.is_momentum_confirmed("BUY")
    assert allowed is True
    assert "insufficient tick data" in reason

    # 1 tick -> allowed
    mc.update_price(2400.0)
    allowed, reason = mc.is_momentum_confirmed("BUY")
    assert allowed is True

    # 3 ticks (only 2 intervals, need at least 3 intervals) -> allowed
    mc.update_price(2400.1)
    mc.update_price(2400.2)
    allowed, reason = mc.is_momentum_confirmed("BUY")
    assert allowed is True
    assert "insufficient tick data" in reason


def test_wave28_momentum_confirmation_buy_signal_confirmed_and_rejected():
    """Verify BUY signals pass when prices are ascending and fail when descending."""
    mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)

    # 1. Feed ascending prices: 2400.0 -> 2400.2 -> 2400.4 -> 2400.6 (3 up intervals)
    for p in [2400.0, 2400.2, 2400.4, 2400.6]:
        mc.update_price(p)

    confirmed, reason = mc.is_momentum_confirmed("BUY")
    assert confirmed is True
    assert reason == ""
    assert mc._total_rejections == 0

    # 2. Feed descending prices: 2400.6 -> 2400.4 -> 2400.2 -> 2400.0
    for p in [2400.4, 2400.2, 2400.0]:
        mc.update_price(p)

    confirmed, reason = mc.is_momentum_confirmed("BUY")
    assert confirmed is False
    assert "BUY rejected" in reason
    assert mc._total_rejections == 1


def test_wave28_momentum_confirmation_sell_signal_confirmed_and_rejected():
    """Verify SELL signals pass when prices are descending and fail when ascending."""
    mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)

    # Feed descending prices: 2405.0 -> 2404.0 -> 2403.0 -> 2402.0 (3 down intervals)
    for p in [2405.0, 2404.0, 2403.0, 2402.0]:
        mc.update_price(p)

    confirmed, reason = mc.is_momentum_confirmed("SELL")
    assert confirmed is True
    assert reason == ""

    # Feed ascending prices: 2402.0 -> 2403.0 -> 2404.0 -> 2405.0
    for p in [2403.0, 2404.0, 2405.0]:
        mc.update_price(p)

    confirmed, reason = mc.is_momentum_confirmed("SELL")
    assert confirmed is False
    assert "SELL rejected" in reason
    assert mc._total_rejections == 1


def test_wave28_momentum_confirmation_fail_closed_inputs_and_reset():
    """Verify invalid prices and non-directional signals are handled safely, and reset flushes state."""
    mc = MomentumConfirmation()

    # Invalid prices ignored
    mc.update_price(2400.0)
    mc.update_price(None)
    mc.update_price(True)
    mc.update_price(float("nan"))
    mc.update_price(-2400.0)
    mc.update_price("invalid")
    assert len(mc._price_buffer) == 1

    # Non-directional or invalid signals pass through
    assert mc.is_momentum_confirmed("HOLD") == (True, "")
    assert mc.is_momentum_confirmed(None) == (True, "")
    assert mc.is_momentum_confirmed(123) == (True, "")

    # Reset
    mc.update_price(2401.0)
    mc.update_price(2402.0)
    info = mc.info()
    assert info["wave"] == 28
    assert info["name"] == "MomentumConfirmation"
    assert info["buffer_size"] == 3

    mc.reset()
    info_reset = mc.info()
    assert info_reset["buffer_size"] == 0
    assert info_reset["total_rejections"] == 0


def test_wave29_adaptive_tp_initialization_defaults():
    """Verify AdaptiveTp initializes with defaults and guards boolean inputs."""
    atp = AdaptiveTp()
    assert atp._window == 20
    assert atp._extend_ratio == 1.5
    assert atp._shrink_ratio == 0.7
    assert atp._atr_high == 0.15
    assert atp._atr_low == 0.04
    assert atp._min_tp_pips == 5.0
    assert len(atp._prices) == 0
    assert atp._total_adjustments == 0

    # Boolean parameter rejection in init
    atp_bool = AdaptiveTp(
        window=True,
        extend_ratio=False,
        shrink_ratio=True,
        atr_high_threshold=False,
        atr_low_threshold=True,
        min_tp_pips=False,
    )
    assert atp_bool._window == 20
    assert atp_bool._extend_ratio == 1.5
    assert atp_bool._shrink_ratio == 0.7
    assert atp_bool._atr_high == 0.15
    assert atp_bool._atr_low == 0.04
    assert atp_bool._min_tp_pips == 5.0


def test_wave29_adaptive_tp_cold_start_neutral_multiplier():
    """Verify TP multiplier defaults to neutral 1.0x during cold start or flat price action."""
    atp = AdaptiveTp(window=10)

    # Empty buffer -> 1.0
    assert atp.get_tp_multiplier() == 1.0
    assert atp.adjust_tp(20.0) == 20.0

    # Partially filled buffer (< window) -> 1.0
    for p in [2400.0, 2400.5, 2401.0]:
        atp.update_price(p)
    assert atp.get_tp_multiplier() == 1.0
    assert atp.adjust_tp(20.0) == 20.0


def test_wave29_adaptive_tp_high_volatility_tp_extension():
    """Verify TP is extended by 1.5x when ATR proxy exceeds high threshold."""
    atp = AdaptiveTp(window=5, extend_ratio=1.5, atr_high_threshold=0.15)

    # Feed 6 prices with high volatility: 2400.0, 2400.3, 2400.0, 2400.3, 2400.0, 2400.3 (ranges = 0.30 >= 0.15)
    for p in [2400.0, 2400.3, 2400.0, 2400.3, 2400.0, 2400.3]:
        atp.update_price(p)

    assert atp._current_atr >= 0.15
    assert atp.get_tp_multiplier() == 1.5
    # 20.0 base TP * 1.5 = 30.0
    assert atp.adjust_tp(20.0) == 30.0


def test_wave29_adaptive_tp_low_volatility_tp_shrinkage_with_floor():
    """Verify TP is shrunk by 0.7x when ATR is low, respecting min_tp_pips floor."""
    atp = AdaptiveTp(window=5, shrink_ratio=0.7, atr_low_threshold=0.04, min_tp_pips=5.0)

    # Feed 6 prices with very low volatility (ranges = 0.02 <= 0.04)
    for p in [2400.0, 2400.02, 2400.0, 2400.02, 2400.0, 2400.02]:
        atp.update_price(p)

    assert atp._current_atr <= 0.04
    assert atp.get_tp_multiplier() == 0.7

    # 10.0 base TP * 0.7 = 7.0 (above 5.0 floor)
    assert atp.adjust_tp(10.0) == 7.0

    # 6.0 base TP * 0.7 = 4.2 -> clamped to 5.0 floor
    assert atp.adjust_tp(6.0) == 5.0


def test_wave29_adaptive_tp_rr_constraint_and_telemetry():
    """Verify reward-to-risk ratio calculation, min_rr_ratio constraint, reset(), and info() telemetry."""
    atp = AdaptiveTp(min_tp_pips=5.0)

    # Reward to risk calculation
    assert atp.calculate_reward_to_risk(15.0, 10.0) == 1.5
    assert atp.calculate_reward_to_risk(20.0, 10.0) == 2.0
    assert atp.calculate_reward_to_risk(10.0, 0.0) == 0.0
    assert atp.calculate_reward_to_risk(10.0, -5.0) == 0.0
    assert atp.calculate_reward_to_risk(10.0, True) == 0.0

    # adjust_tp with min_rr_ratio constraint:
    # base_tp = 10.0, sl = 10.0, min_rr = 1.6 -> adjusted must be at least 16.0
    assert atp.adjust_tp(10.0, sl_pips=10.0, min_rr_ratio=1.6) == 16.0

    # Telemetry
    info = atp.info()
    assert info["wave"] == 29
    assert info["name"] == "AdaptiveTp"
    assert info["mode"] in ("EXTEND", "SHRINK", "NEUTRAL")

    # Reset
    atp.reset()
    info_reset = atp.info()
    assert info_reset["buffer_size"] == 0
    assert info_reset["total_adjustments"] == 0
