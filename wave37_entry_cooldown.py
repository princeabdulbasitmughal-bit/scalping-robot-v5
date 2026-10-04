"""
Wave 37: EntryCooldown
Enforce a mandatory cooldown period after any trade closes (win or loss)
to prevent revenge trading and overtrading in volatile markets.
"""

import time


class EntryCooldown:
    """
    After any trade closes, blocks new entries for COOLDOWN_SECONDS.
    Configurable: different cooldowns for wins vs losses.
    """

    COOLDOWN_WIN_SEC = 60      # 60s cooldown after a winning trade
    COOLDOWN_LOSS_SEC = 120    # 120s cooldown after a losing trade (revenge prevention)

    def __init__(self):
        self._cooldown_until = 0.0
        self._last_cooldown_reason = "NONE"
        self.total_cooldowns_triggered = 0
        self.total_win_cooldowns = 0
        self.total_loss_cooldowns = 0
        self.last_trade_result = "NONE"

    def record_trade_close(self, was_win: bool, pnl: float = 0.0):
        """
        Call after every trade closes.
        was_win: True if trade was profitable, False otherwise.
        pnl: trade profit/loss in USD (for logging).
        """
        self.last_trade_result = "WIN" if was_win else "LOSS"
        cooldown = self.COOLDOWN_WIN_SEC if was_win else self.COOLDOWN_LOSS_SEC
        self._cooldown_until = time.time() + cooldown
        self._last_cooldown_reason = (
            f"{'WIN' if was_win else 'LOSS'} trade (PnL={pnl:+.2f}): {cooldown}s cooldown"
        )
        self.total_cooldowns_triggered += 1
        if was_win:
            self.total_win_cooldowns += 1
        else:
            self.total_loss_cooldowns += 1

    def is_entry_blocked(self) -> bool:
        """Returns True if in cooldown period — no new entries allowed."""
        return time.time() < self._cooldown_until

    def seconds_remaining(self) -> float:
        """Seconds until cooldown expires."""
        return max(0.0, self._cooldown_until - time.time())

    def force_reset(self):
        """Manually clear the cooldown (e.g. on daily reset)."""
        self._cooldown_until = 0.0
        self._last_cooldown_reason = "RESET"

    def info(self) -> dict:
        return {
            "cooldown_win_sec": self.COOLDOWN_WIN_SEC,
            "cooldown_loss_sec": self.COOLDOWN_LOSS_SEC,
            "currently_blocked": self.is_entry_blocked(),
            "seconds_remaining": round(self.seconds_remaining(), 1),
            "last_trade_result": self.last_trade_result,
            "last_cooldown_reason": self._last_cooldown_reason,
            "total_cooldowns_triggered": self.total_cooldowns_triggered,
            "total_win_cooldowns": self.total_win_cooldowns,
            "total_loss_cooldowns": self.total_loss_cooldowns,
        }


# Module-level singleton
entry_cooldown = EntryCooldown()
