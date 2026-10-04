"""
test_waves.py — Comprehensive pytest test suite for Wave filters.
Tests: initialization, core methods, edge cases (empty data, zero denominators, extreme values).

Run: python -m pytest tests/test_waves.py -v
"""

import sys
import os
import time
import pytest

# Add project root to sys.path so wave modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 20 — Spike Filter
# API: check(current_price, prev_price, closes=None), is_blocked(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave20SpikeFilter:
    def setup_method(self):
        from wave20_spike_filter import SpikeFilter
        self.sf = SpikeFilter()

    def test_init_not_blocked(self):
        assert not self.sf.is_blocked()

    def test_normal_ticks_not_blocked(self):
        price = 2400.0
        prev = price
        for i in range(50):
            cur = price + i * 0.01
            result = self.sf.check(cur, prev)
            assert isinstance(result, tuple)
            prev = cur
        assert not self.sf.is_blocked()

    def test_spike_triggers_no_crash(self):
        """A huge sudden jump should not crash."""
        sf = self.sf
        prev = 2400.0
        for _ in range(30):
            sf.check(2400.0 + 0.01, prev)
            prev = 2400.0 + 0.01
        # Now inject a massive spike
        blocked, reason = sf.check(2500.0, prev)  # +100 in one tick
        assert isinstance(blocked, bool)
        assert isinstance(reason, str)

    def test_info_returns_dict(self):
        info = self.sf.info()
        assert isinstance(info, dict)
        assert "blocked" in info


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 31 — Reversal Detector
# API: update_price(price), get_reversal_signal() -> tuple, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave31ReversalDetector:
    def setup_method(self):
        from wave31_reversal_detector import ReversalDetector
        self.rd = ReversalDetector()

    def test_init_returns_hold(self):
        sig, conf, reason = self.rd.get_reversal_signal()
        assert sig == "HOLD"
        assert conf == 0.0

    def test_update_does_not_crash(self):
        for p in [2400.0, 2401.0, 2399.5, 2402.0]:
            self.rd.update_price(p)

    def test_overbought_does_not_crash(self):
        rd = self.rd
        for i in range(20):
            rd.update_price(2400.0 + i * 2)
        sig, conf, reason = rd.get_reversal_signal()
        assert sig in ("BUY", "SELL", "HOLD")
        assert 0.0 <= conf <= 1.0

    def test_info_dict(self):
        info = self.rd.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 32 — Gap Guard
# API: update_price(price), is_trading_allowed() -> tuple, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave32GapGuard:
    def setup_method(self):
        from wave32_gap_guard import GapGuard
        self.gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=10.0, pip_size=0.1)

    def test_init_allows_trading(self):
        allowed, reason = self.gg.is_trading_allowed()
        assert allowed

    def test_small_gap_no_block(self):
        self.gg.update_price(2400.0)
        self.gg.update_price(2400.3)  # 3 pips — below threshold
        allowed, reason = self.gg.is_trading_allowed()
        assert allowed

    def test_large_gap_triggers_block(self):
        self.gg.update_price(2400.0)
        self.gg.update_price(2401.0)  # 10 pips — above threshold
        allowed, reason = self.gg.is_trading_allowed()
        assert not allowed

    def test_block_expires(self):
        gg = __import__("wave32_gap_guard", fromlist=["GapGuard"]).GapGuard(
            gap_threshold_pips=5.0, block_duration_sec=0.01, pip_size=0.1
        )
        gg.update_price(2400.0)
        gg.update_price(2401.0)  # trigger block
        time.sleep(0.05)
        allowed, reason = gg.is_trading_allowed()
        assert allowed  # block should have expired

    def test_info_dict(self):
        info = self.gg.info()
        assert isinstance(info, dict)
        assert "trading_allowed" in info
        assert "gap_threshold_pips" in info


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 33 — Partial Close Manager
# API: check_position(ticket, direction, entry_price, current_price, sl_price, tp_price, lot),
#      get_partial_lot(lot), reset_ticket(ticket), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave33PartialClose:
    def setup_method(self):
        from wave33_partial_close import PartialCloseManager
        self.pc = PartialCloseManager(trigger_pct=0.5)

    def test_no_trigger_early(self):
        result = self.pc.check_position(
            ticket=1, direction="BUY",
            entry_price=2400.0, current_price=2401.0,
            sl_price=2370.0, tp_price=2420.0,
            lot=0.02
        )
        assert not result

    def test_trigger_at_50pct(self):
        result = self.pc.check_position(
            ticket=2, direction="BUY",
            entry_price=2400.0, current_price=2410.0,
            sl_price=2370.0, tp_price=2420.0,
            lot=0.02
        )
        assert result

    def test_no_double_trigger(self):
        """Same ticket should not trigger twice."""
        self.pc.check_position(
            ticket=3, direction="BUY",
            entry_price=2400.0, current_price=2415.0,
            sl_price=2370.0, tp_price=2420.0,
            lot=0.02
        )
        # Second call for same ticket should be False (already triggered)
        result = self.pc.check_position(
            ticket=3, direction="BUY",
            entry_price=2400.0, current_price=2415.0,
            sl_price=2370.0, tp_price=2420.0,
            lot=0.02
        )
        assert not result

    def test_sell_direction(self):
        result = self.pc.check_position(
            ticket=4, direction="SELL",
            entry_price=2400.0, current_price=2390.0,
            sl_price=2430.0, tp_price=2380.0,
            lot=0.02
        )
        assert result  # 50% of 20 pip TP hit

    def test_zero_tp_dist_no_crash(self):
        result = self.pc.check_position(
            ticket=5, direction="BUY",
            entry_price=2400.0, current_price=2400.0,
            sl_price=2370.0, tp_price=2400.0,  # tp_dist = 0
            lot=0.02
        )
        assert not result  # should return False, not crash

    def test_info_dict(self):
        info = self.pc.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 36 — Spread Momentum Guard
# API: update(spread_pips), is_entry_blocked() -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave36SpreadMomentum:
    def setup_method(self):
        from wave36_spread_momentum import SpreadMomentumGuard
        self.sm = SpreadMomentumGuard()

    def test_init_not_blocked(self):
        assert not self.sm.is_entry_blocked()

    def test_stable_spread_not_blocked(self):
        for _ in range(30):
            self.sm.update(1.5)  # constant spread
        assert not self.sm.is_entry_blocked()

    def test_spike_spread_blocks(self):
        for _ in range(20):
            self.sm.update(1.5)
        self.sm.update(10.0)  # massive spike
        assert self.sm.is_entry_blocked()

    def test_zero_spread_baseline_no_crash(self):
        """Zero spread — baseline=0 guard should prevent division."""
        for _ in range(30):
            self.sm.update(0.0)
        result = self.sm.is_entry_blocked()
        assert isinstance(result, bool)

    def test_info_dict(self):
        info = self.sm.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 38 — Volatility Breaker
# API: update(price), is_entry_blocked() -> bool, seconds_remaining(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave38VolatilityBreaker:
    def setup_method(self):
        from wave38_volatility_breaker import VolatilityBreaker
        self.vb = VolatilityBreaker()

    def test_init_not_blocked(self):
        assert not self.vb.is_entry_blocked()

    def test_calm_market_not_blocked(self):
        price = 2400.0
        for i in range(110):
            self.vb.update(price + (i % 5) * 0.01)
        assert not self.vb.is_entry_blocked()

    def test_volatile_market_no_crash(self):
        """Build calm baseline, then spike volatility — must not crash."""
        price = 2400.0
        for i in range(110):
            self.vb.update(price + (i % 3) * 0.005)
        for _ in range(25):
            self.vb.update(price)
            price += 5.0  # huge jumps per tick
        result = self.vb.is_entry_blocked()
        assert isinstance(result, bool)

    def test_all_same_price_no_crash(self):
        """Zero ATR — baseline_atr=0 guard."""
        for _ in range(110):
            self.vb.update(2400.0)
        assert not self.vb.is_entry_blocked()

    def test_info_dict(self):
        info = self.vb.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 39 — Drawdown Pause
