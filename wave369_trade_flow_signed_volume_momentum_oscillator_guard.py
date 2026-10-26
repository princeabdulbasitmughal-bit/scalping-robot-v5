"""
wave369_trade_flow_signed_volume_momentum_oscillator_guard.py
WAVE 369 -- Trade Flow Signed Volume Momentum Oscillator Guard

Algorithm:
  Each tick receives a (volume, side) pair. Signed volume sv = +volume for
  "buy" and -volume for "sell". Two Exponential Moving Averages are
  maintained:
      alpha_fast = 2 / (fast_period + 1)
      alpha_slow = 2 / (slow_period + 1)
      fast_EMA_i = alpha_fast * sv_i + (1 - alpha_fast) * fast_EMA_{i-1}
      slow_EMA_i = alpha_slow * sv_i + (1 - alpha_slow) * slow_EMA_{i-1}
      SVMO = fast_EMA - slow_EMA

  Evaluation only begins once at least slow_period ticks have been consumed.
  Blocking triggers when |SVMO| >= oscillator_threshold.

Blocking reasons: SVMO_EXTREME_MOMENTUM, INPUT_VALIDATION_ERROR
Thread safety: threading.RLock()
"""

import threading
import time


class Wave369TradeFlowSignedVolumeMomentumOscillatorGuard:
    """Trade Flow Signed Volume Momentum Oscillator Guard (WAVE 369)."""

    VALID_SIDES = frozenset({"buy", "sell"})

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        fast_period: int = 5,
        slow_period: int = 20,
        oscillator_threshold: float = 500.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if not isinstance(fast_period, int) or isinstance(fast_period, bool):
            raise TypeError("fast_period must be int")
        if fast_period < 1:
            raise ValueError("fast_period must be >= 1")

        if not isinstance(slow_period, int) or isinstance(slow_period, bool):
            raise TypeError("slow_period must be int")
        if slow_period < 1:
            raise ValueError("slow_period must be >= 1")

        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")

        if isinstance(oscillator_threshold, bool):
            raise TypeError("oscillator_threshold must be float or int")
        if not isinstance(oscillator_threshold, (int, float)):
            raise TypeError("oscillator_threshold must be float or int")
        if oscillator_threshold <= 0.0:
            raise ValueError("oscillator_threshold must be > 0")

        if isinstance(cooldown_seconds, bool):
            raise TypeError("cooldown_seconds must be float or int")
        if not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be float or int")
        if cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._fast_period = fast_period
        self._slow_period = slow_period
        self._oscillator_threshold = float(oscillator_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._alpha_fast: float = 2.0 / (fast_period + 1)
        self._alpha_slow: float = 2.0 / (slow_period + 1)

        self._lock = threading.RLock()

        self._tick_count: int = 0
        self._fast_ema: float = 0.0
        self._slow_ema: float = 0.0
        self._svmo: float = 0.0

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
        with self._lock:
            self._tick_count = 0
            self._fast_ema = 0.0
            self._slow_ema = 0.0
            self._svmo = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def update(self, volume: float, side: str, timestamp: float) -> None:
        """Ingest one trade tick.

        Parameters
        ----------
        volume    : traded quantity (> 0)
        side      : "buy" or "sell"
        timestamp : monotonic tick timestamp (float)
        """
        with self._lock:
            if not self._validate(volume, side, timestamp):
                return

            signed_volume = volume if side == "buy" else -volume

            if self._tick_count == 0:
                # Seed both EMAs with the first signed volume
                self._fast_ema = signed_volume
                self._slow_ema = signed_volume
            else:
                self._fast_ema = (
                    self._alpha_fast * signed_volume
                    + (1.0 - self._alpha_fast) * self._fast_ema
                )
                self._slow_ema = (
                    self._alpha_slow * signed_volume
                    + (1.0 - self._alpha_slow) * self._slow_ema
                )

            self._tick_count += 1
            self._svmo = self._fast_ema - self._slow_ema

            # Only evaluate after warming up slow_period ticks
            if self._tick_count >= self._slow_period:
                if abs(self._svmo) >= self._oscillator_threshold:
                    self._blocked_until = time.monotonic() + self._cooldown_seconds
                    self._last_reason = "SVMO_EXTREME_MOMENTUM"

    def is_blocked(self, current_time: float | None = None) -> bool:
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(current_time=ts)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate(self, volume: float, side: str, timestamp: float) -> bool:
        """Return True if valid; block and return False otherwise."""
        # side must be str -- check before numeric guards
        if not isinstance(side, str) or side not in self.VALID_SIDES:
            self._blocked_until = time.monotonic() + self._cooldown_seconds
            self._last_reason = "INPUT_VALIDATION_ERROR"
            return False

        for name, val in [("volume", volume), ("timestamp", timestamp)]:
            # bool check BEFORE int/float (bool is subclass of int)
            if isinstance(val, bool):
                self._blocked_until = time.monotonic() + self._cooldown_seconds
                self._last_reason = "INPUT_VALIDATION_ERROR"
                return False
            if not isinstance(val, (int, float)):
                self._blocked_until = time.monotonic() + self._cooldown_seconds
                self._last_reason = "INPUT_VALIDATION_ERROR"
                return False
            if val != val:  # NaN check
                self._blocked_until = time.monotonic() + self._cooldown_seconds
                self._last_reason = "INPUT_VALIDATION_ERROR"
                return False

        if volume <= 0:
            self._blocked_until = time.monotonic() + self._cooldown_seconds
            self._last_reason = "INPUT_VALIDATION_ERROR"
            return False

        return True
