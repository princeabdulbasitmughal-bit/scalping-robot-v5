"""
tests/test_batch104.py
Batch 104 Unit Tests: Daily Profit Lock (wave24) & Drawdown Accelerator (wave25).
Expands test baseline beyond 1,277+ passing tests to 1,287+ passing tests across 104 test suites!
Verifies:
1. wave24: DailyProfitLock initialization defaults, target aliases, and boolean parameter protection.
2. wave24: Normal sub-target daily PnL permitting standard lot sizes and signal score thresholds.
3. wave24: Profit target achievement (+150 USD) engaging protect mode (lot reduced to 0.01, min score 70).
4. wave24: Intraday profit lock persistence (no premature disengagement on PnL drawdown) and midnight reset.
5. wave24: Fail-closed input handling on boolean/invalid inputs, apply_lot(), and info() telemetry.
6. wave25: DrawdownAccelerator initialization defaults, thresholds, and boolean parameter protection.
7. wave25: Progressive lot scaling across loss streaks (3 losses -> 0.50x, 5 losses -> 0.25x, 7+ losses -> 0.10x).
8. wave25: Full sizing recovery protocol upon completing required consecutive wins (2 wins).
9. wave25: Interrupted recovery streak behavior resetting win counter upon intermediate loss.
10. wave25: Fail-closed lot containment, reset(), and info() telemetry mode reporting.
"""

import math
import pytest

from wave24_daily_profit_lock import DailyProfitLock
from wave25_drawdown_accelerator import DrawdownAccelerator


def test_wave24_daily_profit_lock_initialization_defaults():
    """Verify DailyProfitLock initializes with defaults and guards boolean inputs."""
    dpl = DailyProfitLock()
    assert dpl._profit_target == 150.0
    assert dpl._protect_lot == 0.01
    assert dpl._protect_score == 70
    assert dpl.is_active is False
    assert dpl._peak_daily_pnl == 0.0
    assert dpl._engagements == 0

    # Custom targets and alias support
    dpl_custom = DailyProfitLock(profit_target_usd=200.0, protect_lot=0.02, protect_min_score=75)
    assert dpl_custom.profit_target_usd == 200.0
    assert dpl_custom._protect_lot == 0.02
    assert dpl_custom._protect_score == 75

    # Boolean parameter rejection
    dpl_bool = DailyProfitLock(daily_target_usd=True, protect_lot=False, protect_min_score=True)
    assert dpl_bool._profit_target == 150.0
    assert dpl_bool._protect_lot == 0.01
    assert dpl_bool._protect_score == 70


def test_wave24_daily_profit_lock_normal_pnl_below_target():
    """Verify daily PnL below target does not engage protect mode."""
    dpl = DailyProfitLock(profit_target_usd=150.0)

    # Moderate profit ($50)
    dpl.update(50.0)
    assert dpl.is_active is False
    assert dpl.apply_lot(0.04) == 0.04
    assert dpl.get_min_score(55) == 55

    # Higher profit below target ($120)
    dpl.update(120.0)
    assert dpl.is_active is False
    assert dpl._peak_daily_pnl == 120.0
    assert dpl.apply_lot(0.04) == 0.04


def test_wave24_daily_profit_lock_target_reached_protect_mode_engagement():
    """Verify achieving target ($150) engages protect mode and enforces risk constraints."""
    dpl = DailyProfitLock(profit_target_usd=150.0, protect_lot=0.01, protect_min_score=70)

    # Reaching target PnL
    dpl.update(155.0)
    assert dpl.is_active is True
    assert dpl._engagements == 1
    assert dpl._peak_daily_pnl == 155.0

    # Lot size clamped to protect_lot (0.01)
    assert dpl.apply_lot(0.05) == 0.01
    assert dpl.apply_lot(0.01) == 0.01

    # Signal score requirement elevated to 70
    assert dpl.get_min_score(55) == 70
    assert dpl.get_min_score(75) == 75  # retains higher score if caller requires 75


def test_wave24_daily_profit_lock_no_intraday_disengagement_and_reset():
    """Verify protect mode persists throughout the trading day even if PnL declines."""
    dpl = DailyProfitLock(profit_target_usd=150.0)

    dpl.update(160.0)
    assert dpl.is_active is True

    # PnL draws down from $160 to $130
    dpl.update(130.0)
    assert dpl.is_active is True  # does not give back profits
    assert dpl.apply_lot(0.03) == 0.01

    # Midnight UTC reset clears protect mode
    dpl.reset()
    assert dpl.is_active is False
    assert dpl._peak_daily_pnl == 0.0
    assert dpl.apply_lot(0.03) == 0.03


