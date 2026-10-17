"""
Test Suite: Batch 61 — Swarm 100 Engine, Backtester Mathematical Indicators, Rolling Economic Calendar & Alert Thresholds
========================================================================================================================
Hermetic unit test suite verifying:
  1. ScalpingSwarm100: Squadron routing and agent mapping across 10 specialized squadrons
  2. ScalpingSwarm100: Ultra-parallel 100-subagent fast burst execution and health aggregation
  3. Backtester: Bollinger Bands calculation, standard deviation multiplier scaling, and short series fallback
  4. Backtester: Exponential Moving Average (EMA) alpha weighting and edge cases
  5. Backtester: Wilder's RSI boundary conditions (zero loss, zero gain, insufficient data)
  6. EconomicNewsFilter: Rolling high-impact calendar generation (NFP, CPI, FOMC)
  7. AlertSystem: Equity drawdown threshold evaluation (> 5% drawdown -> CRITICAL alert)
  8. AlertSystem: Trading stalled detection (> 90 minutes idle during active session -> WARNING)
  9. EmailAlerter: SMTP test_connection successful authentication handshake
 10. EmailAlerter: SMTP test_connection authentication failure containment
"""

import math
import smtplib
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest

from swarm_100_scalping_engine import ScalpingSwarm100
from python_engine.backtester import Backtester
from python_engine.scalping_engine import EconomicNewsFilter
from alert_system import AlertSystem
from email_alert import EmailAlerter


# ── Test 1: ScalpingSwarm100 Agent Execution Mapping ───────────────────────────
def test_swarm_100_agent_execution_mapping():
    """Verify ScalpingSwarm100 maps agent IDs correctly across all 10 squadrons."""
    with tempfile.TemporaryDirectory() as tmpdir:
        swarm = ScalpingSwarm100(root_dir=Path(tmpdir))

        # Agent 5 -> Squadron 1 (Market Feeds & XAUUSD Tick Sentinel)
        res5 = swarm._execute_agent(5, fast=True)
        assert res5["id"] == 5
        assert res5["squadron_id"] == 1
        assert "Market Feeds" in res5["squadron_name"]
        assert res5["status"] == "OPTIMAL"

        # Agent 15 -> Squadron 2 (Technical Indicators & Trend Oscillators)
        res15 = swarm._execute_agent(15, fast=True)
        assert res15["id"] == 15
        assert res15["squadron_id"] == 2
        assert "Technical Indicators" in res15["squadron_name"]

        # Agent 35 -> Squadron 4 (Spread & Execution Governors)
        res35 = swarm._execute_agent(35, fast=True)
        assert res35["id"] == 35
        assert res35["squadron_id"] == 4
        assert "Spread" in res35["squadron_name"]

        # Agent 55 -> Squadron 6 (Profit Streak & Recovery Management)
        res55 = swarm._execute_agent(55, fast=True)
        assert res55["id"] == 55
        assert res55["squadron_id"] == 6
        assert "Profit Streak" in res55["squadron_name"]

        # Agent 75 -> Squadron 8 (Candlestick, Reversal & Pattern Detectors)
        res75 = swarm._execute_agent(75, fast=True)
        assert res75["id"] == 75
        assert res75["squadron_id"] == 8
        assert "Candlestick" in res75["squadron_name"]

        # Agent 95 -> Squadron 10 (Process Watchdog, Live Heartbeat & Telemetry)
        res95 = swarm._execute_agent(95, fast=True)
        assert res95["id"] == 95
        assert res95["squadron_id"] == 10
        assert "Process Watchdog" in res95["squadron_name"]


# ── Test 2: ScalpingSwarm100 Parallel Burst Execution ─────────────────────────
def test_swarm_100_burst_run():
    """Verify run_swarm executes 100 concurrent subagents and aggregates 10 squadrons."""
    with tempfile.TemporaryDirectory() as tmpdir:
        report_file = Path(tmpdir) / "swarm_100_report.json"
        swarm = ScalpingSwarm100(root_dir=Path(tmpdir), report_file=report_file)

        report = swarm.run_swarm(fast=True, max_workers=20, save_report=False)
        assert isinstance(report, dict)
        assert report["total_agents"] == 100
        assert len(report["agents"]) == 100
        assert len(report["squadrons"]) == 10
        assert "health_score" in report
        assert report["health_score"].endswith("%")


# ── Test 3: Backtester Bollinger Bands Mathematical Properties ────────────────
def test_backtester_bb_math_properties():
    """Verify _calc_bb handles fallback on short series and scales with std_dev_mult."""
    bt = Backtester()

    # Short series (< period) -> Fallback (p+1, p, p-1)
    short_series = [2400.0, 2401.0, 2402.0]
    up_s, mid_s, low_s = bt._calc_bb(short_series, period=20)
    assert mid_s == 2402.0
    assert up_s == 2403.0
    assert low_s == 2401.0

    # Normal series with standard deviation scaling
    series = [2400.0 + i for i in range(25)]
    up_1, mid_1, low_1 = bt._calc_bb(series, period=20, std_dev_mult=1.0)
    up_2, mid_2, low_2 = bt._calc_bb(series, period=20, std_dev_mult=2.0)

    assert mid_1 == mid_2
    # Multiplier of 2.0 must produce strictly wider bands than 1.0
    assert (up_2 - low_2) > (up_1 - low_1)
    assert math.isclose(up_2 - mid_2, 2.0 * (up_1 - mid_1), rel_tol=1e-5)


