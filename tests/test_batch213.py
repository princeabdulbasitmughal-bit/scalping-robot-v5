"""
test_batch213.py
----------------
Unit tests for Batch 213:
- wave192_order_flow_burst_concentration_guard.py (5 tests)
- wave193_level2_queue_replenishment_rate_guard.py (5 tests)
"""

import math
import time
import pytest

import wave192_order_flow_burst_concentration_guard as w192
import wave193_level2_queue_replenishment_rate_guard as w193


# ===========================================================================
# wave192_order_flow_burst_concentration_guard tests
# ===========================================================================

def test_wave192_dispersed_order_flow_low_hhi_no_block():
    w192.reset()
    try:
        # Uniform dispersed volume: 15 trades of 1.0 lot each -> HHI = 1/15 = 0.067
        for _ in range(15):
            w192.record_trade(1.0)

        assert not w192.is_entry_blocked()
        assert w192.get_hhi() < 0.20
    finally:
        w192.reset()


def test_wave192_whale_concentrated_burst_triggers_block():
    w192.reset()
    try:
        # 10 small retail trades of 0.1 lot (total 1.0 lot)
        for _ in range(10):
            w192.record_trade(0.1)

        # Single massive whale order of 15.0 lots (captures ~93% of burst volume)
        # HHI ~ 0.93^2 = 0.86 >= 0.50
        w192.record_trade(15.0)

        assert w192.is_entry_blocked()
        assert w192.is_blocked()
        assert w192.get_hhi() >= 0.50
    finally:
        w192.reset()


def test_wave192_insufficient_samples_no_block():
    w192.reset()
    try:
        # Only 5 trades (< MIN_SAMPLES 10)
        for _ in range(4):
            w192.record_trade(0.1)
        w192.record_trade(15.0)

        assert not w192.is_entry_blocked()
        assert w192.get_status()["sample_count"] == 5
    finally:
        w192.reset()


def test_wave192_invalid_inputs_fail_closed():
    w192.reset()
    try:
        w192.record_trade(1.0)
        # Invalid inputs safely rejected
        w192.record_trade(True)
        w192.record_trade(False)
        w192.record_trade("bad")
        w192.record_trade(float("nan"))
        w192.record_trade(float("inf"))
        w192.record_trade(-10.0)
        w192.record_trade(0.0)

        assert not w192.is_entry_blocked()
        assert w192.get_status()["sample_count"] == 1
    finally:
        w192.reset()


def test_wave192_aliases_get_status_and_reset():
    w192.reset()
    try:
        for _ in range(10):
            w192.update(0.1)
        w192.update(15.0)

        assert w192.is_blocked()
        status = w192.get_status()
        assert status["is_blocked"] is True
        assert status["hhi"] >= 0.50

        w192.reset()
        assert not w192.is_blocked()
        assert w192.get_hhi() == 0.0
        assert w192.get_status()["sample_count"] == 0
    finally:
        w192.reset()


# ===========================================================================
# wave193_level2_queue_replenishment_rate_guard tests
# ===========================================================================

def test_wave193_rapid_replenishment_healthy_book_no_block():
    w193.reset()
    try:
        # Baseline depth 20 lots at t=1000.0
        w193.record_depth(bid_depth=20.0, ask_depth=20.0, ts=1000.0)
        # Drop to 5.0 lots (75% drop) at t=1000.1
        w193.record_depth(bid_depth=5.0, ask_depth=20.0, ts=1000.1)
        # Restocks to 18.0 lots (needed = 15, restored = 13, ratio = 86.7%) at t=1000.2
        w193.record_depth(bid_depth=18.0, ask_depth=20.0, ts=1000.2)

        assert not w193.is_entry_blocked()
        assert w193.get_replenish_ratio() >= 0.80
    finally:
        w193.reset()


def test_wave193_replenishment_deficit_triggers_block():
    w193.reset()
    try:
        # Baseline depth 20 lots at t=1000.0
        w193.record_depth(bid_depth=20.0, ask_depth=20.0, ts=1000.0)
        # Drop to 4.0 lots (80% drop) at t=1000.1
        w193.record_depth(bid_depth=4.0, ask_depth=20.0, ts=1000.1)
        # Fails to restock by deadline t=1000.7 (window 0.50s expired, depth remains 4.0)
        w193.record_depth(bid_depth=4.0, ask_depth=20.0, ts=1000.7)

        assert w193.is_entry_blocked()
        assert w193.is_blocked()
        assert w193.get_replenish_ratio() < 0.30
    finally:
        w193.reset()


def test_wave193_small_drop_or_dust_depth_ignored():
    w193.reset()
    try:
        # Baseline depth 20.0, drop to 15.0 (only 25% drop < 50%) -> ignored
        w193.record_depth(bid_depth=20.0, ask_depth=20.0, ts=1000.0)
        w193.record_depth(bid_depth=15.0, ask_depth=20.0, ts=1000.1)
        w193.record_depth(bid_depth=15.0, ask_depth=20.0, ts=1000.7)
        assert not w193.is_entry_blocked()

        w193.reset()
        # Dust depth < 10.0 lots -> ignored
        w193.record_depth(bid_depth=6.0, ask_depth=6.0, ts=1000.0)
        w193.record_depth(bid_depth=1.0, ask_depth=6.0, ts=1000.1)
        w193.record_depth(bid_depth=1.0, ask_depth=6.0, ts=1000.7)
        assert not w193.is_entry_blocked()
    finally:
        w193.reset()


def test_wave193_invalid_inputs_fail_closed():
    w193.reset()
    try:
        # Invalid inputs safely rejected
        w193.record_depth(True, 20.0, ts=1000.0)
        w193.record_depth(20.0, False, ts=1000.0)
        w193.record_depth("bad", 20.0, ts=1000.0)
        w193.record_depth(20.0, 20.0, ts=True)
        w193.record_depth(float("nan"), 20.0, ts=1000.0)
        w193.record_depth(20.0, float("inf"), ts=1000.0)
        w193.record_depth(-10.0, 20.0, ts=1000.0)

        assert not w193.is_entry_blocked()
    finally:
        w193.reset()


def test_wave193_aliases_get_status_and_reset():
    w193.reset()
    try:
        w193.update(20.0, 20.0, ts=1000.0)
        w193.update(4.0, 20.0, ts=1000.1)
        w193.update(4.0, 20.0, ts=1000.7)

        assert w193.is_blocked()
        status = w193.get_status()
        assert status["is_blocked"] is True

        w193.reset()
        assert not w193.is_blocked()
        assert w193.get_replenish_ratio() == 1.0
    finally:
        w193.reset()
