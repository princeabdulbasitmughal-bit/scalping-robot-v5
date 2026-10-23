"""
wave298_lob_order_flow_toxicity_momentum_guard.py
-------------------------------------------------
Guard: LOB Net Order Flow Imbalance Momentum & Toxic Adverse Selection Guard

Monitors limit order book Order Flow Imbalance (OFI), cumulative flow momentum, and directional toxicity surges
(Cont, Kukanov & Stoikov 2014; Cartea & Jaimungal 2014; Lehalle & Mounjid 2017):
    Level-1 State:               (P_{bid}, Q_{bid}, P_{ask}, Q_{ask})
    Bid Flow Contribution:       Delta Q_{bid} * I_{P_{bid} >= P_{bid,prev}}
    Ask Flow Contribution:       Delta Q_{ask} * I_{P_{ask} <= P_{ask,prev}}
    Order Flow Imbalance:        OFI_t in lots
    OFI Momentum:                M_{OFI} = sum_{i=1}^N OFI_i / max(sum_{i=1}^N |OFI_i|, 0.10) in [-1.0, +1.0]
    Acute Unidirectional Surge:  Flow burst >= 15.0 lots in Delta t <= 0.50 seconds

Under stable, stationary market making conditions:
    - Order flow fluctuations are balanced and mean-reverting: |M_{OFI}| <= 0.40.
    - Buying and selling pressure offset continuously, keeping quotes stable.

During aggressive predatory sweeping, informed institutional flow, or sudden liquidity exhaustion:
    - Order flow becomes violently unidirectional, driving persistent adverse selection:
        1) Persistent OFI Momentum Bias:
           OFI momentum |M_{OFI}| >= MAX_OFI_MOMENTUM (default: 0.80)
           with total flow sum |OFI_i| >= MIN_TOTAL_FLOW (default: 12.0 lots)
           over rolling N >= MIN_SAMPLES (default: 12 book events).
        2) Acute OFI Surge Burst:
           Unidirectional net flow burst |OFI_{burst}| >= ACUTE_SURGE_FLOW (default: 15.0 lots)
           within Delta t <= ACUTE_SURGE_WINDOW_SEC (default: 0.50s).

Entering trades against high OFI momentum subjects market makers to severe adverse selection,
instantaneous queue evaporation, and high-probability quote jumps.

When OFI momentum bias or an acute flow surge is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests OFI flow via record_ofi(ofi_lots, ts=None) or
  direct metrics via record_ofi_metrics(ofi_momentum, total_flow=None, acute_surge=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 events.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, or Inf values are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_ofi(ofi_lots, ts=None)                                                                -> None
  record_ofi_metrics(ofi_momentum, total_flow=None, acute_surge=None, sample_count=None)        -> None
  update(ofi_lots, ts=None)                                                                    -> None   (alias)
  get_ofi_metrics()                                                                            -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave298LobOrderFlowToxicityMomentumGuard:
    """
    Guards against persistent LOB order flow imbalance momentum, toxic adverse selection, and queue collapse.
    """

    MAX_OFI_MOMENTUM: float = 0.80
    MIN_TOTAL_FLOW: float = 12.0
    MIN_SAMPLES: int = 12
    ACUTE_SURGE_FLOW: float = 15.0
    ACUTE_SURGE_WINDOW_SEC: float = 0.50
    WINDOW_SIZE: int = 20
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_ofi_momentum: float = MAX_OFI_MOMENTUM,
        min_total_flow: float = MIN_TOTAL_FLOW,
        min_samples: int = MIN_SAMPLES,
        acute_surge_flow: float = ACUTE_SURGE_FLOW,
        acute_surge_window_sec: float = ACUTE_SURGE_WINDOW_SEC,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_ofi_momentum = float(max_ofi_momentum)
        self.min_total_flow = float(min_total_flow)
        self.min_samples = int(min_samples)
        self.acute_surge_flow = float(acute_surge_flow)
        self.acute_surge_window_sec = float(acute_surge_window_sec)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._ofi_history = collections.deque(maxlen=self.window_size)
        self._burst_events = collections.deque()

        self._latest_ofi: float = 0.0
        self._latest_momentum: float = 0.0
        self._latest_total_flow: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _purge_old_bursts(self, now_ts: float) -> None:
        cutoff = now_ts - self.acute_surge_window_sec
        while self._burst_events and self._burst_events[0][0] < cutoff:
            self._burst_events.popleft()

    def _check_and_trigger_block(
        self,
        momentum: float,
        total_flow: float,
        burst_flow: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute OFI surge burst
        if abs(burst_flow) >= self.acute_surge_flow:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_OFI_SURGE_BURST: burst_flow={abs(burst_flow):.2f} >= {self.acute_surge_flow:.2f} lots "
                f"in dt <= {self.acute_surge_window_sec:.2f}s"
            )
            return True

        # 2. Persistent OFI momentum bias
        if (
            sample_count >= self.min_samples
            and abs(momentum) >= self.max_ofi_momentum
            and total_flow >= self.min_total_flow
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"OFI_MOMENTUM_BIAS: |M_OFI|={abs(momentum):.2f} >= {self.max_ofi_momentum:.2f}, "
                f"total_flow={total_flow:.2f} >= {self.min_total_flow:.2f} lots (N={sample_count})"
            )
            return True

        return False

    def record_ofi(self, ofi_lots: float, ts: Optional[float] = None) -> None:
        """
        Record instantaneous Order Flow Imbalance (OFI) event in lots.
        """
        with self._lock:
            if not self._is_valid_num(ofi_lots):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_OFI_INPUT"
                return

            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            flow = float(ofi_lots)
            self._latest_ofi = flow
            self._ofi_history.append(flow)
            self._sample_count += 1

            self._burst_events.append((now_ts, flow))
            self._purge_old_events = self._purge_old_bursts(now_ts)

            burst_flow = sum(f for t, f in self._burst_events)
            total_abs_flow = sum(abs(x) for x in self._ofi_history)
            net_flow = sum(self._ofi_history)
            momentum = net_flow / max(total_abs_flow, 0.10)

            self._latest_momentum = momentum
            self._latest_total_flow = total_abs_flow

            self._check_and_trigger_block(
                momentum,
                total_abs_flow,
                burst_flow,
                len(self._ofi_history),
            )

    def record_ofi_metrics(
        self,
        ofi_momentum: float,
        total_flow: Optional[float] = None,
        acute_surge: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed OFI momentum metrics.
        """
        with self._lock:
            if not self._is_valid_num(ofi_momentum) or abs(ofi_momentum) > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_MOMENTUM_METRIC"
                return

            m = float(ofi_momentum)
            tf = float(total_flow) if (self._is_valid_num(total_flow) and total_flow >= 0.0) else self.min_total_flow + 5.0
            asg = float(acute_surge) if self._is_valid_num(acute_surge) else 0.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_momentum = m
            self._latest_total_flow = tf
            self._sample_count = cnt

            self._check_and_trigger_block(
                m,
                tf,
                asg,
                cnt,
            )

    def update(self, ofi_lots: float, ts: Optional[float] = None) -> None:
        """Alias for record_ofi."""
        self.record_ofi(ofi_lots, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_ofi_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._ofi_history:
                total_abs = sum(abs(x) for x in self._ofi_history)
                net = sum(self._ofi_history)
                momentum = net / max(total_abs, 0.10)
            else:
                momentum = self._latest_momentum
                total_abs = self._latest_total_flow

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "ofi_momentum": float(momentum),
                "total_flow_lots": float(total_abs),
                "latest_ofi_lots": float(self._latest_ofi),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_ofi_metrics()

    def reset(self) -> None:
        with self._lock:
            self._ofi_history.clear()
            self._burst_events.clear()
            self._latest_ofi = 0.0
            self._latest_momentum = 0.0
            self._latest_total_flow = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
