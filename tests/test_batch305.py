"""
tests/test_batch305.py
Combined pytest test suite for WAVE 368 and WAVE 369 guards.

Covers:
  - No-block before window/warm-up fills
  - Happy-path no-block
  - Trigger block (iceberg pattern / extreme SVMO)
  - Invalid input blocks (fail-closed)
  - reset() clears all state
  - is_entry_blocked delegates correctly
  - Monotonic cooldown behaviour
  - Bool validation ordering
  - NaN rejection
  - Side validation (wave 369)
  - Consecutive resets
  - Thread-safety smoke test
"""

import math
import sys
import threading
import time
import types

import pytest

# ---------------------------------------------------------------------------
# Import both guards from the project root (E:\scalping-robot-v5)
# ---------------------------------------------------------------------------
sys.path.insert(0, r"E:\scalping-robot-v5")

from wave368_lob_hidden_liquidity_iceberg_detection_guard import (
    Wave368LobHiddenLiquidityIcebergDetectionGuard,
)
from wave369_trade_flow_signed_volume_momentum_oscillator_guard import (
    Wave369TradeFlowSignedVolumeMomentumOscillatorGuard,
)

# ===========================================================================
# Helpers
# ===========================================================================

def _now() -> float:
    return time.monotonic()


# ===========================================================================
# WAVE 368 -- Iceberg Detection Guard tests
# ===========================================================================

