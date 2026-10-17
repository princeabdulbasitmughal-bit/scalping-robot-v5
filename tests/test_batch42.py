"""
tests/test_batch42.py - Comprehensive Unit Tests for Batch 42 Components:
1. wave61_opening_range_breakout (OpeningRangeBreakout): window tracking, breakout triggers, and range calculation
2. wave61_opening_range_breakout (Session Rollover & BlockResult): multi-day session rollover and BlockResult interface
3. wave12_telegram_alerts (TelegramAlerter): custom sender dispatch, rate limiting, and config updates
4. wave12_telegram_alerts (Formatted Alerts): trade open, trade close, circuit breaker, and daily summary formatting
5. wave13_ml_predictor (LinearRegressor): OLS 1-D linear regression, slope, R^2, and input sanitization
6. wave13_ml_predictor (MLPredictor): direction prediction, signal agreement, accuracy tracking, and outcome recording
7. wave14_auto_tuner (AutoTuner Rules): trade history analysis, low win rate, profit factor, and timeout suggestions
8. wave14_auto_tuner (Safe Persistence): balance sanity floor, atomic file write, dry-run, and timer tracking
9. alert_system (AlertSystem): evaluation of 6 alert conditions, rate limiting, and alert status generation
10. trade_journal & support modules (TradeJournal, GoldNewsFetcher, AutoBackup, LogAnalyzer): end-to-end integration
"""

import os
import json
import time
import math
import threading
from datetime import datetime, timezone, date
from pathlib import Path
import pytest

from wave61_opening_range_breakout import OpeningRangeBreakout, BlockResult
from wave12_telegram_alerts import TelegramAlerter
from wave13_ml_predictor import LinearRegressor, MLPredictor
from wave14_auto_tuner import AutoTuner
from alert_system import AlertSystem
from trade_journal import TradeJournal
from gold_news_fetcher import check_high_impact
from auto_backup import cleanup_old_backups
from log_analyzer import parse_trader_log


def test_wave61_opening_range_breakout_window_and_breakout():
    """Verify OpeningRangeBreakout builds range during session open and filters breakouts correctly."""
    orb = OpeningRangeBreakout(min_ticks=10, window_seconds=1800)
    orb.reset()

    # Outside window or before completion -> should not block
    assert orb.is_signal_blocked("BUY") == BlockResult(False, "window_not_complete")

    # London open: 08:00 UTC
    dt_open = datetime(2026, 10, 20, 8, 2, tzinfo=timezone.utc)
    # Feed 12 ticks during first 30 minutes (prices between 2400.0 and 2410.0)
    for i in range(12):
        p = 2400.0 + (i % 5) * 2.5  # 2400.0, 2402.5, 2405.0, 2407.5, 2410.0
        orb.update(p, now_dt=dt_open)

    info_mid = orb.info()
    assert info_mid["in_window"] is True
    assert info_mid["window_complete"] is False
    assert info_mid["or_high"] == 2410.0
    assert info_mid["or_low"] == 2400.0
    assert info_mid["range_pips"] == 100.0

    # Advance time past 30-min window (08:35 UTC)
    dt_post = datetime(2026, 10, 20, 8, 35, tzinfo=timezone.utc)
    orb.update(2405.0, now_dt=dt_post)

    info_post = orb.info()
    assert info_post["window_complete"] is True
    assert info_post["in_window"] is False

    # After window complete:
    # BUY at 2408.0 (<= 2410.0 high) -> BLOCKED
    res_buy_blocked = orb.is_signal_blocked("BUY", price=2408.0)
    assert bool(res_buy_blocked) is True
    assert res_buy_blocked.reason == "price_not_above_or_high"
    assert orb.is_entry_blocked("BUY", price=2408.0) is True

    # BUY at 2412.0 (> 2410.0 high) -> ALLOWED (breakout confirmed)
    res_buy_allowed = orb.is_signal_blocked("BUY", price=2412.0)
    assert bool(res_buy_allowed) is False
    assert res_buy_allowed.reason == "breakout_confirmed"

    # SELL at 2405.0 (>= 2400.0 low) -> BLOCKED
    res_sell_blocked = orb.is_signal_blocked("SELL", price=2405.0)
    assert bool(res_sell_blocked) is True
    assert res_sell_blocked.reason == "price_not_below_or_low"

    # SELL at 2398.0 (< 2400.0 low) -> ALLOWED
    res_sell_allowed = orb.is_signal_blocked("SELL", price=2398.0)
    assert bool(res_sell_allowed) is False
    assert res_sell_allowed.reason == "breakout_confirmed"


