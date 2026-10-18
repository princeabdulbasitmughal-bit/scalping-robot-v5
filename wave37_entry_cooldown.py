"""
Wave 37: EntryCooldown
Enforce a mandatory cooldown period after any trade closes (win or loss)
to prevent revenge trading and overtrading in volatile markets.
"""

import math
import threading
import time


class EntryCooldown:
    """
    After any trade closes, blocks new entries for COOLDOWN_SECONDS.
    Configurable: different cooldowns for wins vs losses.
    """

    COOLDOWN_WIN_SEC = 60      # 60s cooldown after a winning trade
    COOLDOWN_LOSS_SEC = 120    # 120s cooldown after a losing trade (revenge prevention)

    def __init__(self):
        self._lock = threading.RLock()
        self._cooldown_until = 0.0
        self._last_cooldown_reason = "NONE"
        self.total_cooldowns_triggered = 0
        self.total_win_cooldowns = 0
        self.total_loss_cooldowns = 0
        self.last_trade_result = "NONE"

    def record_trade_close(self, was_win: bool, pnl: float = 0.0, now_ts: float = None):
        """
        Call after every trade closes.
        was_win: True if trade was profitable, False otherwise.
        pnl: trade profit/loss in USD (for logging).
        """
        clean_pnl = float(pnl) if isinstance(pnl, (int, float)) and not isinstance(pnl, bool) and math.isfinite(pnl) else 0.0
        now = now_ts if now_ts is not None else time.time()
        cooldown = self.COOLDOWN_WIN_SEC if was_win else self.COOLDOWN_LOSS_SEC

        with self._lock:
            self.last_trade_result = "WIN" if was_win else "LOSS"
            # FIX: use max() so a shorter new cooldown never truncates a longer active one
            self._cooldown_until = max(self._cooldown_until, now + cooldown)
            self._last_cooldown_reason = (
                f"{'WIN' if was_win else 'LOSS'} trade (PnL={clean_pnl:+.2f}): {cooldown}s cooldown"
            )
            self.total_cooldowns_triggered += 1
            if was_win:
                self.total_win_cooldowns += 1
            else:
                self.total_loss_cooldowns += 1

    def is_entry_blocked(self, now_ts: float = None) -> bool:
        """Returns True if in cooldown period — no new entries allowed."""
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return now < self._cooldown_until

    def is_blocked(self, now_ts: float = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(now_ts=now_ts)

    def seconds_remaining(self, now_ts: float = None) -> float:
        """Seconds until cooldown expires."""
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return max(0.0, self._cooldown_until - now)

    def force_reset(self):
        """Manually clear the cooldown (e.g. on daily reset)."""
        with self._lock:
            self._cooldown_until = 0.0
            self._last_cooldown_reason = "RESET"

    def reset(self):
        """Thread-safe reset clearing cooldown and counters."""
        with self._lock:
            self._cooldown_until = 0.0
            self._last_cooldown_reason = "RESET"
            self.total_cooldowns_triggered = 0
            self.total_win_cooldowns = 0
            self.total_loss_cooldowns = 0
            self.last_trade_result = "NONE"

    def info(self, now_ts: float = None) -> dict:
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return {
                "cooldown_win_sec": self.COOLDOWN_WIN_SEC,
                "cooldown_loss_sec": self.COOLDOWN_LOSS_SEC,
                "currently_blocked": now < self._cooldown_until,
                "seconds_remaining": round(max(0.0, self._cooldown_until - now), 1),
                "last_trade_result": self.last_trade_result,
                "last_cooldown_reason": self._last_cooldown_reason,
                "total_cooldowns_triggered": self.total_cooldowns_triggered,
                "total_win_cooldowns": self.total_win_cooldowns,
                "total_loss_cooldowns": self.total_loss_cooldowns,
            }


# Module-level singleton
entry_cooldown = EntryCooldown()


def is_entry_blocked(now_ts: float = None) -> bool:
    """Module-level risk interface check."""
    return entry_cooldown.is_entry_blocked(now_ts=now_ts)


def is_blocked(now_ts: float = None) -> bool:
    """Module-level alias for is_entry_blocked."""
    return entry_cooldown.is_blocked(now_ts=now_ts)


def record_trade_close(was_win: bool, pnl: float = 0.0, now_ts: float = None) -> None:
    """Module-level alias for record_trade_close."""
    return entry_cooldown.record_trade_close(was_win=was_win, pnl=pnl, now_ts=now_ts)

