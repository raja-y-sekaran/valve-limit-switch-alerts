"""Parse the SOE log, raise operator alerts, score them against the injected faults, draw the figures."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from valve_alerts import figures, pipeline  # noqa: E402

if __name__ == "__main__":
    strokes, alerts, dcs, det, summary, load, reg, faults, base = pipeline.run()
    figures.drift_timeline(strokes, alerts, dcs, det, reg, base)
    figures.alert_load(alerts, dcs)
    print(summary.to_string(index=False))
    print(json.dumps(load, indent=2))
