"""
tests/test_batch107.py
======================
Unit tests for Batch 107:
- wave19_volatility_tpsl.py (VolatilityTPSLAdjuster)
- wave14_auto_tuner.py (AutoTuner)
"""

import json
import math
import os
import pytest
from wave19_volatility_tpsl import VolatilityTPSLAdjuster
from wave14_auto_tuner import AutoTuner, _mean, _std, _percentile


# =====================================================================
# VolatilityTPSLAdjuster Tests (wave19)
# =====================================================================

def test_volatility_tpsl_init_defaults():
    adj = VolatilityTPSLAdjuster()
    assert adj.atr_period == 14
    assert adj.min_tp_pips == 20.0
    assert adj.max_tp_pips == 120.0
    assert adj.min_sl_pips == 15.0
    assert adj.max_sl_pips == 60.0

    # Bad parameter fallbacks
    bad_adj = VolatilityTPSLAdjuster(
        atr_period=-5,
        min_tp_pips=-10.0,
        max_tp_pips=10.0,  # less than min_tp
        min_sl_pips=-5.0,
        max_sl_pips=5.0,   # less than min_sl
    )
    assert bad_adj.atr_period == 14
    assert bad_adj.min_tp_pips == 20.0
    assert bad_adj.max_tp_pips == 120.0
    assert bad_adj.min_sl_pips == 15.0
    assert bad_adj.max_sl_pips == 60.0

    inf = adj.info()
    assert inf["atr_period"] == 14
    assert inf["max_tp_pips"] == 120.0


def test_volatility_tpsl_high_volatility():
    adj = VolatilityTPSLAdjuster()
    # High price changes: 1.2 pips per bar
    closes = [100.0 + i * 1.2 for i in range(20)]
    tp, sl = adj.adjusted_tpsl(
        closes=closes,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 1.6},
    )
    # High volatility regime: TP widens (> 45.0), SL stays at 30.0
    assert tp > 45.0
    assert sl == 30.0


def test_volatility_tpsl_low_volatility():
    adj = VolatilityTPSLAdjuster()
    # Very small changes: 0.05 pips per bar
    closes = [100.0 + i * 0.05 for i in range(20)]
    tp, sl = adj.adjusted_tpsl(
        closes=closes,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 0.4},
    )
    # Low volatility regime: TP tightens (45 * 0.75 = 33.8), SL tightens (30 * 0.85 = 25.5)
    assert tp < 45.0
    assert sl < 30.0
    assert tp == pytest.approx(33.8, rel=1e-1)
    assert sl == pytest.approx(25.5, rel=1e-1)


def test_volatility_tpsl_normal_volatility():
    adj = VolatilityTPSLAdjuster()
    # Normal changes: exactly 0.6 pips per bar, normal vol_index 1.0
    closes = [100.0 + i * 0.6 for i in range(20)]
    tp, sl = adj.adjusted_tpsl(
        closes=closes,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 1.0},
    )
    assert tp == 45.0
    assert sl == 30.0


def test_volatility_tpsl_bounds_and_fail_closed():
    adj = VolatilityTPSLAdjuster(min_tp_pips=20.0, max_tp_pips=120.0, min_sl_pips=15.0, max_sl_pips=60.0)

    # Boolean and invalid bases fallback to 45.0, 30.0
    tp, sl = adj.adjusted_tpsl(closes=[], base_tp_pips=True, base_sl_pips=False)
    assert tp >= 20.0
    assert sl >= 15.0

    # Extreme base values clamped to [min, max]
    tp_high, sl_high = adj.adjusted_tpsl(closes=[], base_tp_pips=500.0, base_sl_pips=300.0)
    assert tp_high == 120.0
    assert sl_high == 60.0

    tp_low, sl_low = adj.adjusted_tpsl(closes=[], base_tp_pips=5.0, base_sl_pips=2.0)
    assert tp_low == 20.0
    assert sl_low == 15.0


# =====================================================================
# AutoTuner Tests (wave14)
# =====================================================================

def test_auto_tuner_init_defaults(tmp_path):
    cfg_file = str(tmp_path / "config.json")
    tuner = AutoTuner(config_path=cfg_file, min_trades=10)
    assert tuner.MIN_TRADES == 10
    assert tuner.seconds_since_last_run == float("inf")

    # Math helper checks
    assert _mean([10.0, 20.0, True, "bad", 30.0]) == 20.0
    assert _std([10.0, 20.0, 30.0]) == pytest.approx(10.0, rel=1e-2)
    assert _percentile([10.0, 20.0, 30.0], 50) == 20.0


