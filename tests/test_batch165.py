"""
tests/test_batch165.py
-----------------------
Unit tests for Batch 165 wave modules:
  - wave96_drawdown_velocity_guard  (5 tests)
  - wave97_correlation_risk_guard   (5 tests)

Baseline before this batch: 1,893 passed, 1 skipped
Expected after: 1,903 passed, 1 skipped
"""

import math
import time
import threading
import importlib
import sys
import os

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave96_drawdown_velocity_guard as w96
import wave97_correlation_risk_guard as w97


# ===========================================================================
# wave96 — Drawdown Velocity Guard (5 tests)
# ===========================================================================

class TestWave96DrawdownVelocityGuard:

    def setup_method(self):
        w96.reset()

    # -- T1: Not blocked before warmup (fewer than MIN_SAMPLES) --
    def test_not_blocked_before_warmup(self):
        """With fewer than MIN_SAMPLES snapshots, guard must not block."""
        # Feed only MIN_SAMPLES - 1 updates (all showing rapid drop)
        for i in range(w96.MIN_SAMPLES - 1):
            w96.update(10000.0 - i * 1000.0)
        assert w96.is_entry_blocked() is False

    # -- T2: Blocked when equity drops faster than threshold --
    def test_blocked_on_rapid_drawdown(self):
        """Guard must block when equity drops > MAX_VELOCITY_USD_PER_SEC."""
        # Simulate: equity drops $100 over ~1 second (>> 0.5 USD/s threshold)
        base_time = time.monotonic()
        # Monkey-patch time.monotonic to inject controlled timestamps
        snapshots_injected = []

        def fake_monotonic():
            if not snapshots_injected:
                return base_time
            return base_time + len(snapshots_injected) * 0.1

        original_monotonic = time.monotonic
        time.monotonic = fake_monotonic
        try:
            # 5 samples: equity drops from 10000 to 9940 over 0.4 seconds
            equities = [10000.0, 9990.0, 9970.0, 9950.0, 9940.0]
            for eq in equities:
                snapshots_injected.append(1)
                w96.update(eq)
        finally:
            time.monotonic = original_monotonic

        # Restore real monotonic; block deadline set to real future time
        assert w96.is_entry_blocked() is True

    # -- T3: Not blocked when drawdown is gradual (below threshold) --
    def test_not_blocked_on_slow_drawdown(self):
        """A very slow equity decline must not trigger the block."""
        w96.reset()
        # Simulate 5 USD drop over 60 seconds window — velocity = 5/60 = 0.083 USD/s
        # Well below MAX_VELOCITY_USD_PER_SEC = 0.5
        # We use real monotonic but ensure WINDOW_SECONDS elapses by
        # directly manipulating the internal deque
        now = time.monotonic()
        with w96._lock:
            w96._snapshots.clear()
            # oldest snapshot 60s ago with equity 10000
            w96._snapshots.append((now - 60.0, 10000.0))
            # latest snapshot now with equity 9995 (only $5 drop / 60s)
            w96._snapshots.append((now - 0.1, 9995.0))
            w96._snapshots.append((now, 9995.0))
        # Manually trigger velocity check via update with same equity
        w96.update(9995.0)
        assert w96.is_entry_blocked() is False

    # -- T4: Invalid inputs are silently ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, strings must be silently rejected."""
        w96.update(True)
        w96.update(False)
        w96.update(float("nan"))
        w96.update(float("inf"))
        w96.update(float("-inf"))
        w96.update("10000")   # type: ignore
        w96.update(None)      # type: ignore
        assert w96.is_entry_blocked() is False

    # -- T5: reset() clears block and snapshots --
    def test_reset_clears_state(self):
        """After reset(), guard must report not blocked regardless of prior state."""
        # Force a block by directly setting internal state
        with w96._lock:
            w96._blocked_until = time.monotonic() + 999.0
        assert w96.is_entry_blocked() is True
        w96.reset()
        assert w96.is_entry_blocked() is False
        with w96._lock:
            assert len(w96._snapshots) == 0


# ===========================================================================
# wave97 — Correlation Risk Guard (5 tests)
# ===========================================================================

class TestWave97CorrelationRiskGuard:

    def setup_method(self):
        w97.reset()

    # -- T1: Not blocked with insufficient data (below MIN_SAMPLES) --
    def test_not_blocked_before_warmup(self):
        """With fewer than MIN_SAMPLES return samples, must not block."""
        # Feed only MIN_SAMPLES - 1 price pairs (need MIN_SAMPLES returns,
        # so MIN_SAMPLES price changes = MIN_SAMPLES+1 prices)
        for i in range(w97.MIN_SAMPLES):  # produces MIN_SAMPLES-1 returns each
            w97.update(1.1000 + i * 0.0001, 1.3000 + i * 0.0001)
        # Only MIN_SAMPLES-1 returns per series; if below threshold → no block
        assert w97.is_entry_blocked() is False

    # -- T2: Blocked when series are perfectly positively correlated --
    def test_blocked_on_high_positive_correlation(self):
        """Perfectly correlated series (r=1.0) must trigger a block."""
        # Feed WINDOW_SIZE+1 prices for each: both move up by same % each tick
        base_a = 1.1000
        base_b = 1.3000
        for i in range(w97.WINDOW_SIZE + 1):
            # Both increase by 0.1% each step — perfectly correlated
            pa = base_a * (1 + 0.001 * i)
            pb = base_b * (1 + 0.001 * i)
            w97.update(pa, pb)
        assert w97.is_entry_blocked() is True

    # -- T3: Not blocked when series are anti-correlated (r = -1) below threshold --
    def test_blocked_on_high_negative_correlation(self):
        """Perfectly anti-correlated series (r=-1.0) must also block (abs check)."""
        base_a = 1.1000
        base_b = 1.3000
        for i in range(w97.WINDOW_SIZE + 1):
            pa = base_a * (1 + 0.001 * i)
            # B moves exactly opposite direction to A
            pb = base_b * (1 - 0.001 * i)
            w97.update(pa, pb)
        assert w97.is_entry_blocked() is True

    # -- T4: Invalid inputs are silently ignored --
    def test_invalid_inputs_ignored(self):
        """Boolean, NaN, Inf, zero, negative prices must be rejected silently."""
        w97.update_a(True)
        w97.update_b(False)
        w97.update_a(float("nan"))
        w97.update_b(float("inf"))
        w97.update_a(-1.0)    # negative price
        w97.update_b(0.0)     # zero price
        w97.update("1.1", "1.3")  # type: ignore
        assert w97.is_entry_blocked() is False

    # -- T5: reset() clears all state and block --
    def test_reset_clears_state(self):
        """After reset(), guard must be unblocked and all price history cleared."""
        # Force an artificial block
        with w97._lock:
            w97._blocked_until = time.monotonic() + 999.0
        assert w97.is_entry_blocked() is True
        w97.reset()
        assert w97.is_entry_blocked() is False
        with w97._lock:
            assert len(w97._prices_a) == 0
            assert len(w97._prices_b) == 0
