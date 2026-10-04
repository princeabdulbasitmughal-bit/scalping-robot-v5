"""
Wave 27: Correlation Guard
--------------------------
Detects when multiple BUY or SELL signals fire in rapid succession (within
a configurable window, default 30 seconds).  Rapid-fire signals almost
always indicate a choppy/whipsaw market rather than a clean directional move.

Logic:
- A circular buffer stores the last N signal timestamps.
- If more than `max_signals_in_window` signals arrived within `window_sec`,
  block all new signals for `cooldown_sec` (default 60 s).

This is different from the entry_cooldown (which just spaces trades out);
the Correlation Guard looks at signal *cluster density* and triggers a
longer cooldown when the market is genuinely choppy.
"""
from __future__ import annotations
import time
import logging
from collections import deque
from typing import Tuple

logger = logging.getLogger(__name__)


class CorrelationGuard:
    """
    Blocks trading when signals arrive too densely (choppy market indicator).

    Parameters
    ----------
    window_sec            : rolling window in seconds to count signals
    max_signals_in_window : max signals allowed before triggering cooldown
    cooldown_sec          : block duration after trigger
    """

    def __init__(
        self,
        window_sec: float = 30.0,
        max_signals_in_window: int = 3,
        cooldown_sec: float = 60.0,
    ):
        self._window_sec            = window_sec
        self._max_signals           = max_signals_in_window
        self._cooldown_sec          = cooldown_sec

        self._signal_times: deque[float] = deque(maxlen=50)
        self._blocked_until: float       = 0.0
        self._total_triggers: int        = 0

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #

    def record_signal(self) -> None:
        """
        Call this every time a non-HOLD signal is generated (regardless of
        whether it eventually passes all other gates).
        """
        now = time.monotonic()
        self._signal_times.append(now)
        self._maybe_trigger_cooldown(now)

    def is_trading_allowed(self) -> Tuple[bool, str]:
        """
        Returns (True, "") if clear, or (False, reason) if in cooldown.
        """
        now = time.monotonic()
        if now < self._blocked_until:
            remaining = round(self._blocked_until - now, 1)
            reason = (
                f"CORR_GUARD: choppy market cooldown active ({remaining}s remaining)"
            )
            return False, reason
        return True, ""

    def info(self) -> dict:
        """Return status dict for live_status.json."""
        now = time.monotonic()
        in_cooldown = now < self._blocked_until
        # Count recent signals in window
        cutoff = now - self._window_sec
        recent = sum(1 for t in self._signal_times if t >= cutoff)
        return {
            "in_cooldown": in_cooldown,
            "cooldown_remaining_sec": round(max(self._blocked_until - now, 0.0), 1),
            "signals_in_window": recent,
            "window_sec": self._window_sec,
            "max_signals": self._max_signals,
            "total_triggers": self._total_triggers,
        }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _maybe_trigger_cooldown(self, now: float) -> None:
        cutoff = now - self._window_sec
        recent_times = [t for t in self._signal_times if t >= cutoff]
        if len(recent_times) > self._max_signals:
            self._blocked_until = now + self._cooldown_sec
            self._total_triggers += 1
            logger.warning(
                "[WAVE27] %d signals in %.0fs window → CHOPPY MARKET, "
                "blocking for %.0fs",
                len(recent_times),
                self._window_sec,
                self._cooldown_sec,
            )


# Module-level singleton
correlation_guard = CorrelationGuard()
