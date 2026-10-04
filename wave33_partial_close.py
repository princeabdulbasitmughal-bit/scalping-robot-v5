"""
Wave 33: Partial Close Manager
When a position is 50% toward its TP, close half the lot to lock partial profit.
Tracks which tickets have been partially closed to avoid double-firing.
"""

import logging
import time
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_PARTIAL_TRIGGER_PCT = 0.50   # Fire when 50% of TP distance is covered
_PARTIAL_CLOSE_RATIO = 0.50   # Close 50% of the lot


class PartialCloseManager:
    """
    Monitors open positions and signals when a partial close should occur.
    The main trader loop calls `check_position()` each tick for each open position.
    If the position has moved >= 50% to TP and hasn't been partially closed yet,
    `check_position()` returns True so the caller can execute the partial close.
    """

    def __init__(
        self,
        trigger_pct: float = _PARTIAL_TRIGGER_PCT,
        close_ratio: float = _PARTIAL_CLOSE_RATIO,
    ):
        self.trigger_pct = trigger_pct
        self.close_ratio = close_ratio
        self._closed_tickets: set = set()   # tickets already partially closed
        self._lock = Lock()
        self._total_partials = 0
        self._total_pips_locked = 0.0
        logger.info(
            f"[WAVE33] PartialCloseManager init: trigger={trigger_pct*100:.0f}% TP, "
            f"close_ratio={close_ratio*100:.0f}%"
        )

    # ─────────────────────────────────────────────────────────────
    def check_position(
        self,
        ticket: Any,
        direction: str,          # 'BUY' or 'SELL'
        entry_price: float,
        current_price: float,
        tp_price: float,
        sl_price: float = 0.0,
        lot: float = 0.02,
    ) -> bool:
        """
        Returns True if a partial close should be executed NOW.
        Call once per tick per open position.

        Returns False if:
          - ticket already partially closed
          - lot too small to split (< 0.02)
          - position not yet at trigger threshold
        """
        try:
            with self._lock:
                if ticket in self._closed_tickets:
                    return False
                if lot < 0.02:
                    return False  # Can't split < 0.02 lot cleanly

                if direction == "BUY":
                    tp_dist = tp_price - entry_price
                    moved = current_price - entry_price
                else:
                    tp_dist = entry_price - tp_price
                    moved = entry_price - current_price

                if tp_dist <= 0:
                    return False

                progress = moved / tp_dist
                if progress >= self.trigger_pct:
                    pips_locked = moved  # pip equivalent
                    self._closed_tickets.add(ticket)
                    self._total_partials += 1
                    self._total_pips_locked += pips_locked
                    logger.info(
                        f"[WAVE33] Partial close triggered: ticket={ticket} dir={direction} "
                        f"progress={progress*100:.1f}% pips_locked~{pips_locked:.2f}"
                    )
                    return True
        except Exception as exc:
            logger.debug(f"[WAVE33] check_position error: {exc}")
        return False

    # ─────────────────────────────────────────────────────────────
    def get_partial_lot(self, lot: float) -> float:
        """Return lot size to close (half of position)."""
        partial = round(lot * self.close_ratio, 2)
        return max(0.01, partial)

    # ─────────────────────────────────────────────────────────────
    def reset_ticket(self, ticket: int) -> None:
        """Remove ticket from closed set (e.g., if partial close failed)."""
        try:
            with self._lock:
                self._closed_tickets.discard(ticket)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────
    def info(self) -> dict:
        """Return status dict for live_status.json."""
        try:
            with self._lock:
                return {
                    "trigger_pct": self.trigger_pct,
                    "close_ratio": self.close_ratio,
                    "total_partials_executed": self._total_partials,
                    "total_pips_locked_approx": round(self._total_pips_locked, 2),
                    "tracked_tickets": len(self._closed_tickets),
                }
        except Exception:
            return {}


# Module-level singleton
partial_close_manager = PartialCloseManager()
PartialClose = PartialCloseManager
