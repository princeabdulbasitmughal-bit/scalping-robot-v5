"""
Test Batch 351: Wave 451 Wavelet Variance Decomposition & Wave 452 Poisson Burst Hazard
=======================================================================================
Institutional unit test suite verifying multi-scale wavelet variance decomposition,
high-frequency noise-to-signal filtering, and order arrival point-process burstiness.
"""

import pytest
import math
import numpy as np
from wave451_wavelet_variance_decomposition_guard import Wave451WaveletVarianceDecompositionGuard
from wave452_poisson_burst_hazard_guard import Wave452PoissonBurstHazardGuard


class TestWave451WaveletVarianceDecompositionGuard:
    """Test suite for Wave 451: Multi-Scale Wavelet Variance Decomposition Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 16"):
            Wave451WaveletVarianceDecompositionGuard(window_size=10)

        with pytest.raises(ValueError, match="max_hf_energy_ratio must be in"):
            Wave451WaveletVarianceDecompositionGuard(max_hf_energy_ratio=0.20)

    def test_calm_multiscale_trend_no_block(self):
        guard = Wave451WaveletVarianceDecompositionGuard(window_size=32, max_hf_energy_ratio=0.65, min_samples=16)

        # Smooth persistent trend: returns have low high-frequency jitter, variance is at scales 2 and 3
        t = 100.0
        for i in range(25):
            t += 1.0
            # Smooth low-frequency drift
            r = 0.001 * math.sin(i / 5.0)
            guard.update(r, t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave451WaveletVarianceDecompositionGuard"
        assert telem["hf_energy_ratio"] <= 0.65

    def test_noise_dominated_microstructure_triggers_block(self):
        guard = Wave451WaveletVarianceDecompositionGuard(window_size=32, max_hf_energy_ratio=0.60, min_samples=16)

        # Pure alternating bid-ask bounce: r_t = +0.002, -0.002, +0.002, -0.002...
        # Max difference at lag 1, almost all energy at Scale 1!
        t = 100.0
        for i in range(25):
            t += 1.0
            r = 0.002 if i % 2 == 0 else -0.002
            guard.update(r, t)

        assert guard.is_blocked()
        assert "NOISE_DOMINATED_MICROSTRUCTURE" in guard.block_reason
        assert guard.hf_energy_ratio > 0.60

    def test_validation_and_reset(self):
        guard = Wave451WaveletVarianceDecompositionGuard()
        with pytest.raises(ValueError, match="log_return must be finite"):
            guard.update(float("inf"), 1.0)

        guard.update(0.001, 1.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(0.001, 1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._returns) == 0


class TestWave452PoissonBurstHazardGuard:
    """Test suite for Wave 452: High-Frequency Order Arrival Poisson Burst Hazard Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 15"):
            Wave452PoissonBurstHazardGuard(window_size=10)

        with pytest.raises(ValueError, match="burst_k must be in"):
            Wave452PoissonBurstHazardGuard(burst_k=2)

        with pytest.raises(ValueError, match="max_burstiness_threshold must be in"):
            Wave452PoissonBurstHazardGuard(max_burstiness_threshold=0.10)

        with pytest.raises(ValueError, match="max_arrival_intensity must be > 1"):
            Wave452PoissonBurstHazardGuard(max_arrival_intensity=0.5)

    def test_regular_poisson_stream_no_block(self):
        guard = Wave452PoissonBurstHazardGuard(
            window_size=25,
            burst_k=6,
            max_burstiness_threshold=0.60,
            max_arrival_intensity=80.0,
            min_events_for_decision=12
        )

        # Moderate exponential/regular arrivals (dt ~ 0.25s -> 4 arrivals/sec)
        t = 10.0
        np.random.seed(42)
        for i in range(20):
            dt = 0.20 + 0.10 * np.random.rand()
            t += dt
            guard.update(t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("SELL")
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave452PoissonBurstHazardGuard"
        assert telem["burstiness_index"] < 0.60
        assert telem["burst_intensity_hz"] < 80.0

    def test_bursty_clustering_triggers_block(self):
        guard = Wave452PoissonBurstHazardGuard(
            window_size=25,
            burst_k=6,
            max_burstiness_threshold=0.55,
            max_arrival_intensity=1000.0,
            min_events_for_decision=12
        )

        # Extreme heavy-tailed arrival pattern (Barabási 2005 burstiness):
        # Long quiet interval followed by intense clustering of arrivals
        t = 10.0
        guard.update(t)
        t += 50.0  # Prolonged silence creates high sigma/mu ratio
        guard.update(t)
        for _ in range(20):
            t += 0.002
            guard.update(t)

        assert guard.is_blocked()
        assert "PREDATORY_BURST_CLUSTERING" in guard.block_reason
        assert guard.burstiness_index > 0.55

    def test_high_frequency_order_flooding_triggers_block(self):
        guard = Wave452PoissonBurstHazardGuard(
            window_size=25,
            burst_k=6,
            max_burstiness_threshold=0.90,  # High B threshold to isolate intensity trigger
            max_arrival_intensity=60.0,      # 60 arrivals/sec cap
            min_events_for_decision=12
        )

        # 15 events spaced by 0.005s (200 arrivals/sec)
        t = 10.0
        for i in range(16):
            t += 0.005
            guard.update(t)

        assert guard.is_blocked()
        assert "HFT_ORDER_FLOODING_BURST" in guard.block_reason
        assert guard.burst_intensity_hz > 60.0

    def test_validation_and_reset(self):
        guard = Wave452PoissonBurstHazardGuard()
        with pytest.raises(ValueError, match="timestamp must be finite"):
            guard.update(float("nan"))

        guard.update(1.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._durations) == 0
