"""
Wave 34: Trailing Stop Manager
Once a position is >= PROFIT_THRESHOLD_PIPS in profit,
trail the SL by TRAIL_PIPS behind the current price in TRAIL_STEP_PIPS steps.
Returns new SL price each tick so the caller can update it.
"""

import math
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_PROFIT_TRIGGER_PIPS = 15.0   # Start trailing once 15 pips in profit
_TRAIL_PIPS = 10.0            # Keep SL 10 pips behind current best price
_TRAIL_STEP_PIPS = 1.0        # Minimum step distance in pips before moving SL


def _is_valid_num(val: Any) -> bool:
    """Return True if val is a finite real number (int or float, not bool)."""
    return not isinstance(val, bool) and isinstance(val, (int, float)) and math.isfinite(val)


class TrailingStopManager:
    """
    Manages trailing stop logic per ticket.
    Call `update(ticket, ...)` each tick for each open position.
    Returns new SL price if it should be moved, else None.
    """

    def __init__(
        self,
        profit_trigger_pips: float = _PROFIT_TRIGGER_PIPS,
        trail_pips: float = _TRAIL_PIPS,
        trail_step_pips: float = _TRAIL_STEP_PIPS,
    ):
        self.profit_trigger_pips = float(profit_trigger_pips) if _is_valid_num(profit_trigger_pips) and profit_trigger_pips >= 0 else _PROFIT_TRIGGER_PIPS
        self.trail_pips = float(trail_pips) if _is_valid_num(trail_pips) and trail_pips >= 0 else _TRAIL_PIPS
        self.trail_step_pips = float(trail_step_pips) if _is_valid_num(trail_step_pips) and trail_step_pips >= 0 else _TRAIL_STEP_PIPS
        self._best_prices: dict[Any, float] = {}    # ticket -> best price seen while trailing
        self._trailing_active: set[Any] = set()    # tickets with trailing active
        self._lock = threading.RLock()
        self._total_trails: int = 0
        self._total_sl_moves: int = 0
        logger.info(
            f"[WAVE34] TrailingStopManager init: trigger={self.profit_trigger_pips}pips "
            f"trail={self.trail_pips}pips step={self.trail_step_pips}pips"
        )

    # ─────────────────────────────────────────────────────────────
    def quantize_lot(
        self,
        lot: float,
        min_lot: float = 0.01,
        lot_step: float = 0.01,
        max_lot: float = 100.0,
    ) -> float:
        """
        Quantize lot size strictly to lot_step increments within [min_lot, max_lot].
        Prevents broker rejection from invalid volume steps or precision.
        """
        if not _is_valid_num(lot) or lot <= 0:
            return 0.0
        min_l = float(min_lot) if _is_valid_num(min_lot) and min_lot > 0 else 0.01
        step = float(lot_step) if _is_valid_num(lot_step) and lot_step > 0 else 0.01
        max_l = float(max_lot) if _is_valid_num(max_lot) and max_lot >= min_l else 100.0

        steps = math.floor((float(lot) / step) + 1e-9)
        quantized = round(steps * step, 4)
        clamped = max(min_l, min(quantized, max_l))
        return round(clamped, 2 if step >= 0.01 else 4)

    # ─────────────────────────────────────────────────────────────
    def quantize_price(
        self,
        price: float,
        pip_size: float = 0.1,
        digits: int | None = None,
    ) -> float:
        """Quantize price to symbol digits to eliminate IEEE-754 precision artifacts."""
        if not _is_valid_num(price):
            return 0.0
        if digits is None:
            if _is_valid_num(pip_size) and pip_size > 0:
                digits = max(0, int(math.ceil(-math.log10(pip_size) + 1e-9)) + 1)
            else:
                digits = 2
        return round(price, max(0, int(digits)))

    # ─────────────────────────────────────────────────────────────
    def update(
        self,
        ticket: Any,
        direction: str,       # 'BUY' or 'SELL'
        entry_price: float,
        current_price: float,
        current_sl: float,
        pip_size: float = 0.1,   # XAUUSD = 0.1; EURUSD = 0.0001
        trail_step_pips: float | None = None,
        digits: int | None = None,
    ) -> float | None:
        """
        Returns the new SL price if it should be moved, else None.
        Caller should only send the new SL to the broker if it's better
        (i.e., tighter than the old SL).
        pip_size: the value of 1 pip in price units (0.1 for XAUUSD, 0.0001 for EURUSD).
        """
        try:
            # 1. Input & finite number guards
            if not (_is_valid_num(entry_price) and _is_valid_num(current_price) and _is_valid_num(current_sl)):
                return None

            if not _is_valid_num(pip_size) or pip_size <= 0:
                pip_size = 0.1  # default XAUUSD

            dir_norm = str(direction).strip().upper()
            if dir_norm not in ("BUY", "SELL"):
                return None

            # Resolve step distance
            step_pips = trail_step_pips if (_is_valid_num(trail_step_pips) and trail_step_pips >= 0) else self.trail_step_pips
            trail_price = self.trail_pips * pip_size
            trigger_price = self.profit_trigger_pips * pip_size
            step_price = step_pips * pip_size

            with self._lock:
                if dir_norm == "BUY":
                    profit_dist = current_price - entry_price
                    if profit_dist < trigger_price:
                        return None  # Not profitable enough yet

                    # Start / continue trailing
                    if ticket not in self._trailing_active:
                        self._trailing_active.add(ticket)
                        self._best_prices[ticket] = current_price
                        self._total_trails += 1
                        logger.info(
                            f"[WAVE34] Trailing activated: ticket={ticket} dir=BUY "
                            f"profit={profit_dist/pip_size:.1f}pips"
                        )

                    best = self._best_prices.get(ticket, current_price)
                    if current_price > best:
                        self._best_prices[ticket] = current_price
                        best = current_price

                    raw_new_sl = best - trail_price
                    new_sl = self.quantize_price(raw_new_sl, pip_size=pip_size, digits=digits)

                    # Guard: Stop Loss for BUY cannot be at or above current market price
                    if new_sl >= current_price:
                        return None

                    # Step check: must improve SL by at least step_price
                    if current_sl <= 0.0 or (new_sl - current_sl >= step_price - 1e-9):
                        if new_sl > current_sl:
                            self._total_sl_moves += 1
                            logger.debug(
                                f"[WAVE34] SL moved: ticket={ticket} {current_sl:.5f}->{new_sl:.5f}"
                            )
                            return new_sl

                elif dir_norm == "SELL":
                    profit_dist = entry_price - current_price
                    if profit_dist < trigger_price:
                        return None

                    if ticket not in self._trailing_active:
                        self._trailing_active.add(ticket)
                        self._best_prices[ticket] = current_price
                        self._total_trails += 1
                        logger.info(
                            f"[WAVE34] Trailing activated: ticket={ticket} dir=SELL "
                            f"profit={profit_dist/pip_size:.1f}pips"
                        )

                    best = self._best_prices.get(ticket, current_price)
                    if current_price < best:
                        self._best_prices[ticket] = current_price
                        best = current_price

                    raw_new_sl = best + trail_price
                    new_sl = self.quantize_price(raw_new_sl, pip_size=pip_size, digits=digits)

                    # Guard: Stop Loss for SELL cannot be at or below current market price
                    if new_sl <= current_price:
                        return None

                    # Step check: for SELL, new SL is better when lower by at least step_price
                    if current_sl <= 0.0 or (current_sl - new_sl >= step_price - 1e-9):
                        if current_sl <= 0.0 or new_sl < current_sl:
                            self._total_sl_moves += 1
                            logger.debug(
                                f"[WAVE34] SL moved: ticket={ticket} {current_sl:.5f}->{new_sl:.5f}"
                            )
                            return new_sl

        except Exception as exc:
            logger.debug(f"[WAVE34] update error: {exc}")
        return None

    # ─────────────────────────────────────────────────────────────
    def close_ticket(self, ticket: Any) -> None:
        """Clean up when position is closed."""
        try:
            with self._lock:
                self._trailing_active.discard(ticket)
                self._best_prices.pop(ticket, None)
        except Exception as exc:
            logger.debug(f"[WAVE34] close_ticket error for {ticket}: {exc}")

    # ─────────────────────────────────────────────────────────────
    def reset(self) -> None:
        """Reset internal trailing stop state and telemetry."""
        with self._lock:
            self._best_prices.clear()
            self._trailing_active.clear()
            self._total_trails = 0
            self._total_sl_moves = 0

    # ─────────────────────────────────────────────────────────────
    def info(self) -> dict:
        """Return status dict for live_status.json."""
        try:
            with self._lock:
                return {
                    "wave": 34,
                    "name": "TrailingStopManager",
                    "profit_trigger_pips": self.profit_trigger_pips,
                    "trail_pips": self.trail_pips,
                    "trail_step_pips": self.trail_step_pips,
                    "currently_trailing": len(self._trailing_active),
                    "total_trails_activated": self._total_trails,
                    "total_sl_moves": self._total_sl_moves,
                }
        except Exception as exc:
            logger.warning(f"[WAVE34] info() error: {exc}")
            return {}


# Module-level singleton
trailing_stop_manager = TrailingStopManager()
