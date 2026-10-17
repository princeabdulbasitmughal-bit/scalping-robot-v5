"""
Wave 35: OvernightGuard
Force-close all positions 30 min before Friday market close (21:00 UTC)
and block new entries from Friday 20:30 UTC onwards to avoid weekend gap risk.
Also blocks entries during dangerous rollover window (21:45-22:15 UTC daily).
"""

import threading
import logging
from typing import Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class OvernightGuard:
    """
    Prevents weekend gap exposure by:
    - Blocking new entries from Friday 20:30 UTC
    - Signalling force-close for ALL open positions from Friday 20:30 UTC
    - Blocking entries during daily rollover window 21:45-22:15 UTC
    Thread-safe with RLock and supports deterministic datetime injection.
    """

    FRIDAY_BLOCK_HOUR = 20
    FRIDAY_BLOCK_MINUTE = 30
    MARKET_OPEN_DAY = 0       # Monday
    ROLLOVER_START_HOUR = 21
    ROLLOVER_START_MIN = 45
    ROLLOVER_END_HOUR = 22
    ROLLOVER_END_MIN = 15

    def __init__(self):
        self._lock = threading.RLock()
        self.friday_block_active = False
        self.rollover_block_active = False
        self.force_close_triggered = False
        self.total_weekend_blocks = 0
        self.total_rollover_blocks = 0
        self.total_force_closes = 0

    def reset(self) -> None:
        """Thread-safe reset of guard states and counters."""
        with self._lock:
            self.friday_block_active = False
            self.rollover_block_active = False
            self.force_close_triggered = False
            self.total_weekend_blocks = 0
            self.total_rollover_blocks = 0
            self.total_force_closes = 0

    def _utc_now(self, now_dt: Optional[datetime] = None) -> datetime:
        if now_dt is not None:
            return now_dt.astimezone(timezone.utc) if now_dt.tzinfo else now_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    def is_entry_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """
        Returns True if new entries should be blocked.
        Blocks during:
        - Friday >= 20:30 UTC (weekend gap risk)
        - Saturday and Sunday (markets closed)
        - Daily rollover 21:45-22:15 UTC
        """
        with self._lock:
            now = self._utc_now(now_dt)
            weekday = now.weekday()  # 4=Friday, 5=Saturday, 6=Sunday
            hour = now.hour
            minute = now.minute

            # Saturday and Sunday - always block
            if weekday in (5, 6):
                if not self.friday_block_active:
                    self.total_weekend_blocks += 1
                self.friday_block_active = True
                return True

            # Friday from 20:30 UTC onwards
            if weekday == 4:
                if hour > self.FRIDAY_BLOCK_HOUR or (hour == self.FRIDAY_BLOCK_HOUR and minute >= self.FRIDAY_BLOCK_MINUTE):
                    if not self.friday_block_active:
                        self.total_weekend_blocks += 1
                    self.friday_block_active = True
                    return True

            self.friday_block_active = False

            # Daily rollover window 21:45-22:15 UTC
            total_min = hour * 60 + minute
            rollover_start = self.ROLLOVER_START_HOUR * 60 + self.ROLLOVER_START_MIN  # 1305
            rollover_end = self.ROLLOVER_END_HOUR * 60 + self.ROLLOVER_END_MIN        # 1335
            if rollover_start <= total_min < rollover_end:
                if not self.rollover_block_active:
                    self.total_rollover_blocks += 1
                self.rollover_block_active = True
                return True

            self.rollover_block_active = False
            return False

    def is_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """Standard alias for is_entry_blocked."""
        return self.is_entry_blocked(now_dt=now_dt)

    def is_trading_allowed(self, now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """Returns (True, '') if clear, (False, reason) if blocked."""
        with self._lock:
            blocked = self.is_entry_blocked(now_dt=now_dt)
            if blocked:
                if self.friday_block_active:
                    return False, "OVERNIGHT_GUARD: weekend holding protection active"
                if self.rollover_block_active:
                    return False, "OVERNIGHT_GUARD: daily rollover window active (21:45-22:15 UTC)"
                return False, "OVERNIGHT_GUARD: trading blocked"
            return True, ""

    def get_reason(self, now_dt: Optional[datetime] = None) -> str:
        """Human-readable reason for current block."""
        with self._lock:
            self.is_entry_blocked(now_dt=now_dt)
            if self.friday_block_active:
                return "FRIDAY_CLOSE_BLOCK: weekend gap risk"
            if self.rollover_block_active:
                return "ROLLOVER_BLOCK: 21:45-22:15 UTC daily rollover"
            return "CLEAR"

    def should_force_close_all(self, now_dt: Optional[datetime] = None) -> bool:
        """
        Returns True if ALL open positions should be force-closed.
        Triggers from Friday 20:30 UTC to avoid weekend gaps.
        """
        with self._lock:
            now = self._utc_now(now_dt)
            weekday = now.weekday()
            hour = now.hour
            minute = now.minute

            if weekday == 4:
                if hour > self.FRIDAY_BLOCK_HOUR or (hour == self.FRIDAY_BLOCK_HOUR and minute >= self.FRIDAY_BLOCK_MINUTE):
                    if not self.force_close_triggered:
                        self.total_force_closes += 1
                        self.force_close_triggered = True
                        logger.warning(
                            f"[WAVE35] Weekend force-close triggered at {now.strftime('%H:%M')} UTC. "
                            f"Closing all open positions."
                        )
                    return True

            # Reset trigger on other days
            self.force_close_triggered = False
            return False

    def info(self, now_dt: Optional[datetime] = None) -> dict:
        with self._lock:
            blocked = self.is_entry_blocked(now_dt=now_dt)
            return {
                "wave": 35,
                "name": "OvernightGuard",
                "friday_block_active": self.friday_block_active,
                "rollover_block_active": self.rollover_block_active,
                "force_close_active": self.should_force_close_all(now_dt=now_dt),
                "is_blocked": blocked,
                "total_weekend_blocks": self.total_weekend_blocks,
                "total_rollover_blocks": self.total_rollover_blocks,
                "total_force_closes": self.total_force_closes,
            }


# Module-level singleton
overnight_guard = OvernightGuard()
