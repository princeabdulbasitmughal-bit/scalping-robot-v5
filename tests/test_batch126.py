"""
tests/test_batch126.py
Unit tests for Batch 126:
- wave14_auto_tuner.py (statistical helpers _mean/_std/_percentile, trade history analysis, suggestions, dry-run safety, risk aliases)
- wave19_volatility_tpsl.py (ATR calculation, high-vol TP widening, low-vol TP/SL tightening, boundary clamping, risk aliases)
"""

import math
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import wave14_auto_tuner as w14
import wave19_volatility_tpsl as w19


class TestBatch126(unittest.TestCase):

    def test_wave14_tuner_helpers(self):
        """Test _mean, _std, and _percentile statistical helpers with clean and invalid inputs."""
        # Clean inputs
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertEqual(w14._mean(vals), 30.0)
        self.assertAlmostEqual(w14._std(vals), 15.81, places=2)
        self.assertEqual(w14._percentile(vals, 50.0), 30.0)
        self.assertEqual(w14._percentile(vals, 0.0), 10.0)
        self.assertEqual(w14._percentile(vals, 100.0), 50.0)

        # Empty and non-finite defense
        self.assertEqual(w14._mean([]), 0.0)
        self.assertEqual(w14._std([]), 0.0)
        self.assertEqual(w14._percentile([], 50.0), 0.0)
        self.assertEqual(w14._mean([float("nan"), True, None]), 0.0)

    def test_wave14_tuner_analyse_insufficient_trades(self):
        """Test AutoTuner.analyse with fewer than MIN_TRADES."""
        tuner = w14.AutoTuner()
        short_history = [{"pnl": 10.0}, {"pnl": -5.0}]
        report = tuner.analyse(short_history)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertFalse(report["config_changed"])

    def test_wave14_tuner_analyse_low_win_rate_and_loss_streak(self):
        """Test AutoTuner.analyse identifies low win rate and generates suggestions."""
        tuner = w14.AutoTuner()
        # 12 trades: 3 wins, 9 losses (25% win rate)
        trades = []
        for i in range(12):
            if i % 4 == 0:
                trades.append({"pnl": 20.0, "mae_pips": 10.0, "mfe_pips": 30.0, "exit_reason": "TP_HIT", "duration_sec": 120})
            else:
                trades.append({"pnl": -15.0, "mae_pips": 25.0, "mfe_pips": 5.0, "exit_reason": "SL_HIT", "duration_sec": 60})

        report = tuner.analyse(trades)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["trades_analysed"], 12)
        self.assertLess(report["win_rate_pct"], 45.0)
        self.assertTrue(report["config_changed"])
        self.assertGreater(len(report["suggestions"]), 0)
        self.assertIn("proposed_config", report)

    def test_wave14_tuner_dry_run(self):
        """Test analyse_and_tune does not write to config.json when dry_run=True."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_file = Path(tmp_dir) / "config.json"
            tuner = w14.AutoTuner(config_path=str(cfg_file))
            trades = [{"pnl": -10.0, "mae_pips": 20.0, "mfe_pips": 5.0, "exit_reason": "SL_HIT", "duration_sec": 60}] * 12

            report = tuner.analyse_and_tune(trades, balance=10000.0, dry_run=True)
            self.assertTrue(report["config_changed"])
            # In dry_run, file should not have been created
            self.assertFalse(cfg_file.exists())

    def test_wave14_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on AutoTuner and module level."""
        tuner = w14.AutoTuner()
        self.assertFalse(tuner.is_entry_blocked())
        self.assertFalse(tuner.is_blocked())
        self.assertFalse(w14.is_entry_blocked())
        self.assertFalse(w14.is_blocked())

    def test_wave19_volatility_tpsl_calc_atr(self):
        """Test _calc_atr with empty, short, and realistic close series."""
        adj = w19.VolatilityTPSLAdjuster()
        self.assertEqual(adj._calc_atr([]), 0.5)
        self.assertEqual(adj._calc_atr([2400.0]), 0.5)

        # Constant step diff = 1.0
        closes = [2400.0 + i * 1.0 for i in range(20)]
        atr = adj._calc_atr(closes)
        self.assertAlmostEqual(atr, 1.0, places=2)

    def test_wave19_volatility_tpsl_high_vol_widens_tp(self):
        """Test high-volatility session widens TP up to 1.5x."""
        adj = w19.VolatilityTPSLAdjuster()
        # High vol ATR (step = 2.0 pips) and high vol index session
        closes_high = [2400.0 + (i * 2.0 if i % 2 == 0 else -1.0) for i in range(20)]
        session_high = {"vol_index": 2.0}

        tp, sl = adj.adjusted_tpsl(closes_high, base_tp_pips=40.0, base_sl_pips=25.0, session_info=session_high)
        self.assertGreater(tp, 40.0)
        self.assertEqual(sl, 25.0)  # SL remains firm in high-vol

    def test_wave19_volatility_tpsl_low_vol_tightens(self):
        """Test low-volatility dead zone tightens both TP and SL."""
        adj = w19.VolatilityTPSLAdjuster()
        # Flat prices (low ATR) and low vol index session
        closes_low = [2400.0 + i * 0.05 for i in range(20)]
        session_low = {"vol_index": 0.2}

        tp, sl = adj.adjusted_tpsl(closes_low, base_tp_pips=40.0, base_sl_pips=30.0, session_info=session_low)
        self.assertEqual(tp, 30.0)  # 40 * 0.75 = 30.0
        self.assertEqual(sl, 25.5)  # 30 * 0.85 = 25.5

    def test_wave19_volatility_tpsl_clamping_and_fallbacks(self):
        """Test boundary clamping [min, max] and non-finite argument handling."""
        adj = w19.VolatilityTPSLAdjuster(min_tp_pips=20.0, max_tp_pips=100.0, min_sl_pips=15.0, max_sl_pips=50.0)
        
        # Base values beyond limits
        tp_hi, sl_hi = adj.adjusted_tpsl([], base_tp_pips=200.0, base_sl_pips=90.0)
        self.assertEqual(tp_hi, 100.0)
        self.assertEqual(sl_hi, 50.0)

        # Non-finite and negative inputs fallback
        tp_fb, sl_fb = adj.adjusted_tpsl([], base_tp_pips=float("nan"), base_sl_pips=-5.0)
        self.assertGreaterEqual(tp_fb, 20.0)
        self.assertGreaterEqual(sl_fb, 15.0)

    def test_wave19_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on VolatilityTPSLAdjuster and module level."""
        adj = w19.VolatilityTPSLAdjuster()
        self.assertFalse(adj.is_entry_blocked())
        self.assertFalse(adj.is_blocked())
        self.assertFalse(w19.is_entry_blocked())
        self.assertFalse(w19.is_blocked())


if __name__ == "__main__":
    unittest.main()
