"""
Batch 323 -- Tests for Wave 403 and Wave 404
=============================================
Wave 403: Gamma Scalping Inventory Imbalance Guard
Wave 404: Adaptive Volatility Kalman Filter Innovation Guard

Target: 14+ tests, 0 failures
"""

import time
import pytest

from wave403_gamma_scalping_inventory_imbalance_guard import (
    Wave403GammaScalpingInventoryImbalanceGuard,
)
from wave404_adaptive_volatility_kalman_filter_guard import (
    Wave404AdaptiveVolatilityKalmanFilterGuard,
)


class TestWave403InventoryImbalance:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave403GammaScalpingInventoryImbalanceGuard(critical_load_threshold=1.5)
        with pytest.raises(ValueError):
            Wave403GammaScalpingInventoryImbalanceGuard(cooldown_seconds=0.0)

    def test_low_inventory_no_block(self):
        guard = Wave403GammaScalpingInventoryImbalanceGuard(critical_load_threshold=0.80)
        t0 = time.monotonic()
        # 2 lots on 10 max capacity -> load = 0.20 < 0.80
        for i in range(5):
            guard.update(net_inventory=2.0, max_capacity=10.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_critical_inventory_triggers_block(self):
        guard = Wave403GammaScalpingInventoryImbalanceGuard(critical_load_threshold=0.80)
        t0 = time.monotonic()
        # 9 lots on 10 max capacity -> load = 0.90 >= 0.80
        guard.update(net_inventory=-9.0, max_capacity=10.0, timestamp=t0)
        assert guard.is_blocked()
        assert guard.last_reason == "GAMMA_INVENTORY_SKEW_LOCKOUT"

    def test_invalid_input_validation(self):
        guard = Wave403GammaScalpingInventoryImbalanceGuard()
        guard.update(net_inventory=5.0, max_capacity=0.0, timestamp=1.0)  # zero capacity
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(net_inventory="5", max_capacity=10.0, timestamp=1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave403GammaScalpingInventoryImbalanceGuard()
        guard.update(net_inventory=True, max_capacity=10.0, timestamp=1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 2.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave404KalmanFilterInnovation:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave404AdaptiveVolatilityKalmanFilterGuard(q_process_noise=-0.1)
        with pytest.raises(ValueError):
            Wave404AdaptiveVolatilityKalmanFilterGuard(nis_threshold=0.0)

    def test_smooth_tracking_no_block(self):
        guard = Wave404AdaptiveVolatilityKalmanFilterGuard(
            q_process_noise=0.1, r_measurement_noise=0.1, nis_threshold=25.0
        )
        t0 = time.monotonic()
        # Small continuous steps
        for i in range(20):
            p = 100.0 + i * 0.05
            guard.update(bid=p, ask=p + 0.1, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_large_innovation_spike_triggers_block(self):
        guard = Wave404AdaptiveVolatilityKalmanFilterGuard(
            q_process_noise=0.01, r_measurement_noise=0.05, nis_threshold=16.0
        )
        t0 = time.monotonic()
        # Track baseline around 100
        for i in range(5):
            guard.update(bid=100.0, ask=100.1, timestamp=t0 + i)
        assert not guard.is_blocked()

        # Sudden massive shock: jump to 110.0 -> nu ~ 10.0, S ~ 0.1 -> NIS ~ 1000 >> 16
        guard.update(bid=110.0, ask=110.1, timestamp=t0 + 6.0)
        assert guard.is_blocked()
        assert guard.last_reason == "KALMAN_INNOVATION_OUTLIER"

    def test_invalid_input_validation(self):
        guard = Wave404AdaptiveVolatilityKalmanFilterGuard()
        guard.update(bid=100.5, ask=100.2, timestamp=1.0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(bid=-100.0, ask=100.0, timestamp=1.0)  # negative bid
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_non_monotonic_timestamp(self):
        guard = Wave404AdaptiveVolatilityKalmanFilterGuard()
        guard.update(bid=100.0, ask=100.1, timestamp=5.0)
        guard.update(bid=100.0, ask=100.1, timestamp=4.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave404AdaptiveVolatilityKalmanFilterGuard()
        guard.update(bid=100.0, ask=100.1, timestamp=1.0)
        guard.update(bid=100.0, ask=100.1, timestamp=1.0)  # dt = 0
        assert guard.is_blocked()
        assert guard.is_entry_blocked(100.0, 100.1, 2.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
