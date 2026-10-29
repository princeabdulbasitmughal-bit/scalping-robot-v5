"""
Wave 447: Limit Order Queue Cancellation Intensity Hazard Guard
==============================================================
Institutional Quantitative Mathematical Formulation:
In ultra-low-latency electronic order books (Cont & de Larrard 2013, Bouchaud et al. 2002),
over 80-90% of order messages represent cancellations rather than trade executions.
However, extreme spikes in the cancellation-to-fill ratio or arrival intensity of cancellations
frequently precede toxic quote stuffing, phantom liquidity pullbacks, and predatory spoofing.

Let V_cancel(t, Delta) be the cumulative cancelled volume and V_fill(t, Delta) be the
cumulative filled/executed volume across sliding window Delta:
    R_cancel = V_cancel / (V_cancel + V_fill + epsilon)

Let N_cancel be the number of cancellation events in time interval Delta_t:
    lambda_cancel = N_cancel / max(Delta_t, epsilon)

The guard engages an immediate protective lockout when:
1. R_cancel exceeds max_cancellation_ratio (e.g. > 0.85) over an active observation sample,
   signalling that posted liquidity is predominantly phantom and subject to immediate eviction.
2. lambda_cancel exceeds max_cancellation_intensity (e.g. > 60 cancels/sec),
   indicating quote stuffing or hyperactive algorithmic baiting.
"""

import math
from typing import List, Dict, Any, Optional


class Wave447QueueCancellationIntensityGuard:
    """
    Monitors limit order queue cancellations, execution ratios, and cancellation hazard rates
    to guard against phantom liquidity, quote stuffing, and spoofing pullbacks.
    """

    def __init__(
        self,
        window_size: int = 40,
        max_cancellation_ratio: float = 0.85,
        max_cancellation_intensity: float = 50.0,
        min_events_for_decision: int = 10
    ) -> None:
        if window_size < 10:
            raise ValueError(f"window_size must be >= 10, got {window_size}")
        if not (0.50 <= max_cancellation_ratio < 1.0):
            raise ValueError(f"max_cancellation_ratio must be in [0.50, 1.0), got {max_cancellation_ratio}")
        if max_cancellation_intensity <= 0.0:
            raise ValueError(f"max_cancellation_intensity must be > 0.0, got {max_cancellation_intensity}")

        self.window_size: int = window_size
        self.max_cancellation_ratio: float = max_cancellation_ratio
        self.max_cancellation_intensity: float = max_cancellation_intensity
        self.min_events_for_decision: int = min_events_for_decision

        # Internal event ring buffers: (event_type, volume, timestamp)
        self._events: List[Dict[str, Any]] = []
        self._last_timestamp: float = 0.0

        # State outputs
        self.cancellation_ratio: float = 0.0
        self.cancellation_intensity: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""

    def update(self, event_type: str, volume: float, timestamp: float) -> bool:
        """
        Record a queue event: 'CANCEL', 'FILL', or 'LIMIT'.
        Returns True if trading is blocked, False otherwise.
        """
        norm_type = str(event_type).strip().upper()
        if norm_type not in ("CANCEL", "FILL", "LIMIT"):
            raise ValueError(f"event_type must be one of ('CANCEL', 'FILL', 'LIMIT'), got {event_type}")
        if volume <= 0.0 or not math.isfinite(volume):
            raise ValueError(f"volume must be positive and finite, got {volume}")
        if self._events and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp
        self._events.append({
            "type": norm_type,
            "volume": float(volume),
            "timestamp": float(timestamp)
        })

        if len(self._events) > self.window_size:
            self._events.pop(0)

        if len(self._events) < self.min_events_for_decision:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLE"
            return False

        # Compute volume sums
        cancel_vol = sum(e["volume"] for e in self._events if e["type"] == "CANCEL")
        fill_vol = sum(e["volume"] for e in self._events if e["type"] == "FILL")
        total_vol = cancel_vol + fill_vol

        # Cancellation ratio
        if total_vol > 1e-8:
            self.cancellation_ratio = cancel_vol / total_vol
        else:
            self.cancellation_ratio = 0.0

        # Cancellation arrival intensity (cancels per second)
        t_start = self._events[0]["timestamp"]
        t_span = max(1e-4, timestamp - t_start)
        cancel_count = sum(1 for e in self._events if e["type"] == "CANCEL")
        self.cancellation_intensity = cancel_count / t_span

        # Evaluate safety invariants
        if self.cancellation_ratio > self.max_cancellation_ratio and cancel_count >= 5:
            self._is_blocked = True
            self._block_reason = (
                f"PHANTOM_LIQUIDITY_HAZARD: Cancellation ratio {self.cancellation_ratio:.2%} > "
                f"threshold {self.max_cancellation_ratio:.2%} (aggressive order pulling)"
            )
        elif self.cancellation_intensity > self.max_cancellation_intensity and cancel_count >= 8:
            self._is_blocked = True
            self._block_reason = (
                f"QUOTE_STUFFING_BURST: Cancellation intensity {self.cancellation_intensity:.1f} events/s > "
                f"cap {self.max_cancellation_intensity:.1f} events/s"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Queue Cancellation Intensity Guard."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave447QueueCancellationIntensityGuard",
            "cancellation_ratio": round(self.cancellation_ratio, 4),
            "cancellation_intensity_hz": round(self.cancellation_intensity, 2),
            "max_cancellation_ratio": self.max_cancellation_ratio,
            "max_cancellation_intensity": self.max_cancellation_intensity,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "events_buffered": len(self._events)
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._events.clear()
        self._last_timestamp = 0.0
        self.cancellation_ratio = 0.0
        self.cancellation_intensity = 0.0
        self._is_blocked = False
        self._block_reason = ""
