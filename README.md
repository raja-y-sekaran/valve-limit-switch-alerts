# Valve limit-switch alerts

**Use the limit-switch timing every on/off and shutdown valve already sends to the DCS to warn operators and maintenance before a valve fails to close in time, and to replace floods of raw position alarms with a few alerts that name the likely cause.**

![Slow-stroke drift caught before the travel limit](docs/drift_timeline.png)

## Why it matters

A shutdown valve that closes too slowly can defeat the safety function it belongs to. A process on/off valve that sticks or fails to travel trips units and spoils batches. The evidence builds up for weeks in the sequence-of-events (SOE) record: every command, and the moment each limit switch drops and makes. But a plain DCS only uses it for a fixed travel-timeout alarm, which fires once the valve is already too slow. Meanwhile a loose switch cam can raise hundreds of "uncommanded change" alarms a week. That is the nuisance load ISA-18.2 alarm management sets out to remove.

## Approach

```mermaid
flowchart LR
    A[SOE log<br/>CMD, ZSO, ZSC changes] --> B[Strokes<br/>breakaway = command to start switch drops<br/>travel = start switch drops to end switch makes]
    B --> C[Per-valve baseline<br/>median + MAD, first 60 days]
    C --> D[Rules<br/>limits, EWMA trend, repeated sticking,<br/>failure to move, chatter]
    D --> E[Operator alerts<br/>priority, cause, 24 h shelving]
```

| Alert | Priority | What triggers it | Why this technique |
|---|---|---|---|
| Failure to move | High | Command given, start switch never drops | Unambiguous, so it needs no statistics |
| Travel not confirmed | High | Valve left its end position but the other switch didn't make in time | Says plainly that it's *either* a part-open valve *or* a switch fault; the field check decides which |
| Limit exceeded | High for SDV closing, Medium otherwise | Stroke time above the required closing time (SDV) or travel timeout (XV) | The existing hard limit, kept as is |
| Slow-stroke trend | Low | EWMA of stroke time against the valve's **own** baseline above +12%, with the last 3 strokes all slow; the message gives a projected date for reaching the limit | Each valve has its own normal time, so one fleet-wide threshold would be too loose for some valves and too tight for others. EWMA filters single slow strokes (cold start, low air) |
| Sticking | Low | Breakaway time more than 3× normal in at least 2 of the last 6 strokes | A valve that hesitates before moving can still finish in time; separating breakaway from travel exposes it |
| Chattering switch | Medium | 3 or more uncommanded changes of one switch within 60 s; one alert, then shelved for 24 h | ISA-18.2 chattering-alarm handling |

Repeats of the same alert on the same valve within 24 hours are suppressed and counted rather than re-announced.

Example messages (taken from `outputs/operator_alerts.csv`):

| Priority | Message |
|---|---|
| Low | XV-1127 open time trending up: 3.6 s vs normal 3.1 s (+19%), projected to reach the 5.3 s limit in about 21 days. Check air supply, actuator, packing |
| Low | XV-1113 hesitating on close: breakaway 3.1 s vs normal 0.6 s (2 of last 6 strokes) |
| High | XV-1102 open command: open switch not made within 8 s: valve stuck part-way or open switch fault |
| High | SDV-2110 did not leave open position on close command |
| Medium | SDV-2106.ZSO chattering: 7 changes in 60 s with no command |

## How it was validated

The SOE log is simulated: 45 valves (30 process on/off XVs cycling several times a day, and 15 SDVs stroke-tested weekly) over one year. Twenty faults are injected at random hidden onset times, four of each type: slow-stroke drift, intermittent sticking, failure to move, end-switch failure and a chattering switch. About 1% of healthy strokes are one-off slow strokes that should **not** raise an alert.

1. **Detection and timing** for every injected fault: the first matching alert after onset, against the first plain DCS alarm (travel timeout / travel failure / uncommanded change).
2. **Right cause named:** did an alert of the matching kind fire, not just any alert?
3. **False alerts:** any alert on a healthy valve, or on a faulty valve before its fault began.
4. **Alert load** against the plain DCS alarms, in ISA-18.2 terms (alerts per day, peak day).
5. **Six simulated fleets** (seeds), so the result is not one lucky draw: `python scripts/robustness.py`.
6. **Unit tests** for stroke parsing (including a stroke that starts with its switch already off because of an earlier switch fault), trend versus one-off slow strokes, the sticking-repeat rule, and chatter shelving.

