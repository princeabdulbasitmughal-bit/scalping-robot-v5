"""
Scalping Robot V5 - Autonomous Live Runner and Paper Trading Service
Simulates live market ticks or streams from broker, evaluating micro-signals and logging state.
Hardened with atomic state writes, memory bounding, and crash-proof execution.
"""

import os
import sys
import time
import json
import random
import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from .scalping_engine import ScalpingRobotV5, ScalpingSignal
from .storage import atomic_write_json

logger = logging.getLogger("ScalpingRobotV5.LiveRunner")

STATUS_FILE = Path(__file__).resolve().parent.parent / "live_status.json"

class ScalpingLiveRunner:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._lock = threading.RLock()
        self.robot = ScalpingRobotV5(config)
        self.running = False
        self.bars = []
        self.current_price = 2385.50
        self.balance = 10000.0
        self.equity = 10000.0
        self.trades_history = []
        self.total_trades_count = 0
        self.winning_trades_count = 0
        self.daily_pnl = 0.0
        self.last_bar_time = time.time()

        
        # Seed initial bars
        now = time.time()
        for i in range(100):
            p = self.current_price + random.uniform(-1.5, 1.5)
            self.bars.append({
                "open": round(p - 0.2, 2),
                "high": round(p + 0.5, 2),
                "low": round(p - 0.5, 2),
                "close": round(p, 2),
                "volume": random.randint(10, 100),
                "timestamp": datetime.fromtimestamp(now - (100 - i)*60, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            })
            self.current_price = p
        self.last_bar_time = now
            
    def update_tick(self, tick_price: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                now = time.time()
                if tick_price is None or not isinstance(tick_price, (int, float)) or not math.isfinite(tick_price) or tick_price <= 0:
                    # Simulate high frequency tick micro-movement
                    delta = random.gauss(0, 0.25)
                    self.current_price = round(self.current_price + delta, 2)
                else:
                    self.current_price = round(float(tick_price), 2)

                
            # Manage candlestick rollover
            if (now - self.last_bar_time) >= 60.0 or not self.bars:
                self.last_bar_time = now
                self.bars.append({
                    "open": self.current_price,
                    "high": self.current_price,
                    "low": self.current_price,
                    "close": self.current_price,
                    "volume": 1,
                    "timestamp": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                })
                if len(self.bars) > 300:
                    self.bars = self.bars[-300:]
            else:
                last_bar = self.bars[-1]
                last_bar["close"] = self.current_price
                if self.current_price > last_bar.get("high", self.current_price):
                    last_bar["high"] = self.current_price
                if self.current_price < last_bar.get("low", self.current_price):
                    last_bar["low"] = self.current_price
                last_bar["volume"] = last_bar.get("volume", 0) + 1
                
            indicators = self.robot.calculate_indicators(self.bars)
            spread = round(random.uniform(1.0, 2.2), 1)
            
            # Check open positions
            pip_size = max(1e-6, float(self.robot.config.get("pip_size") or 0.1))
            lot_size = max(0.001, float(self.robot.config.get("lot_size") or 0.01))
            pip_value = max(1e-6, float(self.robot.config.get("pip_value") or 1.0))
            
            remaining = []
            for pos in self.robot.open_positions:
                closed = False
                pnl = 0.0
                pos_type = pos.get("type")
                pos_tp = float(pos.get("tp", 0.0))
                pos_sl = float(pos.get("sl", 0.0))
                pos_entry = float(pos.get("entry", self.current_price))

                if pos_type == ScalpingSignal.BUY:
                    if self.current_price >= pos_tp and pos_tp > 0:
                        closed = True
                        pnl = (pos_tp - pos_entry) / pip_size * (lot_size / 0.01) * pip_value
                        pos["close_reason"] = "TP_HIT"
                    elif self.current_price <= pos_sl and pos_sl > 0:
                        closed = True
                        pnl = (pos_sl - pos_entry) / pip_size * (lot_size / 0.01) * pip_value
                        pos["close_reason"] = "SL_HIT"
                elif pos_type == ScalpingSignal.SELL:
                    if self.current_price <= pos_tp and pos_tp > 0:
                        closed = True
                        pnl = (pos_entry - pos_tp) / pip_size * (lot_size / 0.01) * pip_value
                        pos["close_reason"] = "TP_HIT"
                    elif self.current_price >= pos_sl and pos_sl > 0:
                        closed = True
                        pnl = (pos_entry - pos_sl) / pip_size * (lot_size / 0.01) * pip_value
                        pos["close_reason"] = "SL_HIT"
                        
                if closed:
                    self.balance += pnl
                    self.daily_pnl += pnl
                    pos["pnl"] = round(pnl, 2)
                    pos["close_time"] = datetime.now(timezone.utc).isoformat()
                    pos["close_price"] = self.current_price
                    self.total_trades_count += 1
                    if pnl > 0:
                        self.winning_trades_count += 1
                    self.trades_history.append(pos)
                    if len(self.trades_history) > 1000:
                        self.trades_history = self.trades_history[-1000:]
                else:
                    remaining.append(pos)
                    
            self.robot.open_positions = remaining
            
            # Evaluate new signal
            sig = self.robot.evaluate_entry(indicators, spread)
            if sig in (ScalpingSignal.BUY, ScalpingSignal.SELL):
                tp_dist = float(self.robot.config.get("tp_pips", 15.0)) * pip_size
                sl_dist = float(self.robot.config.get("sl_pips", 30.0)) * pip_size
                order = {
                    "id": self.total_trades_count + len(self.robot.open_positions) + 1,
                    "type": sig,
                    "symbol": self.robot.config.get("symbol", "XAUUSD"),
                    "entry": self.current_price,
                    "lot": lot_size,
                    "tp": self.current_price + (tp_dist if sig == ScalpingSignal.BUY else -tp_dist),
                    "sl": self.current_price - (sl_dist if sig == ScalpingSignal.BUY else -sl_dist),
                    "open_time": datetime.now(timezone.utc).isoformat()
                }
                self.robot.open_positions.append(order)
                
            # Write state snapshot atomically
            floating_pnl = sum(
                ((self.current_price - float(p.get("entry", self.current_price))) if p.get("type") == ScalpingSignal.BUY else (float(p.get("entry", self.current_price)) - self.current_price)) / pip_size * (lot_size / 0.01) * pip_value
                for p in self.robot.open_positions
            )
            self.equity = round(self.balance + floating_pnl, 2)
            
            total_trades = self.total_trades_count if self.total_trades_count > 0 else len(self.trades_history)
            win_count = self.winning_trades_count if self.total_trades_count > 0 else len([t for t in self.trades_history if t.get("pnl", 0) > 0])
            win_rate = round(win_count / total_trades * 100.0, 1) if total_trades > 0 else 0.0

            status = {
                "status": "ACTIVE_SCALPING",
                "symbol": self.robot.config.get("symbol", "XAUUSD"),
                "current_price": self.current_price,
                "balance": round(self.balance, 2),
                "equity": self.equity,
                "daily_pnl": round(self.daily_pnl, 2),
                "open_positions": self.robot.open_positions,
                "total_trades": total_trades,
                "win_rate_pct": win_rate,
                "last_signal": sig,
                "spread_pips": spread,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            atomic_write_json(STATUS_FILE, status)
            return status

        except Exception as exc:
            logger.error(f"Error during update_tick: {exc}", exc_info=True)
            return {
                "status": "ERROR_RECOVERING",
                "current_price": self.current_price,
                "balance": round(self.balance, 2),
                "equity": round(self.equity, 2),
                "error": str(exc)
            }

    def get_state(self) -> Dict[str, Any]:
        """Return thread-safe snapshot of live runner state."""
        with self._lock:
            return {
                "current_price": self.current_price,
                "balance": round(self.balance, 2),
                "equity": round(self.equity, 2),
                "daily_pnl": round(self.daily_pnl, 2),
                "open_positions_count": len(self.robot.open_positions),
                "total_trades_count": self.total_trades_count,
                "winning_trades_count": self.winning_trades_count,
                "bars_count": len(self.bars),
            }

    def reset(self, balance: float = 10000.0) -> None:
        """Reset live runner state and positions."""
        with self._lock:
            self.balance = float(balance) if math.isfinite(balance) and balance > 0 else 10000.0
            self.equity = self.balance
            self.daily_pnl = 0.0
            self.total_trades_count = 0
            self.winning_trades_count = 0
            self.robot.open_positions = []
            self.trades_history = []


if __name__ == "__main__":

    runner = ScalpingLiveRunner()
    print("Scalping Robot V5 Live Runner Initialized.")
    for _ in range(5):
        s = runner.update_tick()
        print(f"Tick: {s.get('current_price')} | Signal: {s.get('last_signal')} | Balance: ${s.get('balance')} | Open Pos: {len(s.get('open_positions', []))}")
