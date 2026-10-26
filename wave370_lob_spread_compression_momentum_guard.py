"""
wave370_lob_spread_compression_momentum_guard.py
LOB Spread Compression Momentum Guard (Wave 370)

Algorithm:
  - Record spread_bps at each tick.
  - Compute momentum: spread_mom_i = spread_bps_i - spread_bps_{i - lookback}
  - Maintain rolling window of last window_size spread momenta.
  - Block when rolling mean(spread_mom) <= -compression_threshold_bps
    (spread compressing rapidly => unusual liquidity event).

Blocking reasons: SPREAD_COMPRESSION_MOMENTUM, INPUT_VALIDATION_ERROR
Thread-safe via threading.RLock(). ASCII-only source.
"""

import collections
import threading
import time


class LOBSpreadCompressionMomentumGuard:
    """
    Monitors the momentum of bid-ask spread in basis points.
    Blocks when the rolling mean of spread momentum falls below
    -compression_threshold_bps, indicating rapid spread compression.
    """

    def __init__(
        self,
        window_size=15,
        lookback=3,
        compression_threshold_bps=1.0,
        cooldown_seconds=45.0,
    ):
        if not isinstance(window_size, int) or window_size < 1:
            raise ValueError("window_size must be a positive int")
        if not isinstance(lookback, int) or lookback < 1:
            raise ValueError("lookback must be a positive int")
        if isinstance(compression_threshold_bps, bool) or not isinstance(
            compression_threshold_bps, (int, float)
        ):
            raise ValueError("compression_threshold_bps must be a number")
        if isinstance(cooldown_seconds, bool) or not isinstance(
            cooldown_seconds, (int, float)
        ):
            raise ValueError("cooldown_seconds must be a number")

        self._window_size = window_size
        self._lookback = lookback
        self._compression_threshold_bps = float(compression_threshold_bps)
        self._cooldown_seconds = float(cooldown_seconds)

        # Ring buffer holding raw spread_bps values (we need lookback extra slots)
        self._raw_spreads = collections.deque(maxlen=window_size + lookback)
        # Rolling window of computed spread momenta
        self._momenta = collections.deque(maxlen=window_size)

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

    def update(self, bid, ask, timestamp):
        """
        Ingest a new tick (bid, ask, timestamp).

        Parameters
        ----------
        bid       : float  -- best bid price (> 0)
        ask       : float  -- best ask price (> bid)
        timestamp : float  -- monotonic or epoch timestamp (unused for logic,
                              stored for extensibility)
        """
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(bid, bool) or not isinstance(bid, (int, float)):
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return
            if isinstance(ask, bool) or not isinstance(ask, (int, float)):
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return
            if isinstance(timestamp, bool) or not isinstance(
                timestamp, (int, float)
            ):
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return
            bid = float(bid)
            ask = float(ask)
            if ask <= bid or bid <= 0.0:
                self._set_blocked("INPUT_VALIDATION_ERROR")
                return

            # --- compute spread in bps ---
            mid = (bid + ask) / 2.0
            spread_bps = ((ask - bid) / mid) * 10_000.0

            self._raw_spreads.append(spread_bps)

            # We need at least (lookback + 1) raw values to form one momentum
            if len(self._raw_spreads) > self._lookback:
                # Index math: last element vs element lookback positions back
                raw_list = list(self._raw_spreads)
                current = raw_list[-1]
                prior = raw_list[-(self._lookback + 1)]
                mom = current - prior
                self._momenta.append(mom)

            # --- evaluate block condition ---
            if len(self._momenta) == self._window_size:
                rolling_mean = sum(self._momenta) / self._window_size
                if rolling_mean <= -self._compression_threshold_bps:
                    self._set_blocked("SPREAD_COMPRESSION_MOMENTUM")

    def is_blocked(self, current_time=None):
        """Return True if cooldown is still active."""
        with self._lock:
            if current_time is None:
                current_time = time.monotonic()
            return current_time < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts):
        """
        Ingest tick then return whether entry is currently blocked.
        Delegates block evaluation to update() + is_blocked().
        """
        self.update(bid, ask, ts)
        return self.is_blocked()

    def reset(self):
        """Clear all accumulated state and cooldown."""
        with self._lock:
            self._raw_spreads.clear()
            self._momenta.clear()
            self._blocked_until = 0.0
            self._last_reason = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_blocked(self, reason):
        """Arm the monotonic cooldown and record reason (must hold lock)."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
