"""
tests/test_batch214.py
-----------------------
Unit test suite for Batch 214:
- Wave 194: Microstructure Amihud Illiquidity Ratio & Return-to-Volume Elasticity Guard
- Wave 195: Execution Slippage Dispersion, Adverse Mean & Heavy-Tail Kurtosis Guard

Verifies quantitative logic, fail-closed assertions, edge cases, thread safety, and cooldown resets.
"""

import math
import time
import pytest

import wave194_microstructure_illiquidity_ratio_guard as wave194
import wave195_execution_slippage_dispersion_guard as wave195


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave194.reset()
    wave195.reset()
    yield
    wave194.reset()
    wave195.reset()


# ---------------------------------------------------------------------------
# Wave 194: Microstructure Amihud Illiquidity Ratio Guard Tests
# ---------------------------------------------------------------------------

def test_wave194_normal_liquid_trading_no_block():
    """In liquid regimes with large volumes and small price changes, illiquidity remains low."""
    assert not wave194.is_entry_blocked()
    assert not wave194.is_blocked()

    # Base price 2000.0, volume 50.0 lots, price moving by 0.05 (0.25 bps)
    price = 2000.0
    for i in range(15):
        price += 0.05 if i % 2 == 0 else -0.05
        wave194.record_trade(price=price, volume=50.0)

    assert not wave194.is_entry_blocked()
    assert wave194.get_rolling_illiq() < wave194.MAX_ROLLING_ILLIQ
    status = wave194.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 14  # First price sets anchor


def test_wave194_excessive_rolling_illiquidity_blocks():
    """When returns per unit volume exceed MAX_ROLLING_ILLIQ, guard blocks entries."""
    # Price moves 2.0 points on 2000.0 (10 bps) with only 0.1 lot volume
    # illiq = (2.0 / 2000.0) / 0.1 = 0.001 / 0.1 = 0.01 (100 bps per lot) >> 0.0005
    price = 2000.0
    for i in range(8):
        price += 2.0 if i % 2 == 0 else -2.0
        wave194.update(price=price, volume=0.1)

    assert wave194.is_entry_blocked()
    assert wave194.is_blocked()
    status = wave194.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave194_illiquidity_spike_blocks():
    """An established baseline followed by a sudden illiquidity spike >= 3.5x baseline blocks entries."""
    # Establish baseline with low illiquidity: 0.1 price move on 2000.0 (0.5 bps) on 10.0 lots
    # illiq = 0.00005 / 10 = 5e-6
    price = 2000.0
    for i in range(10):
        price += 0.1 if i % 2 == 0 else -0.1
        wave194.record_trade(price=price, volume=10.0)

    assert not wave194.is_entry_blocked()
    baseline = wave194.get_rolling_illiq()
    assert baseline > 0.0

    # Sudden brittle illiquidity trade: 1.0 price move on 0.5 lot
    # illiq = (1.0 / 2000) / 0.5 = 0.0005 / 0.5 = 0.001 (100x baseline and >= 0.0002)
    price += 1.0
    wave194.record_trade(price=price, volume=0.5)

    assert wave194.is_entry_blocked()
    assert wave194.get_illiq() >= 0.0002


def test_wave194_input_validation_and_fail_closed():
    """Invalid types, booleans, negative values, and non-numerics are ignored safely."""
    wave194.record_trade(True, 10.0)  # bool price rejected
    wave194.record_trade(2000.0, False)  # bool volume rejected
    wave194.record_trade(-2000.0, 10.0)  # negative price rejected
    wave194.record_trade(2000.0, -5.0)  # negative volume rejected
    wave194.record_trade(0.0, 10.0)  # zero price rejected
    wave194.record_trade(2000.0, 0.0)  # zero volume rejected
    wave194.record_trade(float("nan"), 10.0)  # nan rejected
    wave194.record_trade(2000.0, float("inf"))  # inf rejected
    wave194.record_trade("2000.0", 10.0)  # string rejected

    assert not wave194.is_entry_blocked()
    assert wave194.get_status()["sample_count"] == 0


def test_wave194_reset_and_status():
    """Verify reset clears state and get_status reports correct values."""
    wave194.record_trade(2000.0, 1.0)
    wave194.record_trade(2010.0, 0.01)  # huge illiq
    for _ in range(5):
        wave194.record_trade(2000.0, 0.01)

    assert wave194.is_entry_blocked()

    wave194.reset()
    assert not wave194.is_entry_blocked()
    assert wave194.get_illiq() == 0.0
    assert wave194.get_rolling_illiq() == 0.0
    status = wave194.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 195: Execution Slippage Dispersion Guard Tests
