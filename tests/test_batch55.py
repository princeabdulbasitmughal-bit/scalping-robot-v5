"""
Test Suite: Batch 55 — RiskGuard Daily Loss & Rollover, Economic News Filter, Scalping Regimes & Storage Resilience
==================================================================================================================
Hermetic unit test suite verifying:
  1. RiskGuard: record_trade daily loss accumulation and trip wire trigger
  2. RiskGuard: reset_daily_loss manual override and state recovery
  3. RiskGuard: UTC day rollover resetting daily metrics while preserving permanent balance floor halt
  4. RiskGuard: Minimum time between trades cooldown enforcement
  5. RiskGuard: Fail-closed type safety on corrupt and non-dictionary inputs
  6. EconomicNewsFilter: Pre-event and post-event blackout window detection with phase calculation
  7. EconomicNewsFilter: Currency matching and non-interfering cross-currency isolation
  8. ScalpingRobotV5: Multi-bar indicator computation and volatility regime classification
  9. Storage: Atomic write, backup synchronization, and corrupt JSON recovery
 10. Gold News Fetcher: Whole-word high-impact keyword pattern matching accuracy
"""

import time
import math
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest

from python_engine.risk_guard import RiskGuard, Decision
from python_engine.scalping_engine import ScalpingRobotV5, EconomicNewsFilter, MarketRegime, ScalpingSignal
from python_engine.storage import atomic_write_json, safe_read_json
from gold_news_fetcher import check_high_impact


# ── Test 1: RiskGuard Daily Loss Accumulation & Circuit Breaker ────────────────
def test_risk_guard_daily_loss_trip_wire():
    """Verify record_trade tracks negative PnL and trips daily loss halt at max limit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"
        guard = RiskGuard(
            config={
                "max_daily_loss_usd": 150.0,
                "min_balance_usd": 5000.0,
                "min_sl_pips": 5.0,
                "max_sl_pips": 100.0,
            },
            state_path=state_file,
        )

        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        market = {"spread_pips": 1.2, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}
        order = {"type": "BUY", "price": 2400.0, "sl": 2390.0, "lots": 0.01}

        # Initial order approved
        assert guard.check_order(order=order, account=account, market=market).allowed is True

        # Record trades: -$80.0, then -$75.0 -> Total -$155.0 <= -$150.0 limit
        guard.record_trade(-80.0)
        assert guard.state["daily_loss_halted"] is False
        assert guard.check_order(order=order, account=account, market=market).allowed is True

        guard.record_trade(-75.0)
        assert guard.state["daily_loss_halted"] is True

        # Subsequent orders strictly blocked
        decision = guard.check_order(order=order, account=account, market=market)
        assert decision.allowed is False
        assert "DAILY_LOSS_HALTED" in decision.reason


# ── Test 2: RiskGuard Manual Daily Loss Reset ───────────────────────────────────
def test_risk_guard_reset_daily_loss():
    """Verify reset_daily_loss clears halted flag and permits trading resumption."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(
            config={"max_daily_loss_usd": 100.0, "min_balance_usd": 5000.0},
            state_path=Path(tmpdir) / "state.json",
        )
        guard.record_trade(-120.0)
        assert guard.state["daily_loss_halted"] is True

        guard.reset_daily_loss()
        assert guard.state["daily_loss_halted"] is False
        assert guard.state["daily_pnl"] == 0.0

        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        market = {"spread_pips": 1.0, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}
        order = {"type": "BUY", "price": 2400.0, "sl": 2390.0, "lots": 0.01}
        assert guard.check_order(order=order, account=account, market=market).allowed is True


