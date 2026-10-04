"""
Wave 55: Balance Floor Guard
Halts ALL trading when account balance drops below a configurable floor.
Trading resumes at the start of the next UTC day.

Default floor: $9,500 (configurable).
Recovery: auto-unlocks at midnight UTC or when balance rises above floor + $50 hysteresis.
"""

import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BALANCE_FLOOR_USD    = 9_500.0   # Halt when balance drops below this
HYSTERESIS_USD       = 50.0      # Must rise this much above floor to auto-recover intraday


class BalanceFloorGuard:
    """
    Hard balance floor protection.
    When balance < floor, all trading is halted immediately and stays halted
    until the next UTC day or balance recovers above floor + hysteresis.
    """

    def __init__(
        self,
        floor_usd: float = BALANCE_FLOOR_USD,
        hysteresis_usd: float = HYSTERESIS_USD,
    ):
        self._floor = floor_usd
        self._hysteresis = hysteresis_usd
        self._current_balance: float = 0.0
        self._is_halted: bool = False
        self._halt_triggered_at: float = 0.0
        self._halt_balance: float = 0.0
        self._halt_day: str = ""        # UTC date string when halt triggered
        self._halt_count: int = 0
        self._update_count: int = 0
        self._created_at = time.time()

    def _today_utc(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def update(self, balance: float):
        """
        Feed the current account balance.
        Call every tick with self.balance.
        """
        try:
            self._current_balance = float(balance)
            self._update_count += 1

            today = self._today_utc()

            # Check if halt should be triggered
            if not self._is_halted and self._current_balance < self._floor:
                self._is_halted = True
                self._halt_triggered_at = time.time()
                self._halt_balance = self._current_balance
                self._halt_day = today
                self._halt_count += 1
                logger.warning(
                    f"[W55-BalanceFloor] TRADING HALTED — balance ${self._current_balance:.2f} "
                    f"< floor ${self._floor:.2f}"
                )
                return

            # Check if halt should be lifted
            if self._is_halted:
                # Auto-recover at new UTC day
                if today != self._halt_day:
                    self._is_halted = False
                    logger.info(
                        f"[W55-BalanceFloor] Halt lifted — new UTC day ({today}). "
                        f"Balance: ${self._current_balance:.2f}"
                    )
                    return

                # Intraday recovery above floor + hysteresis
                if self._current_balance >= self._floor + self._hysteresis:
                    self._is_halted = False
                    logger.info(
                        f"[W55-BalanceFloor] Halt lifted — balance recovered to "
                        f"${self._current_balance:.2f} (floor + hysteresis: "
                        f"${self._floor + self._hysteresis:.2f})"
                    )
                    return

                logger.debug(
                    f"[W55-BalanceFloor] Still HALTED — balance ${self._current_balance:.2f} "
                    f"(need ${self._floor + self._hysteresis:.2f} to recover)"
                )

        except Exception as e:
            logger.debug(f"[W55-BalanceFloor] update error: {e}")

    def is_entry_blocked(self) -> bool:
        """Return True if trading should be halted due to balance floor breach."""
        try:
            if self._is_halted:
                logger.debug(
                    f"[W55-BalanceFloor] Entry BLOCKED — balance ${self._current_balance:.2f} "
                    f"below floor ${self._floor:.2f}"
                )
                return True
            return False
        except Exception as e:
            logger.debug(f"[W55-BalanceFloor] is_entry_blocked error: {e}")
            return False

    def info(self) -> dict:
        """Return serializable status dict for live_status.json."""
        try:
            halted_for = 0.0
            if self._is_halted and self._halt_triggered_at > 0:
                halted_for = round(time.time() - self._halt_triggered_at, 1)
            return {
                "floor_usd": self._floor,
                "hysteresis_usd": self._hysteresis,
                "current_balance": round(self._current_balance, 2),
                "is_halted": self._is_halted,
                "halt_count": self._halt_count,
                "halt_balance": round(self._halt_balance, 2),
                "halt_day_utc": self._halt_day,
                "halted_for_sec": halted_for,
                "update_count": self._update_count,
            }
        except Exception:
            return {}


# Module-level singleton
balance_floor_guard = BalanceFloorGuard()
