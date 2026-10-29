"""
Wave 452: High-Frequency Order Arrival Poisson Burst Hazard Guard
================================================================
Institutional Quantitative Mathematical Formulation:
Under Engle & Russell (1998) "Autoregressive Conditional Duration" and
Goh & Barabási (2008) "Burstiness and Memory in Complex Systems",
normal high-frequency order arrivals follow a quasi-Poisson point process where
inter-arrival durations X_i = t_i - t_{i-1} possess an exponential-like distribution
with coefficient of variation c_v = sigma_X / mu_X ~ 1.0.

The Goh-Barabási burstiness index is defined on [-1, 1]:
    B = (sigma_X - mu_X) / (sigma_X + mu_X)

- Poisson baseline: B ~ 0.0 (regular random arrivals)
- Deterministic queue: B -> -1.0 (equispaced periodic ticks)
- Predatory HFT Burst / Quote Sweeping: B -> +1.0 (heavy clustering with long pauses)

The instantaneous burst intensity across the last k arrivals:
    lambda_burst(t) = (k - 1) / max(t_now - t_{now - k + 1}, epsilon)

The guard engages an immediate protective lockout when:
1. Burstiness index B > max_burstiness_threshold (default: > 0.60), signalling heavy-tailed
   clustering and predatory liquidity sweeping.
2. Burst arrival intensity lambda_burst > max_arrival_intensity (default: > 80.0 arrivals/sec),
   indicating aggressive algorithmic order flooding.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave452PoissonBurstHazardGuard:
    """
    Evaluates order arrival point-process dynamics, Goh-Barabási burstiness index B,
    and instantaneous arrival intensity lambda to guard against predatory liquidity sweeps.
    """

    def __init__(
        self,
        window_size: int = 30,
        burst_k: int = 8,
        max_burstiness_threshold: float = 0.60,
        max_arrival_intensity: float = 80.0,
        min_events_for_decision: int = 12
    ) -> None:
        if window_size < 15:
            raise ValueError(f"window_size must be >= 15, got {window_size}")
        if burst_k < 4 or burst_k >= window_size:
            raise ValueError(f"burst_k must be in [4, window_size), got {burst_k}")
        if not (0.20 <= max_burstiness_threshold <= 0.95):
            raise ValueError(f"max_burstiness_threshold must be in [0.20, 0.95], got {max_burstiness_threshold}")
        if max_arrival_intensity <= 1.0:
            raise ValueError(f"max_arrival_intensity must be > 1.0, got {max_arrival_intensity}")

        self.window_size: int = window_size
        self.burst_k: int = burst_k
        self.max_burstiness_threshold: float = max_burstiness_threshold
        self.max_arrival_intensity: float = max_arrival_intensity
        self.min_events_for_decision: int = min_events_for_decision

        # Timestamps and inter-arrival durations
        self._timestamps: List[float] = []
        self._durations: List[float] = []

        # Current state
        self.burstiness_index: float = 0.0
        self.burst_intensity_hz: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""

    def update(self, timestamp: float) -> bool:
        """
        Record a new order arrival event timestamp.
        Returns True if trading is blocked, False otherwise.
        """
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        if self._timestamps:
            dt = timestamp - self._timestamps[-1]
            self._durations.append(float(dt))
            if len(self._durations) > self.window_size:
                self._durations.pop(0)

        self._timestamps.append(float(timestamp))
        if len(self._timestamps) > self.window_size + 1:
            self._timestamps.pop(0)

        if len(self._durations) < self.min_events_for_decision:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_EVENTS"
            return False

        d_arr = np.array(self._durations, dtype=np.float64)
        mu_d = float(np.mean(d_arr))
        sigma_d = float(np.std(d_arr))

        # Goh-Barabási burstiness index B = (sigma - mu) / (sigma + mu)
        if (sigma_d + mu_d) > 1e-12:
            self.burstiness_index = float((sigma_d - mu_d) / (sigma_d + mu_d))
        else:
            self.burstiness_index = 0.0

        # Burst intensity across latest burst_k arrivals
        recent_ts = self._timestamps[-self.burst_k:]
        recent_span = max(1e-5, recent_ts[-1] - recent_ts[0])
        self.burst_intensity_hz = float((len(recent_ts) - 1) / recent_span)

        # Safety evaluation
        if self.burstiness_index > self.max_burstiness_threshold:
            self._is_blocked = True
            self._block_reason = (
                f"PREDATORY_BURST_CLUSTERING: Burstiness index B={self.burstiness_index:.3f} > "
                f"threshold {self.max_burstiness_threshold:.3f} (heavy-tailed arrival shock)"
            )
        elif self.burst_intensity_hz > self.max_arrival_intensity:
            self._is_blocked = True
            self._block_reason = (
                f"HFT_ORDER_FLOODING_BURST: Arrival intensity {self.burst_intensity_hz:.1f} events/s > "
                f"cap {self.max_arrival_intensity:.1f} events/s"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Poisson Burst Hazard Guard."""
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
            "guard": "Wave452PoissonBurstHazardGuard",
            "burstiness_index": round(self.burstiness_index, 4),
            "burst_intensity_hz": round(self.burst_intensity_hz, 2),
            "max_burstiness_threshold": self.max_burstiness_threshold,
            "max_arrival_intensity": self.max_arrival_intensity,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "events_tracked": len(self._durations)
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._timestamps.clear()
        self._durations.clear()
        self.burstiness_index = 0.0
        self.burst_intensity_hz = 0.0
        self._is_blocked = False
        self._block_reason = ""
