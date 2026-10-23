import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from valve_alerts.alerts import baselines, dcs_alarms, raw_alerts, shelve  # noqa: E402
from valve_alerts.strokes import parse_strokes, prepare_events  # noqa: E402

REG = pd.DataFrame([dict(tag="XV-1", service="process on/off", strokes_per_day=4, open_s=5.0, close_s=4.0,
                         breakaway_s=0.5, close_limit_s=8.0, open_limit_s=10.0)])
T0 = pd.Timestamp("2025-01-01")


def ev(rows):
    return prepare_events(pd.DataFrame([dict(timestamp=(T0 + pd.Timedelta(seconds=s)).isoformat(), point=f"XV-1.{p}", value=v)
                                        for s, p, v in rows]))


def test_complete_stroke_timing():
    st, un = parse_strokes(ev([(0, "ZSC", 1), (0, "ZSO", 0), (100, "CMD", 1), (100.6, "ZSC", 0), (105.6, "ZSO", 1)]), REG)
    s = st.iloc[0]
    assert s.status == "complete" and s.direction == "open"
    assert round(s.breakaway_s, 2) == 0.6 and round(s.travel_s, 2) == 5.0 and round(s.total_s, 2) == 5.6
    assert un.empty


def test_no_move_and_not_confirmed():
    st, _ = parse_strokes(ev([(0, "ZSC", 1), (0, "ZSO", 0), (100, "CMD", 1),  # nothing happens
                              (1000, "CMD", 1), (1000.5, "ZSC", 0)]), REG)  # leaves closed, open switch never made
    assert st.status.tolist() == ["no_move", "not_confirmed"]


def test_stroke_after_failed_end_switch_is_not_called_no_move():
    # close stroke: ZSC never makes (switch fault); next open stroke starts with both switches off
    st, _ = parse_strokes(ev([(0, "ZSC", 0), (0, "ZSO", 1), (100, "CMD", 0), (100.5, "ZSO", 0),
                              (1000, "CMD", 1), (1005.5, "ZSO", 1)]), REG)
    assert st.status.tolist() == ["not_confirmed", "complete_start_switch_not_made"]


def test_uncommanded_changes_are_kept_apart():
    _, un = parse_strokes(ev([(0, "ZSC", 1), (0, "ZSO", 0), (500, "ZSO", 1), (501, "ZSO", 0)]), REG)
    assert len(un) == 2


def _strokes(times_and_totals, direction="open"):
    return pd.DataFrame([dict(tag="XV-1", direction=direction, t_cmd=T0 + pd.Timedelta(days=d), breakaway_s=b,
                              travel_s=t - b, total_s=t, status="complete") for d, t, b in times_and_totals])


def test_trend_alert_on_ramp_but_not_on_one_slow_stroke():
    healthy = [(d, 5.0, 0.5) for d in range(0, 80)]
    one_off = healthy + [(80, 6.8, 0.5)] + [(d, 5.0, 0.5) for d in range(81, 100)]
    a = raw_alerts(_strokes(one_off), pd.DataFrame(columns=["tag", "ts", "signal", "value"]), REG, baselines(_strokes(one_off)))
    assert "slow_trend" not in set(a.rule)
    ramp = healthy + [(80 + k, 5.0 * (1 + 0.02 * k), 0.5) for k in range(20)]
    a = raw_alerts(_strokes(ramp), pd.DataFrame(columns=["tag", "ts", "signal", "value"]), REG, baselines(_strokes(ramp)))
    first = a[a.rule == "slow_trend"].ts.min()
    lim = a[a.rule == "limit_exceeded"].ts.min()
    assert pd.notna(first) and (pd.isna(lim) or first < lim)


def test_sticking_needs_repeats():
    s = [(d, 5.0, 0.5) for d in range(80)] + [(80, 9.0, 4.5), (81, 5.0, 0.5), (82, 9.5, 5.0)]
    a = raw_alerts(_strokes(s), pd.DataFrame(columns=["tag", "ts", "signal", "value"]), REG, baselines(_strokes(s)))
    st = a[a.rule == "sticking"]
    assert len(st) == 1 and st.ts.iloc[0] == T0 + pd.Timedelta(days=82)


def test_chatter_is_one_alert_and_repeats_are_shelved():
    un = pd.DataFrame([dict(tag="XV-1", ts=T0 + pd.Timedelta(hours=h, seconds=s), signal="ZSO", value=s % 2)
                       for h in (1, 3) for s in range(5)])
    a = raw_alerts(pd.DataFrame(columns=["tag", "direction", "t_cmd", "breakaway_s", "travel_s", "total_s", "status"]),
                   un, REG, pd.DataFrame(columns=["tag", "direction"]))
    assert a.rule.tolist() == ["chattering", "chattering"]
    sh = shelve(a)
    assert len(sh) == 1 and sh.repeats_suppressed.iloc[0] == 1
    assert len(dcs_alarms(pd.DataFrame(columns=["tag", "direction", "t_cmd", "total_s", "status"]), un, REG)) == 10
