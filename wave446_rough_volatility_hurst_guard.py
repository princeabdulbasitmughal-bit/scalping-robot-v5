"""
Wave 446: Fractional Brownian Motion Rough Volatility Hurst Exponent Guard
========================================================================
Institutional Quantitative Mathematical Formulation:
Under Gatheral, Jaisson, and Rosenbaum (2018) "Volatility is Rough", log-volatility
behaves as a fractional Brownian motion (fBm) with Hurst parameter H in (0, 0.5),
typically H ~ 0.10 - 0.15 in stationary equity/FX/commodity markets.

Let v(t) = ln sigma(t) be the instantaneous realized volatility.
The second-order structure function across time lag Delta is:
    m(2, Delta) = E[|v(t + Delta) - v(t)|^2] = c * Delta^(2H)
Taking logarithms:
    ln m(2, Delta) = 2H * ln Delta + ln c

When market microstructure degrades:
1. Ultra-rough regime (H < H_min, e.g. H < 0.05): Realized variance undergoes singular,
   turbulent shockwaves characteristic of liquidity flash crashes or orderbook cascades.
2. Super-diffusive / Trending regime (H > H_max, e.g. H > 0.50): Mean-reversion of volatility
   breaks down, signalling persistent toxic directional momentum and structural regime shift.

The guard computes the empirical structure function across multi-scale lags Delta in {1, 2, 4, 8},
extracts H via Ordinary Least Squares (OLS), and engages protective lockout when H deviates
outside institutional safety bands.
"""

import math
import numpy as np
from typing import List, Tuple, Dict, Any, Optional


class Wave446RoughVolatilityHurstGuard:
    """
    Evaluates real-time fractional Brownian motion Hurst exponent H of realized volatility
    to detect microstructural turbulence, singular volatility jumps, and toxic drift regimes.
    """

    def __init__(
        self,
        window_size: int = 32,
        min_hurst_threshold: float = 0.05,
        max_hurst_threshold: float = 0.50,
        lags: Optional[List[int]] = None
    ) -> None:
        if window_size < 16:
            raise ValueError(f"window_size must be >= 16 for robust multi-lag OLS, got {window_size}")
        if min_hurst_threshold <= 0.0 or min_hurst_threshold >= max_hurst_threshold:
            raise ValueError(f"Invalid thresholds: min={min_hurst_threshold}, max={max_hurst_threshold}")

        self.window_size: int = window_size
        self.min_hurst_threshold: float = min_hurst_threshold
        self.max_hurst_threshold: float = max_hurst_threshold
        self.lags: List[int] = lags if lags is not None else [1, 2, 4, 8]
        
        # Internal state
        self._vol_history: List[float] = []
        self._timestamps: List[float] = []
        self.estimated_hurst: float = 0.14  # Default typical stationary rough volatility
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._structure_values: Dict[int, float] = {}

    def update(self, volatility: float, timestamp: float) -> bool:
        """
        Record a new realized volatility observation and recompute Hurst exponent H.
        Returns True if trading is blocked, False otherwise.
        """
        if volatility <= 0.0 or not math.isfinite(volatility):
            raise ValueError(f"Volatility must be positive and finite, got {volatility}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"Timestamp must be strictly increasing. Got {timestamp} <= {self._timestamps[-1]}")

        log_vol = math.log(max(volatility, 1e-8))
        self._vol_history.append(log_vol)
        self._timestamps.append(timestamp)

        if len(self._vol_history) > self.window_size:
            self._vol_history.pop(0)
            self._timestamps.pop(0)

        # Require at least minimum buffer to estimate structure functions
        if len(self._vol_history) < max(self.lags) * 2:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_DATA"
            return False

        # Compute empirical structure function m(2, Delta) for each lag
        v_arr = np.array(self._vol_history, dtype=np.float64)
        valid_log_lags: List[float] = []
        valid_log_m2: List[float] = []
        self._structure_values.clear()

        for delta in self.lags:
            if len(v_arr) > delta:
                diffs = v_arr[delta:] - v_arr[:-delta]
                m2 = np.mean(diffs ** 2)
                if m2 > 1e-12:
                    valid_log_lags.append(math.log(float(delta)))
                    valid_log_m2.append(math.log(float(m2)))
                    self._structure_values[delta] = float(m2)

        if len(valid_log_lags) < 2:
            self._is_blocked = False
            self._block_reason = "DEGENERATE_STRUCTURE_FUNCTION"
            return False

        # OLS regression: ln m(2, Delta) = 2H * ln Delta + intercept
        x = np.array(valid_log_lags, dtype=np.float64)
        y = np.array(valid_log_m2, dtype=np.float64)
        
        # OLS slope = Cov(x, y) / Var(x)
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        var_x = np.sum((x - x_mean) ** 2)
        if var_x < 1e-12:
            self.estimated_hurst = 0.14
        else:
            cov_xy = np.sum((x - x_mean) * (y - y_mean))
            slope_2h = cov_xy / var_x
            # H = slope / 2, clipped to non-negative range for sanity
            self.estimated_hurst = max(0.001, float(slope_2h / 2.0))

        # Evaluate safety invariant
        if self.estimated_hurst < self.min_hurst_threshold:
            self._is_blocked = True
            self._block_reason = (
                f"ULTRA_ROUGH_TURBULENCE: Estimated Hurst H={self.estimated_hurst:.4f} < "
                f"floor={self.min_hurst_threshold:.4f} (singular jump cascade risk)"
            )
        elif self.estimated_hurst > self.max_hurst_threshold:
            self._is_blocked = True
            self._block_reason = (
                f"SUPER_DIFFUSIVE_DRIFT: Estimated Hurst H={self.estimated_hurst:.4f} > "
                f"ceiling={self.max_hurst_threshold:.4f} (persistent toxic trending risk)"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Rough Volatility Hurst Guard."""
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
            "guard": "Wave446RoughVolatilityHurstGuard",
            "estimated_hurst": round(self.estimated_hurst, 5),
            "min_hurst_threshold": self.min_hurst_threshold,
            "max_hurst_threshold": self.max_hurst_threshold,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "buffer_depth": len(self._vol_history),
            "structure_values": {k: round(v, 8) for k, v in self._structure_values.items()}
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._vol_history.clear()
        self._timestamps.clear()
        self.estimated_hurst = 0.14
        self._is_blocked = False
        self._block_reason = ""
        self._structure_values.clear()
