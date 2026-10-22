"""
test_batch210.py
----------------
Unit tests for Batch 210:
- wave186_trade_sign_entropy_production_guard.py (5 tests)
- wave187_order_flow_imbalance_curvature_guard.py (5 tests)
"""

import math
import time
import pytest

import wave186_trade_sign_entropy_production_guard as w186
import wave187_order_flow_imbalance_curvature_guard as w187


# ===========================================================================
# wave186_trade_sign_entropy_production_guard tests
# ===========================================================================

def test_wave186_reversible_symmetric_order_flow_no_block():
    w186.reset()
    try:
        # Reversible symmetric sign sequence: e.g. balanced transitions where words and their reverses match
        p = 100.0
        w186.record_price(p)
        steps = [0.05, -0.05, 0.05, 0.05, -0.05, -0.05] * 6
        for s in steps:
            p += s
            w186.record_price(p)

        assert not w186.is_entry_blocked()
        assert w186.get_entropy_production() < 0.35
    finally:
        w186.reset()


def test_wave186_irreversible_breakout_streak_triggers_block():
    w186.reset()
    try:
        # Strongly asymmetric non-equilibrium flow:
        # 4 consecutive up ticks followed by 1 down tick (up-runs length 4, down-runs length 1)
        p = 100.0
        w186.record_price(p)
        pattern = [0.05, 0.05, 0.05, 0.05, -0.05] * 7
        for s in pattern:
            p += s
            w186.record_price(p)

        assert w186.is_entry_blocked()
        assert w186.is_blocked()
        assert w186.get_entropy_production() >= 0.50
    finally:
        w186.reset()


def test_wave186_insufficient_samples_no_block():
    w186.reset()
    try:
        # Only 10 signs (< MIN_SAMPLES 25)
        p = 100.0
        w186.record_price(p)
        for _ in range(10):
            p += 0.05
            w186.record_price(p)

        assert not w186.is_entry_blocked()
        assert w186.get_status()["sample_count"] == 10
    finally:
        w186.reset()


def test_wave186_invalid_prices_fail_closed():
    w186.reset()
    try:
        w186.record_price(100.0)
        # Invalid inputs safely rejected
        w186.record_price(True)
        w186.record_price(False)
        w186.record_price("bad")
        w186.record_price(float("nan"))
        w186.record_price(float("inf"))
        w186.record_price(-100.0)
        w186.record_price(0.0)

        assert not w186.is_entry_blocked()
        assert w186.get_status()["sample_count"] == 0
    finally:
        w186.reset()


def test_wave186_aliases_get_status_and_reset():
    w186.reset()
    try:
        p = 100.0
        w186.update(p)
        pattern = [0.05, 0.05, 0.05, 0.05, -0.05] * 7
        for s in pattern:
            p += s
            w186.update(p)

        assert w186.is_blocked()
        status = w186.get_status()
        assert status["is_blocked"] is True
        assert status["entropy_production"] >= 0.50

        w186.reset()
        assert not w186.is_blocked()
        assert w186.get_entropy_production() == 0.0
        assert w186.get_status()["sample_count"] == 0
    finally:
        w186.reset()


# ===========================================================================
# wave187_order_flow_imbalance_curvature_guard tests
# ===========================================================================

def test_wave187_stable_linear_book_flow_no_block():
    w187.reset()
    try:
        t = 1000.0
        # Smoothly stationary order book
        for i in range(10):
            w187.record_book(bid=100.00, ask=100.02, bid_depth=20.0, ask_depth=20.0, ts=t + (i * 0.1))

        assert not w187.is_entry_blocked()
        assert abs(w187.get_ofi_curvature()) < 2.0
    finally:
        w187.reset()


def test_wave187_parabolic_depth_vacuum_curvature_triggers_block():
    w187.reset()
    try:
        # Sudden non-linear book shift causing massive OFI acceleration
        w187.record_book(bid=100.00, ask=100.02, bid_depth=20.0, ask_depth=20.0, ts=1000.0)
        w187.record_book(bid=100.00, ask=100.02, bid_depth=20.0, ask_depth=20.0, ts=1000.1)
        # Violent collapse: bid drops, ask explodes in depth
        w187.record_book(bid=99.98, ask=100.02, bid_depth=5.0, ask_depth=50.0, ts=1000.2)

        assert w187.is_entry_blocked()
        assert w187.is_blocked()
        assert abs(w187.get_ofi_curvature()) >= 5.0
    finally:
        w187.reset()


def test_wave187_dt_out_of_bounds_ignored():
    w187.reset()
    try:
        # Sub-millisecond dt (< 0.005s) ignored
        w187.record_book(bid=100.00, ask=100.02, bid_depth=20.0, ask_depth=20.0, ts=1000.0)
        w187.record_book(bid=99.98, ask=100.02, bid_depth=5.0, ask_depth=50.0, ts=1000.001)
        assert not w187.is_entry_blocked()

        w187.reset()
        # Stale dt (> 2.0s) ignored
        w187.record_book(bid=100.00, ask=100.02, bid_depth=20.0, ask_depth=20.0, ts=1000.0)
        w187.record_book(bid=99.98, ask=100.02, bid_depth=5.0, ask_depth=50.0, ts=1005.0)
        assert not w187.is_entry_blocked()
    finally:
        w187.reset()


def test_wave187_invalid_quotes_fail_closed():
    w187.reset()
    try:
        # Invalid inputs safely rejected
        w187.record_book(True, 100.02, 20.0, 20.0, ts=1000.0)
        w187.record_book(100.00, False, 20.0, 20.0, ts=1000.0)
        w187.record_book(100.00, 100.02, "bad", 20.0, ts=1000.0)
        w187.record_book(100.00, 100.02, 20.0, float("nan"), ts=1000.0)
        w187.record_book(100.00, 100.02, 20.0, 20.0, ts=True)
        w187.record_book(-100.00, 100.02, 20.0, 20.0, ts=1000.0)

        # Crossed quotes: bid > ask safely rejected
        w187.record_book(100.05, 100.02, 20.0, 20.0, ts=1000.0)

        assert not w187.is_entry_blocked()
        assert w187.get_ofi_curvature() == 0.0
    finally:
        w187.reset()


def test_wave187_aliases_get_status_and_reset():
    w187.reset()
    try:
        w187.update(bid=100.00, ask=100.02, bid_depth=20.0, ask_depth=20.0, ts=1000.0)
        w187.update(bid=100.00, ask=100.02, bid_depth=20.0, ask_depth=20.0, ts=1000.1)
        w187.update(bid=99.98, ask=100.02, bid_depth=5.0, ask_depth=50.0, ts=1000.2)

        assert w187.is_blocked()
        status = w187.get_status()
        assert status["is_blocked"] is True
        assert abs(status["ofi_curvature"]) >= 5.0

        w187.reset()
        assert not w187.is_blocked()
        assert w187.get_ofi_curvature() == 0.0
    finally:
        w187.reset()
