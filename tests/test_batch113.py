import os
import json
import tempfile
import threading
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import email_alert
from email_alert import EmailAlerter, get_alerter
import gold_news_fetcher


def test_email_alert_init_and_template_creation():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = os.path.join(tmpdir, "subdir", "email_config.json")
        alerter = EmailAlerter(config_file=cfg_file)
        assert os.path.exists(cfg_file)
        assert alerter.config["enabled"] is False
        assert alerter.config["smtp_host"] == "smtp.gmail.com"
        assert alerter.config["smtp_port"] == 587


def test_email_alert_update_config_and_persist():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = os.path.join(tmpdir, "email_config.json")
        alerter = EmailAlerter(config_file=cfg_file)
        new_data = {
            "from_email": "bot@goldscalper.io",
            "password": "secret_app_password",
            "to_email": "trader@goldscalper.io",
            "enabled": True,
        }
        alerter.update_config(new_data, persist=True)
        assert alerter.config["from_email"] == "bot@goldscalper.io"
        assert alerter.config["enabled"] is True

        # Verify disk persistence
        with open(cfg_file, "r", encoding="utf-8") as f:
            disk_cfg = json.load(f)
        assert disk_cfg["from_email"] == "bot@goldscalper.io"
        assert disk_cfg["enabled"] is True


def test_email_alert_send_alert_disabled_or_missing_creds():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = os.path.join(tmpdir, "email_config.json")
        alerter = EmailAlerter(config_file=cfg_file)
        # Disabled by default
        assert alerter.send_alert("Test Alert", "Body message") is False

        # Enabled but incomplete credentials
        alerter.update_config({"enabled": True, "from_email": "bot@test.com", "to_email": ""}, persist=True)
        assert alerter.send_alert("Test Alert", "Body message") is False


def test_email_alert_send_alert_success_with_mock_smtp():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = os.path.join(tmpdir, "email_config.json")
        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server
        mock_server.__exit__.return_value = False
        mock_factory = MagicMock(return_value=mock_server)

        alerter = EmailAlerter(config_file=cfg_file, smtp_factory=mock_factory)
        alerter.update_config({
            "enabled": True,
            "from_email": "sender@test.com",
            "password": "pass",
            "to_email": "recipient@test.com",
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
        }, persist=True)

        res = alerter.send_alert("Circuit Breaker Tripped", "Max daily drawdown reached: -3.5%")
        assert res is True
        mock_server.login.assert_called_once_with("sender@test.com", "pass")
        mock_server.send_message.assert_called_once()


def test_email_alert_test_connection_and_risk_aliases():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = os.path.join(tmpdir, "email_config.json")
        mock_server = MagicMock()
        mock_factory = MagicMock(return_value=mock_server)

        alerter = EmailAlerter(config_file=cfg_file, smtp_factory=mock_factory)
        alerter.update_config({
            "from_email": "admin@test.com",
            "password": "pwd",
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
        })
        assert alerter.test_connection() is True

        # Simulate connection error
        mock_factory.side_effect = ConnectionRefusedError("Connection refused")
        assert alerter.test_connection() is False

        # Unified risk aliases (never blocks trading)
        assert alerter.is_entry_blocked() is False
        assert alerter.is_blocked() is False
        assert email_alert.is_entry_blocked() is False
        assert email_alert.is_blocked() is False


def test_gold_news_fetcher_keyword_matching():
    # Whole-word matches
    impact, matched = gold_news_fetcher.check_high_impact([
        ("Fed keeps rates unchanged at FOMC meeting", "date"),
    ])
    assert impact is True
    assert "Fed" in matched or "FOMC" in matched or "rates" in matched

    impact, _ = gold_news_fetcher.check_high_impact([("US CPI inflation print hotter than expected", "date")])
    assert impact is True

    impact, _ = gold_news_fetcher.check_high_impact([("Non-farm payrolls surge past forecasts", "date")])
    assert impact is True

    # Substrings that must NOT trigger false positives
    no_impact, _ = gold_news_fetcher.check_high_impact([
        ("Federation of jewelers announces new award ceremony", "date"),
        ("Forward looking modified unified system launched", "date"),
    ])
    assert no_impact is False

    # Edge cases
    assert gold_news_fetcher.check_high_impact(None) == (False, "")
    assert gold_news_fetcher.check_high_impact([]) == (False, "")
    assert gold_news_fetcher.check_high_impact([("", "")]) == (False, "")


