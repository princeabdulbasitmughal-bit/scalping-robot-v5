"""
Unit tests for Batch 29: Wave & Python Engine Modules Hardening
Covers:
- wave9_risk_manager (RLock, input sanitization, now_ts injection, reset, info, state persistence)
- wave12_telegram_alerts (RLock, testable sender_fn, now_dt/now_ts injection, input validation, update_config, reset, stats)
- python_engine.signal_engine (RLock, update_config, info, get_signal_safe)
- python_engine.scalping_engine.EconomicNewsFilter (RLock, is_blackout timestamp sanitization, currency filtering)
- python_engine.scalping_engine.ScalpingRobotV5 (RLock, calculate_indicators bar sanitization, reset)
"""

import math
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from wave9_risk_manager import RiskManager
from wave12_telegram_alerts import TelegramAlerter
from python_engine.signal_engine import SignalEngine
from python_engine.scalping_engine import EconomicNewsFilter, ScalpingRobotV5, ScalpingSignal


# ==============================================================================
# Wave 9: RiskManager Hardened
# ==============================================================================
def test_wave9_risk_manager_hardened():
    rm = RiskManager(config={"max_daily_loss_usd": 200.0, "max_drawdown_pct": 10.0, "starting_balance": 10000.0})

    # 1. Input sanitization: invalid balance or equity fails closed
    assert rm.should_trade(None, 10000.0, 0.0, 0.0, [], "BUY")["allowed"] is False
    assert rm.should_trade(-100.0, 10000.0, 0.0, 0.0, [], "BUY")["allowed"] is False
    assert rm.should_trade(float("nan"), 10000.0, 0.0, 0.0, [], "BUY")["allowed"] is False
    assert rm.should_trade(10000.0, None, 0.0, 0.0, [], "BUY")["allowed"] is False
    assert rm.should_trade(10000.0, -50.0, 0.0, 0.0, [], "BUY")["allowed"] is False
    assert rm.should_trade(10000.0, float("nan"), 0.0, 0.0, [], "BUY")["allowed"] is False

    # 2. Drawdown percent calculation with invalid balance returns 100.0 (fail-closed)
    assert rm.drawdown_pct(None) == 100.0
    assert rm.drawdown_pct(float("nan")) == 100.0
    assert rm.drawdown_pct(-10.0) == 100.0
    assert rm.drawdown_pct(10000.0) == 0.0
    assert rm.drawdown_pct(9500.0) == 5.0

    # 3. Drawdown lot scale tiers
    assert rm.drawdown_lot_scale(10000.0) == 1.0
    assert rm.drawdown_lot_scale(9700.0) == 0.75  # 3% dd (>= 2%)
    assert rm.drawdown_lot_scale(9500.0) == 0.5   # 5% dd (>= 4%)
    assert rm.drawdown_lot_scale(9300.0) == 0.25  # 7% dd (>= 6%)
    assert rm.drawdown_lot_scale(9100.0) == 0.1   # 9% dd (>= 8%)

    # 4. Max drawdown breach (10% of 10000 -> 9000 balance)
    assert rm.is_max_drawdown_hit(9000.0) is True
    res_halt = rm.should_trade(8900.0, 8900.0, 0.0, 0.0, [], "BUY")
    assert res_halt["allowed"] is False
    assert "MAX_DRAWDOWN_HIT" in res_halt["reason"]
    assert res_halt["lot_scale"] == 0.0

    # 5. Frequency governor with deterministic now_ts
    base_t = 1000000.0
    for i in range(20):
        assert rm.can_trade_frequency(now_ts=base_t + i) is True
        rm.record_trade(now_ts=base_t + i)
    # 21st trade within the same hour should be rejected
    assert rm.can_trade_frequency(now_ts=base_t + 25) is False
    # After 3601 seconds, sliding window slides out oldest trades
    assert rm.can_trade_frequency(now_ts=base_t + 3605) is True

    # 6. Correlation check with noisy open positions list
    assert rm.correlation_ok(None, "BUY") is True
    assert rm.correlation_ok([None, "not_a_dict"], "BUY") is True
    assert rm.correlation_ok([{"type": "SELL"}], "BUY") is True
    assert rm.correlation_ok([{"type": "BUY"}], "BUY") is False

    # 7. Telemetry info and reset
    info = rm.info()
    assert "peak_balance" in info
    assert "equity_ema" in info
    assert info["trade_times_count"] == 15

    rm.reset(starting_balance=12000.0)
    assert rm.peak_balance == 12000.0
    assert len(rm._trade_times) == 0
    assert rm.can_trade_frequency(now_ts=base_t) is True

    # 8. State persistence to temp file
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp_path = tf.name
    try:
        rm.peak_balance = 15000.0
        rm._equity_ema = 14950.0
        rm.save_state(tmp_path)

        rm2 = RiskManager()
        rm2.load_state(tmp_path)
        assert rm2.peak_balance == 15000.0
        assert rm2._equity_ema == 14950.0
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        Path(tmp_path + ".tmp").unlink(missing_ok=True)


