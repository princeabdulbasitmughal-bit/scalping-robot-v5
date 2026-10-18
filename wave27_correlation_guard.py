"""
Wave 27: Correlation Guard & Matrix Analyzer
-------------------------------------------
1. Signal Cluster Density:
   Detects when multiple BUY or SELL signals fire in rapid succession (within
   window_sec). Rapid-fire signals indicate choppy/whipsaw conditions.
   
2. Multi-Asset / Multi-Signal Correlation Matrix:
   Computes Pearson correlation across asset price returns or signal streams
   with strict bounds clamping [-1.0, 1.0], zero-variance fallback (preventing
   ZeroDivisionError / NaN), and thread-safe lock-free computation.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def compute_pearson_correlation(
    series_a: Sequence[float],
    series_b: Sequence[float],
) -> float:
    """
    Computes Pearson correlation r between two sequences.
    
    Guarantees:
    - Zero variance in either series returns 0.0 (no division by zero or NaN).
    - Length mismatch or < 2 samples returns 0.0.
    - Non-finite values (NaN/Inf) are filtered or handled safely.
    - Result is strictly clamped to [-1.0, 1.0].
    """
    n_a = len(series_a)
    n_b = len(series_b)
    if n_a < 2 or n_b < 2 or n_a != n_b:
        return 0.0

    # Ensure all elements are clean finite floats
    try:
        clean_a = [float(x) for x in series_a if not isinstance(x, bool)]
        clean_b = [float(x) for x in series_b if not isinstance(x, bool)]
        if len(clean_a) < 2 or len(clean_b) < 2 or len(clean_a) != len(clean_b):
            return 0.0
        if not all(math.isfinite(x) for x in clean_a) or not all(math.isfinite(x) for x in clean_b):
            return 0.0
    except (ValueError, TypeError):
        return 0.0

    n = len(clean_a)
    mean_a = sum(clean_a) / n
    mean_b = sum(clean_b) / n

    var_a = 0.0
    var_b = 0.0
    cov = 0.0

    for x, y in zip(clean_a, clean_b):
        da = x - mean_a
        db = y - mean_b
        cov += da * db
        var_a += da * da
        var_b += db * db

    # Zero variance handling: if either series is flat, correlation is undefined -> return 0.0
    if var_a <= 1e-14 or var_b <= 1e-14:
        return 0.0

    denominator = math.sqrt(var_a * var_b)
    if denominator <= 1e-14:
        return 0.0

    r = cov / denominator
    
    # Strict bounds clamping to [-1.0, 1.0] to guard against IEEE-754 precision drift
    return max(-1.0, min(1.0, r))


class CorrelationGuard:
    """
    Blocks trading when signals arrive too densely (choppy market indicator)
    and provides cross-asset / cross-signal correlation matrix calculations.

    Parameters
    ----------
    window_sec            : rolling window in seconds to count signals
    max_signals_in_window : max signals allowed before triggering cooldown
    cooldown_sec          : block duration after trigger
    max_corr_threshold    : max acceptable correlation before flagging concentration
    """

    def __init__(
        self,
        window_sec: float = 30.0,
        max_signals_in_window: int = 3,
        cooldown_sec: float = 60.0,
        max_corr_threshold: float = 0.85,
    ):
        self._window_sec = float(window_sec) if isinstance(window_sec, (int, float)) and not isinstance(window_sec, bool) and window_sec > 0 else 30.0
        self._max_signals = int(max_signals_in_window) if isinstance(max_signals_in_window, (int, float)) and not isinstance(max_signals_in_window, bool) and max_signals_in_window > 0 else 3
        self._cooldown_sec = float(cooldown_sec) if isinstance(cooldown_sec, (int, float)) and not isinstance(cooldown_sec, bool) and cooldown_sec >= 0 else 60.0
        self._max_corr_threshold = float(max_corr_threshold) if isinstance(max_corr_threshold, (int, float)) and not isinstance(max_corr_threshold, bool) else 0.85

        self._signal_times: deque[float] = deque(maxlen=50)
        self._blocked_until: float = 0.0
        self._total_triggers: int = 0
        self._lock = threading.RLock()

        # Multi-asset price series buffer: symbol -> deque of prices
        self._asset_buffers: Dict[str, deque[float]] = {}
        self._asset_maxlen = 100

    # ------------------------------------------------------------------ #
    #  Public API: Signal Rate Limiting                                  #
    # ------------------------------------------------------------------ #

    def record_signal(self, now_ts: Optional[float] = None) -> None:
        """
        Call this every time a non-HOLD signal is generated.
        Supports optional `now_ts` for deterministic simulation.
        """
        now = float(now_ts) if (now_ts is not None and not isinstance(now_ts, bool)) else time.monotonic()
        with self._lock:
            self._signal_times.append(now)
            self._maybe_trigger_cooldown(now)

    def is_trading_allowed(self, now_ts: Optional[float] = None) -> Tuple[bool, str]:
        """
        Returns (True, "") if clear, or (False, reason) if in cooldown.
        """
        now = float(now_ts) if (now_ts is not None and not isinstance(now_ts, bool)) else time.monotonic()
        with self._lock:
            if now < self._blocked_until:
                remaining = max(0.1, round(self._blocked_until - now, 1))
                reason = (
                    f"CORR_GUARD: choppy market cooldown active ({remaining}s remaining)"
                )
                return False, reason
            return True, ""

    def is_entry_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Unified risk interface check for trade entry blocking."""
        allowed, _ = self.is_trading_allowed(now_ts=now_ts)
        return not allowed

    def is_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(now_ts=now_ts)

    def info(self, now_ts: Optional[float] = None) -> dict:
        """Return status dict for live_status.json."""
        now = float(now_ts) if (now_ts is not None and not isinstance(now_ts, bool)) else time.monotonic()
        with self._lock:
            in_cooldown = now < self._blocked_until
            cutoff = now - self._window_sec
            recent = sum(1 for t in self._signal_times if t >= cutoff)
            return {
                "wave": 27,
                "name": "CorrelationGuard",
                "in_cooldown": in_cooldown,
                "cooldown_remaining_sec": round(max(self._blocked_until - now, 0.0), 1),
                "signals_in_window": recent,
                "window_sec": self._window_sec,
                "max_signals": self._max_signals,
                "total_triggers": self._total_triggers,
            }

    def reset(self) -> None:
        """Thread-safe reset of all runtime state."""
        with self._lock:
            self._signal_times.clear()
            self._blocked_until = 0.0
            self._total_triggers = 0
            self._asset_buffers.clear()

    # ------------------------------------------------------------------ #
    #  Public API: Correlation Matrix & Bounds Engine                    #
    # ------------------------------------------------------------------ #

    def update_asset_price(self, symbol: str, price: float) -> None:
        """Record price tick for cross-asset correlation analysis."""
        if not symbol or isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price):
            return
        with self._lock:
            if symbol not in self._asset_buffers:
                self._asset_buffers[symbol] = deque(maxlen=self._asset_maxlen)
            self._asset_buffers[symbol].append(float(price))

    def compute_correlation_matrix(
        self,
        series_map: Optional[Dict[str, Sequence[float]]] = None,
    ) -> Dict[str, Dict[str, float]]:
        """
        Computes an N x N correlation matrix.
        If series_map is None, uses internal asset buffers.
        
        Guarantees:
        - Diagonal is strictly 1.0.
        - Off-diagonals are clamped to [-1.0, 1.0].
        - Symmetric (corr[A][B] == corr[B][A]).
        - Zero variance series evaluate safely to 0.0.
        """
        if series_map is None:
            with self._lock:
                # Snapshot buffers under lock to prevent lock contention
                data = {sym: list(buf) for sym, buf in self._asset_buffers.items() if len(buf) >= 2}
        else:
            data = {k: list(v) for k, v in series_map.items()}

        symbols = sorted(data.keys())
        matrix: Dict[str, Dict[str, float]] = {s: {} for s in symbols}

        for i, s1 in enumerate(symbols):
            matrix[s1][s1] = 1.0
            for j in range(i + 1, len(symbols)):
                s2 = symbols[j]
                r = compute_pearson_correlation(data[s1], data[s2])
                matrix[s1][s2] = r
                matrix[s2][s1] = r

        return matrix

    def is_correlation_too_high(
        self,
        symbol_a: str,
        symbol_b: str,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, float]:
        """
        Checks if correlation between two registered assets exceeds threshold.
        Returns (is_too_high: bool, correlation: float).
        """
        thresh = threshold if threshold is not None else self._max_corr_threshold
        with self._lock:
            buf_a = list(self._asset_buffers.get(symbol_a, []))
            buf_b = list(self._asset_buffers.get(symbol_b, []))

        r = compute_pearson_correlation(buf_a, buf_b)
        return (abs(r) >= thresh, r)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                  #
    # ------------------------------------------------------------------ #

    def _maybe_trigger_cooldown(self, now: float) -> None:
        """Must be called while holding self._lock."""
        cutoff = now - self._window_sec
        # Prune ancient timestamps to prevent accumulation
        while self._signal_times and self._signal_times[0] < cutoff:
            self._signal_times.popleft()

        recent_times = [t for t in self._signal_times if t >= cutoff]
        if len(recent_times) > self._max_signals:
            if now >= self._blocked_until:
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


def is_entry_blocked(now_ts: Optional[float] = None) -> bool:
    """Module-level risk interface check."""
    return correlation_guard.is_entry_blocked(now_ts=now_ts)


def is_blocked(now_ts: Optional[float] = None) -> bool:
    """Module-level alias for is_entry_blocked."""
    return correlation_guard.is_blocked(now_ts=now_ts)


def is_trading_allowed(now_ts: Optional[float] = None) -> Tuple[bool, str]:
    """Module-level alias for is_trading_allowed."""
    return correlation_guard.is_trading_allowed(now_ts=now_ts)

