"""
wave285_trade_flow_signed_volume_momentum_guard.py
--------------------------------------------------
Guard: Trade Flow Cumulative Signed Volume Momentum & Toxic Drift Guard

Monitors cumulative signed trade volume, order flow momentum, and directional avalanche persistence
(Kyle 1985; Hasbrouck 1991; Madhavan, Richardson & Roomans 1997; Cont, Kukanov & Stoikov 2014):
    Signed Trade Volume:          q_t = epsilon_t * v_t  where epsilon_t in {-1, +1}, v_t > 0 in lots
    Cumulative Signed Volume:     C_t = sum_{i=1}^K q_i
    Total Unsigned Volume:        V_{total} = sum_{i=1}^K v_i
    Signed Volume Ratio:          S_{ratio} = |C_t| / max(V_{total}, 0.10) in [0.0, 1.0]
    Unidirectional Volume Streak: C_{streak} = sum of volume across consecutive trades of identical sign

Under balanced two-way market making conditions:
    - Buyers and sellers interact organically, resulting in mean-reverting signed volume:
      S_{ratio} <= 0.40, C_{streak} <= 4.0 lots.

During institutional sweep execution, toxic news-driven panic, or predatory momentum runs:
    - Order flow turns heavily unidirectional, accumulating severe signed volume momentum:
        1) Directional Signed Volume Imbalance:
           Signed volume ratio S_{ratio} >= MAX_SIGNED_RATIO (default: 0.80)
           with total volume V_{total} >= MIN_TOTAL_VOLUME (default: 15.0 lots)
           over rolling N >= MIN_TRADES (default: 15 trades).
        2) Acute Directional Volume Avalanche:
           Same-direction volume streak |C_{streak}| >= ACUTE_STREAK_VOLUME (default: 12.0 lots)
           across L_{streak} >= ACUTE_STREAK_LEN (default: 6 consecutive trades).

Entering trades counter to an active signed volume avalanche exposes market makers to immediate
inventory overhang, devastating toxic flow, and catastrophic adverse selection.

When directional imbalance or an acute volume avalanche is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade flow via record_signed_trade(trade_sign, volume_lots, ts=None) or
  direct metrics via record_flow_metrics(signed_ratio, total_volume=None, streak_volume=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_signed_trade(trade_sign, volume_lots, ts=None)                                        -> None
  record_flow_metrics(signed_ratio, total_volume=None, streak_volume=None, sample_count=None)  -> None
  update(trade_sign, volume_lots, ts=None)                                                     -> None   (alias)
  get_flow_momentum_metrics()                                                                  -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave285TradeFlowSignedVolumeMomentumGuard:
    """
    Guards against persistent directional order flow drift, signed volume momentum avalanches, and adverse selection.
    """

    MAX_SIGNED_RATIO: float = 0.80
    MIN_TOTAL_VOLUME: float = 15.0
    MIN_TRADES: int = 15
    ACUTE_STREAK_VOLUME: float = 12.0
    ACUTE_STREAK_LEN: int = 6
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_signed_ratio: float = MAX_SIGNED_RATIO,
        min_total_volume: float = MIN_TOTAL_VOLUME,
        min_trades: int = MIN_TRADES,
        acute_streak_volume: float = ACUTE_STREAK_VOLUME,
        acute_streak_len: int = ACUTE_STREAK_LEN,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_signed_ratio = float(max_signed_ratio)
        self.min_total_volume = float(min_total_volume)
        self.min_trades = int(min_trades)
        self.acute_streak_volume = float(acute_streak_volume)
        self.acute_streak_len = int(acute_streak_len)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._signed_history = collections.deque(maxlen=self.window_size)
        self._volume_history = collections.deque(maxlen=self.window_size)

        self._last_sign: Optional[int] = None
        self._streak_len: int = 0
        self._streak_volume: float = 0.0

        self._latest_signed_ratio: float = 0.0
        self._latest_total_vol: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        signed_ratio: float,
        total_vol: float,
        streak_vol: float,
        streak_len: int,
        sample_count: int,
    ) -> bool:
        # 1. Acute directional volume avalanche
        if streak_len >= self.acute_streak_len and streak_vol >= self.acute_streak_volume:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_VOLUME_AVALANCHE: streak_vol={streak_vol:.2f} >= {self.acute_streak_volume:.2f} lots, "
                f"streak_len={streak_len} >= {self.acute_streak_len}"
            )
            return True

        # 2. Directional signed volume imbalance
        if (
            sample_count >= self.min_trades
            and signed_ratio >= self.max_signed_ratio
            and total_vol >= self.min_total_volume
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"DIRECTIONAL_SIGNED_IMBALANCE: ratio={signed_ratio:.2f} >= {self.max_signed_ratio:.2f}, "
                f"total_vol={total_vol:.2f} >= {self.min_total_volume:.2f} lots (N={sample_count})"
            )
            return True

        return False

    def record_signed_trade(
        self,
        trade_sign: int,
        volume_lots: float,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record a trade execution with sign (+1 for buyer-initiated, -1 for seller-initiated) and volume.
        """
        with self._lock:
            if (
                not self._is_valid_num(trade_sign)
                or not self._is_valid_num(volume_lots)
                or volume_lots <= 0.0
                or int(trade_sign) not in (-1, 1)
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SIGNED_TRADE"
                return

            sgn = int(trade_sign)
            vol = float(volume_lots)
            signed_vol = sgn * vol

            self._signed_history.append(signed_vol)
            self._volume_history.append(vol)
            self._sample_count += 1

            if self._last_sign is not None and sgn == self._last_sign:
                self._streak_len += 1
                self._streak_volume += vol
            else:
                self._streak_len = 1
                self._streak_volume = vol
            self._last_sign = sgn

            total_vol = sum(self._volume_history)
            cum_signed = sum(self._signed_history)
            signed_ratio = abs(cum_signed) / max(total_vol, 0.10)

            self._latest_signed_ratio = signed_ratio
            self._latest_total_vol = total_vol

            self._check_and_trigger_block(
                signed_ratio,
                total_vol,
                self._streak_volume,
                self._streak_len,
                len(self._volume_history),
            )

    def record_flow_metrics(
        self,
        signed_ratio: float,
        total_volume: Optional[float] = None,
        streak_volume: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed signed volume metrics.
        """
        with self._lock:
            if not self._is_valid_num(signed_ratio) or signed_ratio < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_FLOW_METRIC"
                return

            ratio = float(signed_ratio)
            t_vol = float(total_volume) if (self._is_valid_num(total_volume) and total_volume >= 0.0) else self.min_total_volume + 1.0
            stk_vol = float(streak_volume) if (self._is_valid_num(streak_volume) and streak_volume >= 0.0) else 0.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_trades

            self._latest_signed_ratio = ratio
            self._latest_total_vol = t_vol
            self._sample_count = cnt

            self._check_and_trigger_block(
                ratio,
                t_vol,
                stk_vol,
                self.acute_streak_len if stk_vol >= self.acute_streak_volume else 1,
                cnt,
            )

    def update(
        self,
        trade_sign: int,
        volume_lots: float,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_signed_trade."""
        self.record_signed_trade(trade_sign, volume_lots, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_flow_momentum_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._volume_history:
                total_vol = sum(self._volume_history)
                cum_signed = sum(self._signed_history)
                signed_ratio = abs(cum_signed) / max(total_vol, 0.10)
            else:
                total_vol = self._latest_total_vol
                cum_signed = self._latest_signed_ratio * total_vol
                signed_ratio = self._latest_signed_ratio

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "signed_volume_ratio": float(signed_ratio),
                "cumulative_signed_volume": float(cum_signed),
                "total_volume_lots": float(total_vol),
                "streak_volume_lots": float(self._streak_volume),
                "streak_len": int(self._streak_len),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_flow_momentum_metrics()

    def reset(self) -> None:
        with self._lock:
            self._signed_history.clear()
            self._volume_history.clear()
            self._last_sign = None
            self._streak_len = 0
            self._streak_volume = 0.0
            self._latest_signed_ratio = 0.0
            self._latest_total_vol = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
