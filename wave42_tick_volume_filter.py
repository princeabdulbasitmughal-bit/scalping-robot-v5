"""
Wave 42: TickVolumeFilter
Enforces healthy tick velocity before allowing entries:
1. Dead Market Guard: If fewer than min_ticks arrive per window_sec → dead market → block entries.
2. Volume Spike Guard: If ticks exceed max_ticks or surge >= spike_ratio vs baseline → extreme volatility/news surge → block entries with cooldown.
3. Thread-Safe: Protected by threading.RLock to prevent deque mutation exceptions during live MT5 ingestion.
4. Division-by-Zero Protected: Guaranteed zero-denominator guards on all tick and rate metrics.
"""
import time
import math
import logging
import threading
from collections import deque
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_SEC = 10.0         # short rolling window for dead-market check
_DEFAULT_MIN_TICKS = 4             # minimum ticks required in window (dead-market if below)
_DEFAULT_MAX_TICKS = 50            # maximum ticks in window before flagging volume spike (surge ceiling)
_DEFAULT_SPIKE_RATIO = 3.5         # ratio of current rate to baseline rate triggering a spike block
_DEFAULT_BASELINE_SEC = 60.0       # longer look-back window for baseline tick velocity
_DEFAULT_SPIKE_COOLDOWN_SEC = 30.0 # seconds to hold entry block after a tick volume spike
_MAX_HISTORY_TICKS = 1000          # deque buffer cap


