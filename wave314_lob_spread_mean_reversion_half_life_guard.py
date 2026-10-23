"""
wave314_lob_spread_mean_reversion_half_life_guard.py
---------------------------------------------------
Guard: LOB Inside Spread Mean-Reversion Half-Life & Hysteresis Guard

Monitors bid-ask spread autoregressive persistence phi and Ornstein-Uhlenbeck mean-reversion half-life t_{1/2},
guarding against spread hysteresis, permanent quote widening, and acute spread lockout traps
(Roll 1984; Hasbrouck 1999; Engle & Patton 2004; Foucault, Kadan & Kandel 2005):
    Spread at Tick t:             S_t in bps
    Rolling Mean Spread:          \\bar{S} = (1 / N) * sum_{i=1}^N S_i
    AR(1) Spread Persistence:     (S_t - \\bar{S}) = phi * (S_{t-1} - \\bar{S}) + epsilon_t
                                  phi = Cov(S_t, S_{t-1}) / Var(S_{t-1})
    Mean-Reversion Half-Life:     t_{1/2} = -ln(2) / ln(max(phi, 1e-4)) in ticks

Under healthy, competitive market making:
    - Transitory spread shocks revert swiftly to tight baseline:
      phi in [0.10, 0.65], t_{1/2} <= 1.6 ticks.

Under market maker withdrawal, structural risk repricing, or panic widening:
    - Spread widening shocks become persistent and fail to revert:
        1) Spread Hysteresis:
           Autoregressive persistence phi >= MAX_PERSISTENCE_PHI (default: 0.92, t_{1/2} >= 8.3 ticks)
           with elevated mean spread \\bar{S} >= MIN_ELEVATED_SPREAD_BPS (default: 2.50 bps)
           over rolling N >= MIN_SAMPLES (default: 12 ticks).
        2) Acute Spread Lockout:
           Unbroken streak of >= ACUTE_LOCKOUT_TICKS (default: 8) consecutive ticks
           with wide spread S_t >= ACUTE_LOCKOUT_SPREAD_BPS (default: 3.50 bps).

Trading during active spread hysteresis guarantees paying inflated transaction costs with zero
spread compression before exit, triggering adverse slippage and execution drag.

When spread hysteresis or an acute spread lockout is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests spread via record_spread(spread_bps, ts=None) or
  direct metrics via record_reversion_metrics(persistence_phi, mean_spread_bps=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 ticks.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive spreads are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_spread(spread_bps, ts=None)                                                           -> None
  record_reversion_metrics(persistence_phi, mean_spread_bps=None, sample_count=None, ts=None)   -> None
  update(spread_bps, ts=None)                                                                  -> None   (alias)
  get_reversion_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave314LobSpreadMeanReversionHalfLifeGuard:
    """
    Guards against LOB spread hysteresis, failed mean-reversion, and acute spread lockouts.
    """

    MAX_PERSISTENCE_PHI: float = 0.92
    MIN_ELEVATED_SPREAD_BPS: float = 2.50
    MIN_SAMPLES: int = 12
    ACUTE_LOCKOUT_SPREAD_BPS: float = 3.50
    ACUTE_LOCKOUT_TICKS: int = 8
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_persistence_phi: float = MAX_PERSISTENCE_PHI,
        min_elevated_spread_bps: float = MIN_ELEVATED_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_lockout_spread_bps: float = ACUTE_LOCKOUT_SPREAD_BPS,
        acute_lockout_ticks: int = ACUTE_LOCKOUT_TICKS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_persistence_phi = float(max_persistence_phi)
        self.min_elevated_spread_bps = float(min_elevated_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_lockout_spread_bps = float(acute_lockout_spread_bps)
        self.acute_lockout_ticks = int(acute_lockout_ticks)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._spreads = collections.deque(maxlen=self.window_size)

        self._lockout_streak: int = 0

        self._latest_phi: float = 0.30
        self._latest_half_life: float = 1.0
        self._latest_mean_spread: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _estimate_phi(self) -> tuple[float, float, float]:
        n = len(self._spreads)
        if n < 4:
            return 0.30, 1.0, 1.0

        spreads = list(self._spreads)
        mean_s = statistics.fmean(spreads)

        x = spreads[:-1]
        y = spreads[1:]
        m_x = statistics.fmean(x)
        m_y = statistics.fmean(y)

        var_x = sum((val - m_x) ** 2 for val in x)
        if var_x <= 1e-6:
            return 0.0, 1.0, mean_s

        cov_xy = sum((x[i] - m_x) * (y[i] - m_y) for i in range(len(x)))
        phi = cov_xy / var_x
        phi = max(-0.99, min(0.999, phi))

        # Half-life in ticks
        if phi > 0.01:
            half_life = -math.log(2.0) / math.log(phi)
        else:
            half_life = 0.1

        return phi, half_life, mean_s

    def _check_and_trigger_block(
        self,
        phi: float,
        half_life: float,
        mean_spread: float,
        lockout_streak: int,
        count: int,
    ) -> bool:
        # 1. Acute spread lockout
        if lockout_streak >= self.acute_lockout_ticks:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_SPREAD_LOCKOUT: streak={lockout_streak} >= {self.acute_lockout_ticks} ticks "
                f"with spread >= {self.acute_lockout_spread_bps:.2f} bps"
            )
            return True

        # 2. Spread hysteresis (failed mean reversion)
        if count >= self.min_samples and phi >= self.max_persistence_phi and mean_spread >= self.min_elevated_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"SPREAD_HYSTERESIS: phi={phi:.3f} >= {self.max_persistence_phi:.3f} (half_life={half_life:.1f}t) "
                f"with mean_spread={mean_spread:.2f} >= {self.min_elevated_spread_bps:.2f} bps over N={count}"
            )
            return True

        return False

    def record_spread(self, spread_bps: float, ts: Optional[float] = None) -> None:
        """
        Record instantaneous bid-ask spread in bps and evaluate mean-reversion persistence.
        """
        with self._lock:
            if not self._is_valid_num(spread_bps) or spread_bps <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SPREAD_INPUT"
                return

            spr = float(spread_bps)
            self._spreads.append(spr)
            self._sample_count += 1

            if spr >= self.acute_lockout_spread_bps:
                self._lockout_streak += 1
            else:
                self._lockout_streak = 0

            phi, hl, mean_s = self._estimate_phi()
            self._latest_phi = phi
            self._latest_half_life = hl
            self._latest_mean_spread = mean_s

            self._check_and_trigger_block(
                phi,
                hl,
                mean_s,
                self._lockout_streak,
                len(self._spreads),
            )

    def record_reversion_metrics(
        self,
        persistence_phi: float,
        mean_spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed AR(1) persistence metrics.
        """
        with self._lock:
            if not self._is_valid_num(persistence_phi) or persistence_phi < -1.0 or persistence_phi >= 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_PERSISTENCE_METRIC"
                return

            phi = float(persistence_phi)
            mean_s = float(mean_spread_bps) if (self._is_valid_num(mean_spread_bps) and mean_spread_bps >= 0.0) else (self.min_elevated_spread_bps + 0.5)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            hl = -math.log(2.0) / math.log(max(phi, 1e-4)) if phi > 0.01 else 0.1

            self._latest_phi = phi
            self._latest_half_life = hl
            self._latest_mean_spread = mean_s
            self._sample_count = cnt

            self._check_and_trigger_block(
                phi,
                hl,
                mean_s,
                self.acute_lockout_ticks if phi >= 0.98 else 0,
                cnt,
            )

    def update(self, spread_bps: float, ts: Optional[float] = None) -> None:
        """Alias for record_spread."""
        self.record_spread(spread_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_reversion_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "persistence_phi": float(self._latest_phi),
                "half_life_ticks": float(self._latest_half_life),
                "mean_spread_bps": float(self._latest_mean_spread),
                "lockout_streak": int(self._lockout_streak),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_reversion_metrics()

    def reset(self) -> None:
        with self._lock:
            self._spreads.clear()
            self._lockout_streak = 0
            self._latest_phi = 0.30
            self._latest_half_life = 1.0
            self._latest_mean_spread = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
