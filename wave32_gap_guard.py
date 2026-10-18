"""
Wave 32: Gap Guard
Detects large price gaps between consecutive ticks and blocks trading
during the dangerous gap-fill zone.

Logic:
  - If |current_price - last_price| > gap_threshold_pips: trigger block
  - Block lasts block_duration_sec (default 120s) after gap detected
  - Log gap size and direction
"""

import math
import time
import logging
import threading
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

_DEFAULT_GAP_THRESHOLD_PIPS = 5.0
_DEFAULT_BLOCK_DURATION_SEC = 120.0
_DEFAULT_PIP_SIZE = 0.1


class GapGuard:
    """
    Detects abnormal tick-to-tick gaps and applies a temporary entry lockout.
    Thread-safe with RLock and supports deterministic timestamp injection.
    """

    def __init__(
        self,
        gap_threshold_pips: float = _DEFAULT_GAP_THRESHOLD_PIPS,
        block_duration_sec: float = _DEFAULT_BLOCK_DURATION_SEC,
        pip_size: float = _DEFAULT_PIP_SIZE,
    ):
        try:
            if isinstance(pip_size, bool):
                self._pip_size = _DEFAULT_PIP_SIZE
            else:
                ps = float(pip_size)
                self._pip_size = ps if math.isfinite(ps) and ps > 0 else _DEFAULT_PIP_SIZE
        except (ValueError, TypeError):
            self._pip_size = _DEFAULT_PIP_SIZE

        try:
            if isinstance(gap_threshold_pips, bool):
                self._gap_threshold_pips = _DEFAULT_GAP_THRESHOLD_PIPS
            else:
                gt = float(gap_threshold_pips)
                self._gap_threshold_pips = gt if math.isfinite(gt) and gt > 0 else _DEFAULT_GAP_THRESHOLD_PIPS
        except (ValueError, TypeError):
            self._gap_threshold_pips = _DEFAULT_GAP_THRESHOLD_PIPS

        self._gap_threshold = self._gap_threshold_pips * self._pip_size  # in price units

        try:
            if isinstance(block_duration_sec, bool):
                self._block_duration = _DEFAULT_BLOCK_DURATION_SEC
            else:
                bd = float(block_duration_sec)
                self._block_duration = bd if math.isfinite(bd) and bd >= 0 else _DEFAULT_BLOCK_DURATION_SEC
        except (ValueError, TypeError):
            self._block_duration = _DEFAULT_BLOCK_DURATION_SEC

        self._last_price: float = 0.0
        self._gap_detected_at: float = 0.0
        self._last_gap_pips: float = 0.0
        self._total_gaps: int = 0
        self._total_blocks: int = 0
        self._created_at: float = time.time()
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of gap state and counters."""
        with self._lock:
            self._last_price = 0.0
            self._gap_detected_at = 0.0
            self._last_gap_pips = 0.0
            self._total_gaps = 0
            self._total_blocks = 0

    def update_price(self, price: Any, now_ts: Optional[float] = None) -> None:
        """Feed latest tick. Triggers block if gap is detected."""
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
            if not math.isfinite(p) or p <= 0:
                return
        except (ValueError, TypeError):
            return

        current_time = float(now_ts) if (now_ts is not None and not isinstance(now_ts, bool)) else time.time()

        try:
            with self._lock:
                if self._last_price > 0:
                    gap_raw = abs(p - self._last_price)
                    if gap_raw >= self._gap_threshold:
                        self._gap_detected_at = current_time
                        self._last_gap_pips = round(gap_raw / self._pip_size, 1)
                        self._total_gaps += 1
                        self._total_blocks += 1
                        logger.warning(
                            f"[WAVE32] GAP detected: {self._last_gap_pips:.1f} pips — "
                            f"blocking for {self._block_duration}s"
                        )
                self._last_price = p
        except Exception as e:
            logger.debug(f"[WAVE32] update_price error: {e}")

    def update(self, price: Any, now_ts: Optional[float] = None) -> None:
        """Alias for update_price."""
        self.update_price(price, now_ts=now_ts)

    def is_trading_allowed(self, now_ts: Optional[float] = None) -> Tuple[bool, str]:
        """
        Returns (allowed: bool, reason: str).
        allowed=False means a gap was recently detected; avoid trading.
        """
        current_time = float(now_ts) if (now_ts is not None and not isinstance(now_ts, bool)) else time.time()
        with self._lock:
            if self._gap_detected_at == 0:
                return (True, "")
            elapsed = current_time - self._gap_detected_at
            if elapsed < self._block_duration:
                remaining = max(0.1, round(self._block_duration - elapsed, 1))
                return (False, f"GAP_GUARD: {self._last_gap_pips:.1f}p gap active ({remaining}s remaining)")
            return (True, "")

    def is_entry_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Returns True if trading is blocked due to recent gap."""
        allowed, _ = self.is_trading_allowed(now_ts=now_ts)
        return not allowed

    def is_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Standard alias for is_entry_blocked."""
        return self.is_entry_blocked(now_ts=now_ts)

    def info(self, now_ts: Optional[float] = None) -> dict:
        current_time = float(now_ts) if (now_ts is not None and not isinstance(now_ts, bool)) else time.time()
        with self._lock:
            if self._gap_detected_at == 0:
                allowed = True
                remaining = 0.0
            else:
                elapsed = current_time - self._gap_detected_at
                if elapsed < self._block_duration:
                    allowed = False
                    remaining = round(self._block_duration - elapsed, 1)
                else:
                    allowed = True
                    remaining = 0.0

            return {
                "wave": 32,
                "name": "GapGuard",
                "trading_allowed": allowed,
                "is_blocked": not allowed,
                "last_gap_pips": self._last_gap_pips,
                "gap_threshold_pips": self._gap_threshold_pips,
                "block_duration_sec": self._block_duration,
                "cooldown_remaining_sec": max(0.0, remaining),
                "total_gaps_detected": self._total_gaps,
                "total_blocks": self._total_blocks,
                "last_price": self._last_price,
            }


# Module-level singleton
gap_guard = GapGuard()


def is_entry_blocked(now_ts: Optional[float] = None) -> bool:
    """Module-level risk interface check."""
    return gap_guard.is_entry_blocked(now_ts=now_ts)


def is_blocked(now_ts: Optional[float] = None) -> bool:
    """Module-level alias for is_entry_blocked."""
    return gap_guard.is_blocked(now_ts=now_ts)


def is_trading_allowed(now_ts: Optional[float] = None) -> Tuple[bool, str]:
    """Module-level alias for is_trading_allowed."""
    return gap_guard.is_trading_allowed(now_ts=now_ts)


def update_price(price: Any, now_ts: Optional[float] = None) -> None:
    """Module-level alias for update_price."""
    return gap_guard.update_price(price=price, now_ts=now_ts)

