"""
tests/test_batch36.py - Comprehensive Unit Tests for Batch 36 Components:
1. wave44_price_velocity_filter normal tick velocity tracking
2. wave44_price_velocity_filter spike blocking, recovery, and reset
3. performance_monitor calculate_grade scoring and non-finite guards
4. performance_monitor evaluate_and_report with mock files and alert conditions
5. auto_install_to_mt4 discovery routines and error resilience
6. python_engine.signal_engine Bollinger Bands and RSI calculations
7. python_engine.signal_engine MACD and get_signal_safe confluence fallback
8. python_engine.scalping_engine indicator calculation and regime determination
9. python_engine.scalping_engine EconomicNewsFilter blackout windows
10. python_engine package export integrity for Batch 36 symbols
"""

import math
import time
import json
from pathlib import Path
import pytest

from wave44_price_velocity_filter import PriceVelocityFilter
import performance_monitor
from performance_monitor import calculate_grade, evaluate_and_report, _safe_float
import auto_install_to_mt4
from python_engine.signal_engine import SignalEngine
from python_engine.scalping_engine import ScalpingRobotV5, EconomicNewsFilter, MarketRegime, ScalpingSignal
import python_engine


def test_wave44_price_velocity_filter_basic():
    """Verify PriceVelocityFilter allows entries during normal, steady markets."""
    pv = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)
    pv.reset()

    now = 1000.0
    # Add gentle ticks: 2400.0 -> 2400.2 (2 pips change)
    pv.update(2400.0, now_ts=now)
    pv.update(2400.2, now_ts=now + 1.0)

    assert pv.is_entry_blocked(now_ts=now + 1.5) is False
    allowed, reason = pv.is_trading_allowed(now_ts=now + 1.5)
    assert allowed is True
    assert reason == ""

    info = pv.info()
    assert info["wave"] == 44
    assert info["velocity_pips"] == 2.0
    assert info["blocked"] is False


def test_wave44_price_velocity_filter_surge():
    """Verify PriceVelocityFilter blocks entries during fast surges and recovers after window."""
    pv = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)
    pv.reset()

    now = 2000.0
    # Price surges from 2400.0 to 2401.0 (10 pips) within 1.0s
    pv.update(2400.0, now_ts=now)
    pv.update(2401.0, now_ts=now + 1.0)

    # Within 3s window -> blocked
    assert pv.is_entry_blocked(now_ts=now + 1.5) is True
    allowed, reason = pv.is_trading_allowed(now_ts=now + 1.5)
    assert allowed is False
    assert "VELOCITY_LIMIT" in reason

    # After 3.5s beyond surge -> window expires, unblocks
    assert pv.is_entry_blocked(now_ts=now + 4.5) is False
    allowed_later, _ = pv.is_trading_allowed(now_ts=now + 4.5)
    assert allowed_later is True

    # Reset clears everything
    pv.reset()
    assert pv.info()["velocity_pips"] == 0.0
    assert pv.info()["total_blocks"] == 0


def test_performance_monitor_grading():
    """Verify performance grade calculation across ranges and non-finite values."""
    assert calculate_grade(95.0) == "A+"
    assert calculate_grade(88.0) == "A"
    assert calculate_grade(76.0) == "B"
    assert calculate_grade(75.0) == "B"
    assert calculate_grade(70.0) == "C"
    assert calculate_grade(0.0) == "C"

    # Non-finite values
    assert calculate_grade(float("nan")) == "C"
    assert calculate_grade(float("inf")) == "C"
    assert calculate_grade("invalid") == "C"

    # _safe_float validation
    assert _safe_float(None, 10.0) == 10.0
    assert _safe_float("25.5") == 25.5
    assert _safe_float(float("nan"), 5.0) == 5.0


def test_performance_monitor_evaluation(tmp_path):
    """Verify evaluate_and_report with mock status file and alert triggers."""
    mock_status = tmp_path / "mock_status.json"
    mock_report = tmp_path / "mock_report.txt"

    # Test missing file
    assert evaluate_and_report(status_file=mock_status, report_file=mock_report) is False

    # Create healthy status
    status_data = {
        "status": "ACTIVE_SCALPING",
        "account_mode": "PAPER",
        "symbol": "XAUUSD",
        "balance": 10500.0,
        "equity": 10550.0,
        "daily_pnl": 50.0,
        "win_rate": 88.0,
        "total_trades": 25,
        "current_price": 2405.50
    }
    mock_status.write_text(json.dumps(status_data), encoding="utf-8")

    assert evaluate_and_report(status_file=mock_status, report_file=mock_report) is True
    assert mock_report.exists()
    content = mock_report.read_text(encoding="utf-8")
    assert "Performance Grade   : A" in content
    assert "Win Rate            : 88.00%" in content
    assert "[OK] No active alerts" in content

    # Test alert condition (daily_pnl < -100)
    status_data["daily_pnl"] = -150.0
    mock_status.write_text(json.dumps(status_data), encoding="utf-8")
    assert evaluate_and_report(status_file=mock_status, report_file=mock_report) is True
    content_alert = mock_report.read_text(encoding="utf-8")
    assert "ALERT: Daily loss >$100" in content_alert


