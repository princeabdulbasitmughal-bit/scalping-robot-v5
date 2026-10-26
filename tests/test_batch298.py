# tests/test_batch298.py
# Combined pytest suite for WAVE 354 and WAVE 355 guards.
# Self-contained: no external dependencies beyond the two guard modules.
# ASCII-only file. No live server calls.

import sys
import os
import time
import threading

import pytest

# ---------------------------------------------------------------------------
# Path setup so tests can be run from any working directory
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wave354_lob_inside_spread_microprice_drift_guard import (
    Wave354LobInsideSpreadMicropriceDriftGuard,
)
from wave355_trade_flow_volume_weighted_arrival_rate_surge_guard import (
    Wave355TradeFlowVolumeWeightedArrivalRateSurgeGuard,
)


# ===========================================================================
# Helpers
# ===========================================================================

def make_w354(**kwargs) -> Wave354LobInsideSpreadMicropriceDriftGuard:
    defaults = dict(drift_window=5, drift_threshold_bps=3.0, cooldown_seconds=1.0)
    defaults.update(kwargs)
    return Wave354LobInsideSpreadMicropriceDriftGuard(**defaults)


def make_w355(**kwargs) -> Wave355TradeFlowVolumeWeightedArrivalRateSurgeGuard:
    defaults = dict(window_size=5, surge_multiple=5.0, cooldown_seconds=1.0)
    defaults.update(kwargs)
    return Wave355TradeFlowVolumeWeightedArrivalRateSurgeGuard(**defaults)


# ===========================================================================
# WAVE 354 — LOB Inside-Spread Microprice Drift Guard Tests
# ===========================================================================

class TestWave354NoblockBeforeWindowFills:
    """Guard must NOT block before drift_window ticks have been observed."""

    def test_no_block_on_first_tick(self):
        g = make_w354(drift_window=5, drift_threshold_bps=0.001)
        g.update(bid=1.0, ask=1.002, bid_size=10, ask_size=10, timestamp=1.0)
        assert not g.is_blocked(current_time=time.monotonic())

    def test_no_block_before_two_ticks(self):
        """Drift can only be computed from tick 2 onward; 1 tick is never enough."""
        g = make_w354(drift_window=5, drift_threshold_bps=0.001)
        # single tick -> no drift recorded yet
        g.update(bid=1.0, ask=1.002, bid_size=10, ask_size=10, timestamp=1.0)
        assert not g.is_blocked(current_time=time.monotonic())


class TestWave354HappyPathNoBlock:
    """Stable microprice must not trigger a block."""

    def test_flat_microprice_no_block(self):
        g = make_w354(drift_window=5, drift_threshold_bps=3.0, cooldown_seconds=1.0)
        ts = 1.0
        for _ in range(10):
            # bid_size == ask_size -> microprice == mid -> no drift
            g.update(bid=1.0, ask=1.002, bid_size=10, ask_size=10, timestamp=ts)
            ts += 0.1
        assert not g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == ""


class TestWave354TriggerBlock:
    """Repeated upward microprice drift must breach threshold and block."""

    def test_large_drift_triggers_block(self):
        # Use a very low threshold so a deliberate drift always triggers.
        g = make_w354(drift_window=5, drift_threshold_bps=0.001, cooldown_seconds=60.0)
        ts = 1.0
        bid = 1.0
        # Feed ticks where bid keeps rising -> microprice drifts upward each tick.
        for i in range(6):
            g.update(bid=bid, ask=bid + 0.002, bid_size=10, ask_size=10, timestamp=ts)
            bid += 0.005
            ts += 0.1
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "MICROPRICE_DRIFT_BREACH"

    def test_block_lasts_for_cooldown(self):
        g = make_w354(drift_window=5, drift_threshold_bps=0.001, cooldown_seconds=60.0)
        ts = 1.0
        bid = 1.0
        for i in range(6):
            g.update(bid=bid, ask=bid + 0.002, bid_size=10, ask_size=10, timestamp=ts)
            bid += 0.005
            ts += 0.1
        # Check slightly in the future but still within 60 s cooldown.
        assert g.is_blocked(current_time=time.monotonic() + 5.0)


