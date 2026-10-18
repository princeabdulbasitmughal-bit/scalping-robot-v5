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
import math
import threading

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
        self._recovery_wins = int(recovery_wins) if isinstance(recovery_wins, (int, float)) and not isinstance(recovery_wins, bool) and recovery_wins > 0 else 2

        self._consec_losses: int = 0
        self._consec_wins: int = 0
        self._total_reductions: int = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Reset streak counters and reductions to initial state."""
        with self._lock:
            self._consec_losses = 0
            self._consec_wins = 0
            self._total_reductions = 0

    def record_trade(self, won: bool) -> None:
        """Update streak counters after each closed trade."""
        is_win = bool(won)
        with self._lock:
            if is_win:
                self._consec_wins += 1
                if self._consec_wins >= self._recovery_wins:
                    # Full recovery
                    self._consec_losses = 0
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
        if lot is None or isinstance(lot, bool) or not isinstance(lot, (int, float)) or not math.isfinite(lot) or lot <= 0.0:
            return 0.0
        with self._lock:
            multiplier = self._get_multiplier()
            if multiplier >= 1.0:
                return float(lot)
            adjusted = round(max(float(lot) * multiplier, 0.01), 2)
            return adjusted

    def get_multiplier(self) -> float:
        """Return current lot multiplier (1.0 = no reduction)."""
        with self._lock:
            return self._get_multiplier()

    def is_entry_blocked(self) -> bool:
        """Unified risk interface check (returns True only if multiplier <= 0)."""
        with self._lock:
            return self._get_multiplier() <= 0.0

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def info(self) -> dict:
        """Return status dict for live_status.json and telemetry."""
        with self._lock:
            mult = self._get_multiplier()
            return {
                "consec_losses": self._consec_losses,
                "consec_wins": self._consec_wins,
                "lot_multiplier": round(mult, 2),
                "current_multiplier": mult,
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
                try:
                    clean_mult = float(mult)
                    if math.isfinite(clean_mult) and clean_mult > 0:
                        multiplier = clean_mult
                except Exception:
                    pass
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


def is_entry_blocked() -> bool:
    """Module-level risk interface check."""
    return drawdown_accelerator.is_entry_blocked()


def is_blocked() -> bool:
    """Module-level alias for is_entry_blocked."""
    return drawdown_accelerator.is_blocked()


def apply_lot(lot: float) -> float:
    """Module-level alias for apply_lot."""
    return drawdown_accelerator.apply_lot(lot=lot)


def get_multiplier() -> float:
    """Module-level alias for get_multiplier."""
    return drawdown_accelerator.get_multiplier()

