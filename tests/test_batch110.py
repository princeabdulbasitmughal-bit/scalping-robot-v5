"""
tests/test_batch110.py
======================
Unit tests for Batch 110:
- wave8_signal_optimizer.py (SignalScorer)
- wave9_risk_manager.py (RiskManager)
"""

import math
import pytest
from wave8_signal_optimizer import SignalScorer
from wave9_risk_manager import RiskManager


# =====================================================================
# SignalScorer Tests (wave8)
# =====================================================================

def test_signal_scorer_init_defaults():
    ss = SignalScorer()
    inf = ss.info()
    assert inf["wave"] == 8
    assert inf["name"] == "SignalOptimizer"
    assert inf["vol_proxy_len"] == 0
    assert inf["stoch_k_len"] == 0

    assert ss.is_entry_blocked(score=50, threshold=55) is True
    assert ss.is_entry_blocked(score=60, threshold=55) is False
    assert ss.is_blocked(score=60, threshold=55) is False

    ss.reset()
    assert ss.info()["vol_proxy_len"] == 0


def test_signal_scorer_compute_atr():
    ss = SignalScorer()
    # Empty or short bars fallback to 1.0
    assert ss.compute_atr([]) == 1.0
    assert ss.compute_atr([{"close": 100.0}]) == 1.0

    # Bars with high-low spread of 2.0
    bars = []
    p = 2650.0
    for i in range(15):
        bars.append({"open": p, "high": p + 1.0, "low": p - 1.0, "close": p})
        p += 0.5
    atr = ss.compute_atr(bars)
    assert 1.5 <= atr <= 2.5


def test_signal_scorer_compute_stoch_rsi():
    ss = SignalScorer()
    # Under 15 closes -> 50.0 fallback
    assert ss.compute_stoch_rsi([100.0 + i for i in range(10)]) == 50.0

    # 35 closes steadily rising -> valid stoch RSI
    closes = [100.0 + i * 0.5 for i in range(35)]
    stoch = ss.compute_stoch_rsi(closes)
    assert 0.0 <= stoch <= 100.0


def test_signal_scorer_detect_pattern():
    ss = SignalScorer()
    assert ss.detect_pattern([]) == "NONE"

    # DOJI: body < 10% of total range
    doji_bars = [
        {"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0},
        {"open": 100.0, "high": 105.0, "low": 95.0, "close": 100.05},
    ]
    assert ss.detect_pattern(doji_bars) == "DOJI"

    # HAMMER: bullish, small body at top, long lower wick
    hammer_bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"open": 98.0, "high": 100.2, "low": 90.0, "close": 100.0},
    ]
    assert ss.detect_pattern(hammer_bars) == "HAMMER"

    # BULLISH ENGULFING: previous bear, current bull engulfs previous body
    engulf_bars = [
        {"open": 100.0, "high": 101.0, "low": 97.0, "close": 98.0},
        {"open": 97.0, "high": 102.0, "low": 96.0, "close": 101.0},
    ]
    assert ss.detect_pattern(engulf_bars) == "BULL_ENGULF"


def test_signal_scorer_score_signal_and_trading_allowed():
    ss = SignalScorer()
    closes = [100.0 + i * 0.2 for i in range(35)]
    bars = [{"open": c - 0.1, "high": c + 0.5, "low": c - 0.5, "close": c} for c in closes]

    # HOLD signal scores 0
    assert ss.score_signal("HOLD", closes, bars, rsi=50.0, bb_squeeze=False, market_regime="RANGING", ema_cross="NEUTRAL") == 0

    # Strong BUY signal
    score_buy = ss.score_signal(
        signal="BUY",
        closes=closes,
        bars=bars,
        rsi=25.0,  # oversold bonus
        bb_squeeze=True,  # squeeze bonus
        market_regime="TRENDING_UP",  # trend bonus
        ema_cross="BUY",  # cross bonus
    )
    assert score_buy >= 60

    allowed, reason = ss.is_trading_allowed(score_buy, threshold=55)
    assert allowed is True
    assert reason == ""
    assert ss.is_entry_blocked(score_buy, threshold=55) is False


# =====================================================================
# RiskManager Tests (wave9)
# =====================================================================

def test_risk_manager_init_defaults():
    rm = RiskManager()
    assert rm.max_daily_loss_usd == 200.0
    assert rm.daily_profit_target == 200.0
    assert rm.max_drawdown_pct == 10.0
    assert rm.peak_balance == 10000.0
    assert rm.is_recovery_mode() is False

    inf = rm.info()
    assert inf["peak_balance"] == 10000.0
    assert inf["max_trades_per_hour"] == 20


