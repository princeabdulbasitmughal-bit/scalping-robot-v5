"""
tests/test_batch301.py
----------------------
Combined pytest test suite for WAVE 360 and WAVE 361 guards.

Covers:
  - No-block before window fills
  - Happy-path (no block in healthy market)
  - Bid-dominance trigger (WAVE 360)
  - Ask-dominance trigger (WAVE 360)
  - CVaR tail breach trigger (WAVE 361)
  - No block when window not yet full (WAVE 361)
  - Invalid inputs -> INPUT_VALIDATION_ERROR for both guards
  - reset() clears state and lifts block
  - is_entry_blocked delegates to is_blocked
  - is_blocked with explicit current_time
  - last_reason tracks the most recent block reason
  - Thread safety smoke test (concurrent updates do not crash)
"""

import time
import threading
import sys
import os

# Make sure the project root is on the path so imports resolve without install
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from wave360_lob_bid_ask_level_count_asymmetry_guard import (
    Wave360LobBidAskLevelCountAsymmetryGuard,
)
from wave361_trade_flow_cvar_breach_guard import (
    Wave361TradeFlowCvarBreachGuard,
)


# ===========================================================================
# WAVE 360 - LOB Bid-Ask Level Count Asymmetry Guard tests
# ===========================================================================


class TestWave360NoBlockBeforeWindowFills:
    """No block signal should be emitted until the rolling window is full."""

    def test_no_block_before_window_fills(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=5, ratio_threshold=2.0, cooldown_seconds=10.0
        )
        # Feed 4 ticks with extreme bid dominance -- should still not block
        for _ in range(4):
            g.update(100, 1, timestamp=time.monotonic())
        assert not g.is_blocked()
        assert g.last_reason == ""


class TestWave360HappyPath:
    """Balanced LOB should never trigger a block."""

    def test_balanced_lob_no_block(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=5, ratio_threshold=3.0, cooldown_seconds=10.0
        )
        for _ in range(10):
            g.update(10, 10, timestamp=time.monotonic())
        assert not g.is_blocked()
        assert g.last_reason == ""


