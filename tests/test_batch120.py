"""
tests/test_batch120.py
Unit tests for Batch 120:
- escape_launch.py (Breakaway flags, fallback flags, parameter overrides, safe directory logging, breakaway / fallback mode switching, fail-closed risk guard)
- auto_install_to_mt4.py (Terminal directory discovery, EA and preset copying, error isolation, risk aliases)
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import escape_launch as el
import auto_install_to_mt4 as aim


class TestBatch120(unittest.TestCase):

    def test_escape_launch_breakaway_flags(self):
        """Test get_breakaway_flags returns expected bits."""
        flags = el.get_breakaway_flags()
        self.assertTrue(flags & el.DETACHED_PROCESS)
        self.assertTrue(flags & el.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & el.CREATE_NO_WINDOW)
        self.assertTrue(flags & el.CREATE_BREAKAWAY_FROM_JOB)

    def test_escape_launch_fallback_flags(self):
        """Test get_fallback_flags returns flags without breakaway."""
        flags = el.get_fallback_flags()
        self.assertTrue(flags & el.DETACHED_PROCESS)
        self.assertTrue(flags & el.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & el.CREATE_NO_WINDOW)
        self.assertFalse(flags & el.CREATE_BREAKAWAY_FROM_JOB)

    def test_escape_launch_get_watchdog_command(self):
        """Test get_watchdog_command with defaults and overrides."""
        cmd_def = el.get_watchdog_command()
        self.assertEqual(len(cmd_def), 2)
        self.assertIn("watchdog_runner.py", cmd_def[1])

        custom_cmd = el.get_watchdog_command(python_exe="custom_py.exe", watchdog_script="custom_wd.py")
        self.assertEqual(custom_cmd, ["custom_py.exe", "custom_wd.py"])

    def test_escape_launch_watchdog_breakaway_success(self):
        """Test launch_watchdog succeeds on breakaway path."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_f = Path(tmp_dir) / "sub" / "out.log"
            err_f = Path(tmp_dir) / "sub" / "err.log"

            with patch("subprocess.Popen") as mock_popen:
                mock_proc = MagicMock()
                mock_proc.pid = 1234
                mock_popen.return_value = mock_proc

                proc, mode = el.launch_watchdog(out_path=out_f, err_path=err_f)
                self.assertEqual(mode, "BREAKAWAY")
                self.assertEqual(proc.pid, 1234)
                self.assertTrue(out_f.parent.exists())
                mock_popen.assert_called_once()
                self.assertEqual(mock_popen.call_args[1]["creationflags"], el.get_breakaway_flags())

    def test_escape_launch_watchdog_fallback_on_permission_error(self):
        """Test launch_watchdog falls back to fallback flags on PermissionError."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_f = Path(tmp_dir) / "sub" / "out.log"
            err_f = Path(tmp_dir) / "sub" / "err.log"

            with patch("subprocess.Popen") as mock_popen:
                mock_proc_fallback = MagicMock()
                mock_proc_fallback.pid = 5678
                # First call raises PermissionError (breakaway denied), second succeeds
                mock_popen.side_effect = [PermissionError("Breakaway denied"), mock_proc_fallback]

                proc, mode = el.launch_watchdog(out_path=out_f, err_path=err_f)
                self.assertEqual(mode, "FALLBACK")
                self.assertEqual(proc.pid, 5678)
                self.assertEqual(mock_popen.call_count, 2)
                self.assertEqual(mock_popen.call_args[1]["creationflags"], el.get_fallback_flags())

    def test_escape_launch_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on escape_launch."""
        # WATCHDOG exists in project root
        self.assertFalse(el.is_entry_blocked())
        self.assertFalse(el.is_blocked())

        # If WATCHDOG does not exist, fail-closed block
        with patch.object(el, "WATCHDOG", Path("non_existent_watchdog.py")):
            self.assertTrue(el.is_entry_blocked())
            self.assertTrue(el.is_blocked())

    def test_auto_install_find_mt4_directories(self):
        """Test find_mt4_directories with mock APPDATA structure."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_appdata = Path(tmp_dir)
            mock_term = mock_appdata / "MetaQuotes" / "Terminal" / "INSTANCE_ABC" / "MQL4"
            mock_term.mkdir(parents=True, exist_ok=True)

            with patch.dict(os.environ, {"APPDATA": str(mock_appdata), "PROGRAMFILES": "", "PROGRAMFILES(X86)": ""}):
                with patch("string.ascii_uppercase", ""):
                    found = aim.find_mt4_directories()
                    self.assertEqual(len(found), 1)
                    self.assertIn("INSTANCE_ABC", found[0])

    def test_auto_install_to_target_success(self):
        """Test install_to_target successfully copies EA and preset files."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            src_exp = tmp_path / "src_experts"
            src_pre = tmp_path / "src_presets"
            src_exp.mkdir()
            src_pre.mkdir()

            (src_exp / "Scalper.mq4").write_text("// EA source", encoding="utf-8")
            (src_exp / "Scalper.ex4").write_text("BINARY", encoding="utf-8")
            (src_exp / "Readme.txt").write_text("Doc", encoding="utf-8")  # Non-EA file
            (src_pre / "Safe.set").write_text("param=1", encoding="utf-8")

            target = tmp_path / "target_mt4"
            installed = aim.install_to_target(str(target), experts_src=src_exp, presets_src=src_pre)

            self.assertEqual(len(installed), 3)
            self.assertTrue((target / "MQL4" / "Experts" / "Scalper.mq4").exists())
            self.assertTrue((target / "MQL4" / "Experts" / "Scalper.ex4").exists())
            self.assertFalse((target / "MQL4" / "Experts" / "Readme.txt").exists())
            self.assertTrue((target / "MQL4" / "Presets" / "Safe.set").exists())

    def test_auto_install_to_target_permission_error(self):
        """Test install_to_target handles directory creation failure gracefully."""
        with patch("os.makedirs", side_effect=PermissionError("Access Denied")):
            res = aim.install_to_target("invalid_dir")
            self.assertEqual(res, [])

    def test_auto_install_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked aliases for auto_install_to_mt4."""
        self.assertFalse(aim.is_entry_blocked())
        self.assertFalse(aim.is_blocked())


if __name__ == "__main__":
    unittest.main()
