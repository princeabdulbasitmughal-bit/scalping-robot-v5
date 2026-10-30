"""
Wave 493: Microstructure Hidden Liquidity Iceberg Detector & Adverse Selection Replenishment Guard
==================================================================================================
Institutional Quantitative Mathematical Formulation:
Under Esser & Trotha (2014) "Optimal execution of iceberg orders in a limit order book",
De Winne & D'Hondt (2007), and Bessembinder et al. (2009), algorithmic institutional orders
mask substantial hidden reserve liquidity behind small visible display quantities:

1. Hidden Iceberg Volume Ratio:
   R_bid = max(0.0, (Q_exec_bid - V_vis_bid)) / max(V_vis_bid, 1e-6)
   R_ask = max(0.0, (Q_exec_ask - V_vis_ask)) / max(V_vis_ask, 1e-6)

   - When R_bid >= 2.50, an institutional buyer is reloading invisible size (absorption wall).
   - When R_ask >= 2.50, an institutional seller is reloading invisible size (absorption ceiling).

2. Algorithmic Replenishment Latency:
   tau_replenish <= 0.050 s (50 ms) indicates automated institutional algorithmic execution.

Circuit Breakers:
1. EXTREME_ICEBERG_BREACH: max(R_bid, R_ask) >= critical_iceberg_threshold (default: >= 5.0) -> HALT_ALL
2. ICEBERG_PIN_HALT: R_bid >= iceberg_detect_threshold and R_ask >= iceberg_detect_threshold (default: >= 2.50) -> HALT_ALL
3. Directional Absorption Overrides:
   - R_ask >= iceberg_detect_threshold (default: >= 2.50) -> BLOCK_BUY (absorbing buy orders into ceiling)
   - R_bid >= iceberg_detect_threshold (default: >= 2.50) -> BLOCK_SELL (absorbing sell orders into floor)
"""

import math
import time
from typing import List, Dict, Any, Optional


class Wave493HiddenIcebergAdverseReplenishmentGuard:
    """
    Detects institutional iceberg orders, hidden reserve replenishment ratios,
    and adverse absorption ceilings/floors to prevent toxic routing.
    """

    def __init__(
        self,
        iceberg_detect_threshold: float = 2.50,
        critical_iceberg_threshold: float = 5.0,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (1.20 <= iceberg_detect_threshold <= 4.0):
            raise ValueError(f"iceberg_detect_threshold must be in [1.20, 4.0], got {iceberg_detect_threshold}")
        if not (3.50 <= critical_iceberg_threshold <= 10.0):
            raise ValueError(f"critical_iceberg_threshold must be in [3.50, 10.0], got {critical_iceberg_threshold}")
        if iceberg_detect_threshold >= critical_iceberg_threshold:
            raise ValueError("iceberg_detect_threshold must be strictly less than critical_iceberg_threshold")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.iceberg_detect_threshold: float = iceberg_detect_threshold
        self.critical_iceberg_threshold: float = critical_iceberg_threshold
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self.breaker_active: bool = False
        self.breaker_tripped_at: float = 0.0
        self.last_trip_reason: str = "NONE"

    def reset(self) -> None:
        """Reset temporal state."""
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def compute_iceberg_ratios(
        self,
        exec_volume_bid: float,
        vis_volume_bid: float,
        exec_volume_ask: float,
        vis_volume_ask: float
    ) -> Dict[str, float]:
        """
        Compute hidden-to-visible volume ratios for bid and ask quotes.
        """
        if exec_volume_bid < 0.0 or vis_volume_bid < 0.0 or exec_volume_ask < 0.0 or vis_volume_ask < 0.0:
            raise ValueError("All volumes must be non-negative")

        r_bid = max(0.0, (exec_volume_bid - vis_volume_bid)) / max(vis_volume_bid, 1e-6)
        r_ask = max(0.0, (exec_volume_ask - vis_volume_ask)) / max(vis_volume_ask, 1e-6)

        return {
            "r_bid": float(r_bid),
            "r_ask": float(r_ask)
        }

    def evaluate(
        self,
        r_bid: float,
        r_ask: float,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate iceberg absorption ratios and trigger protective halts.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Range validations
        if r_bid < 0.0:
            raise ValueError(f"r_bid must be non-negative, got {r_bid}")
        if r_ask < 0.0:
            raise ValueError(f"r_ask must be non-negative, got {r_ask}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "r_bid": r_bid,
                    "r_ask": r_ask
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        max_r = max(r_bid, r_ask)

        # 1. Extreme Iceberg Size Breach
        if max_r >= self.critical_iceberg_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"EXTREME_ICEBERG_BREACH: max(R_bid, R_ask)={max_r:.2f} >= {self.critical_iceberg_threshold:.2f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "r_bid": r_bid,
                "r_ask": r_ask
            }

        # 2. Iceberg Pin Halt (Bilateral Icebergs)
        bid_iceberg = r_bid >= self.iceberg_detect_threshold
        ask_iceberg = r_ask >= self.iceberg_detect_threshold

        if bid_iceberg and ask_iceberg:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"ICEBERG_PIN_HALT: Bilateral icebergs (R_bid={r_bid:.2f}, R_ask={r_ask:.2f} >= {self.iceberg_detect_threshold:.2f})"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "r_bid": r_bid,
                "r_ask": r_ask
            }

        # 3. Directional Absorption Overrides
        if ask_iceberg:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"ASK_ICEBERG_CEILING: R_ask={r_ask:.2f} >= {self.iceberg_detect_threshold:.2f}",
                "r_bid": r_bid,
                "r_ask": r_ask
            }

        if bid_iceberg:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"BID_ICEBERG_FLOOR: R_bid={r_bid:.2f} >= {self.iceberg_detect_threshold:.2f}",
                "r_bid": r_bid,
                "r_ask": r_ask
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "NORMAL_VISIBLE_DEPTH",
            "r_bid": r_bid,
            "r_ask": r_ask
        }
