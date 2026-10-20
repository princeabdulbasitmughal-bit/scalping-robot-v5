"""
tests/test_batch152.py
-----------------------
10 unit tests for Batch 152 wave modules:
  • wave70_candle_size_guard    (5 tests)
  • wave71_bid_ask_skew_guard   (5 tests)

All tests are deterministic, use fresh class instances, and are
independent of global module singletons.
"""

import sys
import os
import math
import time as _time

import pytest

# ── ensure project root is importable ──────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from wave70_candle_size_guard import CandleSizeGuard
from wave71_bid_ask_skew_guard import BidAskSkewGuard


# ════════════════════════════════════════════════════════════════════════════
# wave70 — CandleSizeGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestCandleSizeGuard:

    def test_not_blocked_during_warmup(self):
        """Gate stays open before min_candles threshold is reached."""
        g = CandleSizeGuard(
            spike_multiplier=2.0, ema_period=5,
            min_candles=10, cooldown_seconds=60.0, pip_size=0.1
        )
        # Feed 9 giant candles — still in warmup, must not block
        for _ in range(9):
            g.update(1800.0, 1850.0)   # 500 pip candle
        assert g.is_entry_blocked() is False

    def test_not_blocked_with_normal_candles(self):
        """Gate stays open when candles are within the normal size range."""
        g = CandleSizeGuard(
            spike_multiplier=3.0, ema_period=5,
            min_candles=5, cooldown_seconds=60.0, pip_size=0.1
        )
        # Feed 10 identical 10-pip candles → EMA = 10 pips; 10 < 3×10
        for _ in range(10):
            g.update(1800.0, 1801.0)   # 10-pip candle
        assert g.is_entry_blocked() is False

    def test_blocked_on_spike_candle(self):
        """Gate closes when a candle body exceeds spike_multiplier × EMA."""
        g = CandleSizeGuard(
            spike_multiplier=3.0, ema_period=10,
            min_candles=5, cooldown_seconds=60.0, pip_size=0.1
        )
        # Warm up with 10-pip candles
        for _ in range(10):
            g.update(1800.0, 1801.0)   # 10 pips → EMA ≈ 10
        # Spike: 500 pip candle → 500 >= 3×10
        g.update(1800.0, 1850.0)
        assert g.is_entry_blocked() is True

    def test_cooldown_expires_reopens_gate(self):
        """Gate reopens after cooldown_seconds elapses."""
        g = CandleSizeGuard(
            spike_multiplier=2.0, ema_period=5,
            min_candles=5, cooldown_seconds=0.05, pip_size=0.1
        )
        for _ in range(5):
            g.update(1800.0, 1801.0)
        g.update(1800.0, 1860.0)   # large spike
        assert g.is_entry_blocked() is True
        _time.sleep(0.1)
        assert g.is_entry_blocked() is False

    def test_invalid_price_raises(self):
        """Invalid price inputs raise TypeError or ValueError."""
        g = CandleSizeGuard()
        with pytest.raises(TypeError):
            g.update(True, 1800.0)
        with pytest.raises(ValueError):
            g.update(float("nan"), 1800.0)
        with pytest.raises(ValueError):
            g.update(float("inf"), 1800.0)
        with pytest.raises(TypeError):
            g.update("1800", 1800.0)


# ════════════════════════════════════════════════════════════════════════════
# wave71 — BidAskSkewGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestBidAskSkewGuard:

    def test_not_blocked_during_warmup(self):
        """Gate stays open before min_ticks readings are collected."""
        g = BidAskSkewGuard(skew_threshold=0.7, hard_block_threshold=0.9, min_ticks=5)
        # Extreme skew but only 4 readings → warmup
        for _ in range(4):
            g.update(0.0, 1000.0)   # skew = -1.0
        assert g.is_entry_blocked() is False

    def test_not_blocked_with_balanced_depth(self):
        """Balanced bid/ask returns not blocked."""
        g = BidAskSkewGuard(skew_threshold=0.7, hard_block_threshold=0.9, min_ticks=3)
        for _ in range(5):
            g.update(500.0, 500.0)   # skew = 0.0
        assert g.is_entry_blocked() is False

    def test_blocked_on_extreme_sell_skew(self):
        """Extreme ask volume (strong sell pressure) triggers block."""
        g = BidAskSkewGuard(skew_threshold=0.7, hard_block_threshold=0.9, min_ticks=3)
        for _ in range(5):
            g.update(50.0, 950.0)   # skew = -0.9 → at hard threshold
        assert g.is_entry_blocked() is True

    def test_blocked_on_directional_skew(self):
        """Skew above directional threshold (but below hard) still blocks."""
        g = BidAskSkewGuard(skew_threshold=0.6, hard_block_threshold=0.9, min_ticks=3)
        for _ in range(5):
            g.update(850.0, 150.0)   # skew = +0.7 → above 0.6 threshold
        assert g.is_entry_blocked() is True

    def test_invalid_volume_raises(self):
        """Invalid volume inputs raise TypeError or ValueError."""
        g = BidAskSkewGuard()
        with pytest.raises(TypeError):
            g.update(True, 500.0)
        with pytest.raises(ValueError):
            g.update(float("nan"), 500.0)
        with pytest.raises(ValueError):
            g.update(-100.0, 500.0)   # negative volume
        with pytest.raises(TypeError):
            g.update("500", 500.0)
