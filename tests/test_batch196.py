"""
test_batch196.py
----------------
Unit tests for Batch 196:
- wave158_garman_klass_volatility_burst_guard.py (5 tests)
- wave159_trade_sign_autocorrelation_guard.py (5 tests)
"""

import math
import time
import pytest

import wave158_garman_klass_volatility_burst_guard as w158
import wave159_trade_sign_autocorrelation_guard as w159


# ===========================================================================
# wave158_garman_klass_volatility_burst_guard tests
# ===========================================================================

def test_wave158_normal_tight_microbars_no_block():
    w158.reset()
    try:
        # Tight micro-bars with ~0.1% range
        for _ in range(12):
            w158.record_bar(open_p=100.0, high_p=100.08, low_p=99.95, close_p=100.02)

        assert not w158.is_entry_blocked()
        assert w158.get_garman_klass_vol() < 0.0020
    finally:
        w158.reset()


def test_wave158_volatility_wick_burst_triggers_block():
    w158.reset()
    try:
        # Wide wick micro-bars with ~3% range (violent excursion)
        for _ in range(5):
            w158.record_bar(open_p=100.0, high_p=101.8, low_p=98.5, close_p=100.2)

        assert w158.get_garman_klass_vol() >= 0.0060
        assert w158.is_entry_blocked()
        assert w158.is_blocked()
    finally:
        w158.reset()


def test_wave158_insufficient_bars_no_block():
    w158.reset()
    try:
        # Less than 3 bars
        w158.record_bar(open_p=100.0, high_p=102.0, low_p=98.0, close_p=101.0)
        w158.record_bar(open_p=101.0, high_p=103.0, low_p=99.0, close_p=100.0)

        assert not w158.is_entry_blocked()
        assert w158.get_garman_klass_vol() == 0.0
    finally:
        w158.reset()


def test_wave158_invalid_ohlc_bars_fail_closed():
    w158.reset()
    try:
        w158.record_bar(open_p=100.0, high_p=100.1, low_p=99.9, close_p=100.0)
        # Invalid OHLC geometries should be safely discarded
        w158.record_bar(open_p=100.0, high_p=99.0, low_p=101.0, close_p=100.0) # High < Low
        w158.record_bar(open_p=100.0, high_p=100.1, low_p=100.5, close_p=100.0) # Low > Open
        w158.record_bar(open_p="bad", high_p=100.1, low_p=99.9, close_p=100.0)
        w158.record_bar(open_p=100.0, high_p=True, low_p=99.9, close_p=100.0)
        w158.record_bar(open_p=100.0, high_p=float("nan"), low_p=99.9, close_p=100.0)
        w158.record_bar(open_p=-10.0, high_p=100.1, low_p=99.9, close_p=100.0)

        assert not w158.is_entry_blocked()
        assert w158.get_garman_klass_vol() == 0.0
    finally:
        w158.reset()


def test_wave158_update_alias_and_reset():
    w158.reset()
    try:
        for _ in range(5):
            w158.update(open_p=100.0, high_p=102.5, low_p=98.0, close_p=101.0)

        assert w158.is_entry_blocked()

        w158.reset()
        assert not w158.is_entry_blocked()
        assert not w158.is_blocked()
        assert w158.get_garman_klass_vol() == 0.0
    finally:
        w158.reset()


# ===========================================================================
# wave159_trade_sign_autocorrelation_guard tests
# ===========================================================================

def test_wave159_balanced_alternating_flow_no_block():
    w159.reset()
    try:
        # Alternating buy and sell trades (+1, -1, +1, -1)
        for i in range(20):
            sign = 1 if i % 2 == 0 else -1
            w159.record_trade_sign(sign)

        corr = w159.get_sign_autocorrelation()
        # Alternating series has negative autocorrelation (around -1.0)
        assert corr < 0.0
        assert not w159.is_entry_blocked()
    finally:
        w159.reset()


def test_wave159_persistent_unidirectional_flow_triggers_block():
    w159.reset()
    try:
        # 20 consecutive buyer-initiated trades (metaorder buy sweep)
        for _ in range(20):
            w159.record_trade_sign(1)

        assert w159.get_sign_autocorrelation() == pytest.approx(1.0)
        assert w159.is_entry_blocked()
        assert w159.is_blocked()
    finally:
        w159.reset()


def test_wave159_clustered_persistent_flow_triggers_block():
    w159.reset()
    try:
        # Clustered runs of buys and sells: 6 buys, 6 sells, 6 buys
        signs = [1]*6 + [-1]*6 + [1]*6
        for s in signs:
            w159.record_trade_sign(s)

        corr = w159.get_sign_autocorrelation()
        assert corr >= 0.45
        assert w159.is_entry_blocked()
        assert w159.is_blocked()
    finally:
        w159.reset()


def test_wave159_invalid_and_neutral_signs_fail_closed():
    w159.reset()
    try:
        w159.record_trade_sign(1)
        # Neutral (0) or invalid should be ignored
        w159.record_trade_sign(0)
        w159.record_trade_sign("buy")
        w159.record_trade_sign(True)
        w159.record_trade_sign(float("nan"))
        w159.record_trade_sign(float("inf"))

        assert not w159.is_entry_blocked()
        assert w159.get_sign_autocorrelation() == 0.0
    finally:
        w159.reset()


def test_wave159_update_alias_and_reset():
    w159.reset()
    try:
        for _ in range(20):
            w159.update(-1)

        assert w159.is_entry_blocked()

        w159.reset()
        assert not w159.is_entry_blocked()
        assert not w159.is_blocked()
        assert w159.get_sign_autocorrelation() == 0.0
    finally:
        w159.reset()
