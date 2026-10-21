"""
tests/test_batch168.py
-----------------------
Unit tests for Batch 168 wave modules:
  - wave102_spread_spike_guard           (5 tests)
  - wave103_time_since_last_trade_guard  (5 tests)

Baseline before this batch: 1,923 passed, 1 skipped
Expected after: 1,933 passed, 1 skipped
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave102_spread_spike_guard as w102
import wave103_time_since_last_trade_guard as w103


# ===========================================================================
# wave102 — Spread Spike Guard (5 tests)
# ===========================================================================

class TestWave102SpreadSpikeGuard:

    def setup_method(self):
        w102.reset()

    # -- T1: Not blocked before MIN_SAMPLES warmup --
    def test_not_blocked_before_warmup(self):
        """Fewer than MIN_SAMPLES spreads must never trigger a block."""
        for _ in range(w102.MIN_SAMPLES - 1):
            w102.update(10.0)   # massive spike value but below warmup
        assert w102.is_entry_blocked() is False

    # -- T2: Blocked when current spread is >= SPIKE_MULTIPLIER * avg --
    def test_blocked_on_spike(self):
        """A spread 3x the rolling average must trigger a block."""
        # Fill window with baseline spread of 1.0 pip
        for _ in range(w102.MIN_SAMPLES):
            w102.update(1.0)
        # Now inject a spike: 3.0 * avg(1.0) = 3.0 -> blocked at >= 3.0x
        w102.update(5.0)   # 5x the average -> well above threshold
        assert w102.is_entry_blocked() is True

    # -- T3: Not blocked when spread is below spike threshold --
    def test_not_blocked_below_spike_threshold(self):
        """A spread below SPIKE_MULTIPLIER * avg must not block."""
        for _ in range(w102.WINDOW_SIZE):
            w102.update(2.0)   # steady baseline 2.0 pips
        # Next spread: 2x avg = 4.0 pips, threshold is 3x avg = 6.0 pips
        w102.update(4.0)
        assert w102.is_entry_blocked() is False

    # -- T4: Invalid inputs silently ignored --
    def test_invalid_inputs_ignored(self):
        """Bool/NaN/Inf/zero/negative spread values silently rejected."""
        w102.update(True)
        w102.update(False)
        w102.update(float("nan"))
        w102.update(float("inf"))
        w102.update(0.0)
        w102.update(-2.0)
        w102.update("1.5")   # type: ignore
        w102.update(None)    # type: ignore
        assert w102.is_entry_blocked() is False

    # -- T5: reset() clears block and spread history --
    def test_reset_clears_state(self):
        """After reset(), guard is unblocked and spreads deque is empty."""
        with w102._lock:
            w102._blocked_until = time.monotonic() + 999.0
        assert w102.is_entry_blocked() is True
        w102.reset()
        assert w102.is_entry_blocked() is False
        with w102._lock:
            assert len(w102._spreads) == 0


# ===========================================================================
# wave103 — Time-Since-Last-Trade Guard (5 tests)
# ===========================================================================

class TestWave103TimeSinceLastTradeGuard:

    def setup_method(self):
        w103.reset()

    # -- T1: Not blocked before any trade is recorded --
    def test_not_blocked_initially(self):
        """Before any trade, guard must allow entry (fail-open pre-trade)."""
        assert w103.is_entry_blocked() is False

    # -- T2: Blocked immediately after recording a trade --
    def test_blocked_immediately_after_trade(self):
        """Right after record_trade(), the interval has not elapsed -> blocked."""
        w103.record_trade()
        assert w103.is_entry_blocked() is True

    # -- T3: Block expires after MIN_INTERVAL_SECONDS --
    def test_block_expires_after_interval(self):
        """By backdating _last_trade_time, the block must appear expired."""
        w103.record_trade()
        assert w103.is_entry_blocked() is True
        # Simulate elapsed time by manipulating internal timestamp
        with w103._lock:
            w103._last_trade_time = time.monotonic() - w103.MIN_INTERVAL_SECONDS - 1.0
        assert w103.is_entry_blocked() is False

    # -- T4: update() is an alias for record_trade() --
    def test_update_alias(self):
        """update() must behave identically to record_trade()."""
        assert w103.is_entry_blocked() is False
        w103.update()
        assert w103.is_entry_blocked() is True

    # -- T5: reset() clears the last trade timestamp --
    def test_reset_clears_state(self):
        """After reset(), guard must report not blocked (no trade on record)."""
        w103.record_trade()
        assert w103.is_entry_blocked() is True
        w103.reset()
        assert w103.is_entry_blocked() is False
        with w103._lock:
            assert w103._last_trade_time < 0.0
