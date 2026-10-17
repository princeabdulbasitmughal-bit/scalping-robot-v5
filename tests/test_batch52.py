"""
Test Suite: Batch 52 — Backtester, Signal/Risk Optimizers & ML Predictor Verification
====================================================================================
Hermetic unit test suite verifying:
  1. Backtester: Session volatility & Gaussian random walk tick simulation
  2. Backtester: In-memory simulation execution & metrics aggregation
  3. Wave 8: Signal Scorer (ATR, Stochastic RSI, Candlestick pattern recognition)
  4. Wave 8: Master signal scoring confluence (0-100 thresholding)
  5. Wave 9: Risk Manager (Equity curve EMA, trade allowance, lot multiplier)
  6. Wave 10: Session Optimizer (Session volatility profile, target adjustment, rollover filter)
  7. Wave 11: Profit Optimizer (Win/loss streaks, confidence/recovery lot multipliers, reversal exit)
  8. Wave 12: Telegram Alerter (Zero-dependency notifications, rate limiting, disabled mode)
  9. Wave 13: ML Predictor (Pure Python OLS Linear Regression, trend direction & confidence)
 10. Wave 14 & Escape Launch: AutoTuner statistics (_mean, _std, _percentile) & process creation flags
"""

import math
from datetime import datetime, timezone
import pytest

from python_engine.backtester import Backtester
from wave8_signal_optimizer import SignalScorer
from wave9_risk_manager import RiskManager
from wave10_session_optimizer import SessionOptimizer
from wave11_profit_optimizer import ProfitOptimizer
from wave12_telegram_alerts import TelegramAlerter
from wave13_ml_predictor import LinearRegressor, MLPredictor
from wave14_auto_tuner import _mean, _std, _percentile
from escape_launch import get_breakaway_flags, get_fallback_flags, CREATE_BREAKAWAY_FROM_JOB


# ── Test 1: Backtester Session Volatility & Tick Simulation ───────────────────
def test_backtester_tick_simulation():
    """Verify Backtester models session-aware volatility and generates realistic ticks."""
    bt = Backtester(config={"symbol": "XAUUSD", "pip_size": 0.1})

    assert bt.get_session_volatility("TOKYO") == 0.02
    assert bt.get_session_volatility("LONDON") == 0.08
    assert bt.get_session_volatility("NY") == 0.12

    session_tokyo, vol_tokyo = bt.determine_session(10, 100)
    assert session_tokyo == "TOKYO"
    assert vol_tokyo == 0.02

    session_london, vol_london = bt.determine_session(50, 100)
    assert session_london == "LONDON"
    assert vol_london == 0.08

    session_ny, vol_ny = bt.determine_session(90, 100)
    assert session_ny == "NY"
    assert vol_ny == 0.12

    ticks = bt.simulate_ticks(n_ticks=100, start_price=2400.0, session="LONDON")
    assert len(ticks) == 100
    assert all("price" in t and "spread_pips" in t and "session" in t for t in ticks)
    assert ticks[0]["session"] == "LONDON"


# ── Test 2: Backtester Metrics Aggregation ────────────────────────────────────
def test_backtester_execution_flow():
    """Verify Backtester runs backtest over synthetic ticks and returns result metrics."""
    bt = Backtester(config={"symbol": "XAUUSD", "pip_size": 0.1, "lot_size": 0.01})
    ticks = bt.simulate_ticks(n_ticks=200, start_price=2400.0)

    results = bt.run_backtest(ticks)
    assert isinstance(results, dict)
    assert "total_trades" in results or "trades" in results or "total_pnl" in results or "balance" in results


# ── Test 3: Wave 8 ATR, Stochastic RSI & Pattern Detection ───────────────────
def test_wave8_indicators_and_patterns():
    """Verify SignalScorer computes ATR, Stochastic RSI, and candlestick patterns."""
    scorer = SignalScorer()

    bars = [
        {"high": 2402.0, "low": 2400.0, "open": 2400.5, "close": 2401.5},
        {"high": 2403.0, "low": 2401.0, "open": 2401.5, "close": 2402.5},
        {"high": 2404.0, "low": 2402.0, "open": 2402.5, "close": 2403.5},
    ]
    atr = scorer.compute_atr(bars)
    assert atr > 0.0

    closes = [2400.0 + i * 0.5 for i in range(25)]
    stoch = scorer.compute_stoch_rsi(closes)
    assert 0.0 <= stoch <= 100.0

    # Test Doji pattern: open close very tight (< 10% of range)
    doji_bars = [
        {"high": 2400.0, "low": 2398.0, "open": 2399.0, "close": 2399.0},
        {"high": 2405.0, "low": 2395.0, "open": 2400.0, "close": 2400.05},
    ]
    assert scorer.detect_pattern(doji_bars) == "DOJI"


