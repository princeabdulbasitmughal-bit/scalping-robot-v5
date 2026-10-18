"""
tests/test_batch122.py
Unit tests for Batch 122:
- tunnel_watchdog.py (calculate_backoff, URL extraction patterns, session expiry detection, process liveness, atomic status updates, risk aliases)
- omnicommand_server.py (_compute_grade, _enrich_live_status, API key validation, risk guard aliases)
"""

import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

import tunnel_watchdog as twd
import omnicommand_server as ocs


class TestBatch122(unittest.TestCase):

    def test_tunnel_calculate_backoff(self):
        """Test calculate_backoff exponential progression and input defenses."""
        self.assertEqual(twd.calculate_backoff(1), 15)
        self.assertEqual(twd.calculate_backoff(2), 30)
        self.assertEqual(twd.calculate_backoff(3), 60)
        self.assertEqual(twd.calculate_backoff(4), 120)
        self.assertEqual(twd.calculate_backoff(5), 240)
        self.assertEqual(twd.calculate_backoff(6), 300)
        self.assertEqual(twd.calculate_backoff(10), 300)

        # Boolean and invalid input defense
        self.assertEqual(twd.calculate_backoff(0), 15)
        self.assertEqual(twd.calculate_backoff(-5), 15)
        self.assertEqual(twd.calculate_backoff(True), 15)
        self.assertEqual(twd.calculate_backoff(False), 15)
        self.assertEqual(twd.calculate_backoff("invalid"), 15)

    def test_tunnel_extract_url_patterns(self):
        """Test extract_url matches primary serveo format and secondary fallback."""
        sample_log = "Forwarding HTTP traffic from https://scalper.serveo.net\nPress Ctrl-C to quit."
        url = twd.extract_url(content=sample_log)
        self.assertEqual(url, "https://scalper.serveo.net")

        # Fallback serveousercontent format
        fallback_log = "Tunnel active at https://xyz123.serveousercontent.com for port 8899"
        url_fb = twd.extract_url(content=fallback_log)
        self.assertEqual(url_fb, "https://xyz123.serveousercontent.com")

    def test_tunnel_extract_url_expired_or_closed(self):
        """Test extract_url returns None when session has closed or expired."""
        expired_log = "Forwarding HTTP traffic from https://test.serveo.net\nSession expired: reconnecting"
        self.assertIsNone(twd.extract_url(content=expired_log))

        closed_log = "Forwarding HTTP traffic from https://test.serveo.net\nConnection closed by remote host."
        self.assertIsNone(twd.extract_url(content=closed_log))

        empty_log = "Connecting to serveo.net..."
        self.assertIsNone(twd.extract_url(content=empty_log))

    def test_tunnel_is_tunnel_alive(self):
        """Test is_tunnel_alive with process polling state and log inspection."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running

        # Healthy log
        self.assertTrue(twd.is_tunnel_alive(mock_proc, content="Forwarding HTTP traffic from https://alive.serveo.net"))

        # Process exited
        mock_proc.poll.return_value = 1
        self.assertFalse(twd.is_tunnel_alive(mock_proc, content="Forwarding HTTP traffic from https://alive.serveo.net"))

        # Process running but expired log
        mock_proc.poll.return_value = None
        self.assertFalse(twd.is_tunnel_alive(mock_proc, content="session closed by remote"))

    def test_tunnel_update_live_status_and_set_url(self):
        """Test atomic updates for tunnel_url and live_status.json."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            tmp_url_f = tmp_path / "test_tunnel_url.txt"
            tmp_status_f = tmp_path / "live_status.json"

            tmp_status_f.write_text(json.dumps({"symbol": "XAUUSD", "balance": 10000.0}), encoding="utf-8")

            twd.set_tunnel_url("https://new.serveo.net", url_file=tmp_url_f, status_file=tmp_status_f)

            self.assertEqual(tmp_url_f.read_text(encoding="utf-8"), "https://new.serveo.net")
            updated = json.loads(tmp_status_f.read_text(encoding="utf-8"))
            self.assertEqual(updated.get("tunnel_url"), "https://new.serveo.net")
            self.assertEqual(updated.get("balance"), 10000.0)

    def test_tunnel_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on tunnel_watchdog."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_url_f = Path(tmp_dir) / "tunnel_url.txt"

            # Missing file -> blocked
            with patch.object(twd, "TUNNEL_URL", tmp_url_f):
                self.assertTrue(twd.is_entry_blocked())
                self.assertTrue(twd.is_blocked())

                # Empty file -> blocked
                tmp_url_f.write_text("   \n", encoding="utf-8")
                self.assertTrue(twd.is_entry_blocked())

                # Active URL -> unblocked
                tmp_url_f.write_text("https://active.serveo.net\n", encoding="utf-8")
                self.assertFalse(twd.is_entry_blocked())
                self.assertFalse(twd.is_blocked())

    def test_omnicommand_compute_grade(self):
        """Test _compute_grade grading bands."""
        self.assertEqual(ocs._compute_grade(95.0), "A+")
        self.assertEqual(ocs._compute_grade(88.0), "A")
        self.assertEqual(ocs._compute_grade(75.0), "B")
        self.assertEqual(ocs._compute_grade(70.0), "C")
        self.assertEqual(ocs._compute_grade(0.0), "C")

    def test_omnicommand_enrich_live_status(self):
        """Test _enrich_live_status field enrichment."""
        raw = {
            "symbol": "XAUUSD",
            "current_price": 2400.0,
            "win_rate_pct": 82.5,
            "trading_halted": False,
        }
        enriched = ocs._enrich_live_status(raw)
        self.assertEqual(enriched["win_rate"], 82.5)
        self.assertEqual(enriched["grade"], "B")
        self.assertIn("risk_guard", enriched)
        self.assertIn("ma_trend_filter", enriched)
        self.assertIn("opening_range_breakout", enriched)
        self.assertEqual(enriched["circuit_breaker_fired"], False)

    def test_omnicommand_require_api_key(self):
        """Test _require_api_key in open mode and secured mode."""
        # Open mode: no configured key
        with patch.object(ocs, "_CONFIGURED_API_KEY", ""):
            # Should return None without raising
            self.assertIsNone(ocs._require_api_key(api_key=None))
            self.assertIsNone(ocs._require_api_key(api_key="any_key"))

        # Secured mode: configured key exists
        with patch.object(ocs, "_CONFIGURED_API_KEY", "secret_token_123"):
            # Matching key succeeds
            self.assertIsNone(ocs._require_api_key(api_key="secret_token_123"))

            # Mismatched key raises 403
            with self.assertRaises(HTTPException) as ctx:
                ocs._require_api_key(api_key="wrong_key")
            self.assertEqual(ctx.exception.status_code, 403)

            # Missing key raises 403
            with self.assertRaises(HTTPException) as ctx2:
                ocs._require_api_key(api_key=None)
            self.assertEqual(ctx2.exception.status_code, 403)

    def test_omnicommand_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on omnicommand_server."""
        # Normal healthy status
        normal_status = {"circuit_breaker_fired": False, "risk_guard": {}}
        with patch.object(ocs, "read_live_status", return_value=normal_status):
            self.assertFalse(ocs.is_entry_blocked())
            self.assertFalse(ocs.is_blocked())

        # Circuit breaker fired
        cb_status = {"circuit_breaker_fired": True, "risk_guard": {}}
        with patch.object(ocs, "read_live_status", return_value=cb_status):
            self.assertTrue(ocs.is_entry_blocked())
            self.assertTrue(ocs.is_blocked())

        # Risk guard daily loss halted
        rg_status = {"circuit_breaker_fired": False, "risk_guard": {"daily_loss_halted": True}}
        with patch.object(ocs, "read_live_status", return_value=rg_status):
            self.assertTrue(ocs.is_entry_blocked())
            self.assertTrue(ocs.is_blocked())


if __name__ == "__main__":
    unittest.main()
