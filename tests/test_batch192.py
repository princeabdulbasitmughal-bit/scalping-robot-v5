"""
test_batch192.py
----------------
Unit tests for Batch 192:
- wave150_drawdown_stagnation_guard.py (5 tests)
- wave151_effective_spread_adverse_selection_guard.py (5 tests)
"""

import math
import time
import pytest

import wave150_drawdown_stagnation_guard as w150
import wave151_effective_spread_adverse_selection_guard as w151


# ===========================================================================
# wave150_drawdown_stagnation_guard tests
# ===========================================================================

def test_wave150_normal_equity_peaks_no_block():
    w150.reset()
    try:
        w150.record_equity(10000.0, trades_count=0, ts=1000.0)
        assert not w150.is_entry_blocked()
        assert w150.get_underwater_duration() == 0.0

        w150.record_equity(10200.0, trades_count=1, ts=1100.0)
        assert not w150.is_entry_blocked()
        assert w150.get_underwater_duration() == 0.0

        w150.record_equity(10500.0, trades_count=2, ts=1200.0)
        assert not w150.is_blocked()
        assert w150.get_underwater_duration() == 0.0
    finally:
        w150.reset()


def test_wave150_stagnation_and_churn_triggers_block():
    w150.reset()
    try:
        t0 = 1000.0
        w150.record_equity(10000.0, trades_count=0, ts=t0)
        assert not w150.is_entry_blocked()

        # Equity drops to 9500 at t0 + 10s (underwater starts)
        t_underwater = t0 + 10.0
        w150.record_equity(9500.0, trades_count=2, ts=t_underwater)
        assert not w150.is_entry_blocked()
        assert w150.get_underwater_duration() == 0.0

        # Underwater churn over 1850 seconds (> 1800s threshold) with 16 trades (> 15)
        t_churn = t_underwater + 1850.0
        w150.record_equity(9450.0, trades_count=14, ts=t_churn)

        assert w150.get_underwater_duration() == pytest.approx(1850.0)
        assert w150.is_entry_blocked()
        assert w150.is_blocked()
    finally:
        w150.reset()


def test_wave150_recovery_resets_underwater_state():
    w150.reset()
    try:
        t0 = 2000.0
        w150.record_equity(5000.0, trades_count=0, ts=t0)
        # Underwater entry at t0 + 10s
        w150.record_equity(4800.0, trades_count=1, ts=t0 + 10.0)
        # 500s later underwater
        w150.record_equity(4800.0, trades_count=2, ts=t0 + 510.0)
        assert w150.get_underwater_duration() == pytest.approx(500.0)

        # Equity recovers above HWM
        w150.record_equity(5200.0, trades_count=1, ts=t0 + 600.0)
        assert w150.get_underwater_duration() == 0.0
        assert not w150.is_entry_blocked()
    finally:
        w150.reset()


def test_wave150_invalid_inputs_fail_closed():
    w150.reset()
    try:
        w150.record_equity(10000.0, trades_count=0, ts=100.0)
        # Invalid inputs should be silently discarded without throwing or altering state
        w150.record_equity("invalid_string")
        w150.record_equity(True)
        w150.record_equity(float("nan"))
        w150.record_equity(float("inf"))
        w150.record_equity(None)
        assert not w150.is_entry_blocked()
        assert w150.get_underwater_duration() == 0.0
    finally:
        w150.reset()


def test_wave150_reset_clears_all():
    w150.reset()
    try:
        w150.update(1000.0, ts=10.0)
        w150.update(900.0, trades_count=5, ts=100.0)
        w150.update(900.0, trades_count=15, ts=2000.0) # 1900s underwater, 20 trades >= 15
        assert w150.is_entry_blocked()

        w150.reset()
        assert not w150.is_entry_blocked()
        assert not w150.is_blocked()
        assert w150.get_underwater_duration() == 0.0
    finally:
        w150.reset()


# ===========================================================================
# wave151_effective_spread_adverse_selection_guard tests
# ===========================================================================

def test_wave151_normal_execution_at_touch_no_block():
    w151.reset()
    try:
        # Bid 100.0, Ask 100.2 (mid = 100.1, quoted spread = 0.2)
        # Trade at touch (100.2): effective spread = 2 * |100.2 - 100.1| = 0.2 -> ratio = 1.0
        w151.record_execution(trade_price=100.2, bid=100.0, ask=100.2)
        assert not w151.is_entry_blocked()
        assert w151.get_effective_spread_ratio() == pytest.approx(1.0)
    finally:
        w151.reset()


def test_wave151_price_improvement_ratio():
    w151.reset()
    try:
        # Trade inside spread at midpoint 100.1: effective spread = 0.0 -> ratio = 0.0
        w151.record_execution(trade_price=100.1, bid=100.0, ask=100.2)
        assert not w151.is_entry_blocked()
        assert w151.get_effective_spread_ratio() == pytest.approx(0.0)
    finally:
        w151.reset()


def test_wave151_adverse_selection_surge_triggers_block():
    w151.reset()
    try:
        # Quoted: bid 100.0, ask 100.2 (spread = 0.2, mid = 100.1)
        # Severe slippage: trade executed at 100.35 (diff from mid = 0.25 -> effective spread = 0.50 -> ratio = 2.5 >= 2.0)
        w151.record_execution(trade_price=100.35, bid=100.0, ask=100.2)
        assert w151.get_effective_spread_ratio() == pytest.approx(2.5)
        assert w151.is_entry_blocked()
        assert w151.is_blocked()
    finally:
        w151.reset()


def test_wave151_invalid_and_crossed_quotes_rejected():
    w151.reset()
    try:
        # Inverted / crossed quotes should be rejected
        w151.record_execution(trade_price=100.0, bid=100.5, ask=100.2)
        assert not w151.is_entry_blocked()
        assert w151.get_effective_spread_ratio() == 1.0

        # Non-numeric / NaN / boolean
        w151.record_execution(trade_price="100.0", bid=100.0, ask=100.2)
        w151.record_execution(trade_price=100.0, bid=True, ask=100.2)
        w151.record_execution(trade_price=float("nan"), bid=100.0, ask=100.2)
        w151.record_execution(trade_price=100.0, bid=100.0, ask=float("inf"))
        assert not w151.is_entry_blocked()
    finally:
        w151.reset()


def test_wave151_update_alias_and_reset():
    w151.reset()
    try:
        # Use update alias with an adverse fill
        w151.update(trade_price=100.4, bid=100.0, ask=100.2)
        assert w151.is_entry_blocked()

        w151.reset()
        assert not w151.is_entry_blocked()
        assert not w151.is_blocked()
        assert w151.get_effective_spread_ratio() == 1.0
    finally:
        w151.reset()
