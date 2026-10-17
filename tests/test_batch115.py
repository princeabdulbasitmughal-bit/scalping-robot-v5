import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from python_engine.risk_guard import RiskGuard, Decision, _is_valid_num
from python_engine.storage import atomic_write_json, safe_read_json
import python_engine.storage as storage


def test_risk_guard_decision_subclass():
    d_allow = Decision(True, "APPROVED", 0.05)
    assert d_allow.allowed is True
    assert d_allow["allowed"] is True
    assert d_allow.lot == 0.05
    assert bool(d_allow) is True
    assert "Decision(allowed=True" in repr(d_allow)

    d_block = Decision(False, "BLOCKED", 0.0)
    assert d_block.allowed is False
    assert d_block["allowed"] is False
    assert bool(d_block) is False


def test_risk_guard_is_valid_num():
    assert _is_valid_num(100) is True
    assert _is_valid_num(100.5) is True
    assert _is_valid_num(0) is True
    # Bools, None, NaN, Inf, Strings must all evaluate to False
    assert _is_valid_num(True) is False
    assert _is_valid_num(False) is False
    assert _is_valid_num(None) is False
    assert _is_valid_num(float("nan")) is False
    assert _is_valid_num(float("inf")) is False
    assert _is_valid_num("100.5") is False


def test_risk_guard_kill_switch_invariant():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "risk_state.json"
        kill_file = Path(tmpdir) / "KILL_SWITCH"

        # 1. Config kill switch
        guard = RiskGuard({"kill_switch": True}, state_path=state_file)
        dec = guard.check_order({"symbol": "XAUUSD", "lot_size": 0.01}, {"balance": 10000}, {})
        assert dec.allowed is False
        assert "KILL_SWITCH_ACTIVE" in dec.reason

        # 2. File kill switch
        guard2 = RiskGuard({"kill_switch": False, "kill_switch_path": kill_file}, state_path=state_file)
        kill_file.write_text("STOP", encoding="utf-8")
        dec2 = guard2.check_order({"symbol": "XAUUSD", "lot_size": 0.01}, {"balance": 10000}, {})
        assert dec2.allowed is False
        assert "KILL_SWITCH_ACTIVE" in dec2.reason


def test_risk_guard_balance_floor_permanent_halt():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "risk_state.json"
        guard = RiskGuard({"min_balance_usd": 9800.0}, state_path=state_file)

        # Balance drops below floor ($9,750 < $9,800)
        dec = guard.check_order({"symbol": "XAUUSD", "lot_size": 0.01}, {"balance": 9750.0}, {})
        assert dec.allowed is False
        assert "BALANCE_FLOOR_HALTED" in dec.reason
        assert guard.state["balance_floor_halted"] is True

        # Even with balance recovered, remains permanently halted until reset
        dec2 = guard.check_order({"symbol": "XAUUSD", "lot_size": 0.01}, {"balance": 10500.0}, {})
        assert dec2.allowed is False
        assert "BALANCE_FLOOR_HALTED" in dec2.reason

        # Manual reset
        guard.reset_balance_floor()
        assert guard.state["balance_floor_halted"] is False


def test_risk_guard_daily_loss_halt_and_rollover():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "risk_state.json"
        guard = RiskGuard({"max_daily_loss_usd": 150.0}, state_path=state_file)

        # Record losses up to limit
        guard.record_trade(-100.0)
        assert guard.state["daily_loss_halted"] is False

        guard.record_trade(-60.0)
        assert guard.state["daily_loss_halted"] is True

        dec = guard.check_order({"symbol": "XAUUSD", "lot_size": 0.01}, {"balance": 10000.0}, {})
        assert dec.allowed is False
        assert "DAILY_LOSS_HALTED" in dec.reason

        # Manual reset
        guard.reset_daily_loss()
        assert guard.state["daily_loss_halted"] is False
        assert guard.state["daily_pnl"] == 0.0


def test_risk_guard_order_approval_and_lot_quantization():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "risk_state.json"
        cfg = {
            "max_lot_size": 0.10,
            "min_balance_usd": 5000.0,
            "max_daily_loss_usd": 200.0,
        }
        guard = RiskGuard(cfg, state_path=state_file)
        now = guard.clock()
        order = {"symbol": "XAUUSD", "type": "BUY", "lot_size": 0.055, "sl": 2640.0, "tp": 2660.0, "price": 2650.20}
        account = {"balance": 10000.0, "equity": 10000.0, "margin_free": 9000.0, "open_positions": 0}
        market = {
            "bid": 2650.0,
            "ask": 2650.20,
            "point": 0.01,
            "pip_size": 0.1,
            "spread_pips": 2.0,
            "tick_time": now,
            "lot_step": 0.01,
            "min_lot": 0.01,
            "max_lot": 5.0,
        }

        dec = guard.check_order(order, account, market)
        assert dec.allowed is True
        assert dec.reason == "ORDER_APPROVED"
        assert dec.lot == 0.05  # quantized down to lot_step 0.01


def test_risk_guard_is_entry_blocked_and_aliases():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "risk_state.json"
        guard = RiskGuard({"min_balance_usd": 9000.0}, state_path=state_file)

        assert guard.is_entry_blocked() is False
        assert guard.is_blocked() is False

        # Pass account with balance below minimum
        assert guard.is_entry_blocked(account={"balance": 8500.0}) is True

        # Kill switch activates block
        guard.config["kill_switch"] = True
        assert guard.is_entry_blocked() is True
        assert guard.is_blocked() is True


def test_storage_atomic_write_and_safe_read():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "data.json"
        payload = {"bot": "ScalpingRobotV5", "version": 5.0, "active": True}

        assert atomic_write_json(file_path, payload) is True
        assert file_path.exists()

        bak_file = file_path.with_suffix(".json.bak")
        assert bak_file.exists()

        read_data = safe_read_json(file_path)
        assert read_data == payload


def test_storage_safe_read_bak_recovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "state.json"
        payload = {"daily_pnl": 125.50, "trades": 7}

        # Write clean state (creates state.json and state.json.bak)
        assert atomic_write_json(file_path, payload) is True

        # Corrupt primary file with garbage bytes
        with open(file_path, "wb") as f:
            f.write(b"CORRUPTED BYTES {{{ NOT JSON")

        # safe_read_json should seamlessly recover from .bak!
        recovered = safe_read_json(file_path)
        assert recovered == payload


def test_storage_missing_file_and_risk_aliases():
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent = Path(tmpdir) / "none.json"
        assert safe_read_json(non_existent, default={"fallback": True}) == {"fallback": True}

        # Unified risk aliases (never block)
        assert storage.is_entry_blocked() is False
        assert storage.is_blocked() is False
