import os
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import watchdog_runner
from watchdog_runner import (
    calculate_backoff,
    status_age,
    health_check,
    detect_restart_reason,
    is_entry_blocked,
    is_blocked,
)
from swarm_30_scalping_engine import ScalpingSwarm30
import swarm_30_scalping_engine


def test_watchdog_calculate_backoff():
    assert calculate_backoff(0) == 30
    assert calculate_backoff(1) == 60
    assert calculate_backoff(2) == 120
    assert calculate_backoff(3) == 240
    assert calculate_backoff(4) == 300
    assert calculate_backoff(10) == 300
    # Boolean and invalid input guards
    assert calculate_backoff(True) == 30
    assert calculate_backoff(False) == 30
    assert calculate_backoff("invalid") == 30


def test_watchdog_status_age():
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent = Path(tmpdir) / "missing.json"
        assert status_age(non_existent) == 9999.0

        existing = Path(tmpdir) / "live_status.json"
        existing.write_text("{}", encoding="utf-8")
        age = status_age(existing)
        assert 0.0 <= age < 5.0


def test_watchdog_health_check_healthy():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"

        # Explicit ok=True with recent timestamp
        status_file.write_text(json.dumps({
            "ok": True,
            "timestamp": time.time(),
        }), encoding="utf-8")
        assert health_check(status_file) is True

        # Active scalping status
        status_file.write_text(json.dumps({
            "status": "active_scalping",
            "updated_at": time.time(),
        }), encoding="utf-8")
        assert health_check(status_file) is True


def test_watchdog_health_check_unhealthy_or_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"

        # ok=False
        status_file.write_text(json.dumps({"ok": False, "timestamp": time.time()}), encoding="utf-8")
        assert health_check(status_file) is False

        # Stale timestamp (>60s)
        status_file.write_text(json.dumps({"ok": True, "timestamp": time.time() - 120}), encoding="utf-8")
        assert health_check(status_file) is False

        # Corrupted JSON
        status_file.write_text("CORRUPTED {{{{", encoding="utf-8")
        assert health_check(status_file) is False


def test_watchdog_detect_restart_reason():
    # Process exited
    mock_dead_proc = MagicMock()
    mock_dead_proc.poll.return_value = 1
    reason = detect_restart_reason(mock_dead_proc)
    assert "CRASH: process exited with code 1" in reason

    # Process None
    assert "CRASH: process exited with code -1" in detect_restart_reason(None)

    # Process healthy
    mock_alive_proc = MagicMock()
    mock_alive_proc.poll.return_value = None
    with patch("watchdog_runner._memory_check", return_value=120.0):
        assert detect_restart_reason(mock_alive_proc) is None

    # Process OOM (>500MB)
    with patch("watchdog_runner._memory_check", return_value=550.0):
        assert detect_restart_reason(mock_alive_proc) == "OOM: memory > 500MB"


def test_watchdog_is_entry_blocked_and_aliases():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"

        # Missing file defaults to False
        assert is_entry_blocked(status_file) is False
        assert is_blocked(status_file) is False

        # Healthy file -> not blocked
        status_file.write_text(json.dumps({"ok": True, "timestamp": time.time()}), encoding="utf-8")
        assert is_entry_blocked(status_file) is False

        # Stale/unhealthy file -> blocked
        status_file.write_text(json.dumps({"ok": False}), encoding="utf-8")
        assert is_entry_blocked(status_file) is True
        assert is_blocked(status_file) is True


def test_swarm_30_initialization_and_attributes():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_file = Path(tmpdir) / "report.json"
        swarm = ScalpingSwarm30(root_dir=Path(tmpdir), report_file=report_file)
        assert swarm.root == Path(tmpdir)
        assert swarm.report_file == report_file
        assert swarm.get_last_report() is None


def test_swarm_30_execute_single_agent():
    with tempfile.TemporaryDirectory() as tmpdir:
        swarm = ScalpingSwarm30(root_dir=Path(tmpdir))
        res = swarm._execute_agent(agent_id=1)
        assert res["id"] == 1
        assert res["squadron_id"] == 1
        assert res["squadron_name"] == "Market Feeds & Order Book Sentinels"
        assert res["status"] in ("OPTIMAL", "WARN")
        assert res["latency_ms"] >= 0.0


def test_swarm_30_run_swarm_parallel_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_file = Path(tmpdir) / "reports" / "swarm_30_scalping_report.json"
        swarm = ScalpingSwarm30(root_dir=Path(tmpdir), report_file=report_file)

        rep = swarm.run_swarm(fast=True, max_workers=5, save_report=True)
        assert rep["total_agents"] == 30
        assert len(rep["squadrons"]) == 6
        assert len(rep["agents"]) == 30
        assert report_file.exists()
        assert swarm.get_last_report() == rep


def test_swarm_30_is_entry_blocked_and_aliases():
    swarm = ScalpingSwarm30()
    assert swarm.is_entry_blocked() is False
    assert swarm.is_blocked() is False

    # Simulate report with excessive warnings (>10)
    swarm.last_report = {"warn_count": 12, "health_score": "60%"}
    assert swarm.is_entry_blocked() is True
    assert swarm.is_blocked() is True

    # Module-level aliases
    assert swarm_30_scalping_engine.is_entry_blocked() is False
    assert swarm_30_scalping_engine.is_blocked() is False