# ── Test 4: Wave 8 Signal Scoring Confluence ──────────────────────────────────
def test_wave8_signal_scoring():
    """Verify score_signal scales quality based on momentum, pattern and regime."""
    scorer = SignalScorer()

    closes = [2400.0 - i * 0.5 for i in range(25)]  # falling prices -> oversold Stoch RSI
    bars = [{"high": 2401.0, "low": 2399.0, "open": 2400.0, "close": 2400.5}]

    # BUY on oversold conditions scores high
    buy_score = scorer.score_signal(
        signal="BUY",
        closes=closes,
        bars=bars,
        rsi=25.0,
        bb_squeeze=True,
        market_regime="TRENDING_UP",
        ema_cross="BULLISH",
    )
    assert buy_score >= 50

    # HOLD signals score 0
    assert scorer.score_signal("HOLD", closes, bars, 50.0, False, "RANGING", "NONE") == 0


# ── Test 5: Wave 9 Risk Manager Equity Curve & Dynamic Scaling ────────────────
def test_wave9_risk_manager():
    """Verify RiskManager tracks equity EMA curve and scales lots on drawdown."""
    rm = RiskManager(config={"max_daily_loss_usd": 200.0, "daily_profit_target_usd": 150.0})

    # Feed rising equity
    for eq in [10000.0 + i * 50.0 for i in range(15)]:
        rm.update_equity(eq)
    assert rm.equity_curve_ok(10500.0) is True

    # Master risk gate under healthy conditions
    res = rm.should_trade(
        balance=10500.0,
        equity=10500.0,
        daily_pnl=50.0,
        daily_loss=0.0,
        open_positions=[],
        new_signal="BUY",
    )
    assert res["allowed"] is True
    assert res["lot_scale"] >= 0.5

    # PnL scaling: daily loss reduces lot scale
    assert rm.daily_loss_lot_scale(daily_loss=10.0) == 1.0
    assert rm.daily_loss_lot_scale(daily_loss=120.0) <= 0.75


# ── Test 6: Wave 10 Session Optimizer Profiles & Avoid Windows ────────────────
def test_wave10_session_optimizer():
    """Verify SessionOptimizer adjusts pip targets and identifies avoid hours."""
    so = SessionOptimizer()

    # Tokyo session on a Wednesday (2026-10-14 04:00 UTC) -> pip multiplier is 0.7
    dt_tokyo = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)
    info_tokyo = so.get_current_session_info(now_dt=dt_tokyo)
    assert info_tokyo["session"] == "TOKYO"
    assert info_tokyo["pip_multiplier"] == 0.7
    sl_tokyo, tp_tokyo = so.get_adjusted_targets(base_sl=20.0, base_tp=20.0, rr_ratio=1.5, now_dt=dt_tokyo)
    assert sl_tokyo == 15.0  # max(15.0, 14.0)
    assert tp_tokyo == 22.5

    # London/NY Overlap on a Wednesday (2026-10-14 14:30 UTC) -> premium multiplier (1.3x)
    dt_overlap = datetime(2026, 10, 14, 14, 30, tzinfo=timezone.utc)
    info_overlap = so.get_current_session_info(now_dt=dt_overlap)
    assert info_overlap["session"] == "OVERLAP"
    assert info_overlap["pip_multiplier"] == 1.3
    sl_overlap, tp_overlap = so.get_adjusted_targets(base_sl=20.0, base_tp=20.0, rr_ratio=1.5, now_dt=dt_overlap)
    assert sl_overlap == 26.0
    assert tp_overlap == 39.0

    # Rollover window (2026-10-14 22:30 UTC) -> trading blocked
    dt_rollover = datetime(2026, 10, 14, 22, 30, tzinfo=timezone.utc)
    allowed, reason = so.is_trading_allowed(now_dt=dt_rollover)
    assert allowed is False
    assert "ROLLOVER" in reason.upper() or "AVOID" in reason.upper()


