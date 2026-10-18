"""
Test Suite for Batch 140:
- wave46_lot_recovery_ladder.py (LotRecoveryLadder: bounded mild martingale lot sizing)
- wave47_atr_position_sizer.py (ATRPositionSizer: dynamic ATR-scaled SL/TP & balance risk sizing)
Zero regressions, continuing toward 1,647+ passed tests.
"""

import math
import pytest

from wave46_lot_recovery_ladder import (
    LotRecoveryLadder,
    lot_recovery_ladder,
    get_lot as w46_get_lot,
    record_trade as w46_record_trade,
    reset as w46_reset,
)
from wave47_atr_position_sizer import (
    ATRPositionSizer,
    atr_position_sizer,
    get_sl_tp as w47_get_sl_tp,
    get_lot_size as w47_get_lot_size,
    update as w47_update,
    reset as w47_reset,
)


# ---------------------------------------------------------------------
# Wave 46: Lot Recovery Ladder Tests
# ---------------------------------------------------------------------

def test_wave46_initial_state():
    lrl = LotRecoveryLadder()
    assert lrl.current_lot == 0.02
    assert lrl.get_lot() == 0.02
    info = lrl.info()
    assert info["base_lot"] == 0.02
    assert info["min_lot"] == 0.01
    assert info["max_lot"] == 0.10
    assert info["multiplier"] == 1.5
    assert info["trigger"] == 2
    assert not info["recovery_active"]
    assert info["consecutive_losses"] == 0


def test_wave46_single_loss_no_scale():
    lrl = LotRecoveryLadder(base_lot=0.02, consecutive_trigger=2)
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.02
    info = lrl.info()
    assert info["consecutive_losses"] == 1
    assert not info["recovery_active"]


def test_wave46_consecutive_losses_scaling():
    lrl = LotRecoveryLadder(base_lot=0.02, consecutive_trigger=2, multiplier=1.5, max_lot=0.06)
    # Loss 1: no scale
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.02

    # Loss 2 (trigger reached): 0.02 * 1.5 = 0.03
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.03
    assert lrl.info()["recovery_active"]

    # Loss 3: 0.03 * 1.5 = 0.045 -> banker's rounded 0.04
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.04

    # Loss 4: 0.04 * 1.5 = 0.06 (clamped at max_lot 0.06)
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.06


def test_wave46_win_resets_ladder():
    lrl = LotRecoveryLadder(base_lot=0.02, consecutive_trigger=2)
    lrl.record_trade(won=False)
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.03

    # Win resets back to base_lot
    lrl.record_trade(won=True)
    assert lrl.get_lot() == 0.02
    assert lrl.info()["consecutive_losses"] == 0
    assert not lrl.info()["recovery_active"]


def test_wave46_discrete_steps_and_module_aliases():
    ladder = [0.02, 0.04, 0.08]
    lrl = LotRecoveryLadder(base_lot=0.02, consecutive_trigger=1, max_lot=0.10, ladder_steps=ladder)
    # Loss 1 -> step 0 -> 0.02
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.02
    # Loss 2 -> step 1 -> 0.04
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.04
    # Loss 3 -> step 2 -> 0.08
    lrl.record_trade(won=False)
    assert lrl.get_lot() == 0.08

    lrl.reset()
    assert lrl.get_lot() == 0.02

    # Module-level aliases
    w46_reset()
    assert w46_get_lot() == 0.02
    w46_record_trade(won=False)
    w46_record_trade(won=True)
    assert w46_get_lot() == 0.02
    w46_reset()


# ---------------------------------------------------------------------
# Wave 47: ATR Position Sizer Tests
# ---------------------------------------------------------------------

def test_wave47_initial_state():
    aps = ATRPositionSizer()
    sl, tp = aps.get_sl_tp()
    assert sl == 30.0
    assert tp == 45.0
    assert aps.get_atr() == 0.0
    info = aps.info()
    assert info["dynamic_sl_pips"] == 30.0
    assert info["dynamic_tp_pips"] == 45.0
    assert info["buffer_len"] == 0


def test_wave47_invalid_inputs():
    aps = ATRPositionSizer()
    # High < Low
    aps.update(high=2000.0, low=2005.0)
    assert len(aps._closes) == 0

    # Non-finite or bool
    for bad in [None, True, False, -100.0, float("nan"), float("inf"), "abc"]:
        aps.update(high=bad, low=2000.0)
        aps.update(high=2005.0, low=bad)

    assert len(aps._closes) == 0
    sl, tp = aps.get_sl_tp()
    assert sl == 30.0
    assert tp == 45.0


def test_wave47_atr_scaling():
    aps = ATRPositionSizer(period=14)
    price = 2000.0
    # Feed 20 bars of data with range 2.0 (H = price + 1.0, L = price - 1.0)
    for i in range(20):
        aps.update(high=price + 1.0, low=price - 1.0, close=price)

    assert aps.get_atr() > 0.0
    sl, tp = aps.get_sl_tp()
    assert 15.0 <= sl <= 60.0
    assert 22.0 <= tp <= 90.0
    info = aps.info()
    assert info["buffer_len"] > 0
    assert info["atr"] > 0.0


def test_wave47_lot_size_calculation():
    aps = ATRPositionSizer()
    # Account $10,000, 1% risk ($100), SL 30 pips, pip_value $10.0/lot
    # Risk per lot = 30 * 10 = $300
    # Expected lot = $100 / $300 = 0.3333 -> 0.33 lots
    lot = aps.get_lot_size(account_balance=10000.0, risk_pct=0.01, sl_pips=30.0, pip_value=10.0)
    assert lot == 0.33

    # Invalid balance defaults to min_lot 0.01
    for bad_bal in [None, True, False, -500.0, 0.0, float("nan"), float("inf")]:
        assert aps.get_lot_size(account_balance=bad_bal) == 0.01


def test_wave47_reset_and_module_aliases():
    aps = ATRPositionSizer()
    for _ in range(10):
        aps.update(high=2005.0, low=2000.0, close=2002.5)
    assert len(aps._closes) > 0

    aps.reset()
    assert len(aps._closes) == 0
    assert aps.get_atr() == 0.0

    # Module-level aliases
    w47_reset()
    sl, tp = w47_get_sl_tp()
    assert sl == 30.0 and tp == 45.0
    lot = w47_get_lot_size(10000.0, risk_pct=0.01, sl_pips=30.0)
    assert lot == 0.33
    w47_update(high=2005.0, low=2000.0)
    w47_reset()