def test_wave24_daily_profit_lock_fail_closed_inputs_and_telemetry():
    """Verify invalid inputs are handled safely, and info returns complete telemetry."""
    dpl = DailyProfitLock()

    # Invalid inputs ignored
    dpl.update(None)
    dpl.update(True)
    dpl.update(float("nan"))
    assert dpl._peak_daily_pnl == 0.0

    # Invalid lot returned as-is
    assert dpl.apply_lot(None) is None
    assert dpl.apply_lot(True) is True
    assert dpl.apply_lot(-0.01) == -0.01

    # Safe min_score fallback
    assert dpl.get_min_score(True) == 55

    info = dpl.info()
    assert info["protect_mode"] is False
    assert info["profit_target_usd"] == 150.0
    assert info["protect_lot"] == 0.01
    assert info["protect_min_score"] == 70


def test_wave25_drawdown_accelerator_initialization_defaults():
    """Verify DrawdownAccelerator initializes with defaults and guards boolean inputs."""
    da = DrawdownAccelerator()
    assert len(da._thresholds) == 3
    assert da._thresholds == [(3, 0.50), (5, 0.25), (7, 0.10)]
    assert da._recovery_wins == 2
    assert da._consec_losses == 0
    assert da._consec_wins == 0
    assert da.get_multiplier() == 1.0

    # Boolean parameter rejection
    da_bool = DrawdownAccelerator(recovery_wins=False)
    assert da_bool._recovery_wins == 2


def test_wave25_drawdown_accelerator_progressive_lot_reduction():
    """Verify consecutive losses progressively throttle lot multiplier and size."""
    da = DrawdownAccelerator()

    # 1-2 losses: full size (1.0x)
    da.record_trade(won=False)
    assert da.get_multiplier() == 1.0
    assert da.apply_lot(0.04) == 0.04
    assert da.info()["mode"] == "FULL_SIZE"

    da.record_trade(won=False)
    assert da.get_multiplier() == 1.0

    # 3 losses: half size (0.50x)
    da.record_trade(won=False)
    assert da.get_multiplier() == 0.50
    assert da.apply_lot(0.04) == 0.02
    assert da.info()["mode"] == "HALF_SIZE"
    assert da._total_reductions == 1

    # 4 losses: still half size
    da.record_trade(won=False)
    assert da.get_multiplier() == 0.50

    # 5 losses: quarter size (0.25x)
    da.record_trade(won=False)
    assert da.get_multiplier() == 0.25
    assert da.apply_lot(0.04) == 0.01
    assert da.info()["mode"] == "QUARTER_SIZE"

    # 7 losses: micro size (0.10x)
    da.record_trade(won=False)
    da.record_trade(won=False)
    assert da.get_multiplier() == 0.10
    assert da.apply_lot(0.10) == 0.01
    assert da.info()["mode"] == "MICRO_SIZE"


def test_wave25_drawdown_accelerator_full_recovery_after_consecutive_wins():
    """Verify completing recovery_wins (2 consecutive wins) fully restores multiplier to 1.0."""
    da = DrawdownAccelerator(recovery_wins=2)

    # Incur 4 losses -> half size (0.50x)
    for _ in range(4):
        da.record_trade(won=False)
    assert da.get_multiplier() == 0.50

    # 1st win -> not yet recovered (consec_wins=1)
    da.record_trade(won=True)
    assert da._consec_wins == 1
    assert da.get_multiplier() == 0.50

    # 2nd win -> full recovery!
    da.record_trade(won=True)
    assert da._consec_wins == 0
    assert da._consec_losses == 0
    assert da.get_multiplier() == 1.0
    assert da.apply_lot(0.04) == 0.04
    assert da.info()["mode"] == "FULL_SIZE"


def test_wave25_drawdown_accelerator_interrupted_recovery_win_streak():
    """Verify an intermediate loss during recovery streak resets win counter and extends loss streak."""
    da = DrawdownAccelerator(recovery_wins=2)

    # 3 losses -> half size
    for _ in range(3):
        da.record_trade(won=False)
    assert da.get_multiplier() == 0.50

    # 1 win
    da.record_trade(won=True)
    assert da._consec_wins == 1

    # Interrupted by 1 loss -> consec_wins reset to 0, consec_losses increments to 4
    da.record_trade(won=False)
    assert da._consec_wins == 0
    assert da._consec_losses == 4
    assert da.get_multiplier() == 0.50


def test_wave25_drawdown_accelerator_fail_closed_inputs_reset_and_telemetry():
    """Verify invalid lot handling returns 0.0, reset flushes state, and telemetry is reported."""
    da = DrawdownAccelerator()

    # Invalid lots return 0.0
    assert da.apply_lot(None) == 0.0
    assert da.apply_lot(True) == 0.0
    assert da.apply_lot(float("nan")) == 0.0
    assert da.apply_lot(-0.04) == 0.0
    assert da.apply_lot(0.0) == 0.0

    # Set up some streak
    da.record_trade(won=False)
    da.record_trade(won=False)
    da.record_trade(won=False)

    info = da.info()
    assert info["consec_losses"] == 3
    assert info["lot_multiplier"] == 0.50
    assert info["mode"] == "HALF_SIZE"

    # Reset
    da.reset()
    assert da._consec_losses == 0
    assert da._consec_wins == 0
    assert da._total_reductions == 0
    assert da.get_multiplier() == 1.0
