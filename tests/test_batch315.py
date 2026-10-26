"""
Batch 315 -- Tests for Wave 388 and Wave 389
=============================================
Wave 388: LOB Depth-Weighted Spread Guard
Wave 389: Trade Flow Correlated Volume Spike Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave388_lob_depth_weighted_spread_guard import (
    Wave388LOBDepthWeightedSpreadGuard,
)
from wave389_trade_flow_correlated_volume_spike_guard import (
    Wave389TradeFlowCorrelatedVolumeSpikeGuard,
)


class TestWave388DepthWeightedSpread:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave388LOBDepthWeightedSpreadGuard(window_size=1)
        with pytest.raises(ValueError):
            Wave388LOBDepthWeightedSpreadGuard(dws_threshold_bps=-1.0)

    def test_balanced_tight_spread_no_block(self):
        guard = Wave388LOBDepthWeightedSpreadGuard(window_size=10, dws_threshold_bps=3.0)
        t0 = time.monotonic()
        # Tight spread 1 pip (0.91 bps) and balanced depths (imbalance 0.0) -> DWS = 0.91 bps < 3.0 bps
        for i in range(15):
            guard.update(bid=1.1000, ask=1.1001, bid_depth=100.0, ask_depth=100.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_no_block_before_window_fills(self):
        guard = Wave388LOBDepthWeightedSpreadGuard(window_size=10, dws_threshold_bps=2.0)
        t0 = time.monotonic()
        # High DWS, but only 5 ticks
        for i in range(5):
            guard.update(bid=1.1000, ask=1.1010, bid_depth=1000.0, ask_depth=10.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_severe_imbalance_and_wide_spread_triggers_block(self):
        guard = Wave388LOBDepthWeightedSpreadGuard(window_size=10, dws_threshold_bps=4.0)
        t0 = time.monotonic()
        # Spread 3 bps, extreme imbalance (bid 1000 vs ask 10 -> imbalance ~0.98 -> 1 + imb^2 ~ 1.96 -> DWS ~ 5.88 bps)
        for i in range(15):
            guard.update(bid=1.1000, ask=1.10033, bid_depth=1000.0, ask_depth=10.0, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "DWS_BREACH"

    def test_invalid_input_validation(self):
        guard = Wave388LOBDepthWeightedSpreadGuard()
        guard.update(1.1005, 1.1000, 100.0, 100.0, 1.0)  # crossed
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(1.1000, 1.1005, -10.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave388LOBDepthWeightedSpreadGuard()
        guard.update(0.0, 1.1005, 100.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave389CorrelatedVolumeSpike:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave389TradeFlowCorrelatedVolumeSpikeGuard(spike_volume_threshold=0.0)
        with pytest.raises(ValueError):
            Wave389TradeFlowCorrelatedVolumeSpikeGuard(max_consecutive_spikes=1)

    def test_normal_intermittent_spikes_no_block(self):
        guard = Wave389TradeFlowCorrelatedVolumeSpikeGuard(
            spike_volume_threshold=100.0, max_consecutive_spikes=4
        )
        t0 = time.monotonic()
        # Spikes separated by normal trades
        for i in range(10):
            guard.update(volume=150.0, side="buy", timestamp=t0 + i * 2)
            guard.update(volume=20.0, side="buy", timestamp=t0 + i * 2 + 1)
        assert not guard.is_blocked()

    def test_sub_threshold_trade_resets_streak(self):
        guard = Wave389TradeFlowCorrelatedVolumeSpikeGuard(
            spike_volume_threshold=100.0, max_consecutive_spikes=4
        )
        t0 = time.monotonic()
        # 3 spikes, then 1 small trade, then 3 spikes
        for i in range(3):
            guard.update(150.0, "buy", t0 + i)
        guard.update(10.0, "buy", t0 + 3)  # resets
        for i in range(3):
            guard.update(150.0, "buy", t0 + 4 + i)
        assert not guard.is_blocked()

    def test_consecutive_volume_spikes_trigger_block(self):
        guard = Wave389TradeFlowCorrelatedVolumeSpikeGuard(
            spike_volume_threshold=100.0, max_consecutive_spikes=4
        )
        t0 = time.monotonic()
        for i in range(5):
            guard.update(volume=150.0, side="buy", timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "CORRELATED_VOLUME_SPIKE"

    def test_invalid_input_validation(self):
        guard = Wave389TradeFlowCorrelatedVolumeSpikeGuard()
        guard.update(100.0, "invalid_side", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave389TradeFlowCorrelatedVolumeSpikeGuard()
        guard.update(-10.0, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
