"""
Wave 35: OvernightGuard
Force-close all positions 30 min before Friday market close (21:00 UTC)
and block new entries from Friday 20:30 UTC onwards to avoid weekend gap risk.
Also blocks entries during dangerous rollover window (21:45-22:15 UTC daily).
"""

from datetime import datetime, timezone


class OvernightGuard:
    """
    Prevents weekend gap exposure by:
    - Blocking new entries from Friday 20:30 UTC
    - Signalling force-close for ALL open positions from Friday 20:30 UTC
    - Blocking entries during daily rollover window 21:45-22:15 UTC
    """

    FRIDAY_BLOCK_HOUR = 20
    FRIDAY_BLOCK_MINUTE = 30
    MARKET_OPEN_DAY = 0       # Monday
    ROLLOVER_START_HOUR = 21
    ROLLOVER_START_MIN = 45
    ROLLOVER_END_HOUR = 22
    ROLLOVER_END_MIN = 15

    def __init__(self):
        self.friday_block_active = False
        self.rollover_block_active = False
        self.force_close_triggered = False
        self.total_weekend_blocks = 0
        self.total_rollover_blocks = 0
        self.total_force_closes = 0

    def _utc_now(self):
        return datetime.now(timezone.utc)

    def is_entry_blocked(self) -> bool:
        """
        Returns True if new entries should be blocked.
        Blocks during:
        - Friday >= 20:30 UTC (weekend gap risk)
        - Daily rollover 21:45-22:15 UTC
        """
        now = self._utc_now()
        weekday = now.weekday()  # 4=Friday, 5=Saturday, 6=Sunday
        hour = now.hour
        minute = now.minute

        # Saturday and Sunday - always block
        if weekday in (5, 6):
            self.friday_block_active = True
            self.total_weekend_blocks += 1
            return True

        # Friday from 20:30 UTC onwards
        if weekday == 4:
            if hour > self.FRIDAY_BLOCK_HOUR or (hour == self.FRIDAY_BLOCK_HOUR and minute >= self.FRIDAY_BLOCK_MINUTE):
                self.friday_block_active = True
                self.total_weekend_blocks += 1
                return True

        self.friday_block_active = False

        # Daily rollover window 21:45-22:15 UTC
        total_min = hour * 60 + minute
        rollover_start = self.ROLLOVER_START_HOUR * 60 + self.ROLLOVER_START_MIN  # 1305
        rollover_end = self.ROLLOVER_END_HOUR * 60 + self.ROLLOVER_END_MIN        # 1335
        if rollover_start <= total_min < rollover_end:
            self.rollover_block_active = True
            self.total_rollover_blocks += 1
            return True

        self.rollover_block_active = False
        return False

    def should_force_close_all(self) -> bool:
        """
        Returns True if ALL open positions should be force-closed.
        Triggers from Friday 20:30 UTC to avoid weekend gaps.
        """
        now = self._utc_now()
        weekday = now.weekday()
        hour = now.hour
        minute = now.minute

        if weekday in (5, 6):
            if not self.force_close_triggered:
                self.force_close_triggered = True
                self.total_force_closes += 1
            return True

        if weekday == 4:
            if hour > self.FRIDAY_BLOCK_HOUR or (hour == self.FRIDAY_BLOCK_HOUR and minute >= self.FRIDAY_BLOCK_MINUTE):
                if not self.force_close_triggered:
                    self.force_close_triggered = True
                    self.total_force_closes += 1
                return True

        # Reset trigger on Monday-Thursday
        self.force_close_triggered = False
        return False

    def get_reason(self) -> str:
        """Human-readable reason for current block."""
        if self.friday_block_active:
            return "FRIDAY_CLOSE_BLOCK: weekend gap risk"
        if self.rollover_block_active:
            return "ROLLOVER_BLOCK: 21:45-22:15 UTC daily rollover"
        return "CLEAR"

    def info(self) -> dict:
        return {
            "friday_block_hour_utc": self.FRIDAY_BLOCK_HOUR,
            "friday_block_minute_utc": self.FRIDAY_BLOCK_MINUTE,
            "rollover_window_utc": "21:45-22:15",
            "friday_block_active": self.friday_block_active,
            "rollover_block_active": self.rollover_block_active,
            "force_close_triggered": self.force_close_triggered,
            "total_weekend_blocks": self.total_weekend_blocks,
            "total_rollover_blocks": self.total_rollover_blocks,
            "total_force_closes": self.total_force_closes,
        }


# Module-level singleton
overnight_guard = OvernightGuard()
