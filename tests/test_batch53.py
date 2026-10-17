"""
Test Suite: Batch 53 — Watchdog, MT4 Installer, RiskGuard Invariants & Engine Confluence
========================================================================================
Hermetic unit test suite verifying:
  1. Watchdog: Exponential backoff calculation and ceiling clamp
  2. Watchdog: Health check validation (fresh vs stale timestamp, ok field)
  3. Watchdog: status_age calculation and non-existent file safety
  4. MT4 Installer: install_to_target experts and presets deployment
  5. Bootstrap Launch: Process creation flags & supervisor command formulation
  6. RiskGuard Invariant: Hard KILL_SWITCH file suppression and recovery
  7. RiskGuard Invariant: Lot size boundary validation & clamping
  8. RiskGuard Invariant: Account balance sanity floor & blowout prevention
  9. Scalping Engine: Multi-indicator calculation pipeline (BB, ATR, RSI, EMA)
 10. Signal Engine: get_signal_safe error containment on corrupt/empty inputs
"""

import time
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest

from watchdog_runner import calculate_backoff, health_check, status_age
from auto_install_to_mt4 import install_to_target
from bootstrap_launch import get_launch_flags, get_supervisor_command, DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP
from python_engine.risk_guard import RiskGuard, Decision
from python_engine.scalping_engine import ScalpingRobotV5
from python_engine.signal_engine import SignalEngine


# ── Test 1: Watchdog Backoff Calculation ──────────────────────────────────────
def test_watchdog_calculate_backoff():
    """Verify calculate_backoff adheres to exponential scaling with a 300s ceiling."""
    assert calculate_backoff(0) == 30
    assert calculate_backoff(1) == 60
    assert calculate_backoff(2) == 120
    assert calculate_backoff(3) == 240
    assert calculate_backoff(4) == 300  # clamped at 300s max
    assert calculate_backoff(10) == 300
    assert calculate_backoff(-1) == 30
    assert calculate_backoff("invalid") == 30


# ── Test 2: Watchdog Health Check Validation ───────────────────────────────────
def test_watchdog_health_check():
    """Verify health_check validates fresh timestamps and ok status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"

        # Missing file returns False
        assert health_check(status_file=status_file) is False

        # Fresh healthy status (< 60s ago)
        fresh_data = {
            "ok": True,
            "status": "ACTIVE_SCALPING",
            "timestamp": time.time(),
        }
        status_file.write_text(json.dumps(fresh_data), encoding="utf-8")
        assert health_check(status_file=status_file) is True

        # Stale status (120s ago) returns False (hung process)
        stale_data = {
            "ok": True,
            "status": "ACTIVE_SCALPING",
            "timestamp": time.time() - 120,
        }
        status_file.write_text(json.dumps(stale_data), encoding="utf-8")
        assert health_check(status_file=status_file) is False


# ── Test 3: Watchdog Status Age ────────────────────────────────────────────────
def test_watchdog_status_age():
    """Verify status_age accurately returns elapsed file age."""
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent = Path(tmpdir) / "none.json"
        assert status_age(status_file=non_existent) == 9999.0

        existing = Path(tmpdir) / "exists.json"
        existing.write_text("{}", encoding="utf-8")
        age = status_age(status_file=existing)
        assert 0.0 <= age <= 5.0


# ── Test 4: MT4 Installer Deployment ──────────────────────────────────────────
def test_auto_install_to_mt4():
    """Verify install_to_target deploys experts and presets cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        target_dir = base / "MetaTrader"
        experts_src = base / "src_experts"
        presets_src = base / "src_presets"

        experts_src.mkdir(parents=True, exist_ok=True)
        presets_src.mkdir(parents=True, exist_ok=True)

        ea_file = experts_src / "ScalpingRobotV5.mq4"
        ea_file.write_text("// MQL4 code", encoding="utf-8")

        preset_file = presets_src / "Aggressive_Gold.set"
        preset_file.write_text("LotSize=0.02", encoding="utf-8")

        installed = install_to_target(
            target_dir=str(target_dir),
            experts_src=experts_src,
            presets_src=presets_src,
        )

        assert len(installed) == 2
        assert (target_dir / "MQL4" / "Experts" / "ScalpingRobotV5.mq4").exists()
        assert (target_dir / "MQL4" / "Presets" / "Aggressive_Gold.set").exists()


# ── Test 5: Bootstrap Launch Command & Process Flags ──────────────────────────
def test_bootstrap_launch_properties():
    """Verify process creation flags and supervisor command formulation."""
    flags = get_launch_flags()
    assert (flags & DETACHED_PROCESS) == DETACHED_PROCESS
    assert (flags & CREATE_NEW_PROCESS_GROUP) == CREATE_NEW_PROCESS_GROUP

    cmd = get_supervisor_command()
    assert isinstance(cmd, list)
    assert len(cmd) >= 2
    assert "supervisor.py" in cmd[1]


