import pytest
import math
from wave24_daily_profit_lock import DailyProfitLock, daily_profit_lock, is_entry_blocked as w24_is_entry_blocked, is_blocked as w24_is_blocked
from wave25_drawdown_accelerator import DrawdownAccelerator, drawdown_accelerator, is_entry_blocked as w25_is_entry_blocked, is_blocked as w25_is_blocked, apply_lot as w25_apply_lot, get_multiplier as w25_get_multiplier


class TestBatch129:
    """Batch 129 Test Suite: wave24 Daily Profit Lock & wave25 Drawdown Accelerator."""

    def test_wave24_risk_guard_aliases(self):
        dpl = DailyProfitLock(profit_target_usd=100.0, protect_min_score=70)
        assert dpl.is_blocked() is False
        assert dpl.is_entry_blocked() is False

        # Engage protect mode
        dpl.update(120.0)
        assert dpl.is_active is True
        # Score of 65 is blocked because protect_min_score is 70
        assert dpl.is_entry_blocked(score=65) is True
        assert dpl.is_entry_blocked(score=75) is False

        # Module-level aliases
        daily_profit_lock.reset()
        assert w24_is_blocked() is False
        assert w24_is_entry_blocked() is False

    def test_wave24_protect_mode_engagement(self):
        dpl = DailyProfitLock(profit_target_usd=150.0)
        dpl.update(50.0)
        assert dpl.is_active is False
        dpl.update(149.9)
        assert dpl.is_active is False
        dpl.update(150.1)
        assert dpl.is_active is True
        assert dpl._engagements == 1
        info = dpl.info()
        assert info["protect_mode"] is True
        assert info["peak_daily_pnl"] == 150.1

    def test_wave24_protect_mode_lot_reduction(self):
        dpl = DailyProfitLock(profit_target_usd=100.0, protect_lot=0.01)
        # Normal mode -> unmodified lot
        assert dpl.apply_lot(0.05) == 0.05

        # Protect mode -> capped to 0.01
        dpl.update(110.0)
        assert dpl.apply_lot(0.05) == 0.01
        assert dpl.apply_lot(0.01) == 0.01

    def test_wave24_protect_mode_min_score(self):
        dpl = DailyProfitLock(profit_target_usd=100.0, protect_min_score=75)
        # Normal mode -> base score preserved
        assert dpl.get_min_score(55) == 55

        # Protect mode -> elevated score enforced
        dpl.update(100.0)
        assert dpl.get_min_score(55) == 75
        # If base is already higher, keep higher base
        assert dpl.get_min_score(80) == 80

    def test_wave24_reset_and_invalid_inputs(self):
        dpl = DailyProfitLock()
        dpl.update(200.0)
        assert dpl.is_active is True

        dpl.reset()
        assert dpl.is_active is False
        assert dpl._peak_daily_pnl == 0.0

        # Invalid inputs ignored safely
        dpl.update(None)
        dpl.update(True)
        dpl.update(float('nan'))
        dpl.update(float('inf'))
        assert dpl._peak_daily_pnl == 0.0

    def test_wave25_risk_guard_aliases(self):
        da = DrawdownAccelerator()
        assert da.is_blocked() is False
        assert da.is_entry_blocked() is False

        # Module-level aliases
        drawdown_accelerator.reset()
        assert w25_is_blocked() is False
        assert w25_is_entry_blocked() is False
        assert w25_get_multiplier() == 1.0
        assert w25_apply_lot(0.05) == 0.05

    def test_wave25_loss_streak_tiers(self):
        da = DrawdownAccelerator()
        # 1-2 losses: full size (1.0)
        da.record_trade(won=False)
        assert da.get_multiplier() == 1.0
        da.record_trade(won=False)
        assert da.get_multiplier() == 1.0

        # 3-4 losses: tier 1 (0.50)
        da.record_trade(won=False)
        assert da.get_multiplier() == 0.50

        # 5-6 losses: tier 2 (0.25)
        da.record_trade(won=False)
        da.record_trade(won=False)
        assert da.get_multiplier() == 0.25

        # 7+ losses: tier 3 (0.10)
        da.record_trade(won=False)
        da.record_trade(won=False)
        assert da.get_multiplier() == 0.10

    def test_wave25_lot_reduction_calculation(self):
        da = DrawdownAccelerator()
        # 3 losses -> multiplier 0.50 -> 0.10 lot becomes 0.05
        for _ in range(3):
            da.record_trade(won=False)
        assert da.apply_lot(0.10) == 0.05

        # 5 losses -> multiplier 0.25 -> 0.10 lot becomes 0.03 (rounded)
        for _ in range(2):
            da.record_trade(won=False)
        assert da.apply_lot(0.10) == 0.03

        # 7 losses -> multiplier 0.10 -> 0.05 lot clamped to minimum 0.01
        for _ in range(2):
            da.record_trade(won=False)
        assert da.apply_lot(0.05) == 0.01

    def test_wave25_recovery_win_streak(self):
        da = DrawdownAccelerator(recovery_wins=2)
        # Pile up 5 losses -> multiplier 0.25
        for _ in range(5):
            da.record_trade(won=False)
        assert da.get_multiplier() == 0.25

        # 1 win is not enough for recovery
        da.record_trade(won=True)
        assert da.get_multiplier() == 0.25

        # 2nd consecutive win resets multiplier to 1.0
        da.record_trade(won=True)
        assert da.get_multiplier() == 1.0
        info = da.info()
        assert info["mode"] == "FULL_SIZE"
        assert info["lot_multiplier"] == 1.0

    def test_wave25_reset_and_invalid_lots(self):
        da = DrawdownAccelerator()
        for _ in range(4):
            da.record_trade(won=False)
        assert da._total_reductions > 0
        da.reset()
        assert da._consec_losses == 0
        assert da._consec_wins == 0
        assert da._total_reductions == 0

        # Invalid lots return 0.0
        assert da.apply_lot(None) == 0.0
        assert da.apply_lot(True) == 0.0
        assert da.apply_lot(-0.05) == 0.0
        assert da.apply_lot(float('nan')) == 0.0
        assert da.apply_lot(float('inf')) == 0.0
