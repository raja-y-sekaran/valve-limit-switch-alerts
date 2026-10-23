import pandas as pd
from fastapi.testclient import TestClient

from src.api.app import app

client = TestClient(app)
VALVE = dict(tag="XV-9", open_s=5.0, close_s=4.0, open_limit_s=10.0, close_limit_s=8.0)
T0 = pd.Timestamp("2025-01-01")


def _strokes(n_days, open_time):
    """One open and one close per day; opening time given per day by open_time(day)."""
    ev = [(0, "ZSC", 1), (0, "ZSO", 0)]
    for d in range(n_days):
        t = d * 86400 + 3600
        o = open_time(d)
        ev += [(t, "CMD", 1), (t + 0.5, "ZSC", 0), (t + o, "ZSO", 1),
               (t + 600, "CMD", 0), (t + 600.5, "ZSO", 0), (t + 604, "ZSC", 1)]
    return [dict(timestamp=(T0 + pd.Timedelta(seconds=s)).isoformat(timespec="milliseconds"), point=f"XV-9.{p}", value=v)
            for s, p, v in ev]


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_healthy_valve_raises_nothing():
    r = client.post("/alerts", json=dict(valve=VALVE, events=_strokes(120, lambda d: 5.0))).json()
    assert r["strokes"] == 240 and r["alerts"] == []


def test_drifting_valve_gets_a_trend_alert_before_its_limit():
    r = client.post("/alerts", json=dict(valve=VALVE, events=_strokes(150, lambda d: 5.0 if d < 70 else 5.0 + 0.05 * (d - 70)))).json()
    rules = [a["rule"] for a in r["alerts"]]
    assert "slow_trend" in rules
    assert rules.index("slow_trend") < (rules.index("limit_exceeded") if "limit_exceeded" in rules else len(rules))


def test_rejects_points_of_another_valve():
    ev = _strokes(2, lambda d: 5.0)
    ev[0]["point"] = "XV-8.ZSC"
    assert client.post("/alerts", json=dict(valve=VALVE, events=ev)).status_code == 422
