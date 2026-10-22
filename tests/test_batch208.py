"""
test_batch208.py
----------------
Unit tests for Batch 208:
- wave182_microstructure_noise_ratio_guard.py (5 tests)
- wave183_limit_order_cancellation_depth_ratio_guard.py (5 tests)
"""

import math
import time
import pytest

import wave182_microstructure_noise_ratio_guard as w182
import wave183_limit_order_cancellation_depth_ratio_guard as w183


# ===========================================================================
# wave182_microstructure_noise_ratio_guard tests
# ===========================================================================

def test_wave182_smooth_trending_prices_low_noise_no_block():
    w182.reset()
    try:
        # Smooth directional price advance: low microstructure noise
        p = 100.0
        w182.record_price(p)
        for _ in range(25):
            p += 0.05
            w182.record_price(p)

        assert not w182.is_entry_blocked()
        assert w182.get_noise_ratio() < 2.5
    finally:
        w182.reset()


def test_wave182_extreme_bid_ask_bounce_triggers_block():
    w182.reset()
    try:
        # High-frequency ping-pong whipsaw: 100.00 <-> 100.10
        # High 1-tick dense variance, but near-zero 5-tick displacement -> NMR spikes
        for i in range(25):
            p = 100.10 if i % 2 == 1 else 100.00
            w182.record_price(p)

        assert w182.get_noise_ratio() >= 4.5
        assert w182.is_entry_blocked()
        assert w182.is_blocked()
    finally:
        w182.reset()


def test_wave182_insufficient_samples_no_block():
    w182.reset()
    try:
        # Only 10 ticks (< MIN_SAMPLES 20)
        for i in range(10):
            p = 100.10 if i % 2 == 1 else 100.00
            w182.record_price(p)

        assert not w182.is_entry_blocked()
        assert w182.get_status()["sample_count"] == 10
    finally:
        w182.reset()


def test_wave182_invalid_prices_fail_closed():
    w182.reset()
    try:
        w182.record_price(100.0)
        # Invalid inputs safely rejected
        w182.record_price(True)
        w182.record_price(False)
        w182.record_price("bad_price")
        w182.record_price(float("nan"))
        w182.record_price(float("inf"))
        w182.record_price(-50.0)
        w182.record_price(0.0)

        assert not w182.is_entry_blocked()
        assert w182.get_status()["sample_count"] == 1
    finally:
        w182.reset()


def test_wave182_aliases_get_status_and_reset():
    w182.reset()
    try:
        for i in range(25):
            p = 100.15 if i % 2 == 1 else 100.00
            w182.update(p)

        assert w182.is_blocked()
        status = w182.get_status()
        assert status["is_blocked"] is True
        assert status["sample_count"] == 25

        w182.reset()
        assert not w182.is_blocked()
        assert w182.get_noise_ratio() == 1.0
        assert w182.get_status()["sample_count"] == 0
    finally:
        w182.reset()


# ===========================================================================
# wave183_limit_order_cancellation_depth_ratio_guard tests
# ===========================================================================

def test_wave183_normal_cancellations_no_block():
    w183.reset()
    try:
        t = 1000.0
        # 5 cancellations of 2.0 lots against depth of 50.0 -> total 10.0 / 50.0 = 0.20 (< 2.50)
        for i in range(5):
            w183.record_cancellation(cancelled_volume=2.0, current_depth=50.0, ts=t + i)

        assert not w183.is_entry_blocked()
        assert w183.get_cdr() < 1.0
    finally:
        w183.reset()


def test_wave183_massive_cancellation_wave_triggers_block():
    w183.reset()
    try:
        t = 1000.0
        # 6 cancellations of 25.0 lots against depth of 20.0 -> total 150.0 / 20.0 = 7.50 (>= 2.50)
        for i in range(6):
            w183.record_cancellation(cancelled_volume=25.0, current_depth=20.0, ts=t + i)

        assert w183.is_entry_blocked()
        assert w183.is_blocked()
        assert w183.get_cdr() >= 2.50
    finally:
        w183.reset()


def test_wave183_insufficient_cancellations_or_dust_depth_no_block():
    w183.reset()
    try:
        t = 1000.0
        # Only 3 cancellations (< MIN_CANCELLATIONS 5)
        for i in range(3):
            w183.record_cancellation(cancelled_volume=30.0, current_depth=10.0, ts=t + i)
        assert not w183.is_entry_blocked()

        w183.reset()
        # Depth is tiny dust queue (< MIN_DEPTH 5.0)
        for i in range(6):
            w183.record_cancellation(cancelled_volume=5.0, current_depth=2.0, ts=t + i)
        assert not w183.is_entry_blocked()
    finally:
        w183.reset()


def test_wave183_invalid_inputs_fail_closed():
    w183.reset()
    try:
        # Invalid inputs safely rejected
        w183.record_cancellation(True, 50.0, ts=1000.0)
        w183.record_cancellation(10.0, False, ts=1000.0)
        w183.record_cancellation("bad", 50.0, ts=1000.0)
        w183.record_cancellation(10.0, 50.0, ts=True)
        w183.record_cancellation(float("nan"), 50.0, ts=1000.0)
        w183.record_cancellation(10.0, float("inf"), ts=1000.0)
        w183.record_cancellation(-10.0, 50.0, ts=1000.0)
        w183.record_cancellation(10.0, 0.0, ts=1000.0)

        assert not w183.is_entry_blocked()
        assert w183.get_cdr() == 0.0
        assert w183.get_status()["cancellation_count"] == 0
    finally:
        w183.reset()


def test_wave183_aliases_get_status_and_reset():
    w183.reset()
    try:
        t = 1000.0
        for i in range(6):
            w183.update(cancelled_volume=20.0, current_depth=20.0, ts=t + i)

        assert w183.is_blocked()
        status = w183.get_status()
        assert status["is_blocked"] is True
        assert status["cancellation_count"] == 6

        w183.reset()
        assert not w183.is_blocked()
        assert w183.get_cdr() == 0.0
        assert w183.get_status()["cancellation_count"] == 0
    finally:
        w183.reset()
