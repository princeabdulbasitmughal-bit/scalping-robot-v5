"""
wave313_trade_size_round_lot_bias_guard.py
------------------------------------------
Guard: High-Frequency Trade Size Round-Lot Clustering & Algorithmic Modulo Bias Guard

Monitors trade size modulo clustering and normalized decimal fraction Shannon entropy H_{mod},
guarding against deterministic algorithmic child slicing, modulo pinning, and adversarial size randomization
(Christie & Schultz 1994; Harris 1991; Aitken et al. 1996; Ikenberry & Weston 2008):
    Trade Sizes:                  V_1, V_2, ..., V_N in lots
    Decimal Modulo Fraction:      f_i = V_i mod 1.0  in [0.0, 1.0)
    Fractional Bins:              b = min(int(f_i * 10), 9) across B = 10 decimal buckets
    Modulo Shannon Entropy:       H_{mod} = -sum_{b=0}^{B-1} p_b * ln(p_b) / ln(B)  in [0.0, 1.0]
    Round-Lot Ratio:              P_{round} = (1 / N) * sum(1_{|V_i - round(V_i * 10) / 10| < 1e-4})

Under natural mixed market participation:
    - Order flow displays moderate decimal dispersion with healthy round-lot preference:
      H_{mod} in [0.40, 0.92], P_{round} in [0.20, 0.85].

Under predatory execution algorithms (TWAP/VWAP deterministic slicing or adversarial noise):
    - Trade sizes deviate sharply into artificial modulo regimes:
        1) Algorithmic Modulo Pinning:
           Normalized modulo entropy H_{mod} <= MIN_MODULO_ENTROPY (default: 0.15)
           over rolling N >= MIN_SAMPLES (default: 15 trades). Child orders are pinned to a single slice modulo.
        2) Adversarial Obfuscation Noise:
           Round-lot fraction P_{round} <= MIN_ROUND_FRACTION (default: 0.05) with hyper-uniform H_{mod} >= 0.98.
        3) Acute Fractional Slicing Streak:
           An unbroken streak of >= ACUTE_FRACTIONAL_STREAK (default: 8) consecutive trades with identical fraction.

Trading into active algorithmic slicing traps exposes orders to predatory queue exhaustion and adverse fills.

When algorithmic modulo pinning, adversarial noise, or an acute fractional streak is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade size via record_trade_size(trade_size, ts=None) or
  direct metrics via record_bias_metrics(modulo_entropy, round_fraction=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive trade sizes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_size(trade_size, ts=None)                                                       -> None
  record_bias_metrics(modulo_entropy, round_fraction=None, sample_count=None, ts=None)          -> None
  update(trade_size, ts=None)                                                                  -> None   (alias)
  get_bias_metrics()                                                                           -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave313TradeSizeRoundLotBiasGuard:
    """
    Guards against trade size algorithmic modulo pinning, deterministic child slicing, and adversarial noise.
    """

    MIN_MODULO_ENTROPY: float = 0.15
    MIN_ROUND_FRACTION: float = 0.05
    MIN_SAMPLES: int = 15
    ACUTE_FRACTIONAL_STREAK: int = 8
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_modulo_entropy: float = MIN_MODULO_ENTROPY,
        min_round_fraction: float = MIN_ROUND_FRACTION,
        min_samples: int = MIN_SAMPLES,
        acute_fractional_streak: int = ACUTE_FRACTIONAL_STREAK,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_modulo_entropy = float(min_modulo_entropy)
        self.min_round_fraction = float(min_round_fraction)
        self.min_samples = int(min_samples)
        self.acute_fractional_streak = int(acute_fractional_streak)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._sizes = collections.deque(maxlen=self.window_size)

        self._last_fraction: Optional[float] = None
        self._fractional_streak: int = 0

        self._latest_entropy: float = 0.70
        self._latest_round_fraction: float = 0.50
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_modulo_metrics(self) -> tuple[float, float]:
        n = len(self._sizes)
        if n < 3:
            return 0.70, 0.50

        bins = [0] * 10
        round_count = 0

        for sz in self._sizes:
            frac = sz % 1.0
            b = min(int(frac * 10.0), 9)
            bins[b] += 1

            # Check if round to 0.10 lot
            dist_round = abs(sz - round(sz * 10.0) / 10.0)
            if dist_round < 1e-4:
                round_count += 1

        round_frac = round_count / n

        # Shannon entropy across 10 bins
        entropy = 0.0
        log_10 = math.log(10.0)
        for count in bins:
            if count > 0:
                p = count / n
                entropy -= p * math.log(p)
        norm_entropy = entropy / log_10 if log_10 > 0 else 0.0
        norm_entropy = max(0.0, min(1.0, norm_entropy))

        return norm_entropy, round_frac

    def _check_and_trigger_block(
        self,
        entropy: float,
        round_frac: float,
        streak: int,
        count: int,
    ) -> bool:
        # 1. Acute fractional slicing streak
        if streak >= self.acute_fractional_streak:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_FRACTIONAL_SLICING_STREAK: streak={streak} >= {self.acute_fractional_streak} "
                f"consecutive trades with identical fraction"
            )
            return True

        if count >= self.min_samples:
            # 2. Algorithmic modulo pinning (degenerate low entropy)
            if entropy <= self.min_modulo_entropy:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"ALGORITHMIC_MODULO_PINNING: H_mod={entropy:.3f} <= {self.min_modulo_entropy:.3f} "
                    f"over N={count} trades"
                )
                return True

            # 3. Adversarial obfuscation noise
            if round_frac <= self.min_round_fraction and entropy >= 0.98:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"ADVERSARIAL_OBFUSCATION_NOISE: round_fraction={round_frac:.3f} <= {self.min_round_fraction:.3f} "
                    f"with H_mod={entropy:.3f} >= 0.98"
                )
                return True

        return False

    def record_trade_size(self, trade_size: float, ts: Optional[float] = None) -> None:
        """
        Record individual trade size in lots and evaluate modulo fraction distribution.
        """
        with self._lock:
            if not self._is_valid_num(trade_size) or trade_size <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_TRADE_SIZE_INPUT"
                return

            size = float(trade_size)
            self._sizes.append(size)
            self._sample_count += 1

            frac = size % 1.0
            if self._last_fraction is not None and abs(frac - self._last_fraction) < 1e-4:
                self._fractional_streak += 1
            else:
                self._fractional_streak = 1
            self._last_fraction = frac

            entropy, round_frac = self._calculate_modulo_metrics()
            self._latest_entropy = entropy
            self._latest_round_fraction = round_frac

            self._check_and_trigger_block(
                entropy,
                round_frac,
                self._fractional_streak,
                len(self._sizes),
            )

    def record_bias_metrics(
        self,
        modulo_entropy: float,
        round_fraction: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed modulo entropy metrics.
        """
        with self._lock:
            if not self._is_valid_num(modulo_entropy) or modulo_entropy < 0.0 or modulo_entropy > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_ENTROPY_METRIC"
                return

            ent = float(modulo_entropy)
            rf = float(round_fraction) if (self._is_valid_num(round_fraction) and round_fraction >= 0.0) else 0.50
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_entropy = ent
            self._latest_round_fraction = rf
            self._sample_count = cnt

            self._check_and_trigger_block(
                ent,
                rf,
                self.acute_fractional_streak if ent <= 0.02 else 0,
                cnt,
            )

    def update(self, trade_size: float, ts: Optional[float] = None) -> None:
        """Alias for record_trade_size."""
        self.record_trade_size(trade_size, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_bias_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "modulo_entropy": float(self._latest_entropy),
                "round_lot_fraction": float(self._latest_round_fraction),
                "fractional_streak": int(self._fractional_streak),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_bias_metrics()

    def reset(self) -> None:
        with self._lock:
            self._sizes.clear()
            self._last_fraction = None
            self._fractional_streak = 0
            self._latest_entropy = 0.70
            self._latest_round_fraction = 0.50
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
