"""
wave282_lob_imbalance_acceleration_guard.py
-------------------------------------------
Guard: LOB Inside-Queue Imbalance Acceleration & Second-Derivative Order Flow Jolt Guard

Monitors limit order book queue imbalance acceleration and higher-order kinematic order flow forces
(Cont, Kukanov & Stoikov 2014; Cartea, Jaimungal & Ricci 2014; Lehalle & Mounjid 2017):
    Level-1 Imbalance:         I = (Q_{bid} - Q_{ask}) / max(Q_{bid} + Q_{ask}, 1e-4) in [-1.0, +1.0]
    Imbalance Velocity:        v_I = Delta I / max(Delta t, 0.02)  (units / sec)
    Imbalance Acceleration:    a_I = Delta v_I / max(Delta t, 0.02) (units / sec^2)

Under stationary, equilibrium order book quoting:
    - Queue imbalance drifts smoothly around zero with small kinematic forces:
      |v_I| <= 0.60 units/s, |a_I| <= 1.50 units/sec^2.

During institutional sweep cascades, aggressive predatory front-running, or flash liquidity cancellations:
    - Queue imbalance experiences sudden violent second-derivative jolts:
        1) Persistent Imbalance Acceleration Surge:
           Rolling mean acceleration |\\bar{a}_I| >= MAX_MEAN_ACCELERATION (default: 4.50 units/sec^2)
           with |I| >= MIN_IMBALANCE_LEVEL (default: 0.50) over N >= MIN_SAMPLES (6 intervals).
        2) Acute Imbalance Jolt:
           Instantaneous acceleration |a_I| >= ACUTE_JOLT_ACCELERATION (default: 8.00 units/sec^2)
           with swing |Delta I| >= ACUTE_SWING (default: 0.70) in Delta t <= 0.20s.

High imbalance acceleration indicates immediate unbuffered book collapse, triggering rapid adverse quote jumps
and disastrous execution slippage for passive limit orders.

When acceleration surge or an acute imbalance jolt is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests queue depth via record_queue_depth(bid_depth, ask_depth, ts=None) or
  direct metrics via record_acceleration(accel_units_per_sec2, imbalance=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 12 acceleration observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_queue_depth(bid_depth, ask_depth, ts=None)                                            -> None
  record_acceleration(accel_units_per_sec2, imbalance=None, sample_count=None, ts=None)        -> None
  update(bid_depth, ask_depth, ts=None)                                                        -> None   (alias)
  get_acceleration_metrics()                                                                   -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, Optional


class Wave282LobImbalanceAccelerationGuard:
    """
    Guards against rapid second-derivative LOB queue depletion, imbalance jolts, and quote collapses.
    """

    MAX_MEAN_ACCELERATION: float = 4.50
    MIN_IMBALANCE_LEVEL: float = 0.50
    MIN_SAMPLES: int = 6
    ACUTE_JOLT_ACCELERATION: float = 8.00
    ACUTE_SWING: float = 0.70
    WINDOW_SIZE: int = 12
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_mean_acceleration: float = MAX_MEAN_ACCELERATION,
        min_imbalance_level: float = MIN_IMBALANCE_LEVEL,
        min_samples: int = MIN_SAMPLES,
        acute_jolt_acceleration: float = ACUTE_JOLT_ACCELERATION,
        acute_swing: float = ACUTE_SWING,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_mean_acceleration = float(max_mean_acceleration)
        self.min_imbalance_level = float(min_imbalance_level)
        self.min_samples = int(min_samples)
        self.acute_jolt_acceleration = float(acute_jolt_acceleration)
        self.acute_swing = float(acute_swing)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._accel_history = collections.deque(maxlen=self.window_size)
        self._imbalance_history = collections.deque(maxlen=self.window_size)

        self._last_imbalance: Optional[float] = None
        self._last_velocity: Optional[float] = None
        self._last_ts: Optional[float] = None

        self._latest_accel: float = 0.0
        self._latest_imbalance: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        mean_accel: float,
        latest_accel: float,
        imbalance: float,
        swing: float,
        delta_t: float,
    ) -> bool:
        # 1. Acute imbalance jolt
        if abs(latest_accel) >= self.acute_jolt_acceleration and swing >= self.acute_swing and delta_t <= 0.20:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_IMBALANCE_JOLT: accel={latest_accel:.2f} >= {self.acute_jolt_acceleration:.2f}, "
                f"swing={swing:.2f} in dt={delta_t:.3f}s"
            )
            return True

        # 2. Persistent imbalance acceleration surge
        if (
            self._sample_count >= self.min_samples
            and mean_accel >= self.max_mean_acceleration
            and abs(imbalance) >= self.min_imbalance_level
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"IMBALANCE_ACCELERATION_SURGE: mean_accel={mean_accel:.2f} >= {self.max_mean_acceleration:.2f}, "
                f"|I|={abs(imbalance):.2f} >= {self.min_imbalance_level:.2f} (N={self._sample_count})"
            )
            return True

        return False

    def record_queue_depth(
        self,
        bid_depth: float,
        ask_depth: float,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record instantaneous Level-1 bid and ask depths, updating velocity and acceleration.
        """
        with self._lock:
            if (
                not self._is_valid_num(bid_depth)
                or not self._is_valid_num(ask_depth)
                or bid_depth < 0.0
                or ask_depth < 0.0
                or (bid_depth == 0.0 and ask_depth == 0.0)
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_QUEUE_DEPTH"
                return

            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            total_depth = bid_depth + ask_depth
            imbalance = (bid_depth - ask_depth) / total_depth
            self._latest_imbalance = imbalance
            self._imbalance_history.append(imbalance)

            if self._last_ts is not None and self._last_imbalance is not None:
                delta_t = max(now_ts - self._last_ts, 0.02)
                delta_i = imbalance - self._last_imbalance
                velocity = delta_i / delta_t

                if self._last_velocity is not None:
                    delta_v = velocity - self._last_velocity
                    acceleration = delta_v / delta_t
                    self._latest_accel = acceleration
                    self._accel_history.append(abs(acceleration))
                    self._sample_count += 1

                    mean_acc = statistics.mean(self._accel_history) if self._accel_history else abs(acceleration)
                    self._check_and_trigger_block(
                        mean_acc,
                        abs(acceleration),
                        imbalance,
                        abs(delta_i),
                        delta_t,
                    )
                self._last_velocity = velocity
            self._last_imbalance = imbalance
            self._last_ts = now_ts

    def record_acceleration(
        self,
        accel_units_per_sec2: float,
        imbalance: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed imbalance acceleration.
        """
        with self._lock:
            if not self._is_valid_num(accel_units_per_sec2):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_ACCELERATION_METRIC"
                return

            accel = float(accel_units_per_sec2)
            imb = float(imbalance) if self._is_valid_num(imbalance) else 0.60
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_accel = accel
            self._latest_imbalance = imb
            self._sample_count = cnt
            self._accel_history.append(abs(accel))
            self._imbalance_history.append(imb)

            mean_acc = statistics.mean(self._accel_history) if self._accel_history else abs(accel)
            self._check_and_trigger_block(
                mean_acc,
                abs(accel),
                imb,
                abs(imb),
                0.05,
            )

    def update(
        self,
        bid_depth: float,
        ask_depth: float,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_queue_depth."""
        self.record_queue_depth(bid_depth, ask_depth, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_acceleration_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._accel_history:
                mean_acc = statistics.mean(self._accel_history)
                max_acc = max(self._accel_history)
            else:
                mean_acc = abs(self._latest_accel)
                max_acc = abs(self._latest_accel)

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "mean_acceleration": float(mean_acc),
                "max_acceleration": float(max_acc),
                "latest_acceleration": float(self._latest_accel),
                "latest_imbalance": float(self._latest_imbalance),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_acceleration_metrics()

    def reset(self) -> None:
        with self._lock:
            self._accel_history.clear()
            self._imbalance_history.clear()
            self._last_imbalance = None
            self._last_velocity = None
            self._last_ts = None
            self._latest_accel = 0.0
            self._latest_imbalance = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
