"""Simulate one year of DCS sequence-of-events (SOE) records for on/off valves.

Each valve has a command output (<tag>.CMD: 1 = open, 0 = close) and two limit switches
(<tag>.ZSO open, <tag>.ZSC closed). A healthy stroke looks like:
    CMD changes -> start switch drops after the breakaway time -> end switch makes after the travel time.

Fleet: 30 process on/off valves (XV, cycling several times a day) and 15 shutdown valves
(SDV, stroke-tested weekly, with a required closing time). Everything is invented.

Injected faults (written to data/ground_truth/faults.csv with their onset time):
  drift      stroke time creeps up over weeks (actuator wear, packing friction, air supply)
  sticking   intermittent long breakaway (valve sticks before it moves)
  no_move    from onset the valve no longer leaves its end position on some strokes
  switch     end switch in one direction stops making (switch or cam fault; valve may be fine)
  chatter    open switch toggles on and off with no command (loose cam, vibration)
Healthy noise that must NOT raise alerts: ~1% of strokes are one-off slow strokes (cold start, low air).

Usage:  python data/generate_events.py [--seed 42]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
START = datetime(2025, 1, 1)
DAYS = 365
FAULTS = ["drift", "sticking", "no_move", "switch", "chatter"]


def valves(rng):
    rows = []
    for i in range(30):
        size = rng.choice([2, 3, 4, 6, 8])
        rows.append(dict(tag=f"XV-{1101 + i}", service="process on/off", strokes_per_day=float(rng.choice([2, 3, 4, 6])),
                         open_s=round(1.2 * size * rng.uniform(0.8, 1.2), 2), close_s=round(1.0 * size * rng.uniform(0.8, 1.2), 2)))
    for i in range(15):
        size = rng.choice([6, 8, 10, 12])
        close = round(1.1 * size * rng.uniform(0.8, 1.2), 2)
        rows.append(dict(tag=f"SDV-{2101 + i}", service="shutdown valve", strokes_per_day=2 / 7,
                         open_s=round(1.4 * size * rng.uniform(0.8, 1.2), 2), close_s=close))
    v = pd.DataFrame(rows)
    v["breakaway_s"] = np.round(rng.uniform(0.3, 0.9, len(v)), 2)
    # Required closing time: SDVs from the safety requirement spec; XVs from the DCS travel-timeout setting.
    v["close_limit_s"] = np.where(v.service == "shutdown valve", np.round(v.close_s * 1.5, 1), np.round(v.close_s * 2.0, 1))
    v["open_limit_s"] = np.round(v.open_s * 2.0, 1)
    return v


def generate(seed=42):
    rng = np.random.default_rng(seed)
    v = valves(rng)
    faulty = rng.choice(len(v), size=int(len(v) * 0.45), replace=False)
    fault_of = {int(i): FAULTS[k % len(FAULTS)] for k, i in enumerate(faulty)}
    ev, truth = [], []

    sw = {}

    def add(t, tag, sig, val):
        if sig != "CMD":  # an SOE log records changes only
            if sw.get((tag, sig)) == val:
                return
            sw[(tag, sig)] = val
        ev.append((t, f"{tag}.{sig}", val))

    for i, r in v.iterrows():
        kind = fault_of.get(i)
        onset = rng.uniform(75, 290) * 86400 if kind else np.inf
        direction = rng.choice(["close", "open"]) if kind in ("drift", "switch", "sticking") else None
        if r.service == "shutdown valve" and kind in ("drift", "switch", "sticking"):
            direction = "close"
        ramp_days, gain = rng.uniform(30, 120), rng.uniform(0.7, 1.4)  # drift reaches +70-140% after ramp
        limit_hit = None
        n = rng.poisson(r.strokes_per_day * DAYS)
        times = np.sort(rng.uniform(0, DAYS * 86400, n))
        times = times[np.concatenate([[True], np.diff(times) > 300])]  # no reversal within 5 minutes of a command
        state = 0  # start closed
        add(0.0, r.tag, "ZSC", 1)
        add(0.0, r.tag, "ZSO", 0)
        for t in times:
            target = 1 - state
            d = "open" if target == 1 else "close"
            add(t, r.tag, "CMD", target)
            nominal = r.open_s if d == "open" else r.close_s
            b = r.breakaway_s * rng.lognormal(0, 0.10)
            tr = nominal * rng.lognormal(0, 0.04)
            if rng.random() < 0.01:  # one-off slow stroke: not a fault
                tr *= rng.uniform(1.15, 1.35)
            active = t >= onset
            if active and kind == "drift" and d == direction:
                tr *= 1 + gain * min((t - onset) / (ramp_days * 86400), 1.0)
            if active and kind == "sticking" and d == direction and rng.random() < 0.5:
                b *= rng.uniform(5, 12)
            start_sw, end_sw = ("ZSC", "ZSO") if d == "open" else ("ZSO", "ZSC")
            limit = r.open_limit_s if d == "open" else r.close_limit_s
            if active and kind == "drift" and d == direction and limit_hit is None and b + tr > limit:
                limit_hit = t
            if active and kind == "no_move" and rng.random() < 0.3:
                continue  # valve stays put; the command is lost, state unchanged
            add(t + b, r.tag, start_sw, 0)
            if active and kind == "switch" and d == direction:
                pass  # valve travels but the end switch never makes
            else:
                add(t + b + tr, r.tag, end_sw, 1)
            state = target
        if kind == "chatter":
            for t in np.sort(rng.uniform(onset, DAYS * 86400, rng.poisson((DAYS * 86400 - onset) / 86400 * 1.5))):
                for k in range(int(rng.integers(3, 9))):
                    add(t + k * rng.uniform(0.3, 2.0), r.tag, "ZSO", k % 2)  # toggles with no command
        if kind:
            truth.append(dict(tag=r.tag, fault=kind, direction=direction,
                              onset=(START + timedelta(seconds=float(onset))).isoformat(timespec="seconds"),
                              limit_first_exceeded=(START + timedelta(seconds=float(limit_hit))).isoformat(timespec="seconds")
                              if limit_hit else None))
    e = pd.DataFrame(ev, columns=["t", "point", "value"]).sort_values("t", kind="stable")
    e.insert(0, "timestamp", [(START + timedelta(seconds=float(s))).isoformat(timespec="milliseconds") for s in e.t])
    return v, e.drop(columns="t"), pd.DataFrame(truth)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    v, e, truth = generate(ap.parse_args().seed)
    (OUT / "ground_truth").mkdir(exist_ok=True)
    v.to_csv(OUT / "valve_register.csv", index=False)
    e.to_csv(OUT / "soe_events.csv.gz", index=False)
    truth.to_csv(OUT / "ground_truth" / "faults.csv", index=False)
    print(f"{len(v)} valves, {len(e)} SOE events, {len(truth)} faults:", truth.fault.value_counts().to_dict())


if __name__ == "__main__":
    main()
