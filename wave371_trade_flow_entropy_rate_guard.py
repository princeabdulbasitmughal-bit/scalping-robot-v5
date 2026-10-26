"""
wave371_trade_flow_entropy_rate_guard.py
Trade Flow Entropy Rate Guard (Wave 371)

Algorithm:
  - Discretize signed volume into 4 bins:
      large_buy  (+2): side == "buy"  and |volume| >= large_vol_threshold
      small_buy  (+1): side == "buy"  and |volume| <  large_vol_threshold
      small_sell (-1): side == "sell" and |volume| <  large_vol_threshold
      large_sell (-2): side == "sell" and |volume| >= large_vol_threshold
  - Maintain rolling deque of last window_size bin labels.
  - Compute Shannon entropy H over the empirical distribution of the 4 bins.
  - Block when H <= low_entropy_threshold  (too concentrated => directional/manipulation)
       OR  when H >= high_entropy_threshold (too dispersed   => noisy/spoofed).

Blocking reasons: LOW_FLOW_ENTROPY, HIGH_FLOW_ENTROPY, INPUT_VALIDATION_ERROR
Thread-safe via threading.RLock(). ASCII-only source.
"""

import collections
import math
import threading
import time

_VALID_SIDES = frozenset({"buy", "sell"})
_ALL_BINS = (+2, +1, -1, -2)


class TradeFlowEntropyRateGuard:
    """
    Monitors Shannon entropy of discretized trade-flow bins.
    Blocks on either abnormally low (directional) or abnormally high
    (noisy / spoofed) entropy once the rolling window is full.
    """

    def __init__(
        self,
        window_size=30,
        large_vol_threshold=100.0,
        low_entropy_threshold=0.8,
        high_entropy_threshold=1.95,
        cooldown_seconds=45.0,
    ):
        if not isinstance(window_size, int) or window_size < 1:
            raise ValueError("window_size must be a positive int")
        for name, val in [
            ("large_vol_threshold", large_vol_threshold),
            ("low_entropy_threshold", low_entropy_threshold),
            ("high_entropy_threshold", high_entropy_threshold),
            ("cooldown_seconds", cooldown_seconds),
        ]:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError("{} must be a number".format(name))
        if low_entropy_threshold >= high_entropy_threshold:
            raise ValueError(
                "low_entropy_threshold must be less than high_entropy_threshold"
            )

        self._window_size = window_size
        self._large_vol_threshold = float(large_vol_threshold)
        self._low_entropy_threshold = float(low_entropy_threshold)
        self._high_entropy_threshold = float(high_entropy_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._bins = collections.deque(maxlen=window_size)

        self._blocked_until = 0.0
        self._last_reason = None

        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def last_reason(self):
        with self._lock:
            return self._last_reason

    def update(self, volume, side, timestamp):
        """
        Ingest a single trade event.

        Parameters
        ----------
        volume    : float  -- unsigned or signed trade volume (absolute value used)
        side      : str    -- "buy" or "sell"
        timestamp : float  -- monotonic or epoch timestamp
        """
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(volume, bool) or not isinstance(
                volume, (int, float)
            ):
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return
            if not isinstance(side, str):
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return
            if isinstance(timestamp, bool) or not isinstance(
                timestamp, (int, float)
            ):
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return

            vol = float(volume)
            if not math.isfinite(vol):
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return
            if vol < 0.0:
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return
            side_lower = side.strip().lower()
            if side_lower not in _VALID_SIDES:
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return

            # --- discretize ---
            if side_lower == "buy":
                label = +2 if vol >= self._large_vol_threshold else +1
            else:  # sell
                label = -2 if vol >= self._large_vol_threshold else -1

            self._bins.append(label)

            # --- evaluate block condition only when window is full ---
            if len(self._bins) == self._window_size:
                h = self._shannon_entropy(self._bins)
                if h <= self._low_entropy_threshold:
                    self._set_blocked("LOW_FLOW_ENTROPY")
                elif h >= self._high_entropy_threshold:
                    self._set_blocked("HIGH_FLOW_ENTROPY")

    def is_blocked(self, current_time=None):
        """Return True if cooldown is still active."""
        with self._lock:
            if current_time is None:
                current_time = time.monotonic()
            return current_time < self._blocked_until

    def is_entry_blocked(self, volume, side, ts):
        """
        Ingest trade event then return whether entry is currently blocked.
        Delegates block evaluation to update() + is_blocked().
        """
        self.update(volume, side, ts)
        return self.is_blocked()

    def reset(self):
        """Clear all accumulated state and cooldown."""
        with self._lock:
            self._bins.clear()
            self._blocked_until = 0.0
            self._last_reason = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_blocked(self, reason):
        """Arm the monotonic cooldown and record reason (must hold lock)."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason

    @staticmethod
    def _shannon_entropy(labels):
        """
        Compute Shannon entropy (nats base-2 via log2) over 4 fixed bins.
        Bins not observed contribute 0 to the sum (0 * log2(0) := 0).
        """
        n = len(labels)
        if n == 0:
            return 0.0
        counts = collections.Counter(labels)
        h = 0.0
        for b in _ALL_BINS:
            c = counts.get(b, 0)
            if c > 0:
                p = c / n
                h -= p * math.log2(p)
        return h
