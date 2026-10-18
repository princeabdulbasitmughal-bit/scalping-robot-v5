"""
tests/test_batch123.py
Unit tests for Batch 123:
- wave8_signal_optimizer.py (compute_atr, compute_stoch_rsi, find_sr_levels empty list safety, detect_pattern, score_signal, adaptive SL/TP, risk aliases)
- wave9_risk_manager.py (equity curve EMA tracking, drawdown guard, daily loss lot scaling, should_trade quarantine, risk aliases)
"""

import math
import unittest
from unittest.mock import patch, MagicMock

import wave8_signal_optimizer as w8
import wave9_risk_manager as w9


class TestBatch123(unittest.TestCase):

    def test_wave8_compute_atr(self):
        """Test compute_atr with empty, short, and realistic bar lists."""
        scorer = w8.SignalScorer()
        self.assertEqual(scorer.compute_atr([]), 1.0)
        self.assertEqual(scorer.compute_atr([{"close": 2400.0}]), 1.0)

        # 5 bars with 2-pip true range each
        bars = [
            {"high": 2402.0, "low": 2400.0, "close": 2401.0},
            {"high": 2403.0, "low": 2401.0, "close": 2402.0},
            {"high": 2404.0, "low": 2402.0, "close": 2403.0},
            {"high": 2405.0, "low": 2403.0, "close": 2404.0},
            {"high": 2406.0, "low": 2404.0, "close": 2405.0},
        ]
        atr = scorer.compute_atr(bars)
        self.assertAlmostEqual(atr, 2.0, places=1)

    def test_wave8_compute_stoch_rsi(self):
        """Test compute_stoch_rsi with insufficient closes and simulated trending closes."""
        scorer = w8.SignalScorer()
        self.assertEqual(scorer.compute_stoch_rsi([]), 50.0)
        self.assertEqual(scorer.compute_stoch_rsi([2400.0] * 5), 50.0)

        # 25 closes alternating with upward drift
        closes = [2400.0 + (i * 0.5 if i % 2 == 0 else -0.2) for i in range(25)]
        stoch = scorer.compute_stoch_rsi(closes)
        self.assertTrue(0.0 <= stoch <= 100.0)

    def test_wave8_find_sr_levels_hardened(self):
        """Test find_sr_levels handles empty lists without IndexError and computes S/R."""
        scorer = w8.SignalScorer()
        # Empty list should not raise IndexError
        self.assertEqual(scorer.find_sr_levels([]), (0.0, 0.0))
        self.assertEqual(scorer.find_sr_levels(None), (0.0, 0.0))

        # Short list (< window)
        s, r = scorer.find_sr_levels([2400.0, 2405.0], window=20)
        self.assertEqual(s, 2404.0)
        self.assertEqual(r, 2406.0)

        # Full 20-period list
        closes = [2400.0 + i for i in range(20)]
        support, resistance = scorer.find_sr_levels(closes, window=20)
        self.assertEqual(support, 2400.0)
        self.assertEqual(resistance, 2419.0)

    def test_wave8_detect_pattern(self):
        """Test candlestick pattern recognition (DOJI, HAMMER, BULL_ENGULF, NONE)."""
        scorer = w8.SignalScorer()
        self.assertEqual(scorer.detect_pattern([]), "NONE")

        # Doji: body < 10% of range
        doji_bars = [
            {"open": 2400.0, "close": 2401.0},
            {"open": 2401.0, "close": 2401.05, "high": 2403.0, "low": 2399.0}
        ]
        self.assertEqual(scorer.detect_pattern(doji_bars), "DOJI")

        # Bullish Engulfing: previous bear, current bull enveloping
        engulf_bars = [
            {"open": 2405.0, "close": 2400.0},
            {"open": 2398.0, "close": 2407.0, "high": 2408.0, "low": 2397.0}
        ]
        self.assertEqual(scorer.detect_pattern(engulf_bars), "BULL_ENGULF")

    def test_wave8_score_signal_and_adaptive_sl_tp(self):
        """Test score_signal boundaries and get_adaptive_sl_tp clamping."""
        scorer = w8.SignalScorer()
        closes = [2400.0 + i * 0.1 for i in range(30)]
        bars = [{"open": 2400.0, "high": 2402.0, "low": 2399.0, "close": 2401.0}] * 15

        # BUY signal score
        score = scorer.score_signal(
            signal="BUY",
            closes=closes,
            bars=bars,
            rsi=25.0,  # oversold -> boost
            bb_squeeze=True,
            market_regime="TRENDING_UP",
            ema_cross="BUY"
        )
        self.assertGreaterEqual(score, 60)
        self.assertLessEqual(score, 100)

        # HOLD returns 0
        self.assertEqual(scorer.score_signal("HOLD", closes, bars, 50.0, False, "RANGING", "NEUTRAL"), 0)

        # Adaptive SL/TP clamped to [15.0, 60.0]
        sl, tp = scorer.get_adaptive_sl_tp(bars, base_sl_pips=30.0, rr_ratio=1.5)
        self.assertGreaterEqual(sl, 15.0)
        self.assertLessEqual(sl, 60.0)
        self.assertAlmostEqual(tp, sl * 1.5, places=1)

    def test_wave8_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on SignalScorer and module level."""
        scorer = w8.SignalScorer()
        self.assertTrue(scorer.is_entry_blocked(40, threshold=55))
        self.assertTrue(scorer.is_blocked(40, threshold=55))
        self.assertFalse(scorer.is_entry_blocked(70, threshold=55))
        self.assertFalse(scorer.is_blocked(70, threshold=55))

        # Module level functions
        self.assertTrue(w8.is_entry_blocked(score=30, threshold=55))
        self.assertFalse(w8.is_entry_blocked(score=80, threshold=55))
        self.assertTrue(w8.is_blocked(score=30, threshold=55))

    def test_wave9_equity_curve_and_ema(self):
        """Test update_equity and equity_curve_ok EMA tracking."""
        rm = w9.RiskManager()
        # Seed 10 ticks of $10,000 equity
        for _ in range(10):
            rm.update_equity(10000.0)
        self.assertTrue(rm.equity_curve_ok(10000.0))

        # Equity sharply drops below EMA
        self.assertFalse(rm.equity_curve_ok(9500.0))

        # Defense against boolean and invalid equity
        rm.update_equity(True)
        rm.update_equity(-100.0)
        self.assertFalse(rm.equity_curve_ok(None))
        self.assertFalse(rm.equity_curve_ok(True))

    def test_wave9_drawdown_guard_and_daily_loss(self):
        """Test drawdown_pct calculation and lot scaling as loss accumulates."""
        rm = w9.RiskManager({"starting_balance": 10000.0})
        self.assertEqual(rm.drawdown_pct(10000.0), 0.0)
        self.assertEqual(rm.drawdown_pct(9500.0), 5.0)
        self.assertEqual(rm.drawdown_pct(9000.0), 10.0)

        # Lot scaling by daily loss
        lot_normal = rm.scale_lot_by_daily_pnl(0.10, daily_pnl=0.0)
        self.assertEqual(lot_normal, 0.10)

        # Daily loss scaling reduces lot
        lot_reduced = rm.scale_lot_by_daily_pnl(0.10, daily_pnl=-100.0)
        self.assertLess(lot_reduced, 0.10)

    def test_wave9_should_trade_quarantine(self):
        """Test should_trade halts when daily loss ceiling is breached."""
        rm = w9.RiskManager({"max_daily_loss_usd": 200.0})
        # Within loss bounds
        res_ok = rm.should_trade(balance=10000.0, equity=10000.0, daily_loss=50.0, open_positions=[], new_signal="BUY")
        self.assertTrue(res_ok["allowed"])

        # Loss exceeds $200
        res_halt = rm.should_trade(balance=9800.0, equity=9800.0, daily_loss=250.0, open_positions=[], new_signal="BUY")
        self.assertFalse(res_halt["allowed"])
        self.assertIn("daily loss limit", res_halt["reason"].lower())

    def test_wave9_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on RiskManager and module level."""
        rm = w9.RiskManager({"max_daily_loss_usd": 200.0})
        self.assertFalse(rm.is_entry_blocked(balance=10000.0, equity=10000.0, daily_loss=0.0))
        self.assertFalse(rm.is_blocked(balance=10000.0, equity=10000.0, daily_loss=0.0))

        # Blocked when daily loss breached
        self.assertTrue(rm.is_entry_blocked(balance=9700.0, equity=9700.0, daily_loss=250.0))
        self.assertTrue(rm.is_blocked(balance=9700.0, equity=9700.0, daily_loss=250.0))

        # Module level functions
        self.assertFalse(w9.is_entry_blocked(balance=10000.0, equity=10000.0, daily_loss=0.0))
        self.assertFalse(w9.is_blocked(balance=10000.0, equity=10000.0, daily_loss=0.0))


if __name__ == "__main__":
    unittest.main()
