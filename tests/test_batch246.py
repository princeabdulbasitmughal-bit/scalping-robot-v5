"""
test_batch246.py
----------------
Unit test suite for Batch 246:
- wave258_hf_price_jump_intensity_guard.py (Wave 258: High-Frequency Price Jump Intensity & Cascade Arrival Guard)
- wave259_lob_quote_resilience_half_life_guard.py (Wave 259: Order Book Quote Depth Resilience Half-Life Guard)
"""

import math
import pytest
import time

import wave258_hf_price_jump_intensity_guard as w258
import wave259_lob_quote_resilience_half_life_guard as w259


# ---------------------------------------------------------------------------
# Wave 258: High-Frequency Price Jump Intensity & Cascade Arrival Guard Tests
# ---------------------------------------------------------------------------

def test_wave258_normal_continuous_prices_no_block():
    """Calm price changes (< 1 bps) do not trigger jump intensity guard."""
    w258.reset()
    assert not w258.is_entry_blocked()
    assert not w258.is_blocked()

    base_price = 2400.00
    t = 1000.0
    for i in range(15):
        # Tick movements of +/- 0.05 on 2400 is ~0.20 bps (far below 2.50 bps)
        p = base_price + (i % 3) * 0.05
        w258.record_price(p, ts=t + i * 1.0)
        assert not w258.is_entry_blocked()

    metrics = w258.get_jump_metrics()
    assert metrics["jump_count_window"] == 0
    assert not metrics["is_blocked"]


def test_wave258_jump_intensity_cascade_blocks():
    """Four jumps >= 2.50 bps within 30s triggers jump intensity cascade block."""
    w258.reset()
    assert not w258.is_entry_blocked()

    # Base price 2000.0: 1 bps = 0.20. 2.50 bps = 0.50 price jump
    t = 2000.0
    w258.record_price(2000.0, ts=t)

    # Jump 1: +0.60 (3.0 bps) at t+2
    w258.record_price(2000.60, ts=t + 2.0)
    assert not w258.is_entry_blocked()

    # Jump 2: -0.60 (3.0 bps) at t+6 (spaced > 3s to avoid acute double jump)
    w258.record_price(2000.00, ts=t + 6.0)
    assert not w258.is_entry_blocked()

    # Jump 3: +0.60 (3.0 bps) at t+10
    w258.record_price(2000.60, ts=t + 10.0)
    assert not w258.is_entry_blocked()

    # Jump 4: -0.60 (3.0 bps) at t+14 -> hits MAX_JUMP_COUNT = 4
    w258.record_price(2000.00, ts=t + 14.0)
    assert w258.is_entry_blocked()
    assert w258.is_blocked()

    metrics = w258.get_jump_metrics()
    assert metrics["jump_count_window"] == 4
    assert metrics["is_blocked"] is True


def test_wave258_acute_jump_burst_blocks():
    """Two acute jumps >= 3.50 bps within 3.0s triggers acute burst block."""
    w258.reset()
    assert not w258.is_entry_blocked()

    t = 3000.0
    w258.record_price(2000.0, ts=t)

    # Acute jump 1: +0.80 on 2000 is 4.0 bps (>= 3.50 bps)
    w258.record_price(2000.80, ts=t + 1.0)
    assert not w258.is_entry_blocked()

    # Acute jump 2: -0.80 on 2000.80 is ~4.0 bps, occurring 1.5s later (<= 3.0s window)
    w258.record_price(2000.00, ts=t + 2.5)
    assert w258.is_entry_blocked()


def test_wave258_isolated_spaced_jumps_no_block():
    """Jumps spaced > 30s are purged and do not accumulate to trigger block."""
    w258.reset()
    assert not w258.is_entry_blocked()

    t = 4000.0
    # Ingest direct jumps spaced 35s apart
    w258.record_jump(2.80, ts=t)
    assert not w258.is_entry_blocked()

    w258.record_jump(2.80, ts=t + 35.0)
    assert not w258.is_entry_blocked()

    w258.record_jump(2.80, ts=t + 70.0)
    assert not w258.is_entry_blocked()


