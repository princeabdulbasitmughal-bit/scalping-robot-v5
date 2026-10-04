"""
Wave 46: LotRecoveryLadder
After 2 consecutive losses, scale the next trade lot by 1.5x (mild martingale).
Hard cap at max_lot. Resets to base_lot on any win.
"""

import logging

logger = logging.getLogger(__name__)

_DEFAULT_MAX_LOT = 0.10
_DEFAULT_MULTIPLIER = 1.5
_DEFAULT_CONSECUTIVE_TRIGGER = 2


class LotRecoveryLadder:
    """Mild martingale: scales lot after consecutive losses, capped at max_lot."""

    def __init__(self,
                 base_lot: float = 0.02,
                 max_lot: float = _DEFAULT_MAX_LOT,
                 multiplier: float = _DEFAULT_MULTIPLIER,
                 consecutive_trigger: int = _DEFAULT_CONSECUTIVE_TRIGGER):
        self._base_lot = base_lot
        self._max_lot = max_lot
        self._multiplier = multiplier
        self._trigger = consecutive_trigger
        self._consecutive_losses: int = 0
        self._current_lot: float = base_lot

    def record_trade(self, won: bool) -> None:
        """Call after each trade. won=True resets; False increments loss streak."""
        if won:
            self._consecutive_losses = 0
            self._current_lot = self._base_lot
            logger.info(f"[WAVE46] Win — lot reset to {self._base_lot}")
        else:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self._trigger:
                new_lot = min(
                    round(self._current_lot * self._multiplier, 2),
                    self._max_lot
                )
                logger.warning(
                    f"[WAVE46] {self._consecutive_losses} consecutive losses — "
                    f"lot scaled {self._current_lot} -> {new_lot} "
                    f"(cap={self._max_lot})"
                )
                self._current_lot = new_lot
            else:
                logger.info(
                    f"[WAVE46] Loss #{self._consecutive_losses} — "
                    f"below trigger ({self._trigger}), lot unchanged"
                )

    def get_lot(self, base_lot: float = None) -> float:
        """Return the current lot to use. If base_lot provided, recalibrate."""
        if base_lot is not None and base_lot != self._base_lot:
            # External lot override (e.g. Kelly sizing) — apply scale factor proportionally
            scale = self._current_lot / self._base_lot if self._base_lot > 0 else 1.0
            adjusted = min(round(base_lot * scale, 2), self._max_lot)
            return adjusted
        return self._current_lot

    def info(self) -> dict:
        return {
            "consecutive_losses": self._consecutive_losses,
            "current_lot": self._current_lot,
            "base_lot": self._base_lot,
            "max_lot": self._max_lot,
            "multiplier": self._multiplier,
            "trigger": self._trigger,
            "recovery_active": self._consecutive_losses >= self._trigger,
        }


# Module-level singleton
lot_recovery_ladder = LotRecoveryLadder()
