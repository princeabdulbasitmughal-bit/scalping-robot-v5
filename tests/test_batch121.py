"""
tests/test_batch121.py
Unit tests for Batch 121:
- python_engine/live_runner.py (ScalpingLiveRunner, tick processing, bar rollover, TP/SL position closing, equity floating PnL, reset, risk aliases)
- alert_system.py (format_number, parse_timestamp_utc, risk guard aliases on instance and module level)
"""

import sys
import math
import time
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from python_engine.live_runner import ScalpingLiveRunner, is_entry_blocked as lr_is_entry_blocked, is_blocked as lr_is_blocked
from python_engine.scalping_engine import ScalpingSignal
import alert_system as als


class TestBatch121(unittest.TestCase):

    def test_live_runner_init_and_state(self):
        """Test ScalpingLiveRunner initialization and get_state snapshot."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            status_f = Path(tmp_dir) / "live_status.json"
            runner = ScalpingLiveRunner(status_file=status_f)
            self.assertEqual(runner.balance, 10000.0)
            self.assertEqual(runner.equity, 10000.0)
            self.assertEqual(len(runner.bars), 100)
            self.assertEqual(runner.total_trades_count, 0)

            state = runner.get_state()
            self.assertEqual(state["balance"], 10000.0)
            self.assertEqual(state["equity"], 10000.0)
            self.assertEqual(state["bars_count"], 100)
            self.assertEqual(state["open_positions_count"], 0)

    def test_live_runner_update_tick_random_movement(self):
        """Test update_tick with None generating Gaussian micro-movement and updating state."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            status_f = Path(tmp_dir) / "live_status.json"
            runner = ScalpingLiveRunner(status_file=status_f)
            old_price = runner.current_price
            status = runner.update_tick(None)
            self.assertEqual(status["status"], "ACTIVE_SCALPING")
            self.assertIn("current_price", status)
            self.assertTrue(status_f.exists())

    def test_live_runner_update_tick_explicit_price(self):
        """Test update_tick with explicit valid price."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            status_f = Path(tmp_dir) / "live_status.json"
            runner = ScalpingLiveRunner(status_file=status_f)
            status = runner.update_tick(2405.50)
            self.assertEqual(status["current_price"], 2405.50)
            self.assertEqual(runner.current_price, 2405.50)

    def test_live_runner_position_tp_hit(self):
        """Test position closing and positive PnL when take-profit is reached."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            status_f = Path(tmp_dir) / "live_status.json"
            runner = ScalpingLiveRunner(status_file=status_f)
            runner.robot.open_positions.append({
                "id": 101,
                "type": ScalpingSignal.BUY,
                "symbol": "XAUUSD",
                "entry": 2400.00,
                "lot": 0.01,
                "tp": 2410.00,
                "sl": 2390.00,
                "open_time": datetime.now(timezone.utc).isoformat()
            })

            # Advance tick past TP
            status = runner.update_tick(2411.00)
            self.assertEqual(len(runner.robot.open_positions), 0)
            self.assertEqual(len(runner.trades_history), 1)
            closed_trade = runner.trades_history[0]
            self.assertEqual(closed_trade["close_reason"], "TP_HIT")
            self.assertGreater(closed_trade["pnl"], 0.0)
            self.assertGreater(runner.balance, 10000.0)
            self.assertEqual(runner.winning_trades_count, 1)

    def test_live_runner_position_sl_hit(self):
        """Test position closing and negative PnL when stop-loss is reached."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            status_f = Path(tmp_dir) / "live_status.json"
            runner = ScalpingLiveRunner(status_file=status_f)
            runner.robot.open_positions.append({
                "id": 102,
                "type": ScalpingSignal.SELL,
                "symbol": "XAUUSD",
                "entry": 2400.00,
                "lot": 0.01,
                "tp": 2390.00,
                "sl": 2405.00,
                "open_time": datetime.now(timezone.utc).isoformat()
            })

            # Advance tick above SL for a SELL position
            status = runner.update_tick(2406.00)
            self.assertEqual(len(runner.robot.open_positions), 0)
            self.assertEqual(len(runner.trades_history), 1)
            closed_trade = runner.trades_history[0]
            self.assertEqual(closed_trade["close_reason"], "SL_HIT")
            self.assertLess(closed_trade["pnl"], 0.0)
            self.assertLess(runner.balance, 10000.0)

    def test_live_runner_reset(self):
        """Test reset cleanly restores balance and clears histories."""
        runner = ScalpingLiveRunner()
        runner.balance = 8500.0
        runner.daily_pnl = -1500.0
        runner.total_trades_count = 10
        runner.winning_trades_count = 4
        runner.robot.open_positions = [{"id": 1}]
        runner.trades_history = [{"id": 1}]

        runner.reset(12000.0)
        self.assertEqual(runner.balance, 12000.0)
        self.assertEqual(runner.equity, 12000.0)
        self.assertEqual(runner.daily_pnl, 0.0)
        self.assertEqual(runner.total_trades_count, 0)
        self.assertEqual(runner.winning_trades_count, 0)
        self.assertEqual(len(runner.robot.open_positions), 0)
        self.assertEqual(len(runner.trades_history), 0)

    def test_live_runner_is_entry_blocked(self):
        """Test is_entry_blocked and is_blocked on live runner and module level."""
        runner = ScalpingLiveRunner()
        self.assertFalse(runner.is_entry_blocked())
        self.assertFalse(runner.is_blocked())

        # Ruin defense
        runner.equity = 0.0
        self.assertTrue(runner.is_entry_blocked())
        self.assertTrue(runner.is_blocked())

        runner.equity = 10000.0
        # Drawdown trigger
        runner.daily_pnl = -175.0
        self.assertTrue(runner.is_entry_blocked())
        self.assertTrue(runner.is_blocked())

        # Module level functions
        self.assertFalse(lr_is_entry_blocked())
        self.assertFalse(lr_is_blocked())

    def test_alert_system_format_number(self):
        """Test format_number helper in alert_system."""
        self.assertEqual(als.format_number(150.0, is_currency=True), "$150")
        self.assertEqual(als.format_number(175.50, is_currency=True), "$175.50")
        self.assertEqual(als.format_number(65.0, is_currency=False), "65")
        self.assertEqual(als.format_number(64.5, is_currency=False), "64.5")

    def test_alert_system_parse_timestamp_utc(self):
        """Test parse_timestamp_utc across various formats."""
        # None and invalid
        self.assertIsNone(als.parse_timestamp_utc(None))
        self.assertIsNone(als.parse_timestamp_utc(""))
        self.assertIsNone(als.parse_timestamp_utc("invalid_date"))

        # Unix timestamp float and string
        t = 1700000000.0
        dt1 = als.parse_timestamp_utc(t)
        self.assertIsNotNone(dt1)
        self.assertEqual(dt1.tzinfo, timezone.utc)

        dt2 = als.parse_timestamp_utc(str(t))
        self.assertIsNotNone(dt2)

        # ISO format with Z
        dt3 = als.parse_timestamp_utc("2026-10-18T05:00:00Z")
        self.assertIsNotNone(dt3)
        self.assertEqual(dt3.year, 2026)

        # Standard log format
        dt4 = als.parse_timestamp_utc("2026-10-18 05:00:00")
        self.assertIsNotNone(dt4)

    def test_alert_system_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on AlertSystem and module level."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            system = als.AlertSystem(
                status_file=base / "status.json",
                alerts_log_file=base / "alerts.log",
                alert_status_file=base / "alert_status.json"
            )
            # Initially empty alert
            self.assertFalse(system.is_entry_blocked())
            self.assertFalse(system.is_blocked())

            # Critical alert
            system.last_alert = "ALERT: Balance critical: $9700"
            self.assertTrue(system.is_entry_blocked())
            self.assertTrue(system.is_blocked())

            # Danger alert
            system.last_alert = "ALERT: Daily loss danger: $175.50"
            self.assertTrue(system.is_entry_blocked())
            self.assertTrue(system.is_blocked())

            # Informational / non-critical alert
            system.last_alert = "INFO: Trading resumed"
            self.assertFalse(system.is_entry_blocked())
            self.assertFalse(system.is_blocked())

            # Module level
            self.assertFalse(als.is_entry_blocked())
            self.assertFalse(als.is_blocked())


if __name__ == "__main__":
    unittest.main()
