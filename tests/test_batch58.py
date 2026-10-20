"""
Test Suite: Batch 58 — Log Analyzer, Email Alerting, Real-Time Alert System & Trade Journal Edge Cases
======================================================================================================
Hermetic unit test suite verifying:
  1. LogAnalyzer: Heartbeat parsing, balance extraction, and range computation
  2. LogAnalyzer: Signal distribution and closed trade PnL tracking
  3. EmailAlerter: Template generation on missing config file
  4. EmailAlerter: Safe non-transmission when disabled or missing credentials
  5. EmailAlerter: SMTP factory invocation, authentication, and MIME dispatch
  6. AlertSystem: Numeric and currency formatting utilities
  7. AlertSystem: Critical win rate (< 70%) and daily loss (> $150) trigger evaluation
  8. AlertSystem: Capital balance floor (< $9800) and excess open positions (> 4) evaluation
  9. AlertSystem: Alert type rate limiting and cooldown throttling
 10. TradeJournal: Safe empty dataset handling and daily stats defaults
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from log_analyzer import parse_trader_log
from email_alert import EmailAlerter, DEFAULT_CONFIG
from alert_system import AlertSystem, format_number
from trade_journal import TradeJournal


# ── Test 1: LogAnalyzer Heartbeat & Balance Extraction ────────────────────────
def test_log_analyzer_heartbeat_and_balances():
    """Verify parse_trader_log extracts heartbeats, balances, and computes min/max/range."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "trader.log"
        log_file.write_text(
            "2026-10-17 12:00:00,100 [INFO] Trader: [HEARTBEAT] balance=$10000.00 | equity=$10000.00 | signal=HOLD\n"
            "2026-10-17 12:01:00,100 [INFO] Trader: [HEARTBEAT] balance=$10050.50 | equity=$10050.50 | signal=BUY\n"
            "2026-10-17 12:02:00,100 [INFO] Trader: [HEARTBEAT] balance=$9980.00 | equity=$9980.00 | signal=HOLD\n",
            encoding="utf-8",
        )

        summary = parse_trader_log(log_file)
        assert summary["heartbeat_lines"] == 3
        assert summary["balances"] == [10000.0, 10050.50, 9980.0]
        assert summary["max_balance"] == 10050.50
        assert summary["min_balance"] == 9980.0
        assert summary["balance_range"] == round(10050.50 - 9980.0, 2)


# ── Test 2: LogAnalyzer Signals & Closed Trades ───────────────────────────────
def test_log_analyzer_signals_and_trades():
    """Verify parse_trader_log counts signals and extracts closed trade PnLs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "trader.log"
        log_file.write_text(
            "2026-10-17 12:05:00 [INFO] Trader: [SIGNAL FIRED] -> BUY (Confidence: 85%)\n"
            "2026-10-17 12:06:00 [INFO] Trader: [NEW POSITION - LIVE] BUY 0.02 lots at 2400.00\n"
            "2026-10-17 12:10:00 [INFO] Trader: [TRADE CLOSED] BUY | TP_HIT | PnL: $50.00 | Balance: $10050.00\n"
            "2026-10-17 12:15:00 [WARNING] Trader: [SIGNAL SUPPRESSED] High spread\n"
            "2026-10-17 12:20:00 [ERROR] Trader: Connection timeout to broker\n",
            encoding="utf-8",
        )

        summary = parse_trader_log(log_file)
        assert summary["counts"]["TRADE"] >= 2
        assert summary["counts"]["ERROR"] == 1
        assert summary["counts"]["WARNING"] == 1
        assert summary["trade_breakdown"]["new_positions"] == 1
        assert summary["trade_breakdown"]["trades_closed"] == 1

        closed_pnl = summary["trade_breakdown"]["closed_trades_pnl"]
        assert len(closed_pnl) == 1
        assert closed_pnl[0]["side"] == "BUY"
        assert closed_pnl[0]["reason"] == "TP_HIT"
        assert closed_pnl[0]["pnl"] == 50.0


# ── Test 3: EmailAlerter Template Initialization ──────────────────────────────
def test_email_alerter_template_creation():
    """Verify EmailAlerter generates default template file when config is absent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "email_config.json"
        assert not cfg_file.exists()

        alerter = EmailAlerter(config_file=str(cfg_file))
        assert cfg_file.exists()
        saved = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved["enabled"] is False
        assert saved["smtp_host"] == "smtp.gmail.com"
        assert alerter.config["enabled"] is False


