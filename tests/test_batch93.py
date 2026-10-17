"""
tests/test_batch93.py
Batch 93 Unit Tests: Lot Recovery Ladder (wave46) & ATR Position Sizer (wave47).
Expands test baseline beyond 1,167+ passing tests to 1,177+ passing tests.
Verifies:
1. wave46: LotRecoveryLadder initialization defaults, lot boundary enforcement, and parameter sanitization.
2. wave46: Consecutive losses progression, trigger threshold activation, and geometric multiplier scaling.
3. wave46: Winning trade streak termination, immediate reset to base lot, and cap ceiling containment.
4. wave46: Discrete ladder steps support with safe tier index bounds clamping.
5. wave46: LotRecoveryLadder reset() clearing and info() diagnostic telemetry reporting.
6. wave47: ATRPositionSizer initialization defaults, buffer capacities, and period sanitization.
7. wave47: Bar True Range calculation, rolling ATR estimation, and invalid price filtering (high < low).
8. wave47: Dynamic SL/TP scaling relative to ATR volatility baseline with hard min/max clamping.
9. wave47: Risk-budgeted lot sizing calculation quantized by lot_step with account balance protection.
10. wave47: ATRPositionSizer reset() buffer flushing and info() diagnostic telemetry introspection.
"""

import math
import pytest

from wave46_lot_recovery_ladder import LotRecoveryLadder
from wave47_atr_position_sizer import ATRPositionSizer


def test_wave46_initialization_defaults_and_sanitization():
    """Verify LotRecoveryLadder initializes with defaults and clamps invalid arguments."""
    # Defaults: base=0.02, max=0.10, min=0.01, mult=1.5, trigger=2, max_steps=5
    ladder = LotRecoveryLadder()
    assert ladder._base_lot == 0.02
    assert ladder._max_lot == 0.10
    assert ladder._min_lot == 0.01
    assert ladder._multiplier == 1.5
    assert ladder._trigger == 2
    assert ladder._max_steps == 5
    assert ladder.current_lot == 0.02

    # Custom valid configuration
    custom = LotRecoveryLadder(base_lot=0.03, max_lot=0.15, multiplier=2.0, consecutive_trigger=3)
    assert custom._base_lot == 0.03
    assert custom._max_lot == 0.15
    assert custom._multiplier == 2.0
    assert custom._trigger == 3

    # Clamping negative inputs to min_lot (0.01) and invalid/nan to defaults (0.02)
    bad_neg = LotRecoveryLadder(base_lot=-0.05)
    assert bad_neg._base_lot == 0.01

    bad_nan = LotRecoveryLadder(base_lot=float("nan"), max_lot="bad", multiplier=float("nan"))
    assert bad_nan._base_lot == 0.02
    assert bad_nan._max_lot == 0.10
    assert bad_nan._multiplier == 1.5


def test_wave46_consecutive_losses_scale_lot():
    """Verify consecutive losses scale lot size once hitting trigger and clamp at max_lot."""
    ladder = LotRecoveryLadder(base_lot=0.02, max_lot=0.08, multiplier=2.0, consecutive_trigger=2)

    # Loss 1: Below trigger (1 < 2) -> lot remains base_lot 0.02
    ladder.record_trade(won=False)
    assert ladder._consecutive_losses == 1
    assert ladder.get_lot() == 0.02

    # Loss 2: Hits trigger (2 >= 2) -> scales 0.02 * 2.0 = 0.04
    ladder.record_trade(won=False)
    assert ladder._consecutive_losses == 2
    assert ladder.get_lot() == 0.04

    # Loss 3: Scales 0.04 * 2.0 = 0.08 (hits max_lot cap)
    ladder.record_trade(won=False)
    assert ladder._consecutive_losses == 3
    assert ladder.get_lot() == 0.08

    # Loss 4: Clamped at max_lot 0.08
    ladder.record_trade(won=False)
    assert ladder._consecutive_losses == 4
    assert ladder.get_lot() == 0.08


def test_wave46_win_resets_lot_to_base():
    """Verify any winning trade immediately restores lot size to base_lot."""
    ladder = LotRecoveryLadder(base_lot=0.02, max_lot=0.10, multiplier=2.0, consecutive_trigger=2)

    ladder.record_trade(won=False)
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.04

    # Win resets
    ladder.record_trade(won=True)
    assert ladder._consecutive_losses == 0
    assert ladder.get_lot() == 0.02


def test_wave46_discrete_ladder_steps():
    """Verify discrete ladder steps tier progression and out-of-bounds protection."""
    steps = [0.02, 0.05, 0.09, 0.12]
    ladder = LotRecoveryLadder(base_lot=0.02, max_lot=0.15, consecutive_trigger=2, ladder_steps=steps)

    # Loss 1 (below trigger 2): 0.02
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.02

    # Loss 2 (step 0): steps[0] = 0.02
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.02

    # Loss 3 (step 1): steps[1] = 0.05
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.05

    # Loss 4 (step 2): steps[2] = 0.09
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.09

    # Loss 5 (step 3): steps[3] = 0.12
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.12

    # Loss 6: Clamped at last step (0.12)
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.12


