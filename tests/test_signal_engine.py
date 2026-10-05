"""Tests for the standalone technical-indicator signal engine."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from python_engine.signal_engine import SignalEngine


@pytest.fixture
def engine():
    return SignalEngine({})


def test_default_configuration(engine):
    assert engine.bb_period == 20
    assert engine.rsi_period == 14
    assert engine.macd_fast == 12
    assert engine.macd_slow == 26
    assert engine.ema_fast == 8
    assert engine.ema_slow == 21


def test_bb_squeeze_detection(engine):
    result = engine.compute_bb([100.0] * 25)
    assert result["upper"] == result["middle"] == result["lower"] == 100.0
    assert result["width"] == 0.0
    assert result["squeeze"] is True


def test_bb_width_and_band_order(engine):
    result = engine.compute_bb([100.0 + (i % 2) for i in range(25)])
    assert result["upper"] > result["middle"] > result["lower"]
    assert result["width"] > 0.002
    assert result["squeeze"] is False


def test_rsi_wilder_oversold_value(engine):
    rsi = engine.compute_rsi([100.0 - i for i in range(30)])
    assert rsi == 0.0


def test_rsi_oversold_buy(monkeypatch, engine):
    monkeypatch.setattr(engine, "compute_bb", lambda prices: {
        "upper": 110.0, "middle": 105.0, "lower": 90.0, "width": 0.19, "squeeze": False
    })
    monkeypatch.setattr(engine, "compute_rsi", lambda prices: 25.0)
    monkeypatch.setattr(engine, "compute_macd", lambda prices: {
        "macd_line": 0.0, "signal_line": 0.0, "histogram": 0.0, "cross": "NONE"
    })
    monkeypatch.setattr(engine, "compute_ema", lambda prices, period: 100.0)
    result = engine.get_signal([100.0])
    assert result["signal"] == "BUY"
    assert result["tier"] == 3
    assert any("oversold" in reason for reason in result["reasons"])


def test_macd_cross_buy(engine):
    prices = [100.0] * 30 + [99.0, 102.0]
    macd = engine.compute_macd(prices)
    assert macd["cross"] == "BUY"
    assert macd["histogram"] > 0.0


def test_macd_output_shape(engine):
    macd = engine.compute_macd([100.0 + i * 0.1 for i in range(40)])
    assert set(macd) == {"macd_line", "signal_line", "histogram", "cross"}
    assert macd["cross"] in {"BUY", "SELL", "NONE"}


def test_ema_matches_standard_recursive_calculation(engine):
    value = engine.compute_ema([10.0, 12.0, 14.0], 2)
    # alpha=2/(2+1); seeded with the first price.
    expected = ((14.0 * (2.0 / 3.0)) + ((12.0 * (2.0 / 3.0) + 10.0 / 3.0) / 3.0))
    assert value == pytest.approx(expected)


def test_combined_tier1_signal(monkeypatch, engine):
    monkeypatch.setattr(engine, "compute_bb", lambda prices: {
        "upper": 110.0, "middle": 105.0, "lower": 100.0, "width": 0.095, "squeeze": False
    })
    monkeypatch.setattr(engine, "compute_rsi", lambda prices: 25.0)
    monkeypatch.setattr(engine, "compute_macd", lambda prices: {
        "macd_line": 0.0, "signal_line": 0.0, "histogram": 0.0, "cross": "NONE"
    })
    monkeypatch.setattr(engine, "compute_ema", lambda prices, period: 101.0 if period == engine.ema_fast else 100.0)
    result = engine.get_signal([100.0])
    assert result["signal"] == "BUY"
    assert result["tier"] == 1
    assert result["confidence"] == pytest.approx(0.9)


def test_hold_on_no_signal(engine):
    result = engine.get_signal([100.0] * 40)
    assert result["signal"] == "HOLD"
    assert result["tier"] == 3
    assert result["confidence"] == 0.0
    assert result["ema_cross"] == "NEUTRAL"


def test_confidence_ranges(engine):
    for prices in ([100.0] * 40, [100.0 + i for i in range(40)], [100.0 - i for i in range(40)]):
        result = engine.get_signal(prices)
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["tier"] in {1, 2, 3}


def test_signal_result_contract(engine):
    result = engine.get_signal([100.0 + (i * 0.01) for i in range(40)])
    assert set(result) == {"signal", "confidence", "tier", "reasons", "bb", "rsi", "macd", "ema_cross"}
    assert result["signal"] in {"BUY", "SELL", "HOLD"}
    assert 0.0 <= result["rsi"] <= 100.0
    assert isinstance(result["reasons"], list)
