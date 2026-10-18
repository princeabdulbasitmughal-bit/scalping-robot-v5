"""
tests/test_batch119.py
Unit tests for Batch 119:
- swarm_100_scalping_engine.py (ScalpingSwarm100, 10 strategic squadrons, parallel swarm execution, degraded health gating, risk aliases)
- bootstrap_launch.py (Process creation flags, detached execution, parameter overrides, safe directory logging, fail-closed risk guard)
"""

import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import swarm_100_scalping_engine as s100
import bootstrap_launch as bsl


class TestBatch119(unittest.TestCase):

    def test_swarm100_init_and_properties(self):
        """Test ScalpingSwarm100 initialization, paths, and initial report state."""
        swarm = s100.ScalpingSwarm100()
        self.assertIsNotNone(swarm.root)
        self.assertIsNotNone(swarm.report_file)
        self.assertIsNone(swarm.get_last_report())

        custom_root = Path("custom_root")
        custom_report = Path("custom_reports/test_report.json")
        custom_swarm = s100.ScalpingSwarm100(root_dir=custom_root, report_file=custom_report)
        self.assertEqual(custom_swarm.root, custom_root)
        self.assertEqual(custom_swarm.report_file, custom_report)

    def test_swarm100_execute_single_agent(self):
        """Test _execute_agent for subagents across different squadrons."""
        swarm = s100.ScalpingSwarm100()
        
        # Agent 1 (Squad 1: Market Feeds)
        res1 = swarm._execute_agent(1, fast=True)
        self.assertEqual(res1["id"], 1)
        self.assertEqual(res1["squadron_id"], 1)
        self.assertIn("Market Feeds", res1["squadron_name"])
        self.assertEqual(res1["status"], "OPTIMAL")

        # Agent 15 (Squad 2: Technical Indicators)
        res15 = swarm._execute_agent(15, fast=True)
        self.assertEqual(res15["id"], 15)
        self.assertEqual(res15["squadron_id"], 2)
        self.assertIn("RSI", res15["metric"])

        # Agent 95 (Squad 10: Watchdog & Telemetry)
        res95 = swarm._execute_agent(95, fast=True)
        self.assertEqual(res95["id"], 95)
        self.assertEqual(res95["squadron_id"], 10)
        self.assertIn("CPU", res95["metric"])

    def test_swarm100_execute_agent_with_live_status(self, tmp_path_factory=None):
        """Test _execute_agent when live_status.json is present."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            status_file = tmp_root / "live_status.json"
            status_file.write_text(json.dumps({
                "balance": 10500.50,
                "symbol": "XAUUSD",
                "trades_count": 12
            }), encoding="utf-8")

            swarm = s100.ScalpingSwarm100(root_dir=tmp_root)
            res1 = swarm._execute_agent(1, fast=True)
            self.assertIn("$10500.5", res1["metric"])
            self.assertIn("12", res1["details"])

    def test_swarm100_run_fast_execution(self):
        """Test run_swarm() in fast mode with report persistence."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            report_file = tmp_root / "reports" / "test_swarm100_report.json"
            swarm = s100.ScalpingSwarm100(root_dir=tmp_root, report_file=report_file)

            report = swarm.run_swarm(fast=True, max_workers=20, save_report=True)
            self.assertEqual(report["total_agents"], 100)
            self.assertEqual(len(report["agents"]), 100)
            self.assertEqual(len(report["squadrons"]), 10)
            self.assertGreaterEqual(report["optimal_count"], 90)
            self.assertTrue(report_file.exists())
            
            # Check cached report matches
            cached = swarm.get_last_report()
            self.assertEqual(cached["total_agents"], 100)

    def test_swarm100_resilience_on_subagent_exception(self):
        """Test that subagent exceptions are safely caught and reported as WARN."""
        swarm = s100.ScalpingSwarm100()
        original_exec = swarm._execute_agent

        def mock_exec(aid, fast=False):
            if aid in (11, 42):
                raise ValueError(f"Simulated subagent {aid} failure")
            return original_exec(aid, fast)

        with patch.object(swarm, "_execute_agent", side_effect=mock_exec):
            report = swarm.run_swarm(fast=True, max_workers=10, save_report=False)
            agent11 = next(r for r in report["agents"] if r["id"] == 11)
            agent42 = next(r for r in report["agents"] if r["id"] == 42)
            self.assertEqual(agent11["status"], "WARN")
            self.assertEqual(agent42["status"], "WARN")
            self.assertIn("Simulated subagent", agent11["metric"])
            self.assertEqual(report["warn_count"], 2)

    def test_swarm100_is_entry_blocked(self):
        """Test is_entry_blocked and is_blocked risk guard logic."""
        swarm = s100.ScalpingSwarm100()
        self.assertFalse(swarm.is_entry_blocked())
        self.assertFalse(swarm.is_blocked())

        # Unblocked with low warn_count
        swarm.last_report = {"warn_count": 5}
        self.assertFalse(swarm.is_entry_blocked())

        # Blocked with high warn_count (>25)
        swarm.last_report = {"warn_count": 30}
        self.assertTrue(swarm.is_entry_blocked())
        self.assertTrue(swarm.is_blocked())

        # Module level functions
        self.assertFalse(s100.is_entry_blocked())
        self.assertFalse(s100.is_blocked())

    def test_bootstrap_launch_flags(self):
        """Test get_launch_flags returns detached process flags."""
        flags = bsl.get_launch_flags()
        self.assertTrue(flags & bsl.DETACHED_PROCESS)
        self.assertTrue(flags & bsl.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & bsl.CREATE_NO_WINDOW)

    def test_bootstrap_get_supervisor_command(self):
        """Test get_supervisor_command returns correct command and respects overrides."""
        cmd_default = bsl.get_supervisor_command()
        self.assertEqual(len(cmd_default), 2)
        self.assertIn("supervisor.py", cmd_default[1])

        custom_cmd = bsl.get_supervisor_command(python_exe="custom_python.exe", supervisor_script="custom_sup.py")
        self.assertEqual(custom_cmd, ["custom_python.exe", "custom_sup.py"])

    def test_bootstrap_launch_supervisor_mocked(self):
        """Test launch_supervisor executes Popen with expected parameters."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_log = Path(tmp_dir) / "nested" / "supervisor_test.log"
            with patch("subprocess.Popen") as mock_popen:
                mock_proc = MagicMock()
                mock_proc.pid = 9999
                mock_popen.return_value = mock_proc

                proc = bsl.launch_supervisor(log_path=tmp_log)
                self.assertEqual(proc.pid, 9999)
                self.assertTrue(tmp_log.parent.exists())
                mock_popen.assert_called_once()
                call_kwargs = mock_popen.call_args[1]
                self.assertEqual(call_kwargs["creationflags"], bsl.get_launch_flags())
                self.assertTrue(call_kwargs["close_fds"])

    def test_bootstrap_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on bootstrap_launch."""
        # SUP exists in repository root
        self.assertFalse(bsl.is_entry_blocked())
        self.assertFalse(bsl.is_blocked())

        # SUP does not exist scenario
        with patch.object(bsl, "SUP", Path("non_existent_supervisor_script.py")):
            self.assertTrue(bsl.is_entry_blocked())
            self.assertTrue(bsl.is_blocked())


if __name__ == "__main__":
    unittest.main()
