import pytest
import datetime
from datetime import timezone
import math
from wave26_time_filter import TimeFilter, time_filter, is_entry_blocked as w26_is_entry_blocked, is_blocked as w26_is_blocked, is_trading_allowed as w26_is_trading_allowed
from wave27_correlation_guard import CorrelationGuard, correlation_guard, compute_pearson_correlation, is_entry_blocked as w27_is_entry_blocked, is_blocked as w27_is_blocked, is_trading_allowed as w27_is_trading_allowed


class TestBatch130:
    """Batch 130 Test Suite: wave26 Time Filter & wave27 Correlation Guard."""

    def test_wave26_risk_guard_aliases(self):
        tf = TimeFilter(release_times=[(12, 30)], block_before=30, block_after=30)
        # 10:00 UTC is well clear
        dt_clear = datetime.datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
        assert tf.is_blocked(dt_clear) is False
        assert tf.is_entry_blocked(dt_clear) is False

        # 12:15 UTC is 15 min before 12:30 -> blocked
        dt_blocked = datetime.datetime(2026, 10, 18, 12, 15, tzinfo=timezone.utc)
        assert tf.is_blocked(dt_blocked) is True
        assert tf.is_entry_blocked(dt_blocked) is True

        # Module-level aliases
        time_filter.reset()
        assert w26_is_blocked(dt_clear) is False
        assert w26_is_entry_blocked(dt_clear) is False
        allowed, _ = w26_is_trading_allowed(dt_clear)
        assert allowed is True

    def test_wave26_major_economic_release_block(self):
        tf = TimeFilter(release_times=[(12, 30)], block_before=30, block_after=30)
        # 40 min before (11:50) -> OK
        dt_before = datetime.datetime(2026, 10, 18, 11, 50, tzinfo=timezone.utc)
        allowed, _ = tf.is_trading_allowed(dt_before)
        assert allowed is True

        # 15 min after (12:45) -> Blocked
        dt_after = datetime.datetime(2026, 10, 18, 12, 45, tzinfo=timezone.utc)
        allowed, reason = tf.is_trading_allowed(dt_after)
        assert allowed is False
        assert "TIME_FILTER" in reason

        # 35 min after (13:05) -> OK
        dt_clear = datetime.datetime(2026, 10, 18, 13, 5, tzinfo=timezone.utc)
        allowed, _ = tf.is_trading_allowed(dt_clear)
        assert allowed is True

    def test_wave26_dynamic_release_times_and_normalization(self):
        tf = TimeFilter(release_times=[(10, 0)])
        assert len(tf._release_times) == 1

        tf.add_release_time(15, 30)
        assert (15, 30) in tf._release_times

        tf.set_release_times([(8, 0), (16, 0)])
        assert len(tf._release_times) == 2

        # Timestamp normalization: float timestamp
        ts = datetime.datetime(2026, 10, 18, 8, 10, tzinfo=timezone.utc).timestamp()
        assert tf.is_entry_blocked(ts) is True

        # String normalization
        iso_str = "2026-10-18T08:10:00+00:00"
        assert tf.is_entry_blocked(iso_str) is True

    def test_wave26_rollover_and_midnight_wrap(self):
        # Release at 00:05 UTC with 30 min before block
        tf = TimeFilter(release_times=[(0, 5)], block_before=30, block_after=30)
        # 23:50 UTC previous day -> should be blocked across midnight boundary
        dt_midnight = datetime.datetime(2026, 10, 18, 23, 50, tzinfo=timezone.utc)
        allowed, reason = tf.is_trading_allowed(dt_midnight)
        assert allowed is False
        assert "before" in reason

    def test_wave26_info_and_reset(self):
        tf = TimeFilter(release_times=[(12, 30)], block_before=30, block_after=30)
        dt_blocked = datetime.datetime(2026, 10, 18, 12, 10, tzinfo=timezone.utc)
        info = tf.info(dt_blocked)
        assert info["blocked"] is True
        assert info["remaining_block_min"] > 0
        assert tf._total_blocks > 0

        tf.reset()
        assert tf._total_blocks == 0
        assert tf._was_blocked is False

    def test_wave27_risk_guard_aliases(self):
        cg = CorrelationGuard(window_sec=10.0, max_signals_in_window=2, cooldown_sec=30.0)
        assert cg.is_blocked(now_ts=100.0) is False
        assert cg.is_entry_blocked(now_ts=100.0) is False

        # Pre-set cooldown
        cg._blocked_until = 200.0
        assert cg.is_blocked(now_ts=150.0) is True
        assert cg.is_entry_blocked(now_ts=150.0) is True
        assert cg.is_blocked(now_ts=201.0) is False

        # Module-level aliases
        correlation_guard.reset()
        assert w27_is_blocked() is False
        assert w27_is_entry_blocked() is False
        allowed, _ = w27_is_trading_allowed()
        assert allowed is True

    def test_wave27_signal_clustering_and_cooldown(self):
        cg = CorrelationGuard(window_sec=30.0, max_signals_in_window=3, cooldown_sec=60.0)
        # Record 3 signals at t=10, 15, 20
        cg.record_signal(now_ts=10.0)
        cg.record_signal(now_ts=15.0)
        cg.record_signal(now_ts=20.0)
        assert cg.is_blocked(now_ts=20.0) is False

        # 4th signal triggers cooldown
        cg.record_signal(now_ts=25.0)
        assert cg.is_blocked(now_ts=26.0) is True
        allowed, reason = cg.is_trading_allowed(now_ts=26.0)
        assert allowed is False
        assert "CORR_GUARD" in reason
        assert cg._total_triggers == 1

    def test_wave27_pearson_correlation_zero_variance(self):
        # Flat series: variance is 0.0 -> must return 0.0 without crash
        series_flat = [100.0, 100.0, 100.0, 100.0]
        series_norm = [10.0, 20.0, 30.0, 40.0]
        r = compute_pearson_correlation(series_flat, series_norm)
        assert r == 0.0

        # Short series or length mismatch
        assert compute_pearson_correlation([1.0], [2.0]) == 0.0
        assert compute_pearson_correlation([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0
        # NaN / Inf in sequence handled safely
        assert compute_pearson_correlation([1.0, float('nan')], [2.0, 3.0]) == 0.0

    def test_wave27_pearson_correlation_bounds_and_matrix(self):
        # Perfect positive correlation
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = compute_pearson_correlation(a, b)
        assert pytest.approx(r, 0.001) == 1.0

        # Perfect negative correlation
        c = [10.0, 8.0, 6.0, 4.0, 2.0]
        r_neg = compute_pearson_correlation(a, c)
        assert pytest.approx(r_neg, 0.001) == -1.0

        # Matrix calculation
        cg = CorrelationGuard()
        matrix = cg.compute_correlation_matrix({"A": a, "B": b, "C": c})
        assert matrix["A"]["A"] == 1.0
        assert pytest.approx(matrix["A"]["B"], 0.001) == 1.0
        assert pytest.approx(matrix["A"]["C"], 0.001) == -1.0
        assert matrix["A"]["B"] == matrix["B"]["A"]

    def test_wave27_asset_buffers_and_reset(self):
        cg = CorrelationGuard(max_corr_threshold=0.80)
        # Feed prices
        for val in [10.0, 20.0, 30.0, 40.0]:
            cg.update_asset_price("XAUUSD", val)
            cg.update_asset_price("EURUSD", val * 2)

        too_high, corr = cg.is_correlation_too_high("XAUUSD", "EURUSD")
        assert too_high is True
        assert pytest.approx(corr, 0.001) == 1.0

        info = cg.info(now_ts=100.0)
        assert info["name"] == "CorrelationGuard"
        assert "signals_in_window" in info

        cg.reset()
        assert len(cg._asset_buffers) == 0
        assert len(cg._signal_times) == 0
        assert cg._total_triggers == 0
