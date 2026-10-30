"""
Wave 471: LOB Liquidity Replenishment Half-Life Decay Guard
===========================================================
Institutional Quantitative Mathematical Formulation:
Under Biais, Hillion & Spatt (1995), Bouchaud et al. (2009) "How Markets Slowly Digest
Large Orders", and Cont & de Larrard (2013) "Order Book Dynamics in High Frequency with
Markov Chains", when liquidity is consumed by market orders, resting limit orders replenish
via an exponential relaxation process:
    D(t) = D_inf - (D_inf - D(t_0)) * exp(-lambda_rep * (t - t_0))

where lambda_rep is the instantaneous replenishment rate (sec^-1), and the replenishment half-life is:
    t_1/2 = ln(2) / max(lambda_rep, epsilon)  (seconds)

In healthy institutional markets, t_1/2 is fast (typically 0.10s to 0.80s) as automated
liquidity providers immediately post replacement depth. However, during toxic adverse selection
or algorithmic pullouts:
1. Replenishment Half-Life Blowout:
   t_1/2 > max_halflife_sec (default: > 3.0 sec)
   Market makers pull bids/asks and refuse to replenish, leaving an open air pocket.

2. Incomplete Replenishment Ratio (Hysteresis):
   eta_rep = [D(t) - D(t_0)] / max(D_pre - D(t_0), epsilon)
   When eta_rep < min_recovery_ratio (default: < 0.30) after an evaluation duration,
   liquidity recovery has stalled completely.

3. Replenishment Rate Asymmetry:
   A_rep = (lambda_bid - lambda_ask) / max(max(lambda_bid, lambda_ask), 1e-4)
   - When A_rep < -0.75: Bid replenishment is paralyzed -> BUY entries toxic.
   - When A_rep > 0.75: Ask replenishment is paralyzed -> SELL entries toxic.
   - When bilateral recovery stalls or t_1/2 blows out: ALL entries blocked.

This guard halts executions during post-shock liquidity voids, avoiding toxic fills into unreplenished books.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave471LiquidityReplenishmentHalflifeDecayGuard:
    """
    Monitors exponential post-shock liquidity replenishment rates, half-life decay,
    and directional replenishment asymmetries across the Limit Order Book.
    """

    def __init__(
        self,
        depletion_threshold_pct: float = 0.25,
        max_halflife_sec: float = 3.0,
        min_recovery_ratio: float = 0.30,
        eval_window_sec: float = 2.0,
        asymmetry_threshold: float = 0.75,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.10 <= depletion_threshold_pct <= 0.80):
            raise ValueError(f"depletion_threshold_pct must be in [0.10, 0.80], got {depletion_threshold_pct}")
        if not (0.50 <= max_halflife_sec <= 10.0):
            raise ValueError(f"max_halflife_sec must be in [0.50, 10.0], got {max_halflife_sec}")
        if not (0.10 <= min_recovery_ratio <= 0.80):
            raise ValueError(f"min_recovery_ratio must be in [0.10, 0.80], got {min_recovery_ratio}")
        if eval_window_sec < 0.50:
            raise ValueError(f"eval_window_sec must be >= 0.50, got {eval_window_sec}")
        if not (0.50 <= asymmetry_threshold <= 0.95):
            raise ValueError(f"asymmetry_threshold must be in [0.50, 0.95], got {asymmetry_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.depletion_threshold_pct: float = depletion_threshold_pct
        self.max_halflife_sec: float = max_halflife_sec
        self.min_recovery_ratio: float = min_recovery_ratio
        self.eval_window_sec: float = eval_window_sec
        self.asymmetry_threshold: float = asymmetry_threshold
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self.baseline_bid_depth: float = 0.0
        self.baseline_ask_depth: float = 0.0
        self.bid_halflife: float = 0.50
        self.ask_halflife: float = 0.50
        self.total_halflife: float = 0.50
        self.replenishment_asymmetry: float = 0.0
        self.recovery_ratio: float = 1.0

        self._in_depletion_event: bool = False
        self._depletion_time: float = -1.0
        self._depletion_total_depth: float = 0.0
        self._pre_depletion_total_depth: float = 0.0
        self._pre_depletion_bid: float = 0.0
        self._pre_depletion_ask: float = 0.0
        self._min_event_bid: float = 0.0
        self._min_event_ask: float = 0.0

        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def _estimate_halflife(self, d_curr: float, d_min: float, d_pre: float, dt: float) -> float:
        """
        Estimate replenishment half-life from exponential recovery:
        (d_pre - d_curr) / (d_pre - d_min) = exp(-lambda * dt)
        """
        eps = 1e-4
        denom = max(d_pre - d_min, eps)
        numer = max(d_pre - d_curr, 0.0)
        ratio = min(1.0, max(1e-4, numer / denom))

        if dt <= eps:
            return 0.50

        lambda_est = -math.log(ratio) / dt
        if lambda_est <= 1e-4:
            return 999.0 # Paralyzed replenishment
        return math.log(2.0) / lambda_est

    def update(
        self,
        bid_depth: float,
        ask_depth: float,
        timestamp: float
    ) -> bool:
        """
        Record instantaneous bid and ask orderbook depth.
        Returns True if trading is blocked, False otherwise.
        """
        if not (math.isfinite(bid_depth) and math.isfinite(ask_depth)):
            raise ValueError("bid_depth and ask_depth must be finite numbers")
        if bid_depth < 0.0 or ask_depth < 0.0:
            raise ValueError("Depth values must be non-negative")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        total_depth = bid_depth + ask_depth
        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        # Initialize rolling baselines
        if self.baseline_bid_depth <= 0.0:
            self.baseline_bid_depth = bid_depth
            self.baseline_ask_depth = ask_depth
            self._is_blocked = False
            return False

        base_total = self.baseline_bid_depth + self.baseline_ask_depth

        # Detect new depletion shock event
        if not self._in_depletion_event:
            # Check if total depth dropped by at least depletion_threshold_pct
            drop_ratio = (base_total - total_depth) / max(base_total, 1e-4)
            if drop_ratio >= self.depletion_threshold_pct:
                self._in_depletion_event = True
                self._depletion_time = timestamp
                self._depletion_total_depth = total_depth
                self._pre_depletion_total_depth = base_total
                self._pre_depletion_bid = self.baseline_bid_depth
                self._pre_depletion_ask = self.baseline_ask_depth
                self._min_event_bid = bid_depth
                self._min_event_ask = ask_depth
            else:
                # Smooth slow updating baseline
                self.baseline_bid_depth = 0.95 * self.baseline_bid_depth + 0.05 * bid_depth
                self.baseline_ask_depth = 0.95 * self.baseline_ask_depth + 0.05 * ask_depth
                self._is_blocked = False
                self.blocked_side = None
                self._block_reason = ""
                return False

        # In depletion event: track recovery dynamics
        self._min_event_bid = min(self._min_event_bid, bid_depth)
        self._min_event_ask = min(self._min_event_ask, ask_depth)
        dt = timestamp - self._depletion_time

        # Calculate recovery ratio
        recovered_depth = total_depth - self._depletion_total_depth
        expected_recovery = self._pre_depletion_total_depth - self._depletion_total_depth
        self.recovery_ratio = max(0.0, recovered_depth / max(expected_recovery, 1e-4))

        # Estimate half-lives
        self.bid_halflife = self._estimate_halflife(bid_depth, self._min_event_bid, self._pre_depletion_bid, dt)
        self.ask_halflife = self._estimate_halflife(ask_depth, self._min_event_ask, self._pre_depletion_ask, dt)
        self.total_halflife = self._estimate_halflife(total_depth, self._depletion_total_depth, self._pre_depletion_total_depth, dt)

        # Replenishment asymmetry: A_rep in [-1.0, 1.0]
        # Faster half-life = higher replenishment rate (lambda = ln(2)/t_1/2)
        lambda_bid = math.log(2.0) / max(self.bid_halflife, 1e-4)
        lambda_ask = math.log(2.0) / max(self.ask_halflife, 1e-4)
        max_lambda = max(lambda_bid, lambda_ask, 1e-4)
        self.replenishment_asymmetry = (lambda_bid - lambda_ask) / max_lambda

        # Evaluate Circuit Breakers
        halflife_breach = (self.total_halflife > self.max_halflife_sec and dt >= self.eval_window_sec)
        recovery_stall = (self.recovery_ratio < self.min_recovery_ratio and dt >= self.eval_window_sec)
        asymmetry_breach = (abs(self.replenishment_asymmetry) > self.asymmetry_threshold and dt >= 1.0)

        # Event ends if recovery reached >= 90%
        if self.recovery_ratio >= 0.90:
            self._in_depletion_event = False
            self.baseline_bid_depth = bid_depth
            self.baseline_ask_depth = ask_depth
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = ""
            return False

        if halflife_breach or recovery_stall or asymmetry_breach:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution
            if asymmetry_breach and not halflife_breach:
                if self.replenishment_asymmetry < -self.asymmetry_threshold:
                    self.blocked_side = "BUY" # Bid replenishment crippled -> buy into falling book is toxic
                    side_note = "BID_REPLENISHMENT_PARALYZED"
                else:
                    self.blocked_side = "SELL" # Ask replenishment crippled -> sell into rising book is toxic
                    side_note = "ASK_REPLENISHMENT_PARALYZED"
            else:
                self.blocked_side = "ALL"
                side_note = "BILATERAL_REPLENISHMENT_FAILURE"

            trigger = (
                "REPLENISHMENT_HALFLIFE_EXPLOSION" if halflife_breach else
                ("INCOMPLETE_REPLENISHMENT_STALL" if recovery_stall else "ASYMMETRIC_REPLENISHMENT_PARALYSIS")
            )
            self._block_reason = (
                f"{trigger}: t_1/2={self.total_halflife:.2f}s (max={self.max_halflife_sec:.2f}s), "
                f"eta={self.recovery_ratio:.2f} (min={self.min_recovery_ratio:.2f}), "
                f"A_rep={self.replenishment_asymmetry:.2f} [{side_note}], blocked: {self.blocked_side}"
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
            "guard": "Wave471LiquidityReplenishmentHalflifeDecayGuard",
            "in_depletion_event": self._in_depletion_event,
            "total_halflife": round(self.total_halflife, 4),
            "bid_halflife": round(self.bid_halflife, 4),
            "ask_halflife": round(self.ask_halflife, 4),
            "recovery_ratio": round(self.recovery_ratio, 4),
            "replenishment_asymmetry": round(self.replenishment_asymmetry, 4),
            "max_halflife_sec": self.max_halflife_sec,
            "min_recovery_ratio": self.min_recovery_ratio,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.baseline_bid_depth = 0.0
        self.baseline_ask_depth = 0.0
        self.bid_halflife = 0.50
        self.ask_halflife = 0.50
        self.total_halflife = 0.50
        self.replenishment_asymmetry = 0.0
        self.recovery_ratio = 1.0
        self._in_depletion_event = False
        self._depletion_time = -1.0
        self._depletion_total_depth = 0.0
        self._pre_depletion_total_depth = 0.0
        self._pre_depletion_bid = 0.0
        self._pre_depletion_ask = 0.0
        self._min_event_bid = 0.0
        self._min_event_ask = 0.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
