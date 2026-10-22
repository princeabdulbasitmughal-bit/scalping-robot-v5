"""
test_batch194.py
----------------
Unit tests for Batch 194:
- wave154_kyle_lambda_price_impact_guard.py (5 tests)
- wave155_hurst_exponent_mean_reversion_guard.py (5 tests)
"""

import math
import time
import pytest

import wave154_kyle_lambda_price_impact_guard as w154
import wave155_hurst_exponent_mean_reversion_guard as w155


# ===========================================================================
# wave154_kyle_lambda_price_impact_guard tests
# ===========================================================================

def test_wave154_normal_balanced_flow_no_block():
    w154.reset()
    try:
        # Balanced flow: small random variations where lambda is negligible
        for i in range(25):
            dp = 0.0001 if i % 2 == 0 else -0.0001
            vol = 1.0 if i % 3 == 0 else -1.0
            w154.record_trade_impact(price_delta=dp, signed_volume=vol)

        assert not w154.is_entry_blocked()
        assert abs(w154.get_kyle_lambda()) < 0.0010
    finally:
        w154.reset()


def test_wave154_severe_price_impact_triggers_block():
    w154.reset()
    try:
        # High impact: every 1 unit of signed volume moves price by 0.0040 (lambda ~ 0.0040 >= 0.0020)
        for i in range(15):
            q = (i - 7) * 2.0  # signed volume from -14 to +14
            dp = q * 0.0040    # strong proportional price impact
            w154.record_trade_impact(price_delta=dp, signed_volume=q)

        assert w154.get_kyle_lambda() >= 0.0020
        assert w154.is_entry_blocked()
        assert w154.is_blocked()
    finally:
        w154.reset()


def test_wave154_insufficient_samples_no_block():
    w154.reset()
    try:
        # Less than MIN_SAMPLES (10)
        for i in range(5):
            w154.record_trade_impact(price_delta=0.05, signed_volume=10.0)

        assert not w154.is_entry_blocked()
        assert w154.get_kyle_lambda() == 0.0
    finally:
        w154.reset()


def test_wave154_invalid_inputs_fail_closed():
    w154.reset()
    try:
        w154.record_trade_impact(price_delta=0.001, signed_volume=1.0)
        # Invalid inputs should be silently discarded
        w154.record_trade_impact(price_delta="bad", signed_volume=1.0)
        w154.record_trade_impact(price_delta=0.001, signed_volume=True)
        w154.record_trade_impact(price_delta=float("nan"), signed_volume=1.0)
        w154.record_trade_impact(price_delta=0.001, signed_volume=float("inf"))

        assert not w154.is_entry_blocked()
        assert w154.get_kyle_lambda() == 0.0
    finally:
        w154.reset()


def test_wave154_update_alias_and_reset():
    w154.reset()
    try:
        for i in range(15):
            q = (i - 7) * 2.0
            dp = q * 0.0050
            w154.update(price_delta=dp, signed_volume=q)

        assert w154.is_entry_blocked()

        w154.reset()
        assert not w154.is_entry_blocked()
        assert not w154.is_blocked()
        assert w154.get_kyle_lambda() == 0.0
    finally:
        w154.reset()


# ===========================================================================
# wave155_hurst_exponent_mean_reversion_guard tests
# ===========================================================================

def test_wave155_mean_reverting_series_healthy_no_block():
    w155.reset()
    try:
        # Alternating mild oscillations around 100.0: anti-persistent / stationary
        prices = [100.0 + (0.10 if i % 2 == 1 else -0.10) for i in range(35)]
        for p in prices:
            w155.record_price(p)

        h = w155.get_hurst_exponent()
        # In a bounded oscillating series, Hurst should be well below 0.75
        assert h < 0.75
        assert not w155.is_entry_blocked()
    finally:
        w155.reset()


def test_wave155_persistent_trend_runaway_triggers_block():
    w155.reset()
    try:
        # Monotonically runaway compounding trend over 35 steps
        prices = [100.0 * (1.005 ** i) for i in range(35)]
        for p in prices:
            w155.record_price(p)

        h = w155.get_hurst_exponent()
        assert h >= 0.75
        assert w155.is_entry_blocked()
        assert w155.is_blocked()
    finally:
        w155.reset()


def test_wave155_insufficient_data_default_hurst():
    w155.reset()
    try:
        # Fewer than WINDOW_SIZE (32)
        for i in range(15):
            w155.record_price(100.0 + i)

        assert w155.get_hurst_exponent() == 0.50
        assert not w155.is_entry_blocked()
    finally:
        w155.reset()


def test_wave155_invalid_prices_fail_closed():
    w155.reset()
    try:
        w155.record_price(100.0)
        # Invalid inputs should be safely ignored
        w155.record_price("bad_price")
        w155.record_price(True)
        w155.record_price(0.0)
        w155.record_price(-15.0)
        w155.record_price(float("nan"))
        w155.record_price(float("inf"))

        assert not w155.is_entry_blocked()
        assert w155.get_hurst_exponent() == 0.50
    finally:
        w155.reset()


def test_wave155_update_alias_and_reset():
    w155.reset()
    try:
        prices = [100.0 * (1.006 ** i) for i in range(35)]
        for p in prices:
            w155.update(p)

        assert w155.is_entry_blocked()

        w155.reset()
        assert not w155.is_entry_blocked()
        assert not w155.is_blocked()
        assert w155.get_hurst_exponent() == 0.50
    finally:
        w155.reset()
