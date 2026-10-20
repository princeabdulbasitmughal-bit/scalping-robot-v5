"""
tests/test_batch149.py
-----------------------
10 unit tests for Batch 149 wave modules:
  • wave64_max_daily_trades_limiter  (5 tests)
  • wave65_news_blackout_guard       (5 tests)

All tests are deterministic and have zero side-effects on global state
(each test uses a fresh instance or calls reset() afterwards).
"""

import sys
import os
import math
import threading
from datetime import datetime, time, timezone, timedelta

import pytest

# ── ensure project root is importable ──────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import wave64_max_daily_trades_limiter as w64
import wave65_news_blackout_guard as w65

from wave64_max_daily_trades_limiter import MaxDailyTradesLimiter
from wave65_news_blackout_guard import NewsBlackoutGuard


# ════════════════════════════════════════════════════════════════════════════
# wave64 — MaxDailyTradesLimiter (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestMaxDailyTradesLimiter:

    def test_fresh_limiter_not_blocked(self):
        """Brand-new limiter with no trades should NOT block."""
        lim = MaxDailyTradesLimiter(max_trades=5)
        assert lim.is_entry_blocked() is False

    def test_blocks_at_max_trades(self):
        """Gate closes exactly when trade count reaches max_trades."""
        lim = MaxDailyTradesLimiter(max_trades=3)
        for _ in range(3):
            lim.record_trade()
        assert lim.is_entry_blocked() is True

    def test_does_not_block_before_max(self):
        """One trade below ceiling must remain open."""
        lim = MaxDailyTradesLimiter(max_trades=10)
        for _ in range(9):
            lim.record_trade()
        assert lim.is_entry_blocked() is False

    def test_reset_reopens_gate(self):
        """reset() clears the count and reopens the gate."""
        lim = MaxDailyTradesLimiter(max_trades=2)
        lim.record_trade()
        lim.record_trade()
        assert lim.is_entry_blocked() is True
        lim.reset()
        assert lim.is_entry_blocked() is False
        assert lim.get_trade_count() == 0

    def test_invalid_max_trades_raises(self):
        """Non-int or bool max_trades must raise TypeError; zero/negative ValueError."""
        with pytest.raises(TypeError):
            MaxDailyTradesLimiter(max_trades=True)       # bool subclass trap
        with pytest.raises(TypeError):
            MaxDailyTradesLimiter(max_trades=10.0)       # float
        with pytest.raises(ValueError):
            MaxDailyTradesLimiter(max_trades=0)
        with pytest.raises(ValueError):
            MaxDailyTradesLimiter(max_trades=-5)


# ════════════════════════════════════════════════════════════════════════════
# wave65 — NewsBlackoutGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestNewsBlackoutGuard:

    def test_no_windows_not_blocked(self):
        """Guard with empty window list must never block."""
        guard = NewsBlackoutGuard(windows=[])
        assert guard.is_entry_blocked() is False

    def test_inside_recurring_window_blocked(self):
        """is_entry_blocked returns True when inside a recurring window."""
        now_utc = datetime.now(timezone.utc)
        # Build a window that straddles 'now'
        start = (now_utc - timedelta(minutes=5)).time().replace(second=0, microsecond=0)
        end   = (now_utc + timedelta(minutes=5)).time().replace(second=0, microsecond=0)
        guard = NewsBlackoutGuard(windows=[(start, end)])
        assert guard.is_entry_blocked() is True

    def test_outside_recurring_window_not_blocked(self):
        """is_entry_blocked returns False when current time is outside all windows."""
        now_utc = datetime.now(timezone.utc)
        # Window 2 hours ago, already closed
        start = (now_utc - timedelta(hours=3)).time().replace(second=0, microsecond=0)
        end   = (now_utc - timedelta(hours=2)).time().replace(second=0, microsecond=0)
        if start >= end:
            pytest.skip("Time arithmetic crossed midnight — skip this case")
        guard = NewsBlackoutGuard(windows=[(start, end)])
        assert guard.is_entry_blocked() is False

    def test_absolute_window_blocked(self):
        """One-shot absolute window containing now returns blocked."""
        guard = NewsBlackoutGuard(windows=[])
        now_utc = datetime.now(timezone.utc)
        guard.add_absolute_window(
            now_utc - timedelta(minutes=1),
            now_utc + timedelta(minutes=1),
        )
        assert guard.is_entry_blocked() is True

    def test_reset_clears_all_windows(self):
        """reset() removes all recurring and absolute windows."""
        now_utc = datetime.now(timezone.utc)
        start = (now_utc - timedelta(minutes=5)).time().replace(second=0, microsecond=0)
        end   = (now_utc + timedelta(minutes=5)).time().replace(second=0, microsecond=0)
        guard = NewsBlackoutGuard(windows=[(start, end)])
        assert guard.is_entry_blocked() is True
        guard.reset()
        assert guard.is_entry_blocked() is False
        assert guard.get_window_count() == 0
