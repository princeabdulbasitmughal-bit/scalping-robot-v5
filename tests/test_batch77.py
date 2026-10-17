"""
tests/test_batch77.py
Batch 77 Unit Tests: Gold News Fetcher & Macro Safeguards (gold_news_fetcher.py) and
Universal MetaTrader Auto-Installer (auto_install_to_mt4.py).
Expands test baseline beyond 1,017+ passing tests.
Verifies:
1. gold_news_fetcher: Keyword whole-word boundary matching (avoids false-positive substrings).
2. gold_news_fetcher: check_high_impact detection across headlines.
3. gold_news_fetcher: fetch_rss XML parsing from mocked network response.
4. gold_news_fetcher: fetch_rss failure returns None to distinguish from empty feed.
5. gold_news_fetcher: write_status atomic file writing and schema validation.
6. gold_news_fetcher: _load_last_status and _load_last_avoid_trading fail-safe fallbacks.
7. auto_install_to_mt4: install_to_target EA and Presets file distribution.
8. auto_install_to_mt4: Case-insensitive extension handling (.EX4, .MQ4, .SET).
9. auto_install_to_mt4: Missing source directory fault tolerance.
10. auto_install_to_mt4: find_mt4_directories MetaQuotes AppData terminal discovery.
"""

import io
import json
import os
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch, MagicMock
import pytest

import gold_news_fetcher
import auto_install_to_mt4


def test_gold_news_fetcher_whole_word_regex_guard():
    """Verify keyword patterns match whole words and prevent substring false positives."""
    # 1. 'fed' should match 'Fed' but NOT 'forward', 'modified', 'unified'
    fed_pat = next(p for p in gold_news_fetcher._KW_PATTERNS if p.pattern == r"\bfed\b")
    assert fed_pat.search("Fed signals interest rate adjustments") is not None
    assert fed_pat.search("Looking forward to market open") is None
    assert fed_pat.search("Modified trading strategy active") is None
    assert fed_pat.search("Unified framework deployed") is None

    # 2. 'war' should match 'war' but NOT 'award', 'warning', 'software'
    war_pat = next(p for p in gold_news_fetcher._KW_PATTERNS if p.pattern == r"\bwar\b")
    assert war_pat.search("Middle East war escalation impacts oil and gold") is not None
    assert war_pat.search("Trader won annual trading award") is None
    assert war_pat.search("Software update completed") is None


def test_gold_news_fetcher_check_high_impact_matches():
    """Verify check_high_impact detects macro risk headlines and returns matched text."""
    # Scenario A: High impact event
    headlines_a = [
        ("gold steady in early london trade", "Wed, 17 Oct 2026 08:00:00 GMT"),
        ("federal reserve discusses inflation and cpi trajectory", "Wed, 17 Oct 2026 08:30:00 GMT"),
    ]
    high_impact, matched = gold_news_fetcher.check_high_impact(headlines_a)
    assert high_impact is True
    assert "federal reserve discusses inflation" in matched

    # Scenario B: Calm market headlines
    headlines_b = [
        ("gold trading in tight range near 2650", "Wed, 17 Oct 2026 09:00:00 GMT"),
        ("jewelry demand increases in asia", "Wed, 17 Oct 2026 09:15:00 GMT"),
    ]
    high_impact_b, matched_b = gold_news_fetcher.check_high_impact(headlines_b)
    assert high_impact_b is False
    assert matched_b == ""

    # Scenario C: Empty headlines
    high_impact_c, matched_c = gold_news_fetcher.check_high_impact([])
    assert high_impact_c is False
    assert matched_c == ""


def test_gold_news_fetcher_fetch_rss_xml_parsing():
    """Verify fetch_rss parses XML item titles and publication dates into tuples."""
    mock_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Yahoo Finance: GC=F</title>
        <item>
          <title>Gold Prices Rise on Dollar Weakness</title>
          <pubDate>Wed, 17 Oct 2026 10:00:00 GMT</pubDate>
        </item>
        <item>
          <title>Central Bank Reserves Continue to Expand</title>
          <pubDate>Wed, 17 Oct 2026 10:30:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_xml
    mock_resp.__enter__.return_value = mock_resp

    with patch("gold_news_fetcher.urlopen", return_value=mock_resp):
        items = gold_news_fetcher.fetch_rss("https://mock.feeds.yahoo.com/rss")

    assert items is not None
    assert len(items) == 2
    assert items[0][0] == "gold prices rise on dollar weakness"
    assert items[0][1] == "Wed, 17 Oct 2026 10:00:00 GMT"


def test_gold_news_fetcher_fetch_rss_failure_returns_none():
    """Verify fetch_rss returns None on network exception to signal failure (fail-safe)."""
    with patch("gold_news_fetcher.urlopen", side_effect=URLError("Connection refused")):
        items = gold_news_fetcher.fetch_rss("https://dead.endpoint.com")
    assert items is None


