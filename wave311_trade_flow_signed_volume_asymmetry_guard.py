"""
wave311_trade_flow_signed_volume_asymmetry_guard.py
---------------------------------------------------
Guard: High-Frequency Trade Flow Signed Volume Asymmetry & Directional Avalanche Guard

Monitors signed trade volume order flow asymmetry I_V = (V_+ - V_-) / (V_+ + V_-),
guarding against predatory directional volume avalanches, one-sided institutional liquidation, and toxic sweeps
(Kyle 1985; Hasbrouck 1991; Easley et al. 2012, 2016; Cartea, Jaimungal & Penalva 2015):
    Trade Direction & Size:       s_i in {+1, -1}, V_i in lots
    Rolling Buy Volume:           V_+ = sum_{s_i = +1} V_i
    Rolling Sell Volume:          V_- = sum_{s_i = -1} V_i
    Total Traded Volume:          V_{total} = V_+ + V_-
    Signed Volume Asymmetry:      I_V = (V_+ - V_-) / max(V_{total}, 1e-4)  in [-1.0, +1.0]

Under balanced two-sided market making:
    - Order flow volume is evenly distributed between buyers and sellers:
      |I_V| <= 0.40.

Under aggressive institutional liquidation, informed sweeps, or panic cascading:
    - Order flow volume tilts overwhelmingly to one side:
        1) Directional Volume Avalanche:
           Absolute volume asymmetry |I_V| >= MAX_VOLUME_ASYMMETRY (default: 0.78)
           with substantial total volume V_{total} >= MIN_TOTAL_VOLUME (default: 15.0 lots)
           over rolling N >= MIN_SAMPLES (default: 12 trades).
        2) Acute Volume Surge Shock:
           Unilateral trade/sweep V_t >= ACUTE_SURGE_VOLUME (default: 12.0 lots)
           with near-zero opposing volume.

Trading against an active directional volume avalanche guarantees immediate front-running,
depth depletion, and catastrophic adverse selection.

When directional volume avalanche or an acute volume surge shock is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests signed trades via record_signed_trade(sign, volume_lots, ts=None) or
  direct metrics via record_asymmetry_metrics(volume_asymmetry, total_volume=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_signed_trade(sign, volume_lots, ts=None)                                              -> None
  record_asymmetry_metrics(volume_asymmetry, total_volume=None, sample_count=None, ts=None)    -> None
  update(sign, volume_lots, ts=None)                                                           -> None   (alias)
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


class Wave311TradeFlowSignedVolumeAsymmetryGuard:
    """
    Guards against trade flow signed volume avalanches, one-sided institutional dumping, and predatory sweeps.
    """

    MAX_VOLUME_ASYMMETRY: float = 0.78
    MIN_SAMPLES: int = 12
    MIN_TOTAL_VOLUME: float = 15.0
    ACUTE_SURGE_VOLUME: float = 12.0
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_volume_asymmetry: float = MAX_VOLUME_ASYMMETRY,
        min_samples: int = MIN_SAMPLES,
        min_total_volume: float = MIN_TOTAL_VOLUME,
        acute_surge_volume: float = ACUTE_SURGE_VOLUME,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_volume_asymmetry = float(max_volume_asymmetry)
        self.min_samples = int(min_samples)
        self.min_total_volume = float(min_total_volume)
        self.acute_surge_volume = float(acute_surge_volume)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._trades = collections.deque(maxlen=self.window_size)

        self._latest_asymmetry: float = 0.0
        self._latest_total_volume: float = 0.0
        self._latest_buy_volume: float = 0.0
        self._latest_sell_volume: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_asymmetry(self) -> tuple[float, float, float, float]:
        if not self._trades:
            return 0.0, 0.0, 0.0, 0.0

        v_buy = sum(v for s, v in self._trades if s > 0)
        v_sell = sum(v for s, v in self._trades if s < 0)
        v_tot = v_buy + v_sell

        if v_tot <= 1e-4:
            return 0.0, 0.0, 0.0, 0.0

        asym = (v_buy - v_sell) / v_tot
        return asym, v_tot, v_buy, v_sell

    def _check_and_trigger_block(
        self,
        asymmetry: float,
        total_vol: float,
        acute_vol: float,
        count: int,
    ) -> bool:
        # 1. Acute volume surge shock
        if acute_vol >= self.acute_surge_volume and abs(asymmetry) >= 0.85:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_VOLUME_SURGE: trade_vol={acute_vol:.2f} >= {self.acute_surge_volume:.2f} lots "
                f"with asymmetry={asymmetry:.2f}"
            )
            return True

        # 2. Directional volume avalanche
        if count >= self.min_samples and abs(asymmetry) >= self.max_volume_asymmetry and total_vol >= self.min_total_volume:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"DIRECTIONAL_VOLUME_AVALANCHE: asymmetry={asymmetry:.3f} >= {self.max_volume_asymmetry:.3f} "
                f"with total_vol={total_vol:.2f} >= {self.min_total_volume:.2f} lots over N={count} trades"
            )
            return True

        return False

    def record_signed_trade(self, sign: Any, volume_lots: float, ts: Optional[float] = None) -> None:
        """
        Record individual signed trade (+1 buy, -1 sell) and volume in lots.
        """
        with self._lock:
            if not self._is_valid_num(volume_lots) or volume_lots <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_VOLUME_INPUT"
                return

            val_sign = 0
            if isinstance(sign, bool):
                val_sign = 1 if sign else -1
            elif isinstance(sign, (int, float)):
                if not self._is_valid_num(sign):
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_SIGN_INPUT"
                    return
                val_sign = 1 if sign > 0 else (-1 if sign < 0 else 0)
            elif isinstance(sign, str):
                s_lower = sign.strip().lower()
                if s_lower in ("buy", "b", "+1", "1"):
                    val_sign = 1
                elif s_lower in ("sell", "s", "-1"):
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

            if val_sign == 0:
                return

            vol = float(volume_lots)
            self._trades.append((val_sign, vol))
            self._sample_count += 1

            asym, v_tot, v_buy, v_sell = self._calculate_asymmetry()
            self._latest_asymmetry = asym
            self._latest_total_volume = v_tot
            self._latest_buy_volume = v_buy
            self._latest_sell_volume = v_sell

            self._check_and_trigger_block(
                asym,
                v_tot,
                vol,
                len(self._trades),
            )

    def record_asymmetry_metrics(
        self,
        volume_asymmetry: float,
        total_volume: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed volume asymmetry metrics.
        """
        with self._lock:
            if not self._is_valid_num(volume_asymmetry) or volume_asymmetry < -1.0 or volume_asymmetry > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_ASYMMETRY_METRIC"
                return

            asym = float(volume_asymmetry)
            v_tot = float(total_volume) if (self._is_valid_num(total_volume) and total_volume >= 0.0) else (self.min_total_volume + 5.0)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_asymmetry = asym
            self._latest_total_volume = v_tot
            self._sample_count = cnt

            self._check_and_trigger_block(
                asym,
                v_tot,
                self.acute_surge_volume + 2.0 if abs(asym) >= 0.95 else 1.0,
                cnt,
            )

    def update(self, sign: Any, volume_lots: float, ts: Optional[float] = None) -> None:
        """Alias for record_signed_trade."""
        self.record_signed_trade(sign, volume_lots, ts=ts)

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
                "volume_asymmetry": float(self._latest_asymmetry),
                "total_volume": float(self._latest_total_volume),
                "buy_volume": float(self._latest_buy_volume),
                "sell_volume": float(self._latest_sell_volume),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_asymmetry_metrics()

    def reset(self) -> None:
        with self._lock:
            self._trades.clear()
            self._latest_asymmetry = 0.0
            self._latest_total_volume = 0.0
            self._latest_buy_volume = 0.0
            self._latest_sell_volume = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
