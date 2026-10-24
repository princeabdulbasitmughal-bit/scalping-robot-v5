"""Unit tests for Batch 283: Wave 332 and Wave 333 Risk & Microstructure Guards."""

import math
import time
import pytest

from wave332_lob_spread_cross_sectional_dispersion_guard import Wave332LOBSpreadCrossSectionalDispersionGuard
from wave333_trade_flow_signed_volume_imbalance_drift_guard import Wave333TradeFlowSignedVolumeImbalanceDriftGuard


# ==========================================
# Wave 332 Tests: Cross-Venue Spread Dispersion
# ==========================================

def test_wave332_tight_cross_sectional_dispersion_no_block():
    """Verify tight aligned spreads across 3 venues do not trigger dispersion blocks."""
    guard = Wave332LOBSpreadCrossSectionalDispersionGuard(
        window_size=10,
        dispersion_threshold_bps=1.80,
        cooldown_seconds=30.0,
    )
    t0 = 1000.0
    for i in range(12):
        # 3 venues tightly aligned around 1.0 to 1.2 bps spread
        # mid = 1.1000 -> 1.0 bps = 0.00011
        quotes = [
            (1.1000, 1.10011),   # Venue 1: spread 1.0 bps
            (1.09999, 1.10011),  # Venue 2: spread 1.09 bps
            (1.1000, 1.10012),   # Venue 3: spread 1.09 bps
        ]
        blocked = guard.update(quotes, current_time=t0 + i)
        assert not blocked
        assert not guard.is_entry_blocked(t0 + i)

    status = guard.get_status(t0 + 12)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["last_dispersion_bps"] <= 0.50


def test_wave332_cross_venue_spread_decoupling_blocks():
    """Verify persistent spread divergence across fragmented venues triggers decoupling block."""
    guard = Wave332LOBSpreadCrossSectionalDispersionGuard(
        window_size=10,
        dispersion_threshold_bps=1.80,
        primary_spread_threshold_bps=2.20,
        venue_drift_threshold_bps=10.0,  # avoid outlier drift to test rolling dispersion
        cooldown_seconds=45.0,
    )
    t0 = 2000.0
    # Primary spread = 2.5 bps (0.000275), secondary = 6.5 bps (0.000715)
    # Dispersion ~= (6.5 - 2.5)/2 = 2.0 bps >= 1.80 bps
    quotes = [
        (1.1000, 1.100275),  # Venue 1: spread 2.5 bps
        (1.1000, 1.100715),  # Venue 2: spread 6.5 bps
    ]
    for i in range(12):
        blocked = guard.update(quotes, current_time=t0 + i)
        if i < 9:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 12)
    status = guard.get_status(t0 + 12)
    assert "CROSS_VENUE_SPREAD_DECOUPLING" in status["last_block_reason"]
    assert status["rolling_mean_dispersion_bps"] >= 1.80


def test_wave332_acute_quote_crossing_blocks():
    """Verify cross-venue quote crossing (bid_A >= ask_B) triggers locked market block."""
    guard = Wave332LOBSpreadCrossSectionalDispersionGuard(cooldown_seconds=45.0)
    t0 = 3000.0
    # Venue 1: Bid 1.1002, Ask 1.1004
    # Venue 2: Bid 1.0998, Ask 1.1001
    # Venue 1 Bid (1.1002) > Venue 2 Ask (1.1001) -> Arbitrage inversion!
    quotes = [
        (1.1002, 1.1004),
        (1.0998, 1.1001),
    ]
    blocked = guard.update(quotes, current_time=t0)
    assert blocked

    status = guard.get_status(t0)
    assert status["is_blocked"]
    assert "CROSS_VENUE_QUOTE_CROSSING" in status["last_block_reason"]


def test_wave332_outlier_venue_drift_blocks():
    """Verify single venue spread deviating >=4.0 bps from median triggers outlier block."""
    guard = Wave332LOBSpreadCrossSectionalDispersionGuard(
        venue_drift_threshold_bps=4.0,
        cooldown_seconds=45.0,
    )
    t0 = 4000.0
    # 3 venues: Venue 1 spread 1.0 bps, Venue 2 spread 1.2 bps (median ~= 1.1 bps)
    # Venue 3: spread 6.0 bps (drift = 6.0 - 1.1 = 4.9 bps >= 4.0 bps)
    quotes = [
        (1.1000, 1.10011),   # 1.0 bps
        (1.1000, 1.100132),  # 1.2 bps
        (1.1000, 1.10066),   # 6.0 bps
    ]
    blocked = guard.update(quotes, current_time=t0)
    assert blocked

    status = guard.get_status(t0)
    assert "OUTLIER_VENUE_DRIFT" in status["last_block_reason"]


