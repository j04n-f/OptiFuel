import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from cleanup import SIGNALS, UNITS


def flight_signals(raw: dict[str, pd.DataFrame], flight: int) -> Figure:
    fig, axes = plt.subplots(4, 1, figsize=(8, 7), sharex=True)
    for ax, s in zip(axes, SIGNALS, strict=True):
        ax.step(raw[s].index, raw[s][flight].astype(float), where="post")
        ax.set_ylabel(f"{s}\n[{UNITS[s]}]")
    axes[-1].set_xlabel("sample")
    fig.suptitle(f"Flight {flight}: signals move in steps")
    fig.tight_layout()
    return fig


def features_vs_fuel(points: pd.DataFrame) -> Figure:
    features = ["altitude", "speed", "wind"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.5), sharey=True)
    for ax, f in zip(axes, features, strict=True):
        ax.scatter(points[f], points.fuel_flow, s=6, alpha=0.5)
        ax.set_xscale("log")
        ax.set_xlabel(f"{f} [{UNITS[f]}]")
    axes[0].set_yscale("log")
    axes[0].set_ylabel("fuel flow [lb/h]")
    fig.tight_layout()
    return fig


def speed_fit(q2: pd.DataFrame, slope: float, intercept: float, residual: pd.Series) -> Figure:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    sc = ax1.scatter(q2.speed, q2.fuel_flow, c=q2.wind, cmap="viridis", s=18)
    grid_v = np.linspace(q2.speed.min(), q2.speed.max(), 50)
    label = f"ff = {slope:.4f} v + {intercept:.4f}"
    ax1.plot(grid_v, slope * grid_v + intercept, "r-", label=label)
    ax1.set(xlabel="speed [km/h]", ylabel="fuel flow [lb/h]", title="8000 ft")
    ax1.legend()
    fig.colorbar(sc, ax=ax1, label="wind [kt]")
    _residual_vs_wind(ax2, q2.wind, residual, "error [lb/h]")
    fig.tight_layout()
    return fig


def altitude_fit(
    q3: pd.DataFrame, prefactor: float, exponent: float, residual: pd.Series
) -> Figure:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    # h^-2 diverges at 0 ft.
    grid_h = np.linspace(250, 15_000, 300)
    label = f"ff = {prefactor:.3g} h^{exponent:.2f}"
    ax1.plot(grid_h, prefactor * grid_h**exponent, "r-", label=label)
    ax1.scatter(q3.altitude, q3.fuel_flow, c=q3.wind, cmap="viridis", s=18, zorder=3)
    for lo, hi in [(0, q3.altitude.min()), (q3.altitude.max(), 15_000)]:
        ax1.axvspan(lo, hi, color="grey", alpha=0.2)
    ax1.text(10_300, 20, "extrapolated", color="grey")
    ax1.set(yscale="log", xlim=(0, 15_000), xlabel="altitude [ft]", ylabel="fuel flow [lb/h]")
    ax1.set_title("166.25 km/h")
    ax1.legend()
    _residual_vs_wind(ax2, q3.wind, residual, "log error")
    fig.tight_layout()
    return fig


def model_map(points: pd.DataFrame, c: float, b_v: float, b_h: float) -> Figure:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.5))
    v, h = np.meshgrid(np.linspace(23.75, 237.5, 100), np.linspace(1_000, 10_000, 100))
    cs = ax1.contourf(v, h, np.log10(c * v**b_v * h**b_h), levels=20, cmap="viridis")
    ax1.scatter(points.speed, points.altitude, s=3, c="w", alpha=0.5)
    fig.colorbar(cs, ax=ax1, label="log10 fuel flow [lb/h]")
    ax1.set(xlabel="speed [km/h]", ylabel="altitude [ft]", title="fuel predicted by the rule")
    pred = c * points.speed**b_v * points.altitude**b_h
    ax2.scatter(pred, np.log(points.fuel_flow / pred), s=6, alpha=0.5)
    ax2.axhline(0, color="k", lw=0.5)
    ax2.set(xscale="log", xlabel="predicted fuel flow [lb/h]", ylabel="log error")
    ax2.set_title("errors: ~1%, no pattern")
    fig.tight_layout()
    return fig


def _residual_vs_wind(ax: plt.Axes, wind: pd.Series, residual: pd.Series, ylabel: str) -> None:
    ax.scatter(wind, residual, s=12)
    ax.axhline(0, color="k", lw=0.5)
    ax.set(xlabel="wind [kt]", ylabel=ylabel, title="error vs wind: no pattern")
