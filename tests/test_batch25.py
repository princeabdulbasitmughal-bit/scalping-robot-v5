"""
Unit tests for Batch 25: Wave Modules Hardening
Covers:
- wave40_profit_target_shift
- wave41_session_spread_limiter
- wave42_tick_volume_filter
- wave43_win_rate_guard
- wave45_london_open_booster
- wave46_lot_recovery_ladder
- wave56_consecutive_loss_guard
- wave57_hourly_pnl_map
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from wave40_profit_target_shift import ProfitTargetShift
from wave41_session_spread_limiter import SessionSpreadLimiter
from wave42_tick_volume_filter import TickVolumeFilter
from wave43_win_rate_guard import WinRateGuard
from wave45_london_open_booster import LondonOpenBooster
from wave46_lot_recovery_ladder import LotRecoveryLadder
from wave56_consecutive_loss_guard import ConsecutiveLossGuard
from wave57_hourly_pnl_map import HourlyPnLMap


# ==============================================================================
# Wave 40: ProfitTargetShift
# ==============================================================================
def test_wave40_profit_target_shift():
    pts = ProfitTargetShift()
    
    # 1. Normal mode (PnL = 0) -> 1.0x
    assert pts.adjust_tp(15.0, 0.0) == 15.0
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0
    
    # 2. Profit Lock mode (PnL >= +$150) -> 0.8x
    assert pts.adjust_tp(15.0, 160.0) == 12.0
    assert pts.mode == "PROFIT_LOCK"
    assert pts.tp_factor == 0.80
    
    # 3. Recovery mode (PnL <= -$100) -> 1.1x
    assert pts.adjust_tp(15.0, -150.0) == 16.5
    assert pts.mode == "RECOVERY"
    assert pts.tp_factor == 1.10
    
    # 4. Invalid raw_tp guards
    assert pts.adjust_tp(0.0, 50.0) == 0.0
    assert pts.adjust_tp(None, 50.0) is None
    assert math.isnan(pts.adjust_tp(float("nan"), 50.0))
    
    # 5. Reset method
    pts.reset()
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0
    
    # 6. Info dictionary schema
    info = pts.info()
    assert info["wave"] == 40
    assert info["name"] == "ProfitTargetShift"
    assert "tp_factor" in info


# ==============================================================================
# Wave 41: SessionSpreadLimiter
# ==============================================================================
def test_wave41_session_spread_limiter():
    ssl = SessionSpreadLimiter()
    
    # Tokyo hours: 03:00 UTC (limit 1.5)
    tokyo_dt = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(1.2, now_dt=tokyo_dt) is False
    assert ssl.is_entry_blocked(1.8, now_dt=tokyo_dt) is True
    
    # London pre-open: 06:30 UTC (limit 2.0)
    pre_london_dt = datetime(2026, 10, 17, 6, 30, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(1.9, now_dt=pre_london_dt) is False
    assert ssl.is_entry_blocked(2.2, now_dt=pre_london_dt) is True
    
    # Default hours: 14:00 UTC (limit 3.0)
    ny_dt = datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(2.8, now_dt=ny_dt) is False
    assert ssl.is_entry_blocked(3.5, now_dt=ny_dt) is True
    
    # Invalid spread inputs must be blocked
    assert ssl.is_entry_blocked(0.0, now_dt=ny_dt) is True
    assert ssl.is_entry_blocked(-1.0, now_dt=ny_dt) is True
    assert ssl.is_entry_blocked(float("nan"), now_dt=ny_dt) is True
    assert ssl.is_entry_blocked(None, now_dt=ny_dt) is True
    
    # Reset & Info
    ssl.reset()
    info = ssl.info()
    assert info["wave"] == 41
    assert info["blocked_count_total"] == 0


# ==============================================================================
# Wave 42: TickVolumeFilter
# ==============================================================================
def test_wave42_tick_volume_filter():
    tvf = TickVolumeFilter(window_sec=5.0, min_ticks=3)
    
    # Insufficient ticks -> blocked (dead market)
    t0 = 1000.0
    tvf.update(now_ts=t0)
    assert tvf.is_entry_blocked(now_ts=t0) is True
    
    # Enough ticks (3 ticks in window) -> unblocked
    tvf.update(now_ts=t0 + 1.0)
    tvf.update(now_ts=t0 + 2.0)
    assert tvf.is_entry_blocked(now_ts=t0 + 2.0) is False
    
    # Absolute ceiling (exceeding max_ticks) -> blocked
    for i in range(60):
        tvf.update(now_ts=t0 + 2.1 + (i * 0.01))
    assert tvf.is_entry_blocked(now_ts=t0 + 3.0) is True
    
    # Reset method
    tvf.reset()
    assert tvf.info()["blocked_count_total"] == 0


# ==============================================================================
# Wave 43: WinRateGuard
# ==============================================================================
def test_wave43_win_rate_guard():
    wrg = WinRateGuard(min_trades=5, min_win_rate=0.40, pause_seconds=300.0)
    
    # Below min_trades -> never blocked
    t0 = 2000.0
    for _ in range(4):
        wrg.record_trade(False, now_ts=t0)
    assert wrg.is_entry_blocked(now_ts=t0) is False
    
    # 5th trade loss -> 0 wins out of 5 (win rate 0.0 < 0.40) -> blocked
    wrg.record_trade(False, now_ts=t0)
    assert wrg.is_entry_blocked(now_ts=t0) is True
    
    # After pause expires -> unblocked and stale streak pruned
    assert wrg.is_entry_blocked(now_ts=t0 + 301.0) is False
    
    # Reset
    wrg.reset()
    assert wrg.info()["sample_size"] == 0


# ==============================================================================
# Wave 45: LondonOpenBooster
# ==============================================================================
def test_wave45_london_open_booster():
    lob = LondonOpenBooster(score_discount=0.20)
    
    # London open: 07:30 UTC -> discount 0.20
    london_open_dt = datetime(2026, 10, 17, 7, 30, tzinfo=timezone.utc)
    assert lob.is_active(now_dt=london_open_dt) is True
    assert lob.adjust_min_score(10.0, now_dt=london_open_dt) == 8.0
    
    # Outside window: 11:00 UTC -> discount 0.0
    outside_dt = datetime(2026, 10, 17, 11, 0, tzinfo=timezone.utc)
    assert lob.is_active(now_dt=outside_dt) is False
    assert lob.adjust_min_score(10.0, now_dt=outside_dt) == 10.0
    
    # Clamping discount between 0.0 and 0.50
    lob_extreme = LondonOpenBooster(score_discount=0.99)
    assert lob_extreme._discount == 0.50


# ==============================================================================
# Wave 46: LotRecoveryLadder
# ==============================================================================
def test_wave46_lot_recovery_ladder():
    lrl = LotRecoveryLadder(base_lot=0.02, min_lot=0.01, max_lot=0.10, consecutive_trigger=1)
    
    # Initial lot
    assert lrl.get_lot() == 0.02
    
    # Consecutive losses increase step multiplier
    lrl.record_trade(False)
    assert lrl.get_lot() > 0.02
    
    # Win resets back to base lot
    lrl.record_trade(True)
    assert lrl.get_lot() == 0.02
    
    # Clamping to max_lot
    lrl_max = LotRecoveryLadder(base_lot=0.08, max_lot=0.08, consecutive_trigger=1)
    for _ in range(10):
        lrl_max.record_trade(False)
    assert lrl_max.get_lot() <= 0.08
    
    # Reset method
    lrl.reset()
    assert lrl.get_lot() == 0.02


# ==============================================================================
# Wave 56: ConsecutiveLossGuard
# ==============================================================================
def test_wave56_consecutive_loss_guard():
    clg = ConsecutiveLossGuard(max_losses=3, pause_seconds=1800.0)
    t0 = 5000.0
    
    # 2 consecutive losses -> not blocked
    clg.record_trade(False, now_ts=t0)
    clg.record_trade(False, now_ts=t0 + 10.0)
    assert clg.is_entry_blocked(now_ts=t0 + 10.0) is False
    
    # 3rd consecutive loss at t0 + 20.0 -> blocked for 30 minutes (1800s)
    clg.record_trade(False, now_ts=t0 + 20.0)
    assert clg.is_entry_blocked(now_ts=t0 + 20.0) is True
    assert clg.is_entry_blocked(now_ts=t0 + 1000.0) is True
    
    # Pause expired at t0 + 20.0 + 1801.0 -> unblocked and streak cleared
    assert clg.is_entry_blocked(now_ts=t0 + 20.0 + 1801.0) is False
    
    # Winning trade resets loss streak
    clg.record_trade(False, now_ts=t0 + 2000.0)
    assert clg.info(now_ts=t0 + 2000.0)["consecutive_losses"] == 1
    clg.record_trade(True, now_ts=t0 + 2010.0)
    assert clg.info(now_ts=t0 + 2010.0)["consecutive_losses"] == 0
    
    # Reset
    clg.reset()
    assert clg.info()["consecutive_losses"] == 0


# ==============================================================================
# Wave 57: HourlyPnLMap
# ==============================================================================
def test_wave57_hourly_pnl_map():
    hpm = HourlyPnLMap(loss_threshold_usd=-30.0)
    dt1 = datetime(2026, 10, 17, 14, 15, tzinfo=timezone.utc)
    
    # Normal hour PnL -> lot multiplier 1.0
    hpm.record_trade(-10.0, now_dt=dt1)
    assert hpm.get_lot_multiplier(now_dt=dt1) == 1.0
    
    # Bad hour PnL (-$40 total < -$30 threshold) -> lot multiplier 0.5
    hpm.record_trade(-30.0, now_dt=dt1)
    assert hpm.get_lot_multiplier(now_dt=dt1) == 0.5
    
    # Different hour (hour 15) -> unaffected (lot multiplier 1.0)
    dt_other_hour = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
    assert hpm.get_lot_multiplier(now_dt=dt_other_hour) == 1.0
    
    # Next day UTC rollover -> hour 14 reset back to 0.0 PnL (lot multiplier 1.0)
    dt_next_day = datetime(2026, 10, 18, 14, 15, tzinfo=timezone.utc)
    assert hpm.get_lot_multiplier(now_dt=dt_next_day) == 1.0
    
    # Reset method
    hpm.reset()
    info = hpm.info(now_dt=dt1)
    assert info["wave"] == 57
    assert info["total_trades_recorded"] == 0
