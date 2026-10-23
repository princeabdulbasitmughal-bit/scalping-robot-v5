"""
tests/test_batch262.py
----------------------
Unit tests for Batch 262:
  - Wave 290: Wave290LobQuoteCancellationRatioGuard
  - Wave 291: Wave291TradePriceMarkovDriftGuard
"""

import math
import time
import pytest

from wave290_lob_quote_cancellation_ratio_guard import Wave290LobQuoteCancellationRatioGuard
from wave291_trade_price_markov_drift_guard import Wave291TradePriceMarkovDriftGuard


# ----------------------------------------------------------------------
# Wave 290 Tests: LOB Quote-to-Trade Ratio & Cancellation Intensity Guard
# ----------------------------------------------------------------------

def test_wave290_normal_cancellation_no_block():
    guard = Wave290LobQuoteCancellationRatioGuard(
        max_quote_trade_ratio=35.0,
        min_cancellations=50,
        acute_burst_cancellations=30,
        window_sec=10.0,
    )

    # 10 cancellations and 2 trades (ratio = 5.0)
    t = 100.0
    for _ in range(10):
        guard.record_cancellation(ts=t)
        t += 0.5
    guard.record_trade(ts=t)
    guard.record_trade(ts=t + 0.1)

    assert not guard.is_entry_blocked()
    assert not guard.is_blocked()
    metrics = guard.get_cancellation_metrics()
    assert metrics["quote_trade_ratio"] <= 10.0
    assert not metrics["is_blocked"]


def test_wave290_excessive_cancellation_blocks():
    guard = Wave290LobQuoteCancellationRatioGuard(
        max_quote_trade_ratio=35.0,
        min_cancellations=50,
        cooldown_seconds=45.0,
    )

    # Precomputed excessive ratio metric injection: ratio = 42.0, cancellations = 60
    guard.record_cancellation_metrics(quote_trade_ratio=42.0, cancel_count=60, trade_count=1)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "EXCESSIVE_CANCELLATION_RATIO" in metrics["last_block_reason"]


def test_wave290_acute_phantom_burst_blocks():
    guard = Wave290LobQuoteCancellationRatioGuard(
        acute_burst_cancellations=30,
        acute_burst_window_sec=0.50,
        cooldown_seconds=45.0,
    )

    # 30 cancellations clustered within 0.30s (t=10.00 to 10.30)
    for i in range(30):
        guard.record_cancellation(ts=10.0 + (i * 0.01))

    assert guard.is_entry_blocked()
    metrics = guard.get_cancellation_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_PHANTOM_BURST" in metrics["last_block_reason"]


def test_wave290_insufficient_samples_no_block():
    guard = Wave290LobQuoteCancellationRatioGuard(
        max_quote_trade_ratio=35.0,
        min_cancellations=50,
    )

    # High ratio (40.0) but only 20 cancellations (< 50 min_cancellations)
    guard.record_cancellation_metrics(quote_trade_ratio=40.0, cancel_count=20, trade_count=0)

    assert not guard.is_entry_blocked()


def test_wave290_input_validation_and_reset():
    guard = Wave290LobQuoteCancellationRatioGuard()

    # Boolean cancellation metric triggers fail-closed
    guard.record_cancellation_metrics(True)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative ratio triggers fail-closed
    guard.update(-5.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 291 Tests: Trade Price Transition Markov Matrix Guard
# ----------------------------------------------------------------------

def test_wave291_symmetric_bounce_no_block():
    guard = Wave291TradePriceMarkovDriftGuard(
        max_persistence=0.75,
        min_transitions=20,
        acute_run_streak=7,
    )

    # Symmetric bid-ask bounce: alternating up and down ticks
    px = 100.0
    for i in range(25):
        px = 100.01 if i % 2 == 0 else 100.00
        guard.record_trade_price(px)
        assert not guard.is_entry_blocked()

    metrics = guard.get_markov_metrics()
    assert metrics["persistence_probability"] <= 0.20
    assert not metrics["is_blocked"]


def test_wave291_markov_persistence_blocks():
    guard = Wave291TradePriceMarkovDriftGuard(
        max_persistence=0.75,
        min_transitions=20,
        cooldown_seconds=45.0,
    )

    # Precomputed Markov persistence injection (persistence = 0.82 on 22 transitions)
    guard.record_markov_metrics(persistence_prob=0.82, streak_len=2, sample_count=22)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "MARKOV_DIRECTIONAL_DRIFT" in metrics["last_block_reason"]


def test_wave291_acute_run_streak_blocks():
    guard = Wave291TradePriceMarkovDriftGuard(
        acute_run_streak=7,
        cooldown_seconds=45.0,
    )

    # 7 consecutive up-ticks in price (100.00 to 100.07)
    px = 100.00
    for _ in range(8):
        guard.record_trade_price(px)
        px += 0.01

    assert guard.is_entry_blocked()
    metrics = guard.get_markov_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_PRICE_RUN_STREAK" in metrics["last_block_reason"]


def test_wave291_insufficient_samples_no_block():
    guard = Wave291TradePriceMarkovDriftGuard(
        max_persistence=0.75,
        min_transitions=20,
    )

    # High persistence metric but only 8 transitions (< 20 min_transitions)
    guard.record_markov_metrics(persistence_prob=0.90, streak_len=1, sample_count=8)

    assert not guard.is_entry_blocked()


def test_wave291_input_validation_and_reset():
    guard = Wave291TradePriceMarkovDriftGuard()

    # NaN price triggers fail-closed
    guard.record_trade_price(float("nan"))
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative price triggers fail-closed
    guard.update(-100.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
