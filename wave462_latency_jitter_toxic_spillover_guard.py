"""
Wave 462: High-Frequency Latency Jitter Toxic Spillover Guard
============================================================
Institutional Quantitative Mathematical Formulation:
Under Budish, Cramton & Shim (2015) "The High-Frequency Trading Arms Race",
Moallemi & Saglam (2013) "The Cost of Latency in High-Frequency Trading",
and Hasbrouck & Saar (2013) "Low-Latency Trading", execution queue delay
and feed timestamp packet dispersion introduce toxic latency arbitrage risk.

Let L_i be the round-trip or tick-to-signal execution latency observation (in milliseconds).
Across a rolling window of N latency samples {L_1, ..., L_N}:
1. Mean and Dispersion:
    mu_L = mean(L)
    sigma_L = std(L)
    CV_L = sigma_L / max(mu_L, 1e-4)   (Coefficient of Latency Variation / Jitter)

2. Robust Tail Jitter Score:
    med_L = median(L)
    MAD_L = median(|L - med_L|) / 0.6745
    robust_scale = max(MAD_L, sigma_L * 0.5, 0.5)
    Z_tail = (max(L) - med_L) / robust_scale

In high-speed algorithmic market making, execution profitability relies on low,
deterministic queue latency. When network buffers or broker bridge threads suffer jitter:
- Slow Fills / Execution Delays: Fast latency-arbitrage competitors pick off resting limit orders.
- Stale Signal Execution: Signals based on delayed market data trade into adverse selection.

Circuit Breaker Triggers:
1. Hard Latency Ceiling Breach:
   mu_L > max_mean_latency_ms (default: > 25.0 ms)
2. Outlier Packet Dispersion Spike:
   Z_tail > max_tail_z (default: > 5.00 sigma) and max(L) > 10.0 ms
3. Latency Jitter Explosion:
   CV_L > max_jitter_cv (default: > 0.80) and sigma_L > min_jitter_ms (default: > 4.0 ms)

When latency jitter exceeds institutional thresholds, the guard halts aggressive dispatch
and cancels vulnerable resting quotes until packet arrivals return to deterministic regimes.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave462LatencyJitterToxicSpilloverGuard:
    """
    Monitors execution round-trip latency, packet dispersion, and jitter variance
    to protect against toxic latency arbitrage and stale-quote adverse selection.
    """

    def __init__(
        self,
        window_size: int = 25,
        max_jitter_cv: float = 0.80,
        min_jitter_ms: float = 4.0,
        max_tail_z: float = 5.00,
        max_mean_latency_ms: float = 25.0,
        min_samples: int = 10,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_size < 12:
            raise ValueError(f"window_size must be >= 12, got {window_size}")
        if not (0.30 <= max_jitter_cv <= 3.0):
            raise ValueError(f"max_jitter_cv must be in [0.30, 3.0], got {max_jitter_cv}")
        if min_jitter_ms <= 0.5:
            raise ValueError(f"min_jitter_ms must be > 0.5, got {min_jitter_ms}")
        if max_tail_z <= 2.0:
            raise ValueError(f"max_tail_z must be > 2.0, got {max_tail_z}")
        if max_mean_latency_ms <= 2.0:
            raise ValueError(f"max_mean_latency_ms must be > 2.0, got {max_mean_latency_ms}")
        if min_samples < 8:
            raise ValueError(f"min_samples must be >= 8, got {min_samples}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_size: int = window_size
        self.max_jitter_cv: float = max_jitter_cv
        self.min_jitter_ms: float = min_jitter_ms
        self.max_tail_z: float = max_tail_z
        self.max_mean_latency_ms: float = max_mean_latency_ms
        self.min_samples: int = min_samples
        self.cooldown_sec: float = cooldown_sec

        # Ring buffers
        self._latencies: List[float] = []
        self._timestamps: List[float] = []

        # State telemetry
        self.mean_latency_ms: float = 0.0
        self.latency_std_ms: float = 0.0
        self.jitter_cv: float = 0.0
        self.tail_z_score: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(self, latency_ms: float, timestamp: float) -> bool:
        """
        Record a new execution or packet round-trip latency observation in milliseconds.
        Returns True if trading is blocked, False otherwise.
        """
        if not math.isfinite(latency_ms) or latency_ms < 0.0:
            raise ValueError(f"latency_ms must be non-negative and finite, got {latency_ms}")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        self._latencies.append(float(latency_ms))
        self._timestamps.append(float(timestamp))

        # Maintain window size
        if len(self._latencies) > self.window_size:
            self._latencies.pop(0)
            self._timestamps.pop(0)

        # Check cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        if len(self._latencies) < self.min_samples:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLES"
            return False

        lat_arr = np.array(self._latencies, dtype=np.float64)
        self.mean_latency_ms = float(np.mean(lat_arr))
        self.latency_std_ms = float(np.std(lat_arr))
        self.jitter_cv = float(self.latency_std_ms / max(self.mean_latency_ms, 1e-4))

        # Robust Tail Z-score via MAD with floor fallback
        med = float(np.median(lat_arr))
        raw_mad = float(np.median(np.abs(lat_arr - med)) / 0.6745)
        robust_scale = max(raw_mad, self.latency_std_ms * 0.5, 0.5)
        self.tail_z_score = float((np.max(lat_arr) - med) / robust_scale)

        # Evaluate Circuit Breakers in priority order:
        ceiling_breached = (self.mean_latency_ms > self.max_mean_latency_ms)
        tail_spike = (self.tail_z_score > self.max_tail_z and np.max(lat_arr) > 10.0)
        jitter_burst = (self.jitter_cv > self.max_jitter_cv and self.latency_std_ms > self.min_jitter_ms)

        if ceiling_breached:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"LATENCY_CEILING_BREACH: Mean latency={self.mean_latency_ms:.2f}ms > "
                f"ceiling {self.max_mean_latency_ms:.2f}ms"
            )
        elif tail_spike:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"PACKET_DISPERSION_SPIKE: Tail Z={self.tail_z_score:.2f}sigma > {self.max_tail_z:.2f}sigma "
                f"(max_lat={np.max(lat_arr):.2f}ms)"
            )
        elif jitter_burst:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"LATENCY_JITTER_EXPLOSION: CV={self.jitter_cv:.2f} > {self.max_jitter_cv:.2f}, "
                f"sigma={self.latency_std_ms:.2f}ms > {self.min_jitter_ms:.2f}ms (mean={self.mean_latency_ms:.2f}ms)"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Blocks all entries when active."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave462LatencyJitterToxicSpilloverGuard",
            "mean_latency_ms": round(self.mean_latency_ms, 3),
            "latency_std_ms": round(self.latency_std_ms, 3),
            "jitter_cv": round(self.jitter_cv, 3),
            "tail_z_score": round(self.tail_z_score, 3),
            "max_jitter_cv": self.max_jitter_cv,
            "max_mean_latency_ms": self.max_mean_latency_ms,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._latencies)
        }

    def reset(self) -> None:
        """Reset internal buffers and state."""
        self._latencies.clear()
        self._timestamps.clear()
        self.mean_latency_ms = 0.0
        self.latency_std_ms = 0.0
        self.jitter_cv = 0.0
        self.tail_z_score = 0.0
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
