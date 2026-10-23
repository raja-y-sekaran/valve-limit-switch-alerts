"""Operator alerts from limit-switch timing, plus the plain DCS alarms they are compared with.

Rules (priority in brackets):
  fail_to_move     [High]   command given, valve never left its end position
  not_confirmed    [High]   valve left, but the end switch did not make in time (part-open valve or switch fault)
  limit_exceeded   [High for SDV closing, Medium otherwise]  stroke slower than the required / timeout limit
  slow_trend       [Low]    stroke time drifting up against the valve's own baseline (EWMA), with a projected
                            date when it will reach its limit
  sticking         [Low]    breakaway time repeatedly far above baseline: the valve hesitates before moving
  chattering       [Medium] limit switch toggling with no command; one alert, then shelved for 24 h
  uncommanded      [Medium] single position change with no command
Repeats of the same rule on the same valve within 24 h are suppressed and counted (ISA-18.2 practice).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SHELVE = pd.Timedelta(hours=24)


def _limit(reg, tag, d):
    r = reg.loc[tag]
    return r.open_limit_s if d == "open" else r.close_limit_s


def raw_alerts(strokes, uncmd, register, base, ewma_lambda=0.25, trend_ratio=1.12, stick_factor=3.0):
    reg = register.set_index("tag")
    b = base.set_index(["tag", "direction"])
    out = []

    def A(tag, ts, rule, prio, msg):
        out.append(dict(tag=tag, ts=ts, rule=rule, priority=prio, message=msg))

    for (tag, d), g in strokes.sort_values("t_cmd").groupby(["tag", "direction"]):
        sdv = reg.loc[tag].service == "shutdown valve"
        lim = _limit(reg, tag, d)
        bb = b.loc[(tag, d)] if (tag, d) in b.index else None
        ew, recent_break, hist = 0.0, [], []
        for s in g.itertuples(index=False):
            pos_from, pos_to = ("closed", "open") if d == "open" else ("open", "closed")
            if s.status == "no_move":
                A(tag, s.t_cmd, "fail_to_move", "High", f"{tag} did not leave {pos_from} position on {d} command")
                continue
            if s.status == "not_confirmed":
                nominal = reg.loc[tag].open_s if d == "open" else reg.loc[tag].close_s
                A(tag, s.t_cmd, "not_confirmed", "High",
                  f"{tag} {d} command: {pos_to} switch not made within {3 * nominal + 2:.0f} s: "
                  f"valve stuck part-way or {pos_to} switch fault")
                continue
            over = s.total_s > lim
            if over:
                A(tag, s.t_cmd, "limit_exceeded", "High" if (sdv and d == "close") else "Medium",
                  f"{tag} {d} time {s.total_s:.1f} s exceeds limit {lim:.1f} s")
            if bb is None or s.t_cmd <= bb.learn_until:
                continue
            ratio = s.total_s / bb.base_total_s
            ew = ewma_lambda * np.log(ratio) + (1 - ewma_lambda) * ew
            hist.append((s.t_cmd, s.total_s))
            if not over and np.exp(ew) > trend_ratio and len(hist) >= 3 and all(x > bb.base_total_s * 1.05 for _, x in hist[-3:]):
                tt = np.array([(t - hist[-8:][0][0]).total_seconds() / 86400 for t, _ in hist[-8:]])
                yy = np.array([x for _, x in hist[-8:]])
                slope = np.polyfit(tt, yy, 1)[0] if len(tt) >= 4 and np.ptp(tt) > 0 else 0
                proj = f", projected to reach the {lim:.1f} s limit in about {(lim - yy[-1]) / slope:.0f} days" \
                    if slope > 0 and yy[-1] < lim else ""
                A(tag, s.t_cmd, "slow_trend", "Low",
                  f"{tag} {d} time trending up: {s.total_s:.1f} s vs normal {bb.base_total_s:.1f} s "
                  f"(+{100 * (s.total_s / bb.base_total_s - 1):.0f}%){proj}. Check air supply, actuator, packing")
            hi = s.breakaway_s > max(stick_factor * bb.base_break_s, bb.base_break_s + 8 * bb.mad_break_s)
            recent_break = (recent_break + [hi])[-6:]
            if hi and sum(recent_break) >= 2:
                A(tag, s.t_cmd, "sticking", "Low",
                  f"{tag} hesitating on {d}: breakaway {s.breakaway_s:.1f} s vs normal {bb.base_break_s:.1f} s "
                  f"({sum(recent_break)} of last {len(recent_break)} strokes)")

    for (tag, sig), g in uncmd.sort_values("ts").groupby(["tag", "signal"]):
        ts = list(g.ts)
        i = 0
        while i < len(ts):
            j = i
            while j + 1 < len(ts) and (ts[j + 1] - ts[i]).total_seconds() <= 60:
                j += 1
            if j - i + 1 >= 3:
                A(tag, ts[i], "chattering", "Medium", f"{tag}.{sig} chattering: {j - i + 1} changes in 60 s with no command")
            else:
                for k in range(i, j + 1):
                    A(tag, ts[k], "uncommanded", "Medium", f"{tag}.{sig} changed with no command")
            i = j + 1
    return pd.DataFrame(out, columns=["tag", "ts", "rule", "priority", "message"]).sort_values("ts").reset_index(drop=True)


def shelve(alerts: pd.DataFrame, window=SHELVE) -> pd.DataFrame:
    """Keep the first alert per valve and rule; suppress repeats within the window and count them."""
    kept, last = [], {}
    for a in alerts.itertuples(index=False):
        k = (a.tag, a.rule)
        if k in last and a.ts - kept[last[k]]["ts"] < window:
            kept[last[k]]["repeats_suppressed"] += 1
            continue
        last[k] = len(kept)
        kept.append(dict(a._asdict(), repeats_suppressed=0))
    return pd.DataFrame(kept)


def dcs_alarms(strokes, uncmd, register) -> pd.DataFrame:
    """What a typical DCS raises with no analytics: travel-timeout / failure alarms per stroke and an
    alarm for every uncommanded switch change. No trend, no sticking, no chatter suppression."""
    reg = register.set_index("tag")
    out = []
    for s in strokes.itertuples(index=False):
        lim = _limit(reg, s.tag, s.direction)
        if s.status != "complete":
            out.append(dict(tag=s.tag, ts=s.t_cmd, rule="travel_failure"))
        elif s.total_s > lim:
            out.append(dict(tag=s.tag, ts=s.t_cmd, rule="travel_timeout"))
    for u in uncmd.itertuples(index=False):
        out.append(dict(tag=u.tag, ts=u.ts, rule="uncommanded"))
    return pd.DataFrame(out, columns=["tag", "ts", "rule"]).sort_values("ts").reset_index(drop=True)
