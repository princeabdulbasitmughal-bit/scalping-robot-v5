"""
test_batch197.py
----------------
Unit tests for Batch 197:
- wave160_order_book_depth_imbalance_acceleration_guard.py (5 tests)
- wave161_tick_time_skewness_exhaustion_guard.py (5 tests)
"""

import math
import time
import pytest

import wave160_order_book_depth_imbalance_acceleration_guard as w160
import wave161_tick_time_skewness_exhaustion_guard as w161


# ===========================================================================
# wave160_order_book_depth_imbalance_acceleration_guard tests
# ===========================================================================

def test_wave160_normal_smooth_depth_no_block():
    w160.reset()
    try:
        t0 = 100.0
        # Gentle gradual changes in depth
        for i in range(10):
            b = 100.0 + i * 0.5
            a = 100.0 - i * 0.5
            w160.record_depth(bid_depth=b, ask_depth=a, ts=t0 + i * 0.5)

        assert not w160.is_entry_blocked()
        assert abs(w160.get_imbalance_acceleration()) < 1.0
    finally:
        w160.reset()


def test_wave160_imbalance_acceleration_surge_triggers_block():
    w160.reset()
    try:
        t0 = 200.0
        # t0: initial balanced book
        w160.record_depth(bid_depth=100.0, ask_depth=100.0, ts=t0)
        # t0 + 0.1: unchanged
        w160.record_depth(bid_depth=100.0, ask_depth=100.0, ts=t0 + 0.1)
        # t0 + 0.2: massive sudden liquidity collapse on bid side (OBI crashes from 0.0 to -0.90)
        # velocity = -9.0 s^-1, acceleration = -90.0 s^-2 (|accel| >= 4.0)
        w160.record_depth(bid_depth=10.0, ask_depth=190.0, ts=t0 + 0.2)

        assert abs(w160.get_imbalance_acceleration()) >= 4.0
        assert w160.is_entry_blocked()
        assert w160.is_blocked()
    finally:
        w160.reset()


def test_wave160_sub_millisecond_jitter_ignored():
    w160.reset()
    try:
        t0 = 300.0
        w160.record_depth(100.0, 100.0, ts=t0)
        # Interval less than MIN_DT (0.005s) should be safely bypassed
        w160.record_depth(50.0, 150.0, ts=t0 + 0.001)

        assert not w160.is_entry_blocked()
        assert w160.get_imbalance_acceleration() == 0.0
    finally:
        w160.reset()


def test_wave160_invalid_depths_fail_closed():
    w160.reset()
    try:
        w160.record_depth(100.0, 100.0, ts=10.0)
        # Invalid inputs should be safely ignored
        w160.record_depth(bid_depth=-10.0, ask_depth=50.0, ts=11.0)
        w160.record_depth(bid_depth=0.0, ask_depth=0.0, ts=12.0)
        w160.record_depth(bid_depth="bad", ask_depth=50.0, ts=13.0)
        w160.record_depth(bid_depth=True, ask_depth=50.0, ts=14.0)
        w160.record_depth(bid_depth=float("nan"), ask_depth=50.0, ts=15.0)

        assert not w160.is_entry_blocked()
        assert w160.get_imbalance_acceleration() == 0.0
    finally:
        w160.reset()


def test_wave160_update_alias_and_reset():
    w160.reset()
    try:
        t0 = 500.0
        w160.update(100.0, 100.0, ts=t0)
        w160.update(100.0, 100.0, ts=t0 + 0.1)
        w160.update(190.0, 10.0, ts=t0 + 0.2)
        assert w160.is_entry_blocked()

        w160.reset()
        assert not w160.is_entry_blocked()
        assert not w160.is_blocked()
        assert w160.get_imbalance_acceleration() == 0.0
    finally:
        w160.reset()


# ===========================================================================
# wave161_tick_time_skewness_exhaustion_guard tests
# ===========================================================================

def test_wave161_regular_cadence_low_skewness_no_block():
    w161.reset()
    try:
        t0 = 1000.0
        # Evenly spaced ticks every 0.10s
        for i in range(25):
            w161.record_tick(ts=t0 + i * 0.10)

        assert not w161.is_entry_blocked()
        assert abs(w161.get_arrival_skewness()) < 1.0
    finally:
        w161.reset()


def test_wave161_quote_stuffing_burst_triggers_block():
    w161.reset()
    try:
        t0 = 2000.0
        # Hyper-compressed quote stuffing burst: ticks every 1ms (0.001s <= 0.005s threshold)
        for i in range(20):
            w161.record_tick(ts=t0 + i * 0.001)

        assert w161.is_entry_blocked()
        assert w161.is_blocked()
    finally:
        w161.reset()


def test_wave161_extreme_asymmetry_skewness_triggers_block():
    w161.reset()
    try:
        t0 = 3000.0
        # 18 tiny intervals (0.010s) followed by massive long pauses (5.0s) causing extreme positive skewness
        cur = t0
        w161.record_tick(ts=cur)
        for _ in range(18):
            cur += 0.010
            w161.record_tick(ts=cur)

        # Huge void intervals
        for _ in range(2):
            cur += 10.0
            w161.record_tick(ts=cur)

        assert w161.get_arrival_skewness() >= 2.50
        assert w161.is_entry_blocked()
        assert w161.is_blocked()
    finally:
        w161.reset()


def test_wave161_retrogressive_and_invalid_timestamps_ignored():
    w161.reset()
    try:
        w161.record_tick(ts=100.0)
        # Retrogressive or identical timestamps should be disregarded
        w161.record_tick(ts=95.0)
        w161.record_tick(ts=100.0)
        w161.record_tick(ts="bad")
        w161.record_tick(ts=True)
        w161.record_tick(ts=float("nan"))
        w161.record_tick(ts=float("inf"))

        assert not w161.is_entry_blocked()
        assert w161.get_arrival_skewness() == 0.0
    finally:
        w161.reset()


def test_wave161_update_alias_and_reset():
    w161.reset()
    try:
        t0 = 4000.0
        for i in range(20):
            w161.update(ts=t0 + i * 0.001)

        assert w161.is_entry_blocked()

        w161.reset()
        assert not w161.is_entry_blocked()
        assert not w161.is_blocked()
        assert w161.get_arrival_skewness() == 0.0
    finally:
        w161.reset()
