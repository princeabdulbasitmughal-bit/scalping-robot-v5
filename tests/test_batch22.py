"""
test_batch22.py - Regression & Hardening tests for Batch 22:
- wave8_signal_optimizer: Thread safety, finite volume proxy, adaptive SL/TP fallbacks, safe Stoch RSI.
- wave11_profit_optimizer: Thread safety, finite daily target scaling, reversal guards, robust partial close.
- wave14_auto_tuner: Safe statistical functions with NaN/Inf filtering, project-root config path resolution.
"""

import math
import os
import threading
import pytest

from wave8_signal_optimizer import SignalScorer
from wave11_profit_optimizer import ProfitOptimizer
from wave14_auto_tuner import AutoTuner, _mean, _std, _percentile


def test_wave8_volume_proxy_and_adaptive_sl():
    scorer = SignalScorer()
    
    # 1. Non-finite tick movements ignored safely
    scorer.update_volume_proxy(float('nan'))
    scorer.update_volume_proxy(float('inf'))
    scorer.update_volume_proxy("invalid")
    assert len(scorer._vol_proxy) == 0

    # 2. Valid volume tracking
    for val in [1.0, 1.2, 1.1, 0.9, 3.5]:
        scorer.update_volume_proxy(val)
    assert scorer.is_high_volume() is True

    # 3. Adaptive SL/TP fallback guards against NaN/Inf
    sl, tp = scorer.get_adaptive_sl_tp([], base_sl_pips=float('nan'), rr_ratio=float('nan'))
    assert math.isfinite(sl) and sl > 0
    assert math.isfinite(tp) and tp > 0

    # 4. Stoch RSI non-finite resilience
    rsi = scorer.compute_stoch_rsi([float('nan'), 100.0, float('inf')])
    assert math.isfinite(rsi)


def test_wave11_profit_optimizer_finite_guards():
    optimizer = ProfitOptimizer()

    # 1. Daily target lot scale with NaN / Inf / <=0
    assert optimizer.daily_target_lot_scale(100.0, 0.0) == 1.0
    assert optimizer.daily_target_lot_scale(float('nan'), 200.0) == 1.0
    assert optimizer.daily_target_lot_scale(100.0, float('nan')) == 1.0
    assert optimizer.daily_target_lot_scale(float('inf'), 200.0) == 1.0

    # Normal scaling
    assert optimizer.daily_target_lot_scale(160.0, 200.0) == 0.5   # 80% reached -> 0.5x
    assert optimizer.daily_target_lot_scale(110.0, 200.0) == 0.75  # 55% reached -> 0.75x
    assert optimizer.daily_target_lot_scale(50.0, 200.0) == 1.0    # 25% reached -> 1.0x

    # 2. Reversal and partial close checks with non-finite values
    optimizer.update_peak_float('T1', 50.0)
    assert optimizer.should_close_reversal('T1', float('nan')) is False
    assert optimizer.should_close_reversal('T1', 20.0, threshold=0.5) is True  # 60% dropped > 50%

    assert optimizer.get_partial_close_level('T1', pips_profit=float('nan')) is None
    extended_tp = optimizer.get_extended_tp_pips(
        base_tp=float('nan'),
        pips_profit=float('nan'),
        market_regime='TRENDING_UP',
        win_streak=3
    )
    assert extended_tp == 45.0

    # 3. Thread safe session stats
    def record_trades():
        for _ in range(20):
            optimizer.record_result(True)
            optimizer.record_result(False)

    threads = [threading.Thread(target=record_trades) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = optimizer.session_stats()
    assert stats["sample_size"] == 10
    assert 0.0 <= stats["win_rate"] <= 100.0


def test_wave14_auto_tuner_stats_and_path():
    # 1. Statistical functions handle NaN, Inf, non-numbers, empty safely
    dirty = [10.0, float('nan'), 20.0, float('inf'), "invalid", None, 30.0]
    assert _mean(dirty) == pytest.approx(20.0)
    assert _std(dirty) == pytest.approx(10.0)
    assert _percentile(dirty, 50) == pytest.approx(20.0)

    assert _mean([]) == 0.0
    assert _std([]) == 0.0
    assert _percentile([], 50) == 0.0

    # 2. AutoTuner config path resolution points to project root config.json
    tuner = AutoTuner()
    expected_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.json"))
    assert os.path.abspath(tuner.config_path) == expected_path
