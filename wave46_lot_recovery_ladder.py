"""
Wave 46: LotRecoveryLadder (Hardened)
After consecutive losses (>= consecutive_trigger), scale the next trade lot
by multiplier (mild martingale) or step through discrete ladder tiers.
Hard bounded by [min_lot, max_lot] and max_recovery_steps.
Resets to base_lot on any win or reset().
"""

from __future__ import annotations
import logging
import math
import threading
from typing import Sequence

logger = logging.getLogger(__name__)

_DEFAULT_MIN_LOT = 0.01
_DEFAULT_BASE_LOT = 0.02
_DEFAULT_MAX_LOT = 0.10
_DEFAULT_MULTIPLIER = 1.5
_DEFAULT_CONSECUTIVE_TRIGGER = 2
_DEFAULT_MAX_STEPS = 5


class LotRecoveryLadder:
    """Mild martingale: scales lot after consecutive losses, capped at max_lot."""

    def __init__(self,
                 base_lot: float = _DEFAULT_BASE_LOT,
                 max_lot: float = _DEFAULT_MAX_LOT,
                 multiplier: float = _DEFAULT_MULTIPLIER,
                 consecutive_trigger: int = _DEFAULT_CONSECUTIVE_TRIGGER,
                 min_lot: float = _DEFAULT_MIN_LOT,
                 max_recovery_steps: int = _DEFAULT_MAX_STEPS,
                 ladder_steps: Sequence[float] | None = None):
        self._lock = threading.RLock()
        
        # Sanitize lot bounds
        self._min_lot = max(0.01, float(min_lot) if self._is_valid_num(min_lot) else _DEFAULT_MIN_LOT)
        raw_max = float(max_lot) if self._is_valid_num(max_lot) else _DEFAULT_MAX_LOT
        self._max_lot = max(self._min_lot, raw_max)
        
        raw_base = float(base_lot) if self._is_valid_num(base_lot) else _DEFAULT_BASE_LOT
        self._base_lot = self._clamp_lot(raw_base)
        
        self._multiplier = float(multiplier) if (self._is_valid_num(multiplier) and multiplier > 0) else _DEFAULT_MULTIPLIER
        self._trigger = max(1, int(consecutive_trigger) if isinstance(consecutive_trigger, (int, float)) else _DEFAULT_CONSECUTIVE_TRIGGER)
        self._max_steps = max(1, int(max_recovery_steps) if isinstance(max_recovery_steps, (int, float)) else _DEFAULT_MAX_STEPS)
        
        # Optional discrete ladder steps support
        if ladder_steps:
            self._ladder_steps = [self._clamp_lot(float(s)) for s in ladder_steps if self._is_valid_num(s) and s > 0]
        else:
            self._ladder_steps = None
            
        self._consecutive_losses: int = 0
        self._current_lot: float = self._base_lot

    @property
    def current_lot(self) -> float:
        """Current recovery lot size."""
        return self.get_lot()

    @staticmethod
    def _is_valid_num(val: any) -> bool:
        return not isinstance(val, bool) and isinstance(val, (int, float)) and math.isfinite(val)

    def _clamp_lot(self, lot: float) -> float:
        """Clamp lot strictly within [min_lot, max_lot] with 2 decimal precision."""
        if not self._is_valid_num(lot):
            return self._base_lot
        rounded = round(float(lot), 2)
        return max(self._min_lot, min(rounded, self._max_lot))

    def reset(self) -> None:
        """Thread-safe state reset to base lot."""
        with self._lock:
            self._consecutive_losses = 0
            self._current_lot = self._base_lot
            logger.info(f"[WAVE46] Reset — lot restored to base {self._base_lot}")

    def record_trade(self, won: bool) -> None:
        """Call after each trade. won=True resets; False increments loss streak."""
        try:
            with self._lock:
                if won:
                    self._consecutive_losses = 0
                    self._current_lot = self._base_lot
                    logger.info(f"[WAVE46] Win — lot reset to {self._base_lot}")
                else:
                    self._consecutive_losses += 1
                    
                    if self._consecutive_losses >= self._trigger:
                        # Compute ladder step index with strict bounds clamp [0, max_steps - 1]
                        step_idx = self._consecutive_losses - self._trigger
                        clamped_step = max(0, min(step_idx, self._max_steps - 1))
                        
                        if self._ladder_steps and len(self._ladder_steps) > 0:
                            # Index out of range protection for discrete ladder tiers
                            clamped_tier_idx = min(clamped_step, len(self._ladder_steps) - 1)
                            new_lot = self._ladder_steps[clamped_tier_idx]
                        else:
                            # Continuous geometric multiplier
                            calc_lot = self._current_lot * self._multiplier
                            new_lot = self._clamp_lot(calc_lot)
                            # Ensure recovery never scales below base_lot
                            new_lot = max(self._base_lot, new_lot)
                            
                        logger.warning(
                            f"[WAVE46] {self._consecutive_losses} consecutive losses (step {clamped_step + 1}/{self._max_steps}) — "
                            f"lot scaled {self._current_lot} -> {new_lot} (cap={self._max_lot})"
                        )
                        self._current_lot = new_lot
                    else:
                        logger.info(
                            f"[WAVE46] Loss #{self._consecutive_losses} — "
                            f"below trigger ({self._trigger}), lot unchanged ({self._current_lot})"
                        )
        except Exception as exc:
            logger.debug(f"[WAVE46] record_trade error: {exc}")

    def get_lot(self, base_lot: float = None) -> float:
        """
        Return the current lot to use, strictly clamped between min_lot and max_lot.
        If base_lot is provided, proportionally recalibrate with finite & bounds checks.
        """
        try:
            with self._lock:
                if base_lot is not None:
                    # Validate finite positive float
                    if not self._is_valid_num(base_lot) or base_lot <= 0.0:
                        return self._current_lot
                    
                    if base_lot != self._base_lot:
                        scale = (self._current_lot / self._base_lot) if self._base_lot > 0 else 1.0
                        adjusted = round(float(base_lot) * scale, 2)
                        return self._clamp_lot(adjusted)
                        
                return self._clamp_lot(self._current_lot)
        except Exception as exc:
            logger.debug(f"[WAVE46] get_lot error: {exc}")
            return self._base_lot

    def info(self) -> dict:
        try:
            with self._lock:
                active = self._consecutive_losses >= self._trigger
                step = max(0, min(self._consecutive_losses - self._trigger + 1, self._max_steps)) if active else 0
                return {
                    "wave": 46,
                    "name": "LotRecoveryLadder",
                    "consecutive_losses": self._consecutive_losses,
                    "current_lot": self._current_lot,
                    "base_lot": self._base_lot,
                    "min_lot": self._min_lot,
                    "max_lot": self._max_lot,
                    "multiplier": self._multiplier,
                    "trigger": self._trigger,
                    "recovery_active": active,
                    "ladder_step": step,
                    "max_steps": self._max_steps,
                }
        except Exception:
            return {"wave": 46, "name": "LotRecoveryLadder", "error": "info_failed"}


# Module-level singleton
lot_recovery_ladder = LotRecoveryLadder()

# Module-level aliases for risk orchestrator integration
def get_lot(base_lot: float = None) -> float:
    return lot_recovery_ladder.get_lot(base_lot=base_lot)

def record_trade(won: bool) -> None:
    lot_recovery_ladder.record_trade(won)

def reset() -> None:
    lot_recovery_ladder.reset()