# ── Test 7: Wave 11 Profit Optimizer Streaks & Reversal Guard ─────────────────
def test_wave11_profit_optimizer():
    """Verify ProfitOptimizer manages streak bonuses, recovery mode, and floating profit exits."""
    po = ProfitOptimizer()

    # 3 consecutive wins -> 1.1x confidence lot modifier
    po.record_result(won=True)
    po.record_result(won=True)
    po.record_result(won=True)
    assert po.streak_lot_modifier() == 1.1
    assert po.is_recovery_mode() is False

    # 3 consecutive losses -> 0.5x recovery lot modifier
    po.record_result(won=False)
    po.record_result(won=False)
    po.record_result(won=False)
    assert po.streak_lot_modifier() == 0.5
    assert po.is_recovery_mode() is True

    # 5 consecutive losses -> 0.10x ultra-conservative
    po.record_result(won=False)
    po.record_result(won=False)
    assert po.streak_lot_modifier() == 0.10

    # Floating PnL reversal test: peak was $50, drops to $20 (> 50% reversal)
    po.update_peak_float("ticket_100", 50.0)
    should_close = po.should_close_reversal("ticket_100", 20.0)
    assert should_close is True


# ── Test 8: Wave 12 Telegram Alerter Rate Limiting ────────────────────────────
def test_wave12_telegram_alerter():
    """Verify TelegramAlerter rate-limits and handles disabled mode without external calls."""
    import time
    sent_payloads = []

    def mock_sender(text):
        sent_payloads.append(text)
        return True

    alerter = TelegramAlerter(sender_fn=mock_sender)
    # Default is disabled -> returns False
    assert alerter.send_alert("Test Alert", now_ts=1000.0) is False
    assert len(sent_payloads) == 0

    # Enable and test mock sending
    alerter._config["enabled"] = True
    alerter._config["min_alert_interval_sec"] = 60

    sent = alerter.send_alert("Test Alert 1", force=True, now_ts=1000.0)
    assert sent is True
    time.sleep(0.05)
    assert len(sent_payloads) == 1

    # Immediate second alert at now_ts=1010.0 (< 60s) without force is rate-limited
    sent_fast = alerter.send_alert("Rapid Alert", force=False, now_ts=1010.0)
    assert sent_fast is False
    assert len(sent_payloads) == 1


# ── Test 9: Wave 13 ML Predictor Pure Python OLS ──────────────────────────────
def test_wave13_ml_predictor():
    """Verify LinearRegressor and MLPredictor accurately compute slopes and directions."""
    regressor = LinearRegressor()

    # Perfect upward line: y = [1, 2, 3, 4, 5] -> slope=1.0, r_squared=1.0
    fit_up = regressor.fit([1.0, 2.0, 3.0, 4.0, 5.0])
    assert fit_up["slope"] == pytest.approx(1.0, abs=1e-4)
    assert fit_up["r_squared"] == pytest.approx(1.0, abs=1e-4)

    # Empty / short series fails safe
    fit_empty = regressor.fit([])
    assert fit_empty["slope"] == 0.0

    predictor = MLPredictor(_regressor=regressor)
    # 20 ascending prices -> UP prediction
    up_prices = [2400.0 + i * 0.2 for i in range(20)]
    pred_up = predictor.predict(up_prices)
    assert pred_up["direction"] == "UP"
    assert pred_up["confidence"] >= 60

    # 20 descending prices -> DOWN prediction
    down_prices = [2400.0 - i * 0.2 for i in range(20)]
    pred_down = predictor.predict(down_prices)
    assert pred_down["direction"] == "DOWN"
    assert pred_down["confidence"] >= 60


# ── Test 10: Wave 14 AutoTuner & Escape Launch Process Flags ──────────────────
def test_wave14_and_escape_launch_flags():
    """Verify AutoTuner statistics and Windows CREATE_BREAKAWAY_FROM_JOB flags."""
    # Test AutoTuner helpers
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _mean(data) == 30.0
    assert _std(data) > 0.0
    assert _percentile(data, 50) == 30.0
    assert _percentile([], 50) == 0.0

    # Test escape_launch flags
    breakaway_flags = get_breakaway_flags()
    assert (breakaway_flags & CREATE_BREAKAWAY_FROM_JOB) == CREATE_BREAKAWAY_FROM_JOB

    fallback_flags = get_fallback_flags()
    assert (fallback_flags & CREATE_BREAKAWAY_FROM_JOB) == 0