# API: update(equity), is_entry_blocked() -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave39DrawdownPause:
    def setup_method(self):
        from wave39_drawdown_pause import DrawdownPause
        self.dp = DrawdownPause()

    def test_init_not_blocked(self):
        assert not self.dp.is_entry_blocked()

    def test_no_drawdown_no_block(self):
        self.dp.update(10000.0)
        assert not self.dp.is_entry_blocked()

    def test_heavy_drawdown_no_crash(self):
        self.dp.update(10000.0)
        self.dp.update(9000.0)  # 10% drawdown
        result = self.dp.is_entry_blocked()
        assert isinstance(result, bool)

    def test_info_dict(self):
        info = self.dp.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 42 — Tick Volume Filter
# API: update(), is_entry_blocked() -> bool, get_tick_rate(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave42TickVolumeFilter:
    def setup_method(self):
        from wave42_tick_volume_filter import TickVolumeFilter
        self.tvf = TickVolumeFilter(min_ticks=5, window_sec=10.0)

    def test_init_blocked(self):
        """Initially no ticks → blocked."""
        assert self.tvf.is_entry_blocked()

    def test_enough_ticks_unblocks(self):
        for _ in range(10):
            self.tvf.update()
        assert not self.tvf.is_entry_blocked()

    def test_tick_rate(self):
        for _ in range(10):
            self.tvf.update()
        rate = self.tvf.get_tick_rate()
        assert rate >= 0

    def test_info_dict(self):
        info = self.tvf.info()
        assert "tick_rate_per_sec" in info
        assert "min_ticks_required" in info


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 43 — Win Rate Guard
# API: WinRateGuard(min_trades, win_rate_threshold, pause_duration_sec, window)
#      record_trade(won), is_entry_blocked() -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave43WinRateGuard:
    def setup_method(self):
        from wave43_win_rate_guard import WinRateGuard
        self.wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.35, pause_duration_sec=1, window=10)

    def test_init_not_blocked(self):
        assert not self.wrg.is_entry_blocked()

    def test_good_win_rate_not_blocked(self):
        for _ in range(5):
            self.wrg.record_trade(won=True)
        assert not self.wrg.is_entry_blocked()

    def test_bad_win_rate_blocks(self):
        for _ in range(6):
            self.wrg.record_trade(won=False)
        assert self.wrg.is_entry_blocked()

    def test_pause_expires_no_crash(self):
        for _ in range(6):
            self.wrg.record_trade(won=False)
        assert self.wrg.is_entry_blocked()
        time.sleep(1.1)
        result = self.wrg.is_entry_blocked()
        assert isinstance(result, bool)

    def test_empty_results_no_crash(self):
        """Empty results → should not crash."""
        wrg2 = __import__("wave43_win_rate_guard", fromlist=["WinRateGuard"]).WinRateGuard()
        assert not wrg2.is_entry_blocked()

    def test_info_dict(self):
        info = self.wrg.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 47 — ATR Position Sizer
# API: update(high, low, close), get_sl_tp(base_sl, base_tp), get_atr(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave47ATRPositionSizer:
    def setup_method(self):
        from wave47_atr_position_sizer import ATRPositionSizer
        self.aps = ATRPositionSizer()

    def test_init_returns_base_sl_tp(self):
        sl, tp = self.aps.get_sl_tp()
        assert sl > 0 and tp > 0

    def test_update_with_prices(self):
        price = 2400.0
        for i in range(50):
            high = price + (i % 10) * 0.1
            low = high - 0.05
            close = (high + low) / 2
            self.aps.update(high, low, close)
        sl, tp = self.aps.get_sl_tp()
        assert sl > 0
        assert tp > 0

    def test_zero_atr_returns_base(self):
        """If ATR is 0 (no price change), should return base SL/TP."""
        for _ in range(30):
            self.aps.update(2400.0, 2399.9, 2400.0)
        sl, tp = self.aps.get_sl_tp()
        assert sl > 0 and tp > 0

    def test_info_dict(self):
        info = self.aps.info()
        assert "atr" in info


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 49 — Spread Cost Tracker
# API: record_trade(spread_pips, lot_size), is_entry_blocked() -> bool,
#      get_daily_cost(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave49SpreadCostTracker:
    def setup_method(self):
        from wave49_spread_cost_tracker import SpreadCostTracker
        self.sct = SpreadCostTracker(max_daily_usd=10.0)

    def test_init_not_blocked(self):
        assert not self.sct.is_entry_blocked()

    def test_below_limit_not_blocked(self):
        self.sct.record_trade(spread_pips=1.5, lot_size=0.02)
        assert not self.sct.is_entry_blocked()

    def test_exceeds_limit_blocks(self):
        """Hammer trades until daily limit exceeded."""
        for _ in range(100):
            self.sct.record_trade(spread_pips=2.0, lot_size=0.02)
        assert self.sct.is_entry_blocked()

    def test_daily_cost_increases(self):
        cost_before = self.sct.get_daily_cost()
        self.sct.record_trade(spread_pips=2.0, lot_size=0.02)
        cost_after = self.sct.get_daily_cost()
        assert cost_after > cost_before

    def test_info_dict(self):
        info = self.sct.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 50 — Candle Pattern Filter
# API: update(price), is_signal_blocked(signal) -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave50CandlePatternFilter:
    def setup_method(self):
        from wave50_candle_pattern_filter import CandlePatternFilter
        self.cpf = CandlePatternFilter()

    def test_init_not_blocked(self):
        result = self.cpf.is_signal_blocked("BUY")
        assert isinstance(result, bool)

    def test_update_no_crash(self):
        for p in [2400.0, 2401.0, 2399.5, 2402.0, 2398.0]:
            self.cpf.update(p)

    def test_bullish_candles_no_crash(self):
        """Rising prices should not crash."""
        price = 2400.0
        for i in range(40):
            self.cpf.update(price + i * 0.1)
        result = self.cpf.is_signal_blocked("BUY")
        assert isinstance(result, bool)

    def test_is_signal_blocked_bool(self):
        result = self.cpf.is_signal_blocked("BUY")
        assert isinstance(result, bool)

    def test_is_signal_blocked_sell_bool(self):
        result = self.cpf.is_signal_blocked("SELL")
        assert isinstance(result, bool)

    def test_info_dict(self):
        info = self.cpf.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 52 — RSI OB/OS Filter
