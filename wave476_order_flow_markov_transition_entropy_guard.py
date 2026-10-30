"""
Wave 476: Order Flow Markov Transition Entropy Guard
====================================================
Institutional Quantitative Mathematical Formulation:
Under Cont, Kukanov & Stoikov (2014) "The Price Impact of Order Book Events",
Lehalle & Mounjid (2017), and Shannon (1948), the sequence of consecutive trade signs
epsilon_t in {+1, -1} (where +1 = buyer-initiated, -1 = seller-initiated) can be modeled
as a 2-state discrete-time Markov chain.

The transition probability matrix P is:
    P = [[p_{++}, 1 - p_{++}],
         [1 - p_{--}, p_{--}]]

where p_{++} = P(epsilon_t = +1 | epsilon_{t-1} = +1), and
      p_{--} = P(epsilon_t = -1 | epsilon_{t-1} = -1).

The stationary distribution pi = [pi_+, pi_-] satisfies pi * P = pi:
    pi_+ = (1 - p_{--}) / max(2.0 - p_{++} - p_{--}, 1e-4)
    pi_- = 1.0 - pi_+

The Markov Entropy Rate H(P) in bits/symbol is:
    H(P) = - pi_+ * (p_{++} * log2(p_{++}) + (1 - p_{++}) * log2(1 - p_{++}))
           - pi_- * ((1 - p_{--}) * log2(1 - p_{--}) + p_{--} * log2(p_{--}))

Normalized Markov Entropy H_{norm} in [0.0, 1.0] is:
    H_{norm} = H(P) / log2(2) = H(P)

Microstructure Invariants:
1. Markov Transition Entropy Collapse:
   H_{norm} < min_entropy_threshold (default: < 0.45)
   Normal two-sided trading has H_{norm} > 0.85. When H_{norm} collapses toward 0.0,
   order flow has become nearly deterministic, driven by algorithmic execution algorithms
   (TWAP/VWAP/POV icebergs) carving through the book.

2. Directional Continuation Herding:
   - When p_{++} > max_continuation_prob (default: > 0.82): Persistent buyer herding -> SELL entries toxic.
   - When p_{--} > max_continuation_prob (default: > 0.82): Persistent seller herding -> BUY entries toxic.
   - When general entropy collapse occurs: ALL entries blocked.

When triggered, the guard isolates trade routing, protecting against toxic adverse selection
from institutional execution algorithms.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave476OrderFlowMarkovTransitionEntropyGuard:
    """
    Monitors 2-state Markov chain trade sign transition probabilities, stationary distribution,
    and Markov entropy rate to identify algorithmic order slicing and herding.
    """

    def __init__(
        self,
        window_size: int = 30,
        min_samples: int = 15,
        min_entropy_threshold: float = 0.45,
        max_continuation_prob: float = 0.82,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_size < 15:
            raise ValueError(f"window_size must be >= 15, got {window_size}")
        if min_samples < 10:
            raise ValueError(f"min_samples must be >= 10, got {min_samples}")
        if min_samples > window_size:
            raise ValueError(f"min_samples ({min_samples}) cannot exceed window_size ({window_size})")
        if not (0.20 <= min_entropy_threshold <= 0.80):
            raise ValueError(f"min_entropy_threshold must be in [0.20, 0.80], got {min_entropy_threshold}")
        if not (0.65 <= max_continuation_prob <= 0.98):
            raise ValueError(f"max_continuation_prob must be in [0.65, 0.98], got {max_continuation_prob}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_size: int = window_size
        self.min_samples: int = min_samples
        self.min_entropy_threshold: float = min_entropy_threshold
        self.max_continuation_prob: float = max_continuation_prob
        self.cooldown_sec: float = cooldown_sec

        # Historical trade signs
        self._signs: List[int] = []

        # Telemetry metrics
        self.markov_entropy: float = 1.0
        self.p_buy_buy: float = 0.50
        self.p_sell_sell: float = 0.50
        self.pi_buy: float = 0.50
        self.pi_sell: float = 0.50
        self.sample_count: int = 0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def _binary_entropy(self, p: float) -> float:
        """Compute binary entropy -p*log2(p) - (1-p)*log2(1-p)."""
        eps = 1e-6
        p = min(1.0 - eps, max(eps, p))
        return -p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p)

    def update(
        self,
        trade_sign: int,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous trade sign (+1 for buyer-initiated, -1 for seller-initiated).
        Returns True if trading is blocked, False otherwise.
        """
        if trade_sign not in (1, -1):
            raise ValueError(f"trade_sign must be +1 or -1, got {trade_sign}")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        self._signs.append(trade_sign)
        if len(self._signs) > self.window_size:
            self._signs.pop(0)

        self.sample_count = len(self._signs)
        if self.sample_count < self.min_samples:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = "INSUFFICIENT_SAMPLES"
            return False

        # Count 2-state Markov transitions
        n_buy_buy = 0
        n_buy_sell = 0
        n_sell_buy = 0
        n_sell_sell = 0

        for i in range(len(self._signs) - 1):
            s_curr = self._signs[i]
            s_next = self._signs[i + 1]
            if s_curr == 1:
                if s_next == 1:
                    n_buy_buy += 1
                else:
                    n_buy_sell += 1
            else:
                if s_next == 1:
                    n_sell_buy += 1
                else:
                    n_sell_sell += 1

        tot_buy = n_buy_buy + n_buy_sell
        tot_sell = n_sell_buy + n_sell_sell

        # Empirical transition probabilities with Laplace smoothing
        self.p_buy_buy = (n_buy_buy + 0.5) / (tot_buy + 1.0) if tot_buy >= 0 else 0.50
        self.p_sell_sell = (n_sell_sell + 0.5) / (tot_sell + 1.0) if tot_sell >= 0 else 0.50

        # Stationary distribution
        denom_pi = max(2.0 - self.p_buy_buy - self.p_sell_sell, 1e-4)
        self.pi_buy = (1.0 - self.p_sell_sell) / denom_pi
        self.pi_sell = 1.0 - self.pi_buy

        # Markov entropy rate H(P)
        h_buy = self._binary_entropy(self.p_buy_buy)
        h_sell = self._binary_entropy(self.p_sell_sell)
        self.markov_entropy = max(0.0, min(1.0, self.pi_buy * h_buy + self.pi_sell * h_sell))

        # Evaluate Circuit Breakers
        entropy_collapsed = (self.markov_entropy < self.min_entropy_threshold)
        buy_herding = (self.p_buy_buy > self.max_continuation_prob)
        sell_herding = (self.p_sell_sell > self.max_continuation_prob)

        if entropy_collapsed or buy_herding or sell_herding:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution
            if buy_herding and not sell_herding:
                self.blocked_side = "SELL" # Relentless buy herding -> selling is toxic
                side_note = "ALGORITHMIC_BUY_HERDING"
            elif sell_herding and not buy_herding:
                self.blocked_side = "BUY" # Relentless sell herding -> buying is toxic
                side_note = "ALGORITHMIC_SELL_HERDING"
            else:
                self.blocked_side = "ALL"
                side_note = "MARKOV_ENTROPY_COLLAPSE"

            trigger = (
                "MARKOV_BUY_FLOW_HERDING" if (buy_herding and not sell_herding) else
                ("MARKOV_SELL_FLOW_HERDING" if (sell_herding and not buy_herding) else "MARKOV_ENTROPY_COLLAPSE")
            )
            self._block_reason = (
                f"{trigger}: H_markov={self.markov_entropy:.3f} (min={self.min_entropy_threshold:.3f}), "
                f"p(+|+):={self.p_buy_buy:.2f}, p(-|-):={self.p_sell_sell:.2f} [{side_note}], blocked: {self.blocked_side}"
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
            "guard": "Wave476OrderFlowMarkovTransitionEntropyGuard",
            "markov_entropy": round(self.markov_entropy, 4),
            "p_buy_buy": round(self.p_buy_buy, 4),
            "p_sell_sell": round(self.p_sell_sell, 4),
            "pi_buy": round(self.pi_buy, 4),
            "pi_sell": round(self.pi_sell, 4),
            "sample_count": self.sample_count,
            "min_entropy_threshold": self.min_entropy_threshold,
            "max_continuation_prob": self.max_continuation_prob,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self._signs.clear()
        self.markov_entropy = 1.0
        self.p_buy_buy = 0.50
        self.p_sell_sell = 0.50
        self.pi_buy = 0.50
        self.pi_sell = 0.50
        self.sample_count = 0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
