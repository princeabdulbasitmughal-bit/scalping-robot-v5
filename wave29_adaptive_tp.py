"""
Wave 29: Adaptive TP Adjuster
Dynamically scales the TP target based on recent price volatility (ATR proxy).
- Strong momentum (high ATR) -> extend TP by up to 1.5x
- Weak momentum (low ATR)   -> shrink TP by up to 0.7x
- Neutral zone              -> keep TP as configured
- Cold-start / Zero-ATR     -> neutral (1.0x) until buffer fills or volatility exists
"""

import math
import time
import threading
from collections import deque
from typing import Optional, Dict, Any


class AdaptiveTp:
    def __init__(
        self,
        window: int = 20,
        extend_ratio: float = 1.5,
        shrink_ratio: float = 0.7,
        atr_high_threshold: float = 0.15,
        atr_low_threshold: float = 0.04,
        min_tp_pips: float = 5.0,
    ) -> None:
        """
        window:              Number of recent ticks to compute ATR proxy.
        extend_ratio:        Multiply base TP by this when ATR is high.
        shrink_ratio:        Multiply base TP by this when ATR is low.
        atr_high_threshold:  Average range per tick considered "high volatility".
        atr_low_threshold:   Average range per tick considered "low volatility".
        min_tp_pips:         Absolute floor on adjusted TP (only applied if base >= floor).
        """
        self._window = max(2, int(window)) if isinstance(window, (int, float)) and not isinstance(window, bool) and math.isfinite(window) else 20
        self._extend_ratio = float(extend_ratio) if isinstance(extend_ratio, (int, float)) and not isinstance(extend_ratio, bool) and math.isfinite(extend_ratio) and extend_ratio > 0 else 1.5
        self._shrink_ratio = float(shrink_ratio) if isinstance(shrink_ratio, (int, float)) and not isinstance(shrink_ratio, bool) and math.isfinite(shrink_ratio) and shrink_ratio > 0 else 0.7
        self._atr_high = float(atr_high_threshold) if isinstance(atr_high_threshold, (int, float)) and not isinstance(atr_high_threshold, bool) and math.isfinite(atr_high_threshold) and atr_high_threshold > 0 else 0.15
        self._atr_low = float(atr_low_threshold) if isinstance(atr_low_threshold, (int, float)) and not isinstance(atr_low_threshold, bool) and math.isfinite(atr_low_threshold) and atr_low_threshold > 0 else 0.04
        self._min_tp_pips = float(min_tp_pips) if isinstance(min_tp_pips, (int, float)) and not isinstance(min_tp_pips, bool) and math.isfinite(min_tp_pips) and min_tp_pips >= 0 else 5.0

        self._prices: deque = deque(maxlen=self._window + 1)
        self._current_atr: float = 0.0
        self._last_multiplier: float = 1.0
        self._total_adjustments: int = 0
        self._created_at: float = time.time()
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of internal price buffers and telemetry."""
        with self._lock:
            self._prices.clear()
            self._current_atr = 0.0
            self._last_multiplier = 1.0
            self._total_adjustments = 0

    def update_price(self, price: float) -> None:
        """Feed latest tick price into the ATR buffer."""
        if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(price) or price <= 0:
            return
        with self._lock:
            self._prices.append(float(price))
            self._recalculate_atr()

    def _recalculate_atr(self) -> None:
        """Compute simple ATR proxy = mean of abs tick-to-tick ranges."""
        prices = list(self._prices)
        if len(prices) < 2:
            self._current_atr = 0.0
            return
        ranges = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        self._current_atr = sum(ranges) / len(ranges) if ranges else 0.0

    def get_tp_multiplier(self) -> float:
        """
        Returns a multiplier for the base TP pips.
        > 1.0 -> extend TP  |  < 1.0 -> shrink TP  |  1.0 -> unchanged

        Cold-start / Zero ATR guard: when buffer not yet filled or prices flat,
        return 1.0 (neutral) to avoid premature TP shrinkage.
        """
        with self._lock:
            if len(self._prices) < self._window or self._current_atr <= 0.0:
                mult = 1.0
            elif self._current_atr >= self._atr_high:
                mult = self._extend_ratio
            elif self._current_atr <= self._atr_low:
                mult = self._shrink_ratio
            else:
                mult = 1.0

            if mult != self._last_multiplier:
                self._total_adjustments += 1
            self._last_multiplier = mult
            return mult

    def calculate_reward_to_risk(self, tp_pips: float, sl_pips: float) -> float:
        """
        Safely computes Reward-to-Risk ratio (TP / SL).
        Guards against zero-division, negative values, and non-finite numbers.
        Returns 0.0 if SL <= 0 or inputs are invalid.
        """
        if (
            not isinstance(sl_pips, (int, float))
            or isinstance(sl_pips, bool)
            or not math.isfinite(sl_pips)
            or sl_pips <= 0
        ):
            return 0.0
        if (
            not isinstance(tp_pips, (int, float))
            or isinstance(tp_pips, bool)
            or not math.isfinite(tp_pips)
            or tp_pips <= 0
        ):
            return 0.0
        return round(float(tp_pips) / float(sl_pips), 2)

    def adjust_tp(
        self,
        base_tp_pips: float,
        sl_pips: Optional[float] = None,
        min_rr_ratio: Optional[float] = None,
    ) -> float:
        """
        Return adjusted TP pips.
        - Scales base TP by ATR multiplier.
        - Never shrinks below min_tp_pips if base_tp_pips was >= min_tp_pips.
        - Optionally ensures adjusted TP satisfies min_rr_ratio against sl_pips
          without zero-division risks.
        """
        if (
            base_tp_pips is None
            or isinstance(base_tp_pips, bool)
            or not isinstance(base_tp_pips, (int, float))
            or not math.isfinite(base_tp_pips)
            or base_tp_pips <= 0
        ):
            return base_tp_pips

        with self._lock:
            mult = self.get_tp_multiplier()
            adjusted = round(float(base_tp_pips) * mult, 1)

            # Enforce floor only when base_tp_pips is already at or above floor
            if self._min_tp_pips > 0 and base_tp_pips >= self._min_tp_pips:
                adjusted = max(adjusted, self._min_tp_pips)

            # Optional minimum Reward-to-Risk ratio constraint (Zero-Division Safe)
            if (
                sl_pips is not None
                and min_rr_ratio is not None
                and isinstance(sl_pips, (int, float))
                and not isinstance(sl_pips, bool)
                and math.isfinite(sl_pips)
                and sl_pips > 0
                and isinstance(min_rr_ratio, (int, float))
                and not isinstance(min_rr_ratio, bool)
                and math.isfinite(min_rr_ratio)
                and min_rr_ratio > 0
            ):
                min_tp_allowed = round(float(sl_pips) * float(min_rr_ratio), 1)
                adjusted = max(adjusted, min_tp_allowed)

            return adjusted

    def is_entry_blocked(self) -> bool:
        """Unified risk interface check (always allows entry)."""
        return False

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def info(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "wave": 29,
                "name": "AdaptiveTp",
                "current_atr": round(self._current_atr, 5),
                "tp_multiplier": round(self._last_multiplier, 3),
                "mode": (
                    "EXTEND" if self._last_multiplier > 1.0 else
                    "SHRINK" if self._last_multiplier < 1.0 else
                    "NEUTRAL"
                ),
                "total_adjustments": self._total_adjustments,
                "buffer_size": len(self._prices),
                "warmed_up": len(self._prices) >= self._window,
                "atr_high_threshold": self._atr_high,
                "atr_low_threshold": self._atr_low,
                "min_tp_pips": self._min_tp_pips,
            }


# Module-level singleton
adaptive_tp = AdaptiveTp(
    window=20,
    extend_ratio=1.5,
    shrink_ratio=0.7,
    atr_high_threshold=0.15,
    atr_low_threshold=0.04,
    min_tp_pips=5.0,
)


def is_entry_blocked() -> bool:
    """Module-level risk interface check."""
    return adaptive_tp.is_entry_blocked()


def is_blocked() -> bool:
    """Module-level alias for is_entry_blocked."""
    return adaptive_tp.is_blocked()


def adjust_tp(
    base_tp_pips: float,
    sl_pips: Optional[float] = None,
    min_rr_ratio: Optional[float] = None,
) -> float:
    """Module-level alias for adjust_tp."""
    return adaptive_tp.adjust_tp(
        base_tp_pips=base_tp_pips,
        sl_pips=sl_pips,
        min_rr_ratio=min_rr_ratio,
    )


def update_price(price: float) -> None:
    """Module-level alias for update_price."""
    return adaptive_tp.update_price(price=price)