# ── Test 6: RiskGuard Invariant - Hard Kill Switch File ───────────────────────
def test_risk_guard_kill_switch():
    """Verify RiskGuard blocks all orders when KILL_SWITCH file is present."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        kill_file = base / "KILL_SWITCH"
        state_file = base / "risk_state.json"

        guard = RiskGuard(
            config={"kill_switch_path": str(kill_file), "min_balance_usd": 1000.0},
            state_path=state_file,
        )

        order = {"type": "BUY", "price": 2400.0, "sl": 2395.0, "lots": 0.02}
        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        market = {"spread_pips": 1.5, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}

        # Healthy state without kill switch
        dec_normal = guard.check_order(order=order, account=account, market=market)
        assert dec_normal.allowed is True
        assert dec_normal.reason == "ORDER_APPROVED"

        # Activate kill switch
        kill_file.write_text("EMERGENCY_HALT", encoding="utf-8")
        dec_killed = guard.check_order(order=order, account=account, market=market)
        assert dec_killed.allowed is False
        assert "KILL_SWITCH" in dec_killed.reason

        # Remove kill switch
        kill_file.unlink()
        dec_recovered = guard.check_order(order=order, account=account, market=market)
        assert dec_recovered.allowed is True


# ── Test 7: RiskGuard Invariant - Lot Size Boundaries ─────────────────────────
def test_risk_guard_lot_size_boundaries():
    """Verify RiskGuard rejects out-of-boundary lot sizes fail-closed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "risk_state.json"
        guard = RiskGuard(
            config={"min_balance_usd": 1000.0, "max_lot_size": 0.10},
            state_path=state_file,
        )
        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        market = {"spread_pips": 1.5, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01, "max_lot": 0.10}

        # Lot below min
        order_small = {"type": "BUY", "price": 2400.0, "sl": 2395.0, "lots": 0.005}
        dec_small = guard.check_order(order=order_small, account=account, market=market)
        assert dec_small.allowed is False
        assert "RISK_CAP_EXCEEDED" in dec_small.reason or "LOT" in dec_small.reason

        # Excessive lot clamped to effective max_lot
        order_large = {"type": "BUY", "price": 2400.0, "sl": 2395.0, "lots": 5.0}
        dec_large = guard.check_order(order=order_large, account=account, market=market)
        # Should be approved clamped to max allowable or rejected
        if dec_large.allowed:
            assert dec_large.lot <= 0.10


# ── Test 8: RiskGuard Invariant - Balance Sanity Floor ─────────────────────────
def test_risk_guard_balance_sanity_floor():
    """Verify RiskGuard blocks orders when account balance is below sanity floor."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "risk_state.json"
        guard = RiskGuard(
            config={"min_balance_usd": 9700.0},
            state_path=state_file,
        )

        order = {"type": "BUY", "price": 2400.0, "sl": 2395.0, "lots": 0.01}
        market = {"spread_pips": 1.5, "tick_time": time.time(), "pip_size": 0.1}

        # Depleted account balance ($500 < $9700 floor)
        account_depleted = {"balance": 500.0, "equity": 500.0, "open_positions": 0}
        dec = guard.check_order(order=order, account=account_depleted, market=market)
        assert dec.allowed is False
        assert "BALANCE_FLOOR" in dec.reason.upper() or "BALANCE" in dec.reason.upper()


# ── Test 9: Scalping Engine Indicator Calculation ─────────────────────────────
def test_scalping_engine_indicators():
    """Verify ScalpingRobotV5 accurately computes technical indicators from bars."""
    robot = ScalpingRobotV5(config={"symbol": "XAUUSD"})

    bars = []
    base_price = 2400.0
    for i in range(50):
        p = base_price + (i % 5) * 0.4
        bars.append({
            "open": p - 0.2,
            "high": p + 0.6,
            "low": p - 0.6,
            "close": p,
            "volume": 25,
            "timestamp": "2026-10-17 12:00:00",
        })

    indicators = robot.calculate_indicators(bars)
    assert isinstance(indicators, dict)
    assert "bb_upper" in indicators and "bb_lower" in indicators
    assert "atr" in indicators
    assert "rsi" in indicators
    assert indicators["bb_upper"] > indicators["bb_lower"]
    assert indicators["atr"] > 0.0


# ── Test 10: Signal Engine Error Containment ──────────────────────────────────
def test_signal_engine_corrupt_input_containment():
    """Verify SignalEngine safely handles empty or non-numeric prices with HOLD."""
    engine = SignalEngine()

    # Empty prices list
    sig_empty = engine.get_signal_safe([])
    assert sig_empty["signal"] == "HOLD"
    assert sig_empty["confidence"] == 0.0

    # Non-numeric corrupted prices
    sig_corrupt = engine.get_signal_safe([None, "invalid", float('nan'), float('inf')])
    assert sig_corrupt["signal"] == "HOLD"
    assert sig_corrupt["confidence"] == 0.0
