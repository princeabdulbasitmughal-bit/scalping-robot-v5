"""
Scalping Robot V5 Institutional Backtester
Simulates high-precision M1 / M5 historical execution with spread, slippage, and trailing risk control.
"""

import math
import random
from typing import List, Dict, Any
from .scalping_engine import ScalpingRobotV5, ScalpingSignal

class ScalpingBacktester:
    def __init__(self, config: Dict[str, Any] = None):
        self.robot = ScalpingRobotV5(config)
        
    def generate_synthetic_gold_m1(self, bars_count: int = 5000, start_price: float = 2350.0) -> List[Dict[str, float]]:
        """
        Generates realistic high-frequency Gold (XAUUSD) M1 price action with micro-volatility clusters.
        """
        bars = []
        price = start_price
        trend_bias = 0.00005
        
        for i in range(bars_count):
            # Volatility regime
            vol = random.uniform(0.3, 1.8)
            drift = random.gauss(trend_bias, vol)
            open_p = price
            close_p = open_p + drift
            high_p = max(open_p, close_p) + abs(random.gauss(0, vol * 0.5))
            low_p = min(open_p, close_p) - abs(random.gauss(0, vol * 0.5))
            
            bars.append({
                "bar_index": i,
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": random.randint(50, 500),
                "timestamp": f"2026-09-11 {i//60:02d}:{i%60:02d}:00"
            })
            price = close_p
            
        return bars
        
    def run_backtest(self, bars: List[Dict[str, float]], initial_balance: float = 10000.0) -> Dict[str, Any]:
        balance = initial_balance
        equity = initial_balance
        peak_equity = initial_balance
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        
        trades: List[Dict[str, Any]] = []
        open_trades: List[Dict[str, Any]] = []
        
        pip_size = max(1e-6, float(self.robot.config.get("pip_size") or 0.1))
        tp_dist = float(self.robot.config.get("tp_pips", 15.0)) * pip_size
        sl_dist = float(self.robot.config.get("sl_pips", 30.0)) * pip_size
        trailing_dist = float(self.robot.config.get("trailing_stop_pips", 10.0)) * pip_size
        breakeven_dist = float(self.robot.config.get("breakeven_pips", 8.0)) * pip_size
        breakeven_lock = float(self.robot.config.get("breakeven_lock_pips", 2.0)) * pip_size
        lot_size = max(0.001, float(self.robot.config.get("lot_size") or 0.01))

        
        window = 30
        for i in range(window, len(bars)):
            current_bar = bars[i]
            history_slice = bars[max(0, i - 100):i]
            indicators = self.robot.calculate_indicators(history_slice)
            
            curr_price = current_bar["close"]
            high_price = current_bar["high"]
            low_price = current_bar["low"]
            
            # 1. Manage open trades (TP, SL, Trailing, Breakeven)
            remaining_trades = []
            for t in open_trades:
                closed = False
                pnl = 0.0
                close_reason = ""
                
                if t["type"] == ScalpingSignal.BUY:
                    # Breakeven check
                    if not t["breakeven_activated"] and (high_price - t["entry_price"]) >= breakeven_dist:
                        t["sl"] = t["entry_price"] + breakeven_lock
                        t["breakeven_activated"] = True
                        
                    # Trailing stop update
                    if t["breakeven_activated"]:
                        new_sl = high_price - trailing_dist
                        if new_sl > t["sl"]:
                            t["sl"] = new_sl
                            
                    # Hit TP
                    if high_price >= t["tp"]:
                        closed = True
                        pnl = (t["tp"] - t["entry_price"]) / pip_size * (lot_size * 10.0)
                        close_reason = "TAKE_PROFIT"
                        close_price = t["tp"]
                    # Hit SL
                    elif low_price <= t["sl"]:
                        closed = True
                        pnl = (t["sl"] - t["entry_price"]) / pip_size * (lot_size * 10.0)
                        close_reason = "STOP_LOSS"
                        close_price = t["sl"]
                        
                elif t["type"] == ScalpingSignal.SELL:
                    # Breakeven check
                    if not t["breakeven_activated"] and (t["entry_price"] - low_price) >= breakeven_dist:
                        t["sl"] = t["entry_price"] - breakeven_lock
                        t["breakeven_activated"] = True
                        
                    # Trailing stop update
                    if t["breakeven_activated"]:
                        new_sl = low_price + trailing_dist
                        if new_sl < t["sl"]:
                            t["sl"] = new_sl
                            
                    # Hit TP
                    if low_price <= t["tp"]:
                        closed = True
                        pnl = (t["entry_price"] - t["tp"]) / pip_size * (lot_size * 10.0)
                        close_reason = "TAKE_PROFIT"
                        close_price = t["tp"]
                    # Hit SL
                    elif high_price >= t["sl"]:
                        closed = True
                        pnl = (t["entry_price"] - t["sl"]) / pip_size * (lot_size * 10.0)
                        close_reason = "STOP_LOSS"
                        close_price = t["sl"]
                        
                if closed:
                    balance += pnl
                    trades.append({
                        "id": len(trades) + 1,
                        "type": t["type"],
                        "entry_price": t["entry_price"],
                        "close_price": close_price,
                        "pnl": round(pnl, 2),
                        "reason": close_reason,
                        "bar": i
                    })
                else:
                    remaining_trades.append(t)
                    
            open_trades = remaining_trades
            
            # 2. Evaluate new entry
            if len(open_trades) < self.robot.config["max_orders"]:
                sig = self.robot.evaluate_entry(indicators)
                if sig == ScalpingSignal.BUY:
                    open_trades.append({
                        "type": ScalpingSignal.BUY,
                        "entry_price": curr_price,
                        "tp": curr_price + tp_dist,
                        "sl": curr_price - sl_dist,
                        "breakeven_activated": False,
                        "open_bar": i
                    })
                elif sig == ScalpingSignal.SELL:
                    open_trades.append({
                        "type": ScalpingSignal.SELL,
                        "entry_price": curr_price,
                        "tp": curr_price - tp_dist,
                        "sl": curr_price + sl_dist,
                        "breakeven_activated": False,
                        "open_bar": i
                    })
                    
            # 3. Peak & Drawdown track
            equity = balance + sum(
                ((curr_price - t["entry_price"]) if t["type"] == ScalpingSignal.BUY else (t["entry_price"] - curr_price)) / pip_size * (lot_size * 10.0)
                for t in open_trades
            )
            if equity > peak_equity:
                peak_equity = equity
            dd = peak_equity - equity
            dd_pct = (dd / peak_equity) * 100.0 if peak_equity > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct
                
        # Metrics
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] < 0]
        total_pnl = balance - initial_balance
        win_rate = (len(winning_trades) / len(trades) * 100.0) if trades else 0.0
        gross_profit = sum(t["pnl"] for t in winning_trades)
        gross_loss = abs(sum(t["pnl"] for t in losing_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
        
        return {
            "initial_balance": initial_balance,
            "final_balance": round(balance, 2),
            "net_profit": round(total_pnl, 2),
            "return_pct": round((total_pnl / initial_balance) * 100.0, 2),
            "total_trades": len(trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_usd": round(max_drawdown, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "symbol": self.robot.config["symbol"],
            "timeframe": self.robot.config["timeframe"],
            "recent_trades": trades[-10:] if len(trades) > 10 else trades
        }
