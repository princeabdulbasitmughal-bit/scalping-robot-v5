"""
Wave 509: High-Frequency Limit Order Book Multi-Fractal Detrended Fluctuation Analysis (MF-DFA) & Singularity Spectrum Guard
===========================================================================================================================
Institutional Quantitative Mathematical Formulation:
Under Kantelhardt et al. (2002), Lux (2008), Calvet & Fisher (2002), and Bacry et al. (2001),
high-frequency limit order book price transitions, order flow depth fluctuations, and trade inter-arrival
times exhibit non-linear multi-scale multifractal scaling and intermittency.

1. Multifractal Fluctuation Function & Generalized Hurst Exponent h(q):
   For scale s and moment order q in [-5, +5]:
       F_q(s) = ( (1 / (2 * N_s)) * sum_{v=1}^{2*N_s} [ F^2(v, s) ]^(q/2) )^(1/q)
   The generalized Hurst exponent h(q) is the scaling exponent:
       F_q(s) ~ s^(h(q))

   - For pure monofractal Gaussian Brownian motion: h(q) = H = constant for all q.
   - For multi-fractal turbulent markets: h(q) decreases non-linearly with q.

2. Multifractal Spectrum Degree & Width:
   The multifractal width Delta_h captures the degree of structural intermittency:
       Delta_h = h(q_min) - h(q_max)   (typically q_min = -2, q_max = +2 or -5, +5)
   Normal calm markets exhibit small width Delta_h in [0.05, 0.25].
   When Delta_h >= max_multifractal_width (default: >= 0.65), extreme non-Gaussian tail cascades
   and multifractal singularity clusters dominate the book.

3. Singularity Spectrum Asymmetry Index (A_mf):
   Derived via Legendre transform:
       tau(q) = q * h(q) - 1
       alpha = d(tau)/dq
       f(alpha) = q * alpha - tau(q)
   The spectrum asymmetry index A_mf compares the left and right width of the spectrum:
       A_mf = (alpha_0 - alpha_min) - (alpha_max - alpha_0) / Delta_alpha in [-1.0, 1.0]
   - A_mf > 0: Dominance of low-amplitude fluctuations.
   - A_mf < 0: Dominance of high-amplitude catastrophic extreme events (fat left tail).

4. Composite Multifractal Fragility Index (Psi_mf):
       Psi_mf = 0.50 * min(1.0, max(0.0, (Delta_h - 0.25) / 0.40))
              + 0.50 * min(1.0, max(0.0, (abs(A_mf) - 0.20) / 0.60)) in [0.0, 1.0]

Circuit Breakers:
1. MULTIFRACTAL_INTERMITTENCY_CRITICAL: Delta_h >= max_multifractal_width (default: >= 0.65) or Psi_mf >= critical_fragility_threshold (default: >= 0.70) -> HALT_ALL
2. MULTIFRACTAL_SPECTRUM_ASYMMETRY_CRITICAL: abs(A_mf) >= max_asymmetry_threshold (default: >= 0.80) -> HALT_ALL
3. Asymmetric Directional Toxicity Overrides:
   - A_mf <= -0.50 and z_mf >= z_mf_warning_threshold (default: >= 2.00) -> BLOCK_BUY (parabolic meltup extreme tail cascade)
   - A_mf <= -0.50 and z_mf <= -z_mf_warning_threshold (default: <= -2.00) -> BLOCK_SELL (liquidation flush extreme tail cascade)
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave509LobMultifractalDfaSingularitySpectrumGuard:
    """
    Monitors high-frequency order book multifractal scaling, generalized Hurst exponent width Delta_h,
    and singularity spectrum asymmetry to prevent catastrophic slippage during intermittent volatility bursts.
    """

    def __init__(
        self,
        max_multifractal_width: float = 0.65,
        max_asymmetry_threshold: float = 0.80,
        critical_fragility_threshold: float = 0.70,
        z_mf_warning_threshold: float = 2.00,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.35 <= max_multifractal_width <= 1.20):
            raise ValueError(f"max_multifractal_width must be in [0.35, 1.20], got {max_multifractal_width}")
        if not (0.50 <= max_asymmetry_threshold <= 0.99):
            raise ValueError(f"max_asymmetry_threshold must be in [0.50, 0.99], got {max_asymmetry_threshold}")
        if not (0.45 <= critical_fragility_threshold <= 0.90):
            raise ValueError(f"critical_fragility_threshold must be in [0.45, 0.90], got {critical_fragility_threshold}")
        if not (1.00 <= z_mf_warning_threshold <= 3.50):
            raise ValueError(f"z_mf_warning_threshold must be in [1.00, 3.50], got {z_mf_warning_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_multifractal_width: float = max_multifractal_width
        self.max_asymmetry_threshold: float = max_asymmetry_threshold
        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.z_mf_warning_threshold: float = z_mf_warning_threshold
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self.breaker_active: bool = False
        self.breaker_tripped_at: float = 0.0
        self.last_trip_reason: str = "NONE"

    def reset(self) -> None:
        """Reset internal circuit breaker states."""
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def compute_mf_dfa_scaling(
        self,
        series: List[float],
        q_list: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Computes simplified multi-scale fluctuation analysis and estimates Delta_h = h(q_min) - h(q_max).
        """
        if len(series) < 16:
            raise ValueError(f"Must provide at least 16 observations for MF-DFA scaling, got {len(series)}")

        if q_list is None:
            q_list = [-2.0, 2.0]

        arr = np.array(series, dtype=np.float64)
        n = len(arr)
        profile = np.cumsum(arr - np.mean(arr))

        scales = [4, 8, max(8, n // 2)]
        h_q_dict = {}

        for q in q_list:
            log_f = []
            log_s = []
            for s in scales:
                num_segments = n // s
                if num_segments < 1:
                    continue
                var_list = []
                for v in range(num_segments):
                    seg = profile[v * s: (v + 1) * s]
                    x_idx = np.arange(s)
                    poly = np.polyfit(x_idx, seg, 1)
                    fit = np.polyval(poly, x_idx)
                    var_list.append(np.mean((seg - fit) ** 2))
                
                var_arr = np.array(var_list, dtype=np.float64)
                var_arr = np.maximum(var_arr, 1e-12)
                
                if q == 0:
                    f_val = np.exp(0.5 * np.mean(np.log(var_arr)))
                else:
                    f_val = np.mean(var_arr ** (q / 2.0)) ** (1.0 / q)

                log_f.append(np.log(max(f_val, 1e-12)))
                log_s.append(np.log(s))

            if len(log_s) >= 2:
                poly_slope = np.polyfit(log_s, log_f, 1)[0]
                h_q_dict[q] = float(np.clip(poly_slope, 0.05, 1.50))
            else:
                h_q_dict[q] = 0.50

        q_min = min(q_list)
        q_max = max(q_list)
        delta_h = float(np.clip(h_q_dict.get(q_min, 0.50) - h_q_dict.get(q_max, 0.50), 0.0, 1.50))

        return {
            "h_q": h_q_dict,
            "delta_h": delta_h
        }

    def evaluate(
        self,
        delta_h: float,
        a_mf: float = 0.0,
        z_mf: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates multifractal width Delta_h, singularity spectrum asymmetry A_mf,
        and directional tail cascades.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= delta_h <= 2.0):
            raise ValueError(f"delta_h must be in [0.0, 2.0], got {delta_h}")
        if not (-1.0 <= a_mf <= 1.0):
            raise ValueError(f"a_mf must be in [-1.0, 1.0], got {a_mf}")
        if not (-10.0 <= z_mf <= 10.0):
            raise ValueError(f"z_mf must be in [-10.0, 10.0], got {z_mf}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "delta_h": delta_h,
                    "a_mf": a_mf,
                    "z_mf": z_mf,
                    "psi_mf": 1.0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate composite fragility index Psi_mf in [0.0, 1.0]
        phi_delta = min(1.0, max(0.0, (delta_h - 0.25) / 0.40))
        phi_asym = min(1.0, max(0.0, (abs(a_mf) - 0.20) / 0.60))
        psi_mf = float(np.clip(0.50 * phi_delta + 0.50 * phi_asym, 0.0, 1.0))

        # 1. Critical Multifractal Intermittency Breaker
        if delta_h >= self.max_multifractal_width:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"MULTIFRACTAL_INTERMITTENCY_CRITICAL: delta_h={delta_h:.3f} >= {self.max_multifractal_width:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "delta_h": delta_h,
                "a_mf": a_mf,
                "z_mf": z_mf,
                "psi_mf": psi_mf
            }

        if psi_mf >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"MULTIFRACTAL_FRAGILITY_CRITICAL: psi_mf={psi_mf:.3f} >= {self.critical_fragility_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "delta_h": delta_h,
                "a_mf": a_mf,
                "z_mf": z_mf,
                "psi_mf": psi_mf
            }

        # 2. Critical Spectrum Asymmetry Breaker
        if abs(a_mf) >= self.max_asymmetry_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"MULTIFRACTAL_SPECTRUM_ASYMMETRY_CRITICAL: |a_mf|={abs(a_mf):.3f} >= {self.max_asymmetry_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "delta_h": delta_h,
                "a_mf": a_mf,
                "z_mf": z_mf,
                "psi_mf": psi_mf
            }

        # 3. Asymmetric Directional Toxicity Overextensions
        # When negative asymmetry dominates (extreme tail risk) and directional z_score is elevated
        if a_mf <= -0.50 and z_mf >= self.z_mf_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"MULTIFRACTAL_PARABOLIC_TAIL_EXHAUSTION: a_mf={a_mf:.2f} <= -0.50 and z_mf={z_mf:.2f} >= {self.z_mf_warning_threshold:.2f}",
                "delta_h": delta_h,
                "a_mf": a_mf,
                "z_mf": z_mf,
                "psi_mf": psi_mf
            }

        if a_mf <= -0.50 and z_mf <= -self.z_mf_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"MULTIFRACTAL_LIQUIDATION_TAIL_CASCADE: a_mf={a_mf:.2f} <= -0.50 and z_mf={z_mf:.2f} <= -{self.z_mf_warning_threshold:.2f}",
                "delta_h": delta_h,
                "a_mf": a_mf,
                "z_mf": z_mf,
                "psi_mf": psi_mf
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "MULTIFRACTAL_EQUILIBRIUM_ACTIVE",
            "delta_h": delta_h,
            "a_mf": a_mf,
            "z_mf": z_mf,
            "psi_mf": psi_mf
        }
