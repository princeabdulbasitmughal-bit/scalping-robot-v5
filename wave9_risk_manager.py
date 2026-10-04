"""
Wave 9: Advanced Risk Manager
Features:
  - Equity curve filter (stop trading when equity < 20-period EMA of equity)
  - Max drawdown guard with tiered response
  - Position correlation checker (don't stack same-direction positions)
  - Dynamic daily P&L scaling (reduce lot size as daily loss grows)
  - Trade frequency governor (max trades per time window)
  - Profit lock (reduce position size after hitting 50% of daily target)
"""
import time
import collections
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime


class RiskManager:

    def __init__(self, config: Optional[Dict] = None):
        cfg = config or {}
        self.max_daily_loss_usd = float(cfg.get("max_daily_loss_usd", 200.0))
        self.daily_profit_target = float(cfg.get("daily_profit_target_usd", 200.0))
        self.max_drawdown_pct = float(cfg.get("max_drawdown_pct", 10.0))
        self.peak_balance = float(cfg.get("starting_balance", 10000.0))

        # Equity curve EMA
        self._equity_history: collections.deque = collections.deque(maxlen=20)
        self._equity_ema: float = 0.0
        self._eq_alpha: float = 2.0 / 21.0

        # Trade frequency governor
        self._trade_times: collections.deque = collections.deque(maxlen=50)
        self.max_trades_per_hour = int(cfg.get("max_trades_per_hour", 20))

        # Cooldown state
        self._soft_halt_until: float = 0.0  # epoch time
        self._hard_halt: bool = False

        # Session P&L log
        self._session_pnl_log: List[float] = []

    # ── Equity Curve EMA Update ──────────────────────────────────────────────
    def update_equity(self, equity: float):
        """Call every tick. Updates EMA of equity for curve filter."""
        self._equity_history.append(equity)
        if self._equity_ema == 0.0:
            self._equity_ema = equity
        else:
            self._equity_ema = equity * self._eq_alpha + self._equity_ema * (1 - self._eq_alpha)
        if equity > self.peak_balance:
            self.peak_balance = equity

    def equity_curve_ok(self, equity: float) -> bool:
        """Return False if equity dropped below its 20-period EMA — stop trading."""
        if len(self._equity_history) < 5:
            return True  # not enough data yet
        return equity >= self._equity_ema * 0.995  # 0.5% tolerance band

    # ── Drawdown Guard ────────────────────────────────────────────────────────
    def drawdown_pct(self, balance: float) -> float:
        if self.peak_balance <= 0:
            return 0.0
        return round((self.peak_balance - balance) / self.peak_balance * 100, 2)

    def drawdown_lot_scale(self, balance: float) -> float:
        """Return lot multiplier based on drawdown tier."""
        dd = self.drawdown_pct(balance)
        if dd >= 8.0:
            return 0.1   # severe — micro lots only
        elif dd >= 6.0:
            return 0.25
        elif dd >= 4.0:
            return 0.5
        elif dd >= 2.0:
            return 0.75
        return 1.0

    def is_max_drawdown_hit(self, balance: float) -> bool:
        return self.drawdown_pct(balance) >= self.max_drawdown_pct

    # ── Position Correlation ─────────────────────────────────────────────────
    def correlation_ok(self, open_positions: List[Dict], new_signal: str) -> bool:
        """
        Prevent stacking more than 1 position in same direction.
        Returns True if adding new_signal direction is acceptable.
        """
        same_dir = sum(1 for p in open_positions if p.get("type") == new_signal)
        return same_dir < 1  # Allow max 1 position per direction

    # ── Trade Frequency Governor ──────────────────────────────────────────────
    def can_trade_frequency(self) -> bool:
        """Enforce max trades per hour sliding window."""
        now = time.time()
        # Remove trades older than 1 hour
        while self._trade_times and now - self._trade_times[0] > 3600:
            self._trade_times.popleft()
        return len(self._trade_times) < self.max_trades_per_hour

    def record_trade(self):
        self._trade_times.append(time.time())

    # ── Daily P&L Scaling ────────────────────────────────────────────────────
    def daily_loss_lot_scale(self, daily_loss: float) -> float:
        """Reduce lot size as daily loss accumulates."""
        loss_ratio = daily_loss / self.max_daily_loss_usd if self.max_daily_loss_usd > 0 else 0
        if loss_ratio >= 0.75:
            return 0.25  # 75% of daily limit used
        elif loss_ratio >= 0.50:
            return 0.5
        elif loss_ratio >= 0.25:
            return 0.75
        return 1.0

    def profit_lock_lot_scale(self, daily_pnl: float) -> float:
        """After 50% of daily target hit → reduce to 50% lot size (lock profit)."""
        if daily_pnl >= self.daily_profit_target * 0.5:
            return 0.5
        return 1.0

    # ── Composite Risk Gate ───────────────────────────────────────────────────
    def should_trade(
        self,
        balance: float,
        equity: float,
        daily_pnl: float,
        daily_loss: float,
        open_positions: List[Dict],
        new_signal: str,
    ) -> Dict[str, Any]:
        """
        Master risk gate. Returns:
        {
          "allowed": bool,
          "reason": str,
          "lot_scale": float (1.0 = full size, 0.5 = half, etc.)
        }
        """
        self.update_equity(equity)

        # Hard halt checks
        if self._hard_halt or self.is_max_drawdown_hit(balance):
            return {"allowed": False, "reason": f"MAX_DRAWDOWN_HIT ({self.drawdown_pct(balance):.1f}%)", "lot_scale": 0.0}

        if not self.can_trade_frequency():
            return {"allowed": False, "reason": "TRADE_FREQUENCY_LIMIT", "lot_scale": 0.0}

        if not self.equity_curve_ok(equity):
            return {"allowed": False, "reason": f"EQUITY_BELOW_EMA ({equity:.0f}<{self._equity_ema:.0f})", "lot_scale": 0.0}

        if not self.correlation_ok(open_positions, new_signal):
            return {"allowed": False, "reason": f"CORRELATION_BLOCK ({new_signal} already open)", "lot_scale": 0.0}

        # Soft halt
        if time.time() < self._soft_halt_until:
            rem = int(self._soft_halt_until - time.time())
            return {"allowed": False, "reason": f"SOFT_HALT ({rem}s remaining)", "lot_scale": 0.0}

        # Compute lot scale multiplier
        lot_scale = 1.0
        lot_scale *= self.drawdown_lot_scale(balance)
        lot_scale *= self.daily_loss_lot_scale(daily_loss)
        lot_scale *= self.profit_lock_lot_scale(daily_pnl)
        lot_scale = round(max(0.1, min(1.0, lot_scale)), 2)

        return {"allowed": True, "reason": "OK", "lot_scale": lot_scale}

    # ── Persist risk state ────────────────────────────────────────────────────
    def save_state(self, path: str = r"E:\scalping-robot-v5\risk_state.json"):
        try:
            state = {
                "peak_balance": self.peak_balance,
                "equity_ema": round(self._equity_ema, 2),
                "hard_halt": self._hard_halt,
                "soft_halt_until": self._soft_halt_until,
                "updated_at": datetime.utcnow().isoformat() + "Z"
            }
            with open(path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def load_state(self, path: str = r"E:\scalping-robot-v5\risk_state.json"):
        try:
            if os.path.exists(path):
                with open(path) as f:
                    state = json.load(f)
                self.peak_balance = float(state.get("peak_balance", self.peak_balance))
                self._equity_ema = float(state.get("equity_ema", 0.0))
                self._hard_halt = bool(state.get("hard_halt", False))
                self._soft_halt_until = float(state.get("soft_halt_until", 0.0))
        except Exception:
            pass

    def streak_lot_modifier(self) -> float:
        """Returns multiplier for current win/loss streak."""
        return 1.0

    def record_result(self, won: bool) -> None:
        """Record trade win/loss for session stats."""
        self._session_pnl_log.append(1.0 if won else -1.0)

    def is_recovery_mode(self) -> bool:
        """Returns True if currently in drawdown recovery mode."""
        return self._hard_halt

    def session_stats(self) -> Dict[str, Any]:
        """Returns dictionary of current session statistics."""
        return {
            "peak_balance": self.peak_balance,
            "equity_ema": self._equity_ema,
            "hard_halt": self._hard_halt,
            "total_trades": len(self._session_pnl_log),
        }

# ── Module-level singleton ─────────────────────────────────────────────────
risk_manager = RiskManager()
risk_manager.load_state()
