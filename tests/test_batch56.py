"""
Test Suite: Batch 56 — Scalping Signal Confluence, Volatility Shield Cooldown, Position Sizer & Process Flags
=============================================================================================================
Hermetic unit test suite verifying:
  1. Scalping Engine: Full BUY signal generation confluence (oversold RSI + lower BB dip + bullish EMA)
  2. Scalping Engine: Full SELL signal generation confluence (overbought RSI + upper BB tag + bearish EMA)
  3. Scalping Engine: Max concurrent orders guard suppression
  4. Scalping Engine: Volatility Shield spike trigger, bar-by-bar cooldown decrement, and recovery
  5. Scalping Engine: Position sizing fail-closed guards (zero/negative/NaN balance & risk bounds)
  6. Scalping Engine: Volatility-adaptive dynamic stops (ATR scaling, BUY/SELL price targets)
  7. Scalping Engine: Internal state reset hygiene
  8. Escape Launch: Breakaway process flags, fallback bitmasks, and watchdog command formatting
  9. Gold News Fetcher: Status serialization and atomic JSON persistence
 10. MT4 Auto-Installer: Resilient error containment on inaccessible or unwritable paths
"""

import json
import math
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

from python_engine.scalping_engine import ScalpingRobotV5, ScalpingSignal, MarketRegime
import escape_launch
import auto_install_to_mt4
import gold_news_fetcher


# ── Test 1: Scalping Engine BUY Confluence ────────────────────────────────────
def test_scalping_engine_buy_confluence():
    """Verify ScalpingRobotV5 generates BUY signal under full bullish confluence."""
    robot = ScalpingRobotV5(config={"max_spread_pips": 3.0, "rsi_oversold": 30.0})
    robot.news_filter.clear_events()  # Clear calendar to avoid blackout interference

    bullish_indicators = {
        "close": 2399.50,
        "bb_lower": 2400.00,  # Price dips slightly below lower band
        "bb_upper": 2410.00,
        "bb_mid": 2405.00,
        "rsi": 29.0,          # Oversold (< 30 + 3.0)
        "fast_ema": 2404.00,  # Bullish momentum: fast >= slow
        "slow_ema": 2402.00,
        "volatility_ratio": 1.0,
    }

    signal = robot.evaluate_entry(bullish_indicators, current_spread_pips=1.5)
    assert signal == ScalpingSignal.BUY
    assert robot.shield_status["status"] == "NORMAL"
    assert robot.shield_status["halted"] is False


# ── Test 2: Scalping Engine SELL Confluence ───────────────────────────────────
def test_scalping_engine_sell_confluence():
    """Verify ScalpingRobotV5 generates SELL signal under full bearish confluence."""
    robot = ScalpingRobotV5(config={"max_spread_pips": 3.0, "rsi_overbought": 70.0})
    robot.news_filter.clear_events()

    bearish_indicators = {
        "close": 2410.50,
        "bb_lower": 2400.00,
        "bb_upper": 2410.00,  # Price tags or rises above upper band
        "bb_mid": 2405.00,
        "rsi": 72.0,          # Overbought (> 70 - 3.0)
        "fast_ema": 2402.00,  # Bearish momentum: fast <= slow
        "slow_ema": 2404.00,
        "volatility_ratio": 1.0,
    }

    signal = robot.evaluate_entry(bearish_indicators, current_spread_pips=1.5)
    assert signal == ScalpingSignal.SELL
    assert robot.shield_status["status"] == "NORMAL"
    assert robot.shield_status["halted"] is False


# ── Test 3: Scalping Engine Max Orders Guard ───────────────────────────────────
def test_scalping_engine_max_orders_guard():
    """Verify ScalpingRobotV5 suppresses signals when max open positions is reached."""
    robot = ScalpingRobotV5(config={"max_orders": 1})
    robot.news_filter.clear_events()

    # Simulate existing active position
    robot.open_positions.append({"ticket": 1001, "direction": "BUY", "lots": 0.01})

    bullish_indicators = {
        "close": 2399.00,
        "bb_lower": 2400.00,
        "bb_upper": 2410.00,
        "rsi": 25.0,
        "fast_ema": 2405.00,
        "slow_ema": 2403.00,
        "volatility_ratio": 1.0,
    }

    signal = robot.evaluate_entry(bullish_indicators, current_spread_pips=1.2)
    assert signal == ScalpingSignal.HOLD
    assert robot.shield_status["status"] == "MAX_ORDERS_REACHED"
    assert robot.shield_status["halted"] is True


