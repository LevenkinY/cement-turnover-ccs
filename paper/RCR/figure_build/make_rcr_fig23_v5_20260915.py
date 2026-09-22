"""RCR Figures 2–3, v5 demand-aligned rebuild (PNG only, 190 mm, 600 dpi).

Rebuilt 2026-09-19; restructured 2026-09-20 after the Results-outline review
(``v5/docs/RCR_figures_revision_spec_20260920.md``). Figure 2 now carries the
per-node turnover counts as its panel c (the capacity-composition and
retained-fleet maps that previously occupied Fig. 2c/2d were dropped: the
geography is Fig. 3a). Figure 3 keeps the difference-oriented design of
2026-09-19 and changes only panel a's resource underlay — the bioenergy
potential shading gave way to the storage-node layer (the model's ≥10 Mt
node-capacity screen, DSA-only vs EOR-capable symbols), because the
storage-access screen is the binding resource condition of the capture era.

Figure 2 uses S1 only. It connects line-level lifecycle and residual-emission
histories to the per-node turnover decisions and to national AF and capture
sequencing.

Figure 3 compares S2 high, S1 central and S3 low demand directly. All marker
areas that encode annual nameplate capacity use one scale (``fleet_sizes``),
used by the Fig. 3a map.

Outputs
-------
paper/RCR/figures/fig2_capacity_turnover_emissions_capture_atlas_v5_20260915.png
paper/RCR/figures/fig3_spatial_suitability_conditional_priorities_v5_20260915.png

Caption source
--------------
Fig. 2 | Fleet consolidation and mitigation sequencing under the central
demand pathway (S1). (a) Lifecycle state of the 1,572 inherited clinker lines
at the eight five-year decision nodes, grouped by last operating node and
sorted identically in a and b. (b) Residual direct emissions after commercial
capture for the same rows and row order; the square-root colour scale is
capped at the 99.5th percentile of positive values, white marking zero.
(c) Turnover at each node: retirements before expiry (light grey) and at or
after expiry (dark grey), same-site renewals (green) and first commercial-CCS
deployments (blue); expiry is the 40-year service life, and lines below
3,200 t d-1 have no renewal option. (d) National AF heat substitution and
accounted gross direct emissions, split into capture credit and net direct
emissions.

Fig. 3 | Demand pathways rescale the fleet around a stable shared core.
(a) Lines operating in 2060 under at least one of the three demand pathways,
divided into those retained under all three (dark blue) and the
demand-dependent remainder (light blue-grey); marker area is proportional to
annual nameplate capacity and the full 2025 fleet is grey. Grey symbols are
the storage nodes retained by the model's >=10 Mt node-capacity screen
(DSA-only circles, EOR-capable triangles). (b) Operating capacity (solid) and
commercial capture (dashed) at the eight decision nodes under high, central
and low demand. (c, d) Kernel densities of the resource conditions of the
2060 operating lines - the AF accessibility ratio kappa*A_i/H_i (c) and the
distance to the nearest whitelisted sink (d) - for the three pathways and for
the shared retained set (dark); ticks mark unweighted medians. Boundary:
Tianditu basemap (review-grade depiction subject to the competent map-review
authority); South China Sea shown in the inset with the discontinuous line.
The per-line view of the resource conditions is Fig. S8.

Verification anchors asserted in this script
--------------------------------------------
Fig. 2: 1,572 inherited lines; S1 operating lines
1,572/723/577/514/443/359/339/336 at the eight nodes; 2060 operating
capacity 522.009 Mt/yr (±0.001); capture credit non-negative; retirements
per node 849/146/63/71/84/20/3 (total 1,236) split
into 1,088 before expiry and 148 at or after expiry, the two classes closing
on the observed operating-count differences at every node; renewals per node
0/1/0/1/11/84/162/35 (total 294); first CCS deployments 224 (2045) and 103
(2050), cumulative 327, and the cumulative first-deployment count equals the
number of lines with positive capture capacity at every node.
Fig. 3: 2060 operating sets 408/336/262 lines; terminal capacity
628.215/522.009/405.170 Mt/yr (±0.001); terminal capture
366.949/305.254/232.345 Mt/yr (±0.002) with capture-onset nodes
2035/2045/2050; shared retained set 213 lines, 327.081 Mt/yr (±0.001),
capacity shares 0.5207/0.6266/0.8073 (±5e-4); union across pathways 462
lines (716.224 Mt/yr, ±0.001), demand-dependent margin 249 lines (389.143
Mt/yr, ±0.001); resource-condition table rows match the operating sets
exactly; no-sink lines 10/9/7; unweighted medians κA/H 0.473/0.465/0.484
(±5e-4) and nearest-sink 106.4/103.7/102.5 km (±0.05); shared-set medians
0.473 and 103.6 km; storage layer 1,564 nodes (1,285 DSA-only, 279
EOR-capable) from the ≥10 Mt screen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.transforms import blended_transform_factory
from scipy import stats


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
    _scs_boundary_layer,
)

RESULTS = ROOT / "v5" / "results" / "formal_v1_20260914"
RUNS = {
    "C2": ("C2_demand_high", "S1_baseline"),
    "C1": ("C1_central_J", "S1_baseline"),
    "C3": ("C3_demand_low", "S1_baseline"),
}
CONDITIONS_CSV = ROOT / "tmp" / "fig_restructure_20260919" / "fig3b_resource_conditions.csv"
STORAGE_CSV = ROOT / "v5" / "data" / "model_input" / "storage" / "storage_data_tif.csv"
OUTDIR = ROOT / "paper" / "RCR" / "figures"

YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
MM = 1 / 25.4

# Model settings that define panel c's classes (config_v5.py: plant lifetime,
# the base year the effective commissioning year is anchored to, and the
# capacity floor below which a line has no same-site renewal option).
PLANT_LIFETIME_YEARS = 40
BASE_YEAR = 2025
RENEWAL_MIN_CAPACITY_TD = 3200.0
# Storage nodes below this total capacity are dropped by the model's node screen
# (data_loader_v5: STORAGE_MIN_NODE_CAPACITY_MT).
STORAGE_MIN_NODE_MT = 10.0

STATE_COLORS = {
    "inactive": "#D9D9D9",
    "inherited": "#335C81",
    "renewed": "#58A88A",
}
RETIRE_COLORS = {"early": "#D9D9D9", "mature": COLORS["grey"]}
NET_COLOR = "#7B5A8E"
CAPTURE_COLOR = COLORS["blue"]
AF_COLOR = STATE_COLORS["renewed"]
FLEET_COLOR = "#B6B6B6"
# Storage-node symbols: uniform small size (never capacity-scaled, which is the
# fleet-bubble encoding), DSA-only as circles and EOR-capable as triangles. The
# layer is a texture under the fleet, so it stays lighter than the fleet dots.
STORAGE_COLORS = {"dsa": "#A6A6A6", "eor": "#4F4F4F"}
STORAGE_MARKERS = {"dsa": "o", "eor": "^"}
STORAGE_SIZES = {"dsa": 1.3, "eor": 2.6}
STORAGE_ALPHA = {"dsa": 0.65, "eor": 0.80}
SIZE_KEY_COLOR = "#8A8A8E"
# South-China-Sea inset rectangle in axes fraction, shared by every map of this
# figure and of Figs. 4-5 (the viewport aspect 1.176 fills the 0.225 x 0.253
# rectangle exactly, and the frame sits clear of Hainan and Taiwan).
INSET_RECT = (0.778, 0.002, 0.203, 0.228)
SIZE_LEGEND_MT = (1.0, 2.0, 3.0)
# Fig. 3a classes: shared 213 lines in the deep hub blue, demand-dependent
# union lines in a light blue-grey; Fig. 3c draws the shared set as a dark
# slate density curve (the hub blue is taken by the high-demand pathway).
SHARED_MAP_COLOR = "#2166AC"
DEPENDENT_COLOR = "#A9BFD0"
SHARED_DENSITY_COLOR = "#2E3942"
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
    """Scatter area (pt²) proportional to annual nameplate capacity (Mt/yr).

    The single capacity-bubble scale of Figs. 2d and 3 (maps and scatter).
    """
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


def result_json_path(label: str) -> Path:
    task, scenario = RUNS[label]
    return RESULTS / task / f"{scenario}_results.json"


def load_csv(label: str, name: str) -> pd.DataFrame:
    return pd.read_csv(run_dir(label) / name)


def load_json(label: str) -> dict:
    return json.loads(result_json_path(label).read_text(encoding="utf-8"))


def load_static() -> pd.DataFrame:
    plants = pd.read_excel(
        ROOT / "v5" / "data" / "model_input" / "plants" / "plant_data.xlsx"
    ).rename(
        columns={
            "id": "plant_id",
            "capacity": "capacity_t_per_day",
            "year of commissioning": "commission_year",
        }
    )
    plants = plants[
        [
            "plant_id",
            "province",
            "capacity_t_per_day",
            "commission_year",
            "longitude",
            "latitude",
        ]
    ].copy()
    plants["plant_id"] = plants["plant_id"].astype(int)
    plants["commission_year"] = plants["commission_year"].astype(int)
    assert len(plants) == 1572 and plants["plant_id"].is_unique
    assert plants["commission_year"].notna().all()
    return plants


def load_fleet(static: pd.DataFrame) -> pd.DataFrame:
    """Base-year fleet with annual nameplate capacity (Mt/yr) for bubble areas."""
    cap_mt = (
        load_csv("C1", "full_plant_summary.csv")
        .set_index("plant_id")["annual_capacity_kt_per_year"] / 1000.0
    )
    fleet = static.copy()
    fleet["cap_mt"] = fleet["plant_id"].map(cap_mt)
    assert fleet["cap_mt"].notna().all()
    return fleet


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


def load_storage_nodes() -> pd.DataFrame:
    """Storage nodes that pass the model's ≥10 Mt node-capacity screen.

    ``eor`` marks the nodes with EOR capability (they may also carry DSA
    capacity); every other node is DSA-only. The screen is applied to the
    summed DSA + EOR capacity of a node, exactly as in the loader.
    """
    raw = pd.read_csv(STORAGE_CSV)
    total_mt = (
        pd.to_numeric(raw["dsa_capacity"], errors="coerce").fillna(0.0)
        + pd.to_numeric(raw["eor_capacity"], errors="coerce").fillna(0.0)
    )
    nodes = raw.loc[total_mt >= STORAGE_MIN_NODE_MT].copy()
    nodes["kind"] = np.where(nodes["has_eor"], "eor", "dsa")
    assert len(nodes) == 1564
    assert nodes["kind"].value_counts().to_dict() == {"dsa": 1285, "eor": 279}
    assert int(nodes["has_dsa"].sum()) == 1549   # DSA-only plus dual-resource nodes
    assert int(nodes["is_offshore"].sum()) == 462
    return nodes[["longitude", "latitude", "kind", "is_offshore"]]


def turnover_counts(static: pd.DataFrame) -> pd.DataFrame:
    """Per-node retirement, renewal and first-CCS-deployment counts under S1.

    A line retires at the first node at which it no longer operates. The
    retirement is "mature" when the kiln has reached the 40-year service life
    at that node (the effective commissioning year is floored at
    ``BASE_YEAR - PLANT_LIFETIME_YEARS``, as in the model), so a mature
    retirement of a sub-3,200 t d⁻¹ line is the only option it ever has.
    Renewals and first commercial-CCS deployments are read from their own
    decision exports.
    """
    op = load_csv("C1", "full_operation_status.csv")
    renewal = load_csv("C1", "full_same_site_renewal_decisions.csv")
    ccs = load_csv("C1", "full_ccs_decisions.csv")

    commission = static.set_index("plant_id")["commission_year"]
    effective = commission.clip(lower=BASE_YEAR - PLANT_LIFETIME_YEARS)
    expiry = effective + PLANT_LIFETIME_YEARS

    operating = (
        op.pivot(index="plant_id", columns="period", values="operating")
        .reindex(columns=YEARS, fill_value=0)
        .fillna(0)
        .astype(int)
    )
    assert operating.sum().to_dict() == {
        year: count
        for year, count in zip(YEARS, [1572, 723, 577, 514, 443, 359, 339, 336])
    }
    renewed = (
        renewal.pivot(
            index="plant_id", columns="period", values="renewal_investment"
        )
        .reindex(columns=YEARS, fill_value=0.0)
        .fillna(0.0)
        .gt(1e-6)
    )
    first_ccs = (
        ccs.pivot(index="plant_id", columns="period", values="new_installation")
        .reindex(columns=YEARS, fill_value=0)
        .fillna(0)
        .astype(int)
    )
    ccs_z = (
        ccs.pivot(index="plant_id", columns="period", values="k_ccs_kt")
        .reindex(columns=YEARS, fill_value=0.0)
        .fillna(0.0)
        .gt(1e-6)
    )
    # ``new_installation`` is the first-deployment indicator: at every node the
    # cumulative count of new installations equals the count of capturing lines.
    assert first_ccs.sum().cumsum().equals(ccs_z.sum().astype(int))
    assert first_ccs.sum().sum() == int(ccs_z.iloc[:, -1].sum()) == 327

    rows = []
    for previous, node in zip(YEARS[:-1], YEARS[1:]):
        retired = operating.index[
            (operating[previous] == 1) & (operating[node] == 0)
        ]
        mature = int((node - expiry.loc[retired] >= 0).sum())
        rows.append(
            {
                "year": node,
                "early_retirement": int(len(retired) - mature),
                "mature_retirement": mature,
                "renewal": int(renewed[node].sum()),
                "first_ccs": int(first_ccs[node].sum()),
            }
        )
    frame = pd.DataFrame(rows).set_index("year")
    assert frame["early_retirement"].to_dict() == {
        2030: 839, 2035: 144, 2040: 56, 2045: 29, 2050: 19, 2055: 1, 2060: 0,
    }
    assert frame["mature_retirement"].to_dict() == {
        2030: 10, 2035: 2, 2040: 7, 2045: 42, 2050: 65, 2055: 19, 2060: 3,
    }
    assert frame["renewal"].to_dict() == {
        2030: 1, 2035: 0, 2040: 1, 2045: 11, 2050: 84, 2055: 162, 2060: 35,
    }
    assert frame["first_ccs"].to_dict() == {
        2030: 0, 2035: 0, 2040: 0, 2045: 224, 2050: 103, 2055: 0, 2060: 0,
    }
    assert frame["renewal"].sum() == 294
    return frame


def load_resource_conditions() -> pd.DataFrame:
    df = pd.read_csv(CONDITIONS_CSV)
    counts = df.groupby("scenario").size().to_dict()
    assert counts == {"C2": 408, "C1": 336, "C3": 262}
    return df


# ---------------------------------------------------------------------------
# Shared fleet map drawer (Fig. 3a)
# ---------------------------------------------------------------------------

def _draw_storage_layer(axis, storage: pd.DataFrame, mask, *, scale: float) -> None:
    """Uniform small storage symbols (never capacity-sized) in one axes."""
    subset = storage.loc[mask]
    for kind in ("dsa", "eor"):
        side = subset[subset["kind"] == kind]
        if side.empty:
            continue
        points = _project(side["longitude"], side["latitude"])
        axis.scatter(
            points.x, points.y, s=STORAGE_SIZES[kind] * scale,
            marker=STORAGE_MARKERS[kind], c=STORAGE_COLORS[kind],
            linewidths=0, alpha=STORAGE_ALPHA[kind], zorder=0.9,
        )


def draw_fleet_map(
    axis,
    inset,
    china,
    scs,
    fleet: pd.DataFrame,
    storage: pd.DataFrame,
    groups: list[tuple[set[int], str]],
    title: str,
    *,
    letter: str | None = None,
) -> None:
    """Storage-node underlay, grey base-year fleet and capacity-sized bubbles.

    ``groups`` is an ordered list of (plant-id set, colour) pairs; later
    groups draw on top. The inset repeats every thematic layer of the parent
    panel (basemap-stack contract) at half size.
    """
    china.plot(ax=axis, color="#FBFBFB", edgecolor="#333333", linewidth=0.30, zorder=0)
    minx, miny, maxx, maxy = china.total_bounds
    miny = miny - SOUTH_BUFFER * (maxy - miny)
    _draw_storage_layer(
        axis, storage, np.ones(len(storage), dtype=bool), scale=1.0
    )
    # Redraw the province boundaries above the storage texture so the
    # administrative structure stays legible under the raster-derived dots.
    china.boundary.plot(ax=axis, color="#333333", linewidth=0.30, zorder=1.2)
    fleet_points = _project(fleet["longitude"], fleet["latitude"])
    axis.scatter(
        fleet_points.x, fleet_points.y, s=0.9, c=FLEET_COLOR,
        alpha=0.38, linewidths=0, zorder=1.5,
    )
    for layer, (ids, color) in enumerate(groups):
        operating = fleet[fleet["plant_id"].isin(ids)]
        points = _project(operating["longitude"], operating["latitude"])
        axis.scatter(
            points.x, points.y, s=fleet_sizes(operating["cap_mt"]), c=color,
            alpha=0.92, edgecolor="white", linewidth=0.28, zorder=3.0 + layer,
        )
    axis.set_xlim(minx, maxx)
    axis.set_ylim(miny, maxy)
    axis.set_aspect("equal", adjustable="box", anchor="C")
    axis.set_xticks([])
    axis.set_yticks([])
    axis.set_title(title, pad=3, color=COLORS["ink"], fontweight="bold")
    for spine in axis.spines.values():
        spine.set_visible(False)
    if letter:
        panel_label(axis, letter)

    _draw_storage_layer(
        inset,
        storage,
        _inside_scs_data(storage["longitude"], storage["latitude"]),
        scale=0.5,
    )
    fleet_mask = _inside_scs_data(fleet["longitude"], fleet["latitude"])
    inset.scatter(
        fleet_points.x[fleet_mask], fleet_points.y[fleet_mask],
        s=0.45, c=FLEET_COLOR, alpha=0.38, linewidths=0, zorder=2.0,
    )
    for layer, (ids, color) in enumerate(groups):
        operating = fleet[fleet["plant_id"].isin(ids)]
        inside = operating[
            _inside_scs_data(operating["longitude"], operating["latitude"])
        ]
        if inside.empty:
            continue
        points = _project(inside["longitude"], inside["latitude"])
        inset.scatter(
            points.x, points.y, s=fleet_sizes(inside["cap_mt"]) * 0.5, c=color,
            alpha=0.92, edgecolor="white", linewidth=0.18, zorder=3.0 + layer,
        )


def storage_legend_handles() -> list[Line2D]:
    return [
        Line2D([], [], marker=STORAGE_MARKERS["dsa"], ls="",
               mfc=STORAGE_COLORS["dsa"], mec="none", ms=2.4,
               label="DSA sink (≥10 Mt)"),
        Line2D([], [], marker=STORAGE_MARKERS["eor"], ls="",
               mfc=STORAGE_COLORS["eor"], mec="none", ms=3.2,
               label="EOR-capable sink (≥10 Mt)"),
    ]


# ---------------------------------------------------------------------------
# Figure 2 panel c: per-node turnover counts
# ---------------------------------------------------------------------------

TURNOVER_SERIES = [
    ("early_retirement", "Retired early", RETIRE_COLORS["early"]),
    ("mature_retirement", "Retired at expiry", RETIRE_COLORS["mature"]),
    ("renewal", "Same-site renewal", STATE_COLORS["renewed"]),
    ("first_ccs", "First CCS deployment", CAPTURE_COLOR),
]


def turnover_legend_handles() -> list[Patch]:
    return [
        Patch(facecolor=color, label=label) for _, label, color in TURNOVER_SERIES
    ]


def draw_turnover_counts(ax, counts: pd.DataFrame) -> None:
    """Grouped bars: what happens to the fleet at each decision node.

    The four channels are drawn side by side rather than stacked, because a
    renewal keeps a line in service while a retirement removes it; a stack
    would read as if the two added up.
    """
    positions = np.arange(len(YEARS), dtype=float)
    width = 0.20
    offsets = (np.arange(len(TURNOVER_SERIES)) - 1.5) * width
    values = counts.reindex(YEARS, fill_value=0)
    for (column, _, color), offset in zip(TURNOVER_SERIES, offsets):
        heights = values[column].to_numpy(dtype=float)
        ax.bar(
            positions + offset, heights, width * 0.92, color=color,
            edgecolor="white", linewidth=0.35, zorder=2,
        )
        # Only the bars that carry a reader-visible magnitude are annotated:
        # below ~100 lines the bar height is itself the label, and labelling
        # every bar would collide at four bars per node.
        for x, height in zip(positions + offset, heights):
            if height >= 100:
                ax.text(
                    x, height + 12, f"{int(height)}", ha="center", va="bottom",
                    fontsize=FS_NOTE, color=COLORS["ink"],
                )
    ax.set_ylim(0, 900)
    ax.set_yticks([0, 300, 600, 900])
    ax.set_ylabel("Lines (count)", fontsize=FS_LABEL)
    ax.set_xticks(positions)
    ax.set_xticklabels(
        [str(year) for year in YEARS], rotation=45, ha="right", rotation_mode="anchor",
    )
    ax.set_xlim(-0.72, len(YEARS) - 0.28)
    ax.set_title("Turnover at the decision nodes (S1)", pad=4)
    quiet_grid(ax)
    despine(ax)
    panel_label(ax, "c")


# ---------------------------------------------------------------------------
# Figure 2: S1-only capacity turnover, mitigation sequencing, retained geography
# ---------------------------------------------------------------------------

def make_fig2(static: pd.DataFrame) -> Path:
    op = load_csv("C1", "full_operation_status.csv")
    renew = load_csv("C1", "full_same_site_renewal_decisions.csv")
    balance = load_csv("C1", "full_plant_emission_balance.csv")
    plant_summary = load_csv("C1", "full_plant_summary.csv")
    c1 = load_json("C1")

    all_ids = plant_summary["plant_id"].astype(int).tolist()
    assert len(all_ids) == 1572
    base_row = {pid: idx for idx, pid in enumerate(all_ids)}
    cap_kt = plant_summary.set_index("plant_id")["annual_capacity_kt_per_year"]
    cap_tpd = static.set_index("plant_id")["capacity_t_per_day"]

    op_piv = (
        op.pivot(index="plant_id", columns="period", values="operating")
        .reindex(index=all_ids, columns=YEARS, fill_value=0)
        .fillna(0)
    )
    last_operating = op_piv.mul(YEARS, axis=1).max(axis=1).astype(int)

    renewal_piv = (
        renew.pivot(index="plant_id", columns="period", values="renewal_investment")
        .reindex(index=all_ids, columns=YEARS, fill_value=0)
        .fillna(0)
    )
    renewed_upto = renewal_piv.cumsum(axis=1).gt(0)
    first_renewal = renewal_piv.replace(0, np.nan).apply(
        lambda row: row.first_valid_index(), axis=1
    )

    ordered_ids: list[int] = []
    group_bounds: list[float] = []
    group_midpoints: list[tuple[int, float]] = []
    row_cursor = 0
    for last_year in reversed(YEARS):
        ids = last_operating[last_operating == last_year].index
        group = pd.DataFrame({
            "renewal": first_renewal.loc[ids].fillna(9999).astype(float).to_numpy(),
            "capacity": cap_tpd.loc[ids].astype(float).to_numpy(),
            "plant_id": ids.to_numpy(),
        }).sort_values(
            ["renewal", "capacity", "plant_id"], ascending=[True, False, True]
        )
        ordered_ids.extend(group["plant_id"].astype(int).tolist())
        row_cursor += len(group)
        group_bounds.append(row_cursor - 0.5)
        group_midpoints.append((last_year, row_cursor - len(group) / 2 - 0.5))
    assert len(ordered_ids) == 1572 and len(set(ordered_ids)) == 1572
    order_index = [base_row[pid] for pid in ordered_ids]

    state = np.zeros((len(all_ids), len(YEARS)))
    for col, year in enumerate(YEARS):
        operating = op_piv[year].astype(bool)
        renewed = renewed_upto[year]
        state[operating & ~renewed, col] = 1
        state[operating & renewed, col] = 2
    state = state[order_index, :]

    residual = (
        balance.pivot(
            index="plant_id", columns="period",
            values="residual_after_commercial_capture",
        )
        .reindex(index=all_ids, columns=YEARS)
        .fillna(0.0)
        .to_numpy()[order_index, :]
        / 1000.0
    )
    positive = residual[residual > 0]
    residual_vmax = float(np.quantile(positive, 0.995))

    af_rate = np.array([
        100.0 * c1["summary"][str(year)]["national_af_rate"] for year in YEARS
    ])
    gross = np.array([
        c1["summary"][str(year)]["gross_co2_kt"] / 1000.0 for year in YEARS
    ])
    net = np.array([
        c1["summary"][str(year)]["net_co2_kt"] / 1000.0 for year in YEARS
    ])
    capture_credit = gross - net
    assert np.all(capture_credit >= -1e-8)
    assert int(op_piv[2030].sum()) == 723 and int(op_piv[2060].sum()) == 336
    operating_2060 = set(op_piv.index[op_piv[2060].astype(bool)])
    capacity_2060_mt = float(cap_kt.loc[list(operating_2060)].sum() / 1000.0)
    assert abs(capacity_2060_mt - 522.009) < 0.001

    counts = turnover_counts(static)
    # Two-path check for the renewal channel: the count of renewal decisions in
    # panel c is the number of lines that carry the renewed state in panel a.
    assert int(renewed_upto[2060].sum()) == int(counts["renewal"].sum()) == 294

    # Laid out with explicit boxes: every key sits directly under the panel it
    # belongs to (the legend of a under a, the residual-emission colour bar
    # under b, the turnover and mitigation legends under c and d), which a
    # shared bottom strip cannot do.
    fig_w = 190 * MM
    fig_h = 6.98
    fig = plt.figure(figsize=(fig_w, fig_h))

    def rect(x, y_top, w, h):
        return [x / fig_w, (fig_h - y_top - h) / fig_h, w / fig_w, h / fig_h]

    left = 0.70
    col_w = 3.08
    gap_ab = 0.34
    leg_h = 0.42
    row1_top, row1_h = 0.22, 2.70
    leg1_top = row1_top + row1_h + 0.36
    row2_top, row2_h = leg1_top + leg_h + 0.34, 2.02
    leg2_top = row2_top + row2_h + 0.38
    # c reuses the column of a.  The mitigation stack is narrower and pushed
    # right so that its y-axis labels clear panel c, while its right edge stays
    # flush with panel b above.
    c_w = col_w
    d_w = 2.70
    d_left = left + 2 * col_w + gap_ab - d_w

    ax_state = fig.add_axes(rect(left, row1_top, col_w, row1_h))
    ax_residual = fig.add_axes(
        rect(left + col_w + gap_ab, row1_top, col_w, row1_h), sharey=ax_state
    )
    ax_state_legend = fig.add_axes(rect(left, leg1_top, col_w, leg_h))
    ax_colorbar = fig.add_axes(
        rect(left + col_w + gap_ab + 0.28, leg1_top + 0.02, col_w - 0.56, 0.09)
    )
    ax_turnover = fig.add_axes(rect(left, row2_top, c_w, row2_h))
    ax_af = fig.add_axes(rect(d_left, row2_top, d_w, 0.82))
    ax_emissions = fig.add_axes(
        rect(d_left, row2_top + 0.96, d_w, 1.06), sharex=ax_af
    )
    ax_turnover_legend = fig.add_axes(rect(left, leg2_top, c_w, leg_h))
    ax_mitigation_legend = fig.add_axes(rect(d_left, leg2_top, d_w, leg_h))

    image_args = dict(
        aspect="auto", interpolation="nearest", origin="upper",
        extent=(-0.5, len(YEARS) - 0.5, len(all_ids) - 0.5, -0.5),
    )
    state_cmap = mcolors.ListedColormap([
        STATE_COLORS["inactive"], STATE_COLORS["inherited"], STATE_COLORS["renewed"]
    ])
    ax_state.imshow(state, cmap=state_cmap, vmin=-0.5, vmax=2.5, **image_args)
    residual_cmap = mcolors.LinearSegmentedColormap.from_list(
        "residual", ["#FFFFFF", "#DDD1E7", "#6F2C7F"]
    )
    im_residual = ax_residual.imshow(
        residual,
        cmap=residual_cmap,
        norm=mcolors.PowerNorm(gamma=0.50, vmin=0, vmax=residual_vmax, clip=True),
        **image_args,
    )

    for axis, letter, title in (
        (ax_state, "a", "Lifecycle state"),
        (ax_residual, "b", "Residual direct emissions"),
    ):
        panel_label(axis, letter)
        axis.set_title(title, pad=4)
        axis.set_xticks(range(len(YEARS)), [str(year) for year in YEARS],
                        rotation=45, ha="right", rotation_mode="anchor")
        axis.tick_params(axis="x", length=0)
        axis.spines[:].set_visible(False)
    for boundary in group_bounds[:-1]:
        ax_state.axhline(boundary, color="white", lw=0.50, alpha=0.95)
        ax_residual.axhline(boundary, color="white", lw=0.50, alpha=0.95)
    midpoint_by_year = dict(group_midpoints)
    combined_2050_55_midpoint = (
        (group_bounds[0] + 0.5) + group_bounds[2]
    ) / 2.0
    display_years = [2060, "2050–55", 2045, 2040, 2035, 2030, 2025]
    display_midpoints = [
        midpoint_by_year[2060], combined_2050_55_midpoint,
        midpoint_by_year[2045], midpoint_by_year[2040],
        midpoint_by_year[2035], midpoint_by_year[2030], midpoint_by_year[2025],
    ]
    ax_state.set_yticks(display_midpoints, [str(year) for year in display_years])
    ax_state.set_ylabel("Last operating year in S1")
    plt.setp(ax_residual.get_yticklabels(), visible=False)
    ax_residual.tick_params(axis="y", length=0)

    cbar = fig.colorbar(im_residual, cax=ax_colorbar, orientation="horizontal")
    # Five ticks only: the ten of the former vertical bar collide once the bar
    # is laid out horizontally under the panel.
    cbar.set_ticks([0.0, 0.5, 1.0, 1.5, 2.0])
    cbar.set_label("Mt CO₂ per line per year (square-root scale)",
                   labelpad=3, fontsize=FS_LABEL)
    cbar.ax.xaxis.label.set_fontfamily("Helvetica")
    cbar.ax.tick_params(labelsize=FS_NOTE, length=1.8, pad=1.5)

    draw_turnover_counts(ax_turnover, counts)

    ax_af.fill_between(YEARS, 0, af_rate, color=AF_COLOR, alpha=0.18, lw=0)
    ax_af.plot(YEARS, af_rate, color=AF_COLOR, marker="o", ms=2.5, lw=1.1)
    ax_af.set_ylim(0, 65)
    ax_af.set_yticks([0, 30, 60])
    ax_af.set_ylabel("AF heat\nsubstitution (%)")
    ax_af.tick_params(axis="x", labelbottom=False)
    ax_af.set_title("Mitigation sequence (S1)", pad=4)
    panel_label(ax_af, "d")

    ax_emissions.stackplot(
        YEARS, [net, capture_credit],
        colors=[NET_COLOR, CAPTURE_COLOR], alpha=0.92, linewidth=0,
    )
    ax_emissions.plot(YEARS, gross, color="#333333", lw=0.8)
    ax_emissions.set_ylim(0, 950)
    ax_emissions.set_yticks([0, 400, 800])
    ax_emissions.set_ylabel("Direct emissions\n(Mt CO₂ yr⁻¹)", fontsize=FS_LABEL)
    ax_emissions.yaxis.label.set_fontfamily("Helvetica")
    ax_emissions.set_xticks(YEARS)
    ax_emissions.set_xticklabels(
        [str(year) for year in YEARS], rotation=45, ha="right", rotation_mode="anchor",
    )
    for axis in (ax_af, ax_emissions):
        axis.set_xlim(YEARS[0], YEARS[-1])
        quiet_grid(axis)
        despine(axis)

    ax_state_legend.axis("off")
    ax_mitigation_legend.axis("off")
    ax_turnover_legend.axis("off")
    # Each legend is anchored to the top-left of its own slot so that the box
    # hangs directly under the panel it describes.
    legend_loc = dict(loc="upper left", bbox_to_anchor=(0.0, 1.0), frameon=False,
                      borderaxespad=0.0, handlelength=1.4, labelspacing=0.40)
    # Column-major fill with ncol=2: this order reads
    # (Inherited operation, Same-site renewal) then (Inactive / exited).
    ax_state_legend.legend(
        handles=[
            Patch(facecolor=STATE_COLORS["inherited"], label="Inherited operation"),
            Patch(facecolor=STATE_COLORS["inactive"], label="Inactive / exited"),
            Patch(facecolor=STATE_COLORS["renewed"], label="Same-site renewal"),
        ],
        ncol=2, columnspacing=1.0, **legend_loc,
    )
    ax_mitigation_legend.legend(
        handles=[
            Line2D([], [], color=AF_COLOR, marker="o", ms=3.0, lw=1.1,
                   label="AF heat substitution"),
            Patch(facecolor=NET_COLOR, label="Net direct emissions"),
            Patch(facecolor=CAPTURE_COLOR, label="Accounted capture credit"),
            Line2D([], [], color="#333333", lw=0.8, label="Gross direct emissions"),
        ],
        ncol=2, columnspacing=0.9, **legend_loc,
    )
    ax_turnover_legend.legend(
        handles=turnover_legend_handles(),
        ncol=2, columnspacing=0.9, handletextpad=0.5, **legend_loc,
    )

    OUTDIR.mkdir(parents=True, exist_ok=True)
    output = OUTDIR / "fig2_capacity_turnover_emissions_capture_atlas_v5_20260915.png"
    fig.savefig(output, dpi=600, facecolor="white")
    plt.close(fig)

    print("--- Figure 2 summary ---")
    print("last-operating-year groups:", last_operating.value_counts().sort_index().to_dict())
    print("operating lines 2030/2060:", int(op_piv[2030].sum()), int(op_piv[2060].sum()))
    print("operating capacity 2060 (Mt/yr):", round(capacity_2060_mt, 3))
    print("turnover counts:")
    print(counts.T.to_string())
    print("AF rate (%):", dict(zip(YEARS, np.round(af_rate, 1))))
    print("gross/net emissions 2060 (Mt):", round(gross[-1], 1), round(net[-1], 1))
    return output


# ---------------------------------------------------------------------------
# Figure 3: shared core vs demand-dependent margin, trajectories, invariance
# ---------------------------------------------------------------------------

def _kde(values: pd.Series, xs: np.ndarray) -> np.ndarray:
    return stats.gaussian_kde(values.to_numpy())(xs)


def make_fig3(static: pd.DataFrame, fleet: pd.DataFrame) -> Path:
    op_sets = operating_sets(2060)
    shared = set.intersection(*op_sets.values())
    union = set.union(*op_sets.values())
    dependent = union - shared
    assert {label: len(values) for label, values in op_sets.items()} == {
        "C2": 408, "C1": 336, "C3": 262,
    }
    assert len(shared) == 213 and len(union) == 462 and len(dependent) == 249

    cap_mt = (
        load_csv("C1", "full_plant_summary.csv")
        .set_index("plant_id")["annual_capacity_kt_per_year"] / 1000.0
    )
    shared_capacity = float(cap_mt.loc[list(shared)].sum())
    assert abs(shared_capacity - 327.081) < 0.001
    terminal_capacity = {
        label: float(cap_mt.loc[list(ids)].sum()) for label, ids in op_sets.items()
    }
    for label, expected in {"C2": 628.215, "C1": 522.009, "C3": 405.170}.items():
        assert abs(terminal_capacity[label] - expected) < 0.001
    union_capacity = float(cap_mt.loc[list(union)].sum())
    dependent_capacity = float(cap_mt.loc[list(dependent)].sum())
    assert abs(union_capacity - 716.224) < 0.001
    assert abs(dependent_capacity - 389.143) < 0.001
    shares = shared_capacity / np.array(
        [terminal_capacity[label] for label in ("C2", "C1", "C3")]
    )
    assert np.allclose(shares, [0.5207, 0.6266, 0.8073], atol=5e-4)

    status = {label: load_csv(label, "full_operation_status.csv") for label in RUNS}
    summaries = {label: load_json(label)["summary"] for label in RUNS}
    capacity_path: dict[str, np.ndarray] = {}
    capture_path: dict[str, np.ndarray] = {}
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
    for label, expected in {"C2": 366.949, "C1": 305.254, "C3": 232.345}.items():
        assert abs(capture_path[label][-1] - expected) < 0.002
    for label, onset in {"C2": 2035, "C1": 2045, "C3": 2050}.items():
        positive = [
            year for year, value in zip(YEARS, capture_path[label]) if value > 0
        ]
        assert positive[0] == onset

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
    shared_medians = (
        float(shared_view["kA_over_H_real_2060"].median()),
        float(shared_view["nearest_sink_km"].median()),
    )
    assert abs(shared_medians[0] - 0.473) < 5e-4
    assert abs(shared_medians[1] - 103.6) < 0.05

    china, scs = _load_basemap()
    storage = load_storage_nodes()
    # The map's data limits (the South-China-Sea strip is reserved below the
    # mainland), needed to place the density panel c on the drawn map box.
    map_minx, map_miny, map_maxx, map_maxy = china.total_bounds
    map_miny = map_miny - SOUTH_BUFFER * (map_maxy - map_miny)

    fig = plt.figure(figsize=(190 * MM, 160 * MM))
    outer = fig.add_gridspec(
        3, 1,
        height_ratios=[1.46, 1.0, 0.22],
        left=0.075, right=0.985, top=0.960, bottom=0.050, hspace=0.30,
    )

    top = outer[0].subgridspec(1, 2, width_ratios=[1.18, 1.0], wspace=0.15)
    ax_map = fig.add_subplot(top[0, 0])
    # Same inset rectangle as the Fig. 4 and Fig. 5 maps (0.225 x 0.253, the
    # South-China-Sea viewport aspect inside a China map box), so the inset
    # frame clears Hainan and Taiwan in every figure.
    inset = _add_south_china_sea_inset(ax_map, scs, rect=INSET_RECT)
    draw_fleet_map(
        ax_map, inset, china, scs, fleet, storage,
        [(dependent, DEPENDENT_COLOR), (shared, SHARED_MAP_COLOR)],
        "Retained fleet in 2060 across demand pathways",
        letter="a",
    )
    # Open water is reserved along the bottom of the map for the inset frame,
    # so the lower-left corner can hold the class legend without covering the
    # mainland; the size key sits in the empty north-west corner.
    class_legend = ax_map.legend(
        handles=[
            Line2D([], [], marker=".", ls="", color=FLEET_COLOR, ms=4.5,
                   label="2025 fleet"),
            Line2D([], [], marker="o", ls="", mfc=SHARED_MAP_COLOR, mec="white",
                   ms=4.5, label="Retained in all pathways"),
            Line2D([], [], marker="o", ls="", mfc=DEPENDENT_COLOR, mec="white",
                   ms=4.5, label="Demand-dependent"),
            *storage_legend_handles(),
        ],
        loc="lower left", bbox_to_anchor=(-0.065, -0.055), frameon=True,
        fontsize=FS_LEGEND, borderpad=0.55, labelspacing=0.40,
        handlelength=1.2, handletextpad=0.5, borderaxespad=0.2,
    )
    _legend_frame(class_legend)
    ax_map.add_artist(class_legend)
    size_legend = ax_map.legend(
        handles=size_legend_handles(SHARED_MAP_COLOR),
        loc="upper left", bbox_to_anchor=(0.005, 0.995), frameon=True,
        fontsize=FS_LEGEND, borderpad=0.55, labelspacing=0.40,
        handlelength=0.9, handletextpad=0.35, ncol=3, columnspacing=0.7,
        borderaxespad=0.2,
    )
    _legend_frame(size_legend)

    trajectory = top[0, 1].subgridspec(2, 1, height_ratios=[1.0, 1.0], hspace=0.14)
    ax_capacity = fig.add_subplot(trajectory[0, 0])
    ax_capture = fig.add_subplot(trajectory[1, 0], sharex=ax_capacity)
    for label in ("C2", "C1", "C3"):
        color = DEMAND_COLORS[label]
        ax_capacity.plot(
            YEARS, capacity_path[label], color=color, marker="o", ms=2.5, lw=1.1,
        )
        ax_capture.plot(
            YEARS, capture_path[label], color=color, marker="o", ms=2.5, lw=1.1,
            ls=(0, (4, 2)),
        )
    ax_capacity.set_ylim(0, 2000)
    ax_capacity.set_yticks([0, 1000, 2000])
    ax_capacity.set_ylabel("Operating capacity\n(Mt clinker yr⁻¹)", fontsize=FS_LABEL)
    ax_capacity.yaxis.label.set_fontfamily("Helvetica")
    ax_capacity.tick_params(axis="x", labelbottom=False)
    panel_label(ax_capacity, "b")
    ax_capture.set_ylim(0, 500)
    ax_capture.set_yticks([0, 250, 500])
    ax_capture.set_ylabel("Commercial capture\n(Mt CO₂ yr⁻¹)", fontsize=FS_LABEL)
    ax_capture.yaxis.label.set_fontfamily("Helvetica")
    ax_capture.set_xticks(YEARS)
    ax_capture.set_xticklabels(
        [str(year) for year in YEARS], rotation=45, ha="right", rotation_mode="anchor",
    )
    for axis in (ax_capacity, ax_capture):
        axis.set_xlim(YEARS[0], YEARS[-1])
        quiet_grid(axis)
        despine(axis)

    # The two density panels are narrower than the top row's cells: panel c is
    # set to d's width and shifted right so that its left edge falls on the
    # drawn left edge of the map, which equal-aspect fitting insets within its
    # own cell.  Without this, c overhangs the map on the left.
    density_row = outer[1].subgridspec(1, 2, width_ratios=[1.18, 1.0], wspace=0.15)
    ax_kah = fig.add_subplot(density_row[0, 0])
    ax_dist = fig.add_subplot(density_row[0, 1])
    map_cell = ax_map.get_position(original=True)
    map_aspect = (map_maxy - map_miny) / (map_maxx - map_minx)   # height / width
    cell_w = map_cell.width * fig.get_figwidth()
    cell_h = map_cell.height * fig.get_figheight()
    drawn_w = min(cell_w, cell_h / map_aspect)
    map_left = map_cell.x0 + (cell_w - drawn_w) / 2 / fig.get_figwidth()
    kh_box = ax_kah.get_position(original=True)
    ax_kah.set_position([map_left, kh_box.y0, ax_dist.get_position(original=True).width,
                         kh_box.height])
    kah_xs = np.linspace(0.0, 3.3, 400)
    dist_xs = np.linspace(0.0, 500.0, 400)
    shared_with_sink = shared_view[shared_view["has_sink"]]
    for axis, xs, column, frame in (
        (ax_kah, kah_xs, "kA_over_H_real_2060", False),
        (ax_dist, dist_xs, "nearest_sink_km", True),
    ):
        for label in ("C2", "C1", "C3"):
            sub = conditions[conditions["scenario"] == label]
            if frame:
                sub = sub[sub["has_sink"]]
            axis.plot(xs, _kde(sub[column], xs), color=DEMAND_COLORS[label], lw=1.2)
        axis.plot(
            xs,
            _kde(shared_with_sink[column] if frame else shared_view[column], xs),
            color=SHARED_DENSITY_COLOR, lw=1.35,
        )
    # Unweighted medians as staggered tick marks just above each x axis; the
    # near-coincident ladders are the invariance evidence.
    for index, label in enumerate(("C2", "C1", "C3")):
        for axis, transform, xpos in (
            (ax_kah, blended_transform_factory(ax_kah.transData, ax_kah.transAxes),
             medians[label][0]),
            (ax_dist, blended_transform_factory(ax_dist.transData, ax_dist.transAxes),
             medians[label][1]),
        ):
            axis.plot(
                [xpos], [0.020 + 0.028 * index], marker="|", ms=6.0, mew=1.2,
                color=DEMAND_COLORS[label], transform=transform, clip_on=False,
            )
    for axis, transform, xpos in (
        (ax_kah, blended_transform_factory(ax_kah.transData, ax_kah.transAxes),
         shared_medians[0]),
        (ax_dist, blended_transform_factory(ax_dist.transData, ax_dist.transAxes),
         shared_medians[1]),
    ):
        axis.plot(
            [xpos], [0.020 + 0.028 * 3], marker="|", ms=6.0, mew=1.4,
            color=SHARED_DENSITY_COLOR, transform=transform, clip_on=False,
        )
    ax_kah.set_xlim(0, 3.3)
    ax_kah.set_xticks([0, 1, 2, 3])
    ax_kah.set_xlabel(r"$\kappa A_i/H_i$ in 2060 (real conditions)")
    ax_kah.set_ylabel("Density")
    ax_dist.set_xlim(0, 500)
    ax_dist.set_xticks([0, 150, 300, 450])
    ax_dist.set_xlabel("Nearest whitelisted sink (km)")
    for axis in (ax_kah, ax_dist):
        axis.set_ylim(bottom=0)
        quiet_grid(axis)
        despine(axis)
    ax_dist.set_ylabel("Density")
    panel_label(ax_kah, "c")
    panel_label(ax_dist, "d")

    ax_strip = fig.add_subplot(outer[2])
    ax_strip.axis("off")
    pathway_legend = ax_strip.legend(
        handles=[
            *[
                Line2D([], [], color=DEMAND_COLORS[label], lw=1.4,
                       label=DEMAND_LABELS[label])
                for label in ("C2", "C1", "C3")
            ],
            Line2D([], [], color=COLORS["ink"], lw=1.1, label="Operating capacity"),
            Line2D([], [], color=COLORS["ink"], lw=1.1, ls=(0, (4, 2)),
                   label="Commercial capture"),
        ],
        loc="lower center", bbox_to_anchor=(0.5, 0.42), ncol=5, frameon=False,
        fontsize=FS_LEGEND, handlelength=1.6, handletextpad=0.4,
        columnspacing=1.1, borderaxespad=0,
    )
    ax_strip.add_artist(pathway_legend)
    ax_strip.legend(
        handles=[
            Line2D([], [], color=SHARED_DENSITY_COLOR, lw=1.35,
                   label=f"Shared retained set ({len(shared)} lines)"),
            Line2D([], [], marker="|", ls="", color=COLORS["ink"], ms=5.0,
                   mew=1.2, label="Unweighted median"),
        ],
        loc="upper center", bbox_to_anchor=(0.5, 0.38), ncol=2, frameon=False,
        fontsize=FS_LEGEND, handlelength=1.6, handletextpad=0.4,
        columnspacing=1.1, borderaxespad=0,
    )

    OUTDIR.mkdir(parents=True, exist_ok=True)
    output = OUTDIR / "fig3_spatial_suitability_conditional_priorities_v5_20260915.png"
    fig.savefig(output, dpi=600, facecolor="white")
    plt.close(fig)

    print("--- Figure 3 summary ---")
    print("terminal lines:", {label: len(op_sets[label]) for label in RUNS})
    print("terminal capacity (Mt/yr):", {k: round(v, 1) for k, v in terminal_capacity.items()})
    print("shared set:", len(shared), "lines,", round(shared_capacity, 1), "Mt/yr")
    print("union across pathways:", len(union), "lines,", round(union_capacity, 1),
          "Mt/yr; demand-dependent:", len(dependent), "lines,",
          round(dependent_capacity, 1), "Mt/yr")
    print("terminal capture (Mt/yr):",
          {label: round(capture_path[label][-1], 1) for label in RUNS})
    print("no-sink lines:", no_sink_counts)
    print("unweighted medians (kA/H, km):",
          {k: (round(v[0], 3), round(v[1], 1)) for k, v in medians.items()})
    print("shared-set medians (kA/H, km):",
          round(shared_medians[0], 3), round(shared_medians[1], 1))
    return output


def main() -> None:
    apply_style()
    static = load_static()
    fleet = load_fleet(static)
    print(make_fig2(static))
    print(make_fig3(static, fleet))


if __name__ == "__main__":
    main()