def test_risk_manager_drawdown_and_lot_scale():
    rm = RiskManager(config={"starting_balance": 10000.0, "max_drawdown_pct": 10.0})

    # No drawdown
    assert rm.drawdown_pct(10000.0) == 0.0
    assert rm.drawdown_lot_scale(10000.0) == 1.0

    # 3% drawdown (balance 9,700) -> 0.75x
    assert rm.drawdown_pct(9700.0) == 3.0
    assert rm.drawdown_lot_scale(9700.0) == 0.75

    # 5% drawdown (balance 9,500) -> 0.50x
    assert rm.drawdown_pct(9500.0) == 5.0
    assert rm.drawdown_lot_scale(9500.0) == 0.50

    # 9% drawdown (balance 9,100) -> 0.10x
    assert rm.drawdown_pct(9100.0) == 9.0
    assert rm.drawdown_lot_scale(9100.0) == 0.10

    # 11% drawdown (balance 8,900 >= 10% limit) -> max dd hit!
    assert rm.is_max_drawdown_hit(8900.0) is True


def test_risk_manager_equity_curve_ok():
    rm = RiskManager(config={"starting_balance": 10000.0})

    # Under 5 ticks -> always ok (warmup)
    for eq in [10000.0, 10050.0, 10100.0, 10150.0]:
        rm.update_equity(eq)
        assert rm.equity_curve_ok(eq) is True

    # Feed steady climb to establish EMA ~10,500
    for eq in [10200.0, 10300.0, 10400.0, 10500.0, 10550.0, 10600.0]:
        rm.update_equity(eq)

    # Above EMA is ok
    assert rm.equity_curve_ok(10600.0) is True

    # Sudden collapse below EMA * 0.995
    assert rm.equity_curve_ok(9000.0) is False


def test_risk_manager_trade_frequency_and_correlation():
    rm = RiskManager(config={"max_trades_per_hour": 5})
    t0 = 1000.0

    # First 5 trades allowed
    for i in range(5):
        assert rm.can_trade_frequency(now_ts=t0 + i * 10) is True
        rm.record_trade(now_ts=t0 + i * 10)

    # 6th trade within hour is blocked
    assert rm.can_trade_frequency(now_ts=t0 + 100.0) is False

    # After 3600 seconds, older trades expire and trading is permitted
    assert rm.can_trade_frequency(now_ts=t0 + 3650.0) is True

    # Position correlation: don't stack 2 BUY positions
    open_positions = [{"ticket": 1, "type": "BUY"}]
    assert rm.correlation_ok(open_positions, new_signal="BUY") is False
    assert rm.correlation_ok(open_positions, new_signal="SELL") is True


def test_risk_manager_should_trade_composite_and_reset():
    rm = RiskManager(config={"starting_balance": 10000.0, "max_daily_loss_usd": 200.0})

    # Normal healthy conditions
    res = rm.should_trade(
        balance=10000.0,
        equity=10000.0,
        daily_pnl=20.0,
        daily_loss=0.0,
        open_positions=[],
        new_signal="BUY",
    )
    assert res["allowed"] is True
    assert res["reason"] == "OK"
    assert res["lot_scale"] >= 0.75
    assert rm.is_entry_blocked(balance=10000.0, equity=10000.0) is False

    # Daily loss limit reached ($220 >= $200)
    res_loss = rm.should_trade(
        balance=9780.0,
        equity=9780.0,
        daily_pnl=-220.0,
        daily_loss=220.0,
        open_positions=[],
        new_signal="BUY",
    )
    assert res_loss["allowed"] is False
    assert "Daily loss limit reached" in res_loss["reason"]

    # Invalid / boolean inputs fail closed
    assert rm.should_trade(balance=True, equity=10000.0, daily_pnl=0, daily_loss=0, open_positions=[], new_signal="BUY")["allowed"] is False
    assert rm.should_trade(balance=10000.0, equity=float("nan"), daily_pnl=0, daily_loss=0, open_positions=[], new_signal="BUY")["allowed"] is False

    # Reset
    rm.reset(starting_balance=10000.0)
    assert rm.peak_balance == 10000.0
    assert rm._equity_ema == 0.0
    assert len(rm._trade_times) == 0
