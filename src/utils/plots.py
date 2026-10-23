"""Stroke-time history for a drifting valve, and the alert load against plain DCS alarms."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.utils.paths import FIGURES as DOCS

BLUE, ORANGE, RED, AQUA, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#e34948", "#1baf7a", "#0b0b0b", "#52514e", "#e4e3df"


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    ax.grid(True, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)


def drift_timeline(strokes, alerts, dcs, det, reg, base, tag=None):
    d0 = det[det.fault == "drift"].sort_values("earlier_than_dcs_days", ascending=False)
    tag = tag or d0.tag.iloc[0]
    f = d0.set_index("tag").loc[tag]
    st = strokes[(strokes.tag == tag) & (strokes.status == "complete")]
    b = base.set_index(["tag", "direction"])
    direction = st.groupby("direction").total_s.max().idxmax()
    s = st[st.direction == direction]
    r = reg.set_index("tag").loc[tag]
    lim = r.open_limit_s if direction == "open" else r.close_limit_s
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    _style(ax)
    ax.scatter(s.t_cmd, s.total_s, s=7, color=BLUE, alpha=0.6, label=f"{direction} stroke time (each stroke)")
    ax.axhline(b.loc[(tag, direction)].base_total_s, color=MUTED, lw=1, ls=":", label="valve's own normal (first 60 days)")
    ax.axhline(lim, color=RED, lw=1.2, ls="--", label=f"DCS travel limit {lim:.0f} s")
    ax.axvline(f.onset, color=MUTED, lw=1, alpha=0.6)
    ymax = max(s.total_s.max(), lim) * 1.12
    ax.text(f.onset, ymax * 0.06, " fault starts\n (hidden from\n the alerts)", fontsize=7.5, color=MUTED, va="bottom")
    for t, lab, c in [(f.alert_first, "trend alert", ORANGE), (f.dcs_first, "DCS alarm", RED)]:
        ax.annotate(lab, (t, ymax * 0.97), xytext=(0, 0), textcoords="offset points", ha="center", fontsize=8, color=INK)
        ax.plot([t, t], [0, ymax * 0.94], color=c, lw=1.6)
    ax.annotate("", xy=(f.alert_first, ymax * 0.88), xytext=(f.dcs_first, ymax * 0.88),
                arrowprops=dict(arrowstyle="<->", color=INK, lw=0.9))
    mid = f.alert_first + (f.dcs_first - f.alert_first) / 2
    ax.text(mid, ymax * 0.89, f"{f.earlier_than_dcs_days:.0f} days earlier", ha="center", va="bottom", fontsize=8.5)
    ax.set_ylim(0, ymax)
    ax.set_ylabel("Stroke time, command to end switch (s)", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.set_title(f"{tag}: slow-stroke drift caught before the travel limit", fontsize=11.5, loc="left")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.text(0.01, 0.01, "Synthetic SOE data.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(DOCS / "drift_timeline.png")
    plt.close(fig)


def alert_load(alerts, dcs):
    a = alerts.set_index("ts").resample("W").size()
    d = dcs.set_index("ts").resample("W").size()
    idx = pd.date_range(pd.Timestamp("2025-01-05"), max(a.index.max(), d.index.max()), freq="W")
    a, d = a.reindex(idx, fill_value=0), d.reindex(idx, fill_value=0)
    fig, ax = plt.subplots(figsize=(9, 3.6), dpi=150)
    _style(ax)
    ax.plot(idx, d.values, color=RED, lw=1.8, label=f"plain DCS alarms ({len(dcs):,} in the year)")
    ax.plot(idx, a.values, color=BLUE, lw=1.8, label=f"operator alerts, de-duplicated ({len(alerts):,})")
    ax.set_ylabel("Per week, 45 valves", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.set_ylim(0, None)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    ax.set_title("Alert load: same faults, a fifth of the alarms", fontsize=11.5, loc="left")
    fig.tight_layout()
    fig.savefig(DOCS / "alert_load.png")
    plt.close(fig)
