"""
Batch 46 Test Suite:
1. supervisor.py calculate_backoff exponential progression and limits
2. supervisor.py circuit breaker threshold assertion
3. supervisor.py isolated logging and start_watchdog detached parameter passing
4. omnicommand_server.py _compute_grade tiered evaluation (A+, A, B, C)
5. omnicommand_server.py read_live_status fallback resilience and error containment
6. omnicommand_server.py _enrich_live_status default fields and wave diagnostics
7. wave19_volatility_tpsl.py dynamic ATR, high-vol TP expansion & low-vol tightening
8. wave20_spike_filter.py single tick spike detection and cooldown enforcement
9. wave20_spike_filter.py spike cluster detection and rolling reset
10. python_engine/signal_engine.py get_signal_safe error containment and confluence
"""
import math
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import supervisor
import omnicommand_server
from wave19_volatility_tpsl import VolatilityTPSLAdjuster
from wave20_spike_filter import SpikeFilter
from python_engine.signal_engine import SignalEngine


# ── Test 1: Supervisor calculate_backoff ──────────────────────────────────────
def test_supervisor_calculate_backoff():
    """Verify supervisor exponential backoff progression and maximum bounds."""
    # Non-positive values return 0
    assert supervisor.calculate_backoff(0) == 0
    assert supervisor.calculate_backoff(-5) == 0

    # Exponential growth starting at 8s
    assert supervisor.calculate_backoff(1) == 8
    assert supervisor.calculate_backoff(2) == 16
    assert supervisor.calculate_backoff(3) == 32
    assert supervisor.calculate_backoff(4) == 64

    # Capped at _MAX_BACKOFF_SEC (120)
    assert supervisor.calculate_backoff(5) == 120
    assert supervisor.calculate_backoff(6) == 120
    assert supervisor.calculate_backoff(20) == 120


# ── Test 2: Supervisor check_circuit_breaker ──────────────────────────────────
def test_supervisor_circuit_breaker():
    """Verify circuit breaker trips only when consecutive failure threshold is hit."""
    assert supervisor.check_circuit_breaker(0) is False
    assert supervisor.check_circuit_breaker(1) is False
    assert supervisor.check_circuit_breaker(19) is False
    assert supervisor.check_circuit_breaker(20) is True
    assert supervisor.check_circuit_breaker(25) is True


# ── Test 3: Supervisor logging and start_watchdog mock ────────────────────────
def test_supervisor_logging_and_start_watchdog(tmp_path):
    """Verify supervisor log writing to custom file and start_watchdog process launch."""
    log_target = tmp_path / "supervisor_test.log"
    supervisor.log("Test supervisor heartbeat", log_file=str(log_target))

    assert log_target.exists()
    content = log_target.read_text(encoding="utf-8")
    assert "[SUP] Test supervisor heartbeat" in content
    assert "UTC" in content

    # Test start_watchdog with mocked subprocess.Popen
    mock_proc = MagicMock()
    mock_proc.pid = 998811

    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        pid = supervisor.start_watchdog(
            python_bin="custom_python.exe",
            watchdog_script="custom_watchdog.py",
            base_dir=str(tmp_path),
            creationflags=0,
        )

    assert pid == 998811
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert args[0] == ["custom_python.exe", "custom_watchdog.py"]
    assert kwargs["cwd"] == str(tmp_path)


# ── Test 4: OmniCommand _compute_grade ────────────────────────────────────────
def test_omnicommand_compute_grade():
    """Verify OmniCommand win rate tier grading logic."""
    assert omnicommand_server._compute_grade(95.0) == "A+"
    assert omnicommand_server._compute_grade(90.1) == "A+"
    assert omnicommand_server._compute_grade(90.0) == "A"
    assert omnicommand_server._compute_grade(85.1) == "A"
    assert omnicommand_server._compute_grade(85.0) == "B"
    assert omnicommand_server._compute_grade(75.0) == "B"
    assert omnicommand_server._compute_grade(74.9) == "C"
    assert omnicommand_server._compute_grade(0.0) == "C"


# ── Test 5: OmniCommand read_live_status Fallback ─────────────────────────────
def test_omnicommand_read_live_status_fallback(tmp_path):
    """Verify read_live_status returns structured fallback when file is missing."""
    # Point STATUS_FILE to non-existent file
    with patch("omnicommand_server.STATUS_FILE", tmp_path / "non_existent.json"), \
         patch("omnicommand_server._status_cache", {}), \
         patch("omnicommand_server._status_cache_ts", 0.0):
        status = omnicommand_server.read_live_status()

    assert isinstance(status, dict)
    assert status.get("status") == "STANDBY"
    assert status.get("symbol") == "XAUUSD"
    assert status.get("balance") == 10000.0
    assert "risk_guard" in status
    assert "error" in status


# ── Test 6: OmniCommand _enrich_live_status ───────────────────────────────────
def test_omnicommand_enrich_live_status():
    """Verify _enrich_live_status injects required dashboard, risk guard, and wave fields."""
    raw = {
        "status": "ACTIVE_SCALPING",
        "current_price": 2405.50,
        "win_rate": 82.5,
        "trading_halted": False,
        "balance": 10500.0,
    }

    enriched = omnicommand_server._enrich_live_status(raw)
    assert enriched["grade"] == "B"
    assert enriched["win_rate_pct"] == 82.5
    assert enriched["ema_cross"] == "NEUTRAL"
    assert enriched["circuit_breaker_fired"] is False
    assert "risk_guard" in enriched
    assert enriched["risk_guard"]["balance_floor_halted"] is False
    assert "ma_trend_filter" in enriched
    assert enriched["ma_trend_filter"]["wave"] == 59
    assert "opening_range_breakout" in enriched
    assert enriched["opening_range_breakout"]["wave"] == 61


