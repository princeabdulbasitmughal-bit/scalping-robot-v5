"""
Batch 314 -- Tests for Wave 386 and Wave 387
=============================================
Wave 386: LOB Spread Convergence Trap Guard
Wave 387: Trade Flow Intraday Volume Profile Deviation Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave386_lob_spread_convergence_trap_guard import (
    Wave386LOBSpreadConvergenceTrapGuard,
)
from wave387_trade_flow_intraday_volume_profile_deviation_guard import (
    Wave387TradeFlowIntradayVolumeProfileDeviationGuard,
)


class TestWave386SpreadConvergenceTrap:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave386LOBSpreadConvergenceTrapGuard(compress_ticks=1)
        with pytest.raises(ValueError):
            Wave386LOBSpreadConvergenceTrapGuard(explosion_multiple=0.8)

    def test_stable_spread_no_block(self):
        guard = Wave386LOBSpreadConvergenceTrapGuard(compress_ticks=3, explosion_multiple=2.5)
        t0 = time.monotonic()
        for i in range(20):
            guard.update(bid=1.1000, ask=1.1002, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_compression_without_explosion_no_block(self):
        guard = Wave386LOBSpreadConvergenceTrapGuard(compress_ticks=3, explosion_multiple=2.5)
        t0 = time.monotonic()
        # Compress from 5 pips to 1 pip gradually
        spreads = [0.0005, 0.0004, 0.0003, 0.0002, 0.0001]
        for i, s in enumerate(spreads):
            guard.update(bid=1.1000, ask=1.1000 + s, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_convergence_trap_triggers_block(self):
        guard = Wave386LOBSpreadConvergenceTrapGuard(compress_ticks=3, explosion_multiple=2.5)
        t0 = time.monotonic()
        # Compress for 3 ticks: 0.0004 -> 0.0003 -> 0.0002 -> 0.0001
        guard.update(bid=1.1000, ask=1.1004, timestamp=t0 + 0)
        guard.update(bid=1.1000, ask=1.1003, timestamp=t0 + 1)
        guard.update(bid=1.1000, ask=1.1002, timestamp=t0 + 2)
        guard.update(bid=1.1000, ask=1.1001, timestamp=t0 + 3)
        # Explode to 0.0005 (> 2.5 * 0.0001 = 0.00025)
        guard.update(bid=1.1000, ask=1.1005, timestamp=t0 + 4)
        assert guard.is_blocked()
        assert guard.last_reason == "SPREAD_TRAP_DETECTED"

    def test_invalid_input_validation(self):
        guard = Wave386LOBSpreadConvergenceTrapGuard()
        guard.update(1.1005, 1.1000, 1.0)  # crossed
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, 1.1005, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave386LOBSpreadConvergenceTrapGuard()
        guard.update(0.0, 1.1005, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave387IntradayVolumeProfile:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave387TradeFlowIntradayVolumeProfileDeviationGuard(slot_seconds=-10.0)
        with pytest.raises(ValueError):
            Wave387TradeFlowIntradayVolumeProfileDeviationGuard(min_history_slots=1)

    def test_no_block_with_insufficient_history(self):
        guard = Wave387TradeFlowIntradayVolumeProfileDeviationGuard(
            slot_seconds=60.0, day_seconds=86400.0, min_history_slots=3
        )
        # Only day 0 and day 1 history
        guard.update(volume=100.0, timestamp=10.0)
        guard.update(volume=100.0, timestamp=86410.0)
        assert not guard.is_blocked()

    def test_normal_intraday_volume_no_block(self):
        guard = Wave387TradeFlowIntradayVolumeProfileDeviationGuard(
            slot_seconds=60.0, day_seconds=86400.0, min_history_slots=3, z_threshold=3.0
        )
        # 3 historical days with 100.0 volume in slot 0 (0-60s)
        # Day 1
        guard.update(volume=95.0, timestamp=10.0)
        guard.update(volume=5.0, timestamp=20.0)
        # Advance to slot 1 to close slot 0
        guard.update(volume=10.0, timestamp=70.0)

        # Day 2
        guard.update(volume=100.0, timestamp=86400.0 + 10.0)
        guard.update(volume=10.0, timestamp=86400.0 + 70.0)

        # Day 3
        guard.update(volume=105.0, timestamp=86400.0 * 2 + 10.0)
        guard.update(volume=10.0, timestamp=86400.0 * 2 + 70.0)

        # Day 4: typical volume 100 in slot 0 -> no anomaly
        guard.update(volume=102.0, timestamp=86400.0 * 3 + 10.0)
        assert not guard.is_blocked()

    def test_anomalous_volume_surge_triggers_block(self):
        guard = Wave387TradeFlowIntradayVolumeProfileDeviationGuard(
            slot_seconds=60.0, day_seconds=86400.0, min_history_slots=3, z_threshold=2.5
        )
        # Day 1: 100
        guard.update(volume=100.0, timestamp=10.0)
        guard.update(volume=10.0, timestamp=70.0)

        # Day 2: 102
        guard.update(volume=102.0, timestamp=86400.0 + 10.0)
        guard.update(volume=10.0, timestamp=86400.0 + 70.0)

        # Day 3: 98
        guard.update(volume=98.0, timestamp=86400.0 * 2 + 10.0)
        guard.update(volume=10.0, timestamp=86400.0 * 2 + 70.0)

        # Day 4: Massive surge to 1000 in slot 0 -> z-score >> 2.5
        guard.update(volume=1000.0, timestamp=86400.0 * 3 + 10.0)
        assert guard.is_blocked()
        assert guard.last_reason == "VOLUME_PROFILE_ANOMALY"

    def test_invalid_input_validation(self):
        guard = Wave387TradeFlowIntradayVolumeProfileDeviationGuard()
        guard.update(-10.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave387TradeFlowIntradayVolumeProfileDeviationGuard()
        guard.update(0.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
