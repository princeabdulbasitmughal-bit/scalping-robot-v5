"""
test_batch195.py
----------------
Unit tests for Batch 195:
- wave156_amihud_illiquidity_ratio_guard.py (5 tests)
- wave157_relative_volatility_index_guard.py (5 tests)
"""

import math
import time
import pytest

import wave156_amihud_illiquidity_ratio_guard as w156
import wave157_relative_volatility_index_guard as w157


# ===========================================================================
# wave156_amihud_illiquidity_ratio_guard tests
# ===========================================================================

def test_wave156_normal_liquid_trades_no_block():
    w156.reset()
    try:
        # Liquid conditions: 10 lots traded for a modest 0.05% move -> illiq = 0.00005 < 0.0030
        for _ in range(20):
            w156.record_trade(price_return=0.0005, volume=10.0)

        assert not w156.is_entry_blocked()
        assert w156.get_amihud_illiq() == pytest.approx(0.00005)
    finally:
        w156.reset()


def test_wave156_illiquidity_spike_triggers_block():
    w156.reset()
    try:
        # Severe illiquidity: a tiny trade of 0.5 lots moves price by 0.50% -> illiq = 0.0050 / 0.5 = 0.0100 >= 0.0030
        w156.record_trade(price_return=0.0050, volume=0.5)

        assert w156.get_amihud_illiq() == pytest.approx(0.0100)
        assert w156.is_entry_blocked()
        assert w156.is_blocked()
    finally:
        w156.reset()


def test_wave156_invalid_inputs_fail_closed():
    w156.reset()
    try:
        w156.record_trade(price_return=0.0001, volume=5.0)
        # Invalid inputs should be safely discarded
        w156.record_trade(price_return=0.001, volume=0.0)
        w156.record_trade(price_return=0.001, volume=-2.0)
        w156.record_trade(price_return="bad", volume=5.0)
        w156.record_trade(price_return=0.001, volume=True)
        w156.record_trade(price_return=float("nan"), volume=5.0)
        w156.record_trade(price_return=0.001, volume=float("inf"))

        assert not w156.is_entry_blocked()
        assert w156.get_amihud_illiq() == pytest.approx(0.00002)
    finally:
        w156.reset()


def test_wave156_rolling_average_trigger():
    w156.reset()
    try:
        # 15 trades with illiq = 0.0035 (above 0.0030 threshold)
        for _ in range(15):
            w156.record_trade(price_return=0.0035, volume=1.0)

        assert w156.is_entry_blocked()
        assert w156.is_blocked()
        assert w156.get_amihud_illiq() == pytest.approx(0.0035)
    finally:
        w156.reset()


def test_wave156_update_alias_and_reset():
    w156.reset()
    try:
        w156.update(price_return=0.0060, volume=1.0)
        assert w156.is_entry_blocked()

        w156.reset()
        assert not w156.is_entry_blocked()
        assert not w156.is_blocked()
        assert w156.get_amihud_illiq() == 0.0
    finally:
        w156.reset()


# ===========================================================================
# wave157_relative_volatility_index_guard tests
# ===========================================================================

def test_wave157_balanced_market_normal_rvi_no_block():
    w157.reset()
    try:
        # Alternating ticks: up, down, up, down around 100.0 with equal dispersion
        base = 100.0
        for i in range(30):
            p = base + (0.10 if i % 2 == 1 else -0.10)
            w157.record_price(p)

        rvi = w157.get_rvi()
        # Balanced market should keep RVI within safe boundaries [35, 65]
        assert 35.0 <= rvi <= 65.0
        assert not w157.is_entry_blocked()
    finally:
        w157.reset()


def test_wave157_extreme_upward_volatility_triggers_block():
    w157.reset()
    try:
        # 30 consecutive upward expanding price ticks (pure upward volatility)
        prices = [100.0 + (i * 0.20) for i in range(30)]
        for p in prices:
            w157.record_price(p)

        rvi = w157.get_rvi()
        assert rvi >= 85.0
        assert w157.is_entry_blocked()
        assert w157.is_blocked()
    finally:
        w157.reset()


def test_wave157_extreme_downward_volatility_triggers_block():
    w157.reset()
    try:
        # 30 consecutive downward plunging price ticks (pure downward volatility)
        prices = [200.0 - (i * 0.20) for i in range(30)]
        for p in prices:
            w157.record_price(p)

        rvi = w157.get_rvi()
        assert rvi <= 15.0
        assert w157.is_entry_blocked()
        assert w157.is_blocked()
    finally:
        w157.reset()


def test_wave157_invalid_prices_fail_closed():
    w157.reset()
    try:
        w157.record_price(100.0)
        # Invalid inputs safely rejected
        w157.record_price("bad_price")
        w157.record_price(True)
        w157.record_price(0.0)
        w157.record_price(-10.0)
        w157.record_price(float("nan"))
        w157.record_price(float("inf"))

        assert not w157.is_entry_blocked()
        assert w157.get_rvi() == 50.0
    finally:
        w157.reset()


def test_wave157_update_alias_and_reset():
    w157.reset()
    try:
        prices = [100.0 + (i * 0.30) for i in range(30)]
        for p in prices:
            w157.update(p)

        assert w157.is_entry_blocked()

        w157.reset()
        assert not w157.is_entry_blocked()
        assert not w157.is_blocked()
        assert w157.get_rvi() == 50.0
    finally:
        w157.reset()
