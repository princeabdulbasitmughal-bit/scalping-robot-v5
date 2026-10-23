"""
tests/test_batch270.py
----------------------
Unit tests for Batch 270:
  - Wave 306: Wave306LobSpreadAsymmetrySkewGuard
  - Wave 307: Wave307TradeSignRunsTestGuard
"""

import math
import time
import pytest

from wave306_lob_spread_asymmetry_skew_guard import Wave306LobSpreadAsymmetrySkewGuard
from wave307_trade_sign_runs_test_guard import Wave307TradeSignRunsTestGuard


# ----------------------------------------------------------------------
# Wave 306 Tests: LOB Spread Quote Asymmetry & Inventory Shading Skew Guard
# ----------------------------------------------------------------------

def test_wave306_symmetric_quotes_no_block():
    guard = Wave306LobSpreadAsymmetrySkewGuard(
        max_quote_asymmetry=0.65,
        min_samples=10,
    )

    # 12 ticks of symmetric balanced quotes around 100.0 (bid 99.99, ask 100.01)
    for _ in range(12):
        guard.record_quotes(bid=99.99, ask=100.01, prev_mid=100.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_asymmetry_metrics()
    assert abs(metrics["mean_asymmetry"]) < 0.10
    assert not metrics["is_blocked"]


def test_wave306_persistent_quote_asymmetry_blocks():
    guard = Wave306LobSpreadAsymmetrySkewGuard(
        max_quote_asymmetry=0.65,
        min_samples=10,
        min_spread_bps=2.00,
        cooldown_seconds=45.0,
    )

    # Market makers strongly shade ask away (mid=100.0, bid=99.98, ask=100.18)
    # s_bid = 0.02, s_ask = 0.18 -> asymmetry = 0.16 / 0.20 = +0.80 (> 0.65)
    # spread = 0.20 / 100 = 20 bps (> 2 bps)
    for _ in range(11):
        guard.record_quotes(bid=99.98, ask=100.18, prev_mid=100.0)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "PERSISTENT_QUOTE_ASYMMETRY" in status["last_block_reason"]


def test_wave306_acute_quote_blowout_blocks():
    guard = Wave306LobSpreadAsymmetrySkewGuard(
        acute_quote_asymmetry=0.85,
        acute_spread_bps=3.00,
        cooldown_seconds=45.0,
    )

    # Acute extreme shading: bid=99.99, ask=100.25 relative to mid=100.0
    # s_bid = 0.01, s_ask = 0.25 -> asym = 0.24 / 0.26 = 0.923 (> 0.85)
    # spread = 26 bps (> 3 bps)
    guard.record_quotes(bid=99.99, ask=100.25, prev_mid=100.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_asymmetry_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_QUOTE_BLOWOUT" in metrics["last_block_reason"]


def test_wave306_direct_asymmetry_metrics():
    guard = Wave306LobSpreadAsymmetrySkewGuard(
        max_quote_asymmetry=0.65,
        cooldown_seconds=45.0,
    )

    # Below threshold
    guard.record_asymmetry_metrics(asymmetry_skew=0.40, spread_bps=2.5, sample_count=12)
    assert not guard.is_entry_blocked()

    # Above threshold
    guard.record_asymmetry_metrics(asymmetry_skew=-0.75, spread_bps=3.5, sample_count=12)
    assert guard.is_entry_blocked()
    assert "PERSISTENT_QUOTE_ASYMMETRY" in guard.get_status()["last_block_reason"]


def test_wave306_fail_closed_and_reset():
    guard = Wave306LobSpreadAsymmetrySkewGuard(cooldown_seconds=45.0)

    # Corrupted inputs: inverted ask <= bid, NaN, Inf, non-numeric, negative
    for bad_bid, bad_ask in [(100.5, 100.0), (float("nan"), 100.0), (99.0, float("inf")), (-10.0, 100.0), (None, 100.0)]:
        guard.record_quotes(bad_bid, bad_ask)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_QUOTE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(99.9, 100.1, prev_mid=100.0)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 307 Tests: Trade Sign Wald-Wolfowitz Runs Test Guard
# ----------------------------------------------------------------------

def test_wave307_random_walk_runs_no_block():
    guard = Wave307TradeSignRunsTestGuard(
        max_runs_deficit_z=-2.80,
        max_runs_excess_z=3.20,
        min_samples=20,
    )

    # Typical independent random order flow: balanced alternating and short runs
    random_signs = [
        1, 1, -1, 1, -1, -1, 1, -1, 1, 1,
        -1, -1, 1, -1, 1, -1, -1, 1, 1, -1,
        1, -1, -1, 1
    ]
    for s in random_signs:
        guard.record_trade_sign(s)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_runs_metrics()
    assert -2.0 <= metrics["runs_z_score"] <= 2.0
    assert not metrics["is_blocked"]


def test_wave307_runs_deficit_sweep_blocks():
    guard = Wave307TradeSignRunsTestGuard(
        max_runs_deficit_z=-2.80,
        min_samples=20,
        cooldown_seconds=45.0,
    )

    # Severe directional clustering: 11 buys followed by 11 sells (only 2 runs in 22 trades)
    clustered_signs = [1] * 11 + [-1] * 11
    for s in clustered_signs:
        guard.record_trade_sign(s)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    # Triggers runs deficit sweep or acute monotonic run
    assert ("RUNS_DEFICIT_SWEEP" in status["last_block_reason"] or 
            "ACUTE_MONOTONIC_RUN" in status["last_block_reason"])


def test_wave307_runs_excess_pingpong_blocks():
    guard = Wave307TradeSignRunsTestGuard(
        max_runs_excess_z=3.20,
        min_samples=20,
        cooldown_seconds=45.0,
    )

    # Extreme ping-pong alternation: exactly alternating signs every single trade (24 runs in 24 trades)
    pingpong_signs = [1 if i % 2 == 0 else -1 for i in range(24)]
    for s in pingpong_signs:
        guard.record_trade_sign(s)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "RUNS_EXCESS_PINGPONG" in status["last_block_reason"]


def test_wave307_acute_monotonic_run_blocks():
    guard = Wave307TradeSignRunsTestGuard(
        acute_monotonic_run=9,
        cooldown_seconds=45.0,
    )

    # 8 consecutive buys -> not yet 9
    for _ in range(8):
        guard.record_trade_sign(1)
        assert not guard.is_entry_blocked()

    # 9th consecutive buy -> trips acute monotonic run
    guard.record_trade_sign(1)
    assert guard.is_entry_blocked()
    assert "ACUTE_MONOTONIC_RUN" in guard.get_status()["last_block_reason"]


def test_wave307_fail_closed_and_reset():
    guard = Wave307TradeSignRunsTestGuard(cooldown_seconds=45.0)

    # String parsing and boolean parsing
    guard.record_trade_sign("BUY")
    assert not guard.is_entry_blocked()
    guard.record_trade_sign(True)
    assert not guard.is_entry_blocked()

    # Corrupted inputs
    for bad_sign in [None, "invalid_str", float("nan"), float("inf")]:
        guard.record_trade_sign(bad_sign)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_SIGN_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Tick rule price derivation
    guard.record_trade(100.0)
    guard.record_trade(100.05)  # Tick rule: +1
    assert not guard.is_entry_blocked()