# ── Test 4: EmailAlerter Disabled / Unconfigured Safety ───────────────────────
def test_email_alerter_disabled_safety():
    """Verify send_alert immediately returns False when disabled or missing credentials."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "email_config.json"
        alerter = EmailAlerter(config_file=str(cfg_file))

        # Case 1: enabled = False
        assert alerter.send_alert("Test Subject", "Test Body") is False

        # Case 2: enabled = True but missing credentials
        alerter.update_config({"enabled": True, "from_email": "", "to_email": ""}, persist=True)
        assert alerter.send_alert("Test Subject", "Test Body") is False


# ── Test 5: EmailAlerter SMTP Factory Dispatch ────────────────────────────────
def test_email_alerter_smtp_dispatch():
    """Verify send_alert invokes smtp_factory and executes login and message transmission."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "email_config.json"
        mock_smtp = MagicMock()
        mock_smtp_enter = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp_enter

        def mock_factory(host, port, timeout):
            assert host == "smtp.test.com"
            assert port == 587
            return mock_smtp

        alerter = EmailAlerter(config_file=str(cfg_file), smtp_factory=mock_factory)
        alerter.update_config(
            {
                "enabled": True,
                "from_email": "bot@test.com",
                "password": "secret_password",
                "to_email": "trader@test.com",
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
            },
            persist=True,
        )

        success = alerter.send_alert("Drawdown Alert", "Equity dropped by 3.5%")
        assert success is True
        mock_smtp_enter.login.assert_called_once_with("bot@test.com", "secret_password")
        mock_smtp_enter.send_message.assert_called_once()


# ── Test 6: AlertSystem Number Formatting ──────────────────────────────────────
def test_alert_system_format_number():
    """Verify format_number handles whole numbers and floats with currency formatting."""
    assert format_number(150.0, is_currency=True) == "$150"
    assert format_number(150.50, is_currency=True) == "$150.50"
    assert format_number(70.0, is_currency=False) == "70"
    assert format_number(68.45, is_currency=False) == "68.45"


# ── Test 7: AlertSystem Win Rate & Daily Loss Triggers ─────────────────────────
def test_alert_system_win_rate_and_daily_loss_evaluation():
    """Verify evaluate_conditions flags critical win rate (< 70%) and daily loss (> $150)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        alert_sys = AlertSystem(status_file=status_file)

        # Critical Win Rate & Critical Daily Loss
        data = {
            "win_rate": 62.5,
            "total_trades": 8,
            "daily_loss": 175.0,
            "balance": 10000.0,
            "open_positions": [],
        }

        conditions, status = alert_sys.evaluate_conditions(data)
        types = [c["type"] for c in conditions]
        assert "win_rate_critical" in types
        assert "daily_loss_danger" in types
        assert any("62.5%" in c["message"] for c in conditions)
        assert any("$175" in c["message"] for c in conditions)


# ── Test 8: AlertSystem Balance Floor & Excess Positions ──────────────────────
def test_alert_system_balance_floor_and_excess_positions():
    """Verify evaluate_conditions flags balance below $9800 and excess open positions (> 4)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        alert_sys = AlertSystem(status_file=status_file)

        data = {
            "win_rate": 80.0,
            "total_trades": 10,
            "daily_loss": 0.0,
            "balance": 9750.0,  # Below $9800 floor
            "open_positions": [1, 2, 3, 4, 5],  # 5 positions > 4 limit
        }

        conditions, _ = alert_sys.evaluate_conditions(data)
        types = [c["type"] for c in conditions]
        assert "balance_critical" in types
        assert "too_many_positions" in types
        assert any("$9750" in c["message"] for c in conditions)
        assert any("Too many positions: 5" in c["message"] for c in conditions)


# ── Test 9: AlertSystem Rate Limiting & Cooldown ───────────────────────────────
def test_alert_system_rate_limiting():
    """Verify check_alerts enforces 15-minute rate limit between identical alerts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        alerts_log = Path(tmpdir) / "alerts.log"
        alert_status = Path(tmpdir) / "alert_status.json"

        alert_sys = AlertSystem(
            status_file=status_file,
            alerts_log_file=alerts_log,
            alert_status_file=alert_status,
            rate_limit_minutes=15,
        )

        from datetime import datetime, timezone as _tz
        critical_data = {
            "win_rate": 60.0,
            "total_trades": 10,
            "daily_loss": 0.0,
            "balance": 10000.0,
            "open_positions": [],
            # Provide a recent last_trade_time so stalled-check (>90 min idle) doesn't fire
            "last_trade_time": datetime.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }

        # First cycle: alert must trigger and log to file
        alerts1 = alert_sys.check_alerts(live_data=critical_data)
        assert len(alerts1) == 1
        assert "Win rate critical" in alerts1[0]
        assert alert_sys.total_alerts_today == 1
        assert alerts_log.exists()
        assert alert_status.exists()

        # Immediate follow-up cycle: must be suppressed by 15-minute rate limit
        alerts2 = alert_sys.check_alerts(live_data=critical_data)
        assert len(alerts2) == 0
        assert alert_sys.total_alerts_today == 1

        # Fast-forward time past 15-minute rate limit (16 minutes)
        alert_sys.last_alert_times["win_rate_critical"] -= (16 * 60)
        alerts3 = alert_sys.check_alerts(live_data=critical_data)
        assert len(alerts3) == 1
        assert alert_sys.total_alerts_today == 2


# ── Test 10: TradeJournal Empty Stats & Safe Queries ───────────────────────────
def test_trade_journal_empty_stats_defaults():
    """Verify TradeJournal handles queries on empty tables gracefully with safe defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "empty_trades.db"
        journal = TradeJournal(db_path=str(db_path))

        # Querying non-existent trades returns empty list
        assert journal.get_last_N_trades(10) == []

        # Querying daily stats on empty database returns empty dict without throwing
        stats = journal.get_daily_stats("2026-10-17")
        assert isinstance(stats, dict)
        assert stats == {}
