import pytest
import math
from wave32_gap_guard import GapGuard, gap_guard, is_entry_blocked as w32_is_entry_blocked, is_blocked as w32_is_blocked, is_trading_allowed as w32_is_trading_allowed, update_price as w32_update_price
from wave33_partial_close import PartialCloseManager, partial_close_manager, is_entry_blocked as w33_is_entry_blocked, is_blocked as w33_is_blocked, check_position as w33_check_position, get_close_lot as w33_get_close_lot


class TestBatch133:
    """Batch 133 Test Suite: wave32 Gap Guard & wave33 Partial Close Manager."""

    def test_wave32_risk_guard_aliases(self):
        gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=60.0, pip_size=0.1)
        assert gg.is_blocked() is False
        assert gg.is_entry_blocked() is False

        # Feed normal moves
        gg.update_price(2000.0, now_ts=1000.0)
        gg.update_price(2000.2, now_ts=1001.0)
        assert gg.is_blocked(now_ts=1001.0) is False

        # Large gap of 1.0 (10 pips > 5 pips)
        gg.update_price(2001.2, now_ts=1002.0)
        assert gg.is_blocked(now_ts=1003.0) is True
        assert gg.is_entry_blocked(now_ts=1003.0) is True

        # Module-level aliases
        gap_guard.reset()
        assert w32_is_blocked() is False
        assert w32_is_entry_blocked() is False
        allowed, _ = w32_is_trading_allowed()
        assert allowed is True

    def test_wave32_gap_detection_and_lockout(self):
        gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=60.0, pip_size=0.1)
        gg.update_price(2000.0, now_ts=1000.0)
        # Gap of 0.8 (8 pips > 5 pips threshold)
        gg.update_price(2000.8, now_ts=1005.0)
        allowed, reason = gg.is_trading_allowed(now_ts=1010.0)
        assert allowed is False
        assert "GAP_GUARD" in reason
        assert gg._total_gaps == 1
        assert gg._last_gap_pips == 8.0

    def test_wave32_lockout_expiry_and_reset(self):
        gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=60.0, pip_size=0.1)
        gg.update_price(2000.0, now_ts=1000.0)
        gg.update_price(2001.0, now_ts=1005.0)  # triggers 60s block until 1065.0
        assert gg.is_blocked(now_ts=1060.0) is True

        # Past expiry (t=1066.0)
        assert gg.is_blocked(now_ts=1066.0) is False
        allowed, _ = gg.is_trading_allowed(now_ts=1066.0)
        assert allowed is True

        # Reset
        gg.reset()
        assert gg._total_gaps == 0
        assert gg._last_price == 0.0
        assert gg._gap_detected_at == 0.0

    def test_wave32_invalid_prices_and_safe_type_handling(self):
        gg = GapGuard()
        gg.update_price(None)
        gg.update_price(True)
        gg.update_price("invalid")
        gg.update_price(-100.0)
        gg.update_price(0.0)
        gg.update_price(float('nan'))
        gg.update_price(float('inf'))
        assert gg._last_price == 0.0

    def test_wave32_info_telemetry(self):
        gg = GapGuard(block_duration_sec=60.0)
        gg.update_price(2000.0, now_ts=1000.0)
        gg.update_price(2002.0, now_ts=1005.0)
        info = gg.info(now_ts=1015.0)
        assert info["name"] == "GapGuard"
        assert info["is_blocked"] is True
        assert info["cooldown_remaining_sec"] == 50.0

    def test_wave33_risk_guard_aliases(self):
        pcm = PartialCloseManager()
        assert pcm.is_blocked() is False
        assert pcm.is_entry_blocked() is False

        # Module-level aliases
        partial_close_manager.reset()
        assert w33_is_blocked() is False
        assert w33_is_entry_blocked() is False

    def test_wave33_partial_close_trigger_buy(self):
        pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)
        # BUY: entry=2000.0, tp=2010.0 (dist=10.0)
        # At current_price=2004.0 (progress=40% < 50%) -> False
        assert pcm.check_position(ticket=101, direction="BUY", entry_price=2000.0, current_price=2004.0, tp_price=2010.0, lot=0.04) is False

        # At current_price=2005.0 (progress=50%) -> True (triggers partial close)
        assert pcm.check_position(ticket=101, direction="BUY", entry_price=2000.0, current_price=2005.0, tp_price=2010.0, lot=0.04) is True
        assert pcm._total_partials == 1

        # Second check for same ticket -> False (already partially closed)
        assert pcm.check_position(ticket=101, direction="BUY", entry_price=2000.0, current_price=2006.0, tp_price=2010.0, lot=0.04) is False

    def test_wave33_partial_close_trigger_sell(self):
        pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)
        # SELL: entry=2000.0, tp=1990.0 (dist=10.0)
        # At current_price=1996.0 (moved 4.0, 40%) -> False
        assert pcm.check_position(ticket=202, direction="SELL", entry_price=2000.0, current_price=1996.0, tp_price=1990.0, lot=0.04) is False

        # At current_price=1995.0 (moved 5.0, 50%) -> True
        assert pcm.check_position(ticket=202, direction="SELL", entry_price=2000.0, current_price=1995.0, tp_price=1990.0, lot=0.04) is True
        assert 202 in pcm._closed_tickets

    def test_wave33_lot_quantization_and_minimums(self):
        pcm = PartialCloseManager(close_ratio=0.50)
        # Lot 0.04 -> close 0.02
        assert pcm.get_close_lot(0.04) == 0.02

        # Lot 0.05 -> close 0.02 (0.05 * 0.5 = 0.025, rounded to step 0.01)
        assert pcm.get_close_lot(0.05) == 0.02

        # Lot 0.01 cannot be split (would leave 0.005) -> returns 0.0
        assert pcm.get_close_lot(0.01) == 0.0

        # Invalid lots return 0.0
        assert pcm.get_close_lot(None) == 0.0
        assert pcm.get_close_lot(True) == 0.0
        assert pcm.get_close_lot(float('nan')) == 0.0

    def test_wave33_ticket_cleanup_and_reset(self):
        pcm = PartialCloseManager()
        pcm._closed_tickets.add(101)
        pcm._closed_tickets.add(102)
        assert len(pcm._closed_tickets) == 2

        # Remove single ticket
        pcm.remove_ticket(101)
        assert 101 not in pcm._closed_tickets
        assert 102 in pcm._closed_tickets

        # Reset clears all
        pcm.reset()
        assert len(pcm._closed_tickets) == 0
        assert pcm._total_partials == 0
