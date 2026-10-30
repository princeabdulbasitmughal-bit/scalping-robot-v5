"""
Wave 477: Cross-Asset Lead-Lag Granger Causality Guard
=====================================================
Institutional Quantitative Mathematical Formulation:
Under Granger (1969) "Investigating Causal Relations by Econometric Models and
Cross-spectral Methods", Hasbrouck (2003), and Hiemstra & Jones (1994), high-frequency
price discovery often originates in benchmark lead assets X_t (e.g. DXY or US10Y yields)
before diffusing into follower assets Y_t (e.g. XAUUSD).

Let Y_t be follower log-returns and X_t be benchmark lead order flow/returns over rolling window N:
1. Restricted Model (Local Autoregression):
   Y_t = c_0 + sum_{i=1}^p gamma_i Y_{t-i} + epsilon_{r, t}
   Residual Sum of Squares: RSS_r = sum_{t=p+1}^N epsilon_{r, t}^2

2. Unrestricted Model (Bivariate VAR with Cross-Asset Coupling):
   Y_t = c_1 + sum_{i=1}^p alpha_i Y_{t-i} + sum_{j=1}^p beta_j X_{t-j} + epsilon_{u, t}
   Residual Sum of Squares: RSS_u = sum_{t=p+1}^N epsilon_{u, t}^2

3. Granger Causality Intensity Metric:
   Gamma_{cross}(t) = (RSS_r - RSS_u) / max(RSS_r, 1e-6) in [0.0, 1.0]

4. Empirical F-Statistic:
   F_{stat} = [ (RSS_r - RSS_u) / p ] / [ RSS_u / max(N - 2*p - 1, 1) ]

5. Predicted Directional Lead Drift:
   mu_{lead}(t) = sum_{j=1}^p beta_j X_{t-j}

Circuit Breakers:
- When Gamma_{cross}(t) > max_granger_intensity (default: > 0.40) and F_{stat} > f_stat_critical (default: > 4.50):
  The local order book is under the deterministic causal influence of foreign institutional flow.
- Directional attribution:
  - When mu_{lead}(t) > min_lead_drift: Lead asset forecasts upward price thrust -> SELL entries toxic.
  - When mu_{lead}(t) < -min_lead_drift: Lead asset forecasts downward price plunge -> BUY entries toxic.
  - When causality is high without clear drift: ALL entries blocked.

When triggered, the guard isolates trade routing, preventing execution against incoming informed lead flows.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave477CrossAssetLeadLagGrangerCausalityGuard:
    """
    Monitors rolling bivariate autoregressive Granger causality and directional lead drift
    between external benchmark flows and target asset returns.
    """

    def __init__(
        self,
        window_size: int = 30,
        min_samples: int = 15,
        lag_order: int = 2,
        max_granger_intensity: float = 0.40,
        f_stat_critical: float = 4.50,
        min_lead_drift: float = 0.002,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_size < 20:
            raise ValueError(f"window_size must be >= 20, got {window_size}")
        if min_samples < 12:
            raise ValueError(f"min_samples must be >= 12, got {min_samples}")
        if min_samples > window_size:
            raise ValueError(f"min_samples ({min_samples}) cannot exceed window_size ({window_size})")
        if lag_order not in (1, 2, 3):
            raise ValueError(f"lag_order must be 1, 2, or 3, got {lag_order}")
        if not (0.15 <= max_granger_intensity <= 0.85):
            raise ValueError(f"max_granger_intensity must be in [0.15, 0.85], got {max_granger_intensity}")
        if f_stat_critical <= 1.0:
            raise ValueError(f"f_stat_critical must be > 1.0, got {f_stat_critical}")
        if min_lead_drift <= 0.0:
            raise ValueError(f"min_lead_drift must be > 0.0, got {min_lead_drift}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_size: int = window_size
        self.min_samples: int = min_samples
        self.lag_order: int = lag_order
        self.max_granger_intensity: float = max_granger_intensity
        self.f_stat_critical: float = f_stat_critical
        self.min_lead_drift: float = min_lead_drift
        self.cooldown_sec: float = cooldown_sec

        # State buffers
        self._y_history: List[float] = []
        self._x_history: List[float] = []

        # Telemetry metrics
        self.granger_intensity: float = 0.0
        self.f_stat: float = 0.0
        self.predicted_lead_drift: float = 0.0
        self.sample_count: int = 0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        local_return: float,
        lead_flow: float,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous local asset return and foreign lead order flow.
        Returns True if trading is blocked, False otherwise.
        """
        if not (math.isfinite(local_return) and math.isfinite(lead_flow)):
            raise ValueError("local_return and lead_flow must be finite numbers")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        self._y_history.append(local_return)
        self._x_history.append(lead_flow)
        if len(self._y_history) > self.window_size:
            self._y_history.pop(0)
            self._x_history.pop(0)

        self.sample_count = len(self._y_history)
        p = self.lag_order
        n_obs = self.sample_count - p

        if self.sample_count < self.min_samples or n_obs <= (2 * p + 2):
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = "INSUFFICIENT_SAMPLES"
            return False

        # Construct restricted and unrestricted design matrices
        y_arr = np.array(self._y_history, dtype=np.float64)
        x_arr = np.array(self._x_history, dtype=np.float64)

        Y = y_arr[p:]

        # Restricted: constant + lags of Y
        X_r_cols = [np.ones(n_obs)]
        for i in range(1, p + 1):
            X_r_cols.append(y_arr[p - i: -i if i > 0 else None])
        X_r = np.column_stack(X_r_cols)

        # Unrestricted: constant + lags of Y + lags of X
        X_u_cols = list(X_r_cols)
        for j in range(1, p + 1):
            X_u_cols.append(x_arr[p - j: -j if j > 0 else None])
        X_u = np.column_stack(X_u_cols)

        # Least squares solutions
        try:
            beta_r, res_r, _, _ = np.linalg.lstsq(X_r, Y, rcond=None)
            rss_r = float(np.sum((Y - X_r @ beta_r) ** 2))

            beta_u, res_u, _, _ = np.linalg.lstsq(X_u, Y, rcond=None)
            rss_u = float(np.sum((Y - X_u @ beta_u) ** 2))

            # Granger intensity
            rss_diff = max(0.0, rss_r - rss_u)
            self.granger_intensity = float(rss_diff / max(rss_r, 1e-6))

            # F-stat
            df2 = max(n_obs - 2 * p - 1, 1)
            self.f_stat = float((rss_diff / p) / max(rss_u / df2, 1e-6))

            # Predicted lead drift from recent lags of X
            recent_x_lags = np.array([x_arr[-j] for j in range(1, p + 1)], dtype=np.float64)
            lead_betas = beta_u[p + 1: 2 * p + 1]
            self.predicted_lead_drift = float(np.dot(lead_betas, recent_x_lags))

        except Exception:
            self.granger_intensity = 0.0
            self.f_stat = 0.0
            self.predicted_lead_drift = 0.0

        # Evaluate Circuit Breakers
        causality_breached = (self.granger_intensity > self.max_granger_intensity and self.f_stat > self.f_stat_critical)

        if causality_breached:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution based on predicted lead drift
            if abs(self.predicted_lead_drift) > self.min_lead_drift:
                if self.predicted_lead_drift > self.min_lead_drift:
                    self.blocked_side = "SELL" # Lead asset predicts upward surge -> shorting is toxic
                    side_note = "BULLISH_LEAD_LAG_SURGE"
                else:
                    self.blocked_side = "BUY" # Lead asset predicts downward crash -> buying is toxic
                    side_note = "BEARISH_LEAD_LAG_DUMP"
            else:
                self.blocked_side = "ALL"
                side_note = "BILATERAL_GRANGER_COUPLING"

            self._block_reason = (
                f"GRANGER_CAUSALITY_SPIKE: Gamma={self.granger_intensity:.3f} (max={self.max_granger_intensity:.3f}), "
                f"F={self.f_stat:.2f} (crit={self.f_stat_critical:.2f}), drift={self.predicted_lead_drift:.4f} "
                f"[{side_note}], blocked: {self.blocked_side}"
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
            "guard": "Wave477CrossAssetLeadLagGrangerCausalityGuard",
            "granger_intensity": round(self.granger_intensity, 4),
            "f_stat": round(self.f_stat, 2),
            "predicted_lead_drift": round(self.predicted_lead_drift, 6),
            "sample_count": self.sample_count,
            "max_granger_intensity": self.max_granger_intensity,
            "f_stat_critical": self.f_stat_critical,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self._y_history.clear()
        self._x_history.clear()
        self.granger_intensity = 0.0
        self.f_stat = 0.0
        self.predicted_lead_drift = 0.0
        self.sample_count = 0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
