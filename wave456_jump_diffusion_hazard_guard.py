"""
Wave 456: Jump-Diffusion Hazard Rate Circuit Breaker Guard
=========================================================
Institutional Quantitative Mathematical Formulation:
Under Merton (1976) "Option Pricing When Underlying Stock Returns Are Discontinuous",
Kou (2002), and Mancini (2009) "Non-parametric Threshold Estimation for Jump-Diffusions",
asset price returns r(t) decompose into a continuous Brownian diffusion component
and a discontinuous compound Poisson jump process:
    r(t) = mu * dt + sigma_diff * dW(t) + sum_{k=1}^{N(t)} J_k

Where:
- sigma_diff is the continuous diffusion volatility (estimated via Median Absolute Deviation).
- N(t) is a Poisson jump counter with jump arrival hazard rate lambda_jump.
- J_k is the random jump amplitude.

Under threshold estimation, a discrete return observation r_i is classified as a jump if:
    |r_i| > alpha_jump * max(sigma_diff, epsilon)

The local jump arrival hazard rate across the active jump cluster is:
    lambda_jump = (N_jumps - 1) / max(t_last_jump - t_first_jump, epsilon)   (for N_jumps >= 2)
    or N_jumps / max(t_span_window, epsilon)

The jump quadratic variation ratio is:
    R_jump = sum_{i in Jumps} r_i^2 / (sum_{all i} r_i^2 + epsilon)

When:
1. Jump arrival hazard rate lambda_jump > max_jump_intensity (default: > 2.0 jumps/sec), or
2. Jump quadratic variation ratio R_jump > max_jump_variance_ratio (default: > 0.40),
the price process is dominated by discrete discontinuous jumps rather than continuous diffusion.

Under discontinuous jump dominance, linear risk hedging, stop-loss orders, and delta-neutral
market making break down entirely. The guard triggers an immediate emergency circuit breaker.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave456JumpDiffusionHazardGuard:
    """
    Evaluates jump-diffusion hazard arrival rates lambda_jump and jump variance ratio R_jump
    to guard against discontinuous price gapping and flash microstructure crashes.
    """

    def __init__(
        self,
        window_size: int = 30,
        jump_sigma_multiplier: float = 3.0,
        max_jump_intensity: float = 2.0,
        max_jump_variance_ratio: float = 0.40,
        min_samples: int = 12
    ) -> None:
        if window_size < 15:
            raise ValueError(f"window_size must be >= 15, got {window_size}")
        if jump_sigma_multiplier < 1.5:
            raise ValueError(f"jump_sigma_multiplier must be >= 1.5, got {jump_sigma_multiplier}")
        if max_jump_intensity <= 0.1:
            raise ValueError(f"max_jump_intensity must be > 0.1, got {max_jump_intensity}")
        if not (0.10 <= max_jump_variance_ratio <= 0.90):
            raise ValueError(f"max_jump_variance_ratio must be in [0.10, 0.90], got {max_jump_variance_ratio}")

        self.window_size: int = window_size
        self.jump_sigma_multiplier: float = jump_sigma_multiplier
        self.max_jump_intensity: float = max_jump_intensity
        self.max_jump_variance_ratio: float = max_jump_variance_ratio
        self.min_samples: int = min_samples

        # Ring buffers: returns, timestamps, jump flags
        self._returns: List[float] = []
        self._timestamps: List[float] = []
        self._is_jump: List[bool] = []

        # Current state
        self.jump_intensity_hz: float = 0.0
        self.jump_variance_ratio: float = 0.0
        self.continuous_sigma: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""

    def update(self, log_return: float, timestamp: float) -> bool:
        """
        Record a new tick log-return and timestamp.
        Returns True if trading is blocked, False otherwise.
        """
        if not math.isfinite(log_return):
            raise ValueError(f"log_return must be finite, got {log_return}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        self._returns.append(float(log_return))
        self._timestamps.append(float(timestamp))

        # Maintain window size
        if len(self._returns) > self.window_size:
            self._returns.pop(0)
            self._timestamps.pop(0)
            if self._is_jump:
                self._is_jump.pop(0)

        if len(self._returns) < self.min_samples:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLE"
            return False

        r_arr = np.array(self._returns, dtype=np.float64)

        # Robust continuous diffusion volatility via Median Absolute Deviation (MAD / 0.6745)
        # completely immune to jump contamination
        med_r = np.median(r_arr)
        mad = np.median(np.abs(r_arr - med_r))
        self.continuous_sigma = max(1e-8, float(mad / 0.6745))

        # Threshold jump classification
        jump_cutoff = self.jump_sigma_multiplier * self.continuous_sigma
        self._is_jump = [abs(r) > jump_cutoff for r in self._returns]

        jump_indices = [i for i, j in enumerate(self._is_jump) if j]
        n_jumps = len(jump_indices)

        # Calculate cluster jump arrival intensity
        if n_jumps >= 2:
            t_cluster = max(1e-4, self._timestamps[jump_indices[-1]] - self._timestamps[jump_indices[0]])
            self.jump_intensity_hz = float((n_jumps - 1) / t_cluster)
        else:
            self.jump_intensity_hz = 0.0

        # Calculate jump quadratic variation ratio
        total_qv = float(np.sum(r_arr ** 2))
        jump_qv = float(sum(r_arr[i] ** 2 for i in jump_indices))

        if total_qv > 1e-12:
            self.jump_variance_ratio = float(jump_qv / total_qv)
        else:
            self.jump_variance_ratio = 0.0

        # Safety evaluation: evaluate arrival hazard burst first, then quadratic variation ratio
        if self.jump_intensity_hz > self.max_jump_intensity and n_jumps >= 3:
            self._is_blocked = True
            self._block_reason = (
                f"JUMP_ARRIVAL_HAZARD_BURST: Jump intensity {self.jump_intensity_hz:.1f} jumps/s > "
                f"threshold {self.max_jump_intensity:.1f} jumps/s"
            )
        elif self.jump_variance_ratio > self.max_jump_variance_ratio and n_jumps >= 2:
            self._is_blocked = True
            self._block_reason = (
                f"DISCONTINUOUS_JUMP_DOMINANCE: Jump variance ratio {self.jump_variance_ratio:.1%} > "
                f"cap {self.max_jump_variance_ratio:.1%} ({n_jumps} jumps detected)"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Jump Diffusion Hazard Guard."""
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
            "guard": "Wave456JumpDiffusionHazardGuard",
            "jump_intensity_hz": round(self.jump_intensity_hz, 3),
            "jump_variance_ratio": round(self.jump_variance_ratio, 4),
            "continuous_sigma": round(self.continuous_sigma, 6),
            "max_jump_intensity": self.max_jump_intensity,
            "max_jump_variance_ratio": self.max_jump_variance_ratio,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._returns)
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._returns.clear()
        self._timestamps.clear()
        self._is_jump.clear()
        self.jump_intensity_hz = 0.0
        self.jump_variance_ratio = 0.0
        self.continuous_sigma = 0.0
        self._is_blocked = False
        self._block_reason = ""
