"""
tests/test_batch151.py
-----------------------
10 unit tests for Batch 151 wave modules:
  • wave68_tick_velocity_guard    (5 tests)
  • wave69_overnight_gap_guard    (5 tests)

All tests use fresh class instances and are deterministic.
"""

import sys
import os
import math
import threading
import time as _time
from datetime import datetime, time, timezone, timedelta

import pytest

# ── ensure project root is importable ──────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import wave68_tick_velocity_guard as w68
import wave69_overnight_gap_guard as w69

from wave68_tick_velocity_guard import TickVelocityGuard
from wave69_overnight_gap_guard import OvernightGapGuard


# ════════════════════════════════════════════════════════════════════════════
# wave68 — TickVelocityGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestTickVelocityGuard:

    def test_not_blocked_during_warmup(self):
        """Gate stays open while total ticks < min_warmup_ticks."""
        g = TickVelocityGuard(window_seconds=5.0, min_ticks_per_second=10.0, min_warmup_ticks=5)
        # Send only 4 ticks — still in warmup
        for _ in range(4):
            g.update()
        assert g.is_entry_blocked() is False

    def test_not_blocked_with_high_velocity(self):
        """Gate open when many ticks arrive in quick succession."""
        g = TickVelocityGuard(window_seconds=5.0, min_ticks_per_second=0.1, min_warmup_ticks=5)
        for _ in range(20):   # 20 ticks very fast → high velocity
            g.update()
        assert g.is_entry_blocked() is False

    def test_blocked_with_zero_recent_ticks(self):
        """Gate closes after warmup if no recent ticks (window expired)."""
        g = TickVelocityGuard(window_seconds=0.05, min_ticks_per_second=100.0, min_warmup_ticks=3)
        for _ in range(3):
            g.update()
        _time.sleep(0.1)  # let window expire
        assert g.is_entry_blocked() is True

    def test_reset_reopens_gate(self):
        """reset() clears state; gate returns to warmup (open) state."""
        g = TickVelocityGuard(window_seconds=0.05, min_ticks_per_second=100.0, min_warmup_ticks=3)
        for _ in range(3):
            g.update()
        _time.sleep(0.1)
        assert g.is_entry_blocked() is True
        g.reset()
        assert g.is_entry_blocked() is False  # back to warmup
        assert g.get_velocity() == 0.0

    def test_invalid_params_raise(self):
        """Invalid constructor parameters raise TypeError / ValueError."""
        with pytest.raises(TypeError):
            TickVelocityGuard(window_seconds=True)
        with pytest.raises(ValueError):
            TickVelocityGuard(window_seconds=float("nan"))
        with pytest.raises(ValueError):
            TickVelocityGuard(min_ticks_per_second=-1.0)
        with pytest.raises(TypeError):
            TickVelocityGuard(min_warmup_ticks=2.5)


# ════════════════════════════════════════════════════════════════════════════
# wave69 — OvernightGapGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestOvernightGapGuard:

    def test_not_blocked_without_open_trigger(self):
        """Gate stays open when no open time has been triggered."""
        g = OvernightGapGuard(open_times=[], gap_seconds=30.0)
        assert g.is_entry_blocked() is False

    def test_blocked_after_manual_trigger(self):
        """Manually trigger gap window via _gap_triggered_at and verify blocking."""
        g = OvernightGapGuard(open_times=[], gap_seconds=60.0)
        # Simulate a trigger by directly setting the internal state
        import time as _t
        with g._lock:
            g._gap_triggered_at = _t.monotonic()
        assert g.is_entry_blocked() is True

    def test_gap_expires_after_duration(self):
        """Gap window auto-clears after gap_seconds elapses."""
        g = OvernightGapGuard(open_times=[], gap_seconds=0.05)  # 50ms gap
        import time as _t
        with g._lock:
            g._gap_triggered_at = _t.monotonic()
        assert g.is_entry_blocked() is True
        _time.sleep(0.1)   # wait for gap to expire
        assert g.is_entry_blocked() is False

    def test_reset_clears_gap(self):
        """reset() immediately reopens the gate."""
        g = OvernightGapGuard(open_times=[], gap_seconds=60.0)
        import time as _t
        with g._lock:
            g._gap_triggered_at = _t.monotonic()
        assert g.is_entry_blocked() is True
        g.reset()
        assert g.is_entry_blocked() is False
        assert g.get_remaining_gap_seconds() == 0.0

    def test_invalid_gap_seconds_raises(self):
        """Invalid gap_seconds raises TypeError or ValueError."""
        with pytest.raises(TypeError):
            OvernightGapGuard(gap_seconds=True)
        with pytest.raises(ValueError):
            OvernightGapGuard(gap_seconds=float("nan"))
        with pytest.raises(ValueError):
            OvernightGapGuard(gap_seconds=-5.0)
        with pytest.raises(ValueError):
            OvernightGapGuard(gap_seconds=0.0)
        with pytest.raises(TypeError):
            OvernightGapGuard(open_times=[time(0, 0), "invalid"])
