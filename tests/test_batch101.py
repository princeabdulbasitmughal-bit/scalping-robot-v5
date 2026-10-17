"""
tests/test_batch101.py
Batch 101 Unit Tests: Session Lot Booster (wave30) & Reversal Detector (wave31).
Expands test baseline beyond 1,247+ passing tests to 1,257+ passing tests across 101 test suites!
Verifies:
1. wave30: SessionLotBooster initialization defaults, hours, bounds, and boolean rejection.
2. wave30: Overlap window evaluation (London/NY overlap 12:00-15:00 UTC).
3. wave30: Dynamic lot boost application when all window, volatility, and win-rate criteria are met.
4. wave30: Strict preservation of standard lot size when any criteria fails.
5. wave30: Fail-closed handling on boolean/invalid inputs, reset(), and info() telemetry.
6. wave31: ReversalDetector initialization defaults, threshold bounds, and boolean rejection.
7. wave31: OHLC bar validation (dict, list, tuple) and corrupt/inverted bar filtering.
8. wave31: Bearish divergence overbought SELL signal generation and confidence scoring.
9. wave31: Bullish divergence oversold BUY signal generation and confidence scoring.
10. wave31: Post-reversal cooldown lockout (60s), reset(), and info() telemetry introspection.
"""

from datetime import datetime, timezone
import pytest

from wave30_session_lot_booster import SessionLotBooster
from wave31_reversal_detector import ReversalDetector


def test_wave30_session_lot_booster_initialization_defaults():
    """Verify SessionLotBooster initializes with defaults and guards boolean inputs."""
    slb = SessionLotBooster()
    assert slb._start_h == 12
    assert slb._end_h == 15
    assert slb._boost == 1.2
    assert slb._min_vol == 1.3
    assert slb._min_wr == 55.0
    assert slb._total_boosts == 0
    assert slb._last_boosted is False

    # Boolean parameter rejection in init
    slb_bool = SessionLotBooster(
        overlap_start_utc=True,
        overlap_end_utc=False,
        boost_multiplier=True,
        min_vol_index=False,
        min_win_rate=True,
    )
    assert slb_bool._start_h == 12
    assert slb_bool._end_h == 15
    assert slb_bool._boost == 1.2
    assert slb_bool._min_vol == 1.3
    assert slb_bool._min_wr == 55.0


def test_wave30_session_lot_booster_overlap_window_filtering():
    """Verify London/NY overlap window detection correctly identifies active hours."""
    slb = SessionLotBooster(overlap_start_utc=12, overlap_end_utc=15)

    # 13:30 UTC -> inside overlap
    dt_inside = datetime(2026, 10, 21, 13, 30, tzinfo=timezone.utc)
    assert slb._in_overlap(dt_inside) is True

    # 12:00 UTC (exact start) -> inside
    dt_start = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    assert slb._in_overlap(dt_start) is True

    # 15:00 UTC (exact end) -> outside
    dt_end = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
    assert slb._in_overlap(dt_end) is False

    # 09:00 UTC -> outside
    dt_morning = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
    assert slb._in_overlap(dt_morning) is False


def test_wave30_session_lot_booster_boost_execution_when_conditions_met():
    """Verify lot size is multiplied by boost_multiplier when inside overlap and metrics exceed thresholds."""
    slb = SessionLotBooster(boost_multiplier=1.2, min_vol_index=1.3, min_win_rate=55.0)
    dt_active = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)

    # All criteria satisfied: overlap=True, vol=1.4 >= 1.3, win_rate=60.0 >= 55.0
    # Lot 0.10 * 1.2 = 0.12
    boosted = slb.apply_boost(0.10, vol_index=1.4, win_rate_pct=60.0, now_dt=dt_active)
    assert boosted == 0.12
    assert slb._last_boosted is True
    assert slb._total_boosts == 1

    # Consecutive call does not duplicate total_boosts count
    boosted_2 = slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=62.0, now_dt=dt_active)
    assert boosted_2 == 0.12
    assert slb._total_boosts == 1


def test_wave30_session_lot_booster_block_when_conditions_not_met():
    """Verify base lot is preserved unchanged if any condition fails."""
    slb = SessionLotBooster(boost_multiplier=1.2, min_vol_index=1.3, min_win_rate=55.0)
    dt_active = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    dt_inactive = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)

    # 1. Volatility too low (1.1 < 1.3)
    assert slb.apply_boost(0.10, vol_index=1.1, win_rate_pct=60.0, now_dt=dt_active) == 0.10
    assert slb._last_boosted is False

    # 2. Win rate too low (50.0 < 55.0)
    assert slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=50.0, now_dt=dt_active) == 0.10

    # 3. Outside overlap window
    assert slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=65.0, now_dt=dt_inactive) == 0.10


def test_wave30_session_lot_booster_fail_closed_inputs_and_reset():
    """Verify invalid inputs return lot unchanged, reset flushes state, and info reports telemetry."""
    slb = SessionLotBooster()
    dt_active = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)

    # Invalid lots return input unchanged
    assert slb.apply_boost(None) is None
    assert slb.apply_boost(True) is True
    assert slb.apply_boost(float("nan")) is not None
    assert slb.apply_boost(-0.05) == -0.05

    # Safe fallback for boolean metrics
    assert slb.apply_boost(0.10, vol_index=True, win_rate_pct=True, now_dt=dt_active) == 0.10

    # Apply valid boost
    slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=60.0, now_dt=dt_active)
    info = slb.info(now_dt=dt_active)
    assert info["in_overlap_window"] is True
    assert info["currently_boosted"] is True
    assert info["total_boosts"] == 1

    # Reset
    slb.reset()
    assert slb._total_boosts == 0
    assert slb._last_boosted is False


