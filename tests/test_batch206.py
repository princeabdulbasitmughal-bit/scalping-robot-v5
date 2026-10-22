"""
test_batch206.py
----------------
Unit tests for Batch 206:
- wave178_quote_to_trade_ratio_spoofing_guard.py (5 tests)
- wave179_order_flow_duration_entropy_guard.py (5 tests)
"""

import math
import time
import pytest

import wave178_quote_to_trade_ratio_spoofing_guard as w178
import wave179_order_flow_duration_entropy_guard as w179


# ===========================================================================
# wave178_quote_to_trade_ratio_spoofing_guard tests
# ===========================================================================

def test_wave178_normal_qtr_no_block():
    w178.reset()
    try:
        t = 1000.0
        # Interleaved 50 quotes and 5 trades -> QTR = 10.0:1 (< 50.0)
        for j in range(5):
            for i in range(10):
                w178.record_quote(ts=t + (j * 1.0) + (i * 0.05))
            w178.record_trade(ts=t + (j * 1.0) + 0.90)

        assert not w178.is_entry_blocked()
        assert w178.get_qtr() <= 15.0
    finally:
        w178.reset()


def test_wave178_excessive_qtr_spoofing_triggers_block():
    w178.reset()
    try:
        t = 1000.0
        # 60 quotes and 0 trades -> QTR = 60.0 >= 50.0
        for i in range(60):
            w178.record_quote(ts=t + (i * 0.05))

        assert w178.is_entry_blocked()
        assert w178.is_blocked()
        assert w178.get_qtr() >= 50.0
    finally:
        w178.reset()


def test_wave178_window_expiry_pruning():
    w178.reset()
    try:
        t = 1000.0
        # 50 quotes at t=1000
        for i in range(50):
            w178.record_quote(ts=t + (i * 0.01))
        assert w178.is_entry_blocked()

        w178.reset()
        # Advance time by 20.0s (past 10s window) and record normal activity
        t2 = 1025.0
        for i in range(10):
            w178.record_quote(ts=t2 + (i * 0.1))
        for j in range(5):
            w178.record_trade(ts=t2 + (j * 0.2))

        # Only 10 quotes in window -> < MIN_QUOTES (40)
        assert not w178.is_entry_blocked()
    finally:
        w178.reset()


def test_wave178_invalid_inputs_fail_closed():
    w178.reset()
    try:
        # Invalid timestamps safely rejected
        w178.record_quote(ts=True)
        w178.record_quote(ts=False)
        w178.record_quote(ts="bad")
        w178.record_quote(ts=float("nan"))
        w178.record_quote(ts=float("inf"))
        w178.record_quote(ts=-100.0)

        w178.record_trade(ts=True)
        w178.record_trade(ts=float("nan"))

        w178.record_event("invalid_event", ts=1000.0)

        assert not w178.is_entry_blocked()
        status = w178.get_status()
        assert status["quote_count"] == 0
        assert status["trade_count"] == 0
    finally:
        w178.reset()


def test_wave178_aliases_get_status_and_reset():
    w178.reset()
    try:
        t = 1000.0
        for i in range(50):
            w178.update("quote", ts=t + (i * 0.05))

        assert w178.is_blocked()
        status = w178.get_status()
        assert status["is_blocked"] is True
        assert status["quote_count"] == 50

        w178.reset()
        assert not w178.is_blocked()
        status = w178.get_status()
        assert status["quote_count"] == 0
        assert status["is_blocked"] is False
    finally:
        w178.reset()


# ===========================================================================
# wave179_order_flow_duration_entropy_guard tests
# ===========================================================================

def test_wave179_dispersed_stochastic_arrivals_no_block():
    w179.reset()
    try:
        # High entropy stochastic durations dispersed across diverse bins
        # e.g. 5ms, 25ms, 75ms, 180ms, 350ms, 800ms, 1500ms
        durations = [0.005, 0.025, 0.075, 0.180, 0.350, 0.800, 1.500] * 3
        t = 1000.0
        w179.record_trade_arrival(ts=t)
        for d in durations:
            t += d
            w179.record_trade_arrival(ts=t)

        assert not w179.is_entry_blocked()
        assert w179.get_duration_entropy() > 1.20
    finally:
        w179.reset()


def test_wave179_deterministic_periodic_slicing_triggers_block():
    w179.reset()
    try:
        # Rigidly periodic machine slicing: exactly 0.080s every trade (Bin 2)
        # All 20 transitions land in the same bin -> entropy = 0.0 bits
        t = 1000.0
        w179.record_trade_arrival(ts=t)
        for _ in range(20):
            t += 0.080
            w179.record_trade_arrival(ts=t)

        assert w179.get_duration_entropy() <= 0.60
        assert w179.is_entry_blocked()
        assert w179.is_blocked()
    finally:
        w179.reset()


def test_wave179_insufficient_samples_no_block():
    w179.reset()
    try:
        # Only 5 trades -> fewer than MIN_SAMPLES (15)
        t = 1000.0
        w179.record_trade_arrival(ts=t)
        for _ in range(5):
            t += 0.080
            w179.record_trade_arrival(ts=t)

        assert not w179.is_entry_blocked()
        assert w179.get_status()["samples_count"] == 5
    finally:
        w179.reset()


def test_wave179_invalid_inputs_fail_closed():
    w179.reset()
    try:
        w179.record_trade_arrival(ts=1000.0)
        # Invalid inputs safely rejected
        w179.record_trade_arrival(ts=True)
        w179.record_trade_arrival(ts=False)
        w179.record_trade_arrival(ts="bad")
        w179.record_trade_arrival(ts=float("nan"))
        w179.record_trade_arrival(ts=float("inf"))
        w179.record_trade_arrival(ts=-50.0)

        assert not w179.is_entry_blocked()
        assert w179.get_status()["samples_count"] == 0
    finally:
        w179.reset()


def test_wave179_aliases_get_status_and_reset():
    w179.reset()
    try:
        t = 1000.0
        w179.update(ts=t)
        for _ in range(20):
            t += 0.040  # Bin 1
            w179.update(ts=t)

        assert w179.is_blocked()
        status = w179.get_status()
        assert status["is_blocked"] is True
        assert status["samples_count"] == 20

        w179.reset()
        assert not w179.is_blocked()
        assert w179.get_duration_entropy() == 3.0
        assert w179.get_status()["samples_count"] == 0
    finally:
        w179.reset()
