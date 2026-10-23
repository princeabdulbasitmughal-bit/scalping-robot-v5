"""
wave310_lob_queue_half_life_decay_guard.py
------------------------------------------
Guard: LOB Inside-Queue Resting Half-Life & Stale Liquidity Decay Guard [Wave 310 Milestone]

Monitors limit order book inside-queue resting half-life t_{1/2} and attrition hazard rates,
guarding against toxic quote flickering (phantom HFT spoofing) and stagnant stale liquidity mirages
(Biais, Hillion & Spatt 1995; Bouchaud, Mezard & Potters 2002; Cont, Stoikov & Talreja 2010; Maglaras, Yao & Zehavi 2015):
    Cancellation Rate:            theta (cancels/sec or lots cancelled/sec)
    Trade Execution Rate:         mu (trades/sec or lots executed/sec)
    Queue Hazard Rate:            h = theta + mu (sec^{-1})
    Queue Resting Half-Life:      t_{1/2} = ln(2) / max(h, 1e-4) in seconds
    Rolling Mean Half-Life:       \\bar{t}_{1/2} = (1 / N) * sum_{i=1}^N t_{1/2, i}

Under healthy liquid continuous quoting:
    - Order queue half-life is moderate and stable:
      \\bar{t}_{1/2} in [1.5, 12.0] seconds.

Under high-frequency predatory manipulation or abandoned quoting:
    - Order book exhibits extreme hazard distortions:
        1) Toxic Quote Flickering (Phantom Spoofing):
           Rolling mean half-life \\bar{t}_{1/2} <= MIN_HALF_LIFE_SEC (default: 0.15s)
           over rolling N >= MIN_SAMPLES (default: 8 cycles). Orders flash in and cancel in milliseconds.
        2) Stale Liquidity Mirage (Trapped Quoting):
           Rolling mean half-life \\bar{t}_{1/2} >= MAX_HALF_LIFE_SEC (default: 35.0s)
           with wide spread S >= MIN_STALE_SPREAD_BPS (default: 2.50 bps) over N >= MIN_SAMPLES.
        3) Acute Phantom Cancel Burst:
           Instantaneous cancellation rate theta >= ACUTE_CANCEL_RATE (default: 25.0 cancels/sec)
           with trade fill rate mu <= 0.50 trades/sec within dt <= 0.50s.

Trading against phantom quote flickering results in stepping onto vanishing bids/asks,
while trading into stale liquidity mirages exposes orders to severe toxic fills against stale prices.

When quote flickering, stale liquidity, or an acute phantom cancel burst is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests queue events via record_queue_hazard(cancel_rate, fill_rate, spread_bps=None, ts=None) or
  record_queue_lifespan(lifespan_sec, spread_bps=None, ts=None) or
  direct metrics via record_half_life_metrics(half_life_sec, spread_bps=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 20 cycles.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative rates/spreads are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_queue_hazard(cancel_rate, fill_rate, spread_bps=None, ts=None)                        -> None
  record_queue_lifespan(lifespan_sec, spread_bps=None, ts=None)                                -> None
  record_half_life_metrics(half_life_sec, spread_bps=None, sample_count=None, ts=None)          -> None
  update(cancel_rate, fill_rate, spread_bps=None, ts=None)                                     -> None   (alias)
  get_half_life_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave310LobQueueHalfLifeDecayGuard:
    """
    Guards against LOB quote flickering, phantom HFT cancellations, and stale liquidity traps.
    """

    MIN_HALF_LIFE_SEC: float = 0.15
    MAX_HALF_LIFE_SEC: float = 35.0
    MIN_STALE_SPREAD_BPS: float = 2.50
    MIN_SAMPLES: int = 8
    ACUTE_CANCEL_RATE: float = 25.0
    ACUTE_MAX_FILL_RATE: float = 0.50
    WINDOW_SIZE: int = 20
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_half_life_sec: float = MIN_HALF_LIFE_SEC,
        max_half_life_sec: float = MAX_HALF_LIFE_SEC,
        min_stale_spread_bps: float = MIN_STALE_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_cancel_rate: float = ACUTE_CANCEL_RATE,
        acute_max_fill_rate: float = ACUTE_MAX_FILL_RATE,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_half_life_sec = float(min_half_life_sec)
        self.max_half_life_sec = float(max_half_life_sec)
        self.min_stale_spread_bps = float(min_stale_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_cancel_rate = float(acute_cancel_rate)
        self.acute_max_fill_rate = float(acute_max_fill_rate)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._half_lives = collections.deque(maxlen=self.window_size)
        self._spreads = collections.deque(maxlen=self.window_size)

        self._latest_half_life: float = 3.0
        self._latest_mean_half_life: float = 3.0
        self._latest_spread_bps: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        half_life: float,
        mean_half_life: float,
        spread_bps: float,
        cancel_rate: float,
        fill_rate: float,
        count: int,
    ) -> bool:
        # 1. Acute phantom cancel burst
        if cancel_rate >= self.acute_cancel_rate and fill_rate <= self.acute_max_fill_rate:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_PHANTOM_CANCEL_BURST: cancel_rate={cancel_rate:.2f} >= {self.acute_cancel_rate:.2f}/s "
                f"with fill_rate={fill_rate:.2f} <= {self.acute_max_fill_rate:.2f}/s"
            )
            return True

        if count >= self.min_samples:
            # 2. Toxic quote flickering (vanishing book)
            if mean_half_life <= self.min_half_life_sec:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"TOXIC_QUOTE_FLICKERING: mean_half_life={mean_half_life:.3f} <= {self.min_half_life_sec:.3f}s "
                    f"over N={count} cycles"
                )
                return True

            # 3. Stale liquidity mirage
            mean_spread = statistics.fmean(self._spreads) if self._spreads else spread_bps
            if mean_half_life >= self.max_half_life_sec and mean_spread >= self.min_stale_spread_bps:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"STALE_LIQUIDITY_MIRAGE: mean_half_life={mean_half_life:.1f} >= {self.max_half_life_sec:.1f}s "
                    f"with spread={mean_spread:.2f} >= {self.min_stale_spread_bps:.2f} bps"
                )
                return True

        return False

    def record_queue_hazard(
        self,
        cancel_rate: float,
        fill_rate: float,
        spread_bps: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record cancellation rate and fill rate in events/sec or lots/sec.
        """
        with self._lock:
            if not self._is_valid_num(cancel_rate) or not self._is_valid_num(fill_rate) or cancel_rate < 0.0 or fill_rate < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_HAZARD_INPUT"
                return

            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else 1.0
            theta = float(cancel_rate)
            mu = float(fill_rate)

            hazard = max(theta + mu, 1e-4)
            half_life = math.log(2.0) / hazard

            self._half_lives.append(half_life)
            self._spreads.append(spr)
            self._sample_count += 1

            mean_hl = statistics.fmean(self._half_lives)
            self._latest_half_life = half_life
            self._latest_mean_half_life = mean_hl
            self._latest_spread_bps = spr

            self._check_and_trigger_block(
                half_life,
                mean_hl,
                spr,
                theta,
                mu,
                len(self._half_lives),
            )

    def record_queue_lifespan(
        self,
        lifespan_sec: float,
        spread_bps: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record empirically observed order resting lifespan in seconds.
        """
        with self._lock:
            if not self._is_valid_num(lifespan_sec) or lifespan_sec <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_LIFESPAN_INPUT"
                return

            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else 1.0
            hl = float(lifespan_sec) * 0.69315  # t_{1/2} ~= 0.693 * mean_lifespan

            self._half_lives.append(hl)
            self._spreads.append(spr)
            self._sample_count += 1

            mean_hl = statistics.fmean(self._half_lives)
            self._latest_half_life = hl
            self._latest_mean_half_life = mean_hl
            self._latest_spread_bps = spr

            self._check_and_trigger_block(
                hl,
                mean_hl,
                spr,
                1.0 / max(lifespan_sec, 1e-4),
                0.2,
                len(self._half_lives),
            )

    def record_half_life_metrics(
        self,
        half_life_sec: float,
        spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed queue half-life metrics.
        """
        with self._lock:
            if not self._is_valid_num(half_life_sec) or half_life_sec <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_HALF_LIFE_METRIC"
                return

            hl = float(half_life_sec)
            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else (self.min_stale_spread_bps + 0.5)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._half_lives.append(hl)
            self._spreads.append(spr)
            self._latest_half_life = hl
            self._latest_mean_half_life = hl
            self._latest_spread_bps = spr
            self._sample_count = cnt

            self._check_and_trigger_block(
                hl,
                hl,
                spr,
                self.acute_cancel_rate + 5.0 if hl <= 0.02 else 1.0,
                0.1,
                cnt,
            )

    def update(
        self,
        cancel_rate: float,
        fill_rate: float,
        spread_bps: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_queue_hazard."""
        self.record_queue_hazard(cancel_rate, fill_rate, spread_bps=spread_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_half_life_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "latest_half_life_sec": float(self._latest_half_life),
                "mean_half_life_sec": float(self._latest_mean_half_life),
                "latest_spread_bps": float(self._latest_spread_bps),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_half_life_metrics()

    def reset(self) -> None:
        with self._lock:
            self._half_lives.clear()
            self._spreads.clear()
            self._latest_half_life = 3.0
            self._latest_mean_half_life = 3.0
            self._latest_spread_bps = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
