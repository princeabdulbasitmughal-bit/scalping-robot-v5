# wave357_trade_flow_gbm_drift_test_guard.py
# Wave 357 - Trade Flow Geometric Brownian Motion Drift Test Guard
# ASCII-only source file

import math
import threading
import time
from collections import deque

GBM_DRIFT_DETECTED = "GBM_DRIFT_DETECTED"
INSUFFICIENT_VARIANCE = "INSUFFICIENT_VARIANCE"
INPUT_VALIDATION_ERROR = "INPUT_VALIDATION_ERROR"

_EPS = 1e-9  # epsilon to avoid log(0)
_VALID_SIDES = {"buy", "sell"}


class Wave357TradeFlowGBMDriftTestGuard:
    """
    Guard that applies a one-sample t-test for non-zero GBM drift in cumulative
    signed trade volume.

    At each tick the cumulative signed volume SV is updated:
        SV += volume  if side == "buy"
        SV -= volume  if side == "sell"

    A log-return is computed:
        r_i = log(|SV_i + eps| / |SV_{i-1} + eps|)

    Over a rolling window of window_size returns the t-statistic is:
        t = mean(r) / (std(r) / sqrt(n))

    Block when |t| >= t_threshold (significant non-zero drift).
    Also block when variance is effectively zero but mean != 0 (degenerate case).
    """

    def __init__(
        self,
        window_size: int = 20,
        t_threshold: float = 2.0,
        cooldown_seconds: float = 60.0,
    ):
        if not isinstance(window_size, int) or window_size < 2:
            raise ValueError("window_size must be an integer >= 2")
        if isinstance(t_threshold, bool) or not isinstance(
            t_threshold, (int, float)
        ) or t_threshold <= 0:
            raise ValueError("t_threshold must be a positive number")
        if isinstance(cooldown_seconds, bool) or not isinstance(
            cooldown_seconds, (int, float)
        ) or cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be a non-negative number")

        self._window_size = window_size
        self._t_threshold = float(t_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._sv: float = 0.0          # cumulative signed volume
        self._returns: deque = deque(maxlen=window_size)
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update(self, volume, side: str, timestamp) -> None:
        """
        Feed one trade event.

        Parameters
        ----------
        volume : positive numeric
            Unsigned trade volume.
        side : str
            "buy" or "sell".
        timestamp : numeric (monotonic seconds) or any comparable value
            Recorded for external use; guard uses time.monotonic() internally.
        """
        with self._lock:
            # --- validate volume -------------------------------------------
            if isinstance(volume, bool) or not isinstance(volume, (int, float)):
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return
            if volume <= 0:
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return

            # --- validate side ---------------------------------------------
            if not isinstance(side, str) or side not in _VALID_SIDES:
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return

            # --- update cumulative signed volume ---------------------------
            sv_prev = self._sv
            if side == "buy":
                self._sv += float(volume)
            else:
                self._sv -= float(volume)

            sv_curr = self._sv

            # --- compute log-return ----------------------------------------
            log_return = math.log(
                abs(sv_curr + _EPS) / abs(sv_prev + _EPS)
            )
            self._returns.append(log_return)

            # --- t-test only when window is full ---------------------------
            if len(self._returns) >= self._window_size:
                n = len(self._returns)
                r_list = list(self._returns)
                mean_r = sum(r_list) / n
                variance = sum((r - mean_r) ** 2 for r in r_list) / (n - 1)
                std_r = math.sqrt(variance)

                if std_r < _EPS:
                    # Degenerate: zero variance
                    if abs(mean_r) > _EPS:
                        self._trigger_block(INSUFFICIENT_VARIANCE)
                    # If both mean and std are zero: no signal, no block
                    return

                t_stat = mean_r / (std_r / math.sqrt(n))
                if abs(t_stat) >= self._t_threshold:
                    self._trigger_block(GBM_DRIFT_DETECTED)

    def is_blocked(self, current_time: float = None) -> bool:
        """Return True if the guard is currently in its cooldown window."""
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts=None) -> bool:
        """
        Convenience wrapper for entry checks.
        Delegates to is_blocked(); bid/ask/ts are unused but validated.
        """
        with self._lock:
            if isinstance(bid, bool) or not isinstance(bid, (int, float)):
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return True
            if isinstance(ask, bool) or not isinstance(ask, (int, float)):
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return True
            return self.is_blocked(current_time=ts)

    def reset(self) -> None:
        """Clear all state: signed volume, returns deque, cooldown, last reason."""
        with self._lock:
            self._sv = 0.0
            self._returns.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        """The most recent blocking reason string."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _trigger_block(self, reason: str) -> None:
        """Set cooldown and record reason (must be called with lock held)."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
