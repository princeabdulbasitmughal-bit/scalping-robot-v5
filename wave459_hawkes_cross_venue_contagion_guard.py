"""
Wave 459: Hawkes Process Mutual-Excitation Cross-Venue Contagion Guard
======================================================================
Institutional Quantitative Mathematical Formulation:
Under Hawkes (1971) "Spectra of Some Self-Exciting and Mutually Exciting Point Processes",
Bacry, Delattre, Hoffmann & Muzy (2015) "Hawkes Processes in Finance", and Hardiman et al. (2013),
cross-venue high-frequency order arrivals between Primary Venue A and Secondary Venue B
are modeled as a 2-dimensional mutually exciting multivariate Hawkes point process.

The conditional intensity vector lambda(t) = [lambda_A(t), lambda_B(t)]^T evolves as:
    lambda_i(t) = mu_i + sum_{j in {A, B}} sum_{t_{j,k} < t} alpha_{ij} * exp(-beta_{ij} * (t - t_{j,k}))

Where:
- mu_i is the exogenous Poisson baseline intensity.
- alpha_{ij} represents the mutual excitation magnitude (endogenous reflexivity).
- beta_{ij} is the exponential memory decay rate.

The 2x2 Kernel Branching Matrix Gamma is defined by:
    Gamma_{ij} = alpha_{ij} / beta_{ij}

Under the Hawkes Stability Theorem, the long-term stability and reflexivity of the
order flow cascade is governed by the spectral radius (largest eigenvalue) of Gamma:
    rho(Gamma) = max(|eig(Gamma)|)

When:
1. Supercritical Cross-Venue Cascade:
   rho(Gamma) > max_spectral_radius (default: > 0.85)
   The system approaches the critical boundary rho -> 1.0, where order arrivals become
   explosive, endogenous, and self-reinforcing (typical during flash crashes and liquidity runs).
2. Toxic Contagion Asymmetry:
   Cross-excitation ratio Gamma_{BA} / max(Gamma_{BB}, 1e-4) > max_cross_ratio (default: > 1.80x)
   Flow shocks originating on Venue A trigger disproportionate reflexive avalanches on Venue B.

Under supercritical contagion, standard orderbook queuing models and passive market-making
orders face catastrophic adverse selection. The guard activates an immediate quotation freeze
and suppresses order fills until the reflexivity metric rho(Gamma) falls back into the subcritical
stable regime.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave459HawkesCrossVenueContagionGuard:
    """
    Guards against reflexive cross-venue feedback cascades by estimating
    multivariate Hawkes mutual-excitation branching kernels and spectral radius.
    """

    def __init__(
        self,
        window_events: int = 40,
        beta_decay: float = 25.0,
        max_spectral_radius: float = 0.85,
        max_cross_ratio: float = 1.80,
        min_events: int = 15,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_events < 20:
            raise ValueError(f"window_events must be >= 20, got {window_events}")
        if beta_decay <= 1.0:
            raise ValueError(f"beta_decay must be > 1.0, got {beta_decay}")
        if not (0.50 <= max_spectral_radius <= 0.98):
            raise ValueError(f"max_spectral_radius must be in [0.50, 0.98], got {max_spectral_radius}")
        if max_cross_ratio <= 1.0:
            raise ValueError(f"max_cross_ratio must be > 1.0, got {max_cross_ratio}")
        if min_events < 10:
            raise ValueError(f"min_events must be >= 10, got {min_events}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_events: int = window_events
        self.beta_decay: float = beta_decay
        self.max_spectral_radius: float = max_spectral_radius
        self.max_cross_ratio: float = max_cross_ratio
        self.min_events: int = min_events
        self.cooldown_sec: float = cooldown_sec

        # Event histories: tuples of (timestamp, venue_id) where 0=Venue A, 1=Venue B
        self._events: List[tuple] = []
        self._last_timestamp: float = -1.0

        # State telemetry
        self.spectral_radius: float = 0.0
        self.gamma_matrix: np.ndarray = np.zeros((2, 2), dtype=np.float64)
        self.cross_ratio: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(self, venue: str, timestamp: float) -> bool:
        """
        Record a new order arrival event on venue ('A' or 'B') at monotonic timestamp.
        Returns True if trading is blocked, False otherwise.
        """
        v_upper = venue.upper()
        if v_upper not in ("A", "B"):
            raise ValueError(f"venue must be 'A' or 'B', got '{venue}'")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")

        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        venue_idx = 0 if v_upper == "A" else 1
        self._last_timestamp = timestamp
        self._events.append((timestamp, venue_idx))

        # Maintain window size
        if len(self._events) > self.window_events:
            self._events.pop(0)

        # Check cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        if len(self._events) < self.min_events:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_EVENTS"
            return False

        # Analytical estimation of Hawkes Kernel Branching Matrix Gamma
        # Across event pairs (t_i, t_j), compute empirical kernel cross-excitation:
        # Sum_{t_j < t_i} exp(-beta * (t_i - t_j)) for pairs (j -> i)
        kernel_sums = np.zeros((2, 2), dtype=np.float64)
        counts = np.zeros(2, dtype=np.float64)

        n = len(self._events)
        for i in range(1, n):
            t_i, v_i = self._events[i]
            counts[v_i] += 1.0
            for j in range(max(0, i - 12), i):
                t_j, v_j = self._events[j]
                dt = t_i - t_j
                if dt < 1.0: # Only count within local 1-second correlation horizon
                    weight = math.exp(-self.beta_decay * dt)
                    kernel_sums[v_i, v_j] += weight

        # Branching ratios Gamma_{ij} = kernel_sums_{ij} / max(counts_j, 1.0)
        gamma = np.zeros((2, 2), dtype=np.float64)
        for v_to in range(2):
            for v_from in range(2):
                c = max(counts[v_from], 1.0)
                gamma[v_to, v_from] = min(0.99, kernel_sums[v_to, v_from] / c)

        self.gamma_matrix = gamma

        # Compute Spectral Radius rho(Gamma)
        try:
            eigenvalues = np.linalg.eigvals(gamma)
            self.spectral_radius = float(np.max(np.abs(eigenvalues)))
        except Exception:
            self.spectral_radius = 0.0

        # Cross-venue contagion ratio: Gamma_{B,A} / max(Gamma_{B,B}, 1e-4)
        denom = max(gamma[1, 1], 1e-4)
        self.cross_ratio = float(gamma[1, 0] / denom)

        # Circuit Breaker Evaluation
        if self.spectral_radius > self.max_spectral_radius:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"HAWKES_SUPERCRITICAL_CASCADE: Spectral radius rho={self.spectral_radius:.3f} > "
                f"threshold {self.max_spectral_radius:.3f} (Gamma=[[{gamma[0,0]:.2f}, {gamma[0,1]:.2f}], "
                f"[{gamma[1,0]:.2f}, {gamma[1,1]:.2f}]])"
            )
        elif self.cross_ratio > self.max_cross_ratio and gamma[1, 0] > 0.35:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"TOXIC_CROSS_VENUE_CONTAGION: Cross excitation ratio Gamma_{{BA}}/Gamma_{{BB}}={self.cross_ratio:.2f}x > "
                f"cap {self.max_cross_ratio:.2f}x (Gamma_BA={gamma[1,0]:.3f})"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Hawkes Contagion Guard."""
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
            "guard": "Wave459HawkesCrossVenueContagionGuard",
            "spectral_radius": round(self.spectral_radius, 4),
            "cross_ratio": round(self.cross_ratio, 3),
            "gamma_aa": round(float(self.gamma_matrix[0, 0]), 4),
            "gamma_ab": round(float(self.gamma_matrix[0, 1]), 4),
            "gamma_ba": round(float(self.gamma_matrix[1, 0]), 4),
            "gamma_bb": round(float(self.gamma_matrix[1, 1]), 4),
            "max_spectral_radius": self.max_spectral_radius,
            "max_cross_ratio": self.max_cross_ratio,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "event_count": len(self._events)
        }

    def reset(self) -> None:
        """Reset internal event buffers and telemetry."""
        self._events.clear()
        self.spectral_radius = 0.0
        self.gamma_matrix = np.zeros((2, 2), dtype=np.float64)
        self.cross_ratio = 0.0
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
