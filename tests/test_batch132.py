import pytest
import datetime
from datetime import timezone
import math
from wave30_session_lot_booster import SessionLotBooster, session_lot_booster, is_entry_blocked as w30_is_entry_blocked, is_blocked as w30_is_blocked, apply_boost as w30_apply_boost
from wave31_reversal_detector import ReversalDetector, reversal_detector, is_entry_blocked as w31_is_entry_blocked, is_blocked as w31_is_blocked, get_reversal_signal as w31_get_reversal_signal, update_price as w31_update_price


class TestBatch132:
    """Batch 132 Test Suite: wave30 Session Lot Booster & wave31 Reversal Detector."""

    def test_wave30_risk_guard_aliases(self):
        slb = SessionLotBooster()
        assert slb.is_blocked() is False
        assert slb.is_entry_blocked() is False

        # Module-level aliases
        session_lot_booster.reset()
        assert w30_is_blocked() is False
        assert w30_is_entry_blocked() is False
        assert w30_apply_boost(0.10) == 0.10

    def test_wave30_overlap_window_detection(self):
        slb = SessionLotBooster(overlap_start_utc=12, overlap_end_utc=15)
        dt_in = datetime.datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
        assert slb._in_overlap(dt_in) is True

        dt_out = datetime.datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
        assert slb._in_overlap(dt_out) is False

    def test_wave30_apply_boost_conditions(self):
        slb = SessionLotBooster(overlap_start_utc=12, overlap_end_utc=15, boost_multiplier=1.2, min_vol_index=1.3, min_win_rate=55.0)
        dt_overlap = datetime.datetime(2026, 10, 18, 13, 0, tzinfo=timezone.utc)
        # All conditions met: inside overlap, vol=1.5 >= 1.3, win_rate=60.0 >= 55.0
        boosted = slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=60.0, now_dt=dt_overlap)
        assert boosted == 0.12
        info = slb.info(now_dt=dt_overlap)
        assert info["currently_boosted"] is True
        assert info["total_boosts"] == 1

    def test_wave30_unmet_conditions_no_boost(self):
        slb = SessionLotBooster(overlap_start_utc=12, overlap_end_utc=15, min_vol_index=1.3, min_win_rate=55.0)
        dt_overlap = datetime.datetime(2026, 10, 18, 13, 0, tzinfo=timezone.utc)
        dt_outside = datetime.datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)

        # Outside overlap window
        assert slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=60.0, now_dt=dt_outside) == 0.10
        # Volatility too low
        assert slb.apply_boost(0.10, vol_index=1.1, win_rate_pct=60.0, now_dt=dt_overlap) == 0.10
        # Win rate too low
        assert slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=50.0, now_dt=dt_overlap) == 0.10

    def test_wave30_invalid_lots_and_reset(self):
        slb = SessionLotBooster()
        assert slb.apply_boost(None) is None
        assert slb.apply_boost(True) is True
        assert slb.apply_boost(-0.05) == -0.05
        assert slb.apply_boost(float('nan')) != slb.apply_boost(float('nan'))  # NaN identity

        slb._total_boosts = 5
        slb._last_boosted = True
        slb.reset()
        assert slb._total_boosts == 0
        assert slb._last_boosted is False

    def test_wave31_risk_guard_aliases(self):
        rd = ReversalDetector(cooldown_sec=30.0)
        assert rd.is_blocked() is False
        assert rd.is_entry_blocked() is False

        # Module-level aliases
        reversal_detector.reset()
        assert w31_is_blocked() is False
        assert w31_is_entry_blocked() is False
        sig, conf, _ = w31_get_reversal_signal()
        assert sig == "HOLD"

    def test_wave31_bearish_divergence_sell_reversal(self):
        rd = ReversalDetector(rsi_period=5, overbought=75.0, cooldown_sec=10.0)
        # Pre-seed history: price making higher highs (100 -> 105 -> 110), but RSI making lower highs (85 -> 80)
        rd._price_highs.extend([100.0, 105.0, 110.0])
        rd._price_lows.extend([98.0, 103.0, 108.0])
        rd._rsi_history.extend([88.0, 85.0, 80.0])

        sig, conf, reason = rd.get_reversal_signal(now_ts=1000.0)
        assert sig == "SELL"
        assert conf >= 0.30
        assert "bearish_divergence" in reason

        # Proposed BUY should be blocked due to strong SELL reversal
        assert rd.is_entry_blocked(proposed_signal="BUY", now_ts=1000.0) is True
        # Proposed SELL should NOT be blocked
        assert rd.is_entry_blocked(proposed_signal="SELL", now_ts=1000.0) is False

    def test_wave31_bullish_divergence_buy_reversal(self):
        rd = ReversalDetector(rsi_period=5, oversold=25.0, cooldown_sec=10.0)
        # Price making lower lows (100 -> 95 -> 90), but RSI making higher lows (15 -> 20)
        rd._price_highs.extend([102.0, 97.0, 92.0])
        rd._price_lows.extend([100.0, 95.0, 90.0])
        rd._rsi_history.extend([12.0, 15.0, 20.0])

        sig, conf, reason = rd.get_reversal_signal(now_ts=1000.0)
        assert sig == "BUY"
        assert conf >= 0.30
        assert "bullish_divergence" in reason

        # Proposed SELL should be blocked due to strong BUY reversal
        assert rd.is_entry_blocked(proposed_signal="SELL", now_ts=1000.0) is True
        assert rd.is_entry_blocked(proposed_signal="BUY", now_ts=1000.0) is False

    def test_wave31_ohlc_bar_validation(self):
        rd = ReversalDetector()
        # Valid dict bar
        bar_dict = {"open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0}
        assert rd.validate_bar(bar_dict) == (2000.0, 2005.0, 1995.0, 2002.0)

        # Valid tuple bar
        bar_tuple = (2000.0, 2005.0, 1995.0, 2002.0)
        assert rd.validate_bar(bar_tuple) == (2000.0, 2005.0, 1995.0, 2002.0)

        # Inverted invalid bar (high < low)
        invalid_bar = {"open": 2000.0, "high": 1990.0, "low": 2005.0, "close": 2000.0}
        assert rd.validate_bar(invalid_bar) is None

        # Sequence validation
        bars = [bar_dict, invalid_bar, bar_tuple]
        valid_bars = rd.validate_bars(bars)
        assert len(valid_bars) == 2

    def test_wave31_cooldown_and_reset(self):
        rd = ReversalDetector(cooldown_sec=50.0)
        rd._last_signal_time = 1000.0
        # At t=1020 (within 50s cooldown) -> returns HOLD
        sig, conf, reason = rd.get_reversal_signal(now_ts=1020.0)
        assert sig == "HOLD"
        assert "cooldown_active" in reason

        info = rd.info(now_ts=1020.0)
        assert info["is_cooldown_active"] is True
        assert info["cooldown_remaining_sec"] == 30.0

        # Reset
        rd.reset()
        assert rd._last_signal == "HOLD"
        assert rd._last_signal_time == 0.0
        assert len(rd._prices) == 0
