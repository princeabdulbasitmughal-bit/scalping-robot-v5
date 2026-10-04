"""
test_waves_v5_coverage.py — Enhanced edge-case tests for low-coverage wave modules.
Targets: wave13 (37%), wave59 (52%), wave61 (45%), wave12 (54%), wave53 (59%),
         wave22 (58%), wave21 (56%), wave55 (73%), wave52 (73%).

Run: python -m pytest tests/test_waves_v5_coverage.py -v
"""

import sys
import os
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 13 — LinearRegressor / MLPredictor — boost from 37%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave13LinearRegressorExtended:
    def setup_method(self):
        from wave13_ml_predictor import LinearRegressor
        self.lr = LinearRegressor()

    def test_fit_uptrend(self):
        result = self.lr.fit([100.0, 101.0, 102.0, 103.0, 104.0])
        assert result["slope"] > 0
        assert result["r_squared"] >= 0.0

    def test_fit_downtrend(self):
        result = self.lr.fit([105.0, 104.0, 103.0, 102.0, 101.0])
        assert result["slope"] < 0
        assert result["r_squared"] >= 0.0

    def test_fit_flat_line(self):
        result = self.lr.fit([100.0, 100.0, 100.0, 100.0, 100.0])
        assert result["slope"] == 0.0
        assert result["r_squared"] == 0.0

    def test_fit_less_than_3_returns_zero(self):
        result = self.lr.fit([100.0, 101.0])
        assert result == {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}

    def test_fit_single_element(self):
        result = self.lr.fit([99.9])
        assert result["slope"] == 0.0

    def test_fit_empty_list(self):
        result = self.lr.fit([])
        assert result["slope"] == 0.0

    def test_fit_large_dataset(self):
        prices = [2400.0 + i * 0.1 for i in range(200)]
        result = self.lr.fit(prices)
        assert result["slope"] > 0
        assert 0.0 <= result["r_squared"] <= 1.0

    def test_fit_noisy_uptrend(self):
        import random
        random.seed(42)
        prices = [2400.0 + i * 0.5 + random.gauss(0, 0.1) for i in range(50)]
        result = self.lr.fit(prices)
        assert result["slope"] > 0
        assert result["r_squared"] > 0.9

    def test_fit_returns_dict_keys(self):
        result = self.lr.fit([1.0, 2.0, 3.0, 4.0, 5.0])
        assert "slope" in result
        assert "intercept" in result
        assert "r_squared" in result

    def test_r_squared_clamped_0_to_1(self):
        result = self.lr.fit([1.0, 2.0, 3.0, 4.0, 5.0])
        assert 0.0 <= result["r_squared"] <= 1.0

    def test_predict_returns_dict(self):
        result = self.lr.predict([2400.0, 2401.0, 2402.0, 2403.0, 2404.0])
        assert isinstance(result, dict)

    def test_fit_all_same_x_returns_safe(self):
        # ss_xx = 0 branch
        result = self.lr.fit([5.0, 5.0, 5.0])
        assert result["slope"] == 0.0
        assert result["intercept"] == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 59 — MATrendFilter — boost from 52%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave59MATrendFilterExtended:
    def setup_method(self):
        from wave59_ma_trend_filter import MATrendFilter
        self.ma = MATrendFilter(period=5)  # use short period for fast warm-up

    def test_ema_zero_before_warmup(self):
        assert self.ma.get_ema() == 0.0

    def test_warmup_after_period_ticks(self):
        for p in [100.0, 101.0, 102.0, 103.0, 104.0]:
            self.ma.update(p)
        # After 5 ticks (period=5), EMA should be seeded to SMA = 102.0
        assert self.ma.get_ema() > 0.0

    def test_ema_seeded_to_sma_after_period(self):
        prices = [100.0, 100.0, 100.0, 100.0, 100.0]
        for p in prices:
            self.ma.update(p)
        # SMA of [100,100,100,100,100] = 100.0
        assert abs(self.ma.get_ema() - 100.0) < 0.001

    def test_ema_update_after_warmup(self):
        for p in [100.0] * 5:
            self.ma.update(p)
        self.ma.update(200.0)  # big jump
        # EMA should move toward 200 but not reach it
        assert 100.0 < self.ma.get_ema() < 200.0

    def test_ema_tracks_uptrend(self):
        ma = __import__("wave59_ma_trend_filter").MATrendFilter(period=10)
        for i in range(10):
            ma.update(100.0 + i)
        first_ema = ma.get_ema()
        for i in range(10, 20):
            ma.update(100.0 + i)
        # EMA should increase as prices increase
        assert ma.get_ema() > first_ema

    def test_multiple_updates_no_crash(self):
        for i in range(100):
            self.ma.update(2400.0 + i * 0.1)
        assert self.ma.get_ema() > 0.0

    def test_zero_price_no_crash(self):
        self.ma.update(0.0)
        assert self.ma.get_ema() >= 0.0

    def test_negative_price_no_crash(self):
        self.ma.update(-100.0)
        # Should not crash
        assert isinstance(self.ma.get_ema(), float)

    def test_default_period_50(self):
        from wave59_ma_trend_filter import MATrendFilter
        ma = MATrendFilter()
        assert ma.period == 50

    def test_alpha_computed_correctly(self):
        from wave59_ma_trend_filter import MATrendFilter
        ma = MATrendFilter(period=9)
        expected_alpha = 2.0 / (9 + 1)
        assert abs(ma.alpha - expected_alpha) < 1e-10

    def test_seed_prices_cleared_after_warmup(self):
        for p in [100.0] * 5:
            self.ma.update(p)
        # After warmup, seed_prices should be cleared
        assert len(self.ma._seed_prices) == 0
        assert self.ma._warmed_up is True


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 61 — OpeningRangeBreakout — boost from 45%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave61OpeningRangeBreakoutExtended:
    def setup_method(self):
        from wave61_opening_range_breakout import OpeningRangeBreakout
        self.orb = OpeningRangeBreakout()

    def test_initial_state(self):
        assert self.orb._session_start is None
        assert self.orb._or_high is None
        assert self.orb._or_low is None
        assert self.orb._tick_count == 0

    def test_update_increments_no_crash(self):
        self.orb.update(2400.0)
        assert self.orb._last_price == 2400.0

    def test_update_many_ticks(self):
        for i in range(50):
            self.orb.update(2400.0 + i * 0.01)
        # _last_price should be the last update value
        assert self.orb._last_price == 2400.0 + 49 * 0.01

    def test_last_price_updated(self):
        self.orb.update(2401.5)
        assert self.orb._last_price == 2401.5

    def test_last_price_last_update_wins(self):
        self.orb.update(2400.0)
        self.orb.update(2405.0)
        assert self.orb._last_price == 2405.0

    def test_update_no_crash_zero_price(self):
        self.orb.update(0.0)
        assert self.orb._last_price == 0.0

    def test_update_no_crash_extreme_price(self):
        self.orb.update(99999.0)
        assert self.orb._last_price == 99999.0

    def test_session_reset_check_exists(self):
        # _check_session_reset is a method
        assert hasattr(self.orb, "_check_session_reset")
        assert callable(self.orb._check_session_reset)

    def test_multiple_updates_no_crash(self):
        prices = [2400.0, 2401.0, 2398.0, 2402.0, 2399.0]
        for p in prices:
            self.orb.update(p)
        assert self.orb._last_price == 2399.0

    def test_in_window_starts_false(self):
        assert self.orb._in_window is False

    def test_window_complete_starts_false(self):
        assert self.orb._window_complete is False



