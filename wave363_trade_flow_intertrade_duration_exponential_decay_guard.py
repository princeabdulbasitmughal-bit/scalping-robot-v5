"""
wave363_trade_flow_intertrade_duration_exponential_decay_guard.py
=================================================================
Trade Flow Intertrade Duration Exponential Decay Guard (Wave 363)

Algorithm:
  - Collects inter-trade durations (delta_t between consecutive trades).
  - Maintains a rolling window of the most recent window_size durations.
  - Fits exponential distribution: lambda_hat = 1 / mean(durations).
  - Blocks when:
      lambda_hat >= burst_lambda_threshold  -> TRADE_BURST_DETECTED
      lambda_hat <= slow_lambda_threshold   -> MARKET_FREEZE_DETECTED
  - Any invalid input is fail-closed        -> INPUT_VALIDATION_ERROR
  - Thread-safe via threading.RLock; cooldown uses time.monotonic().
"""

import math
import threading
import time


class Wave363TradeFlowIntertradeDecayGuard:
    """Trade Flow Intertrade Duration Exponential Decay Guard."""

    def __init__(
        self,
        window_size: int = 20,
        burst_lambda_threshold: float = 50.0,
        slow_lambda_threshold: float = 0.01,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise TypeError("window_size must be a positive int")
        if window_size < 2:
            raise ValueError("window_size must be >= 2")

        if isinstance(burst_lambda_threshold, bool) or not isinstance(
            burst_lambda_threshold, (int, float)
        ):
            raise TypeError("burst_lambda_threshold must be a positive number")
        if burst_lambda_threshold <= 0:
            raise ValueError("burst_lambda_threshold must be > 0")

        if isinstance(slow_lambda_threshold, bool) or not isinstance(
            slow_lambda_threshold, (int, float)
        ):
            raise TypeError("slow_lambda_threshold must be a positive number")
        if slow_lambda_threshold <= 0:
            raise ValueError("slow_lambda_threshold must be > 0")

        if burst_lambda_threshold <= slow_lambda_threshold:
            raise ValueError(
                "burst_lambda_threshold must be > slow_lambda_threshold"
            )

        if isinstance(cooldown_seconds, bool) or not isinstance(
            cooldown_seconds, (int, float)
        ):
            raise TypeError("cooldown_seconds must be a non-negative number")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._burst_lambda_threshold = float(burst_lambda_threshold)
        self._slow_lambda_threshold = float(slow_lambda_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._durations: list = []
        self._last_trade_ts: float = None
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update(self, timestamp) -> None:
        """Ingest a trade event at `timestamp` and evaluate guard logic."""
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(timestamp, bool) or not isinstance(
                timestamp, (int, float)
            ):
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return
            if not math.isfinite(timestamp):
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return

            if self._last_trade_ts is None:
                # First trade: just store timestamp, no duration yet
                self._last_trade_ts = float(timestamp)
                return

            delta_t = float(timestamp) - self._last_trade_ts

            if delta_t < 0:
                # Timestamp went backwards — treat as invalid
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return

            if delta_t == 0:
                # Two trades at the exact same timestamp: effectively
                # infinite lambda — treat as burst
                self._last_trade_ts = float(timestamp)
                self._trigger_block("TRADE_BURST_DETECTED")
                return

            self._last_trade_ts = float(timestamp)

            # Maintain rolling window
            self._durations.append(delta_t)
            if len(self._durations) > self._window_size:
                self._durations.pop(0)

            # Need at least window_size observations before firing
            if len(self._durations) < self._window_size:
                return

            mean_duration = sum(self._durations) / len(self._durations)
            if mean_duration <= 0:
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return

            lambda_hat = 1.0 / mean_duration

            if lambda_hat >= self._burst_lambda_threshold:
                self._trigger_block("TRADE_BURST_DETECTED")
            elif lambda_hat <= self._slow_lambda_threshold:
                self._trigger_block("MARKET_FREEZE_DETECTED")

    def is_blocked(self, current_time: float = None) -> bool:
        """Return True if the guard is currently in a cooldown block."""
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts) -> bool:
        """
        Convenience wrapper for unified guard interface.
        Calls update(ts) then returns is_blocked().
        bid and ask are accepted but ignored (not applicable here).
        """
        self.update(ts)
        return self.is_blocked()

    def reset(self) -> None:
        """Clear all state: durations, last timestamp, block, and reason."""
        with self._lock:
            self._durations.clear()
            self._last_trade_ts = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        """Return the most recent blocking reason string."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trigger_block(self, reason: str) -> None:
        """Set blocked_until using monotonic clock and record reason."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
