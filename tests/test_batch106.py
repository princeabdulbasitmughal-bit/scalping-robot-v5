"""
tests/test_batch106.py
======================
Unit tests for Batch 106:
- wave20_spike_filter.py (SpikeFilter)
- wave21_news_guard.py (NewsGuard)
"""

import json
import math
import os
import time
import pytest
from wave20_spike_filter import SpikeFilter
from wave21_news_guard import NewsGuard


# =====================================================================
# SpikeFilter Tests (wave20)
# =====================================================================

def test_spike_filter_init_defaults():
    sf = SpikeFilter()
    assert sf.spike_ratio_threshold == 4.0
    assert sf.cooldown_sec == 90.0
    assert sf.lookback == 20
    assert sf.cluster_window_sec == 300.0
    assert sf.cluster_count_limit == 3
    assert sf.is_blocked() is False
    assert sf.is_entry_blocked() is False

    # Invalid / fallback inputs
    sf_bad = SpikeFilter(
        spike_ratio_threshold=-1.0,
        cooldown_sec=-5.0,
        lookback=-10,
        cluster_window_sec=-100.0,
        cluster_count_limit=-2,
    )
    assert sf_bad.spike_ratio_threshold == 4.0
    assert sf_bad.cooldown_sec == 90.0
    assert sf_bad.lookback == 20
    assert sf_bad.cluster_window_sec == 300.0
    assert sf_bad.cluster_count_limit == 3


def test_spike_filter_warmup():
    sf = SpikeFilter()
    t0 = 1000.0
    # Fewer than 5 tick changes -> always allowed
    for i in range(4):
        allowed, reason = sf.check(100.0 + i * 0.1, 100.0 + (i - 1) * 0.1, now_ts=t0 + i)
        assert allowed is True
        assert reason == "OK"


def test_spike_filter_spike_detection_and_cooldown():
    sf = SpikeFilter(spike_ratio_threshold=4.0, cooldown_sec=90.0)
    t0 = 1000.0
    # Seed with 5 steady changes of 0.1
    p = 100.0
    for i in range(5):
        sf.check(p + 0.1, p, now_ts=t0 + i)
        p += 0.1

    # Sudden spike of 1.0 (10x average change of 0.1)
    allowed, reason = sf.check(p + 1.0, p, now_ts=t0 + 10.0)
    assert allowed is False
    assert "SPIKE_DETECTED" in reason
    assert sf.is_blocked(now_ts=t0 + 10.0) is True
    assert sf.is_entry_blocked(now_ts=t0 + 10.0) is True

    # During cooldown (e.g., at t0 + 50.0s < t0 + 10.0 + 90.0s) -> blocked
    allowed, reason = sf.check(p + 1.05, p + 1.0, now_ts=t0 + 50.0)
    assert allowed is False
    assert "SPIKE_COOLDOWN" in reason

    # After cooldown expires (e.g., at t0 + 110.0s > t0 + 100.0s) -> allowed
    allowed, reason = sf.check(p + 1.06, p + 1.05, now_ts=t0 + 110.0)
    assert allowed is True
    assert sf.is_blocked(now_ts=t0 + 110.0) is False


def test_spike_filter_spike_cluster():
    sf = SpikeFilter(spike_ratio_threshold=3.0, cooldown_sec=10.0, cluster_window_sec=300.0, cluster_count_limit=3)
    t0 = 1000.0
    # Seed history with 10 small changes
    p = 100.0
    for i in range(10):
        sf.check(p + 0.05, p, now_ts=t0 + i)
        p += 0.05

    # Spike 1 (large move to register as spike)
    t1 = t0 + 20.0
    allowed1, r1 = sf.check(p + 2.0, p, now_ts=t1)
    assert allowed1 is False
    assert "SPIKE_DETECTED" in r1
    p += 2.0

    # Wait past cooldown 1 (10s), then Spike 2
    t2 = t1 + 15.0
    allowed2, r2 = sf.check(p + 2.0, p, now_ts=t2)
    assert allowed2 is False
    assert "SPIKE_DETECTED" in r2
    p += 2.0

    # Wait past cooldown 2 (10s), then Spike 3 within cluster window
    t3 = t2 + 15.0
    allowed3, r3 = sf.check(p + 2.0, p, now_ts=t3)
    assert allowed3 is False
    assert "SPIKE" in r3
    p += 2.0

    # Now verify cluster check blocks subsequent normal tick while in cluster window
    t4 = t3 + 12.0  # past individual spike cooldown of 10s
    allowed4, reason4 = sf.check(p + 0.01, p, now_ts=t4)
    assert allowed4 is False
    assert "SPIKE_CLUSTER" in reason4


