"""
Test Suite for Batch 143:
- wave52_rsi_ob_os_filter.py (RSIOverboughtOversold: RSI > 75 BUY block, RSI < 25 SELL block)
- wave53_tick_reversal_guard.py (TickReversalGuard: 5 consecutive adverse ticks momentum block)
Zero regressions, continuing toward 1,677+ passed tests.
"""

import math
import pytest

from wave52_rsi_ob_os_filter import (
    RSIOverboughtOversold,
    rsi_filter,
    is_entry_blocked as w52_is_entry_blocked,
    is_blocked as w52_is_blocked,
    update as w52_update,
    get_rsi as w52_get_rsi,
    reset as w52_reset,
)
from wave53_tick_reversal_guard import (
    TickReversalGuard,
    tick_reversal_guard,
    is_entry_blocked as w53_is_entry_blocked,
    is_blocked as w53_is_blocked,
    update as w53_update,
    reset as w53_reset,
)


# ---------------------------------------------------------------------
# Wave 52: RSI Overbought/Oversold Filter Tests
# ---------------------------------------------------------------------

def test_wave52_initial_state():
    rf = RSIOverboughtOversold()
    assert rf.get_rsi() == 50.0
    assert rf.rsi == 50.0
    assert not rf.is_signal_blocked("BUY")
    assert not rf.is_signal_blocked("SELL")
    assert not rf.is_entry_blocked("BUY")
    assert not rf.is_blocked("SELL")
    info = rf.info()
    assert info["rsi"] == 50.0
    assert info["ob_block_threshold"] == 75.0
    assert info["os_block_threshold"] == 25.0
    assert not info["initialized"]


def test_wave52_invalid_inputs():
    rf = RSIOverboughtOversold()
    for bad in [None, True, False, -100.0, 0.0, float("nan"), float("inf"), "abc"]:
        rf.update(bad)

    assert len(rf._prices) == 0
    assert rf.get_rsi() == 50.0


def test_wave52_overbought_blocks_buy():
    rf = RSIOverboughtOversold(period=14, ob_block=75.0)
    price = 2000.0
    # Feed 20 ticks with pure rising prices (+1.0 per tick)
    for _ in range(20):
        rf.update(price)
        price += 1.0

    assert rf.get_rsi() > 75.0
    # Overbought blocks BUY, allows SELL
    assert rf.is_signal_blocked("BUY")
    assert not rf.is_signal_blocked("SELL")
    info = rf.info()
    assert info["status"] == "OVERBOUGHT"


def test_wave52_oversold_blocks_sell():
    rf = RSIOverboughtOversold(period=14, os_block=25.0)
    price = 2050.0
    # Feed 20 ticks with pure falling prices (-1.0 per tick)
    for _ in range(20):
        rf.update(price)
        price -= 1.0

    assert rf.get_rsi() < 25.0
    # Oversold blocks SELL, allows BUY
    assert rf.is_signal_blocked("SELL")
    assert not rf.is_signal_blocked("BUY")
    info = rf.info()
    assert info["status"] == "OVERSOLD"


def test_wave52_reset_and_module_aliases():
    rf = RSIOverboughtOversold(period=14)
    price = 2000.0
    for _ in range(20):
        rf.update(price)
        price += 1.0
    assert rf.get_rsi() > 75.0

    rf.reset()
    assert rf.get_rsi() == 50.0
    assert not rf.is_signal_blocked("BUY")

    # Module-level aliases
    w52_reset()
    assert w52_get_rsi() == 50.0
    assert not w52_is_entry_blocked("BUY")
    assert not w52_is_blocked("SELL")
    w52_update(2000.0)
    w52_reset()


# ---------------------------------------------------------------------
# Wave 53: Tick Reversal Guard Tests
# ---------------------------------------------------------------------

def test_wave53_initial_state():
    trg = TickReversalGuard()
    assert not trg.is_signal_blocked("BUY")
    assert not trg.is_signal_blocked("SELL")
    assert not trg.is_entry_blocked("BUY")
    assert not trg.is_blocked("SELL")
    allowed, reason = trg.is_trading_allowed("BUY")
    assert allowed
    assert reason == ""
    info = trg.info()
    assert info["n_ticks_threshold"] == 5
    assert info["block_duration_sec"] == 30.0
    assert not info["is_blocked"]
    assert info["block_count"] == 0


def test_wave53_invalid_inputs():
    trg = TickReversalGuard()
    for bad in [None, True, False, -100.0, 0.0, float("nan"), float("inf"), "abc"]:
        trg.update(bad)

    assert len(trg._prices) == 0
    assert not trg.is_signal_blocked("BUY")


def test_wave53_falling_ticks_block_buy():
    trg = TickReversalGuard(n_ticks=5, block_duration=30.0)
    t0 = 1000.0
    # 6 prices -> 5 consecutive negative deltas (falling prices)
    prices = [2005.0, 2004.0, 2003.0, 2002.0, 2001.0, 2000.0]
    for p in prices:
        trg.update(p)

    # Falling market blocks BUY, allows SELL
    assert trg.is_signal_blocked("BUY", now_ts=t0)
    assert not trg.is_signal_blocked("SELL", now_ts=t0)
    allowed, reason = trg.is_trading_allowed("BUY", now_ts=t0)
    assert not allowed
    assert "TICK_REVERSAL" in reason
    info = trg.info(now_ts=t0)
    assert info["is_blocked"]
    assert info["last_reversal_direction"] == "DOWN"
    assert info["block_count"] == 1


def test_wave53_rising_ticks_block_sell():
    trg = TickReversalGuard(n_ticks=5, block_duration=30.0)
    t0 = 1000.0
    # 6 prices -> 5 consecutive positive deltas (rising prices)
    prices = [2000.0, 2001.0, 2002.0, 2003.0, 2004.0, 2005.0]
    for p in prices:
        trg.update(p)

    # Rising market blocks SELL, allows BUY
    assert trg.is_signal_blocked("SELL", now_ts=t0)
    assert not trg.is_signal_blocked("BUY", now_ts=t0)
    allowed, reason = trg.is_trading_allowed("SELL", now_ts=t0)
    assert not allowed
    assert "TICK_REVERSAL" in reason
    info = trg.info(now_ts=t0)
    assert info["is_blocked"]
    assert info["last_reversal_direction"] == "UP"
    assert info["block_count"] == 1


def test_wave53_cooldown_expiry_and_module_aliases():
    trg = TickReversalGuard(n_ticks=5, block_duration=30.0)
    t0 = 1000.0
    prices = [2005.0, 2004.0, 2003.0, 2002.0, 2001.0, 2000.0]
    for p in prices:
        trg.update(p)

    assert trg.is_signal_blocked("BUY", now_ts=t0)

    # 31s later, cooldown has expired
    t_after = t0 + 31.0
    assert not trg.is_signal_blocked("BUY", now_ts=t_after)
    assert trg.info(now_ts=t_after)["cooldown_remaining_sec"] == 0.0

    trg.reset()
    assert len(trg._prices) == 0
    assert trg.info()["block_count"] == 0

    # Module-level aliases
    w53_reset()
    assert not w53_is_entry_blocked("BUY")
    assert not w53_is_blocked("SELL")
    w53_update(2000.0)
    w53_reset()
