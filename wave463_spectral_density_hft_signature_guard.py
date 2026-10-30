"""
Wave 463: Discrete Fourier Spectral Density HFT Signature Guard
===============================================================
Institutional Quantitative Mathematical Formulation:
Under Priestley (1981) "Spectral Analysis and Time Series", Welch (1967),
and Bouchaud, Bonart, Donier & Gerig (2018) "Trades, Quotes and Prices",
high-frequency order flow and microsecond midprice returns x_t possess
distinct spectral frequency representations via Discrete Fourier Transform (DFT):

    X(f_k) = sum_{t=0}^{N-1} x_t * exp(-i * 2 * pi * k * t / N)
    Power Spectral Density: S(f_k) = (1 / N) * |X(f_k)|^2

Where frequencies f_k = k / N for k = 0, ..., N//2 (normalized Nyquist range [0.0, 0.50] cycles/sample).

1. High-Frequency Spectral Energy Ratio:
    P_HF = sum_{f_k >= 0.25} S(f_k) / (sum_{all f_k} S(f_k) + epsilon)

2. Spectral Peak Prominence Ratio:
    Pi_max = max_{f_k > 0}(S(f_k)) / (mean(S(f_k > 0)) + epsilon)

Under normal organic liquidity regimes:
- Order flow is broad-band stochastic pink/Brownian noise without sharp periodic peaks.
- High-frequency energy is balanced: P_HF in [0.20, 0.50].
- Peak prominence is low: Pi_max < 3.0x.

Pathological Regimes:
1. Predatory HFT Periodic Pulse / Triangular Arbitrage Signature:
   Algorithmic market sweepers and quote-stuffing loops fire on fixed millisecond cycles,
   creating sharp harmonic delta spikes in the high-frequency spectrum:
   Pi_max > max_peak_prominence (default: > 4.50x)
2. Noise-Dominant High-Frequency Churn:
   P_HF > max_hf_energy_ratio (default: > 0.65)
   The market is dominated by microsecond bid-ask bounce and parasitic quote flickering.

When periodic HFT signatures are detected, the guard activates an institutional circuit breaker,
suppressing order placement and avoiding execution during toxic algorithmic pulses.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave463SpectralDensityHFTSignatureGuard:
    """
    Evaluates Discrete Fourier Power Spectral Density (PSD) and spectral peak prominence
    to detect periodic high-frequency algorithmic manipulation and quote-stuffing pulses.
    """

    def __init__(
        self,
        window_size: int = 32,
        max_hf_energy_ratio: float = 0.65,
        max_peak_prominence: float = 4.50,
        min_samples: int = 16,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_size < 16:
            raise ValueError(f"window_size must be >= 16, got {window_size}")
        if not (0.35 <= max_hf_energy_ratio <= 0.90):
            raise ValueError(f"max_hf_energy_ratio must be in [0.35, 0.90], got {max_hf_energy_ratio}")
        if max_peak_prominence <= 1.50:
            raise ValueError(f"max_peak_prominence must be > 1.50, got {max_peak_prominence}")
        if min_samples < 12:
            raise ValueError(f"min_samples must be >= 12, got {min_samples}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_size: int = window_size
        self.max_hf_energy_ratio: float = max_hf_energy_ratio
        self.max_peak_prominence: float = max_peak_prominence
        self.min_samples: int = min_samples
        self.cooldown_sec: float = cooldown_sec

        # Ring buffers: tick values and timestamps
        self._series: List[float] = []
        self._timestamps: List[float] = []

        # State telemetry
        self.hf_energy_ratio: float = 0.0
        self.peak_prominence: float = 1.0
        self.dominant_frequency: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(self, value: float, timestamp: float) -> bool:
        """
        Record a new microstructural return, order flow imbalance, or spread observation.
        Returns True if trading is blocked, False otherwise.
        """
        if not math.isfinite(value):
            raise ValueError(f"value must be finite, got {value}")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        self._series.append(float(value))
        self._timestamps.append(float(timestamp))

        # Maintain window size
        if len(self._series) > self.window_size:
            self._series.pop(0)
            self._timestamps.pop(0)

        # Check cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        if len(self._series) < self.min_samples:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLES"
            return False

        arr = np.array(self._series, dtype=np.float64)
        n = len(arr)

        # Remove DC component (mean zero)
        arr_centered = arr - np.mean(arr)

        # Real Discrete Fourier Transform
        # rfft returns frequencies from 0 to N//2
        fft_vals = np.fft.rfft(arr_centered)
        psd = (np.abs(fft_vals) ** 2) / float(n)

        # Normalized frequencies in [0, 0.50]
        freqs = np.fft.rfftfreq(n, d=1.0)

        # Exclude DC frequency index 0 for AC spectral metrics
        ac_psd = psd[1:]
        ac_freqs = freqs[1:]

        total_ac_energy = float(np.sum(ac_psd))

        if total_ac_energy > 1e-12 and len(ac_psd) > 0:
            # High-frequency band: f >= 0.25 (top half of Nyquist band)
            hf_mask = ac_freqs >= 0.25
            hf_energy = float(np.sum(ac_psd[hf_mask]))
            self.hf_energy_ratio = float(hf_energy / total_ac_energy)

            # Peak Prominence
            max_p = float(np.max(ac_psd))
            mean_p = float(np.mean(ac_psd))
            self.peak_prominence = float(max_p / max(mean_p, 1e-9))

            # Dominant frequency
            dom_idx = int(np.argmax(ac_psd))
            self.dominant_frequency = float(ac_freqs[dom_idx])
        else:
            self.hf_energy_ratio = 0.0
            self.peak_prominence = 1.0
            self.dominant_frequency = 0.0

        # Evaluate Circuit Breakers
        periodic_pulse = (self.peak_prominence > self.max_peak_prominence and total_ac_energy > 1e-8)
        hf_dominance = (self.hf_energy_ratio > self.max_hf_energy_ratio and total_ac_energy > 1e-8)

        if periodic_pulse:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"HFT_PERIODIC_SPECTRAL_PULSE: Prominence {self.peak_prominence:.2f}x > "
                f"threshold {self.max_peak_prominence:.2f}x at f={self.dominant_frequency:.3f} cycles/sample"
            )
        elif hf_dominance:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"HF_NOISE_ENERGY_DOMINANCE: HF energy {self.hf_energy_ratio:.1%} > "
                f"cap {self.max_hf_energy_ratio:.1%}"
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
            "guard": "Wave463SpectralDensityHFTSignatureGuard",
            "hf_energy_ratio": round(self.hf_energy_ratio, 4),
            "peak_prominence": round(self.peak_prominence, 3),
            "dominant_frequency": round(self.dominant_frequency, 4),
            "max_hf_energy_ratio": self.max_hf_energy_ratio,
            "max_peak_prominence": self.max_peak_prominence,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._series)
        }

    def reset(self) -> None:
        """Reset internal buffers and state."""
        self._series.clear()
        self._timestamps.clear()
        self.hf_energy_ratio = 0.0
        self.peak_prominence = 1.0
        self.dominant_frequency = 0.0
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