def test_gold_news_fetcher_write_status_and_read():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = os.path.join(tmpdir, "news_status.json")
        headlines = [
            ("FOMC minutes indicate potential rate hike", "2026-10-18T00:00:00Z"),
            ("Gold consolidates near $2650 support", "2026-10-18T00:05:00Z"),
        ]
        gold_news_fetcher.write_status(
            high_impact=True,
            headlines=headlines,
            avoid_trading=True,
            target_file=status_file,
        )

        assert os.path.exists(status_file)
        st = gold_news_fetcher._load_last_status(status_file=status_file)
        assert st["high_impact_alert"] is True
        assert st["avoid_trading"] is True
        assert len(st["last_headlines"]) == 2
        assert "FOMC minutes" in st["last_headlines"][0]

        avoid = gold_news_fetcher._load_last_avoid_trading(status_file=status_file)
        assert avoid is True


def test_gold_news_fetcher_is_entry_blocked_logic():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = os.path.join(tmpdir, "news_status.json")

        # Missing file defaults to False (fail-open for normal absence)
        assert gold_news_fetcher.is_entry_blocked(status_file=status_file) is False
        assert gold_news_fetcher.is_blocked(status_file=status_file) is False

        # avoid_trading = True -> blocked
        gold_news_fetcher.write_status(False, [], True, target_file=status_file)
        assert gold_news_fetcher.is_entry_blocked(status_file=status_file) is True
        assert gold_news_fetcher.is_blocked(status_file=status_file) is True

        # high_impact_alert = True -> blocked
        gold_news_fetcher.write_status(True, [], False, target_file=status_file)
        assert gold_news_fetcher.is_entry_blocked(status_file=status_file) is True

        # Both False -> allowed
        gold_news_fetcher.write_status(False, [], False, target_file=status_file)
        assert gold_news_fetcher.is_entry_blocked(status_file=status_file) is False

        # Corrupted JSON -> fail-closed
        with open(status_file, "w", encoding="utf-8") as f:
            f.write("INVALID JSON CONTENT {{{")
        assert gold_news_fetcher.is_entry_blocked(status_file=status_file) is True


def test_gold_news_fetcher_fetch_rss_mock():
    sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Yahoo Finance: GC=F</title>
        <item>
          <title>Gold surges after Jerome Powell speech</title>
          <pubDate>Sun, 18 Oct 2026 01:00:00 GMT</pubDate>
        </item>
        <item>
          <title>Dollar Index DXY slips on treasury yields</title>
          <pubDate>Sun, 18 Oct 2026 01:30:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = sample_xml
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch("gold_news_fetcher.urlopen", return_value=mock_resp):
        items = gold_news_fetcher.fetch_rss("https://example.com/rss", timeout=5)
        assert items is not None
        assert len(items) == 2
        assert items[0][0] == "gold surges after jerome powell speech"

    # Network failure handling
    with patch("gold_news_fetcher.urlopen", side_effect=URLError("DNS lookup failed")):
        failed = gold_news_fetcher.fetch_rss("https://example.com/rss", timeout=5)
        assert failed is None


def test_email_alert_singleton_and_concurrency():
    s1 = get_alerter()
    assert s1 is not None
    assert isinstance(s1, EmailAlerter)

    # Concurrency test
    errors = []
    def worker():
        try:
            for _ in range(50):
                s1.update_config({"enabled": False}, persist=False)
                _ = s1.is_entry_blocked()
                s1._reload_config()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
