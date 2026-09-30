from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
import pandas as pd


def design(columns: Sequence[npt.ArrayLike]) -> np.ndarray:
    """Feature columns plus an intercept column (last)."""
    return np.column_stack([*columns, np.ones(len(np.asarray(columns[0])))])


def fit(columns: Sequence[npt.ArrayLike], y: npt.ArrayLike) -> np.ndarray:
    """Least-squares coefficients, intercept last."""
    return np.linalg.lstsq(design(columns), np.asarray(y), rcond=None)[0]


def r2(y: npt.ArrayLike, pred: npt.ArrayLike) -> float:
    y, pred = np.asarray(y), np.asarray(pred)
    return float(1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2))


def split_by_flight(points: pd.DataFrame, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """80/20 split on whole flights: points of one flight share sensors, a point split leaks."""
    flights = points.flight.unique()
    test = np.random.default_rng(seed).choice(flights, size=len(flights) // 5, replace=False)
    is_test = points.flight.isin(test)
    return points[~is_test], points[is_test]