# ==============================================================================
# Wave 12: TelegramAlerter Hardened
# ==============================================================================
def test_wave12_telegram_alerts_hardened():
    sent_payloads = []

    def mock_sender(text: str) -> bool:
        sent_payloads.append(text)
        return True

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        cfg_path = tf.name

    try:
        ta = TelegramAlerter(config_path=cfg_path, sender_fn=mock_sender)
        assert ta.get_stats()["enabled"] is False

        # 1. Disabled alerter returns False
        assert ta.send_alert("Test alert 1") is False
        assert len(sent_payloads) == 0

        # 2. Enable alerter and update config
        ta.update_config({
            "enabled": True,
            "min_alert_interval_sec": 30.0,
            "bot_token": "mock_token",
            "chat_id": "mock_chat",
        })
        assert ta.get_stats()["enabled"] is True

        # 3. Send alert with deterministic now_ts
        t0 = 2000000.0
        assert ta.send_alert("First alert", now_ts=t0) is True
        time.sleep(0.05)  # allow background thread to execute mock_sender
        assert len(sent_payloads) == 1
        assert "First alert" in sent_payloads[0]

        # 4. Rate-limit blocks within 30s
        assert ta.send_alert("Second alert too soon", now_ts=t0 + 10.0) is False

        # 5. Force bypasses rate-limit
        assert ta.send_alert("Forced alert", force=True, now_ts=t0 + 15.0) is True
        time.sleep(0.05)
        assert len(sent_payloads) == 2
        assert "Forced alert" in sent_payloads[1]

        # 6. Formatted alert helpers with now_dt and non-finite guards
        dt_test = datetime(2026, 10, 17, 12, 30, tzinfo=timezone.utc)
        ta.alert_trade_open("BUY", 2450.50, 2440.0, 2470.0, 0.05, now_dt=dt_test, force=True)
        ta.alert_trade_close("BUY", 50.25, "TP_REACHED", 10050.25, now_dt=dt_test, force=True)
        ta.alert_circuit_breaker("DAILY_LOSS_LIMIT", 9800.0, -200.0, now_dt=dt_test)
        ta.alert_daily_summary(10500.0, 500.0, 8, 2, 80.0, 10, now_dt=dt_test)

        time.sleep(0.1)
        assert len(sent_payloads) >= 6

        # 7. Check NaN/None input safety in alert helpers (zero exceptions)
        ta.alert_trade_open("SELL", float("nan"), None, 2400.0, 0.01, force=True)
        ta.alert_trade_close("SELL", float("nan"), "TEST", None, force=True)

        # 8. Reset telemetry
        ta.reset()
        stats = ta.get_stats()
        assert stats["last_sent"] == 0.0
        assert stats["sent_count"] == 0
    finally:
        Path(cfg_path).unlink(missing_ok=True)
        Path(cfg_path + ".tmp").unlink(missing_ok=True)


# ==============================================================================
# Python Engine: SignalEngine Hardened
# ==============================================================================
def test_python_engine_signal_engine_hardened():
    se = SignalEngine({"bb_period": 10, "rsi_period": 8})

    # 1. Telemetry and update_config
    info = se.info()
    assert info["bb_period"] == 10
    assert info["rsi_period"] == 8

    se.update_config({"bb_period": 15, "bb_std": 2.5})
    assert se.bb_period == 15
    assert se.bb_std == 2.5

    # 2. get_signal_safe with empty and invalid inputs
    res_empty = se.get_signal_safe([])
    assert res_empty["signal"] == "HOLD"
    assert res_empty["confidence"] == 0.0
    assert any("fallback" in r for r in res_empty["reasons"])

    res_nan = se.get_signal_safe([float("nan"), 100.0])
    assert res_nan["signal"] == "HOLD"
    assert res_nan["confidence"] == 0.0

    # 3. get_signal_safe with valid flat prices
    res_valid = se.get_signal_safe([100.0] * 30)
    assert res_valid["signal"] == "HOLD"
    assert res_valid["rsi"] == 50.0
    assert "bb" in res_valid
    assert "macd" in res_valid


