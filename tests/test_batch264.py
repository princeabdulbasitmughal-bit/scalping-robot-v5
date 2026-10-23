"""
tests/test_batch264.py
----------------------
Unit tests for Batch 264:
  - Wave 294: Wave294LobMicroPriceLeadLagGuard
  - Wave 295: Wave295TradeArrivalCrossCorrelationGuard
"""

import math
import time
import pytest

from wave294_lob_micro_price_lead_lag_guard import Wave294LobMicroPriceLeadLagGuard
from wave295_trade_arrival_cross_correlation_guard import Wave295TradeArrivalCrossCorrelationGuard


# ----------------------------------------------------------------------
# Wave 294 Tests: LOB Stoikov Micro-Price Lead-Lag Guard
# ----------------------------------------------------------------------

def test_wave294_balanced_quotes_no_block():
    guard = Wave294LobMicroPriceLeadLagGuard(
        max_mean_deviation_bps=2.20,
        min_spread_bps=2.00,
        min_samples=12,
        acute_deviation_bps=4.50,
    )

    # Balanced book: bid=100.0, ask=100.02, equal depths 10 vs 10 lots -> deviation = 0
    for _ in range(15):
        guard.record_quotes(bid_px=100.0, ask_px=100.02, bid_qty=10.0, ask_qty=10.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_micro_price_metrics()
    assert metrics["mean_deviation_bps"] < 0.50
    assert not metrics["is_blocked"]


def test_wave294_micro_price_lead_bias_blocks():
    guard = Wave294LobMicroPriceLeadLagGuard(
        max_mean_deviation_bps=2.20,
        min_spread_bps=2.00,
        min_samples=12,
        cooldown_seconds=45.0,
    )

    # Precomputed persistent micro-price deviation injection: deviation = 2.80 bps, spread = 2.50 bps
    guard.record_micro_price_metrics(deviation_bps=2.80, spread_bps=2.50, sample_count=14)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "MICRO_PRICE_LEAD_BIAS" in metrics["last_block_reason"]


def test_wave294_acute_micro_price_shock_blocks():
    guard = Wave294LobMicroPriceLeadLagGuard(
        acute_deviation_bps=4.50,
        cooldown_seconds=45.0,
    )

    # Extreme quote skew: bid=100.0, ask=100.10 (10 bps spread), bid_qty=100.0, ask_qty=1.0 (micro-price skewed by ~4.9 bps)
    guard.record_quotes(bid_px=100.0, ask_px=100.10, bid_qty=100.0, ask_qty=1.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_micro_price_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_MICRO_PRICE_SHOCK" in metrics["last_block_reason"]


def test_wave294_insufficient_samples_no_block():
    guard = Wave294LobMicroPriceLeadLagGuard(
        max_mean_deviation_bps=2.20,
        min_spread_bps=2.00,
        min_samples=12,
    )

    # Elevated deviation (3.0 bps) but only 5 observations (< 12 min_samples)
    guard.record_micro_price_metrics(deviation_bps=3.0, spread_bps=2.5, sample_count=5)

    assert not guard.is_entry_blocked()


def test_wave294_input_validation_and_reset():
    guard = Wave294LobMicroPriceLeadLagGuard()

    # Boolean price triggers fail-closed
    guard.record_quotes(True, 100.0, 10.0, 10.0)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Inverted quotes (ask < bid) triggers fail-closed
    guard.update(100.05, 100.00, 10.0, 10.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 295 Tests: Trade Arrival Cross-Correlation Guard
# ----------------------------------------------------------------------

def test_wave295_symmetric_flow_no_block():
    guard = Wave295TradeArrivalCrossCorrelationGuard(
        min_cross_correlation=-0.45,
        min_total_trades=20,
        min_bins=8,
        acute_concentration=0.92,
        min_trades=20,
    )

    # Balanced flow: 10 buys, 10 sells
    for _ in range(10):
        guard.record_trade(1)
        guard.record_trade(-1)
        assert not guard.is_entry_blocked()

    metrics = guard.get_correlation_metrics()
    assert metrics["dominant_side_fraction"] <= 0.60
    assert not metrics["is_blocked"]


def test_wave295_flow_decoupling_blocks():
    guard = Wave295TradeArrivalCrossCorrelationGuard(
        min_cross_correlation=-0.45,
        min_total_trades=20,
        min_bins=8,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed decoupled flow: corr = -0.65 over 10 bins
    guard.record_correlation_metrics(cross_corr=-0.65, dominant_fraction=0.70, sample_count=10)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "BUYER_SELLER_DECOUPLING" in metrics["last_block_reason"]


def test_wave295_acute_one_sided_flow_blocks():
    guard = Wave295TradeArrivalCrossCorrelationGuard(
        acute_concentration=0.92,
        min_trades=20,
        cooldown_seconds=45.0,
    )

    # 19 buys and 1 sell out of 20 trades (dominant fraction = 0.95 >= 0.92)
    for _ in range(19):
        guard.record_trade(1)
    guard.record_trade(-1)

    assert guard.is_entry_blocked()
    metrics = guard.get_correlation_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_ONE_SIDED_FLOW" in metrics["last_block_reason"]


def test_wave295_insufficient_samples_no_block():
    guard = Wave295TradeArrivalCrossCorrelationGuard(
        min_cross_correlation=-0.45,
        min_total_trades=20,
        min_bins=8,
    )

    # Negative correlation metric but only 4 bins (< 8 min_bins)
    guard.record_correlation_metrics(cross_corr=-0.80, dominant_fraction=0.60, sample_count=4)

    assert not guard.is_entry_blocked()


def test_wave295_input_validation_and_reset():
    guard = Wave295TradeArrivalCrossCorrelationGuard()

    # Invalid direction (e.g. 0) triggers fail-closed
    guard.record_trade(0)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Boolean direction triggers fail-closed
    guard.update(True)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