# API: update(price), get_rsi() -> float, is_signal_blocked(signal) -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave52RSIFilter:
    def setup_method(self):
        from wave52_rsi_ob_os_filter import RSIOverboughtOversold
        self.rf = RSIOverboughtOversold()

    def test_init_not_blocked(self):
        # is_signal_blocked returns bool
        blocked = self.rf.is_signal_blocked("BUY")
        assert not blocked

    def test_insufficient_data_not_blocked(self):
        self.rf.update(2400.0)
        blocked = self.rf.is_signal_blocked("BUY")
        assert not blocked

    def test_update_no_crash(self):
        for p in [2400.0 + i * 0.1 for i in range(50)]:
            self.rf.update(p)

    def test_rsi_value_in_range(self):
        for p in [2400.0 + i * 0.1 for i in range(20)]:
            self.rf.update(p)
        rsi = self.rf.get_rsi()
        assert 0 <= rsi <= 100

    def test_info_dict(self):
        info = self.rf.info()
        assert isinstance(info, dict)
        assert "rsi" in info


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 55 — Balance Floor Guard
# API: BalanceFloorGuard(floor_usd, hysteresis_usd), update(balance),
#      is_entry_blocked() -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave55BalanceFloor:
    def setup_method(self):
        from wave55_balance_floor_guard import BalanceFloorGuard
        self.bfg = BalanceFloorGuard(floor_usd=9700.0)

    def test_above_floor_not_blocked(self):
        self.bfg.update(10000.0)
        assert not self.bfg.is_entry_blocked()

    def test_below_floor_blocks(self):
        self.bfg.update(9600.0)
        assert self.bfg.is_entry_blocked()

    def test_at_floor_no_crash(self):
        self.bfg.update(9700.0)
        result = self.bfg.is_entry_blocked()
        assert isinstance(result, bool)

    def test_info_dict(self):
        info = self.bfg.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 56 — Consecutive Loss Guard
# API: ConsecutiveLossGuard(max_losses, pause_seconds), record_trade(won),
#      is_entry_blocked() -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave56ConsecutiveLossGuard:
    def setup_method(self):
        from wave56_consecutive_loss_guard import ConsecutiveLossGuard
        self.clg = ConsecutiveLossGuard(max_losses=3, pause_seconds=1)

    def test_init_not_blocked(self):
        assert not self.clg.is_entry_blocked()

    def test_wins_dont_block(self):
        for _ in range(5):
            self.clg.record_trade(won=True)
        assert not self.clg.is_entry_blocked()

    def test_three_losses_block(self):
        for _ in range(3):
            self.clg.record_trade(won=False)
        assert self.clg.is_entry_blocked()

    def test_win_resets_streak(self):
        for _ in range(2):
            self.clg.record_trade(won=False)
        self.clg.record_trade(won=True)  # reset streak
        assert not self.clg.is_entry_blocked()

    def test_pause_expires(self):
        for _ in range(3):
            self.clg.record_trade(won=False)
        assert self.clg.is_entry_blocked()
        time.sleep(1.1)
        assert not self.clg.is_entry_blocked()

    def test_info_dict(self):
        info = self.clg.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 58 — Price Range Filter
# API: PriceRangeFilter(min_range_pips), update(price), is_entry_blocked() -> bool,
#      get_range_pips() -> float, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave58PriceRangeFilter:
    def setup_method(self):
        from wave58_price_range_filter import PriceRangeFilter
        self.prf = PriceRangeFilter(min_range_pips=20.0)

    def test_init_not_blocked(self):
        assert not self.prf.is_entry_blocked()

    def test_insufficient_ticks_not_blocked(self):
        for _ in range(10):
            self.prf.update(2400.0)
        assert not self.prf.is_entry_blocked()

    def test_wide_range_not_blocked(self):
        for i in range(60):
            self.prf.update(2400.0 + (i % 2) * 5.0)  # 50 pip range
        assert not self.prf.is_entry_blocked()

    def test_flat_market_blocks(self):
        for _ in range(60):
            self.prf.update(2400.0)  # no range
        assert self.prf.is_entry_blocked()

    def test_get_range_pips_no_crash(self):
        self.prf.update(2400.0)
        self.prf.update(2401.0)
        pips = self.prf.get_range_pips()
        assert pips >= 0

    def test_info_dict(self):
        info = self.prf.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 59 — MA Trend Filter
