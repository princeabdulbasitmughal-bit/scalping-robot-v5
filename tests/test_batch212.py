"""
test_batch212.py
----------------
Unit tests for Batch 212:
- wave190_microstructure_price_staleness_guard.py (5 tests)
- wave191_volume_weighted_spread_shock_guard.py (5 tests)
"""

import math
import time
import pytest

import wave190_microstructure_price_staleness_guard as w190
import wave191_volume_weighted_spread_shock_guard as w191


# ===========================================================================
# wave190_microstructure_price_staleness_guard tests
# ===========================================================================

def test_wave190_fresh_continuous_ticks_no_block():
    w190.reset()
    try:
        t = 1000.0
        p = 100.0
        # Continuous fresh ticks every 100 ms
        for _ in range(15):
            w190.record_price(p, ts=t)
            t += 0.10
            p += 0.01

        assert not w190.is_entry_blocked()
        assert w190.get_staleness_sec() <= 0.20
        assert w190.get_gap_bps() < 0.00020
    finally:
        w190.reset()


def test_wave190_post_staleness_jump_gap_triggers_block():
    w190.reset()
    try:
        # Tick 1 at t=1000.0
        w190.record_price(100.00, ts=1000.0)
        # Feed freezes for 4.0 seconds (>= 3.0s), then jumps to 100.06 (6 bps >= 3.0 bps)
        w190.record_price(100.06, ts=1004.0)

        assert w190.is_entry_blocked()
        assert w190.is_blocked()
        assert w190.get_staleness_sec() == 4.0
        assert w190.get_gap_bps() >= 0.00030
    finally:
        w190.reset()


def test_wave190_stale_interval_without_gap_no_block():
    w190.reset()
    try:
        # Feed paused for 4.0s, but resumes with identical price -> no jump gap -> no block
        w190.record_price(100.00, ts=1000.0)
        w190.record_price(100.001, ts=1004.0)  # 0.1 bps gap (< 3.0 bps)

        assert not w190.is_entry_blocked()
        assert w190.get_staleness_sec() == 4.0
        assert w190.get_gap_bps() < 0.00020
    finally:
        w190.reset()


def test_wave190_invalid_inputs_fail_closed():
    w190.reset()
    try:
        w190.record_price(100.0, ts=1000.0)
        # Invalid inputs safely rejected
        w190.record_price(True, ts=1001.0)
        w190.record_price(False, ts=1001.0)
        w190.record_price("bad", ts=1001.0)
        w190.record_price(100.0, ts=True)
        w190.record_price(float("nan"), ts=1001.0)
        w190.record_price(100.0, ts=float("inf"))
        w190.record_price(-50.0, ts=1001.0)
        w190.record_price(0.0, ts=1001.0)

        assert not w190.is_entry_blocked()
        assert w190.get_gap_bps() == 0.0
    finally:
        w190.reset()


def test_wave190_aliases_get_status_and_reset():
    w190.reset()
    try:
        w190.update(100.00, ts=1000.0)
        w190.update(100.08, ts=1005.0)

        assert w190.is_blocked()
        status = w190.get_status()
        assert status["is_blocked"] is True
        assert status["latest_staleness_sec"] == 5.0

        w190.reset()
        assert not w190.is_blocked()
        assert w190.get_staleness_sec() == 0.0
        assert w190.get_gap_bps() == 0.0
    finally:
        w190.reset()


# ===========================================================================
# wave191_volume_weighted_spread_shock_guard tests
# ===========================================================================

def test_wave191_deep_dense_book_no_block():
    w191.reset()
    try:
        # Tier 1: 100.00 / 100.02 (size 20/20) -> touch spread = 0.02 (2 bps)
        # Tier 2: 99.99 / 100.03 (size 30/30) -> robust depth
        w191.record_two_tier_book(
            bid1=100.00, ask1=100.02, qb1=20.0, qa1=20.0,
            bid2=99.99, ask2=100.03, qb2=30.0, qa2=30.0,
        )

        assert not w191.is_entry_blocked()
        assert w191.get_vws_bps() < 0.00040
        assert w191.get_vws_ratio() < 2.0
    finally:
        w191.reset()


def test_wave191_hollow_book_shock_triggers_block():
    w191.reset()
    try:
        # Tier 1: 100.00 / 100.01 (dust size 0.1/0.1) -> touch spread = 0.01 (1 bps)
        # Tier 2: 99.94 / 100.07 (large size 50/50) -> depth is hollow and 13 bps wide!
        w191.record_two_tier_book(
            bid1=100.00, ask1=100.01, qb1=0.1, qa1=0.1,
            bid2=99.94, ask2=100.07, qb2=50.0, qa2=50.0,
        )

        assert w191.is_entry_blocked()
        assert w191.is_blocked()
        assert w191.get_vws_ratio() >= 2.50
    finally:
        w191.reset()


def test_wave191_hard_vws_ceiling_triggers_block():
    w191.reset()
    try:
        # Tier 1: 100.00 / 100.08 (size 10/10) -> touch spread = 0.08 (8 bps >= 6.0 bps)
        w191.record_two_tier_book(
            bid1=100.00, ask1=100.08, qb1=10.0, qa1=10.0,
            bid2=99.98, ask2=100.10, qb2=10.0, qa2=10.0,
        )

        assert w191.is_entry_blocked()
        assert w191.get_vws_bps() >= 0.00060
    finally:
        w191.reset()


def test_wave191_invalid_inputs_and_crossed_books_fail_closed():
    w191.reset()
    try:
        # Crossed book: bid1 >= ask1 safely rejected
        w191.record_two_tier_book(
            bid1=100.05, ask1=100.02, qb1=10.0, qa1=10.0,
            bid2=100.00, ask2=100.08, qb2=10.0, qa2=10.0,
        )
        assert not w191.is_entry_blocked()

        # Invalid types safely rejected
        w191.record_two_tier_book(
            bid1=True, ask1=100.02, qb1=10.0, qa1=10.0,
            bid2=100.00, ask2=100.08, qb2=10.0, qa2=10.0,
        )
        w191.record_book_levels(bids=[], asks=[])
        w191.record_book_levels(bids=[(100.0, float("nan"))], asks=[(100.02, 10.0)])

        assert not w191.is_entry_blocked()
        assert w191.get_vws_bps() == 0.0
    finally:
        w191.reset()


def test_wave191_aliases_get_status_and_reset():
    w191.reset()
    try:
        # Test update alias with 8 scalar arguments
        w191.update(
            100.00, 100.01, 0.1, 0.1,
            99.94, 100.07, 50.0, 50.0,
        )

        assert w191.is_blocked()
        status = w191.get_status()
        assert status["is_blocked"] is True
        assert status["latest_vws_ratio"] >= 2.50

        w191.reset()
        assert not w191.is_blocked()
        assert w191.get_vws_bps() == 0.0
        assert w191.get_vws_ratio() == 1.0
    finally:
        w191.reset()