# ── Test 3: RiskGuard UTC Day Rollover & Permanent Balance Halt ─────────────────
def test_risk_guard_day_rollover_and_balance_persistence():
    """Verify UTC day rollover resets daily metrics but leaves balance floor halt permanently active."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(
            config={"max_daily_loss_usd": 100.0, "min_balance_usd": 9000.0},
            state_path=Path(tmpdir) / "state.json",
        )
        # Simulate yesterday's state with both daily loss and balance floor halts
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        guard.state["date_utc"] = yesterday
        guard.state["daily_pnl"] = -150.0
        guard.state["daily_loss_halted"] = True
        guard.state["balance_floor_halted"] = True
        guard.state["trade_count_today"] = 25
        guard._save_state()

        # Trigger rollover check
        guard._check_day_rollover()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert guard.state["date_utc"] == today
        assert guard.state["daily_pnl"] == 0.0
        assert guard.state["trade_count_today"] == 0
        assert guard.state["daily_loss_halted"] is False
        # Balance floor halt MUST remain permanent across date rollovers!
        assert guard.state["balance_floor_halted"] is True


# ── Test 4: RiskGuard Cooldown Between Trades ──────────────────────────────────
def test_risk_guard_trade_cooldown():
    """Verify minimum cooldown seconds between trade executions is enforced."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(
            config={"min_time_between_trades_sec": 30.0, "min_balance_usd": 5000.0},
            state_path=Path(tmpdir) / "state.json",
        )
        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        market = {"spread_pips": 1.0, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}
        order = {"type": "BUY", "price": 2400.0, "sl": 2390.0, "lots": 0.01}

        # Simulate a trade recorded 10 seconds ago (within 30s cooldown window)
        now = time.time()
        guard.state["last_trade_time"] = now - 10.0
        guard._save_state()

        dec = guard.check_order(order=order, account=account, market=market)
        assert dec.allowed is False
        assert "COOLDOWN_ACTIVE" in dec.reason

        # Simulate time moving past cooldown window (35s elapsed > 30s)
        guard.state["last_trade_time"] = now - 35.0
        guard._save_state()

        dec_allowed = guard.check_order(order=order, account=account, market=market)
        assert dec_allowed.allowed is True


