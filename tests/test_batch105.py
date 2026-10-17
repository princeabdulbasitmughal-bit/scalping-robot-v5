"""
tests/test_batch105.py
Batch 105 Unit Tests: Equity Curve Halt (wave22) & Spread Optimizer (wave23).
Expands test baseline beyond 1,287+ passing tests to 1,297+ passing tests across 105 test suites!
Verifies:
1. wave22: EquityCurveHalt initialization defaults, thresholds, and boolean parameter protection.
2. wave22: Warmup phase clearance when trade history buffer is below window size.
3. wave22: Halt trigger activation on deep negative drawdown slope (loss < -150 USD, slope < -10 USD/trade).
4. wave22: Resumption clearance via consecutive winning trade recovery streak (2 wins).
5. wave22: Resumption clearance via cooldown expiration (300s), fail-closed balance validation, and info() telemetry.
6. wave23: SpreadOptimizer initialization defaults and telemetry counters.
7. wave23: Session detection and session-specific spread limits (Tokyo 1.8p, London 3.0p, LDN/NY 3.5p, NY 2.5p).
8. wave23: Spread gating acceptance within limits and rejection on excessive spread.
9. wave23: Dynamic volatility adjustment scaling limits wider in fast markets and tighter in low-vol regimes.
10. wave23: Fail-closed input handling on boolean/invalid spreads, reset(), and info() telemetry.
"""

from datetime import datetime, timezone
import math
import pytest

from wave22_equity_curve_halt import EquityCurveHalt
from wave23_spread_optimizer import SpreadOptimizer


def test_wave22_equity_curve_halt_initialization_defaults():
    """Verify EquityCurveHalt initializes with standard defaults and guards boolean inputs."""
    ech = EquityCurveHalt()
    assert ech._window == 10
    assert ech._loss_threshold == -150.0
    assert ech._slope_threshold == -10.0
    assert ech._recovery_win_streak == 2
    assert ech._cooldown_sec == 300.0
    assert ech._halted is False
    assert ech._halt_count == 0

    # Custom bounded initialization
    ech_custom = EquityCurveHalt(
        window=15,
        loss_threshold_usd=-200.0,
        slope_threshold=-15.0,
        recovery_win_streak=3,
        cooldown_sec=600.0,
    )
    assert ech_custom._window == 15
    assert ech_custom._loss_threshold == -200.0
    assert ech_custom._slope_threshold == -15.0
    assert ech_custom._recovery_win_streak == 3
    assert ech_custom._cooldown_sec == 600.0

    # Boolean parameter rejection
    ech_bool = EquityCurveHalt(
        window=True,
        loss_threshold_usd=False,
        slope_threshold=True,
        recovery_win_streak=False,
        cooldown_sec=True,
    )
    assert ech_bool._window == 10
    assert ech_bool._loss_threshold == -150.0
    assert ech_bool._slope_threshold == -10.0
    assert ech_bool._recovery_win_streak == 2
    assert ech_bool._cooldown_sec == 300.0


def test_wave22_equity_curve_halt_warmup_clearance():
    """Verify trade history below window capacity allows trading during warmup."""
    ech = EquityCurveHalt(window=10)

    # Empty buffer -> allowed
    allowed, reason = ech.is_trading_allowed(current_balance=10000.0)
    assert allowed is True
    assert "warming up 0/10" in reason

    # 5 trades -> allowed
    for _ in range(5):
        ech.record_trade(-20.0, won=False)

    allowed, reason = ech.is_trading_allowed(current_balance=9900.0)
    assert allowed is True
    assert "warming up 5/10" in reason


def test_wave22_equity_curve_halt_activation_on_accelerating_drawdown():
    """Verify deep negative drawdown slope (< -150 USD and slope < -10 USD/trade) activates halt."""
    ech = EquityCurveHalt(window=10, loss_threshold_usd=-150.0, slope_threshold=-10.0)
    t0 = 1000.0

    # Feed 10 losing trades of -$20 each: sum = -$200, slope = -$20/trade
    for _ in range(10):
        ech.record_trade(-20.0, won=False)

    allowed, reason = ech.is_trading_allowed(current_balance=9800.0, now_mono=t0)
    assert allowed is False
    assert "EQUITY CURVE HALT #1" in reason
    assert "window_sum=$-200.00" in reason
    assert "slope=$-20.00/trade" in reason
    assert ech._halted is True
    assert ech._halt_count == 1
    assert ech._halt_balance == 9800.0


def test_wave22_equity_curve_halt_recovery_via_win_streak():
    """Verify achieving recovery_win_streak (2 consecutive wins) clears the halt."""
    ech = EquityCurveHalt(window=10, loss_threshold_usd=-150.0, slope_threshold=-10.0, recovery_win_streak=2)
    t0 = 2000.0

    # Trip halt
    for _ in range(10):
        ech.record_trade(-20.0, won=False)
    ech.is_trading_allowed(current_balance=9800.0, now_mono=t0)
    assert ech._halted is True

    # 1st win -> still halted (need 2 wins)
    ech.record_trade(15.0, won=True)
    allowed, reason = ech.is_trading_allowed(current_balance=9815.0, now_mono=t0 + 10.0)
    assert allowed is False
    assert "wins_needed=1" in reason

    # 2nd win -> recovered!
    ech.record_trade(15.0, won=True)
    allowed, reason = ech.is_trading_allowed(current_balance=9830.0, now_mono=t0 + 20.0)
    assert allowed is True
    assert "eq_halt recovered (win streak=2)" in reason
    assert ech._halted is False


