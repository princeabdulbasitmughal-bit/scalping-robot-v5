"""
Batch 285 — Tests for Wave 336 and Wave 337
============================================
Wave 336: LOB Order-Flow Toxicity VPIN Guard
Wave 337: Trade Flow Cross-Asset Correlation Breakdown Guard

Target: 10 new tests, 0 failures
Baseline before: 3,093 passed, 1 skipped
Baseline after:  3,103 passed, 1 skipped
"""

import time
import pytest

from wave336_lob_order_flow_toxicity_vpin_guard import (
    Wave336LOBOrderFlowToxicityVPINGuard,
)
from wave337_trade_flow_cross_asset_correlation_breakdown_guard import (
    Wave337TradeFlowCrossAssetCorrelationBreakdownGuard,
)


# ─────────────────────────────────────────────────────────────
# Wave 336 — VPIN Guard Tests
# ─────────────────────────────────────────────────────────────


class TestWave336VPINGuard:
    """Tests for the VPIN order-flow toxicity guard."""

    def _make_guard(self, **kw):
        defaults = dict(
            bucket_volume=10.0,
            n_buckets=5,
            vpin_threshold=0.60,
            primary_spread_threshold_bps=1.5,
            cooldown_seconds=60.0,
        )
        defaults.update(kw)
        return Wave336LOBOrderFlowToxicityVPINGuard(**defaults)

    def test_wave336_no_block_before_buckets_fill(self):
        """Guard must not block before n_buckets complete."""
        guard = self._make_guard()
        t0 = time.monotonic()
        # Send only 4 complete buckets worth of data (< n_buckets=5)
        for i in range(4):
            guard.update(1.1000, 1.10011, 10.0, "buy", t0 + i)
        assert not guard.is_blocked(t0 + 4), "Should not block before window fills"

    def test_wave336_balanced_flow_no_block(self):
        """Balanced buy/sell flow yields low VPIN; should not block."""
        guard = self._make_guard(vpin_threshold=0.60)
        t0 = time.monotonic()
        # Alternate buy/sell evenly: tau ~ 0 for each bucket
        for i in range(20):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(1.1000, 1.10011, 5.0, side, t0 + i)
        assert not guard.is_blocked(t0 + 20), "Balanced flow should not trigger VPIN"

    def test_wave336_toxic_flow_triggers_block(self):
        """Heavily one-sided buy flow should trigger VPIN block."""
        guard = self._make_guard(vpin_threshold=0.60, primary_spread_threshold_bps=1.5)
        t0 = time.monotonic()
        # All buys → tau = 1.0 for every bucket → VPIN = 1.0 >= 0.60
        for i in range(15):
            guard.update(1.1000, 1.10020, 10.0, "buy", t0 + i)
        assert guard.is_blocked(t0 + 15), "All-buy flow should trigger VPIN block"
        assert guard.last_reason == "VPIN_TOXICITY_BREACH"

    def test_wave336_toxic_flow_narrow_spread_no_block(self):
        """Toxic VPIN alone does not block if spread is below threshold."""
        guard = self._make_guard(
            vpin_threshold=0.60,
            primary_spread_threshold_bps=5.0,  # high threshold
        )
        t0 = time.monotonic()
        # Spread ~ 1.0 bps → below 5.0 bps threshold
        for i in range(15):
            guard.update(1.1000, 1.10011, 10.0, "buy", t0 + i)
        # VPIN is high but spread is only ~1 bps < 5 bps threshold
        assert not guard.is_blocked(t0 + 15), "Low spread should prevent VPIN block"

    def test_wave336_invalid_side_blocks(self):
        """Invalid trade side must trigger INPUT_VALIDATION_ERROR block."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(1.1000, 1.10011, 10.0, "MARKET", t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave336_negative_volume_blocks(self):
        """Non-positive volume must trigger INPUT_VALIDATION_ERROR block."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(1.1000, 1.10011, -1.0, "buy", t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave336_reset_clears_state(self):
        """Reset must clear all accumulated state."""
        guard = self._make_guard()
        t0 = time.monotonic()
        for i in range(15):
            guard.update(1.1000, 1.10020, 10.0, "buy", t0 + i)
        assert guard.is_blocked(t0 + 15)
        guard.reset()
        assert not guard.is_blocked(t0 + 15), "After reset, guard should be unblocked"
        assert guard.last_reason == ""

    def test_wave336_is_entry_blocked_delegates(self):
        """is_entry_blocked must delegate to is_blocked."""
        guard = self._make_guard()
        t0 = time.monotonic()
        for i in range(15):
            guard.update(1.1000, 1.10020, 10.0, "buy", t0 + i)
        assert guard.is_entry_blocked(1.1000, 1.10020, t0 + 15) == guard.is_blocked(t0 + 15)


