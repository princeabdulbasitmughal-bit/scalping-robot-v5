"""
tests/test_batch109.py
======================
Unit tests for Batch 109:
- wave12_telegram_alerts.py (TelegramAlerter)
- wave13_ml_predictor.py (LinearRegressor, MLPredictor)
"""

import math
import os
from datetime import datetime, timezone
import pytest
from wave12_telegram_alerts import TelegramAlerter
from wave13_ml_predictor import LinearRegressor, MLPredictor


# =====================================================================
# TelegramAlerter Tests (wave12)
# =====================================================================

def test_telegram_alerter_init_and_config(tmp_path):
    cfg_file = str(tmp_path / "telegram_config.json")
    alerter = TelegramAlerter(config_path=cfg_file)
    assert alerter.is_entry_blocked() is False
    assert alerter.is_blocked() is False

    stats = alerter.get_stats()
    assert stats["enabled"] is False
    assert stats["sent_count"] == 0

    alerter.update_config({"enabled": True, "min_alert_interval_sec": 30}, persist=True)
    assert alerter._config["enabled"] is True
    assert alerter._config["min_alert_interval_sec"] == 30
    assert os.path.exists(cfg_file)


def test_telegram_alerter_disabled_by_default():
    sent_payloads = []
    alerter = TelegramAlerter(sender_fn=lambda txt: sent_payloads.append(txt))
    alerter.update_config({"enabled": False})

    res = alerter.send_alert("Test message")
    assert res is False
    assert len(sent_payloads) == 0


def test_telegram_alerter_rate_limiting_and_force():
    sent_payloads = []
    alerter = TelegramAlerter(sender_fn=lambda txt: sent_payloads.append(txt))
    alerter.update_config({"enabled": True, "min_alert_interval_sec": 60})

    t0 = 1000.0
    # First message: accepted
    ok1 = alerter.send_alert("Message 1", now_ts=t0)
    assert ok1 is True

    # Immediate second message within 60s: rejected by rate limit
    ok2 = alerter.send_alert("Message 2", now_ts=t0 + 10.0)
    assert ok2 is False

    # Forced message within 60s: accepted!
    ok3 = alerter.send_alert("Message 3 (Forced)", force=True, now_ts=t0 + 15.0)
    assert ok3 is True

    stats = alerter.get_stats()
    assert stats["sent_count"] == 2


def test_telegram_alerter_formatted_open_and_close():
    sent_payloads = []
    alerter = TelegramAlerter(sender_fn=lambda txt: sent_payloads.append(txt))
    alerter.update_config({"enabled": True, "alert_on_trade_open": True, "alert_on_trade_close": True})

    # Alert trade open
    alerter.alert_trade_open(direction="BUY", entry=2650.50, sl=2640.0, tp=2670.0, lot=0.05, force=True)
    # Alert trade close with boolean / malformed inputs
    alerter.alert_trade_close(direction="BUY", pnl=150.25, reason="TP_HIT", balance=10150.25, force=True)

    stats = alerter.get_stats()
    assert stats["sent_count"] == 2
    assert "OPENED" in alerter._sent_messages[0][1]
    assert "CLOSED" in alerter._sent_messages[1][1]
    assert "$+150.25" in alerter._sent_messages[1][1]


def test_telegram_alerter_circuit_breaker_and_summary():
    sent_payloads = []
    alerter = TelegramAlerter(sender_fn=lambda txt: sent_payloads.append(txt))
    alerter.update_config({"enabled": True})

    # Circuit breaker
    alerter.alert_circuit_breaker(reason="MAX_DAILY_LOSS", balance=9800.0, daily_pnl=-200.0)
    # Daily summary with boolean/invalid data
    alerter.alert_daily_summary(balance=9800.0, daily_pnl=-200.0, wins=2, losses=8, win_rate=20.0, total_trades=10)

    stats = alerter.get_stats()
    assert stats["sent_count"] == 2
    assert "CIRCUIT BREAKER FIRED" in alerter._sent_messages[0][1]
    assert "DAILY SUMMARY" in alerter._sent_messages[1][1]
    assert "Grade: <b>C</b>" in alerter._sent_messages[1][1]

    alerter.reset()
    assert alerter.get_stats()["sent_count"] == 0