class TestWave368Iceberg:

    # --- Test 1: No block before window fills ---
    def test_no_block_before_window_fills(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard(
            window_size=20, min_iceberg_count=3, cooldown_seconds=60.0
        )
        ts = _now()
        # Send normal ticks without trade -- should never block
        for i in range(15):
            g.update(bid_size=100.0, ask_size=100.0, trade_occurred=False, timestamp=ts + i)
        assert not g.is_blocked()

    # --- Test 2: Happy path -- no iceberg signal ---
    def test_happy_path_no_block(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard(
            window_size=20, recovery_ratio=0.8, min_iceberg_count=3, cooldown_seconds=60.0
        )
        ts = _now()
        # Trade occurred but bid size does NOT recover -- no iceberg
        g.update(bid_size=100.0, ask_size=100.0, trade_occurred=False, timestamp=ts)
        g.update(bid_size=100.0, ask_size=100.0, trade_occurred=True, timestamp=ts + 1)
        # Post-trade: bid_size DOES NOT recover (stays low)
        g.update(bid_size=30.0, ask_size=100.0, trade_occurred=False, timestamp=ts + 2)
        assert not g.is_blocked()

    # --- Test 3: Trigger iceberg block ---
    def test_trigger_iceberg_block(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard(
            window_size=20, recovery_ratio=0.8, min_iceberg_count=3, cooldown_seconds=60.0
        )
        ts = _now()

        def _iceberg_tick(t_base, i):
            """One iceberg cycle: normal -> trade -> recovery."""
            g.update(bid_size=100.0, ask_size=100.0, trade_occurred=False, timestamp=t_base + i * 3)
            g.update(bid_size=50.0, ask_size=100.0, trade_occurred=True, timestamp=t_base + i * 3 + 1)
            g.update(bid_size=90.0, ask_size=100.0, trade_occurred=False, timestamp=t_base + i * 3 + 2)

        for i in range(3):
            _iceberg_tick(ts, i)

        assert g.is_blocked()
        assert g.last_reason == "ICEBERG_PATTERN_DETECTED"

    # --- Test 4: Invalid bid_size (None) blocks with INPUT_VALIDATION_ERROR ---
    def test_invalid_bid_size_none_blocks(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard()
        ts = _now()
        g.update(bid_size=None, ask_size=100.0, trade_occurred=False, timestamp=ts)  # type: ignore[arg-type]
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 5: Invalid trade_occurred (int instead of bool) blocks ---
    def test_invalid_trade_occurred_type_blocks(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard()
        ts = _now()
        g.update(bid_size=100.0, ask_size=100.0, trade_occurred=1, timestamp=ts)  # type: ignore[arg-type]
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 6: Bool bid_size is rejected (bool before int/float check) ---
    def test_bool_bid_size_rejected(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard()
        ts = _now()
        g.update(bid_size=True, ask_size=100.0, trade_occurred=False, timestamp=ts)  # type: ignore[arg-type]
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 7: Negative bid_size blocks ---
    def test_negative_bid_size_blocks(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard()
        ts = _now()
        g.update(bid_size=-1.0, ask_size=100.0, trade_occurred=False, timestamp=ts)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 8: NaN timestamp blocks ---
    def test_nan_timestamp_blocks(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard()
        g.update(bid_size=100.0, ask_size=100.0, trade_occurred=False, timestamp=float("nan"))
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 9: reset() clears block and all state ---
    def test_reset_clears_state(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard(
            window_size=20, min_iceberg_count=3, cooldown_seconds=60.0
        )
        ts = _now()

        def _iceberg_tick(t_base, i):
            g.update(bid_size=100.0, ask_size=100.0, trade_occurred=False, timestamp=t_base + i * 3)
            g.update(bid_size=50.0, ask_size=100.0, trade_occurred=True, timestamp=t_base + i * 3 + 1)
            g.update(bid_size=90.0, ask_size=100.0, trade_occurred=False, timestamp=t_base + i * 3 + 2)

        for i in range(3):
            _iceberg_tick(ts, i)

        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""

    # --- Test 10: is_entry_blocked delegates to is_blocked ---
    def test_is_entry_blocked_delegates(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard()
        ts = _now()
        # Not blocked yet
        assert not g.is_entry_blocked(bid=1.0, ask=1.0, ts=ts)
        # Force block via invalid input
        g.update(bid_size=None, ask_size=1.0, trade_occurred=False, timestamp=ts)  # type: ignore[arg-type]
        assert g.is_entry_blocked(bid=1.0, ask=1.0, ts=ts)

    # --- Test 11: Cooldown monotonic -- block expires after cooldown ---
    def test_cooldown_expires(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard(cooldown_seconds=0.0)
        g.update(bid_size=None, ask_size=1.0, trade_occurred=False, timestamp=_now())  # type: ignore[arg-type]
        # With cooldown=0 the block should already have expired
        assert not g.is_blocked()

    # --- Test 12: Consecutive resets leave guard clean ---
    def test_consecutive_resets(self):
        g = Wave368LobHiddenLiquidityIcebergDetectionGuard()
        g.reset()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""


# ===========================================================================
# WAVE 369 -- SVMO Guard tests
# ===========================================================================

class TestWave369SVMO:

    # --- Test 13: No block before slow_period ticks ---
    def test_no_block_before_warmup(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard(
            fast_period=5, slow_period=20, oscillator_threshold=500.0, cooldown_seconds=45.0
        )
        ts = _now()
        for i in range(19):
            g.update(volume=1000.0, side="buy", timestamp=ts + i)
        # Only 19 ticks (< slow_period=20) -- must not block regardless of signal
        assert not g.is_blocked()

    # --- Test 14: Happy path -- balanced flow does not block ---
    def test_balanced_flow_no_block(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard(
            fast_period=5, slow_period=20, oscillator_threshold=500.0, cooldown_seconds=45.0
        )
        ts = _now()
        # Alternating buy/sell keeps EMA difference near zero
        for i in range(30):
            side = "buy" if i % 2 == 0 else "sell"
            g.update(volume=10.0, side=side, timestamp=ts + i)
        assert not g.is_blocked()

    # --- Test 15: Trigger SVMO block on extreme buy momentum ---
    def test_trigger_extreme_buy_momentum(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard(
            fast_period=5, slow_period=20, oscillator_threshold=500.0, cooldown_seconds=45.0
        )
        ts = _now()
        # Baseline ticks followed by massive surge to diverge fast EMA from slow EMA
        for i in range(20):
            g.update(volume=10.0, side="buy", timestamp=ts + i)
        for i in range(20, 25):
            g.update(volume=10_000.0, side="buy", timestamp=ts + i)
        assert g.is_blocked()
        assert g.last_reason == "SVMO_EXTREME_MOMENTUM"

    # --- Test 16: Trigger SVMO block on extreme sell momentum ---
    def test_trigger_extreme_sell_momentum(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard(
            fast_period=5, slow_period=20, oscillator_threshold=500.0, cooldown_seconds=45.0
        )
        ts = _now()
        for i in range(20):
            g.update(volume=10.0, side="sell", timestamp=ts + i)
        for i in range(20, 25):
            g.update(volume=10_000.0, side="sell", timestamp=ts + i)
        assert g.is_blocked()
        assert g.last_reason == "SVMO_EXTREME_MOMENTUM"

    # --- Test 17: Invalid side blocks with INPUT_VALIDATION_ERROR ---
    def test_invalid_side_blocks(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard()
        ts = _now()
        g.update(volume=100.0, side="long", timestamp=ts)  # type: ignore[arg-type]
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 18: Bool volume rejected before int/float check ---
    def test_bool_volume_rejected(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard()
        ts = _now()
        g.update(volume=True, side="buy", timestamp=ts)  # type: ignore[arg-type]
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 19: Zero volume blocks (must be > 0) ---
    def test_zero_volume_blocks(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard()
        ts = _now()
        g.update(volume=0.0, side="buy", timestamp=ts)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 20: NaN volume blocks ---
    def test_nan_volume_blocks(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard()
        ts = _now()
        g.update(volume=float("nan"), side="buy", timestamp=ts)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # --- Test 21: reset() clears block and EMA state ---
    def test_reset_clears_state(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard(
            fast_period=5, slow_period=20, oscillator_threshold=500.0, cooldown_seconds=45.0
        )
        ts = _now()
        for i in range(20):
            g.update(volume=10.0, side="buy", timestamp=ts + i)
        for i in range(20, 25):
            g.update(volume=10_000.0, side="buy", timestamp=ts + i)
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""
        # After reset tick count should be zero -- small volumes must NOT block
        for i in range(5):
            g.update(volume=1.0, side="sell", timestamp=ts + 100 + i)
        assert not g.is_blocked()

    # --- Test 22: is_entry_blocked delegates correctly ---
    def test_is_entry_blocked_delegates(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard()
        ts = _now()
        assert not g.is_entry_blocked(bid=1.0, ask=1.0, ts=ts)
        g.update(volume=float("nan"), side="buy", timestamp=ts)
        assert g.is_entry_blocked(bid=1.0, ask=1.0, ts=ts)

    # --- Test 23: Cooldown with zero seconds expires immediately ---
    def test_cooldown_zero_expires(self):
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard(cooldown_seconds=0.0)
        ts = _now()
        g.update(volume=float("nan"), side="buy", timestamp=ts)
        assert not g.is_blocked()

    # --- Test 24: Thread safety smoke test ---
    def test_thread_safety_smoke(self):
        """Run updates from multiple threads without crashing."""
        g = Wave369TradeFlowSignedVolumeMomentumOscillatorGuard(
            fast_period=5, slow_period=10, oscillator_threshold=1e9, cooldown_seconds=1.0
        )
        errors: list[Exception] = []

        def worker():
            try:
                ts = _now()
                for i in range(50):
                    side = "buy" if i % 2 == 0 else "sell"
                    g.update(volume=float(i + 1), side=side, timestamp=ts + i)
                    _ = g.is_blocked()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
