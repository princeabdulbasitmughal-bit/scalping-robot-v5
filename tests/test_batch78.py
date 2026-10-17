"""
tests/test_batch78.py
Batch 78 Unit Tests: Performance Monitor (performance_monitor.py) & Log Analyzer (log_analyzer.py).
Expands test baseline beyond 1,027+ passing tests.
Verifies:
1. performance_monitor: calculate_grade exact boundary checks and Inf/NaN safety.
2. performance_monitor: _safe_float conversion with non-finite values and fallbacks.
3. performance_monitor: evaluate_and_report missing status file error handling.
4. performance_monitor: evaluate_and_report decimal ratio to percentage conversion (0.885 -> 88.50%).
5. performance_monitor: evaluate_and_report win-rate and daily-loss alert triggers.
6. performance_monitor: evaluate_and_report open positions table and latency metrics report rendering.
7. log_analyzer: parse_trader_log FileNotFoundError on non-existent path.
8. log_analyzer: parse_trader_log heartbeat balance parsing (with commas/dollars) and signal extraction.
9. log_analyzer: parse_trader_log closed trade PnL, reason, and side parsing.
10. log_analyzer: trades_log cross-file aggregation and print_summary report generation.
"""

import io
import json
import math
from pathlib import Path
import pytest

from performance_monitor import calculate_grade, _safe_float, evaluate_and_report
from log_analyzer import parse_trader_log, print_summary


def test_perf_monitor_calculate_grade_boundaries_and_inf_nan():
    """Verify calculate_grade evaluates boundary values and safely rejects Inf/NaN."""
    # 1. Standard boundaries
    assert calculate_grade(95.0) == "A+"
    assert calculate_grade(90.01) == "A+"
    assert calculate_grade(90.0) == "A"
    assert calculate_grade(85.01) == "A"
    assert calculate_grade(85.0) == "B"
    assert calculate_grade(75.0) == "B"
    assert calculate_grade(74.99) == "C"
    assert calculate_grade(50.0) == "C"

    # 2. Non-finite and invalid inputs default to 'C'
    assert calculate_grade(float("nan")) == "C"
    assert calculate_grade(float("inf")) == "C"
    assert calculate_grade(-float("inf")) == "C"
    assert calculate_grade(None) == "C"
    assert calculate_grade("invalid") == "C"


def test_perf_monitor_safe_float_conversions():
    """Verify _safe_float converts finite numbers and returns defaults for invalid inputs."""
    # 1. Valid conversions
    assert _safe_float(42.5) == 42.5
    assert _safe_float("100.25") == 100.25
    assert _safe_float(10) == 10.0

    # 2. Non-finite values return default
    assert _safe_float(float("nan"), default=5.0) == 5.0
    assert _safe_float(float("inf"), default=10.0) == 10.0
    assert _safe_float(-float("inf"), default=-1.0) == -1.0
    assert _safe_float(None, default=0.0) == 0.0
    assert _safe_float("corrupt_string", default=99.0) == 99.0


def test_perf_monitor_evaluate_and_report_missing_file(tmp_path):
    """Verify evaluate_and_report returns False when status file is missing."""
    missing_status = tmp_path / "does_not_exist.json"
    report_file = tmp_path / "report.txt"

    success = evaluate_and_report(status_file=missing_status, report_file=report_file)
    assert success is False
    assert not report_file.exists()


def test_perf_monitor_evaluate_and_report_win_rate_ratio_conversion(tmp_path):
    """Verify evaluate_and_report converts ratio win rates (<=1.0) to percentages."""
    status_file = tmp_path / "live_status.json"
    report_file = tmp_path / "performance_report.txt"

    status_file.write_text(
        json.dumps({
            "status": "ACTIVE_SCALPING",
            "symbol": "XAUUSD",
            "balance": 10500.0,
            "equity": 10500.0,
            "daily_pnl": 50.0,
            "win_rate": 0.885,  # Ratio format
            "total_trades": 10,
        }),
        encoding="utf-8"
    )

    success = evaluate_and_report(status_file=status_file, report_file=report_file)
    assert success is True
    assert report_file.exists()

    report_content = report_file.read_text(encoding="utf-8")
    assert "Win Rate            : 88.50%" in report_content
    assert "Performance Grade   : A" in report_content


def test_perf_monitor_evaluate_and_report_alerts_generation(tmp_path):
    """Verify evaluate_and_report writes active alert warnings when thresholds are breached."""
    status_file = tmp_path / "live_status.json"
    report_file = tmp_path / "performance_report.txt"

    status_file.write_text(
        json.dumps({
            "status": "ACTIVE_SCALPING",
            "symbol": "XAUUSD",
            "balance": 9800.0,
            "equity": 9800.0,
            "daily_pnl": -150.0,  # Below -100 trigger
            "win_rate_pct": 68.0,  # Below 75% trigger
            "total_trades": 8,
        }),
        encoding="utf-8"
    )

    success = evaluate_and_report(status_file=status_file, report_file=report_file)
    assert success is True

    report_content = report_file.read_text(encoding="utf-8")
    assert "[!] ALERT: Win rate below 75%" in report_content
    assert "[!] ALERT: Daily loss >$100" in report_content
    assert "Performance Grade   : C" in report_content