# ── Test 4: Scalping Engine Volatility Shield & Cooldown ───────────────────────
def test_scalping_engine_volatility_shield_and_cooldown():
    """Verify Volatility Shield trips on spike and cools down bar-by-bar before resetting."""
    robot = ScalpingRobotV5(
        config={
            "volatility_spike_threshold": 2.2,
            "volatility_cooldown_bars": 3,
        }
    )
    robot.news_filter.clear_events()

    normal_indicators = {
        "close": 2400.0,
        "bb_lower": 2395.0,
        "bb_upper": 2405.0,
        "rsi": 50.0,
        "fast_ema": 2400.0,
        "slow_ema": 2400.0,
        "volatility_ratio": 1.0,
    }

    # Spike bar (ratio 2.8 >= 2.2 threshold) -> VOLATILITY_HALT
    spike_indicators = dict(normal_indicators, volatility_ratio=2.8)
    sig_spike = robot.evaluate_entry(spike_indicators, current_spread_pips=1.0)
    assert sig_spike == ScalpingSignal.HOLD
    assert robot.shield_status["status"] == "VOLATILITY_HALT"
    assert robot.volatility_halt_counter == 3

    # Bar 1 of cooldown (counter goes from 3 -> 2)
    sig_c1 = robot.evaluate_entry(normal_indicators, current_spread_pips=1.0)
    assert sig_c1 == ScalpingSignal.HOLD
    assert robot.shield_status["status"] == "COOLDOWN"
    assert robot.volatility_halt_counter == 2

    # Bar 2 of cooldown (counter goes from 2 -> 1)
    sig_c2 = robot.evaluate_entry(normal_indicators, current_spread_pips=1.0)
    assert sig_c2 == ScalpingSignal.HOLD
    assert robot.volatility_halt_counter == 1

    # Bar 3 of cooldown (counter goes from 1 -> 0)
    sig_c3 = robot.evaluate_entry(normal_indicators, current_spread_pips=1.0)
    assert sig_c3 == ScalpingSignal.HOLD
    assert robot.volatility_halt_counter == 0

    # Bar 4: Cooldown complete -> Shield returns to NORMAL
    sig_c4 = robot.evaluate_entry(normal_indicators, current_spread_pips=1.0)
    assert robot.shield_status["status"] == "NORMAL"
    assert robot.shield_status["halted"] is False


# ── Test 5: Scalping Engine Position Sizing Safeguards ─────────────────────────
def test_scalping_engine_position_sizing_safeguards():
    """Verify calculate_position_size fails closed on non-positive or non-finite inputs."""
    robot = ScalpingRobotV5(
        config={
            "pip_value": 1.0,
            "min_lot_size": 0.01,
            "max_lot_size": 2.0,
            "lot_step": 0.01,
        }
    )

    indicators = {"atr": 2.5}

    # 1. Zero or negative balance
    assert robot.calculate_position_size(0.0, indicators) == 0.0
    assert robot.calculate_position_size(-500.0, indicators) == 0.0

    # 2. NaN balance
    assert robot.calculate_position_size(float("nan"), indicators) == 0.0

    # 3. Zero or negative risk percent
    assert robot.calculate_position_size(10000.0, indicators, risk_percent=0.0) == 0.0
    assert robot.calculate_position_size(10000.0, indicators, risk_percent=-1.0) == 0.0

    # 4. Valid normal sizing: $10,000 balance, 1% risk ($100), 20 pips SL, $1 pip value -> 5.0 lots capped to max 2.0 lots
    lots = robot.calculate_position_size(10000.0, indicators, sl_pips=20.0, risk_percent=1.0)
    assert lots == 2.0  # Capped at max_lot_size (2.0)

    # 5. Sizing within bounds: $10,000 balance, 0.1% risk ($10), 50 pips SL, $1 pip value -> $10 / $50 = 0.20 lots
    lots_mid = robot.calculate_position_size(10000.0, indicators, sl_pips=50.0, risk_percent=0.1)
    assert lots_mid == 0.20


