"""
Tests for OmniCommand HTTP server routes, /api/* aliases, /guards, /risk,
/alerts, and live status enrichment (grade, win_rate, risk_guard, Wave 59/61).
"""
from fastapi.testclient import TestClient
import omnicommand_server


client = TestClient(omnicommand_server.app)


def test_all_get_routes_and_api_aliases_return_200():
    routes = [
        "/status",
        "/api/status",
        "/api/scalping-robot/status",
        "/metrics",
        "/api/metrics",
        "/health",
        "/api/health",
        "/performance",
        "/api/performance",
        "/performance/json",
        "/positions",
        "/api/positions",
        "/guards",
        "/api/guards",
        "/risk",
        "/api/risk",
        "/trades",
        "/api/trades",
        "/history",
        "/api/history",
        "/analytics",
        "/api/analytics",
        "/alerts",
        "/api/alerts",
        "/system",
        "/api/system",
        "/api/telemetry",
        "/api/info",
        "/ml_status",
        "/api/ml_status",
        "/api/ml",
        "/ping",
        "/api/ping",
    ]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code == 200, f"GET {route} returned {resp.status_code}"


def test_status_and_api_status_enriched_fields():
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    for required_key in [
        "status",
        "symbol",
        "balance",
        "equity",
        "win_rate",
        "win_rate_pct",
        "grade",
        "ema_cross",
        "ema_cross_signal",
        "circuit_breaker_fired",
        "circuit_breaker_active",
        "risk_guard",
        "ma_trend_filter",
        "opening_range_breakout",
    ]:
        assert required_key in data, f"Missing {required_key} in /api/status"
    assert isinstance(data["risk_guard"], dict)
    assert "daily_loss_halted" in data["risk_guard"]
    assert "balance_floor_halted" in data["risk_guard"]
    assert "kill_switch_active" in data["risk_guard"]


def test_metrics_and_api_metrics_enriched_fields():
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    for required_key in [
        "balance",
        "equity",
        "daily_pnl",
        "daily_loss",
        "win_rate",
        "grade",
        "sharpe_ratio",
        "profit_factor",
        "max_drawdown",
        "drawdown_pct",
        "tick_to_signal_us",
        "signal_to_dispatch_us",
        "order_execution_ms",
        "ema_cross",
        "ema_cross_signal",
        "circuit_breaker_fired",
        "circuit_breaker_active",
    ]:
        assert required_key in data, f"Missing {required_key} in /api/metrics"


def test_guards_and_risk_endpoints():
    for route in ["/guards", "/api/guards", "/risk", "/api/risk"]:
        resp = client.get(route)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "trading_allowed" in data
        assert "risk_guard" in data
        assert "guards" in data
        assert "total_guards" in data
        assert "active_blocks_count" in data
        assert "blocked_guards" in data
        assert isinstance(data["guards"], dict)
        assert data["total_guards"] >= 1
