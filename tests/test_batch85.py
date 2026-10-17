"""
tests/test_batch85.py
Batch 85 Unit Tests: Atomic JSON Storage, Backup Recovery & Stale Temp Garbage Collection (python_engine/storage.py).
Expands test baseline beyond 1,097+ passing tests.
Verifies:
1. atomic_write_json: Creates file, writes valid nested content, and returns True.
2. atomic_write_json: Safely handles non-standard types (Path, datetime) via default=str serialization.
3. atomic_write_json: Automatically generates and updates <file>.bak backup file.
4. atomic_write_json: Leaves zero orphaned .tmp files in destination directory upon success.
5. atomic_write_json: Garbage-collects stale temp files older than 60s from prior crashes.
6. atomic_write_json: Automatically creates missing deep parent directory hierarchies.
7. safe_read_json: Non-existent file returns designated default value immediately.
8. safe_read_json: Reads and parses valid UTF-8 JSON datasets with binary buffer speed.
9. safe_read_json: Recovers dataset from .bak backup file when primary file suffers JSON corruption.
10. safe_read_json: Broken file without usable backup breaks early and returns designated default.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import pytest

from python_engine.storage import atomic_write_json, safe_read_json


def test_atomic_write_json_creates_file_and_valid_content(tmp_path):
    """Verify atomic_write_json creates destination file with formatted valid JSON content."""
    target = tmp_path / "data.json"
    data = {
        "symbol": "XAUUSD",
        "balance": 10000.0,
        "active": True,
        "trades": [1, 2, 3],
        "meta": {"version": 5.0},
    }

    success = atomic_write_json(target, data, indent=2)
    assert success is True
    assert target.exists()

    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


def test_atomic_write_json_default_serializer_handling(tmp_path):
    """Verify atomic_write_json safely serializes Path and datetime objects via default=str."""
    target = tmp_path / "custom_types.json"
    now_dt = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
    data = {
        "file_path": Path("C:/test/file.txt"),
        "timestamp": now_dt,
    }

    success = atomic_write_json(target, data)
    assert success is True

    loaded = safe_read_json(target)
    assert "C:" in loaded["file_path"] or "file.txt" in loaded["file_path"]
    assert "2026-10-18" in loaded["timestamp"]


def test_atomic_write_json_updates_backup_file(tmp_path):
    """Verify atomic_write_json creates and updates the .bak backup copy on each successful write."""
    target = tmp_path / "state.json"
    bak_file = tmp_path / "state.json.bak"

    # First write
    atomic_write_json(target, {"version": 1})
    assert target.exists()
    assert bak_file.exists()
    assert safe_read_json(bak_file) == {"version": 1}

    # Second write
    atomic_write_json(target, {"version": 2})
    assert safe_read_json(target) == {"version": 2}
    assert safe_read_json(bak_file) == {"version": 2}


def test_atomic_write_json_temp_file_cleanup_on_success(tmp_path):
    """Verify atomic_write_json cleans up its temporary file without leaving orphaned .tmp files."""
    target = tmp_path / "test_cleanup.json"
    atomic_write_json(target, {"status": "ok"})

    tmp_files = list(tmp_path.glob("test_cleanup.json.tmp.*"))
    assert len(tmp_files) == 0


def test_atomic_write_json_stale_temp_cleanup(tmp_path):
    """Verify atomic_write_json garbage-collects stale temp files older than 60s."""
    target = tmp_path / "robot.json"

    # Simulate an orphaned temp file from a crash 120s ago
    stale_tmp = tmp_path / "robot.json.tmp.9999.1.1000"
    stale_tmp.write_text("abandoned temp content", encoding="utf-8")
    past_time = time.time() - 120.0
    os.utime(stale_tmp, (past_time, past_time))
    assert stale_tmp.exists()

    # Now execute an atomic write
    atomic_write_json(target, {"status": "active"})

    # The stale temp file should have been cleaned up automatically
    assert not stale_tmp.exists()


def test_atomic_write_json_parent_directory_creation(tmp_path):
    """Verify atomic_write_json creates deep parent directories if they do not exist."""
    deep_target = tmp_path / "nested" / "sub" / "folder" / "config.json"
    assert not deep_target.parent.exists()

    success = atomic_write_json(deep_target, {"nested": True})
    assert success is True
    assert deep_target.exists()
    assert safe_read_json(deep_target) == {"nested": True}


def test_safe_read_json_non_existent_file(tmp_path):
    """Verify safe_read_json immediately returns designated default when file does not exist."""
    missing = tmp_path / "missing_file.json"

    assert safe_read_json(missing) is None
    assert safe_read_json(missing, default={}) == {}
    assert safe_read_json(missing, default=[]) == []
    assert safe_read_json(missing, default="DEFAULT") == "DEFAULT"


def test_safe_read_json_valid_data(tmp_path):
    """Verify safe_read_json parses valid JSON data correctly."""
    target = tmp_path / "valid.json"
    payload = {"account": 12345, "equity": 10500.50, "pairs": ["XAUUSD", "EURUSD"]}
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = safe_read_json(target)
    assert result == payload


def test_safe_read_json_bak_recovery_on_corruption(tmp_path):
    """Verify safe_read_json recovers data from .bak when primary file suffers JSON corruption."""
    target = tmp_path / "critical_state.json"
    original_data = {"checkpoint": 42, "balance": 10250.0}

    # Step 1: Write valid data (creates target and target.bak)
    atomic_write_json(target, original_data)
    assert target.exists()
    assert (tmp_path / "critical_state.json.bak").exists()

    # Step 2: Corrupt primary file with garbage bytes
    with open(target, "wb") as f:
        f.write(b"{CORRUPTED_JSON_BYTES_NOT_VALID...")

    # Step 3: safe_read_json should detect JSONDecodeError and seamlessly recover from .bak
    recovered = safe_read_json(target, default={"checkpoint": 0})
    assert recovered == original_data


def test_safe_read_json_corrupted_without_bak_returns_default(tmp_path):
    """Verify safe_read_json returns default value when corrupted and no backup exists."""
    broken = tmp_path / "broken.json"
    broken.write_text("INVALID_JSON_WITHOUT_BAK", encoding="utf-8")

    result = safe_read_json(broken, default={"fallback": True})
    assert result == {"fallback": True}
