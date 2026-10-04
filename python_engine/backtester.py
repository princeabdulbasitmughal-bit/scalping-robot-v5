"""
Scalping Robot V5 Institutional Backtester & High-Frequency Tick Simulation Engine.
Simulates high-precision tick-by-tick and historical M1/M5 bar execution:
  - Session-aware Gaussian random walk (Tokyo=0.02, London=0.08, NY=0.12)
  - Realistic spread modeling (0.5 to 2.5 pips)
  - Multi-tier signal confluence (Bollinger Bands, EMA Trend/Pullback, Wilder's RSI)
  - Trailing stops, dynamic breakeven locks, and drawdown analytics
"""

import math
import random
import sys
from typing import List, Dict, Any, Optional, Union, Tuple

try:
    from .scalping_engine import ScalpingRobotV5, ScalpingSignal
except (ImportError, ValueError):
    from scalping_engine import ScalpingRobotV5, ScalpingSignal


class Backtester:
    """
    Institutional Backtester for Gold (XAUUSD) Scalping Robot V5.
    Simulates high-frequency tick price action with session-aware volatility,
    realistic bid/ask spreads, and multi-tier indicator confluence.
    """

    # Session volatility configuration
    SESSION_VOLATILITIES = {
        "TOKYO": 0.02,      # Asian session: low micro-volatility
        "LONDON": 0.08,     # European session: medium institutional volatility
        "NY": 0.12,         # New York session: high peak-impact volatility
        "NEW_YORK": 0.12,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.robot = ScalpingRobotV5(self.config)
        self.symbol = str(self.config.get("symbol", "XAUUSD"))
        self.pip_size = max(1e-6, float(self.config.get("pip_size") or 0.1))
        self.lot_size = max(0.001, float(self.config.get("lot_size") or 0.01))
        self.tp_dist = float(self.config.get("tp_pips", 15.0)) * self.pip_size
        self.sl_dist = float(self.config.get("sl_pips", 30.0)) * self.pip_size
        self.trailing_dist = float(self.config.get("trailing_stop_pips", 10.0)) * self.pip_size
        self.breakeven_dist = float(self.config.get("breakeven_pips", 8.0)) * self.pip_size
        self.breakeven_lock = float(self.config.get("breakeven_lock_pips", 2.0)) * self.pip_size
        self.max_spread = float(self.config.get("max_spread_pips", 3.0))

    def get_session_volatility(self, session_name: str) -> float:
        """Returns the configured volatility sigma for a given session."""
        normalized = session_name.upper().replace(" ", "_")
        return self.SESSION_VOLATILITIES.get(normalized, 0.08)

    def determine_session(self, tick_index: int, total_ticks: int) -> Tuple[str, float]:
        """
        Determines the active trading session and volatility based on tick position.
        Allocates realistic distribution across major global trading sessions:
          - Tokyo: First ~33% of ticks (vol=0.02)
          - London: Middle ~34% of ticks (vol=0.08)
          - NY: Final ~33% of ticks (vol=0.12)
        """
        if total_ticks <= 0:
            return "LONDON", 0.08

        ratio = tick_index / total_ticks
        if ratio < 0.333:
            session = "TOKYO"
        elif ratio < 0.667:
            session = "LONDON"
        else:
            session = "NY"

        vol = self.get_session_volatility(session)
        return session, vol

    def simulate_ticks(
        self,
        n_ticks: int = 1000,
        start_price: float = 2350.0,
        session: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Simulates n_ticks of realistic tick data using Gaussian random walk:
          price += random.gauss(0, session_vol) per tick
        Session-aware: Tokyo vol=0.02, London vol=0.08, NY vol=0.12
        Realistic spread: random.uniform(0.5, 2.5) pips
        """
        ticks = []
        price = start_price

        for i in range(n_ticks):
            if session:
                session_name = session.upper()
                vol = self.get_session_volatility(session_name)
            else:
                session_name, vol = self.determine_session(i, n_ticks)

            # Gaussian walk per tick
            price += random.gauss(0, vol)
            price = round(price, 3)

            # Realistic spread: random.uniform(0.5, 2.5)
            spread_pips = round(random.uniform(0.5, 2.5), 2)
            half_spread_price = (spread_pips * self.pip_size) / 2.0
            bid = round(price - half_spread_price, 3)
            ask = round(price + half_spread_price, 3)

            ticks.append({
                "tick": i,
                "price": price,
                "bid": bid,
                "ask": ask,
                "spread_pips": spread_pips,
                "session": session_name,
                "volatility": vol,
            })

        return ticks

    def _calc_ema(self, series: List[float], period: int) -> float:
        if not series or period <= 0:
            return 0.0
        if len(series) < period:
            return series[-1]
        k = 2.0 / (period + 1.0)
        ema = sum(series[:period]) / period
        for val in series[period:]:
            ema = (val * k) + (ema * (1.0 - k))
        return ema

    def _calc_rsi(self, series: List[float], period: int = 14) -> float:
        """Wilder's smoothed RSI matching main trader engine."""
        if not series or period <= 0 or len(series) < period + 1:
            return 50.0
        deltas = [series[i] - series[i - 1] for i in range(1, len(series))]
        gains = [max(0.0, d) for d in deltas]
        losses = [abs(min(0.0, d)) for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0.0 and avg_gain == 0.0:
            return 50.0
        if avg_loss == 0.0:
            return 100.0
        if avg_gain == 0.0:
            return 0.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_bb(self, series: List[float], period: int = 20, std_dev_mult: float = 2.0) -> Tuple[float, float, float]:
        if len(series) < period:
            p = series[-1] if series else 0.0
            return p + 1.0, p, p - 1.0
        slice_vals = series[-period:]
        mid = sum(slice_vals) / period
        var = sum((x - mid) ** 2 for x in slice_vals) / period
        sd = math.sqrt(max(0.0, var))
        upper = mid + (std_dev_mult * sd)
        lower = mid - (std_dev_mult * sd)
        return upper, mid, lower

    def calculate_tick_indicators(self, prices: List[float]) -> Dict[str, Any]:
        """Calculates BB, EMA, RSI indicators on rolling price stream."""
        if len(prices) < 22:
            return {}

        curr_price = prices[-1]
        fast_period = int(self.config.get("fast_ema", 8))
        slow_period = int(self.config.get("slow_ema", 21))
        bb_period = int(self.config.get("bb_period", 20))
        bb_std = float(self.config.get("bb_std", 2.0))
        rsi_period = int(self.config.get("rsi_period", 14))

        fast_ema = self._calc_ema(prices, fast_period)
        slow_ema = self._calc_ema(prices, slow_period)
        bb_upper, bb_mid, bb_lower = self._calc_bb(prices, period=bb_period, std_dev_mult=bb_std)
        rsi = self._calc_rsi(prices, period=rsi_period)

        return {
            "close": curr_price,
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "bb_upper": bb_upper,
            "bb_mid": bb_mid,
            "bb_lower": bb_lower,
            "rsi": rsi,
            "trend": "BULLISH" if fast_ema > slow_ema else "BEARISH",
        }

    def evaluate_signal(self, ind: Dict[str, Any], current_spread_pips: float = 1.0) -> str:
        """
        Applies identical signal logic (BB/EMA/RSI confluence) from main trader:
          - Spread protection: skip if spread > max_spread_pips
          - Tier 1: Bollinger Bands Mean Reversion
          - Tier 2: EMA Trend + Pullback Momentum
          - Tier 3: RSI Momentum Extremes
          - Tier 4: Price vs Midband + EMA Confluence
          - Tier 5: ScalpingRobotV5 evaluate_entry fallback
        """
        if not ind:
            return ScalpingSignal.HOLD

        # Spread Protection
        if current_spread_pips > self.max_spread:
            return ScalpingSignal.HOLD

        close = float(ind.get("close", 0.0))
        bb_upper = float(ind.get("bb_upper", close + 5.0))
        bb_lower = float(ind.get("bb_lower", close - 5.0))
        bb_mid = float(ind.get("bb_mid", (bb_upper + bb_lower) / 2.0))
        fast_ema = float(ind.get("fast_ema", close))
        slow_ema = float(ind.get("slow_ema", close))
        rsi = float(ind.get("rsi", 50.0))

        if close <= 0.0:
            return ScalpingSignal.HOLD

        # Tier 1: Strong BB mean-reversion
        if close <= bb_lower and rsi < 55.0:
            return ScalpingSignal.BUY
        elif close >= bb_upper and rsi > 45.0:
            return ScalpingSignal.SELL

        # Tier 2: EMA trend + momentum
        elif fast_ema > slow_ema and rsi < 65.0 and close < fast_ema * 1.0015:
            return ScalpingSignal.BUY
        elif fast_ema < slow_ema and rsi > 35.0 and close > fast_ema * 0.9985:
            return ScalpingSignal.SELL

        # Tier 3: RSI momentum extremes
        elif rsi <= 35.0:
            return ScalpingSignal.BUY
        elif rsi >= 65.0:
            return ScalpingSignal.SELL

        # Tier 4: Price vs midband + EMA agreement
        elif fast_ema >= slow_ema and close < bb_mid and rsi < 58.0:
            return ScalpingSignal.BUY
        elif fast_ema < slow_ema and close > bb_mid and rsi > 42.0:
            return ScalpingSignal.SELL

        # Tier 5: ScalpingRobotV5 fallback
        fallback = self.robot.evaluate_entry(ind, current_spread_pips=current_spread_pips)
        if fallback in [ScalpingSignal.BUY, ScalpingSignal.SELL]:
            return fallback

        return ScalpingSignal.HOLD

    def run_backtest_ticks(
        self,
        n_ticks: int = 1000,
        initial_balance: float = 10000.0,
        session: Optional[str] = None,
        start_price: float = 2350.0,
        print_summary: bool = True
    ) -> Dict[str, Any]:
        """
        Executes tick-by-tick backtest simulation over n_ticks.
        Tracks total_trades, wins, losses, total_pnl, max_drawdown, win_rate.
        """
        warmup_len = 30
        history_prices = [round(start_price + random.gauss(0, 0.02), 3) for _ in range(warmup_len)]

        ticks = self.simulate_ticks(n_ticks=n_ticks, start_price=history_prices[-1], session=session)

        balance = initial_balance
        equity = initial_balance
        peak_equity = initial_balance
        max_drawdown = 0.0
        max_drawdown_pct = 0.0

        trades: List[Dict[str, Any]] = []
        open_trades: List[Dict[str, Any]] = []
        max_orders = int(self.config.get("max_orders", 1))

        spreads = []

        for i, tick_data in enumerate(ticks):
            curr_price = tick_data["price"]
            bid = tick_data["bid"]
            ask = tick_data["ask"]
            spread = tick_data["spread_pips"]
            current_session = tick_data["session"]
            spreads.append(spread)

            history_prices.append(curr_price)

            # 1. Manage open trades (TP, SL, Breakeven, Trailing stop)
            remaining_trades = []
            for t in open_trades:
                closed = False
                pnl = 0.0
                close_reason = ""
                t_type = t.get("type")
                t_entry = float(t.get("entry_price", curr_price))
                t_tp = float(t.get("tp", 0.0))
                t_sl = float(t.get("sl", 0.0))
                breakeven_act = bool(t.get("breakeven_activated", False))

                if t_type == ScalpingSignal.BUY:
                    # Breakeven check
                    if not breakeven_act and (bid - t_entry) >= self.breakeven_dist:
                        t["sl"] = t_entry + self.breakeven_lock
                        t["breakeven_activated"] = True
                        breakeven_act = True
                        t_sl = t["sl"]

                    # Trailing stop update
                    if breakeven_act:
                        new_sl = bid - self.trailing_dist
                        if new_sl > t_sl:
                            t["sl"] = new_sl
                            t_sl = new_sl

                    # Hit TP
                    if bid >= t_tp and t_tp > 0:
                        closed = True
                        close_price = t_tp
                        pnl = (close_price - t_entry) / self.pip_size * (self.lot_size * 10.0)
                        close_reason = "TAKE_PROFIT"
                    # Hit SL
                    elif bid <= t_sl and t_sl > 0:
                        closed = True
                        close_price = t_sl
                        pnl = (close_price - t_entry) / self.pip_size * (self.lot_size * 10.0)
                        close_reason = "STOP_LOSS"

                elif t_type == ScalpingSignal.SELL:
                    # Breakeven check
                    if not breakeven_act and (t_entry - ask) >= self.breakeven_dist:
                        t["sl"] = t_entry - self.breakeven_lock
                        t["breakeven_activated"] = True
                        breakeven_act = True
                        t_sl = t["sl"]

                    # Trailing stop update
                    if breakeven_act:
                        new_sl = ask + self.trailing_dist
                        if new_sl < t_sl or t_sl == 0:
                            t["sl"] = new_sl
                            t_sl = new_sl

                    # Hit TP
                    if ask <= t_tp and t_tp > 0:
                        closed = True
                        close_price = t_tp
                        pnl = (t_entry - close_price) / self.pip_size * (self.lot_size * 10.0)
                        close_reason = "TAKE_PROFIT"
                    # Hit SL
                    elif ask >= t_sl and t_sl > 0:
                        closed = True
                        close_price = t_sl
                        pnl = (t_entry - close_price) / self.pip_size * (self.lot_size * 10.0)
                        close_reason = "STOP_LOSS"

                if closed:
                    balance += pnl
                    trades.append({
                        "id": len(trades) + 1,
                        "type": t_type,
                        "entry_price": t_entry,
                        "close_price": close_price,
                        "pnl": round(pnl, 2),
                        "reason": close_reason,
                        "tick": i,
                        "session": current_session,
                        "spread_pips": spread
                    })
                else:
                    remaining_trades.append(t)

            open_trades = remaining_trades

            # 2. Evaluate new entry
            if len(open_trades) < max_orders:
                indicators = self.calculate_tick_indicators(history_prices)
                sig = self.evaluate_signal(indicators, current_spread_pips=spread)

                if sig == ScalpingSignal.BUY:
                    open_trades.append({
                        "type": ScalpingSignal.BUY,
                        "entry_price": ask,
                        "tp": ask + self.tp_dist,
                        "sl": ask - self.sl_dist,
                        "breakeven_activated": False,
                        "open_tick": i,
                        "session": current_session
                    })
                elif sig == ScalpingSignal.SELL:
                    open_trades.append({
                        "type": ScalpingSignal.SELL,
                        "entry_price": bid,
                        "tp": bid - self.tp_dist,
                        "sl": bid + self.sl_dist,
                        "breakeven_activated": False,
                        "open_tick": i,
                        "session": current_session
                    })

            # 3. Peak & Drawdown track
            unrealized = 0.0
            for t in open_trades:
                if t["type"] == ScalpingSignal.BUY:
                    unrealized += (bid - float(t["entry_price"])) / self.pip_size * (self.lot_size * 10.0)
                else:
                    unrealized += (float(t["entry_price"]) - ask) / self.pip_size * (self.lot_size * 10.0)

            equity = balance + unrealized
            if equity > peak_equity:
                peak_equity = equity
            dd = peak_equity - equity
            dd_pct = (dd / peak_equity) * 100.0 if peak_equity > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct

        # Close any remaining open trades at market
        final_bid = ticks[-1]["bid"]
        final_ask = ticks[-1]["ask"]
        for t in open_trades:
            t_type = t["type"]
            t_entry = float(t["entry_price"])
            if t_type == ScalpingSignal.BUY:
                close_p = final_bid
                pnl = (close_p - t_entry) / self.pip_size * (self.lot_size * 10.0)
            else:
                close_p = final_ask
                pnl = (t_entry - close_p) / self.pip_size * (self.lot_size * 10.0)
            balance += pnl
            trades.append({
                "id": len(trades) + 1,
                "type": t_type,
                "entry_price": t_entry,
                "close_price": close_p,
                "pnl": round(pnl, 2),
                "reason": "END_OF_TEST",
                "tick": len(ticks) - 1,
                "session": ticks[-1]["session"],
                "spread_pips": ticks[-1]["spread_pips"]
            })

        # Calculate metrics
        winning_trades = [t for t in trades if float(t.get("pnl", 0.0)) > 0]
        losing_trades = [t for t in trades if float(t.get("pnl", 0.0)) < 0]
        total_trades = len(trades)
        wins = len(winning_trades)
        losses = len(losing_trades)
        total_pnl = round(balance - initial_balance, 2)
        win_rate = round((wins / total_trades * 100.0), 2) if total_trades > 0 else 0.0
        gross_profit = sum(float(t.get("pnl", 0.0)) for t in winning_trades)
        gross_loss = abs(sum(float(t.get("pnl", 0.0)) for t in losing_trades))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        return_pct = round((total_pnl / initial_balance) * 100.0, 2)
        avg_spread = round(sum(spreads) / max(1, len(spreads)), 2)

        results = {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "total_pnl": total_pnl,
            "max_drawdown": round(max_drawdown, 2),
            "win_rate": win_rate,
            "initial_balance": initial_balance,
            "final_balance": round(balance, 2),
            "net_profit": total_pnl,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_usd": round(max_drawdown, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "return_pct": return_pct,
            "avg_spread_pips": avg_spread,
            "symbol": self.symbol,
            "ticks_simulated": n_ticks,
            "recent_trades": trades[-10:] if len(trades) > 10 else trades,
            "trades": trades
        }

        if print_summary:
            self.print_results_summary(results)

        return results

    def print_results_summary(self, results: Dict[str, Any]) -> None:
        """Prints formatted institutional backtest performance summary."""
        print("\n" + "=" * 65)
        print("          GOLD SCALPING ROBOT V5 - BACKTEST SUMMARY")
        print("=" * 65)
        print(f"Symbol:                 {results.get('symbol', 'XAUUSD')}")
        print(f"Ticks Simulated:        {results.get('ticks_simulated', 1000)}")
        print(f"Avg Spread:             {results.get('avg_spread_pips', 1.5):.2f} pips")
        print("-" * 65)
        print(f"Initial Balance:        ${results.get('initial_balance', 10000.0):,.2f}")
        print(f"Final Balance:          ${results.get('final_balance', 10000.0):,.2f}")
        print(f"Total PnL:              ${results.get('total_pnl', 0.0):+,.2f} ({results.get('return_pct', 0.0):+.2f}%)")
        print("-" * 65)
        print(f"Total Trades:           {results.get('total_trades', 0)}")
        print(f"Wins:                   {results.get('wins', 0)}")
        print(f"Losses:                 {results.get('losses', 0)}")
        print(f"Win Rate:               {results.get('win_rate', 0.0):.2f}%")
        print(f"Profit Factor:          {results.get('profit_factor', 0.0):.2f}")
        print(f"Max Drawdown:           ${results.get('max_drawdown', 0.0):,.2f} ({results.get('max_drawdown_pct', 0.0):.2f}%)")
        print("=" * 65 + "\n")

    def run_backtest_bars(
        self,
        bars: List[Dict[str, float]],
        initial_balance: float = 10000.0,
        print_summary: bool = False
    ) -> Dict[str, Any]:
        """Historical bar-based simulation for backward compatibility with M1/M5 datasets."""
        balance = initial_balance
        equity = initial_balance
        peak_equity = initial_balance
        max_drawdown = 0.0
        max_drawdown_pct = 0.0

        trades: List[Dict[str, Any]] = []
        open_trades: List[Dict[str, Any]] = []

        window = 30
        for i in range(window, len(bars)):
            current_bar = bars[i]
            history_slice = bars[max(0, i - 100):i]
            indicators = self.robot.calculate_indicators(history_slice)

            curr_price = float(current_bar.get("close", 0.0))
            high_price = float(current_bar.get("high", curr_price))
            low_price = float(current_bar.get("low", curr_price))
            if curr_price <= 0.0:
                continue

            # 1. Manage open trades
            remaining_trades = []
            for t in open_trades:
                closed = False
                pnl = 0.0
                close_reason = ""
                t_type = t.get("type")
                t_entry = float(t.get("entry_price", 0.0))
                t_tp = float(t.get("tp", 0.0))
                t_sl = float(t.get("sl", 0.0))
                breakeven_act = bool(t.get("breakeven_activated", False))

                if t_type == ScalpingSignal.BUY:
                    if not breakeven_act and (high_price - t_entry) >= self.breakeven_dist:
                        t["sl"] = t_entry + self.breakeven_lock
                        t["breakeven_activated"] = True
                        breakeven_act = True
                        t_sl = t["sl"]

                    if breakeven_act:
                        new_sl = high_price - self.trailing_dist
                        if new_sl > t_sl:
                            t["sl"] = new_sl
                            t_sl = new_sl

                    if high_price >= t_tp and t_tp > 0:
                        closed = True
                        pnl = (t_tp - t_entry) / self.pip_size * (self.lot_size * 10.0)
                        close_reason = "TAKE_PROFIT"
                        close_price = t_tp
                    elif low_price <= t_sl and t_sl > 0:
                        closed = True
                        pnl = (t_sl - t_entry) / self.pip_size * (self.lot_size * 10.0)
                        close_reason = "STOP_LOSS"
                        close_price = t_sl

                elif t_type == ScalpingSignal.SELL:
                    if not breakeven_act and (t_entry - low_price) >= self.breakeven_dist:
                        t["sl"] = t_entry - self.breakeven_lock
                        t["breakeven_activated"] = True
                        breakeven_act = True
                        t_sl = t["sl"]

                    if breakeven_act:
                        new_sl = low_price + self.trailing_dist
                        if new_sl < t_sl or t_sl == 0:
                            t["sl"] = new_sl
                            t_sl = new_sl

                    if low_price <= t_tp and t_tp > 0:
                        closed = True
                        pnl = (t_entry - t_tp) / self.pip_size * (self.lot_size * 10.0)
                        close_reason = "TAKE_PROFIT"
                        close_price = t_tp
                    elif high_price >= t_sl and t_sl > 0:
                        closed = True
                        pnl = (t_entry - t_sl) / self.pip_size * (self.lot_size * 10.0)
                        close_reason = "STOP_LOSS"
                        close_price = t_sl

                if closed:
                    balance += pnl
                    trades.append({
                        "id": len(trades) + 1,
                        "type": t_type,
                        "entry_price": t_entry,
                        "close_price": close_price,
                        "pnl": round(pnl, 2),
                        "reason": close_reason,
                        "bar": i
                    })
                else:
                    remaining_trades.append(t)

            open_trades = remaining_trades

            # 2. Evaluate new entry
            if len(open_trades) < int(self.robot.config.get("max_orders", 1)):
                sig = self.robot.evaluate_entry(indicators)
                if sig == ScalpingSignal.BUY:
                    open_trades.append({
                        "type": ScalpingSignal.BUY,
                        "entry_price": curr_price,
                        "tp": curr_price + self.tp_dist,
                        "sl": curr_price - self.sl_dist,
                        "breakeven_activated": False,
                        "open_bar": i
                    })
                elif sig == ScalpingSignal.SELL:
                    open_trades.append({
                        "type": ScalpingSignal.SELL,
                        "entry_price": curr_price,
                        "tp": curr_price - self.tp_dist,
                        "sl": curr_price + self.sl_dist,
                        "breakeven_activated": False,
                        "open_bar": i
                    })

            # 3. Peak & Drawdown track
            equity = balance + sum(
                ((curr_price - float(t.get("entry_price", curr_price))) if t.get("type") == ScalpingSignal.BUY else (float(t.get("entry_price", curr_price)) - curr_price)) / self.pip_size * (self.lot_size * 10.0)
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

        winning_trades = [t for t in trades if float(t.get("pnl", 0.0)) > 0]
        losing_trades = [t for t in trades if float(t.get("pnl", 0.0)) < 0]
        total_pnl = balance - initial_balance
        win_rate = (len(winning_trades) / len(trades) * 100.0) if trades else 0.0
        gross_profit = sum(float(t.get("pnl", 0.0)) for t in winning_trades)
        gross_loss = abs(sum(float(t.get("pnl", 0.0)) for t in losing_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

        results = {
            "initial_balance": initial_balance,
            "final_balance": round(balance, 2),
            "net_profit": round(total_pnl, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": round((total_pnl / initial_balance) * 100.0, 2),
            "total_trades": len(trades),
            "wins": len(winning_trades),
            "winning_trades": len(winning_trades),
            "losses": len(losing_trades),
            "losing_trades": len(losing_trades),
            "win_rate": round(win_rate, 2),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_drawdown, 2),
            "max_drawdown_usd": round(max_drawdown, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "symbol": self.robot.config.get("symbol", "XAUUSD"),
            "timeframe": self.robot.config.get("timeframe", "M1"),
            "recent_trades": trades[-10:] if len(trades) > 10 else trades,
            "trades": trades
        }

        if print_summary:
            self.print_results_summary(results)

        return results

    def generate_synthetic_gold_m1(self, bars_count: int = 5000, start_price: float = 2350.0) -> List[Dict[str, float]]:
        """Generates realistic synthetic M1 Gold bars."""
        bars = []
        price = start_price
        trend_bias = 0.00005

        for i in range(bars_count):
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
                "timestamp": f"2026-09-11 {i // 60:02d}:{i % 60:02d}:00"
            })
            price = close_p

        return bars

    def run_backtest(
        self,
        bars_or_n_ticks: Optional[Union[List[Dict[str, float]], int]] = None,
        initial_balance: float = 10000.0,
        n_ticks: int = 1000,
        session: Optional[str] = None,
        print_summary: bool = True
    ) -> Dict[str, Any]:
        """
        Unified backtest entry point:
          - If passed a list of bar dicts, executes bar-based simulation.
          - If passed integer or n_ticks, executes tick-by-tick Gaussian walk simulation.
        """
        if isinstance(bars_or_n_ticks, list):
            return self.run_backtest_bars(bars_or_n_ticks, initial_balance=initial_balance, print_summary=print_summary)

        target_ticks = bars_or_n_ticks if isinstance(bars_or_n_ticks, int) else n_ticks
        return self.run_backtest_ticks(
            n_ticks=target_ticks,
            initial_balance=initial_balance,
            session=session,
            print_summary=print_summary
        )


# Backward compatibility alias
ScalpingBacktester = Backtester


if __name__ == "__main__":
    bt = Backtester({"symbol": "XAUUSD", "lot_size": 0.01})
    res = bt.run_backtest(n_ticks=1000)
