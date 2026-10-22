"""
test_batch198.py
----------------
Unit tests for Batch 198:
- wave162_parkinson_high_low_volatility_guard.py (5 tests)
- wave163_trade_size_asymmetry_skewness_guard.py (5 tests)
"""

import math
import time
import pytest

import wave162_parkinson_high_low_volatility_guard as w162
import wave163_trade_size_asymmetry_skewness_guard as w163


# ===========================================================================
# wave162_parkinson_high_low_volatility_guard tests
# ===========================================================================

def test_wave162_normal_tight_bars_no_block():
    w162.reset()
    try:
        # Tight micro-bars with ~0.1% range
        for _ in range(12):
            w162.record_bar(high_p=100.10, low_p=100.00)

        assert not w162.is_entry_blocked()
        assert w162.get_parkinson_vol() < 0.0020
    finally:
        w162.reset()


def test_wave162_range_volatility_burst_triggers_block():
    w162.reset()
    try:
        # Wide range micro-bars: ~3% range (violent diffusion)
        for _ in range(5):
            w162.record_bar(high_p=101.50, low_p=98.50)

        assert w162.get_parkinson_vol() >= 0.0055
        assert w162.is_entry_blocked()
        assert w162.is_blocked()
    finally:
        w162.reset()


def test_wave162_insufficient_bars_no_block():
    w162.reset()
    try:
        # Less than 3 bars
        w162.record_bar(high_p=105.0, low_p=95.0)
        w162.record_bar(high_p=106.0, low_p=94.0)

        assert not w162.is_entry_blocked()
        assert w162.get_parkinson_vol() == 0.0
    finally:
        w162.reset()


def test_wave162_invalid_high_low_fail_closed():
    w162.reset()
    try:
        w162.record_bar(high_p=100.1, low_p=100.0)
        # Invalid inputs safely rejected
        w162.record_bar(high_p=99.0, low_p=100.0) # High < Low
        w162.record_bar(high_p=-5.0, low_p=-10.0)
        w162.record_bar(high_p="bad", low_p=100.0)
        w162.record_bar(high_p=100.0, low_p=True)
        w162.record_bar(high_p=float("nan"), low_p=100.0)

        assert not w162.is_entry_blocked()
        assert w162.get_parkinson_vol() == 0.0
    finally:
        w162.reset()


def test_wave162_update_alias_and_reset():
    w162.reset()
    try:
        for _ in range(5):
            w162.update(high_p=102.0, low_p=98.0)

        assert w162.is_entry_blocked()

        w162.reset()
        assert not w162.is_entry_blocked()
        assert not w162.is_blocked()
        assert w162.get_parkinson_vol() == 0.0
    finally:
        w162.reset()


# ===========================================================================
# wave163_trade_size_asymmetry_skewness_guard tests
# ===========================================================================

def test_wave163_balanced_flow_no_block():
    w163.reset()
    try:
        # Symmetric 1.0 lot trades alternating buy (+1) and sell (-1)
        for i in range(16):
            sign = 1 if i % 2 == 0 else -1
            w163.record_trade(volume=1.0, sign=sign)

        assert not w163.is_entry_blocked()
        assert abs(w163.get_volume_skewness()) < 1.0
    finally:
        w163.reset()


def test_wave163_volume_concentration_imbalance_triggers_block():
    w163.reset()
    try:
        # 15 consecutive buyer trades (100% buy concentration >= 85%)
        for _ in range(15):
            w163.record_trade(volume=2.0, sign=1)

        assert w163.is_entry_blocked()
        assert w163.is_blocked()
    finally:
        w163.reset()


def test_wave163_signed_volume_skewness_triggers_block():
    w163.reset()
    try:
        # 14 small seller fills (-0.1) followed by 1 massive buyer sweep (+15.0)
        for _ in range(14):
            w163.record_trade(volume=0.1, sign=-1)

        w163.record_trade(volume=15.0, sign=1)

        assert w163.get_volume_skewness() >= 2.50
        assert w163.is_entry_blocked()
        assert w163.is_blocked()
    finally:
        w163.reset()


def test_wave163_invalid_and_zero_volume_fail_closed():
    w163.reset()
    try:
        w163.record_trade(volume=1.0, sign=1)
        # Invalid inputs safely rejected
        w163.record_trade(volume=0.0, sign=1)
        w163.record_trade(volume=-2.0, sign=1)
        w163.record_trade(volume=1.0, sign=0) # neutral sign ignored
        w163.record_trade(volume="bad", sign=1)
        w163.record_trade(volume=1.0, sign=True)
        w163.record_trade(volume=float("nan"), sign=1)

        assert not w163.is_entry_blocked()
        assert w163.get_volume_skewness() == 0.0
    finally:
        w163.reset()


def test_wave163_update_alias_and_reset():
    w163.reset()
    try:
        for _ in range(15):
            w163.update(volume=3.0, sign=-1)

        assert w163.is_entry_blocked()

        w163.reset()
        assert not w163.is_entry_blocked()
        assert not w163.is_blocked()
        assert w163.get_volume_skewness() == 0.0
    finally:
        w163.reset()
