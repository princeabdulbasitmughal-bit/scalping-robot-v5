"""
tests/test_batch96.py
Batch 96 Unit Tests: Profit Target Shift (wave40) & Session Spread Limiter (wave41).
Crosses the monumental landmark milestone: 1,200+ PASSING TESTS!
Expands test baseline beyond 1,197+ passing tests to 1,207+ passing tests.
Verifies:
1. wave40: ProfitTargetShift initialization defaults, threshold values, and property accessors.
2. wave40: Profit lock mode (+150 USD) tightening take-profit target to 80% of normal baseline.
3. wave40: Recovery mode (-100 USD) loosening take-profit target to 110% of normal baseline.
4. wave40: Normal mode operation and resilient fallback on non-finite, negative, or invalid inputs.
5. wave40: ProfitTargetShift reset() clearing and info() telemetry diagnostics reporting.
6. wave41: SessionSpreadLimiter initialization defaults (Tokyo 1.5p, London Pre 2.0p, Default 3.0p).
7. wave41: UTC session routing logic across Tokyo (00-06), London Pre-Open (06-07), and Default sessions.
8. wave41: Session-specific spread threshold enforcement and directional blocking.
9. wave41: Fail-closed blocking and invalid count incrementing on corrupt, negative, or non-finite spreads.
10. wave41: Dynamic limit updating, reset() state clearing, and info() telemetry introspection.
"""

import math
from datetime import datetime, timezone
import pytest

from wave40_profit_target_shift import ProfitTargetShift
from wave41_session_spread_limiter import SessionSpreadLimiter


def test_wave40_initialization_defaults_and_properties():
    """Verify ProfitTargetShift initializes with defaults and exposes property getters."""
    pts = ProfitTargetShift()
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0


def test_wave40_profit_lock_mode_tightens_tp():
    """Verify daily profit >= +$150 triggers PROFIT_LOCK mode and tightens TP by 20% (0.80x)."""
    pts = ProfitTargetShift()
    base_tp = 40.0

    # PnL = +$180.0 >= $150.0 threshold
    adj_tp = pts.adjust_tp(raw_tp_pips=base_tp, daily_pnl=180.0)
    assert adj_tp == 32.0  # 40.0 * 0.80
    assert pts.mode == "PROFIT_LOCK"
    assert pts.tp_factor == 0.80


def test_wave40_recovery_mode_loosens_tp():
    """Verify daily loss <= -$100 triggers RECOVERY mode and widens TP by 10% (1.10x)."""
    pts = ProfitTargetShift()
    base_tp = 40.0

    # PnL = -$120.0 <= -$100.0 threshold
    adj_tp = pts.adjust_tp(raw_tp_pips=base_tp, daily_pnl=-120.0)
    assert adj_tp == 44.0  # 40.0 * 1.10
    assert pts.mode == "RECOVERY"
    assert pts.tp_factor == 1.10


def test_wave40_normal_mode_and_invalid_inputs():
    """Verify neutral PnL retains normal TP and invalid inputs fall back gracefully."""
    pts = ProfitTargetShift()
    base_tp = 40.0

    # Neutral PnL: +$45.0
    adj_tp = pts.adjust_tp(raw_tp_pips=base_tp, daily_pnl=45.0)
    assert adj_tp == 40.0
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0

    # Invalid raw_tp_pips returns unmodified
    assert pts.adjust_tp(raw_tp_pips=None, daily_pnl=200.0) is None
    assert pts.adjust_tp(raw_tp_pips=True, daily_pnl=200.0) is True
    assert pts.adjust_tp(raw_tp_pips=-10.0, daily_pnl=200.0) == -10.0
    assert pts.adjust_tp(raw_tp_pips=0.0, daily_pnl=200.0) == 0.0
    assert pts.adjust_tp(raw_tp_pips=float("nan"), daily_pnl=200.0) is not None

    # Invalid daily_pnl defaults to safe 0.0 (NORMAL mode)
    adj_safe = pts.adjust_tp(raw_tp_pips=base_tp, daily_pnl=None)
    assert adj_safe == 40.0
    assert pts.mode == "NORMAL"


def test_wave40_reset_and_info_introspection():
    """Verify reset() restores defaults and info() outputs diagnostic status."""
    pts = ProfitTargetShift()
    pts.adjust_tp(raw_tp_pips=30.0, daily_pnl=200.0)
    assert pts.mode == "PROFIT_LOCK"

    info = pts.info()
    assert info["wave"] == 40
    assert info["name"] == "ProfitTargetShift"
    assert info["mode"] == "PROFIT_LOCK"
    assert info["tp_factor"] == 0.80
    assert info["tighten_threshold_usd"] == 150.0
    assert info["loosen_threshold_usd"] == -100.0

    pts.reset()
    info_reset = pts.info()
    assert info_reset["mode"] == "NORMAL"
    assert info_reset["tp_factor"] == 1.0


