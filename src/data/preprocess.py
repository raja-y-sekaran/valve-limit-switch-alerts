"""Prepare raw SOE records: parse timestamps, split '<tag>.<signal>' points, sort in time."""
from __future__ import annotations

import pandas as pd


def load_events(path) -> pd.DataFrame:
    return prepare_events(pd.read_csv(path))


def prepare_events(e: pd.DataFrame) -> pd.DataFrame:
    e = e.copy()
    e["ts"] = pd.to_datetime(e.timestamp, format="ISO8601")
    e[["tag", "signal"]] = e.point.str.rsplit(".", n=1, expand=True)
    return e.sort_values("ts", kind="stable").reset_index(drop=True)