# ─────────────────────────────────────────────────────────────
# Wave 337 — Cross-Asset Correlation Breakdown Guard Tests
# ─────────────────────────────────────────────────────────────


class TestWave337CrossAssetCorrelationGuard:
    """Tests for cross-asset correlation breakdown guard."""

    def _make_guard(self, **kw):
        defaults = dict(
            window_size=10,
            decorrelation_threshold=0.30,
            cooldown_seconds=60.0,
        )
        defaults.update(kw)
        return Wave337TradeFlowCrossAssetCorrelationBreakdownGuard(**defaults)

    def test_wave337_no_block_before_window_fills(self):
        """Guard must not block before window_size observations collected."""
        guard = self._make_guard(window_size=10)
        t0 = time.monotonic()
        for i in range(9):
            guard.update(float(i), float(i), t0 + i)
        assert not guard.is_blocked(t0 + 9), "Should not block before window fills"

    def test_wave337_correlated_streams_no_block(self):
        """Perfectly correlated streams (r=1) should not trigger block."""
        guard = self._make_guard(decorrelation_threshold=0.30)
        t0 = time.monotonic()
        import math
        for i in range(20):
            v = math.sin(i * 0.5) * 100
            guard.update(v, v, t0 + i)
        assert not guard.is_blocked(t0 + 20), "r=1 should not trigger decorrelation block"

    def test_wave337_decorrelated_streams_triggers_block(self):
        """Uncorrelated random-like streams should trigger correlation block."""
        guard = self._make_guard(decorrelation_threshold=0.30)
        t0 = time.monotonic()
        # x has slight variation (avoids zero-variance path), y alternates sign
        # → Pearson r ~ 0 because alternating y is orthogonal to slowly drifting x
        xs = [10.0 + 0.01 * i for i in range(20)]   # tiny upward drift
        ys = [5.0 if i % 2 == 0 else -5.0 for i in range(20)]  # alternating
        for i, (x, y) in enumerate(zip(xs, ys)):
            guard.update(x, y, t0 + i)
        # Both streams have non-zero variance; alternating y vs monotone x → |r| near 0
        assert guard.is_blocked(t0 + 20), "Near-zero |r| should trigger decorrelation block"
        assert guard.last_reason == "CROSS_ASSET_DECORRELATION"

    def test_wave337_zero_variance_blocks(self):
        """Constant stream with zero variance should trigger INSUFFICIENT_VARIANCE."""
        guard = self._make_guard()
        t0 = time.monotonic()
        for i in range(12):
            guard.update(0.0, 0.0, t0 + i)
        assert guard.is_blocked(t0 + 12)
        assert guard.last_reason == "INSUFFICIENT_VARIANCE"

    def test_wave337_bool_input_validation_error(self):
        """Boolean x_volume must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, 5.0, t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave337_reset_clears_state(self):
        """Reset must clear all accumulated observations."""
        guard = self._make_guard()
        t0 = time.monotonic()
        for i in range(12):
            guard.update(0.0, 0.0, t0 + i)
        assert guard.is_blocked(t0 + 12)
        guard.reset()
        assert not guard.is_blocked(t0 + 12), "After reset, guard should be unblocked"
        assert guard.last_reason == ""

    def test_wave337_negative_correlation_does_not_block(self):
        """Streams with |r|=1 (anti-correlated) should NOT block (|r| >= threshold)."""
        guard = self._make_guard(decorrelation_threshold=0.30)
        t0 = time.monotonic()
        # x = i, y = -i → perfect anti-correlation, |r|=1 >= 0.30
        for i in range(15):
            guard.update(float(i + 1), float(-(i + 1)), t0 + i)
        assert not guard.is_blocked(t0 + 15), "Anti-correlated (|r|=1) should not block"
