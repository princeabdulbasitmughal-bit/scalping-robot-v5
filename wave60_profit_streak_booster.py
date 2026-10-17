"""
Wave 60: Profit Streak Booster
================================
Tracks the last N trades. If the last `streak_length` trades are ALL wins,
the bot enters "confidence mode" and temporarily raises the TP multiplier.
Resets on any losing trade.

API:
    profit_streak_booster.record_trade(won: bool)
    profit_streak_booster.get_tp_multiplier() -> float   (1.2 during streak, else 1.0)
    profit_streak_booster.adjust_tp(base_tp_pips: float) -> float
    profit_streak_booster.is_in_streak() -> bool
    profit_streak_booster.info() -> dict
"""

import math
import logging
import threading
from collections import deque
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_STREAK_LENGTH = 3
_DEFAULT_TP_MULTIPLIER = 1.2   # +20% TP during confidence mode


class ProfitStreakBooster:
    """
    Confidence-mode TP booster. After `streak_length` consecutive wins,
    applies a TP multiplier until the next loss.
    Thread-safe with RLock and bounded parameters.
    """

    def __init__(
        self,
        streak_length: int = _DEFAULT_STREAK_LENGTH,
        tp_multiplier: float = _DEFAULT_TP_MULTIPLIER,
    ):
        try:
            sl = int(streak_length)
            self.streak_length = max(1, sl)
        except (ValueError, TypeError):
            self.streak_length = _DEFAULT_STREAK_LENGTH

        try:
            mult = float(tp_multiplier)
            self.tp_multiplier = max(1.0, min(3.0, mult)) if math.isfinite(mult) else _DEFAULT_TP_MULTIPLIER
        except (ValueError, TypeError):
            self.tp_multiplier = _DEFAULT_TP_MULTIPLIER

        # Store last N results (True = win, False = loss)
        self._results: deque[bool] = deque(maxlen=self.streak_length)
        self._total_boosts: int = 0
        self._current_streak: int = 0
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of trade results and streak counters."""
        with self._lock:
            self._results.clear()
            self._total_boosts = 0
            self._current_streak = 0

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def record_trade(self, won: Any) -> None:
        """
        Call at trade close.
        Accepts boolean (True=win, False=loss) or numeric PnL (pnl > 0 = win).
        """
        if won is None:
            return

        is_win: bool
        if isinstance(won, bool):
            is_win = won
        elif isinstance(won, (int, float)):
            if not math.isfinite(won):
                return
            is_win = float(won) > 0.0
        else:
            return

        try:
            with self._lock:
                was_in_streak = len(self._results) >= self.streak_length and all(self._results)
                self._results.append(is_win)

                if is_win:
                    self._current_streak += 1
                else:
                    self._current_streak = 0

                now_in_streak = len(self._results) >= self.streak_length and all(self._results)

                if now_in_streak and not was_in_streak:
                    self._total_boosts += 1
                    logger.info(
                        f"[WAVE60] CONFIDENCE MODE ACTIVATED: {self.streak_length} "
                        f"consecutive wins -> TP x{self.tp_multiplier:.2f}"
                    )
                elif was_in_streak and not is_win:
                    logger.info("[WAVE60] Losing trade — confidence mode DEACTIVATED")
        except Exception as exc:
            logger.debug(f"[WAVE60] record_trade error: {exc}")

    # ------------------------------------------------------------------
    # Advisory API
    # ------------------------------------------------------------------

    def is_in_streak(self) -> bool:
        """True if the last `streak_length` trades are all wins."""
        try:
            with self._lock:
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
            with self._lock:
                in_streak = len(self._results) >= self.streak_length and all(self._results)
                if in_streak:
                    return round(self.tp_multiplier, 2)
                return 1.0
        except Exception:
            return 1.0

    def adjust_tp(self, base_tp_pips: Any) -> float:
        """Apply current streak multiplier to base TP pips."""
        if base_tp_pips is None or isinstance(base_tp_pips, bool):
            return 0.0
        try:
            tp = float(base_tp_pips)
            if not math.isfinite(tp) or tp <= 0:
                return 0.0
        except (ValueError, TypeError):
            return 0.0

        multiplier = self.get_tp_multiplier()
        return round(tp * multiplier, 2)

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self) -> dict:
        try:
            with self._lock:
                in_streak = len(self._results) >= self.streak_length and all(self._results)
                return {
                    "wave": 60,
                    "name": "ProfitStreakBooster",
                    "in_confidence_mode": in_streak,
                    "tp_multiplier": round(self.tp_multiplier, 2) if in_streak else 1.0,
                    "streak_length_target": self.streak_length,
                    "current_consecutive_wins": self._current_streak,
                    "recent_trades_count": len(self._results),
                    "total_boost_activations": self._total_boosts,
                }
        except Exception:
            return {"wave": 60, "name": "ProfitStreakBooster", "error": "info_failed"}


# Module-level singleton
profit_streak_booster = ProfitStreakBooster()
