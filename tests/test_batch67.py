"""
tests/test_batch67.py
Batch 67 Unit Tests: Signal Optimizer (Wave 8), Risk Manager (Wave 9),
ML Predictor (Wave 13), Telegram Alerts (Wave 12), Trade Journal,
Performance Monitor, and Supervisor Keep-Alive Resiliency.
"""

import math
import time
import pytest
from datetime import datetime, timezone
from pathlib import Path

from wave8_signal_optimizer import SignalScorer
from wave9_risk_manager import RiskManager
from wave13_ml_predictor import LinearRegressor, MLPredictor
from wave12_telegram_alerts import TelegramAlerter
from trade_journal import TradeJournal
from performance_monitor import calculate_grade, _safe_float
from supervisor import calculate_backoff, check_circuit_breaker


def test_wave8_signal_scorer_atr_stoch_rsi_patterns():
    """Verify SignalScorer computes ATR, Stochastic RSI, and candlestick patterns."""
    scorer = SignalScorer()

    # 1. ATR calculation
    bars = [
        {"high": 2652.0, "low": 2648.0, "close": 2650.0, "open": 2649.0},
        {"high": 2654.0, "low": 2649.0, "close": 2653.0, "open": 2650.0},
        {"high": 2655.0, "low": 2651.0, "close": 2652.0, "open": 2653.0},
        {"high": 2653.0, "low": 2648.0, "close": 2649.0, "open": 2652.0},
    ]
    atr = scorer.compute_atr(bars)
    assert atr > 0.0
    assert math.isfinite(atr)

    # 2. Stochastic RSI
    closes = [2640.0 + i * 0.8 for i in range(25)]
    stoch = scorer.compute_stoch_rsi(closes)
    assert 0.0 <= stoch <= 100.0

    # 3. Candlestick patterns
    # Hammer: bullish, small body at top, lower wick > 2*body, upper wick < body
    hammer_bars = [
        {"high": 2650.0, "low": 2648.0, "open": 2650.0, "close": 2649.0},
        {"open": 2651.0, "close": 2651.5, "high": 2651.6, "low": 2648.0},
    ]
    assert scorer.detect_pattern(hammer_bars) == "HAMMER"

    # Shooting Star: bearish, small body at bottom, upper wick > 2*body, lower wick < body
    star_bars = [
        {"open": 2650.0, "close": 2651.0, "high": 2651.5, "low": 2649.5},
        {"open": 2651.5, "close": 2651.0, "high": 2654.0, "low": 2650.8},
    ]
    assert scorer.detect_pattern(star_bars) == "SHOOTING_STAR"

    # Doji: body < 10% of total range
    doji_bars = [
        {"open": 2650.0, "close": 2651.0, "high": 2651.5, "low": 2649.5},
        {"open": 2650.50, "close": 2650.52, "high": 2653.0, "low": 2648.0},
    ]
    assert scorer.detect_pattern(doji_bars) == "DOJI"


def test_wave8_signal_scorer_composite_score_and_adaptive_tpsl():
    """Verify SignalScorer composite score and ATR-adaptive SL/TP scaling."""
    scorer = SignalScorer()

    # HOLD returns 0
    assert scorer.score_signal("HOLD", [2650.0] * 20, [], 50.0, False, "RANGING", "NEUTRAL") == 0

    # Strong BUY in uptrend with bullish engulfing
    bars = [
        {"open": 2652.0, "close": 2649.0, "high": 2652.5, "low": 2648.5},  # previous bear
        {"open": 2648.0, "close": 2653.0, "high": 2653.5, "low": 2647.5},  # current bull engulf
    ]
    closes = [2640.0 + i * 0.5 for i in range(25)]
    score = scorer.score_signal(
        signal="BUY",
        closes=closes,
        bars=bars,
        rsi=28.0,  # oversold bonus
        bb_squeeze=True,
        market_regime="TRENDING_UP",
        ema_cross="BUY",
    )
    assert score >= 60

    # Gate verification
    allowed, _ = scorer.is_trading_allowed(score=score, threshold=55)
    assert allowed is True

    blocked, reason = scorer.is_trading_allowed(score=40, threshold=55)
    assert blocked is False
    assert "LOW_SIGNAL_SCORE" in reason

    # Adaptive SL/TP
    sl, tp = scorer.get_adaptive_sl_tp(bars, base_sl_pips=30.0, rr_ratio=1.5)
    assert 15.0 <= sl <= 60.0
    assert tp == round(sl * 1.5, 1)


