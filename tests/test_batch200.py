"""
test_batch200.py
----------------
Unit tests for Batch 200 (Century Milestone):
- wave166_consecutive_slippage_deficit_guard.py (5 tests)
- wave167_order_flow_wick_reversal_guard.py (5 tests)
"""

import math
import time
import pytest

import wave166_consecutive_slippage_deficit_guard as w166
import wave167_order_flow_wick_reversal_guard as w167


# ===========================================================================
# wave166_consecutive_slippage_deficit_guard tests
# ===========================================================================

def test_wave166_normal_low_slippage_no_block():
    w166.reset()
    try:
        # Fills with minimal or zero slippage, alternating positive fills
        w166.record_slippage(0.0001, is_adverse=True)
        w166.record_slippage(0.0001, is_adverse=False)
        w166.record_slippage(0.0001, is_adverse=True)
        w166.record_slippage(0.0001, is_adverse=False)

        assert not w166.is_entry_blocked()
        assert w166.get_adverse_streak() == 0
    finally:
        w166.reset()


def test_wave166_adverse_streak_triggers_block():
    w166.reset()
    try:
        # 4 consecutive adverse slippage fills
        for _ in range(4):
            w166.record_slippage(0.0002, is_adverse=True)

        assert w166.get_adverse_streak() == 4
        assert w166.is_entry_blocked()
        assert w166.is_blocked()
    finally:
        w166.reset()


def test_wave166_cumulative_deficit_triggers_block():
    w166.reset()
    try:
        # 2 fills with massive cumulative slippage deficit (0.0040 >= 0.0030)
        w166.record_slippage(0.0020, is_adverse=True)
        w166.record_slippage(0.0020, is_adverse=True)

        assert w166.get_cumulative_slippage() == pytest.approx(0.0040)
        assert w166.is_entry_blocked()
        assert w166.is_blocked()
    finally:
        w166.reset()


def test_wave166_invalid_slippage_fail_closed():
    w166.reset()
    try:
        w166.record_slippage(0.0001, is_adverse=True)
        # Invalid inputs safely ignored
        w166.record_slippage("bad", is_adverse=True)
        w166.record_slippage(True, is_adverse=True)
        w166.record_slippage(float("nan"), is_adverse=True)
        w166.record_slippage(float("inf"), is_adverse=True)

        assert not w166.is_entry_blocked()
        assert w166.get_adverse_streak() == 1
    finally:
        w166.reset()


def test_wave166_update_alias_and_reset():
    w166.reset()
    try:
        for _ in range(4):
            w166.update(0.0005, is_adverse=True)

        assert w166.is_entry_blocked()

        w166.reset()
        assert not w166.is_entry_blocked()
        assert not w166.is_blocked()
        assert w166.get_adverse_streak() == 0
        assert w166.get_cumulative_slippage() == 0.0
    finally:
        w166.reset()


# ===========================================================================
# wave167_order_flow_wick_reversal_guard tests
# ===========================================================================

def test_wave167_normal_full_body_bar_no_block():
    w167.reset()
    try:
        # Full-body bullish bar with no wicks
        w167.record_bar(open_p=100.0, high_p=100.5, low_p=100.0, close_p=100.5)

        assert not w167.is_entry_blocked()
        assert w167.get_wick_ratio() == pytest.approx(0.0)
    finally:
        w167.reset()


def test_wave167_upper_wick_absorption_triggers_block():
    w167.reset()
    try:
        # Inverted pin bar / shooting star: range 1.0, upper wick 0.85 -> 85% wick rejection >= 65%
        w167.record_bar(open_p=100.0, high_p=101.0, low_p=100.0, close_p=100.15)

        assert w167.get_wick_ratio() == pytest.approx(0.85)
        assert w167.is_entry_blocked()
        assert w167.is_blocked()
    finally:
        w167.reset()


def test_wave167_lower_wick_hammer_triggers_block():
    w167.reset()
    try:
        # Hammer bar: range 1.0, lower wick 0.85 -> 85% wick rejection >= 65%
        w167.record_bar(open_p=100.85, high_p=101.0, low_p=100.0, close_p=101.0)

        assert w167.get_wick_ratio() == pytest.approx(0.85)
        assert w167.is_entry_blocked()
        assert w167.is_blocked()
    finally:
        w167.reset()


def test_wave167_micro_noise_range_ignored():
    w167.reset()
    try:
        # Range is below MIN_RANGE (0.0010)
        w167.record_bar(open_p=100.0000, high_p=100.0005, low_p=99.9998, close_p=100.0001)

        assert not w167.is_entry_blocked()
        assert w167.get_wick_ratio() == 0.0
    finally:
        w167.reset()


def test_wave167_update_alias_and_reset():
    w167.reset()
    try:
        w167.update(open_p=100.0, high_p=101.0, low_p=100.0, close_p=100.2)
        assert w167.is_entry_blocked()

        w167.reset()
        assert not w167.is_entry_blocked()
        assert not w167.is_blocked()
        assert w167.get_wick_ratio() == 0.0
    finally:
        w167.reset()