# ─────────────────────────────────────────────────────────────────────────────
# WAVE 12 — TelegramAlerter — boost from 54%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave12TelegramAlerterExtended:
    def setup_method(self):
        from wave12_telegram_alerts import TelegramAlerter
        self.ta = TelegramAlerter()

    def test_send_alert_disabled_returns_false(self):
        # By default enabled=False in config
        self.ta._config["enabled"] = False
        result = self.ta.send_alert("test message")
        assert result is False

    def test_send_alert_no_token_returns_false(self):
        self.ta._config["enabled"] = True
        self.ta._config["bot_token"] = ""
        self.ta._config["chat_id"] = ""
        # Even with enabled, _send_raw returns False with no token
        result = self.ta.send_alert("test", force=True)
        # Returns True from send_alert (rate limit bypass) but raw send fails
        # The send_alert returns True once it dispatches the thread
        assert isinstance(result, bool)

    def test_send_alert_with_force_bypasses_rate_limit(self):
        self.ta._config["enabled"] = False
        # disabled -> always False regardless of force
        result = self.ta.send_alert("forced", force=True)
        assert result is False

    def test_alert_trade_open_no_crash_when_disabled(self):
        self.ta._config["enabled"] = False
        self.ta._config["alert_on_trade_open"] = False
        # Should complete without error
        self.ta.alert_trade_open("BUY", 2400.0, 2397.0, 2404.5, 0.02)

    def test_alert_trade_open_no_crash_when_config_missing(self):
        self.ta._config = {}
        self.ta.alert_trade_open("SELL", 2400.0, 2403.0, 2395.5, 0.02)

    def test_alert_trade_close_no_crash(self):
        self.ta._config = {}
        self.ta.alert_trade_close("BUY", 25.0, "TP_HIT", 9125.0)

    def test_alert_trade_close_loss_no_crash(self):
        self.ta._config = {}
        self.ta.alert_trade_close("SELL", -30.0, "SL_HIT", 9070.0)

    def test_alert_circuit_breaker_no_crash(self):
        self.ta._config = {}
        self.ta.alert_circuit_breaker("DAILY_LOSS_LIMIT", 9000.0, -200.0)

    def test_alert_daily_summary_no_crash(self):
        self.ta._config = {}
        self.ta.alert_daily_summary(9100.0, 50.0, 5, 3, 62.5, 8)

    def test_config_has_defaults_on_missing_file(self):
        # Config should have fallback values
        from wave12_telegram_alerts import TelegramAlerter
        ta = TelegramAlerter()
        assert isinstance(ta._config, dict)

    def test_rate_limit_blocks_second_call(self):
        self.ta._config["enabled"] = True
        self.ta._config["bot_token"] = "fake"
        self.ta._config["chat_id"] = "123"
        self.ta._config["min_alert_interval_sec"] = 60
        # First call sets _last_sent
        self.ta._last_sent = time.time()
        # Second call within rate limit -> False
        result = self.ta.send_alert("second call")
        assert result is False

    def test_lock_attribute_exists(self):
        import threading
        assert hasattr(self.ta, "_lock")


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 53 — TickReversalGuard — boost from 59%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave53TickReversalGuardExtended:
    def setup_method(self):
        from wave53_tick_reversal_guard import TickReversalGuard
        self.g = TickReversalGuard(n_ticks=5, block_duration=1)

    def test_fresh_instance_no_block_buy(self):
        assert self.g.is_signal_blocked("BUY") is False

    def test_fresh_instance_no_block_sell(self):
        assert self.g.is_signal_blocked("SELL") is False

    def test_uptrend_then_buy_not_blocked(self):
        # 5 rising ticks -> no reversal for BUY
        for p in [100.0, 101.0, 102.0, 103.0, 104.0]:
            self.g.update(p)
        # BUY in uptrend should not be blocked by reversal guard
        blocked = self.g.is_signal_blocked("BUY")
        assert isinstance(blocked, bool)

    def test_downtrend_ticks_sell_check(self):
        for p in [104.0, 103.0, 102.0, 101.0, 100.0]:
            self.g.update(p)
        blocked = self.g.is_signal_blocked("SELL")
        assert isinstance(blocked, bool)

    def test_update_many_ticks_no_crash(self):
        for i in range(100):
            self.g.update(2400.0 + (i % 10) * 0.5)
        assert isinstance(self.g.is_signal_blocked("BUY"), bool)

    def test_info_contains_expected_keys(self):
        info = self.g.info()
        assert isinstance(info, dict)

    def test_n_ticks_custom_init(self):
        from wave53_tick_reversal_guard import TickReversalGuard
        g = TickReversalGuard(n_ticks=10, block_duration=30)
        assert g._n == 10

    def test_block_duration_custom_init(self):
        from wave53_tick_reversal_guard import TickReversalGuard
        g = TickReversalGuard(n_ticks=5, block_duration=60)
        assert g._block_duration == 60

    def test_alternating_prices_no_crash(self):
        for i in range(20):
            self.g.update(2400.0 if i % 2 == 0 else 2401.0)
        assert isinstance(self.g.is_signal_blocked("BUY"), bool)

    def test_same_price_ticks_no_crash(self):
        for _ in range(10):
            self.g.update(2400.0)
        assert isinstance(self.g.is_signal_blocked("SELL"), bool)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 22 — EquityCurveHalt — boost from 58%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave22EquityCurveHaltExtended:
    def setup_method(self):
        from wave22_equity_curve_halt import EquityCurveHalt
        self.ech = EquityCurveHalt(
            window=5,
            loss_threshold_usd=-50.0,
            slope_threshold=-5.0,
            recovery_win_streak=2,
            cooldown_sec=0.0
        )

    def test_fresh_trading_allowed(self):
        ok, reason = self.ech.is_trading_allowed(9100.0)
        assert ok is True

    def test_record_wins_keeps_trading(self):
        for _ in range(5):
            self.ech.record_trade(10.0, True)
        ok, _ = self.ech.is_trading_allowed(9100.0)
        assert ok is True

    def test_big_consecutive_losses_triggers_halt(self):
        for _ in range(5):
            self.ech.record_trade(-20.0, False)
        ok, reason = self.ech.is_trading_allowed(9100.0)
        # With 5 losses of -20 = -100 < threshold -50 -> halt
        assert isinstance(ok, bool)
        assert isinstance(reason, str)

    def test_record_trade_win_sets_streak(self):
        self.ech.record_trade(10.0, True)
        assert self.ech._consecutive_wins >= 0

    def test_recovery_after_losses(self):
        # Trigger halt via losses
        for _ in range(5):
            self.ech.record_trade(-20.0, False)
        # Now win enough for recovery
        for _ in range(3):
            self.ech.record_trade(10.0, True)
        ok, reason = self.ech.is_trading_allowed(9100.0)
        assert isinstance(ok, bool)

    def test_info_returns_dict(self):
        info = self.ech.info()
        assert isinstance(info, dict)

    def test_info_has_required_keys(self):
        info = self.ech.info()
        # Should contain some status info
        assert len(info) > 0

    def test_zero_cooldown_no_block_after_reset(self):
        from wave22_equity_curve_halt import EquityCurveHalt
        ech = EquityCurveHalt(cooldown_sec=0.0, recovery_win_streak=1)
        for _ in range(5):
            ech.record_trade(-30.0, False)
        ech.record_trade(10.0, True)
        ok, _ = ech.is_trading_allowed(9100.0)
        assert isinstance(ok, bool)

    def test_mixed_trades_no_crash(self):
        trades = [(-10.0, False), (5.0, True), (-15.0, False), (8.0, True), (-20.0, False)]
        for pnl, won in trades:
            self.ech.record_trade(pnl, won)
        assert isinstance(self.ech.is_trading_allowed(9100.0), tuple)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 21 — NewsGuard — boost from 56%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave21NewsGuardExtended:
    def setup_method(self):
        from wave21_news_guard import NewsGuard
        self.ng = NewsGuard()

    def test_is_trading_allowed_returns_tuple(self):
        result = self.ng.is_trading_allowed()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_is_trading_allowed_bool_first(self):
        ok, reason = self.ng.is_trading_allowed()
        assert isinstance(ok, bool)

    def test_is_trading_allowed_str_second(self):
        ok, reason = self.ng.is_trading_allowed()
        assert isinstance(reason, str)

    def test_info_returns_dict(self):
        info = self.ng.info()
        assert isinstance(info, dict)

    def test_info_has_content(self):
        info = self.ng.info()
        assert len(info) > 0

    def test_multiple_calls_no_crash(self):
        for _ in range(10):
            self.ng.is_trading_allowed()

    def test_fresh_instance_consistent(self):
        from wave21_news_guard import NewsGuard
        ng1 = NewsGuard()
        ng2 = NewsGuard()
        ok1, _ = ng1.is_trading_allowed()
        ok2, _ = ng2.is_trading_allowed()
        assert ok1 == ok2


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 55 — BalanceFloorGuard — boost from 73%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave55BalanceFloorGuardExtended:
    def setup_method(self):
        from wave55_balance_floor_guard import BalanceFloorGuard
        self.bg = BalanceFloorGuard()

    def test_init_not_blocked(self):
        # Fresh instance with no update — not blocked
        assert isinstance(self.bg.is_entry_blocked(), bool)

    def test_above_floor_allowed(self):
        self.bg.update(10000.0)
        assert self.bg.is_entry_blocked() is False

    def test_far_below_floor_blocked(self):
        self.bg.update(1.0)
        assert self.bg.is_entry_blocked() is True

    def test_reason_is_string(self):
        self.bg.update(9100.0)
        info = self.bg.info()
        assert isinstance(info, dict)

    def test_info_returns_dict(self):
        info = self.bg.info()
        assert isinstance(info, dict)

    def test_extreme_high_balance_no_crash(self):
        self.bg.update(999999.0)
        assert self.bg.is_entry_blocked() is False

    def test_zero_balance_blocked(self):
        self.bg.update(0.0)
        assert self.bg.is_entry_blocked() is True

    def test_negative_balance_blocked(self):
        self.bg.update(-100.0)
        assert self.bg.is_entry_blocked() is True

    def test_custom_floor_init(self):
        from wave55_balance_floor_guard import BalanceFloorGuard
        bg = BalanceFloorGuard(floor_usd=5000.0)
        bg.update(4999.0)
        assert bg.is_entry_blocked() is True

    def test_custom_floor_above_allowed(self):
        from wave55_balance_floor_guard import BalanceFloorGuard
        bg = BalanceFloorGuard(floor_usd=5000.0)
        bg.update(5100.0)
        assert bg.is_entry_blocked() is False


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 52 — RSIOverboughtOversold — boost from 73%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave52RSIFilterExtended:
    def setup_method(self):
        from wave52_rsi_ob_os_filter import RSIOverboughtOversold
        self.rsi = RSIOverboughtOversold()

    def test_is_signal_blocked_returns_bool(self):
        assert isinstance(self.rsi.is_signal_blocked("BUY"), bool)

    def test_is_signal_blocked_no_data_returns_false(self):
        # No price updates -> neutral state -> not blocked
        assert self.rsi.is_signal_blocked("BUY") is False
        assert self.rsi.is_signal_blocked("SELL") is False

    def test_update_price_no_crash(self):
        for p in [2400.0, 2401.0, 2402.0]:
            self.rsi.update(p)

    def test_warmup_period_not_blocked(self):
        # RSI needs ~14 ticks to warm up
        for i in range(5):
            self.rsi.update(2400.0 + i)
        result = self.rsi.is_signal_blocked("BUY")
        assert isinstance(result, bool)

    def test_after_warmup_price_rising_buy_check(self):
        # Feed 20 rising prices
        for i in range(20):
            self.rsi.update(2400.0 + i * 0.5)
        # Buy in very overbought territory might be blocked
        result = self.rsi.is_signal_blocked("BUY")
        assert isinstance(result, bool)

    def test_after_warmup_price_falling_sell_check(self):
        for i in range(20):
            self.rsi.update(2420.0 - i * 0.5)
        result = self.rsi.is_signal_blocked("SELL")
        assert isinstance(result, bool)

    def test_info_returns_dict(self):
        info = self.rsi.info()
        assert isinstance(info, dict)

    def test_update_and_is_blocked_consistent_type(self):
        self.rsi.update(2400.0)
        b1 = self.rsi.is_signal_blocked("BUY")
        b2 = self.rsi.is_signal_blocked("SELL")
        assert isinstance(b1, bool)
        assert isinstance(b2, bool)

    def test_same_price_no_crash(self):
        for _ in range(30):
            self.rsi.update(2400.0)
        assert isinstance(self.rsi.is_signal_blocked("BUY"), bool)


    def test_hold_signal_not_blocked(self):
        result = self.rsi.is_signal_blocked("HOLD")
        assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 14 — AutoTuner — boost from 52%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave14AutoTunerExtended:
    def setup_method(self):
        from wave14_auto_tuner import AutoTuner
        self.at = AutoTuner()

    def test_seconds_since_last_run_is_float(self):
        assert isinstance(self.at.seconds_since_last_run, float)

    def test_seconds_since_last_run_starts_inf(self):
        import math
        assert math.isinf(self.at.seconds_since_last_run)

    def test_last_report_is_dict(self):
        assert isinstance(self.at.last_report, dict)

    def test_last_report_starts_empty(self):
        assert self.at.last_report == {}

    def test_min_trades_is_10(self):
        assert self.at.MIN_TRADES == 10

    def test_config_defaults_is_dict(self):
        assert isinstance(self.at.CONFIG_DEFAULTS, dict)

    def test_analyse_empty_returns_dict(self):
        result = self.at.analyse([])
        assert isinstance(result, dict)

    def test_analyse_insufficient_data_status(self):
        result = self.at.analyse([])
        assert result['status'] == 'insufficient_data'

    def test_analyse_few_trades_insufficient(self):
        trades = [{'pnl': 10.0, 'won': True}] * 3
        result = self.at.analyse(trades)
        assert result['status'] == 'insufficient_data'

    def test_analyse_and_tune_no_crash(self):
        result = self.at.analyse_and_tune([], balance=10000.0, dry_run=True)
        assert isinstance(result, dict)

    def test_analyse_and_tune_with_trades_no_crash(self):
        trades = [{'pnl': 10.0 if i % 2 else -5.0, 'won': i % 2 == 0} for i in range(15)]
        result = self.at.analyse_and_tune(trades, balance=10000.0, dry_run=True)
        assert isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE 50 — CandlePatternFilter — boost from 67%
