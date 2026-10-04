"""
Wave 56: Consecutive Loss Guard
================================
Pauses all entry for 30 minutes after N consecutive losing trades.
Prevents revenge-trading spirals.

API:
    consecutive_loss_guard.record_trade(won: bool)
    consecutive_loss_guard.is_entry_blocked() -> bool
    consecutive_loss_guard.info() -> dict
"""

import time
import logging

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
_DEFAULT_PAUSE_SECONDS = 1800  # 30 minutes


class ConsecutiveLossGuard:
    """
    Tracks consecutive losing trades. After `max_losses` losses in a row,
    blocks new entries for `pause_seconds`.
    Resets on any winning trade or when the pause expires.
    """

    def __init__(self, max_losses: int = _DEFAULT_MAX_CONSECUTIVE_LOSSES,
                 pause_seconds: float = _DEFAULT_PAUSE_SECONDS):
        self.max_losses = max_losses
        self.pause_seconds = pause_seconds
        self._consecutive_losses: int = 0
        self._pause_until: float = 0.0  # epoch seconds
        self._total_pauses: int = 0

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def record_trade(self, won: bool) -> None:
        """Call at trade close. won=True for profit, False for loss."""
        try:
            if won:
                if self._consecutive_losses > 0:
                    logger.info(
                        "[WAVE56] Winning trade resets consecutive loss streak "
                        f"(was {self._consecutive_losses})"
                    )
                self._consecutive_losses = 0
            else:
                self._consecutive_losses += 1
                logger.info(
                    f"[WAVE56] Consecutive losses: {self._consecutive_losses}/{self.max_losses}"
                )
                if self._consecutive_losses >= self.max_losses:
                    self._pause_until = time.time() + self.pause_seconds
                    self._total_pauses += 1
                    mins = self.pause_seconds / 60
                    logger.warning(
                        f"[WAVE56] CONSECUTIVE LOSS GUARD: {self._consecutive_losses} losses in a row "
                        f"-> ENTRY BLOCKED for {mins:.0f} min"
                    )
        except Exception as exc:
            logger.debug(f"[WAVE56] record_trade error: {exc}")

    # ------------------------------------------------------------------
    # Gate API
    # ------------------------------------------------------------------

    def is_entry_blocked(self) -> bool:
        """Returns True if currently in cool-down period."""
        try:
            if time.time() < self._pause_until:
                remaining = self._pause_until - time.time()
                logger.debug(
                    f"[WAVE56] Entry blocked: {remaining:.0f}s remaining in cool-down"
                )
                return True
            # Pause expired — reset streak so it doesn't immediately re-trigger
            if self._pause_until > 0 and time.time() >= self._pause_until:
                self._consecutive_losses = 0
                self._pause_until = 0.0
            return False
        except Exception as exc:
            logger.debug(f"[WAVE56] is_entry_blocked error: {exc}")
            return False

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self) -> dict:
        try:
            remaining = max(0.0, self._pause_until - time.time())
            return {
                "wave": 56,
                "name": "ConsecutiveLossGuard",
                "consecutive_losses": self._consecutive_losses,
                "max_losses": self.max_losses,
                "paused": remaining > 0,
                "pause_remaining_sec": round(remaining, 1),
                "total_pauses": self._total_pauses,
            }
        except Exception:
            return {"wave": 56, "error": "info_failed"}


# Module-level singleton
consecutive_loss_guard = ConsecutiveLossGuard()
