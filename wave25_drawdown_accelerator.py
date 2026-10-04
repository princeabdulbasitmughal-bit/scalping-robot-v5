"""
Wave 25: Drawdown Accelerator
-----------------------------
Reduces lot size progressively when consecutive losses pile up.
- 3 consecutive losses  → lot × 0.50
- 5 consecutive losses  → lot × 0.25
- 7+ consecutive losses → lot × 0.10  (barely alive sizing)
Recovery: 2 consecutive wins reset back to full sizing.
This is complementary to Wave 22 (equity curve halt) which fully STOPS
trading; Wave 25 just REDUCES sizing so the robot stays in the game at
micro-size while losses continue.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class DrawdownAccelerator:
    """
    Progressive lot-size reducer based on consecutive loss streaks.

    Parameters
    ----------
    thresholds : list[tuple[int, float]]
        List of (min_consecutive_losses, lot_multiplier) sorted ascending.
        Default: [(3, 0.50), (5, 0.25), (7, 0.10)]
    recovery_wins : int
        Consecutive wins needed to fully reset multiplier. Default: 2.
    """

    _DEFAULTS = [(3, 0.50), (5, 0.25), (7, 0.10)]

    def __init__(
        self,
        thresholds: list | None = None,
        recovery_wins: int = 2,
    ):
        self._thresholds: list[tuple[int, float]] = sorted(
            thresholds or self._DEFAULTS, key=lambda x: x[0]
        )
        self._recovery_wins = recovery_wins

        self._consec_losses: int = 0
        self._consec_wins: int = 0
        self._total_reductions: int = 0

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #

    def record_trade(self, won: bool) -> None:
        """Update streak counters after each closed trade."""
        if won:
            self._consec_wins += 1
            self._consec_losses = 0
            if self._consec_wins >= self._recovery_wins:
                # Full recovery
                self._consec_wins = 0
                logger.info(
                    "[WAVE25] %d consecutive wins → lot multiplier RESET to 1.0",
                    self._recovery_wins,
                )
        else:
            self._consec_losses += 1
            self._consec_wins = 0
            multiplier = self._get_multiplier()
            if multiplier < 1.0:
                self._total_reductions += 1
                logger.warning(
                    "[WAVE25] Consecutive losses=%d → lot multiplier=%.2f",
                    self._consec_losses,
                    multiplier,
                )

    def apply_lot(self, lot: float) -> float:
        """Return the adjusted lot size based on current streak."""
        multiplier = self._get_multiplier()
        if multiplier >= 1.0:
            return lot
        adjusted = round(max(lot * multiplier, 0.01), 2)
        return adjusted

    def get_multiplier(self) -> float:
        """Return current lot multiplier (1.0 = no reduction)."""
        return self._get_multiplier()

    def info(self) -> dict:
        """Return status dict for live_status.json."""
        return {
            "consec_losses": self._consec_losses,
            "consec_wins": self._consec_wins,
            "lot_multiplier": round(self._get_multiplier(), 2),
            "total_reductions": self._total_reductions,
            "mode": self._mode_label(),
        }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_multiplier(self) -> float:
        multiplier = 1.0
        for min_losses, mult in self._thresholds:
            if self._consec_losses >= min_losses:
                multiplier = mult
        return multiplier

    def _mode_label(self) -> str:
        m = self._get_multiplier()
        if m >= 1.0:
            return "FULL_SIZE"
        if m >= 0.45:
            return "HALF_SIZE"
        if m >= 0.20:
            return "QUARTER_SIZE"
        return "MICRO_SIZE"


# Module-level singleton
drawdown_accelerator = DrawdownAccelerator()
