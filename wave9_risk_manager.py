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
import math
import time
import collections
import json
import logging
import os
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


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

        # Session P&L log — bounded to prevent unbounded growth
        self._session_pnl_log: collections.deque = collections.deque(maxlen=1000)

        self._lock = threading.RLock()

    # ── Equity Curve EMA Update ──────────────────────────────────────────────
    def update_equity(self, equity: float):
        """Call every tick. Updates EMA of equity for curve filter."""
        try:
            if equity is None or isinstance(equity, bool):
                return
            equity = float(equity)
            if not math.isfinite(equity) or equity <= 0:
                return
            with self._lock:
                self._equity_history.append(equity)
                if self._equity_ema == 0.0:
                    self._equity_ema = equity
                else:
                    self._equity_ema = equity * self._eq_alpha + self._equity_ema * (1 - self._eq_alpha)
                if equity > self.peak_balance:
                    self.peak_balance = equity
        except Exception as e:
            logger.error(f"[W9-Risk] update_equity error: {e}")

    def equity_curve_ok(self, equity: float) -> bool:
        """Return False if equity dropped below its 20-period EMA — stop trading."""
        if equity is None or isinstance(equity, bool):
            return False
        try:
            eq = float(equity)
            if not math.isfinite(eq) or eq <= 0:
                return False
        except (ValueError, TypeError):
            return False
        with self._lock:
            if len(self._equity_history) < 5:
                return True  # not enough data yet
            return eq >= self._equity_ema * 0.995  # 0.5% tolerance band

    # ── Drawdown Guard ────────────────────────────────────────────────────────
    def drawdown_pct(self, balance: float) -> float:
        with self._lock:
            if balance is None or isinstance(balance, bool):
                return 100.0
            try:
                b = float(balance)
                if not math.isfinite(b) or b <= 0:
                    return 100.0
            except (ValueError, TypeError):
                return 100.0
            if self.peak_balance <= 0:
                return 0.0
            return round((self.peak_balance - b) / self.peak_balance * 100.0, 2)

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
        if not open_positions or not isinstance(open_positions, (list, tuple)):
            return True
        same_dir = sum(1 for p in open_positions if isinstance(p, dict) and p.get("type") == new_signal)
        return same_dir < 1  # Allow max 1 position per direction

    # ── Trade Frequency Governor ──────────────────────────────────────────────
    def can_trade_frequency(self, now_ts: Optional[float] = None) -> bool:
        """Enforce max trades per hour sliding window."""
        now = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            # Remove trades older than 1 hour
            while self._trade_times and now - self._trade_times[0] > 3600:
                self._trade_times.popleft()
            return len(self._trade_times) < self.max_trades_per_hour

    def record_trade(self, now_ts: Optional[float] = None):
        now = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            self._trade_times.append(now)

    # ── Daily P&L Scaling ────────────────────────────────────────────────────
    def daily_loss_lot_scale(self, daily_loss: float) -> float:
        """Reduce lot size as daily loss accumulates."""
        if daily_loss is None or isinstance(daily_loss, bool):
            return 1.0
        try:
            loss = float(daily_loss)
            if not math.isfinite(loss) or loss <= 0:
                return 1.0
        except (ValueError, TypeError):
            return 1.0
        loss_ratio = loss / self.max_daily_loss_usd if self.max_daily_loss_usd > 0 else 0
        if loss_ratio >= 0.75:
            return 0.25  # 75% of daily limit used
        elif loss_ratio >= 0.50:
            return 0.5
        elif loss_ratio >= 0.25:
            return 0.75
        return 1.0

    def profit_lock_lot_scale(self, daily_pnl: float) -> float:
        """After 50% of daily target hit → reduce to 50% lot size (lock profit)."""
        if daily_pnl is None or isinstance(daily_pnl, bool):
            return 1.0
        try:
            pnl = float(daily_pnl)
            if not math.isfinite(pnl):
                return 1.0
        except (ValueError, TypeError):
            return 1.0
        if pnl >= self.daily_profit_target * 0.5:
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
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Master risk gate. Returns:
        {
          "allowed": bool,
          "reason": str,
          "lot_scale": float (1.0 = full size, 0.5 = half, etc.)
        }
        """
        if balance is None or isinstance(balance, bool):
            return {"allowed": False, "reason": "INVALID_BALANCE", "lot_scale": 0.0}
        try:
            b = float(balance)
            if not math.isfinite(b) or b <= 0:
                return {"allowed": False, "reason": "INVALID_BALANCE", "lot_scale": 0.0}
        except (ValueError, TypeError):
            return {"allowed": False, "reason": "INVALID_BALANCE", "lot_scale": 0.0}

        if equity is None or isinstance(equity, bool):
            return {"allowed": False, "reason": "INVALID_EQUITY", "lot_scale": 0.0}
        try:
            eq = float(equity)
            if not math.isfinite(eq) or eq <= 0:
                return {"allowed": False, "reason": "INVALID_EQUITY", "lot_scale": 0.0}
        except (ValueError, TypeError):
            return {"allowed": False, "reason": "INVALID_EQUITY", "lot_scale": 0.0}

        now = time.time() if now_ts is None else float(now_ts)
        self.update_equity(eq)

        # Hard halt checks
        if self._hard_halt or self.is_max_drawdown_hit(b):
            return {"allowed": False, "reason": f"MAX_DRAWDOWN_HIT ({self.drawdown_pct(b):.1f}%)", "lot_scale": 0.0}

        if not self.can_trade_frequency(now_ts=now):
            return {"allowed": False, "reason": "TRADE_FREQUENCY_LIMIT", "lot_scale": 0.0}

        if not self.equity_curve_ok(eq):
            return {"allowed": False, "reason": f"EQUITY_BELOW_EMA ({eq:.0f}<{self._equity_ema:.0f})", "lot_scale": 0.0}

        if not self.correlation_ok(open_positions, new_signal):
            return {"allowed": False, "reason": f"CORRELATION_BLOCK ({new_signal} already open)", "lot_scale": 0.0}

        # Daily loss limit hard gate
        if daily_loss is not None and isinstance(daily_loss, (int, float)) and daily_loss >= self.max_daily_loss_usd:
            return {"allowed": False, "reason": f"Daily loss limit reached ({daily_loss:.1f}>={self.max_daily_loss_usd:.1f})", "lot_scale": 0.0}

        # Soft halt
        if now < self._soft_halt_until:
            rem = max(0, int(self._soft_halt_until - now))
            return {"allowed": False, "reason": f"SOFT_HALT ({rem}s remaining)", "lot_scale": 0.0}

        # Compute lot scale multiplier
        lot_scale = 1.0
        lot_scale *= self.drawdown_lot_scale(b)
        lot_scale *= self.daily_loss_lot_scale(daily_loss)
        lot_scale *= self.profit_lock_lot_scale(daily_pnl)
        lot_scale = round(max(0.1, min(1.0, lot_scale)), 2)

        return {"allowed": True, "reason": "OK", "lot_scale": lot_scale}

    def can_open_trade(
        self,
        balance: float,
        equity: float,
        open_positions: List[Dict],
        new_direction: str,
        daily_pnl: float = 0.0,
        daily_loss: float = 0.0,
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Convenience interface returning (allowed: bool, reason: str)."""
        loss = abs(float(daily_pnl)) if isinstance(daily_pnl, (int, float)) and daily_pnl < 0 else float(daily_loss)
        res = self.should_trade(
            balance=balance,
            equity=equity,
            daily_pnl=daily_pnl,
            daily_loss=loss,
            open_positions=open_positions,
            new_signal=new_direction,
            now_ts=now_ts,
        )
        return res["allowed"], res["reason"]

    def scale_lot_by_daily_pnl(self, base_lot: float, daily_pnl: float) -> float:
        """Scale lot size according to daily loss accumulated."""
        loss = abs(float(daily_pnl)) if isinstance(daily_pnl, (int, float)) and daily_pnl < 0 else 0.0
        scale = self.daily_loss_lot_scale(loss)
        return round(float(base_lot) * scale, 2)


    # ── Persist risk state ────────────────────────────────────────────────────
    def save_state(self, path: str = None):
        if path is None:
            import pathlib
            path = str(pathlib.Path(__file__).resolve().parent / "risk_state.json")
        try:
            with self._lock:
                state = {
                    "peak_balance": self.peak_balance,
                    "equity_ema": round(self._equity_ema, 2),
                    "hard_halt": self._hard_halt,
                    "soft_halt_until": self._soft_halt_until,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"[W9-Risk] save_state failed: {e}")

    def load_state(self, path: str = None):
        if path is None:
            import pathlib
            path = str(pathlib.Path(__file__).resolve().parent / "risk_state.json")
        try:
            if not os.path.exists(path):
                return
            if os.path.getsize(path) == 0:
                logger.warning(f"[W9-Risk] load_state: file is empty: {path}")
                return
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            if not isinstance(state, dict):
                logger.warning(f"[W9-Risk] load_state: invalid state format in {path}")
                return
            with self._lock:
                self.peak_balance = float(state.get("peak_balance", self.peak_balance))
                self._equity_ema = float(state.get("equity_ema", 0.0))
                self._hard_halt = bool(state.get("hard_halt", False))
                self._soft_halt_until = float(state.get("soft_halt_until", 0.0))
        except Exception as e:
            logger.error(f"[W9-Risk] load_state failed: {e}")

    def streak_lot_modifier(self) -> float:
        """Returns multiplier for current win/loss streak."""
        return 1.0

    def record_result(self, won: bool) -> None:
        """Record trade win/loss for session stats."""
        with self._lock:
            self._session_pnl_log.append(1.0 if won else -1.0)

    def is_recovery_mode(self) -> bool:
        """Returns True if currently in drawdown recovery mode."""
        with self._lock:
            return self._hard_halt

    def session_stats(self) -> Dict[str, Any]:
        """Returns dictionary of current session statistics."""
        with self._lock:
            return {
                "peak_balance": self.peak_balance,
                "equity_ema": self._equity_ema,
                "hard_halt": self._hard_halt,
                "total_trades": len(self._session_pnl_log),
            }

    def is_entry_blocked(self, balance: float = 10000.0, equity: float = 10000.0, **kwargs) -> bool:
        """Unified risk interface check for trade entry blocking."""
        res = self.should_trade(
            balance=balance,
            equity=equity,
            daily_pnl=kwargs.get("daily_pnl", 0.0),
            daily_loss=kwargs.get("daily_loss", 0.0),
            open_positions=kwargs.get("open_positions", []),
            new_signal=kwargs.get("new_signal", "BUY"),
            now_ts=kwargs.get("now_ts"),
        )
        return not res["allowed"]

    def is_blocked(self, balance: float = 10000.0, equity: float = 10000.0, **kwargs) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(balance=balance, equity=equity, **kwargs)

    def reset(self, starting_balance: Optional[float] = None) -> None:
        """Restore initial clean state."""
        with self._lock:
            if starting_balance is not None and not isinstance(starting_balance, bool) and math.isfinite(starting_balance) and starting_balance > 0:
                self.peak_balance = float(starting_balance)
            self._equity_history.clear()
            self._equity_ema = 0.0
            self._trade_times.clear()
            self._soft_halt_until = 0.0
            self._hard_halt = False
            self._session_pnl_log.clear()

    def info(self) -> Dict[str, Any]:
        """Comprehensive telemetry dictionary."""
        with self._lock:
            return {
                "peak_balance": self.peak_balance,
                "equity_ema": round(self._equity_ema, 2),
                "hard_halt": self._hard_halt,
                "soft_halt_until": self._soft_halt_until,
                "trade_times_count": len(self._trade_times),
                "total_trades": len(self._session_pnl_log),
                "max_trades_per_hour": self.max_trades_per_hour,
                "max_daily_loss_usd": self.max_daily_loss_usd,
                "daily_profit_target": self.daily_profit_target,
                "max_drawdown_pct": self.max_drawdown_pct,
            }

# ── Module-level singleton ─────────────────────────────────────────────────
risk_manager = RiskManager()
risk_manager.load_state()
