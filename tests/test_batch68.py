"""
tests/test_batch68.py
Batch 68 Unit Tests: Atomic Storage & Safe JSON Recovery (storage.py),
Confluence Indicator Signal Engine (signal_engine.py), and
Defense-in-Depth Fail-Closed Risk Guardian (risk_guard.py).
"""

import math
import time
import pytest
from pathlib import Path

from python_engine.storage import atomic_write_json, safe_read_json
from python_engine.signal_engine import SignalEngine
from python_engine.risk_guard import RiskGuard, Decision


def test_python_engine_storage_atomic_write_and_bak(tmp_path):
    """Verify atomic_write_json writes payload, updates backup, and syncs atomically."""
    target_file = tmp_path / "data.json"
    payload = {"status": "ACTIVE", "trades": 42, "pnl": 1250.50}

    assert atomic_write_json(target_file, payload) is True
    assert target_file.exists()

    # Verify content
    read_back = safe_read_json(target_file)
    assert read_back == payload

    # Verify .bak file created
    bak_file = target_file.with_suffix(".json.bak")
    assert bak_file.exists()
    assert safe_read_json(bak_file) == payload


def test_python_engine_storage_safe_read_and_corruption_recovery(tmp_path):
    """Verify safe_read_json gracefully recovers from .bak upon JSON corruption."""
    target_file = tmp_path / "state.json"
    bak_file = target_file.with_suffix(".json.bak")

    # Establish valid .bak
    good_payload = {"recovery_key": "VALID_STATE", "balance": 10000.0}
    atomic_write_json(target_file, good_payload)

    # Intentionally corrupt the primary JSON file with truncated garbage
    with open(target_file, "w", encoding="utf-8") as f:
        f.write("{\"truncated_json_key\": ")

    # safe_read_json should detect JSONDecodeError and read from .bak
    recovered = safe_read_json(target_file, default={"recovery_key": "FAILED"})
    assert recovered["recovery_key"] == "VALID_STATE"
    assert recovered["balance"] == 10000.0


def test_python_engine_signal_engine_bollinger_bands():
    """Verify SignalEngine computes Bollinger Bands middle, upper, lower, and squeeze."""
    se = SignalEngine({"bb_period": 10, "bb_std": 2.0})

    prices = [2650.0 + (i % 3) * 0.5 for i in range(25)]
    bb = se.compute_bb(prices)

    assert bb["upper"] > bb["middle"] > bb["lower"]
    assert bb["width"] > 0.0
    assert isinstance(bb["squeeze"], bool)

    # Tight flat prices -> squeeze is True
    flat_prices = [2650.00, 2650.01, 2650.00, 2650.01, 2650.00] * 5
    bb_flat = se.compute_bb(flat_prices)
    assert bb_flat["squeeze"] is True


def test_python_engine_signal_engine_wilder_rsi_and_macd():
    """Verify SignalEngine Wilder RSI and MACD indicator series."""
    se = SignalEngine({"rsi_period": 14, "macd_fast": 5, "macd_slow": 10, "macd_signal": 3})

    # Rising prices -> high RSI (> 70)
    rising = [2640.0 + i * 1.0 for i in range(30)]
    rsi_high = se.compute_rsi(rising)
    assert rsi_high > 70.0

    # Falling prices -> low RSI (< 30)
    falling = [2670.0 - i * 1.0 for i in range(30)]
    rsi_low = se.compute_rsi(falling)
    assert rsi_low < 30.0

    # MACD series
    macd = se.compute_macd(rising)
    assert "macd_line" in macd
    assert "signal_line" in macd
    assert "histogram" in macd
    assert macd["cross"] in ("BUY", "SELL", "NONE")


def test_python_engine_signal_engine_confluence_and_safe_fallback():
    """Verify SignalEngine confluence scoring and get_signal_safe input containment."""
    se = SignalEngine()

    prices = [2650.0 + math.sin(i * 0.2) * 5.0 for i in range(40)]
    sig = se.get_signal(prices)

    assert sig["signal"] in ("BUY", "SELL", "HOLD")
    assert 0.0 <= sig["confidence"] <= 1.0
    assert sig["tier"] in (1, 2, 3)
    assert isinstance(sig["reasons"], list)

    # Safe fallback on invalid/empty inputs
    fallback = se.get_signal_safe([])
    assert fallback["signal"] == "HOLD"
    assert fallback["confidence"] == 0.0
    assert fallback["tier"] == 3
    assert "fallback" in fallback["reasons"][0]


def test_python_engine_risk_guard_decision_object():
    """Verify Decision behaves seamlessly as both a dict and boolean-evaluable object."""
    d_allow = Decision(True, "ORDER_APPROVED", 0.05)
    assert d_allow.allowed is True
    assert d_allow["allowed"] is True
    assert d_allow.lot == 0.05
    assert d_allow["lot"] == 0.05
    assert bool(d_allow) is True
    assert "ORDER_APPROVED" in repr(d_allow)

    d_reject = Decision(False, "SPREAD_EXCEEDED", 0.0)
    assert d_reject.allowed is False
    assert d_reject["allowed"] is False
    assert bool(d_reject) is False


