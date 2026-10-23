"""Each valve's own normal: median and spread of stroke and breakaway times, learned from its first weeks
in service. This is the only thing in the project that is 'trained', and it is saved to models/."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.utils.paths import MODELS


def baselines(strokes: pd.DataFrame, learn_days: int = 60, min_n: int = 4) -> pd.DataFrame:
    """Median and MAD of each valve's stroke and breakaway times per direction, from its first weeks in service."""
    ok = strokes[strokes.status == "complete"].copy()
    t0 = ok.t_cmd.min()
    rows = []
    for (tag, d), g in ok.groupby(["tag", "direction"]):
        learn = g[g.t_cmd < t0 + pd.Timedelta(days=learn_days)]
        if len(learn) < min_n:
            learn = g.head(min_n)
        mad = lambda x: float(np.median(np.abs(x - np.median(x)))) * 1.4826
        rows.append(dict(tag=tag, direction=d, n_learn=len(learn), base_total_s=float(learn.total_s.median()),
                         mad_total_s=max(mad(learn.total_s), 0.02 * float(learn.total_s.median())),
                         base_break_s=float(learn.breakaway_s.median()),
                         mad_break_s=max(mad(learn.breakaway_s), 0.05 * float(learn.breakaway_s.median())),
                         learn_until=learn.t_cmd.max()))
    return pd.DataFrame(rows)


def save(base: pd.DataFrame):
    base.to_csv(MODELS / "valve_baselines.csv", index=False)
    (MODELS / "model_card.json").write_text(json.dumps(dict(
        model="Per-valve, per-direction baseline of stroke and breakaway time (median and MAD), learned from the "
              "first 60 days of complete strokes (at least 4); alert rules in src/alerts/rules.py compare against it",
        trend="EWMA (lambda 0.25) of log(stroke time / baseline); slow_trend above +12% with three strokes over +5%",
        training_data="synthetic SOE log (src/data/generate_events.py), one year, 45 valves",
        intended_use="demonstration on synthetic data; baselines must be relearned after valve maintenance and "
                     "checked on the plant's own SOE history before use",
    ), indent=2))
    return MODELS / "valve_baselines.csv"
