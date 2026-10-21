"""
tests/test_batch154.py
-----------------------
10 unit tests for Batch 154 wave modules:
  • wave74_realized_vol_guard        (5 tests)
  • wave75_time_of_day_pnl_guard     (5 tests)

All tests use fresh class instances and are fully deterministic.
"""

import sys
import os
import math
import time as _time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from wave74_realized_vol_guard import RealizedVolGuard
from wave75_time_of_day_pnl_guard import TimeOfDayPnlGuard


# ════════════════════════════════════════════════════════════════════════════
# wave74 — RealizedVolGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestRealizedVolGuard:

    def test_not_blocked_during_warmup(self):
        """Gate stays open before min_ticks are collected."""
        g = RealizedVolGuard(window=20, vol_threshold=0.0001, min_ticks=10, cooldown_seconds=60.0)
        # Feed only 9 volatile ticks — below warmup threshold
        price = 1800.0
        for i in range(9):
            g.update(price + i * 5.0)
        assert g.is_entry_blocked() is False

    def test_not_blocked_with_flat_prices(self):
        """Constant price stream has zero vol — gate stays open."""
        g = RealizedVolGuard(window=10, vol_threshold=0.001, min_ticks=5, cooldown_seconds=60.0)
        for _ in range(15):
            g.update(1800.0)
        assert g.is_entry_blocked() is False

    def test_blocked_on_high_volatility(self):
        """Gate closes when realized vol exceeds threshold."""
        g = RealizedVolGuard(window=10, vol_threshold=0.0001, min_ticks=5, cooldown_seconds=60.0)
        # Alternating prices → large log-returns
        for i in range(15):
            g.update(1800.0 if i % 2 == 0 else 1900.0)
        assert g.is_entry_blocked() is True

    def test_cooldown_expires_reopens_gate(self):
        """Gate reopens after cooldown_seconds elapses."""
        g = RealizedVolGuard(window=10, vol_threshold=0.0001, min_ticks=5, cooldown_seconds=0.05)
        for i in range(15):
            g.update(1800.0 if i % 2 == 0 else 1900.0)
        assert g.is_entry_blocked() is True
        _time.sleep(0.1)
        assert g.is_entry_blocked() is False

    def test_invalid_price_raises(self):
        """Invalid price inputs raise TypeError or ValueError."""
        g = RealizedVolGuard()
        with pytest.raises(TypeError):
            g.update(True)
        with pytest.raises(ValueError):
            g.update(float("nan"))
        with pytest.raises(ValueError):
            g.update(-100.0)   # negative price (log undefined)
        with pytest.raises(ValueError):
            g.update(0.0)      # zero price (log undefined)


# ════════════════════════════════════════════════════════════════════════════
# wave75 — TimeOfDayPnlGuard (5 tests)
# ════════════════════════════════════════════════════════════════════════════

class TestTimeOfDayPnlGuard:

    def test_not_blocked_with_no_history(self):
        """Fresh guard with no trades must not block."""
        g = TimeOfDayPnlGuard(loss_threshold=50.0, min_trades_per_hour=5)
        assert g.is_entry_blocked() is False

    def test_not_blocked_below_min_trades(self):
        """Current hour must not block before min_trades_per_hour is reached."""
        g = TimeOfDayPnlGuard(loss_threshold=10.0, min_trades_per_hour=5)
        # Record 4 big losses — not enough trades yet to trigger block
        for _ in range(4):
            g.record_trade_pnl(-100.0)
        assert g.is_entry_blocked() is False

    def test_blocked_after_sufficient_losing_trades(self):
        """Hour blocks when cumulative loss > loss_threshold after min trades."""
        g = TimeOfDayPnlGuard(loss_threshold=50.0, min_trades_per_hour=5)
        # Record 5 trades with total loss = -300 (> 50)
        for _ in range(5):
            g.record_trade_pnl(-60.0)
        assert g.is_entry_blocked() is True

    def test_not_blocked_when_hour_profitable(self):
        """Profitable hour with enough trades must not block."""
        g = TimeOfDayPnlGuard(loss_threshold=50.0, min_trades_per_hour=5)
        for _ in range(6):
            g.record_trade_pnl(20.0)   # cumulative = +120
        assert g.is_entry_blocked() is False

    def test_reset_clears_all_hourly_data(self):
        """reset() clears all cumulative PnL and trade counts."""
        g = TimeOfDayPnlGuard(loss_threshold=10.0, min_trades_per_hour=3)
        # Build up blocked state
        for _ in range(5):
            g.record_trade_pnl(-50.0)
        assert g.is_entry_blocked() is True
        g.reset()
        assert g.is_entry_blocked() is False
        # All hours should be zeroed
        for h in range(24):
            assert g.get_hourly_pnl(h) == 0.0
            assert g.get_hourly_trade_count(h) == 0
