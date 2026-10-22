"""
tests/test_batch188.py
-----------------------
Unit tests for Batch 188 wave modules:
  - wave142_order_book_slope_guard             (5 tests)
  - wave143_directional_volatility_ratio_guard (5 tests)

Baseline before this batch: 2,124 collected items (2,123 passed, 1 skipped)
Expected after: 2,134 collected items (2,133 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave142_order_book_slope_guard as w142
import wave143_directional_volatility_ratio_guard as w143


# ===========================================================================
# wave142 — Order Book Liquidity Slope Guard (5 tests)
# ===========================================================================

class TestWave142OrderBookSlopeGuard:

    def setup_method(self):
        w142.reset()

    # -- T1: Deep resilient order book produces flat slope and does not block --
    def test_resilient_book_not_blocked(self):
        """Tight spread (0.0001) with thick depth (10.0 lots) yields slope 0.00001 < 0.0010."""
        w142.record_depth(1.0000, 1.0001, 5.0, 5.0)

        assert w142.get_current_slope() < 0.0005
        assert w142.is_entry_blocked() is False
        assert w142.is_blocked() is False

    # -- T2: Hollow book with wide spread and depleted depth triggers slope block --
    def test_hollow_book_blocks(self):
        """Spread = 0.0008 with thin depth (0.5 lots) yields slope = 0.0016 >= 0.0010 and blocks."""
        w142.record_depth(1.0000, 1.0008, 0.25, 0.25)

        assert w142.get_current_slope() >= 0.0010
        assert w142.is_entry_blocked() is True

    # -- T3: update() alias works identically and records slope --
    def test_update_alias(self):
        """update() correctly evaluates depth slope and triggers block on thin book."""
        w142.update(1.0000, 1.0010, 0.2, 0.3)  # spread = 0.0010, depth = 0.5 -> slope = 0.0020

        assert w142.get_current_slope() >= 0.0010
        assert w142.is_entry_blocked() is True

    # -- T4: Crossed quotes or invalid numbers safely ignored --
    def test_invalid_and_crossed_quotes_ignored(self):
        """ask <= bid or invalid numbers do not corrupt state."""
        w142.record_depth(1.0005, 1.0000, 5.0, 5.0)  # crossed: ask < bid
        w142.record_depth(1.0000, 1.0000, 5.0, 5.0)  # locked: ask == bid
        w142.record_depth(True, 1.0001, 5.0, 5.0)
        w142.record_depth(1.0000, False, 5.0, 5.0)
        w142.record_depth(float("nan"), 1.0001, 5.0, 5.0)
        w142.record_depth(1.0000, 1.0001, float("inf"), 5.0)
        w142.record_depth(1.0000, 1.0001, -1.0, 5.0)

        assert w142.get_current_slope() == 0.00005

    # -- T5: reset() restores default slope and unblocks --
    def test_reset_clears_state(self):
        """reset() restores default slope (0.00005) and clears active block."""
        w142.record_depth(1.0000, 1.0008, 0.25, 0.25)
        assert w142.is_entry_blocked() is True

        w142.reset()
        assert w142.is_entry_blocked() is False
        assert w142.get_current_slope() == 0.00005
        with w142._lock:
            assert w142._blocked_until == 0.0


# ===========================================================================
# wave143 — Directional Semi-Variance Volatility Asymmetry Guard (5 tests)
# ===========================================================================

class TestWave143DirectionalVolatilityRatioGuard:

    def setup_method(self):
        w143.reset()

    # -- T1: Balanced two-way returns produce low asymmetry ratio and do not block --
    def test_balanced_variance_not_blocked(self):
        """Symmetric up and down returns yield ratio ~ 1.0 and do not block."""
        price = 100.0
        w143.record_tick(price)
        for i in range(20):
            delta = 0.15 if (i % 2 == 0) else -0.15
            price += delta
            w143.record_tick(price)

        ratio = w143.get_volatility_asymmetry_ratio()
        assert ratio < 2.0
        assert w143.is_entry_blocked() is False
        assert w143.is_blocked() is False

    # -- T2: Downside liquidation cascade drives ratio >= 4.0 and blocks --
    def test_downside_cascade_blocks(self):
        """Heavy downside moves relative to tiny upward steps drive ratio >= 4.0 and block."""
        price = 100.0
        w143.record_tick(price)
        # 16 ticks: 8 tiny upticks (+0.02) and 8 heavy downticks (-0.20)
        # Downside variance is (0.20/0.02)^2 = 100x higher!
        for _ in range(8):
            price += 0.02
            w143.record_tick(price)
            price -= 0.20
            w143.record_tick(price)

        ratio = w143.get_volatility_asymmetry_ratio()
        assert ratio >= 4.0
        assert w143.is_entry_blocked() is True

    # -- T3: Upside short squeeze drives ratio >= 4.0 and blocks --
    def test_upside_squeeze_blocks(self):
        """Heavy upside jumps relative to tiny downward steps drive ratio >= 4.0 and block."""
        price = 100.0
        w143.record_tick(price)
        for _ in range(8):
            price -= 0.02
            w143.record_tick(price)
            price += 0.20
            w143.record_tick(price)

        ratio = w143.get_volatility_asymmetry_ratio()
        assert ratio >= 4.0
        assert w143.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w143.record_tick(True)
        w143.record_tick(float("nan"))
        w143.record_tick(float("inf"))
        w143.record_tick(-50.0)
        w143.record_tick(0.0)

        with w143._lock:
            assert w143._prev_price is None
            assert len(w143._returns) == 0

    # -- T5: update() alias works and reset() clears all state --
    def test_update_alias_and_reset(self):
        """update() evaluates asymmetry correctly; reset() restores default ratio (1.0)."""
        price = 100.0
        w143.update(price)
        for _ in range(8):
            price += 0.02
            w143.update(price)
            price -= 0.20
            w143.update(price)

        assert w143.is_entry_blocked() is True

        w143.reset()
        assert w143.is_entry_blocked() is False
        assert w143.get_volatility_asymmetry_ratio() == 1.0
        with w143._lock:
            assert w143._prev_price is None
            assert len(w143._returns) == 0
            assert w143._blocked_until == 0.0