def test_wave31_reversal_detector_initialization_defaults_and_clamping():
    """Verify ReversalDetector initializes with defaults, clamps bounds, and rejects booleans."""
    rd = ReversalDetector()
    assert rd._rsi_period == 14
    assert rd._overbought == 75.0
    assert rd._oversold == 25.0
    assert rd._price_window == 5
    assert rd._cooldown == 60.0
    assert rd._last_signal == "HOLD"
    assert rd._total_reversals == 0

    # Custom bounded initialization
    rd_clamped = ReversalDetector(overbought=120.0, oversold=-10.0, price_window=1)
    assert rd_clamped._overbought == 75.0  # clamped to default
    assert rd_clamped._oversold == 25.0    # clamped to default
    assert rd_clamped._price_window == 3   # min window 3

    # Boolean parameter rejection
    rd_bool = ReversalDetector(rsi_period=True, overbought=False, cooldown_sec=True)
    assert rd_bool._rsi_period == 14
    assert rd_bool._overbought == 75.0
    assert rd_bool._cooldown == 60.0


def test_wave31_reversal_detector_bar_validation():
    """Verify OHLC bar validator accepts valid formats and discards corrupt/inverted bars."""
    # Valid dict bar
    bar_dict = {"open": 2400.0, "high": 2405.0, "low": 2398.0, "close": 2402.0}
    clean_dict = ReversalDetector.validate_bar(bar_dict)
    assert clean_dict == (2400.0, 2405.0, 2398.0, 2402.0)

    # Valid tuple bar
    bar_tuple = (2400.0, 2405.0, 2398.0, 2402.0)
    assert ReversalDetector.validate_bar(bar_tuple) == (2400.0, 2405.0, 2398.0, 2402.0)

    # Corrupt / inverted high-low bar -> None
    assert ReversalDetector.validate_bar({"open": 2400.0, "high": 2390.0, "low": 2405.0, "close": 2400.0}) is None
    # None bar -> None
    assert ReversalDetector.validate_bar(None) is None
    # Short bar -> None
    assert ReversalDetector.validate_bar([2400.0, 2405.0]) is None

    # Batch validation discards bad bars
    bars = [
        {"open": 2400.0, "high": 2405.0, "low": 2398.0, "close": 2402.0},
        None,
        {"open": 2402.0, "high": 2406.0, "low": 2401.0, "close": 2404.0},
    ]
    valid_list = ReversalDetector.validate_bars(bars)
    assert len(valid_list) == 2


def test_wave31_reversal_detector_bearish_divergence_sell_signal():
    """Verify bearish divergence (price higher high, RSI lower high in overbought zone) produces SELL signal."""
    rd = ReversalDetector(overbought=75.0, cooldown_sec=60.0)
    t0 = 5000.0

    # Feed 3 ticks establishing price higher high but RSI lower high (>75)
    rd.update(2400.0, rsi=76.0)
    rd.update(2402.0, rsi=82.0)  # prev high = 2402.0, prev rsi = 82.0
    rd.update(2405.0, rsi=78.0)  # latest high = 2405.0 (> 2402.0), latest rsi = 78.0 (< 82.0 and > 75.0)

    signal, conf, reason = rd.get_reversal_signal(now_ts=t0)
    assert signal == "SELL"
    assert conf >= 0.30
    assert reason == "bearish_divergence_overbought"
    assert rd._total_reversals == 1


def test_wave31_reversal_detector_bullish_divergence_buy_signal():
    """Verify bullish divergence (price lower low, RSI higher low in oversold zone) produces BUY signal."""
    rd = ReversalDetector(oversold=25.0, cooldown_sec=60.0)
    t0 = 6000.0

    # Feed 3 ticks establishing price lower low but RSI higher low (<25)
    rd.update(2400.0, rsi=24.0)
    rd.update(2398.0, rsi=18.0)  # prev low = 2398.0, prev rsi = 18.0
    rd.update(2395.0, rsi=22.0)  # latest low = 2395.0 (< 2398.0), latest rsi = 22.0 (> 18.0 and < 25.0)

    signal, conf, reason = rd.get_reversal_signal(now_ts=t0)
    assert signal == "BUY"
    assert conf >= 0.30
    assert reason == "bullish_divergence_oversold"
    assert rd._total_reversals == 1


def test_wave31_reversal_detector_cooldown_lockout_and_telemetry():
    """Verify cooldown period (60s) blocks subsequent signals, reset flushes state, and info reports telemetry."""
    rd = ReversalDetector(overbought=75.0, cooldown_sec=60.0)
    t0 = 7000.0

    # Establish bearish divergence
    rd.update(2400.0, rsi=76.0)
    rd.update(2402.0, rsi=82.0)
    rd.update(2405.0, rsi=78.0)

    # First signal fires
    sig1, _, _ = rd.get_reversal_signal(now_ts=t0)
    assert sig1 == "SELL"

    # Query during cooldown (t0 + 30s) -> HOLD with cooldown_active
    sig2, conf2, reason2 = rd.get_reversal_signal(now_ts=t0 + 30.0)
    assert sig2 == "HOLD"
    assert conf2 == 0.0
    assert reason2 == "cooldown_active"

    info = rd.info(now_ts=t0 + 30.0)
    assert info["wave"] == 31
    assert info["name"] == "ReversalDetector"
    assert info["last_signal"] == "SELL"
    assert info["is_cooldown_active"] is True
    assert info["cooldown_remaining_sec"] == 30.0
    assert info["total_reversals"] == 1

    # Reset flushes state
    rd.reset()
    assert rd._last_signal == "HOLD"
    assert len(rd._prices) == 0
    assert len(rd._rsi_history) == 0
