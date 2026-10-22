"""
test_batch207.py
----------------
Unit tests for Batch 207:
- wave180_cross_impact_spillover_guard.py (5 tests)
- wave181_trade_clustering_dispersion_guard.py (5 tests)
"""

import math
import time
import pytest

import wave180_cross_impact_spillover_guard as w180
import wave181_trade_clustering_dispersion_guard as w181


# ===========================================================================
# wave180_cross_impact_spillover_guard tests
# ===========================================================================

def test_wave180_normal_co_movement_no_block():
    w180.reset()
    try:
        # Gentle co-movement of target (100.0) and proxy (100.0) with returns ~ 0.0001 (1 bps)
        p_t = 100.0
        p_p = 100.0
        w180.record_prices(p_t, p_p)
        for _ in range(20):
            p_t += 0.01
            p_p += 0.01
            w180.record_prices(p_t, p_p)

        assert not w180.is_entry_blocked()
        assert w180.get_spillover_impact() < 0.0010
    finally:
        w180.reset()


def test_wave180_proxy_macro_shock_triggers_block():
    w180.reset()
    try:
        # Proxy drops suddenly by 25 bps (0.0025 >= 0.0015 threshold)
        w180.record_prices(100.0, 100.0)
        w180.record_prices(100.0, 99.75)

        assert w180.is_entry_blocked()
        assert w180.is_blocked()
        assert w180.get_spillover_impact() >= 0.0015
    finally:
        w180.reset()


def test_wave180_high_beta_amplification_triggers_block():
    w180.reset()
    try:
        # Establish a high beta relationship: target moves 2.0x proxy with varying step sizes
        p_t = 100.0
        p_p = 100.0
        w180.record_prices(p_t, p_p)
        for i in range(16):
            step_p = 0.01 if i % 2 == 0 else 0.03
            step_t = step_p * 2.0
            p_t += step_t
            p_p += step_p
            w180.record_prices(p_t, p_p)

        assert w180.get_beta() > 1.8

        # Proxy moves 12 bps -> spillover = 12 bps * 2.0 = 24 bps >= 20 bps
        p_p += 0.12
        p_t += 0.02
        w180.record_prices(p_t, p_p)

        assert w180.get_spillover_impact() >= 0.0020
        assert w180.is_entry_blocked()
    finally:
        w180.reset()


def test_wave180_invalid_inputs_fail_closed():
    w180.reset()
    try:
        w180.record_prices(100.0, 100.0)
        # Invalid inputs safely rejected
        w180.record_prices(True, 100.0)
        w180.record_prices(100.0, False)
        w180.record_prices("bad", 100.0)
        w180.record_prices(float("nan"), 100.0)
        w180.record_prices(100.0, float("inf"))
        w180.record_prices(-50.0, 100.0)
        w180.record_prices(100.0, 0.0)

        assert not w180.is_entry_blocked()
        assert w180.get_status()["sample_count"] == 0
    finally:
        w180.reset()


def test_wave180_aliases_get_status_and_reset():
    w180.reset()
    try:
        w180.update(100.0, 100.0)
        w180.update(100.0, 99.70)  # 30 bps drop

        assert w180.is_blocked()
        status = w180.get_status()
        assert status["is_blocked"] is True
        assert status["spillover_impact"] >= 0.0015

        w180.reset()
        assert not w180.is_blocked()
        assert w180.get_spillover_impact() == 0.0
        assert w180.get_beta() == 1.0
    finally:
        w180.reset()


# ===========================================================================
# wave181_trade_clustering_dispersion_guard tests
# ===========================================================================

def test_wave181_homogeneous_poisson_arrivals_no_block():
    w181.reset()
    try:
        # Uniform trade rate: exactly 2 trades per 1-second slice over 15 slices
        t = 1000.0
        for s in range(15):
            w181.record_trade(ts=t + s + 0.1)
            w181.record_trade(ts=t + s + 0.6)
        # Commit the 15th slice by stepping into slice 16
        w181.record_trade(ts=t + 16.0)

        assert not w181.is_entry_blocked()
        assert w181.get_fano_factor() < 1.0
    finally:
        w181.reset()


def test_wave181_clustered_burst_cascade_triggers_block():
    w181.reset()
    try:
        # Highly overdispersed burst arrivals:
        # e.g. 0, 0, 20, 0, 0, 25, 0, 0, 20...
        t = 1000.0
        for s in range(15):
            if s % 3 == 0:
                for _ in range(25):
                    w181.record_trade(ts=t + s + 0.1)
            else:
                # 0 trades in this slice (will be filled with 0)
                pass
        # Advance into slice 16 to flush all pending slices
        w181.record_trade(ts=t + 16.0)

        assert w181.is_entry_blocked()
        assert w181.is_blocked()
        assert w181.get_fano_factor() >= 4.0
    finally:
        w181.reset()


def test_wave181_insufficient_slices_no_block():
    w181.reset()
    try:
        # Only 5 slices completed (< MIN_SLICES 10)
        t = 1000.0
        for s in range(5):
            for _ in range(15):
                w181.record_trade(ts=t + s + 0.2)
        w181.record_trade(ts=t + 5.0)

        assert not w181.is_entry_blocked()
        assert w181.get_status()["completed_slices"] == 5
    finally:
        w181.reset()


def test_wave181_invalid_inputs_fail_closed():
    w181.reset()
    try:
        # Invalid timestamps safely rejected
        w181.record_trade(ts=True)
        w181.record_trade(ts=False)
        w181.record_trade(ts="bad")
        w181.record_trade(ts=float("nan"))
        w181.record_trade(ts=float("inf"))
        w181.record_trade(ts=-100.0)

        assert not w181.is_entry_blocked()
        assert w181.get_status()["completed_slices"] == 0
    finally:
        w181.reset()


def test_wave181_aliases_get_status_and_reset():
    w181.reset()
    try:
        t = 1000.0
        for s in range(15):
            if s % 3 == 0:
                for _ in range(25):
                    w181.update(ts=t + s + 0.1)
        w181.update(ts=t + 16.0)

        assert w181.is_blocked()
        status = w181.get_status()
        assert status["is_blocked"] is True
        assert status["completed_slices"] >= 10

        w181.reset()
        assert not w181.is_blocked()
        assert w181.get_fano_factor() == 1.0
        assert w181.get_status()["completed_slices"] == 0
    finally:
        w181.reset()
