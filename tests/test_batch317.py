"""
Batch 317 -- Tests for Wave 392 and Wave 393
=============================================
Wave 392: LOB Liquidity Provision Ratio Guard
Wave 393: Trade Flow Amplitude Modulation Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave392_lob_liquidity_provision_ratio_guard import (
    Wave392LOBLiquidityProvisionRatioGuard,
)
from wave393_trade_flow_amplitude_modulation_guard import (
    Wave393TradeFlowAmplitudeModulationGuard,
)


class TestWave392LiquidityProvisionRatio:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave392LOBLiquidityProvisionRatioGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave392LOBLiquidityProvisionRatioGuard(high_lpr_threshold=0.2, low_lpr_threshold=0.8)

    def test_balanced_provision_no_block(self):
        guard = Wave392LOBLiquidityProvisionRatioGuard(
            window_size=10, high_lpr_threshold=0.85, low_lpr_threshold=0.15
        )
        t0 = time.monotonic()
        # 50% passive / 50% aggressive -> LPR = 0.50
        for i in range(15):
            guard.update(is_passive=(i % 2 == 0), timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_no_block_before_window_fills(self):
        guard = Wave392LOBLiquidityProvisionRatioGuard(window_size=10)
        t0 = time.monotonic()
        for i in range(5):
            guard.update(is_passive=True, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_high_passive_ratio_triggers_block(self):
        guard = Wave392LOBLiquidityProvisionRatioGuard(
            window_size=10, high_lpr_threshold=0.80, low_lpr_threshold=0.20
        )
        t0 = time.monotonic()
        # 9 out of 10 passive (90% >= 80%)
        for i in range(10):
            guard.update(is_passive=(i != 0), timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "HIGH_PASSIVE_RATIO"

    def test_low_passive_ratio_triggers_block(self):
        guard = Wave392LOBLiquidityProvisionRatioGuard(
            window_size=10, high_lpr_threshold=0.80, low_lpr_threshold=0.20
        )
        t0 = time.monotonic()
        # 9 out of 10 aggressive (10% passive <= 20%)
        for i in range(10):
            guard.update(is_passive=(i == 0), timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "LOW_PASSIVE_RATIO"

    def test_invalid_input_validation(self):
        guard = Wave392LOBLiquidityProvisionRatioGuard()
        guard.update("not_a_bool", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, True)  # timestamp is bool
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave392LOBLiquidityProvisionRatioGuard()
        guard.update(True, "bad_ts")
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave393AmplitudeModulation:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave393TradeFlowAmplitudeModulationGuard(env_window=1)
        with pytest.raises(ValueError):
            Wave393TradeFlowAmplitudeModulationGuard(modulation_threshold=-10.0)

    def test_constant_volume_no_block(self):
        guard = Wave393TradeFlowAmplitudeModulationGuard(
            env_window=3, am_window=10, modulation_threshold=50.0
        )
        t0 = time.monotonic()
        # Constant volume -> constant envelope -> std = 0.0
        for i in range(20):
            guard.update(volume=10.0, side="buy", timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_no_block_before_window_fills(self):
        guard = Wave393TradeFlowAmplitudeModulationGuard(env_window=3, am_window=10)
        t0 = time.monotonic()
        for i in range(5):
            guard.update(volume=10.0 + i * 100.0, side="buy", timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_violent_amplitude_modulation_triggers_block(self):
        guard = Wave393TradeFlowAmplitudeModulationGuard(
            env_window=3, am_window=10, modulation_threshold=80.0
        )
        t0 = time.monotonic()
        # Oscillating between tiny volume (1.0) and huge burst (500.0) every 4 ticks
        for i in range(25):
            v = 500.0 if (i % 8 < 4) else 1.0
            guard.update(volume=v, side="buy", timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "AMPLITUDE_MODULATION_BREACH"

    def test_invalid_input_validation(self):
        guard = Wave393TradeFlowAmplitudeModulationGuard()
        guard.update(10.0, "invalid_side", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave393TradeFlowAmplitudeModulationGuard()
        guard.update(0.0, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
