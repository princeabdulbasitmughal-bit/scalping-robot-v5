"""
Wave 410 -- Markov-Switching Volatility Regime Transition Guard
===============================================================
Implements a 2-state Hamilton (1989) Markov-switching volatility filter to detect
instantaneous transitions between normal orderly microstructure (State 0: Low Volatility)
and turbulent crisis regimes (State 1: High Volatility). Computes recursive Bayesian
filtered probabilities of regime occupancy. When posterior turbulent state probability
or transition shock exceeds safety thresholds, locks out aggressive scalping entries.

Methodology
-----------
* Observes midprice returns r_t = ln(P_t / P_{t-1}).
* Transition matrix P = [[p00, 1 - p00], [1 - p11, p11]].
* Prior state predictions:
    pi_{t|t-1}(0) = pi_{t-1}(0) * p00 + pi_{t-1}(1) * (1 - p11)
    pi_{t|t-1}(1) = pi_{t-1}(0) * (1 - p00) + pi_{t-1}(1) * p11
* Likelihoods:
    f_k(r_t) = (1 / (sqrt(2*pi) * sigma_k)) * exp(-0.5 * (r_t / sigma_k)^2)
* Filtered posterior probability:
    pi_t(1) = (pi_{t|t-1}(1) * f_1) / (pi_{t|t-1}(0) * f_0 + pi_{t|t-1}(1) * f_1 + 1e-15)
* If pi_t(1) >= `turbulent_prob_threshold`, blocks with MARKOV_TURBULENT_REGIME_DETECTED.
* If |pi_t(1) - pi_{t-1}(1)| >= `max_regime_shock`, blocks with REGIME_TRANSITION_INSTABILITY.

Blocking reasons
----------------
MARKOV_TURBULENT_REGIME_DETECTED -- filtered probability of high-volatility regime exceeded limit
REGIME_TRANSITION_INSTABILITY    -- acute probability jump into turbulent regime
INPUT_VALIDATION_ERROR           -- invalid price, non-positive sigma, or non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
turbulent_prob                 -> float
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

__all__ = ["Wave410MarkovSwitchingRegimeTransitionGuard"]

_REASON_TURBULENT = "MARKOV_TURBULENT_REGIME_DETECTED"
_REASON_SHOCK = "REGIME_TRANSITION_INSTABILITY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"
_SQRT_2PI = math.sqrt(2.0 * math.pi)


class Wave410MarkovSwitchingRegimeTransitionGuard:
    """Hamilton 2-State Markov-Switching Volatility Regime Guard."""

    def __init__(
        self,
        sigma_low: float = 0.0005,
        sigma_high: float = 0.0030,
        p00: float = 0.95,
        p11: float = 0.90,
        turbulent_prob_threshold: float = 0.75,
        max_regime_shock: float = 0.50,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            sigma_low <= 0.0
            or sigma_high <= sigma_low
            or not (0.50 <= p00 < 1.0)
            or not (0.50 <= p11 < 1.0)
            or not (0.20 <= turbulent_prob_threshold <= 0.98)
            or not (0.10 <= max_regime_shock <= 0.95)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave410MarkovSwitchingRegimeTransitionGuard")

        self._sigma_low = float(sigma_low)
        self._sigma_high = float(sigma_high)
        self._p00 = float(p00)
        self._p11 = float(p11)
        self._turbulent_threshold = float(turbulent_prob_threshold)
        self._max_shock = float(max_regime_shock)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_mid: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._pi_turbulent: float = 0.05  # Initial state prior: 95% calm, 5% turbulent
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def turbulent_prob(self) -> float:
        with self._lock:
            return self._pi_turbulent

    def reset(self) -> None:
        with self._lock:
            self._last_mid = None
            self._last_ts = None
            self._pi_turbulent = 0.05
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def _gaussian_density(self, x: float, sigma: float) -> float:
        denom = _SQRT_2PI * sigma
        exp_val = math.exp(-0.5 * (x / sigma) ** 2)
        return max(exp_val / denom, 1e-25)

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(bid, (int, float))
                or not isinstance(ask, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid <= 0.0
                or ask <= 0.0
                or bid >= ask
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            mid = (float(bid) + float(ask)) / 2.0
            ts = float(timestamp)

            if self._last_mid is not None and self._last_mid > 0.0:
                ret = math.log(mid / self._last_mid)

                # Prior state predictions
                prev_pi1 = self._pi_turbulent
                prev_pi0 = 1.0 - prev_pi1

                pred_pi0 = prev_pi0 * self._p00 + prev_pi1 * (1.0 - self._p11)
                pred_pi1 = prev_pi0 * (1.0 - self._p00) + prev_pi1 * self._p11

                # Likelihoods
                f0 = self._gaussian_density(ret, self._sigma_low)
                f1 = self._gaussian_density(ret, self._sigma_high)

                # Posterior update
                num = pred_pi1 * f1
                denom = pred_pi0 * f0 + num + 1e-25
                post_pi1 = max(0.0, min(1.0, num / denom))

                shock = post_pi1 - prev_pi1
                self._pi_turbulent = post_pi1

                if post_pi1 >= self._turbulent_threshold:
                    self._block(_REASON_TURBULENT, ts)

                if shock >= self._max_shock:
                    self._block(_REASON_SHOCK, ts)

            self._last_mid = mid
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
