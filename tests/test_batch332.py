"""
Batch 332 -- Tests for Wave 418 & Wave 419
==========================================
Wave 418: Bid-Ask Spread Asymmetry & Quote Resilience Guard
Wave 419: Order Flow Toxicity Duration & Horizon Persistence Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave418_spread_asymmetry_resilience_guard import (
    Wave418SpreadAsymmetryResilienceGuard,
)
from wave419_order_flow_toxicity_duration_guard import (
    Wave419OrderFlowToxicityDurationGuard,
)


class TestWave418SpreadAsymmetryGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave418SpreadAsymmetryResilienceGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave418SpreadAsymmetryResilienceGuard(max_asymmetry_threshold=1.5)
        with pytest.raises(ValueError):
            Wave418SpreadAsymmetryResilienceGuard(ema_alpha=0.0)

    def test_symmetric_market_quotes_no_block(self):
        guard = Wave418SpreadAsymmetryResilienceGuard(
            window_size=5, max_asymmetry_threshold=0.70
        )
        t0 = time.monotonic()
        # Symmetric spreads around stable price 100.0 (bid 99.95, ask 100.05) -> zeta ~ 0.0
        for i in range(10):
            guard.update(bid=99.95, ask=100.05, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert abs(guard.asymmetry_index) < 0.10

    def test_defensive_ask_widening_triggers_block(self):
        guard = Wave418SpreadAsymmetryResilienceGuard(
            window_size=5, max_asymmetry_threshold=0.60, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Stable baseline around 100.0
        for i in range(5):
            guard.update(bid=99.95, ask=100.05, timestamp=t0 + i * 0.1)

        # Sudden quote skewing: bid remains tight (99.98), but ask blows out (100.50)
        # s_bid = 100.0 - 99.98 = 0.02, s_ask = 100.50 - 100.0 = 0.50 -> zeta = (0.50 - 0.02)/(0.52) = 0.92 > 0.60
        guard.update(bid=99.98, ask=100.50, timestamp=t0 + 1.0)

        assert guard.is_blocked(t0 + 1.0)
        assert guard.last_reason == "ONE_SIDED_QUOTE_WIDENING"
        assert guard.asymmetry_index >= 0.70

    def test_validation_and_reset(self):
        guard = Wave418SpreadAsymmetryResilienceGuard()
        t0 = time.monotonic()
        guard.update(100.0, 99.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.asymmetry_index == 0.0


class TestWave419ToxicityDurationGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave419OrderFlowToxicityDurationGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave419OrderFlowToxicityDurationGuard(max_toxic_duration_sec=-1.0)
        with pytest.raises(ValueError):
            Wave419OrderFlowToxicityDurationGuard(min_toxic_ratio=1.5)

    def test_balanced_trading_flow_no_block(self):
        guard = Wave419OrderFlowToxicityDurationGuard(
            window_size=6, min_toxic_ratio=0.70
        )
        t0 = time.monotonic()
        # Alternating buy and sell trades of equal volume
        for i in range(12):
            guard.update(volume=50.0, is_buy=(i % 2 == 0), timestamp=t0 + i * 0.5)

        assert not guard.is_blocked()
        assert guard.toxic_duration_sec == 0.0

    def test_persistent_unidirectional_sweep_duration(self):
        guard = Wave419OrderFlowToxicityDurationGuard(
            window_size=5, max_toxic_duration_sec=2.0, min_toxic_ratio=0.70, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 14 continuous buy orders spread across 4.2 seconds (toxic duration 2.7s > 2.0s)
        for i in range(14):
            guard.update(volume=25.0, is_buy=True, timestamp=t0 + i * 0.3)

        assert guard.is_blocked(t0 + 4.2)
        assert guard.last_reason == "PERSISTENT_TOXIC_FLOW_DURATION"
        assert guard.toxic_duration_sec >= 2.0

    def test_unrelenting_volume_sweep_limit(self):
        guard = Wave419OrderFlowToxicityDurationGuard(
            window_size=5, max_toxic_duration_sec=10.0, max_sweep_volume=300.0, min_toxic_ratio=0.70, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 12 trades of 50 units (accumulates > 350 volume after window warm-up)
        for i in range(12):
            guard.update(volume=50.0, is_buy=True, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.2)
        assert guard.last_reason == "UNRELENTING_ORDER_SWEEP"
        assert guard.cumulative_sweep_volume >= 300.0

    def test_validation_and_reset(self):
        guard = Wave419OrderFlowToxicityDurationGuard(window_size=5)
        t0 = time.monotonic()
        guard.update(volume=-50.0, is_buy=True, timestamp=t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.toxic_duration_sec == 0.0
