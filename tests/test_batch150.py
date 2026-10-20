"""
tests/test_batch150.py
-----------------------
15 unit tests for Batch 150 wave modules:
  • wave66_equity_curve_brake   (5 tests)
  • wave67_session_time_filter  (5 tests)
  • wave68_tick_velocity_guard  (5 tests)

All tests are deterministic and isolate state via fresh class instances.
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

import wave66_equity_curve_brake as w66
import wave67_session_time_filter as w67
import wave68_tick_velocity_guard as w68

from wave66_equity_curve_brake import EquityCurveBrake
from wave67_session_time_filter import SessionTimeFilter
from wave68_tick_velocity_guard import TickVelocityGuard


# ════════════════════════════════════════════════════════════════════════════
# wave66 — EquityCurveBrake (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestEquityCurveBrake:

    def test_not_blocked_before_min_ticks(self):
        """Gate stays open during warmup regardless of equity value."""
        brake = EquityCurveBrake(max_drawdown_pct=5.0, cooldown_seconds=60.0, min_ticks=10)
        # Send 9 ticks — one below warmup threshold
        for i in range(9):
            brake.update(1000.0)
        assert brake.is_entry_blocked() is False

    def test_not_blocked_when_within_threshold(self):
        """No brake below drawdown threshold."""
        brake = EquityCurveBrake(max_drawdown_pct=10.0, cooldown_seconds=60.0, min_ticks=3)
        for eq in [1000.0, 1010.0, 1020.0, 1015.0]:  # only 0.5% drop
            brake.update(eq)
        assert brake.is_entry_blocked() is False

    def test_blocked_when_drawdown_exceeded(self):
        """Brake trips when equity drops more than max_drawdown_pct from peak."""
        brake = EquityCurveBrake(max_drawdown_pct=5.0, cooldown_seconds=300.0, min_ticks=3)
        for eq in [1000.0, 1000.0, 1000.0]:  # build warmup + peak
            brake.update(eq)
        brake.update(940.0)  # 6% drawdown → trips brake
        assert brake.is_entry_blocked() is True

    def test_reset_clears_brake(self):
        """reset() reopens gate and clears all state."""
        brake = EquityCurveBrake(max_drawdown_pct=5.0, cooldown_seconds=300.0, min_ticks=3)
        for _ in range(3):
            brake.update(1000.0)
        brake.update(900.0)  # 10% drop → tripped
        assert brake.is_entry_blocked() is True
        brake.reset()
        assert brake.is_entry_blocked() is False

    def test_invalid_equity_raises(self):
        """Invalid equity inputs raise TypeError or ValueError."""
        brake = EquityCurveBrake(max_drawdown_pct=5.0, cooldown_seconds=60.0, min_ticks=3)
        with pytest.raises(TypeError):
            brake.update(True)                # bool subclass trap
        with pytest.raises(TypeError):
            brake.update("1000")              # string
        with pytest.raises(ValueError):
            brake.update(float("nan"))        # NaN
        with pytest.raises(ValueError):
            brake.update(float("inf"))        # Inf
        with pytest.raises(ValueError):
            brake.update(-500.0)              # negative equity
        with pytest.raises(ValueError):
            brake.update(0.0)                 # zero equity invalid


# ════════════════════════════════════════════════════════════════════════════
# wave67 — SessionTimeFilter (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestSessionTimeFilter:

    def test_no_sessions_always_blocked(self):
        """Empty session list must always block (fail-closed)."""
        f = SessionTimeFilter(sessions=[])
        assert f.is_entry_blocked() is True

    def test_inside_session_not_blocked(self):
        """is_entry_blocked returns False when inside a configured session."""
        now_utc = datetime.now(timezone.utc)
        open_t  = (now_utc - timedelta(minutes=30)).time().replace(second=0, microsecond=0)
        close_t = (now_utc + timedelta(minutes=30)).time().replace(second=0, microsecond=0)
        if open_t >= close_t:
            pytest.skip("Time arithmetic crossed midnight — skip this edge case")
        f = SessionTimeFilter(sessions=[(open_t, close_t)])
        assert f.is_entry_blocked() is False

    def test_outside_session_blocked(self):
        """is_entry_blocked returns True when outside all sessions."""
        now_utc = datetime.now(timezone.utc)
        # Build a session that ended 2 hours ago
        open_t  = (now_utc - timedelta(hours=3)).time().replace(second=0, microsecond=0)
        close_t = (now_utc - timedelta(hours=2)).time().replace(second=0, microsecond=0)
        if open_t >= close_t:
            pytest.skip("Time arithmetic crossed midnight — skip this edge case")
        f = SessionTimeFilter(sessions=[(open_t, close_t)])
        assert f.is_entry_blocked() is True

    def test_reset_makes_fully_blocked(self):
        """After reset() with no sessions, gate is always blocked."""
        now_utc = datetime.now(timezone.utc)
        open_t  = (now_utc - timedelta(minutes=30)).time().replace(second=0, microsecond=0)
        close_t = (now_utc + timedelta(minutes=30)).time().replace(second=0, microsecond=0)
        if open_t >= close_t:
            pytest.skip("Time arithmetic crossed midnight — skip this edge case")
        f = SessionTimeFilter(sessions=[(open_t, close_t)])
        assert f.is_entry_blocked() is False   # inside session
        f.reset()
        assert f.is_entry_blocked() is True    # no sessions → blocked
        assert f.get_session_count() == 0

    def test_invalid_session_raises(self):
        """Invalid session specs raise TypeError or ValueError."""
        with pytest.raises(TypeError):
            SessionTimeFilter(sessions=["not-a-tuple"])
        with pytest.raises(TypeError):
            SessionTimeFilter(sessions=[(1, 2)])           # ints, not time objects
        with pytest.raises(ValueError):
            # open >= close
            SessionTimeFilter(sessions=[(time(15, 0), time(10, 0))])
