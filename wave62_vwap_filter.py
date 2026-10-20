"""
Wave 62: VWAP Deviation Filter
==============================
Tracks a rolling Volume-Weighted Average Price (VWAP) from tick prices
(using uniform weight since live volume is unavailable).

Logic:
- Maintain a rolling VWAP over the last N ticks (default N=50)
- Block BUY  if price is too far ABOVE vwap (overextended long: > threshold pips)
- Block SELL if price is too far BELOW vwap (overextended short: > threshold pips)
- Requires at least `min_ticks` ticks before activating (default 20)
- Fail-closed on invalid inputs; advisory-safe on warmup

API:
    vwap_filter.update(price)
    vwap_filter.is_entry_blocked(signal, price) -> bool
    vwap_filter.get_vwap() -> float
    vwap_filter.info() -> dict
"""

import math
import logging
import threading
from collections import deque
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW = 50
_DEFAULT_MIN_TICKS = 20
_DEFAULT_THRESHOLD_PIPS = 10.0   # block if deviation > 10 pips from VWAP
_PIP_SIZE = 0.1                  # XAUUSD: 0.1 per pip


class VWAPFilter:
    """
    Rolling VWAP deviation filter.
    Blocks entries that are over-extended relative to VWAP.
    Thread-safe with RLock. Fail-closed on bad inputs.
    """

    def __init__(
        self,
        window: int = _DEFAULT_WINDOW,
        min_ticks: int = _DEFAULT_MIN_TICKS,
        threshold_pips: float = _DEFAULT_THRESHOLD_PIPS,
    ):
        try:
            self._window = max(2, int(window))
        except (ValueError, TypeError):
            self._window = _DEFAULT_WINDOW

        try:
            self._min_ticks = max(1, int(min_ticks))
        except (ValueError, TypeError):
            self._min_ticks = _DEFAULT_MIN_TICKS

        try:
            t = float(threshold_pips)
            self._threshold_pips = max(0.1, t) if math.isfinite(t) else _DEFAULT_THRESHOLD_PIPS
        except (ValueError, TypeError):
            self._threshold_pips = _DEFAULT_THRESHOLD_PIPS

        self._prices: deque = deque(maxlen=self._window)
        self._vwap: float = 0.0
        self._tick_count: int = 0
        self._total_blocks: int = 0
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of all state."""
        with self._lock:
            self._prices.clear()
            self._vwap = 0.0
            self._tick_count = 0
            self._total_blocks = 0

    def _safe_price(self, price: Any) -> Optional[float]:
        if price is None or isinstance(price, bool):
            return None
        try:
            p = float(price)
            return p if math.isfinite(p) and p > 0 else None
        except (ValueError, TypeError):
            return None

    def update(self, price: Any) -> None:
        """Feed each tick price to update rolling VWAP."""
        p = self._safe_price(price)
        if p is None:
            return
        try:
            with self._lock:
                self._prices.append(p)
                self._tick_count += 1
                # Uniform-weight VWAP = simple mean of window prices
                self._vwap = sum(self._prices) / len(self._prices)
        except Exception as exc:
            logger.debug(f"[WAVE62] update error: {exc}")

    def get_vwap(self) -> float:
        """Return current VWAP estimate."""
        with self._lock:
            return round(self._vwap, 5)

    def is_signal_blocked(self, signal: Any, price: Optional[float] = None) -> bool:
        """
        Returns True if the signal is blocked due to over-extension from VWAP.
        Fail-open during warmup (insufficient ticks).
        """
        try:
            sig = str(signal).strip().upper() if signal is not None else ""
            if sig not in ("BUY", "SELL"):
                return False

            with self._lock:
                if self._tick_count < self._min_ticks or self._vwap <= 0:
                    return False   # warmup — advisory pass
                if len(self._prices) < 2:
                    return False

                curr_p = self._safe_price(price)
                if curr_p is None:
                    curr_p = self._prices[-1] if self._prices else 0.0

                vwap = self._vwap
                deviation_pips = abs(curr_p - vwap) / _PIP_SIZE

                if sig == "BUY" and (curr_p - vwap) / _PIP_SIZE > self._threshold_pips:
                    self._total_blocks += 1
                    logger.debug(
                        f"[WAVE62] BUY blocked — price {curr_p:.2f} is "
                        f"{deviation_pips:.1f} pips above VWAP {vwap:.2f}"
                    )
                    return True

                if sig == "SELL" and (vwap - curr_p) / _PIP_SIZE > self._threshold_pips:
                    self._total_blocks += 1
                    logger.debug(
                        f"[WAVE62] SELL blocked — price {curr_p:.2f} is "
                        f"{deviation_pips:.1f} pips below VWAP {vwap:.2f}"
                    )
                    return True

            return False
        except Exception as exc:
            logger.error(f"[WAVE62] is_signal_blocked error: {exc}")
            return False

    def is_entry_blocked(self, signal: Any, price: Optional[float] = None) -> bool:
        """Alias for is_signal_blocked."""
        return self.is_signal_blocked(signal, price=price)

    def is_blocked(self, signal: Any, price: Optional[float] = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(signal, price=price)

    def info(self) -> dict:
        with self._lock:
            return {
                "wave": 62,
                "name": "VWAPFilter",
                "vwap": round(self._vwap, 5),
                "tick_count": self._tick_count,
                "window": self._window,
                "threshold_pips": self._threshold_pips,
                "min_ticks": self._min_ticks,
                "prices_in_window": len(self._prices),
                "total_blocks": self._total_blocks,
            }


# Module-level singleton
vwap_filter = VWAPFilter()

# Module-level aliases for risk orchestrator integration
def update(price: Any) -> None:
    vwap_filter.update(price)

def get_vwap() -> float:
    return vwap_filter.get_vwap()

def is_signal_blocked(signal: Any, price: Optional[float] = None) -> bool:
    return vwap_filter.is_signal_blocked(signal, price=price)

def is_entry_blocked(signal: Any, price: Optional[float] = None) -> bool:
    return vwap_filter.is_entry_blocked(signal, price=price)

def is_blocked(signal: Any, price: Optional[float] = None) -> bool:
    return vwap_filter.is_blocked(signal, price=price)

def reset() -> None:
    vwap_filter.reset()

def info() -> dict:
    return vwap_filter.info()
