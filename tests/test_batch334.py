"""
Batch 334 -- Tests for Wave 421 & Wave 422
==========================================
Wave 421: Trade Sign Run-Length Persistence Guard
Wave 422: Liquidity Replenishment Asymmetry & Skew Drift Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave421_trade_sign_run_length_guard import (
    Wave421TradeSignRunLengthGuard,
)
from wave422_replenishment_asymmetry_guard import (
    Wave422ReplenishmentAsymmetryGuard,
)


class TestWave421RunLengthGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave421TradeSignRunLengthGuard(max_run_length=2)
        with pytest.raises(ValueError):
            Wave421TradeSignRunLengthGuard(max_avg_run_length=0.5)

    def test_balanced_alternating_trades_no_block(self):
        guard = Wave421TradeSignRunLengthGuard(max_run_length=6, max_avg_run_length=3.0)
        t0 = time.monotonic()
        # Alternating trades (run lengths 1, 2, 1, 2)
        signs = [True, False, True, True, False, True, False, False, True]
        for i, s in enumerate(signs):
            guard.update(is_buy=s, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.current_run_length <= 2

    def test_persistent_run_length_triggers_block(self):
        guard = Wave421TradeSignRunLengthGuard(
            max_run_length=5, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 5 consecutive buys (run length 5 == max_run)
        for i in range(5):
            guard.update(is_buy=True, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 0.4)
        assert guard.last_reason == "PERSISTENT_TRADE_SIGN_RUN"
        assert guard.current_run_length >= 5

    def test_high_average_run_length_triggers_ignition(self):
        guard = Wave421TradeSignRunLengthGuard(
            max_run_length=10, max_avg_run_length=3.5, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Series of large runs (4 buys, 4 sells, 4 buys, 4 sells) -> avg = 4.0 > 3.5
        signs = [True]*4 + [False]*4 + [True]*4 + [False]*4
        for i, s in enumerate(signs):
            guard.update(is_buy=s, timestamp=t0 + i * 0.05)

        assert guard.is_blocked(t0 + len(signs)*0.05)
        assert guard.last_reason in [
            "UNILATERAL_ORDER_MOMENTUM_IGNITION",
            "PERSISTENT_TRADE_SIGN_RUN",
        ]

    def test_validation_and_reset(self):
        guard = Wave421TradeSignRunLengthGuard()
        t0 = time.monotonic()
        guard.update("INVALID_BOOL", t0)  # type: ignore
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.current_run_length == 0


class TestWave422ReplenishmentAsymmetryGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave422ReplenishmentAsymmetryGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave422ReplenishmentAsymmetryGuard(max_asymmetry_threshold=1.5)

    def test_symmetric_replenishment_no_block(self):
        guard = Wave422ReplenishmentAsymmetryGuard(
            window_size=5, max_asymmetry_threshold=0.70
        )
        t0 = time.monotonic()
        # Bids and asks replenish at identical rates (10 units per tick) -> Lambda = 0.0
        for i in range(10):
            guard.update(bid_queue=100.0 + i * 10.0, ask_queue=100.0 + i * 10.0, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert abs(guard.asymmetry_index) < 0.10

    def test_severe_asymmetric_drain_triggers_block(self):
        guard = Wave422ReplenishmentAsymmetryGuard(
            window_size=5, max_asymmetry_threshold=0.60, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=t0)
        # Ask replenishes massively (+100 in 0.1s), Bid remains static (+0)
        # v_ask = 1000, v_bid = 0 -> Lambda = 1.0 > 0.60
        guard.update(bid_queue=100.0, ask_queue=200.0, timestamp=t0 + 0.1)

        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "LIQUIDITY_REPLENISHMENT_ASYMMETRY"
        assert guard.asymmetry_index >= 0.90

    def test_validation_and_reset(self):
        guard = Wave422ReplenishmentAsymmetryGuard()
        t0 = time.monotonic()
        guard.update(-10.0, 50.0, t0)  # negative queue
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.asymmetry_index == 0.0
