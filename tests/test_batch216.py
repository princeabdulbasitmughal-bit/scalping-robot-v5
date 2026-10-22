"""
tests/test_batch216.py
-----------------------
Unit test suite for Batch 216:
- Wave 198: Price Impact Decay Half-Life & Permanent Retracement Deficit Guard
- Wave 199: Multiscale Realized Volatility Ratio & Microstructure Hurst Divergence Guard

Verifies price impact relaxation dynamics, multiscale variance scaling, fail-closed handling,
and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave198_price_impact_decay_half_life_guard as wave198
import wave199_multiscale_volatility_ratio_guard as wave199


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave198.reset()
    wave199.reset()
    yield
    wave198.reset()
    wave199.reset()


# ---------------------------------------------------------------------------
# Wave 198: Price Impact Decay Half-Life Guard Tests
# ---------------------------------------------------------------------------

def test_wave198_normal_elastic_market_retraces_no_block():
    """A price shock that relaxes back toward equilibrium does not block."""
    assert not wave198.is_entry_blocked()
    assert not wave198.is_blocked()

    # Pre-shock at t=0
    wave198.record_price(2000.0, ts=100.0)
    # Shock: +1.0 point (5.0 bps) at t=0.1s
    wave198.record_price(2001.0, ts=100.1)

    status = wave198.get_status()
    assert status["has_active_shock"]

    # Retracement: price relaxes back to 2000.4 (60% retraced) at t=1.0s
    wave198.record_price(2000.4, ts=101.0)
    # Price relaxes further to 2000.2 (80% retraced) at t=2.1s (past deadline)
    wave198.record_price(2000.2, ts=102.2)

    assert not wave198.is_entry_blocked()
    status = wave198.get_status()
    assert not status["is_blocked"]
    assert not status["has_active_shock"]


def test_wave198_permanent_impact_no_retracement_blocks():
    """A price shock that fails to retrace (< 35%) after 2.0s blocks entries for 45s."""
    # Pre-shock at t=100.0
    wave198.record_price(2000.0, ts=100.0)
    # Shock: +2.0 points (10.0 bps) at t=100.2
    wave198.record_price(2002.0, ts=100.2)

    # Price barely moves back: 2001.8 (only 10% retraced)
    wave198.record_price(2001.8, ts=101.0)
    # Evaluation deadline expires at t=102.3s with zero further relaxation
    wave198.record_price(2001.8, ts=102.3)

    assert wave198.is_entry_blocked()
    assert wave198.is_blocked()
    status = wave198.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave198_early_recovery_resolves_shock():
    """Rapid >= 70% retracement before the deadline resolves the active shock immediately."""
    wave198.record_price(2000.0, ts=100.0)
    wave198.record_price(2001.0, ts=100.1)  # 5 bps shock
    assert wave198.get_status()["has_active_shock"]

    # Immediate snap-back to 2000.15 (85% retraced) at t=100.4s
    wave198.record_price(2000.15, ts=100.4)

    assert not wave198.get_status()["has_active_shock"]
    assert not wave198.is_entry_blocked()


def test_wave198_input_validation_and_fail_closed():
    """Booleans, negative prices, NaNs, and Infs are rejected safely."""
    wave198.record_price(True)  # bool rejected
    wave198.record_price(False)  # bool rejected
    wave198.record_price(-2000.0)  # negative rejected
    wave198.record_price(0.0)  # zero rejected
    wave198.record_price(float("nan"))  # nan rejected
    wave198.record_price(float("inf"))  # inf rejected
    wave198.record_price("2000.0")  # string rejected

    assert not wave198.is_entry_blocked()
    assert not wave198.get_status()["has_active_shock"]


def test_wave198_reset_and_status():
    """Reset clears price history, shock state, and active blocks."""
    wave198.record_price(2000.0, ts=100.0)
    wave198.record_price(2005.0, ts=100.1)  # huge shock
    wave198.record_price(2005.0, ts=103.0)  # expired, no retracement -> blocked

    assert wave198.is_entry_blocked()

    wave198.reset()
    assert not wave198.is_entry_blocked()
    status = wave198.get_status()
    assert not status["is_blocked"]
    assert not status["has_active_shock"]


# ---------------------------------------------------------------------------
# Wave 199: Multiscale Realized Volatility Ratio Guard Tests
# ---------------------------------------------------------------------------

def test_wave199_normal_diffusive_equilibrium_no_block():
    """Consistent, steady price returns across horizons maintain VR ~ 1.0, no block."""
    assert not wave199.is_entry_blocked()
    assert not wave199.is_blocked()

    # Steady alternating price moves (+0.20, -0.20 on 2000.0, ~1 bp per tick)
    price = 2000.0
    for i in range(40):
        price += 0.20 if i % 2 == 0 else -0.20
        wave199.record_price(price=price)

    assert not wave199.is_entry_blocked()
    vr = wave199.get_volatility_ratio()
    assert 0.60 <= vr <= 1.80
    status = wave199.get_status()
    assert not status["is_blocked"]


def test_wave199_hyper_volatility_cascade_blocks():
    """A sudden explosion of volatility in the fast scale pushes VR >= 3.0, blocking entries."""
    price = 2000.0
    wave199.record_price(price=price)  # anchor
    # First 24 returns: calm baseline (+0.10, -0.10, ~0.5 bps per tick)
    for i in range(24):
        price += 0.10 if i % 2 == 0 else -0.10
        wave199.record_price(price=price)

    # Next 8 returns (fast scale): violent oscillation (+2.0, -2.0, ~10 bps per tick)
    for i in range(8):
        price += 2.0 if i % 2 == 0 else -2.0
        wave199.record_price(price=price)

    assert wave199.is_entry_blocked()
    assert wave199.is_blocked()
    assert wave199.get_volatility_ratio() >= wave199.MAX_VOLATILITY_RATIO
    status = wave199.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave199_subdiffusive_quote_freeze_blocks():
    """An artificial freeze in fast scale against volatile background pushes VR <= 0.25, blocking entries."""
    price = 2000.0
    wave199.record_price(price=price)  # anchor
    # First 24 returns: active background volatility (+0.50, -0.50, ~2.5 bps per tick)
    for i in range(24):
        price += 0.50 if i % 2 == 0 else -0.50
        wave199.record_price(price=price)

    # Next 8 returns (fast scale): completely pegged/flat (0.0 price moves)
    for _ in range(8):
        wave199.record_price(price=price)

    assert wave199.is_entry_blocked()
    assert wave199.get_volatility_ratio() <= wave199.MIN_VOLATILITY_RATIO


def test_wave199_insufficient_samples_no_block():
    """Less than SLOW_WINDOW returns do not trigger block regardless of price values."""
    price = 2000.0
    wave199.record_price(price=price)  # anchor
    for i in range(20):
        price += 5.0 if i % 2 == 0 else -5.0
        wave199.record_price(price=price)

    assert not wave199.is_entry_blocked()
    assert wave199.get_status()["sample_count"] == 20


def test_wave199_fail_closed_and_reset():
    """Invalid types are ignored; reset clears buffers, metrics, and active blocks."""
    wave199.record_price(True)
    wave199.record_price(-2000.0)
    wave199.record_price(float("nan"))
    wave199.record_price(float("inf"))

    assert not wave199.is_entry_blocked()
    assert wave199.get_status()["sample_count"] == 0

    # Trip block with hyper-volatility
    price = 2000.0
    wave199.update(price=price)  # anchor
    for i in range(24):
        price += 0.10 if i % 2 == 0 else -0.10
        wave199.update(price=price)
    for i in range(8):
        price += 2.0 if i % 2 == 0 else -2.0
        wave199.update(price=price)

    assert wave199.is_entry_blocked()

    # Reset
    wave199.reset()
    assert not wave199.is_entry_blocked()
    assert wave199.get_volatility_ratio() == 1.0
    status = wave199.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
