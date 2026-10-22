"""
test_batch211.py
----------------
Unit tests for Batch 211:
- wave188_trade_size_clustering_power_law_guard.py (5 tests)
- wave189_order_flow_markov_transition_entropy_guard.py (5 tests)
"""

import math
import time
import pytest

import wave188_trade_size_clustering_power_law_guard as w188
import wave189_order_flow_markov_transition_entropy_guard as w189


# ===========================================================================
# wave188_trade_size_clustering_power_law_guard tests
# ===========================================================================

def test_wave188_standard_retail_sizes_high_alpha_no_block():
    w188.reset()
    try:
        # Homogeneous retail sizes close to baseline (1.0 to 1.3 lots)
        sizes = [1.0, 1.1, 1.0, 1.2, 1.1, 1.0, 1.3, 1.1] * 3
        for v in sizes:
            w188.record_trade(v)

        assert not w188.is_entry_blocked()
        assert w188.get_power_law_alpha() >= 2.50
    finally:
        w188.reset()


def test_wave188_institutional_whale_sizes_triggers_block():
    w188.reset()
    try:
        # Massive whale block sizes mixed in with baseline orders:
        # Baseline = 1.0, whale orders = 50.0, 80.0, 100.0 lots
        # Extreme log ratios -> alpha drops below 1.50
        sizes = [1.0, 50.0, 1.0, 80.0, 1.0, 100.0, 1.0, 75.0] * 3
        for v in sizes:
            w188.record_trade(v)

        assert w188.is_entry_blocked()
        assert w188.is_blocked()
        assert w188.get_power_law_alpha() <= 1.50
    finally:
        w188.reset()


def test_wave188_insufficient_samples_no_block():
    w188.reset()
    try:
        # Only 8 trades (< MIN_SAMPLES 15)
        sizes = [1.0, 50.0, 1.0, 80.0, 1.0, 100.0, 1.0, 75.0]
        for v in sizes:
            w188.record_trade(v)

        assert not w188.is_entry_blocked()
        assert w188.get_status()["sample_count"] == 8
    finally:
        w188.reset()


def test_wave188_invalid_inputs_fail_closed():
    w188.reset()
    try:
        w188.record_trade(1.0)
        # Invalid inputs safely rejected
        w188.record_trade(True)
        w188.record_trade(False)
        w188.record_trade("bad")
        w188.record_trade(float("nan"))
        w188.record_trade(float("inf"))
        w188.record_trade(-10.0)
        w188.record_trade(0.0)

        assert not w188.is_entry_blocked()
        assert w188.get_status()["sample_count"] == 1
    finally:
        w188.reset()


def test_wave188_aliases_get_status_and_reset():
    w188.reset()
    try:
        sizes = [1.0, 50.0, 1.0, 80.0, 1.0, 100.0, 1.0, 75.0] * 3
        for v in sizes:
            w188.update(v)

        assert w188.is_blocked()
        status = w188.get_status()
        assert status["is_blocked"] is True
        assert status["alpha"] <= 1.50

        w188.reset()
        assert not w188.is_blocked()
        assert w188.get_power_law_alpha() == 3.0
        assert w188.get_status()["sample_count"] == 0
    finally:
        w188.reset()


# ===========================================================================
# wave189_order_flow_markov_transition_entropy_guard tests
# ===========================================================================

def test_wave189_diffusive_order_flow_high_entropy_no_block():
    w189.reset()
    try:
        # High entropy stochastic walk: +, -, -, +, +, -, +, -
        p = 100.0
        w189.record_price(p)
        steps = [0.05, -0.05, -0.05, 0.05, 0.05, -0.05, 0.05, -0.05] * 4
        for s in steps:
            p += s
            w189.record_price(p)

        assert not w189.is_entry_blocked()
        assert w189.get_markov_entropy() > 0.70
    finally:
        w189.reset()


def test_wave189_directional_sweep_absorbing_entropy_collapse_triggers_block():
    w189.reset()
    try:
        # Monotonic directional price advance: all transitions are (+ -> +)
        p = 100.0
        w189.record_price(p)
        for _ in range(25):
            p += 0.05
            w189.record_price(p)

        assert w189.is_entry_blocked()
        assert w189.is_blocked()
        assert w189.get_markov_entropy() <= 0.45
    finally:
        w189.reset()


def test_wave189_ping_pong_spoofing_cyclic_entropy_collapse_triggers_block():
    w189.reset()
    try:
        # Strictly alternating ticks: (+ -> -, - -> +, + -> -, - -> +)
        p = 100.0
        w189.record_price(p)
        for i in range(25):
            p = 100.10 if i % 2 == 1 else 100.00
            w189.record_price(p)

        assert w189.is_entry_blocked()
        assert w189.get_markov_entropy() <= 0.45
    finally:
        w189.reset()


def test_wave189_invalid_prices_fail_closed():
    w189.reset()
    try:
        w189.record_price(100.0)
        # Invalid inputs safely rejected
        w189.record_price(True)
        w189.record_price(False)
        w189.record_price("bad")
        w189.record_price(float("nan"))
        w189.record_price(float("inf"))
        w189.record_price(-50.0)
        w189.record_price(0.0)

        assert not w189.is_entry_blocked()
        assert w189.get_status()["sample_count"] == 0
    finally:
        w189.reset()


def test_wave189_aliases_get_status_and_reset():
    w189.reset()
    try:
        p = 100.0
        w189.update(p)
        for _ in range(25):
            p += 0.05
            w189.update(p)

        assert w189.is_blocked()
        status = w189.get_status()
        assert status["is_blocked"] is True
        assert status["markov_entropy"] <= 0.45

        w189.reset()
        assert not w189.is_blocked()
        assert w189.get_markov_entropy() == 1.0
        assert w189.get_status()["sample_count"] == 0
    finally:
        w189.reset()
