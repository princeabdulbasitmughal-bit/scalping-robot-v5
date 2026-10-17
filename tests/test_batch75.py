"""
tests/test_batch75.py
Batch 75 Unit Tests: OmniCommand Pro API Endpoints & State Management (omnicommand_server.py).
Verifies:
1. read_live_status: Corrupted JSON fault recovery and safe fallback defaults.
2. read_live_status: TTL caching and cache invalidation.
3. reset_daily_pnl: /api/reset-daily-pnl state clearing, RESET_TRIGGER creation & atomic persistence.
4. alerts_endpoint: /api/alerts parsing from alert_status.json and alerts.log.
5. ml_status: /api/ml_status payload retrieval from live status.
6. system_health: /api/system host telemetry (RAM, CPU, disk, uptime).
7. positions and trade_history: /api/positions and /api/history data retrieval.
8. analytics: /api/analytics equity curve generation (50 balance points) and signal tier detection.
9. _read_risk_guard_state: KILL_SWITCH sentinel file and balance floor threshold evaluation.
10. download endpoints: 404 handling when archive files are absent.
"""

import json
import time
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

import omnicommand_server


@pytest.fixture
def mock_omnicommand_env(tmp_path, monkeypatch):
    """Fixture configuring isolated file paths for OmniCommand testing."""
    status_file = tmp_path / "live_status.json"
    risk_state_file = tmp_path / "risk_state.json"
    alert_status_file = tmp_path / "alert_status.json"
    alerts_log_file = tmp_path / "alerts.log"

    monkeypatch.setattr(omnicommand_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(omnicommand_server, "STATUS_FILE", status_file)
    monkeypatch.setattr(omnicommand_server, "_status_cache", {})
    monkeypatch.setattr(omnicommand_server, "_status_cache_ts", 0.0)

    # Scaffolding default live_status.json
    status_file.write_text(
        json.dumps({
            "status": "ACTIVE_SCALPING",
            "symbol": "XAUUSD",
            "balance": 10000.0,
            "equity": 10000.0,
            "daily_pnl": 0.0,
            "win_rate": 85.0,
            "total_trades": 20,
        }),
        encoding="utf-8"
    )

    client = TestClient(omnicommand_server.app)
    return tmp_path, status_file, client


def test_omnicommand_read_live_status_corrupted_json_resilience(mock_omnicommand_env, monkeypatch):
    """Verify read_live_status safely handles invalid JSON without raising exceptions."""
    tmp_path, status_file, _ = mock_omnicommand_env

    # Corrupt the status file
    status_file.write_text("INVALID_JSON_CORRUPTED{{{", encoding="utf-8")
    monkeypatch.setattr(omnicommand_server, "_status_cache", {})
    monkeypatch.setattr(omnicommand_server, "_status_cache_ts", 0.0)

    data = omnicommand_server.read_live_status()
    assert isinstance(data, dict)
    assert data["status"] == "STANDBY"
    assert "error" in data
    assert data["balance"] == 10000.0


def test_omnicommand_read_live_status_ttl_cache(mock_omnicommand_env, monkeypatch):
    """Verify read_live_status caches reads within 1.0s TTL and refreshes after expiry."""
    tmp_path, status_file, _ = mock_omnicommand_env

    status_file.write_text(json.dumps({"balance": 10000.0, "symbol": "XAUUSD"}), encoding="utf-8")
    monkeypatch.setattr(omnicommand_server, "_status_cache", {})
    monkeypatch.setattr(omnicommand_server, "_status_cache_ts", 0.0)

    # 1. Initial read caches data
    data1 = omnicommand_server.read_live_status()
    assert data1["balance"] == 10000.0

    # 2. Modify disk file immediately; read should still return cached value
    status_file.write_text(json.dumps({"balance": 12500.0, "symbol": "XAUUSD"}), encoding="utf-8")
    data2 = omnicommand_server.read_live_status()
    assert data2["balance"] == 10000.0  # Returned from cache

    # 3. Simulate TTL expiration
    monkeypatch.setattr(omnicommand_server, "_status_cache_ts", time.monotonic() - 5.0)
    data3 = omnicommand_server.read_live_status()
    assert data3["balance"] == 12500.0  # Refreshed from disk


def test_omnicommand_reset_daily_pnl_endpoint(mock_omnicommand_env):
    """Verify /api/reset-daily-pnl clears circuit breaker flags and creates RESET_TRIGGER."""
    tmp_path, status_file, client = mock_omnicommand_env

    # Seed tripped circuit breaker
    status_file.write_text(
        json.dumps({
            "daily_pnl": -175.50,
            "daily_loss": 175.50,
            "circuit_breaker_fired": True,
            "trading_halted": True,
            "risk_guard": {"daily_loss_halted": True, "daily_pnl": -175.50},
        }),
        encoding="utf-8"
    )

    resp = client.post("/api/reset-daily-pnl")
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["ok"] is True
    assert res_data["success"] is True
    assert res_data["daily_pnl"] == 0.0
    assert res_data["circuit_breaker_fired"] is False
    assert res_data["trading_halted"] is False

    # Check RESET_TRIGGER file created
    trigger_file = tmp_path / "RESET_TRIGGER"
    assert trigger_file.exists()
    assert trigger_file.read_text(encoding="utf-8") == "RESET"

    # Check live_status.json updated
    saved = json.loads(status_file.read_text(encoding="utf-8"))
    assert saved["daily_pnl"] == 0.0
    assert saved["circuit_breaker_fired"] is False
    assert saved["trading_halted"] is False


def test_omnicommand_alerts_endpoint_parsing(mock_omnicommand_env):
    """Verify /api/alerts reads alert_status.json and parses alerts.log format."""
    tmp_path, _, client = mock_omnicommand_env

    alert_status_file = tmp_path / "alert_status.json"
    alert_status_file.write_text(
        json.dumps({
            "alert_status": "WARNING",
            "last_alert": "High spread detected",
            "total_alerts_today": 2,
            "timestamp": "2026-10-17T12:00:00Z",
        }),
        encoding="utf-8"
    )

    alerts_log_file = tmp_path / "alerts.log"
    alerts_log_file.write_text(
        "[2026-10-17 11:50:00] ALERT: Spread widened to 3.8 pips\n"
        "[2026-10-17 12:00:00] ALERT: High spread detected\n",
        encoding="utf-8"
    )

    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "WARNING"
    assert len(data["alerts"]) == 2
    assert data["alerts"][0]["time"] == "2026-10-17 11:50:00"
    assert "Spread widened" in data["alerts"][0]["message"]


def test_omnicommand_ml_status_endpoint(mock_omnicommand_env):
    """Verify /api/ml_status extracts machine learning predictor telemetry."""
    tmp_path, status_file, client = mock_omnicommand_env

    status_file.write_text(
        json.dumps({
            "ml_prediction": {
                "direction": "BULLISH",
                "confidence": 0.82,
                "model": "Qwen 32B + Random Forest",
            },
            "updated_at": "2026-10-17T12:30:00Z",
        }),
        encoding="utf-8"
    )

    resp = client.get("/api/ml_status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["ml"]["direction"] == "BULLISH"
    assert data["ml"]["confidence"] == 0.82


def test_omnicommand_system_telemetry_endpoint(mock_omnicommand_env):
    """Verify /api/system queries host resources (RAM, CPU, disk, uptime)."""
    _, _, client = mock_omnicommand_env

    resp = client.get("/api/system")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["service"] == "OmniCommand Pro"
    assert "ram_pct" in data
    assert "cpu_pct" in data
    assert "disk_free_gb" in data
    assert isinstance(data["uptime_sec"], float)


def test_omnicommand_positions_and_history_endpoints(mock_omnicommand_env):
    """Verify /api/positions and /api/history parse active trades and historical log."""
    tmp_path, status_file, client = mock_omnicommand_env

    status_file.write_text(
        json.dumps({
            "open_positions": [{"ticket": 9901, "direction": "BUY", "lot": 0.02, "pnl": 12.5}],
            "trades_history": [{"id": "TRD-1", "direction": "SELL", "pnl": 45.0, "result": "WIN"}],
            "total_trades": 15,
            "win_rate": 80.0,
        }),
        encoding="utf-8"
    )

    # 1. /api/positions
    pos_resp = client.get("/api/positions")
    assert pos_resp.status_code == 200
    pos_data = pos_resp.json()
    assert pos_data["ok"] is True
    assert pos_data["count"] == 1
    assert pos_data["open_positions"][0]["ticket"] == 9901

    # 2. /api/history
    hist_resp = client.get("/api/history")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    assert hist_data["ok"] is True
    assert hist_data["count"] == 1
    assert hist_data["trades"][0]["id"] == "TRD-1"


def test_omnicommand_analytics_equity_curve(mock_omnicommand_env):
    """Verify /api/analytics generates 50 balance points for chart rendering."""
    tmp_path, status_file, client = mock_omnicommand_env

    status_file.write_text(
        json.dumps({
            "balance": 10350.0,
            "equity": 10375.0,
            "win_rate_pct": 86.7,
        }),
        encoding="utf-8"
    )

    resp = client.get("/api/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["balances"]) == 50
    assert data["balances"][-1] == 10350.0
    assert "signal_tier" in data


def test_omnicommand_risk_guard_state_kill_switch_detection(tmp_path, monkeypatch):
    """Verify _read_risk_guard_state detects KILL_SWITCH file and balance floor breaches."""
    monkeypatch.setattr(omnicommand_server, "BASE_DIR", tmp_path)

    # Scenario A: Clean state
    state_a = omnicommand_server._read_risk_guard_state({"balance": 10000.0})
    assert state_a["kill_switch_active"] is False
    assert state_a["balance_floor_halted"] is False

    # Scenario B: Balance below $9700 floor
    state_b = omnicommand_server._read_risk_guard_state({"balance": 9650.0})
    assert state_b["balance_floor_halted"] is True

    # Scenario C: KILL_SWITCH file present
    kill_switch_file = tmp_path / "KILL_SWITCH"
    kill_switch_file.write_text("HALT", encoding="utf-8")
    state_c = omnicommand_server._read_risk_guard_state({"balance": 10000.0})
    assert state_c["kill_switch_active"] is True


def test_omnicommand_download_endpoints_and_dashboard(mock_omnicommand_env):
    """Verify download endpoints return HTTP 404 when target files are absent, and dashboard serves HTML."""
    tmp_path, _, client = mock_omnicommand_env

    # 1. When ZIP archives do not exist, endpoints return 404
    with patch.object(Path, "exists", return_value=False):
        for endpoint in ["/download/suite", "/download/omnitrade", "/download/jarvis", "/download/scalper"]:
            resp = client.get(endpoint)
            assert resp.status_code == 404
            assert "not found" in resp.json()["error"].lower()

    # 2. Verify dashboard endpoint serves HTML
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert "text/html" in resp_dash.headers["content-type"]
    assert "OmniCommand Pro" in resp_dash.text or "Active" in resp_dash.text
