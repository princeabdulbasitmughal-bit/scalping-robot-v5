import math
import time
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from wave23_spread_optimizer import SpreadOptimizer
from wave24_daily_profit_lock import DailyProfitLock
from wave30_session_lot_booster import SessionLotBooster
from wave35_overnight_guard import OvernightGuard
from wave36_spread_momentum import SpreadMomentumGuard
from wave40_profit_target_shift import ProfitTargetShift
from wave41_session_spread_limiter import SessionSpreadLimiter
from run_backtest import bb_signal
from python_engine.live_runner import ScalpingLiveRunner
from swarm_30_scalping_engine import ScalpingSwarm30


class TestBatch18Hardening:
    def test_run_backtest_bb_signal_guards(self):
        # Period <= 0
        assert bb_signal([2400.0] * 10, 5, period=0) == 'HOLD'
        assert bb_signal([2400.0] * 10, 5, period=-5) == 'HOLD'
        # Out of bounds
        assert bb_signal([], 0, period=20) == 'HOLD'
        assert bb_signal([2400.0] * 5, 10, period=20) == 'HOLD'

    def test_live_runner_memory_bounding(self):
        runner = ScalpingLiveRunner()
        # Simulate closing 1200 trades
        for i in range(1200):
            runner.trades_history.append({"id": i, "pnl": 10.0 if i % 2 == 0 else -5.0})
            runner.total_trades_count += 1
            if i % 2 == 0:
                runner.winning_trades_count += 1
            if len(runner.trades_history) > 1000:
                runner.trades_history = runner.trades_history[-1000:]

        assert len(runner.trades_history) == 1000
        assert runner.total_trades_count == 1200
        assert runner.winning_trades_count == 600

    def test_wave23_nan_and_lock(self):
        opt = SpreadOptimizer()
        ok, reason = opt.is_spread_ok(float('nan'))
        assert ok is False
        assert "invalid spread" in reason

        ok, reason = opt.is_spread_ok(-1.0)
        assert ok is False

        ok, reason = opt.is_spread_ok(1.5, session_name="TOKYO", vol_index=float('nan'))
        assert ok is True
        info = opt.info()
        assert info["accepted"] == 1

    def test_wave24_nan_and_lock(self):
        lock = DailyProfitLock(profit_target_usd=100.0)
        lock.update(float('nan'))
        assert lock.is_active is False
        lock.update(150.0)
        assert lock.is_active is True
        assert lock.apply_lot(0.05) == 0.01
        res = lock.apply_lot(float('nan'))
        assert math.isnan(res)
        lock.reset()
        assert lock.is_active is False

    def test_wave30_midnight_wrap_and_nan(self):
        # Wrap around midnight: 22:00 to 02:00
        booster = SessionLotBooster(overlap_start_utc=22, overlap_end_utc=2)
        with patch("wave30_session_lot_booster.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            assert booster._in_overlap() is True
            mock_dt.now.return_value.hour = 1
            assert booster._in_overlap() is True
            mock_dt.now.return_value.hour = 12
            assert booster._in_overlap() is False

        assert math.isnan(booster.apply_boost(float('nan')))
        assert booster.apply_boost(0.0) == 0.0

    def test_wave35_transition_counters(self):
        og = OvernightGuard()
        with patch.object(og, "_utc_now") as mock_now:
            # Friday 21:00 UTC (blocked)
            mock_dt = MagicMock()
            mock_dt.weekday.return_value = 4
            mock_dt.hour = 21
            mock_dt.minute = 0
            mock_now.return_value = mock_dt

            # Call multiple times during the block
            assert og.is_entry_blocked() is True
            assert og.is_entry_blocked() is True
            assert og.is_entry_blocked() is True
            # total_weekend_blocks should increment only once on transition!
            assert og.total_weekend_blocks == 1

    def test_wave36_spike_block_extension(self):
        guard = SpreadMomentumGuard()
        guard.update(1.0)
        guard.update(1.0)
        guard.update(1.0)
        # 4x spike
        guard.update(4.0)
        assert guard.is_entry_blocked() is True
        assert guard.total_spikes_detected == 1

        # Second spike during existing block extends block
        guard.update(5.0)
        assert guard.is_entry_blocked() is True
        assert guard.total_spikes_detected == 1

    def test_wave40_profit_target_shift_guards(self):
        shift = ProfitTargetShift()
        assert shift.adjust_tp(0.0, 50.0) == 0.0
        assert shift.adjust_tp(15.0, float('nan')) == 15.0
        assert shift.adjust_tp(15.0, 200.0) == 12.0  # 80% of 15
        assert shift.adjust_tp(15.0, -150.0) == 16.5  # 110% of 15

    def test_wave41_nan_spread_blocked(self):
        limiter = SessionSpreadLimiter()
        assert limiter.is_entry_blocked(float('nan')) is True
        assert limiter.is_entry_blocked(-1.0) is True

    def test_swarm_30_resilience(self, tmp_path):
        swarm = ScalpingSwarm30()
        swarm.root = tmp_path
        # Agent 3 without live_status.json
        res3 = swarm._execute_agent(3)
        assert "Telemetry Heartbeat Age" in res3["metric"]
        # Agent 30 without backups dir
        res30 = swarm._execute_agent(30)
        assert "0 backups preserved" in res30["metric"]
