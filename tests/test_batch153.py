"""
tests/test_batch153.py
-----------------------
10 unit tests for Batch 153 wave modules:
  • wave72_price_acceleration_guard  (5 tests)
  • wave73_correlation_risk_guard    (5 tests)

All tests use fresh class instances and are deterministic.
"""

import sys
import os
import math
import time as _time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from wave72_price_acceleration_guard import PriceAccelerationGuard
from wave73_correlation_risk_guard import CorrelationRiskGuard


# ════════════════════════════════════════════════════════════════════════════
# wave72 — PriceAccelerationGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestPriceAccelerationGuard:

    def test_not_blocked_during_warmup(self):
        """Gate stays open before min_ticks threshold is reached."""
        g = PriceAccelerationGuard(
            accel_threshold=1.0, ema_period=5,
            min_ticks=10, cooldown_seconds=60.0, pip_size=0.1
        )
        # Feed only 4 ticks (below min_ticks=10)
        base = 1800.0
        for i in range(4):
            g.update(base + i * 50.0)   # large jumps but warmup not done
        assert g.is_entry_blocked() is False

    def test_not_blocked_with_stable_prices(self):
        """Steady price stream with no acceleration stays open."""
        g = PriceAccelerationGuard(
            accel_threshold=10.0, ema_period=5,
            min_ticks=5, cooldown_seconds=60.0, pip_size=0.1
        )
        # Constant price → delta=0 → acceleration=0
        for _ in range(10):
            g.update(1800.0)
        assert g.is_entry_blocked() is False

    def test_blocked_on_sudden_acceleration(self):
        """Rapid price jump that exceeds accel_threshold triggers block."""
        g = PriceAccelerationGuard(
            accel_threshold=5.0, ema_period=3,
            min_ticks=5, cooldown_seconds=60.0, pip_size=0.1
        )
        # Warm up with tiny 1-pip moves
        for i in range(5):
            g.update(1800.0 + i * 0.1)
        # Sudden 200-pip jump → massive acceleration
        g.update(1820.0)
        assert g.is_entry_blocked() is True

    def test_cooldown_expires_reopens_gate(self):
        """Gate reopens after cooldown_seconds elapses."""
        g = PriceAccelerationGuard(
            accel_threshold=1.0, ema_period=3,
            min_ticks=5, cooldown_seconds=0.05, pip_size=0.1
        )
        for i in range(5):
            g.update(1800.0 + i * 0.1)
        g.update(1900.0)   # spike
        assert g.is_entry_blocked() is True
        _time.sleep(0.1)
        assert g.is_entry_blocked() is False

    def test_invalid_price_raises(self):
        """Invalid price inputs raise TypeError or ValueError."""
        g = PriceAccelerationGuard()
        with pytest.raises(TypeError):
            g.update(True)
        with pytest.raises(ValueError):
            g.update(float("nan"))
        with pytest.raises(ValueError):
            g.update(float("inf"))
        with pytest.raises(TypeError):
            g.update("1800.0")


# ════════════════════════════════════════════════════════════════════════════
# wave73 — CorrelationRiskGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestCorrelationRiskGuard:

    def test_not_blocked_with_no_positions(self):
        """Zero open positions must not block."""
        g = CorrelationRiskGuard(max_positions=3)
        assert g.is_entry_blocked() is False

    def test_not_blocked_below_max(self):
        """One position below ceiling stays open."""
        g = CorrelationRiskGuard(max_positions=3)
        g.open_position(101)
        g.open_position(102)
        assert g.is_entry_blocked() is False
        assert g.get_open_count() == 2

    def test_blocked_at_max_positions(self):
        """Gate closes exactly when position count reaches max_positions."""
        g = CorrelationRiskGuard(max_positions=3)
        for ticket in [201, 202, 203]:
            g.open_position(ticket)
        assert g.is_entry_blocked() is True

    def test_reopens_after_close(self):
        """Closing a position reopens the gate when count drops below max."""
        g = CorrelationRiskGuard(max_positions=2)
        g.open_position("T-001")
        g.open_position("T-002")
        assert g.is_entry_blocked() is True
        g.close_position("T-001")
        assert g.is_entry_blocked() is False
        assert g.get_open_count() == 1

    def test_invalid_ticket_raises(self):
        """Invalid ticket types raise TypeError or ValueError."""
        g = CorrelationRiskGuard(max_positions=5)
        with pytest.raises(TypeError):
            g.open_position(None)
        with pytest.raises(TypeError):
            g.open_position(True)
        with pytest.raises(TypeError):
            g.open_position([123])   # list not allowed
        with pytest.raises(ValueError):
            g.open_position(float("nan"))