# ── Test 6: Scalping Engine Volatility-Adaptive Dynamic Stops ──────────────────
def test_scalping_engine_dynamic_stops():
    """Verify calculate_dynamic_stops adapts stop buffer to ATR and prices."""
    robot = ScalpingRobotV5(
        config={
            "pip_size": 0.1,
            "sl_pips": 30.0,
            "tp_pips": 15.0,
            "sl_atr_multiplier": 2.0,
            "tp_atr_multiplier": 1.5,
            "min_sl_pips": 15.0,
            "max_sl_pips": 120.0,
        }
    )

    # High ATR: ATR = 2.0 price points = 20.0 pips (pip_size = 0.1)
    # SL = 20.0 * 2.0 = 40.0 pips; TP = 20.0 * 1.5 = 30.0 pips
    indicators = {"atr": 2.0}

    stops_buy = robot.calculate_dynamic_stops(indicators, price=2400.0, signal=ScalpingSignal.BUY)
    assert stops_buy["sl_pips"] == 40.0
    assert stops_buy["tp_pips"] == 30.0
    assert stops_buy["sl_price"] == 2400.0 - (40.0 * 0.1)  # 2396.0
    assert stops_buy["tp_price"] == 2400.0 + (30.0 * 0.1)  # 2403.0

    stops_sell = robot.calculate_dynamic_stops(indicators, price=2400.0, signal=ScalpingSignal.SELL)
    assert stops_sell["sl_price"] == 2400.0 + (40.0 * 0.1)  # 2404.0
    assert stops_sell["tp_price"] == 2400.0 - (30.0 * 0.1)  # 2397.0


# ── Test 7: Scalping Engine Internal Reset Hygiene ────────────────────────────
def test_scalping_engine_reset():
    """Verify robot.reset() restores circuit breakers and clears open state."""
    robot = ScalpingRobotV5()
    robot.volatility_halt_counter = 5
    robot.shield_status = {"status": "VOLATILITY_HALT", "halted": True}
    robot.open_positions.append({"ticket": 1})
    robot.trade_history.append({"pnl": 50.0})

    robot.reset()
    assert robot.volatility_halt_counter == 0
    assert robot.shield_status["status"] == "NORMAL"
    assert robot.shield_status["halted"] is False
    assert len(robot.open_positions) == 0
    assert len(robot.trade_history) == 0


# ── Test 8: Escape Launch Process Creation Flags & Command ────────────────────
def test_escape_launch_properties():
    """Verify escape_launch provides correct breakaway flags and watchdog command formatting."""
    breakaway = escape_launch.get_breakaway_flags()
    fallback = escape_launch.get_fallback_flags()

    # Breakaway flag must include CREATE_BREAKAWAY_FROM_JOB (0x01000000)
    assert bool(breakaway & escape_launch.CREATE_BREAKAWAY_FROM_JOB) is True
    assert bool(breakaway & escape_launch.DETACHED_PROCESS) is True
    assert bool(breakaway & escape_launch.CREATE_NEW_PROCESS_GROUP) is True
    assert bool(breakaway & escape_launch.CREATE_NO_WINDOW) is True

    # Fallback flags must NOT include breakaway flag
    assert bool(fallback & escape_launch.CREATE_BREAKAWAY_FROM_JOB) is False
    assert bool(fallback & escape_launch.DETACHED_PROCESS) is True

    # Command verification
    cmd = escape_launch.get_watchdog_command()
    assert isinstance(cmd, list)
    assert len(cmd) == 2
    assert cmd[0] == sys.executable
    assert "watchdog_runner.py" in cmd[1]


# ── Test 9: Gold News Fetcher Status Serialization ────────────────────────────
def test_gold_news_fetcher_status_serialization():
    """Verify write_status atomically serializes high impact state to JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_status_file = Path(tmpdir) / "news_status.json"

        headlines = [
            ("fed signals potential policy rate adjustment", "2026-10-17"),
            ("gold demand steady across global markets", "2026-10-17"),
        ]

        with patch("gold_news_fetcher.NEWS_STATUS_FILE", str(tmp_status_file)):
            gold_news_fetcher.write_status(
                high_impact=True,
                headlines=headlines,
                avoid_trading=True,
            )

            assert tmp_status_file.exists()
            status_data = json.loads(tmp_status_file.read_text(encoding="utf-8"))
            assert status_data["high_impact_alert"] is True
            assert status_data["avoid_trading"] is True
            assert len(status_data["last_headlines"]) == 2
            assert "last_checked" in status_data


# ── Test 10: MT4 Auto-Installer Resilient Error Handling ────────────────────────
def test_auto_install_to_mt4_error_containment():
    """Verify install_to_target safely returns empty list on invalid or unwritable target path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file where a directory would need to be created (provoking OSError/FileExistsError)
        blocking_file = Path(tmpdir) / "blocked_target"
        blocking_file.write_text("blocker", encoding="utf-8")

        # install_to_target should catch filesystem error and return [] without crashing
        result = auto_install_to_mt4.install_to_target(target_dir=str(blocking_file / "subfolder"))
        assert result == []