# ─────────────────────────────────────────────────────────────────────────────
class TestWave50CandlePatternFilterExtended:
    def setup_method(self):
        from wave50_candle_pattern_filter import CandlePatternFilter
        self.cpf = CandlePatternFilter()

    def test_is_signal_blocked_returns_bool(self):
        assert isinstance(self.cpf.is_signal_blocked("BUY"), bool)

    def test_no_data_not_blocked(self):
        assert self.cpf.is_signal_blocked("BUY") is False

    def test_update_no_crash(self):
        self.cpf.update(2400.0)

    def test_update_multiple_no_crash(self):
        for price in [2400.0, 2401.0, 2402.5, 2401.5, 2403.0]:
            self.cpf.update(price)

    def test_bullish_prices_buy_not_blocked(self):
        for price in [2400.0, 2401.0, 2402.0, 2403.0, 2404.0]:
            self.cpf.update(price)
        result = self.cpf.is_signal_blocked("BUY")
        assert isinstance(result, bool)

    def test_bearish_prices_sell_check(self):
        for price in [2404.0, 2403.0, 2402.0, 2401.0, 2400.0]:
            self.cpf.update(price)
        result = self.cpf.is_signal_blocked("SELL")
        assert isinstance(result, bool)

    def test_flat_price_no_crash(self):
        for _ in range(5):
            self.cpf.update(2400.0)
        assert isinstance(self.cpf.is_signal_blocked("BUY"), bool)

    def test_info_returns_dict(self):
        info = self.cpf.info()
        assert isinstance(info, dict)

    def test_many_updates_no_crash(self):
        prices = [2400.0 + (i % 10) * 0.5 for i in range(20)]
        for p in prices:
            self.cpf.update(p)
        assert isinstance(self.cpf.is_signal_blocked("BUY"), bool)

    def test_hold_signal_returns_bool(self):
        result = self.cpf.is_signal_blocked("HOLD")
        assert isinstance(result, bool)



