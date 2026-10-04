"""
Wave 34: Trailing Stop Manager
Once a position is >= PROFIT_THRESHOLD_PIPS in profit,
trail the SL by TRAIL_PIPS behind the current price.
Returns new SL price each tick so the caller can update it.
"""

import logging
from threading import Lock

logger = logging.getLogger(__name__)

_PROFIT_TRIGGER_PIPS = 15.0   # Start trailing once 15 pips in profit
_TRAIL_PIPS = 10.0            # Keep SL 10 pips behind current best price


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
    ):
        self.profit_trigger_pips = profit_trigger_pips
        self.trail_pips = trail_pips
        self._best_prices: dict = {}    # ticket -> best price seen while trailing
        self._trailing_active: set = set()   # tickets with trailing active
        self._lock = Lock()
        self._total_trails = 0
        self._total_sl_moves = 0
        logger.info(
            f"[WAVE34] TrailingStopManager init: trigger={profit_trigger_pips}pips trail={trail_pips}pips"
        )

    # ─────────────────────────────────────────────────────────────
    def update(
        self,
        ticket: int,
        direction: str,       # 'BUY' or 'SELL'
        entry_price: float,
        current_price: float,
        current_sl: float,
    ) -> float | None:
        """
        Returns the new SL price if it should be moved, else None.
        Caller should only send the new SL to the broker if it's better
        (i.e., tighter than the old SL).
        """
        try:
            with self._lock:
                if direction == "BUY":
                    pips_profit = current_price - entry_price
                    if pips_profit < self.profit_trigger_pips:
                        return None  # Not profitable enough yet

                    # Start / continue trailing
                    if ticket not in self._trailing_active:
                        self._trailing_active.add(ticket)
                        self._best_prices[ticket] = current_price
                        self._total_trails += 1
                        logger.info(
                            f"[WAVE34] Trailing activated: ticket={ticket} dir=BUY "
                            f"profit={pips_profit:.2f}pips"
                        )

                    best = self._best_prices.get(ticket, current_price)
                    if current_price > best:
                        self._best_prices[ticket] = current_price
                        best = current_price

                    new_sl = best - self.trail_pips
                    if new_sl > current_sl:
                        self._total_sl_moves += 1
                        logger.debug(
                            f"[WAVE34] SL moved: ticket={ticket} {current_sl:.2f}->{new_sl:.2f}"
                        )
                        return new_sl

                elif direction == "SELL":
                    pips_profit = entry_price - current_price
                    if pips_profit < self.profit_trigger_pips:
                        return None

                    if ticket not in self._trailing_active:
                        self._trailing_active.add(ticket)
                        self._best_prices[ticket] = current_price
                        self._total_trails += 1
                        logger.info(
                            f"[WAVE34] Trailing activated: ticket={ticket} dir=SELL "
                            f"profit={pips_profit:.2f}pips"
                        )

                    best = self._best_prices.get(ticket, current_price)
                    if current_price < best:
                        self._best_prices[ticket] = current_price
                        best = current_price

                    new_sl = best + self.trail_pips
                    if new_sl < current_sl:
                        self._total_sl_moves += 1
                        logger.debug(
                            f"[WAVE34] SL moved: ticket={ticket} {current_sl:.2f}->{new_sl:.2f}"
                        )
                        return new_sl

        except Exception as exc:
            logger.debug(f"[WAVE34] update error: {exc}")
        return None

    # ─────────────────────────────────────────────────────────────
    def close_ticket(self, ticket: int) -> None:
        """Clean up when position is closed."""
        try:
            with self._lock:
                self._trailing_active.discard(ticket)
                self._best_prices.pop(ticket, None)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────
    def info(self) -> dict:
        """Return status dict for live_status.json."""
        try:
            with self._lock:
                return {
                    "profit_trigger_pips": self.profit_trigger_pips,
                    "trail_pips": self.trail_pips,
                    "currently_trailing": len(self._trailing_active),
                    "total_trails_activated": self._total_trails,
                    "total_sl_moves": self._total_sl_moves,
                }
        except Exception:
            return {}


# Module-level singleton
trailing_stop_manager = TrailingStopManager()
