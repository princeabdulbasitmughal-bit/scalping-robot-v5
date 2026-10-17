"""
tests/test_batch73.py
Batch 73 Unit Tests: 100-Subagent Ultra-Parallel Multi-Model Swarm Engine (swarm_100_scalping_engine.py).
Verifies:
1. Default and custom path initializations.
2. 100-agent to 10-squadron mapping and naming parity.
3. Squadron 1 live status file telemetry, fallback, and corrupted JSON resilience.
4. Squadrons 2 to 9 indicator, risk, news, and ML telemetry metrics.
5. Squadron 10 host telemetry metrics (CPU and RAM tracking via psutil).
6. Fast-mode latency bypass vs non-fast execution.
7. Resilience guard error containment and graceful status degradation.
8. Full swarm execution structure and 10-squadron aggregation.
9. Atomic report JSON file persistence and .tmp swap cleanup.
10. Thread safety across concurrent runs and cached report retrieval.
"""

import json
import time
import threading
from pathlib import Path
from unittest.mock import patch
import pytest

from swarm_100_scalping_engine import ScalpingSwarm100, ROOT_DIR, REPORT_FILE


def test_swarm100_initialization_defaults_and_custom_paths(tmp_path):
    """Verify ScalpingSwarm100 initializes correctly with defaults and custom paths."""
    # 1. Default initialization
    swarm_default = ScalpingSwarm100()
    assert swarm_default.root == ROOT_DIR
    assert swarm_default.report_file == REPORT_FILE
    assert swarm_default.get_last_report() is None

    # 2. Custom path initialization
    custom_root = tmp_path / "custom_root"
    custom_root.mkdir()
    custom_report = custom_root / "reports" / "custom_swarm.json"
    swarm_custom = ScalpingSwarm100(root_dir=custom_root, report_file=custom_report)
    assert swarm_custom.root == custom_root
    assert swarm_custom.report_file == custom_report
    assert swarm_custom.get_last_report() is None


