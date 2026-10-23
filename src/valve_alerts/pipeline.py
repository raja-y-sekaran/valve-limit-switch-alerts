"""Run parsing, alerting and scoring against the injected faults; compare with plain DCS alarms."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .alerts import baselines, dcs_alarms, raw_alerts, shelve
from .strokes import load_events, parse_strokes

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT, DOCS = ROOT / "data", ROOT / "outputs", ROOT / "docs"
OURS = {"drift": ["slow_trend", "limit_exceeded"], "sticking": ["sticking", "limit_exceeded"], "no_move": ["fail_to_move"],
        "switch": ["not_confirmed"], "chatter": ["chattering"]}
# The alert that names the cause, used to check the diagnosis rather than just the timing.
DIAGNOSIS = {"drift": "slow_trend", "sticking": "sticking", "no_move": "fail_to_move", "switch": "not_confirmed",
             "chatter": "chattering"}
DCS = {"drift": ["travel_timeout"], "sticking": ["travel_timeout"], "no_move": ["travel_failure"],
       "switch": ["travel_failure"], "chatter": ["uncommanded"]}


def first_after(alerts, tag, rules, t0):
    a = alerts[(alerts.tag == tag) & alerts.rule.isin(rules) & (alerts.ts >= t0)]
    return a.ts.min() if len(a) else pd.NaT


def evaluate(alerts, dcs, faults, register):
    rows = []
    for f in faults.itertuples():
        t0 = pd.Timestamp(f.onset)
        ours, plain = first_after(alerts, f.tag, OURS[f.fault], t0), first_after(dcs, f.tag, DCS[f.fault], t0)
        named = pd.notna(first_after(alerts, f.tag, [DIAGNOSIS[f.fault]], t0))
        rows.append(dict(tag=f.tag, fault=f.fault, onset=t0, alert_first=ours, dcs_first=plain, cause_named=named,
                         alert_delay_days=(ours - t0).total_seconds() / 86400 if pd.notna(ours) else np.nan,
                         dcs_delay_days=(plain - t0).total_seconds() / 86400 if pd.notna(plain) else np.nan,
                         earlier_than_dcs_days=(plain - ours).total_seconds() / 86400
                         if pd.notna(ours) and pd.notna(plain) else np.nan))
    det = pd.DataFrame(rows)
    faulty = faults.set_index("tag")
    healthy = ~alerts.tag.isin(faulty.index)
    before = alerts.tag.isin(faulty.index) & (alerts.ts < alerts.tag.map(lambda t: pd.Timestamp(faulty.loc[t, "onset"])
                                                                            if t in faulty.index else pd.NaT))
    days = (alerts.ts.max() - alerts.ts.min()).days or 365
    load = dict(
        alerts_total=int(len(alerts)), alerts_suppressed_repeats=int(alerts.repeats_suppressed.sum()),
        dcs_alarms_total=int(len(dcs)),
        alerts_per_day_mean=round(len(alerts) / days, 1), dcs_alarms_per_day_mean=round(len(dcs) / days, 1),
        alerts_peak_day=int(alerts.groupby(alerts.ts.dt.date).size().max()),
        dcs_peak_day=int(dcs.groupby(dcs.ts.dt.date).size().max()),
        false_alerts_healthy_valves=int(healthy.sum()), false_alerts_before_onset=int(before.sum()),
        healthy_valves=int(len(register) - len(faulty)))
    chat = faults[faults.fault == "chatter"].tag
    load["chatter_valves_dcs_alarms"] = int(dcs.tag.isin(chat).sum())
    load["chatter_valves_operator_alerts"] = int(alerts.tag.isin(chat).sum())
    return det, load


def run():
    OUT.mkdir(exist_ok=True)
    reg = pd.read_csv(DATA / "valve_register.csv")
    faults = pd.read_csv(DATA / "ground_truth" / "faults.csv")
    strokes, uncmd = parse_strokes(load_events(DATA / "soe_events.csv.gz"), reg)
    base = baselines(strokes)
    alerts = shelve(raw_alerts(strokes, uncmd, reg, base))
    dcs = dcs_alarms(strokes, uncmd, reg)
    det, load = evaluate(alerts, dcs, faults, reg)
    summary = (det.groupby("fault").agg(faults=("tag", "size"), detected=("alert_first", lambda s: int(s.notna().sum())),
                                         dcs_detected=("dcs_first", lambda s: int(s.notna().sum())),
                                         cause_named=("cause_named", "sum"),
                                         median_alert_delay_days=("alert_delay_days", "median"),
                                         median_earlier_than_dcs_days=("earlier_than_dcs_days", "median"))
               .round(2).reset_index())
    strokes.to_csv(OUT / "strokes.csv.gz", index=False)
    alerts.to_csv(OUT / "operator_alerts.csv", index=False)
    det.to_csv(OUT / "fault_detection.csv", index=False)
    base.to_csv(OUT / "valve_baselines.csv", index=False)
    (OUT / "metrics.json").write_text(json.dumps(dict(load=load, by_fault=summary.to_dict("records"),
                                                      strokes=strokes.status.value_counts().to_dict()), indent=2, default=str))
    return strokes, alerts, dcs, det, summary, load, reg, faults, base
