"""
tests/test_batch257.py
----------------------
Unit tests for Batch 257:
  - Wave 280: Wave280LobQueueAgeDecayGuard
  - Wave 281: Wave281TradeSizeClusteringDispersionGuard
"""

import math
import time
import pytest

from wave280_lob_queue_age_decay_guard import Wave280LobQueueAgeDecayGuard
from wave281_trade_size_clustering_dispersion_guard import Wave281TradeSizeClusteringDispersionGuard


# ----------------------------------------------------------------------
# Wave 280 Tests: LOB Inside-Queue Quote Age & Stale Depth Attrition Guard
# ----------------------------------------------------------------------

def test_wave280_fresh_quotes_no_block():
    guard = Wave280LobQueueAgeDecayGuard(
        max_mean_quote_age_sec=12.0,
        min_stale_spread_bps=2.50,
        min_samples=8,
        acute_stale_age_sec=25.0,
    )

    # Dynamic resting quotes refreshing every 0.50s - 1.50s with narrow spread 1.0 bps
    for _ in range(12):
        guard.record_quote_age(age_seconds=1.2, spread_bps=1.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_quote_age_metrics()
    assert metrics["mean_quote_age_sec"] == pytest.approx(1.2, rel=1e-2)
    assert not metrics["is_blocked"]


def test_wave280_stale_quote_accumulation_blocks():
    guard = Wave280LobQueueAgeDecayGuard(
        max_mean_quote_age_sec=12.0,
        min_stale_spread_bps=2.50,
        min_samples=8,
        cooldown_seconds=45.0,
    )

    # 10 stale quotes averaging 14.0 seconds with spread 3.0 bps
    for _ in range(10):
        guard.record_quote_age(age_seconds=14.0, spread_bps=3.0)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "STALE_DEPTH_PERSISTENCE" in metrics["last_block_reason"]


def test_wave280_acute_stale_trap_blocks():
    guard = Wave280LobQueueAgeDecayGuard(
        acute_stale_age_sec=25.0,
        cooldown_seconds=45.0,
    )

    # Single acute resting duration of 28.0 seconds without update
    guard.record_quote_age(age_seconds=28.0, spread_bps=1.5)

    assert guard.is_entry_blocked()
    metrics = guard.get_quote_age_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_STALE_TRAP" in metrics["last_block_reason"]


def test_wave280_insufficient_samples_no_block():
    guard = Wave280LobQueueAgeDecayGuard(
        max_mean_quote_age_sec=12.0,
        min_stale_spread_bps=2.50,
        min_samples=8,
    )

    # Elevated quote age (15.0s) but only 4 samples (< 8 min_samples)
    for _ in range(4):
        guard.record_quote_age(age_seconds=15.0, spread_bps=3.0)

    assert not guard.is_entry_blocked()


def test_wave280_input_validation_and_reset():
    guard = Wave280LobQueueAgeDecayGuard()

    # Boolean input triggers fail-closed
    guard.record_quote_age(True)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Corrupted touch prices trigger fail-closed
    guard.record_touch_update(bid_price=-10.0, ask_price=100.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 281 Tests: Trade Size Gini Dispersion Guard
# ----------------------------------------------------------------------

def test_wave281_organic_dispersion_no_block():
    guard = Wave281TradeSizeClusteringDispersionGuard(
        min_gini_coefficient=0.12,
        max_gini_coefficient=0.88,
        min_trades=15,
    )

    # Diverse, heterogeneous trade sizes (0.5, 1.0, 2.5, 0.8, 3.2 lots)
    sizes = [0.5, 1.0, 2.5, 0.8, 3.2, 1.5, 0.2, 4.0, 1.2, 2.0, 0.7, 3.0, 1.8, 0.9, 2.2, 1.1]
    for s in sizes:
        guard.record_trade_size(s)
        assert not guard.is_entry_blocked()

    metrics = guard.get_dispersion_metrics()
    assert 0.20 <= metrics["gini_coefficient"] <= 0.65
    assert not metrics["is_blocked"]


def test_wave281_algorithmic_slicing_concentration_blocks():
    guard = Wave281TradeSizeClusteringDispersionGuard(
        min_gini_coefficient=0.12,
        min_trades=15,
        cooldown_seconds=45.0,
    )

    # Identical child orders sliced to 1.00 lots (Gini = 0.0)
    # Use direct precomputed metrics or 18 identical trades
    guard.record_dispersion_metrics(gini_coeff=0.05, max_size=1.0, streak_len=1, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "ALGORITHMIC_SLICING_CONCENTRATION" in metrics["last_block_reason"]


def test_wave281_whale_inequality_blocks():
    guard = Wave281TradeSizeClusteringDispersionGuard(
        max_gini_coefficient=0.88,
        min_whale_size=12.0,
        min_trades=15,
        cooldown_seconds=45.0,
    )

    # Extremely skewed distribution with a 25.0 lot whale print swamping tiny trades
    guard.record_dispersion_metrics(gini_coeff=0.92, max_size=25.0, streak_len=1, sample_count=16)

    assert guard.is_entry_blocked()
    metrics = guard.get_dispersion_metrics()
    assert metrics["is_blocked"]
    assert "WHALE_INEQUALITY_SKEW" in metrics["last_block_reason"]


def test_wave281_acute_identical_streak_blocks():
    guard = Wave281TradeSizeClusteringDispersionGuard(
        acute_streak_len=8,
        cooldown_seconds=45.0,
    )

    # 8 consecutive trades of exactly 0.50 lots
    for _ in range(8):
        guard.record_trade_size(0.50)

    assert guard.is_entry_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "ACUTE_IDENTICAL_STREAK" in metrics["last_block_reason"]


def test_wave281_input_validation_and_reset():
    guard = Wave281TradeSizeClusteringDispersionGuard()

    # Corrupted size (NaN) triggers fail-closed
    guard.record_trade_size(float("nan"))
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative trade size triggers fail-closed
    guard.update(-2.5)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