def test_gold_news_fetcher_write_status_atomic(tmp_path, monkeypatch):
    """Verify write_status atomically writes status JSON without corruption."""
    status_file = tmp_path / "news_status.json"
    monkeypatch.setattr(gold_news_fetcher, "NEWS_STATUS_FILE", str(status_file))

    headlines = [
        ("fed rate cut anticipated", "2026-10-17"),
        ("inflation report scheduled", "2026-10-17"),
    ]
    gold_news_fetcher.write_status(high_impact=True, headlines=headlines, avoid_trading=True)

    assert status_file.exists()
    with open(status_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["high_impact_alert"] is True
    assert data["avoid_trading"] is True
    assert len(data["last_headlines"]) == 2
    assert "last_checked" in data


def test_gold_news_fetcher_load_last_status_fallback(tmp_path, monkeypatch):
    """Verify _load_last_status and _load_last_avoid_trading safely handle missing and corrupt files."""
    status_file = tmp_path / "news_status.json"
    monkeypatch.setattr(gold_news_fetcher, "NEWS_STATUS_FILE", str(status_file))

    # 1. Missing file -> safe empty fallback
    assert gold_news_fetcher._load_last_status() == {}
    assert gold_news_fetcher._load_last_avoid_trading() is False

    # 2. Valid file with avoid_trading: True
    status_file.write_text(json.dumps({"avoid_trading": True}), encoding="utf-8")
    assert gold_news_fetcher._load_last_avoid_trading() is True

    # 3. Corrupted file -> catches error safely
    status_file.write_text("NOT_VALID_JSON{{{", encoding="utf-8")
    assert gold_news_fetcher._load_last_status() == {}
    assert gold_news_fetcher._load_last_avoid_trading() is False


def test_auto_install_to_mt4_install_to_target_distribution(tmp_path):
    """Verify install_to_target distributes EA (.ex4, .mq4) and Presets (.set) to target."""
    target_dir = tmp_path / "MT4_Terminal"
    experts_src = tmp_path / "src_experts"
    presets_src = tmp_path / "src_presets"
    experts_src.mkdir()
    presets_src.mkdir()

    # Create dummy source files
    (experts_src / "ScalpingRobotV5.ex4").write_text("mock binary", encoding="utf-8")
    (experts_src / "ScalpingRobotV5.mq4").write_text("// mock source", encoding="utf-8")
    (experts_src / "readme.txt").write_text("ignore this file", encoding="utf-8")

    (presets_src / "Aggressive_Gold.set").write_text("LotSize=0.02", encoding="utf-8")
    (presets_src / "config.ini").write_text("ignore this file", encoding="utf-8")

    installed = auto_install_to_mt4.install_to_target(
        target_dir=str(target_dir),
        experts_src=str(experts_src),
        presets_src=str(presets_src),
    )

    # Check installed files list
    assert len(installed) == 3
    assert any("ScalpingRobotV5.ex4" in s for s in installed)
    assert any("ScalpingRobotV5.mq4" in s for s in installed)
    assert any("Aggressive_Gold.set" in s for s in installed)

    # Check target directory layout
    dst_experts = target_dir / "MQL4" / "Experts"
    dst_presets = target_dir / "MQL4" / "Presets"
    assert (dst_experts / "ScalpingRobotV5.ex4").exists()
    assert (dst_experts / "ScalpingRobotV5.mq4").exists()
    assert not (dst_experts / "readme.txt").exists()
    assert (dst_presets / "Aggressive_Gold.set").exists()
    assert not (dst_presets / "config.ini").exists()


def test_auto_install_to_mt4_case_insensitive_extensions(tmp_path):
    """Verify install_to_target handles uppercase file extensions (.EX4, .MQ4, .SET)."""
    target_dir = tmp_path / "MT4_Terminal"
    experts_src = tmp_path / "src_experts"
    presets_src = tmp_path / "src_presets"
    experts_src.mkdir()
    presets_src.mkdir()

    (experts_src / "ROBOT_V5.EX4").write_text("binary", encoding="utf-8")
    (presets_src / "SCALPER_PRO.SET").write_text("params", encoding="utf-8")

    installed = auto_install_to_mt4.install_to_target(
        target_dir=str(target_dir),
        experts_src=str(experts_src),
        presets_src=str(presets_src),
    )

    assert len(installed) == 2
    assert (target_dir / "MQL4" / "Experts" / "ROBOT_V5.EX4").exists()
    assert (target_dir / "MQL4" / "Presets" / "SCALPER_PRO.SET").exists()


def test_auto_install_to_mt4_missing_source_dirs_graceful(tmp_path):
    """Verify install_to_target safely creates directories when source dirs do not exist."""
    target_dir = tmp_path / "MT4_Terminal"
    non_existent_exp = tmp_path / "does_not_exist_exp"
    non_existent_pre = tmp_path / "does_not_exist_pre"

    installed = auto_install_to_mt4.install_to_target(
        target_dir=str(target_dir),
        experts_src=str(non_existent_exp),
        presets_src=str(non_existent_pre),
    )

    assert installed == []
    assert (target_dir / "MQL4" / "Experts").exists()
    assert (target_dir / "MQL4" / "Presets").exists()


def test_auto_install_to_mt4_find_mt4_directories_parsing(tmp_path, monkeypatch):
    """Verify find_mt4_directories discovers terminal folders inside MetaQuotes/Terminal."""
    appdata_mock = tmp_path / "AppData" / "Roaming"
    terminals_dir = appdata_mock / "MetaQuotes" / "Terminal"
    mock_instance = terminals_dir / "50CA3DFB510CAD5A8F270B351261FB21"
    (mock_instance / "MQL4").mkdir(parents=True)

    monkeypatch.setenv("APPDATA", str(appdata_mock))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "empty_prog"))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "empty_prog_x86"))

    found = auto_install_to_mt4.find_mt4_directories()
    assert len(found) >= 1
    assert str(mock_instance) in found
