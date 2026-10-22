"""
test_batch256.py
----------------
Unit test suite for Batch 256:
- wave278_lob_depth_recovery_velocity_guard.py (Wave 278: LOB Inside-Queue Replenishment Speed Guard)
- wave279_trade_sign_entropy_rate_guard.py (Wave 279: Trade Sign Symbolic Entropy Rate & Information Predictability Guard)
"""

import math
import pytest
import time

import wave278_lob_depth_recovery_velocity_guard as w278
import wave279_trade_sign_entropy_rate_guard as w279


# ---------------------------------------------------------------------------
# Wave 278: LOB Depth Recovery Velocity Guard Tests
# ---------------------------------------------------------------------------

def test_wave278_rapid_replenishment_no_block():
    """Rapid replenishment velocities (> 2.5 lots/s) do not trigger block."""
    w278.reset()
    assert not w278.is_entry_blocked()
    assert not w278.is_blocked()

    # Ingest 10 healthy recoveries with velocity = 4.0 lots/s
    for _ in range(10):
        w278.record_recovery_velocity(4.0)
        assert not w278.is_entry_blocked()

    metrics = w278.get_recovery_metrics()
    assert metrics["mean_velocity"] >= 2.50
    assert not metrics["is_blocked"]


def test_wave278_sluggish_replenishment_blocks():
    """Mean recovery velocity <= 0.80 lots/s over 8 intervals triggers block."""
    w278.reset()
    assert not w278.is_entry_blocked()

    # Ingest 8 sluggish recoveries (0.50 lots/s)
    for _ in range(8):
        w278.record_recovery_velocity(0.50)

    assert w278.is_entry_blocked()
    assert w278.is_blocked()

    metrics = w278.get_recovery_metrics()
    assert metrics["mean_velocity"] <= 0.80
    assert metrics["is_blocked"] is True


def test_wave278_acute_replenishment_freeze_blocks():
    """Acute replenishment freeze (velocity <= 0.15 lots/s over >= 2.5s) triggers block."""
    w278.reset()
    assert not w278.is_entry_blocked()

    # Prev depth = 0.0, Curr depth = 0.20 lots, Delta t = 3.0s -> velocity = 0.20 / 3.0 = 0.067 lots/s
    w278.record_depth_transition(0.0, 0.20, 3.0)
    assert w278.is_entry_blocked()
    assert w278.is_blocked()

    metrics = w278.get_recovery_metrics()
    assert metrics["latest_velocity"] <= 0.15
    assert metrics["is_blocked"] is True


def test_wave278_insufficient_samples_no_block():
    """Fewer than 8 observations without acute freeze does not trip condition 1."""
    w278.reset()
    assert not w278.is_entry_blocked()

    # Ingest only 4 sluggish samples (duration < 2.5s to avoid acute freeze)
    for _ in range(4):
        w278.record_recovery_velocity(0.40)

    assert not w278.is_entry_blocked()


def test_wave278_input_validation_and_reset():
    """Invalid velocity inputs are rejected and reset restores normal state."""
    w278.reset()

    # Booleans and negative/invalid numbers rejected
    w278.record_recovery_velocity(True)  # type: ignore
    w278.record_recovery_velocity(False)  # type: ignore
    w278.record_recovery_velocity(float("nan"))
    w278.record_depth_transition(float("inf"), 5.0, 1.0)
    w278.record_depth_transition(5.0, 10.0, -1.0)
    w278.update(True)  # type: ignore
    assert not w278.is_entry_blocked()

    # Trip block and reset
    w278.record_depth_transition(0.0, 0.10, 3.0)
    assert w278.is_entry_blocked()

    w278.reset()
    assert not w278.is_entry_blocked()
    status = w278.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 279: Trade Sign Symbolic Entropy Rate Guard Tests
# ---------------------------------------------------------------------------

def test_wave279_unpredictable_trade_signs_no_block():
    """Unpredictable balanced signs yield high symbolic entropy rate and no block."""
    w279.reset()
    assert not w279.is_entry_blocked()
    assert not w279.is_blocked()

    # Pseudo-random balanced sequence: (+1, +1, -1, +1, -1, -1, +1, -1...)
    pattern = [1, 1, -1, 1, -1, -1, 1, -1, 1, 1, 1, -1, -1, 1, -1, 1, -1, -1, 1, 1, -1, 1, 1, -1, 1, -1, 1, 1]
    for s in pattern:
        w279.record_trade_sign(s)
        assert not w279.is_entry_blocked()

    metrics = w279.get_entropy_metrics()
    assert metrics["entropy_rate"] >= 0.70
    assert metrics["max_word_frequency"] <= 0.40
    assert not metrics["is_blocked"]


def test_wave279_symbolic_entropy_rate_collapse_blocks():
    """Deterministic repetition (all buys +1) collapses entropy rate <= 0.40 over 25 trades."""
    w279.reset()
    assert not w279.is_entry_blocked()

    # Ingest direct entropy rate collapse
    w279.record_entropy_rate(0.25, max_word_freq=0.50, sample_count=26)
    assert w279.is_entry_blocked()
    assert w279.is_blocked()

    metrics = w279.get_entropy_metrics()
    assert metrics["entropy_rate"] <= 0.40
    assert metrics["is_blocked"] is True


def test_wave279_acute_pattern_repetition_blocks():
    """Acute single 3-gram pattern repetition >= 0.65 over 18 trades triggers block."""
    w279.reset()
    assert not w279.is_entry_blocked()

    # 18 consecutive buy trades -> 100% frequency of (+1, +1, +1)
    for _ in range(18):
        w279.record_trade_sign(1)

    assert w279.is_entry_blocked()
    assert w279.is_blocked()

    metrics = w279.get_entropy_metrics()
    assert metrics["max_word_frequency"] >= 0.65
    assert metrics["is_blocked"] is True


def test_wave279_insufficient_trades_no_block():
    """Fewer than 18 trades without acute repetition does not trip condition 1."""
    w279.reset()
    assert not w279.is_entry_blocked()

    # Ingest only 10 trades of all buys
    for _ in range(10):
        w279.record_trade_sign(1)

    assert not w279.is_entry_blocked()


def test_wave279_input_validation_and_reset():
    """Invalid trade sign inputs are rejected and reset restores normal state."""
    w279.reset()

    # Booleans, zero signs, NaN rejected
    w279.record_trade_sign(True)  # type: ignore
    w279.record_trade_sign(False)  # type: ignore
    w279.record_trade_sign(0)
    w279.record_trade_sign(float("nan"))  # type: ignore
    w279.record_entropy_rate(float("inf"))
    w279.update(True)  # type: ignore
    assert not w279.is_entry_blocked()

    # Trip block and reset
    for _ in range(18):
        w279.record_trade_sign(1)
    assert w279.is_entry_blocked()

    w279.reset()
    assert not w279.is_entry_blocked()
    status = w279.get_status()
    assert status["is_blocked"] is False
