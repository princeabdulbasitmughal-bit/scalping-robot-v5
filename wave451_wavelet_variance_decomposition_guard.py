"""
Wave 451: Multi-Scale Wavelet Variance Decomposition Guard
==========================================================
Institutional Quantitative Mathematical Formulation:
Under Percival & Walden (2000) "Wavelet Methods for Time Series Analysis" and
Gençay, Selçuk & Whitcher (2001) "An Introduction to Wavelets in Finance",
market price discovery is intrinsically multi-scale:
- Scale 1 (tau_1 = 1-2 ticks): High-frequency microstructure noise, bid-ask bounce, and toxic tick bounce.
- Scale 2 (tau_2 = 2-4 ticks): Short-term liquidity replenishment and local queue flow.
- Scale 3 (tau_3 = 4-8 ticks): Intermediate directional momentum and informed order flow.

The Maximal Overlap Discrete Wavelet Transform (MODWT) with Haar filters decomposes
the total realized return variance sigma^2 into octave-band scale wavelet variances:
    sigma^2 = sum_{j=1}^J nu_j^2 + r_J^2

Where:
    W_{j, t} = sum_{l=0}^{L_j-1} h_{j, l} * r_{t-l}
    nu_j^2 = (1 / N) * sum_{t} W_{j, t}^2

The high-frequency microstructural noise energy ratio is:
    E_HF = nu_1^2 / (sum_{j=1}^J nu_j^2 + epsilon)

When E_HF exceeds max_hf_energy_ratio (default: > 0.65), over 65% of all price variance
is concentrated in non-tradable high-frequency microstructure noise rather than genuine
trend or informed flow. The guard blocks execution to prevent adverse selection.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave451WaveletVarianceDecompositionGuard:
    """
    Evaluates multi-scale wavelet variance decomposition across dyadic scales tau_1, tau_2, tau_3
    to detect noise-dominated microstructure regimes and prevent trading on bid-ask jitter.
    """

    def __init__(
        self,
        window_size: int = 32,
        max_hf_energy_ratio: float = 0.65,
        min_samples: int = 16
    ) -> None:
        if window_size < 16:
            raise ValueError(f"window_size must be >= 16, got {window_size}")
        if not (0.30 <= max_hf_energy_ratio <= 0.95):
            raise ValueError(f"max_hf_energy_ratio must be in [0.30, 0.95], got {max_hf_energy_ratio}")

        self.window_size: int = window_size
        self.max_hf_energy_ratio: float = max_hf_energy_ratio
        self.min_samples: int = min_samples

        # Return history and timestamps
        self._returns: List[float] = []
        self._timestamps: List[float] = []

        # Current state
        self.scale_variances: Dict[str, float] = {"scale_1": 0.0, "scale_2": 0.0, "scale_3": 0.0}
        self.hf_energy_ratio: float = 0.0
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

        if len(self._returns) > self.window_size:
            self._returns.pop(0)
            self._timestamps.pop(0)

        if len(self._returns) < self.min_samples:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLE"
            return False

        r_arr = np.array(self._returns, dtype=np.float64)
        n = len(r_arr)

        # Scale 1: Wavelet filter h_1 = [1/2, -1/2] (Haar MODWT)
        w1 = (r_arr[1:] - r_arr[:-1]) / math.sqrt(2.0)
        nu1_sq = float(np.mean(w1 ** 2)) if len(w1) > 0 else 0.0

        # Scale 2: Haar MODWT scale 2 filter (lag 2 differences)
        if n >= 4:
            w2 = (r_arr[2:] - r_arr[:-2]) / 2.0
            nu2_sq = float(np.mean(w2 ** 2))
        else:
            nu2_sq = 0.0

        # Scale 3: Haar MODWT scale 3 filter (lag 4 differences)
        if n >= 8:
            w3 = (r_arr[4:] - r_arr[:-4]) / (2.0 * math.sqrt(2.0))
            nu3_sq = float(np.mean(w3 ** 2))
        else:
            nu3_sq = 0.0

        total_wavelet_var = nu1_sq + nu2_sq + nu3_sq
        self.scale_variances = {
            "scale_1": nu1_sq,
            "scale_2": nu2_sq,
            "scale_3": nu3_sq
        }

        if total_wavelet_var > 1e-12:
            self.hf_energy_ratio = nu1_sq / total_wavelet_var
        else:
            self.hf_energy_ratio = 0.0

        if self.hf_energy_ratio > self.max_hf_energy_ratio:
            self._is_blocked = True
            self._block_reason = (
                f"NOISE_DOMINATED_MICROSTRUCTURE: HF Wavelet Energy Ratio {self.hf_energy_ratio:.1%} > "
                f"threshold {self.max_hf_energy_ratio:.1%} (pure bid-ask bounce regime)"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Wavelet Variance Decomposition Guard."""
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
            "guard": "Wave451WaveletVarianceDecompositionGuard",
            "hf_energy_ratio": round(self.hf_energy_ratio, 4),
            "max_hf_energy_ratio": self.max_hf_energy_ratio,
            "scale_variances": {k: round(v, 8) for k, v in self.scale_variances.items()},
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._returns)
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._returns.clear()
        self._timestamps.clear()
        self.scale_variances = {"scale_1": 0.0, "scale_2": 0.0, "scale_3": 0.0}
        self.hf_energy_ratio = 0.0
        self._is_blocked = False
        self._block_reason = ""
