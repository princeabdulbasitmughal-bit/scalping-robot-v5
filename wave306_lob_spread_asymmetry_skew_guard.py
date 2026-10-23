"""
wave306_lob_spread_asymmetry_skew_guard.py
------------------------------------------
Guard: LOB Bid-Ask Spread Quote Asymmetry & Inventory Shading Skew Guard

Monitors bid-ask quote shading asymmetry relative to previous mid-price, guarding against
predatory one-sided quote widening, adverse inventory shading, and directional quote blowout traps
(Huang & Stoll 1997; Chordia, Roll & Subrahmanyam 2000, 2008; Handa, Schwartz & Tiwari 2003):
    Reference Mid-Price:          m_{t-1} = (p_{bid, t-1} + p_{ask, t-1}) / 2
    Bid Distance:                 s_{bid, t} = max(m_{t-1} - p_{bid, t}, 1e-5)
    Ask Distance:                 s_{ask, t} = max(p_{ask, t} - m_{t-1}, 1e-5)
    Spread in bps:                S_t = ((p_{ask, t} - p_{bid, t}) / m_{t-1}) * 10000
    Quote Asymmetry Skew:         A_t = (s_{ask, t} - s_{bid, t}) / (s_{ask, t} + s_{bid, t})
                                  where A_t in [-1.0, +1.0]
    Rolling Mean Asymmetry:       \\bar{A} = (1 / N) * sum_{i=1}^N A_i

Under symmetric, competitive quoting:
    - Market makers position bid and ask evenly around equilibrium:
      |\\bar{A}| <= 0.35.

Under informed flow, toxic order arrival, or predatory liquidity shading:
    - Market makers aggressively shade quotes away from impending adverse price moves:
        1) Persistent Quote Shading Asymmetry:
           Absolute mean asymmetry |\\bar{A}| >= MAX_QUOTE_ASYMMETRY (default: 0.65)
           with average spread S_t >= MIN_SPREAD_BPS (default: 2.00 bps)
           over rolling N >= MIN_SAMPLES (default: 10 ticks).
        2) Acute Directional Quote Blowout:
           Instantaneous |A_t| >= ACUTE_QUOTE_ASYMMETRY (default: 0.85)
           with wide spread S_t >= ACUTE_SPREAD_BPS (default: 3.00 bps).

Trading into heavily skewed quotes guarantees high adverse selection penalty, immediate toxic fills,
and slippage on order execution.

When persistent quote asymmetry or an acute directional quote blowout is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes via record_quotes(bid, ask, prev_mid=None, ts=None) or
  direct metrics via record_asymmetry_metrics(asymmetry_skew, spread_bps=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 20 ticks.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive, or inverted quotes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quotes(bid, ask, prev_mid=None, ts=None)                                              -> None
  record_asymmetry_metrics(asymmetry_skew, spread_bps=None, sample_count=None, ts=None)        -> None
  update(bid, ask, prev_mid=None, ts=None)                                                     -> None   (alias)
  get_asymmetry_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave306LobSpreadAsymmetrySkewGuard:
    """
    Guards against LOB quote shading asymmetry, predatory one-sided widening, and adverse inventory skew.
    """

    MAX_QUOTE_ASYMMETRY: float = 0.65
    MIN_SAMPLES: int = 10
    MIN_SPREAD_BPS: float = 2.00
    ACUTE_QUOTE_ASYMMETRY: float = 0.85
    ACUTE_SPREAD_BPS: float = 3.00
    WINDOW_SIZE: int = 20
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_quote_asymmetry: float = MAX_QUOTE_ASYMMETRY,
        min_samples: int = MIN_SAMPLES,
        min_spread_bps: float = MIN_SPREAD_BPS,
        acute_quote_asymmetry: float = ACUTE_QUOTE_ASYMMETRY,
        acute_spread_bps: float = ACUTE_SPREAD_BPS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_quote_asymmetry = float(max_quote_asymmetry)
        self.min_samples = int(min_samples)
        self.min_spread_bps = float(min_spread_bps)
        self.acute_quote_asymmetry = float(acute_quote_asymmetry)
        self.acute_spread_bps = float(acute_spread_bps)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._asymmetry_history = collections.deque(maxlen=self.window_size)
        self._spread_history = collections.deque(maxlen=self.window_size)

        self._last_mid: Optional[float] = None

        self._latest_asymmetry: float = 0.0
        self._latest_mean_asymmetry: float = 0.0
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
        asymmetry: float,
        mean_asymmetry: float,
        spread_bps: float,
        mean_spread: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute directional quote blowout
        if abs(asymmetry) >= self.acute_quote_asymmetry and spread_bps >= self.acute_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_QUOTE_BLOWOUT: asymmetry={asymmetry:.3f} (>= {self.acute_quote_asymmetry:.3f}) "
                f"with spread={spread_bps:.2f} >= {self.acute_spread_bps:.2f} bps"
            )
            return True

        # 2. Persistent quote shading asymmetry
        if sample_count >= self.min_samples and abs(mean_asymmetry) >= self.max_quote_asymmetry and mean_spread >= self.min_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"PERSISTENT_QUOTE_ASYMMETRY: mean_asym={mean_asymmetry:.3f} (>= {self.max_quote_asymmetry:.3f}) "
                f"with mean_spread={mean_spread:.2f} >= {self.min_spread_bps:.2f} bps over N={sample_count}"
            )
            return True

        return False

    def record_quotes(
        self,
        bid: float,
        ask: float,
        prev_mid: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record instantaneous bid and ask prices and evaluate quote asymmetry.
        """
        with self._lock:
            if not self._is_valid_num(bid) or not self._is_valid_num(ask) or bid <= 0.0 or ask <= 0.0 or ask <= bid:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_QUOTE_INPUT"
                return

            current_mid = (bid + ask) / 2.0
            ref_mid = float(prev_mid) if (self._is_valid_num(prev_mid) and prev_mid > 0.0) else (self._last_mid if self._last_mid is not None else current_mid)

            s_bid = max(ref_mid - bid, 1e-5)
            s_ask = max(ask - ref_mid, 1e-5)
            spread_bps = ((ask - bid) / ref_mid) * 10000.0

            denom = s_ask + s_bid
            asymmetry = (s_ask - s_bid) / denom if denom > 0.0 else 0.0
            asymmetry = max(-1.0, min(1.0, asymmetry))

            self._asymmetry_history.append(asymmetry)
            self._spread_history.append(spread_bps)
            self._sample_count += 1
            self._last_mid = current_mid

            mean_asym = statistics.fmean(self._asymmetry_history)
            mean_spread = statistics.fmean(self._spread_history)

            self._latest_asymmetry = asymmetry
            self._latest_mean_asymmetry = mean_asym
            self._latest_spread_bps = spread_bps

            self._check_and_trigger_block(
                asymmetry,
                mean_asym,
                spread_bps,
                mean_spread,
                len(self._asymmetry_history),
            )

    def record_asymmetry_metrics(
        self,
        asymmetry_skew: float,
        spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed quote asymmetry metrics.
        """
        with self._lock:
            if not self._is_valid_num(asymmetry_skew) or asymmetry_skew < -1.0 or asymmetry_skew > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_ASYMMETRY_METRIC"
                return

            asym = float(asymmetry_skew)
            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else (self.min_spread_bps + 0.5)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_asymmetry = asym
            self._latest_mean_asymmetry = asym
            self._latest_spread_bps = spr
            self._sample_count = cnt

            self._check_and_trigger_block(
                asym,
                asym,
                spr,
                spr,
                cnt,
            )

    def update(
        self,
        bid: float,
        ask: float,
        prev_mid: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_quotes."""
        self.record_quotes(bid, ask, prev_mid=prev_mid, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_asymmetry_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "latest_asymmetry": float(self._latest_asymmetry),
                "mean_asymmetry": float(self._latest_mean_asymmetry),
                "latest_spread_bps": float(self._latest_spread_bps),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_asymmetry_metrics()

    def reset(self) -> None:
        with self._lock:
            self._asymmetry_history.clear()
            self._spread_history.clear()
            self._last_mid = None
            self._latest_asymmetry = 0.0
            self._latest_mean_asymmetry = 0.0
            self._latest_spread_bps = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
