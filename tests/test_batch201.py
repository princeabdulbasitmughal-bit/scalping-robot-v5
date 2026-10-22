"""
test_batch201.py
----------------
Unit tests for Batch 201:
- wave168_rogers_satchell_drift_robust_volatility_guard.py (5 tests)
- wave169_microstructure_quote_flicker_guard.py (5 tests)
"""

import math
import time
import pytest

import wave168_rogers_satchell_drift_robust_volatility_guard as w168
import wave169_microstructure_quote_flicker_guard as w169


# ===========================================================================
# wave168_rogers_satchell_drift_robust_volatility_guard tests
# ===========================================================================

def test_wave168_normal_calm_bars_no_block():
    w168.reset()
    try:
        # Tight micro-bars with ~0.1% range
        for _ in range(12):
            w168.record_bar(open_p=100.0, high_p=100.08, low_p=99.95, close_p=100.02)

        assert not w168.is_entry_blocked()
        assert w168.get_rogers_satchell_vol() < 0.0020
    finally:
        w168.reset()


def test_wave168_volatility_burst_triggers_block():
    w168.reset()
    try:
        # Micro-bars with large intraday excursion ~2-3%
        for _ in range(5):
            w168.record_bar(open_p=100.0, high_p=102.5, low_p=97.5, close_p=101.0)

        assert w168.get_rogers_satchell_vol() >= 0.0050
        assert w168.is_entry_blocked()
        assert w168.is_blocked()
    finally:
        w168.reset()


def test_wave168_insufficient_bars_no_block():
    w168.reset()
    try:
        # Less than 3 bars
        w168.record_bar(open_p=100.0, high_p=103.0, low_p=97.0, close_p=101.0)
        w168.record_bar(open_p=101.0, high_p=104.0, low_p=98.0, close_p=102.0)

        assert not w168.is_entry_blocked()
        assert w168.get_rogers_satchell_vol() == 0.0
    finally:
        w168.reset()


def test_wave168_invalid_ohlc_bars_fail_closed():
    w168.reset()
    try:
        w168.record_bar(100.0, 100.1, 99.9, 100.0)
        # Invalid inputs safely rejected
        w168.record_bar(100.0, 99.0, 101.0, 100.0) # High < Low
        w168.record_bar(-10.0, 100.0, 90.0, 95.0)
        w168.record_bar("bad", 100.0, 90.0, 95.0)
        w168.record_bar(100.0, True, 90.0, 95.0)
        w168.record_bar(100.0, 105.0, float("nan"), 102.0)

        assert not w168.is_entry_blocked()
        assert w168.get_rogers_satchell_vol() == 0.0
    finally:
        w168.reset()


def test_wave168_update_alias_and_reset():
    w168.reset()
    try:
        for _ in range(5):
            w168.update(open_p=100.0, high_p=103.0, low_p=97.0, close_p=101.5)

        assert w168.is_entry_blocked()

        w168.reset()
        assert not w168.is_entry_blocked()
        assert not w168.is_blocked()
        assert w168.get_rogers_satchell_vol() == 0.0
    finally:
        w168.reset()


# ===========================================================================
# wave169_microstructure_quote_flicker_guard tests
# ===========================================================================

def test_wave169_normal_slow_quote_updates_no_block():
    w169.reset()
    try:
        t0 = 1000.0
        # 1 quote change per second (rate = 1.0 < 25.0)
        for i in range(15):
            b = 100.00 + (0.01 if i % 2 == 1 else 0.00)
            a = b + 0.05
            w169.record_quote(bid_price=b, ask_price=a, ts=t0 + i * 1.0)

        assert not w169.is_entry_blocked()
        assert w169.get_flicker_rate() < 5.0
    finally:
        w169.reset()


def test_wave169_rapid_quote_flickering_triggers_block():
    w169.reset()
    try:
        t0 = 2000.0
        # 15 quote changes within 0.20s (rate ~ 70 updates/sec >= 25.0)
        w169.record_quote(bid_price=100.00, ask_price=100.05, ts=t0)
        for i in range(1, 15):
            b = 100.00 + (0.01 if i % 2 == 1 else 0.00)
            a = b + 0.05
            w169.record_quote(bid_price=b, ask_price=a, ts=t0 + i * 0.01)

        assert w169.get_flicker_rate() >= 25.0
        assert w169.is_entry_blocked()
        assert w169.is_blocked()
    finally:
        w169.reset()


def test_wave169_identical_quotes_no_flicker():
    w169.reset()
    try:
        t0 = 3000.0
        # 20 identical quotes arriving at high speed
        for i in range(20):
            w169.record_quote(bid_price=100.00, ask_price=100.05, ts=t0 + i * 0.001)

        assert not w169.is_entry_blocked()
        assert w169.get_flicker_rate() == 0.0
    finally:
        w169.reset()


def test_wave169_invalid_and_crossed_quotes_rejected():
    w169.reset()
    try:
        w169.record_quote(100.00, 100.05, ts=10.0)
        # Inverted quote (ask <= bid) or invalid values safely rejected
        w169.record_quote(bid_price=100.10, ask_price=100.05, ts=11.0)
        w169.record_quote(bid_price=-10.0, ask_price=100.05, ts=12.0)
        w169.record_quote(bid_price="bad", ask_price=100.05, ts=13.0)
        w169.record_quote(bid_price=100.00, ask_price=True, ts=14.0)
        w169.record_quote(bid_price=float("nan"), ask_price=100.05, ts=15.0)

        assert not w169.is_entry_blocked()
        assert w169.get_flicker_rate() == 0.0
    finally:
        w169.reset()


def test_wave169_update_alias_and_reset():
    w169.reset()
    try:
        t0 = 4000.0
        w169.update(100.00, 100.05, ts=t0)
        for i in range(1, 15):
            b = 100.00 + (0.01 if i % 2 == 1 else 0.00)
            a = b + 0.05
            w169.update(b, a, ts=t0 + i * 0.01)

        assert w169.is_entry_blocked()

        w169.reset()
        assert not w169.is_entry_blocked()
        assert not w169.is_blocked()
        assert w169.get_flicker_rate() == 0.0
    finally:
        w169.reset()
