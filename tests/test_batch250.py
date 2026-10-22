"""
test_batch250.py
----------------
Unit test suite for Batch 250:
- wave266_lob_queue_imbalance_momentum_guard.py (Wave 266: LOB Top-of-Book Queue Imbalance Momentum & Flow Velocity Guard)
- wave267_trade_arrival_poisson_overdispersion_guard.py (Wave 267: Trade Arrival Poisson Overdispersion & Negative Binomial Clustering Guard)
"""

import math
import pytest
import time

import wave266_lob_queue_imbalance_momentum_guard as w266
import wave267_trade_arrival_poisson_overdispersion_guard as w267


# ---------------------------------------------------------------------------
# Wave 266: LOB Queue Imbalance Momentum Guard Tests
# ---------------------------------------------------------------------------

def test_wave266_balanced_queues_no_block():
    """Balanced bid and ask queues do not trigger imbalance block."""
    w266.reset()
    assert not w266.is_entry_blocked()
    assert not w266.is_blocked()

    # 5.0 lots bid, 5.0 lots ask -> imbalance = 0.0
    for i in range(10):
        w266.record_depths(5.0, 5.0, ts=1000.0 + i * 1.0)
        assert not w266.is_entry_blocked()

    metrics = w266.get_imbalance_metrics()
    assert abs(metrics["latest_imbalance"]) < 0.10
    assert not metrics["is_blocked"]


def test_wave266_severe_imbalance_blocks():
    """Directional imbalance >= 0.80 with depth >= 5.0 lots triggers block."""
    w266.reset()
    assert not w266.is_entry_blocked()

    # 9.0 lots bid, 1.0 lot ask -> imbalance = 8.0/10.0 = 0.80, total depth = 10.0
    w266.record_depths(9.0, 1.0, ts=2000.0)
    assert w266.is_entry_blocked()
    assert w266.is_blocked()

    metrics = w266.get_imbalance_metrics()
    assert metrics["latest_imbalance"] >= 0.80
    assert metrics["is_blocked"] is True


def test_wave266_explosive_imbalance_velocity_blocks():
    """Explosive imbalance velocity >= 1.50 units/s with swing >= 0.60 triggers block."""
    w266.reset()
    assert not w266.is_entry_blocked()

    t = 3000.0
    # Initial: 3.5 bid, 2.5 ask -> imbalance = 1.0 / 6.0 = +0.167
    w266.record_depths(3.5, 2.5, ts=t)
    assert not w266.is_entry_blocked()

    # 0.20s later, flips to 1.0 bid, 5.0 ask -> imbalance = -4.0 / 6.0 = -0.667
    # Delta I = -0.833, velocity = -0.833 / 0.20 = -4.167 units/s
    w266.record_depths(1.0, 5.0, ts=t + 0.20)
    assert w266.is_entry_blocked()
    assert w266.is_blocked()


def test_wave266_acute_flank_blanking_blocks():
    """One flank blanked (<= 0.15 lots) while opposing flank heavy (>= 6.0 lots) triggers block."""
    w266.reset()
    assert not w266.is_entry_blocked()

    w266.record_depths(0.10, 8.0, ts=4000.0)
    assert w266.is_entry_blocked()
    assert w266.is_blocked()


def test_wave266_input_validation_and_reset():
    """Invalid depth inputs are rejected and reset restores normal state."""
    w266.reset()

    # Booleans and invalid values rejected
    w266.record_depths(True, 5.0)  # type: ignore
    w266.record_depths(5.0, False)  # type: ignore
    w266.record_depths(-1.0, 5.0)
    w266.record_depths(5.0, float("nan"))
    w266.record_imbalance(float("inf"))
    w266.update(True)  # type: ignore
    assert not w266.is_entry_blocked()

    # Trip block and reset
    w266.record_imbalance(0.90, total_depth=8.0)
    assert w266.is_entry_blocked()

    w266.reset()
    assert not w266.is_entry_blocked()
    status = w266.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 267: Trade Arrival Poisson Overdispersion Guard Tests
# ---------------------------------------------------------------------------

def test_wave267_uniform_poisson_arrivals_no_block():
    """Uniform arrivals across bins produce low overdispersion and no block."""
    w267.reset()
    assert not w267.is_entry_blocked()
    assert not w267.is_blocked()

    # 10 trades spaced 2.0s apart (1 per bin across 20s window)
    t = 1000.0
    for i in range(10):
        w267.record_trade(ts=t + i * 2.0)
        assert not w267.is_entry_blocked()

    metrics = w267.get_dispersion_metrics()
    assert metrics["overdispersion_ratio"] <= 1.50
    assert not metrics["is_blocked"]


def test_wave267_poisson_overdispersion_explosion_blocks():
    """Overdispersion ratio >= 3.20 with mean count >= 3.0 triggers block."""
    w267.reset()
    assert not w267.is_entry_blocked()

    # Direct ingestion of extreme overdispersion
    w267.record_overdispersion(4.50, mean_count=3.5, acute_bin_count=12)
    assert w267.is_entry_blocked()
    assert w267.is_blocked()

    metrics = w267.get_dispersion_metrics()
    assert metrics["overdispersion_ratio"] >= 3.20
    assert metrics["is_blocked"] is True


def test_wave267_acute_trade_avalanche_blocks():
    """Acute trade avalanche of >= 20 trades in a single 2.0s bin triggers block."""
    w267.reset()
    assert not w267.is_entry_blocked()

    t = 2000.0
    # Ingest 22 trades within 1.0s (all in the same 2.0s bin)
    for i in range(22):
        w267.record_trade(ts=t + i * 0.04)

    assert w267.is_entry_blocked()
    assert w267.is_blocked()

    metrics = w267.get_dispersion_metrics()
    assert metrics["max_bin_count"] >= 20
    assert metrics["is_blocked"] is True


def test_wave267_insufficient_mean_count_no_block():
    """High overdispersion with mean count < 3.0 does not trip condition 1."""
    w267.reset()
    assert not w267.is_entry_blocked()

    # Direct ingestion with low mean count (e.g. 1.2 trades/bin)
    w267.record_overdispersion(5.00, mean_count=1.2, acute_bin_count=8)
    assert not w267.is_entry_blocked()


def test_wave267_input_validation_and_reset():
    """Invalid trade inputs are rejected and reset restores normal state."""
    w267.reset()

    # Booleans and invalid values rejected
    w267.record_trade(ts=True)  # type: ignore
    w267.record_trade(ts=float("nan"))
    w267.record_overdispersion(float("inf"))
    w267.update(ts=True)  # type: ignore
    assert not w267.is_entry_blocked()

    # Trip block and reset
    w267.record_overdispersion(4.00, mean_count=4.0, acute_bin_count=22)
    assert w267.is_entry_blocked()

    w267.reset()
    assert not w267.is_entry_blocked()
    status = w267.get_status()
    assert status["is_blocked"] is False
