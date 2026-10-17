"""
Wave 55: Balance Floor Guard
Halts ALL trading when account balance drops below a configurable floor.
Trading resumes at the start of the next UTC day or when balance recovers
above floor + hysteresis.

Default floor: $9,500 (configurable).
Recovery: auto-unlocks at midnight UTC or when balance rises above floor + $50 hysteresis.
"""

import math
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

BALANCE_FLOOR_USD    = 9_500.0   # Halt when balance drops below this
HYSTERESIS_USD       = 50.0      # Must rise this much above floor to auto-recover intraday


class BalanceFloorGuard:
    """
    Hard balance floor protection.
    When balance < floor or balance <= 0, all trading is halted immediately
    and stays halted until the next UTC day or balance recovers above floor + hysteresis.
    Thread-safe with RLock and supports deterministic datetime injection.
    """

    def __init__(
        self,
        floor_usd: Optional[float] = None,
        hysteresis_usd: float = HYSTERESIS_USD,
        min_balance: Optional[float] = None,
        **kwargs,
    ):
        raw_floor = min_balance if min_balance is not None else floor_usd
        if raw_floor is None and "min_balance_usd" in kwargs:
            raw_floor = kwargs["min_balance_usd"]

        try:
            self._floor = float(raw_floor) if raw_floor is not None and math.isfinite(float(raw_floor)) else BALANCE_FLOOR_USD
        except (ValueError, TypeError):
            self._floor = BALANCE_FLOOR_USD

        try:
            self._hysteresis = float(hysteresis_usd) if math.isfinite(float(hysteresis_usd)) and float(hysteresis_usd) >= 0 else HYSTERESIS_USD
        except (ValueError, TypeError):
            self._hysteresis = HYSTERESIS_USD

        self._current_balance: float = 0.0
        self._is_halted: bool = False
        self._halt_triggered_at: float = 0.0
        self._halt_balance: float = 0.0
        self._halt_day: str = ""        # UTC date string when halt triggered
        self._halt_count: int = 0
        self._update_count: int = 0
        self._created_at = time.time()
        self._lock = threading.RLock()

    @property
    def floor_usd(self) -> float:
        with self._lock:
            return self._floor

    @property
    def min_balance(self) -> float:
        with self._lock:
            return self._floor

    @property
    def current_balance(self) -> float:
        with self._lock:
            return self._current_balance

    @property
    def is_halted(self) -> bool:
        with self._lock:
            return self._is_halted

    def reset(self) -> None:
        """Thread-safe reset of runtime state."""
        with self._lock:
            self._current_balance = 0.0
            self._is_halted = False
            self._halt_triggered_at = 0.0
            self._halt_balance = 0.0
            self._halt_day = ""
            self._halt_count = 0
            self._update_count = 0

    def _today_utc(self, now_dt: Optional[datetime] = None) -> str:
        if now_dt is None:
            dt = datetime.now(timezone.utc)
        elif now_dt.tzinfo is None:
            dt = now_dt.replace(tzinfo=timezone.utc)
        else:
            dt = now_dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d")

    def update(self, balance: Any, now_dt: Optional[datetime] = None) -> None:
        """
        Feed the current account balance.
        Call every tick with self.balance.
        """
        if balance is None or isinstance(balance, bool):
            return
        try:
            bal = float(balance)
            if not math.isfinite(bal):
                return
        except (ValueError, TypeError):
            return

        try:
            with self._lock:
                self._current_balance = bal
                self._update_count += 1
                today = self._today_utc(now_dt)

                # Negative balance or zero: catastrophic halt
                if bal <= 0.0:
                    self._is_halted = True
                    self._halt_triggered_at = time.time()
                    self._halt_balance = bal
                    self._halt_day = today
                    self._halt_count += 1
                    logger.critical(
                        f"[W55-BalanceFloor] CATASTROPHIC BALANCE BLOWOUT — balance ${bal:.2f} <= 0.0! TRADING HALTED"
                    )
                    return

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

    def is_entry_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """Return True if trading should be halted due to balance floor breach."""
        try:
            with self._lock:
                if now_dt is not None and self._is_halted:
                    # Check if new UTC day lifts halt
                    today = self._today_utc(now_dt)
                    if today != self._halt_day and self._current_balance >= self._floor:
                        self._is_halted = False
                        return False

                if self._is_halted:
                    logger.debug(
                        f"[W55-BalanceFloor] Entry BLOCKED — balance ${self._current_balance:.2f} "
                        f"below floor ${self._floor:.2f}"
                    )
                    return True
                return False
        except Exception as e:
            logger.error(f"[W55-BalanceFloor] is_entry_blocked error: {e}")
            return True  # fail-closed

    def is_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """Standard alias for is_entry_blocked."""
        return self.is_entry_blocked(now_dt=now_dt)

    def is_trading_allowed(self, now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """Returns (True, '') if clear or (False, reason) if halted."""
        blocked = self.is_entry_blocked(now_dt=now_dt)
        if blocked:
            with self._lock:
                return False, f"BALANCE_FLOOR: balance ${self._current_balance:.2f} < floor ${self._floor:.2f}"
        return True, ""

    def info(self) -> dict:
        """Return serializable status dict for live_status.json."""
        try:
            with self._lock:
                halted_for = 0.0
                if self._is_halted and self._halt_triggered_at > 0:
                    halted_for = round(time.time() - self._halt_triggered_at, 1)
                return {
                    "wave": 55,
                    "name": "BalanceFloorGuard",
                    "floor_usd": self._floor,
                    "min_balance": self._floor,
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
            return {"wave": 55, "name": "BalanceFloorGuard", "error": "info_failed"}


# Module-level singleton
balance_floor_guard = BalanceFloorGuard()
