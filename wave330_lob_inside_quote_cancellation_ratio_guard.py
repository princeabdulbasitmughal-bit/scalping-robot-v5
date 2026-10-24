"""Wave 330: Limit Order Book Inside-Quote Add-to-Cancel Lifetime Asymmetry & Spoofing Ratio Guard.

Landmark Wave 330 Deployment.

Mathematical and Microstructural Context:
----------------------------------------
In electronic financial markets, predatory market manipulation strategies such as spoofing,
layering, and quote stuffing exploit inside-quote placement to bait other participants into
unfavorable executions (Cartea, Jaimungal & Ricci 2014; Biais, Foucault & Moinas 2015).
These non-bona-fide quotes are characterized by high cancellation frequency and fleeting resting lifetimes:
    Cancellation Ratio: theta_cancel = V_cancel / (V_add + V_cancel)   in [0, 1]
    Resting Lifetime:   tau_life = t_cancel - t_submit

Under legitimate liquidity provision:
1. Limit orders rest in the book until naturally filled or cancelled due to genuine repricing,
   yielding balanced theta_cancel <= 0.70 and substantial resting durations tau_life > 0.5s.

However, during predatory spoofing or quote stuffing regimes:
1. Extreme Cancellation Volume Ratio (theta_cancel >= 0.88 over N >= 20 events with V_total >= 15.0 lots):
   Over 88% of quote updates represent cancellations rather than committed liquidity additions.
2. Fleeting Resting Lifetime Collapse (mean(tau_life) <= 0.08s with cancelled volume >= 12.0 lots):
   Quotes exist for sub-100 millisecond flickers, serving merely to flash phantom liquidity before retreating.
3. Acute Cancellation Barrage:
   A burst of >= 10 consecutive order cancellations with zero intervening additions or fills in dt <= 0.25s.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against spoofed execution pricing.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or negative input trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave330LOBInsideQuoteCancellationRatioGuard:
    """Wave 330: LOB Inside-Quote Cancellation Ratio & Spoofing Guard [Landmark Wave 330]."""

    def __init__(
        self,
        window_size: int = 20,
        cancel_ratio_threshold: float = 0.88,
        min_volume_threshold: float = 15.0,
        fleeting_lifetime_threshold_s: float = 0.08,
        fleeting_min_cancel_volume: float = 12.0,
        acute_barrage_streak_threshold: int = 10,
        acute_barrage_time_window_s: float = 0.25,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 5:
            window_size = 20
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.cancel_ratio_threshold = float(cancel_ratio_threshold)
        self.min_volume_threshold = float(min_volume_threshold)
        self.fleeting_lifetime_threshold_s = float(fleeting_lifetime_threshold_s)
        self.fleeting_min_cancel_volume = float(fleeting_min_cancel_volume)
        self.acute_barrage_streak_threshold = int(acute_barrage_streak_threshold)
        self.acute_barrage_time_window_s = float(acute_barrage_time_window_s)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._events: deque = deque(maxlen=self.window_size)
        self._cancel_lifetimes: deque = deque(maxlen=self.window_size)
        self._cancel_streak: int = 0
        self._cancel_streak_start_time: Optional[float] = None
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_cancel_ratio: float = 0.0
        self._total_events: int = 0
        self._total_violations: int = 0

    def _validate_numeric(self, val: Any) -> Optional[float]:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval

    def record_add(
        self,
        volume: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Record an inside quote placement (addition)."""
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_events += 1
            v_vol = self._validate_numeric(volume)

            if v_vol is None or v_vol <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = f"FAIL_CLOSED: Non-numeric, NaN, or non-positive add volume: {volume}"
                self._total_violations += 1
                return True

            self._events.append(("ADD", v_vol, 0.0))
            self._cancel_streak = 0
            self._cancel_streak_start_time = None

            return self._evaluate_rolling_ratios(now)

    def record_cancel(
        self,
        volume: float,
        resting_lifetime_s: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Record an inside quote cancellation."""
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_events += 1
            v_vol = self._validate_numeric(volume)
            v_life = self._validate_numeric(resting_lifetime_s)

            if v_vol is None or v_life is None or v_vol <= 0.0 or v_life < 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"FAIL_CLOSED: Invalid cancel inputs: vol={volume}, lifetime={resting_lifetime_s}"
                )
                self._total_violations += 1
                return True

            # Track acute cancellation barrage streak
            if self._cancel_streak == 0:
                self._cancel_streak_start_time = now
            self._cancel_streak += 1

            if self._cancel_streak >= self.acute_barrage_streak_threshold and self._cancel_streak_start_time is not None:
                dt = now - self._cancel_streak_start_time
                if dt <= self.acute_barrage_time_window_s:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ACUTE_CANCELLATION_BARRAGE: {self._cancel_streak} consecutive cancels "
                        f"within {dt:.3f}s <= {self.acute_barrage_time_window_s:.3f}s"
                    )
                    self._total_violations += 1
                    return True

            self._events.append(("CANCEL", v_vol, v_life))
            self._cancel_lifetimes.append((v_vol, v_life))

            return self._evaluate_rolling_ratios(now)

    def update(
        self,
        event_type: str,
        volume: float,
        resting_lifetime_s: float = 0.0,
        current_time: Optional[float] = None,
    ) -> bool:
        """Unified update alias: event_type in ('ADD', 'CANCEL')."""
        if str(event_type).upper() == "ADD":
            return self.record_add(volume, current_time)
        elif str(event_type).upper() == "CANCEL":
            return self.record_cancel(volume, resting_lifetime_s, current_time)
        else:
            now = time.monotonic() if current_time is None else float(current_time)
            with self._lock:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = f"FAIL_CLOSED: Invalid event_type: {event_type}"
                self._total_violations += 1
                return True

    def _evaluate_rolling_ratios(self, now: float) -> bool:
        """Internal helper to calculate rolling cancellation ratio and resting lifetime."""
        if len(self._events) >= self.window_size:
            v_add = sum(vol for ev, vol, _ in self._events if ev == "ADD")
            v_cancel = sum(vol for ev, vol, _ in self._events if ev == "CANCEL")
            v_total = v_add + v_cancel

            if v_total > 0.0:
                cancel_ratio = v_cancel / v_total
                self._last_cancel_ratio = cancel_ratio

                # 1. Extreme Cancellation Volume Ratio
                if cancel_ratio >= self.cancel_ratio_threshold and v_total >= self.min_volume_threshold:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"EXTREME_CANCELLATION_RATIO: Cancel ratio {cancel_ratio:.2f} >= "
                        f"{self.cancel_ratio_threshold:.2f} with total volume {v_total:.2f} lots >= {self.min_volume_threshold:.2f}"
                    )
                    self._total_violations += 1
                    return True

            # 2. Fleeting Resting Lifetime Collapse
            if len(self._cancel_lifetimes) >= 8:
                cancels = list(self._cancel_lifetimes)
                total_c_vol = sum(v for v, _ in cancels)
                mean_life = sum(life for _, life in cancels) / len(cancels)

                if mean_life <= self.fleeting_lifetime_threshold_s and total_c_vol >= self.fleeting_min_cancel_volume:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"FLEETING_LIFETIME_COLLAPSE: Mean resting lifetime {mean_life:.4f}s <= "
                        f"{self.fleeting_lifetime_threshold_s:.3f}s with cancel vol {total_c_vol:.2f} lots"
                    )
                    self._total_violations += 1
                    return True

        return now < self._blocked_until

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        """Return True if the guard is currently blocking entries."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            return now < self._blocked_until

    def is_entry_blocked(self, current_time: Optional[float] = None) -> bool:
        """Alias for is_blocked."""
        return self.is_blocked(current_time)

    def reset(self) -> None:
        """Reset internal state and buffers."""
        with self._lock:
            self._events.clear()
            self._cancel_lifetimes.clear()
            self._cancel_streak = 0
            self._cancel_streak_start_time = None
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_cancel_ratio = 0.0
            self._total_events = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            cancels = list(self._cancel_lifetimes)
            mean_life = (sum(life for _, life in cancels) / len(cancels)) if cancels else 1.0

            return {
                "guard_name": "Wave330LOBInsideQuoteCancellationRatioGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "cancel_ratio": round(self._last_cancel_ratio, 4),
                "mean_resting_lifetime_s": round(mean_life, 5),
                "cancel_streak": self._cancel_streak,
                "buffer_fill": len(self._events),
                "total_events": self._total_events,
                "total_violations": self._total_violations,
            }
