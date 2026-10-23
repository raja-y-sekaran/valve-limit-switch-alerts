"""One place for every folder the project reads or writes (course layout)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
GROUND_TRUTH = DATA_RAW / "ground_truth"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_SAMPLE = ROOT / "data" / "sample"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"

for _p in (DATA_RAW, GROUND_TRUTH, DATA_PROCESSED, DATA_SAMPLE, MODELS, REPORTS, FIGURES):
    _p.mkdir(parents=True, exist_ok=True)
