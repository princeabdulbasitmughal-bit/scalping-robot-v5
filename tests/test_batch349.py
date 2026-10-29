"""
Test Batch 349: Wave 446 Rough Volatility Hurst Guard & Wave 447 Queue Cancellation Intensity Guard
===================================================================================================
Rigorous quantitative unit tests verifying fractional Brownian motion Hurst exponent estimation,
microstructure roughness guards, phantom liquidity detection, and cancellation hazard monitoring.
"""

import pytest
import math
import numpy as np
from wave446_rough_volatility_hurst_guard import Wave446RoughVolatilityHurstGuard
from wave447_queue_cancellation_intensity_guard import Wave447QueueCancellationIntensityGuard


class TestWave446RoughVolatilityHurstGuard:
    """Test suite for Wave 446: Fractional Brownian Motion Rough Volatility Hurst Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 16"):
            Wave446RoughVolatilityHurstGuard(window_size=12)

        with pytest.raises(ValueError, match="Invalid thresholds"):
            Wave446RoughVolatilityHurstGuard(min_hurst_threshold=0.6, max_hurst_threshold=0.5)

    def test_calm_rough_volatility_no_block(self):
        guard = Wave446RoughVolatilityHurstGuard(window_size=32, min_hurst_threshold=0.05, max_hurst_threshold=0.50)
        
        # Smooth scaling series with H ~ 0.20
        # |v(t+Delta) - v(t)|^2 ~ Delta^(0.40)
        t = 100.0
        # Synthetic path generated with positive Hurst structure
        np.random.seed(42)
        v = 0.0
        for i in range(32):
            t += 1.0
            # fractional noise approximation with memory
            v = 0.65 * v + 0.15 * np.random.randn()
            vol_val = 0.020 * math.exp(v)
            guard.update(vol_val, t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        telem = guard.get_telemetry()
        assert 0.05 <= telem["estimated_hurst"] <= 0.50
        assert telem["guard"] == "Wave446RoughVolatilityHurstGuard"

    def test_ultra_rough_volatility_spike_triggers_block(self):
        guard = Wave446RoughVolatilityHurstGuard(window_size=32, min_hurst_threshold=0.10, max_hurst_threshold=0.50)
        
        # i.i.d. noise in log volatility creates a flat structure function across lags:
        # m(2, Delta) = 2 * sigma^2 for all Delta => slope 2H ~ 0 => H ~ 0 < 0.10
        t = 100.0
        np.random.seed(123)
        for i in range(32):
            t += 1.0
            vol_val = 0.020 * math.exp(0.20 * np.random.randn())
            guard.update(vol_val, t)

        assert guard.is_blocked()
        assert "ULTRA_ROUGH_TURBULENCE" in guard.block_reason
        assert guard.estimated_hurst < guard.min_hurst_threshold

    def test_trending_drift_volatility_triggers_block(self):
        guard = Wave446RoughVolatilityHurstGuard(window_size=32, min_hurst_threshold=0.05, max_hurst_threshold=0.45)
        
        # Deterministic linear drift: v(t) = a * t => |v(t+Delta) - v(t)|^2 = a^2 * Delta^2
        # Slope of ln m(2, Delta) vs ln Delta is exactly 2.0 => H = 2.0 / 2 = 1.0 > 0.45!
        t = 100.0
        for i in range(32):
            t += 1.0
            vol_val = math.exp(0.10 * i)
            guard.update(vol_val, t)

        assert guard.is_blocked()
        assert "SUPER_DIFFUSIVE_DRIFT" in guard.block_reason
        assert guard.estimated_hurst > guard.max_hurst_threshold

    def test_validation_and_reset(self):
        guard = Wave446RoughVolatilityHurstGuard(window_size=20)
        with pytest.raises(ValueError, match="Volatility must be positive and finite"):
            guard.update(-0.01, 1.0)

        with pytest.raises(ValueError, match="Volatility must be positive and finite"):
            guard.update(float("nan"), 1.0)

        guard.update(0.02, 1.0)
        with pytest.raises(ValueError, match="Timestamp must be strictly increasing"):
            guard.update(0.02, 1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._vol_history) == 0


class TestWave447QueueCancellationIntensityGuard:
    """Test suite for Wave 447: Limit Order Queue Cancellation Intensity Hazard Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 10"):
            Wave447QueueCancellationIntensityGuard(window_size=5)

        with pytest.raises(ValueError, match="max_cancellation_ratio must be in"):
            Wave447QueueCancellationIntensityGuard(max_cancellation_ratio=0.40)

        with pytest.raises(ValueError, match="max_cancellation_intensity must be > 0"):
            Wave447QueueCancellationIntensityGuard(max_cancellation_intensity=-5.0)

    def test_calm_balanced_flow_no_block(self):
        guard = Wave447QueueCancellationIntensityGuard(
            window_size=30,
            max_cancellation_ratio=0.85,
            max_cancellation_intensity=50.0,
            min_events_for_decision=10
        )
        
        # Balanced mix of CANCEL and FILL events at normal pace
        t = 10.0
        for i in range(20):
            t += 0.5  # 2 events/sec -> low intensity
            ev_type = "FILL" if i % 2 == 0 else "CANCEL"
            guard.update(ev_type, volume=10.0, timestamp=t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("SELL")
        assert math.isclose(guard.cancellation_ratio, 0.50, rel_tol=1e-2)
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave447QueueCancellationIntensityGuard"

    def test_high_cancellation_ratio_triggers_block(self):
        guard = Wave447QueueCancellationIntensityGuard(
            window_size=30,
            max_cancellation_ratio=0.80,
            max_cancellation_intensity=100.0,
            min_events_for_decision=10
        )

        # 9 cancellations and 1 fill spread across 10 seconds (intensity = 0.9/s, ratio = 900/910 = 98.9%)
        t = 10.0
        for i in range(9):
            t += 1.0
            guard.update("CANCEL", volume=100.0, timestamp=t)
        t += 1.0
        guard.update("FILL", volume=10.0, timestamp=t)

        assert guard.is_blocked()
        assert "PHANTOM_LIQUIDITY_HAZARD" in guard.block_reason
        assert guard.cancellation_ratio > 0.80

    def test_quote_stuffing_burst_triggers_block(self):
        guard = Wave447QueueCancellationIntensityGuard(
            window_size=30,
            max_cancellation_ratio=0.85,
            max_cancellation_intensity=40.0,  # 40 cancels/sec cap
            min_events_for_decision=10
        )

        # Interleave 10 cancels and 10 fills in 0.1 seconds -> total 20 events in 0.1s
        # cancel_ratio = 50% < 85%, but cancel_intensity = 10 / 0.1 = 100 cancels/sec > 40!
        t = 10.0
        for i in range(10):
            t += 0.005
            guard.update("CANCEL", volume=10.0, timestamp=t)
            t += 0.005
            guard.update("FILL", volume=10.0, timestamp=t)

        assert guard.is_blocked()
        assert "QUOTE_STUFFING_BURST" in guard.block_reason
        assert guard.cancellation_intensity > 40.0

    def test_validation_and_reset(self):
        guard = Wave447QueueCancellationIntensityGuard()
        with pytest.raises(ValueError, match="event_type must be one of"):
            guard.update("UNKNOWN_TYPE", 10.0, 1.0)

        with pytest.raises(ValueError, match="volume must be positive"):
            guard.update("CANCEL", -5.0, 1.0)

        guard.update("CANCEL", 10.0, 1.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update("CANCEL", 10.0, 1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._events) == 0
