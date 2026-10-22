"""
test_batch203.py
----------------
Unit tests for Batch 203:
- wave172_tick_entropy_rate_guard.py (5 tests)
- wave173_order_flow_toxicity_kurtosis_guard.py (5 tests)
"""

import math
import time
import pytest

import wave172_tick_entropy_rate_guard as w172
import wave173_order_flow_toxicity_kurtosis_guard as w173


# ===========================================================================
# wave172_tick_entropy_rate_guard tests
# ===========================================================================

def test_wave172_stochastic_random_walk_no_block():
    w172.reset()
    try:
        # High entropy pseudo-random sequence of price steps
        steps = [
            0.05, -0.05, -0.05, 0.05, 0.05, -0.05, 0.05, -0.05,
            -0.05, 0.05, 0.05, 0.05, -0.05, 0.05, -0.05, -0.05,
            0.05, 0.05, -0.05, -0.05, 0.05, -0.05, 0.05, 0.05
        ]
        p = 100.0
        w172.record_price(p)
        for s in steps:
            p += s
            w172.record_price(p)

        assert not w172.is_entry_blocked()
        assert w172.get_entropy_rate() > 0.40
    finally:
        w172.reset()


def test_wave172_deterministic_monotonic_streak_triggers_block():
    w172.reset()
    try:
        # Monotonically increasing ticks -> all transitions are (+ -> +), entropy = 0.0
        p = 100.0
        w172.record_price(p)
        for _ in range(20):
            p += 0.05
            w172.record_price(p)

        assert w172.get_entropy_rate() <= 0.40
        assert w172.is_entry_blocked()
        assert w172.is_blocked()
    finally:
        w172.reset()


def test_wave172_deterministic_ping_pong_cycle_triggers_block():
    w172.reset()
    try:
        # Strictly alternating ticks -> all transitions are (+ -> -) and (- -> +), entropy = 0.0
        p = 100.0
        w172.record_price(p)
        for i in range(20):
            p = 100.10 if i % 2 == 1 else 100.00
            w172.record_price(p)

        assert w172.get_entropy_rate() <= 0.40
        assert w172.is_entry_blocked()
    finally:
        w172.reset()


def test_wave172_invalid_prices_fail_closed():
    w172.reset()
    try:
        w172.record_price(100.0)
        # Invalid inputs safely rejected
        w172.record_price(0.0)
        w172.record_price(-15.0)
        w172.record_price("bad_price")
        w172.record_price(True)
        w172.record_price(float("nan"))
        w172.record_price(float("inf"))

        assert not w172.is_entry_blocked()
        assert w172.get_entropy_rate() == 1.0
    finally:
        w172.reset()


def test_wave172_update_alias_and_reset():
    w172.reset()
    try:
        p = 100.0
        w172.update(p)
        for _ in range(20):
            p -= 0.05
            w172.update(p)

        assert w172.is_entry_blocked()

        w172.reset()
        assert not w172.is_entry_blocked()
        assert not w172.is_blocked()
        assert w172.get_entropy_rate() == 1.0
    finally:
        w172.reset()


# ===========================================================================
# wave173_order_flow_toxicity_kurtosis_guard tests
# ===========================================================================

def test_wave173_uniform_order_sizes_no_block():
    w173.reset()
    try:
        # Uniform, moderately dispersed volumes
        volumes = [1.0, 1.2, 0.8, 1.1, 0.9, 1.0, 1.3, 0.7, 1.0, 1.1, 0.9, 1.2, 0.8, 1.0, 1.1, 1.0]
        for v in volumes:
            w173.record_volume(v)

        assert not w173.is_entry_blocked()
        assert w173.get_volume_kurtosis() < 2.0
    finally:
        w173.reset()


def test_wave173_whale_order_leptokurtic_shock_triggers_block():
    w173.reset()
    try:
        # 18 tiny retail orders followed by massive institutional whale order
        for _ in range(18):
            w173.record_volume(1.0)

        w173.record_volume(60.0)

        assert w173.get_volume_kurtosis() >= 6.0
        assert w173.is_entry_blocked()
        assert w173.is_blocked()
    finally:
        w173.reset()


def test_wave173_insufficient_samples_no_block():
    w173.reset()
    try:
        # Less than 15 samples
        for _ in range(5):
            w173.record_volume(50.0)

        assert not w173.is_entry_blocked()
        assert w173.get_volume_kurtosis() == 0.0
    finally:
        w173.reset()


def test_wave173_invalid_and_zero_volume_fail_closed():
    w173.reset()
    try:
        w173.record_volume(1.0)
        # Invalid inputs safely rejected
        w173.record_volume(0.0)
        w173.record_volume(-5.0)
        w173.record_volume("bad")
        w173.record_volume(True)
        w173.record_volume(float("nan"))
        w173.record_volume(float("inf"))

        assert not w173.is_entry_blocked()
        assert w173.get_volume_kurtosis() == 0.0
    finally:
        w173.reset()


def test_wave173_update_alias_and_reset():
    w173.reset()
    try:
        for _ in range(18):
            w173.update(1.0)
        w173.update(70.0)

        assert w173.is_entry_blocked()

        w173.reset()
        assert not w173.is_entry_blocked()
        assert not w173.is_blocked()
        assert w173.get_volume_kurtosis() == 0.0
    finally:
        w173.reset()
