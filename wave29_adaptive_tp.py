"""
Wave 29: Adaptive TP Adjuster
Dynamically scales the TP target based on recent price volatility (ATR proxy).
- Strong momentum (high ATR) -> extend TP by up to 1.5x
- Weak momentum (low ATR)   -> shrink TP by up to 0.7x
- Neutral zone              -> keep TP as configured
"""

import time
from collections import deque


class AdaptiveTp:
    def __init__(self, window: int = 20, extend_ratio: float = 1.5,
                 shrink_ratio: float = 0.7, atr_high_threshold: float = 0.15,
                 atr_low_threshold: float = 0.04):
        """
        window:              Number of recent ticks to compute ATR proxy.
        extend_ratio:        Multiply base TP by this when ATR is high.
        shrink_ratio:        Multiply base TP by this when ATR is low.
        atr_high_threshold:  Average range per tick considered "high volatility".
        atr_low_threshold:   Average range per tick considered "low volatility".
        """
        self._window = window
        self._extend_ratio = extend_ratio
        self._shrink_ratio = shrink_ratio
        self._atr_high = atr_high_threshold
        self._atr_low = atr_low_threshold
        self._prices: deque = deque(maxlen=window + 1)
        self._current_atr: float = 0.0
        self._last_multiplier: float = 1.0
        self._total_adjustments: int = 0
        self._created_at: float = time.time()

    def update_price(self, price: float) -> None:
        """Feed latest tick price into the ATR buffer."""
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
        > 1.0 → extend TP  |  < 1.0 → shrink TP  |  1.0 → unchanged
        """
        if self._current_atr >= self._atr_high:
            mult = self._extend_ratio
        elif self._current_atr <= self._atr_low:
            mult = self._shrink_ratio
        else:
            mult = 1.0

        if mult != self._last_multiplier:
            self._total_adjustments += 1
        self._last_multiplier = mult
        return mult

    def adjust_tp(self, base_tp_pips: float) -> float:
        """Return adjusted TP pips. Always ≥ 5 pips floor."""
        adjusted = base_tp_pips * self.get_tp_multiplier()
        return max(adjusted, 5.0)

    def info(self) -> dict:
        return {
            "current_atr": round(self._current_atr, 5),
            "tp_multiplier": round(self._last_multiplier, 3),
            "mode": (
                "EXTEND" if self._last_multiplier > 1.0 else
                "SHRINK" if self._last_multiplier < 1.0 else
                "NEUTRAL"
            ),
            "total_adjustments": self._total_adjustments,
            "buffer_size": len(self._prices),
            "atr_high_threshold": self._atr_high,
            "atr_low_threshold": self._atr_low,
        }


# Module-level singleton
adaptive_tp = AdaptiveTp(
    window=20,
    extend_ratio=1.5,
    shrink_ratio=0.7,
    atr_high_threshold=0.15,
    atr_low_threshold=0.04,
)