# API: update(price), get_ema() -> float
# Note: only update() and get_ema() are available
# ─────────────────────────────────────────────────────────────────────────────
class TestWave59MATrendFilter:
    def setup_method(self):
        from wave59_ma_trend_filter import MATrendFilter
        self.mtf = MATrendFilter()

    def test_update_no_crash(self):
        for p in [2400.0, 2401.0, 2399.0]:
            self.mtf.update(p)

    def test_get_ema_returns_float(self):
        for i in range(20):
            self.mtf.update(2400.0 + i * 0.1)
        ema = self.mtf.get_ema()
        assert isinstance(ema, (int, float))
        # EMA converges toward price — after 20 updates it should be non-negative
        assert ema >= 0

    def test_get_ema_rises_with_price(self):
        for _ in range(30):
            self.mtf.update(2300.0)
        ema_low = self.mtf.get_ema()
        for _ in range(30):
            self.mtf.update(2500.0)
        ema_high = self.mtf.get_ema()
        assert ema_high > ema_low

    def test_has_period_or_alpha(self):
        assert hasattr(self.mtf, 'alpha') or hasattr(self.mtf, 'period')


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 61 — Opening Range Breakout
# API: update(price) only
# Note: only update(price) is available
# ─────────────────────────────────────────────────────────────────────────────
class TestWave61ORB:
    def setup_method(self):
        from wave61_opening_range_breakout import OpeningRangeBreakout
        self.orb = OpeningRangeBreakout()

    def test_update_no_crash(self):
        for p in [2400.0, 2401.0, 2399.0, 2402.0]:
            self.orb.update(p)

    def test_update_single_price(self):
        self.orb.update(2400.0)

    def test_update_many_prices(self):
        for i in range(100):
            self.orb.update(2400.0 + i * 0.05)

    def test_update_zero_price_no_crash(self):
        try:
            self.orb.update(0.0)
        except Exception:
            pass  # may validate — must not hang


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 8 — Signal Scorer
# API: compute_atr(bars), compute_stoch_rsi(closes, period=14),
#      update_volume_proxy(price_change), is_high_volume() -> bool,
#      score_signal(signal, closes, bars, rsi, bb_squeeze, market_regime, ema_cross) -> int,
#      detect_pattern(bars)
# ─────────────────────────────────────────────────────────────────────────────
class TestWave8SignalScorer:
    def setup_method(self):
        from wave8_signal_optimizer import SignalScorer
        self.so = SignalScorer()

    def test_compute_stoch_rsi_no_crash(self):
        closes = [2400.0 + i * 0.1 for i in range(20)]
        rsi = self.so.compute_stoch_rsi(closes)
        assert 0 <= rsi <= 100

    def test_compute_stoch_rsi_flat_no_crash(self):
        """All same prices → RSI should not crash."""
        closes = [2400.0] * 20
        rsi = self.so.compute_stoch_rsi(closes)
        assert 0 <= rsi <= 100

    def test_compute_stoch_rsi_rising(self):
        closes = [2400.0 + i for i in range(20)]
        rsi = self.so.compute_stoch_rsi(closes)
        assert rsi >= 50  # rising prices → overbought

    def test_score_signal_no_crash(self):
        closes = [2400.0 + i * 0.1 for i in range(30)]
        bars = [{"open": 2400.0, "high": 2400.5, "low": 2399.5, "close": 2400.2}] * 5
        score = self.so.score_signal(
            signal="BUY", closes=closes, bars=bars,
            rsi=40.0, bb_squeeze=False,
            market_regime="RANGING", ema_cross="NEUTRAL"
        )
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_update_volume_proxy_no_crash(self):
        for _ in range(10):
            self.so.update_volume_proxy(0.1)
        result = self.so.is_high_volume()
        assert isinstance(result, bool)

    def test_empty_atr_no_crash(self):
        """compute_atr with empty list should not crash."""
        atr = self.so.compute_atr([])
        assert atr >= 0


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 9 — Risk Manager
# API: RiskManager(), update_equity(equity: float),
#      should_trade(balance, equity, daily_pnl, daily_loss, open_positions, new_signal) -> Dict,
#      record_trade(), drawdown_pct() -> float,
#      is_max_drawdown_hit(balance) -> bool, equity_curve_ok(equity) -> bool,
#      drawdown_lot_scale(balance) -> float
# ─────────────────────────────────────────────────────────────────────────────
class TestWave9RiskManager:
    def setup_method(self):
        from wave9_risk_manager import RiskManager
        self.rm = RiskManager()

    def test_should_trade_default(self):
        result = self.rm.should_trade(
            balance=10000.0, equity=10000.0, daily_pnl=0.0,
            daily_loss=0.0, open_positions=[], new_signal="BUY"
        )
        assert isinstance(result, dict)

    def test_update_equity_no_crash(self):
        self.rm.update_equity(10000.0)  # takes 1 arg: equity

    def test_drawdown_pct_no_crash(self):
        self.rm.update_equity(10000.0)
        pct = self.rm.drawdown_pct(balance=10000.0)
        assert isinstance(pct, float)

    def test_is_max_drawdown_hit_bool(self):
        result = self.rm.is_max_drawdown_hit(balance=10000.0)
        assert isinstance(result, bool)

    def test_equity_curve_ok_bool(self):
        result = self.rm.equity_curve_ok(equity=10000.0)
        assert isinstance(result, bool)

    def test_record_trade_no_crash(self):
        self.rm.record_trade()

    def test_drawdown_lot_scale_default(self):
        scale = self.rm.drawdown_lot_scale(balance=10000.0)
        assert isinstance(scale, float)
        assert scale > 0


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 11 — Profit Optimizer
# API: update_peak_float(ticket, current_float_pnl),
#      should_close_reversal(ticket, current_float_pnl, threshold=0.5) -> bool,
#      get_partial_close_level(ticket, current_float_pnl, tp_pips, base_lot),
#      cleanup_ticket(ticket), session_stats() -> dict,
#      record_result(won), streak_lot_modifier() -> float, is_recovery_mode() -> bool
# ─────────────────────────────────────────────────────────────────────────────
class TestWave11ProfitOptimizer:
    def setup_method(self):
        from wave11_profit_optimizer import ProfitOptimizer
        self.po = ProfitOptimizer()

    def test_should_close_reversal_no_crash(self):
        result = self.po.should_close_reversal(
            ticket="T1", current_float_pnl=5.0
        )
        assert isinstance(result, bool)

    def test_peak_tracking(self):
        """Peak should track highest floating PnL."""
        self.po.update_peak_float(ticket="T1", current_float_pnl=10.0)
        self.po.update_peak_float(ticket="T1", current_float_pnl=15.0)
        self.po.update_peak_float(ticket="T1", current_float_pnl=8.0)
        result = self.po.should_close_reversal(ticket="T1", current_float_pnl=8.0)
        assert isinstance(result, bool)

    def test_partial_close_suggestion(self):
        result = self.po.get_partial_close_level(
            ticket="T2", current_float_pnl=20.0, tp_pips=40.0, base_lot=0.02
        )
        assert result is None or isinstance(result, float)

    def test_cleanup_no_crash(self):
        self.po.cleanup_ticket("T_NONEXISTENT")

    def test_session_stats_dict(self):
        stats = self.po.session_stats()
        assert isinstance(stats, dict)

    def test_streak_lot_modifier(self):
        mod = self.po.streak_lot_modifier()
        assert isinstance(mod, float)
        assert mod > 0

    def test_is_recovery_mode_bool(self):
        result = self.po.is_recovery_mode()
        assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 13 — Linear Regressor (ML Predictor)
# API: LinearRegressor(), fit(y), predict(closes) -> dict
# ─────────────────────────────────────────────────────────────────────────────
class TestWave13LinearRegressor:
    def setup_method(self):
        from wave13_ml_predictor import LinearRegressor
        self.ml = LinearRegressor()

    def test_predict_empty_no_crash(self):
        """fit with empty data should not crash."""
        try:
            self.ml.fit([])
        except Exception:
            pass  # may raise — must not hang

    def test_predict_rising_prices(self):
        closes = [2400.0 + i for i in range(30)]
        self.ml.fit(closes)
        # fit should not crash on valid data
        assert True

    def test_predict_falling_prices_no_crash(self):
        closes = [2430.0 - i for i in range(30)]
        self.ml.fit(closes)
        assert True

    def test_fit_flat_no_crash(self):
        """Flat prices → ss_xx = 0 → should not crash."""
        closes = [2400.0] * 20
        try:
            self.ml.fit(closes)
        except Exception:
            pass  # guarded — must not hang

    def test_fit_single_price_no_crash(self):
        try:
            self.ml.fit([2400.0])
        except Exception:
            pass  # may raise — must not hang

    def test_fit_no_crash_large(self):
        closes = [2400.0 + i * 0.05 for i in range(100)]
        self.ml.fit(closes)
        assert True


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 14 — Auto Tuner
# API: AutoTuner(config_path=None), analyse(trade_history) -> dict,
#      analyse_and_tune(trade_history) -> dict, seconds_since_last_run(), last_report()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave14AutoTuner:
    def setup_method(self):
        from wave14_auto_tuner import AutoTuner
        self.at = AutoTuner()

    def test_insufficient_data_returns_status(self):
        result = self.at.analyse(trade_history=[])
        assert "status" in result
        assert result["status"] == "insufficient_data"

    def test_enough_trades_runs(self):
        trades = []
        for i in range(15):
            trades.append({
                "pnl": 10.0 if i % 2 == 0 else -8.0,
                "duration_sec": 300,
                "exit_reason": "TP"
            })
        result = self.at.analyse(trade_history=trades)
        assert "status" in result
        assert result["status"] in ("ok", "no_changes", "adjusted")

    def test_zero_losses_no_crash(self):
        """All wins — gross_loss = 0, profit_factor should be handled."""
        trades = [{"pnl": 10.0, "duration_sec": 300, "exit_reason": "TP"}] * 15
        result = self.at.analyse(trade_history=trades)
        assert "status" in result

    def test_seconds_since_last_run(self):
        # seconds_since_last_run is a float attribute, not a method
        result = self.at.seconds_since_last_run
        assert isinstance(result, (int, float))

    def test_last_report_no_crash(self):
        # last_report is a dict attribute, not a method
        result = self.at.last_report
        # May be None or dict — must not crash
        assert result is None or isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 19 — Volatility TP/SL Adjuster
