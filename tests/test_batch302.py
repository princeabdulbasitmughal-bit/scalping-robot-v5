"""
tests/test_batch302.py
======================
Combined pytest test suite for Batch 302:
  - Wave 362: LOB Spread Mean-Reversion Half-Life Guard
  - Wave 363: Trade Flow Intertrade Duration Exponential Decay Guard

At least 12 tests covering both guards.
"""

import math
import sys
import time
import os
import pytest

# Ensure project root is importable regardless of pytest invocation directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave362_lob_spread_mean_reversion_half_life_guard import (
    Wave362LobSpreadMeanReversionHalfLifeGuard,
)
from wave363_trade_flow_intertrade_duration_exponential_decay_guard import (
    Wave363TradeFlowIntertradeDecayGuard,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BID_NORM = 1.0000
ASK_NORM = 1.0002  # 2 bps spread


def _fill_w362(guard, window_size=20, spread_bps=2.0, stable=True):
    """
    Feed `window_size` ticks into a Wave 362 guard.

    stable=True  => constant spread  (phi ~ 0, half-life ~ 0 ticks, no block)
    stable=False => slowly drifting spread (phi close to 1)
    """
    ts = time.monotonic()
    mid = 1.0
    for i in range(window_size):
        if stable:
            s = spread_bps / 10000.0 * mid
        else:
            # Linearly drifting ask so phi -> 1
            s = (spread_bps + i * 0.5) / 10000.0 * mid
        ask = mid + s / 2.0
        bid = mid - s / 2.0
        guard.update(bid, ask, ts + i)


def _fill_w363(guard, window_size=20, interval=1.0):
    """
    Feed `window_size + 1` trade events with fixed `interval` seconds apart.
    This produces `window_size` inter-trade durations.
    """
    ts = time.monotonic()
    for i in range(window_size + 1):
        guard.update(ts + i * interval)


# ===========================================================================
# WAVE 362 TESTS
# ===========================================================================


class TestWave362:

    # T1 — No block before window is full
    def test_no_block_before_window_fills(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(window_size=20)
        ts = time.monotonic()
        for i in range(19):  # one less than window_size
            g.update(BID_NORM, ASK_NORM, ts + i)
        assert not g.is_blocked()
        assert g.last_reason == ""

    # T2 — Stable spread never blocks (phi ~ 0, tiny half-life)
    def test_stable_spread_no_block(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(
            window_size=20, max_half_life_ticks=30.0, cooldown_seconds=0.0
        )
        _fill_w362(g, window_size=20, spread_bps=2.0, stable=True)
        assert not g.is_blocked()

    # T3 — Explosive spread blocks with EXPLOSIVE_SPREAD
    def test_explosive_spread_blocks(self):
        """
        Construct a series where spread increases geometrically so that
        the OLS phi estimate >= 1.0.
        """
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(
            window_size=10, max_half_life_ticks=30.0, cooldown_seconds=60.0
        )
        ts = time.monotonic()
        mid = 1.0
        # Spread doubles each tick: phi ~ 2 in AR(1)
        for i in range(10):
            s = (0.001 * (2 ** i))
            ask = mid + s
            bid = mid - s
            g.update(bid, ask, ts + i)
        assert g.is_blocked()
        assert g.last_reason == "EXPLOSIVE_SPREAD"

    # T4 — Slow reversion (large half-life) blocks with SLOW_SPREAD_REVERSION
    def test_slow_reversion_blocks(self):
        """
        phi close to but strictly less than 1 => large half-life.
        Build series: spread_t = 0.999 * spread_{t-1} + small_constant
        so OLS recovers phi ~ 0.999 and half-life = -log2/log(0.999) ~ 693 ticks.
        """
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(
            window_size=20, max_half_life_ticks=30.0, cooldown_seconds=60.0
        )
        ts = time.monotonic()
        mid = 1.0
        spread = 0.001  # initial spread fraction
        phi_true = 0.998
        for i in range(20):
            ask = mid + spread / 2.0
            bid = mid - spread / 2.0
            g.update(bid, ask, ts + i)
            spread = phi_true * spread + 1e-6  # AR(1) with phi close to 1

        assert g.is_blocked()
        assert g.last_reason == "SLOW_SPREAD_REVERSION"

    # T5 — Invalid bid (string) blocks with INPUT_VALIDATION_ERROR
    def test_invalid_bid_type_blocks(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update("bad", ASK_NORM, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T6 — Invalid ask (bool) blocks with INPUT_VALIDATION_ERROR
    def test_invalid_ask_bool_blocks(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update(BID_NORM, True, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T7 — NaN bid blocks with INPUT_VALIDATION_ERROR
    def test_nan_bid_blocks(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update(float("nan"), ASK_NORM, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T8 — Negative bid blocks with INPUT_VALIDATION_ERROR
    def test_negative_bid_blocks(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update(-1.0, ASK_NORM, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T9 — ask < bid (inverted) blocks with INPUT_VALIDATION_ERROR
    def test_inverted_spread_blocks(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update(ASK_NORM, BID_NORM, time.monotonic())  # bid > ask
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T10 — reset clears all state
    def test_reset_clears_state(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update("bad", ASK_NORM, time.monotonic())
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""

    # T11 — is_entry_blocked delegates update and returns bool
    def test_is_entry_blocked_delegates(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        result = g.is_entry_blocked("bad", ASK_NORM, time.monotonic())
        assert result is True
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T12 — Bool timestamp blocked (bool before numeric check)
    def test_bool_timestamp_blocks(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update(BID_NORM, ASK_NORM, True)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T13 — cooldown_seconds=0 means block expires immediately
    def test_zero_cooldown_expires_immediately(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(
            window_size=10, max_half_life_ticks=5.0, cooldown_seconds=0.0
        )
        g.update("bad", ASK_NORM, time.monotonic())
        # With cooldown=0 the blocked_until == monotonic() at trigger time,
        # which is already <= current monotonic()
        assert not g.is_blocked()


# ===========================================================================
# WAVE 363 TESTS
# ===========================================================================


class TestWave363:

    # T14 — No block before window is full
    def test_no_block_before_window_fills(self):
        g = Wave363TradeFlowIntertradeDecayGuard(window_size=20)
        ts = time.monotonic()
        for i in range(20):  # produces 19 durations — one less than window_size
            g.update(ts + i)
        assert not g.is_blocked()
        assert g.last_reason == ""

    # T15 — Normal trading rate does not block
    def test_normal_rate_no_block(self):
        g = Wave363TradeFlowIntertradeDecayGuard(
            window_size=20,
            burst_lambda_threshold=50.0,
            slow_lambda_threshold=0.01,
            cooldown_seconds=0.0,
        )
        # interval=1.0s => lambda=1.0, well within [0.01, 50]
        _fill_w363(g, window_size=20, interval=1.0)
        assert not g.is_blocked()

    # T16 — Burst trading (tiny interval) blocks with TRADE_BURST_DETECTED
    def test_burst_trading_blocks(self):
        g = Wave363TradeFlowIntertradeDecayGuard(
            window_size=10,
            burst_lambda_threshold=50.0,
            slow_lambda_threshold=0.01,
            cooldown_seconds=45.0,
        )
        # interval=0.001s => lambda=1000 >> 50 => burst
        _fill_w363(g, window_size=10, interval=0.001)
        assert g.is_blocked()
        assert g.last_reason == "TRADE_BURST_DETECTED"

    # T17 — Market freeze (very long interval) blocks with MARKET_FREEZE_DETECTED
    def test_market_freeze_blocks(self):
        g = Wave363TradeFlowIntertradeDecayGuard(
            window_size=10,
            burst_lambda_threshold=50.0,
            slow_lambda_threshold=0.01,
            cooldown_seconds=45.0,
        )
        # interval=200s => lambda=0.005 < 0.01 => freeze
        _fill_w363(g, window_size=10, interval=200.0)
        assert g.is_blocked()
        assert g.last_reason == "MARKET_FREEZE_DETECTED"

    # T18 — Invalid timestamp type blocks with INPUT_VALIDATION_ERROR
    def test_invalid_timestamp_type_blocks(self):
        g = Wave363TradeFlowIntertradeDecayGuard(cooldown_seconds=45.0)
        g.update("not_a_number")
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T19 — Bool timestamp blocked (bool before numeric check)
    def test_bool_timestamp_blocked(self):
        g = Wave363TradeFlowIntertradeDecayGuard(cooldown_seconds=45.0)
        g.update(True)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T20 — NaN timestamp blocks with INPUT_VALIDATION_ERROR
    def test_nan_timestamp_blocks(self):
        g = Wave363TradeFlowIntertradeDecayGuard(cooldown_seconds=45.0)
        g.update(float("nan"))
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T21 — Backwards timestamp blocks with INPUT_VALIDATION_ERROR
    def test_backwards_timestamp_blocks(self):
        g = Wave363TradeFlowIntertradeDecayGuard(cooldown_seconds=45.0)
        ts = time.monotonic()
        g.update(ts + 10.0)
        g.update(ts)  # earlier timestamp => backwards
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T22 — Simultaneous timestamps (delta=0) detected as burst
    def test_simultaneous_timestamps_burst(self):
        g = Wave363TradeFlowIntertradeDecayGuard(cooldown_seconds=45.0)
        ts = time.monotonic()
        g.update(ts)
        g.update(ts)  # delta = 0
        assert g.is_blocked()
        assert g.last_reason == "TRADE_BURST_DETECTED"

    # T23 — reset clears all state
    def test_reset_clears_state(self):
        g = Wave363TradeFlowIntertradeDecayGuard(cooldown_seconds=45.0)
        g.update("bad")
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""
        # After reset the first update should be treated as the seed tick
        ts = time.monotonic()
        g.update(ts)
        assert not g.is_blocked()

    # T24 — is_entry_blocked delegates update and returns bool
    def test_is_entry_blocked_delegates(self):
        g = Wave363TradeFlowIntertradeDecayGuard(cooldown_seconds=45.0)
        result = g.is_entry_blocked(BID_NORM, ASK_NORM, "bad_ts")
        assert result is True
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    # T25 — Constructor validation: window_size < 2 raises
    def test_constructor_invalid_window_raises(self):
        with pytest.raises(ValueError):
            Wave363TradeFlowIntertradeDecayGuard(window_size=1)

    # T26 — Constructor validation: burst <= slow raises
    def test_constructor_burst_leq_slow_raises(self):
        with pytest.raises(ValueError):
            Wave363TradeFlowIntertradeDecayGuard(
                burst_lambda_threshold=0.005,
                slow_lambda_threshold=0.01,
            )

    # T27 — last_reason is empty string before any update
    def test_last_reason_empty_initially(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard()
        assert g.last_reason == ""
        g2 = Wave363TradeFlowIntertradeDecayGuard()
        assert g2.last_reason == ""

    # T28 — is_blocked with explicit far-future time returns True
    def test_is_blocked_explicit_time_future(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update("bad", ASK_NORM, time.monotonic())
        far_past = time.monotonic() - 1000.0
        # far past => should still be blocked (blocked_until is ~now+60)
        assert g.is_blocked(current_time=far_past)

    # T29 — is_blocked with explicit far-past time returns False
    def test_is_blocked_explicit_time_past(self):
        g = Wave362LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=60.0)
        g.update("bad", ASK_NORM, time.monotonic())
        far_future = time.monotonic() + 1000.0
        assert not g.is_blocked(current_time=far_future)
