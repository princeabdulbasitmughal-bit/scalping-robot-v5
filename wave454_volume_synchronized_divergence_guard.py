"""
Wave 454: Volume-Synchronized Cross-Exchange Divergence Guard
============================================================
Institutional Quantitative Mathematical Formulation:
Under Easley, de Prado & O'Hara (2012) "Flow Toxicity and Liquidity in a High-Frequency World"
and Budish, Cramton & Shim (2015) "The High-Frequency Trading Arms Race",
cross-venue arbitrage across fragmented electronic markets operates on volume clocks.

Let P_1(t) be the primary execution venue midprice (e.g. MT5 broker feed) and P_2(t) be
the institutional reference ECN/futures midprice.
The instantaneous logarithmic basis divergence is:
    Delta_basis(t) = ln P_1(t) - ln P_2(t)

Under volume-synchronized sampling across rolling volume V:
    mu_basis = sum(w_i * Delta_basis,i) / sum(w_i)
    sigma_basis = sqrt(sum(w_i * (Delta_basis,i - mu_basis)^2) / sum(w_i))

The volume-synchronized divergence z-score is:
    Z_div(t) = |Delta_basis(t) - mu_basis| / max(sigma_basis, epsilon)

When:
1. Z_div(t) exceeds max_divergence_zscore (default: > 2.80 sigma), or
2. Absolute basis divergence |Delta_basis| exceeds max_basis_bps_threshold (default: > 15.0 bps),
an acute cross-venue information dislocation or toxic latency arbitrage attack is occurring.

This signals that one venue has stale quotes or has been swept by an informed institutional order
not yet reflected on the sister venue. The guard locks out trade execution on the lagging book.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave454VolumeSynchronizedDivergenceGuard:
    """
    Evaluates volume-synchronized cross-exchange basis divergence Z_div and basis spread
    to prevent adverse selection against stale quotes and predatory latency arbitrage.
    """

    def __init__(
        self,
        window_size: int = 30,
        max_divergence_zscore: float = 2.80,
        max_basis_bps_threshold: float = 15.0,
        min_samples: int = 10
    ) -> None:
        if window_size < 10:
            raise ValueError(f"window_size must be >= 10, got {window_size}")
        if max_divergence_zscore <= 1.0:
            raise ValueError(f"max_divergence_zscore must be > 1.0, got {max_divergence_zscore}")
        if max_basis_bps_threshold <= 1.0:
            raise ValueError(f"max_basis_bps_threshold must be > 1.0 bps, got {max_basis_bps_threshold}")

        self.window_size: int = window_size
        self.max_divergence_zscore: float = max_divergence_zscore
        self.max_basis_bps_threshold: float = max_basis_bps_threshold
        self.min_samples: int = min_samples

        # Ring buffers: basis divergences, volumes, timestamps
        self._basis_history: List[float] = []
        self._volume_history: List[float] = []
        self._timestamps: List[float] = []

        # Current state
        self.current_basis_bps: float = 0.0
        self.divergence_zscore: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""

    def update(
        self,
        primary_price: float,
        reference_price: float,
        volume: float,
        timestamp: float
    ) -> bool:
        """
        Record simultaneous primary price, reference venue price, trade volume, and timestamp.
        Returns True if trading is blocked, False otherwise.
        """
        if primary_price <= 0.0 or not math.isfinite(primary_price):
            raise ValueError(f"primary_price must be positive and finite, got {primary_price}")
        if reference_price <= 0.0 or not math.isfinite(reference_price):
            raise ValueError(f"reference_price must be positive and finite, got {reference_price}")
        if volume <= 0.0 or not math.isfinite(volume):
            raise ValueError(f"volume must be positive and finite, got {volume}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        # Basis in basis points (1 bp = 0.0001 = 0.01%)
        basis_bps = (math.log(primary_price) - math.log(reference_price)) * 10000.0
        self.current_basis_bps = basis_bps

        self._basis_history.append(basis_bps)
        self._volume_history.append(float(volume))
        self._timestamps.append(float(timestamp))

        if len(self._basis_history) > self.window_size:
            self._basis_history.pop(0)
            self._volume_history.pop(0)
            self._timestamps.pop(0)

        if len(self._basis_history) < self.min_samples:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLE"
            return False

        b_arr = np.array(self._basis_history, dtype=np.float64)
        v_arr = np.array(self._volume_history, dtype=np.float64)

        # Volume-weighted mean and standard deviation
        v_sum = np.sum(v_arr)
        if v_sum < 1e-12:
            self.divergence_zscore = 0.0
            self._is_blocked = False
            return False

        mu_b = np.sum(b_arr * v_arr) / v_sum
        var_b = np.sum(v_arr * (b_arr - mu_b) ** 2) / v_sum
        sigma_b = math.sqrt(max(1e-8, var_b))

        self.divergence_zscore = float(abs(basis_bps - mu_b) / sigma_b)

        # Safety evaluation
        if abs(basis_bps) > self.max_basis_bps_threshold:
            self._is_blocked = True
            self._block_reason = (
                f"ABSOLUTE_BASIS_DISLOCATION: Basis {abs(basis_bps):.1f} bps > "
                f"threshold {self.max_basis_bps_threshold:.1f} bps (stale quote mismatch)"
            )
        elif self.divergence_zscore > self.max_divergence_zscore:
            self._is_blocked = True
            self._block_reason = (
                f"CROSS_VENUE_STATISTICAL_ARBITRAGE_SHOCK: Z-score {self.divergence_zscore:.2f} > "
                f"cap {self.max_divergence_zscore:.2f} (volume-synchronized divergence)"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Volume-Synchronized Divergence Guard."""
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
            "guard": "Wave454VolumeSynchronizedDivergenceGuard",
            "current_basis_bps": round(self.current_basis_bps, 3),
            "divergence_zscore": round(self.divergence_zscore, 3),
            "max_divergence_zscore": self.max_divergence_zscore,
            "max_basis_bps_threshold": self.max_basis_bps_threshold,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._basis_history)
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._basis_history.clear()
        self._volume_history.clear()
        self._timestamps.clear()
        self.current_basis_bps = 0.0
        self.divergence_zscore = 0.0
        self._is_blocked = False
        self._block_reason = ""
