"""
Wave 467: Cross-Impact Propagator & Transient Market Decay Guard
===============================================================
Institutional Quantitative Mathematical Formulation:
Under Bouchaud, Farmer & Lillo (2009) "How markets slowly digest changes in supply and demand",
Hasbrouck (2007) "Empirical Market Microstructure", and Schneider & Lillo (2019)
"Cross-impact and market microstructure", aggressive order flow on a leading reference
instrument L (e.g. BTCUSDT, EURUSD, XAUUSD futures or index proxies) propagates cross-asset
price impact to correlated follower asset F via a transient kernel G_LF(tau).

Transient Propagator Kernel:
    G_LF(tau) = Gamma_LF * (tau_0 / (tau + tau_0))^gamma

Where:
- tau = t - t_k >= 0 is the elapsed lag since aggressive lead trade k.
- tau_0 > 0 is the microscopic characteristic relaxation timescale (e.g. 0.2s).
- gamma in (0, 1.5] is the transient decay exponent (gamma ~ 0.5 under square-root sub-diffusion).
- Gamma_LF > 0 is the cross-coupling sensitivity coefficient (rho * sigma_F / sigma_L).

Cumulative Cross-Impact Pressure:
    I_cross(t) = sum_{k: t - window <= t_k <= t} Gamma_LF * sign_k * (v_k)^alpha * (tau_0 / (t - t_k + tau_0))^gamma

Where:
- sign_k in {+1, -1} is the trade direction on the leading asset (1 for buyer-initiated, -1 for seller-initiated).
- v_k > 0 is the trade size or normalized volume.
- alpha in [0.4, 1.0] is the concave impact volume scaling exponent (default alpha = 0.5 for square-root law).

Microstructure Adverse Selection & Circuit Breakers:
1. Directional Toxic Drift (Single-Sided Block):
   - If I_cross(t) > toxic_impact_threshold:
     Large upward cross-impact propagating -> Shorting/selling follower is toxic (BLOCK_SELL).
   - If I_cross(t) < -toxic_impact_threshold:
     Large downward cross-impact propagating -> Buying follower is toxic (BLOCK_BUY).

2. Severe Cross-Market Contagion (Double-Sided Emergency Lock):
   - If |I_cross(t)| > emergency_impact_threshold:
     Catastrophic cross-market shock wave -> Freeze all trading (BLOCK_ALL).

3. Cooldown & Transient Half-Life Relaxation:
   - Residual impact decays monotonically over time as elapsed tau increases.
   - Guard enforces minimum cooldown after any threshold breach to protect against stale quoting.
"""

import math
from typing import List, Dict, Any, Optional, Tuple


