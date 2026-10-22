"""
tests/test_batch177.py
-----------------------
Unit tests for Batch 177 wave modules:
  - wave120_equity_drawdown_recovery_factor_guard (5 tests)
  - wave121_price_noise_ratio_guard              (5 tests)

Baseline before this batch: 2,014 collected items
Expected after: 2,024 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave120_equity_drawdown_recovery_factor_guard as w120
import wave121_price_noise_ratio_guard as w121


# ===========================================================================
# wave120 — Drawdown Recovery Stagnation & Giveback Guard (5 tests)
# ===========================================================================

class TestWave120EquityDrawdownRecoveryGuard:

    def setup_method(self):
        w120.reset()

    # -- T1: Normal new peaks do not block --
    def test_new_peaks_not_blocked(self):
        """Monotonically increasing equity constantly updates HWM and does not block."""
        w120.update(10000.0)
        w120.update(10050.0)
        w120.update(10100.0)
        assert w120.is_entry_blocked() is False

    # -- T2: Shallow rebound below MIN_REBOUND_USD does not trigger rule --
    def test_small_rebound_no_block(self):
        """Rebounding only $10 (< $30 min) then falling does not trigger giveback block."""
        w120.update(10000.0) # HWM
        w120.update(9800.0)  # trough
        w120.update(9810.0)  # rebound +$10 < $30
        w120.update(9800.0)  # back to trough
        assert w120.is_entry_blocked() is False

    # -- T3: 60%+ giveback of a $50 rebound triggers block --
    def test_rebound_giveback_triggers_block(self):
        """Rebounding $50 from trough (9800 -> 9850) then giving back to 9815 (70% giveback) blocks."""
        w120.update(10000.0) # HWM
        w120.update(9800.0)  # trough
        w120.update(9850.0)  # rebound +$50 >= $30 trigger
        w120.update(9815.0)  # giveback $35 / $50 = 70% >= 60%
        assert w120.is_entry_blocked() is True

    # -- T4: Reaching new HWM resets recovery and trough state --
    def test_new_hwm_clears_recovery_state(self):
        """Surpassing previous HWM resets trough and peak recovery to new peak."""
        w120.update(10000.0)
        w120.update(9800.0)
        w120.update(10050.0) # new HWM
        assert w120._hwm == 10050.0
        assert w120._trough == 10050.0
        assert w120.is_entry_blocked() is False

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Invalid inputs rejected; reset() restores baseline uninitialized state."""
        w120.update(True)
        w120.update(float("nan"))
        w120.update(-100.0)
        assert w120._hwm == 0.0

        with w120._lock:
            w120._blocked_until = time.monotonic() + 100.0
        assert w120.is_entry_blocked() is True
        w120.reset()
        assert w120.is_entry_blocked() is False
        assert w120._hwm == 0.0


# ===========================================================================
# wave121 — Price Noise & Market Efficiency Ratio Guard (5 tests)
# ===========================================================================

class TestWave121PriceNoiseRatioGuard:

    def setup_method(self):
        w121.reset()

    # -- T1: Warmup requires WINDOW_SIZE before evaluation --
    def test_warmup_requires_full_window(self):
        """Fewer than WINDOW_SIZE ticks do not evaluate ER and do not block."""
        for _ in range(w121.WINDOW_SIZE - 1):
            w121.update(1.1000)
        assert w121.is_entry_blocked() is False

    # -- T2: Strong directional trend has high ER (near 1.0); not blocked --
    def test_strong_trend_high_efficiency(self):
        """Steady uptrend has displacement = total_path -> ER=1.0 >= 0.15 -> not blocked."""
        price = 100.0
        for _ in range(w121.WINDOW_SIZE):
            w121.update(price)
            price += 0.10
        assert w121.is_entry_blocked() is False

    # -- T3: Heavy whipsaw churn produces low ER (< 0.15) -> blocks --
    def test_noisy_chop_low_efficiency_blocked(self):
        """Alternating price churn (100.0 -> 100.1 -> 100.0) with zero net move blocks."""
        # Oscillate 20 times between 100.0 and 100.1
        # net_change = 0.0 (or 0.1), total_path = 1.9 -> ER ~ 0.05 < 0.15
        for i in range(w121.WINDOW_SIZE):
            p = 100.0 if (i % 2 == 0) else 100.1
            w121.update(p)
        assert w121.is_entry_blocked() is True

    # -- T4: update() works properly --
    def test_update_behavior(self):
        """update() maintains deque capacity at WINDOW_SIZE."""
        for i in range(30):
            w121.update(100.0 + i)
        with w121._lock:
            assert len(w121._prices) == w121.WINDOW_SIZE

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf, non-positive values ignored; reset() clears."""
        w121.update(True)
        w121.update(float("nan"))
        w121.update(-5.0)
        with w121._lock:
            assert len(w121._prices) == 0

        # Force block then reset
        with w121._lock:
            w121._blocked_until = time.monotonic() + 100.0
        assert w121.is_entry_blocked() is True
        w121.reset()
        assert w121.is_entry_blocked() is False
        with w121._lock:
            assert len(w121._prices) == 0
