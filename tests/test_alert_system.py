"""
Unit Tests for AlertSystem (alert_system.py).
Tests all 6 alert conditions, 15-minute rate limiting, persistence to alert_status.json,
and logging to alerts.log.
"""

import time
import tempfile
import pytest
from pathlib import Path
from alert_system import AlertSystem


@pytest.fixture
def temp_alert_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        status_file = base / "live_status.json"
        alerts_log_file = base / "alerts.log"
        alert_status_file = base / "alert_status.json"

        system = AlertSystem(
            status_file=status_file,
            alerts_log_file=alerts_log_file,
            alert_status_file=alert_status_file,
            check_interval=60,
            rate_limit_minutes=15,
        )
        yield system, alerts_log_file, alert_status_file


def test_alert_system_initialization(temp_alert_env):
    system, _, alert_status_file = temp_alert_env
    assert system.total_alerts_today == 0
    assert system.last_alert == ""
    assert alert_status_file.exists()


def test_alert_conditions_and_rate_limiting(temp_alert_env):
    system, alerts_log, alert_status = temp_alert_env

    # 1. Normal data
    normal_data = {
        "status": "ACTIVE_SCALPING",
        "win_rate_pct": 80.0,
        "daily_loss": 20.0,
        "balance": 10000.0,
        "equity": 10000.0,
        "open_positions_count": 1,
        "last_trade_time": time.time(),
        "total_trades": 10,
    }
    alerts = system.check_alerts(normal_data)
    assert len(alerts) == 0

    # 2. Win rate dropped below 70%
    data_wr = dict(normal_data, win_rate_pct=64.5)
    alerts = system.check_alerts(data_wr)
    assert len(alerts) == 1
    assert "ALERT: Win rate critical: 64.5%" in alerts[0]

    # Rate limiting: second call within 15 min does not fire
    alerts_rl = system.check_alerts(data_wr)
    assert len(alerts_rl) == 0

    # 3. Daily loss > $150
    data_loss = dict(normal_data, daily_loss=175.5)
    alerts = system.check_alerts(data_loss)
    assert len(alerts) == 1
    assert "ALERT: Daily loss danger: $175.50" in alerts[0]

    # 4. Balance below $9800
    data_bal = dict(normal_data, balance=9700.0)
    alerts = system.check_alerts(data_bal)
    assert len(alerts) == 1
    assert "ALERT: Balance critical: $9700" in alerts[0]

    # 5. Equity drawdown > 5%
    data_dd = dict(normal_data, balance=10000.0, equity=9350.0)
    alerts = system.check_alerts(data_dd)
    assert len(alerts) == 1
    assert "ALERT: Equity drawdown:" in alerts[0]

    # 6. Open positions > 4
    data_pos = dict(normal_data, open_positions_count=6)
    alerts = system.check_alerts(data_pos)
    assert len(alerts) == 1
    assert "ALERT: Too many positions: 6" in alerts[0]

    # 7. No trades in 90 min during active session
    data_stalled = dict(normal_data, last_trade_time=time.time() - (92 * 60))
    alerts = system.check_alerts(data_stalled)
    assert len(alerts) == 1
    assert "ALERT: Trading stalled" in alerts[0]

    # Verify total alerts fired
    assert system.total_alerts_today == 6

    # Verify alerts.log contents
    with open(alerts_log, "r", encoding="utf-8") as f:
        log_text = f.read()
    assert "ALERT: Win rate critical: 64.5%" in log_text
    assert "ALERT: Daily loss danger: $175.50" in log_text
    assert "ALERT: Balance critical: $9700" in log_text
    assert "ALERT: Equity drawdown:" in log_text
    assert "ALERT: Too many positions: 6" in log_text
    assert "ALERT: Trading stalled" in log_text

    # Verify rate limit expiration
    system.last_alert_times["win_rate_critical"] = time.time() - (16 * 60)
    alerts_refired = system.check_alerts(data_wr)
    assert len(alerts_refired) == 1
    assert "ALERT: Win rate critical: 64.5%" in alerts_refired[0]