def test_perf_monitor_evaluate_and_report_open_positions_and_latency(tmp_path):
    """Verify evaluate_and_report renders positions table and system latency sections."""
    status_file = tmp_path / "live_status.json"
    report_file = tmp_path / "performance_report.txt"

    status_file.write_text(
        json.dumps({
            "status": "ACTIVE_SCALPING",
            "symbol": "XAUUSD",
            "balance": 10000.0,
            "equity": 10025.0,
            "open_positions": [
                {"id": "POS-001", "symbol": "XAUUSD", "type": "BUY", "lot_size": 0.02, "entry": 2650.0, "sl": 2640.0, "tp": 2665.0},
                {"id": "POS-002", "symbol": "XAUUSD", "type": "SELL", "lot_size": 0.02, "entry": 2652.5, "sl": 2660.0, "tp": 2640.0},
            ],
            "latency_metrics": {
                "tick_to_signal_us": 45.2,
                "signal_to_dispatch_us": 12.8,
                "order_execution_ms": 1.25,
                "ticks_processed": 150000,
            },
        }),
        encoding="utf-8"
    )

    success = evaluate_and_report(status_file=status_file, report_file=report_file)
    assert success is True

    report_content = report_file.read_text(encoding="utf-8")
    assert "OPEN POSITIONS (2)" in report_content
    assert "POS-001" in report_content
    assert "POS-002" in report_content
    assert "Tick to Signal Latency  : 45.2 us" in report_content
    assert "Order Execution Latency : 1.25 ms" in report_content


def test_log_analyzer_parse_trader_log_missing_file_raises(tmp_path):
    """Verify parse_trader_log raises FileNotFoundError when target log does not exist."""
    missing_log = tmp_path / "missing_trader.log"
    with pytest.raises(FileNotFoundError):
        parse_trader_log(missing_log)


def test_log_analyzer_parse_trader_log_balance_and_signals(tmp_path):
    """Verify parse_trader_log parses formatted balance amounts and signals from heartbeats."""
    log_file = tmp_path / "trader.log"
    log_file.write_text(
        "2026-10-17 12:00:00,100 [INFO] Trader: HEARTBEAT | balance=$10,250.75 | signal=BUY\n"
        "2026-10-17 12:01:00,100 [INFO] Trader: HEARTBEAT | balance=$10,300.00 | signal=HOLD\n"
        "2026-10-17 12:02:00,100 [INFO] SignalEngine: [SIGNAL FIRED] T2-EMA -> SELL\n",
        encoding="utf-8"
    )

    summary = parse_trader_log(log_file)
    assert summary["counts"]["HEARTBEAT"] == 2
    assert summary["counts"]["SIGNAL"] >= 1
    assert summary["balances"] == [10250.75, 10300.0]
    assert summary["max_balance"] == 10300.0
    assert summary["min_balance"] == 10250.75
    assert summary["signal_distribution"]["BUY"] >= 1
    assert summary["signal_distribution"]["SELL"] >= 1


def test_log_analyzer_parse_trader_log_closed_trade_pnl(tmp_path):
    """Verify parse_trader_log extracts side, reason, and PnL from closed trade records."""
    log_file = tmp_path / "trader.log"
    log_file.write_text(
        "2026-10-17 14:00:00,500 [INFO] LiveTrader: [NEW POSITION - LIVE] BUY 0.02 XAUUSD @ 2650.0\n"
        "2026-10-17 14:05:00,500 [INFO] LiveTrader: [TRADE CLOSED] BUY | TP_HIT | PnL: $+65.50 | Balance: $10,065.50\n"
        "2026-10-17 14:10:00,500 [INFO] LiveTrader: [TRADE CLOSED] SELL | SL_HIT | PnL: $-45.00 | Balance: $10,020.50\n",
        encoding="utf-8"
    )

    summary = parse_trader_log(log_file)
    breakdown = summary["trade_breakdown"]
    assert breakdown["new_positions"] == 1
    assert breakdown["trades_closed"] == 2
    assert len(breakdown["closed_trades_pnl"]) == 2

    trade_1 = breakdown["closed_trades_pnl"][0]
    assert trade_1["side"] == "BUY"
    assert trade_1["reason"] == "TP_HIT"
    assert trade_1["pnl"] == 65.50

    trade_2 = breakdown["closed_trades_pnl"][1]
    assert trade_2["side"] == "SELL"
    assert trade_2["reason"] == "SL_HIT"
    assert trade_2["pnl"] == -45.00


def test_log_analyzer_trades_log_integration_and_print_summary(tmp_path, capsys):
    """Verify parse_trader_log incorporates trades.log metrics and print_summary executes cleanly."""
    trader_log = tmp_path / "trader.log"
    trades_log = tmp_path / "trades.log"

    trader_log.write_text(
        "2026-10-17 15:00:00,000 [INFO] ScalpingRobot: HEARTBEAT | balance=$10000.0 | signal=HOLD\n",
        encoding="utf-8"
    )

    trades_log.write_text(
        "2026-10-17 15:01:00 [INFO] [NEW POSITION - SIM] BUY 0.02 @ 2650.0\n"
        "2026-10-17 15:05:00 [INFO] [TRADE CLOSED] BUY | TP_HIT | PnL: $+50.0\n",
        encoding="utf-8"
    )

    summary = parse_trader_log(trader_log, trades_log_path=trades_log)
    assert summary["trades_log"]["exists"] is True
    assert summary["trades_log"]["positions_opened"] == 1
    assert summary["trades_log"]["trades_closed"] == 1

    # Verify print_summary runs without errors
    print_summary(summary)
    captured = capsys.readouterr()
    assert "LOG ANALYSIS & PERFORMANCE REPORT" in captured.out
    assert "HEARTBEAT lines:" in captured.out
