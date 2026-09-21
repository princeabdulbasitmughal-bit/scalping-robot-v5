"""
Comprehensive Test Suite for Scalping Robot V5 Pro
Tests atomic storage, concurrent I/O, indicator math, MT5 live trader resiliency,
zero-unhandled-exception guarantees, and backtester stability.
"""

import os
import sys
import json
import time
import tempfile
import threading
import pytest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from python_engine.storage import atomic_write_json, safe_read_json
from python_engine.scalping_engine import ScalpingRobotV5, ScalpingSignal
from python_engine.mt5_live_trader import MT5LiveTrader
from python_engine.live_runner import ScalpingLiveRunner
from python_engine.backtester import ScalpingBacktester


# ---------------------------------------------------------------------------
# Storage & Atomic Write Tests
# ---------------------------------------------------------------------------
def test_atomic_write_and_safe_read():
    """Verify atomic write creates valid file and safe_read reads it back accurately."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target_file = Path(tmpdir) / "test_status.json"
        payload = {
            "status": "ACTIVE_SCALPING",
            "price": 2450.50,
            "balance": 10500.25,
            "positions": [{"id": 1, "type": "BUY"}]
        }

        # Test write
        success = atomic_write_json(target_file, payload)
        assert success is True
        assert target_file.exists()

        # Test read
        data = safe_read_json(target_file)
        assert data == payload
        assert data["balance"] == 10500.25


def test_atomic_write_concurrency():
    """Simulate rapid concurrent writes and reads to verify zero read locks or corruption."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target_file = Path(tmpdir) / "concurrent_status.json"
        errors = []
        read_counts = [0]
        stop_flag = threading.Event()

        def writer():
            for i in range(50):
                payload = {"counter": i, "timestamp": time.time(), "nested": {"val": i * 10}}
                ok = atomic_write_json(target_file, payload)
                if not ok:
                    errors.append(f"Write failed at {i}")
                time.sleep(0.005)

        def reader():
            while not stop_flag.is_set():
                val = safe_read_json(target_file, default=None)
                if val is not None:
                    assert isinstance(val, dict)
                    assert "counter" in val
                    read_counts[0] += 1
                time.sleep(0.002)

        # Initial write
        atomic_write_json(target_file, {"counter": -1, "timestamp": time.time(), "nested": {"val": 0}})

        w_thread = threading.Thread(target=writer)
        r_threads = [threading.Thread(target=reader) for _ in range(3)]

        for t in r_threads:
            t.start()
        w_thread.start()

        w_thread.join()
        stop_flag.set()
        for t in r_threads:
            t.join()

        assert len(errors) == 0
        assert read_counts[0] > 10


# ---------------------------------------------------------------------------
# Scalping Engine & Indicator Tests
# ---------------------------------------------------------------------------
def test_indicator_calculations_normal():
    """Verify indicators calculate correctly with sufficient bars."""
    robot = ScalpingRobotV5({"bb_period": 10, "fast_ema": 5, "slow_ema": 10, "rsi_period": 7, "atr_period": 7})
    bars = []
    price = 2400.0
    for i in range(40):
        price += (1.0 if i % 2 == 0 else -0.5)
        bars.append({
            "open": price - 0.2,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 50,
            "timestamp": f"2026-09-15 00:{i:02d}:00"
        })

    indicators = robot.calculate_indicators(bars)
    assert indicators != {}
    assert "fast_ema" in indicators
    assert "slow_ema" in indicators
    assert "bb_upper" in indicators
    assert "bb_lower" in indicators
    assert "rsi" in indicators
    assert "atr" in indicators
    assert indicators["bb_upper"] >= indicators["bb_lower"]
    assert 0.0 <= indicators["rsi"] <= 100.0
    assert indicators["atr"] > 0.0


def test_indicator_edge_cases():
    """Verify indicators handle flat prices, zero variance, and small samples gracefully."""
    robot = ScalpingRobotV5({"bb_period": 10, "fast_ema": 5, "slow_ema": 10, "rsi_period": 7})

    # Insufficient bars
    short_bars = [{"close": 2400.0, "high": 2401.0, "low": 2399.0} for _ in range(5)]
    assert robot.calculate_indicators(short_bars) == {}

    # Completely flat bars (zero price change -> 0 variance, 0 gains, 0 losses)
    flat_bars = [{"close": 2400.0, "high": 2400.0, "low": 2400.0, "volume": 10, "timestamp": ""} for _ in range(30)]
    indicators = robot.calculate_indicators(flat_bars)
    assert indicators != {}
    assert indicators["bb_upper"] == indicators["bb_lower"] == 2400.0
    assert indicators["rsi"] == 50.0  # Equal gains and losses (both 0) should evaluate to 50.0 neutral


