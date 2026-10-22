"""
tests/test_batch184.py
-----------------------
Unit tests for Batch 184 wave modules:
  - wave134_fractal_dimension_guard            (5 tests)
  - wave135_liquidity_hole_spread_guard        (5 tests)

Baseline before this batch: 2,084 collected items (2,083 passed, 1 skipped)
Expected after: 2,094 collected items (2,093 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave134_fractal_dimension_guard as w134
import wave135_liquidity_hole_spread_guard as w135


# ===========================================================================
# wave134 — Microstructure Sevcik Fractal Dimension Guard (5 tests)
# ===========================================================================

class TestWave134FractalDimensionGuard:

    def setup_method(self):
        w134.reset()

    # -- T1: Natural price path with typical roughness does not block --
    def test_balanced_path_not_blocked(self):
        """Natural random-walk-like price path produces D around 1.3-1.6 and does not block."""
        price = 100.0
        # Walk with moderate variance: up 2, up 1, down 1, up 2, down 2, etc.
        steps = [0.2, 0.1, -0.1, 0.2, -0.2, 0.3, -0.1, 0.2, 0.1, -0.2,
                 0.1, 0.2, -0.1, 0.3, -0.2, 0.2, -0.1, 0.2]
        w134.record_tick(price)
        for s in steps:
            price += s
            w134.record_tick(price)

        d = w134.get_fractal_dimension()
        assert 1.15 <= d <= 1.75
        assert w134.is_entry_blocked() is False
        assert w134.is_blocked() is False

    # -- T2: Monotonic straight-line move collapses D < 1.15 and blocks --
    def test_straight_line_move_blocks(self):
        """Strictly straight-line runaway moves produce D ~= 1.09 < 1.15 and block."""
        price = 100.0
        w134.record_tick(price)
        for _ in range(18):
            price += 1.0  # monotonic upward steps
            w134.record_tick(price)

        d = w134.get_fractal_dimension()
        assert d < 1.15
        assert w134.is_entry_blocked() is True

    # -- T3: Extreme ping-pong noise drives D > 1.75 and blocks --
    def test_ping_pong_noise_blocks(self):
        """Hyper-erratic ping-pong alternating price action expands normalized length and blocks."""
        price = 100.0
        w134.record_tick(price)
        # Alternate price back and forth between 100.0 and 100.5
        for i in range(18):
            price = 100.5 if (i % 2 == 0) else 100.0
            w134.record_tick(price)

        d = w134.get_fractal_dimension()
        assert d > 1.75
        assert w134.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w134.record_tick(True)
        w134.record_tick(float("nan"))
        w134.record_tick(float("inf"))
        w134.record_tick(-50.0)
        w134.record_tick(0.0)

        with w134._lock:
            assert len(w134._prices) == 0

    # -- T5: update() works as alias and reset() clears all state --
    def test_update_alias_and_reset(self):
        """update() alias triggers block on runaway knife; reset() clears block."""
        price = 100.0
        w134.update(price)
        for _ in range(18):
            price += 1.0
            w134.update(price)

        assert w134.is_entry_blocked() is True

        w134.reset()
        assert w134.is_entry_blocked() is False
        assert w134.get_fractal_dimension() == 1.50
        with w134._lock:
            assert len(w134._prices) == 0


# ===========================================================================
# wave135 — Order Book Liquidity Hole & Flash Spread Widening Guard (5 tests)
# ===========================================================================

class TestWave135LiquidityHoleSpreadGuard:

    def setup_method(self):
        w135.reset()

    # -- T1: Normal tight spread does not block --
    def test_tight_spread_not_blocked(self):
        """Normal steady bid-ask spread maintains low ratio and does not block."""
        for _ in range(20):
            w135.record_quote(1.0000, 1.0002)  # spread = 0.0002 (2 pips)

        assert w135.get_current_spread_ratio() < 2.0
        assert w135.is_entry_blocked() is False
        assert w135.is_blocked() is False

    # -- T2: Sudden spread blowout triggers protective block --
    def test_spread_blowout_blocks(self):
        """Spread widening by 4x median triggers liquidity hole block."""
        # Establish median spread of 0.0002 across 20 quotes
        for _ in range(20):
            w135.record_quote(1.0000, 1.0002)

        # Sudden blowout: ask jumps to 1.0010 (spread = 0.0010 = 5x median)
        w135.record_quote(1.0000, 1.0010)

        assert w135.get_current_spread_ratio() >= 3.5
        assert w135.is_entry_blocked() is True

    # -- T3: Absolute spread exceeding ABSOLUTE_MAX_SPREAD blocks --
    def test_absolute_max_spread_blocks(self):
        """Spread >= 0.0050 triggers block even if median is high."""
        for _ in range(20):
            w135.record_quote(1.0000, 1.0020)

        # Huge spread = 0.0060 >= 0.0050
        w135.record_quote(1.0000, 1.0060)

        assert w135.is_entry_blocked() is True

    # -- T4: Crossed quotes or invalid numbers safely rejected --
    def test_invalid_and_crossed_quotes_rejected(self):
        """ask <= bid or invalid float values ignored."""
        w135.record_quote(1.0005, 1.0000)  # crossed: ask < bid
        w135.record_quote(1.0000, 1.0000)  # locked: ask == bid
        w135.record_quote(True, 1.0002)
        w135.record_quote(1.0000, False)
        w135.record_quote(float("nan"), 1.0002)
        w135.record_quote(1.0000, float("inf"))

        with w135._lock:
            assert len(w135._spreads) == 0

    # -- T5: update() alias works and reset() clears all state --
    def test_update_alias_and_reset(self):
        """update() processes quotes; reset() clears spread history and unblocks."""
        for _ in range(20):
            w135.update(1.0000, 1.0002)
        w135.update(1.0000, 1.0010)
        assert w135.is_entry_blocked() is True

        w135.reset()
        assert w135.is_entry_blocked() is False
        assert w135.get_current_spread_ratio() == 1.0
        with w135._lock:
            assert len(w135._spreads) == 0
            assert w135._blocked_until == 0.0
