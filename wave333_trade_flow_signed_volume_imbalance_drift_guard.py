"""Wave 333: High-Frequency Trade Flow Cumulative Signed Volume Drift & Information Rent Guard.

Mathematical and Microstructural Context:
----------------------------------------
In balanced financial markets, order flow arrival signs epsilon_t in {-1, +1} (buy/sell)
and executed volumes V_t oscillate symmetrically around zero mean, preventing persistent
directional inventory accumulation for passive market makers (Kyle 1985; Glosten & Milgrom 1985;
Hasbrouck 1991).

For a rolling window of N aggressive trade prints with signed volumes v_i = epsilon_i * V_i:
    Cumulative signed volume: C_t = sum_{i=1}^N epsilon_i * V_i
    Total executed volume:    V_total = sum_{i=1}^N V_i
    Directional drift ratio:  rho_drift = |C_t| / V_total   in [0, 1]

Under balanced two-sided trading:
1. Buy and sell volumes offset naturally, keeping rho_drift <= 0.40.

However, during informed institutional execution sweeps or stop-loss cascades:
1. Persistent Directional Volume Drift (rho_drift >= 0.78 with V_total >= 16.0 lots over N >= 16 trades):
   Indicates severe unilateral order flow toxicity exhausting book depth on one side.
2. Acute Directional Volume Avalanche (|Delta C| >= 12.0 lots in dt <= 0.30s):
   A rapid succession of aggressive market orders slamming the book in sub-second time.
3. Monotonic Sign Concentration (>= 12 trades on the same side within 14 consecutive trades):
   Persistent predatory order routing overwhelming market maker quote replenishment.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against severe adverse selection.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, non-positive volume or invalid sign
trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave333TradeFlowSignedVolumeImbalanceDriftGuard:
    """Wave 333: Trade Flow Cumulative Signed Volume Drift Guard."""

    def __init__(
        self,
        window_size: int = 20,
        drift_ratio_threshold: float = 0.78,
        min_total_volume: float = 16.0,
        acute_avalanche_volume: float = 12.0,
        acute_time_window_s: float = 0.30,
        sign_concentration_threshold: int = 12,
        sign_concentration_window: int = 14,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 8:
            window_size = 20
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.drift_ratio_threshold = float(drift_ratio_threshold)
        self.min_total_volume = float(min_total_volume)
        self.acute_avalanche_volume = float(acute_avalanche_volume)
        self.acute_time_window_s = float(acute_time_window_s)
        self.sign_concentration_threshold = int(sign_concentration_threshold)
        self.sign_concentration_window = int(sign_concentration_window)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._trades: deque = deque(maxlen=self.window_size)
        self._recent_signs: deque = deque(maxlen=self.sign_concentration_window)
        self._recent_time_trades: deque = deque(maxlen=self.window_size)
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_drift_ratio: float = 0.0
        self._total_trades: int = 0
        self._total_violations: int = 0

    def _validate_numeric(self, val: Any) -> Optional[float]:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval

    def update(
        self,
        trade_volume: float,
        trade_sign: int,
        current_time: Optional[float] = None,
    ) -> bool:
        """Process an aggressive trade print and evaluate signed volume drift.

        trade_sign: +1 for Buy, -1 for Sell.
        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_trades += 1

            v_vol = self._validate_numeric(trade_volume)
            v_sign = self._validate_numeric(trade_sign)

            if v_vol is None or v_sign is None or v_vol <= 0.0 or v_sign not in (-1.0, 1.0):
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"FAIL_CLOSED: Invalid trade input: vol={trade_volume}, sign={trade_sign}"
                )
                self._total_violations += 1
                return True

            sign_int = 1 if v_sign > 0 else -1
            signed_vol = sign_int * v_vol

            # 1. Acute Directional Volume Avalanche check over rolling time window
            self._recent_time_trades.append((now, signed_vol))
            # Purge entries older than acute_time_window_s
            while self._recent_time_trades and (now - self._recent_time_trades[0][0]) > self.acute_time_window_s:
                self._recent_time_trades.popleft()

            net_time_signed_vol = sum(sv for _, sv in self._recent_time_trades)
            if abs(net_time_signed_vol) >= self.acute_avalanche_volume:
                self._blocked_until = now + self.cooldown_seconds
                side = "BUY" if net_time_signed_vol > 0 else "SELL"
                self._last_block_reason = (
                    f"ACUTE_DIRECTIONAL_AVALANCHE: Net {side} signed volume {abs(net_time_signed_vol):.2f} lots "
                    f">= {self.acute_avalanche_volume:.2f} lots in {self.acute_time_window_s:.3f}s"
                )
                self._total_violations += 1
                return True

            # 2. Monotonic Sign Concentration check
            self._recent_signs.append(sign_int)
            if len(self._recent_signs) >= self.sign_concentration_window:
                buy_count = sum(1 for s in self._recent_signs if s == 1)
                sell_count = len(self._recent_signs) - buy_count
                max_side_count = max(buy_count, sell_count)

                if max_side_count >= self.sign_concentration_threshold:
                    self._blocked_until = now + self.cooldown_seconds
                    side = "BUY" if buy_count > sell_count else "SELL"
                    self._last_block_reason = (
                        f"MONOTONIC_SIGN_CONCENTRATION: {max_side_count} {side} trades out of "
                        f"{len(self._recent_signs)} consecutive trades >= {self.sign_concentration_threshold}"
                    )
                    self._total_violations += 1
                    return True

            self._trades.append((v_vol, signed_vol))

            # 3. Persistent Directional Volume Drift check
            if len(self._trades) >= 16:
                tot_vol = sum(v for v, _ in self._trades)
                cum_signed = sum(sv for _, sv in self._trades)

                if tot_vol > 0.0:
                    drift_ratio = abs(cum_signed) / tot_vol
                    self._last_drift_ratio = drift_ratio

                    if drift_ratio >= self.drift_ratio_threshold and tot_vol >= self.min_total_volume:
                        self._blocked_until = now + self.cooldown_seconds
                        side = "BUY" if cum_signed > 0 else "SELL"
                        self._last_block_reason = (
                            f"PERSISTENT_VOLUME_DRIFT: {side} drift ratio {drift_ratio:.2f} >= "
                            f"{self.drift_ratio_threshold:.2f} with total volume {tot_vol:.2f} lots >= {self.min_total_volume:.2f}"
                        )
                        self._total_violations += 1
                        return True

            return now < self._blocked_until

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        """Return True if the guard is currently blocking entries."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            return now < self._blocked_until

    def is_entry_blocked(self, current_time: Optional[float] = None) -> bool:
        """Alias for is_blocked."""
        return self.is_blocked(current_time)

    def reset(self) -> None:
        """Reset internal buffers and state."""
        with self._lock:
            self._trades.clear()
            self._recent_signs.clear()
            self._recent_time_trades.clear()
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_drift_ratio = 0.0
            self._total_trades = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            tot_vol = sum(v for v, _ in self._trades)
            cum_signed = sum(sv for _, sv in self._trades)
            drift = (abs(cum_signed) / tot_vol) if tot_vol > 0.0 else self._last_drift_ratio

            return {
                "guard_name": "Wave333TradeFlowSignedVolumeImbalanceDriftGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "drift_ratio": round(drift, 4),
                "total_volume": round(tot_vol, 3),
                "cumulative_signed_volume": round(cum_signed, 3),
                "buffer_fill": len(self._trades),
                "total_trades": self._total_trades,
                "total_violations": self._total_violations,
            }
