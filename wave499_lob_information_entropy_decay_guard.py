"""
Wave 499: High-Frequency Limit Order Book Shannon & Tsallis Information Entropy Decay Guard
========================================================================================
Institutional Quantitative Mathematical Formulation:
Under Shannon (1948), Tsallis (1988), and Biais, Hillion & Spatt (1995), the distribution
of limit order book liquidity across depth levels carries quantifiable informational structure.

Given normalized depth probabilities p_i = v_i / sum_{k=1}^K v_k across K depth levels:

1. Shannon Information Entropy:
       H_shannon = -sum_{i=1}^K p_i * ln(p_i)
   Normalized Shannon Entropy:
       H_norm = H_shannon / ln(K) in [0.0, 1.0]

   - Low Entropy (H_norm < 0.35): Liquidity is pinned at a single price level, leaving the rest
     of the book hollowed out (extreme liquidity vacuum / cliff risk).
   - High Entropy (H_norm > 0.92): Liquidity is completely scattered and disorganized across levels,
     signaling structural disorder and loss of market maker quoting consensus.

2. Tsallis Non-Extensive Entropy (q = 1.5):
       S_q = (1 / (q - 1)) * (1 - sum_{i=1}^K p_i^q)

3. Entropy Decay Rate (Microstructure Velocity):
       dH_rate = (H_norm(t) - H_norm(t - dt)) / dt

4. Composite Entropy Fragility Index (Psi_entropy):
       Psi_entropy = 0.50 * min(1.0, max(0.0, abs(H_norm - 0.70) / 0.25))
                   + 0.50 * min(1.0, max(0.0, (abs(dH_rate) - 0.40) / 0.80)) in [0.0, 1.0]

Circuit Breakers:
1. LOB_ENTROPY_COLLAPSE: H_norm <= min_entropy_threshold (default: <= 0.35) -> HALT_ALL
2. LOB_ENTROPY_DISORGANIZATION: H_norm >= max_entropy_threshold (default: >= 0.92) or Psi_entropy >= critical_fragility_threshold (default: >= 0.75) -> HALT_ALL
3. Asymmetric Directional Entropy Vacuums:
   - H_bid <= 0.35 and H_ask >= 0.60 -> BLOCK_SELL (bid-side liquidity cliff / vacuum)
   - H_ask <= 0.35 and H_bid >= 0.60 -> BLOCK_BUY (ask-side liquidity cliff / vacuum)
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave499LobInformationEntropyDecayGuard:
    """
    Monitors Shannon & Tsallis order book entropy, liquidity concentration vacuums,
    and instantaneous structural disorganization velocity across depth levels.
    """

    def __init__(
        self,
        min_entropy_threshold: float = 0.35,
        max_entropy_threshold: float = 0.92,
        critical_fragility_threshold: float = 0.75,
        max_decay_rate_threshold: float = 1.20,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.15 <= min_entropy_threshold <= 0.50):
            raise ValueError(f"min_entropy_threshold must be in [0.15, 0.50], got {min_entropy_threshold}")
        if not (0.75 <= max_entropy_threshold <= 0.99):
            raise ValueError(f"max_entropy_threshold must be in [0.75, 0.99], got {max_entropy_threshold}")
        if not (0.50 <= critical_fragility_threshold <= 0.95):
            raise ValueError(f"critical_fragility_threshold must be in [0.50, 0.95], got {critical_fragility_threshold}")
        if not (0.50 <= max_decay_rate_threshold <= 3.00):
            raise ValueError(f"max_decay_rate_threshold must be in [0.50, 3.00], got {max_decay_rate_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.min_entropy_threshold: float = min_entropy_threshold
        self.max_entropy_threshold: float = max_entropy_threshold
        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.max_decay_rate_threshold: float = max_decay_rate_threshold
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self.prev_entropy: Optional[float] = None
        self.prev_timestamp: Optional[float] = None
        self.breaker_active: bool = False
        self.breaker_tripped_at: float = 0.0
        self.last_trip_reason: str = "NONE"

    def reset(self) -> None:
        """Reset internal temporal states."""
        self.prev_entropy = None
        self.prev_timestamp = None
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def compute_orderbook_entropy(
        self,
        volumes: List[float],
        q: float = 1.5
    ) -> Dict[str, float]:
        """
        Computes normalized Shannon entropy H_norm and Tsallis entropy S_q
        across discrete depth levels.
        """
        if len(volumes) < 2:
            raise ValueError(f"Must provide at least 2 depth levels, got {len(volumes)}")

        v = np.array(volumes, dtype=np.float64)
        if np.any(v < 0.0):
            raise ValueError("Depth volumes must be non-negative")

        total_vol = float(np.sum(v))
        k = len(v)
        max_shannon = math.log(k)

        if total_vol <= 1e-12:
            return {"h_norm": 0.0, "s_tsallis": 0.0, "shannon": 0.0}

        p = v / total_vol
        # Filter zero probabilities for Shannon
        p_pos = p[p > 1e-12]

        shannon = float(-np.sum(p_pos * np.log(p_pos)))
        h_norm = float(np.clip(shannon / max_shannon, 0.0, 1.0))

        # Tsallis entropy with parameter q
        if abs(q - 1.0) < 1e-6:
            s_tsallis = shannon
        else:
            s_tsallis = float((1.0 / (q - 1.0)) * (1.0 - np.sum(p ** q)))

        return {
            "h_norm": h_norm,
            "s_tsallis": s_tsallis,
            "shannon": shannon
        }

    def evaluate(
        self,
        h_norm: float,
        h_bid: float = 0.70,
        h_ask: float = 0.70,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates order book entropy level, decay velocity, and asymmetric vacuums.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= h_norm <= 1.0):
            raise ValueError(f"h_norm must be in [0.0, 1.0], got {h_norm}")
        if not (0.0 <= h_bid <= 1.0):
            raise ValueError(f"h_bid must be in [0.0, 1.0], got {h_bid}")
        if not (0.0 <= h_ask <= 1.0):
            raise ValueError(f"h_ask must be in [0.0, 1.0], got {h_ask}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "h_norm": h_norm,
                    "psi_entropy": 1.0,
                    "dh_rate": 0.0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate decay rate dH_rate
        dh_rate = 0.0
        if self.prev_entropy is not None and self.prev_timestamp is not None:
            dt = now - self.prev_timestamp
            if dt > 1e-6:
                dh_rate = (h_norm - self.prev_entropy) / dt

        self.prev_entropy = h_norm
        self.prev_timestamp = now

        # Compute composite entropy fragility index Psi_entropy in [0.0, 1.0]
        # Normal equilibrium around 0.65-0.75
        dev = abs(h_norm - 0.70)
        phi_level = min(1.0, max(0.0, dev / 0.25))
        phi_velocity = min(1.0, max(0.0, (abs(dh_rate) - 0.40) / 0.80))
        psi_entropy = float(np.clip(0.50 * phi_level + 0.50 * phi_velocity, 0.0, 1.0))

        # 1. Critical Disorganization Velocity Breaker
        if abs(dh_rate) >= self.max_decay_rate_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"ENTROPY_DECAY_VELOCITY_CRITICAL: |dh_rate|={abs(dh_rate):.3f} >= {self.max_decay_rate_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_norm": h_norm,
                "psi_entropy": psi_entropy,
                "dh_rate": dh_rate
            }

        # 2. Critical Order Book Entropy Collapse (Pin Vacuum)
        if h_norm <= self.min_entropy_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"LOB_ENTROPY_COLLAPSE: h_norm={h_norm:.3f} <= {self.min_entropy_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_norm": h_norm,
                "psi_entropy": psi_entropy,
                "dh_rate": dh_rate
            }

        # 3. Critical Order Book Disorganization / Scatter
        if h_norm >= self.max_entropy_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"LOB_ENTROPY_DISORGANIZATION: h_norm={h_norm:.3f} >= {self.max_entropy_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_norm": h_norm,
                "psi_entropy": psi_entropy,
                "dh_rate": dh_rate
            }

        if psi_entropy >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"ENTROPY_FRAGILITY_CRITICAL: psi_entropy={psi_entropy:.3f} >= {self.critical_fragility_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_norm": h_norm,
                "psi_entropy": psi_entropy,
                "dh_rate": dh_rate
            }

        # 4. Asymmetric Directional Entropy Vacuums
        if h_bid <= self.min_entropy_threshold and h_ask >= 0.60:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"BID_SIDE_ENTROPY_VACUUM: h_bid={h_bid:.2f} <= {self.min_entropy_threshold:.2f}",
                "h_norm": h_norm,
                "psi_entropy": psi_entropy,
                "dh_rate": dh_rate
            }

        if h_ask <= self.min_entropy_threshold and h_bid >= 0.60:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"ASK_SIDE_ENTROPY_VACUUM: h_ask={h_ask:.2f} <= {self.min_entropy_threshold:.2f}",
                "h_norm": h_norm,
                "psi_entropy": psi_entropy,
                "dh_rate": dh_rate
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "ENTROPY_EQUILIBRIUM_ACTIVE",
            "h_norm": h_norm,
            "psi_entropy": psi_entropy,
            "dh_rate": dh_rate
        }