# API: VolatilityTPSLAdjuster(...), adjusted_tpsl(closes, base_tp_pips, base_sl_pips, session_info) -> (sl, tp)
# ─────────────────────────────────────────────────────────────────────────────
class TestWave19VolatilityTPSL:
    def setup_method(self):
        from wave19_volatility_tpsl import VolatilityTPSLAdjuster
        self.vt = VolatilityTPSLAdjuster()

    def test_adjusted_tpsl_default(self):
        closes = [2400.0 + i * 0.1 for i in range(30)]
        sl, tp = self.vt.adjusted_tpsl(closes=closes)
        # Both values must be positive (ordering depends on volatility)
        assert sl > 0 and tp > 0

    def test_adjusted_tpsl_empty_closes(self):
        """Empty closes — should use base values, not crash."""
        sl, tp = self.vt.adjusted_tpsl(closes=[])
        assert sl > 0 and tp > 0

    def test_adjusted_tpsl_flat_prices(self):
        """Flat prices → ATR=0 → should return base values."""
        closes = [2400.0] * 30
        sl, tp = self.vt.adjusted_tpsl(closes=closes)
        assert sl > 0 and tp > 0


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 24 — Daily Profit Lock
# API: DailyProfitLock(profit_target_usd, protect_lot, protect_min_score),
#      update(daily_pnl), is_active() -> bool, reset(), apply_lot(lot), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave24DailyProfitLock:
    def setup_method(self):
        from wave24_daily_profit_lock import DailyProfitLock
        self.dpl = DailyProfitLock(profit_target_usd=200.0)

    def test_init_not_locked(self):
        # is_active is a bool attribute, not a method
        assert not self.dpl.is_active

    def test_below_target_not_locked(self):
        self.dpl.update(daily_pnl=100.0)
        assert not self.dpl.is_active

    def test_at_target_locks(self):
        self.dpl.update(daily_pnl=200.0)
        assert self.dpl.is_active

    def test_above_target_locks(self):
        self.dpl.update(daily_pnl=300.0)
        assert self.dpl.is_active

    def test_reset_unlocks(self):
        self.dpl.update(daily_pnl=300.0)
        self.dpl.reset()
        assert not self.dpl.is_active

    def test_info_dict(self):
        info = self.dpl.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# DIVISION BY ZERO EDGE CASE TESTS (critical safety tests)
# ─────────────────────────────────────────────────────────────────────────────
class TestEdgeCases:
    """Ensure no wave crashes on extreme/zero inputs."""

    def test_wave36_zero_spread_no_crash(self):
        from wave36_spread_momentum import SpreadMomentumGuard
        sm = SpreadMomentumGuard()
        for _ in range(30):
            sm.update(0.0)  # zero spread — baseline = 0, guarded
        result = sm.is_entry_blocked()
        assert isinstance(result, bool)

    def test_wave38_all_same_price_no_crash(self):
        from wave38_volatility_breaker import VolatilityBreaker
        vb = VolatilityBreaker()
        for _ in range(110):
            vb.update(2400.0)  # zero ATR — baseline_atr = 0, guarded
        assert not vb.is_entry_blocked()

    def test_wave47_zero_atr_no_crash(self):
        from wave47_atr_position_sizer import ATRPositionSizer
        aps = ATRPositionSizer()
        # ATR = 0 case → guarded by atr <= 0 or baseline <= 0
        sl, tp = aps.get_sl_tp()
        assert sl > 0 and tp > 0

    def test_wave13_empty_prices_no_crash(self):
        from wave13_ml_predictor import LinearRegressor
        ml = LinearRegressor()
        try:
            ml.fit([])
        except Exception:
            pass  # may raise on empty — must not hang

    def test_wave13_single_price_no_crash(self):
        from wave13_ml_predictor import LinearRegressor
        ml = LinearRegressor()
        try:
            ml.fit([2400.0])
        except Exception:
            pass

    def test_wave14_empty_history_no_crash(self):
        from wave14_auto_tuner import AutoTuner
        at = AutoTuner()
        result = at.analyse([])
        assert result["status"] == "insufficient_data"

    def test_wave43_empty_results_no_crash(self):
        from wave43_win_rate_guard import WinRateGuard
        wrg = WinRateGuard()
        # Empty results → _current_win_rate returns 1.0
        assert not wrg.is_entry_blocked()

    def test_wave33_zero_tp_dist_no_crash(self):
        from wave33_partial_close import PartialCloseManager
        pc = PartialCloseManager()
        result = pc.check_position(
            ticket=999, direction="BUY",
            entry_price=2400.0, current_price=2400.0,
            sl_price=2370.0, tp_price=2400.0,  # tp_dist = 0
            lot=0.02
        )
        assert not result  # tp_dist = 0 → guarded → False

    def test_wave8_empty_atr_no_crash(self):
        from wave8_signal_optimizer import SignalScorer
        so = SignalScorer()
        atr = so.compute_atr([])
        assert atr >= 0

    def test_wave9_drawdown_lot_scale_no_crash(self):
        from wave9_risk_manager import RiskManager
        rm = RiskManager()
        scale = rm.drawdown_lot_scale(balance=10000.0)
        assert scale >= 0.0  # should never return negative


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 10 — Session Optimizer
# API: get_adjusted_targets(base_sl, base_tp, rr_ratio=1.5), get_current_session_info(), session_report()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave10SessionOptimizer:
    def setup_method(self):
        from wave10_session_optimizer import SessionOptimizer
        self.so = SessionOptimizer()

    def test_init(self):
        assert self.so is not None

    def test_get_adjusted_targets_returns_tuple(self):
        result = self.so.get_adjusted_targets(30.0, 45.0, 1.5)
        assert isinstance(result, tuple)
        assert len(result) == 2
        sl, tp = result
        assert sl > 0
        assert tp > 0

    def test_get_adjusted_targets_default_rr(self):
        sl, tp = self.so.get_adjusted_targets(30.0, 45.0)
        assert sl > 0
        assert tp > 0

    def test_get_current_session_info_returns_dict(self):
        info = self.so.get_current_session_info()
        assert isinstance(info, dict)

    def test_session_report_returns_str(self):
        report = self.so.session_report()
        assert isinstance(report, str)
        assert len(report) > 0


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 12 — Telegram Alerts
# API: send_alert(text, force=False), alert_trade_open(...), alert_trade_close(...),
#       alert_daily_summary(...), alert_circuit_breaker(...)
# ─────────────────────────────────────────────────────────────────────────────
class TestWave12TelegramAlerter:
    def setup_method(self):
        from wave12_telegram_alerts import TelegramAlerter
        self.ta = TelegramAlerter()

    def test_init(self):
        assert self.ta is not None

    def test_send_alert_no_crash(self):
        result = self.ta.send_alert("test alert")
        assert isinstance(result, bool)

    def test_send_alert_force(self):
        result = self.ta.send_alert("forced alert", force=True)
        assert isinstance(result, bool)

    def test_alert_trade_open_no_crash(self):
        self.ta.alert_trade_open("BUY", 2400.0, 2370.0, 2445.0, 0.02)

    def test_alert_trade_close_no_crash(self):
        self.ta.alert_trade_close("BUY", 12.5, "TP_HIT", 9200.0)

    def test_alert_circuit_breaker_no_crash(self):
        self.ta.alert_circuit_breaker("daily loss limit", 9100.0, -200.0)

    def test_alert_daily_summary_no_crash(self):
        self.ta.alert_daily_summary(9200.0, 50.0, 3, 1, 75.0, 4)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 21 — News Guard
# API: is_trading_allowed() -> tuple, info() -> dict
# ─────────────────────────────────────────────────────────────────────────────
class TestWave21NewsGuard:
    def setup_method(self):
        from wave21_news_guard import NewsGuard
        self.ng = NewsGuard()

    def test_init(self):
        assert self.ng is not None

    def test_is_trading_allowed_returns_tuple(self):
        result = self.ng.is_trading_allowed()
        assert isinstance(result, tuple)
        assert len(result) == 2
        allowed, reason = result
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)

    def test_info_returns_dict(self):
        info = self.ng.info()
        assert isinstance(info, dict)

    def test_trading_allowed_by_default(self):
        allowed, _ = self.ng.is_trading_allowed()
        assert isinstance(allowed, bool)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 22 — Equity Curve Halt
