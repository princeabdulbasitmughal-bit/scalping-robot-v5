#!/usr/bin/env python3
"""
Scalping Robot V5 - Log Analyzer & Report Generator
Parses trader.log and trades.log to generate performance metrics and summaries.
"""

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Ensure UTF-8 output in Windows PowerShell / Command Prompt
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def parse_trader_log(log_path: Path, trades_log_path: Path = None) -> Dict[str, Any]:
    """
    Parses trader.log and extracts key trading and operational metrics:
      - Line counts for HEARTBEAT, SIGNAL, TRADE, ERROR, WARNING
      - Balance values from HEARTBEAT lines (max, min, range)
      - Signal distribution (BUY, SELL, HOLD)
      - Detailed trade information and breakdowns
    """
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = [line.rstrip("\r\n") for line in f]

    total_lines = len(lines)

    # Metrics collectors
    heartbeat_lines = 0
    signal_lines = 0
    trade_lines = 0
    error_lines = 0
    warning_lines = 0
    critical_lines = 0

    balances: List[float] = []
    heartbeat_signals: Dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
    all_signals: Dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}

    # Trade activity counters
    new_positions_count = 0
    trades_closed_count = 0
    risk_loss_count = 0
    risk_win_count = 0

    # Detailed trade pnl records from trader.log
    trade_pnls: List[Dict[str, Any]] = []

    for line in lines:
        if not line.strip():
            continue

        # Split logger prefix to separate message content from logger name
        # Format: YYYY-MM-DD HH:MM:SS,mmm [LEVEL] LoggerName: Message
        match = re.match(
            r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?)\s+\[(\w+)\]\s+([^:]+):\s*(.*)$",
            line,
        )
        if match:
            timestamp_str, level, logger_name, message = match.groups()
        else:
            timestamp_str, level, logger_name, message = "", "UNKNOWN", "", line

        level_upper = level.upper()
        msg_upper = message.upper()

        # 1. HEARTBEAT lines
        is_hb = "HEARTBEAT" in msg_upper or "HEARTBEAT" in line.upper()
        if is_hb:
            heartbeat_lines += 1

            # Extract balance: balance=$10000.00
            bal_match = re.search(r"balance=\$?([0-9,]+(?:\.[0-9]+)?)", message, re.IGNORECASE)
            if bal_match:
                try:
                    val = float(bal_match.group(1).replace(",", ""))
                    balances.append(val)
                except ValueError:
                    pass

            # Extract signal from heartbeat: signal=SELL
            sig_match = re.search(r"signal=([A-Za-z]+)", message, re.IGNORECASE)
            if sig_match:
                sig_val = sig_match.group(1).upper()
                if sig_val in heartbeat_signals:
                    heartbeat_signals[sig_val] += 1
                else:
                    heartbeat_signals[sig_val] = 1

                if sig_val in all_signals:
                    all_signals[sig_val] += 1
                else:
                    all_signals[sig_val] = 1

        # 2. SIGNAL lines
        # Matches explicit [SIGNAL FIRED], [SIGNAL SUPPRESSED], or heartbeat signal lines
        is_signal_fired = "[SIGNAL" in msg_upper
        is_signal_line = is_signal_fired or ("SIGNAL=" in msg_upper) or (bool(re.search(r"\bsignal\b", message, re.IGNORECASE)) and not is_hb)
        if is_signal_fired or ("SIGNAL=" in msg_upper):
            signal_lines += 1

        if is_signal_fired:
            # Check if BUY/SELL/HOLD in signal fired line: e.g. "→ BUY" or "-> SELL" or "T2-EMA-BUY"
            arrow_match = re.search(r"(?:→|->|to)\s*([A-Za-z]+)", message)
            if arrow_match:
                sig_val = arrow_match.group(1).upper()
                if sig_val in ("BUY", "SELL", "HOLD"):
                    all_signals[sig_val] = all_signals.get(sig_val, 0) + 1
            else:
                for s in ("BUY", "SELL", "HOLD"):
                    if f"-{s}" in msg_upper or f" {s}" in msg_upper:
                        all_signals[s] = all_signals.get(s, 0) + 1
                        break

        # 3. TRADE lines
        # In ScalpingRobotV5, trades are [NEW POSITION - SIM/LIVE] and [TRADE CLOSED]
        is_new_pos = "[NEW POSITION" in msg_upper
        is_closed = "[TRADE CLOSED]" in msg_upper or "[TRADE" in msg_upper
        is_trade_event = is_new_pos or is_closed or ("[RISK] TRADE" in msg_upper)
        if is_trade_event:
            trade_lines += 1

        if is_new_pos:
            new_positions_count += 1
        if is_closed:
            trades_closed_count += 1
            # Try parsing closed trade details:
            # [TRADE CLOSED] SELL | SL_HIT | PnL: $-300.00 | Balance: $9,700.00
            pnl_match = re.search(r"PnL:\s*([+-]?\$?[-+]?[0-9,]+(?:\.[0-9]+)?)", message)
            reason_match = re.search(r"(TP_HIT|SL_HIT|MANUAL|TRAILING_SL)", message)
            side_match = re.search(r"\[TRADE CLOSED\]\s*(BUY|SELL)", message)
            if pnl_match:
                pnl_raw = pnl_match.group(1).replace("$", "").replace(",", "")
                try:
                    pnl_val = float(pnl_raw)
                    trade_pnls.append({
                        "side": side_match.group(1) if side_match else "UNKNOWN",
                        "reason": reason_match.group(1) if reason_match else "UNKNOWN",
                        "pnl": pnl_val,
                        "timestamp": timestamp_str
                    })
                except ValueError:
                    pass

        if "[RISK] TRADE LOSS" in msg_upper:
            risk_loss_count += 1
        if "[RISK] TRADE WIN" in msg_upper:
            risk_win_count += 1

        # 4. ERROR lines
        # Check for [ERROR] level, WinError, or explicit error in message
        is_error = (level_upper == "ERROR") or bool(re.search(r"\bWinError\b|\bException\b|\[ERROR\]", message, re.IGNORECASE))
        if is_error:
            error_lines += 1

        # 5. WARNING lines
        is_warning = (level_upper == "WARNING") or ("WARNING" in msg_upper)
        if is_warning:
            warning_lines += 1

        if level_upper == "CRITICAL" or "[CRITICAL]" in line.upper():
            critical_lines += 1

    # Balance calculations
    if balances:
        max_balance = round(max(balances), 2)
        min_balance = round(min(balances), 2)
        balance_range = round(max_balance - min_balance, 2)
    else:
        max_balance = 0.0
        min_balance = 0.0
        balance_range = 0.0

    # Read trades.log if provided or exists
    trades_log_data = {"exists": False, "total_lines": 0, "positions_opened": 0, "trades_closed": 0}
    if trades_log_path and trades_log_path.exists():
        try:
            with open(trades_log_path, "r", encoding="utf-8", errors="replace") as tf:
                tlines = [l.strip() for l in tf if l.strip()]
            trades_log_data["exists"] = True
            trades_log_data["total_lines"] = len(tlines)
            trades_log_data["positions_opened"] = sum(1 for l in tlines if "[NEW POSITION" in l.upper())
            trades_log_data["trades_closed"] = sum(1 for l in tlines if "[TRADE CLOSED]" in l.upper())
        except Exception as e:
            trades_log_data["error"] = str(e)

    # Build summary dictionary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_lines_analyzed": total_lines,
        # Direct counts requested by prompt
        "heartbeat_lines": heartbeat_lines,
        "signal_lines": signal_lines,
        "trade_lines": trade_lines,
        "error_lines": error_lines,
        "warning_lines": warning_lines,
        # Nested counts object
        "counts": {
            "HEARTBEAT": heartbeat_lines,
            "SIGNAL": signal_lines,
            "TRADE": trade_lines,
            "ERROR": error_lines,
            "WARNING": warning_lines,
            "CRITICAL": critical_lines
        },
        # Balance metrics
        "balances": balances,
        "max_balance": max_balance,
        "min_balance": min_balance,
        "balance_range": balance_range,
        # Signal distributions
        "signal_distribution": {
            "BUY": all_signals.get("BUY", 0),
            "SELL": all_signals.get("SELL", 0),
            "HOLD": all_signals.get("HOLD", 0)
        },
        "heartbeat_signals": {
            "BUY": heartbeat_signals.get("BUY", 0),
            "SELL": heartbeat_signals.get("SELL", 0),
            "HOLD": heartbeat_signals.get("HOLD", 0)
        },
        # Trade breakdown
        "trade_breakdown": {
            "new_positions": new_positions_count,
            "trades_closed": trades_closed_count,
            "risk_losses_recorded": risk_loss_count,
            "risk_wins_recorded": risk_win_count,
            "closed_trades_pnl": trade_pnls
        },
        "trades_log": trades_log_data
    }

    return summary


