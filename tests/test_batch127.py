import os
import json
import time
import pytest
from wave20_spike_filter import SpikeFilter, spike_filter, is_entry_blocked as w20_is_entry_blocked, is_blocked as w20_is_blocked
from wave21_news_guard import NewsGuard, news_guard, is_entry_blocked as w21_is_entry_blocked, is_blocked as w21_is_blocked, is_trading_allowed as w21_is_trading_allowed


class TestBatch127:
    """Batch 127 Test Suite: wave20 Spike Filter and wave21 News Guard."""

    def test_wave20_risk_guard_aliases(self):
        sf = SpikeFilter()
        assert sf.is_blocked(now_ts=1000.0) is False
        assert sf.is_entry_blocked(now_ts=1000.0) is False
        
        # Trigger cooldown
        sf._blocked_until = 1100.0
        assert sf.is_blocked(now_ts=1050.0) is True
        assert sf.is_entry_blocked(now_ts=1050.0) is True
        assert sf.is_blocked(now_ts=1101.0) is False

        # Module-level aliases
        spike_filter.reset()
        assert w20_is_blocked() is False
        assert w20_is_entry_blocked() is False

    def test_wave20_spike_detection(self):
        sf = SpikeFilter(spike_ratio_threshold=4.0, cooldown_sec=60.0)
        # Establish baseline tick change of ~0.10
        base_time = 1000.0
        for i in range(10):
            p1 = 2000.0 + (i * 0.10)
            p2 = p1 + 0.10
            ok, reason = sf.check(p2, p1, now_ts=base_time + i)
            assert ok is True
            assert reason == "OK"

        # Sudden large spike of 2.0 (20x average move of 0.10)
        p_prev = 2001.0
        p_spike = 2003.0
        ok, reason = sf.check(p_spike, p_prev, now_ts=base_time + 15)
        assert ok is False
        assert "SPIKE_DETECTED" in reason
        assert sf.is_blocked(now_ts=base_time + 20) is True

    def test_wave20_cluster_detection(self):
        sf = SpikeFilter(spike_ratio_threshold=3.0, cooldown_sec=30.0, cluster_count_limit=3, cluster_window_sec=300.0)
        base_time = 1000.0
        # Warm up rolling changes with 0.1 moves
        for _ in range(6):
            sf._recent_changes.append(0.1)

        # Pre-seed 3 spikes in the recent window
        sf._spike_timestamps.extend([base_time + 10, base_time + 20, base_time + 30])
        sf._blocked_until = 0.0  # past individual cooldown

        # Normal small move of 0.1 (ratio = 1.0, below threshold 3.0)
        ok, reason = sf.check(100.1, 100.0, now_ts=base_time + 40)
        assert ok is False
        assert "SPIKE_CLUSTER" in reason
        assert sf.is_blocked(now_ts=base_time + 45) is True

    def test_wave20_cooldown_expiry_and_reset(self):
        sf = SpikeFilter(cooldown_sec=50.0)
        sf._blocked_until = 1050.0
        assert sf.is_blocked(now_ts=1049.0) is True
        assert sf.is_blocked(now_ts=1051.0) is False

        # Reset
        sf.reset()
        assert sf._blocked_until == 0.0
        assert len(sf._recent_changes) == 0
        assert len(sf._spike_timestamps) == 0

    def test_wave20_invalid_and_fail_closed_inputs(self):
        sf = SpikeFilter()
        # Non-finite and invalid types
        assert sf.check(None, 2000.0)[0] is False
        assert sf.check(2000.0, None)[0] is False
        assert sf.check(True, 2000.0)[0] is False
        assert sf.check(2000.0, False)[0] is False
        assert sf.check(float('nan'), 2000.0)[0] is False
        assert sf.check(2000.0, float('inf'))[0] is False
        assert sf.check("invalid", 2000.0)[0] is False

    def test_wave20_update_and_info(self):
        sf = SpikeFilter()
        sf.reset()
        # Single-argument update
        ok, reason = sf.update(2000.0)
        assert ok is True
        ok, reason = sf.update(2000.2)
        assert ok is True
        info = sf.info(now_ts=1000.0)
        assert "blocked" in info
        assert "avg_tick_change" in info
        assert info["blocked"] is False

    def test_wave21_risk_guard_aliases(self, tmp_path):
        ng = NewsGuard(status_file=str(tmp_path / "news_status.json"), cache_ttl=10.0)
        assert ng.is_entry_blocked(now_ts=1000.0) is False
        assert ng.is_blocked(now_ts=1000.0) is False

        # Set avoid
        ng.set_override(avoid=True, reason="Non-farm payrolls pending")
        assert ng.is_entry_blocked() is True
        assert ng.is_blocked() is True

        allowed, reason = ng.is_trading_allowed()
        assert allowed is False
        assert "payroll" in reason

        # Module-level aliases with explicit override
        news_guard.set_override(avoid=False, reason="Clear")
        assert w21_is_blocked() is False
        assert w21_is_entry_blocked() is False
        allowed, _ = w21_is_trading_allowed()
        assert allowed is True

        news_guard.set_override(avoid=True, reason="War escalation")
        assert w21_is_blocked() is True
        assert w21_is_entry_blocked() is True

    def test_wave21_status_file_reading(self, tmp_path):
        status_file = tmp_path / "news_status.json"
        status_data = {
            "avoid_trading": True,
            "last_headlines": ["FOMC Rate Decision: 50bps cut announced"],
            "last_checked": "2026-10-18 12:00:00"
        }
        status_file.write_text(json.dumps(status_data), encoding="utf-8")

        ng = NewsGuard(status_file=str(status_file), cache_ttl=10.0)
        allowed, reason = ng.is_trading_allowed(now_ts=1000.0)
        assert allowed is False
        assert "FOMC" in reason
        assert ng.is_entry_blocked(now_ts=1000.0) is True

        # Now update file to clear news
        status_data["avoid_trading"] = False
        status_file.write_text(json.dumps(status_data), encoding="utf-8")

        # Before TTL expires (now_ts=1005.0) -> cached result
        allowed_cached, _ = ng.is_trading_allowed(now_ts=1005.0)
        assert allowed_cached is False

        # After TTL expires (now_ts=1015.0) -> reloads and clears
        allowed_new, reason_new = ng.is_trading_allowed(now_ts=1015.0)
        assert allowed_new is True
        assert "news clear" in reason_new

    def test_wave21_manual_override(self, tmp_path):
        status_file = tmp_path / "news_status.json"
        override_file = tmp_path / "news_override.json"

        # News status says avoid trading
        status_file.write_text(json.dumps({"avoid_trading": True, "last_headlines": ["CPI Spike"]}), encoding="utf-8")
        
        # Override file says force allow
        override_file.write_text(json.dumps({"override": True}), encoding="utf-8")

        ng = NewsGuard(status_file=str(status_file), override_file=str(override_file), cache_ttl=5.0)
        allowed, reason = ng.is_trading_allowed(now_ts=1000.0)
        assert allowed is True
        assert "manual override active" in reason

    def test_wave21_set_override_and_info_and_error_handling(self, tmp_path):
        corrupted_file = tmp_path / "corrupted_news.json"
        corrupted_file.write_text("{invalid json", encoding="utf-8")

        ng = NewsGuard(status_file=str(corrupted_file), cache_ttl=5.0)
        # Should gracefully fail-open and not crash
        allowed, reason = ng.is_trading_allowed(now_ts=1000.0)
        assert allowed is True
        assert "news read error" in reason

        # Info telemetry
        info = ng.info(now_ts=1000.0)
        assert info["avoid_trading"] is False
        assert "blocked_total" in info

        # Reset
        ng.set_override(avoid=True, reason="Manual block")
        assert ng.is_entry_blocked() is True
        ng.reset()
        assert ng._cached_avoid is False
        assert ng._blocked_count == 0