def test_wave61_opening_range_breakout_session_rollover_and_block_result():
    """Verify session rollover across London and NY and validate BlockResult polymorphism."""
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)
    orb.reset()

    # 1. London session
    dt_london = datetime(2026, 10, 20, 8, 5, tzinfo=timezone.utc)
    for p in [2400.0, 2405.0, 2410.0, 2402.0, 2408.0]:
        orb.update(p, now_dt=dt_london)

    assert orb.info()["in_window"] is True
    assert orb.info()["or_high"] == 2410.0

    # 2. NY session open at 13:02 UTC triggers reset
    dt_ny = datetime(2026, 10, 20, 13, 2, tzinfo=timezone.utc)
    orb.update(2420.0, now_dt=dt_ny)

    info_ny = orb.info()
    assert info_ny["in_window"] is True
    assert info_ny["window_complete"] is False
    assert info_ny["tick_count"] == 1
    assert info_ny["or_high"] == 2420.0
    assert info_ny["or_low"] == 2420.0

    # 3. BlockResult polymorphism tests
    res = BlockResult(True, "price_not_above_or_high")
    assert bool(res) is True
    assert int(res) == 1
    assert res[0] is True
    assert res[1] == "price_not_above_or_high"
    with pytest.raises(IndexError):
        _ = res[2]

    # Unpackable as 2-tuple
    blocked, reason = res
    assert blocked is True
    assert reason == "price_not_above_or_high"
    assert "BlockResult(True" in repr(res)

    # Corrupted / invalid prices in update
    orb.update(None)
    orb.update("invalid")
    orb.update(float("nan"))
    orb.update(-50.0)
    assert orb.info()["tick_count"] == 1


def test_wave12_telegram_alerter_custom_sender_and_rate_limiting(tmp_path):
    """Verify TelegramAlerter with custom sender_fn, rate limiting, and config overrides."""
    sent_payloads = []
    send_event = threading.Event()

    def mock_sender(msg: str) -> bool:
        sent_payloads.append(msg)
        send_event.set()
        return True

    cfg_file = tmp_path / "test_telegram_config.json"
    alerter = TelegramAlerter(config_path=str(cfg_file), sender_fn=mock_sender)

    # Initially disabled
    assert alerter.send_alert("Test initial", force=False) is False
    assert len(sent_payloads) == 0

    # Enable and configure 60s min interval
    alerter.update_config({"enabled": True, "min_alert_interval_sec": 60}, persist=True)
    assert cfg_file.exists()

    # First send at t=100.0 -> succeeds
    send_event.clear()
    ok1 = alerter.send_alert("First Message", force=False, now_ts=100.0)
    assert ok1 is True
    send_event.wait(timeout=2.0)
    assert len(sent_payloads) == 1
    assert "First Message" in sent_payloads[0]

    # Second send at t=130.0 (< 60s interval) -> dropped by rate limiter
    ok2 = alerter.send_alert("Second Message", force=False, now_ts=130.0)
    assert ok2 is False
    assert len(sent_payloads) == 1

    # Forced send at t=130.0 -> bypasses rate limiter
    send_event.clear()
    ok3 = alerter.send_alert("Forced Message", force=True, now_ts=130.0)
    assert ok3 is True
    send_event.wait(timeout=2.0)
    assert len(sent_payloads) == 2

    # Stats check & reset
    stats = alerter.get_stats()
    assert stats["enabled"] is True
    assert stats["sent_count"] == 2
    assert stats["last_sent"] == 130.0

    alerter.reset()
    assert alerter.get_stats()["sent_count"] == 0


