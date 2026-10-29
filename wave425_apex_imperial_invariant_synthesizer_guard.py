"""
Wave 425 -- Apex Imperial Invariant Synthesizer Guard
=====================================================
The supreme sovereign synthesizer presiding over the complete quantitative architecture
of Waves 401 to 425. Synthesizes 8 high-order institutional microstructure vectors:
  1. Queue Cancellation Ratio (Wave 416)
  2. Trade Flow Clustered Dispersion (Wave 417)
  3. Spread Asymmetry & Defense Shading (Wave 418)
  4. Order Flow Toxicity Duration (Wave 419)
  5. Trade Sign Run-Length Persistence (Wave 421)
  6. Replenishment Asymmetry (Wave 422)
  7. Realized Tri-Power Quarticity (Wave 423)
  8. Multifractal Hurst Spectrum Width (Wave 424)

Computes the normalized Imperial Fragility Index Psi in [0, 1]. Enforces an all-weather
multi-canopy shutdown across scalper engines during systemic liquidity fracture.

Methodology
-----------
* Evaluates weighted composite score:
    Psi = (1/8) * sum_{i=1}^8 s_i
* Detects global convergence when count(s_i >= 0.70) >= 4.
* If Psi >= `critical_threshold`, blocks with IMPERIAL_INVARIANT_FRAGILITY_SPIKE.
* If multi-vector convergence fires, blocks with SOVEREIGN_GLOBAL_LOCKOUT.

Blocking reasons
----------------
IMPERIAL_INVARIANT_FRAGILITY_SPIKE -- composite imperial fragility index breached limit
SOVEREIGN_GLOBAL_LOCKOUT           -- simultaneous multi-dimensional risk invariants tripped
INPUT_VALIDATION_ERROR             -- inputs outside [0, 1], non-numeric, or non-monotonic ts

Public API (standardised)
-------------------------
update(...)                    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
imperial_score                 -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave425ApexImperialInvariantSynthesizerGuard"]

_REASON_FRAGILITY = "IMPERIAL_INVARIANT_FRAGILITY_SPIKE"
_REASON_LOCKOUT = "SOVEREIGN_GLOBAL_LOCKOUT"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave425ApexImperialInvariantSynthesizerGuard:
    """Apex Imperial Invariant Synthesizer Guard."""

    def __init__(
        self,
        critical_imperial_threshold: float = 0.65,
        convergence_count_threshold: int = 4,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            not (0.20 <= critical_imperial_threshold <= 0.95)
            or not (2 <= convergence_count_threshold <= 8)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave425ApexImperialInvariantSynthesizerGuard")

        self._critical_threshold = float(critical_imperial_threshold)
        self._convergence_threshold = int(convergence_count_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._imperial_score: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def imperial_score(self) -> float:
        with self._lock:
            return self._imperial_score

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._imperial_score = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        cancel_ratio_risk: float,
        burst_dispersion_risk: float,
        spread_asymmetry_risk: float,
        toxicity_duration_risk: float,
        run_length_risk: float,
        replenish_asym_risk: float,
        quarticity_risk: float,
        multifractal_risk: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            signals = [
                cancel_ratio_risk,
                burst_dispersion_risk,
                spread_asymmetry_risk,
                toxicity_duration_risk,
                run_length_risk,
                replenish_asym_risk,
                quarticity_risk,
                multifractal_risk,
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
            psi = sum(float(s) for s in signals) / 8.0
            self._imperial_score = psi

            high_count = sum(1 for s in signals if s >= 0.70)

            if high_count >= self._convergence_threshold:
                self._block(_REASON_LOCKOUT, ts)
            elif psi >= self._critical_threshold:
                self._block(_REASON_FRAGILITY, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