# =====================================================================
# MLPredictor & LinearRegressor Tests (wave13)
# =====================================================================

def test_linear_regressor_fit():
    reg = LinearRegressor()
    assert reg.is_entry_blocked() is False
    assert reg.is_blocked() is False

    # Perfect linear line: y = 2.0 * x + 10.0
    y = [10.0 + 2.0 * i for i in range(10)]
    fit_res = reg.fit(y)
    assert fit_res["slope"] == pytest.approx(2.0, rel=1e-3)
    assert fit_res["intercept"] == pytest.approx(10.0, rel=1e-3)
    assert fit_res["r_squared"] == pytest.approx(1.0, rel=1e-3)

    # Short / bad inputs
    assert reg.fit(None)["slope"] == 0.0
    assert reg.fit([1.0, 2.0])["slope"] == 0.0
    assert reg.fit([5.0] * 10)["slope"] == 0.0


def test_ml_predictor_init_defaults():
    mlp = MLPredictor()
    assert mlp.window == 20
    assert mlp.min_r2 == 0.25
    assert mlp.is_entry_blocked() is False
    assert mlp.is_blocked() is False

    inf = mlp.info()
    assert inf["window"] == 20
    assert inf["accuracy_pct"] == 0.0

    # Bad parameter fallbacks
    bad_mlp = MLPredictor(window=-5, min_r2=True)
    assert bad_mlp.window == 20
    assert bad_mlp.min_r2 == 0.25


def test_ml_predictor_trending_up_prediction():
    mlp = MLPredictor(window=20, min_r2=0.20)
    # 20 bars rising steadily: 100.0 to 120.0
    closes = [100.0 + i * 1.0 for i in range(25)]
    pred = mlp.predict(closes)

    assert pred["direction"] == "UP"
    assert pred["confidence"] >= 50
    assert pred["slope"] > 0
    assert pred["r_squared"] > 0.9
    assert pred["momentum"] > 0


def test_ml_predictor_trending_down_prediction():
    mlp = MLPredictor(window=20, min_r2=0.20)
    # 20 bars falling steadily: 120.0 to 100.0
    closes = [120.0 - i * 1.0 for i in range(25)]
    pred = mlp.predict(closes)

    assert pred["direction"] == "DOWN"
    assert pred["confidence"] >= 50
    assert pred["slope"] < 0
    assert pred["r_squared"] > 0.9
    assert pred["momentum"] < 0


def test_ml_predictor_agreement_and_accuracy():
    mlp = MLPredictor(window=20, min_r2=0.20)
    up_closes = [100.0 + i * 1.0 for i in range(25)]

    # Agree with BUY on UP trend
    agr_buy = mlp.predict_signal_agreement(up_closes, signal="BUY")
    assert agr_buy["agree"] is True
    assert agr_buy["direction"] == "UP"
    assert agr_buy["boost"] >= 1.0

    # Disagree with SELL on UP trend
    agr_sell = mlp.predict_signal_agreement(up_closes, signal="SELL")
    assert agr_sell["agree"] is False

    # Accuracy tracking
    mlp.record_outcome(predicted_direction="UP", actual_direction="UP")      # hit
    mlp.record_outcome(predicted_direction="UP", actual_direction="UP")      # hit
    mlp.record_outcome(predicted_direction="UP", actual_direction="DOWN")    # miss
    mlp.record_outcome(predicted_direction="DOWN", actual_direction="DOWN")  # hit

    assert mlp.accuracy == 75.0  # 3 / 4 hits = 75.0%
    mlp.reset()
    assert mlp.accuracy == 0.0
    assert mlp.last_prediction == {}