def test_wave258_input_validation_and_reset():
    """Invalid inputs are rejected and reset restores normal state."""
    w258.reset()

    # Booleans and invalid values rejected
    w258.record_price(True)  # type: ignore
    w258.record_price(False)  # type: ignore
    w258.record_price(-100.0)
    w258.record_price(0.0)
    w258.record_price(float("nan"))
    w258.record_price(float("inf"))
    w258.record_jump("invalid")  # type: ignore
    w258.update(True)  # type: ignore
    assert not w258.is_entry_blocked()

    # Trip block and reset
    w258.record_jump(4.00, ts=100.0)
    w258.record_jump(4.00, ts=101.0)
    assert w258.is_entry_blocked()

    w258.reset()
    assert not w258.is_entry_blocked()
    status = w258.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 259: Order Book Quote Depth Resilience Half-Life Guard Tests
# ---------------------------------------------------------------------------

def test_wave259_healthy_fast_replenishment_no_block():
    """Sub-second replenishment latencies do not trigger resilience block."""
    w259.reset()
    assert not w259.is_entry_blocked()
    assert not w259.is_blocked()

    # Ingest fast recoveries of 0.20s - 0.40s
    for d in [0.25, 0.30, 0.20, 0.35, 0.22, 0.28]:
        w259.record_recovery_duration(d)
        assert not w259.is_entry_blocked()

    metrics = w259.get_resilience_metrics()
    assert metrics["recovery_events_count"] == 6
    assert metrics["mean_recovery_sec"] < 1.00
    assert not metrics["is_blocked"]


def test_wave259_sluggish_replenishment_persistence_blocks():
    """Average recovery latency >= 2.00s over 5 samples triggers block."""
    w259.reset()
    assert not w259.is_entry_blocked()

    # Ingest 5 sluggish recoveries of 2.50s
    for _ in range(5):
        w259.record_recovery_duration(2.50)

    assert w259.is_entry_blocked()
    assert w259.is_blocked()

    metrics = w259.get_resilience_metrics()
    assert metrics["mean_recovery_sec"] >= 2.00
    assert metrics["is_blocked"] is True


def test_wave259_acute_unrecovered_liquidity_hole_blocks():
    """Severe depth drop (<= 40% baseline) unrecovered for >= 3.0s triggers block."""
    w259.reset()
    assert not w259.is_entry_blocked()

    # Seed baseline depth with 10 lots total (5 bid, 5 ask)
    t = 1000.0
    for i in range(8):
        w259.record_depths(5.0, 5.0, ts=t + i * 1.0)
    assert not w259.is_entry_blocked()

    # Depletion event: drop to 1.5 lots total (0.75 bid, 0.75 ask) -> 15% of 10 lots
    w259.record_depths(0.75, 0.75, ts=t + 10.0)
    assert not w259.is_entry_blocked()

    # Still unrecovered after 3.5 seconds (t+13.5)
    w259.record_depths(0.75, 0.75, ts=t + 13.5)
    assert w259.is_entry_blocked()
    assert w259.is_blocked()


def test_wave259_insufficient_samples_no_block():
    """Fewer than 5 recovery events does not trip sluggish persistence condition."""
    w259.reset()
    assert not w259.is_entry_blocked()

    # Only 3 samples of high duration
    w259.record_recovery_duration(3.00)
    w259.record_recovery_duration(3.00)
    w259.record_recovery_duration(3.00)
    assert not w259.is_entry_blocked()


def test_wave259_input_validation_and_reset():
    """Invalid depth/duration inputs are rejected and reset clears state."""
    w259.reset()

    # Booleans and negative/invalid numbers rejected
    w259.record_depths(True, 5.0)  # type: ignore
    w259.record_depths(5.0, False)  # type: ignore
    w259.record_depths(-1.0, 5.0)
    w259.record_depths(float("nan"), 5.0)
    w259.record_recovery_duration(-5.0)
    w259.record_recovery_duration(float("inf"))
    w259.update(True)  # type: ignore
    assert not w259.is_entry_blocked()

    # Trip block and reset
    for _ in range(5):
        w259.record_recovery_duration(2.80)
    assert w259.is_entry_blocked()

    w259.reset()
    assert not w259.is_entry_blocked()
    status = w259.get_status()
    assert status["is_blocked"] is False
