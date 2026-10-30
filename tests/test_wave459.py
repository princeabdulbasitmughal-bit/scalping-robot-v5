"""
Unit Test Suite for Wave 459: Hawkes Process Mutual-Excitation Cross-Venue Contagion Guard
"""

import pytest
import numpy as np
from wave459_hawkes_cross_venue_contagion_guard import Wave459HawkesCrossVenueContagionGuard


def test_initialization_defaults_and_validation():
    guard = Wave459HawkesCrossVenueContagionGuard()
    assert guard.window_events == 40
    assert guard.beta_decay == 25.0
    assert guard.max_spectral_radius == 0.85
    assert guard.max_cross_ratio == 1.80
    assert guard.min_events == 15
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="window_events"):
        Wave459HawkesCrossVenueContagionGuard(window_events=10)
    with pytest.raises(ValueError, match="beta_decay"):
        Wave459HawkesCrossVenueContagionGuard(beta_decay=0.5)
    with pytest.raises(ValueError, match="max_spectral_radius"):
        Wave459HawkesCrossVenueContagionGuard(max_spectral_radius=0.40)
    with pytest.raises(ValueError, match="max_spectral_radius"):
        Wave459HawkesCrossVenueContagionGuard(max_spectral_radius=0.99)
    with pytest.raises(ValueError, match="max_cross_ratio"):
        Wave459HawkesCrossVenueContagionGuard(max_cross_ratio=0.9)
    with pytest.raises(ValueError, match="min_events"):
        Wave459HawkesCrossVenueContagionGuard(min_events=5)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave459HawkesCrossVenueContagionGuard(cooldown_sec=0.05)


def test_venue_and_monotonicity_validation():
    guard = Wave459HawkesCrossVenueContagionGuard()
    with pytest.raises(ValueError, match="venue must be 'A' or 'B'"):
        guard.update(venue="C", timestamp=1.0)

    guard.update(venue="A", timestamp=1.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(venue="B", timestamp=1.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(venue="A", timestamp=0.5)


def test_insufficient_events_state():
    guard = Wave459HawkesCrossVenueContagionGuard(min_events=15)
    for i in range(14):
        blocked = guard.update(venue="A" if i % 2 == 0 else "B", timestamp=10.0 + i * 0.1)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.block_reason == "INSUFFICIENT_EVENTS"


def test_calm_subcritical_arrivals_no_block():
    guard = Wave459HawkesCrossVenueContagionGuard(min_events=15, beta_decay=25.0)
    # Slow events with dt=0.2s -> exp(-25 * 0.2) = exp(-5) ~ 0.0067 -> very small excitation
    t = 10.0
    for i in range(25):
        t += 0.20
        venue = "A" if i % 2 == 0 else "B"
        blocked = guard.update(venue=venue, timestamp=t)

    assert not blocked
    assert not guard.is_blocked()
    assert guard.spectral_radius < 0.85
    assert guard.block_reason == ""


def test_supercritical_burst_cascade_block():
    guard = Wave459HawkesCrossVenueContagionGuard(
        min_events=15,
        max_spectral_radius=0.85,
        beta_decay=25.0
    )
    # Extremely dense cluster of events arriving every 0.002s (2ms) across both venues
    t = 100.0
    blocked = False
    for i in range(30):
        t += 0.002
        venue = "A" if i % 2 == 0 else "B"
        blocked = guard.update(venue=venue, timestamp=t)
        if blocked:
            break

    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "HAWKES_SUPERCRITICAL_CASCADE" in guard.block_reason
    assert guard.spectral_radius > 0.85


def test_asymmetric_toxic_cross_venue_contagion_block():
    guard = Wave459HawkesCrossVenueContagionGuard(
        min_events=15,
        max_cross_ratio=1.80,
        beta_decay=25.0
    )
    # Generate arrivals where Venue A arrivals are immediately followed by rapid Venue B arrivals (Venue A -> Venue B cross-excitation),
    # while Venue B has very few self-arrivals
    t = 200.0
    for i in range(25):
        # Venue A arrival
        t += 0.04
        guard.update(venue="A", timestamp=t)
        # Immediate Venue B reactive arrivals shortly after A (dt = 0.004s -> exp(-25*0.004) = 0.90)
        t += 0.004
        guard.update(venue="B", timestamp=t)
        t += 0.004
        guard.update(venue="B", timestamp=t)

    assert guard.is_blocked()
    assert guard.cross_ratio > 1.80 or guard.spectral_radius > guard.max_spectral_radius


def test_cooldown_period_enforcement():
    guard = Wave459HawkesCrossVenueContagionGuard(
        min_events=15,
        cooldown_sec=2.0
    )
    # Trigger supercritical cascade
    t = 300.0
    for i in range(25):
        t += 0.002
        guard.update(venue="A" if i % 2 == 0 else "B", timestamp=t)

    assert guard.is_blocked()

    # Advance time by 0.5s (within 2.0s cooldown) with a single calm event
    t += 0.5
    blocked_in_cooldown = guard.update(venue="A", timestamp=t)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave459HawkesCrossVenueContagionGuard()
    t = 400.0
    for i in range(20):
        t += 0.05
        guard.update(venue="A" if i % 2 == 0 else "B", timestamp=t)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave459HawkesCrossVenueContagionGuard"
    assert "spectral_radius" in telem
    assert "cross_ratio" in telem
    assert "gamma_aa" in telem
    assert "gamma_ab" in telem
    assert "gamma_ba" in telem
    assert "gamma_bb" in telem
    assert telem["max_spectral_radius"] == 0.85
    assert isinstance(telem["is_blocked"], bool)
    assert telem["event_count"] == 20


def test_reset_functionality():
    guard = Wave459HawkesCrossVenueContagionGuard()
    t = 500.0
    for i in range(25):
        t += 0.002
        guard.update(venue="A" if i % 2 == 0 else "B", timestamp=t)

    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard.spectral_radius == 0.0
    assert np.all(guard.gamma_matrix == 0.0)
    assert guard.cross_ratio == 0.0
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
