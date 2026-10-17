"""
tests/test_batch79.py
Batch 79 Unit Tests: Bulletproof Watchdog (watchdog_runner.py) & Process Supervisor (supervisor.py).
Expands test baseline beyond 1,037+ passing tests.
Verifies:
1. watchdog_runner: calculate_backoff exponential delay schedule and 300s cap.
2. watchdog_runner: health_check active status detection and staleness rejection.
3. watchdog_runner: detect_restart_reason crash, OOM (>500MB), and freeze (>120s) triggers.
4. watchdog_runner: status_age modification time tracking and missing file fallback (9999.0s).
5. watchdog_runner: log_restart formatted notification persistence in watchdog.log.
6. watchdog_runner: safe_kill and safe_close null-safety and exception resilience.
7. supervisor: calculate_backoff exponential crash-loop backoff (8s, 16s, 32s, 64s, 120s cap).
8. supervisor: check_circuit_breaker threshold enforcement (20 consecutive failures).
9. supervisor: log custom destination routing and timestamp formatting.
10. supervisor: Process launch flags composition (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW).
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

import watchdog_runner
import supervisor


def test_watchdog_calculate_backoff_schedule():
    """Verify watchdog exponential backoff progression and 300s ceiling."""
    # 0 restarts -> 30s
    assert watchdog_runner.calculate_backoff(0) == 30
    # 1 restart -> 60s
    assert watchdog_runner.calculate_backoff(1) == 60
    # 2 restarts -> 120s
    assert watchdog_runner.calculate_backoff(2) == 120
    # 3 restarts -> 240s
    assert watchdog_runner.calculate_backoff(3) == 240
    # >=4 restarts -> capped at 300s
    assert watchdog_runner.calculate_backoff(4) == 300
    assert watchdog_runner.calculate_backoff(10) == 300

    # Negative or invalid inputs default safely to 30s
    assert watchdog_runner.calculate_backoff(-1) == 30
    assert watchdog_runner.calculate_backoff("invalid") == 30


def test_watchdog_health_check_states(tmp_path):
    """Verify health_check identifies healthy trader status and rejects stale/unhealthy states."""
    status_file = tmp_path / "live_status.json"

    # 1. Missing file -> False
    assert watchdog_runner.health_check(status_file) is False

    # 2. Healthy status with recent timestamp -> True
    now_ts = time.time()
    status_file.write_text(
        json.dumps({
            "status": "ACTIVE_SCALPING",
            "timestamp": now_ts - 10.0,  # 10s old
        }),
        encoding="utf-8"
    )
    assert watchdog_runner.health_check(status_file) is True

    # 3. Healthy status but stale timestamp (>60s old) -> False
    status_file.write_text(
        json.dumps({
            "status": "ACTIVE_SCALPING",
            "timestamp": now_ts - 90.0,  # 90s old
        }),
        encoding="utf-8"
    )
    assert watchdog_runner.health_check(status_file) is False

    # 4. Explicit ok: false -> False
    status_file.write_text(
        json.dumps({
            "ok": False,
            "status": "ERROR",
            "timestamp": now_ts - 5.0,
        }),
        encoding="utf-8"
    )
    assert watchdog_runner.health_check(status_file) is False


def test_watchdog_detect_restart_reason():
    """Verify detect_restart_reason identifies crash, OOM, and freeze conditions."""
    # 1. Crash: Process terminated
    proc_crash = MagicMock()
    proc_crash.poll.return_value = 137
    assert watchdog_runner.detect_restart_reason(proc_crash, age=10.0) == "CRASH: process exited with code 137"

    # 2. Crash: Process is None
    assert watchdog_runner.detect_restart_reason(None, age=10.0) == "CRASH: process exited with code -1"

    # 3. OOM: Memory exceeds 500MB
    proc_running = MagicMock()
    proc_running.poll.return_value = None
    with patch("watchdog_runner._memory_check", return_value=550.0):
        assert watchdog_runner.detect_restart_reason(proc_running, age=10.0) == "OOM: memory > 500MB"

    # 4. Freeze: Status age exceeds 120s
    with patch("watchdog_runner._memory_check", return_value=120.0):
        assert watchdog_runner.detect_restart_reason(proc_running, age=150.0) == "FREEZE: no status update for 120+ seconds"

    # 5. Healthy process
    with patch("watchdog_runner._memory_check", return_value=150.0):
        assert watchdog_runner.detect_restart_reason(proc_running, age=30.0) is None


def test_watchdog_status_age_calculation(tmp_path):
    """Verify status_age measures file modification age and returns 9999.0 for missing files."""
    status_file = tmp_path / "live_status.json"

    # Missing file
    assert watchdog_runner.status_age(status_file) == 9999.0

    # Existing file
    status_file.write_text("{}", encoding="utf-8")
    age = watchdog_runner.status_age(status_file)
    assert isinstance(age, float)
    assert 0.0 <= age < 5.0


def test_watchdog_log_restart_formatting(tmp_path, monkeypatch):
    """Verify log_restart formats notification and appends to watchdog.log."""
    log_file = tmp_path / "watchdog.log"
    monkeypatch.setattr(watchdog_runner, "WATCHDOG_LOG", log_file)

    watchdog_runner.log_restart(
        target="trader",
        reason="CRASH: process exited with code 1",
        restart_count=2,
        backoff_seconds=120,
    )

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "[RESTART] trader restart triggered" in content
    assert "reason: CRASH: process exited with code 1" in content
    assert "restart_count=2" in content
    assert "backoff_seconds=120" in content


def test_watchdog_safe_kill_and_safe_close():
    """Verify safe_kill and safe_close handle None and exceptions without errors."""
    # None arguments
    watchdog_runner.safe_kill(None)
    watchdog_runner.safe_close(None)

    # Mock process raising exception on kill
    proc_err = MagicMock()
    proc_err.kill.side_effect = PermissionError("Cannot kill")
    watchdog_runner.safe_kill(proc_err)

    # Mock file raising exception on close
    file_err = MagicMock()
    file_err.close.side_effect = OSError("Handle locked")
    watchdog_runner.safe_close(file_err)


def test_supervisor_calculate_backoff_schedule():
    """Verify supervisor exponential progression: 8s, 16s, 32s, 64s, 120s cap."""
    assert supervisor.calculate_backoff(0) == 0
    assert supervisor.calculate_backoff(-1) == 0
    assert supervisor.calculate_backoff(1) == 8
    assert supervisor.calculate_backoff(2) == 16
    assert supervisor.calculate_backoff(3) == 32
    assert supervisor.calculate_backoff(4) == 64
    assert supervisor.calculate_backoff(5) == 120
    assert supervisor.calculate_backoff(10) == 120


def test_supervisor_check_circuit_breaker_threshold():
    """Verify check_circuit_breaker halts supervisor after 20 consecutive failures."""
    assert supervisor.check_circuit_breaker(0) is False
    assert supervisor.check_circuit_breaker(10) is False
    assert supervisor.check_circuit_breaker(19) is False
    assert supervisor.check_circuit_breaker(20) is True
    assert supervisor.check_circuit_breaker(25) is True


def test_supervisor_log_output(tmp_path):
    """Verify supervisor log appends timestamped [SUP] lines to log file."""
    sup_log = tmp_path / "supervisor.log"

    supervisor.log("Supervisor initialized", log_file=str(sup_log))
    supervisor.log("Watchdog health verified", log_file=str(sup_log))

    assert sup_log.exists()
    content = sup_log.read_text(encoding="utf-8")
    assert "[SUP] Supervisor initialized" in content
    assert "[SUP] Watchdog health verified" in content


def test_supervisor_launch_flags_composition():
    """Verify supervisor process creation flags include DETACHED_PROCESS and NO_WINDOW."""
    assert supervisor.DETACHED_PROCESS == 0x00000008
    assert supervisor.CREATE_NEW_PROCESS_GROUP == 0x00000200
    assert supervisor.CREATE_NO_WINDOW == 0x08000000

    expected_flags = (
        supervisor.DETACHED_PROCESS |
        supervisor.CREATE_NEW_PROCESS_GROUP |
        supervisor.CREATE_NO_WINDOW
    )
    assert supervisor.FLAGS == expected_flags