# ── Test 7: Wave 19 Volatility TPSL Adjuster ──────────────────────────────────
def test_wave19_volatility_tpsl_high_and_low_vol():
    """Verify Wave 19 ATR proxy and volatility-based TP/SL adjustments."""
    adjuster = VolatilityTPSLAdjuster()

    # High volatility closes (ATR ~ 1.5) and high vol session (vol_index=2.0)
    closes_high = [2400.0 + (i * 1.5) for i in range(20)]
    tp_high, sl_high = adjuster.adjusted_tpsl(
        closes=closes_high,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 2.0},
    )
    assert tp_high == 67.5  # 45.0 * 1.5x
    assert sl_high == 30.0

    # Low volatility closes (ATR ~ 0.05) and low vol session (vol_index=0.2)
    closes_low = [2400.0 + (i * 0.05) for i in range(20)]
    tp_low, sl_low = adjuster.adjusted_tpsl(
        closes=closes_low,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 0.2},
    )
    assert tp_low == round(45.0 * 0.75, 1)  # 33.8
    assert sl_low == round(30.0 * 0.85, 1)  # 25.5

    # Corrupt closes / error handling fallback
    tp_fb, sl_fb = adjuster.adjusted_tpsl(closes=None, base_tp_pips=-10.0, base_sl_pips=0.0)
    assert tp_fb == 45.0
    assert sl_fb == 30.0


# ── Test 8: Wave 20 Spike Filter Single Tick Spike ────────────────────────────
def test_wave20_spike_filter_single_tick_spike():
    """Verify abnormal tick-to-tick spikes trigger cooldown blocking."""
    sf = SpikeFilter(spike_ratio_threshold=4.0, cooldown_sec=60.0)

    # Establish baseline with 10 normal small price changes (0.1 each)
    base_time = 100000.0
    price = 2400.0
    for i in range(10):
        next_price = price + 0.1
        ok, reason = sf.check(next_price, price, now_ts=base_time + i)
        assert ok is True
        assert reason == "OK"
        price = next_price

    # Sudden price spike (1.5 move vs 0.1 average = 15x ratio >= 4.0 threshold)
    spike_price = price + 1.5
    ok_spike, reason_spike = sf.check(spike_price, price, now_ts=base_time + 11)
    assert ok_spike is False
    assert "SPIKE_DETECTED" in reason_spike
    assert sf.is_blocked(now_ts=base_time + 12) is True

    # Cooldown in effect at base_time + 30
    ok_cd, reason_cd = sf.check(spike_price + 0.05, spike_price, now_ts=base_time + 30)
    assert ok_cd is False
    assert "SPIKE_COOLDOWN" in reason_cd

    # Cooldown expires after 60s
    assert sf.is_blocked(now_ts=base_time + 72) is False


# ── Test 9: Wave 20 Spike Filter Cluster Detection ────────────────────────────
def test_wave20_spike_filter_cluster_limit():
    """Verify multiple smaller spikes within cluster window trigger cluster block."""
    sf = SpikeFilter(cluster_window_sec=300.0, cluster_count_limit=3, cooldown_sec=120.0)

    now = 50000.0
    # Artificially record 3 spike timestamps in window
    sf._spike_timestamps.extend([now - 200, now - 100, now - 10])

    # Feed enough changes so it doesn't return early due to history < 5
    for _ in range(6):
        sf._recent_changes.append(0.2)

    # Normal tick change (ratio < 4.0)
    ok, reason = sf.check(2400.25, 2400.20, now_ts=now)
    assert ok is False
    assert "SPIKE_CLUSTER:3_in_5min" in reason
    assert sf.is_blocked(now_ts=now + 5) is True

    # Reset clears cluster and cooldown state
    sf.reset()
    assert sf.is_blocked(now_ts=now + 5) is False
    assert sf.info(now_ts=now)["spikes_in_5min"] == 0


# ── Test 10: SignalEngine Resilience and Confluence ───────────────────────────
def test_signal_engine_resilience_and_confluence():
    """Verify SignalEngine get_signal_safe error containment and indicator calculation."""
    engine = SignalEngine({"bb_period": 10, "rsi_period": 7})

    # Empty prices fallback
    safe_out = engine.get_signal_safe([])
    assert safe_out["signal"] == "HOLD"
    assert safe_out["confidence"] == 0.0
    assert safe_out["tier"] == 3

    # Non-finite prices fallback
    safe_nan = engine.get_signal_safe([2400.0, float("nan"), 2405.0])
    assert safe_nan["signal"] == "HOLD"
    assert safe_nan["confidence"] == 0.0

    # Thread-safe config update
    engine.update_config({"bb_period": 15, "rsi_period": 9})
    info = engine.info()
    assert info["bb_period"] == 15
    assert info["rsi_period"] == 9

    # Valid price series
    valid_prices = [2400.0 + (i * 0.2) for i in range(30)]
    signal_res = engine.get_signal(valid_prices)
    assert signal_res["signal"] in ("BUY", "SELL", "HOLD")
    assert 0.0 <= signal_res["confidence"] <= 1.0
    assert "bb" in signal_res
    assert "rsi" in signal_res
    assert "macd" in signal_res
    assert "ema_cross" in signal_res