def test_python_engine_risk_guard_kill_switch_invariant4(tmp_path):
    """Verify Invariant 4: Kill switch active via config or sentinel file blocks trading."""
    state_file = tmp_path / "risk_state.json"
    sentinel_file = tmp_path / "KILL_SWITCH"

    # 1. Config flag kill switch
    rg_cfg = RiskGuard(
        config={"kill_switch": True},
        state_path=state_file,
    )
    order = {"symbol": "XAUUSD", "direction": "BUY", "price": 2650.0, "sl": 2640.0, "lots": 0.02}
    account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
    market = {"ask": 2650.0, "bid": 2649.8, "spread_pips": 2.0, "tick_time": time.time()}

    dec1 = rg_cfg.check_order(order, account, market)
    assert dec1.allowed is False
    assert "KILL_SWITCH_ACTIVE" in dec1.reason

    # 2. File sentinel kill switch
    sentinel_file.write_text("MANUAL HALT", encoding="utf-8")
    rg_file = RiskGuard(
        config={"kill_switch": False, "kill_switch_path": str(sentinel_file)},
        state_path=state_file,
    )
    dec2 = rg_file.check_order(order, account, market)
    assert dec2.allowed is False
    assert "KILL_SWITCH_ACTIVE" in dec2.reason


def test_python_engine_risk_guard_balance_floor_invariant5(tmp_path):
    """Verify Invariant 5: Balance floor triggers permanent halt surviving rollover until reset."""
    state_file = tmp_path / "risk_state.json"
    rg = RiskGuard(
        config={"min_balance_usd": 9700.0},
        state_path=state_file,
    )

    now = time.time()
    order = {"symbol": "XAUUSD", "direction": "BUY", "price": 2650.0, "sl": 2640.0, "lots": 0.02}
    account_breached = {"balance": 9650.0, "equity": 9650.0, "open_positions": 0}
    market = {"ask": 2650.0, "bid": 2649.8, "spread_pips": 2.0, "tick_time": now}

    dec = rg.check_order(order, account_breached, market)
    assert dec.allowed is False
    assert "BALANCE_FLOOR_HALTED" in dec.reason
    assert rg.state["balance_floor_halted"] is True

    # Account recovers balance, but halt is permanent until manual reset
    account_recovered = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
    dec_locked = rg.check_order(order, account_recovered, market)
    assert dec_locked.allowed is False
    assert "BALANCE_FLOOR_HALTED" in dec_locked.reason

    # Manual reset frees trading
    rg.reset_balance_floor()
    assert rg.state["balance_floor_halted"] is False


def test_python_engine_risk_guard_daily_loss_and_rollover_invariant5(tmp_path):
    """Verify Invariant 5: Daily loss limit halts trading and auto-clears on UTC day rollover."""
    state_file = tmp_path / "risk_state.json"
    current_time = [1776420000.0]  # simulated epoch

    def mock_clock():
        return current_time[0]

    rg = RiskGuard(
        config={"max_daily_loss_usd": 200.0},
        state_path=state_file,
        clock=mock_clock,
    )

    # Accumulate losses to breach daily loss ceiling
    rg.record_trade(pnl=-220.0, timestamp=current_time[0])
    assert rg.state["daily_loss_halted"] is True

    order = {"symbol": "XAUUSD", "direction": "BUY", "price": 2650.0, "sl": 2640.0, "lots": 0.02}
    account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
    market = {"ask": 2650.0, "bid": 2649.8, "spread_pips": 2.0, "tick_time": current_time[0]}

    dec_halted = rg.check_order(order, account, market)
    assert dec_halted.allowed is False
    assert "DAILY_LOSS_HALTED" in dec_halted.reason

    # Advance clock by 24 hours to trigger UTC day rollover
    current_time[0] += 86400.0
    market["tick_time"] = current_time[0]

    # Rollover triggers reset
    rg._check_day_rollover()
    assert rg.state["daily_loss_halted"] is False
    assert rg.state["daily_pnl"] == 0.0


def test_python_engine_risk_guard_order_approval_and_lot_quantization(tmp_path):
    """Verify Invariant 1, 2, 3, 10: Valid order approval and lot size step quantization."""
    state_file = tmp_path / "risk_state.json"
    now = time.time()
    rg = RiskGuard(
        config={
            "max_open_positions": 3,
            "min_balance_usd": 9000.0,
            "max_daily_loss_usd": 200.0,
            "spread_filter_pips": 3.0,
            "min_sl_pips": 10.0,
            "max_sl_pips": 100.0,
            "max_lot_size": 0.10,
            "risk_per_trade_pct": 2.0,
        },
        state_path=state_file,
    )

    order = {
        "symbol": "XAUUSD",
        "direction": "BUY",
        "price": 2650.00,
        "sl": 2645.00,  # 5.0 points = 50 pips (pip_size=0.1)
        "lots": 0.045,  # Needs quantization to step 0.01 -> 0.04
    }
    account = {
        "balance": 10000.0,
        "equity": 10000.0,
        "open_positions": 0,
    }
    market = {
        "ask": 2650.00,
        "bid": 2649.80,
        "spread_pips": 2.0,
        "tick_time": now,
        "pip_size": 0.1,
        "lot_step": 0.01,
        "min_lot": 0.01,
        "max_lot": 10.0,
        "contract_size": 100.0,
    }

    decision = rg.check_order(order, account, market)
    assert decision.allowed is True
    assert decision.reason == "ORDER_APPROVED"
    assert decision.lot == 0.04  # Quantized down to nearest 0.01
