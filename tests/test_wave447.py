"""
tests/test_wave447.py
=====================
Pytest suite for Wave 447: Wave447QueueCancellationIntensityGuard.
Validates Limit Order Queue Cancellation Intensity Hazard Guard.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave447_queue_cancellation_intensity_guard import Wave447QueueCancellationIntensityGuard


def _make_guard(**kwargs):
    defaults = dict(
        window_size=40,
        max_cancellation_ratio=0.85,
        max_cancellation_intensity=50.0,
        min_events_for_decision=10
    )
    defaults.update(kwargs)
    return Wave447QueueCancellationIntensityGuard(**defaults)


def test_guard_initialization():
    g = _make_guard()
    assert g.window_size == 40
    assert g.max_cancellation_ratio == 0.85
    assert g.max_cancellation_intensity == 50.0
    assert not g.is_blocked()
    assert g.block_reason == ""
    assert g.cancellation_ratio == 0.0


def test_guard_invalid_initialization():
    with pytest.raises(ValueError, match="window_size must be >= 10"):
        Wave447QueueCancellationIntensityGuard(window_size=5)

    with pytest.raises(ValueError, match="max_cancellation_ratio must be in"):
        Wave447QueueCancellationIntensityGuard(max_cancellation_ratio=0.40)

    with pytest.raises(ValueError, match="max_cancellation_intensity must be > 0.0"):
        Wave447QueueCancellationIntensityGuard(max_cancellation_intensity=-1.0)


def test_invalid_event_inputs():
    g = _make_guard()
    with pytest.raises(ValueError, match="event_type must be one of"):
        g.update("UNKNOWN", 10.0, 100.0)

    with pytest.raises(ValueError, match="volume must be positive"):
        g.update("FILL", -5.0, 100.0)

    g.update("FILL", 10.0, 100.0)
    with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
        g.update("FILL", 10.0, 100.0)


def test_insufficient_sample_does_not_block():
    g = _make_guard()
    for i in range(8):
        blocked = g.update("CANCEL", 100.0, 100.0 + i)
        assert not blocked
    assert not g.is_blocked()
    assert g.block_reason == "INSUFFICIENT_SAMPLE"


def test_normal_execution_flow_does_not_block():
    """Balanced stream of limit adds and fills should not block."""
    g = _make_guard()
    t = 1000.0
    for i in range(20):
        # 3 fills per 1 cancel -> 25% cancel ratio
        evt_type = "CANCEL" if i % 4 == 0 else "FILL"
        g.update(evt_type, 10.0, t + i * 0.1)

    assert not g.is_blocked()
    assert g.cancellation_ratio < 0.85
    telem = g.get_telemetry()
    assert telem["guard"] == "Wave447QueueCancellationIntensityGuard"
    assert telem["events_buffered"] == 20


def test_phantom_liquidity_hazard_blocks():
    """Extreme cancellation ratio > 85% with >= 5 cancels blocks."""
    g = _make_guard(max_cancellation_ratio=0.80)
    t = 2000.0
    # 9 cancels of 100 units, 1 fill of 10 units -> 900 / 910 = 98.9%
    for i in range(9):
        g.update("CANCEL", 100.0, t + i * 0.2)
    g.update("FILL", 10.0, t + 9 * 0.2)

    assert g.is_blocked()
    assert "PHANTOM_LIQUIDITY_HAZARD" in g.block_reason
    assert g.is_entry_blocked("BUY")
    assert g.is_entry_blocked("SELL")


def test_quote_stuffing_burst_blocks():
    """Very rapid cancellation burst exceeding max_cancellation_intensity blocks."""
    g = _make_guard(max_cancellation_intensity=40.0, max_cancellation_ratio=0.85)
    t = 3000.0
    # Alternating CANCEL and FILL: 10 cancels + 10 fills in 0.10s
    # Cancel ratio = 50% (< 85%), but cancel count = 10 in 0.10s = 100 cancels/sec (> 40.0)
    for i in range(20):
        evt_type = "CANCEL" if i % 2 == 0 else "FILL"
        g.update(evt_type, 1.0, t + i * 0.005)

    assert g.is_blocked()
    assert "QUOTE_STUFFING_BURST" in g.block_reason


def test_reset_behavior():
    g = _make_guard(max_cancellation_ratio=0.80)
    t = 4000.0
    for i in range(10):
        g.update("CANCEL", 100.0, t + i * 0.1)

    assert g.is_blocked()
    g.reset()
    assert not g.is_blocked()
    assert g.block_reason == ""
    assert g.cancellation_ratio == 0.0
    assert g.cancellation_intensity == 0.0
    assert len(g._events) == 0