def test_wave12_telegram_alerter_formatted_messages(tmp_path):
    """Verify TelegramAlerter formatted notification helpers and payload contents."""
    sent_messages = []
    event = threading.Event()

    def mock_sender(msg: str):
        sent_messages.append(msg)
        event.set()
        return True

    alerter = TelegramAlerter(config_path=str(tmp_path / "cfg.json"), sender_fn=mock_sender)
    alerter.update_config({"enabled": True, "min_alert_interval_sec": 0})

    fixed_dt = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Trade Open
    event.clear()
    alerter.alert_trade_open(
        direction="BUY", entry=2400.50, sl=2395.00, tp=2410.00, lot=0.05,
        now_dt=fixed_dt, force=True
    )
    event.wait(timeout=2.0)
    assert any("BUY OPENED" in m and "2400.50" in m and "Lot: 0.05" in m for m in sent_messages)

    # 2. Trade Close
    event.clear()
    alerter.alert_trade_close(
        direction="BUY", pnl=75.25, reason="TP_HIT", balance=10250.00,
        now_dt=fixed_dt, force=True
    )
    event.wait(timeout=2.0)
    assert any("WIN CLOSED" in m and "$+75.25" in m and "TP_HIT" in m for m in sent_messages)

    # 3. Circuit Breaker
    event.clear()
    alerter.alert_circuit_breaker(
        reason="Daily drawdown limit breached", balance=9800.00, daily_pnl=-200.00,
        now_dt=fixed_dt
    )
    event.wait(timeout=2.0)
    assert any("CIRCUIT BREAKER FIRED" in m and "Daily drawdown" in m for m in sent_messages)

    # 4. Daily Summary
    event.clear()
    alerter.alert_daily_summary(
        balance=10500.00, daily_pnl=350.00, wins=7, losses=3, win_rate=70.0,
        total_trades=10, now_dt=fixed_dt
    )
    event.wait(timeout=2.0)
    assert any("DAILY SUMMARY" in m and "Grade: <b>A</b>" in m and "Win Rate: <b>70.0%</b>" in m for m in sent_messages)


def test_wave13_ml_linear_regressor():
    """Verify LinearRegressor handles clean linear trends, flatlines, and malformed inputs."""
    reg = LinearRegressor()

    # Empty or short data
    assert reg.fit([]) == {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}
    assert reg.fit([10.0, 20.0]) == {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}

    # Perfect uptrend: y = 10 + 5 * x
    res_up = reg.fit([10.0, 15.0, 20.0, 25.0, 30.0])
    assert pytest.approx(res_up["slope"], 0.001) == 5.0
    assert pytest.approx(res_up["intercept"], 0.001) == 10.0
    assert pytest.approx(res_up["r_squared"], 0.001) == 1.0

    # Perfect downtrend: y = 50 - 2 * x
    res_down = reg.fit([50.0, 48.0, 46.0, 44.0, 42.0])
    assert pytest.approx(res_down["slope"], 0.001) == -2.0
    assert pytest.approx(res_down["intercept"], 0.001) == 50.0
    assert pytest.approx(res_down["r_squared"], 0.001) == 1.0

    # Flatline prices
    res_flat = reg.fit([25.0, 25.0, 25.0, 25.0])
    assert pytest.approx(res_flat["slope"], 0.001) == 0.0
    assert pytest.approx(res_flat["r_squared"], 0.001) == 0.0

    # Robust against None, string, NaN, Inf
    res_dirty = reg.fit([10.0, None, "bad", float("nan"), 15.0, float("inf"), 20.0])
    assert pytest.approx(res_dirty["slope"], 0.001) == 5.0