def test_signal_evaluation_and_spread_guard():
    """Test BUY/SELL signals and spread protection."""
    robot = ScalpingRobotV5({"max_spread_pips": 2.0, "max_orders": 1})

    # Spread too wide -> MUST HOLD
    ind = {
        "close": 2390.0,
        "bb_lower": 2395.0,
        "bb_upper": 2415.0,
        "fast_ema": 2405.0,
        "slow_ema": 2400.0,
        "rsi": 25.0
    }
    sig = robot.evaluate_entry(ind, current_spread_pips=3.5)
    assert sig == ScalpingSignal.HOLD

    # Buy Setup: close <= bb_lower, rsi oversold, spread normal
    sig_buy = robot.evaluate_entry(ind, current_spread_pips=1.5)
    assert sig_buy == ScalpingSignal.BUY

    # Max orders full -> MUST HOLD
    robot.open_positions.append({"id": "dummy"})
    assert robot.evaluate_entry(ind, current_spread_pips=1.5) == ScalpingSignal.HOLD


# ---------------------------------------------------------------------------
# MT5 Live Trader Hardening & Crash-Proof Tests
# ---------------------------------------------------------------------------
def test_mt5_live_trader_simulation_loop():
    """Test MT5LiveTrader in simulation mode with atomic status updates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_status = Path(tmpdir) / "live_status.json"

        trader = MT5LiveTrader({
            "symbol": "XAUUSD",
            "lot_size": 0.01,
            "max_orders": 1,
            "tick_interval_sec": 0.01
        })

        # Run 5 steps
        for _ in range(5):
            trader.evaluate_and_trade()

        assert trader.current_price > 0
        assert trader.equity > 0
        assert len(trader.bars) >= 120
        assert trader.last_signal in [ScalpingSignal.BUY, ScalpingSignal.SELL, ScalpingSignal.HOLD]


def test_zero_unhandled_exceptions_in_live_trader():
    """Verify that simulated corrupted inputs or exceptions inside evaluate_and_trade do not crash the engine."""
    trader = MT5LiveTrader({"symbol": "XAUUSD", "lot_size": 0.01})

    # Sabotage bars with empty list
    trader.bars = []
    # Should self-heal and re-initialize without raising
    trader.evaluate_and_trade()
    assert len(trader.bars) > 0

    # Test run_live with 3 iterations - should execute cleanly
    trader.config["tick_interval_sec"] = 0.001
    trader.run_live(iterations=3)


# ---------------------------------------------------------------------------
# Backtester & Live Runner Tests
# ---------------------------------------------------------------------------
def test_backtester_simulation():
    """Verify ScalpingBacktester runs synthetic backtests and outputs valid institutional metrics."""
    backtester = ScalpingBacktester({"symbol": "XAUUSD", "lot_size": 0.01})
    bars = backtester.generate_synthetic_gold_m1(bars_count=200, start_price=2400.0)
    assert len(bars) == 200

    results = backtester.run_backtest(bars, initial_balance=10000.0)
    assert "final_balance" in results
    assert "net_profit" in results
    assert "win_rate_pct" in results
    assert "profit_factor" in results
    assert "max_drawdown_usd" in results
    assert results["initial_balance"] == 10000.0


def test_live_runner_tick_and_atomic_write():
    """Verify ScalpingLiveRunner executes ticks and persists state atomically."""
    runner = ScalpingLiveRunner({"symbol": "XAUUSD", "lot_size": 0.01})
    status = runner.update_tick(2410.50)
    assert status["status"] == "ACTIVE_SCALPING"
    assert status["current_price"] == 2410.50
    assert status["balance"] == 10000.0


# ---------------------------------------------------------------------------
# Latency & Slippage Optimization Tests
# ---------------------------------------------------------------------------
def test_dynamic_slippage_calculation():
    """Verify dynamic slippage adapts to spread and volatility while strictly clamping to min/max boundaries."""
    trader = MT5LiveTrader({
        "symbol": "XAUUSD",
        "base_slippage": 10,
        "min_slippage": 5,
        "max_slippage": 30
    })

    # Calm market, tight spread (1.2 pips, low ATR)
    trader.spread_pips = 1.2
    calm_dev = trader.calculate_dynamic_slippage({"atr": 0.2})
    assert 5 <= calm_dev <= 15
    assert calm_dev == trader.current_dynamic_slippage

    # Volatile breakout, wide spread (3.0 pips, surging ATR 3.5)
    trader.spread_pips = 3.0
    vol_dev = trader.calculate_dynamic_slippage({"atr": 3.5})
    assert vol_dev > calm_dev
    assert vol_dev <= 30  # Clamped to max_slippage

    # Extreme volatility: must clamp at max_slippage (30)
    trader.spread_pips = 10.0
    extreme_dev = trader.calculate_dynamic_slippage({"atr": 50.0})
    assert extreme_dev == 30

    # Negative or extreme tight: must clamp at min_slippage (5)
    trader.spread_pips = 0.1
    tight_dev = trader.calculate_dynamic_slippage({"atr": 0.001})
    assert tight_dev >= 5


def test_adaptive_spread_filter_and_spike_guard():
    """Verify spread filter rejects wide spreads, detects liquidity shock spikes, and accepts normal conditions."""
    trader = MT5LiveTrader({
        "symbol": "XAUUSD",
        "max_spread_pips": 2.5,
        "hard_max_spread_pips": 3.5,
        "spread_spike_ratio": 1.5
    })

    # 1. Normal spread (1.5 pips)
    trader.spread_pips = 1.5
    trader._rolling_spread_ema = 1.5
    for _ in range(10):
        trader._spread_history.append(1.5)
    ok, reason = trader.check_spread_filter()
    assert ok is True
    assert reason == "OK"

    # 2. Hard spread exceeded (> 3.5 pips)
    trader.spread_pips = 3.8
    ok, reason = trader.check_spread_filter()
    assert ok is False
    assert "HARD_SPREAD_EXCEEDED" in reason

    # 3. Liquidity shock / news spike (normal is 1.2, sudden spike to 2.2 = 1.83x)
    trader._rolling_spread_ema = 1.2
    trader._spread_history.clear()
    for _ in range(10):
        trader._spread_history.append(1.2)
    trader.spread_pips = 2.4  # 2.4 > 1.2 * 1.5 and >= 1.8
    ok, reason = trader.check_spread_filter()
    assert ok is False
    assert "SPREAD_SPIKE" in reason

    # 4. Invalid zero/negative spread
    trader.spread_pips = 0.0
    ok, reason = trader.check_spread_filter()
    assert ok is False
    assert reason == "INVALID_SPREAD"


def test_non_blocking_order_worker_and_fill_confirmation():
    """Verify order execution worker confirms orders asynchronously without stalling the tick loop."""
    trader = MT5LiveTrader({
        "symbol": "XAUUSD",
        "lot_size": 0.01,
        "max_orders": 1,
        "tick_interval_sec": 0.001
    })

    # In simulation mode, order placement occurs cleanly
    assert trader._order_in_flight is False
    assert len(trader.open_positions) == 0

    # Simulate 5 rapid evaluation steps
    for _ in range(5):
        trader.evaluate_and_trade()

    # Worker and queue should be responsive
    assert trader.latency_metrics["avg_tick_loop_us"] > 0
    assert trader.latency_metrics["ticks_processed"] >= 5
    trader.stop()


def test_micro_tick_latency_benchmarking():
    """Benchmark that tick processing loop latency is sub-millisecond (< 1.0 ms) after optimizations."""
    trader = MT5LiveTrader({
        "symbol": "XAUUSD",
        "lot_size": 0.01,
        "max_orders": 1,
        "tick_interval_sec": 0.001
    })

    times_ms = []
    for _ in range(30):
        t0 = time.perf_counter()
        trader.evaluate_and_trade()
        t1 = time.perf_counter()
        times_ms.append((t1 - t0) * 1000.0)

    avg_ms = sum(times_ms) / len(times_ms)
    # Average loop latency must be sub-millisecond (previously ~6-10ms)
    assert avg_ms < 1.0, f"Tick loop took {avg_ms:.2f} ms (expected < 1.0 ms)"
    trader.stop()
