"""
Test Suite for Batch 137:
- wave40_profit_target_shift.py (ProfitTargetShift: PnL-dependent TP tightening & loosening)
- wave41_session_spread_limiter.py (SessionSpreadLimiter: session-dependent spread filtering)
Zero regressions, continuing toward 1,617+ passed tests.
"""

import math
from datetime import datetime, timezone
import pytest

from wave40_profit_target_shift import (
    ProfitTargetShift,
    profit_target_shift,
    adjust_tp as w40_adjust_tp,
    reset as w40_reset,
    get_mode as w40_get_mode,
    get_tp_factor as w40_get_tp_factor,
)
from wave41_session_spread_limiter import (
    SessionSpreadLimiter,
    session_spread_limiter,
    is_entry_blocked as w41_is_entry_blocked,
    is_blocked as w41_is_blocked,
    update_limits as w41_update_limits,
    reset as w41_reset,
)


# ---------------------------------------------------------------------
# Wave 40: Profit Target Shift Tests
# ---------------------------------------------------------------------

def test_wave40_initial_state():
    pts = ProfitTargetShift()
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0
    info = pts.info()
    assert info["mode"] == "NORMAL"
    assert info["tp_factor"] == 1.0
    assert info["tighten_threshold_usd"] == 150.0
    assert info["loosen_threshold_usd"] == -100.0


def test_wave40_invalid_inputs():
    pts = ProfitTargetShift()
    # Invalid base TP
    for invalid_tp in [None, True, False, -10.0, 0.0, float("inf")]:
        assert pts.adjust_tp(invalid_tp, 50.0) == invalid_tp

    # Check NaN specifically since nan != nan
    res_nan = pts.adjust_tp(float("nan"), 50.0)
    assert math.isnan(res_nan)

    # Invalid daily PnL defaults to 0.0 (NORMAL mode)
    for invalid_pnl in [None, True, False, "100", float("nan"), float("inf")]:
        adjusted = pts.adjust_tp(20.0, invalid_pnl)
        assert adjusted == 20.0
        assert pts.mode == "NORMAL"


def test_wave40_profit_tighten():
    pts = ProfitTargetShift()
    # Daily PnL at +160 (> +150 threshold)
    adjusted = pts.adjust_tp(20.0, 160.0)
    assert adjusted == 16.0  # 20.0 * 0.80
    assert pts.mode == "PROFIT_LOCK"
    assert pts.tp_factor == 0.80

    info = pts.info()
    assert info["mode"] == "PROFIT_LOCK"
    assert info["tp_factor"] == 0.80


def test_wave40_loss_loosen():
    pts = ProfitTargetShift()
    # Daily PnL at -150 (< -100 threshold)
    adjusted = pts.adjust_tp(20.0, -150.0)
    assert adjusted == 22.0  # 20.0 * 1.10
    assert pts.mode == "RECOVERY"
    assert pts.tp_factor == 1.10

    info = pts.info()
    assert info["mode"] == "RECOVERY"
    assert info["tp_factor"] == 1.10


def test_wave40_reset_and_module_aliases():
    pts = ProfitTargetShift()
    pts.adjust_tp(20.0, 200.0)
    assert pts.mode == "PROFIT_LOCK"

    pts.reset()
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0

    # Module-level aliases
    w40_reset()
    assert w40_get_mode() == "NORMAL"
    assert w40_get_tp_factor() == 1.0
    assert w40_adjust_tp(25.0, 180.0) == 20.0  # 25.0 * 0.80
    assert w40_get_mode() == "PROFIT_LOCK"
    w40_reset()
    assert w40_get_mode() == "NORMAL"


# ---------------------------------------------------------------------
# Wave 41: Session Spread Limiter Tests
# ---------------------------------------------------------------------

def test_wave41_initial_state():
    ssl = SessionSpreadLimiter()
    info = ssl.info()
    assert info["limit_pips"] == 3.0
    assert info["blocked_count_total"] == 0
    assert info["invalid_count"] == 0


def test_wave41_invalid_spreads():
    ssl = SessionSpreadLimiter()
    invalid_spreads = [None, True, False, -1.0, 0.0, float("nan"), float("inf"), "high"]
    for s in invalid_spreads:
        assert ssl.is_entry_blocked(s)
        assert ssl.is_blocked(s)

    info = ssl.info()
    assert info["invalid_count"] == len(invalid_spreads) * 2
    assert info["blocked_count_total"] == len(invalid_spreads) * 2


def test_wave41_session_resolution():
    ssl = SessionSpreadLimiter()
    # 1. Tokyo session (03:30 UTC): limit = 1.5 pips
    dt_tokyo = datetime(2026, 10, 18, 3, 30, tzinfo=timezone.utc)
    assert not ssl.is_entry_blocked(1.4, now_dt=dt_tokyo)
    assert ssl.is_entry_blocked(1.6, now_dt=dt_tokyo)
    assert ssl.info()["session"] == "tokyo"
    assert ssl.info()["limit_pips"] == 1.5

    # 2. London Pre-open (06:45 UTC): limit = 2.0 pips
    dt_london_pre = datetime(2026, 10, 18, 6, 45, tzinfo=timezone.utc)
    assert not ssl.is_entry_blocked(1.9, now_dt=dt_london_pre)
    assert ssl.is_entry_blocked(2.1, now_dt=dt_london_pre)
    assert ssl.info()["session"] == "london_pre"
    assert ssl.info()["limit_pips"] == 2.0

    # 3. Default/NY session (14:15 UTC): limit = 3.0 pips
    dt_ny = datetime(2026, 10, 18, 14, 15, tzinfo=timezone.utc)
    assert not ssl.is_entry_blocked(2.8, now_dt=dt_ny)
    assert ssl.is_entry_blocked(3.2, now_dt=dt_ny)
    assert ssl.info()["session"] == "default"
    assert ssl.info()["limit_pips"] == 3.0


def test_wave41_custom_and_update_limits():
    # Constructor custom limits
    custom_ssl = SessionSpreadLimiter({"tokyo": 1.2, "default": 2.5})
    dt_tokyo = datetime(2026, 10, 18, 2, 0, tzinfo=timezone.utc)
    assert not custom_ssl.is_entry_blocked(1.1, now_dt=dt_tokyo)
    assert custom_ssl.is_entry_blocked(1.3, now_dt=dt_tokyo)

    # Dynamic limit updating
    custom_ssl.update_limits({"tokyo": 1.8})
    assert not custom_ssl.is_entry_blocked(1.7, now_dt=dt_tokyo)
    assert custom_ssl.is_entry_blocked(1.9, now_dt=dt_tokyo)


def test_wave41_reset_and_module_aliases():
    ssl = SessionSpreadLimiter()
    dt = datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc)
    ssl.is_entry_blocked(2.5, now_dt=dt)  # Blocked in Tokyo
    assert ssl.info()["blocked_count_total"] == 1

    ssl.reset()
    assert ssl.info()["blocked_count_total"] == 0

    # Module-level aliases
    w41_reset()
    assert not w41_is_entry_blocked(1.0, now_dt=dt)
    assert w41_is_blocked(2.5, now_dt=dt)
    w41_update_limits({"tokyo": 3.0})
    assert not w41_is_blocked(2.5, now_dt=dt)
    w41_update_limits({"tokyo": 1.5})
    w41_reset()
