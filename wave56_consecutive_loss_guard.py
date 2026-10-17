"""
Wave 56: Consecutive Loss Guard
================================
Pauses all entry for 30 minutes after N consecutive losing trades.
Prevents revenge-trading spirals.

API:
    consecutive_loss_guard.record_trade(won: bool, now_ts: Optional[float] = None)
    consecutive_loss_guard.is_entry_blocked(now_ts: Optional[float] = None) -> bool
    consecutive_loss_guard.reset() -> None
    consecutive_loss_guard.info(now_ts: Optional[float] = None) -> dict
"""

import time
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
_DEFAULT_PAUSE_SECONDS = 1800.0  # 30 minutes


class ConsecutiveLossGuard:
    """
    Tracks consecutive losing trades. After `max_losses` losses in a row,
    blocks new entries for `pause_seconds`.
    Resets on any winning trade or when the pause expires.
    """

    def __init__(
        self,
        max_losses: int = _DEFAULT_MAX_CONSECUTIVE_LOSSES,
        pause_seconds: float = _DEFAULT_PAUSE_SECONDS,
    ):
        self.max_losses = max(1, int(max_losses)) if isinstance(max_losses, (int, float)) else _DEFAULT_MAX_CONSECUTIVE_LOSSES
        self.pause_seconds = max(0.0, float(pause_seconds)) if isinstance(pause_seconds, (int, float)) else _DEFAULT_PAUSE_SECONDS
        self._consecutive_losses: int = 0
        self._pause_until: float = 0.0  # epoch seconds
        self._total_pauses: int = 0
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of internal loss streak and pause state."""
        with self._lock:
            self._consecutive_losses = 0
            self._pause_until = 0.0
            self._total_pauses = 0

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def record_trade(self, won: bool, now_ts: Optional[float] = None) -> None:
        """Call at trade close. won=True for profit, False for loss."""
        try:
            current_time = float(now_ts) if now_ts is not None else time.time()
            with self._lock:
                # If pause just expired, reset streak before recording new trade
                if self._pause_until > 0 and current_time >= self._pause_until:
                    self._consecutive_losses = 0
                    self._pause_until = 0.0

                if bool(won):
                    if self._consecutive_losses > 0:
                        logger.info(
                            "[WAVE56] Winning trade resets consecutive loss streak "
                            f"(was {self._consecutive_losses})"
                        )
                    self._consecutive_losses = 0
                else:
                    # Only count loss if not currently in an active pause
                    if current_time >= self._pause_until:
                        self._consecutive_losses += 1
                        logger.info(
                            f"[WAVE56] Consecutive losses: {self._consecutive_losses}/{self.max_losses}"
                        )
                        if self._consecutive_losses >= self.max_losses:
                            self._pause_until = current_time + self.pause_seconds
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

    def is_entry_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Returns True if currently in cool-down period. Fails closed."""
        try:
            current_time = float(now_ts) if now_ts is not None else time.time()
            with self._lock:
                if current_time < self._pause_until:
                    remaining = self._pause_until - current_time
                    logger.debug(
                        f"[WAVE56] Entry blocked: {remaining:.0f}s remaining in cool-down"
                    )
                    return True
                # Pause expired — reset streak so it doesn't immediately re-trigger
                if self._pause_until > 0 and current_time >= self._pause_until:
                    self._consecutive_losses = 0
                    self._pause_until = 0.0
                return False
        except Exception as exc:
            logger.debug(f"[WAVE56] is_entry_blocked error: {exc}")
            return True  # Fail-closed

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self, now_ts: Optional[float] = None) -> dict:
        try:
            current_time = float(now_ts) if now_ts is not None else time.time()
            with self._lock:
                remaining = max(0.0, self._pause_until - current_time)
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
