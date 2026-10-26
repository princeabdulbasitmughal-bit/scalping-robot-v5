"""
Batch 312 -- Tests for Wave 382 and Wave 383
=============================================
Wave 382: LOB Level Arrival Rate Guard
Wave 383: Trade Flow Signed Tick Volume Imbalance EMA Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave382_lob_level_arrival_rate_guard import (
    Wave382LOBLevelArrivalRateGuard,
)
from wave383_trade_flow_signed_tick_volume_imbalance_ema_guard import (
    Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard,
)


class TestWave382LevelArrivalRate:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave382LOBLevelArrivalRateGuard(window_seconds=0.0)
        with pytest.raises(ValueError):
            Wave382LOBLevelArrivalRateGuard(max_arrival_rate=-1.0)

    def test_static_levels_no_block(self):
        guard = Wave382LOBLevelArrivalRateGuard(window_seconds=1.0, max_arrival_rate=10.0)
        t0 = time.monotonic()
        bids = [1.1000, 1.0999, 1.0998]
        asks = [1.1001, 1.1002, 1.1003]
        for i in range(15):
            guard.update(bid_levels=bids, ask_levels=asks, timestamp=t0 + i * 0.05)
        assert not guard.is_blocked()

    def test_high_arrival_rate_triggers_block(self):
        guard = Wave382LOBLevelArrivalRateGuard(window_seconds=1.0, max_arrival_rate=5.0)
        t0 = time.monotonic()
        # Initial snapshot
        guard.update([1.1000], [1.1005], t0)
        # Introduce 10 completely new price levels within 0.2 seconds
        for i in range(10):
            bids = [1.1000 - (i + 1) * 0.0001]
            asks = [1.1005 + (i + 1) * 0.0001]
            guard.update(bids, asks, t0 + 0.02 * (i + 1))
        assert guard.is_blocked()
        assert guard.last_reason == "LEVEL_ARRIVAL_RATE_BREACH"

    def test_stale_arrivals_evicted(self):
        guard = Wave382LOBLevelArrivalRateGuard(window_seconds=0.5, max_arrival_rate=5.0)
        t0 = time.monotonic()
        guard.update([1.10], [1.11], t0)
        guard.update([1.101], [1.111], t0 + 0.01)
        # Advance beyond window_seconds
        guard.update([1.101], [1.111], t0 + 1.0)
        assert not guard.is_blocked()

    def test_invalid_input_validation(self):
        guard = Wave382LOBLevelArrivalRateGuard()
        guard.update("not_a_list", [1.10], 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update([True], [1.10], 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave382LOBLevelArrivalRateGuard()
        guard.update([-1.10], [1.10], 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave383SignedVolumeEMA:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard(ema_period=1)
        with pytest.raises(ValueError):
            Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard(imbalance_threshold=0.0)

    def test_balanced_flow_no_block(self):
        guard = Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard(
            ema_period=10, imbalance_threshold=200.0, min_warmup_ticks=5
        )
        t0 = time.monotonic()
        # Alternating 50 buys and 50 sells -> EMA oscillates around 0
        for i in range(20):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(volume=50.0, side=side, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_no_block_before_warmup(self):
        guard = Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard(
            ema_period=10, imbalance_threshold=100.0, min_warmup_ticks=10
        )
        t0 = time.monotonic()
        # 5 big buys, but warmup is 10
        for i in range(5):
            guard.update(volume=500.0, side="buy", timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_sustained_imbalance_triggers_block(self):
        guard = Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard(
            ema_period=10, imbalance_threshold=200.0, min_warmup_ticks=5
        )
        t0 = time.monotonic()
        for i in range(15):
            guard.update(volume=300.0, side="buy", timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "EMA_IMBALANCE_BREACH"

    def test_invalid_input_validation(self):
        guard = Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard()
        guard.update(100.0, "invalid_side", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard()
        guard.update(0.0, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
