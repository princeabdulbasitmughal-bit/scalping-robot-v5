"""
wave361_trade_flow_cvar_breach_guard.py
---------------------------------------
WAVE 361 - Trade Flow Conditional Value-at-Risk Breach Guard

Algorithm:
  Maintain a rolling window of signed volumes.
  A "buy" tick contributes +volume; a "sell" tick contributes -volume.
  Once the window is full, sort the signed volumes in ascending order.
  CVaR_alpha = mean of the bottom (1 - alpha) fraction (tail slice).
  Block when CVaR_alpha <= -cvar_threshold -> CVAR_TAIL_BREACH.
  Any invalid input triggers an immediate block with INPUT_VALIDATION_ERROR.

Thread safety: threading.RLock() guards all shared state.
Cooldown: monotonic clock, _blocked_until = time.monotonic() + cooldown_seconds.
"""

import time
import math
import threading
from collections import deque


class Wave361TradeFlowCvarBreachGuard:
    """Trade Flow Conditional Value-at-Risk Breach Guard (WAVE 361)."""

    REASON_CVAR_BREACH = "CVAR_TAIL_BREACH"
    REASON_INPUT_ERROR = "INPUT_VALIDATION_ERROR"

    _VALID_SIDES = frozenset({"buy", "sell"})

    def __init__(
        self,
        window_size: int = 30,
        alpha: float = 0.95,
        cvar_threshold: float = 100.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        # --- parameter validation ---
        if not isinstance(window_size, int) or isinstance(window_size, bool):
            raise TypeError("window_size must be a positive int")
        if window_size < 1:
            raise ValueError("window_size must be >= 1")

        if isinstance(alpha, bool):
            raise TypeError("alpha must be a float in (0, 1)")
        if not isinstance(alpha, (int, float)):
            raise TypeError("alpha must be a float in (0, 1)")
        if not (0.0 < float(alpha) < 1.0):
            raise ValueError("alpha must be in open interval (0, 1)")

        if isinstance(cvar_threshold, bool):
            raise TypeError("cvar_threshold must be a positive float")
        if not isinstance(cvar_threshold, (int, float)):
            raise TypeError("cvar_threshold must be a positive float")
        if cvar_threshold <= 0:
            raise ValueError("cvar_threshold must be > 0")

        if isinstance(cooldown_seconds, bool):
            raise TypeError("cooldown_seconds must be a non-negative float")
        if not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be a non-negative float")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._alpha = float(alpha)
        self._cvar_threshold = float(cvar_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._signed_volumes: deque = deque(maxlen=window_size)
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, volume, side: str, timestamp=None) -> None:
        """Ingest one trade tick and update block state."""
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(volume, bool):
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if not isinstance(volume, (int, float)):
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if math.isnan(volume) or math.isinf(volume):
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if volume < 0:
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if not isinstance(side, str) or side not in self._VALID_SIDES:
                self._trigger_block(self.REASON_INPUT_ERROR)
                return

            signed = float(volume) if side == "buy" else -float(volume)
            self._signed_volumes.append(signed)

            if len(self._signed_volumes) < self._window_size:
                # Window not yet filled; no block signal
                return

            cvar = self._compute_cvar()

            if cvar <= -self._cvar_threshold:
                self._trigger_block(self.REASON_CVAR_BREACH)
            else:
                # Healthy state - clear prior block only if cooldown elapsed
                if time.monotonic() >= self._blocked_until:
                    self._last_reason = ""

    def is_blocked(self, current_time: float = None) -> bool:
        """Return True if the guard is currently in cooldown."""
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts=None) -> bool:
        """Delegate: block entry if the guard is blocked (bid/ask unused here)."""
        return self.is_blocked(current_time=ts)

    def reset(self) -> None:
        """Clear all rolling state and lift any active block."""
        with self._lock:
            self._signed_volumes.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        """Human-readable reason for the most recent block."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_cvar(self) -> float:
        """Compute CVaR_alpha as mean of bottom (1-alpha) fraction. Caller holds lock."""
        data = sorted(self._signed_volumes)
        n = len(data)
        # Number of tail observations (at least 1)
        tail_count = max(1, int(math.floor(n * (1.0 - self._alpha))))
        tail = data[:tail_count]
        return sum(tail) / len(tail)

    def _trigger_block(self, reason: str) -> None:
        """Set block with monotonic cooldown. Caller must hold _lock."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