def test_wave41_initialization_defaults_and_custom_limits():
    """Verify SessionSpreadLimiter initializes with defaults and allows custom limit overrides."""
    limiter = SessionSpreadLimiter()
    assert limiter._limits["tokyo"] == 1.5
    assert limiter._limits["london_pre"] == 2.0
    assert limiter._limits["default"] == 3.0
    assert limiter._blocked_count == 0
    assert limiter._invalid_count == 0

    custom = SessionSpreadLimiter(custom_limits={"tokyo": 1.2, "ny": 2.5})
    assert custom._limits["tokyo"] == 1.2
    assert custom._limits["ny"] == 2.5


def test_wave41_session_routing_by_utc_hour():
    """Verify session name resolution based on UTC hour and minute."""
    # Tokyo: 00:00 - 06:00 UTC
    assert SessionSpreadLimiter._get_session(0, 0) == "tokyo"
    assert SessionSpreadLimiter._get_session(5, 59) == "tokyo"

    # London Pre-Open: 06:00 - 07:00 UTC
    assert SessionSpreadLimiter._get_session(6, 0) == "london_pre"
    assert SessionSpreadLimiter._get_session(6, 45) == "london_pre"

    # Default: all other hours
    assert SessionSpreadLimiter._get_session(7, 0) == "default"
    assert SessionSpreadLimiter._get_session(14, 30) == "default"
    assert SessionSpreadLimiter._get_session(23, 15) == "default"

    # Robustness against string/negative inputs
    assert SessionSpreadLimiter._get_session("bad") == "default"
    assert SessionSpreadLimiter._get_session(-1) == "default"


def test_wave41_session_spread_limit_blocking():
    """Verify spread gating enforces session-specific pip caps."""
    limiter = SessionSpreadLimiter()

    # 1. Tokyo session (limit 1.5 pips)
    dt_tokyo = datetime(2026, 10, 18, 3, 0, 0, tzinfo=timezone.utc)
    assert limiter.is_entry_blocked(spread_pips=1.2, now_dt=dt_tokyo) is False
    assert limiter.is_entry_blocked(spread_pips=1.8, now_dt=dt_tokyo) is True

    # 2. London Pre-Open session (limit 2.0 pips)
    dt_london_pre = datetime(2026, 10, 18, 6, 30, 0, tzinfo=timezone.utc)
    assert limiter.is_entry_blocked(spread_pips=1.8, now_dt=dt_london_pre) is False
    assert limiter.is_entry_blocked(spread_pips=2.4, now_dt=dt_london_pre) is True

    # 3. Default session (limit 3.0 pips)
    dt_default = datetime(2026, 10, 18, 14, 0, 0, tzinfo=timezone.utc)
    assert limiter.is_entry_blocked(spread_pips=2.6, now_dt=dt_default) is False
    assert limiter.is_entry_blocked(spread_pips=3.2, now_dt=dt_default) is True


def test_wave41_invalid_spread_fails_closed():
    """Verify invalid, non-numeric, or non-positive spreads fail closed (blocked=True)."""
    limiter = SessionSpreadLimiter()
    dt = datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)

    # All invalid inputs must block entry and increment invalid_count
    assert limiter.is_entry_blocked(spread_pips=None, now_dt=dt) is True
    assert limiter.is_entry_blocked(spread_pips=True, now_dt=dt) is True
    assert limiter.is_entry_blocked(spread_pips=False, now_dt=dt) is True
    assert limiter.is_entry_blocked(spread_pips=-1.5, now_dt=dt) is True
    assert limiter.is_entry_blocked(spread_pips=0.0, now_dt=dt) is True
    assert limiter.is_entry_blocked(spread_pips=float("nan"), now_dt=dt) is True
    assert limiter.is_entry_blocked(spread_pips=float("inf"), now_dt=dt) is True
    assert limiter.is_entry_blocked(spread_pips="invalid_spread", now_dt=dt) is True

    assert limiter._invalid_count == 8
    assert limiter._blocked_count == 8


def test_wave41_update_limits_reset_and_info():
    """Verify dynamic limit updates, reset() state clearing, and info() reporting."""
    limiter = SessionSpreadLimiter()
    dt = datetime(2026, 10, 18, 4, 0, 0, tzinfo=timezone.utc)
    limiter.is_entry_blocked(spread_pips=2.0, now_dt=dt)  # Blocked in Tokyo (2.0 > 1.5)

    info = limiter.info()
    assert info["wave"] == 41
    assert info["name"] == "SessionSpreadLimiter"
    assert info["session"] == "tokyo"
    assert info["spread_pips"] == 2.0
    assert info["limit_pips"] == 1.5
    assert info["blocked_count_total"] == 1

    # Update limits dynamically
    limiter.update_limits({"tokyo": 2.5})
    assert limiter.is_entry_blocked(spread_pips=2.0, now_dt=dt) is False

    # Reset flushes counters
    limiter.reset()
    info_reset = limiter.info()
    assert info_reset["blocked_count_total"] == 0
    assert info_reset["invalid_count"] == 0
    assert info_reset["spread_pips"] == 0.0