def test_auto_install_mt4_discovery():
    """Verify find_mt4_directories returns list without unhandled errors."""
    res = auto_install_to_mt4.find_mt4_directories()
    assert isinstance(res, list)

    # Verify install_to_target handles non-existent or invalid target safely
    res_install = auto_install_to_mt4.install_to_target("Z:\\NonExistentTargetDirectory12345")
    assert isinstance(res_install, list)


def test_signal_engine_bollinger_and_rsi():
    """Verify SignalEngine indicator mathematics for Bollinger Bands and RSI."""
    engine = SignalEngine({"bb_period": 10, "rsi_period": 10})
    prices = [2400.0 + i * 0.5 for i in range(25)]

    # Bollinger Bands
    bb = engine.compute_bb(prices)
    assert bb["upper"] > bb["middle"] > bb["lower"]
    assert bb["width"] > 0.0

    # RSI on rising prices
    rsi_up = engine.compute_rsi(prices)
    assert rsi_up > 70.0

    # Non-finite prices error
    with pytest.raises(ValueError):
        engine.compute_bb([2400.0, float("nan")])


def test_signal_engine_macd_and_confluence():
    """Verify SignalEngine MACD and exception-safe get_signal_safe."""
    engine = SignalEngine({"macd_fast": 6, "macd_slow": 12, "macd_signal": 4})
    prices = [2400.0 + math.sin(i * 0.2) * 5.0 for i in range(30)]

    macd = engine.compute_macd(prices)
    assert "macd_line" in macd
    assert "signal_line" in macd
    assert "histogram" in macd
    assert macd["cross"] in ("BUY", "SELL", "NONE")

    signal_info = engine.get_signal(prices)
    assert signal_info["signal"] in ("BUY", "SELL", "HOLD")
    assert 0.0 <= signal_info["confidence"] <= 1.0

    # Safe fallback with empty or degenerate list
    fallback = engine.get_signal_safe([])
    assert fallback["signal"] == "HOLD"
    assert fallback["confidence"] == 0.0


def test_scalping_engine_indicators_calculation():
    """Verify ScalpingRobotV5 calculate_indicators extracts complete indicator suite."""
    robot = ScalpingRobotV5()
    
    # Insufficient bars
    assert robot.calculate_indicators([]) == {}

    # Valid synthetic bars (35 bars)
    bars = []
    base_price = 2400.0
    for i in range(40):
        p = base_price + math.sin(i * 0.3) * 2.0
        bars.append({
            "open": p - 0.1,
            "high": p + 0.3,
            "low": p - 0.3,
            "close": p,
            "volume": 100,
            "timestamp": "2026-10-17 12:00:00"
        })

    indicators = robot.calculate_indicators(bars)
    assert "bb_upper" in indicators
    assert "rsi" in indicators
    assert "atr" in indicators
    assert "volatility_regime" in indicators
    assert indicators["volatility_regime"] in (
        MarketRegime.LOW_VOLATILITY,
        MarketRegime.NORMAL_VOLATILITY,
        MarketRegime.HIGH_VOLATILITY,
        MarketRegime.EXTREME_SPIKE
    )


def test_economic_news_filter_blackout():
    """Verify EconomicNewsFilter detects blackout periods and clear periods."""
    news = EconomicNewsFilter(pre_minutes=15, post_minutes=30)
    news.clear_events()

    event_time = 1700000000.0
    news.add_event(event_time, "US Non-Farm Payrolls", currency="USD", impact="HIGH")

    # 10 minutes before event -> blackout active
    in_blackout, ev = news.is_blackout(current_time=event_time - 600)
    assert in_blackout is True
    assert ev is not None
    assert ev["event"] == "US Non-Farm Payrolls"
    assert ev["phase"] == "PRE_EVENT"

    # 2 hours before event -> no blackout
    not_blackout, _ = news.is_blackout(current_time=event_time - 7200)
    assert not_blackout is False

    # Clear events
    news.clear_events()
    assert len(news.events) == 0


def test_python_engine_batch36_exports():
    """Verify python_engine exports SignalEngine, EconomicNewsFilter, and MarketRegime."""
    assert hasattr(python_engine, "SignalEngine")
    assert hasattr(python_engine, "EconomicNewsFilter")
    assert hasattr(python_engine, "MarketRegime")
    assert hasattr(python_engine, "ScalpingRobotV5")
    assert python_engine.SignalEngine is SignalEngine
    assert python_engine.EconomicNewsFilter is EconomicNewsFilter
    assert python_engine.MarketRegime is MarketRegime
