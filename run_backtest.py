"""
run_backtest.py - Strategy Backtester for Gold Scalping Robot
Simulates signal system over historical-style price data.
"""
import random
import math
import json
import os
from datetime import datetime

RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest_results.json')


def simulate_price(n_ticks=2000, start_price=2400.0):
    prices = [start_price]
    for i in range(n_ticks - 1):
        # Session-aware volatility
        session_vol = 0.08
        if i % 1440 < 540:    # Tokyo hours
            session_vol = 0.02
        elif i % 1440 < 1020:  # London hours
            session_vol = 0.08
        else:                   # NY hours
            session_vol = 0.12
        drift = random.gauss(0, session_vol)
        price = max(prices[-1] + drift, 100.0)
        prices.append(price)
    return prices


def bb_signal(prices, i, period=20):
    if i < period:
        return 'HOLD'
    window = prices[i - period:i]
    mean = sum(window) / len(window)
    variance = sum((x - mean) ** 2 for x in window) / len(window)
    std = math.sqrt(variance)
    if std < 0.001:
        return 'HOLD'
    upper = mean + 2 * std
    lower = mean - 2 * std
    price = prices[i]
    if price <= lower:
        return 'BUY'
    elif price >= upper:
        return 'SELL'
    return 'HOLD'


def run_backtest(n_ticks=2000, sl_pips=30.0, tp_pips=45.0, lot=0.02, start_balance=10000.0):
    random.seed(42)
    prices = simulate_price(n_ticks)
    balance = start_balance
    peak_balance = start_balance
    max_drawdown = 0.0
    trades = []
    in_trade = None
    entry_price = 0.0
    entry_i = 0
    spread = 1.5

    for i in range(20, len(prices)):
        price = prices[i]
        if in_trade is None:
            sig = bb_signal(prices, i)
            if sig == 'BUY':
                in_trade = 'BUY'
                entry_price = price + spread / 2
                entry_i = i
            elif sig == 'SELL':
                in_trade = 'SELL'
                entry_price = price - spread / 2
                entry_i = i
        else:
            if in_trade == 'BUY':
                pips_moved = price - entry_price
            else:
                pips_moved = entry_price - price

            pnl = pips_moved * lot * 100
            duration = i - entry_i
            closed = False
            reason = ''

            if pips_moved >= tp_pips:
                reason = 'TP'
                closed = True
            elif pips_moved <= -sl_pips:
                reason = 'SL'
                closed = True
            elif duration > 180:
                reason = 'TIMEOUT'
                closed = True

            if closed:
                balance += pnl
                peak_balance = max(peak_balance, balance)
                dd = (peak_balance - balance) / peak_balance * 100
                max_drawdown = max(max_drawdown, dd)
                trades.append({
                    'result': 'WIN' if pnl > 0 else 'LOSS',
                    'pnl': round(pnl, 2),
                    'duration': duration,
                    'reason': reason,
                    'direction': in_trade,
                })
                in_trade = None

    wins = sum(1 for t in trades if t['result'] == 'WIN')
    losses = len(trades) - wins
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = round((wins / len(trades) * 100), 1) if trades else 0.0
    profit_factor = 0.0
    gross_wins = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_losses = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    if gross_losses > 0:
        profit_factor = round(gross_wins / gross_losses, 2)

    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'n_ticks': n_ticks,
        'total_trades': len(trades),
        'wins': wins,
        'losses': losses,
        'win_rate_pct': win_rate,
        'total_pnl': round(total_pnl, 2),
        'final_balance': round(balance, 2),
        'max_drawdown_pct': round(max_drawdown, 2),
        'profit_factor': profit_factor,
    }

    print("=" * 50)
    print("BACKTEST RESULTS - Gold Scalping Robot")
    print("=" * 50)
    print("Ticks simulated : {}".format(n_ticks))
    print("Total Trades    : {}".format(results['total_trades']))
    print("Wins            : {} | Losses: {}".format(wins, losses))
    print("Win Rate        : {}%".format(win_rate))
    print("Total PnL       : ${:.2f}".format(total_pnl))
    print("Final Balance   : ${:.2f}".format(balance))
    print("Max Drawdown    : {:.2f}%".format(max_drawdown))
    print("Profit Factor   : {}".format(profit_factor))
    print("=" * 50)

    try:
        with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        print("Results saved to backtest_results.json")
    except Exception as e:
        print("Could not save results: {}".format(e))

    return results


if __name__ == '__main__':
    run_backtest()
