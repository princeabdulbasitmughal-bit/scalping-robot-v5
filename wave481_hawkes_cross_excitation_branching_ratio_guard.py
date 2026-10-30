"""
Wave 481: Hawkes Cross-Excitation Branching Ratio Guard
======================================================
Institutional Quantitative Mathematical Formulation:
Under Hawkes (1971), Bacry, Delattre, Hoffmann & Muzy (2013) "Some Properties of Mutually
Exciting, Multifactor Hawkes Processes with Applications to Financial Data", and
Hardiman, Bercot & Bouchaud (2013) "Reflexivity and Criticality in Financial Markets",
high-frequency order flow events on Bid and Ask sides are modeled as a 2D point process:

    lambda_buy(t) = mu_buy + sum_{t_i^b < t} alpha_{bb} * exp(-beta_{bb} * (t - t_i^b))
                           + sum_{t_j^a < t} alpha_{ba} * exp(-beta_{ba} * (t - t_j^a))

    lambda_sell(t) = mu_sell + sum_{t_i^b < t} alpha_{ab} * exp(-beta_{ab} * (t - t_i^b))
                             + sum_{t_j^a < t} alpha_{aa} * exp(-beta_{aa} * (t - t_j^a))

The 2x2 Hawkes Branching Matrix Gamma governs endogenous self- and cross-excitation:
    Gamma = [[alpha_{bb} / beta_{bb}, alpha_{ba} / beta_{ba}],
             [alpha_{ab} / beta_{ab}, alpha_{aa} / beta_{aa}]]

The Spectral Radius rho(Gamma) is the dominant eigenvalue:
    rho(Gamma) = max(|eig_1|, |eig_2|) in [0.0, infinity)

Physical Interpretation:
- Subcritical Regime (rho < 0.80): Stable market. Endogenous cascades decay exponentially.
- Critical Regime (0.80 <= rho < 1.0): High reflexivity. Shocks trigger prolonged cascades.
- Supercritical Cascade (rho >= 0.88): Explosive feedback loop. Orders self-reproduce
  faster than liquidity providers can replenish quotes, producing flash crashes.

Directional Branching Intensities:
    eta_buy = Gamma_{0,0} + Gamma_{1,0}   (Total expected offspring from a buy order)
    eta_sell = Gamma_{1,1} + Gamma_{0,1}  (Total expected offspring from a sell order)

Circuit Breakers:
1. HAWKES_SUPERCRITICAL_CASCADE: rho(Gamma) > max_spectral_radius (default: > 0.88)
2. RUNAWAY_BUY_EXCITATION: eta_buy > max_branching_ratio (default: > 0.85) -> SELL entries toxic.
3. RUNAWAY_SELL_EXCITATION: eta_sell > max_branching_ratio (default: > 0.85) -> BUY entries toxic.

When triggered, the guard freezes trade routing, protecting capital from being caught in runaway reflexivity loops.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave481HawkesCrossExcitationBranchingRatioGuard:
    """
    Monitors 2D Hawkes self- and cross-excitation kernels, spectral radius rho(Gamma),
    and directional branching ratios to prevent execution during supercritical feedback cascades.
    """

    def __init__(
        self,
        max_spectral_radius: float = 0.88,
        max_branching_ratio: float = 0.85,
        asymmetry_threshold: float = 0.25,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.60 <= max_spectral_radius <= 0.98):
            raise ValueError(f"max_spectral_radius must be in [0.60, 0.98], got {max_spectral_radius}")
        if not (0.50 <= max_branching_ratio <= 0.98):
            raise ValueError(f"max_branching_ratio must be in [0.50, 0.98], got {max_branching_ratio}")
        if not (0.10 <= asymmetry_threshold <= 0.60):
            raise ValueError(f"asymmetry_threshold must be in [0.10, 0.60], got {asymmetry_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_spectral_radius: float = max_spectral_radius
        self.max_branching_ratio: float = max_branching_ratio
        self.asymmetry_threshold: float = asymmetry_threshold
        self.cooldown_sec: float = cooldown_sec

        # Telemetry metrics
        self.spectral_radius: float = 0.0
        self.eta_buy: float = 0.0
        self.eta_sell: float = 0.0
        self.branching_matrix: List[List[float]] = [[0.0, 0.0], [0.0, 0.0]]
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        g_bb: float,
        g_ba: float,
        g_ab: float,
        g_aa: float,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous branching matrix components:
        Gamma = [[g_bb, g_ba],
                 [g_ab, g_aa]]
        where g_{ij} = alpha_{ij} / beta_{ij} >= 0.0.
        """
        inputs = [g_bb, g_ba, g_ab, g_aa]
        for g in inputs:
            if not math.isfinite(g):
                raise ValueError("All branching matrix entries must be finite numbers")
            if g < 0.0:
                raise ValueError("Branching matrix entries must be non-negative")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        gamma = np.array([[g_bb, g_ba],
                          [g_ab, g_aa]], dtype=np.float64)

        self.branching_matrix = [
            [round(float(g_bb), 4), round(float(g_ba), 4)],
            [round(float(g_ab), 4), round(float(g_aa), 4)]
        ]

        # Spectral radius (maximum absolute eigenvalue)
        eigenvalues = np.linalg.eigvals(gamma)
        self.spectral_radius = float(np.max(np.abs(eigenvalues)))

        # Directional branching ratios
        self.eta_buy = float(g_bb + g_ab)
        self.eta_sell = float(g_aa + g_ba)

        # Evaluate Circuit Breakers
        supercritical = (self.spectral_radius > self.max_spectral_radius)
        buy_runaway = (self.eta_buy > self.max_branching_ratio and (self.eta_buy - self.eta_sell) > self.asymmetry_threshold)
        sell_runaway = (self.eta_sell > self.max_branching_ratio and (self.eta_sell - self.eta_buy) > self.asymmetry_threshold)

        if supercritical or buy_runaway or sell_runaway:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution
            if buy_runaway and not sell_runaway:
                self.blocked_side = "SELL" # Heavy runaway buying cascade -> shorting is toxic
                side_note = "RUNAWAY_BUY_EXCITATION"
            elif sell_runaway and not buy_runaway:
                self.blocked_side = "BUY" # Heavy runaway selling cascade -> buying is toxic
                side_note = "RUNAWAY_SELL_EXCITATION"
            else:
                self.blocked_side = "ALL"
                side_note = "SUPERCRITICAL_CASCADE"

            trigger = (
                "RUNAWAY_BUY_EXCITATION" if (buy_runaway and not sell_runaway) else
                ("RUNAWAY_SELL_EXCITATION" if (sell_runaway and not buy_runaway) else "HAWKES_SUPERCRITICAL_CASCADE")
            )
            self._block_reason = (
                f"{trigger}: rho={self.spectral_radius:.3f} (max={self.max_spectral_radius:.3f}), "
                f"eta_buy={self.eta_buy:.3f}, eta_sell={self.eta_sell:.3f} [{side_note}], blocked: {self.blocked_side}"
            )
        else:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Checks if specific side is blocked."""
        if not self._is_blocked:
            return False
        if self.blocked_side == "ALL":
            return True
        return self.blocked_side == side.upper()

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave481HawkesCrossExcitationBranchingRatioGuard",
            "spectral_radius": round(self.spectral_radius, 4),
            "eta_buy": round(self.eta_buy, 4),
            "eta_sell": round(self.eta_sell, 4),
            "branching_matrix": self.branching_matrix,
            "max_spectral_radius": self.max_spectral_radius,
            "max_branching_ratio": self.max_branching_ratio,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.spectral_radius = 0.0
        self.eta_buy = 0.0
        self.eta_sell = 0.0
        self.branching_matrix = [[0.0, 0.0], [0.0, 0.0]]
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
