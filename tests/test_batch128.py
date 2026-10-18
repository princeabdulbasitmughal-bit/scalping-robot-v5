import pytest
import math
from datetime import datetime, timezone
from wave22_equity_curve_halt import EquityCurveHalt, equity_curve_halt, is_entry_blocked as w22_is_entry_blocked, is_blocked as w22_is_blocked, is_trading_allowed as w22_is_trading_allowed
from wave23_spread_optimizer import SpreadOptimizer, spread_optimizer, is_entry_blocked as w23_is_entry_blocked, is_blocked as w23_is_blocked, is_spread_ok as w23_is_spread_ok


class TestBatch128:
    """Batch 128 Test Suite: wave22 Equity Curve Halt & wave23 Spread Optimizer."""

    def test_wave22_risk_guard_aliases(self):
        eq = EquityCurveHalt(window=5, loss_threshold_usd=-50.0, slope_threshold=-10.0)
        assert eq.is_blocked(current_balance=1000.0) is False
        assert eq.is_entry_blocked(current_balance=1000.0) is False

        # If balance not supplied, checks _halted flag
        assert eq.is_blocked() is False
        eq._halted = True
        assert eq.is_blocked() is True
        assert eq.is_entry_blocked() is True

        # Module-level aliases
        equity_curve_halt.reset()
        assert w22_is_blocked(current_balance=1000.0) is False
        assert w22_is_entry_blocked(current_balance=1000.0) is False
        allowed, reason = w22_is_trading_allowed(current_balance=1000.0)
        assert allowed is True

    def test_wave22_warming_up(self):
        eq = EquityCurveHalt(window=5)
        eq.record_trade(-20.0, won=False)
        eq.record_trade(-30.0, won=False)
        allowed, reason = eq.is_trading_allowed(current_balance=1000.0)
        assert allowed is True
        assert "warming up" in reason

    def test_wave22_halt_condition(self):
        eq = EquityCurveHalt(window=5, loss_threshold_usd=-100.0, slope_threshold=-15.0)
        # 5 consecutive losing trades of -$30 each -> sum = -$150, slope = -$30/trade
        for _ in range(5):
            eq.record_trade(-30.0, won=False)

        allowed, reason = eq.is_trading_allowed(current_balance=850.0, now_mono=1000.0)
        assert allowed is False
        assert "EQUITY CURVE HALT" in reason
        assert eq.is_blocked(current_balance=850.0, now_mono=1000.0) is True

    def test_wave22_recovery_via_win_streak(self):
        eq = EquityCurveHalt(window=5, loss_threshold_usd=-100.0, slope_threshold=-15.0, recovery_win_streak=2, cooldown_sec=600.0)
        for _ in range(5):
            eq.record_trade(-30.0, won=False)
        eq.is_trading_allowed(current_balance=850.0, now_mono=1000.0)
        assert eq._halted is True

        # 1 win is not enough
        eq.record_trade(15.0, won=True)
        allowed, _ = eq.is_trading_allowed(current_balance=865.0, now_mono=1010.0)
        assert allowed is False

        # 2nd win achieves recovery
        eq.record_trade(20.0, won=True)
        allowed, reason = eq.is_trading_allowed(current_balance=885.0, now_mono=1020.0)
        assert allowed is True
        assert "win streak" in reason
        assert eq._halted is False

    def test_wave22_recovery_via_cooldown(self):
        eq = EquityCurveHalt(window=5, loss_threshold_usd=-100.0, slope_threshold=-15.0, recovery_win_streak=2, cooldown_sec=300.0)
        for _ in range(5):
            eq.record_trade(-30.0, won=False)
        eq.is_trading_allowed(current_balance=850.0, now_mono=1000.0)
        assert eq._halted is True

        # At t = 1000 + 290s -> still halted
        allowed, _ = eq.is_trading_allowed(current_balance=850.0, now_mono=1290.0)
        assert allowed is False

        # At t = 1000 + 301s -> recovered via cooldown
        allowed, reason = eq.is_trading_allowed(current_balance=850.0, now_mono=1301.0)
        assert allowed is True
        assert "cooldown" in reason
        assert eq._halted is False

    def test_wave22_invalid_inputs_and_reset(self):
        eq = EquityCurveHalt()
        # Invalid balance
        assert eq.is_trading_allowed(None)[0] is False
        assert eq.is_trading_allowed(True)[0] is False
        assert eq.is_trading_allowed(float('nan'))[0] is False
        assert eq.is_trading_allowed(float('inf'))[0] is False

        # Record trade with invalid PnL ignored
        eq.record_trade(None, won=True)
        eq.record_trade(float('nan'), won=False)
        assert len(eq._pnl_history) == 0

        # Reset
        eq._halted = True
        eq._halt_count = 5
        eq.reset()
        assert eq._halted is False
        assert eq._halt_count == 0

    def test_wave23_risk_guard_aliases(self):
        so = SpreadOptimizer()
        # Spread 1.0 pip is acceptable in any session
        assert so.is_blocked(spread_pips=1.0) is False
        assert so.is_entry_blocked(spread_pips=1.0) is False

        # Excessive spread of 5.0 pips is blocked
        assert so.is_blocked(spread_pips=5.0) is True
        assert so.is_entry_blocked(spread_pips=5.0) is True

        # Module-level aliases
        spread_optimizer.reset()
        assert w23_is_blocked(spread_pips=1.0) is False
        assert w23_is_entry_blocked(spread_pips=1.0) is False
        assert w23_is_blocked(spread_pips=6.0) is True
        ok, _ = w23_is_spread_ok(1.0)
        assert ok is True

    def test_wave23_session_spread_thresholds(self):
        so = SpreadOptimizer()
        # Tokyo limit is 1.8 pips
        ok, _ = so.is_spread_ok(spread_pips=1.7, session_name="TOKYO")
        assert ok is True
        ok, reason = so.is_spread_ok(spread_pips=1.9, session_name="TOKYO")
        assert ok is False
        assert "TOKYO" in reason

        # London limit is 3.0 pips
        ok, _ = so.is_spread_ok(spread_pips=2.9, session_name="LONDON")
        assert ok is True
        ok, reason = so.is_spread_ok(spread_pips=3.1, session_name="LONDON")
        assert ok is False

        # LDN_NY overlap limit is 3.5 pips
        ok, _ = so.is_spread_ok(spread_pips=3.4, session_name="LDN_NY")
        assert ok is True
        ok, reason = so.is_spread_ok(spread_pips=3.6, session_name="LDN_NY")
        assert ok is False

    def test_wave23_volatility_adjustments(self):
        so = SpreadOptimizer()
        # London base limit = 3.0. With vol_index = 2.0 (high vol) -> limit = 3.0 * 1.2 = 3.6
        ok, _ = so.is_spread_ok(spread_pips=3.4, session_name="LONDON", vol_index=2.0)
        assert ok is True

        # With vol_index = 0.3 (calm/low vol) -> limit = 3.0 * 0.85 = 2.55
        ok, _ = so.is_spread_ok(spread_pips=2.5, session_name="LONDON", vol_index=0.3)
        assert ok is True
        ok, reason = so.is_spread_ok(spread_pips=2.7, session_name="LONDON", vol_index=0.3)
        assert ok is False

    def test_wave23_invalid_spreads_and_info(self):
        so = SpreadOptimizer()
        # Fail-closed rejection of invalid spread values
        assert so.is_spread_ok(None)[0] is False
        assert so.is_spread_ok(True)[0] is False
        assert so.is_spread_ok(-1.0)[0] is False
        assert so.is_spread_ok(float('nan'))[0] is False
        assert so.is_spread_ok(float('inf'))[0] is False

        # Telemetry info
        info = so.info()
        assert "accepted" in info
        assert "rejected" in info
        assert "limit_pips" in info
