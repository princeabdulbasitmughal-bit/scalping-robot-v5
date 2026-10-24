"""Wave 335: High-Frequency Trade Arrival Autoregressive Conditional Duration (ACD) Hazard Guard.

Mathematical and Microstructural Context:
----------------------------------------
In high-frequency financial markets, the time interval between consecutive aggressive market orders
tau_i = t_i - t_{i-1} (in seconds) follows an Autoregressive Conditional Duration (ACD) point process
(Engle & Russell 1998; Bauwens & Giot 2000; Dufour & Engle 2000).
Let conditional expected duration be:
    psi_i = E[tau_i | F_{i-1}] = omega + alpha * tau_{i-1} + beta * psi_{i-1}
where typical stationarity holds with alpha + beta < 1.0.

Under orderly, two-sided market liquidity:
1. Trade arrivals occur at smooth, healthy intervals with rolling average duration tau_bar >= 0.15s,
   allowing market makers ample time to replenish inside book queues.

However, during informed institutional execution sweeps, predatory HFT momentum ignition, or panic cascades:
1. ACD Extreme Duration Compression / Hazard Rate Surge (mean(tau) <= 0.030s over N >= 16 trades with V_total >= 15.0 lots):
   A rapid succession of aggressive market orders choking the matching engine and exhausting resting book depth.
2. Directional Duration Ratio Asymmetry (tau_sell_bar / tau_buy_bar >= 4.0 or tau_buy_bar / tau_sell_bar >= 4.0 over N >= 14 trades with active side volume >= 10.0 lots):
   Arrival duration on one side is drastically compressed compared to the other side, revealing intense one-sided informed aggressive order flow.
3. Acute Microsecond Avalanche Cluster:
   >= 10 aggressive trades arriving within dt <= 0.15s with total executed volume >= 12.0 lots.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against severe adverse selection and execution slippage.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, non-positive volume, negative duration, or invalid sign trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave335TradeArrivalACDHazardGuard:
    """Wave 335: Trade Arrival Autoregressive Conditional Duration Hazard Guard."""

    def __init__(
        self,
        window_size: int = 20,
        compressed_duration_threshold_s: float = 0.030,
        min_compressed_volume: float = 15.0,
        duration_asymmetry_ratio_threshold: float = 4.0,
        min_asymmetry_side_volume: float = 10.0,
        asymmetry_window: int = 14,
        acute_avalanche_trade_count: int = 10,
        acute_avalanche_time_window_s: float = 0.15,
        acute_avalanche_volume: float = 12.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 8:
            window_size = 20
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.compressed_duration_threshold_s = float(compressed_duration_threshold_s)
        self.min_compressed_volume = float(min_compressed_volume)
        self.duration_asymmetry_ratio_threshold = float(duration_asymmetry_ratio_threshold)
        self.min_asymmetry_side_volume = float(min_asymmetry_side_volume)
        self.asymmetry_window = int(asymmetry_window)
        self.acute_avalanche_trade_count = int(acute_avalanche_trade_count)
        self.acute_avalanche_time_window_s = float(acute_avalanche_time_window_s)
        self.acute_avalanche_volume = float(acute_avalanche_volume)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._durations: deque = deque(maxlen=self.window_size)
        self._volumes: deque = deque(maxlen=self.window_size)
        self._asymmetry_trades: deque = deque(maxlen=self.asymmetry_window)
        self._recent_time_trades: deque = deque(maxlen=self.window_size)
        self._last_arrival_time: Optional[float] = None
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_duration: float = 0.0
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
        """Process an aggressive trade print and evaluate arrival duration hazards.

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

            # Determine inter-trade duration
            if self._last_arrival_time is None:
                duration = 0.50  # baseline initiation duration
            else:
                raw_duration = now - self._last_arrival_time
                if raw_duration < 0.0:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"FAIL_CLOSED: Negative inter-trade duration {raw_duration:.6f}s (Clock regression)"
                    )
                    self._total_violations += 1
                    return True
                duration = raw_duration

            self._last_arrival_time = now
            self._last_duration = duration

            # 1. Acute Microsecond Avalanche Cluster check
            self._recent_time_trades.append((now, v_vol))
            # Purge entries outside time window
            while self._recent_time_trades and (now - self._recent_time_trades[0][0]) > self.acute_avalanche_time_window_s:
                self._recent_time_trades.popleft()

            cluster_count = len(self._recent_time_trades)
            cluster_vol = sum(v for _, v in self._recent_time_trades)
            if cluster_count >= self.acute_avalanche_trade_count and cluster_vol >= self.acute_avalanche_volume:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"ACUTE_AVALANCHE_CLUSTER: {cluster_count} trades (vol: {cluster_vol:.2f} lots) "
                    f"in {self.acute_avalanche_time_window_s:.3f}s"
                )
                self._total_violations += 1
                return True

            # 2. Directional Duration Asymmetry check
            self._asymmetry_trades.append((duration, sign_int, v_vol))
            if len(self._asymmetry_trades) >= self.asymmetry_window:
                buy_durations = [d for d, s, _ in self._asymmetry_trades if s == 1]
                sell_durations = [d for d, s, _ in self._asymmetry_trades if s == -1]
                buy_vol = sum(v for _, s, v in self._asymmetry_trades if s == 1)
                sell_vol = sum(v for _, s, v in self._asymmetry_trades if s == -1)

                if buy_durations and sell_durations:
                    mean_buy_dur = sum(buy_durations) / len(buy_durations)
                    mean_sell_dur = sum(sell_durations) / len(sell_durations)

                    # Guard against near-zero division
                    denom_buy = max(mean_buy_dur, 0.001)
                    denom_sell = max(mean_sell_dur, 0.001)

                    # Predatory buying rush: sell duration is much longer than buy duration (buys arrive in rapid bursts)
                    buy_rush_ratio = mean_sell_dur / denom_buy
                    if buy_rush_ratio >= self.duration_asymmetry_ratio_threshold and buy_vol >= self.min_asymmetry_side_volume:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"DIRECTIONAL_DURATION_ASYMMETRY_BUY_RUSH: Ratio {buy_rush_ratio:.2f} >= "
                            f"{self.duration_asymmetry_ratio_threshold:.2f} with buy vol {buy_vol:.2f} lots"
                        )
                        self._total_violations += 1
                        return True

                    # Predatory selling rush: buy duration is much longer than sell duration (sells arrive in rapid bursts)
                    sell_rush_ratio = mean_buy_dur / denom_sell
                    if sell_rush_ratio >= self.duration_asymmetry_ratio_threshold and sell_vol >= self.min_asymmetry_side_volume:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"DIRECTIONAL_DURATION_ASYMMETRY_SELL_RUSH: Ratio {sell_rush_ratio:.2f} >= "
                            f"{self.duration_asymmetry_ratio_threshold:.2f} with sell vol {sell_vol:.2f} lots"
                        )
                        self._total_violations += 1
                        return True

            self._durations.append(duration)
            self._volumes.append(v_vol)

            # 3. ACD Extreme Duration Compression / Hazard Rate Surge
            if len(self._durations) >= 16:
                mean_dur = sum(self._durations) / len(self._durations)
                tot_vol = sum(self._volumes)

                if mean_dur <= self.compressed_duration_threshold_s and tot_vol >= self.min_compressed_volume:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ACD_DURATION_COMPRESSION_HAZARD: Mean duration {mean_dur:.4f}s <= "
                        f"{self.compressed_duration_threshold_s:.4f}s with volume {tot_vol:.2f} lots >= {self.min_compressed_volume:.2f}"
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
            self._durations.clear()
            self._volumes.clear()
            self._asymmetry_trades.clear()
            self._recent_time_trades.clear()
            self._last_arrival_time = None
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_duration = 0.0
            self._total_trades = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            durs = list(self._durations)
            mean_d = (sum(durs) / len(durs)) if durs else self._last_duration
            tot_v = sum(self._volumes)

            return {
                "guard_name": "Wave335TradeArrivalACDHazardGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_duration_s": round(self._last_duration, 4),
                "rolling_mean_duration_s": round(mean_d, 4),
                "total_volume": round(tot_v, 3),
                "buffer_fill": len(self._durations),
                "total_trades": self._total_trades,
                "total_violations": self._total_violations,
            }