# ── Test 4: Backtester EMA Mathematical Smoothing ──────────────────────────────
def test_backtester_ema_smoothing():
    """Verify _calc_ema handles empty series, short series, and constant series."""
    bt = Backtester()

    # Empty series or period <= 0
    assert bt._calc_ema([], period=10) == 0.0
    assert bt._calc_ema([2400.0], period=0) == 0.0

    # Series shorter than period returns last value
    assert bt._calc_ema([2400.0, 2405.0], period=10) == 2405.0

    # Constant price series must have exact identical EMA
    constant_series = [2400.0] * 30
    assert round(bt._calc_ema(constant_series, period=8), 2) == 2400.0


# ── Test 5: Backtester Wilder's RSI Boundary Conditions ────────────────────────
def test_backtester_rsi_boundary_conditions():
    """Verify _calc_rsi handles insufficient data, zero-loss (100.0), and zero-gain (0.0)."""
    bt = Backtester()

    # Insufficient data (len <= period) -> Neutral 50.0
    assert bt._calc_rsi([2400.0, 2401.0], period=14) == 50.0

    # Strictly increasing series -> Zero loss -> 100.0
    rising = [2400.0 + i * 2.0 for i in range(20)]
    assert bt._calc_rsi(rising, period=14) == 100.0

    # Strictly decreasing series -> Zero gain -> 0.0
    falling = [2450.0 - i * 2.0 for i in range(20)]
    assert bt._calc_rsi(falling, period=14) == 0.0


# ── Test 6: EconomicNewsFilter Rolling Calendar Generation ─────────────────────
def test_economic_news_filter_rolling_calendar():
    """Verify _load_default_calendar populates high-impact events with valid timestamps."""
    news = EconomicNewsFilter()
    assert len(news.events) >= 6

    now = datetime.now(timezone.utc).timestamp()
    for ev in news.events:
        assert ev["timestamp"] > 0
        assert ev["currency"] == "USD"
        assert ev["impact"] == "HIGH"
        # Event titles must correspond to high impact macro releases
        assert any(k in ev["event"] for k in ("NFP", "CPI", "FOMC", "Unemployment"))


# ── Test 7: AlertSystem Equity Drawdown Condition ──────────────────────────────
def test_alert_system_equity_drawdown_condition():
    """Verify evaluate_conditions flags equity drawdown exceeding 5% threshold."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        alert_sys = AlertSystem(status_file=status_file)

        # Drawdown: peak=10000, current equity=9400 -> 6.0% drawdown (> 5.0%)
        data = {
            "balance": 10000.0,
            "equity": 9400.0,
            "win_rate": 80.0,
            "total_trades": 10,
            "open_positions": [],
        }

        conditions, status = alert_sys.evaluate_conditions(data)
        dd_cond = next((c for c in conditions if c["type"] == "equity_drawdown"), None)
        assert dd_cond is not None
        assert dd_cond["level"] == "CRITICAL"
        assert "6%" in dd_cond["message"]
        assert status == "CRITICAL"


# ── Test 8: AlertSystem Trading Stalled Condition ──────────────────────────────
def test_alert_system_trading_stalled_condition():
    """Verify evaluate_conditions flags trading stalled when idle > 90 min during active session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        alert_sys = AlertSystem(status_file=status_file)

        # Mock trade 100 minutes ago during active session
        now_dt = datetime.now(timezone.utc)
        stalled_time = (now_dt - timedelta(minutes=100)).isoformat()

        data = {
            "active_session": True,
            "last_trade_time": stalled_time,
            "balance": 10000.0,
            "equity": 10000.0,
            "win_rate": 80.0,
            "total_trades": 10,
            "open_positions": [],
        }

        conditions, status = alert_sys.evaluate_conditions(data)
        stall_cond = next((c for c in conditions if c["type"] == "trading_stalled"), None)
        assert stall_cond is not None
        assert stall_cond["level"] == "WARNING"
        assert "Trading stalled" in stall_cond["message"]


# ── Test 9: EmailAlerter Test Connection Success ───────────────────────────────
def test_email_alerter_test_connection_success():
    """Verify test_connection returns True upon successful SMTP authentication."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "email_config.json"
        mock_smtp = MagicMock()
        mock_server = MagicMock()
        mock_smtp.__enter__.return_value = mock_server

        def mock_factory(host, port, timeout):
            return mock_smtp

        alerter = EmailAlerter(config_file=str(cfg_file), smtp_factory=mock_factory)
        alerter.update_config(
            {
                "enabled": True,
                "from_email": "bot@test.com",
                "password": "secret_password",
                "to_email": "trader@test.com",
            },
            persist=True,
        )

        assert alerter.test_connection() is True
        mock_server.login.assert_called_once_with("bot@test.com", "secret_password")


# ── Test 10: EmailAlerter Test Connection Failure Containment ──────────────────
def test_email_alerter_test_connection_failure():
    """Verify test_connection catches SMTP authentication errors and returns False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "email_config.json"
        mock_smtp = MagicMock()
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
        mock_smtp.__enter__.return_value = mock_server

        def mock_factory(host, port, timeout):
            return mock_smtp

        alerter = EmailAlerter(config_file=str(cfg_file), smtp_factory=mock_factory)
        alerter.update_config(
            {
                "enabled": True,
                "from_email": "bot@test.com",
                "password": "bad_password",
                "to_email": "trader@test.com",
            },
            persist=True,
        )

        # Must return False safely without raising unhandled exception
        assert alerter.test_connection() is False
