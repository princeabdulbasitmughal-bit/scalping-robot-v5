"""
test_batch193.py
----------------
Unit tests for Batch 193:
- wave152_order_size_herding_guard.py (5 tests)
- wave153_realized_kernel_volatility_guard.py (5 tests)
"""

import math
import time
import pytest

import wave152_order_size_herding_guard as w152
import wave153_realized_kernel_volatility_guard as w153


# ===========================================================================
# wave152_order_size_herding_guard tests
# ===========================================================================

def test_wave152_normal_varying_sizes_no_block():
    w152.reset()
    try:
        sizes = [1.0, 2.5, 0.5, 3.0, 1.2, 0.8, 4.0, 2.1]
        for idx, s in enumerate(sizes):
            w152.record_trade_size(s, ts=100.0 + idx)
            assert not w152.is_entry_blocked()
        assert w152.get_herding_run_length() == 1
    finally:
        w152.reset()


def test_wave152_herding_streak_triggers_block():
    w152.reset()
    try:
        t0 = 200.0
        # 6 consecutive trades of identical size (5.0 lots) within 5 seconds
        for i in range(6):
            w152.record_trade_size(5.0, ts=t0 + i * 0.5)

        assert w152.get_herding_run_length() == 6
        assert w152.is_entry_blocked()
        assert w152.is_blocked()
    finally:
        w152.reset()


def test_wave152_time_gap_resets_streak():
    w152.reset()
    try:
        # 4 identical size trades
        t0 = 500.0
        for i in range(4):
            w152.record_trade_size(2.0, ts=t0 + i * 1.0)
        assert w152.get_herding_run_length() == 4
        assert not w152.is_entry_blocked()

        # Next trade arrives 15.0 seconds later (> 10.0s window)
        w152.record_trade_size(2.0, ts=t0 + 20.0)
        assert w152.get_herding_run_length() == 1
        assert not w152.is_entry_blocked()
    finally:
        w152.reset()


def test_wave152_invalid_inputs_fail_closed():
    w152.reset()
    try:
        w152.record_trade_size(1.0, ts=10.0)
        # Invalid inputs should be silently discarded without altering streak
        w152.record_trade_size("invalid_size")
        w152.record_trade_size(True)
        w152.record_trade_size(0.0)
        w152.record_trade_size(-5.0)
        w152.record_trade_size(float("nan"))
        w152.record_trade_size(float("inf"))

        assert w152.get_herding_run_length() == 1
        assert not w152.is_entry_blocked()
    finally:
        w152.reset()


def test_wave152_update_alias_and_reset():
    w152.reset()
    try:
        t0 = 1000.0
        for i in range(6):
            w152.update(3.5, ts=t0 + i * 0.2)
        assert w152.is_entry_blocked()

        w152.reset()
        assert not w152.is_entry_blocked()
        assert not w152.is_blocked()
        assert w152.get_herding_run_length() == 0
    finally:
        w152.reset()


# ===========================================================================
# wave153_realized_kernel_volatility_guard tests
# ===========================================================================

def test_wave153_flat_price_series_low_vol_no_block():
    w153.reset()
    try:
        base = 100.0
        for i in range(25):
            # Gentle drift ~0.01%
            p = base + (0.005 if i % 2 == 0 else -0.005)
            w153.record_price(p)

        assert not w153.is_entry_blocked()
        assert w153.get_realized_kernel_vol() < 0.0010
    finally:
        w153.reset()


def test_wave153_high_volatility_jump_triggers_block():
    w153.reset()
    try:
        # Large price gyrations ~1-3% per step
        prices = [
            100.0, 102.5, 98.0, 103.0, 97.5, 104.0, 96.0, 103.5,
            97.0, 105.0, 95.5, 104.5, 96.5, 105.5, 95.0, 106.0,
            94.0, 107.0, 93.0, 108.0, 92.0, 109.0, 91.0
        ]
        for p in prices:
            w153.record_price(p)

        assert w153.get_realized_kernel_vol() >= 0.0050
        assert w153.is_entry_blocked()
        assert w153.is_blocked()
    finally:
        w153.reset()


def test_wave153_microstructure_noise_dampening():
    w153.reset()
    try:
        # High-frequency alternating bid-ask bounce with minimal true drift (e.g. 100.00 <-> 100.01)
        for i in range(25):
            p = 100.01 if i % 2 == 1 else 100.00
            w153.record_price(p)

        # Autocovariance kernel cancels out high-frequency bounce
        assert w153.get_realized_kernel_vol() < 0.0010
        assert not w153.is_entry_blocked()
    finally:
        w153.reset()


def test_wave153_invalid_prices_fail_closed():
    w153.reset()
    try:
        w153.record_price(100.0)
        # Invalid inputs should be safely ignored
        w153.record_price("bad_price")
        w153.record_price(True)
        w153.record_price(0.0)
        w153.record_price(-10.0)
        w153.record_price(float("nan"))
        w153.record_price(float("inf"))

        assert not w153.is_entry_blocked()
        assert w153.get_realized_kernel_vol() == 0.0
    finally:
        w153.reset()


def test_wave153_update_alias_and_reset():
    w153.reset()
    try:
        prices = [
            100.0, 103.0, 97.0, 104.0, 96.0, 105.0, 95.0, 106.0,
            94.0, 107.0, 93.0, 108.0, 92.0, 109.0, 91.0, 110.0
        ]
        for p in prices:
            w153.update(p)

        assert w153.is_entry_blocked()

        w153.reset()
        assert not w153.is_entry_blocked()
        assert not w153.is_blocked()
        assert w153.get_realized_kernel_vol() == 0.0
    finally:
        w153.reset()
