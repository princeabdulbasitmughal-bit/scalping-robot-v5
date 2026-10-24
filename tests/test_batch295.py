"""
Test Suite Batch 295 -- Wave 349: Trade Flow Signed Volume Clustering Dispersion Guard
"""

import time
import pytest
from wave349_trade_flow_signed_volume_clustering_dispersion_guard import Wave349TradeFlowSignedVolumeClusteringDispersionGuard


class TestWave349SignedVolumeClusteringDispersionGuard:
    """Comprehensive test suite for Wave 349: Signed Volume Clustering Dispersion Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            window_size=8,
            dispersion_ratio_threshold=2.0,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave349TradeFlowSignedVolumeClusteringDispersionGuard(**defaults)

    def test_wave349_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave349TradeFlowSignedVolumeClusteringDispersionGuard(window_size=4)
        with pytest.raises(ValueError):
            Wave349TradeFlowSignedVolumeClusteringDispersionGuard(dispersion_ratio_threshold=0.0)

    def test_wave349_no_block_before_window_fills(self):
        """Guard should not block before window_size trades accumulate."""
        guard = self._make_guard(window_size=8)
        t0 = time.monotonic()
        for i in range(5):
            guard.update("buy", 10.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 1.0)

    def test_wave349_balanced_uniform_flow_no_block(self):
        """Uniform balanced flow (equal buy/sell) has dispersion ratio ~ 1.0 and must not block."""
        guard = self._make_guard(window_size=8, dispersion_ratio_threshold=2.0)
        t0 = time.monotonic()
        # Alternating +10, -10: Var(SV)=100, Mean(|SV|)=10 -> ratio = 100 / 100 = 1.0 < 2.0
        for i in range(15):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(side, 10.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 2.0)

    def test_wave349_bursty_clustering_dispersion_triggers_block(self):
        """Predatory clumped block sizes with extreme variance trigger SIGNED_VOLUME_CLUSTERING_DISPERSION."""
        guard = self._make_guard(window_size=8, dispersion_ratio_threshold=2.5)
        t0 = time.monotonic()
        # 6 tiny trades of 1 lot, then 2 massive 100 lot buys: Var is huge compared to Mean(|SV|)^2
        ts = t0
        for i in range(6):
            ts += 0.1
            guard.update("buy" if i % 2 == 0 else "sell", 1.0, ts)

        # Extreme predatory block clump
        ts += 0.1
        guard.update("buy", 100.0, ts)
        ts += 0.1
        guard.update("buy", 100.0, ts)

        assert guard.is_blocked(ts + 0.05)
        assert guard.last_reason == "SIGNED_VOLUME_CLUSTERING_DISPERSION"

    def test_wave349_invalid_side_blocks(self):
        """Invalid order side string must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update("hold", 10.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave349_non_positive_volume_blocks(self):
        """Non-positive volume must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update("buy", -5.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave349_bool_inputs_block(self):
        """Boolean inputs must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update("buy", True, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave349_reset_clears_state(self):
        """Reset must unblock the guard and clear history."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update("hold", 10.0, t0)
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""

    def test_wave349_is_entry_blocked_delegation(self):
        """is_entry_blocked delegates to is_blocked with timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update("hold", 10.0, t0)
        assert guard.is_entry_blocked(2400.0, 2400.20, t0 + 0.1)

    def test_wave349_abbreviated_side_strings(self):
        """Abbreviated side strings ('b' and 's') are parsed correctly."""
        guard = self._make_guard(window_size=6)
        t0 = time.monotonic()
        guard.update("b", 10.0, t0)
        guard.update("s", 10.0, t0 + 0.1)
        assert len(guard._signed_volumes) == 2
        assert guard._signed_volumes[0] == 10.0
        assert guard._signed_volumes[1] == -10.0