class TestWave354InvalidInputBlocks:
    """Any invalid input must immediately set INPUT_VALIDATION_ERROR."""

    def test_bool_bid_blocks(self):
        g = make_w354()
        g.update(bid=True, ask=1.002, bid_size=10, ask_size=10, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_string_ask_blocks(self):
        g = make_w354()
        g.update(bid=1.0, ask="bad", bid_size=10, ask_size=10, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_bid_size_blocks(self):
        g = make_w354()
        g.update(bid=1.0, ask=1.002, bid_size=-5, ask_size=10, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_zero_ask_size_blocks(self):
        g = make_w354()
        g.update(bid=1.0, ask=1.002, bid_size=10, ask_size=0, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_inverted_spread_blocks(self):
        # ask < bid is invalid
        g = make_w354()
        g.update(bid=1.005, ask=1.002, bid_size=10, ask_size=10, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_timestamp_blocks(self):
        g = make_w354()
        g.update(bid=1.0, ask=1.002, bid_size=10, ask_size=10, timestamp=-1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_none_volume_blocks(self):
        g = make_w354()
        g.update(bid=None, ask=1.002, bid_size=10, ask_size=10, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestWave354ResetClearsState:
    """reset() must lift any block and wipe all rolling state."""

    def test_reset_clears_block(self):
        g = make_w354(drift_window=5, drift_threshold_bps=0.001, cooldown_seconds=60.0)
        ts, bid = 1.0, 1.0
        for _ in range(6):
            g.update(bid=bid, ask=bid + 0.002, bid_size=10, ask_size=10, timestamp=ts)
            bid += 0.005
            ts += 0.1
        assert g.is_blocked(current_time=time.monotonic())
        g.reset()
        assert not g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == ""

    def test_reset_clears_drift_history(self):
        """After reset, a flat tick sequence should not trigger."""
        g = make_w354(drift_window=5, drift_threshold_bps=0.001, cooldown_seconds=60.0)
        ts, bid = 1.0, 1.0
        for _ in range(6):
            g.update(bid=bid, ask=bid + 0.002, bid_size=10, ask_size=10, timestamp=ts)
            bid += 0.005
            ts += 0.1
        g.reset()
        # Now send flat ticks; guard should not block.
        ts2 = time.monotonic()
        for _ in range(8):
            g.update(bid=2.0, ask=2.002, bid_size=10, ask_size=10, timestamp=ts2)
            ts2 += 0.1
        assert not g.is_blocked(current_time=time.monotonic())


class TestWave354IsEntryBlocked:
    """is_entry_blocked delegates correctly to is_blocked."""

    def test_is_entry_blocked_not_blocked(self):
        g = make_w354()
        ts = time.monotonic()
        assert not g.is_entry_blocked(bid=1.0, ask=1.002, ts=ts)

    def test_is_entry_blocked_after_invalid_input(self):
        g = make_w354()
        g.update(bid=True, ask=1.002, bid_size=10, ask_size=10, timestamp=1.0)
        ts = time.monotonic()
        assert g.is_entry_blocked(bid=1.0, ask=1.002, ts=ts)


# ===========================================================================
# WAVE 355 — Trade Flow VWAR Surge Guard Tests
# ===========================================================================

class TestWave355NoblockBeforeWindowFills:
    """Guard must not block on very first tick (no VWAR computable yet)."""

    def test_no_block_on_first_tick(self):
        g = make_w355()
        g.update(volume=100, timestamp=1.0)
        assert not g.is_blocked(current_time=time.monotonic())


class TestWave355HappyPathNoBlock:
    """Steady arrival rate should never trigger a surge block."""

    def test_steady_rate_no_block(self):
        g = make_w355(window_size=5, surge_multiple=5.0, cooldown_seconds=1.0)
        ts = 1.0
        for _ in range(12):
            g.update(volume=10.0, timestamp=ts)
            ts += 1.0  # constant 10 vol/s
        assert not g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == ""


class TestWave355TriggerBlock:
    """A sudden volume spike must trigger VWAR_SURGE_DETECTED."""

    def test_single_large_spike_triggers_block(self):
        g = make_w355(window_size=10, surge_multiple=5.0, cooldown_seconds=60.0)
        ts = 1.0
        # Feed 10 small ticks to build a stable mean VWAR ~10 vol/s.
        for _ in range(10):
            g.update(volume=10.0, timestamp=ts)
            ts += 1.0
        # Spike: 1000 vol in the same 1 s delta -> VWAR = 1000, mean ~10.
        # 1000 >= 5.0 * 10 -> should block.
        g.update(volume=1000.0, timestamp=ts)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "VWAR_SURGE_DETECTED"

    def test_block_lasts_for_cooldown(self):
        g = make_w355(window_size=10, surge_multiple=5.0, cooldown_seconds=60.0)
        ts = 1.0
        for _ in range(10):
            g.update(volume=10.0, timestamp=ts)
            ts += 1.0
        g.update(volume=1000.0, timestamp=ts)
        assert g.is_blocked(current_time=time.monotonic() + 30.0)


class TestWave355InvalidInputBlocks:
    """Any invalid input must immediately set INPUT_VALIDATION_ERROR."""

    def test_bool_volume_blocks(self):
        g = make_w355()
        g.update(volume=True, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_bool_timestamp_blocks(self):
        g = make_w355()
        g.update(volume=10.0, timestamp=True)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_volume_blocks(self):
        g = make_w355()
        g.update(volume=-1.0, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_zero_volume_blocks(self):
        g = make_w355()
        g.update(volume=0.0, timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_timestamp_blocks(self):
        g = make_w355()
        g.update(volume=10.0, timestamp=-5.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_non_monotonic_timestamp_blocks(self):
        g = make_w355()
        g.update(volume=10.0, timestamp=5.0)
        # Repeat same timestamp -> delta_t == 0 -> invalid.
        g.update(volume=10.0, timestamp=5.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_string_volume_blocks(self):
        g = make_w355()
        g.update(volume="big", timestamp=1.0)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_none_timestamp_blocks(self):
        g = make_w355()
        g.update(volume=10.0, timestamp=None)
        assert g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestWave355ResetClearsState:
    """reset() must lift the block and wipe rolling VWAR history."""

    def test_reset_lifts_block(self):
        g = make_w355(window_size=5, surge_multiple=5.0, cooldown_seconds=60.0)
        ts = 1.0
        for _ in range(5):
            g.update(volume=10.0, timestamp=ts)
            ts += 1.0
        g.update(volume=1000.0, timestamp=ts)
        assert g.is_blocked(current_time=time.monotonic())
        g.reset()
        assert not g.is_blocked(current_time=time.monotonic())
        assert g.last_reason == ""

    def test_reset_clears_vwar_history(self):
        g = make_w355(window_size=5, surge_multiple=5.0, cooldown_seconds=60.0)
        ts = 1.0
        for _ in range(5):
            g.update(volume=10.0, timestamp=ts)
            ts += 1.0
        g.update(volume=1000.0, timestamp=ts)
        g.reset()
        # After reset, steady ticks should not block.
        ts2 = time.monotonic()
        for _ in range(8):
            g.update(volume=10.0, timestamp=ts2)
            ts2 += 1.0
        assert not g.is_blocked(current_time=time.monotonic())


class TestWave355IsEntryBlocked:
    """is_entry_blocked delegates correctly to is_blocked."""

    def test_is_entry_blocked_not_blocked(self):
        g = make_w355()
        ts = time.monotonic()
        assert not g.is_entry_blocked(bid=1.0, ask=1.002, ts=ts)

    def test_is_entry_blocked_after_surge(self):
        g = make_w355(window_size=5, surge_multiple=5.0, cooldown_seconds=60.0)
        ts = 1.0
        for _ in range(5):
            g.update(volume=10.0, timestamp=ts)
            ts += 1.0
        g.update(volume=1000.0, timestamp=ts)
        ts_now = time.monotonic()
        assert g.is_entry_blocked(bid=1.0, ask=1.002, ts=ts_now)


# ===========================================================================
# Thread safety smoke test (both guards)
# ===========================================================================

class TestThreadSafety:
    """Concurrent updates must not raise exceptions or corrupt state."""

    def test_w354_concurrent_updates(self):
        g = make_w354(drift_window=10, drift_threshold_bps=3.0, cooldown_seconds=0.0)
        errors = []

        def worker():
            ts = time.monotonic()
            try:
                for _ in range(50):
                    g.update(bid=1.0, ask=1.002, bid_size=10, ask_size=10, timestamp=ts)
                    ts += 0.01
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"Thread errors: {errors}"

    def test_w355_concurrent_updates(self):
        g = make_w355(window_size=10, surge_multiple=5.0, cooldown_seconds=0.0)
        errors = []

        def worker():
            ts = time.monotonic()
            try:
                for _ in range(50):
                    g.update(volume=10.0, timestamp=ts)
                    ts += 0.05
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"Thread errors: {errors}"