def test_wave46_reset_and_info_introspection():
    """Verify reset() flushes state and info() outputs diagnostic telemetry."""
    ladder = LotRecoveryLadder(base_lot=0.02, max_lot=0.10, multiplier=1.5, consecutive_trigger=2)
    ladder.record_trade(won=False)
    ladder.record_trade(won=False)

    info = ladder.info()
    assert info["wave"] == 46
    assert info["name"] == "LotRecoveryLadder"
    assert info["consecutive_losses"] == 2
    assert info["current_lot"] == 0.03
    assert info["recovery_active"] is True
    assert info["ladder_step"] == 1

    ladder.reset()
    info_reset = ladder.info()
    assert info_reset["consecutive_losses"] == 0
    assert info_reset["current_lot"] == 0.02
    assert info_reset["recovery_active"] is False
    assert info_reset["ladder_step"] == 0


def test_wave47_initialization_defaults_and_clamping():
    """Verify ATRPositionSizer initializes with defaults and clamps invalid periods."""
    sizer = ATRPositionSizer()
    assert sizer._period == 14
    assert sizer.get_atr() == 0.0

    # Custom valid period
    custom = ATRPositionSizer(period=10)
    assert custom._period == 10

    # Period clamped to minimum 2 or fallback
    assert ATRPositionSizer(period=1)._period == 14
    assert ATRPositionSizer(period=-5)._period == 14
    assert ATRPositionSizer(period="invalid")._period == 14


def test_wave47_update_and_atr_calculation():
    """Verify ATR computation on incoming bars and rejection of invalid inputs."""
    sizer = ATRPositionSizer(period=5)

    # Rejection of invalid inputs (None, boolean, negative, high < low)
    sizer.update(None, 10.0)
    sizer.update(10.0, None)
    sizer.update(True, 10.0)
    sizer.update(10.0, 15.0)  # High < Low -> invalid
    sizer.update(-5.0, -10.0)
    assert len(sizer._highs) == 0

    # Feed 6 valid bars with 2.0 true range per bar
    # Bar 1: h=102, l=100, c=101
    # Bar 2: h=103, l=101, c=102
    for i in range(7):
        h = 100.0 + i + 2.0
        l = 100.0 + i
        c = 100.0 + i + 1.0
        sizer.update(high=h, low=l, close=c)

    assert len(sizer._highs) == 6  # maxlen = period + 1 = 6
    assert sizer.get_atr() > 0.0
    assert len(sizer._atr_history) == 6


def test_wave47_get_sl_tp_scaling():
    """Verify dynamic SL and TP scaling against volatility baseline with boundary clamping."""
    sizer = ATRPositionSizer(period=5)

    # Before baseline is established, returns base SL and TP
    sl, tp = sizer.get_sl_tp(base_sl=30.0, base_tp=45.0)
    assert sl == 30.0
    assert tp == 45.0

    # Establish baseline ATR = 2.0
    for i in range(10):
        sizer.update(high=102.0, low=100.0, close=101.0)

    # Simulated volatility expansion: ATR = 3.0, baseline = 2.0 -> ratio = 1.5
    sizer._atr = 3.0
    sizer._atr_baseline = 2.0
    sl, tp = sizer.get_sl_tp(base_sl=30.0, base_tp=45.0)
    assert sl == 45.0   # 30.0 * 1.5
    assert tp == 67.5   # 45.0 * 1.5

    # Extreme volatility ratio clamped to [0.5, 2.0] and bounds [_SL_MIN=15, _SL_MAX=60]
    sizer._atr = 10.0
    sizer._atr_baseline = 1.0  # ratio 10.0 clamped to 2.0
    sl_max, tp_max = sizer.get_sl_tp(base_sl=30.0, base_tp=45.0)
    assert sl_max == 60.0  # 30 * 2.0 = 60.0 (_SL_MAX)
    assert tp_max == 90.0  # 45 * 2.0 = 90.0 (_TP_MAX)


def test_wave47_get_lot_size_risk_budget():
    """Verify position sizing calculates risk budget and quantizes to lot_step increments."""
    sizer = ATRPositionSizer()

    # Balance $10,000, risk 1% ($100 risk)
    # SL = 20 pips, pip_value = $10 per lot ($200 risk per lot)
    # raw_lot = 100 / 200 = 0.50 lots
    lot = sizer.get_lot_size(
        account_balance=10000.0,
        risk_pct=0.01,
        sl_pips=20.0,
        pip_value=10.0,
        min_lot=0.01,
        max_lot=10.0,
        lot_step=0.01,
    )
    assert lot == 0.50

    # Test invalid balance fallback
    assert sizer.get_lot_size(None) == 0.01
    assert sizer.get_lot_size(0.0) == 0.01
    assert sizer.get_lot_size(-500.0) == 0.01
    assert sizer.get_lot_size(float("nan")) == 0.01


def test_wave47_reset_and_info_introspection():
    """Verify reset() flushes buffers and info() outputs diagnostic telemetry."""
    sizer = ATRPositionSizer(period=5)
    for i in range(6):
        sizer.update(102.0 + i, 100.0 + i, 101.0 + i)

    info = sizer.info()
    assert info["wave"] == 47
    assert info["name"] == "ATRPositionSizer"
    assert info["atr"] > 0
    assert info["buffer_len"] == 6

    sizer.reset()
    info_reset = sizer.info()
    assert info_reset["atr"] == 0.0
    assert info_reset["atr_baseline"] == 0.0
    assert info_reset["buffer_len"] == 0
    assert info_reset["dynamic_sl_pips"] == 30.0
    assert info_reset["dynamic_tp_pips"] == 45.0
