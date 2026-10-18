"""
Wave 33: Partial Close Manager
When a position is 50% toward its TP, close half the lot to lock partial profit.
Tracks which tickets have been partially closed to avoid double-firing.
"""

import logging
import time
import math
import threading
from typing import Any, Tuple, Optional

logger = logging.getLogger(__name__)

_PARTIAL_TRIGGER_PCT = 0.50   # Fire when 50% of TP distance is covered
_PARTIAL_CLOSE_RATIO = 0.50   # Close 50% of the lot


class PartialCloseManager:
    """
    Monitors open positions and signals when a partial close should occur.
    The main trader loop calls `check_position()` each tick for each open position.
    If the position has moved >= 50% to TP and hasn't been partially closed yet,
    `check_position()` returns True so the caller can execute the partial close.
    Thread-safe with RLock and broker lot quantization.
    """

    def __init__(
        self,
        trigger_pct: float = _PARTIAL_TRIGGER_PCT,
        close_ratio: float = _PARTIAL_CLOSE_RATIO,
    ):
        try:
            if isinstance(trigger_pct, bool):
                self.trigger_pct = _PARTIAL_TRIGGER_PCT
            else:
                tp = float(trigger_pct)
                self.trigger_pct = max(0.10, min(0.90, tp)) if math.isfinite(tp) else _PARTIAL_TRIGGER_PCT
        except (ValueError, TypeError):
            self.trigger_pct = _PARTIAL_TRIGGER_PCT

        try:
            if isinstance(close_ratio, bool):
                self.close_ratio = _PARTIAL_CLOSE_RATIO
            else:
                cr = float(close_ratio)
                self.close_ratio = max(0.10, min(0.90, cr)) if math.isfinite(cr) else _PARTIAL_CLOSE_RATIO
        except (ValueError, TypeError):
            self.close_ratio = _PARTIAL_CLOSE_RATIO

        self._closed_tickets: set = set()   # tickets already partially closed
        self._total_partials = 0
        self._total_pips_locked = 0.0
        self._lock = threading.RLock()
        logger.info(
            f"[WAVE33] PartialCloseManager init: trigger={self.trigger_pct*100:.0f}% TP, "
            f"close_ratio={self.close_ratio*100:.0f}%"
        )

    def reset(self) -> None:
        """Thread-safe reset of tickets and statistics."""
        with self._lock:
            self._closed_tickets.clear()
            self._total_partials = 0
            self._total_pips_locked = 0.0

    def remove_ticket(self, ticket: Any) -> None:
        """Clean up closed position ticket from history."""
        if ticket is None:
            return
        with self._lock:
            self._closed_tickets.discard(ticket)

    def close_ticket(self, ticket: Any) -> None:
        """Alias for remove_ticket."""
        self.remove_ticket(ticket)

    def get_partial_lot(
        self,
        lot: Any,
        min_lot: float = 0.01,
        lot_step: float = 0.01,
    ) -> float:
        """Alias for get_close_lot matching Wave 33 API."""
        return self.get_close_lot(lot, min_lot=min_lot, lot_step=lot_step)

    def get_close_lot(
        self,
        lot: Any,
        min_lot: float = 0.01,
        lot_step: float = 0.01,
    ) -> float:
        """
        Quantizes partial close volume to broker step increments.
        Returns 0.0 if remaining volume cannot be split.
        """
        if lot is None or isinstance(lot, bool):
            return 0.0
        try:
            min_l = float(min_lot) if (min_lot is not None and not isinstance(min_lot, bool)) else 0.01
            step = float(lot_step) if (lot_step is not None and not isinstance(lot_step, bool)) else 0.01
            if min_l <= 0:
                min_l = 0.01
            if step <= 0:
                step = 0.01
            total_lot = float(lot)
            if not math.isfinite(total_lot) or total_lot < (min_l * 2):
                return 0.0

            raw_close = total_lot * self.close_ratio
            steps = math.floor((raw_close / step) + 1e-9)
            quantized = round(steps * step, 2)
            # Ensure at least min_lot remains open and at least min_lot is closed
            if quantized < min_l or (total_lot - quantized) < min_l:
                return min_l
            return quantized
        except (ValueError, TypeError):
            return 0.0

    # ─────────────────────────────────────────────────────────────
    def check_position(
        self,
        ticket: Any,
        direction: str,          # 'BUY' or 'SELL'
        entry_price: Any,
        current_price: Any,
        tp_price: Any,
        sl_price: Any = 0.0,
        lot: Any = 0.02,
    ) -> bool:
        """
        Returns True if a partial close should be executed NOW.
        Call once per tick per open position.

        Returns False if:
          - ticket is None or boolean
          - ticket already partially closed
          - lot too small to split (< 0.02)
          - position not yet at trigger threshold
        """
        if ticket is None or isinstance(ticket, bool):
            return False
        if entry_price is None or current_price is None or tp_price is None or lot is None:
            return False
        if isinstance(entry_price, bool) or isinstance(current_price, bool) or isinstance(tp_price, bool) or isinstance(lot, bool):
            return False

        try:
            ep = float(entry_price)
            cp = float(current_price)
            tp = float(tp_price)
            pos_lot = float(lot)
            if not (math.isfinite(ep) and math.isfinite(cp) and math.isfinite(tp) and math.isfinite(pos_lot)):
                return False
            if ep <= 0 or cp <= 0 or tp <= 0:
                return False
        except (ValueError, TypeError):
            return False

        sig = str(direction).strip().upper()
        if sig not in ("BUY", "SELL"):
            return False

        try:
            with self._lock:
                if ticket in self._closed_tickets:
                    return False
                if pos_lot < 0.02:
                    return False  # Can't split < 0.02 lot cleanly

                if sig == "BUY":
                    tp_dist = tp - ep
                    moved = cp - ep
                else:
                    tp_dist = ep - tp
                    moved = ep - cp

                if tp_dist <= 0:
                    return False

                progress = moved / tp_dist
                if progress >= self.trigger_pct:
                    pips_locked = moved  # pip equivalent
                    self._closed_tickets.add(ticket)
                    self._total_partials += 1
                    self._total_pips_locked += pips_locked
                    logger.info(
                        f"[WAVE33] Partial close triggered: ticket={ticket} dir={sig} "
                        f"progress={progress*100:.1f}% pips_locked~{pips_locked:.2f}"
                    )
                    return True
        except Exception as exc:
            logger.warning(f"[WAVE33] check_position error: {exc}")
        return False

    def is_entry_blocked(self) -> bool:
        """Unified risk interface check (always allows entry)."""
        return False

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def info(self) -> dict:
        with self._lock:
            return {
                "wave": 33,
                "name": "PartialCloseManager",
                "trigger_pct": self.trigger_pct,
                "close_ratio": self.close_ratio,
                "total_partials": self._total_partials,
                "total_pips_locked": round(self._total_pips_locked, 2),
                "active_closed_tickets_count": len(self._closed_tickets),
            }


# Module-level singleton
partial_close_manager = PartialCloseManager()


def is_entry_blocked() -> bool:
    """Module-level risk interface check."""
    return partial_close_manager.is_entry_blocked()


def is_blocked() -> bool:
    """Module-level alias for is_entry_blocked."""
    return partial_close_manager.is_blocked()


def check_position(
    ticket: Any,
    direction: str,
    entry_price: Any,
    current_price: Any,
    tp_price: Any,
    sl_price: Any = 0.0,
    lot: Any = 0.02,
) -> bool:
    """Module-level alias for check_position."""
    return partial_close_manager.check_position(
        ticket=ticket,
        direction=direction,
        entry_price=entry_price,
        current_price=current_price,
        tp_price=tp_price,
        sl_price=sl_price,
        lot=lot,
    )


def get_close_lot(
    lot: Any,
    min_lot: float = 0.01,
    lot_step: float = 0.01,
) -> float:
    """Module-level alias for get_close_lot."""
    return partial_close_manager.get_close_lot(lot=lot, min_lot=min_lot, lot_step=lot_step)

