"""
Wave 63: Tick Spread Spike Guard
=================================
Detects sudden abnormal spread spikes in real-time tick data.

Logic:
- Maintain a rolling baseline spread (EMA over last N ticks, default N=30)
- If current spread exceeds baseline by `spike_ratio` or more (default 3.0x),
  classify it as a spike and block new entries for `cooldown_seconds` (default 45s)
- Also blocks if spread is NaN, Inf, negative, or zero (fail-closed)
- Minimum ticks before activating baseline (default 10)

API:
    spread_spike_guard.update(spread_pips)
    spread_spike_guard.is_entry_blocked() -> bool
    spread_spike_guard.is_blocked() -> bool
    spread_spike_guard.info() -> dict
"""

import math
import time
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW = 30
_DEFAULT_MIN_TICKS = 10
_DEFAULT_SPIKE_RATIO = 3.0    # spike if spread >= 3x baseline
_DEFAULT_COOLDOWN = 45.0      # seconds of entry lock after a spike
_EMA_ALPHA = 2.0 / (_DEFAULT_WINDOW + 1)


class SpreadSpikeGuard:
    """
    Real-time spread spike detection with cooldown-based entry blocking.
    Thread-safe with RLock. Fail-closed on malformed spread data.
    """

    def __init__(
        self,
        spike_ratio: float = _DEFAULT_SPIKE_RATIO,
        cooldown_seconds: float = _DEFAULT_COOLDOWN,
        min_ticks: int = _DEFAULT_MIN_TICKS,
    ):
        try:
            r = float(spike_ratio)
            self._spike_ratio = max(1.1, r) if math.isfinite(r) else _DEFAULT_SPIKE_RATIO
        except (ValueError, TypeError):
            self._spike_ratio = _DEFAULT_SPIKE_RATIO

        try:
            c = float(cooldown_seconds)
            self._cooldown_seconds = max(1.0, c) if math.isfinite(c) else _DEFAULT_COOLDOWN
        except (ValueError, TypeError):
            self._cooldown_seconds = _DEFAULT_COOLDOWN

        try:
            self._min_ticks = max(1, int(min_ticks))
        except (ValueError, TypeError):
            self._min_ticks = _DEFAULT_MIN_TICKS

        self._ema_spread: float = 0.0
        self._tick_count: int = 0
        self._spike_active: bool = False
        self._spike_deadline: float = 0.0
        self._total_spikes: int = 0
        self._last_spread: float = 0.0
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of all state."""
        with self._lock:
            self._ema_spread = 0.0
            self._tick_count = 0
            self._spike_active = False
            self._spike_deadline = 0.0
            self._total_spikes = 0
            self._last_spread = 0.0

    def _safe_spread(self, spread: Any) -> Optional[float]:
        if spread is None or isinstance(spread, bool):
            return None
        try:
            s = float(spread)
            return s if math.isfinite(s) and s > 0 else None
        except (ValueError, TypeError):
            return None

    def update(self, spread_pips: Any, now: Optional[float] = None) -> None:
        """
        Feed each tick spread (in pips).
        Detects spikes vs rolling EMA baseline and arms cooldown.
        """
        s = self._safe_spread(spread_pips)
        if s is None:
            # Invalid spread — fail-closed: arm a short protective cooldown
            now_ts = now if now is not None else time.monotonic()
            with self._lock:
                if not self._spike_active:
                    self._spike_active = True
                    self._spike_deadline = now_ts + self._cooldown_seconds
                    self._total_spikes += 1
                    logger.warning("[WAVE63] Invalid spread — fail-closed protective lock armed")
            return

        now_ts = now if now is not None else time.monotonic()

        try:
            with self._lock:
                self._last_spread = s
                self._tick_count += 1

                # Expire any active cooldown
                if self._spike_active and now_ts >= self._spike_deadline:
                    self._spike_active = False
                    logger.debug("[WAVE63] Spread spike cooldown expired — entries re-enabled")

                # Update EMA baseline
                if self._tick_count == 1:
                    self._ema_spread = s
                else:
                    alpha = _EMA_ALPHA
                    self._ema_spread = alpha * s + (1 - alpha) * self._ema_spread

                # Check for spike
                if self._tick_count >= self._min_ticks and self._ema_spread > 0:
                    ratio = s / self._ema_spread
                    if ratio >= self._spike_ratio:
                        if not self._spike_active:
                            self._spike_active = True
                            self._total_spikes += 1
                            logger.warning(
                                f"[WAVE63] SPREAD SPIKE: {s:.2f} pips = "
                                f"{ratio:.2f}x baseline {self._ema_spread:.2f} — "
                                f"locking entries for {self._cooldown_seconds:.0f}s"
                            )
                        # Always extend cooldown deadline on spike
                        self._spike_deadline = now_ts + self._cooldown_seconds

        except Exception as exc:
            logger.debug(f"[WAVE63] update error: {exc}")

    def is_entry_blocked(self, now: Optional[float] = None) -> bool:
        """Returns True if a spread spike cooldown is currently active."""
        try:
            now_ts = now if now is not None else time.monotonic()
            with self._lock:
                if self._spike_active and now_ts >= self._spike_deadline:
                    self._spike_active = False
                    logger.debug("[WAVE63] Spread spike cooldown expired on check")
                return self._spike_active
        except Exception:
            return True   # fail-closed

    def is_blocked(self, now: Optional[float] = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(now=now)

    def seconds_remaining(self, now: Optional[float] = None) -> float:
        """Seconds remaining in active cooldown, or 0.0."""
        try:
            now_ts = now if now is not None else time.monotonic()
            with self._lock:
                if self._spike_active:
                    remaining = self._spike_deadline - now_ts
                    return max(0.0, remaining)
                return 0.0
        except Exception:
            return 0.0

    def info(self) -> dict:
        now_ts = time.monotonic()
        with self._lock:
            return {
                "wave": 63,
                "name": "SpreadSpikeGuard",
                "ema_spread_pips": round(self._ema_spread, 4),
                "last_spread_pips": round(self._last_spread, 4),
                "tick_count": self._tick_count,
                "spike_active": self._spike_active,
                "seconds_remaining": round(self.seconds_remaining(now=now_ts), 1),
                "total_spikes": self._total_spikes,
                "spike_ratio_threshold": self._spike_ratio,
                "cooldown_seconds": self._cooldown_seconds,
            }


# Module-level singleton
spread_spike_guard = SpreadSpikeGuard()

# Module-level aliases for risk orchestrator integration
def update(spread_pips: Any, now: Optional[float] = None) -> None:
    spread_spike_guard.update(spread_pips, now=now)

def is_entry_blocked(now: Optional[float] = None) -> bool:
    return spread_spike_guard.is_entry_blocked(now=now)

def is_blocked(now: Optional[float] = None) -> bool:
    return spread_spike_guard.is_blocked(now=now)

def seconds_remaining(now: Optional[float] = None) -> float:
    return spread_spike_guard.seconds_remaining(now=now)

def reset() -> None:
    spread_spike_guard.reset()

def info() -> dict:
    return spread_spike_guard.info()
