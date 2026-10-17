"""
tests/test_batch97.py
Batch 97 Unit Tests: Volatility Breaker (wave38) & Drawdown Pause (wave39).
Expands test baseline beyond 1,207+ passing tests to 1,217+ passing tests.
Verifies:
1. wave38: VolatilityBreaker initialization defaults, window constants, and parameter bounds.
2. wave38: Minimum tick warmup gating (25 ticks) and non-finite/negative input rejection.
3. wave38: Normal volatility ratio operation (ratio < 2.5x) allowing entry clearance.
4. wave38: Sustained volatility surge (ratio >= 2.5x baseline) triggering 90-second entry lockout.
5. wave38: VolatilityBreaker reset() clearing and info() diagnostic telemetry reporting.
6. wave39: DrawdownPause initialization defaults, 30-minute window, and 1.5% threshold constants.
7. wave39: Timestamped equity ingestion, rolling 30-minute window pruning, and invalid input filtering.
8. wave39: Sub-threshold equity drawdown (< 1.5%) allowing trading without restriction.
9. wave39: Drawdown breach (>= 1.5% from peak) triggering 15-minute pause and auto-expiry.
10. wave39: DrawdownPause reset() state flushing and info() diagnostic telemetry introspection.
"""

import math
import time
import pytest

from wave38_volatility_breaker import VolatilityBreaker
from wave39_drawdown_pause import DrawdownPause


def test_wave38_initialization_defaults_and_constants():
    """Verify VolatilityBreaker initializes with defaults and proper window constants."""
    breaker = VolatilityBreaker()
    assert breaker.SHORT_WINDOW == 20
    assert breaker.LONG_WINDOW == 100
    assert breaker.SPIKE_RATIO == 2.5
    assert breaker.BLOCK_SECONDS == 90
    assert breaker.MIN_TICKS == 25
    assert len(breaker._short_prices) == 0
    assert len(breaker._long_prices) == 0
    assert breaker._block_until == 0.0
    assert breaker.total_spikes == 0
    assert breaker.total_blocks == 0
    assert breaker._tick_count == 0


def test_wave38_warmup_and_invalid_inputs():
    """Verify minimum tick warmup requirement and rejection of invalid price inputs."""
    breaker = VolatilityBreaker()
    t0 = 1750000000.0

    # Feed 15 ticks (fewer than MIN_TICKS 25)
    for i in range(15):
        breaker.update(2400.0 + i, now_ts=t0 + i)

    assert breaker._tick_count == 15
    assert breaker.is_entry_blocked(now_ts=t0 + 15) is False

    # Feed invalid prices: None, boolean, string, <= 0, NaN, inf
    breaker.update(None, now_ts=t0 + 16)
    breaker.update(True, now_ts=t0 + 16)
    breaker.update(False, now_ts=t0 + 16)
    breaker.update(-2400.0, now_ts=t0 + 16)
    breaker.update(0.0, now_ts=t0 + 16)
    breaker.update(float("nan"), now_ts=t0 + 16)
    breaker.update(float("inf"), now_ts=t0 + 16)
    breaker.update("bad_price", now_ts=t0 + 16)

    # Tick count remains unchanged at 15
    assert breaker._tick_count == 15


def test_wave38_normal_volatility_allows_trading():
    """Verify normal volatility ratio (ratio < 2.5x baseline) does not block entry."""
    breaker = VolatilityBreaker()
    t0 = 1750000000.0

    # Feed 30 ticks with constant small step changes (0.1 per tick)
    for i in range(30):
        breaker.update(2400.0 + (i * 0.1), now_ts=t0 + i)

    assert breaker._tick_count == 30
    assert breaker._last_ratio == pytest.approx(1.0, abs=0.1)
    assert breaker.is_entry_blocked(now_ts=t0 + 30) is False
    assert breaker.total_spikes == 0


def test_wave38_volatility_spike_triggers_90s_block():
    """Verify sustained volatility surge (short ATR >= 2.5x baseline ATR) triggers 90s lockout."""
    breaker = VolatilityBreaker()
    t0 = 1750000000.0

    # 1. Feed 80 calm ticks (0.05 step change per tick) to establish low baseline ATR
    price = 2400.0
    for i in range(80):
        price += (0.05 if i % 2 == 0 else -0.05)
        breaker.update(price, now_ts=t0 + i)

    # 2. Feed 20 aggressive volatility ticks (1.5 step change per tick)
    for i in range(20):
        price += (1.5 if i % 2 == 0 else -1.5)
        breaker.update(price, now_ts=t0 + 80 + i)

    # Short ATR (~1.5) / Baseline ATR (~0.34) >= 2.5 -> SPIKE!
    assert breaker._last_ratio >= 2.5
    assert breaker.is_entry_blocked(now_ts=t0 + 100) is True
    assert breaker.total_spikes >= 1
    assert breaker.total_blocks >= 1
    assert breaker._block_until >= t0 + 100
    rem = breaker.seconds_remaining(now_ts=t0 + 100)
    assert rem > 0.0

    # Cooldown expires after _block_until
    unblock_time = breaker._block_until + 1.0
    assert breaker.is_entry_blocked(now_ts=unblock_time) is False
    assert breaker.seconds_remaining(now_ts=unblock_time) == 0.0


