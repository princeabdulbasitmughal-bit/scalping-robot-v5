"""
tests/test_wave392.py
=====================
Pytest suite for Wave 392: Wave392LOBLiquidityProvisionRatioGuard.
"""

import sys
import os
import time
import threading
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave392_lob_liquidity_provision_ratio_guard import (
    Wave392LOBLiquidityProvisionRatioGuard,
)


def _make_guard(**kwargs):
    defaults = dict(
        window_size=10,
        high_lpr_threshold=0.80,
        low_lpr_threshold=0.20,
        cooldown_seconds=30.0,
    )
    defaults.update(kwargs)
    return Wave392LOBLiquidityProvisionRatioGuard(**defaults)


def test_no_block_before_window_full():
    g = _make_guard(window_size=10)
    ts = time.monotonic()
    for i in range(9):
        g.update(True, ts + i)
    assert not g.is_blocked()
    assert g.last_reason == ""


def test_balanced_ratio_no_block():
    g = _make_guard(window_size=10)
    ts = time.monotonic()
    # 5 passive, 5 aggressive -> LPR = 0.50 (in [0.20, 0.80])
    for i in range(10):
        g.update(i % 2 == 0, ts + i)
    assert not g.is_blocked()


def test_high_passive_ratio_blocks():
    g = _make_guard(window_size=10, high_lpr_threshold=0.80)
    ts = time.monotonic()
    # 9 passive, 1 aggressive -> LPR = 0.90 >= 0.80
    for i in range(9):
        g.update(True, ts + i)
    g.update(False, ts + 9)

    assert g.is_blocked()
    assert g.last_reason == "HIGH_PASSIVE_RATIO"


def test_low_passive_ratio_blocks():
    g = _make_guard(window_size=10, low_lpr_threshold=0.20)
    ts = time.monotonic()
    # 1 passive, 9 aggressive -> LPR = 0.10 <= 0.20
    g.update(True, ts)
    for i in range(1, 10):
        g.update(False, ts + i)

    assert g.is_blocked()
    assert g.last_reason == "LOW_PASSIVE_RATIO"


def test_invalid_passive_type_blocks():
    g = _make_guard()
    g.update("not-a-bool", time.monotonic())
    assert g.is_blocked()
    assert g.last_reason == "INPUT_VALIDATION_ERROR"


def test_invalid_timestamp_type_blocks():
    g = _make_guard()
    g.update(True, "not-a-timestamp")
    assert g.is_blocked()
    assert g.last_reason == "INPUT_VALIDATION_ERROR"


def test_bool_timestamp_blocks():
    g = _make_guard()
    g.update(True, True)
    assert g.is_blocked()
    assert g.last_reason == "INPUT_VALIDATION_ERROR"


def test_reset_clears_all_state():
    g = _make_guard(window_size=5, high_lpr_threshold=0.80)
    ts = time.monotonic()
    for i in range(5):
        g.update(True, ts + i)
    assert g.is_blocked()

    g.reset()
    assert not g.is_blocked()
    assert g.last_reason == ""
    assert len(g._executions) == 0


def test_cooldown_expiration():
    g = _make_guard(window_size=4, high_lpr_threshold=0.75, cooldown_seconds=0.05)
    ts = time.monotonic()
    for i in range(4):
        g.update(True, ts + i)
    assert g.is_blocked()

    time.sleep(0.06)
    assert not g.is_blocked()


def test_is_entry_blocked_delegation():
    g = _make_guard(window_size=5, high_lpr_threshold=0.80)
    ts = time.monotonic()
    for i in range(5):
        g.update(True, ts + i)
    assert g.is_entry_blocked(100.0, 100.1, ts + 10)


def test_invalid_constructor_params():
    with pytest.raises(ValueError):
        Wave392LOBLiquidityProvisionRatioGuard(window_size=3)  # < 4

    with pytest.raises(ValueError):
        Wave392LOBLiquidityProvisionRatioGuard(low_lpr_threshold=0.8, high_lpr_threshold=0.2)  # low > high


def test_thread_safety_concurrent_updates():
    g = _make_guard(window_size=50)
    ts = time.monotonic()

    def worker(val):
        for i in range(25):
            g.update(val, ts + i)

    t1 = threading.Thread(target=worker, args=(True,))
    t2 = threading.Thread(target=worker, args=(False,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(g._executions) == 50
