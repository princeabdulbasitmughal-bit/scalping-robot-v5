"""
wave353_trade_flow_signed_order_flow_imbalance_reversal_guard.py
Trade Flow Signed Order Flow Imbalance Reversal Guard (Wave 353)

Algorithm:
  - Each tick: sign_vol = +volume (buy) or -volume (sell)
  - OFI_i = sum of last short_window sign_vols
  - Reversal: sign(OFI_i) != sign(OFI_{i-1}) AND |OFI_i| >= ofi_threshold
  - Count reversals in last long_window events; block when count >= max_reversals
  - Reasons: OFI_REVERSAL_STORM, INPUT_VALIDATION_ERROR
"""

import threading
import time
import math

_VALID_SIDES = frozenset(("buy", "sell"))


def _sign(x: float) -> int:
    """Return -1, 0, or +1."""
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


class Wave353TradeFlowSignedOrderFlowImbalanceReversalGuard:
    """Trade Flow Signed Order Flow Imbalance Reversal Guard -- Wave 353."""

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        ofi_threshold: float = 50.0,
        max_reversals: int = 3,
        cooldown_seconds: float = 45.0,
    ) -> None:
        # -- validate constructor args --
        if not isinstance(short_window, int) or isinstance(short_window, bool):
            raise TypeError("short_window must be a positive int")
        if short_window < 1:
            raise ValueError("short_window must be >= 1")

        if not isinstance(long_window, int) or isinstance(long_window, bool):
            raise TypeError("long_window must be a positive int")
        if long_window < short_window:
            raise ValueError("long_window must be >= short_window")

        if isinstance(ofi_threshold, bool):
            raise TypeError("ofi_threshold must be a positive float/int")
        if not isinstance(ofi_threshold, (int, float)):
            raise TypeError("ofi_threshold must be a positive float/int")
        if ofi_threshold <= 0:
            raise ValueError("ofi_threshold must be > 0")

        if not isinstance(max_reversals, int) or isinstance(max_reversals, bool):
            raise TypeError("max_reversals must be a positive int")
        if max_reversals < 1:
            raise ValueError("max_reversals must be >= 1")

        if isinstance(cooldown_seconds, bool):
            raise TypeError("cooldown_seconds must be a positive float/int")
        if not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be a positive float/int")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._short_window = short_window
        self._long_window = long_window
        self._ofi_threshold = float(ofi_threshold)
        self._max_reversals = max_reversals
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        # Rolling buffer of signed volumes (capped at long_window)
        self._signed_vols: list = []
        # Reversal event log: list of bool (True = reversal at that tick)
        # We store one entry per tick (once short_window is warm)
        self._reversal_flags: list = []
        self._prev_ofi_sign: int = 0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, volume, side, timestamp=None) -> None:  # noqa: ANN001
        """Record a new trade and evaluate OFI reversal count."""
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(volume, bool) or not isinstance(volume, (int, float)):
                self._block("INPUT_VALIDATION_ERROR")
                return
            if volume <= 0 or math.isnan(volume) or math.isinf(volume):
                self._block("INPUT_VALIDATION_ERROR")
                return
            if not isinstance(side, str) or side not in _VALID_SIDES:
                self._block("INPUT_VALIDATION_ERROR")
                return

            sign_vol = float(volume) if side == "buy" else -float(volume)

            self._signed_vols.append(sign_vol)
            if len(self._signed_vols) > self._long_window:
                self._signed_vols.pop(0)

            # Need at least short_window ticks to compute OFI
            if len(self._signed_vols) < self._short_window:
                return

            # Compute current OFI over last short_window ticks
            current_ofi = sum(self._signed_vols[-self._short_window:])
            current_sign = _sign(current_ofi)

            # Reversal = sign flipped when OFI reaches threshold
            is_reversal = False
            if abs(current_ofi) >= self._ofi_threshold:
                if self._prev_ofi_sign != 0 and current_sign != self._prev_ofi_sign:
                    is_reversal = True
                self._prev_ofi_sign = current_sign

            # Store reversal flag (rolling window = long_window entries)
            self._reversal_flags.append(is_reversal)
            if len(self._reversal_flags) > self._long_window:
                self._reversal_flags.pop(0)

            reversal_count = sum(self._reversal_flags)
            if reversal_count >= self._max_reversals:
                self._block("OFI_REVERSAL_STORM")

    def is_blocked(self, current_time=None) -> bool:
        """Return True if the guard is currently blocking."""
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts=None) -> bool:
        """Delegates to is_blocked (no volume info available from spread alone)."""
        return self.is_blocked(current_time=ts)

    def reset(self) -> None:
        """Clear all state."""
        with self._lock:
            self._signed_vols.clear()
            self._reversal_flags.clear()
            self._prev_ofi_sign = 0
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        """Return the reason for the most recent block (empty if never blocked)."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _block(self, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
