#!/usr/bin/env python3
"""
Scalping Robot V5 - Performance Monitor
Monitors live trading metrics, grades performance, triggers alerts,
and generates performance reports every 10 minutes.
"""

import os
import sys
import json
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

# File Paths
BASE_DIR = Path(__file__).resolve().parent
STATUS_FILE = BASE_DIR / "live_status.json"
REPORT_FILE = BASE_DIR / "performance_report.txt"
LOG_FILE = BASE_DIR / "monitor.log"

# Configure Logging to file and console
logger = logging.getLogger("PerformanceMonitor")
logger.setLevel(logging.INFO)

# Avoid duplicate handlers if reloaded
if not logger.handlers:
    # File handler
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)


def calculate_grade(win_rate: float) -> str:
    """
    Computes performance grade based on win rate:
      - A+ if win_rate > 90
      - A  if win_rate > 85
      - B  if win_rate > 75 (or >= 75)
      - C  if win_rate < 75
    """
    if win_rate > 90.0:
        return "A+"
    elif win_rate > 85.0:
        return "A"
    elif win_rate >= 75.0:
        return "B"
    else:
        return "C"


def evaluate_and_report() -> bool:
    """
    Reads live_status.json, evaluates performance metrics,
    logs alerts if thresholds are breached, and outputs performance_report.txt.
    """
    logger.info("Starting performance evaluation cycle...")

    if not STATUS_FILE.exists():
        msg = f"Status file not found at {STATUS_FILE}"
        logger.error(msg)
        return False

    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read/parse {STATUS_FILE}: {e}")
        return False

    # Extract metrics
    status = data.get("status", "UNKNOWN")
    account_mode = data.get("account_mode", "UNKNOWN")
    broker_name = data.get("broker_name", "N/A")
    account_id = data.get("account_id", data.get("broker_login", "N/A"))
    symbol = data.get("symbol", "N/A")
    current_price = data.get("current_price", 0.0)
    balance = data.get("balance", 0.0)
    equity = data.get("equity", 0.0)
    margin_free = data.get("margin_free", 0.0)
    daily_pnl = float(data.get("daily_pnl", 0.0))
    total_trades = data.get("total_trades", 0)

    # Win rate parsing (handles win_rate or win_rate_pct)
    raw_win_rate = data.get("win_rate", data.get("win_rate_pct", 0.0))
    win_rate = float(raw_win_rate)
    # If represented as a ratio <= 1.0 (e.g. 0.905), convert to percentage
    if 0.0 < win_rate <= 1.0 and total_trades > 0:
        win_rate *= 100.0

    grade = calculate_grade(win_rate)

    alerts = []

    # Check alert conditions
    # Requirement 5: Alert if win_rate < 75: log 'ALERT: Win rate below 75%'
    if win_rate < 75.0:
        alert_msg = "ALERT: Win rate below 75%"
        logger.warning(alert_msg)
        alerts.append(f"{alert_msg} (Current: {win_rate:.2f}%)")

    # Requirement 6: Alert if daily_pnl < -100: log 'ALERT: Daily loss >$100'
    if daily_pnl < -100.0:
        alert_msg = "ALERT: Daily loss >$100"
        logger.warning(alert_msg)
        alerts.append(f"{alert_msg} (Current: ${daily_pnl:.2f})")

    logger.info(
        f"Metrics parsed: Daily PnL: ${daily_pnl:.2f} | "
        f"Win Rate: {win_rate:.2f}% | Grade: {grade} | Total Trades: {total_trades}"
    )

    open_positions = data.get("open_positions", [])
    open_positions_count = data.get("open_positions_count", len(open_positions))
    latency_metrics = data.get("latency_metrics", {})
    updated_at = data.get("updated_at", datetime.utcnow().isoformat() + "Z")
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Generate Performance Report Content
    report_lines = [
        "=" * 80,
        "                   SCALPING ROBOT V5 - PERFORMANCE REPORT                   ",
        "=" * 80,
        f"Report Generated At : {current_time_str}",
        f"Status Updated At   : {updated_at}",
        f"Robot Status        : {status}",
        f"Account Mode        : {account_mode}",
        f"Account ID          : {account_id}",
        f"Broker              : {broker_name}",
        f"Active Symbol       : {symbol}",
        f"Current Price       : {current_price:.2f}" if isinstance(current_price, (int, float)) else f"Current Price       : {current_price}",
        "-" * 80,
        "                            PERFORMANCE & GRADING                           ",
        "-" * 80,
        f"Performance Grade   : {grade}",
        f"Win Rate            : {win_rate:.2f}%",
        f"Daily PnL           : ${daily_pnl:.2f}",
        f"Total Trades        : {total_trades}",
        f"Balance             : ${balance:.2f}" if isinstance(balance, (int, float)) else f"Balance             : {balance}",
        f"Equity              : ${equity:.2f}" if isinstance(equity, (int, float)) else f"Equity              : {equity}",
        f"Free Margin         : ${margin_free:.2f}" if isinstance(margin_free, (int, float)) else f"Free Margin         : {margin_free}",
        "-" * 80,
        "                                ACTIVE ALERTS                               ",
        "-" * 80,
    ]

    if alerts:
        for alert in alerts:
            report_lines.append(f"  [!] {alert}")
    else:
        report_lines.append("  [OK] No active alerts. All performance parameters within normal limits.")

    report_lines.extend([
        "-" * 80,
        f"                           OPEN POSITIONS ({open_positions_count})                          ",
        "-" * 80,
    ])

    if open_positions:
        for idx, pos in enumerate(open_positions, 1):
            pos_id = pos.get("id", "N/A")
            pos_sym = pos.get("symbol", symbol)
            pos_type = pos.get("type", "N/A")
            pos_lot = pos.get("lot_size", "N/A")
            pos_entry = pos.get("entry", "N/A")
            pos_sl = pos.get("sl", "N/A")
            pos_tp = pos.get("tp", "N/A")
            report_lines.append(
                f"  {idx}. [{pos_sym}] {pos_type:<4} | Lots: {pos_lot} | Entry: {pos_entry} | SL: {pos_sl} | TP: {pos_tp} | ID: {pos_id}"
            )
    else:
        report_lines.append("  No open positions at this time.")

    if latency_metrics:
        report_lines.extend([
            "-" * 80,
            "                            SYSTEM & LATENCY                                ",
            "-" * 80,
            f"Tick to Signal Latency  : {latency_metrics.get('tick_to_signal_us', 'N/A')} us",
            f"Signal to Dispatch Latency: {latency_metrics.get('signal_to_dispatch_us', 'N/A')} us",
            f"Order Execution Latency : {latency_metrics.get('order_execution_ms', 'N/A')} ms",
            f"Dynamic Slippage Points : {latency_metrics.get('dynamic_slippage_points', 'N/A')}",
            f"Ticks Processed         : {latency_metrics.get('ticks_processed', 'N/A')}",
        ])

    report_lines.extend([
        "=" * 80,
        ""
    ])

    report_content = "\n".join(report_lines)

    # Write report to performance_report.txt
    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as rf:
            rf.write(report_content)
        logger.info(f"Performance report successfully written to {REPORT_FILE}")
    except Exception as e:
        logger.error(f"Failed to write performance report to {REPORT_FILE}: {e}")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Scalping Robot V5 Performance Monitor")
    parser.add_argument("--once", action="store_true", help="Execute single evaluation check and exit")
    args = parser.parse_args()

    logger.info("Performance Monitor Service initialized.")

    if args.once:
        logger.info("Single execution mode (--once) triggered.")
        evaluate_and_report()
        sys.exit(0)

    # Infinite loop running every 10 minutes (600 seconds)
    logger.info("Entering 10-minute infinite monitoring loop (time.sleep(600))...")
    while True:
        try:
            evaluate_and_report()
        except Exception as e:
            logger.error(f"Unexpected error in monitoring cycle: {e}", exc_info=True)

        logger.info("Sleeping for 600 seconds (10 minutes) until next evaluation...")
        time.sleep(600)


if __name__ == "__main__":
    main()
