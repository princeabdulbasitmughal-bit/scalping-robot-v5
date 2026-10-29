"""
Wave 453: Multivariate Hawkes Process Cross-Asset Excitation Matrix & Contagion Hazard Guard
=============================================================================================
Institutional Quantitative Mathematical Formulation:
Under Hawkes (1971) "Spectra of Some Self-Exciting and Mutually Exciting Point Processes"
and Bacry, Delattre, Hoffmann & Muzy (2013) "Some properties of the mutually exciting Hawkes
processes with applications to financial data", the multivariate conditional intensity
lambda(t) = [lambda_1(t), ..., lambda_M(t)]^T across M correlated liquidity channels
(e.g., cross-asset order books, or bid/ask cancellation vs aggressive trade flows) is:

    lambda_m(t) = mu_m + sum_{n=1}^M integral_0^t alpha_{mn} * exp(-beta * (t - s)) dN_n(s)

where:
- mu_m > 0 is the baseline exogenous arrival rate.
- alpha_{mn} >= 0 represents the cross-excitation magnitude from channel n to channel m.
- beta > 0 is the exponential memory decay parameter.

The Branching Matrix Gamma = [gamma_{mn}] in R^{M x M} is defined as:
    gamma_{mn} = alpha_{mn} / beta

representing the expected number of secondary events induced in channel m by an event in channel n.

Spectral Radius Stability Criterion:
Let rho(Gamma) = max_i |lambda_i(Gamma)| be the spectral radius (Perron-Frobenius eigenvalue).
1. When rho(Gamma) < 1.0:
   The multi-asset market is subcritical and stationary; microstructural cascades dissipate exponentially.
2. When rho(Gamma) >= 1.0:
   The system becomes supercritical and explosive; order cancellations or aggressive sweeps trigger
   self-reinforcing runaway liquidity avalanches (cross-asset flash crash contagion).

The guard maintains real-time recursive decay accumulators R_{mn}(t) in O(M^2) updates,
estimates instantaneous branching ratios gamma_{mn}, and triggers immediate protective lockout if:
1. Spectral radius rho(Gamma) >= max_spectral_radius (default: >= 0.88), preventing exposure to explosive cascades.
2. Cross-excitation spillover ratio S_cross = (sum_{m != n} gamma_{mn}) / (sum_{m,n} gamma_{mn}) > max_spillover (default: > 0.65),
   indicating toxic exogenous contagion overwhelming endogenous local liquidity.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional, Tuple


class Wave453HawkesCrossExcitationSpilloverGuard:
    """
    Multivariate Hawkes Process Cross-Excitation Matrix and Contagion Spillover Guard.
    Monitors inter-channel feedback and spectral radius rho(Gamma) to prevent exposure
    during supercritical self-exciting liquidity cascades.
    """

    def __init__(
        self,
        num_channels: int = 4,
        decay_beta: float = 10.0,
        window_size: int = 50,
        max_spectral_radius: float = 0.88,
        max_spillover_ratio: float = 0.65,
        min_events_for_decision: int = 15
    ) -> None:
        if num_channels < 2 or num_channels > 16:
            raise ValueError(f"num_channels must be in [2, 16], got {num_channels}")
        if decay_beta <= 0.1:
            raise ValueError(f"decay_beta must be > 0.1, got {decay_beta}")
        if window_size < 20:
            raise ValueError(f"window_size must be >= 20, got {window_size}")
        if not (0.50 <= max_spectral_radius <= 1.50):
            raise ValueError(f"max_spectral_radius must be in [0.50, 1.50], got {max_spectral_radius}")
        if not (0.20 <= max_spillover_ratio <= 0.95):
            raise ValueError(f"max_spillover_ratio must be in [0.20, 0.95], got {max_spillover_ratio}")

        self.num_channels: int = num_channels
        self.decay_beta: float = decay_beta
        self.window_size: int = window_size
        self.max_spectral_radius: float = max_spectral_radius
        self.max_spillover_ratio: float = max_spillover_ratio
        self.min_events_for_decision: int = min_events_for_decision

        # Event storage: list of (timestamp, channel_id)
        self._events: List[Tuple[float, int]] = []
        self._last_timestamp: Optional[float] = None

        # Recursive decay accumulators: R[m, n]
        self._R: np.ndarray = np.zeros((num_channels, num_channels), dtype=np.float64)

        # Baseline channel count
        self._channel_counts: np.ndarray = np.zeros(num_channels, dtype=np.float64)

        # State outputs
        self.spectral_radius: float = 0.0
        self.spillover_ratio: float = 0.0
        self.branching_matrix: np.ndarray = np.zeros((num_channels, num_channels), dtype=np.float64)
        self._is_blocked: bool = False
        self._block_reason: str = ""

    def update(self, timestamp: float, channel_id: int) -> bool:
        """
        Record a new event on a given channel.
        timestamp: strictly monotonic event timestamp in seconds.
        channel_id: integer in [0, num_channels - 1].
        Returns True if trading is blocked due to supercritical contagion, False otherwise.
        """
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if not (0 <= channel_id < self.num_channels):
            raise ValueError(f"channel_id must be in [0, {self.num_channels - 1}], got {channel_id}")
        if self._last_timestamp is not None and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        # Update recursive decay from last event
        if self._last_timestamp is not None:
            dt = timestamp - self._last_timestamp
            decay = math.exp(-self.decay_beta * dt)
            self._R *= decay

        # Add impulse: event occurred in channel_id, exciting all recipient channels
        # Cross-excitation accumulator increments
        self._R[:, channel_id] += 1.0

        self._last_timestamp = timestamp
        self._events.append((timestamp, channel_id))
        self._channel_counts[channel_id] += 1.0

        # Maintain sliding window
        if len(self._events) > self.window_size:
            evicted_ts, evicted_ch = self._events.pop(0)
            self._channel_counts[evicted_ch] = max(0.0, self._channel_counts[evicted_ch] - 1.0)

        # Check if enough events for decision
        if len(self._events) < self.min_events_for_decision:
            self._is_blocked = False
            self._block_reason = "WARMUP_INSUFFICIENT_EVENTS"
            return False

        # Evaluate branching matrix Gamma = [gamma_{mn}]
        self._evaluate_branching()

        # Decision thresholds
        if self.spectral_radius >= self.max_spectral_radius:
            self._is_blocked = True
            self._block_reason = f"HAWKES_SUPERCRITICAL_CASCADE (rho={self.spectral_radius:.4f} >= {self.max_spectral_radius:.2f})"
            return True

        if self.spillover_ratio >= self.max_spillover_ratio:
            self._is_blocked = True
            self._block_reason = f"HAWKES_CROSS_SPILLOVER_CONTAGION (spillover={self.spillover_ratio:.4f} >= {self.max_spillover_ratio:.2f})"
            return True

        self._is_blocked = False
        self._block_reason = "NOMINAL_STATIONARY"
        return False

    def _evaluate_branching(self) -> None:
        """
        Compute empirical branching matrix Gamma, spectral radius rho(Gamma),
        and cross-excitation spillover ratio.
        """
        total_events = len(self._events)
        duration = max(1e-6, self._events[-1][0] - self._events[0][0])
        
        # Empirical intensity estimation per channel
        # Base arrival rate mu_m ~ count_m / duration
        # Instantaneous excitation alpha_{mn} ~ R_{mn} / duration
        # gamma_{mn} = alpha_{mn} / decay_beta
        gamma = np.zeros((self.num_channels, self.num_channels), dtype=np.float64)
        for m in range(self.num_channels):
            for n in range(self.num_channels):
                # Normalized excitation weight per event in channel n
                events_n = max(1.0, self._channel_counts[n])
                effective_alpha = self._R[m, n] / (duration * events_n)
                gamma[m, n] = effective_alpha / self.decay_beta

        self.branching_matrix = gamma

        # Compute spectral radius: maximum absolute eigenvalue of Gamma
        try:
            eigenvalues = np.linalg.eigvals(gamma)
            self.spectral_radius = float(np.max(np.abs(eigenvalues)))
        except Exception:
            self.spectral_radius = 0.0

        # Compute cross-excitation spillover ratio: off-diagonal sum / total sum
        diag_sum = float(np.trace(gamma))
        total_sum = float(np.sum(gamma))
        off_diag_sum = max(0.0, total_sum - diag_sum)

        if total_sum > 1e-9:
            self.spillover_ratio = off_diag_sum / total_sum
        else:
            self.spillover_ratio = 0.0

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return diagnostic metrics dictionary."""
        return {
            "num_channels": self.num_channels,
            "window_events": len(self._events),
            "spectral_radius": float(self.spectral_radius),
            "max_spectral_radius": self.max_spectral_radius,
            "spillover_ratio": float(self.spillover_ratio),
            "max_spillover_ratio": self.max_spillover_ratio,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "channel_counts": self._channel_counts.tolist(),
            "branching_trace": float(np.trace(self.branching_matrix)),
            "branching_norm": float(np.linalg.norm(self.branching_matrix))
        }

    def reset(self) -> None:
        """Reset internal history and state."""
        self._events.clear()
        self._last_timestamp = None
        self._R.fill(0.0)
        self._channel_counts.fill(0.0)
        self.spectral_radius = 0.0
        self.spillover_ratio = 0.0
        self.branching_matrix.fill(0.0)
        self._is_blocked = False
        self._block_reason = ""