class Wave467CrossImpactPropagatorTransientDecayGuard:
    """
    Tracks order flow cross-impact from a correlated leading asset and computes
    transient power-law kernel decay to protect the follower instrument from
    adverse selection and stale quote arbitrage.
    """

    def __init__(
        self,
        coupling_coeff: float = 1.0,
        decay_exponent: float = 0.5,
        tau_0: float = 0.2,
        alpha: float = 0.5,
        toxic_impact_threshold: float = 5.0,
        emergency_impact_threshold: float = 15.0,
        window_sec: float = 10.0,
        cooldown_sec: float = 2.0
    ) -> None:
        if coupling_coeff <= 0.0:
            raise ValueError(f"coupling_coeff must be > 0.0, got {coupling_coeff}")
        if not (0.05 <= decay_exponent <= 2.5):
            raise ValueError(f"decay_exponent must be in [0.05, 2.5], got {decay_exponent}")
        if tau_0 <= 0.001:
            raise ValueError(f"tau_0 must be > 0.001, got {tau_0}")
        if not (0.2 <= alpha <= 1.2):
            raise ValueError(f"alpha must be in [0.2, 1.2], got {alpha}")
        if toxic_impact_threshold <= 0.1:
            raise ValueError(f"toxic_impact_threshold must be > 0.1, got {toxic_impact_threshold}")
        if emergency_impact_threshold <= toxic_impact_threshold:
            raise ValueError(
                f"emergency_impact_threshold ({emergency_impact_threshold}) must be > "
                f"toxic_impact_threshold ({toxic_impact_threshold})"
            )
        if window_sec < 1.0:
            raise ValueError(f"window_sec must be >= 1.0, got {window_sec}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.coupling_coeff: float = float(coupling_coeff)
        self.decay_exponent: float = float(decay_exponent)
        self.tau_0: float = float(tau_0)
        self.alpha: float = float(alpha)
        self.toxic_impact_threshold: float = float(toxic_impact_threshold)
        self.emergency_impact_threshold: float = float(emergency_impact_threshold)
        self.window_sec: float = float(window_sec)
        self.cooldown_sec: float = float(cooldown_sec)

        # Buffer of leading trades: (t_k, sign_k, volume_k)
        self._lead_trades: List[Tuple[float, int, float]] = []

        # State tracking
        self._prev_timestamp: float = -1.0
        self.current_cross_impact: float = 0.0
        self._is_blocked_buy: bool = False
        self._is_blocked_sell: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def record_lead_trade(self, timestamp: float, sign: int, volume: float) -> None:
        """
        Record an aggressive trade from the correlated lead instrument.
        - sign: +1 for buyer-initiated, -1 for seller-initiated.
        - volume: positive trade volume or notional.
        """
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._prev_timestamp >= 0.0 and timestamp < self._prev_timestamp:
            raise ValueError(f"timestamp must be monotonic. Got {timestamp} < {self._prev_timestamp}")
        if sign not in (1, -1):
            raise ValueError(f"sign must be +1 or -1, got {sign}")
        if not math.isfinite(volume) or volume <= 0.0:
            raise ValueError(f"volume must be positive and finite, got {volume}")

        self._prev_timestamp = timestamp
        self._lead_trades.append((timestamp, sign, volume))
        self._prune_history(timestamp)

    def _prune_history(self, current_time: float) -> None:
        """Prune trades outside the sliding memory window."""
        cutoff = current_time - self.window_sec
        self._lead_trades = [trade for trade in self._lead_trades if trade[0] >= cutoff]

    def update(self, current_time: float) -> bool:
        """
        Evaluate instantaneous cross-impact pressure at current_time.
        Returns True if ANY side (BUY or SELL) is blocked, False otherwise.
        """
        if not math.isfinite(current_time):
            raise ValueError(f"current_time must be finite, got {current_time}")
        if self._prev_timestamp >= 0.0 and current_time < self._prev_timestamp:
            raise ValueError(f"current_time must be monotonic. Got {current_time} < {self._prev_timestamp}")

        self._prev_timestamp = current_time
        self._prune_history(current_time)

        # Calculate cumulative cross-impact with power-law kernel decay
        cum_impact = 0.0
        for t_k, sign_k, vol_k in self._lead_trades:
            tau = max(0.0, current_time - t_k)
            # Kernel: G(tau) = (tau_0 / (tau + tau_0))^gamma
            kernel = (self.tau_0 / (tau + self.tau_0)) ** self.decay_exponent
            # Concave volume impact: vol^alpha
            concave_vol = vol_k ** self.alpha
            trade_impact = self.coupling_coeff * sign_k * concave_vol * kernel
            cum_impact += trade_impact

        self.current_cross_impact = float(cum_impact)

        # Check cooldown period
        in_cooldown = (self._last_breach_time > 0 and (current_time - self._last_breach_time) < self.cooldown_sec)

        # Circuit Breaker Logic
        abs_impact = abs(self.current_cross_impact)

        if abs_impact >= self.emergency_impact_threshold:
            self._is_blocked_buy = True
            self._is_blocked_sell = True
            self._last_breach_time = current_time
            self._block_reason = (
                f"EMERGENCY_CROSS_IMPACT_SPIKE: |I_cross|={abs_impact:.2f} >= "
                f"emergency threshold {self.emergency_impact_threshold:.2f} (impact={self.current_cross_impact:.2f})"
            )
            return True

        if self.current_cross_impact >= self.toxic_impact_threshold:
            # Massive upward cross-impact: shorting follower asset is toxic
            self._is_blocked_sell = True
            self._is_blocked_buy = in_cooldown  # If in cooldown from recent emergency, buy might also be held
            self._last_breach_time = current_time
            self._block_reason = (
                f"TOXIC_UPWARD_CROSS_IMPACT: I_cross=+{self.current_cross_impact:.2f} >= "
                f"threshold +{self.toxic_impact_threshold:.2f} -> SELL BLOCKED"
            )
            return True

        if self.current_cross_impact <= -self.toxic_impact_threshold:
            # Massive downward cross-impact: buying follower asset is toxic
            self._is_blocked_buy = True
            self._is_blocked_sell = in_cooldown
            self._last_breach_time = current_time
            self._block_reason = (
                f"TOXIC_DOWNWARD_CROSS_IMPACT: I_cross={self.current_cross_impact:.2f} <= "
                f"threshold -{self.toxic_impact_threshold:.2f} -> BUY BLOCKED"
            )
            return True

        # If we reach here and cooldown is active, maintain block
        if in_cooldown:
            # If recently breached, keep the previous block active during cooldown
            return (self._is_blocked_buy or self._is_blocked_sell)

        # Safe regime
        self._is_blocked_buy = False
        self._is_blocked_sell = False
        self._block_reason = ""
        return False

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade compatibility check for directional order blocking."""
        side_norm = side.strip().upper()
        if side_norm == "BUY":
            return self._is_blocked_buy
        elif side_norm == "SELL":
            return self._is_blocked_sell
        return self._is_blocked_buy or self._is_blocked_sell

    def is_blocked(self) -> bool:
        """Returns True if ANY side is blocked."""
        return self._is_blocked_buy or self._is_blocked_sell

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Auditing telemetry snapshot."""
        return {
            "guard": "Wave467CrossImpactPropagatorTransientDecayGuard",
            "current_cross_impact": round(self.current_cross_impact, 3),
            "coupling_coeff": self.coupling_coeff,
            "decay_exponent": self.decay_exponent,
            "tau_0": self.tau_0,
            "alpha": self.alpha,
            "toxic_impact_threshold": self.toxic_impact_threshold,
            "emergency_impact_threshold": self.emergency_impact_threshold,
            "active_lead_trades_count": len(self._lead_trades),
            "is_blocked_buy": self._is_blocked_buy,
            "is_blocked_sell": self._is_blocked_sell,
            "is_blocked": self.is_blocked(),
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self._lead_trades.clear()
        self._prev_timestamp = -1.0
        self.current_cross_impact = 0.0
        self._is_blocked_buy = False
        self._is_blocked_sell = False
        self._block_reason = ""
        self._last_breach_time = -1.0