def test_wave22_equity_curve_halt_recovery_via_cooldown_and_fail_closed():
    """Verify cooldown timer restores trading, invalid balance fails closed, and reset flushes state."""
    ech = EquityCurveHalt(window=10, cooldown_sec=300.0)
    t0 = 3000.0

    # Trip halt
    for _ in range(10):
        ech.record_trade(-20.0, won=False)
    ech.is_trading_allowed(current_balance=9800.0, now_mono=t0)
    assert ech._halted is True

    # At t0 + 200s -> still halted
    allowed, reason = ech.is_trading_allowed(current_balance=9800.0, now_mono=t0 + 200.0)
    assert allowed is False
    assert "wait 1.7min" in reason

    # At t0 + 301s -> recovered via cooldown
    allowed, reason = ech.is_trading_allowed(current_balance=9800.0, now_mono=t0 + 301.0)
    assert allowed is True
    assert "cooldown 5.0min" in reason

    # Fail closed on non-finite balance
    assert ech.is_trading_allowed(None)[0] is False
    assert ech.is_trading_allowed(True)[0] is False
    assert ech.is_trading_allowed(float("nan"))[0] is False

    # Telemetry and Reset
    info = ech.info()
    assert info["halted"] is False
    assert info["halt_count"] == 1

    ech.reset()
    assert ech._halt_count == 0
    assert len(ech._pnl_history) == 0


def test_wave23_spread_optimizer_initialization_defaults():
    """Verify SpreadOptimizer initializes with default counters and limits."""
    so = SpreadOptimizer()
    assert so._rejected_count == 0
    assert so._accepted_count == 0
    assert so._last_limit == 2.5
    assert so._last_session == "OFF"


def test_wave23_spread_optimizer_session_detection():
    """Verify UTC hour correctly maps to standard trading sessions."""
    so = SpreadOptimizer()

    # Tokyo: 04:00 UTC
    dt_tokyo = datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)
    assert so._detect_session(dt_tokyo) == "TOKYO"

    # London: 09:00 UTC
    dt_london = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
    assert so._detect_session(dt_london) == "LONDON"

    # London/NY Overlap: 14:00 UTC
    dt_overlap = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)
    assert so._detect_session(dt_overlap) == "LDN_NY"

    # New York: 19:00 UTC
    dt_ny = datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)
    assert so._detect_session(dt_ny) == "NEW_YORK"


def test_wave23_spread_optimizer_spread_evaluation_accept_and_reject():
    """Verify spread gating checks against session thresholds."""
    so = SpreadOptimizer()
    dt_tokyo = datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)  # Tokyo limit = 1.8p

    # Spread 1.5p <= 1.8p -> Accepted
    ok, reason = so.is_spread_ok(1.5, now_dt=dt_tokyo)
    assert ok is True
    assert "spread ok [TOKYO]: 1.50pip <= 1.80pip" in reason
    assert so._accepted_count == 1

    # Spread 2.2p > 1.8p -> Rejected
    ok, reason = so.is_spread_ok(2.2, now_dt=dt_tokyo)
    assert ok is False
    assert "SPREAD REJECT [TOKYO]: 2.20pip > limit 1.80pip" in reason
    assert so._rejected_count == 1


def test_wave23_spread_optimizer_volatility_scaling():
    """Verify session spread limit scales with market volatility index."""
    so = SpreadOptimizer()
    dt_london = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)  # London base limit = 3.0p

    # High volatility (vol_index=1.6 >= 1.5): limit expanded by 1.2x = 3.60p
    # Spread of 3.4p (normally > 3.0p) is accepted!
    ok, reason = so.is_spread_ok(3.4, vol_index=1.6, now_dt=dt_london)
    assert ok is True
    assert "3.40pip <= 3.60pip" in reason

    # Low volatility (vol_index=0.4 <= 0.5): limit tightened by 0.85x = 2.55p
    # Spread of 2.8p (normally <= 3.0p) is rejected!
    ok, reason = so.is_spread_ok(2.8, vol_index=0.4, now_dt=dt_london)
    assert ok is False
    assert "2.80pip > limit 2.55pip" in reason


def test_wave23_spread_optimizer_fail_closed_inputs_reset_and_telemetry():
    """Verify invalid spreads fail closed, reset flushes state, and telemetry reports accurately."""
    so = SpreadOptimizer()

    # Invalid spreads rejected
    assert so.is_spread_ok(None)[0] is False
    assert so.is_spread_ok(True)[0] is False
    assert so.is_spread_ok(float("nan"))[0] is False
    assert so.is_spread_ok(-1.5)[0] is False

    # Perform valid evaluation
    so.is_spread_ok(2.0, session_name="LONDON")
    info = so.info()
    assert info["last_spread_pips"] == 2.0
    assert info["session"] == "LONDON"
    assert info["limit_pips"] == 3.0
    assert info["accepted"] == 1

    # Reset
    so.reset()
    info_reset = so.info()
    assert info_reset["accepted"] == 0
    assert info_reset["rejected"] == 0
    assert info_reset["last_spread_pips"] == 0.0