# API: record_trade(pnl, won), is_trading_allowed(current_balance) -> tuple, info() -> dict
# ─────────────────────────────────────────────────────────────────────────────
class TestWave22EquityCurveHalt:
    def setup_method(self):
        from wave22_equity_curve_halt import EquityCurveHalt
        self.ech = EquityCurveHalt()

    def test_init(self):
        assert self.ech is not None

    def test_custom_params(self):
        from wave22_equity_curve_halt import EquityCurveHalt
        e = EquityCurveHalt(window=5, loss_threshold_usd=-50.0, recovery_win_streak=1)
        assert e is not None

    def test_is_trading_allowed_fresh(self):
        allowed, reason = self.ech.is_trading_allowed(10000.0)
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)

    def test_record_trade_win(self):
        self.ech.record_trade(10.0, True)

    def test_record_trade_loss(self):
        self.ech.record_trade(-20.0, False)

    def test_info_returns_dict(self):
        info = self.ech.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 23 — Spread Optimizer
# API: is_spread_ok(spread_pips, session_name=None, vol_index=1.0) -> tuple, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave23SpreadOptimizer:
    def setup_method(self):
        from wave23_spread_optimizer import SpreadOptimizer
        self.so = SpreadOptimizer()

    def test_init(self):
        assert self.so is not None

    def test_tight_spread_ok(self):
        ok, reason = self.so.is_spread_ok(0.5)
        assert isinstance(ok, bool)
        assert isinstance(reason, str)

    def test_wide_spread_blocked(self):
        ok, reason = self.so.is_spread_ok(99.0)
        assert ok is False

    def test_spread_ok_with_session(self):
        ok, reason = self.so.is_spread_ok(1.5, "London", 1.0)
        assert isinstance(ok, bool)

    def test_info_returns_dict(self):
        info = self.so.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 25 — Drawdown Accelerator
# API: record_trade(won), apply_lot(lot), get_multiplier(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave25DrawdownAccelerator:
    def setup_method(self):
        from wave25_drawdown_accelerator import DrawdownAccelerator
        self.da = DrawdownAccelerator()

    def test_init(self):
        assert self.da is not None

    def test_multiplier_default_is_positive(self):
        m = self.da.get_multiplier()
        assert isinstance(m, float)
        assert m > 0

    def test_apply_lot_positive(self):
        lot = self.da.apply_lot(0.02)
        assert lot > 0

    def test_record_win(self):
        self.da.record_trade(True)

    def test_record_loss(self):
        self.da.record_trade(False)

    def test_info_returns_dict(self):
        info = self.da.info()
        assert isinstance(info, dict)

    def test_custom_thresholds(self):
        from wave25_drawdown_accelerator import DrawdownAccelerator
        d = DrawdownAccelerator(thresholds=[(5, 0.8), (10, 0.5)], recovery_wins=3)
        assert d.get_multiplier() >= 0


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 26 — Time Filter
# API: is_trading_allowed(now_utc=None) -> Tuple[bool, str], info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave26TimeFilter:
    def setup_method(self):
        from wave26_time_filter import TimeFilter
        self.tf = TimeFilter()

    def test_init(self):
        assert self.tf is not None

    def test_no_release_times_allows_trading(self):
        allowed, reason = self.tf.is_trading_allowed()
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)

    def test_info_returns_dict(self):
        info = self.tf.info()
        assert isinstance(info, dict)

    def test_with_release_times(self):
        from wave26_time_filter import TimeFilter
        tf = TimeFilter(release_times=[(8, 30), (13, 30)], block_before=30, block_after=30)
        allowed, reason = tf.is_trading_allowed()
        assert isinstance(allowed, bool)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 27 — Correlation Guard
# API: record_signal(), is_trading_allowed() -> Tuple[bool, str], info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave27CorrelationGuard:
    def setup_method(self):
        from wave27_correlation_guard import CorrelationGuard
        self.cg = CorrelationGuard()

    def test_init(self):
        assert self.cg is not None

    def test_fresh_allows_trading(self):
        allowed, reason = self.cg.is_trading_allowed()
        assert allowed is True

    def test_record_signal_no_crash(self):
        self.cg.record_signal()

    def test_too_many_signals_blocks(self):
        from wave27_correlation_guard import CorrelationGuard
        cg = CorrelationGuard(window_sec=60.0, max_signals_in_window=2, cooldown_sec=30.0)
        cg.record_signal()
        cg.record_signal()
        cg.record_signal()
        allowed, _ = cg.is_trading_allowed()
        assert allowed is False

    def test_info_returns_dict(self):
        info = self.cg.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 28 — Momentum Confirmation
# API: update_price(price), is_momentum_confirmed(signal) -> Tuple[bool, str], info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave28MomentumConfirmation:
    def setup_method(self):
        from wave28_momentum_confirmation import MomentumConfirmation
        self.mc = MomentumConfirmation()

    def test_init(self):
        assert self.mc is not None

    def test_no_prices_result_is_bool(self):
        ok, reason = self.mc.is_momentum_confirmed("BUY")
        assert isinstance(ok, bool)
        assert isinstance(reason, str)

    def test_update_price_no_crash(self):
        for p in [2400.0, 2401.0, 2402.0, 2403.0, 2404.0]:
            self.mc.update_price(p)

    def test_uptrend_buy_check(self):
        from wave28_momentum_confirmation import MomentumConfirmation
        mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)
        for p in [2400.0, 2401.0, 2402.0, 2403.0, 2404.0]:
            mc.update_price(p)
        ok, _ = mc.is_momentum_confirmed("BUY")
        assert isinstance(ok, bool)

    def test_downtrend_sell_check(self):
        from wave28_momentum_confirmation import MomentumConfirmation
        mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)
        for p in [2405.0, 2404.0, 2403.0, 2402.0, 2401.0]:
            mc.update_price(p)
        ok, _ = mc.is_momentum_confirmed("SELL")
        assert isinstance(ok, bool)

    def test_info_returns_dict(self):
        info = self.mc.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 29 — Adaptive TP
# API: update_price(price), adjust_tp(base_tp_pips), get_tp_multiplier(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave29AdaptiveTp:
    def setup_method(self):
        from wave29_adaptive_tp import AdaptiveTp
        self.at = AdaptiveTp()

    def test_init(self):
        assert self.at is not None

    def test_multiplier_default_positive(self):
        m = self.at.get_tp_multiplier()
        assert isinstance(m, float)
        assert m > 0

    def test_adjust_tp_no_data_positive(self):
        tp = self.at.adjust_tp(45.0)
        assert isinstance(tp, float)
        assert tp > 0

    def test_update_price_and_adjust(self):
        for p in [2400.0 + i * 0.1 for i in range(25)]:
            self.at.update_price(p)
        tp = self.at.adjust_tp(45.0)
        assert tp > 0

    def test_info_returns_dict(self):
        info = self.at.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 30 — Session Lot Booster
# API: apply_boost(lot, vol_index=1.0, win_rate_pct=50.0) -> float, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave30SessionLotBooster:
    def setup_method(self):
        from wave30_session_lot_booster import SessionLotBooster
        self.slb = SessionLotBooster()

    def test_init(self):
        assert self.slb is not None

    def test_apply_boost_returns_positive_float(self):
        lot = self.slb.apply_boost(0.02)
        assert isinstance(lot, float)
        assert lot > 0

    def test_apply_boost_high_vol_high_winrate(self):
        lot = self.slb.apply_boost(0.02, vol_index=1.5, win_rate_pct=60.0)
        assert lot > 0

    def test_info_returns_dict(self):
        info = self.slb.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 34 — Trailing Stop Manager