def test_spike_filter_fail_closed_invalid_prices():
    sf = SpikeFilter()
    # None inputs
    allowed, reason = sf.check(None, 100.0)
    assert allowed is False
    assert reason == "SPIKE_FILTER_INVALID_PRICE"

    allowed, reason = sf.check(100.0, None)
    assert allowed is False
    assert reason == "SPIKE_FILTER_INVALID_PRICE"

    # Boolean inputs
    allowed, reason = sf.check(True, 100.0)
    assert allowed is False
    assert reason == "SPIKE_FILTER_INVALID_PRICE"

    # NaN / Inf inputs
    allowed, reason = sf.check(float("nan"), 100.0)
    assert allowed is False
    assert reason == "SPIKE_FILTER_INVALID_PRICE"

    allowed, reason = sf.check(100.0, float("inf"))
    assert allowed is False
    assert reason == "SPIKE_FILTER_INVALID_PRICE"

    # String input
    allowed, reason = sf.check("100.0", 100.0)
    assert allowed is False
    assert reason == "SPIKE_FILTER_INVALID_PRICE"


def test_spike_filter_reset_and_info():
    sf = SpikeFilter()
    t0 = 2000.0
    for i in range(5):
        sf.check(100.0 + i * 0.1, 100.0 + (i - 1) * 0.1, now_ts=t0 + i)
    # Trigger spike
    sf.check(105.0, 100.4, now_ts=t0 + 10.0)
    inf = sf.info(now_ts=t0 + 15.0)
    assert inf["blocked"] is True
    assert inf["spikes_in_5min"] == 1
    assert inf["avg_tick_change"] > 0

    sf.reset()
    inf_clean = sf.info(now_ts=t0 + 15.0)
    assert inf_clean["blocked"] is False
    assert inf_clean["spikes_in_5min"] == 0
    assert inf_clean["avg_tick_change"] == 0.0
    assert sf.is_entry_blocked(now_ts=t0 + 15.0) is False


# =====================================================================
# NewsGuard Tests (wave21)
# =====================================================================

def test_news_guard_init_and_missing_file_fail_open(tmp_path):
    status_file = str(tmp_path / "non_existent_status.json")
    override_file = str(tmp_path / "non_existent_override.json")
    ng = NewsGuard(status_file=status_file, override_file=override_file)

    allowed, reason = ng.is_trading_allowed()
    assert allowed is True
    assert "not found — allow" in reason
    assert ng.is_entry_blocked() is False
    assert ng.is_blocked() is False


def test_news_guard_avoid_trading_active(tmp_path):
    status_file = str(tmp_path / "news_status.json")
    override_file = str(tmp_path / "news_override.json")

    status_data = {
        "avoid_trading": True,
        "last_headlines": ["US CPI Inflation MoM Exceeds Expectations"],
        "last_checked": "2026-10-18T03:00:00Z"
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f)

    ng = NewsGuard(status_file=status_file, override_file=override_file)
    allowed, reason = ng.is_trading_allowed()
    assert allowed is False
    assert "NEWS GUARD: US CPI Inflation MoM Exceeds Expectations" in reason
    assert ng.is_entry_blocked() is True
    assert ng.is_blocked() is True

    info = ng.info()
    assert info["avoid_trading"] is True
    assert info["blocked_total"] == 3


def test_news_guard_manual_override_precedence(tmp_path):
    status_file = str(tmp_path / "news_status.json")
    override_file = str(tmp_path / "news_override.json")

    # Even if status file says avoid_trading: True
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump({"avoid_trading": True, "last_headlines": ["FOMC Rate Decision"]}, f)

    # Override file forces override: True
    with open(override_file, "w", encoding="utf-8") as f:
        json.dump({"override": True}, f)

    ng = NewsGuard(status_file=status_file, override_file=override_file)
    allowed, reason = ng.is_trading_allowed()
    assert allowed is True
    assert "manual override active" in reason
    assert ng.is_entry_blocked() is False

    # Also test programmatic set_override
    ng.set_override(avoid=True, reason="manual pause")
    allowed2, reason2 = ng.is_trading_allowed()
    assert allowed2 is False
    assert reason2 == "manual pause"


def test_news_guard_cache_ttl_and_reset(tmp_path):
    status_file = str(tmp_path / "news_status.json")
    override_file = str(tmp_path / "news_override.json")

    # Initially clear
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump({"avoid_trading": False, "last_checked": "2026-10-18T00:00:00Z"}, f)

    ng = NewsGuard(status_file=status_file, override_file=override_file, cache_ttl=10.0)
    t0 = 1000.0
    allowed, _ = ng.is_trading_allowed(now_ts=t0)
    assert allowed is True

    # Modify status file to avoid_trading: True
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump({"avoid_trading": True, "last_headlines": ["Flash Crash"]}, f)

    # Within TTL (t0 + 5s < t0 + 10s), cached result still returned
    allowed_cached, _ = ng.is_trading_allowed(now_ts=t0 + 5.0)
    assert allowed_cached is True

    # Past TTL (t0 + 15s > t0 + 10s), file re-read and block detected
    allowed_expired, reason_expired = ng.is_trading_allowed(now_ts=t0 + 15.0)
    assert allowed_expired is False
    assert "Flash Crash" in reason_expired

    # Reset
    ng.reset()
    assert ng._blocked_count == 0
    assert ng._last_check_time == 0.0