def test_auto_tuner_insufficient_data():
    tuner = AutoTuner(min_trades=10)
    # None or empty history
    rep_none = tuner.analyse(None)
    assert rep_none["status"] == "insufficient_data"
    assert rep_none["trades_analysed"] == 0

    # Fewer than 10 trades
    rep_few = tuner.analyse([{"pnl": 10.0}] * 5)
    assert rep_few["status"] == "insufficient_data"
    assert rep_few["trades_analysed"] == 5


def test_auto_tuner_low_win_rate_and_low_pf_tightens():
    tuner = AutoTuner(min_trades=10)
    current_cfg = {
        "sl_pips": 30.0,
        "tp_pips": 45.0,
        "rr_ratio": 1.5,
        "lot_size": 0.05,
        "max_lot_size": 0.10,
        "max_daily_loss_usd": 200.0,
    }

    # 10 trades: 3 wins ($10 each) and 7 losses (-$20 each)
    # win rate = 30% (< 40%) -> reduces SL
    # profit factor = 30 / 140 = 0.21 (< 1.1) -> reduces lot size
    history = [{"pnl": 10.0, "exit_reason": "TP"}] * 3 + [{"pnl": -20.0, "exit_reason": "SL"}] * 7
    rep = tuner.analyse(history, current_config=current_cfg)

    assert rep["status"] == "ok"
    assert rep["win_rate_pct"] == 30.0
    assert rep["config_changed"] is True
    assert rep["proposed_config"]["sl_pips"] < 30.0
    assert rep["proposed_config"]["lot_size"] < 0.05
    assert len(rep["suggestions"]) >= 2


def test_auto_tuner_high_pf_and_streak_expands():
    tuner = AutoTuner(min_trades=10)
    current_cfg = {
        "sl_pips": 30.0,
        "tp_pips": 45.0,
        "rr_ratio": 1.5,
        "lot_size": 0.02,
        "max_lot_size": 0.10,
        "max_daily_loss_usd": 200.0,
    }

    # 20 trades: 16 wins ($30 each), 4 losses (-$10 each)
    # win rate = 80% (> 55%), PF = 480 / 40 = 12.0 (> 2.0), n >= 20 -> expands lot
    history = [{"pnl": 30.0, "exit_reason": "TP"}] * 16 + [{"pnl": -10.0, "exit_reason": "SL"}] * 4
    rep = tuner.analyse(history, current_config=current_cfg)

    assert rep["status"] == "ok"
    assert rep["win_rate_pct"] == 80.0
    assert rep["profit_factor"] > 2.0
    assert rep["config_changed"] is True
    assert rep["proposed_config"]["lot_size"] > 0.02


def test_auto_tuner_analyse_and_tune_safety_floor(tmp_path):
    cfg_file = str(tmp_path / "config.json")
    initial_cfg = {
        "sl_pips": 30.0,
        "tp_pips": 45.0,
        "rr_ratio": 1.5,
        "lot_size": 0.05,
        "max_lot_size": 0.10,
        "max_daily_loss_usd": 200.0,
    }
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(initial_cfg, f)

    tuner = AutoTuner(config_path=cfg_file, min_trades=10)

    # Low win rate history wanting SL reduction
    history = [{"pnl": 10.0}] * 3 + [{"pnl": -20.0}] * 7

    # Case 1: Balance under $500 safety floor (e.g. $300) -> NOT written
    rep1 = tuner.analyse_and_tune(history, balance=300.0)
    assert rep1["config_changed"] is False
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg_check1 = json.load(f)
    assert cfg_check1["sl_pips"] == 30.0  # unchanged

    # Case 2: Dry run -> NOT written
    rep2 = tuner.analyse_and_tune(history, balance=1000.0, dry_run=True)
    assert rep2["config_changed"] is True
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg_check2 = json.load(f)
    assert cfg_check2["sl_pips"] == 30.0  # unchanged

    # Case 3: Balance > $500 and not dry run -> written!
    rep3 = tuner.analyse_and_tune(history, balance=1000.0, dry_run=False)
    assert rep3["config_changed"] is True
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg_check3 = json.load(f)
    assert cfg_check3["sl_pips"] < 30.0  # updated!

    # Check telemetry
    assert tuner.seconds_since_last_run < 10.0
    tuner.reset()
    assert tuner.seconds_since_last_run == float("inf")
