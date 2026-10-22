"""
test_batch209.py
----------------
Unit tests for Batch 209:
- wave184_effective_spread_drift_guard.py (5 tests)
- wave185_signed_volume_acceleration_guard.py (5 tests)
"""

import math
import time
import pytest

import wave184_effective_spread_drift_guard as w184
import wave185_signed_volume_acceleration_guard as w185


# ===========================================================================
# wave184_effective_spread_drift_guard tests
# ===========================================================================

def test_wave184_tight_stable_effective_spread_no_block():
    w184.reset()
    try:
        # Tight stable effective spread: mid = 100.01, trade = 100.015 -> S_eff = 0.01 (1 bps)
        for _ in range(20):
            w184.record_trade_spread(trade_price=100.015, bid=100.00, ask=100.02)

        assert not w184.is_entry_blocked()
        assert w184.get_effective_spread_bps() < 0.00030
    finally:
        w184.reset()


def test_wave184_hard_ceiling_effective_spread_triggers_block():
    w184.reset()
    try:
        # Trade price 100.10 while quotes are 100.00 / 100.02 -> Mid = 100.01
        # S_eff = 2 * (100.10 - 100.01) = 0.18 -> 18 bps >= 8.0 bps ceiling
        w184.record_trade_spread(trade_price=100.10, bid=100.00, ask=100.02)

        assert w184.is_entry_blocked()
        assert w184.is_blocked()
        assert w184.get_effective_spread_bps() >= 0.00080
    finally:
        w184.reset()


def test_wave184_relative_drift_widening_triggers_block():
    w184.reset()
    try:
        # 16 trades at tight baseline (mid = 100.01, trade = 100.02 -> diff = 0.01 -> S_eff = 0.02 -> ~2 bps)
        for _ in range(16):
            w184.record_trade_spread(trade_price=100.02, bid=100.00, ask=100.02)

        assert not w184.is_entry_blocked()

        # Spread suddenly widens: mid = 100.01, trade = 100.035 -> diff = 0.025 -> S_eff = 0.05 -> ~5 bps (+150% drift >= 100%)
        w184.record_trade_spread(trade_price=100.035, bid=100.00, ask=100.02)

        assert w184.is_entry_blocked()
    finally:
        w184.reset()


def test_wave184_invalid_inputs_fail_closed():
    w184.reset()
    try:
        w184.record_trade_spread(100.01, 100.00, 100.02)
        # Invalid inputs safely rejected
        w184.record_trade_spread(True, 100.00, 100.02)
        w184.record_trade_spread(100.01, False, 100.02)
        w184.record_trade_spread(100.01, 100.00, "bad")
        w184.record_trade_spread(float("nan"), 100.00, 100.02)
        w184.record_trade_spread(100.01, float("inf"), 100.02)
        w184.record_trade_spread(-50.0, 100.00, 100.02)

        # Crossed quotes: bid > ask safely rejected
        w184.record_trade_spread(100.01, 100.05, 100.02)

        assert not w184.is_entry_blocked()
        assert w184.get_status()["sample_count"] == 1
    finally:
        w184.reset()


def test_wave184_aliases_get_status_and_reset():
    w184.reset()
    try:
        w184.update(100.10, 100.00, 100.02)
        assert w184.is_blocked()
        status = w184.get_status()
        assert status["is_blocked"] is True
        assert status["latest_spread_bps"] >= 0.00080

        w184.reset()
        assert not w184.is_blocked()
        assert w184.get_effective_spread_bps() == 0.0
        assert w184.get_status()["sample_count"] == 0
    finally:
        w184.reset()


# ===========================================================================
# wave185_signed_volume_acceleration_guard tests
# ===========================================================================

def test_wave185_smooth_uniform_flow_no_block():
    w185.reset()
    try:
        # Uniform trade rate: 1.0 lot every 0.1s in same direction
        # Velocity = 10.0 lots/s, acceleration = 0.0 lots/s^2
        t = 1000.0
        p = 100.0
        for _ in range(10):
            p += 0.01
            w185.record_trade(price=p, volume=1.0, ts=t, sign=1)
            t += 0.10

        assert not w185.is_entry_blocked()
        assert abs(w185.get_flow_acceleration()) < 1.0
    finally:
        w185.reset()


def test_wave185_flow_surge_acceleration_triggers_block():
    w185.reset()
    try:
        # Rapid surge in volume:
        # Trade 1 at t=1000.0: 0.1 lot
        # Trade 2 at t=1000.1: 0.1 lot -> vel_1 = 1.0 lots/s
        # Trade 3 at t=1000.2: 5.0 lots -> vel_2 = 50.0 lots/s
        # Acceleration = (50.0 - 1.0) / 0.1 = 490.0 >= 15.0 lots/s^2
        w185.record_trade(price=100.01, volume=0.1, ts=1000.0, sign=1)
        w185.record_trade(price=100.02, volume=0.1, ts=1000.1, sign=1)
        w185.record_trade(price=100.05, volume=5.0, ts=1000.2, sign=1)

        assert w185.is_entry_blocked()
        assert w185.is_blocked()
        assert w185.get_flow_acceleration() >= 15.0
    finally:
        w185.reset()


def test_wave185_stale_or_sub_millisecond_interval_ignored():
    w185.reset()
    try:
        # Interval < 5ms (0.001s) is ignored to prevent division-by-zero artifacts
        w185.record_trade(price=100.01, volume=0.1, ts=1000.0, sign=1)
        w185.record_trade(price=100.02, volume=10.0, ts=1000.001, sign=1)
        assert not w185.is_entry_blocked()

        w185.reset()
        # Interval > 2.0s is ignored as stale
        w185.record_trade(price=100.01, volume=0.1, ts=1000.0, sign=1)
        w185.record_trade(price=100.02, volume=10.0, ts=1005.0, sign=1)
        assert not w185.is_entry_blocked()
    finally:
        w185.reset()


def test_wave185_invalid_inputs_fail_closed():
    w185.reset()
    try:
        # Invalid inputs safely rejected
        w185.record_trade(price=True, volume=1.0, ts=1000.0)
        w185.record_trade(price=100.0, volume=False, ts=1000.0)
        w185.record_trade(price="bad", volume=1.0, ts=1000.0)
        w185.record_trade(price=100.0, volume=1.0, ts=True)
        w185.record_trade(price=float("nan"), volume=1.0, ts=1000.0)
        w185.record_trade(price=100.0, volume=float("inf"), ts=1000.0)
        w185.record_trade(price=-100.0, volume=1.0, ts=1000.0)
        w185.record_trade(price=100.0, volume=-1.0, ts=1000.0)

        assert not w185.is_entry_blocked()
        assert w185.get_flow_acceleration() == 0.0
    finally:
        w185.reset()


def test_wave185_aliases_get_status_and_reset():
    w185.reset()
    try:
        w185.update(price=100.01, volume=0.1, ts=1000.0, sign=1)
        w185.update(price=100.02, volume=0.1, ts=1000.1, sign=1)
        w185.update(price=100.05, volume=5.0, ts=1000.2, sign=1)

        assert w185.is_blocked()
        status = w185.get_status()
        assert status["is_blocked"] is True
        assert status["latest_acceleration"] >= 15.0

        w185.reset()
        assert not w185.is_blocked()
        assert w185.get_flow_acceleration() == 0.0
    finally:
        w185.reset()
