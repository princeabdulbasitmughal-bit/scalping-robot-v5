"""
tests/test_batch124.py
Unit tests for Batch 124:
- wave10_session_optimizer.py (weekend filter, Friday close, Monday gap, London-NY overlap, adjusted targets, risk aliases)
- wave11_profit_optimizer.py (win/loss streak tracking, lot modifiers, floating PnL reversal guard, daily target scaling, session stats, risk aliases)
"""

import math
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import wave10_session_optimizer as w10
import wave11_profit_optimizer as w11


class TestBatch124(unittest.TestCase):

    def test_wave10_session_weekend_filter(self):
        """Test get_current_session_info returns CLOSED and untradeable on weekends."""
        opt = w10.SessionOptimizer()
        # Saturday: 2026-10-17 12:00:00 UTC
        sat = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
        info = opt.get_current_session_info(sat)
        self.assertEqual(info["session"], "CLOSED")
        self.assertFalse(info["tradeable"])
        self.assertEqual(info["reason"], "WEEKEND")

    def test_wave10_session_friday_close_filter(self):
        """Test Friday afternoon filter after 19:00 UTC halts new entries."""
        opt = w10.SessionOptimizer()
        # Friday: 2026-10-16 19:30:00 UTC
        fri_afternoon = datetime(2026, 10, 16, 19, 30, 0, tzinfo=timezone.utc)
        info = opt.get_current_session_info(fri_afternoon)
        self.assertEqual(info["session"], "FRIDAY_CLOSE")
        self.assertFalse(info["tradeable"])
        self.assertEqual(info["reason"], "FRIDAY_AFTERNOON")

    def test_wave10_session_monday_gap_filter(self):
        """Test Monday morning filter before 08:00 UTC protects against gap risk."""
        opt = w10.SessionOptimizer()
        # Monday: 2026-10-19 04:00:00 UTC
        mon_morning = datetime(2026, 10, 19, 4, 0, 0, tzinfo=timezone.utc)
        info = opt.get_current_session_info(mon_morning)
        self.assertEqual(info["session"], "MONDAY_OPEN")
        self.assertFalse(info["tradeable"])
        self.assertEqual(info["reason"], "MONDAY_MORNING_GAP")

    def test_wave10_session_overlap_peak(self):
        """Test London-NY overlap window identifies PREMIUM quality and 1.3x multiplier."""
        opt = w10.SessionOptimizer()
        # Wednesday: 2026-10-14 14:30:00 UTC
        wed_overlap = datetime(2026, 10, 14, 14, 30, 0, tzinfo=timezone.utc)
        info = opt.get_current_session_info(wed_overlap)
        self.assertEqual(info["session"], "OVERLAP")
        self.assertEqual(info["quality"], "PREMIUM")
        self.assertEqual(info["vol_index"], 10)
        self.assertTrue(info["tradeable"])
        self.assertEqual(info["pip_multiplier"], 1.3)

    def test_wave10_get_adjusted_targets(self):
        """Test get_adjusted_targets scales SL and TP by session multiplier."""
        opt = w10.SessionOptimizer()
        # London-NY Overlap (1.3x multiplier)
        wed_overlap = datetime(2026, 10, 14, 14, 30, 0, tzinfo=timezone.utc)
        sl, tp = opt.get_adjusted_targets(base_sl=30.0, base_tp=45.0, rr_ratio=1.5, now_dt=wed_overlap)
        self.assertEqual(sl, 39.0)  # 30 * 1.3 = 39.0
        self.assertAlmostEqual(tp, 39.0 * 1.5, places=1)

        # Non-finite and negative inputs fallback
        sl_fb, tp_fb = opt.get_adjusted_targets(base_sl=-10.0, base_tp=float("nan"), rr_ratio=-1.0, now_dt=wed_overlap)
        self.assertGreaterEqual(sl_fb, 15.0)
        self.assertGreaterEqual(tp_fb, 15.0)

    def test_wave10_risk_guard_aliases(self):
        """Test is_entry_blocked and is_blocked on SessionOptimizer and module level."""
        opt = w10.SessionOptimizer()
        sat = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(opt.is_entry_blocked(now_dt=sat))
        self.assertTrue(opt.is_blocked(now_dt=sat))

        wed_active = datetime(2026, 10, 14, 14, 30, 0, tzinfo=timezone.utc)
        self.assertFalse(opt.is_entry_blocked(now_dt=wed_active))
        self.assertFalse(opt.is_blocked(now_dt=wed_active))

        # Module-level functions
        self.assertTrue(w10.is_entry_blocked(now_dt=sat))
        self.assertFalse(w10.is_entry_blocked(now_dt=wed_active))
        self.assertTrue(w10.is_blocked(now_dt=sat))

    def test_wave11_streak_tracking_and_lot_modifiers(self):
        """Test win and loss streak accumulation and lot multiplier adjustments."""
        po = w11.ProfitOptimizer()
        self.assertEqual(po.streak_lot_modifier(), 1.0)
        self.assertFalse(po.is_recovery_mode())

        # 3 consecutive wins -> 1.1x bonus
        po.record_result(True)
        po.record_result(True)
        po.record_result(True)
        self.assertEqual(po.streak_lot_modifier(), 1.1)

        # Loss breaks win streak; 3 losses -> 0.5x recovery
        po.record_result(False)
        po.record_result(False)
        po.record_result(False)
        self.assertEqual(po.streak_lot_modifier(), 0.5)
        self.assertTrue(po.is_recovery_mode())

        # 5 losses -> ultra-conservative 0.10x
        po.record_result(False)
        po.record_result(False)
        self.assertEqual(po.streak_lot_modifier(), 0.10)

    def test_wave11_floating_pnl_reversal_guard(self):
        """Test peak floating PnL tracking and reversal threshold detection."""
        po = w11.ProfitOptimizer()
        ticket = "TICKET_9001"

        po.update_peak_float(ticket, 50.0)
        po.update_peak_float(ticket, 100.0)
        self.assertFalse(po.should_close_reversal(ticket, 80.0, threshold=0.5))

        # Reversal from $100 down to $40 is 60% reversal (>50%) -> close
        self.assertTrue(po.should_close_reversal(ticket, 40.0, threshold=0.5))

        # Invalid and non-finite values handled safely
        po.update_peak_float(ticket, float("nan"))
        self.assertFalse(po.should_close_reversal(ticket, float("nan")))

    def test_wave11_daily_target_lot_scale(self):
        """Test daily_target_lot_scale scaling down as daily profit target is reached."""
        po = w11.ProfitOptimizer()
        # 0% target hit
        self.assertEqual(po.daily_target_lot_scale(0.0, 200.0), 1.0)
        # 50% target hit -> 0.75
        self.assertEqual(po.daily_target_lot_scale(100.0, 200.0), 0.75)
        # 75% target hit -> 0.5
        self.assertEqual(po.daily_target_lot_scale(160.0, 200.0), 0.5)
        # Invalid inputs return default 1.0
        self.assertEqual(po.daily_target_lot_scale(None, 200.0), 1.0)
        self.assertEqual(po.daily_target_lot_scale(50.0, 0.0), 1.0)

    def test_wave11_session_stats_and_risk_aliases(self):
        """Test session stats summary, reset, and risk guard aliases."""
        po = w11.ProfitOptimizer()
        po.record_result(True)
        po.record_result(False)
        stats = po.session_stats()
        self.assertEqual(stats["win_rate"], 50.0)
        self.assertEqual(stats["sample_size"], 2)

        # Risk aliases
        self.assertFalse(po.is_entry_blocked())
        self.assertFalse(po.is_blocked())
        self.assertFalse(w11.is_entry_blocked())
        self.assertFalse(w11.is_blocked())

        # Reset cleans state
        po.reset()
        reset_stats = po.session_stats()
        self.assertEqual(reset_stats["win_rate"], 0.0)
        self.assertEqual(reset_stats["win_streak"], 0)


if __name__ == "__main__":
    unittest.main()
