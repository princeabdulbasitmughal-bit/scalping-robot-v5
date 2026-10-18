import pytest
import math
from wave36_spread_momentum import SpreadMomentumGuard, spread_momentum_guard, is_entry_blocked as w36_is_entry_blocked, is_blocked as w36_is_blocked, update as w36_update
from wave37_entry_cooldown import EntryCooldown, entry_cooldown, is_entry_blocked as w37_is_entry_blocked, is_blocked as w37_is_blocked, record_trade_close as w37_record_trade_close


class TestBatch135:
    """Batch 135 Test Suite: wave36 Spread Momentum & wave37 Entry Cooldown."""

    def test_wave36_risk_guard_aliases(self):
        smg = SpreadMomentumGuard()
        assert smg.is_blocked() is False
        assert smg.is_entry_blocked() is False

        # Module-level aliases
        spread_momentum_guard.reset()
        assert w36_is_blocked() is False
        assert w36_is_entry_blocked() is False

    def test_wave36_spread_spike_detection(self):
        smg = SpreadMomentumGuard()
        base_time = 1000.0
        # Establish baseline spread ~1.5 pips across 4 ticks
        for i in range(4):
            smg.update(1.5, now_ts=base_time + i)
        assert smg.is_blocked(now_ts=base_time + 4) is False

        # Sudden spread spike to 5.0 pips (ratio = 5.0 / 1.5 = 3.33x >= 3.0x threshold)
        smg.update(5.0, now_ts=base_time + 5)
        assert smg.is_blocked(now_ts=base_time + 6) is True
        assert smg.is_entry_blocked(now_ts=base_time + 6) is True
        assert smg.total_spikes_detected == 1

    def test_wave36_spread_calm_and_expiry(self):
        smg = SpreadMomentumGuard()
        base_time = 1000.0
        for i in range(4):
            smg.update(1.5, now_ts=base_time + i)

        # Mild increase to 2.5 pips (ratio = 2.5 / 1.5 = 1.67x < 3.0x) -> no block
        smg.update(2.5, now_ts=base_time + 5)
        assert smg.is_blocked(now_ts=base_time + 6) is False

        # Trigger spike at t=1010
        smg.update(6.0, now_ts=base_time + 10)
        assert smg.is_blocked(now_ts=base_time + 20) is True

        # Block lasts 60s (until t=1070)
        assert smg.is_blocked(now_ts=base_time + 69) is True
        assert smg.is_blocked(now_ts=base_time + 71) is False

    def test_wave36_invalid_spreads_and_reset(self):
        smg = SpreadMomentumGuard()
        smg.update(None)
        smg.update(True)
        smg.update(-1.5)
        smg.update(0.0)
        smg.update(float('nan'))
        smg.update(float('inf'))
        assert len(smg._spread_history) == 0

        smg.update(1.5)
        assert len(smg._spread_history) == 1
        smg.reset()
        assert len(smg._spread_history) == 0
        assert smg.total_spikes_detected == 0

    def test_wave36_info_telemetry(self):
        smg = SpreadMomentumGuard()
        base_time = 1000.0
        for _ in range(4):
            smg.update(1.0, now_ts=base_time)
        smg.update(4.0, now_ts=base_time + 2)

        info = smg.info(now_ts=base_time + 12)
        assert info["currently_blocked"] is True
        assert info["seconds_remaining"] == 50.0
        assert info["spike_ratio_threshold"] == 3.0

    def test_wave37_risk_guard_aliases(self):
        ec = EntryCooldown()
        assert ec.is_blocked() is False
        assert ec.is_entry_blocked() is False

        # Module-level aliases
        entry_cooldown.reset()
        assert w37_is_blocked() is False
        assert w37_is_entry_blocked() is False

    def test_wave37_win_cooldown(self):
        ec = EntryCooldown()
        base_time = 1000.0
        # Winning trade closes at t=1000 -> 60s cooldown
        ec.record_trade_close(was_win=True, pnl=25.0, now_ts=base_time)
        assert ec.is_blocked(now_ts=base_time + 30) is True
        assert ec.is_entry_blocked(now_ts=base_time + 30) is True
        assert ec.seconds_remaining(now_ts=base_time + 30) == 30.0

        # After 61s -> expired
        assert ec.is_blocked(now_ts=base_time + 61) is False
        assert ec.total_win_cooldowns == 1

    def test_wave37_loss_cooldown_revenge_protection(self):
        ec = EntryCooldown()
        base_time = 1000.0
        # Losing trade closes at t=1000 -> 120s cooldown
        ec.record_trade_close(was_win=False, pnl=-35.0, now_ts=base_time)
        assert ec.is_blocked(now_ts=base_time + 90) is True
        assert ec.seconds_remaining(now_ts=base_time + 90) == 30.0

        # After 121s -> expired
        assert ec.is_blocked(now_ts=base_time + 121) is False
        assert ec.total_loss_cooldowns == 1

    def test_wave37_cooldown_monotonicity_max_rule(self):
        ec = EntryCooldown()
        base_time = 1000.0
        # Loss sets cooldown to 1000 + 120 = 1120
        ec.record_trade_close(was_win=False, pnl=-20.0, now_ts=base_time)
        assert ec._cooldown_until == 1120.0

        # Win at t=1010 would set 1010 + 60 = 1070 -> must NOT shorten active 1120 deadline
        ec.record_trade_close(was_win=True, pnl=10.0, now_ts=base_time + 10)
        assert ec._cooldown_until == 1120.0

    def test_wave37_force_reset_and_reset(self):
        ec = EntryCooldown()
        ec.record_trade_close(was_win=False, pnl=-50.0, now_ts=1000.0)
        assert ec.is_blocked(now_ts=1050.0) is True

        # Force reset clears active lockout
        ec.force_reset()
        assert ec.is_blocked(now_ts=1050.0) is False
        assert ec.total_cooldowns_triggered == 1

        # Full reset clears counters too
        ec.reset()
        assert ec.total_cooldowns_triggered == 0
        assert ec.last_trade_result == "NONE"