def test_wave9_risk_manager_equity_ema_and_drawdown_tiers():
    """Verify RiskManager tracks equity curve EMA and scales lots based on drawdown tiers."""
    rm = RiskManager({"starting_balance": 10000.0, "max_drawdown_pct": 10.0})

    # Update equity series
    for eq in [10000.0, 10050.0, 10100.0, 10150.0, 10200.0]:
        rm.update_equity(eq)

    assert rm.peak_balance == 10200.0
    assert rm.equity_curve_ok(10200.0) is True

    # Equity drop below EMA
    assert rm.drawdown_pct(10200.0) == 0.0

    # 3% drawdown (10200 -> 9894) -> tier 0.75x
    assert rm.drawdown_lot_scale(9894.0) == 0.75

    # 5% drawdown (10200 -> 9690) -> tier 0.50x
    assert rm.drawdown_lot_scale(9690.0) == 0.50

    # 7% drawdown (10200 -> 9486) -> tier 0.25x
    assert rm.drawdown_lot_scale(9486.0) == 0.25

    # 9% drawdown (10200 -> 9282) -> tier 0.10x
    assert rm.drawdown_lot_scale(9282.0) == 0.10

    # >= 10% drawdown -> max drawdown hit
    assert rm.is_max_drawdown_hit(9180.0) is True


def test_wave9_risk_manager_frequency_governor_and_composite_gate():
    """Verify RiskManager frequency governor and master risk gate."""
    rm = RiskManager({
        "max_trades_per_hour": 3,
        "starting_balance": 10000.0,
        "max_daily_loss_usd": 200.0,
        "daily_profit_target_usd": 150.0,
    })

    # Trade frequency sliding window
    rm.record_trade(now_ts=100.0)
    rm.record_trade(now_ts=110.0)
    rm.record_trade(now_ts=120.0)

    # 4th trade in same hour blocked
    assert rm.can_trade_frequency(now_ts=130.0) is False

    # Trades older than 3600s roll off
    assert rm.can_trade_frequency(now_ts=3750.0) is True

    # Position correlation (max 1 position per direction)
    open_positions = [{"type": "BUY", "ticket": 101}]
    assert rm.correlation_ok(open_positions, new_signal="BUY") is False
    assert rm.correlation_ok(open_positions, new_signal="SELL") is True

    # Composite risk gate: valid state
    gate_ok = rm.should_trade(
        balance=10000.0,
        equity=10000.0,
        daily_pnl=50.0,
        daily_loss=0.0,
        open_positions=[],
        new_signal="BUY",
        now_ts=3800.0,
    )
    assert gate_ok["allowed"] is True
    assert gate_ok["lot_scale"] > 0.0

    # Composite risk gate: daily loss breached
    gate_loss = rm.should_trade(
        balance=9750.0,
        equity=9750.0,
        daily_pnl=-250.0,
        daily_loss=250.0,
        open_positions=[],
        new_signal="BUY",
        now_ts=3800.0,
    )
    assert gate_loss["allowed"] is False
    assert "Daily loss limit" in gate_loss["reason"]


def test_wave13_linear_regressor_math_and_edge_cases():
    """Verify LinearRegressor fit calculations, r-squared bounds, and malformed inputs."""
    lr = LinearRegressor()

    # Empty and tiny sets
    assert lr.fit([]) == {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}
    assert lr.fit([10.0, 20.0]) == {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}

    # Flat line (zero slope)
    flat_fit = lr.fit([100.0] * 10)
    assert flat_fit["slope"] == 0.0
    assert flat_fit["r_squared"] == 0.0

    # Perfect linear rise: y = 2x + 10
    rising_y = [10.0 + 2.0 * i for i in range(10)]
    rising_fit = lr.fit(rising_y)
    assert abs(rising_fit["slope"] - 2.0) < 1e-4
    assert abs(rising_fit["intercept"] - 10.0) < 1e-4
    assert abs(rising_fit["r_squared"] - 1.0) < 1e-4

    # Handling NaN and None elements cleanly
    messy_y = [10.0, None, float("nan"), 12.0, 14.0, 16.0]
    messy_fit = lr.fit(messy_y)
    assert messy_fit["slope"] > 0.0
    assert 0.0 <= messy_fit["r_squared"] <= 1.0


def test_wave13_ml_predictor_direction_and_confidence():
    """Verify MLPredictor classifies trend direction, confidence, and signal agreement."""
    mlp = MLPredictor(window=10, min_r2=0.20)

    # 1. Upward trend
    closes_up = [2650.0 + 0.6 * i for i in range(15)]
    res_up = mlp.predict(closes_up)
    assert res_up["direction"] == "UP"
    assert res_up["confidence"] >= 50
    assert res_up["slope"] > 0.0

    # Agreement with BUY signal
    agree_buy = mlp.predict_signal_agreement(closes_up, signal="BUY")
    assert agree_buy["agree"] is True
    assert agree_buy["confidence"] >= 50

    # 2. Downward trend
    closes_down = [2650.0 - 0.6 * i for i in range(15)]
    res_down = mlp.predict(closes_down)
    assert res_down["direction"] == "DOWN"
    assert res_down["confidence"] >= 50
    assert res_down["slope"] < 0.0

    # Disagreement with BUY signal
    agree_mismatch = mlp.predict_signal_agreement(closes_down, signal="BUY")
    assert agree_mismatch["agree"] is False


