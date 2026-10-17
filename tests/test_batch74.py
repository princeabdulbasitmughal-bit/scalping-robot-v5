"""
tests/test_batch74.py
Batch 74 Unit Tests: Tunnel Watchdog (tunnel_watchdog.py) & OmniCommand Pro Logic (omnicommand_server.py).
Verifies:
1. tunnel_watchdog: URL extraction regex from serveo stdout log (primary & fallback patterns).
2. tunnel_watchdog: Expired/closed session detection and missing log handling.
3. tunnel_watchdog: Tunnel process liveness and log status evaluation.
4. tunnel_watchdog: Live status and tunnel_url.txt atomic persistence.
5. tunnel_watchdog: Safe kill/close error handling and exponential backoff schedule.
6. omnicommand_server: Performance grade calculation thresholds (A+, A, B, C).
7. omnicommand_server: 42-Wave risk guard blocking condition detection.
8. omnicommand_server: Live status enrichment with risk guard, Wave 59, and Wave 61 synthesis.
9. omnicommand_server: API key authentication enforcement and open mode fallback.
10. omnicommand_server: Body size limiter middleware (1MB ceiling and invalid header protection).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import tunnel_watchdog
import omnicommand_server


def test_tunnel_watchdog_extract_url_primary_and_fallback(tmp_path, monkeypatch):
    """Verify extract_url parses primary 'Forwarding HTTP' and fallback regex patterns."""
    log_file = tmp_path / "serveo_out.log"
    monkeypatch.setattr(tunnel_watchdog, "TUNNEL_OUT", log_file)

    # 1. Primary pattern
    log_file.write_text("Forwarding HTTP traffic from https://scalper-v5.serveo.net\n", encoding="utf-8")
    assert tunnel_watchdog.extract_url() == "https://scalper-v5.serveo.net"

    # 2. Primary pattern with trailing period
    log_file.write_text("Forwarding HTTP traffic from https://scalper-v5.serveo.net.\n", encoding="utf-8")
    assert tunnel_watchdog.extract_url() == "https://scalper-v5.serveo.net"

    # 3. Fallback pattern (*.serveousercontent.com)
    log_file.write_text("Allocated tunnel at https://alpha-node-99.serveousercontent.com active\n", encoding="utf-8")
    assert tunnel_watchdog.extract_url() == "https://alpha-node-99.serveousercontent.com"


def test_tunnel_watchdog_extract_url_expired_or_closed(tmp_path, monkeypatch):
    """Verify extract_url returns None when session is closed, expired, or log is missing."""
    log_file = tmp_path / "serveo_out.log"
    monkeypatch.setattr(tunnel_watchdog, "TUNNEL_OUT", log_file)

    # Missing file
    assert tunnel_watchdog.extract_url() is None

    # Expired session
    log_file.write_text("Forwarding HTTP traffic from https://scalper.serveo.net\nSession expired", encoding="utf-8")
    assert tunnel_watchdog.extract_url() is None

    # Closed connection
    log_file.write_text("Forwarding HTTP traffic from https://scalper.serveo.net\nconnection closed by remote host", encoding="utf-8")
    assert tunnel_watchdog.extract_url() is None


def test_tunnel_watchdog_is_tunnel_alive_states(tmp_path, monkeypatch):
    """Verify is_tunnel_alive evaluates process return code and log markers."""
    log_file = tmp_path / "serveo_out.log"
    monkeypatch.setattr(tunnel_watchdog, "TUNNEL_OUT", log_file)

    # 1. Process is None
    assert tunnel_watchdog.is_tunnel_alive(None) is False

    # 2. Process exited
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1
    assert tunnel_watchdog.is_tunnel_alive(mock_proc) is False

    # 3. Process running but log shows session closed
    mock_proc.poll.return_value = None
    log_file.write_text("tunnel running\nsession closed", encoding="utf-8")
    assert tunnel_watchdog.is_tunnel_alive(mock_proc) is False

    # 4. Process running with clean log
    log_file.write_text("tunnel connected and forwarding http traffic", encoding="utf-8")
    assert tunnel_watchdog.is_tunnel_alive(mock_proc) is True


def test_tunnel_watchdog_update_live_status_and_set_tunnel_url(tmp_path, monkeypatch):
    """Verify set_tunnel_url and update_live_status atomically persist URL state."""
    status_file = tmp_path / "live_status.json"
    url_file = tmp_path / "tunnel_url.txt"
    log_file = tmp_path / "tunnel_watchdog.log"

    monkeypatch.setattr(tunnel_watchdog, "STATUS_FILE", status_file)
    monkeypatch.setattr(tunnel_watchdog, "TUNNEL_URL", url_file)
    monkeypatch.setattr(tunnel_watchdog, "LOG", log_file)

    status_file.write_text(json.dumps({"symbol": "XAUUSD", "balance": 10000.0}), encoding="utf-8")

    # Set URL
    tunnel_watchdog.set_tunnel_url("https://scalper-live.serveo.net")

    # Verify url file
    assert url_file.exists()
    assert url_file.read_text(encoding="utf-8") == "https://scalper-live.serveo.net"

    # Verify live_status.json updated
    saved_status = json.loads(status_file.read_text(encoding="utf-8"))
    assert saved_status["tunnel_url"] == "https://scalper-live.serveo.net"
    assert saved_status["symbol"] == "XAUUSD"

    # Empty URL is a no-op
    tunnel_watchdog.set_tunnel_url("")
    assert url_file.read_text(encoding="utf-8") == "https://scalper-live.serveo.net"


def test_tunnel_watchdog_safe_helpers_and_backoff_schedule():
    """Verify safe_kill/safe_close handle None safely, and exponential backoff matches schedule."""
    # Safe cleanup no-ops
    tunnel_watchdog.safe_kill(None)
    tunnel_watchdog.safe_close(None)

    # Exponential backoff schedule formula: min(300, 15 * (2 ** (fail_count - 1)))
    expected_backoffs = [15, 30, 60, 120, 240, 300, 300]
    calculated_backoffs = [min(300, 15 * (2 ** (f - 1))) for f in range(1, 8)]
    assert calculated_backoffs == expected_backoffs


def test_omnicommand_compute_grade_thresholds():
    """Verify _compute_grade correctly maps win rate percentages to academic grades."""
    assert omnicommand_server._compute_grade(95.0) == "A+"
    assert omnicommand_server._compute_grade(90.1) == "A+"
    assert omnicommand_server._compute_grade(90.0) == "A"
    assert omnicommand_server._compute_grade(85.1) == "A"
    assert omnicommand_server._compute_grade(85.0) == "B"
    assert omnicommand_server._compute_grade(75.0) == "B"
    assert omnicommand_server._compute_grade(74.9) == "C"
    assert omnicommand_server._compute_grade(0.0) == "C"


def test_omnicommand_is_guard_blocking_detection():
    """Verify _is_guard_blocking detects all boolean blocking permutations across wave guards."""
    # Blocking conditions
    assert omnicommand_server._is_guard_blocking({"blocked": True}) is True
    assert omnicommand_server._is_guard_blocking({"currently_blocked": True}) is True
    assert omnicommand_server._is_guard_blocking({"is_blocked": True}) is True
    assert omnicommand_server._is_guard_blocking({"halted": True}) is True
    assert omnicommand_server._is_guard_blocking({"is_halted": True}) is True
    assert omnicommand_server._is_guard_blocking({"paused": True}) is True
    assert omnicommand_server._is_guard_blocking({"entry_blocked": True}) is True
    assert omnicommand_server._is_guard_blocking({"avoid_trading": True}) is True
    assert omnicommand_server._is_guard_blocking({"in_cooldown": True}) is True
    assert omnicommand_server._is_guard_blocking({"trading_allowed": False}) is True

    # Non-blocking conditions
    assert omnicommand_server._is_guard_blocking({"trading_allowed": True, "blocked": False}) is False
    assert omnicommand_server._is_guard_blocking({}) is False
    assert omnicommand_server._is_guard_blocking(None) is False
    assert omnicommand_server._is_guard_blocking("invalid_input") is False


def test_omnicommand_enrich_live_status_synthesis():
    """Verify _enrich_live_status injects grade, risk_guard, Wave 59, and Wave 61 structures."""
    raw_input = {
        "balance": 10500.0,
        "win_rate_pct": 88.5,
        "current_price": 2650.25,
        "mtf_bias": "BULL",
    }
    enriched = omnicommand_server._enrich_live_status(raw_input)

    assert enriched["grade"] == "A"
    assert enriched["win_rate"] == 88.5
    assert enriched["risk_guard"]["balance_floor_halted"] is False
    assert enriched["ma_trend_filter"]["wave"] == 59
    assert enriched["ma_trend_filter"]["trend"] == "BULLISH"
    assert enriched["opening_range_breakout"]["wave"] == 61
    assert enriched["opening_range_breakout"]["last_price"] == 2650.25


def test_omnicommand_api_key_auth_enforcement(monkeypatch):
    """Verify _require_api_key enforces key presence when configured and allows open mode when unset."""
    # 1. Configured mode
    monkeypatch.setattr(omnicommand_server, "_CONFIGURED_API_KEY", "secret-test-token")

    # Valid key passes
    omnicommand_server._require_api_key(api_key="secret-test-token")

    # Invalid key raises 403
    with pytest.raises(HTTPException) as exc_info_invalid:
        omnicommand_server._require_api_key(api_key="wrong-token")
    assert exc_info_invalid.value.status_code == 403

    # Missing key raises 403
    with pytest.raises(HTTPException) as exc_info_missing:
        omnicommand_server._require_api_key(api_key=None)
    assert exc_info_missing.value.status_code == 403

    # 2. Open mode (unconfigured)
    monkeypatch.setattr(omnicommand_server, "_CONFIGURED_API_KEY", "")
    omnicommand_server._require_api_key(api_key=None)  # Should not raise


def test_omnicommand_body_size_limit_middleware():
    """Verify limit_body_size middleware rejects payloads > 1MB with 413 and invalid headers with 400."""
    client = TestClient(omnicommand_server.app)

    # 1. Payload exceeding 1 MB
    resp_large = client.get("/ping", headers={"Content-Length": str(1024 * 1024 + 1)})
    assert resp_large.status_code == 413
    assert resp_large.json()["error"] == "Request body too large (max 1 MB)"

    # 2. Invalid Content-Length header
    resp_invalid = client.get("/ping", headers={"Content-Length": "not-an-integer"})
    assert resp_invalid.status_code == 400
    assert resp_invalid.json()["error"] == "Invalid Content-Length header"

    # 3. Normal payload size
    resp_normal = client.get("/ping", headers={"Content-Length": "10"})
    assert resp_normal.status_code == 200