Testing exposed two problems, both fixed:
- After an end-switch fault, the parser called the next healthy stroke "failed to move".
- One-off slow strokes on an SDV were being recorded as a drift's first limit breach.

## Results on the sample data

| Fault (4 each) | Detected | Cause named | Median delay after onset | Ahead of the plain DCS alarm |
|---|---|---|---|---|
| Slow-stroke drift | 4 / 4 | 4 / 4 | 14 days | **16, 40 and 52 days** on the three XVs; 0 on the weekly-tested SDV |
| Sticking | 4 / 4 | 4 / 4 | 1.2 days | same time (the long hesitation also tripped the travel limit) |
| Failure to move | 4 / 4 | 4 / 4 | 5.7 days | same time (the first failed stroke) |
| End-switch failure | 4 / 4 | 4 / 4 | 0.4 days | same time |
| Chattering switch | 4 / 4 | 4 / 4 | 0.1 days | same time |

| Alert load (one year, 45 valves) | Operator alerts | Plain DCS alarms |
|---|---|---|
| Total | **2,044** | 10,156 |
| Per day (mean / peak day) | 7.1 / 16 | 35.1 / 86 |
| From the 4 chattering switches | 613 | 6,470 |
| False alerts (25 healthy valves, and before onset) | **0** | — |

![Alert load against plain DCS alarms](docs/alert_load.png)

**Across six simulated fleets (120 faults):** all 120 detected, with the right cause named for 119, and 3 false alerts in total, about one per 90 valve-years. Two were early "trend" alerts on healthy valves after a run of slow strokes. One was a healthy SDV whose one-off slow closure really did exceed its closing spec, so the plain DCS alarmed too. Operator alerts were 20–28% of the plain DCS alarm count. For drift, the trend alert came ahead of the travel-limit alarm by a median of **31 days on process valves** (range 9–63) but only **4 days on SDVs** (range 0–10). An SDV is stroked only weekly, so a fast drift reaches the limit within a few tests.

**What this means in practice.** The gain is in two places:
- **Slow drift on frequently-cycled valves.** Weeks of warning give time to fix the air supply or actuator before the valve fails its stroke.
- **Alert quality.** Each alert names the likely cause, and a fifth of the alarms means operators actually see them.

Sudden failures are found at the first failed stroke, just as the DCS finds them. For SDVs, the honest conclusion is that a weekly test gives too few data points for an early warning. A partial-stroke test, or a richer signal (actuator pressure), would be needed.

The load grows through the simulated year because faulty valves are never repaired in the simulation. In a plant, each alert would lead to a work order.

## How to run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/generate_events.py        # optional: the sample SOE log is already in data/
python run.py                         # strokes, alerts, scoring, figures (about 10 s)
pytest                                # unit tests
python scripts/robustness.py          # six simulated fleets (about 1 min)
```

## Outputs

| File | Contents |
|---|---|
| `outputs/operator_alerts.csv` | Every alert: valve, time, rule, priority, message, repeats suppressed |
| `outputs/strokes.csv.gz` | One row per stroke: breakaway, travel and total time, status |
| `outputs/valve_baselines.csv` | Each valve's normal stroke and breakaway times per direction |
| `outputs/fault_detection.csv` | Per injected fault: first alert, first DCS alarm, delays, cause named |
| `outputs/metrics.json` | Summary numbers |

## Limits

- The baseline is learned once, from the first 60 days. After maintenance on a valve, it should be re-learned.
- Thresholds (12% trend, 3× breakaway, 3 changes in 60 s) are tuned on simulated data and would need tuning on a real plant's history.
- Only limit-switch timing is used. Smart positioners and partial-stroke tests give richer data, especially for SDVs.
- Simulated noise is simpler than the real thing: no air-header events affecting many valves at once, no DCS scan-time effects.

## Data note

**All data in this repository is simulated** by `data/generate_events.py`. Valve tags, timings, limits and faults are invented. No employer data, SOE logs, DCS exports, valve lists or plant names were used.

This is a public re-implementation of a personal prototype built on sample data. It has not been deployed at any plant.

## Credits

Built with Claude Code; design, requirements and validation by Raja (Rajayoganandha Sekaran).

Licence: MIT.