def test_wave12_telegram_alerter_custom_sender_and_formatting(tmp_path):
    """Verify TelegramAlerter message formatting and mocked network dispatch."""
    sent_payloads = []

    def mock_sender(msg: str) -> bool:
        sent_payloads.append(msg)
        return True

    cfg_file = str(tmp_path / "telegram_config.json")
    alerter = TelegramAlerter(config_path=cfg_file, sender_fn=mock_sender)
    alerter.update_config({"enabled": True, "min_alert_interval_sec": 10})

    # Trade Open Alert
    alerter.alert_trade_open(
        direction="BUY",
        entry=2650.50,
        sl=2645.00,
        tp=2660.00,
        lot=0.03,
        force=True,
    )
    time.sleep(0.05)  # background thread dispatch

    assert len(sent_payloads) >= 1
    assert "BUY OPENED" in sent_payloads[0]
    assert "2650.50" in sent_payloads[0]
    assert "0.03" in sent_payloads[0]

    # Trade Close Alert
    alerter.alert_trade_close(
        direction="BUY",
        pnl=85.20,
        reason="TP_HIT",
        balance=10085.20,
        force=True,
    )
    time.sleep(0.05)

    assert len(sent_payloads) >= 2
    assert "WIN CLOSED" in sent_payloads[1]
    assert "$+85.20" in sent_payloads[1]


def test_trade_journal_sqlite_lifecycle_and_queries(tmp_path):
    """Verify TradeJournal SQLite WAL initialization, trade logging, and upserts."""
    db_file = str(tmp_path / "test_journal.db")
    tj = TradeJournal(db_path=db_file)

    # Log trade
    trade = {
        "timestamp": "2026-10-17T12:00:00Z",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "entry_price": 2650.00,
        "exit_price": 2655.00,
        "lot_size": 0.02,
        "sl_price": 2645.00,
        "tp_price": 2660.00,
        "pnl": 50.00,
        "exit_reason": "TP",
        "duration_sec": 240,
        "signal_tier": 1,
        "spread_pips": 1.5,
    }
    assert tj.log_trade(trade) is True

    # Retrieve trades
    history = tj.get_last_N_trades(5)
    assert len(history) == 1
    assert history[0]["symbol"] == "XAUUSD"
    assert history[0]["pnl"] == 50.00

    # Daily summary upsert
    summary_initial = {
        "date": "2026-10-17",
        "total_trades": 1,
        "wins": 1,
        "losses": 0,
        "win_rate": 100.0,
        "total_pnl": 50.00,
    }
    assert tj.log_daily_summary(summary_initial) is True

    # Update same date without conflict
    summary_updated = {
        "date": "2026-10-17",
        "total_trades": 2,
        "wins": 2,
        "losses": 0,
        "win_rate": 100.0,
        "total_pnl": 110.00,
    }
    assert tj.log_daily_summary(summary_updated) is True


def test_performance_monitor_grading_and_safe_float():
    """Verify performance grading tiers and float sanitization."""
    assert calculate_grade(95.0) == "A+"
    assert calculate_grade(88.0) == "A"
    assert calculate_grade(78.0) == "B"
    assert calculate_grade(65.0) == "C"
    assert calculate_grade(float("nan")) == "C"
    assert calculate_grade(None) == "C"

    # Float sanitization
    assert _safe_float(45.5) == 45.5
    assert _safe_float("invalid", 10.0) == 10.0
    assert _safe_float(None, 20.0) == 20.0
    assert _safe_float(float("nan"), 0.0) == 0.0
    assert _safe_float(float("inf"), 0.0) == 0.0


def test_supervisor_backoff_and_circuit_breaker():
    """Verify supervisor exponential backoff progression and circuit breaker threshold."""
    assert calculate_backoff(0) == 0
    assert calculate_backoff(1) == 8
    assert calculate_backoff(2) == 16
    assert calculate_backoff(3) == 32
    assert calculate_backoff(4) == 64
    assert calculate_backoff(5) == 120  # capped at 120s
    assert calculate_backoff(10) == 120

    # Circuit breaker
    assert check_circuit_breaker(10) is False
    assert check_circuit_breaker(19) is False
    assert check_circuit_breaker(20) is True
    assert check_circuit_breaker(25) is True
