"""Repeat on several synthetic fleets (seeds): detection, cause named, lead over the DCS limit alarm,
false alerts and alert load.   python scripts/robustness.py"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "data"))

import generate_events as gen  # noqa: E402
from valve_alerts.alerts import baselines, dcs_alarms, raw_alerts, shelve  # noqa: E402
from valve_alerts.pipeline import evaluate  # noqa: E402
from valve_alerts.strokes import parse_strokes, prepare_events  # noqa: E402

rows, dets = [], []
for seed in [1, 2, 3, 4, 5, 42]:
    reg, ev, faults = gen.generate(seed)
    strokes, uncmd = parse_strokes(prepare_events(ev), reg)
    alerts = shelve(raw_alerts(strokes, uncmd, reg, baselines(strokes)))
    det, load = evaluate(alerts, dcs_alarms(strokes, uncmd, reg), faults, reg)
    dets.append(det.assign(seed=seed))
    rows.append(dict(seed=seed, faults=len(det), detected=int(det.alert_first.notna().sum()),
                     cause_named=int(det.cause_named.sum()),
                     false_alerts=load["false_alerts_healthy_valves"] + load["false_alerts_before_onset"],
                     alerts=load["alerts_total"], dcs_alarms=load["dcs_alarms_total"]))
r = pd.DataFrame(rows)
d = pd.concat(dets)
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
