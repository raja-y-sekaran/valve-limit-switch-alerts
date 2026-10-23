"""Run the project end to end (course layout: data -> features (strokes) -> baselines -> alert rules -> evaluation).

    python main.py                         # all stages on the SOE log in data/raw/
    python main.py --regenerate --seed 7   # simulate a different fleet first
    python main.py --robustness            # repeat on six synthetic fleets (data/raw untouched)
"""
import argparse
import json
import sys

from src import pipeline
from src.data import generate_events
from src.models.evaluate import robustness
from src.utils import plots


def run_all(quiet=False):
    strokes, alerts, dcs, det, summary, load, reg, faults, base = pipeline.run()
    plots.drift_timeline(strokes, alerts, dcs, det, reg, base)
    plots.alert_load(alerts, dcs)
    if not quiet:
        print(summary.to_string(index=False))
        print(json.dumps(load, indent=2))
    return summary, load


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--regenerate", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--robustness", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.robustness:
        robustness()
    else:
        if a.regenerate:
            sys.argv = ["generate_events", "--seed", str(a.seed)]
            generate_events.main()
        run_all(a.quiet)
