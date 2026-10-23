"""Score operator alerts and plain DCS alarms against the injected faults; repeat over several synthetic fleets."""
from __future__ import annotations

import numpy as np
import pandas as pd

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


def robustness(seeds=(1, 2, 3, 4, 5, 42)):
    from src.alerts.rules import dcs_alarms, raw_alerts, shelve
    from src.data import generate_events as gen
    from src.data.preprocess import prepare_events
    from src.features.strokes import parse_strokes
    from src.models.baseline import baselines

    rows, dets = [], []
    for seed in seeds:
        reg, ev, faults = gen.generate(seed)
        strokes, uncmd = parse_strokes(prepare_events(ev), reg)
        alerts = shelve(raw_alerts(strokes, uncmd, reg, baselines(strokes)))
        det, load = evaluate(alerts, dcs_alarms(strokes, uncmd, reg), faults, reg)
        dets.append(det.assign(seed=seed))
        rows.append(dict(seed=seed, faults=len(det), detected=int(det.alert_first.notna().sum()),
                         cause_named=int(det.cause_named.sum()),
                         false_alerts=load["false_alerts_healthy_valves"] + load["false_alerts_before_onset"],
                         alerts=load["alerts_total"], dcs_alarms=load["dcs_alarms_total"]))
    r, d = pd.DataFrame(rows), pd.concat(dets)
    print("| Seed | Faults | Detected | Cause named | False alerts | Operator alerts | Plain DCS alarms |")
    print("|---|---|---|---|---|---|---|")
    for x in r.itertuples():
        print(f"| {x.seed} | {x.faults} | {x.detected} | {x.cause_named} | {x.false_alerts} | {x.alerts:,} | {x.dcs_alarms:,} |")
    dr = d[d.fault == "drift"]
    xv = dr[dr.tag.str.startswith("XV")].earlier_than_dcs_days
    sdv = dr[dr.tag.str.startswith("SDV")].earlier_than_dcs_days
    print(f"\nDrift on process valves (XV): trend alert ahead of the DCS limit alarm by median {xv.median():.0f} days "
          f"(range {xv.min():.0f}-{xv.max():.0f}, n={len(xv)})")
    print(f"Drift on weekly-tested SDVs: median {sdv.median():.0f} days ahead (range {sdv.min():.0f}-{sdv.max():.0f}, n={len(sdv)})")
    return r, d