def print_summary(summary: Dict[str, Any]) -> None:
    """Prints a clean, human-readable terminal report."""
    counts = summary["counts"]
    sig_dist = summary["signal_distribution"]
    hb_sig = summary["heartbeat_signals"]
    trades = summary["trade_breakdown"]
    trades_log = summary["trades_log"]

    print("=" * 65)
    print("      SCALPING ROBOT V5 PRO - LOG ANALYSIS & PERFORMANCE REPORT")
    print("=" * 65)
    print(f"Timestamp:              {summary['timestamp']}")
    print(f"Total Lines Analyzed:   {summary['total_lines_analyzed']}")
    print("-" * 65)
    print("LINE CATEGORY COUNTS:")
    print(f"  * HEARTBEAT lines:    {counts['HEARTBEAT']}")
    print(f"  * SIGNAL lines:       {counts['SIGNAL']}")
    print(f"  * TRADE lines:        {counts['TRADE']} (Positions: {trades['new_positions']}, Closed: {trades['trades_closed']})")
    print(f"  * ERROR lines:        {counts['ERROR']}")
    print(f"  * WARNING lines:      {counts['WARNING']}")
    print(f"  * CRITICAL lines:     {counts.get('CRITICAL', 0)}")
    print("-" * 65)
    print("BALANCE METRICS (from HEARTBEAT):")
    print(f"  * Extracted Balances: {summary['balances']}")
    print(f"  * Max Balance:        ${summary['max_balance']:,.2f}")
    print(f"  * Min Balance:        ${summary['min_balance']:,.2f}")
    print(f"  * Balance Range:      ${summary['balance_range']:,.2f}")
    print("-" * 65)
    print("SIGNAL DISTRIBUTION:")
    print(f"  * Overall Signals:    BUY: {sig_dist['BUY']} | SELL: {sig_dist['SELL']} | HOLD: {sig_dist['HOLD']}")
    print(f"  * Heartbeat Signals:  BUY: {hb_sig['BUY']} | SELL: {hb_sig['SELL']} | HOLD: {hb_sig['HOLD']}")
    print("-" * 65)
    print("TRADE ACTIVITY BREAKDOWN:")
    print(f"  * Positions Opened:   {trades['new_positions']}")
    print(f"  * Trades Closed:      {trades['trades_closed']}")
    print(f"  * Risk Loss Events:   {trades['risk_losses_recorded']}")
    print(f"  * Risk Win Events:    {trades['risk_wins_recorded']}")
    if trades["closed_trades_pnl"]:
        print("  * Closed Trades Details:")
        for idx, t in enumerate(trades["closed_trades_pnl"], 1):
            pnl_sign = "+" if t['pnl'] > 0 else ""
            print(f"      {idx}. {t['side']} | {t['reason']} | PnL: {pnl_sign}${t['pnl']:.2f}")
    if trades_log["exists"]:
        print(f"  * trades.log stats:   {trades_log['total_lines']} entries ({trades_log['positions_opened']} opened, {trades_log['trades_closed']} closed)")
    print("=" * 65)


def main():
    base_dir = Path(__file__).resolve().parent
    trader_log_path = base_dir / "trader.log"
    trades_log_path = base_dir / "trades.log"
    output_summary_path = base_dir / "log_summary.json"

    # Allow custom path via arguments if desired
    if len(sys.argv) > 1:
        trader_log_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        output_summary_path = Path(sys.argv[2])

    summary = parse_trader_log(trader_log_path, trades_log_path)

    # Write summary to log_summary.json
    with open(output_summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Print readable summary
    print_summary(summary)
    print(f"[OK] Summary successfully written to {output_summary_path}\n")


if __name__ == "__main__":
    main()
