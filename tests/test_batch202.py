"""
test_batch202.py
----------------
Unit tests for Batch 202:
- wave170_realized_semivariance_downside_drag_guard.py (5 tests)
- wave171_tick_run_length_streak_guard.py (5 tests)
"""

import math
import time
import pytest

import wave170_realized_semivariance_downside_drag_guard as w170
import wave171_tick_run_length_streak_guard as w171


# ===========================================================================
# wave170_realized_semivariance_downside_drag_guard tests
# ===========================================================================

def test_wave170_balanced_volatility_no_block():
    w170.reset()
    try:
        # Alternating balanced up and down ticks: 100.0 -> 100.1 -> 100.0 -> 100.1 ...
        p = 100.0
        w170.record_price(p)
        for i in range(25):
            p = 100.10 if i % 2 == 1 else 100.00
            w170.record_price(p)

        assert not w170.is_entry_blocked()
        ratio = w170.get_downside_ratio()
        assert 0.40 <= ratio <= 0.60
    finally:
        w170.reset()


def test_wave170_downside_drag_cascade_triggers_block():
    w170.reset()
    try:
        # Downside cascade: large drops and microscopic upward ticks
        # 16 returns: drops of ~0.50% and tiny gains of ~0.01%
        p = 100.0
        w170.record_price(p)
        for i in range(18):
            if i % 3 == 0:
                p += 0.01  # small bounce
            else:
                p -= 0.50  # heavy sell-off
            w170.record_price(p)

        assert w170.get_downside_ratio() >= 0.80
        assert w170.is_entry_blocked()
        assert w170.is_blocked()
    finally:
        w170.reset()


def test_wave170_upside_parabolic_squeeze_triggers_block():
    w170.reset()
    try:
        # Upside parabolic squeeze: large pumps of ~0.50% and tiny drops of ~0.01%
        p = 100.0
        w170.record_price(p)
        for i in range(18):
            if i % 3 == 0:
                p -= 0.01  # small pullback
            else:
                p += 0.50  # heavy pump
            w170.record_price(p)

        assert w170.get_downside_ratio() <= 0.20
        assert w170.is_entry_blocked()
        assert w170.is_blocked()
    finally:
        w170.reset()


def test_wave170_invalid_prices_fail_closed():
    w170.reset()
    try:
        w170.record_price(100.0)
        # Invalid inputs safely rejected
        w170.record_price(0.0)
        w170.record_price(-15.0)
        w170.record_price("bad_price")
        w170.record_price(True)
        w170.record_price(float("nan"))
        w170.record_price(float("inf"))

        assert not w170.is_entry_blocked()
        assert w170.get_downside_ratio() == 0.50
    finally:
        w170.reset()


def test_wave170_update_alias_and_reset():
    w170.reset()
    try:
        p = 100.0
        w170.update(p)
        for i in range(18):
            p -= 0.60
            w170.update(p)

        assert w170.is_entry_blocked()

        w170.reset()
        assert not w170.is_entry_blocked()
        assert not w170.is_blocked()
        assert w170.get_downside_ratio() == 0.50
    finally:
        w170.reset()


# ===========================================================================
# wave171_tick_run_length_streak_guard tests
# ===========================================================================

def test_wave171_normal_alternating_ticks_no_block():
    w171.reset()
    try:
        p = 100.0
        w171.record_price(p)
        for i in range(12):
            p = 100.1 if i % 2 == 1 else 100.0
            w171.record_price(p)

        assert not w171.is_entry_blocked()
        assert w171.get_streak_length() <= 1
    finally:
        w171.reset()


def test_wave171_monotonic_upward_sweep_triggers_block():
    w171.reset()
    try:
        p = 100.0
        w171.record_price(p)
        # 8 consecutive upward ticks without pullback
        for i in range(8):
            p += 0.05
            w171.record_price(p)

        assert w171.get_streak_length() == 8
        assert w171.get_streak_direction() == 1
        assert w171.is_entry_blocked()
        assert w171.is_blocked()
    finally:
        w171.reset()


def test_wave171_flat_ticks_preserve_streak():
    w171.reset()
    try:
        p = 100.0
        w171.record_price(p)
        # 4 downward ticks
        for _ in range(4):
            p -= 0.05
            w171.record_price(p)

        # 2 flat ticks (same price)
        w171.record_price(p)
        w171.record_price(p)

        # 4 more downward ticks (streak should reach 8)
        for _ in range(4):
            p -= 0.05
            w171.record_price(p)

        assert w171.get_streak_length() == 8
        assert w171.get_streak_direction() == -1
        assert w171.is_entry_blocked()
    finally:
        w171.reset()


def test_wave171_invalid_prices_fail_closed():
    w171.reset()
    try:
        w171.record_price(100.0)
        # Invalid inputs safely rejected
        w171.record_price(0.0)
        w171.record_price(-10.0)
        w171.record_price("bad")
        w171.record_price(True)
        w171.record_price(float("nan"))
        w171.record_price(float("inf"))

        assert not w171.is_entry_blocked()
        assert w171.get_streak_length() == 0
    finally:
        w171.reset()


def test_wave171_update_alias_and_reset():
    w171.reset()
    try:
        p = 100.0
        w171.update(p)
        for _ in range(8):
            p += 0.10
            w171.update(p)

        assert w171.is_entry_blocked()

        w171.reset()
        assert not w171.is_entry_blocked()
        assert not w171.is_blocked()
        assert w171.get_streak_length() == 0
        assert w171.get_streak_direction() == 0
    finally:
        w171.reset()
