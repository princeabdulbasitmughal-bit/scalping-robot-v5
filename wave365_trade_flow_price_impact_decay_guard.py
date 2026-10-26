"""
wave365_trade_flow_price_impact_decay_guard.py
Trade Flow Price Impact Decay Guard -- Batch 303, Wave 365

Algorithm:
  - For each trade: signed_volume = volume if buy, -volume if sell
  - price_impact = delta_mid / max(abs(signed_volume), 1e-10)
    where delta_mid = curr_mid - prev_mid
  - Maintains a rolling deque of last window_size price_impact values
  - Blocks when rolling mean(price_impact) >= impact_threshold
    (high per-unit price impact signals illiquidity or manipulation)
  - Blocking reasons: HIGH_PRICE_IMPACT, INPUT_VALIDATION_ERROR
  - Thread-safe via threading.RLock; cooldown is monotonic
"""

import threading
import time
from collections import deque

REASON_HIGH_IMPACT = "HIGH_PRICE_IMPACT"
REASON_VALIDATION = "INPUT_VALIDATION_ERROR"

VALID_SIDES = frozenset({"buy", "sell"})

_EPSILON = 1e-10


class Wave365TradeFlowPriceImpactDecayGuard:
    """Trade Flow Price Impact Decay Guard.

    Parameters
    ----------
    window_size : int
        Number of recent price-impact observations kept in the rolling window.
    impact_threshold : float
        Rolling-mean price-impact threshold.  Block when mean >= this value.
    cooldown_seconds : float
        Minimum duration (monotonic seconds) the guard stays blocked
        after a trigger.
    """

    def __init__(
        self,
        window_size: int = 15,
        impact_threshold: float = 0.0001,
        cooldown_seconds: float = 60.0,
    ):
        # --- validate constructor args ---
        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise TypeError("window_size must be a positive int")
        if window_size < 1:
            raise ValueError("window_size must be >= 1")
        if isinstance(impact_threshold, bool) or not isinstance(
            impact_threshold, (int, float)
        ):
            raise TypeError("impact_threshold must be numeric")
        if isinstance(cooldown_seconds, bool) or not isinstance(
            cooldown_seconds, (int, float)
        ):
            raise TypeError("cooldown_seconds must be numeric")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._impact_threshold = float(impact_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._impacts: deque = deque(maxlen=window_size)
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    def reset(self) -> None:
        """Clear all state; guard returns to unblocked."""
        with self._lock:
            self._impacts.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    def update(
        self,
        volume,
        side: str,
        prev_mid,
        curr_mid,
        timestamp,
    ) -> None:
        """Record one trade observation.

        Parameters
        ----------
        volume :
            Absolute trade volume (must be a non-negative real number).
        side : str
            "buy" or "sell".
        prev_mid :
            Mid-price before the trade.
        curr_mid :
            Mid-price after the trade.
        timestamp :
            Opaque timestamp (stored but not used for internal logic).
        """
        with self._lock:
            # --- input validation: side ---
            if isinstance(side, bool) or not isinstance(side, str):
                self._trigger(REASON_VALIDATION)
                return
            if side not in VALID_SIDES:
                self._trigger(REASON_VALIDATION)
                return

            # --- input validation: volume ---
            if isinstance(volume, bool) or not isinstance(
                volume, (int, float)
            ):
                self._trigger(REASON_VALIDATION)
                return
            if volume != volume:  # NaN check
                self._trigger(REASON_VALIDATION)
                return

            # --- input validation: prev_mid ---
            if isinstance(prev_mid, bool) or not isinstance(
                prev_mid, (int, float)
            ):
                self._trigger(REASON_VALIDATION)
                return
            if prev_mid != prev_mid:
                self._trigger(REASON_VALIDATION)
                return

            # --- input validation: curr_mid ---
            if isinstance(curr_mid, bool) or not isinstance(
                curr_mid, (int, float)
            ):
                self._trigger(REASON_VALIDATION)
                return
            if curr_mid != curr_mid:
                self._trigger(REASON_VALIDATION)
                return

            # --- input validation: timestamp ---
            if isinstance(timestamp, bool):
                self._trigger(REASON_VALIDATION)
                return
            if timestamp is None:
                self._trigger(REASON_VALIDATION)
                return

            # --- compute signed volume and price impact ---
            signed_volume = float(volume) if side == "buy" else -float(volume)
            delta_mid = float(curr_mid) - float(prev_mid)
            vol_abs = max(abs(signed_volume), _EPSILON)
            price_impact = (delta_mid if side == "buy" else -delta_mid) / vol_abs

            self._impacts.append(price_impact)
            self._evaluate()

    def is_blocked(self, current_time: float = None) -> bool:
        """Return True if the guard is currently blocking trade entry."""
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts) -> bool:
        """Convenience wrapper used by the execution layer.

        Delegates to is_blocked(); bid/ask/ts accepted for API compatibility.
        """
        return self.is_blocked()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rolling_mean(self) -> float:
        n = len(self._impacts)
        if n == 0:
            return 0.0
        return sum(self._impacts) / n

    def _evaluate(self) -> None:
        """Check rolling mean price impact and trigger block if breached."""
        if len(self._impacts) < self._window_size:
            return  # window not yet full -- no-block until warm
        mean_impact = self._rolling_mean()
        if mean_impact >= self._impact_threshold:
            self._trigger(REASON_HIGH_IMPACT)

    def _trigger(self, reason: str) -> None:
        """Set blocked-until and record reason (monotonic cooldown)."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
