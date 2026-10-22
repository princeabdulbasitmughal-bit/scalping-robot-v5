"""
test_batch199.py
----------------
Unit tests for Batch 199:
- wave164_yang_zhang_drift_independent_volatility_guard.py (5 tests)
- wave165_hasbrouck_temporary_price_impact_guard.py (5 tests)
"""

import math
import time
import pytest

import wave164_yang_zhang_drift_independent_volatility_guard as w164
import wave165_hasbrouck_temporary_price_impact_guard as w165


# ===========================================================================
# wave164_yang_zhang_drift_independent_volatility_guard tests
# ===========================================================================

def test_wave164_normal_calm_microbars_no_block():
    w164.reset()
    try:
        # Tight micro-bars with ~0.1% range and no gaps
        for i in range(12):
            w164.record_bar(open_p=100.0, high_p=100.08, low_p=99.95, close_p=100.02)

        assert not w164.is_entry_blocked()
        assert w164.get_yang_zhang_vol() < 0.0020
    finally:
        w164.reset()


def test_wave164_gap_and_intraday_volatility_burst_triggers_block():
    w164.reset()
    try:
        # Bars with substantial gaps and wide ranges ~2-3%
        bars = [
            (100.0, 102.0, 98.0, 101.5),
            (103.0, 105.0, 101.0, 104.5),
            (102.0, 104.5, 99.5, 101.0),
            (105.0, 108.0, 103.0, 107.0),
            (104.0, 107.0, 102.0, 105.0),
            (108.0, 111.0, 106.0, 110.0),
        ]
        for b in bars:
            w164.record_bar(open_p=b[0], high_p=b[1], low_p=b[2], close_p=b[3])

        assert w164.get_yang_zhang_vol() >= 0.0050
        assert w164.is_entry_blocked()
        assert w164.is_blocked()
    finally:
        w164.reset()


def test_wave164_insufficient_bars_no_block():
    w164.reset()
    try:
        # Less than 4 bars
        w164.record_bar(open_p=100.0, high_p=105.0, low_p=95.0, close_p=102.0)
        w164.record_bar(open_p=102.0, high_p=107.0, low_p=97.0, close_p=105.0)

        assert not w164.is_entry_blocked()
        assert w164.get_yang_zhang_vol() == 0.0
    finally:
        w164.reset()


def test_wave164_invalid_ohlc_bars_fail_closed():
    w164.reset()
    try:
        w164.record_bar(100.0, 100.1, 99.9, 100.0)
        # Invalid inputs safely rejected
        w164.record_bar(100.0, 99.0, 101.0, 100.0) # High < Low
        w164.record_bar(-10.0, 100.0, 90.0, 95.0)
        w164.record_bar("bad", 100.0, 90.0, 95.0)
        w164.record_bar(100.0, True, 90.0, 95.0)
        w164.record_bar(100.0, 105.0, float("nan"), 102.0)

        assert not w164.is_entry_blocked()
        assert w164.get_yang_zhang_vol() == 0.0
    finally:
        w164.reset()


def test_wave164_update_alias_and_reset():
    w164.reset()
    try:
        for i in range(6):
            w164.update(100.0 + i, 103.0 + i, 97.0 + i, 102.0 + i)

        assert w164.is_entry_blocked()

        w164.reset()
        assert not w164.is_entry_blocked()
        assert not w164.is_blocked()
        assert w164.get_yang_zhang_vol() == 0.0
    finally:
        w164.reset()


# ===========================================================================
# wave165_hasbrouck_temporary_price_impact_guard tests
# ===========================================================================

def test_wave165_pure_permanent_impact_no_block():
    w165.reset()
    try:
        # Trade at 100.05, initial mid 100.00. Subsequent mid 100.05 (pure permanent price discovery)
        # Temporary impact = |100.05 - 100.00| - |100.05 - 100.00| = 0.0
        w165.record_impact(trade_price=100.05, initial_mid=100.00, subsequent_mid=100.05)

        assert not w165.is_entry_blocked()
        assert w165.get_temporary_impact() == pytest.approx(0.0)
    finally:
        w165.reset()


def test_wave165_severe_temporary_impact_triggers_block():
    w165.reset()
    try:
        # Trade executed at 100.10, initial mid 100.00, subsequent mid snaps back to 100.00
        # Temporary concession = 0.10 >= 0.0020 (20 bps)
        w165.record_impact(trade_price=100.10, initial_mid=100.00, subsequent_mid=100.00)

        assert w165.get_temporary_impact() == pytest.approx(0.10)
        assert w165.is_entry_blocked()
        assert w165.is_blocked()
    finally:
        w165.reset()


def test_wave165_delayed_midpoint_resolution():
    w165.reset()
    try:
        # Register execution: trade at 100.05, initial mid 100.00
        w165.record_execution(trade_price=100.05, initial_mid=100.00)

        # 4 midpoint updates (still pending horizon of 5 ticks)
        for _ in range(4):
            w165.record_midpoint(mid_price=100.03)
        assert not w165.is_entry_blocked()
        assert w165.get_temporary_impact() == 0.0

        # 5th midpoint arrives at 100.00 (complete snapback concession of 0.05)
        w165.record_midpoint(mid_price=100.00)

        assert w165.get_temporary_impact() == pytest.approx(0.05)
        assert w165.is_entry_blocked()
        assert w165.is_blocked()
    finally:
        w165.reset()


def test_wave165_invalid_prices_fail_closed():
    w165.reset()
    try:
        w165.record_impact(100.01, 100.00, 100.01)
        # Invalid inputs safely rejected
        w165.record_impact(trade_price=-10.0, initial_mid=100.0, subsequent_mid=100.0)
        w165.record_impact(trade_price=100.0, initial_mid=0.0, subsequent_mid=100.0)
        w165.record_impact(trade_price="bad", initial_mid=100.0, subsequent_mid=100.0)
        w165.record_impact(trade_price=100.0, initial_mid=True, subsequent_mid=100.0)
        w165.record_impact(trade_price=float("nan"), initial_mid=100.0, subsequent_mid=100.0)

        assert not w165.is_entry_blocked()
        assert w165.get_temporary_impact() == 0.0
    finally:
        w165.reset()


def test_wave165_update_alias_and_reset():
    w165.reset()
    try:
        # Use update alias with direct resolution
        w165.update(trade_price=100.08, initial_mid=100.00, subsequent_mid=100.00)
        assert w165.is_entry_blocked()

        w165.reset()
        assert not w165.is_entry_blocked()
        assert not w165.is_blocked()
        assert w165.get_temporary_impact() == 0.0
    finally:
        w165.reset()
