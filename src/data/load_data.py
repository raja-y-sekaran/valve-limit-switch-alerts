"""Load the valve register and the raw SOE log."""
import pandas as pd

from src.data.preprocess import load_events
from src.utils.paths import DATA_RAW, GROUND_TRUTH


def load_data():
    """Returns (register, prepared SOE events)."""
    return pd.read_csv(DATA_RAW / "valve_register.csv"), load_events(DATA_RAW / "soe_events.csv.gz")


def load_truth():
    """Injected faults with their onset times, for scoring only (known because the data is synthetic)."""
    return pd.read_csv(GROUND_TRUTH / "faults.csv")