def test_wave332_fail_closed_and_reset():
    """Verify single venue, non-numeric price, or crossed spread fail closed and reset restores pristine state."""
    guard = Wave332LOBSpreadCrossSectionalDispersionGuard(cooldown_seconds=20.0)
    t0 = 5000.0

    # Only 1 venue
    assert guard.update([(1.1000, 1.1001)], current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # Non-numeric price
    assert guard.update([(True, 1.1001), (1.1000, 1.1002)], current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Crossed individual venue spread (ask < bid)
    assert guard.update([(1.1005, 1.1001), (1.1000, 1.1002)], current_time=t0 + 2.0)
    assert "VENUE_CROSSED_OR_LOCKED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0


# ==========================================
# Wave 333 Tests: Signed Volume Drift
# ==========================================

def test_wave333_balanced_flow_no_block():
    """Verify balanced two-sided order flow does not trigger volume drift blocks."""
    guard = Wave333TradeFlowSignedVolumeImbalanceDriftGuard(
        window_size=20,
        drift_ratio_threshold=0.78,
        cooldown_seconds=30.0,
    )
    t0 = 6000.0
    # Perfectly alternating buys and sells
    for i in range(25):
        sign = 1 if i % 2 == 0 else -1
        blocked = guard.update(trade_volume=1.0, trade_sign=sign, current_time=t0 + i * 0.5)
        assert not blocked

    status = guard.get_status(t0 + 15.0)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["drift_ratio"] <= 0.20


def test_wave333_persistent_volume_drift_blocks():
    """Verify persistent unilateral buying (drift ratio >= 0.78 with volume >= 16 lots) triggers drift block."""
    guard = Wave333TradeFlowSignedVolumeImbalanceDriftGuard(
        window_size=20,
        drift_ratio_threshold=0.78,
        min_total_volume=16.0,
        sign_concentration_threshold=20,  # avoid sign streak to test drift ratio
        cooldown_seconds=45.0,
    )
    t0 = 7000.0
    # 18 buy trades of 1.0 lot spaced 0.5s apart (to avoid acute avalanche)
    for i in range(18):
        blocked = guard.update(trade_volume=1.0, trade_sign=1, current_time=t0 + i * 0.5)
        if i < 15:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 9.0)
    status = guard.get_status(t0 + 9.0)
    assert "PERSISTENT_VOLUME_DRIFT" in status["last_block_reason"]
    assert status["drift_ratio"] >= 0.78


def test_wave333_acute_directional_avalanche_blocks():
    """Verify rapid sub-second avalanche of signed volume triggers acute avalanche block."""
    guard = Wave333TradeFlowSignedVolumeImbalanceDriftGuard(
        acute_avalanche_volume=12.0,
        acute_time_window_s=0.30,
        cooldown_seconds=45.0,
    )
    t0 = 8000.0
    # 3 trades in 0.15s: 4.5, 4.5, 4.0 lots (total 13.0 lots >= 12.0)
    assert not guard.update(trade_volume=4.5, trade_sign=-1, current_time=t0)
    assert not guard.update(trade_volume=4.5, trade_sign=-1, current_time=t0 + 0.05)
    blocked = guard.update(trade_volume=4.0, trade_sign=-1, current_time=t0 + 0.10)
    assert blocked

    status = guard.get_status(t0 + 0.10)
    assert "ACUTE_DIRECTIONAL_AVALANCHE" in status["last_block_reason"]


def test_wave333_monotonic_sign_concentration_blocks():
    """Verify 12 trades on the same side within 14 trades triggers sign concentration block."""
    guard = Wave333TradeFlowSignedVolumeImbalanceDriftGuard(
        sign_concentration_threshold=12,
        sign_concentration_window=14,
        acute_avalanche_volume=50.0,  # avoid avalanche
        drift_ratio_threshold=0.95,   # avoid drift ratio
        cooldown_seconds=45.0,
    )
    t0 = 9000.0
    # 12 buys and 2 sells in small 0.2 lot sizes spaced 0.5s apart
    signs = [1, 1, 1, 1, -1, 1, 1, 1, 1, -1, 1, 1, 1, 1]
    for i, s in enumerate(signs):
        blocked = guard.update(trade_volume=0.2, trade_sign=s, current_time=t0 + i * 0.5)
        if i == 13:
            assert blocked

    assert guard.is_blocked(t0 + 7.0)
    status = guard.get_status(t0 + 7.0)
    assert "MONOTONIC_SIGN_CONCENTRATION" in status["last_block_reason"]


def test_wave333_fail_closed_and_reset():
    """Verify non-numeric/bool/invalid sign inputs fail closed and reset restores pristine state."""
    guard = Wave333TradeFlowSignedVolumeImbalanceDriftGuard(cooldown_seconds=20.0)
    t0 = 10000.0

    # Non-numeric volume
    assert guard.update(True, 1, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # Invalid sign (e.g. 0)
    assert guard.update(1.0, 0, current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Non-positive volume
    assert guard.update(-2.0, 1, current_time=t0 + 2.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0
