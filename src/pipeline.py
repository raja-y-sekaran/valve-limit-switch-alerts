"""Run parsing, alerting and scoring against the injected faults; compare with plain DCS alarms."""
from __future__ import annotations

import json

from src.alerts.rules import dcs_alarms, raw_alerts, shelve
from src.data.load_data import load_data, load_truth
from src.features.strokes import parse_strokes
from src.models import baseline
from src.models.evaluate import evaluate
from src.utils.paths import DATA_PROCESSED, REPORTS
def run():
    reg, events = load_data()
    faults = load_truth()
    strokes, uncmd = parse_strokes(events, reg)
    base = baseline.baselines(strokes)
    alerts = shelve(raw_alerts(strokes, uncmd, reg, base))
    dcs = dcs_alarms(strokes, uncmd, reg)
    det, load = evaluate(alerts, dcs, faults, reg)
    summary = (det.groupby("fault").agg(faults=("tag", "size"), detected=("alert_first", lambda s: int(s.notna().sum())),
                                         dcs_detected=("dcs_first", lambda s: int(s.notna().sum())),
                                         cause_named=("cause_named", "sum"),
                                         median_alert_delay_days=("alert_delay_days", "median"),
                                         median_earlier_than_dcs_days=("earlier_than_dcs_days", "median"))
               .round(2).reset_index())
    strokes.to_csv(DATA_PROCESSED / "strokes.csv.gz", index=False)
    alerts.to_csv(REPORTS / "operator_alerts.csv", index=False)
    det.to_csv(REPORTS / "fault_detection.csv", index=False)
    baseline.save(base)
    (REPORTS / "metrics.json").write_text(json.dumps(dict(load=load, by_fault=summary.to_dict("records"),
                                                      strokes=strokes.status.value_counts().to_dict()), indent=2, default=str))
    return strokes, alerts, dcs, det, summary, load, reg, faults, base
