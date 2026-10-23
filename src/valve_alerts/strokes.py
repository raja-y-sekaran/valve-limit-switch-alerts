"""Turn raw SOE records (command and limit-switch transitions) into one row per valve stroke."""
from __future__ import annotations

import numpy as np
import pandas as pd


def load_events(path) -> pd.DataFrame:
    return prepare_events(pd.read_csv(path))


def prepare_events(e: pd.DataFrame) -> pd.DataFrame:
    e = e.copy()
    e["ts"] = pd.to_datetime(e.timestamp, format="ISO8601")
    e[["tag", "signal"]] = e.point.str.rsplit(".", n=1, expand=True)
    return e.sort_values("ts", kind="stable").reset_index(drop=True)


def parse_strokes(events: pd.DataFrame, register: pd.DataFrame, timeout_factor: float = 3.0):
    """Returns (strokes, uncommanded).

    strokes: tag, direction, t_cmd, breakaway_s (command -> start switch drops), travel_s (start switch drops ->
             end switch makes), total_s, status (complete / no_move / not_confirmed).
    uncommanded: limit-switch transitions that do not belong to any commanded stroke.
    Timeout per stroke = timeout_factor x the valve's nominal stroke time in that direction.
    """
    reg = register.set_index("tag")
    strokes, uncmd = [], []
    for tag, g in events.groupby("tag", sort=False):
        r = reg.loc[tag]
        cur = None  # the stroke being watched
        state = {}  # last known value of each limit switch

        def close_out(s):
            if s["t_end"] is not None:
                s["status"] = "complete" if s["t_rel"] is not None else "complete_start_switch_not_made"
            elif s["t_rel"] is None and not s["start_already_off"]:
                s["status"] = "no_move"
            else:
                s["status"] = "not_confirmed"
            s["breakaway_s"] = (s["t_rel"] - s["t_cmd"]).total_seconds() if s["t_rel"] is not None else np.nan
            s["travel_s"] = (s["t_end"] - s["t_rel"]).total_seconds() if (s["t_end"] is not None and
                                                                          s["t_rel"] is not None) else np.nan
            s["total_s"] = (s["t_end"] - s["t_cmd"]).total_seconds() if s["t_end"] is not None else np.nan
            s["start_switch_made_before"] = not s["start_already_off"]
            strokes.append({k: s[k] for k in ("tag", "direction", "t_cmd", "breakaway_s", "travel_s", "total_s", "status",
                                                    "start_switch_made_before")})

        for row in g.itertuples(index=False):
            if cur is not None and row.ts > cur["deadline"]:
                close_out(cur)
                cur = None
            if row.signal == "CMD":
                if cur is not None:
                    close_out(cur)
                d = "open" if row.value == 1 else "close"
                nominal = r.open_s if d == "open" else r.close_s
                start, end = ("ZSC", "ZSO") if d == "open" else ("ZSO", "ZSC")
                cur = dict(tag=tag, direction=d, t_cmd=row.ts, t_rel=None, t_end=None, start=start, end=end,
                           start_already_off=state.get(start, 1) == 0,
                           deadline=row.ts + pd.Timedelta(seconds=timeout_factor * nominal + 2))
                continue
            state[row.signal] = row.value
            belongs = cur is not None and ((row.signal == cur["start"] and row.value == 0 and cur["t_rel"] is None) or
                                           (row.signal == cur["end"] and row.value == 1 and cur["t_end"] is None
                                            and (cur["t_rel"] is not None or cur["start_already_off"])))
            if belongs:
                if row.signal == cur["start"]:
                    cur["t_rel"] = row.ts
                else:
                    cur["t_end"] = row.ts
            elif row.ts > g.ts.iloc[0]:  # the first records are the initial state
                uncmd.append(dict(tag=tag, ts=row.ts, signal=row.signal, value=row.value))
        if cur is not None:
            close_out(cur)
    return pd.DataFrame(strokes), pd.DataFrame(uncmd, columns=["tag", "ts", "signal", "value"])