def test_swarm100_squadron_mapping_coverage():
    """Verify all 100 agents map to the correct squadron IDs (1-10) and names."""
    swarm = ScalpingSwarm100()
    expected_squadrons = [
        (1, 10, 1, "Market Feeds & XAUUSD Tick Sentinel"),
        (11, 20, 2, "Technical Indicators & Trend Oscillators"),
        (21, 30, 3, "Volatility & Dynamic TP/SL Handlers"),
        (31, 40, 4, "Spread & Execution Governors"),
        (41, 50, 5, "Drawdown & Equity Circuit Breakers"),
        (51, 60, 6, "Profit Streak & Recovery Management"),
        (61, 70, 7, "Time, Session & News Safeguards"),
        (71, 80, 8, "Candlestick, Reversal & Pattern Detectors"),
        (81, 90, 9, "ML & Autonomous AI Prediction Matrix"),
        (91, 100, 10, "Process Watchdog, Live Heartbeat & Telemetry"),
    ]

    for start_id, end_id, squad_id, squad_name in expected_squadrons:
        for aid in (start_id, (start_id + end_id) // 2, end_id):
            agent_res = swarm._execute_agent(aid, fast=True)
            assert agent_res["id"] == aid
            assert agent_res["squadron_id"] == squad_id
            assert agent_res["squadron_name"] == squad_name
            assert agent_res["status"] == "OPTIMAL"
            assert agent_res["agent_name"].startswith(f"Agent-{aid:03d}-")


def test_swarm100_squad1_live_status_and_fallback(tmp_path):
    """Verify Squadron 1 parses live_status.json, falls back on missing, and recovers on corrupt file."""
    # Scenario A: Missing live_status.json -> Simulation Active
    swarm_a = ScalpingSwarm100(root_dir=tmp_path)
    res_a = swarm_a._execute_agent(1, fast=True)
    assert res_a["metric"] == "Simulation Active"
    assert "Simulated tick stream verified" in res_a["details"]

    # Scenario B: Valid live_status.json
    status_file = tmp_path / "live_status.json"
    status_file.write_text(
        json.dumps({"balance": 10850.75, "symbol": "XAUUSD", "trades_count": 25}),
        encoding="utf-8"
    )
    res_b = swarm_a._execute_agent(1, fast=True)
    assert "Balance: $10850.75" in res_b["metric"]
    assert "Symbol: XAUUSD" in res_b["metric"]
    assert "Trades: 25" in res_b["details"]

    # Scenario C: Corrupted live_status.json -> Fallback telemetry
    status_file.write_text("INVALID_JSON_CORRUPTED{{{", encoding="utf-8")
    res_c = swarm_a._execute_agent(1, fast=True)
    assert res_c["metric"] == "Mock Feed Online"
    assert "fallback telemetry" in res_c["details"]


def test_swarm100_squadrons_2_to_9_telemetry_metrics():
    """Verify Squadrons 2 through 9 emit appropriate scalping and risk telemetry."""
    swarm = ScalpingSwarm100()

    # Squadron 2: Technical Indicators
    s2 = swarm._execute_agent(15, fast=True)
    assert "RSI: 48.5" in s2["metric"]
    assert "EMA9/21: Neutral" in s2["metric"]

    # Squadron 3: Volatility & TP/SL
    s3 = swarm._execute_agent(25, fast=True)
    assert "ATR: 14.2 pips" in s3["metric"]
    assert "Dynamic SL: 25 pips" in s3["metric"]

    # Squadron 4: Spread & Execution
    s4 = swarm._execute_agent(35, fast=True)
    assert "Spread: 1.8 pips" in s4["metric"]
    assert "Max Allowed: 3.5 pips" in s4["metric"]

    # Squadron 5: Drawdown & Equity
    s5 = swarm._execute_agent(45, fast=True)
    assert "Daily Drawdown: 0.00%" in s5["metric"]
    assert "Ceiling: 3.5%" in s5["metric"]

    # Squadron 6: Profit Streak & Recovery
    s6 = swarm._execute_agent(55, fast=True)
    assert "Streak: +3 consecutive wins" in s6["metric"]
    assert "Lot Multiplier: 1.0x" in s6["metric"]

    # Squadron 7: Time, Session & News
    s7 = swarm._execute_agent(65, fast=True)
    assert "Session: Overlap London-NY" in s7["metric"]
    assert "High Impact News: Clear" in s7["metric"]

    # Squadron 8: Candlestick & Reversal
    s8 = swarm._execute_agent(75, fast=True)
    assert "Pattern: Pinbar Bullish Confirmation" in s8["metric"]
    assert "Reversal: False" in s8["metric"]

    # Squadron 9: ML Prediction Matrix
    s9 = swarm._execute_agent(85, fast=True)
    assert "Direction: BULLISH" in s9["metric"]
    assert "Model: Qwen 32B + Random Forest" in s9["metric"]


def test_swarm100_squad10_host_telemetry():
    """Verify Squadron 10 measures host CPU and RAM telemetry via psutil."""
    swarm = ScalpingSwarm100()
    res = swarm._execute_agent(95, fast=True)

    assert res["squadron_id"] == 10
    assert res["squadron_name"] == "Process Watchdog, Live Heartbeat & Telemetry"
    assert "Host CPU:" in res["metric"]
    assert "RAM:" in res["metric"]
    assert "System Watchdog #95" in res["details"]
    assert res["status"] == "OPTIMAL"


def test_swarm100_fast_mode_latency():
    """Verify fast=True completes with low latency (< 100ms per agent)."""
    swarm = ScalpingSwarm100()
    res = swarm._execute_agent(50, fast=True)

    assert res["status"] == "OPTIMAL"
    assert isinstance(res["latency_ms"], float)
    assert res["latency_ms"] >= 0.0
    assert res["latency_ms"] < 100.0  # Fast mode bypasses 5-15ms intentional sleep


def test_swarm100_resilience_guard_on_exception(tmp_path):
    """Verify run_swarm gracefully catches subagent exceptions and records WARN status."""
    report_file = tmp_path / "reports" / "resilience_report.json"
    swarm = ScalpingSwarm100(root_dir=tmp_path, report_file=report_file)

    orig_execute = swarm._execute_agent

    def mock_execute(aid, fast=False):
        if aid == 42:
            raise RuntimeError("Simulated neural disconnect")
        return orig_execute(aid, fast)

    with patch.object(swarm, "_execute_agent", side_effect=mock_execute):
        report = swarm.run_swarm(fast=True, max_workers=10, save_report=False)

    assert report["total_agents"] == 100
    assert report["optimal_count"] == 99
    assert report["warn_count"] == 1
    assert report["health_score"] == "99.0%"

    # Agent 42 inspection
    agent_42 = next(a for a in report["agents"] if a["id"] == 42)
    assert agent_42["status"] == "WARN"
    assert "Simulated neural disconnect" in agent_42["metric"]
    assert agent_42["details"] == "Recovered by Swarm Resilience Guard"

    # Squadron 5 aggregation inspection
    squad_5 = next(s for s in report["squadrons"] if s["squadron_id"] == 5)
    assert squad_5["agents_count"] == 10
    assert squad_5["optimal_count"] == 9
    assert squad_5["health"] == "90.0%"


def test_swarm100_full_run_structure_and_squadrons_aggregation(tmp_path):
    """Verify run_swarm outputs complete schema with 10 squadrons and 100 agents."""
    report_file = tmp_path / "reports" / "full_swarm_report.json"
    swarm = ScalpingSwarm100(root_dir=tmp_path, report_file=report_file)

    report = swarm.run_swarm(fast=True, max_workers=20, save_report=False)

    assert report["title"] == "Scalping Robot V5 — 100-Subagent Ultra-Parallel Burst Swarm Report"
    assert report["total_agents"] == 100
    assert report["optimal_count"] == 100
    assert report["warn_count"] == 0
    assert report["health_score"] == "100.0%"
    assert len(report["squadrons"]) == 10
    assert len(report["agents"]) == 100

    # Verify agent IDs are sequentially ordered 1..100
    for idx, agent in enumerate(report["agents"], start=1):
        assert agent["id"] == idx

    # Verify all 10 squadrons have 10 agents and 100.0% health
    for s_idx, squad in enumerate(report["squadrons"], start=1):
        assert squad["squadron_id"] == s_idx
        assert squad["agents_count"] == 10
        assert squad["optimal_count"] == 10
        assert squad["health"] == "100.0%"


def test_swarm100_report_file_persistence_atomic(tmp_path):
    """Verify run_swarm persists report file atomically via .tmp replace without temp leftovers."""
    report_file = tmp_path / "reports" / "persisted_swarm_report.json"
    swarm = ScalpingSwarm100(root_dir=tmp_path, report_file=report_file)

    report = swarm.run_swarm(fast=True, max_workers=10, save_report=True)

    assert report_file.exists()
    tmp_candidate = report_file.with_suffix(".tmp")
    assert not tmp_candidate.exists()

    with open(report_file, "r", encoding="utf-8") as f:
        persisted_data = json.load(f)

    assert persisted_data["total_agents"] == 100
    assert persisted_data["health_score"] == report["health_score"]
    assert len(persisted_data["agents"]) == 100


def test_swarm100_thread_safety_and_cached_report(tmp_path):
    """Verify concurrent runs and get_last_report access remain thread-safe."""
    report_file = tmp_path / "reports" / "concurrency_report.json"
    swarm = ScalpingSwarm100(root_dir=tmp_path, report_file=report_file)

    errors = []

    def worker_run():
        try:
            res = swarm.run_swarm(fast=True, max_workers=5, save_report=False)
            assert res["total_agents"] == 100
        except Exception as exc:
            errors.append(exc)

    def worker_read():
        try:
            for _ in range(10):
                rep = swarm.get_last_report()
                if rep is not None:
                    assert rep["total_agents"] == 100
                time.sleep(0.005)
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker_run),
        threading.Thread(target=worker_run),
        threading.Thread(target=worker_read),
        threading.Thread(target=worker_read),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrency test encountered errors: {errors}"
    final_report = swarm.get_last_report()
    assert final_report is not None
    assert final_report["total_agents"] == 100
