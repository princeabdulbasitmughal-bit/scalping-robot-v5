"""
Batch 324 -- Tests for Wave 405 Multi-Asset Order Flow Correlation Guard
========================================================================
Wave 405: Sovereign Multi-Asset Order Flow Correlation Guard

Target: 8+ tests, 0 failures
"""

import time
import pytest

from wave405_multi_asset_order_flow_correlation_guard import (
    Wave405MultiAssetOrderFlowCorrelationGuard,
)


class TestWave405CorrelationGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave405MultiAssetOrderFlowCorrelationGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave405MultiAssetOrderFlowCorrelationGuard(min_correlation_threshold=1.5)

    def test_strongly_correlated_no_block(self):
        guard = Wave405MultiAssetOrderFlowCorrelationGuard(
            window_size=10, min_correlation_threshold=0.50
        )
        t0 = time.monotonic()
        # Primary and proxy move together in lockstep (rho ~ 1.0)
        for i in range(15):
            ret = 0.001 * (1.0 if i % 2 == 0 else -1.0)
            guard.update(primary_return=ret, proxy_return=ret * 0.95, timestamp=t0 + i)
        assert not guard.is_blocked()
        assert guard.current_correlation >= 0.80

    def test_decoupling_triggers_block(self):
        guard = Wave405MultiAssetOrderFlowCorrelationGuard(
            window_size=10, min_correlation_threshold=0.40
        )
        t0 = time.monotonic()
        # Inverted returns (rho = -1.0 <= 0.40)
        for i in range(12):
            ret = 0.001 * (1.0 if i % 2 == 0 else -1.0)
            guard.update(primary_return=ret, proxy_return=-ret, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "CROSS_ASSET_CORRELATION_DECOUPLING"

    def test_correlation_drift_triggers_block(self):
        guard = Wave405MultiAssetOrderFlowCorrelationGuard(
            window_size=6, min_correlation_threshold=-0.50, max_correlation_drift=0.50
        )
        t0 = time.monotonic()
        # Step 1: positively correlated (rho = 1.0)
        for i in range(6):
            ret = 0.001 * (1.0 if i % 2 == 0 else -1.0)
            guard.update(primary_return=ret, proxy_return=ret, timestamp=t0 + i)
        assert not guard.is_blocked()

        # Step 2: suddenly invert pairs to create huge drift
        for i in range(6):
            ret = 0.001 * (1.0 if i % 2 == 0 else -1.0)
            guard.update(primary_return=ret, proxy_return=-ret, timestamp=t0 + 6 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "CROSS_ASSET_CORRELATION_DECOUPLING"

    def test_invalid_input_validation(self):
        guard = Wave405MultiAssetOrderFlowCorrelationGuard()
        guard.update(primary_return="invalid", proxy_return=0.01, timestamp=1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(primary_return=0.01, proxy_return=True, timestamp=1.0)  # bool
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave405MultiAssetOrderFlowCorrelationGuard()
        guard.update(primary_return=0.01, proxy_return=0.01, timestamp="bad_ts")
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 2.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
        assert guard.current_correlation == 1.0
