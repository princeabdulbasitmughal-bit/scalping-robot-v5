"""
tests/test_batch125.py
Unit tests for Batch 125:
- wave12_telegram_alerts.py (TelegramAlerter, config management, rate-limiting, trade alerts, circuit breaker/summary alerts, risk aliases)
- wave13_ml_predictor.py (LinearRegressor OLS fit, MLPredictor direction prediction, signal agreement and boost, accuracy tracking, risk aliases)
"""

import math
import time
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import wave12_telegram_alerts as w12
import wave13_ml_predictor as w13


class TestBatch125(unittest.TestCase):

    def test_wave12_alerter_init_and_config(self):
        """Test TelegramAlerter initialization, config loading, and update_config."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "test_telegram_config.json"
            alerter = w12.TelegramAlerter(config_path=str(cfg_path))
            self.assertTrue(cfg_path.exists())
            self.assertFalse(alerter._config.get("enabled", False))

            # Update and persist
            alerter.update_config({"bot_token": "TEST_TOKEN_123", "chat_id": "123456", "enabled": True}, persist=True)
            self.assertEqual(alerter._config["bot_token"], "TEST_TOKEN_123")
            self.assertTrue(alerter._config["enabled"])

    def test_wave12_send_alert_rate_limiting(self):
        """Test send_alert rate-limiting and force bypass."""
        sent = []
        def mock_sender(text):
            sent.append(text)
            return True

        alerter = w12.TelegramAlerter(sender_fn=mock_sender)
        alerter.update_config({"enabled": True, "min_alert_interval_sec": 60})

        # First alert sent
        alerter.send_alert("Alert 1")
        self.assertEqual(len(sent), 1)

        # Immediate second alert suppressed by rate limit
        alerter.send_alert("Alert 2")
        self.assertEqual(len(sent), 1)

        # Forced alert bypasses rate limit
        alerter.send_alert("Alert 3 (Forced)", force=True)
        self.assertEqual(len(sent), 2)
        self.assertIn("Alert 3 (Forced)", sent[-1])

    def test_wave12_alert_trade_open_and_close(self):
        """Test alert_trade_open and alert_trade_close message formatting."""
        sent = []
        alerter = w12.TelegramAlerter(sender_fn=lambda t: (sent.append(t), True)[1])
        alerter.update_config({"enabled": True})

        # Trade Open: direction, entry, sl, tp, lot
        alerter.alert_trade_open("BUY", 2400.50, 2390.0, 2415.0, 0.05, force=True)
        self.assertEqual(len(sent), 1)
        self.assertIn("BUY OPENED", sent[0])
        self.assertIn("2400.50", sent[0])

        # Trade Close: direction, pnl, reason, balance
        alerter.alert_trade_close("BUY", 72.50, "TP_HIT", 10072.50, force=True)
        self.assertEqual(len(sent), 2)
        self.assertIn("WIN CLOSED", sent[1])
        self.assertIn("72.50", sent[1])

    def test_wave12_alert_circuit_breaker_and_summary(self):
        """Test alert_circuit_breaker and alert_daily_summary."""
        sent = []
        alerter = w12.TelegramAlerter(sender_fn=lambda t: (sent.append(t), True)[1])
        alerter.update_config({"enabled": True})

        # Circuit breaker
        alerter.alert_circuit_breaker("Daily Drawdown Limit Exceeded", balance=9750.0, daily_pnl=-250.0)
        self.assertEqual(len(sent), 1)
        self.assertIn("CIRCUIT BREAKER FIRED", sent[0])
        self.assertIn("Daily Drawdown Limit", sent[0])

        # Daily summary
        alerter.alert_daily_summary(balance=10250.0, daily_pnl=250.0, wins=8, losses=2, win_rate=80.0, total_trades=10)
        self.assertEqual(len(sent), 2)
        self.assertIn("DAILY SUMMARY", sent[1])
        self.assertIn("80.0%", sent[1])

    def test_wave12_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on TelegramAlerter and module level."""
        alerter = w12.TelegramAlerter()
        self.assertFalse(alerter.is_entry_blocked())
        self.assertFalse(alerter.is_blocked())
        self.assertFalse(w12.is_entry_blocked())
        self.assertFalse(w12.is_blocked())

    def test_wave13_linear_regression_fit(self):
        """Test LinearRegressor OLS linear fit and defense against invalid inputs."""
        reg = w13.LinearRegressor()
        # Empty and short lists
        self.assertEqual(reg.fit([])["slope"], 0.0)
        self.assertEqual(reg.fit([2400.0, 2401.0])["r_squared"], 0.0)

        # Upward line: y = 2x + 10
        y_up = [10.0 + 2.0 * i for i in range(10)]
        res_up = reg.fit(y_up)
        self.assertAlmostEqual(res_up["slope"], 2.0, places=2)
        self.assertAlmostEqual(res_up["r_squared"], 1.0, places=2)

        # Downward line: y = -1.5x + 50
        y_down = [50.0 - 1.5 * i for i in range(10)]
        res_down = reg.fit(y_down)
        self.assertAlmostEqual(res_down["slope"], -1.5, places=2)
        self.assertAlmostEqual(res_down["r_squared"], 1.0, places=2)

    def test_wave13_ml_predictor_predict_direction(self):
        """Test MLPredictor direction classification (UP, DOWN, NEUTRAL)."""
        pred = w13.MLPredictor(window=20, min_r2=0.20)
        
        # Upward series
        closes_up = [2400.0 + i * 0.5 for i in range(25)]
        res_up = pred.predict(closes_up)
        self.assertEqual(res_up["direction"], "UP")
        self.assertGreaterEqual(res_up["confidence"], 50)

        # Downward series
        closes_down = [2420.0 - i * 0.5 for i in range(25)]
        res_down = pred.predict(closes_down)
        self.assertEqual(res_down["direction"], "DOWN")
        self.assertGreaterEqual(res_down["confidence"], 50)

        # Flat / choppy series
        closes_flat = [2400.0 + (0.01 if i % 2 == 0 else -0.01) for i in range(25)]
        res_flat = pred.predict(closes_flat)
        self.assertEqual(res_flat["direction"], "NEUTRAL")

    def test_wave13_predict_signal_agreement(self):
        """Test predict_signal_agreement boost and alignment."""
        pred = w13.MLPredictor(window=20, min_r2=0.20)
        closes_up = [2400.0 + i * 0.5 for i in range(25)]

        # BUY with UP prediction agrees and boosts lot
        ag_buy = pred.predict_signal_agreement(closes_up, signal="BUY")
        self.assertTrue(ag_buy["agree"])
        self.assertGreaterEqual(ag_buy["boost"], 1.0)

        # SELL with UP prediction does not agree (disagreement)
        ag_sell = pred.predict_signal_agreement(closes_up, signal="SELL")
        self.assertFalse(ag_sell["agree"])

    def test_wave13_accuracy_tracking_and_reset(self):
        """Test record_outcome tracking and reset."""
        pred = w13.MLPredictor()
        self.assertEqual(pred.accuracy, 0.0)

        pred.record_outcome("UP", "UP")      # Hit
        pred.record_outcome("DOWN", "DOWN")  # Hit
        pred.record_outcome("UP", "DOWN")    # Miss
        self.assertAlmostEqual(pred.accuracy, 66.7, places=1)

        # Reset clears counters
        pred.reset()
        self.assertEqual(pred.accuracy, 0.0)

    def test_wave13_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on MLPredictor, LinearRegressor, and module level."""
        pred = w13.MLPredictor()
        reg = w13.LinearRegressor()
        self.assertFalse(pred.is_entry_blocked())
        self.assertFalse(pred.is_blocked())
        self.assertFalse(reg.is_entry_blocked())
        self.assertFalse(reg.is_blocked())
        self.assertFalse(w13.is_entry_blocked())
        self.assertFalse(w13.is_blocked())


if __name__ == "__main__":
    unittest.main()
