"""
tests/test_batch163.py
-----------------------
Unit tests for:
  wave92_reentry_cooldown_guard  (same-direction re-entry after stop-loss)
  wave93_broker_latency_guard    (round-trip order latency monitor)

5 tests per module = 10 total.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave92_reentry_cooldown_guard as w92
import wave93_broker_latency_guard as w93


# ---------------------------------------------------------------------------
# wave92 tests
# ---------------------------------------------------------------------------

class TestWave92ReentryCooldownGuard:

    def setup_method(self):
        w92.reset()

    def test_no_stop_loss_not_blocked(self):
        """Without any recorded stop-loss, no entries are blocked."""
        assert w92.is_entry_blocked("EURUSD", "BUY") is False
        assert w92.is_entry_blocked("EURUSD", "SELL") is False

    def test_stop_loss_blocks_same_direction(self):
        """After a BUY stop-loss, re-entering BUY on same symbol is blocked."""
        w92.record_stop_loss("EURUSD", "BUY")
        assert w92.is_entry_blocked("EURUSD", "BUY") is True

    def test_stop_loss_does_not_block_opposite_direction(self):
        """A BUY stop-loss must NOT block SELL entries."""
        w92.record_stop_loss("EURUSD", "BUY")
        assert w92.is_entry_blocked("EURUSD", "SELL") is False

    def test_case_insensitive_symbol_and_direction(self):
        """Symbol and direction matching must be case-insensitive."""
        w92.record_stop_loss("eurusd", "buy")
        assert w92.is_entry_blocked("EURUSD", "BUY") is True
        assert w92.is_entry_blocked("EurUsd", "Buy") is True

    def test_invalid_inputs_not_blocked(self):
        """Empty symbol, invalid direction, non-string inputs -> not blocked."""
        assert w92.is_entry_blocked("", "BUY") is False
        assert w92.is_entry_blocked("EURUSD", "LONG") is False
        assert w92.is_entry_blocked("EURUSD", "") is False
        # record_stop_loss with invalid inputs must be silently ignored
        w92.record_stop_loss("", "BUY")
        w92.record_stop_loss("EURUSD", "HOLD")
        assert w92.is_entry_blocked("EURUSD", "BUY") is False


# ---------------------------------------------------------------------------
# wave93 tests
# ---------------------------------------------------------------------------

class TestWave93BrokerLatencyGuard:

    def setup_method(self):
        w93.reset()

    def test_warmup_fail_closed(self):
        """Fewer than min_samples (5) -> fail-closed."""
        w93.record_latency(100.0)
        w93.record_latency(120.0)
        assert w93.is_entry_blocked() is True
        assert w93.get_avg_latency_ms() == -1.0

    def test_low_latency_not_blocked(self):
        """Average latency of 200ms (< 500ms threshold) -> not blocked."""
        for _ in range(6):
            w93.record_latency(200.0)
        assert w93.is_entry_blocked() is False
        assert abs(w93.get_avg_latency_ms() - 200.0) < 1.0

    def test_high_latency_triggers_block(self):
        """Average latency >= 500ms -> triggers cooldown block."""
        for _ in range(6):
            w93.record_latency(600.0)
        assert w93.is_entry_blocked() is True
        assert w93.get_avg_latency_ms() >= 500.0

    def test_reset_clears_state(self):
        """After reset, guard returns to warmup (fail-closed)."""
        for _ in range(6):
            w93.record_latency(600.0)
        assert w93.is_entry_blocked() is True
        w93.reset()
        assert w93.get_avg_latency_ms() == -1.0
        assert w93.is_entry_blocked() is True  # warmup again

    def test_invalid_latency_ignored(self):
        """bool, NaN, Inf, zero, negative ms values must be silently ignored."""
        w93.record_latency(True)
        w93.record_latency(float("nan"))
        w93.record_latency(float("inf"))
        w93.record_latency(0.0)
        w93.record_latency(-100.0)
        # No valid samples -> warmup -> fail-closed
        assert w93.is_entry_blocked() is True
        assert w93.get_avg_latency_ms() == -1.0
