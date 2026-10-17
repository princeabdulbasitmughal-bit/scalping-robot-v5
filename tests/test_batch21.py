import math
import time
import threading
from pathlib import Path
import pytest

from performance_monitor import _safe_float, calculate_grade
from wave19_volatility_tpsl import VolatilityTPSLAdjuster
from wave20_spike_filter import SpikeFilter
from wave21_news_guard import NewsGuard


class TestBatch21Hardening:
    def test_performance_monitor_safe_float_and_grade(self):
        # Rejects NaN and Inf
        assert _safe_float(float('nan'), default=0.0) == 0.0
        assert _safe_float(float('inf'), default=10.0) == 10.0
        assert _safe_float(-float('inf'), default=-5.0) == -5.0
        assert _safe_float(None, default=0.0) == 0.0
        assert _safe_float("invalid", default=0.0) == 0.0
        assert _safe_float(95.5, default=0.0) == 95.5

        # Grades
        assert calculate_grade(95.0) == "A+"
        assert calculate_grade(88.0) == "A"
        assert calculate_grade(78.0) == "B"
        assert calculate_grade(65.0) == "C"

    def test_wave19_volatility_tpsl_nan_and_none_resilience(self):
        adj = VolatilityTPSLAdjuster()
        # Closes with NaNs, Infs, and Nones
        tp, sl = adj.adjusted_tpsl(
            closes=[float('nan'), 2400.0, None, 2402.0, float('inf'), 2405.0],
            base_tp_pips=float('nan'),
            base_sl_pips=-10.0,
            session_info={"vol_index": float('nan')}
        )
        assert isinstance(tp, float) and math.isfinite(tp) and tp > 0
        assert isinstance(sl, float) and math.isfinite(sl) and sl > 0

    def test_wave20_spike_filter_nan_price_and_thread_safety(self):
        sf = SpikeFilter()
        # NaN and Inf prices rejected fail-closed
        ok, reason = sf.check(float('nan'), 2400.0)
        assert ok is False
        assert reason == "SPIKE_FILTER_INVALID_PRICE"

        ok, reason = sf.check(2400.0, float('inf'))
        assert ok is False

        # Concurrent check calls under multiple threads
        def worker():
            for p in range(50):
                sf.update(2400.0 + p * 0.1, 2400.0 + (p - 1) * 0.1)
                sf.info()

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        info = sf.info()
        assert isinstance(info, dict)
        assert "blocked" in info

    def test_wave21_news_guard_thread_safety(self):
        ng = NewsGuard()
        def worker():
            for _ in range(50):
                ng.is_trading_allowed()
                ng.info()

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        info = ng.info()
        assert isinstance(info, dict)
        assert "avoid_trading" in info