def test_wave13_ml_predictor_signals_and_accuracy():
    """Verify MLPredictor direction prediction, signal agreement booster, and accuracy telemetry."""
    predictor = MLPredictor(window=10, min_r2=0.20)
    predictor.reset()

    # 1. Bullish sequence
    bullish_closes = [2400.0 + i * 1.5 for i in range(15)]
    pred_up = predictor.predict(bullish_closes)
    assert pred_up["direction"] == "UP"
    assert pred_up["confidence"] >= 50
    assert pred_up["slope"] > 0
    assert pred_up["r_squared"] > 0.90

    # Signal agreement: BUY agrees with UP
    agree_buy = predictor.predict_signal_agreement(bullish_closes, signal="BUY")
    assert agree_buy["agree"] is True
    assert agree_buy["boost"] > 1.0

    # Signal agreement: SELL disagrees with UP
    agree_sell = predictor.predict_signal_agreement(bullish_closes, signal="SELL")
    assert agree_sell["agree"] is False

    # 2. Bearish sequence
    bearish_closes = [2450.0 - i * 1.5 for i in range(15)]
    pred_down = predictor.predict(bearish_closes)
    assert pred_down["direction"] == "DOWN"
    assert pred_down["confidence"] >= 50

    # 3. Accuracy tracking
    predictor.record_outcome("UP", "UP")      # hit
    predictor.record_outcome("DOWN", "DOWN")  # hit
    predictor.record_outcome("UP", "DOWN")    # miss
    assert predictor.accuracy == 66.7

    info = predictor.info()
    assert info["total_checked"] == 3
    assert info["hit_count"] == 2
    assert info["accuracy_pct"] == 66.7

    predictor.reset()
    assert predictor.accuracy == 0.0
    assert predictor.last_prediction == {}


def test_wave14_auto_tuner_analysis_rules():
    """Verify AutoTuner evaluates trade history rules (win rate, profit factor, timeout, consec losses)."""
    tuner = AutoTuner()
    tuner.reset()

    # Rule: Insufficient trades (< 10)
    short_history = [{"pnl": 10.0, "exit_reason": "TP_HIT"} for _ in range(5)]
    rep_short = tuner.analyse(short_history)
    assert rep_short["status"] == "insufficient_data"
    assert rep_short["trades_analysed"] == 5

    # Base healthy config
    base_cfg = {
        "sl_pips": 30.0,
        "tp_pips": 45.0,
        "rr_ratio": 1.5,
        "max_lot_size": 0.10,
        "lot_size": 0.04,
        "max_daily_loss_usd": 200.0,
    }

    # Scenario 1: Low win rate (30% wins) -> suggest reducing SL
    low_wr_history = (
        [{"pnl": 20.0, "exit_reason": "TP_HIT"} for _ in range(3)] +
        [{"pnl": -30.0, "exit_reason": "SL_HIT"} for _ in range(7)]
    )
    rep_low_wr = tuner.analyse(low_wr_history, current_config=base_cfg)
    assert rep_low_wr["win_rate_pct"] == 30.0
    assert rep_low_wr["config_changed"] is True
    assert rep_low_wr["proposed_config"]["sl_pips"] < base_cfg["sl_pips"]
    assert any("Low win rate" in s for s in rep_low_wr["suggestions"])

    # Scenario 2: High timeout rate (> 40%) -> suggest reducing TP
    timeout_history = (
        [{"pnl": 5.0, "exit_reason": "TIMEOUT"} for _ in range(6)] +
        [{"pnl": 20.0, "exit_reason": "TP_HIT"} for _ in range(4)]
    )
    rep_timeout = tuner.analyse(timeout_history, current_config=base_cfg)
    assert rep_timeout["config_changed"] is True
    assert rep_timeout["proposed_config"]["tp_pips"] < base_cfg["tp_pips"]
    assert any("High timeout rate" in s for s in rep_timeout["suggestions"])

    # Scenario 3: Consecutive losses >= 5 -> suggest reducing daily loss limit
    consec_loss_history = (
        [{"pnl": -20.0, "exit_reason": "SL_HIT"} for _ in range(5)] +
        [{"pnl": 25.0, "exit_reason": "TP_HIT"} for _ in range(5)]
    )
    rep_consec = tuner.analyse(consec_loss_history, current_config=base_cfg)
    assert rep_consec["max_consec_losses"] == 5
    assert rep_consec["config_changed"] is True
    assert rep_consec["proposed_config"]["max_daily_loss_usd"] < base_cfg["max_daily_loss_usd"]


