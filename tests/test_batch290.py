"""
Test Suite Batch 290 -- Wave 344: LOB Queue Depletion Hazard Rate Guard
"""

import time
import pytest
from wave344_lob_queue_depletion_hazard_rate_guard import Wave344LOBQueueDepletionHazardRateGuard


class TestWave344QueueDepletionHazardRateGuard:
    """Comprehensive test suite for Wave 344: LOB Queue Depletion Hazard Rate Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            window_size=6,
            hazard_rate_threshold=1.5,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave344LOBQueueDepletionHazardRateGuard(**defaults)

    def test_wave344_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave344LOBQueueDepletionHazardRateGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave344LOBQueueDepletionHazardRateGuard(hazard_rate_threshold=0.0)

    def test_wave344_no_block_before_window_fills(self):
        """Guard should not block before window_size hazard observations accumulate."""
        guard = self._make_guard(window_size=6)
        t0 = time.monotonic()
        for i in range(4):
            guard.update(100.0, 100.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 1.0)

    def test_wave344_stable_queue_no_block(self):
        """Stable or oscillating queue sizes must have zero or low hazard and not block."""
        guard = self._make_guard(window_size=6, hazard_rate_threshold=1.5)
        t0 = time.monotonic()
        for i in range(15):
            guard.update(100.0 + (i % 2) * 5.0, 100.0 + (i % 2) * 5.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 2.0)

    def test_wave344_bid_depletion_hazard_triggers_block(self):
        """Severe sustained bid depth depletion must trigger QUEUE_DEPLETION_HAZARD."""
        guard = self._make_guard(window_size=5, hazard_rate_threshold=2.0)
        t0 = time.monotonic()
        # Initial depth: 1000 lots
        # Severe rapid depletion: dropping 30% each 0.1s -> lambda = 0.3 / 0.1 = 3.0 >= 2.0
        bid = 1000.0
        guard.update(bid, 500.0, t0)
        ts = t0
        for i in range(1, 8):
            ts += 0.1
            bid *= 0.70  # 30% drop per 100ms
            guard.update(bid, 500.0, ts)

        assert guard.is_blocked(ts + 0.05)
        assert guard.last_reason == "QUEUE_DEPLETION_HAZARD"

    def test_wave344_ask_depletion_hazard_triggers_block(self):
        """Severe sustained ask depth depletion must trigger QUEUE_DEPLETION_HAZARD."""
        guard = self._make_guard(window_size=5, hazard_rate_threshold=2.0)
        t0 = time.monotonic()
        ask = 1000.0
        guard.update(500.0, ask, t0)
        ts = t0
        for i in range(1, 8):
            ts += 0.1
            ask *= 0.70  # 30% drop per 100ms
            guard.update(500.0, ask, ts)

        assert guard.is_blocked(ts + 0.05)
        assert guard.last_reason == "QUEUE_DEPLETION_HAZARD"

    def test_wave344_replenishing_queue_no_block(self):
        """Growing or replenishing queue depth has zero hazard and must never block."""
        guard = self._make_guard(window_size=5, hazard_rate_threshold=1.5)
        t0 = time.monotonic()
        for i in range(15):
            guard.update(100.0 + i * 20.0, 100.0 + i * 20.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 2.0)

    def test_wave344_non_positive_inputs_block(self):
        """Non-positive depth sizes must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-5.0, 100.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave344_bool_inputs_block(self):
        """Boolean inputs must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, 100.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave344_negative_dt_blocks(self):
        """Timestamps moving backwards must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(100.0, 100.0, t0)
        guard.update(90.0, 100.0, t0 - 1.0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave344_reset_clears_state(self):
        """Reset must unblock the guard and clear history."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-5.0, 100.0, t0)
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""
