"""
Wave 60: Profit Streak Booster
================================
Tracks the last N trades. If the last `streak_length` trades are ALL wins,
the bot enters "confidence mode" and temporarily raises the TP multiplier.
Resets on any losing trade.

API:
    profit_streak_booster.record_trade(won: bool)
    profit_streak_booster.get_tp_multiplier() -> float   (1.2 during streak, else 1.0)
    profit_streak_booster.is_in_streak() -> bool
    profit_streak_booster.info() -> dict
"""

import logging
from collections import deque

logger = logging.getLogger(__name__)

_DEFAULT_STREAK_LENGTH = 3
_DEFAULT_TP_MULTIPLIER = 1.2   # +20% TP during confidence mode


class ProfitStreakBooster:
    """
    Confidence-mode TP booster. After `streak_length` consecutive wins,
    applies a TP multiplier until the next loss.
    """

    def __init__(self, streak_length: int = _DEFAULT_STREAK_LENGTH,
                 tp_multiplier: float = _DEFAULT_TP_MULTIPLIER):
        self.streak_length = streak_length
        self.tp_multiplier = tp_multiplier
        # Store last N results (True = win, False = loss)
        self._results: deque = deque(maxlen=streak_length)
        self._total_boosts: int = 0

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def record_trade(self, won: bool) -> None:
        """Call at trade close. won=True for profit, False for loss."""
        try:
            was_in_streak = self.is_in_streak()
            self._results.append(won)
            now_in_streak = self.is_in_streak()

            if now_in_streak and not was_in_streak:
                self._total_boosts += 1
                logger.info(
                    f"[WAVE60] CONFIDENCE MODE ACTIVATED: {self.streak_length} "
                    f"consecutive wins -> TP x{self.tp_multiplier:.1f}"
                )
            elif was_in_streak and not won:
                logger.info("[WAVE60] Losing trade — confidence mode DEACTIVATED")
        except Exception as exc:
            logger.debug(f"[WAVE60] record_trade error: {exc}")

    # ------------------------------------------------------------------
    # Advisory API
    # ------------------------------------------------------------------

    def is_in_streak(self) -> bool:
        """True if the last `streak_length` trades are all wins."""
        try:
            if len(self._results) < self.streak_length:
                return False
            return all(self._results)
        except Exception:
            return False

    def get_tp_multiplier(self) -> float:
        """
        Returns tp_multiplier (e.g. 1.2) during a winning streak,
        otherwise 1.0 (no boost).
        """
        try:
            if self.is_in_streak():
                logger.debug(
                    f"[WAVE60] TP boost active: x{self.tp_multiplier:.1f}"
                )
                return self.tp_multiplier
            return 1.0
        except Exception:
            return 1.0

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self) -> dict:
        try:
            return {
                "wave": 60,
                "name": "ProfitStreakBooster",
                "streak_length_required": self.streak_length,
                "recent_results": list(self._results),
                "in_confidence_mode": self.is_in_streak(),
                "tp_multiplier": self.get_tp_multiplier(),
                "total_boosts_activated": self._total_boosts,
            }
        except Exception:
            return {"wave": 60, "error": "info_failed"}


# Module-level singleton
profit_streak_booster = ProfitStreakBooster()