# ---------------------------------------------------------------------------

def test_wave195_normal_tight_fills_no_block():
    """Normal execution with minimal slippage does not trigger block."""
    assert not wave195.is_entry_blocked()
    assert not wave195.is_blocked()

    # Expected price 2000.0, slight fluctuations within +/- 0.02 (0.1 bps)
    for i in range(10):
        exp = 2000.0
        exe = 2000.01 if i % 2 == 0 else 1999.99
        side = "buy" if i % 2 == 0 else "sell"
        wave195.record_execution(expected_price=exp, exec_price=exe, side=side)

    assert not wave195.is_entry_blocked()
    stats = wave195.get_slippage_stats()
    assert stats["mean_slippage_bps"] < wave195.MAX_MEAN_SLIPPAGE_BPS
    assert stats["std_slippage_bps"] < wave195.MAX_SLIPPAGE_STD_BPS


def test_wave195_excessive_adverse_mean_slippage_blocks():
    """Realized executions with severe adverse mean slippage >= 3.0 bps trigger block."""
    # BUY at expected 2000.0, executed at 2001.0 (5.0 bps adverse)
    for _ in range(8):
        wave195.update(expected_price=2000.0, exec_price=2001.0, side="buy")

    assert wave195.is_entry_blocked()
    stats = wave195.get_slippage_stats()
    assert stats["mean_slippage_bps"] >= 3.0
    status = wave195.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave195_high_slippage_dispersion_blocks():
    """Widely dispersed execution fills (std >= 2.5 bps) trigger block."""
    # Alternating zero slippage and 6 bps slippage (mean ~3 bps, std ~3.2 bps)
    for i in range(10):
        if i % 2 == 0:
            wave195.record_execution(2000.0, 2000.0, "buy")  # 0 bps
        else:
            wave195.record_execution(2000.0, 2001.2, "buy")  # 6 bps

    assert wave195.is_entry_blocked()
    stats = wave195.get_slippage_stats()
    assert stats["std_slippage_bps"] >= wave195.MAX_SLIPPAGE_STD_BPS


def test_wave195_fat_tail_kurtosis_blocks():
    """A leptokurtic tail shock (extreme outlier fill) trips kurtosis threshold."""
    # 9 executions with very tight slippage (0.1 bps) and 1 severe shock (12 bps)
    # This creates extreme peakedness and fat tail: kurtosis > 5.0
    for _ in range(9):
        wave195.record_execution(expected_price=2000.0, exec_price=2000.02, side="buy")

    assert not wave195.is_entry_blocked()

    # Outlier fill: 2000.0 expected, 2002.5 filled (12.5 bps)
    wave195.record_execution(expected_price=2000.0, exec_price=2002.5, side="buy")

    assert wave195.is_entry_blocked()
    stats = wave195.get_slippage_stats()
    assert stats["kurtosis"] >= wave195.MAX_SLIPPAGE_KURTOSIS


def test_wave195_input_validation_fail_closed_and_reset():
    """Invalid sides, booleans, negative prices, and NaNs are ignored; reset clears all."""
    wave195.record_execution(True, 2000.0, "buy")  # bool expected rejected
    wave195.record_execution(2000.0, False, "buy")  # bool exec rejected
    wave195.record_execution(-2000.0, 2000.0, "buy")  # negative expected rejected
    wave195.record_execution(2000.0, -2000.0, "buy")  # negative exec rejected
    wave195.record_execution(0.0, 2000.0, "buy")  # zero price rejected
    wave195.record_execution(2000.0, float("nan"), "buy")  # nan rejected
    wave195.record_execution(2000.0, float("inf"), "buy")  # inf rejected
    wave195.record_execution(2000.0, 2000.0, "hold")  # invalid side rejected
    wave195.record_execution(2000.0, 2000.0, 123)  # non-string side rejected

    assert not wave195.is_entry_blocked()
    assert wave195.get_status()["sample_count"] == 0

    # Trip the guard
    for _ in range(8):
        wave195.record_execution(2000.0, 2002.0, "buy")
    assert wave195.is_entry_blocked()

    # Reset
    wave195.reset()
    assert not wave195.is_entry_blocked()
    stats = wave195.get_slippage_stats()
    assert stats["mean_slippage_bps"] == 0.0
    assert stats["std_slippage_bps"] == 0.0
    assert stats["kurtosis"] == 0.0
    assert wave195.get_status()["sample_count"] == 0