class TestWave360BidDominance:
    """Filling window with bid-heavy ratios should trigger BID_LEVEL_DOMINANCE."""

    def test_bid_dominance_triggers_block(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=5, ratio_threshold=3.0, cooldown_seconds=30.0
        )
        # ratio = 10/1 = 10 >> 3.0 threshold
        for _ in range(5):
            g.update(10, 1, timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "BID_LEVEL_DOMINANCE"

    def test_bid_dominance_last_reason_is_bid(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=3, ratio_threshold=2.0, cooldown_seconds=10.0
        )
        for _ in range(3):
            g.update(50, 1, timestamp=time.monotonic())
        assert g.last_reason == "BID_LEVEL_DOMINANCE"


class TestWave360AskDominance:
    """Filling window with ask-heavy ratios should trigger ASK_LEVEL_DOMINANCE."""

    def test_ask_dominance_triggers_block(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=5, ratio_threshold=3.0, cooldown_seconds=30.0
        )
        # ratio = 1/10 = 0.1 < 1/3.0 = 0.333
        for _ in range(5):
            g.update(1, 10, timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "ASK_LEVEL_DOMINANCE"


class TestWave360InvalidInput:
    """Any invalid input must immediately block with INPUT_VALIDATION_ERROR."""

    def test_float_bid_levels_blocks(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard()
        g.update(3.5, 5, timestamp=time.monotonic())  # float not allowed
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_bool_ask_levels_blocks(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard()
        g.update(3, True, timestamp=time.monotonic())  # bool not allowed
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_bid_levels_blocks(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard()
        g.update(-1, 5, timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_none_input_blocks(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard()
        g.update(None, 5, timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestWave360Reset:
    """reset() must clear rolling state and lift any active block."""

    def test_reset_clears_block(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=3, ratio_threshold=2.0, cooldown_seconds=300.0
        )
        for _ in range(3):
            g.update(100, 1, timestamp=time.monotonic())
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""

    def test_reset_clears_ratios_so_window_must_refill(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=3, ratio_threshold=2.0, cooldown_seconds=300.0
        )
        for _ in range(3):
            g.update(100, 1, timestamp=time.monotonic())
        g.reset()
        # After reset, only 2 ticks -- window not full again, no block
        g.update(100, 1, timestamp=time.monotonic())
        g.update(100, 1, timestamp=time.monotonic())
        assert not g.is_blocked()


class TestWave360IsEntryBlocked:
    """is_entry_blocked must delegate to is_blocked."""

    def test_is_entry_blocked_when_blocked(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=3, ratio_threshold=2.0, cooldown_seconds=300.0
        )
        for _ in range(3):
            g.update(50, 1, timestamp=time.monotonic())
        assert g.is_entry_blocked(bid=1.0, ask=1.0001)

    def test_is_entry_blocked_false_when_healthy(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=3, ratio_threshold=2.0, cooldown_seconds=0.0
        )
        for _ in range(3):
            g.update(5, 5, timestamp=time.monotonic())
        assert not g.is_entry_blocked(bid=1.0, ask=1.0001)


class TestWave360IsBlockedExplicitTime:
    """is_blocked(current_time) must honour an explicit monotonic timestamp."""

    def test_explicit_time_past_cooldown_not_blocked(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=3, ratio_threshold=2.0, cooldown_seconds=10.0
        )
        for _ in range(3):
            g.update(50, 1, timestamp=time.monotonic())
        assert g.is_blocked()
        # Simulate time well past cooldown
        far_future = time.monotonic() + 1000.0
        assert not g.is_blocked(current_time=far_future)


# ===========================================================================
# WAVE 361 - Trade Flow CVaR Breach Guard tests
# ===========================================================================


class TestWave361NoBlockBeforeWindowFills:
    """No block should fire until window_size ticks are accumulated."""

    def test_no_block_before_window_fills(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=5, alpha=0.95, cvar_threshold=10.0, cooldown_seconds=30.0
        )
        for _ in range(4):
            g.update(500.0, "sell", timestamp=time.monotonic())
        assert not g.is_blocked()
        assert g.last_reason == ""


class TestWave361HappyPath:
    """Balanced buy/sell flow should never breach CVaR threshold."""

    def test_balanced_flow_no_block(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=10, alpha=0.95, cvar_threshold=100.0, cooldown_seconds=30.0
        )
        for _ in range(20):
            g.update(10.0, "buy", timestamp=time.monotonic())
            g.update(10.0, "sell", timestamp=time.monotonic())
        assert not g.is_blocked()


class TestWave361CvarBreach:
    """Heavy sell-side flow should trigger CVAR_TAIL_BREACH."""

    def test_sell_flood_triggers_cvar_breach(self):
        # window=10, alpha=0.9 -> tail = bottom 10% = 1 element
        # cvar_threshold=50: all sells of 200 -> signed = -200
        # CVaR = -200 <= -50 -> block
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=10, alpha=0.90, cvar_threshold=50.0, cooldown_seconds=60.0
        )
        for _ in range(10):
            g.update(200.0, "sell", timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "CVAR_TAIL_BREACH"

    def test_cvar_reason_is_correct(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=5, alpha=0.8, cvar_threshold=20.0, cooldown_seconds=60.0
        )
        for _ in range(5):
            g.update(100.0, "sell", timestamp=time.monotonic())
        assert g.last_reason == "CVAR_TAIL_BREACH"


class TestWave361InvalidInput:
    """Any invalid input must immediately block with INPUT_VALIDATION_ERROR."""

    def test_negative_volume_blocks(self):
        g = Wave361TradeFlowCvarBreachGuard()
        g.update(-50.0, "buy", timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_bool_volume_blocks(self):
        g = Wave361TradeFlowCvarBreachGuard()
        g.update(True, "sell", timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_none_volume_blocks(self):
        g = Wave361TradeFlowCvarBreachGuard()
        g.update(None, "buy", timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_invalid_side_string_blocks(self):
        g = Wave361TradeFlowCvarBreachGuard()
        g.update(10.0, "SELL", timestamp=time.monotonic())  # wrong case
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_numeric_side_blocks(self):
        g = Wave361TradeFlowCvarBreachGuard()
        g.update(10.0, 1, timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_nan_volume_blocks(self):
        import math
        g = Wave361TradeFlowCvarBreachGuard()
        g.update(math.nan, "buy", timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_inf_volume_blocks(self):
        import math
        g = Wave361TradeFlowCvarBreachGuard()
        g.update(math.inf, "buy", timestamp=time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestWave361Reset:
    """reset() must clear rolling state and lift any active block."""

    def test_reset_clears_block(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=5, alpha=0.8, cvar_threshold=20.0, cooldown_seconds=300.0
        )
        for _ in range(5):
            g.update(100.0, "sell", timestamp=time.monotonic())
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""

    def test_reset_clears_window_so_no_block_on_partial_refill(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=5, alpha=0.8, cvar_threshold=20.0, cooldown_seconds=300.0
        )
        for _ in range(5):
            g.update(100.0, "sell", timestamp=time.monotonic())
        g.reset()
        # Only 3 ticks after reset -- window not full, no block
        for _ in range(3):
            g.update(100.0, "sell", timestamp=time.monotonic())
        assert not g.is_blocked()


class TestWave361IsEntryBlocked:
    """is_entry_blocked must delegate to is_blocked."""

    def test_is_entry_blocked_when_cvar_breached(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=5, alpha=0.8, cvar_threshold=20.0, cooldown_seconds=300.0
        )
        for _ in range(5):
            g.update(100.0, "sell", timestamp=time.monotonic())
        assert g.is_entry_blocked(bid=1.0, ask=1.0001)

    def test_is_entry_blocked_false_when_healthy(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=5, alpha=0.8, cvar_threshold=20.0, cooldown_seconds=0.0
        )
        for _ in range(10):
            g.update(1.0, "buy", timestamp=time.monotonic())
        assert not g.is_entry_blocked(bid=1.0, ask=1.0001)


class TestWave361IsBlockedExplicitTime:
    """is_blocked(current_time) must honour an explicit monotonic timestamp."""

    def test_explicit_time_past_cooldown_not_blocked(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=5, alpha=0.8, cvar_threshold=20.0, cooldown_seconds=10.0
        )
        for _ in range(5):
            g.update(100.0, "sell", timestamp=time.monotonic())
        assert g.is_blocked()
        far_future = time.monotonic() + 1000.0
        assert not g.is_blocked(current_time=far_future)


class TestBatch301ThreadSafety:
    """Concurrent updates must not raise or corrupt state."""

    def test_wave360_thread_safety(self):
        g = Wave360LobBidAskLevelCountAsymmetryGuard(
            window_size=10, ratio_threshold=3.0, cooldown_seconds=0.0
        )
        errors = []

        def worker():
            try:
                for _ in range(100):
                    g.update(5, 5, timestamp=time.monotonic())
                    g.is_blocked()
                    g.last_reason
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"Thread errors: {errors}"

    def test_wave361_thread_safety(self):
        g = Wave361TradeFlowCvarBreachGuard(
            window_size=10, alpha=0.9, cvar_threshold=50.0, cooldown_seconds=0.0
        )
        errors = []

        def worker():
            try:
                for i in range(100):
                    side = "buy" if i % 2 == 0 else "sell"
                    g.update(10.0, side, timestamp=time.monotonic())
                    g.is_blocked()
                    g.last_reason
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"Thread errors: {errors}"
