"""
test_batch204.py
----------------
Unit tests for Batch 204:
- wave174_vpin_toxicity_bucket_guard.py (5 tests)
- wave175_cross_venue_quote_arbitrage_lag_guard.py (5 tests)
"""

import math
import time
import pytest

import wave174_vpin_toxicity_bucket_guard as w174
import wave175_cross_venue_quote_arbitrage_lag_guard as w175


# ===========================================================================
# wave174_vpin_toxicity_bucket_guard tests
# ===========================================================================

def test_wave174_balanced_order_flow_low_vpin_no_block():
    w174.reset()
    try:
        # Alternating trades: buy 25, sell 25 per bucket of 50 -> imbalance = 0.0
        p = 100.0
        for _ in range(12):
            # Buy trade
            p += 0.01
            w174.record_trade(price=p, volume=25.0)
            # Sell trade
            p -= 0.01
            w174.record_trade(price=p, volume=25.0)

        assert not w174.is_entry_blocked()
        assert w174.get_vpin() <= 0.20
    finally:
        w174.reset()


def test_wave174_one_sided_toxic_sweep_triggers_block():
    w174.reset()
    try:
        # 12 consecutive pure buy buckets (50 lots each) -> imbalance = 50 -> VPIN = 1.00
        p = 100.0
        for _ in range(12):
            p += 0.05
            w174.record_trade(price=p, volume=50.0)

        assert w174.get_vpin() >= 0.70
        assert w174.is_entry_blocked()
        assert w174.is_blocked()
    finally:
        w174.reset()


def test_wave174_bucket_volume_splitting():
    w174.reset()
    try:
        # Single large trade of 150 lots should cleanly split into 3 buckets of 50
        w174.record_trade(price=100.05, volume=150.0)
        status = w174.get_status()
        assert status["completed_buckets"] == 3
        assert status["current_buy_partial"] == 0.0
        assert status["current_sell_partial"] == 0.0
    finally:
        w174.reset()


def test_wave174_invalid_inputs_fail_closed():
    w174.reset()
    try:
        # Invalid prices or volumes safely rejected
        w174.record_trade(True, 50.0)
        w174.record_trade(100.0, False)
        w174.record_trade("bad", 50.0)
        w174.record_trade(100.0, "bad")
        w174.record_trade(float("nan"), 50.0)
        w174.record_trade(100.0, float("nan"))
        w174.record_trade(float("inf"), 50.0)
        w174.record_trade(100.0, float("inf"))
        w174.record_trade(-100.0, 50.0)
        w174.record_trade(100.0, -50.0)
        w174.record_trade(0.0, 50.0)
        w174.record_trade(100.0, 0.0)

        assert not w174.is_entry_blocked()
        assert w174.get_vpin() == 0.0
        assert w174.get_status()["completed_buckets"] == 0
    finally:
        w174.reset()


def test_wave174_aliases_get_status_and_reset():
    w174.reset()
    try:
        p = 100.0
        for _ in range(12):
            p -= 0.05
            w174.update(price=p, volume=50.0)

        assert w174.is_blocked()
        status = w174.get_status()
        assert status["is_blocked"] is True
        assert status["vpin"] >= 0.70
        assert status["completed_buckets"] == 12

        w174.reset()
        assert not w174.is_blocked()
        assert w174.get_vpin() == 0.0
        assert w174.get_status()["completed_buckets"] == 0
    finally:
        w174.reset()


# ===========================================================================
# wave175_cross_venue_quote_arbitrage_lag_guard tests
# ===========================================================================

def test_wave175_synchronized_quotes_no_block():
    w175.reset()
    try:
        # Local: 100.00 / 100.02 | Ref: 100.005 / 100.015
        # Mid local = 100.01, Mid ref = 100.01, divergence = 0.0
        w175.record_quotes(
            local_bid=100.00,
            local_ask=100.02,
            ref_bid=100.005,
            ref_ask=100.015,
            local_ts=1000.0,
            ref_ts=1000.05,
        )
        assert not w175.is_entry_blocked()
        assert w175.get_mid_divergence() < 0.00010
        assert w175.get_latency_lag() < 0.1
    finally:
        w175.reset()


def test_wave175_downside_arbitrage_dislocation_triggers_block():
    w175.reset()
    try:
        # Ref Ask (99.98) < Local Bid (100.00) -> downside latency arbitrage dislocation
        w175.record_quotes(
            local_bid=100.00,
            local_ask=100.02,
            ref_bid=99.96,
            ref_ask=99.98,
        )
        assert w175.is_entry_blocked()
        assert w175.is_blocked()
        assert w175.get_status()["dislocation_detected"] is True
    finally:
        w175.reset()


def test_wave175_upside_arbitrage_dislocation_and_crossed_books():
    w175.reset()
    try:
        # Ref Bid (100.05) > Local Ask (100.02) -> upside latency arbitrage dislocation
        w175.record_quotes(
            local_bid=100.00,
            local_ask=100.02,
            ref_bid=100.05,
            ref_ask=100.07,
        )
        assert w175.is_entry_blocked()

        w175.reset()
        assert not w175.is_entry_blocked()

        # Inverted / crossed book: local bid > local ask
        w175.record_quotes(
            local_bid=100.05,
            local_ask=100.02,
            ref_bid=100.00,
            ref_ask=100.02,
        )
        assert w175.is_entry_blocked()
    finally:
        w175.reset()


def test_wave175_midpoint_divergence_and_timestamp_lag():
    w175.reset()
    try:
        # Mid local = 100.01, Mid ref = 100.05 -> divergence = 0.04 / 100.05 = 0.0003998 >= 0.00020 (2 bps)
        w175.record_quotes(
            local_bid=100.00,
            local_ask=100.02,
            ref_bid=100.04,
            ref_ask=100.06,
        )
        assert w175.get_mid_divergence() >= 0.00020
        assert w175.is_entry_blocked()

        w175.reset()
        assert not w175.is_entry_blocked()

        # Timestamp desynchronization lag >= 2.5s
        w175.record_quotes(
            local_bid=100.00,
            local_ask=100.02,
            ref_bid=100.00,
            ref_ask=100.02,
            local_ts=1000.0,
            ref_ts=1003.0,  # 3.0s lag >= 2.5s
        )
        assert w175.get_latency_lag() == 3.0
        assert w175.is_entry_blocked()
    finally:
        w175.reset()


def test_wave175_invalid_quotes_fail_closed_and_reset():
    w175.reset()
    try:
        # Invalid inputs safely ignored
        w175.record_quotes(True, 100.02, 100.00, 100.02)
        w175.record_quotes(100.00, "bad", 100.00, 100.02)
        w175.record_quotes(100.00, 100.02, float("nan"), 100.02)
        w175.record_quotes(100.00, 100.02, 100.00, float("inf"))
        w175.record_quotes(-100.00, 100.02, 100.00, 100.02)
        w175.record_quotes(0.0, 100.02, 100.00, 100.02)

        assert not w175.is_entry_blocked()
        assert w175.get_mid_divergence() == 0.0

        # Test update alias
        w175.update(
            local_bid=100.00,
            local_ask=100.02,
            ref_bid=99.90,
            ref_ask=99.95,
        )
        assert w175.is_entry_blocked()

        w175.reset()
        assert not w175.is_entry_blocked()
        assert w175.get_mid_divergence() == 0.0
        assert w175.get_latency_lag() == 0.0
    finally:
        w175.reset()
