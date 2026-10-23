"""
wave316_lob_spread_elasticity_guard.py
--------------------------------------
Guard: LOB Inside Spread Depth-Elasticity & Brittle Liquidity Guard [Wave 316 - 3,000 Tests Milestone]

Monitors limit order book inside spread elasticity relative to depth depletion epsilon_S = - (% Delta Spread) / (% Delta Depth),
guarding against brittle order books, liquidity cliff edges, and flash spread blowouts
(Glosten & Milgrom 1985; Kyle 1985; Black 1986; Foucault, Kadan & Kandel 2005; Rosu 2009):
    Spread in bps:                S_t
    Inside Cumulative Depth:      Q_t = (q_{bid, 1} + q_{ask, 1}) in lots
    Relative Spread Change:       % Delta S = (S_t - S_{t-1}) / max(S_{t-1}, 0.50)
    Relative Depth Depletion:     % Delta Q = (Q_t - Q_{t-1}) / max(Q_{t-1}, 0.50)
    Spread Depth-Elasticity:      epsilon_S = - (% Delta S) / min(% Delta Q, -1e-4)   (when Delta Q < 0)
    Rolling Mean Elasticity:      \\bar{epsilon}_S = (1 / N) * sum_{i=1}^N epsilon_{S, i}

Under healthy, resilient quoting:
    - Depth withdrawals or sweeps are absorbed with low elasticity:
      \\bar{epsilon}_S <= 1.50.

Under fragile, brittle order books with zero replenishment:
    - Minor depth drops trigger disproportionate, catastrophic spread widening:
        1) Brittle Spread Elasticity Surge:
           Rolling mean elasticity \\bar{epsilon}_S >= MAX_SPREAD_ELASTICITY (default: 3.20)
           with elevated spread \\bar{S} >= MIN_ELEVATED_SPREAD_BPS (default: 2.20 bps)
           over rolling N >= MIN_SAMPLES (default: 10 depletion events).
        2) Acute Brittle Spread Blowout:
           Instantaneous elasticity epsilon_S >= ACUTE_ELASTICITY (default: 4.50)
           with acute spread widening Delta S >= ACUTE_SPREAD_JUMP_BPS (default: 3.00 bps)
           triggered by small volume sweep <= ACUTE_MAX_SWEEP_LOTS (default: 1.50 lots).

Trading against a brittle, hyper-elastic book guarantees paying massive adverse fill penalties,
as any minor execution instantly tears through empty order levels.

When brittle spread elasticity surge or an acute spread blowout is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests book snapshots via record_book_state(spread_bps, inside_depth_lots, ts=None) or
  direct metrics via record_elasticity_metrics(spread_elasticity, mean_spread_bps=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 depletion events.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive spreads or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_book_state(spread_bps, inside_depth_lots, ts=None)                                    -> None
  record_elasticity_metrics(spread_elasticity, mean_spread_bps=None, sample_count=None, ts=None) -> None
  update(spread_bps, inside_depth_lots, ts=None)                                               -> None   (alias)
  get_elasticity_metrics()                                                                     -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave316LobSpreadElasticityGuard:
    """
    Guards against LOB spread depth-elasticity collapse, brittle book profiles, and flash spread blowouts.
    """

    MAX_SPREAD_ELASTICITY: float = 3.20
    MIN_ELEVATED_SPREAD_BPS: float = 2.20
    MIN_SAMPLES: int = 10
    ACUTE_ELASTICITY: float = 4.50
    ACUTE_SPREAD_JUMP_BPS: float = 3.00
    ACUTE_MAX_SWEEP_LOTS: float = 1.50
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_spread_elasticity: float = MAX_SPREAD_ELASTICITY,
        min_elevated_spread_bps: float = MIN_ELEVATED_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_elasticity: float = ACUTE_ELASTICITY,
        acute_spread_jump_bps: float = ACUTE_SPREAD_JUMP_BPS,
        acute_max_sweep_lots: float = ACUTE_MAX_SWEEP_LOTS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_spread_elasticity = float(max_spread_elasticity)
        self.min_elevated_spread_bps = float(min_elevated_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_elasticity = float(acute_elasticity)
        self.acute_spread_jump_bps = float(acute_spread_jump_bps)
        self.acute_max_sweep_lots = float(acute_max_sweep_lots)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._elasticities = collections.deque(maxlen=self.window_size)
        self._spreads = collections.deque(maxlen=self.window_size)

        self._last_spread: Optional[float] = None
        self._last_depth: Optional[float] = None

        self._latest_elasticity: float = 0.50
        self._latest_mean_elasticity: float = 0.50
        self._latest_mean_spread: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        elasticity: float,
        mean_elasticity: float,
        mean_spread: float,
        delta_spread: float,
        delta_depth: float,
        count: int,
    ) -> bool:
        # 1. Acute brittle blowout shock
        if elasticity >= self.acute_elasticity and delta_spread >= self.acute_spread_jump_bps and abs(delta_depth) <= self.acute_max_sweep_lots:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_BRITTLE_SPREAD_BLOWOUT: elasticity={elasticity:.2f} >= {self.acute_elasticity:.2f} "
                f"with spread_jump={delta_spread:.2f} >= {self.acute_spread_jump_bps:.2f} bps "
                f"for small sweep={abs(delta_depth):.2f} lots"
            )
            return True

        # 2. Brittle spread elasticity surge
        if count >= self.min_samples and mean_elasticity >= self.max_spread_elasticity and mean_spread >= self.min_elevated_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"BRITTLE_SPREAD_ELASTICITY_SURGE: mean_elasticity={mean_elasticity:.2f} >= {self.max_spread_elasticity:.2f} "
                f"with mean_spread={mean_spread:.2f} >= {self.min_elevated_spread_bps:.2f} bps over N={count}"
            )
            return True

        return False

    def record_book_state(self, spread_bps: float, inside_depth_lots: float, ts: Optional[float] = None) -> None:
        """
        Record instantaneous spread and depth, computing elasticity upon depth depletion.
        """
        with self._lock:
            if not self._is_valid_num(spread_bps) or not self._is_valid_num(inside_depth_lots) or spread_bps <= 0.0 or inside_depth_lots < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_BOOK_STATE_INPUT"
                return

            spr = float(spread_bps)
            dep = float(inside_depth_lots)

            delta_s = 0.0
            delta_q = 0.0
            elasticity = 0.50

            if self._last_spread is not None and self._last_depth is not None:
                delta_s = spr - self._last_spread
                delta_q = dep - self._last_depth

                if delta_q < -1e-4:  # Depth was depleted
                    pct_ds = delta_s / max(self._last_spread, 0.50)
                    pct_dq = delta_q / max(self._last_depth, 0.50)
                    elasticity = -pct_ds / min(pct_dq, -1e-4)
                    elasticity = max(0.0, min(20.0, elasticity))

                    self._elasticities.append(elasticity)
                    self._spreads.append(spr)
                    self._sample_count += 1

            self._last_spread = spr
            self._last_depth = dep

            mean_elas = statistics.fmean(self._elasticities) if self._elasticities else elasticity
            mean_spr = statistics.fmean(self._spreads) if self._spreads else spr

            self._latest_elasticity = elasticity
            self._latest_mean_elasticity = mean_elas
            self._latest_mean_spread = mean_spr

            self._check_and_trigger_block(
                elasticity,
                mean_elas,
                mean_spr,
                delta_s,
                delta_q,
                len(self._elasticities),
            )

    def record_elasticity_metrics(
        self,
        spread_elasticity: float,
        mean_spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed spread elasticity metrics.
        """
        with self._lock:
            if not self._is_valid_num(spread_elasticity) or spread_elasticity < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_ELASTICITY_METRIC"
                return

            elas = float(spread_elasticity)
            m_spr = float(mean_spread_bps) if (self._is_valid_num(mean_spread_bps) and mean_spread_bps >= 0.0) else (self.min_elevated_spread_bps + 0.5)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_elasticity = elas
            self._latest_mean_elasticity = elas
            self._latest_mean_spread = m_spr
            self._sample_count = cnt

            self._check_and_trigger_block(
                elas,
                elas,
                m_spr,
                self.acute_spread_jump_bps + 1.0 if elas >= 5.0 else 0.5,
                -1.0,
                cnt,
            )

    def update(self, spread_bps: float, inside_depth_lots: float, ts: Optional[float] = None) -> None:
        """Alias for record_book_state."""
        self.record_book_state(spread_bps, inside_depth_lots, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_elasticity_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "spread_elasticity": float(self._latest_elasticity),
                "mean_elasticity": float(self._latest_mean_elasticity),
                "mean_spread_bps": float(self._latest_mean_spread),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_elasticity_metrics()

    def reset(self) -> None:
        with self._lock:
            self._elasticities.clear()
            self._spreads.clear()
            self._last_spread = None
            self._last_depth = None
            self._latest_elasticity = 0.50
            self._latest_mean_elasticity = 0.50
            self._latest_mean_spread = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
