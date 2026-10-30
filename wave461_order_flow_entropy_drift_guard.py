"""
Wave 461: Shannon-Rényi Order Flow Entropy Drift Guard
======================================================
Institutional Quantitative Mathematical Formulation:
Under Shannon (1948) "A Mathematical Theory of Communication", Rényi (1961),
and Bormetti, Cazzola, Livan, Mantegna & Treccani (2015) "Information Entropy in
High-Frequency Order Books", the information-theoretic entropy of discrete order book events
provides an instantaneous measure of algorithmic manipulation, sweep clustering, and flow toxicity.

Let discrete limit order book events be classified into a state alphabet S = {1, ..., M}:
- S=1: Aggressive Market Buy
- S=2: Aggressive Market Sell
- S=3: Passive Bid Limit Placement
- S=4: Passive Ask Limit Placement
- S=5: Bid Order Cancellation
- S=6: Ask Order Cancellation

Across a rolling window of N events, empirical event probabilities are:
    p_i = count(S = i) / N

1. Normalized Shannon Information Entropy:
    H_shannon = - sum_{i=1}^M p_i * log2(max(p_i, 1e-9))
    H_norm = H_shannon / log2(M)   (where H_norm in [0, 1])

2. Rényi Collision Entropy (alpha = 2):
    H_2 = - log2(sum_{i=1}^M p_i^2)
    H_2_norm = H_2 / log2(M)

In organic, healthy, liquidity-providing market conditions, order events arrive with high
stochastic dispersion across all categories, yielding high entropy: H_norm in [0.75, 1.0].

Pathological Regimes:
1. Algorithmic Monopolization / Sweep Clustering:
   When an institutional execution algorithm (TWAP/VWAP/Iceberg) or predatory HFT sweep
   monopolizes the book, order types collapse into a deterministic sub-sequence:
   H_norm < min_entropy_threshold (default: < 0.45)
   and max_p = max_i(p_i) > max_concentration_threshold (default: > 0.60)
2. Rapid Entropy Drift Collapse:
   d(H_norm)/dt < -0.30 s^-1 (sudden information evaporation)

Under collapsed entropy regimes, market depth is not genuine; passive limit orders are
adversely selected by aggressive deterministic sweeps. The guard trips an immediate
circuit breaker, blocking entries in the toxic direction.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave461OrderFlowEntropyDriftGuard:
    """
    Monitors Shannon and Rényi order flow entropy to detect deterministic algorithmic sweeps,
    quote stuffing, and adverse selection information cascades.
    """

    NUM_STATES = 6

    def __init__(
        self,
        window_size: int = 30,
        min_entropy_threshold: float = 0.45,
        max_concentration_threshold: float = 0.60,
        max_entropy_drift_rate: float = 0.30,
        min_samples: int = 15,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_size < 15:
            raise ValueError(f"window_size must be >= 15, got {window_size}")
        if not (0.20 <= min_entropy_threshold <= 0.85):
            raise ValueError(f"min_entropy_threshold must be in [0.20, 0.85], got {min_entropy_threshold}")
        if not (0.40 <= max_concentration_threshold <= 0.95):
            raise ValueError(f"max_concentration_threshold must be in [0.40, 0.95], got {max_concentration_threshold}")
        if max_entropy_drift_rate <= 0.05:
            raise ValueError(f"max_entropy_drift_rate must be > 0.05, got {max_entropy_drift_rate}")
        if min_samples < 10:
            raise ValueError(f"min_samples must be >= 10, got {min_samples}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_size: int = window_size
        self.min_entropy_threshold: float = min_entropy_threshold
        self.max_concentration_threshold: float = max_concentration_threshold
        self.max_entropy_drift_rate: float = max_entropy_drift_rate
        self.min_samples: int = min_samples
        self.cooldown_sec: float = cooldown_sec

        self._max_possible_entropy: float = math.log2(self.NUM_STATES)

        # Ring buffers: event types (1-6) and timestamps
        self._events: List[int] = []
        self._timestamps: List[float] = []
        self._entropy_history: List[float] = []

        # State telemetry
        self.shannon_entropy_norm: float = 1.0
        self.renyi_entropy_norm: float = 1.0
        self.max_concentration: float = 0.0
        self.dominant_event_type: int = 0
        self.entropy_drift_rate: float = 0.0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(self, event_type: int, timestamp: float) -> bool:
        """
        Record a new order book event type (1=MktBuy, 2=MktSell, 3=LimBid, 4=LimAsk, 5=CanBid, 6=CanAsk).
        Returns True if trading is blocked, False otherwise.
        """
        if not isinstance(event_type, (int, np.integer)):
            raise ValueError(f"event_type must be integer in [1, 6], got {type(event_type)}")
        if not (1 <= event_type <= self.NUM_STATES):
            raise ValueError(f"event_type must be in range [1, {self.NUM_STATES}], got {event_type}")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        self._events.append(int(event_type))
        self._timestamps.append(float(timestamp))

        # Maintain window size
        if len(self._events) > self.window_size:
            self._events.pop(0)
            self._timestamps.pop(0)
            if self._entropy_history:
                self._entropy_history.pop(0)

        # Check active cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        if len(self._events) < self.min_samples:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLES"
            self.blocked_side = None
            return False

        # Compute empirical state distribution
        counts = np.bincount(self._events, minlength=self.NUM_STATES + 1)[1:] # 1-indexed to 0-indexed
        n_total = float(len(self._events))
        probs = counts / n_total

        # Shannon Normalized Entropy
        nz_probs = probs[probs > 0]
        h_shannon = -float(np.sum(nz_probs * np.log2(nz_probs)))
        self.shannon_entropy_norm = float(h_shannon / self._max_possible_entropy)

        # Rényi Collision Entropy (alpha = 2)
        sum_p2 = float(np.sum(probs ** 2))
        h_renyi = -math.log2(max(sum_p2, 1e-9))
        self.renyi_entropy_norm = float(h_renyi / self._max_possible_entropy)

        # Concentration metrics
        self.max_concentration = float(np.max(probs))
        self.dominant_event_type = int(np.argmax(probs) + 1)

        # Entropy Drift Rate d(H)/dt
        self._entropy_history.append(self.shannon_entropy_norm)
        if len(self._entropy_history) >= 5:
            dt_drift = max(1e-3, self._timestamps[-1] - self._timestamps[-5])
            dH = self._entropy_history[-1] - self._entropy_history[-5]
            self.entropy_drift_rate = float(dH / dt_drift)
        else:
            self.entropy_drift_rate = 0.0

        # Evaluate Circuit Breaker
        entropy_collapsed = (
            self.shannon_entropy_norm < self.min_entropy_threshold and
            self.max_concentration > self.max_concentration_threshold
        )
        entropy_rapid_drain = (
            self.entropy_drift_rate < -self.max_entropy_drift_rate and
            self.shannon_entropy_norm < 0.60
        )

        if entropy_collapsed or entropy_rapid_drain:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Determine toxic adverse selection direction based on dominant event
            if self.dominant_event_type in (1, 6): # Aggressive Buy or Ask Cancellation (Bullish sweep)
                self.blocked_side = "BUY"
            elif self.dominant_event_type in (2, 5): # Aggressive Sell or Bid Cancellation (Bearish sweep)
                self.blocked_side = "SELL"
            else:
                self.blocked_side = "ALL"

            trigger = "ENTROPY_COLLAPSE" if entropy_collapsed else "RAPID_ENTROPY_DRAIN"
            self._block_reason = (
                f"{trigger}: H_norm={self.shannon_entropy_norm:.3f} < {self.min_entropy_threshold:.3f}, "
                f"max_p={self.max_concentration:.1%} (event {self.dominant_event_type}), "
                f"dH/dt={self.entropy_drift_rate:.2f}/s (blocked: {self.blocked_side})"
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
        """OmniTrade interface compatibility."""
        if not self._is_blocked:
            return False
        if self.blocked_side in ("ALL", None):
            return True
        return side.upper() == self.blocked_side

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave461OrderFlowEntropyDriftGuard",
            "shannon_entropy_norm": round(self.shannon_entropy_norm, 4),
            "renyi_entropy_norm": round(self.renyi_entropy_norm, 4),
            "max_concentration": round(self.max_concentration, 4),
            "dominant_event_type": self.dominant_event_type,
            "entropy_drift_rate": round(self.entropy_drift_rate, 4),
            "min_entropy_threshold": self.min_entropy_threshold,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._events)
        }

    def reset(self) -> None:
        """Reset internal buffers and state."""
        self._events.clear()
        self._timestamps.clear()
        self._entropy_history.clear()
        self.shannon_entropy_norm = 1.0
        self.renyi_entropy_norm = 1.0
        self.max_concentration = 0.0
        self.dominant_event_type = 0
        self.entropy_drift_rate = 0.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