class TickVolumeFilter:
    """
    Monitors tick arrival velocity. Blocks entries if:
    - Market is dead (tick velocity < min_ticks).
    - Market is spiking / news shock (tick velocity > max_ticks or surges vs baseline).
    """

    def __init__(
        self,
        window_sec: float = _DEFAULT_WINDOW_SEC,
        min_ticks: int = _DEFAULT_MIN_TICKS,
        max_ticks: int = _DEFAULT_MAX_TICKS,
        spike_ratio_threshold: float = _DEFAULT_SPIKE_RATIO,
        spike_cooldown_sec: float = _DEFAULT_SPIKE_COOLDOWN_SEC,
        baseline_sec: float = _DEFAULT_BASELINE_SEC,
    ) -> None:
        self._window_sec = float(window_sec) if window_sec and window_sec > 0 else _DEFAULT_WINDOW_SEC
        self._min_ticks = int(min_ticks)
        self._max_ticks = int(max_ticks)
        self._spike_ratio_threshold = float(spike_ratio_threshold)
        self._spike_cooldown_sec = float(spike_cooldown_sec)
        self._baseline_sec = float(baseline_sec) if baseline_sec and baseline_sec > 0 else _DEFAULT_BASELINE_SEC

        self._tick_times: deque = deque(maxlen=_MAX_HISTORY_TICKS)
        self._blocked_count: int = 0
        self._spike_blocked_count: int = 0
        self._cooldown_until: float = 0.0
        self._last_block_reason: str = ""
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Reset internal buffers and state."""
        with self._lock:
            self._tick_times.clear()
            self._blocked_count = 0
            self._spike_blocked_count = 0
            self._cooldown_until = 0.0
            self._last_block_reason = ""

    # ------------------------------------------------------------------
    def update(self, now_ts: Optional[float] = None) -> None:
        """Call once per tick to record arrival time."""
        ts = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            self._tick_times.append(ts)

    # ------------------------------------------------------------------
    def _count_ticks_in_window_locked(self, window_sec: float, now_ts: float) -> int:
        """Thread-safe count of ticks arrived in the last window_sec."""
        if not self._tick_times or window_sec <= 0:
            return 0
        cutoff = now_ts - window_sec
        # Snapshot iteration under lock avoids deque mutation error
        return sum(1 for t in self._tick_times if t >= cutoff)

    # ------------------------------------------------------------------
    def is_entry_blocked(self, now_ts: Optional[float] = None) -> bool:
        """
        Return True if:
        1. In volume-spike cooldown period.
        2. Tick velocity is below minimum (dead market).
        3. Tick velocity exceeds maximum or surges vs baseline (volume spike).
        """
        now = time.time() if now_ts is None else float(now_ts)

        with self._lock:
            # 1. Check active spike cooldown
            if now < self._cooldown_until:
                remaining = self._cooldown_until - now
                self._last_block_reason = f"SPIKE_COOLDOWN ({remaining:.1f}s left)"
                self._spike_blocked_count += 1
                return True

            recent = self._count_ticks_in_window_locked(self._window_sec, now)

            # 2. Dead market check (insufficient ticks)
            if recent < self._min_ticks:
                self._blocked_count += 1
                self._last_block_reason = f"DEAD_MARKET ({recent}/{self._min_ticks} ticks in {self._window_sec:.0f}s)"
                logger.debug(
                    f"[TICK VOLUME FILTER] Dead market — only {recent} ticks "
                    f"in last {self._window_sec:.0f}s (min={self._min_ticks})"
                )
                return True

            # 3. Volume spike check (absolute ceiling)
            if self._max_ticks > 0 and recent >= self._max_ticks:
                self._spike_blocked_count += 1
                self._cooldown_until = now + self._spike_cooldown_sec
                self._last_block_reason = f"VOLUME_SPIKE ({recent} >= max {self._max_ticks})"
                logger.warning(
                    f"[TICK VOLUME FILTER] Volume spike detected: {recent} ticks in {self._window_sec:.0f}s "
                    f"(ceiling={self._max_ticks}). Blocking entries for {self._spike_cooldown_sec:.0f}s"
                )
                return True

            # 4. Volume spike check (relative surge vs baseline)
            if self._baseline_sec > self._window_sec and self._spike_ratio_threshold > 0:
                baseline_ticks = self._count_ticks_in_window_locked(self._baseline_sec, now)
                # Division-by-zero safety on baseline ticks and duration
                if baseline_ticks > 0 and self._baseline_sec > 0:
                    recent_rate = recent / self._window_sec
                    baseline_rate = baseline_ticks / self._baseline_sec
                    if baseline_rate > 0.0:
                        ratio = recent_rate / baseline_rate
                        if ratio >= self._spike_ratio_threshold:
                            self._spike_blocked_count += 1
                            self._cooldown_until = now + self._spike_cooldown_sec
                            self._last_block_reason = f"VOLUME_SPIKE_SURGE ({ratio:.1f}x baseline rate)"
                            logger.warning(
                                f"[TICK VOLUME FILTER] Tick surge detected: rate {recent_rate:.1f}/s is {ratio:.1f}x "
                                f"baseline {baseline_rate:.1f}/s. Blocking entries for {self._spike_cooldown_sec:.0f}s"
                            )
                            return True

            self._last_block_reason = ""
            return False

    # ------------------------------------------------------------------
    def get_tick_rate(self, window_sec: Optional[float] = None, now_ts: Optional[float] = None) -> float:
        """
        Returns ticks-per-second rate over window_sec.
        Protected against division-by-zero, non-numeric, and negative/zero window values.
        """
        win = self._window_sec if window_sec is None else float(window_sec)
        if not math.isfinite(win) or win <= 0.0:
            return 0.0

        now = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            recent = self._count_ticks_in_window_locked(win, now)
            # Safe division guaranteed by win > 0.0
            return round(recent / win, 2)

    # ------------------------------------------------------------------
    def get_avg_tick_interval(self, now_ts: Optional[float] = None) -> float:
        """
        Returns average seconds between ticks in the rolling window.
        Safe against tick count division-by-zero when recent == 0.
        """
        now = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            recent = self._count_ticks_in_window_locked(self._window_sec, now)
            if recent <= 0:
                return 0.0
            return round(self._window_sec / recent, 3)

    # ------------------------------------------------------------------
    def get_block_reason(self) -> str:
        """Returns the human-readable reason for the current or most recent block."""
        with self._lock:
            return self._last_block_reason

    # ------------------------------------------------------------------
    def info(self) -> Dict[str, Any]:
        """Telemetry dict compatible with OmniCommand guard monitors."""
        now = time.time()
        with self._lock:
            rate = self.get_tick_rate(self._window_sec, now)
            recent = self._count_ticks_in_window_locked(self._window_sec, now)
            in_cooldown = now < self._cooldown_until
            is_dead = recent < self._min_ticks
            is_spike = (self._max_ticks > 0 and recent >= self._max_ticks) or in_cooldown
            blocked = is_dead or is_spike or in_cooldown

            return {
                "blocked": blocked,
                "entry_blocked": blocked,
                "is_blocked": blocked,
                "block_reason": self._last_block_reason,
                "is_dead_market": is_dead,
                "is_volume_spike": is_spike,
                "spike_cooldown_remaining_sec": max(0.0, round(self._cooldown_until - now, 1)),
                "tick_rate_per_sec": rate,
                "avg_tick_interval_sec": self.get_avg_tick_interval(now),
                "ticks_in_window": recent,
                "window_sec": self._window_sec,
                "min_ticks_required": self._min_ticks,
                "max_ticks_ceiling": self._max_ticks,
                "total_ticks_tracked": len(self._tick_times),
                "blocked_count_total": self._blocked_count,
                "spike_blocked_count_total": self._spike_blocked_count,
            }


# Module-level singleton
tick_volume_filter = TickVolumeFilter()
