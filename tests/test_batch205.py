"""
test_batch205.py
----------------
Unit tests for Batch 205:
- wave176_order_flow_markov_drift_guard.py (5 tests)
- wave177_queue_depletion_velocity_guard.py (5 tests)
"""

import math
import time
import pytest

import wave176_order_flow_markov_drift_guard as w176
import wave177_queue_depletion_velocity_guard as w177


# ===========================================================================
# wave176_order_flow_markov_drift_guard tests
# ===========================================================================

def test_wave176_diffusive_two_sided_market_no_block():
    w176.reset()
    try:
        # Alternating ticks: +, -, +, -, +, + (balanced transitions)
        p = 100.0
        w176.record_price(p)
        steps = [0.05, -0.05] * 15
        for s in steps:
            p += s
            w176.record_price(p)

        assert not w176.is_entry_blocked()
        probs = w176.get_transition_probabilities()
        assert probs["p_plus_given_plus_plus"] < 0.85
        assert probs["p_minus_given_minus_minus"] < 0.85
    finally:
        w176.reset()


def test_wave176_persistent_upside_drift_triggers_block():
    w176.reset()
    try:
        # Monotonic upside price advance -> P(+ | ++) = 1.0
        p = 100.0
        w176.record_price(p)
        for _ in range(25):
            p += 0.05
            w176.record_price(p)

        assert w176.is_entry_blocked()
        assert w176.is_blocked()
        probs = w176.get_transition_probabilities()
        assert probs["p_plus_given_plus_plus"] >= 0.85
    finally:
        w176.reset()


def test_wave176_persistent_downside_drift_triggers_block():
    w176.reset()
    try:
        # Monotonic downside price collapse -> P(- | --) = 1.0
        p = 100.0
        w176.record_price(p)
        for _ in range(25):
            p -= 0.05
            w176.record_price(p)

        assert w176.is_entry_blocked()
        probs = w176.get_transition_probabilities()
        assert probs["p_minus_given_minus_minus"] >= 0.85
    finally:
        w176.reset()


def test_wave176_invalid_inputs_fail_closed():
    w176.reset()
    try:
        w176.record_price(100.0)
        # Invalid inputs safely ignored
        w176.record_price(True)
        w176.record_price(False)
        w176.record_price("bad_price")
        w176.record_price(float("nan"))
        w176.record_price(float("inf"))
        w176.record_price(-50.0)
        w176.record_price(0.0)

        assert not w176.is_entry_blocked()
        status = w176.get_status()
        assert status["sample_count"] == 0
    finally:
        w176.reset()


def test_wave176_aliases_get_status_and_reset():
    w176.reset()
    try:
        p = 100.0
        w176.update(p)
        for _ in range(25):
            p += 0.05
            w176.update(p)

        assert w176.is_blocked()
        status = w176.get_status()
        assert status["is_blocked"] is True
        assert status["sample_count"] == 25

        w176.reset()
        assert not w176.is_blocked()
        status = w176.get_status()
        assert status["sample_count"] == 0
        assert status["is_blocked"] is False
    finally:
        w176.reset()


# ===========================================================================
# wave177_queue_depletion_velocity_guard tests
# ===========================================================================

def test_wave177_normal_queue_replenishment_no_block():
    w177.reset()
    try:
        t = 1000.0
        w177.record_depth(bid_depth=20.0, ask_depth=20.0, ts=t)
        # Normal small depth fluctuations (10% - 20%)
        w177.record_depth(bid_depth=18.0, ask_depth=22.0, ts=t + 0.1)
        w177.record_depth(bid_depth=21.0, ask_depth=19.0, ts=t + 0.2)

        assert not w177.is_entry_blocked()
        assert w177.get_latest_drop_pct() < 0.75
    finally:
        w177.reset()


def test_wave177_bid_queue_phantom_pull_triggers_block():
    w177.reset()
    try:
        t = 1000.0
        w177.record_depth(bid_depth=25.0, ask_depth=20.0, ts=t)
        # Bid depth suddenly collapses from 25.0 to 2.0 (92% drop) in 100 ms
        w177.record_depth(bid_depth=2.0, ask_depth=20.0, ts=t + 0.10)

        assert w177.is_entry_blocked()
        assert w177.is_blocked()
        assert w177.get_latest_drop_pct() >= 0.75
    finally:
        w177.reset()


def test_wave177_ask_queue_phantom_pull_triggers_block():
    w177.reset()
    try:
        t = 1000.0
        w177.record_depth(bid_depth=20.0, ask_depth=30.0, ts=t)
        # Ask depth collapses from 30.0 to 3.0 (90% drop) in 200 ms
        w177.record_depth(bid_depth=20.0, ask_depth=3.0, ts=t + 0.20)

        assert w177.is_entry_blocked()
        assert w177.get_latest_drop_pct() >= 0.75
    finally:
        w177.reset()


def test_wave177_slow_depletion_or_dust_queue_no_block():
    w177.reset()
    try:
        t = 1000.0
        # Slow depletion over 2.0 seconds (> 0.50s window) -> normal orderly exit, not phantom pull
        w177.record_depth(bid_depth=20.0, ask_depth=20.0, ts=t)
        w177.record_depth(bid_depth=2.0, ask_depth=20.0, ts=t + 2.0)
        assert not w177.is_entry_blocked()

        w177.reset()

        # Initial queue is tiny dust depth (< 5.0 lots) -> ignore
        w177.record_depth(bid_depth=3.0, ask_depth=3.0, ts=t)
        w177.record_depth(bid_depth=0.5, ask_depth=0.5, ts=t + 0.1)
        assert not w177.is_entry_blocked()
    finally:
        w177.reset()


def test_wave177_invalid_inputs_and_reset():
    w177.reset()
    try:
        # Invalid inputs safely rejected
        w177.record_depth(True, 20.0, ts=1000.0)
        w177.record_depth(20.0, False, ts=1000.0)
        w177.record_depth("bad", 20.0, ts=1000.0)
        w177.record_depth(20.0, 20.0, ts=True)
        w177.record_depth(float("nan"), 20.0, ts=1000.0)
        w177.record_depth(20.0, float("inf"), ts=1000.0)
        w177.record_depth(-10.0, 20.0, ts=1000.0)

        assert not w177.is_entry_blocked()

        # Test update alias
        t = 2000.0
        w177.update(bid_depth=30.0, ask_depth=30.0, ts=t)
        w177.update(bid_depth=30.0, ask_depth=2.0, ts=t + 0.15)
        assert w177.is_entry_blocked()

        status = w177.get_status()
        assert status["is_blocked"] is True

        w177.reset()
        assert not w177.is_entry_blocked()
        assert w177.get_latest_drop_pct() == 0.0
    finally:
        w177.reset()
