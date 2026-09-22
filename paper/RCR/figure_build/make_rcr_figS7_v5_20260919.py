"""RCR Figs. S7–S8, v5 demand-pathway fleet detail (PNG only, 155 mm, 600 dpi).

Fig. S7 is the former main-text Fig. 3 (v5_20260915 version), moved to the
SI on 2026-09-19 when the main-text Fig. 3 was rebuilt around terminal fleets
and their resource conditions (``make_rcr_fig23_v5_20260915.py``). It was
reduced on 2026-09-20 to the two panels the main text does not carry - the
per-pathway maps (a) and the terminal-capacity decomposition (b) - after the
trajectory panel was found to duplicate main-text Fig. 3b value for value.

Fig. S8 is the marginal-distribution resource-condition scatter that briefly
served as main-text Fig. 3b in the morning 2026-09-19 version. On 2026-09-20
it was reduced from three pathway facets to the central pathway alone: the
other two pathways' marginals are the ones main-text Fig. 3c, d already
compare, so one facet keeps the per-line view (capacity-weighted markers, the
shared-set outline and the no-sink lines) without re-plotting the comparison.

Outputs
-------
paper/RCR/figures/figS7_demand_pathways_fleet_detail_v5_20260919.png
paper/RCR/figures/figS8_resource_condition_scatter_v5_20260919.png

Caption source
--------------
Fig. S7 | Demand pathways change the identity and composition of the
retained fleet (fleet-detail companion to main-text Fig. 3). (a) Lines
operating in 2060 under the high-, central- and low-demand pathways (408, 336
and 262 lines). The full 2025 fleet is grey; the 213 lines retained under all
three pathways carry a consistent marker (dark circles) and the remaining
retained lines use the shade assigned to each pathway (squares). Boundary:
Tianditu basemap (review-grade depiction subject to the competent map-review
authority); South China Sea shown in the inset with the discontinuous line.
(b) Terminal operating capacity divided into the capacity of the 213-line
shared retained set (327.1 Mt clinker yr-1) and the demand-dependent
remainder: the shared set represents 52.1%, 62.7% and 80.7% of 2060 operating
capacity under high, central and low demand, respectively. Operating-capacity
and capture trajectories are omitted here because main-text Fig. 3b carries
them on the same data.

Fig. S8 | Resource conditions of the 2060 operating lines under the central
pathway (joint-distribution companion to the density summary of main-text
Fig. 3c, d). The AF accessibility ratio kappa*A_i/H_i in 2060 under real
conditions (x; a scenario-invariant property of each line - values below 1
mean the AF allocation cap binds below full heat coverage) against the
distance to the nearest whitelisted sink (y; model-proxy haversine on the
candidate plant-sink arc set, <=500 km), for the 336 lines operating in 2060
under central demand. Marker area is proportional to annual nameplate
capacity, and the 213 lines retained under all three pathways (327.1 Mt
clinker yr-1) carry a dark outline. The nine lines without a whitelisted sink
have no defined distance and are drawn as rug ticks below the zero line; they
are excluded from the distance statistics. The histograms share bin edges and
count scale, and the dark stacked segment marks the shared retained set.
Unweighted medians: kappa*A/H 0.465, nearest-sink 103.7 km. The same
distributions for the high- and low-demand pathways are compared as densities
in main-text Fig. 3c, d.

Verification anchors asserted in this script
--------------------------------------------
Fig. S7: 2060 operating sets 408/336/262 lines; shared retained set 213
lines, 327.081 Mt/yr (±0.001); terminal capacity 628.215/522.009/405.170
Mt/yr (±0.001); terminal capture 366.949/305.254/232.345 Mt/yr (±0.002);
capture onset nodes 2035/2045/2050; shared-set capacity shares
0.5207/0.6266/0.8073 (±5e-4).
Fig. S8: resource-condition table rows match the 2060 operating sets exactly
(408/336/262, all asserted); the plotted facet is the central pathway (336
lines) with 9 no-sink lines; unweighted medians κA/H 0.465 and nearest-sink
103.7 km (±5e-4 / ±0.05); histogram counts close to the line count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "scripts" / "v4" / "figure_system_2026_common.py").exists():
            return candidate
    raise RuntimeError("repository root not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "scripts" / "v4"))
from figure_system_2026_common import (  # noqa: E402
    COLORS,
    DEMAND_COLORS as _PATHWAY_COLORS,
    FS_LABEL,
    FS_LEGEND,
    FS_NOTE,
    apply_style,
    despine,
    panel_label,
    quiet_grid,
)
from make_main_figures_2026_v2 import (  # noqa: E402
    SOUTH_BUFFER,
    _add_south_china_sea_inset,
    _inside_scs_data,
    _legend_frame,
    _load_basemap,
    _project,
)

RESULTS = ROOT / "v5" / "results" / "formal_v1_20260914"
RUNS = {
    "C2": ("C2_demand_high", "S1_baseline"),
    "C1": ("C1_central_J", "S1_baseline"),
    "C3": ("C3_demand_low", "S1_baseline"),
}
OUTDIR = ROOT / "paper" / "RCR" / "figures"

YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
MM = 1 / 25.4

SHARED_COLOR = "#4C5661"
FLEET_COLOR = "#B6B6B6"
# Fig. S8 constants: the capacity-bubble scale is identical to the one in
# make_rcr_fig23_v5_20260915.py (main-text Figs. 2d and 3a).
SHARED_EDGE = "#2E3942"
RUG_Y = -26.0
SIZE_KEY_COLOR = "#8A8A8E"
SIZE_LEGEND_MT = (1.0, 2.0, 3.0)
CONDITIONS_CSV = ROOT / "tmp" / "fig_restructure_20260919" / "fig3b_resource_conditions.csv"
DEMAND_COLORS = {
    "C2": _PATHWAY_COLORS["high"],
    "C1": _PATHWAY_COLORS["central"],
    "C3": _PATHWAY_COLORS["low"],
}
DEMAND_LABELS = {
    "C2": "High demand",
    "C1": "Central demand",
    "C3": "Low demand",
}


def fleet_sizes(cap_mt) -> np.ndarray:
    """Scatter area (pt²) proportional to annual nameplate capacity (Mt/yr)."""
    return 1.2 + 4.6 * np.asarray(cap_mt, dtype=float)


def size_legend_handles(color: str = SIZE_KEY_COLOR) -> list[Line2D]:
    return [
        Line2D([], [], marker="o", ls="", mfc=color, mec="white",
               ms=float(np.sqrt(fleet_sizes(value))), label=f"{value:.0f} Mt/yr")
        for value in SIZE_LEGEND_MT
    ]


def run_dir(label: str) -> Path:
    task, scenario = RUNS[label]
    return RESULTS / task / scenario


def load_csv(label: str, name: str) -> pd.DataFrame:
    return pd.read_csv(run_dir(label) / name)


def load_json(label: str) -> dict:
    task, scenario = RUNS[label]
    return json.loads(
        (RESULTS / task / f"{scenario}_results.json").read_text(encoding="utf-8")
    )


def load_static() -> pd.DataFrame:
    plants = pd.read_excel(
        ROOT / "v5" / "data" / "model_input" / "plants" / "plant_data.xlsx"
    ).rename(columns={"id": "plant_id", "capacity": "capacity_t_per_day"})
    plants = plants[
        ["plant_id", "province", "capacity_t_per_day", "longitude", "latitude"]
    ].copy()
    plants["plant_id"] = plants["plant_id"].astype(int)
    assert len(plants) == 1572 and plants["plant_id"].is_unique
    return plants


def operating_sets(year: int = 2060) -> dict[str, set[int]]:
    result = {}
    for label in RUNS:
        status = load_csv(label, "full_operation_status.csv")
        result[label] = set(
            status.loc[
                (status["period"] == year) & (status["operating"] == 1), "plant_id"
            ].astype(int)
        )
    return result


def _draw_demand_map(
    axis,
    inset,
    china,
    fleet: pd.DataFrame,
    scenario_set: set[int],
    shared_set: set[int],
    color: str,
    title: str,
    letter: str | None = None,
) -> None:
    china.plot(ax=axis, color="#FBFBFB", edgecolor="#333333", linewidth=0.30, zorder=0)
    minx, miny, maxx, maxy = china.total_bounds
    miny = miny - SOUTH_BUFFER * (maxy - miny)
    fleet_points = _project(fleet["longitude"], fleet["latitude"])
    axis.scatter(
        fleet_points.x, fleet_points.y, s=0.7, c=FLEET_COLOR,
        alpha=0.24, linewidths=0, zorder=1,
    )
    for ids, marker, face, size, zorder in (
        (scenario_set - shared_set, "s", color, 8.5, 2.5),
        (shared_set, "o", SHARED_COLOR, 9.0, 3.0),
    ):
        subset = fleet[fleet["plant_id"].isin(ids)]
        points = _project(subset["longitude"], subset["latitude"])
        axis.scatter(
            points.x, points.y, s=size, marker=marker, c=face,
            alpha=0.90, edgecolor="white", linewidth=0.32, zorder=zorder,
        )
    axis.set_xlim(minx, maxx)
    axis.set_ylim(miny, maxy)
    axis.set_xticks([])
    axis.set_yticks([])
    axis.set_title(title, pad=3, color=COLORS["ink"], fontweight="bold")
    for spine in axis.spines.values():
        spine.set_visible(False)
    if letter:
        panel_label(axis, letter)

    fleet_mask = _inside_scs_data(fleet["longitude"], fleet["latitude"])
    inset.scatter(
        fleet_points.x[fleet_mask], fleet_points.y[fleet_mask],
        s=0.40, c=FLEET_COLOR, alpha=0.24, linewidths=0, zorder=1,
    )
    for ids, marker, face, size, zorder in (
        (scenario_set - shared_set, "s", color, 4.2, 2.5),
        (shared_set, "o", SHARED_COLOR, 4.5, 3.0),
    ):
        subset = fleet[fleet["plant_id"].isin(ids)]
        subset = subset[_inside_scs_data(subset["longitude"], subset["latitude"])]
        if subset.empty:
            continue
        points = _project(subset["longitude"], subset["latitude"])
        inset.scatter(
            points.x, points.y, s=size, marker=marker, c=face,
            alpha=0.90, edgecolor="white", linewidth=0.20, zorder=zorder,
        )


def make_figS7(static: pd.DataFrame) -> Path:
    op_sets = operating_sets(2060)
    shared = set.intersection(*op_sets.values())
    assert {label: len(values) for label, values in op_sets.items()} == {
        "C2": 408, "C1": 336, "C3": 262,
    }
    assert len(shared) == 213

    cap_mt = (
        load_csv("C1", "full_plant_summary.csv")
        .set_index("plant_id")["annual_capacity_kt_per_year"] / 1000.0
    )
    shared_capacity = float(cap_mt.loc[list(shared)].sum())
    assert abs(shared_capacity - 327.081) < 0.001

    status = {label: load_csv(label, "full_operation_status.csv") for label in RUNS}
    summaries = {label: load_json(label)["summary"] for label in RUNS}
    capacity_path: dict[str, np.ndarray] = {}
    capture_path: dict[str, np.ndarray] = {}
    terminal_capacity: dict[str, float] = {}
    for label in RUNS:
        values = []
        for year in YEARS:
            active = set(status[label].loc[
                (status[label]["period"] == year) & (status[label]["operating"] == 1),
                "plant_id",
            ].astype(int))
            values.append(float(cap_mt.loc[list(active)].sum()))
        capacity_path[label] = np.array(values)
        capture_path[label] = np.array([
            summaries[label][str(year)]["commercial_captured_co2_kt"] / 1000.0
            for year in YEARS
        ])
        terminal_capacity[label] = values[-1]

    expected_terminal = {"C2": 628.215, "C1": 522.009, "C3": 405.170}
    for label, expected in expected_terminal.items():
        assert abs(terminal_capacity[label] - expected) < 0.001
    expected_capture = {"C2": 366.949, "C1": 305.254, "C3": 232.345}
    for label, expected in expected_capture.items():
        assert abs(capture_path[label][-1] - expected) < 0.002
    for label, onset in {"C2": 2035, "C1": 2045, "C3": 2050}.items():
        positive = [year for year, value in zip(YEARS, capture_path[label]) if value > 0]
        assert positive[0] == onset
    shares = shared_capacity / np.array(
        [terminal_capacity[label] for label in ("C2", "C1", "C3")]
    )
    assert np.allclose(shares, [0.5207, 0.6266, 0.8073], atol=5e-4)

    china, scs = _load_basemap()
    fig = plt.figure(figsize=(155 * MM, 112 * MM))
    grid = fig.add_gridspec(
        2, 3,
        height_ratios=[1.0, 0.60],
        width_ratios=[1.0, 1.0, 1.0],
        left=0.080, right=0.985, top=0.955, bottom=0.095,
        hspace=0.46, wspace=0.08,
    )

    for index, label in enumerate(("C2", "C1", "C3")):
        axis = fig.add_subplot(grid[0, index])
        inset = _add_south_china_sea_inset(axis, scs, rect=(0.74, 0.01, 0.25, 0.27))
        title = f"{DEMAND_LABELS[label]} \u00b7 {len(op_sets[label])} lines"
        _draw_demand_map(
            axis, inset, china, static, op_sets[label], shared,
            DEMAND_COLORS[label], title, "a" if index == 0 else None,
        )

    map_legend = fig.legend(
        handles=[
            Line2D([], [], marker=".", ls="", color=FLEET_COLOR, ms=4.5,
                   label="2025 fleet"),
            Line2D([], [], marker="o", ls="", mfc=SHARED_COLOR, mec="white", ms=4.5,
                   label="Shared retained set"),
            Line2D([], [], marker="s", ls="", mfc=DEMAND_COLORS["C1"],
                   mec="white", ms=4.5, label="Demand-dependent retained lines"),
        ],
        loc="upper center", bbox_to_anchor=(0.50, 0.520),
        ncol=3, frameon=True, fontsize=FS_LEGEND, handletextpad=0.4,
        columnspacing=1.0, borderaxespad=0,
    )
    _legend_frame(map_legend)

    # Terminal operating capacity split into the shared retained set and the
    # demand-dependent remainder (the decomposition cited in the main text).
    ax_composition = fig.add_subplot(grid[1, :2])
    labels = ["High", "Central", "Low"]
    run_labels = ["C2", "C1", "C3"]
    ypos = np.arange(3)[::-1]
    totals = np.array([terminal_capacity[label] for label in run_labels])
    remainder = totals - shared_capacity
    ax_composition.barh(
        ypos, [shared_capacity] * 3, color=SHARED_COLOR,
        edgecolor="white", linewidth=0.35, height=0.62,
    )
    for y, label, extra in zip(ypos, run_labels, remainder):
        ax_composition.barh(
            y, extra, left=shared_capacity, color=DEMAND_COLORS[label],
            edgecolor="white", linewidth=0.35, height=0.62,
        )
    for y, total, share in zip(ypos, totals, shares):
        ax_composition.text(
            shared_capacity / 2, y, f"{100 * share:.1f}%",
            ha="center", va="center", color="white", fontsize=FS_NOTE,
        )
        ax_composition.text(
            total + 8, y, f"{total:.0f}",
            ha="left", va="center", fontsize=FS_NOTE,
        )
    ax_composition.set_yticks(ypos, labels)
    ax_composition.set_xlim(0, 690)
    ax_composition.set_xticks([0, 300, 600])
    ax_composition.set_xlabel("Operating capacity in 2060\n(Mt clinker yr⁻¹)",
                              fontsize=FS_LABEL)
    ax_composition.xaxis.label.set_fontfamily("Helvetica")
    ax_composition.set_title("Shared and demand-dependent", pad=3)
    quiet_grid(ax_composition, "x")
    despine(ax_composition)
    panel_label(ax_composition, "b")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    output = OUTDIR / "figS7_demand_pathways_fleet_detail_v5_20260919.png"
    fig.savefig(output, dpi=600, facecolor="white")
    plt.close(fig)

    print("--- Figure S7 summary ---")
    print("terminal lines:", {label: len(op_sets[label]) for label in RUNS})
    print("terminal capacity (Mt/yr):", {k: round(v, 1) for k, v in terminal_capacity.items()})
    print("shared set:", len(shared), "lines,", round(shared_capacity, 1), "Mt/yr")
    print("shared terminal-capacity shares:", dict(zip(run_labels, np.round(shares, 3))))
    return output


# ---------------------------------------------------------------------------
# Figure S8: resource-condition scatter with marginal distributions
# ---------------------------------------------------------------------------

def load_resource_conditions() -> pd.DataFrame:
    df = pd.read_csv(CONDITIONS_CSV)
    counts = df.groupby("scenario").size().to_dict()
    assert counts == {"C2": 408, "C1": 336, "C3": 262}
    return df


def _scatter_facet_axes(fig, cell, first: dict | None) -> dict:
    facet = cell.subgridspec(
        2, 2, height_ratios=[0.24, 1.0], width_ratios=[1.0, 0.24],
        hspace=0.05, wspace=0.05,
    )
    if first is None:
        ax = fig.add_subplot(facet[1, 0])
        return {
            "ax": ax,
            "ax_xh": fig.add_subplot(facet[0, 0], sharex=ax),
            "ax_yh": fig.add_subplot(facet[1, 1], sharey=ax),
        }
    return {
        "ax": fig.add_subplot(facet[1, 0], sharex=first["ax"], sharey=first["ax"]),
        "ax_xh": fig.add_subplot(facet[0, 0], sharex=first["ax"]),
        "ax_yh": fig.add_subplot(facet[1, 1], sharey=first["ax"]),
    }


def make_figS8() -> Path:
    op_sets = operating_sets(2060)
    assert {label: len(values) for label, values in op_sets.items()} == {
        "C2": 408, "C1": 336, "C3": 262,
    }

    conditions = load_resource_conditions()
    no_sink_counts = {}
    medians = {}
    for label in RUNS:
        sub = conditions[conditions["scenario"] == label]
        assert set(sub["plant_id"].astype(int)) == op_sets[label]
        no_sink_counts[label] = int((~sub["has_sink"]).sum())
        assert no_sink_counts[label] == {"C2": 10, "C1": 9, "C3": 7}[label]
        medians[label] = (
            float(sub["kA_over_H_real_2060"].median()),
            float(sub["nearest_sink_km"].median()),
        )
    for label, (kexp, dexp) in {
        "C2": (0.473, 106.4), "C1": (0.465, 103.7), "C3": (0.484, 102.5),
    }.items():
        assert abs(medians[label][0] - kexp) < 5e-4
        assert abs(medians[label][1] - dexp) < 0.05
    shared_view = conditions[
        (conditions["scenario"] == "C1") & (conditions["in_shared_213"])
    ]
    assert len(shared_view) == 213
    assert abs(shared_view["annual_capacity_mt_per_yr"].sum() - 327.081) < 0.01

    x_edges = np.linspace(0.0, 3.3, 31)
    y_edges = np.linspace(0.0, 500.0, 21)
    histograms = {}
    for label in ("C2", "C1", "C3"):
        sub = conditions[conditions["scenario"] == label]
        dd = sub[~sub["in_shared_213"]]
        sh = sub[sub["in_shared_213"]]
        hx = (
            np.histogram(dd["kA_over_H_real_2060"], bins=x_edges)[0],
            np.histogram(sh["kA_over_H_real_2060"], bins=x_edges)[0],
        )
        with_sink = sub[sub["has_sink"]]
        hy = (
            np.histogram(
                with_sink.loc[~with_sink["in_shared_213"], "nearest_sink_km"],
                bins=y_edges,
            )[0],
            np.histogram(
                with_sink.loc[with_sink["in_shared_213"], "nearest_sink_km"],
                bins=y_edges,
            )[0],
        )
        assert hx[0].sum() + hx[1].sum() == len(sub)
        assert hy[0].sum() + hy[1].sum() == len(with_sink)
        histograms[label] = (hx, hy)
    x_hist_max = max(int((hx[0] + hx[1]).max()) for hx, _ in histograms.values())
    y_hist_max = max(int((hy[0] + hy[1]).max()) for _, hy in histograms.values())

    fig = plt.figure(figsize=(155 * MM, 90 * MM))
    outer = fig.add_gridspec(
        2, 1, height_ratios=[1.0, 0.14],
        left=0.105, right=0.955, top=0.945, bottom=0.075, hspace=0.34,
    )
    # One pathway only (the central case), centred: the other two pathways'
    # distributions are the ones the density panels of main-text Fig. 3c,d
    # already compare.
    scatter_row = outer[0].subgridspec(
        1, 3, width_ratios=[0.28, 1.0, 0.28], wspace=0.08
    )
    first: dict | None = None
    for index, label in enumerate(("C1",)):
        axes = _scatter_facet_axes(fig, scatter_row[0, 1], first)
        first = first or axes
        ax, ax_xh, ax_yh = axes["ax"], axes["ax_xh"], axes["ax_yh"]
        sub = conditions[conditions["scenario"] == label]
        with_sink = sub[sub["has_sink"]]
        no_sink = sub[~sub["has_sink"]]
        dd = with_sink[~with_sink["in_shared_213"]]
        sh = with_sink[with_sink["in_shared_213"]]
        color = DEMAND_COLORS[label]
        ax.scatter(
            dd["kA_over_H_real_2060"], dd["nearest_sink_km"],
            s=fleet_sizes(dd["annual_capacity_mt_per_yr"]), c=color, alpha=0.78,
            edgecolor="white", linewidth=0.25, zorder=2.4,
        )
        ax.scatter(
            sh["kA_over_H_real_2060"], sh["nearest_sink_km"],
            s=fleet_sizes(sh["annual_capacity_mt_per_yr"]), c=color, alpha=0.95,
            edgecolor=SHARED_EDGE, linewidth=0.55, zorder=3.0,
        )
        ax.scatter(
            no_sink["kA_over_H_real_2060"], np.full(len(no_sink), RUG_Y),
            marker="|", s=13, c="#6E6E6E", linewidths=0.8, zorder=2.2,
        )
        hx, hy = histograms[label]
        ax_xh.bar(
            x_edges[:-1], hx[0], width=np.diff(x_edges), align="edge",
            color=color, alpha=0.85, lw=0,
        )
        ax_xh.bar(
            x_edges[:-1], hx[1], width=np.diff(x_edges), align="edge",
            bottom=hx[0], color=SHARED_COLOR, lw=0,
        )
        ax_yh.barh(
            y_edges[:-1], hy[0], height=np.diff(y_edges), align="edge",
            color=color, alpha=0.85, lw=0,
        )
        ax_yh.barh(
            y_edges[:-1], hy[1], height=np.diff(y_edges), align="edge",
            left=hy[0], color=SHARED_COLOR, lw=0,
        )

        ax.set_xlim(0, 3.3)
        ax.set_ylim(-52, 505)
        ax.set_xticks([0, 1, 2, 3])
        ax.set_yticks([0, 150, 300, 450])
        quiet_grid(ax, "x")
        quiet_grid(ax, "y")
        despine(ax)
        if index > 0:
            plt.setp(ax.get_yticklabels(), visible=False)
            ax.tick_params(axis="y", length=0)
        ax_xh.set_ylim(0, x_hist_max * 1.12)
        ax_xh.set_yticks([])
        ax_xh.tick_params(axis="x", labelbottom=False, length=0)
        despine(ax_xh)
        ax_xh.spines["left"].set_visible(False)
        ax_yh.set_xlim(0, y_hist_max * 1.12)
        ax_yh.set_xticks([])
        plt.setp(ax_yh.get_yticklabels(), visible=False)
        ax_yh.tick_params(axis="y", length=0)
        despine(ax_yh)
        ax_yh.spines["bottom"].set_visible(False)
        ax_xh.set_title(f"{DEMAND_LABELS[label]} · {len(sub)} lines", pad=3)
        ax.set_ylabel("Nearest whitelisted sink (km)")
        ax.set_xlabel(r"$\kappa A_i/H_i$ in 2060 (real conditions)")

    ax_legend = fig.add_subplot(outer[1])
    ax_legend.axis("off")
    highlight_legend = ax_legend.legend(
        handles=[
            Line2D([], [], marker="o", ls="", mfc="#D8DEE3", mec=SHARED_EDGE,
                   mew=0.7, ms=4.5,
                   label="Retained in all three pathways (213 lines)"),
            Line2D([], [], marker="|", ls="", color="#6E6E6E", ms=5.0,
                   label="No whitelisted sink (n = 9)"),
        ],
        loc="center left", frameon=False, borderaxespad=0, handlelength=1.2,
        handletextpad=0.4, labelspacing=0.40,
    )
    ax_legend.add_artist(highlight_legend)
    ax_legend.legend(
        handles=size_legend_handles(),
        loc="center right", frameon=False, borderaxespad=0, handlelength=0.9,
        handletextpad=0.25, labelspacing=0.40, ncol=3, columnspacing=0.7,
    )

    OUTDIR.mkdir(parents=True, exist_ok=True)
    output = OUTDIR / "figS8_resource_condition_scatter_v5_20260919.png"
    fig.savefig(output, dpi=600, facecolor="white")
    plt.close(fig)

    print("--- Figure S8 summary ---")
    print("lines plotted:", len(conditions[conditions["scenario"] == "C1"]))
    print("no-sink lines:", no_sink_counts)
    print("unweighted medians (kA/H, km):",
          {k: (round(v[0], 3), round(v[1], 1)) for k, v in medians.items()})
    return output


def main() -> None:
    apply_style()
    static = load_static()
    print(make_figS7(static))
    print(make_figS8())


if __name__ == "__main__":
    main()
