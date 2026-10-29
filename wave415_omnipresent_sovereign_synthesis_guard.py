"""
Wave 415 -- Omnipresent Sovereign Synthesis & Invariant Governor Guard
======================================================================
The apex quantitative guardian synthesizing the complete High-Frequency Microstructure
Canopy (Waves 401 to 414). Aggregates 7 independent orthogonal risk invariant vectors:
  1. VPIN Flow Toxicity (Wave 407)
  2. Markov Turbulent Regime Probability (Wave 410)
  3. Jump Diffusion Bipower Ratio (Wave 408)
  4. Microprice Queue Asymmetry Skew (Wave 409)
  5. Orderbook Depth Slope Decay (Wave 412)
  6. High-Frequency Return Autocorrelation (Wave 411)
  7. Hasbrouck Microstructure Noise Ratio (Wave 414)

Computes normalized composite institutional fragility metric Omega_{comp} in [0, 1].
Enforces multi-canopy convergence circuit breaker to safeguard institutional capital.

Methodology
-----------
* Evaluates weighted composite score:
    Omega_{comp} = sum_{i=1}^7 w_i * s_i
* Detects multi-canopy convergence when count(s_i >= 0.70) >= `convergence_count`.
* If Omega_{comp} >= `critical_threshold`, blocks with SOVEREIGN_COMPOSITE_FRAGILITY_SPIKE.
* If multi-canopy convergence fires, blocks with MULTI_CANOPY_CONVERGENCE_LOCK.

Blocking reasons
----------------
SOVEREIGN_COMPOSITE_FRAGILITY_SPIKE -- composite institutional fragility index exceeded limit
MULTI_CANOPY_CONVERGENCE_LOCK       -- simultaneous multi-dimensional risk invariants tripped
INPUT_VALIDATION_ERROR              -- inputs outside [0, 1], non-numeric, or non-monotonic ts

Public API (standardised)
-------------------------
update(...)                    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
composite_score                -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave415OmnipresentSovereignSynthesisGuard"]

_REASON_COMPOSITE = "SOVEREIGN_COMPOSITE_FRAGILITY_SPIKE"
_REASON_CONVERGENCE = "MULTI_CANOPY_CONVERGENCE_LOCK"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave415OmnipresentSovereignSynthesisGuard:
    """Omnipresent Sovereign Synthesis and Invariant Governor Guard."""

    def __init__(
        self,
        critical_composite_threshold: float = 0.65,
        convergence_count_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            not (0.20 <= critical_composite_threshold <= 0.95)
            or not (2 <= convergence_count_threshold <= 7)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave415OmnipresentSovereignSynthesisGuard")

        self._critical_threshold = float(critical_composite_threshold)
        self._convergence_threshold = int(convergence_count_threshold)
        self._cooldown = float(cooldown_seconds)

        self._weights = [0.20, 0.20, 0.15, 0.15, 0.10, 0.10, 0.10]
        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._composite_score: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def composite_score(self) -> float:
        with self._lock:
            return self._composite_score

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._composite_score = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        vpin_risk: float,
        markov_turbulent_prob: float,
        jump_ratio: float,
        microprice_skew: float,
        depth_slope_decay: float,
        autocorr_shock: float,
        noise_ratio: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            signals = [
                vpin_risk,
                markov_turbulent_prob,
                jump_ratio,
                microprice_skew,
                depth_slope_decay,
                autocorr_shock,
                noise_ratio,
            ]
            if (
                any(not isinstance(s, (int, float)) or not (0.0 <= s <= 1.0) for s in signals)
                or not isinstance(timestamp, (int, float))
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)

            # Compute weighted composite score
            comp = sum(w * float(s) for w, s in zip(self._weights, signals))
            self._composite_score = comp

            # Check multi-canopy simultaneous convergence (critical count >= 3)
            high_count = sum(1 for s in signals if s >= 0.70)

            if high_count >= self._convergence_threshold:
                self._block(_REASON_CONVERGENCE, ts)
            elif comp >= self._critical_threshold:
                self._block(_REASON_COMPOSITE, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