# ── Test 5: RiskGuard Fail-Closed on Corrupt Inputs ─────────────────────────────
def test_risk_guard_fail_closed_inputs():
    """Verify check_order fails closed on non-dict inputs, non-finite pip size, and negative contract size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(config={}, state_path=Path(tmpdir) / "state.json")
        account = {"balance": 10000.0, "open_positions": 0}
        market = {"spread_pips": 1.0, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}
        order = {"type": "BUY", "price": 2400.0, "sl": 2390.0, "lots": 0.01}

        # 1. Non-dict inputs
        assert guard.check_order(order=None, account=account, market=market).allowed is False
        assert guard.check_order(order=order, account="not_a_dict", market=market).allowed is False
        assert guard.check_order(order=order, account=account, market=12345).allowed is False

        # 2. Invalid pip_size in market
        bad_market = dict(market, pip_size=-0.1)
        assert guard.check_order(order=order, account=account, market=bad_market).allowed is False

        # 3. Invalid contract_size in market
        bad_contract_market = dict(market, contract_size=0.0)
        assert guard.check_order(order=order, account=account, market=bad_contract_market).allowed is False


# ── Test 6: EconomicNewsFilter Blackout Windows & Phases ────────────────────────
def test_economic_news_filter_blackout_and_phases():
    """Verify EconomicNewsFilter identifies PRE_EVENT and POST_EVENT blackout phases."""
    news = EconomicNewsFilter(pre_minutes=15, post_minutes=30)
    news.clear_events()

    base_time = 1700000000.0  # reference epoch
    news.add_event(event_time=base_time, event_name="US CPI Release", currency="USD", impact="HIGH")

    # 1. 10 minutes before event (in 15m pre-window) -> PRE_EVENT
    in_pre, info_pre = news.is_blackout(current_time=base_time - 600, currency="USD")
    assert in_pre is True
    assert info_pre is not None
    assert info_pre["phase"] == "PRE_EVENT"
    assert info_pre["seconds_to_event"] == 600.0

    # 2. 10 minutes after event (in 30m post-window) -> POST_EVENT
    in_post, info_post = news.is_blackout(current_time=base_time + 600, currency="USD")
    assert in_post is True
    assert info_post is not None
    assert info_post["phase"] == "POST_EVENT"
    assert info_post["seconds_to_event"] == -600.0

    # 3. 40 minutes after event (outside 30m post-window) -> CLEAR
    in_clear, info_clear = news.is_blackout(current_time=base_time + 2400, currency="USD")
    assert in_clear is False
    assert info_clear is None


# ── Test 7: EconomicNewsFilter Currency Isolation ──────────────────────────────
def test_economic_news_filter_currency_isolation():
    """Verify news filter only blackouts matching currency events."""
    news = EconomicNewsFilter(pre_minutes=15, post_minutes=30)
    news.clear_events()

    base_time = 1700000000.0
    news.add_event(event_time=base_time, event_name="ECB Rate Decision", currency="EUR", impact="HIGH")

    # Checking for USD should NOT blackout on an EUR event
    is_blocked, _ = news.is_blackout(current_time=base_time, currency="USD")
    assert is_blocked is False

    # Checking for EUR or None SHOULD blackout
    is_blocked_eur, info = news.is_blackout(current_time=base_time, currency="EUR")
    assert is_blocked_eur is True
    assert info["currency"] == "EUR"


# ── Test 8: Scalping Engine Indicator Calculation & Regime Detection ────────────
def test_scalping_engine_indicators_and_regimes():
    """Verify ScalpingRobotV5 calculates technical indicators and classifies volatility regimes."""
    robot = ScalpingRobotV5()

    # Generate synthetic OHLC bars (40 bars)
    bars = []
    base_price = 2400.0
    for i in range(40):
        c = base_price + math.sin(i * 0.3) * 5.0
        h = c + 1.5
        l = c - 1.5
        bars.append({"open": c, "high": h, "low": l, "close": c, "volume": 100})

    ind = robot.calculate_indicators(bars)
    assert isinstance(ind, dict)
    assert "bb_upper" in ind and "bb_lower" in ind and "bb_mid" in ind
    assert ind["bb_upper"] > ind["bb_lower"]
    assert "rsi" in ind
    assert 0.0 <= ind["rsi"] <= 100.0
    assert "atr" in ind and ind["atr"] > 0
    assert "volatility_regime" in ind
    assert ind["volatility_regime"] in (
        MarketRegime.LOW_VOLATILITY,
        MarketRegime.NORMAL_VOLATILITY,
        MarketRegime.HIGH_VOLATILITY,
        MarketRegime.EXTREME_SPIKE,
    )


# ── Test 9: Storage Atomic Write & Corrupt JSON Backup Recovery ────────────────
def test_storage_atomic_write_and_recovery():
    """Verify atomic_write_json synchronizes backup and safe_read_json recovers from corrupted primary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target_file = Path(tmpdir) / "telemetry.json"
        data = {"robot": "ScalpingRobotV5", "version": 5.0, "status": "ACTIVE"}

        # Write data atomically
        success = atomic_write_json(target_file, data)
        assert success is True
        assert target_file.exists()

        bak_file = target_file.with_suffix(".json.bak")
        assert bak_file.exists()

        # Read back safely
        read_data = safe_read_json(target_file)
        assert read_data == data

        # Corrupt the primary JSON file with invalid garbage
        with open(target_file, "wb") as f:
            f.write(b"CORRUPTED{INVALID_JSON:::TRUNCATED")

        # safe_read_json must recover seamlessly from .bak backup!
        recovered = safe_read_json(target_file, default=None)
        assert recovered == data


# ── Test 10: Gold News Fetcher Keyword Matching Accuracy ───────────────────────
def test_gold_news_fetcher_keyword_matching():
    """Verify check_high_impact detects whole-word macro keywords while avoiding false positives."""
    # 1. High impact headlines
    high_impact_headlines = [
        ("fed signals potential 50bp rate cut at next meeting", "2026-10-17"),
        ("gold prices surge as cpi inflation figures exceed expectations", "2026-10-17"),
        ("non-farm payrolls show unexpected drop in jobs", "2026-10-17"),
    ]
    is_high, hit = check_high_impact(high_impact_headlines)
    assert is_high is True
    assert len(hit) > 0

    # 2. Benign headlines without high impact triggers (testing whole-word boundary safety)
    benign_headlines = [
        ("jewelry sales exhibit moderate seasonal uptick", "2026-10-17"),
        ("copper miners forward guidance update for Q4", "2026-10-17"),  # 'forward' should not match 'war' or 'fed'
        ("gold refining technology patent award announcement", "2026-10-17"),  # 'award' should not match 'war'
    ]
    is_benign, hit_b = check_high_impact(benign_headlines)
    assert is_benign is False
    assert hit_b == ""
