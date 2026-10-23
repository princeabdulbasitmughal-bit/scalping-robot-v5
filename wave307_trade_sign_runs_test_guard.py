"""
wave307_trade_sign_runs_test_guard.py
-------------------------------------
Guard: High-Frequency Trade Sign Wald-Wolfowitz Runs Test & Random Walk Independence Guard

Monitors non-parametric Wald-Wolfowitz runs of buyer vs seller initiated trades,
detecting predatory trending order sweeps (runs deficit) and artificial ping-pong oscillations (runs excess)
(Wald & Wolfowitz 1940; Mood 1940; Campbell, Lo & MacKinlay 1997; Cont 2001):
    Trade Signs:                  s_i in {+1, -1}  (+1 = Buy, -1 = Sell)
    Total Buys & Sells:           N_+ = sum(s_i == +1), N_- = sum(s_i == -1), N = N_+ + N_-
    Observed Runs:                R = count of contiguous unbroken blocks of identical signs
    Expected Runs under H0:       mu_R = (2 * N_+ * N_-) / N + 1
    Runs Variance under H0:       sigma_R^2 = (2 * N_+ * N_- * (2 * N_+ * N_- - N)) / (N^2 * (N - 1))
    Runs Z-Score:                 Z_R = (R - mu_R) / max(sqrt(sigma_R^2), 1e-4)

Under independent random walk order flow:
    - Order flow signs arrive as independent Bernoulli trials:
      Z_R in [-2.0, +2.0].

Under predatory sweeping or algorithmic market manipulation:
    1) Runs Deficit (Directional Sweeping / Cascading Herd):
       Predatory algorithms sweep liquidity sequentially in unbroken runs:
       Z_R <= MAX_RUNS_DEFICIT_Z (default: -2.80) over rolling N >= MIN_SAMPLES (default: 20 trades).
    2) Runs Excess (Artificial Alternation / Quote Pinging):
       Predatory quote flashing or toxic ping-pong trading creates excessive alternations:
       Z_R >= MAX_RUNS_EXCESS_Z (default: +3.20) over rolling N >= MIN_SAMPLES (default: 20 trades).
    3) Acute Monotonic Directional Run:
       An unbroken streak of >= ACUTE_MONOTONIC_RUN (default: 9 trades) on one side.

Entering positions during severe runs deficits guarantees stepping directly into active institutional sweeps,
while runs excesses expose executions to toxic latency pinging.

When runs deficit, runs excess, or an acute monotonic run is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade sign via record_trade_sign(sign, ts=None) or record_trade(price, prev_price=None, ts=None)
  or direct metrics via record_runs_metrics(z_score, observed_runs=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 30 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid signs, non-numeric, boolean (except explicit buy_flag), NaN, or Inf are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_sign(sign, ts=None)                                                             -> None
  record_trade(price, prev_price=None, ts=None)                                                -> None
  record_runs_metrics(z_score, observed_runs=None, sample_count=None, ts=None)                 -> None
  update(sign, ts=None)                                                                        -> None   (alias)
  get_runs_metrics()                                                                           -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave307TradeSignRunsTestGuard:
    """
    Guards against trade sign runs deficits (predatory sweeping) and runs excesses (ping-pong manipulation).
    """

    MAX_RUNS_DEFICIT_Z: float = -2.80
    MAX_RUNS_EXCESS_Z: float = 3.20
    MIN_SAMPLES: int = 20
    MIN_SIDE_SAMPLES: int = 4
    ACUTE_MONOTONIC_RUN: int = 9
    WINDOW_SIZE: int = 30
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_runs_deficit_z: float = MAX_RUNS_DEFICIT_Z,
        max_runs_excess_z: float = MAX_RUNS_EXCESS_Z,
        min_samples: int = MIN_SAMPLES,
        min_side_samples: int = MIN_SIDE_SAMPLES,
        acute_monotonic_run: int = ACUTE_MONOTONIC_RUN,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_runs_deficit_z = float(max_runs_deficit_z)
        self.max_runs_excess_z = float(max_runs_excess_z)
        self.min_samples = int(min_samples)
        self.min_side_samples = int(min_side_samples)
        self.acute_monotonic_run = int(acute_monotonic_run)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._signs = collections.deque(maxlen=self.window_size)

        self._last_price: Optional[float] = None
        self._last_sign: int = 0
        self._current_run: int = 0

        self._latest_z: float = 0.0
        self._latest_runs: int = 1
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_runs_z(self) -> tuple[float, int, int, int]:
        n = len(self._signs)
        if n < 4:
            return 0.0, 1, 0, 0

        signs = list(self._signs)
        n_pos = sum(1 for s in signs if s > 0)
        n_neg = sum(1 for s in signs if s < 0)

        # Count runs
        runs = 1
        for i in range(1, n):
            if signs[i] != signs[i - 1]:
                runs += 1

        if n_pos < self.min_side_samples or n_neg < self.min_side_samples:
            return 0.0, runs, n_pos, n_neg

        mu_r = (2.0 * n_pos * n_neg) / n + 1.0
        num = 2.0 * n_pos * n_neg * (2.0 * n_pos * n_neg - n)
        denom = (n ** 2) * (n - 1)
        var_r = num / denom if denom > 0 else 0.0

        if var_r <= 1e-8:
            return 0.0, runs, n_pos, n_neg

        sigma_r = math.sqrt(var_r)
        z_score = (runs - mu_r) / sigma_r
        return z_score, runs, n_pos, n_neg

    def _check_and_trigger_block(
        self,
        z_score: float,
        runs: int,
        current_run: int,
        count: int,
        n_pos: int,
        n_neg: int,
    ) -> bool:
        # 1. Acute monotonic run
        if current_run >= self.acute_monotonic_run:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_MONOTONIC_RUN: streak={current_run} >= {self.acute_monotonic_run} consecutive trades"
            )
            return True

        if count >= self.min_samples and n_pos >= self.min_side_samples and n_neg >= self.min_side_samples:
            # 2. Runs deficit (severe directional sweeping)
            if z_score <= self.max_runs_deficit_z:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"RUNS_DEFICIT_SWEEP: Z={z_score:.3f} <= {self.max_runs_deficit_z:.3f} "
                    f"(runs={runs}, N={count}, buys={n_pos}, sells={n_neg})"
                )
                return True

            # 3. Runs excess (artificial ping-pong oscillation)
            if z_score >= self.max_runs_excess_z:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"RUNS_EXCESS_PINGPONG: Z={z_score:.3f} >= {self.max_runs_excess_z:.3f} "
                    f"(runs={runs}, N={count}, buys={n_pos}, sells={n_neg})"
                )
                return True

        return False

    def record_trade_sign(self, sign: Any, ts: Optional[float] = None) -> None:
        """
        Record individual trade sign (+1 for buyer-initiated, -1 for seller-initiated).
        """
        with self._lock:
            val_sign = 0
            if isinstance(sign, bool):
                val_sign = 1 if sign else -1
            elif isinstance(sign, (int, float)):
                if not self._is_valid_num(sign):
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_SIGN_INPUT"
                    return
                if sign > 0:
                    val_sign = 1
                elif sign < 0:
                    val_sign = -1
                else:
                    # Sign 0 is ambiguous / mid-market print, disregard or reject
                    return
            elif isinstance(sign, str):
                s_str = sign.strip().lower()
                if s_str in ("buy", "b", "+1", "1", "plus"):
                    val_sign = 1
                elif s_str in ("sell", "s", "-1", "-1.0", "minus"):
                    val_sign = -1
                else:
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_SIGN_INPUT"
                    return
            else:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SIGN_INPUT"
                return

            self._signs.append(val_sign)
            self._sample_count += 1

            if val_sign == self._last_sign:
                self._current_run += 1
            else:
                self._current_run = 1
            self._last_sign = val_sign

            z, runs, n_pos, n_neg = self._calculate_runs_z()
            self._latest_z = z
            self._latest_runs = runs

            self._check_and_trigger_block(
                z,
                runs,
                self._current_run,
                len(self._signs),
                n_pos,
                n_neg,
            )

    def record_trade(self, price: float, prev_price: Optional[float] = None, ts: Optional[float] = None) -> None:
        """
        Derive trade sign from tick rule (Lee-Ready): s_t = sign(p_t - p_{t-1}).
        """
        with self._lock:
            if not self._is_valid_num(price) or price <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_PRICE_INPUT"
                return

            p = float(price)
            p_prev = float(prev_price) if (self._is_valid_num(prev_price) and prev_price > 0.0) else self._last_price
            self._last_price = p

            if p_prev is not None:
                diff = p - p_prev
                if diff > 1e-7:
                    self.record_trade_sign(1, ts=ts)
                elif diff < -1e-7:
                    self.record_trade_sign(-1, ts=ts)
                elif self._last_sign != 0:
                    # Zero tick rule: carry over last sign
                    self.record_trade_sign(self._last_sign, ts=ts)

    def record_runs_metrics(
        self,
        z_score: float,
        observed_runs: Optional[int] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed runs test Z-score.
        """
        with self._lock:
            if not self._is_valid_num(z_score):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_RUNS_METRIC"
                return

            z = float(z_score)
            r = int(observed_runs) if (self._is_valid_num(observed_runs) and observed_runs > 0) else 10
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_z = z
            self._latest_runs = r
            self._sample_count = cnt

            self._check_and_trigger_block(
                z,
                r,
                self.acute_monotonic_run if z <= -5.0 else 1,
                cnt,
                self.min_side_samples + 2,
                self.min_side_samples + 2,
            )

    def update(self, sign: Any, ts: Optional[float] = None) -> None:
        """Alias for record_trade_sign."""
        self.record_trade_sign(sign, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_runs_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "runs_z_score": float(self._latest_z),
                "observed_runs": int(self._latest_runs),
                "current_run": int(self._current_run),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_runs_metrics()

    def reset(self) -> None:
        with self._lock:
            self._signs.clear()
            self._last_price = None
            self._last_sign = 0
            self._current_run = 0
            self._latest_z = 0.0
            self._latest_runs = 1
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
