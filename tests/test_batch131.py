import pytest
import math
from wave28_momentum_confirmation import MomentumConfirmation, momentum_confirmation, is_entry_blocked as w28_is_entry_blocked, is_blocked as w28_is_blocked, is_momentum_confirmed as w28_is_momentum_confirmed, update_price as w28_update_price
from wave29_adaptive_tp import AdaptiveTp, adaptive_tp, is_entry_blocked as w29_is_entry_blocked, is_blocked as w29_is_blocked, adjust_tp as w29_adjust_tp, update_price as w29_update_price


class TestBatch131:
    """Batch 131 Test Suite: wave28 Momentum Confirmation & wave29 Adaptive TP."""

    def test_wave28_risk_guard_aliases(self):
        mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)
        # Empty buffer -> not blocked
        assert mc.is_blocked("BUY") is False
        assert mc.is_entry_blocked("BUY") is False

        # Feed 5 falling prices -> BUY should be blocked
        for p in [2000.5, 2000.4, 2000.3, 2000.2, 2000.1]:
            mc.update_price(p)
        assert mc.is_blocked("BUY") is True
        assert mc.is_entry_blocked("BUY") is True
        # SELL should be confirmed
        assert mc.is_blocked("SELL") is False

        # Module-level aliases
        momentum_confirmation.reset()
        assert w28_is_blocked("BUY") is False
        assert w28_is_entry_blocked("BUY") is False
        ok, _ = w28_is_momentum_confirmed("BUY")
        assert ok is True

    def test_wave28_buy_momentum_confirmation(self):
        mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)
        # 3 ascending ticks out of 4 moves: 100 -> 101 -> 102 -> 103 -> 102.5
        for p in [100.0, 101.0, 102.0, 103.0, 102.5]:
            mc.update_price(p)
        ok, reason = mc.is_momentum_confirmed("BUY")
        assert ok is True

        # Now feed 3 descending ticks -> BUY rejected
        for p in [102.0, 101.0, 100.0]:
            mc.update_price(p)
        ok, reason = mc.is_momentum_confirmed("BUY")
        assert ok is False
        assert "BUY rejected" in reason

    def test_wave28_sell_momentum_confirmation(self):
        mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)
        # 3 descending ticks: 105 -> 104 -> 103 -> 102
        for p in [105.0, 104.0, 103.0, 102.0]:
            mc.update_price(p)
        ok, reason = mc.is_momentum_confirmed("SELL")
        assert ok is True

        # Now feed 3 ascending ticks -> SELL rejected
        for p in [103.0, 104.0, 105.0]:
            mc.update_price(p)
        ok, reason = mc.is_momentum_confirmed("SELL")
        assert ok is False
        assert "SELL rejected" in reason

    def test_wave28_insufficient_ticks_and_non_directional_signals(self):
        mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)
        # Only 2 prices -> insufficient data -> default allow
        mc.update_price(100.0)
        mc.update_price(101.0)
        ok, reason = mc.is_momentum_confirmed("BUY")
        assert ok is True
        assert "insufficient tick data" in reason

        # HOLD signal or invalid signal -> always allowed
        assert mc.is_momentum_confirmed("HOLD")[0] is True
        assert mc.is_momentum_confirmed(None)[0] is True

    def test_wave28_invalid_prices_and_reset(self):
        mc = MomentumConfirmation()
        mc.update_price(None)
        mc.update_price(True)
        mc.update_price("not_a_number")
        mc.update_price(-100.0)
        mc.update_price(0.0)
        mc.update_price(float('nan'))
        mc.update_price(float('inf'))
        assert len(mc._price_buffer) == 0

        mc.update_price(100.0)
        mc.update_price(101.0)
        assert len(mc._price_buffer) == 2
        mc.reset()
        assert len(mc._price_buffer) == 0
        assert mc._total_rejections == 0

    def test_wave29_risk_guard_aliases(self):
        atp = AdaptiveTp()
        assert atp.is_blocked() is False
        assert atp.is_entry_blocked() is False

        # Module-level aliases
        adaptive_tp.reset()
        assert w29_is_blocked() is False
        assert w29_is_entry_blocked() is False
        adjusted = w29_adjust_tp(20.0)
        assert adjusted == 20.0

    def test_wave29_high_volatility_extend_tp(self):
        atp = AdaptiveTp(window=5, extend_ratio=1.5, atr_high_threshold=0.10)
        # Feed high-volatility ticks (diff = 0.20 per tick, above threshold 0.10)
        for i in range(6):
            atp.update_price(100.0 + (i * 0.20 if i % 2 == 0 else -i * 0.20))
        assert atp.get_tp_multiplier() == 1.5
        adjusted = atp.adjust_tp(20.0)
        assert adjusted == 30.0

    def test_wave29_low_volatility_shrink_tp(self):
        atp = AdaptiveTp(window=5, shrink_ratio=0.7, atr_low_threshold=0.05, min_tp_pips=5.0)
        # Feed calm/low-volatility ticks (diff = 0.02 per tick, below threshold 0.05)
        for i in range(6):
            atp.update_price(100.0 + (i * 0.02))
        assert atp.get_tp_multiplier() == 0.7
        adjusted = atp.adjust_tp(20.0)
        assert adjusted == 14.0

    def test_wave29_min_tp_and_min_rr_constraints(self):
        atp = AdaptiveTp(window=5, shrink_ratio=0.5, atr_low_threshold=0.05, min_tp_pips=8.0)
        for i in range(6):
            atp.update_price(100.0 + (i * 0.01))
        # Base 10.0 * 0.5 = 5.0, but clamped to min_tp_pips = 8.0
        adjusted = atp.adjust_tp(10.0)
        assert adjusted == 8.0

        # Reward to risk constraint: sl = 10.0, min_rr = 1.5 -> min TP must be 15.0
        adjusted_rr = atp.adjust_tp(10.0, sl_pips=10.0, min_rr_ratio=1.5)
        assert adjusted_rr == 15.0

    def test_wave29_zero_division_safety_and_reset(self):
        atp = AdaptiveTp()
        # Safe reward-to-risk ratio calculation
        assert atp.calculate_reward_to_risk(20.0, 10.0) == 2.0
        assert atp.calculate_reward_to_risk(20.0, 0.0) == 0.0
        assert atp.calculate_reward_to_risk(20.0, -5.0) == 0.0
        assert atp.calculate_reward_to_risk(20.0, float('nan')) == 0.0
        assert atp.calculate_reward_to_risk(None, 10.0) == 0.0

        # Telemetry & reset
        atp.update_price(100.0)
        atp.update_price(105.0)
        info = atp.info()
        assert info["name"] == "AdaptiveTp"
        assert "current_atr" in info

        atp.reset()
        assert len(atp._prices) == 0
        assert atp._current_atr == 0.0
        assert atp._last_multiplier == 1.0