def test_wave38_reset_and_info_introspection():
    """Verify reset() flushes buffers and info() outputs diagnostic telemetry."""
    breaker = VolatilityBreaker()
    t0 = 1750000000.0
    for i in range(30):
        breaker.update(2400.0 + (i * 0.1), now_ts=t0 + i)

    info = breaker.info(now_ts=t0 + 30)
    assert info["short_window_ticks"] == 20
    assert info["long_window_ticks"] == 100
    assert info["spike_ratio_threshold"] == 2.5
    assert info["block_seconds"] == 90
    assert info["currently_blocked"] is False
    assert info["seconds_remaining"] == 0.0
    assert info["current_atr"] > 0.0
    assert info["baseline_atr"] > 0.0

    breaker.reset()
    info_reset = breaker.info(now_ts=t0 + 30)
    assert info_reset["currently_blocked"] is False
    assert info_reset["current_atr"] == 0.0
    assert info_reset["baseline_atr"] == 0.0
    assert breaker._tick_count == 0


def test_wave39_initialization_defaults_and_constants():
    """Verify DrawdownPause initializes with defaults and 30-minute window constants."""
    ddp = DrawdownPause()
    assert ddp.WINDOW_SEC == 1800.0
    assert ddp.DRAWDOWN_PCT == 1.5
    assert ddp.PAUSE_SEC == 900.0
    assert len(ddp._equity_history) == 0
    assert ddp._blocked_until == 0.0
    assert ddp._last_trigger_reason == ""


def test_wave39_update_prunes_stale_entries():
    """Verify update() prunes equity entries older than 30 minutes (WINDOW_SEC=1800s)."""
    ddp = DrawdownPause()
    t0 = 1750000000.0

    # Record equity at t0
    ddp.update(10000.0, now_ts=t0)
    assert len(ddp._equity_history) == 1

    # Record equity at t0 + 1000s (within 1800s window)
    ddp.update(10050.0, now_ts=t0 + 1000.0)
    assert len(ddp._equity_history) == 2

    # Record equity at t0 + 2000s: t0 (2000s ago) is now stale and pruned
    ddp.update(10080.0, now_ts=t0 + 2000.0)
    assert len(ddp._equity_history) == 2
    assert ddp._equity_history[0][0] == t0 + 1000.0

    # Invalid equity inputs are safely ignored
    ddp.update(None, now_ts=t0 + 2100.0)
    ddp.update(True, now_ts=t0 + 2100.0)
    ddp.update(-1000.0, now_ts=t0 + 2100.0)
    ddp.update(0.0, now_ts=t0 + 2100.0)
    ddp.update(float("nan"), now_ts=t0 + 2100.0)
    assert len(ddp._equity_history) == 2


def test_wave39_normal_drawdown_allows_trading():
    """Verify minor drawdown (< 1.5% from peak) allows entry clearance without pause."""
    ddp = DrawdownPause()
    t0 = 1750000000.0

    ddp.update(10000.0, now_ts=t0)
    # Dip to 9900.0 (dd = (10000 - 9900)/10000 * 100 = 1.0% < 1.5%)
    ddp.update(9900.0, now_ts=t0 + 100.0)

    assert ddp.is_entry_blocked(now_ts=t0 + 100.0) is False
    assert ddp._blocked_until == 0.0


def test_wave39_drawdown_breach_triggers_15min_pause():
    """Verify drawdown >= 1.5% from peak trips 15-minute pause lockout."""
    ddp = DrawdownPause()
    t0 = 1750000000.0

    ddp.update(10000.0, now_ts=t0)
    # Drop to 9800.0 (dd = 2.0% >= 1.5% threshold)
    ddp.update(9800.0, now_ts=t0 + 60.0)

    assert ddp.is_entry_blocked(now_ts=t0 + 60.0) is True
    assert ddp._blocked_until == t0 + 60.0 + 900.0
    assert "peak=$10000.00 current=$9800.00 drawdown=2.00%" in ddp._last_trigger_reason
    assert ddp.seconds_remaining(now_ts=t0 + 60.0) == 900.0

    # 450s in (halfway through 15m pause): still blocked
    assert ddp.is_entry_blocked(now_ts=t0 + 510.0) is True
    assert ddp.seconds_remaining(now_ts=t0 + 510.0) == 450.0

    # 901s in: pause expired, equity recovered to 9900 (dd = 1.0% < 1.5%) -> unblocked
    ddp.update(9900.0, now_ts=t0 + 961.0)
    assert ddp.is_entry_blocked(now_ts=t0 + 961.0) is False
    assert ddp.seconds_remaining(now_ts=t0 + 961.0) == 0.0


def test_wave39_reset_and_info_introspection():
    """Verify reset() flushes state and info() outputs diagnostic telemetry."""
    ddp = DrawdownPause()
    t0 = 1750000000.0

    ddp.update(10000.0, now_ts=t0)
    ddp.update(9800.0, now_ts=t0 + 30.0)
    ddp.is_entry_blocked(now_ts=t0 + 30.0)

    info = ddp.info(now_ts=t0 + 30.0)
    assert info["blocked"] is True
    assert info["seconds_remaining"] == 900.0
    assert info["drawdown_pct"] == 2.0
    assert info["peak_equity"] == 10000.0
    assert info["current_equity"] == 9800.0
    assert info["history_points"] == 2
    assert "peak=$10000.00" in info["last_reason"]

    ddp.reset()
    info_reset = ddp.info(now_ts=t0 + 30.0)
    assert info_reset["blocked"] is False
    assert info_reset["seconds_remaining"] == 0.0
    assert info_reset["drawdown_pct"] == 0.0
    assert info_reset["history_points"] == 0
    assert info_reset["last_reason"] == ""