def test_wave14_auto_tuner_safe_persistence(tmp_path):
    """Verify AutoTuner.analyse_and_tune respects balance floor, dry_run, and atomic persistence."""
    cfg_path = tmp_path / "config.json"
    initial_cfg = {
        "sl_pips": 30.0,
        "tp_pips": 45.0,
        "lot_size": 0.05,
        "max_daily_loss_usd": 200.0,
        "max_lot_size": 0.10,
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(initial_cfg, f)

    tuner = AutoTuner(config_path=str(cfg_path))
    tuner.reset()

    # Generate 10 trades triggering low win rate
    trades = (
        [{"pnl": 15.0, "exit_reason": "TP_HIT"} for _ in range(2)] +
        [{"pnl": -25.0, "exit_reason": "SL_HIT"} for _ in range(8)]
    )

    # 1. Dry run: suggestions generated but config NOT written
    rep_dry = tuner.analyse_and_tune(trades, balance=5000.0, config_path=str(cfg_path), dry_run=True)
    assert rep_dry["config_changed"] is True
    with open(cfg_path, "r", encoding="utf-8") as f:
        saved_cfg = json.load(f)
    assert saved_cfg["sl_pips"] == 30.0  # unchanged

    # 2. Safety check: balance < $500 -> config NOT written
    rep_unsafe = tuner.analyse_and_tune(trades, balance=400.0, config_path=str(cfg_path), dry_run=False)
    assert rep_unsafe["config_changed"] is False
    with open(cfg_path, "r", encoding="utf-8") as f:
        saved_cfg2 = json.load(f)
    assert saved_cfg2["sl_pips"] == 30.0  # still unchanged

    # 3. Healthy balance -> config atomically updated
    rep_live = tuner.analyse_and_tune(trades, balance=2500.0, config_path=str(cfg_path), dry_run=False)
    assert rep_live["config_changed"] is True
    with open(cfg_path, "r", encoding="utf-8") as f:
        saved_cfg3 = json.load(f)
    assert saved_cfg3["sl_pips"] < 30.0
    assert tuner.get_seconds_since_last_run(now_ts=time.time() + 10.0) >= 10.0


def test_alert_system_evaluation_conditions(tmp_path):
    """Verify AlertSystem evaluates 6 distinct alert conditions and enforces 15-minute rate limiting."""
    status_file = tmp_path / "live_status.json"
    alerts_log = tmp_path / "alerts.log"
    alert_status = tmp_path / "alert_status.json"

    system = AlertSystem(
        status_file=status_file,
        alerts_log_file=alerts_log,
        alert_status_file=alert_status,
        check_interval=60,
        rate_limit_minutes=15,
    )

    # 1. Clean healthy status
    clean_data = {
        "status": "ACTIVE_SCALPING",
        "balance": 10000.0,
        "equity": 10000.0,
        "win_rate_pct": 75.0,
        "daily_pnl": 50.0,
        "open_positions_count": 2,
        "active_session": True,
        "last_trade_time": datetime.now(timezone.utc).isoformat(),
    }
    conds_clean, status_clean = system.evaluate_conditions(clean_data)
    assert len(conds_clean) == 0
    assert status_clean == "OK"

    # 2. Danger status: win rate < 70%, daily loss > 150, balance < 9800, positions > 4
    danger_data = {
        "status": "ACTIVE_SCALPING",
        "balance": 9750.0,
        "equity": 9400.0,  # 6% drawdown from peak 10000
        "win_rate_pct": 55.0,
        "total_trades": 10,
        "daily_pnl": -175.0,
        "open_positions_count": 5,
        "active_session": True,
        "last_trade_time": datetime.now(timezone.utc).isoformat(),
    }
    conds_danger, status_danger = system.evaluate_conditions(danger_data)
    assert status_danger == "CRITICAL"
    cond_types = {c["type"] for c in conds_danger}
    assert "win_rate_critical" in cond_types
    assert "daily_loss_danger" in cond_types
    assert "balance_critical" in cond_types
    assert "equity_drawdown" in cond_types
    assert "too_many_positions" in cond_types

    # 3. Fire alerts and test rate limiting
    fired1 = system.check_alerts(live_data=danger_data)
    assert len(fired1) > 0
    assert alerts_log.exists()
    assert alert_status.exists()

    # Immediate second check with identical data -> rate-limited (no new alerts logged)
    fired2 = system.check_alerts(live_data=danger_data)
    assert len(fired2) == 0


def test_trade_journal_and_support_modules(tmp_path):
    """Verify TradeJournal, GoldNewsFetcher keywords, AutoBackup cleanup, and LogAnalyzer parser."""
    # 1. TradeJournal
    db_file = str(tmp_path / "test_trades.db")
    journal = TradeJournal(db_path=db_file)

    sample_trade = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": "XAUUSD",
        "direction": "BUY",
        "entry_price": 2400.0,
        "exit_price": 2405.0,
        "lot_size": 0.05,
        "sl_price": 2395.0,
        "tp_price": 2410.0,
        "pnl": 25.0,
        "exit_reason": "TP_HIT",
        "duration_sec": 120,
        "signal_tier": 2,
        "spread_pips": 1.2,
    }
    assert journal.log_trade(sample_trade) is True
    recent_trades = journal.get_last_N_trades(5)
    assert len(recent_trades) == 1
    assert recent_trades[0]["direction"] == "BUY"
    assert recent_trades[0]["pnl"] == 25.0

    today_str = str(date.today())
    summary_data = {
        "date": today_str,
        "total_trades": 1,
        "wins": 1,
        "losses": 0,
        "win_rate": 100.0,
        "total_pnl": 25.0,
        "max_drawdown": 0.0,
        "best_trade": 25.0,
        "worst_trade": 25.0,
    }
    assert journal.log_daily_summary(summary_data) is True
    stats = journal.get_daily_stats(today_str)
    assert stats["total_pnl"] == 25.0
    assert stats["win_rate"] == 100.0

    # 2. GoldNewsFetcher keyword detection
    macro_headlines = [
        ("Federal Reserve signals interest rate hike", "Mon, 20 Oct 2026 10:00:00 GMT"),
        ("Local jewelry store updates catalog", "Mon, 20 Oct 2026 10:05:00 GMT"),
    ]
    is_impact, matched = check_high_impact(macro_headlines)
    assert is_impact is True
    assert "federal reserve" in matched.lower()

    benign_headlines = [
        ("Local craft fair opens in Dallas", "Mon, 20 Oct 2026 10:00:00 GMT"),
    ]
    is_benign, _ = check_high_impact(benign_headlines)
    assert is_benign is False

    # 3. AutoBackup retention pruning
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    # Create 14 dummy snapshot files across 14 timestamps
    for i in range(14):
        ts = f"20261020_{100000 + i:06d}"
        fpath = backups_dir / f"mt5_live_trader_{ts}.py"
        fpath.write_text(f"# Snapshot {i}", encoding="utf-8")

    assert len(list(backups_dir.iterdir())) == 14
    cleanup_old_backups(backups_dir=str(backups_dir), keep_last=10)
    remaining = list(backups_dir.iterdir())
    assert len(remaining) == 10

    # 4. LogAnalyzer parser
    log_file = tmp_path / "trader.log"
    log_file.write_text(
        "2026-10-20 12:00:00,000 [INFO] Trader: [HEARTBEAT] balance=$10,050.00 signal=BUY\n"
        "2026-10-20 12:01:00,000 [INFO] Trader: [SIGNAL FIRED] → BUY\n"
        "2026-10-20 12:02:00,000 [INFO] Trader: [NEW POSITION - LIVE] BUY 0.05 lot\n"
        "2026-10-20 12:05:00,000 [INFO] Trader: [TRADE CLOSED] BUY | TP_HIT | PnL: $50.00\n"
        "2026-10-20 12:06:00,000 [WARNING] Trader: High spread observed\n"
        "2026-10-20 12:07:00,000 [ERROR] Trader: Connection timeout\n",
        encoding="utf-8"
    )
    summary = parse_trader_log(log_path=log_file)
    assert summary["heartbeat_lines"] == 1
    assert summary["signal_lines"] == 2  # 1 from heartbeat signal=BUY + 1 from [SIGNAL FIRED]
    assert summary["trade_lines"] == 2
    assert summary["warning_lines"] == 1
    assert summary["error_lines"] == 1
    assert summary["max_balance"] == 10050.0
    assert summary["signal_distribution"]["BUY"] >= 1