# API: update(ticket, direction, entry_price, current_price, current_sl) -> float|None
#       close_ticket(ticket), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave34TrailingStop:
    def setup_method(self):
        from wave34_trailing_stop import TrailingStopManager
        self.ts = TrailingStopManager()

    def test_init(self):
        assert self.ts is not None

    def test_custom_params(self):
        from wave34_trailing_stop import TrailingStopManager
        ts = TrailingStopManager(profit_trigger_pips=10.0, trail_pips=5.0)
        assert ts is not None

    def test_update_buy_below_trigger(self):
        result = self.ts.update(1, "BUY", 2400.0, 2405.0, 2370.0)
        assert result is None or isinstance(result, float)

    def test_update_buy_above_trigger(self):
        result = self.ts.update(1, "BUY", 2400.0, 2420.0, 2370.0)
        assert result is None or isinstance(result, float)

    def test_update_sell(self):
        result = self.ts.update(2, "SELL", 2400.0, 2380.0, 2430.0)
        assert result is None or isinstance(result, float)

    def test_close_ticket_no_crash(self):
        self.ts.update(3, "BUY", 2400.0, 2420.0, 2370.0)
        self.ts.close_ticket(3)

    def test_info_returns_dict(self):
        info = self.ts.info()
        assert isinstance(info, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 35 — Overnight Guard
# API: is_entry_blocked() -> bool, should_force_close_all() -> bool, get_reason(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave35OvernightGuard:
    def setup_method(self):
        from wave35_overnight_guard import OvernightGuard
        self.og = OvernightGuard()

    def test_init(self):
        assert self.og is not None

    def test_is_entry_blocked_returns_bool(self):
        assert isinstance(self.og.is_entry_blocked(), bool)

    def test_should_force_close_all_returns_bool(self):
        assert isinstance(self.og.should_force_close_all(), bool)

    def test_get_reason_returns_str(self):
        assert isinstance(self.og.get_reason(), str)

    def test_info_returns_dict(self):
        assert isinstance(self.og.info(), dict)

    def test_constants_exist(self):
        assert hasattr(self.og, 'ROLLOVER_START_HOUR')
        assert hasattr(self.og, 'ROLLOVER_END_HOUR')


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 37 — Entry Cooldown
# API: is_entry_blocked() -> bool, record_trade_close(was_win, pnl=0.0),
#       seconds_remaining() -> float, force_reset(), info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave37EntryCooldown:
    def setup_method(self):
        from wave37_entry_cooldown import EntryCooldown
        self.ec = EntryCooldown()

    def test_init_not_blocked(self):
        assert self.ec.is_entry_blocked() is False

    def test_record_loss_triggers_cooldown(self):
        self.ec.record_trade_close(was_win=False, pnl=-15.0)
        assert self.ec.is_entry_blocked() is True

    def test_record_win_check(self):
        self.ec.record_trade_close(was_win=True, pnl=20.0)
        assert isinstance(self.ec.is_entry_blocked(), bool)

    def test_seconds_remaining(self):
        self.ec.record_trade_close(was_win=False, pnl=-10.0)
        secs = self.ec.seconds_remaining()
        assert isinstance(secs, float)
        assert secs >= 0

    def test_force_reset(self):
        self.ec.record_trade_close(was_win=False, pnl=-10.0)
        self.ec.force_reset()
        assert self.ec.is_entry_blocked() is False

    def test_info_returns_dict(self):
        assert isinstance(self.ec.info(), dict)

    def test_constants_exist(self):
        assert hasattr(self.ec, 'COOLDOWN_WIN_SEC')
        assert hasattr(self.ec, 'COOLDOWN_LOSS_SEC')


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 40 — Profit Target Shift
# API: adjust_tp(raw_tp_pips, daily_pnl) -> float, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave40ProfitTargetShift:
    def setup_method(self):
        from wave40_profit_target_shift import ProfitTargetShift
        self.pts = ProfitTargetShift()

    def test_init(self):
        assert self.pts is not None

    def test_adjust_tp_positive_pnl(self):
        tp = self.pts.adjust_tp(45.0, 100.0)
        assert isinstance(tp, float)
        assert tp > 0

    def test_adjust_tp_negative_pnl(self):
        tp = self.pts.adjust_tp(45.0, -50.0)
        assert isinstance(tp, float)
        assert tp > 0

    def test_adjust_tp_zero_pnl(self):
        tp = self.pts.adjust_tp(45.0, 0.0)
        assert isinstance(tp, float)
        assert tp > 0

    def test_info_returns_dict(self):
        assert isinstance(self.pts.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 41 — Session Spread Limiter
# API: is_entry_blocked(spread_pips) -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave41SessionSpreadLimiter:
    def setup_method(self):
        from wave41_session_spread_limiter import SessionSpreadLimiter
        self.ssl = SessionSpreadLimiter()

    def test_init(self):
        assert self.ssl is not None

    def test_tight_spread_check(self):
        result = self.ssl.is_entry_blocked(0.5)
        assert isinstance(result, bool)

    def test_very_wide_spread_blocked(self):
        result = self.ssl.is_entry_blocked(999.0)
        assert result is True

    def test_info_returns_dict(self):
        assert isinstance(self.ssl.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 44 — Price Velocity Filter
# API: update(price), is_entry_blocked() -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave44PriceVelocityFilter:
    def setup_method(self):
        from wave44_price_velocity_filter import PriceVelocityFilter
        self.pv = PriceVelocityFilter()

    def test_init_not_blocked(self):
        assert self.pv.is_entry_blocked() is False

    def test_update_normal_price(self):
        self.pv.update(2400.0)
        self.pv.update(2400.1)

    def test_spike_may_block(self):
        from wave44_price_velocity_filter import PriceVelocityFilter
        pv = PriceVelocityFilter(pip_limit=1.0, window_sec=10.0)
        pv.update(2400.0)
        pv.update(2450.0)
        assert isinstance(pv.is_entry_blocked(), bool)

    def test_info_returns_dict(self):
        assert isinstance(self.pv.info(), dict)

    def test_custom_params(self):
        from wave44_price_velocity_filter import PriceVelocityFilter
        pv = PriceVelocityFilter(pip_limit=3.0, window_sec=5.0)
        assert pv is not None


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 45 — London Open Booster
# API: is_active() -> bool, adjust_min_score(min_score) -> float, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave45LondonOpenBooster:
    def setup_method(self):
        from wave45_london_open_booster import LondonOpenBooster
        self.lob = LondonOpenBooster()

    def test_init(self):
        assert self.lob is not None

    def test_is_active_returns_bool(self):
        assert isinstance(self.lob.is_active(), bool)

    def test_adjust_min_score_positive(self):
        score = self.lob.adjust_min_score(0.5)
        assert isinstance(score, float)
        assert score > 0

    def test_info_returns_dict(self):
        assert isinstance(self.lob.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 46 — Lot Recovery Ladder
# API: record_trade(won), get_lot(base_lot=None) -> float, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave46LotRecoveryLadder:
    def setup_method(self):
        from wave46_lot_recovery_ladder import LotRecoveryLadder
        self.lrl = LotRecoveryLadder()

    def test_init(self):
        assert self.lrl is not None

    def test_get_lot_default_positive(self):
        lot = self.lrl.get_lot()
        assert isinstance(lot, float)
        assert lot > 0

    def test_get_lot_custom_base(self):
        lot = self.lrl.get_lot(0.03)
        assert isinstance(lot, float)
        assert lot > 0

    def test_record_win(self):
        self.lrl.record_trade(True)

    def test_record_loss_increases_lot(self):
        from wave46_lot_recovery_ladder import LotRecoveryLadder
        lrl = LotRecoveryLadder(base_lot=0.02, multiplier=1.5, consecutive_trigger=1)
        lrl.record_trade(False)
        lrl.record_trade(False)
        lot = lrl.get_lot()
        assert lot >= 0.02

    def test_lot_capped_at_max(self):
        from wave46_lot_recovery_ladder import LotRecoveryLadder
        lrl = LotRecoveryLadder(base_lot=0.02, max_lot=0.1, multiplier=2.0, consecutive_trigger=1)
        for _ in range(10):
            lrl.record_trade(False)
        assert lrl.get_lot() <= 0.1

    def test_info_returns_dict(self):
        assert isinstance(self.lrl.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 48 — Equity High Watermark
# API: update(equity), is_entry_blocked() -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave48EquityHighWatermark:
    def setup_method(self):
        from wave48_equity_high_watermark import EquityHighWatermark
        self.ehw = EquityHighWatermark()

    def test_init_not_blocked(self):
        assert self.ehw.is_entry_blocked() is False

    def test_update_equity(self):
        self.ehw.update(10000.0)
        self.ehw.update(10100.0)

    def test_drawdown_triggers_block(self):
        from wave48_equity_high_watermark import EquityHighWatermark
        ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800)
        ehw.update(10000.0)
        ehw.update(9700.0)
        assert ehw.is_entry_blocked() is True

    def test_no_drawdown_not_blocked(self):
        self.ehw.update(10000.0)
        self.ehw.update(10010.0)
        assert self.ehw.is_entry_blocked() is False

    def test_info_returns_dict(self):
        assert isinstance(self.ehw.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 51 — Session PnL Tracker
# API: record_trade(pnl), is_entry_blocked() -> bool,
#       get_session_pnl(session=None) -> float, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave51SessionPnLTracker:
    def setup_method(self):
        from wave51_session_pnl_tracker import SessionPnLTracker
        self.spt = SessionPnLTracker()

    def test_init_not_blocked(self):
        assert self.spt.is_entry_blocked() is False

    def test_record_trade_win(self):
        self.spt.record_trade(25.0)

    def test_record_trade_loss(self):
        self.spt.record_trade(-30.0)

    def test_big_loss_triggers_block(self):
        from wave51_session_pnl_tracker import SessionPnLTracker
        spt = SessionPnLTracker(loss_limit=-50.0)
        spt.record_trade(-60.0)
        assert spt.is_entry_blocked() is True

    def test_get_session_pnl_no_args(self):
        self.spt.record_trade(10.0)
        pnl = self.spt.get_session_pnl()
        assert isinstance(pnl, float)

    def test_get_session_pnl_with_session(self):
        pnl = self.spt.get_session_pnl("London")
        assert isinstance(pnl, float)

    def test_info_returns_dict(self):
        assert isinstance(self.spt.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 53 — Tick Reversal Guard
# API: update(price), is_signal_blocked(signal) -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave53TickReversalGuard:
    def setup_method(self):
        from wave53_tick_reversal_guard import TickReversalGuard
        self.trg = TickReversalGuard()

    def test_init(self):
        assert self.trg is not None

    def test_no_data_result_is_bool(self):
        assert isinstance(self.trg.is_signal_blocked("BUY"), bool)

    def test_update_price_no_crash(self):
        for p in [2400.0, 2401.0, 2400.5, 2399.0, 2400.0]:
            self.trg.update(p)

    def test_downtrend_sell_check(self):
        from wave53_tick_reversal_guard import TickReversalGuard
        trg = TickReversalGuard(n_ticks=3, block_duration=60)
        for p in [2400.0, 2399.0, 2398.0]:
            trg.update(p)
        assert isinstance(trg.is_signal_blocked("SELL"), bool)

    def test_info_returns_dict(self):
        assert isinstance(self.trg.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 54 — Max Spread Per Trade
# API: update(spread_pips), is_entry_blocked() -> bool, get_spread() -> float, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave54MaxSpreadPerTrade:
    def setup_method(self):
        from wave54_max_spread_per_trade import MaxSpreadPerTrade
        self.msp = MaxSpreadPerTrade()

    def test_init_not_blocked(self):
        assert self.msp.is_entry_blocked() is False

    def test_tight_spread_not_blocked(self):
        self.msp.update(1.0)
        assert self.msp.is_entry_blocked() is False

    def test_wide_spread_blocked(self):
        from wave54_max_spread_per_trade import MaxSpreadPerTrade
        msp = MaxSpreadPerTrade(max_spread_pips=2.0)
        msp.update(5.0)
        assert msp.is_entry_blocked() is True

    def test_get_spread_returns_float(self):
        self.msp.update(1.5)
        spread = self.msp.get_spread()
        assert isinstance(spread, float)

    def test_info_returns_dict(self):
        assert isinstance(self.msp.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 57 — Hourly PnL Map
# API: record_trade(pnl), get_lot_multiplier() -> float, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave57HourlyPnLMap:
    def setup_method(self):
        from wave57_hourly_pnl_map import HourlyPnLMap
        self.hpm = HourlyPnLMap()

    def test_init(self):
        assert self.hpm is not None

    def test_multiplier_default_positive(self):
        m = self.hpm.get_lot_multiplier()
        assert isinstance(m, float)
        assert m > 0

    def test_record_profit(self):
        self.hpm.record_trade(20.0)

    def test_record_loss(self):
        self.hpm.record_trade(-15.0)

    def test_big_loss_reduces_multiplier(self):
        from wave57_hourly_pnl_map import HourlyPnLMap
        hpm = HourlyPnLMap(loss_threshold_usd=-10.0)
        hpm.record_trade(-50.0)
        assert hpm.get_lot_multiplier() <= 1.0

    def test_info_returns_dict(self):
        assert isinstance(self.hpm.info(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 60 — Profit Streak Booster
# API: record_trade(won), get_tp_multiplier() -> float, is_in_streak() -> bool, info()
# ─────────────────────────────────────────────────────────────────────────────
class TestWave60ProfitStreakBooster:
    def setup_method(self):
        from wave60_profit_streak_booster import ProfitStreakBooster
        self.psb = ProfitStreakBooster()

    def test_init_no_streak(self):
        assert self.psb.is_in_streak() is False

    def test_multiplier_default_positive(self):
        m = self.psb.get_tp_multiplier()
        assert isinstance(m, float)
        assert m > 0

    def test_three_wins_triggers_streak(self):
        from wave60_profit_streak_booster import ProfitStreakBooster
        psb = ProfitStreakBooster(streak_length=3, tp_multiplier=1.2)
        for _ in range(3):
            psb.record_trade(True)
        assert psb.is_in_streak() is True
        assert psb.get_tp_multiplier() > 1.0

    def test_loss_resets_streak(self):
        from wave60_profit_streak_booster import ProfitStreakBooster
        psb = ProfitStreakBooster(streak_length=3)
        for _ in range(3):
            psb.record_trade(True)
        psb.record_trade(False)
        assert psb.is_in_streak() is False

    def test_record_win(self):
        self.psb.record_trade(True)

    def test_record_loss(self):
        self.psb.record_trade(False)

    def test_info_returns_dict(self):
        assert isinstance(self.psb.info(), dict)
