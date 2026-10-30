"""
Test Batch 363: Wave 475 Queue Cancellation Velocity Guard & Wave 476 Markov Flow Entropy Guard
================================================================================================
Institutional unit test suite verifying multi-tier limit order cancellation velocity,
phantom liquidity spoofing rug-pulls, 2-state Markov chain transition entropy rate, and directional herding.
"""

import pytest
import math
import numpy as np
from wave475_multi_tier_queue_cancellation_velocity_guard import Wave475MultiTierQueueCancellationVelocityGuard
from wave476_order_flow_markov_transition_entropy_guard import Wave476OrderFlowMarkovTransitionEntropyGuard


class TestWave475MultiTierQueueCancellationVelocityGuard:
    """Test suite for Wave 475: Multi-Tier Queue Cancellation Velocity Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="max_cancellation_velocity must be > 0.50"):
            Wave475MultiTierQueueCancellationVelocityGuard(max_cancellation_velocity=0.30)
        with pytest.raises(ValueError, match="max_cancel_ratio must be in"):
            Wave475MultiTierQueueCancellationVelocityGuard(max_cancel_ratio=0.50)
        with pytest.raises(ValueError, match="asymmetry_threshold must be in"):
            Wave475MultiTierQueueCancellationVelocityGuard(asymmetry_threshold=0.30)
        with pytest.raises(ValueError, match="min_burst_volume must be > 1.0"):
            Wave475MultiTierQueueCancellationVelocityGuard(min_burst_volume=0.50)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave475MultiTierQueueCancellationVelocityGuard(cooldown_sec=0.05)

    def test_input_validation(self):
        guard = Wave475MultiTierQueueCancellationVelocityGuard()
        with pytest.raises(ValueError, match="must have equal length"):
            guard.update([10.0, 20.0], [10.0], timestamp=10.0)
        with pytest.raises(ValueError, match="must contain at least 2 levels"):
            guard.update([10.0], [10.0], timestamp=10.0)

    def test_calm_steady_book_no_block(self):
        guard = Wave475MultiTierQueueCancellationVelocityGuard()
        # Initial step
        guard.update([50.0, 50.0], [50.0, 50.0], timestamp=10.0)

        # Steady evolution: depth changes slightly with trade execution
        blocked = guard.update([49.0, 50.0], [49.0, 50.0], executed_bid_volume=1.0, executed_ask_volume=1.0, timestamp=11.0)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.cancellation_velocity < 0.20
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave475MultiTierQueueCancellationVelocityGuard"
        assert telem["is_blocked"] is False

    def test_cancellation_velocity_explosion_blocks_all(self):
        guard = Wave475MultiTierQueueCancellationVelocityGuard(
            max_cancellation_velocity=2.50,
            min_burst_volume=10.0
        )
        # 100 lots bid, 100 lots ask
        guard.update([50.0, 50.0], [50.0, 50.0], timestamp=10.0)

        # Sudden mass bilateral cancellation of 60 lots in 0.2s without executions
        # v_rel = (60 / 0.2) / 100 = 300 / 100 = 3.0 s^-1 > 2.50
        blocked = guard.update([20.0, 20.0], [20.0, 20.0], executed_bid_volume=0.0, executed_ask_volume=0.0, timestamp=10.2)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert "CANCELLATION_VELOCITY_EXPLOSION" in guard.block_reason

    def test_bid_cancellation_rugpull_blocks_buy(self):
        guard = Wave475MultiTierQueueCancellationVelocityGuard(
            max_cancellation_velocity=2.00,
            asymmetry_threshold=0.70,
            min_burst_volume=10.0
        )
        guard.update([50.0, 50.0], [50.0, 50.0], timestamp=10.0)

        # 60 lots cancelled on bid side, ask side remains steady (50, 50)
        # total cancelled = 60 lots in dt=0.2s -> v_rel = 300 / 100 = 3.0 s^-1 > 2.0
        # asym = (300 - 0) / 300 = 1.0 > 0.70
        blocked = guard.update([20.0, 20.0], [50.0, 50.0], executed_bid_volume=0.0, executed_ask_volume=0.0, timestamp=10.2)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Bids pulled -> buying into air pocket is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "BID_CANCELLATION_RUGPULL" in guard.block_reason

    def test_ask_cancellation_rugpull_blocks_sell(self):
        guard = Wave475MultiTierQueueCancellationVelocityGuard(
            max_cancellation_velocity=2.00,
            asymmetry_threshold=0.70,
            min_burst_volume=10.0
        )
        guard.update([50.0, 50.0], [50.0, 50.0], timestamp=10.0)

        # 60 lots cancelled on ask side, bid side remains steady
        blocked = guard.update([50.0, 50.0], [20.0, 20.0], executed_bid_volume=0.0, executed_ask_volume=0.0, timestamp=10.2)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Asks pulled -> selling into air pocket is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "ASK_CANCELLATION_RUGPULL" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave475MultiTierQueueCancellationVelocityGuard(cooldown_sec=2.0, min_burst_volume=10.0)
        guard.update([50.0, 50.0], [50.0, 50.0], timestamp=10.0)
        guard.update([10.0, 10.0], [10.0, 10.0], timestamp=10.2) # Breach
        assert guard.is_blocked()

        # In cooldown
        assert guard.update([50.0, 50.0], [50.0, 50.0], timestamp=11.0) is True

        # Cooldown expired and calm
        assert guard.update([50.0, 50.0], [50.0, 50.0], timestamp=13.0) is False

        guard.reset()
        assert guard.cancellation_velocity == 0.0
        assert guard.is_blocked() is False


class TestWave476OrderFlowMarkovTransitionEntropyGuard:
    """Test suite for Wave 476: Order Flow Markov Transition Entropy Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_size must be >= 15"):
            Wave476OrderFlowMarkovTransitionEntropyGuard(window_size=10)
        with pytest.raises(ValueError, match="min_samples must be >= 10"):
            Wave476OrderFlowMarkovTransitionEntropyGuard(min_samples=8)
        with pytest.raises(ValueError, match="min_samples .* cannot exceed window_size"):
            Wave476OrderFlowMarkovTransitionEntropyGuard(window_size=20, min_samples=25)
        with pytest.raises(ValueError, match="min_entropy_threshold must be in"):
            Wave476OrderFlowMarkovTransitionEntropyGuard(min_entropy_threshold=0.10)
        with pytest.raises(ValueError, match="max_continuation_prob must be in"):
            Wave476OrderFlowMarkovTransitionEntropyGuard(max_continuation_prob=0.50)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave476OrderFlowMarkovTransitionEntropyGuard(cooldown_sec=0.05)

    def test_insufficient_samples(self):
        guard = Wave476OrderFlowMarkovTransitionEntropyGuard(min_samples=15)
        for i in range(10):
            blocked = guard.update(1 if i % 2 == 0 else -1, timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_SAMPLES"

    def test_calm_alternating_flow_no_block(self):
        guard = Wave476OrderFlowMarkovTransitionEntropyGuard(min_samples=15)
        # Alternating random walk flow (+1, -1, +1, +1, -1, -1, ...)
        signs = [1, -1, 1, 1, -1, -1, 1, -1, 1, -1, 1, 1, -1, 1, -1, 1, -1, 1]
        for i, s in enumerate(signs):
            guard.update(s, timestamp=10.0 + i)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.markov_entropy > 0.70
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave476OrderFlowMarkovTransitionEntropyGuard"
        assert telem["is_blocked"] is False

    def test_algorithmic_buy_herding_blocks_sell(self):
        guard = Wave476OrderFlowMarkovTransitionEntropyGuard(
            min_samples=15,
            max_continuation_prob=0.82
        )
        # Relentless series of consecutive buy orders (POV/TWAP buy iceberg slicing)
        # 18 consecutive +1 trades
        for i in range(18):
            blocked = guard.update(1, timestamp=10.0 + i)

        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Relentless buy slicing -> shorting is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "MARKOV_BUY_FLOW_HERDING" in guard.block_reason

    def test_algorithmic_sell_herding_blocks_buy(self):
        guard = Wave476OrderFlowMarkovTransitionEntropyGuard(
            min_samples=15,
            max_continuation_prob=0.82
        )
        # 18 consecutive -1 trades
        for i in range(18):
            blocked = guard.update(-1, timestamp=10.0 + i)

        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Relentless sell slicing -> buying is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "MARKOV_SELL_FLOW_HERDING" in guard.block_reason

    def test_markov_entropy_collapse_blocks_all(self):
        guard = Wave476OrderFlowMarkovTransitionEntropyGuard(
            min_samples=15,
            min_entropy_threshold=0.45,
            max_continuation_prob=0.98 # High so continuation alone doesn't trigger
        )
        # Long sequence of clustered persistent regimes
        # 10 buys, then 10 sells: within each regime p(+\mid+) and p(-\mid-) are very high
        for i in range(10):
            guard.update(1, timestamp=10.0 + i)
        for i in range(10):
            guard.update(-1, timestamp=20.0 + i)

        assert guard.is_blocked()
        assert guard.markov_entropy < 0.45
        assert guard.blocked_side in ("ALL", "BUY")

    def test_cooldown_and_reset(self):
        guard = Wave476OrderFlowMarkovTransitionEntropyGuard(min_samples=15, cooldown_sec=2.0)
        for i in range(16):
            guard.update(1, timestamp=10.0 + i) # Breach

        assert guard.is_blocked()

        # Cooldown active
        assert guard.update(1, timestamp=26.0) is True

        guard.reset()
        assert guard.sample_count == 0
        assert guard.is_blocked() is False

    def test_invalid_trade_sign_and_monotonicity(self):
        guard = Wave476OrderFlowMarkovTransitionEntropyGuard()
        with pytest.raises(ValueError, match=r"trade_sign must be \+1 or -1"):
            guard.update(0, timestamp=10.0)

        guard.update(1, timestamp=10.0)
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update(1, timestamp=9.5)
