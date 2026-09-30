from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent
SIGNALS = ["fuel_flow", "altitude", "speed", "wind"]
UNITS = {"fuel_flow": "lb/h", "altitude": "ft", "speed": "km/h", "wind": "kt"}
BROKEN_FLIGHTS = [7, 12, 44]
# Loose physical bounds: they catch spikes only, the data grid sits well inside.
VALID_RANGE = {
    "fuel_flow": (0, 1_000),
    "altitude": (0, 15_000),
    "speed": (0, 300),
    "wind": (0, 100),
}


def load() -> dict[str, pd.DataFrame]:
    return {s: pd.read_pickle(DATA_DIR / f"signals_{s}.pkl") for s in SIGNALS}


def to_long(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per (t, flight)."""
    return (
        pd.concat({s: df.astype(float).stack() for s, df in raw.items()}, axis=1)  # noqa: PD013  melt drops the (t, flight) index
        .rename_axis(["t", "flight"])
        .reset_index()
    )


def in_range(df: pd.DataFrame) -> pd.Series:
    checks = [df[s].between(lo, hi, inclusive="right") for s, (lo, hi) in VALID_RANGE.items()]
    return pd.concat(checks, axis=1).all(axis=1)


def operating_points(long: pd.DataFrame) -> pd.DataFrame:
    """One row per steady segment, so long segments don't weigh more."""
    samples = long.dropna()
    samples = samples[~samples.flight.isin(BROKEN_FLIGHTS)]
    samples = samples[in_range(samples)]
    return samples.drop_duplicates(["flight", *SIGNALS]).reset_index(drop=True)