# ==============================================================================
# Python Engine: EconomicNewsFilter Hardened
# ==============================================================================
def test_python_engine_economic_news_filter_hardened():
    nf = EconomicNewsFilter(pre_minutes=15, post_minutes=30)
    nf.clear_events()
    assert len(nf.events) == 0

    # 1. Add event with datetime and verify blackout window
    event_dt = datetime(2026, 10, 17, 14, 0, 0, tzinfo=timezone.utc)
    nf.add_event(event_dt, "US Non-Farm Payrolls", currency="USD", impact="HIGH")
    assert len(nf.events) == 1

    event_ts = event_dt.timestamp()

    # 10 minutes before event -> blackout
    is_blk, ev = nf.is_blackout(current_time=event_ts - 600)
    assert is_blk is True
    assert ev["event"] == "US Non-Farm Payrolls"
    assert ev["phase"] == "PRE_EVENT"

    # 20 minutes before event -> outside pre window (15m) -> False
    is_blk2, _ = nf.is_blackout(current_time=event_ts - 1200)
    assert is_blk2 is False

    # 20 minutes after event -> inside post window (30m) -> True
    is_blk3, ev3 = nf.is_blackout(current_time=event_ts + 1200)
    assert is_blk3 is True
    assert ev3["phase"] == "POST_EVENT"

    # 35 minutes after event -> outside post window -> False
    is_blk4, _ = nf.is_blackout(current_time=event_ts + 2100)
    assert is_blk4 is False

    # 2. Currency filtering: EUR query should not trigger on USD event
    is_blk_eur, _ = nf.is_blackout(current_time=event_ts - 300, currency="EUR")
    assert is_blk_eur is False

    # 3. Invalid/non-finite timestamp in is_blackout returns (False, None)
    assert nf.is_blackout(current_time=-100)[0] is False
    assert nf.is_blackout(current_time=float("nan"))[0] is False


# ==============================================================================
# Python Engine: ScalpingRobotV5 Hardened
# ==============================================================================
def test_python_engine_scalping_robot_v5_hardened():
    robot = ScalpingRobotV5({"symbol": "XAUUSD", "bb_period": 10, "rsi_period": 8, "atr_period": 8})

    # 1. calculate_indicators with empty or invalid bar lists returns {}
    assert robot.calculate_indicators([]) == {}
    assert robot.calculate_indicators([{"close": float("nan")}] * 30) == {}
    assert robot.calculate_indicators(["invalid", None, 123]) == {}

    # 2. calculate_indicators with clean synthetic bars computes indicators
    clean_bars = []
    base_price = 2400.0
    for i in range(40):
        clean_bars.append({
            "open": base_price + (i % 3),
            "high": base_price + (i % 3) + 2.0,
            "low": base_price + (i % 3) - 1.0,
            "close": base_price + (i % 3) + 1.0,
            "volume": 100 + i,
            "timestamp": 1700000000 + (i * 60)
        })

    inds = robot.calculate_indicators(clean_bars)
    assert "fast_ema" in inds
    assert "slow_ema" in inds
    assert "bb_upper" in inds
    assert "bb_lower" in inds
    assert "rsi" in inds
    assert "atr" in inds
    assert "regime" in inds

    # 3. reset restores initial state
    robot.volatility_halt_counter = 5
    robot.shield_status = {"status": "HALTED", "reason": "TEST", "halted": True}
    robot.open_positions.append({"ticket": 123})
    robot.trade_history.append({"ticket": 123, "pnl": 10.0})

    robot.reset()
    assert robot.volatility_halt_counter == 0
    assert robot.shield_status["halted"] is False
    assert len(robot.open_positions) == 0
    assert len(robot.trade_history) == 0
