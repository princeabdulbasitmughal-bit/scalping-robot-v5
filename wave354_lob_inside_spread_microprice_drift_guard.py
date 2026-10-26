# wave354_lob_inside_spread_microprice_drift_guard.py
# WAVE 354 - LOB Inside-Spread Microprice Drift Guard
# ASCII-only file. No live server calls.

import threading
import time
from collections import deque


class Wave354LobInsideSpreadMicropriceDriftGuard:
    """
    Tracks the LOB microprice across successive ticks and blocks when the
    cumulative absolute signed drift (in basis-points relative to mid-price)
    breaches a configurable threshold.

    Algorithm:
      micro_price = (bid * ask_size + ask * bid_size) / (bid_size + ask_size)
      drift_i     = micro_price_i - micro_price_{i-1}
      Maintain a rolling deque of the last drift_window signed drift values.
      cumulative_drift = abs(sum(deque))
      Block when (cumulative_drift / mid_price) * 10000 >= drift_threshold_bps.

    Blocking reasons: MICROPRICE_DRIFT_BREACH, INPUT_VALIDATION_ERROR
    """

    REASON_DRIFT_BREACH = "MICROPRICE_DRIFT_BREACH"
    REASON_INPUT_ERROR  = "INPUT_VALIDATION_ERROR"

    def __init__(
        self,
        drift_window: int = 10,
        drift_threshold_bps: float = 3.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if not isinstance(drift_window, int) or drift_window < 1:
            raise ValueError("drift_window must be a positive int")
        if not isinstance(drift_threshold_bps, (int, float)) or drift_threshold_bps <= 0:
            raise ValueError("drift_threshold_bps must be a positive number")
        if not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be a non-negative number")

        self._drift_window       = drift_window
        self._drift_threshold_bps = float(drift_threshold_bps)
        self._cooldown_seconds   = float(cooldown_seconds)

        self._lock            = threading.RLock()
        self._drifts: deque   = deque(maxlen=drift_window)
        self._prev_microprice: float | None = None
        self._blocked_until: float = 0.0
        self._last_reason: str     = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        bid: float,
        ask: float,
        bid_size: float,
        ask_size: float,
        timestamp: float,
    ) -> None:
        """
        Ingest one LOB tick.  Blocks on any invalid input.

        Parameters
        ----------
        bid, ask        : best bid / ask prices (positive floats)
        bid_size, ask_size : sizes at best bid / ask (positive floats)
        timestamp       : monotonic tick timestamp (non-negative float)
        """
        with self._lock:
            # --- validation (bool check before numeric check) ---
            for name, val in [
                ("bid",      bid),
                ("ask",      ask),
                ("bid_size", bid_size),
                ("ask_size", ask_size),
                ("timestamp", timestamp),
            ]:
                if isinstance(val, bool):
                    self._block_now(self.REASON_INPUT_ERROR)
                    return
                if not isinstance(val, (int, float)):
                    self._block_now(self.REASON_INPUT_ERROR)
                    return

            bid      = float(bid)
            ask      = float(ask)
            bid_size = float(bid_size)
            ask_size = float(ask_size)
            timestamp = float(timestamp)

            if bid <= 0 or ask <= 0 or bid_size <= 0 or ask_size <= 0:
                self._block_now(self.REASON_INPUT_ERROR)
                return
            if ask < bid:
                self._block_now(self.REASON_INPUT_ERROR)
                return
            if timestamp < 0:
                self._block_now(self.REASON_INPUT_ERROR)
                return

            # --- compute microprice ---
            total_size  = bid_size + ask_size
            micro_price = (bid * ask_size + ask * bid_size) / total_size
            mid_price   = (bid + ask) / 2.0

            # --- record drift ---
            if self._prev_microprice is not None:
                drift = micro_price - self._prev_microprice
                self._drifts.append(drift)
            self._prev_microprice = micro_price

            # --- evaluate threshold ---
            if len(self._drifts) > 0 and mid_price > 0:
                cumulative_drift = abs(sum(self._drifts))
                drift_bps = (cumulative_drift / mid_price) * 10_000.0
                if drift_bps >= self._drift_threshold_bps:
                    self._block_now(self.REASON_DRIFT_BREACH)

    def is_blocked(self, current_time: float | None = None) -> bool:
        """Return True if currently within a cooldown block period."""
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        """Convenience: block check that also accepts positional quote params."""
        return self.is_blocked(current_time=ts)

    def reset(self) -> None:
        """Clear all rolling state and lift any active block."""
        with self._lock:
            self._drifts.clear()
            self._prev_microprice = None
            self._blocked_until   = 0.0
            self._last_reason     = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _block_now(self, reason: str) -> None:
        """Set block; monotonic cooldown. Caller must hold self._lock."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason   = reason
