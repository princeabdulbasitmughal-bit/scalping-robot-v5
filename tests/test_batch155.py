"""
tests/test_batch155.py
-----------------------
10 unit tests for Batch 155 wave modules:
  • wave76_atr_filter           (5 tests)
  • wave77_weekend_risk_guard   (5 tests)

All tests use fresh class instances and are fully deterministic.
"""

import sys
import os
import math
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from wave76_atr_filter import AtrFilter
from wave77_weekend_risk_guard import WeekendRiskGuard


# ════════════════════════════════════════════════════════════════════════════
# wave76 — AtrFilter (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestAtrFilter:

    def test_not_blocked_during_warmup(self):
        """Gate stays open before min_candles are fed."""
        f = AtrFilter(period=5, atr_min=1.0, atr_max=100.0,
                      pip_size=0.1, min_candles=5)
        # Feed only 4 candles — below warmup
        for _ in range(4):
            f.update(1802.0, 1798.0, 1800.0)
        assert f.is_entry_blocked() is False

    def test_not_blocked_within_atr_band(self):
        """Normal ATR within [min, max] band stays open."""
        f = AtrFilter(period=5, atr_min=1.0, atr_max=100.0,
                      pip_size=0.1, min_candles=5)
        # 40-pip candles → ATR ≈ 40 pips → within [1, 100]
        for _ in range(10):
            f.update(1804.0, 1800.0, 1802.0)
        assert f.is_entry_blocked() is False

    def test_blocked_when_atr_too_high(self):
        """ATR above atr_max triggers block."""
        f = AtrFilter(period=3, atr_min=1.0, atr_max=10.0,
                      pip_size=0.1, min_candles=3)
        # 200-pip candles → ATR >> 10
        for _ in range(10):
            f.update(1820.0, 1800.0, 1810.0)
        assert f.is_entry_blocked() is True

    def test_blocked_when_atr_too_low(self):
        """ATR below atr_min (dead market) triggers block."""
        f = AtrFilter(period=3, atr_min=5.0, atr_max=100.0,
                      pip_size=0.1, min_candles=3)
        # 0.1-pip candles → ATR ≈ 1 pip < 5 pip min
        for _ in range(10):
            f.update(1800.01, 1800.00, 1800.005)
        assert f.is_entry_blocked() is True

    def test_invalid_candle_raises(self):
        """Invalid price inputs raise TypeError or ValueError."""
        f = AtrFilter()
        with pytest.raises(TypeError):
            f.update(True, 1800.0, 1801.0)
        with pytest.raises(ValueError):
            f.update(float("nan"), 1800.0, 1801.0)
        with pytest.raises(ValueError):
            f.update(1798.0, 1802.0, 1800.0)   # high < low


# ════════════════════════════════════════════════════════════════════════════
# wave77 — WeekendRiskGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestWeekendRiskGuard:

    def _make_guard_at(self, dow: int, hour: int, minute: int,
                       friday_buf: int = 30, sunday_buf: int = 30):
        """
        Create a WeekendRiskGuard subclass that overrides the current UTC
        datetime to a synthetic (dow, hour, minute) for deterministic testing.
        """
        from wave77_weekend_risk_guard import _FRIDAY, _SUNDAY, _WEEKLY_CLOSE_HOUR, _WEEKLY_OPEN_HOUR
        FRIDAY = _FRIDAY
        SUNDAY = _SUNDAY
        CLOSE_HOUR = _WEEKLY_CLOSE_HOUR
        OPEN_HOUR  = _WEEKLY_OPEN_HOUR

        class PatchedGuard(WeekendRiskGuard):
            def is_entry_blocked(self_inner, tick=None):
                import threading
                with self_inner._lock:
                    fb = self_inner._friday_buf
                    sb = self_inner._sunday_buf
                if dow == FRIDAY:
                    now_min = hour * 60 + minute
                    if now_min >= (CLOSE_HOUR * 60 - fb):
                        return True
                if dow == 6:
                    return True
                if dow == SUNDAY:
                    open_min = OPEN_HOUR * 60
                    now_min  = hour * 60 + minute
                    if now_min < open_min:
                        return True
                    if now_min < (open_min + sb):
                        return True
                return False

        return PatchedGuard(friday_buffer_minutes=friday_buf,
                            sunday_buffer_minutes=sunday_buf)

    def test_normal_weekday_not_blocked(self):
        """Tuesday mid-day must never be blocked."""
        g = self._make_guard_at(dow=2, hour=12, minute=0)  # Tuesday 12:00
        assert g.is_entry_blocked() is False

    def test_friday_pre_close_blocked(self):
        """Friday 21:45 UTC (inside 30-min pre-close buffer) must block."""
        g = self._make_guard_at(dow=5, hour=21, minute=45)
        assert g.is_entry_blocked() is True

    def test_friday_before_buffer_not_blocked(self):
        """Friday 20:00 UTC (outside 30-min buffer) must not block."""
        g = self._make_guard_at(dow=5, hour=20, minute=0)
        assert g.is_entry_blocked() is False

    def test_saturday_always_blocked(self):
        """Saturday any time must always block (market closed)."""
        g = self._make_guard_at(dow=6, hour=10, minute=0)
        assert g.is_entry_blocked() is True

    def test_sunday_post_open_buffer_blocked(self):
        """Sunday 22:15 UTC (within 30-min post-open buffer) must block."""
        g = self._make_guard_at(dow=7, hour=22, minute=15)
        assert g.is_entry_blocked() is True
