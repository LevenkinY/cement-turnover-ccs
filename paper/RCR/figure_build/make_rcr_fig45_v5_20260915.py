"""RCR Figs. 4-5 (v5 rebuild, 2026-09-15; restructured 2026-09-20 after the
Results-outline review, ``v5/docs/RCR_figures_revision_spec_20260920.md``):
AF-conditioned asset selection and the cost of commitment / lock-in, from the
v5 formal run pack (``v5/results/formal_v1_20260914``).

Fig. 4 became a two-by-two grid: the mitigation-structure and capture-task
panels moved to the SI as Fig. S9, the two maps lead (the asset exchange and the
provincial capture change) and the two quantitative panels follow (the
behavioural response and the equalisation mechanism).
Fig. 5 became four panels (a overview, b waterfall, c and d maps): the
capacity-trajectory stack and the commitment-interval panel were dropped
(the interval is in Fig. S1).

Outputs (PNG only, 190 mm wide, 600 dpi, into ``paper/RCR/figures/``):
  - fig4_af_conditioned_asset_selection_v5_20260915.png
  - fig5_commitment_cost_lockin_v5_20260915.png
  - figS1_commitment_sensitivity_v5_20260918.png   (155 mm)
  - figS9_mitigation_structure_capture_task_20260920.png   (155 mm)
    SUPERSEDED 2026-09-23 by make_rcr_figS9_v2_20260923.py
    (figS9_mitigation_redistribution_v2_20260923.png): the two absolute-volume
    panels repeated each other, so v2 plots the S4 - S1 differences instead.
    Do not re-insert this PNG into the SI; it is kept only for provenance.

---------------------------------------------------------------------------
FIGURE CAPTIONS (for the manuscript; kept here as the single source of truth)

Fig. 4 | AF spatial conditions reshape the retained fleet. (a) 2060 swap
map: lines operating under real conditions but retired under equalised access
(blue squares), lines entering under equalised access (orange circles) and
lines operating in both scenarios (grey dots). (b) Provincial commercial
capture integrated over 2025-2060, equalised minus real conditions (Mt CO2):
blue marks provinces that capture more under real conditions and orange those
that capture more after equalisation. The province-level units without a
modelled plant (Shanghai, Taiwan, Hong Kong and Macao) take the zero value of
the scale. (c) Realised AF heat share in 2030 under S1 against the
access-equalised counterfactual S4, with the two swap groups highlighted; the
dashed line is y = x. (d) Mechanism of the exchange: for each exchange line,
the change that equalisation works on the 2060 AF accessibility ratio
kappa*A_i/H_i against its real value, group medians dashed and the highest
real ratios on a compressed strip below the broken y axis. Boundary:
Tianditu basemap (review-grade depiction subject to the competent map-review
authority); South China Sea shown in the inset with the discontinuous line.

Fig. 5 | The cost of commitment is paid in configuration, not in volume.
(a) S5 metrics relative to S1 at 2060 (S1 = 100%); hollow markers are system
volumes and filled markers spatial configuration. (b) Discounted cost
waterfall, S5 - S1 (bn CNY, 2025-2060), by cost component. (c) Provincial
production dispatch (Mt clinker yr-1; orange marks increases under S5, blue
decreases) with the plant-level capture relocation on top, sized by the
capture change; demand is exogenous, so provincial deliveries are identical
in both scenarios. (d) Change in the flow-weighted proxy delivery distance of
provincial deliveries (km). Boundary: Tianditu basemap, as in Fig. 4a.


Fig. S1 | Sensitivity of the commitment premium. Point estimates and
solver-bound intervals for R1-R8, together with the central and no-minimum-
period comparisons. R5 evaluates the fine-resolution committed path under
the 75-node representation and is shown separately across the broken x axis;
its large value combines path transfer and spatial aggregation and remains
pending a resolution-specific source-path decomposition.

Fig. S9 | Mitigation structure and capture task by fleet group (companion to
main-text Fig. 4; former Fig. 4c,d). (a) Mitigation structure by fleet group
in 2045 and 2060: commercial capture (saturated segments) plus the AF
fossil-abatement credit (light segments, 1.46322 tCO2 per tce of AF supply),
in Mt CO2/yr. Group identities are fixed by 2060 operation status (294
shared, 42 S1-only, 35 S4-only lines); the shared segment comprises all
lines outside the two swap groups, so the bars close on the national totals.
Equalised AF access moves mitigation from capture to fuel substitution
inside the shared fleet (2045: AF credit 31.2 -> 42.2 Mt with capture 191.0
-> 167.3 Mt), whereas the two swap groups carry almost identical capture
volumes in opposite scenarios (2060: 33.9 Mt under S1 versus 33.4 Mt under
S4) - the asset exchange relocates the capture task rather than changing its
volume. (b) Capture task decomposition for the same groups: bars give
commercial capture, so a group with no bar captures nothing in that scenario
(the counts of capturing lines, on an annual capture above 10 kt CO2
threshold, are 200 and 177 in 2045 and 287 and 287 in 2060 for the shared
fleet, and 24 to 0, 0 to 22, 40 to 0 and 0 to 35 for the swap groups). In 2060, 287 of the 294 shared lines capture in
both scenarios, while 40 S1-only and all 35 S4-only lines capture only in
their host scenario; in 2045 the capturing swap lines (24 under S1, 22 under
S4) sit on capacity that the other scenario retires early. The 2045 capture
relief under S4 (-24.3 Mt nationally) is therefore delivered inside the
retained shared fleet, not by the asset exchange.
---------------------------------------------------------------------------

Verification anchors asserted in this script:
  Fig4a physical-heat medians: S1-only 17.7% -> 2.1%, S4-only 1.5% -> 30.5% (2030).
  Fig4a swap sets from the rd_numbers CSVs equal the 2060 operation-status
  set differences (42 / 35).
  Fig4d equalisation: 77 exchange lines; real-condition medians 0.514 / 0.437
  (tolerance 1e-3); change in kappa*A/H medians +0.179 / +0.258 with 31/42
  and 32/35 lines gaining; body/tail split at -0.62 gives 72 / 5 lines;
  median capacity 5,000 t/d in both groups.
  Fig4b provincial capture change: cumulative national capture 4,936.7 (S1)
  and 4,698.5 (S4) Mt CO2 over 2025-2060, closing on the run's own
  cumulative capture (tolerance 0.5); group split S1-only -553.3 / S4-only
  +533.7 / shared -218.6 Mt; Jiangsu -36.1 and Anhui +15.3 Mt; 22 provinces
  losing and 6 gaining (tolerance 0.05 Mt).
  FigS9a design-B structure: group x scenario x year AF fossil credit and
  commercial capture equal the deliverable-4 memo table (tolerance 0.1 Mt),
  with the capture part cross-checked against the deliverable-1 CSV.
  FigS9b capture task: deliverable-1 decomposition (294 / 42 / 35 lines,
  459.0 / 63.1 / 59.2 Mt) closes exactly on national commercial capture
  (212.2 / 305.3 / 187.9 / 297.0 Mt); capturing-line counts under the
  >10 kt CO2/yr threshold are identical to the >0 convention.
  Fig5a: 2060 common / S1-only / S5-only capacity = 459.0 / 63.1 / 59.2 Mt;
  delivered 510.4 Mt both; captured 305.3 vs 306.8 Mt; proxy distance 89.5
  vs 94.7 km; inter-provincial share 6.8% vs 7.6%.
  Fig5c/5d spatial panels: provincial delivered volumes identical across
  scenarios (demand exogenous); production-dispatch deltas Anhui +4.7 /
  Jiangsu -4.3 / Henan -3.1 Mt; proxy-distance deltas Shaanxi +30.2 /
  Yunnan +20.6 / Guizhou +19.7 km; inter-provincial proxy flows 34.6 ->
  38.7 Mt; plant-matched capture split 269.2 common / 36.0 S1-side /
  37.6 S5-side Mt, of which 33.9 / 34.7 Mt sit on the 42 / 35 exchange
  lines; provincial capture deltas Anhui +3.1 / Jiangsu -2.8 / Henan -1.8 Mt.
  Fig5b: component deltas from the two result JSONs; total = +7.00 +/- 0.01.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


def _repo_root() -> Path:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "v4" / "figure_system_2026_common.py").exists():
            return _p
    raise RuntimeError("repo root with scripts/v4 not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "scripts" / "v4"))
from figure_system_2026_common import (  # noqa: E402
    COLORS,
    FS_LABEL,
    FS_LEGEND,
    FS_NOTE,
    apply_style,
    despine,
    fallback_font,
    panel_label,
    quiet_grid,
)
from make_main_figures_2026_v2 import (  # noqa: E402
    ALBERS,
    SCS_VIEW_BOX,
    _add_south_china_sea_inset,
    _inside_scs_data,
    _legend_frame,
    _load_basemap,
    _project,
    _scs_boundary_layer,
)

RUNS = ROOT / "v5/results/formal_v1_20260914"
SCEN = ROOT / "v5/scenarios/rd_numbers_20260915"
PLANT_XLSX = ROOT / "v5/data/model_input/plants/plant_data.xlsx"
FIG_DATA = ROOT / "tmp/fig_restructure_20260919"
M2_METRICS = ROOT / "tmp/m2_analysis_20260918/m2_plant_metrics.csv"
OUTDIR = ROOT / "paper/RCR/figures"

# AF fossil-abatement credit: COAL_EF 2.6604 tCO2/tce x beta 0.55 (README
# section 7 of the fig-restructure data pack; aggregate totals only).
AF_CREDIT_TCO2_PER_TCE = 2.6604 * 0.55

# Fleet groups whose identity is fixed by 2060 operation status.  The group
# identifiers follow the scenario exports; the display names follow the
# S-numbering of the scenarios.
TASK_GROUPS = ("shared", "C1-only", "C4-only")
GROUP_LABEL = {"C1-only": "S1-only", "C4-only": "S4-only"}
TASK_YEARS = (2045, 2060)

RESULT_JSON = {
    "C1": RUNS / "C1_central_J/S1_baseline_results.json",
    "C4": RUNS / "C4_equalized_J/S3_all_spatial_equalized_results.json",
    "C5": RUNS / "C5_commitment_cost/S1_baseline_results.json",
    "K1": RUNS / "K1_commit0_J/S1_baseline_results.json",
    "K2": RUNS / "K2_commit0_fixed/S1_baseline_results.json",
}
CSV_DIR = {
    "C1": RUNS / "C1_central_J/S1_baseline",
    "C4": RUNS / "C4_equalized_J/S3_all_spatial_equalized",
    "C5": RUNS / "C5_commitment_cost/S1_baseline",
}

YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]

# Consistent semantics across Figs. 4–5: blue = real/joint C1;
# orange = equalised or committed alternative.
C1_COLOR = COLORS["blue"]
C4_COLOR = COLORS["orange"]
JOINT_COLOR = COLORS["blue"]
COMMIT_COLOR = COLORS["orange"]

# Diverging scale for the change maps: blue = larger under the real/joint case,
# orange = larger under the equalised or committed alternative, grey = outside
# the modelled set (no data).  The ramp carries saturated stops at +-0.25 of the
# range so that provinces whose change is a quarter of the scale already read as
# clearly tinted; a plain blue-white-orange ramp left them almost white.
DIVERGING_CMAP = LinearSegmentedColormap.from_list(
    "scenario_diverging",
    [
        (0.00, "#034E7B"), (0.25, "#2B8CBA"), (0.45, "#A9D2E8"),
        (0.50, "#FFFFFF"),
        (0.55, "#FDD49E"), (0.75, "#E1701A"), (1.00, "#8C2D04"),
    ],
)
NO_DATA_COLOR = "#D9D9D9"
# Province-level units that carry no plant in the model: they are drawn at the
# zero value of the diverging scale rather than in the no-data grey, so that no
# unit of the country reads as "outside the modelled set".  (Grey stays in
# ``NO_DATA_COLOR`` for any unit the model does not cover at all.)
ZERO_FILL_PROVINCES = ("上海", "台湾", "香港", "澳门")

# South-China-Sea inset rectangle in axes fraction, shared with the Fig. 3 and
# Fig. 4 maps so that every inset frame sits in the same place and clear of the
# southern coastline.
INSET_RECT = (0.778, 0.002, 0.203, 0.228)

# Forest-plot rows (bn CNY, discounted; solver point estimate and bounds).
# R1-R8 adopted from the solver-log table; Central and K re-derived below
# from the result JSONs and asserted against these values.
FOREST_ROWS = [
    # label, point, lower, upper, style
    ("R5 75-node (upper bound)", 74.85, 67.98, 76.69, "bound"),
    ("R4 53.2 + 0.45", 10.88, 2.24, 15.63, "robust"),
    ("R1 AF high cost", 10.85, 2.39, 15.31, "robust"),
    ("R2 beta = 0.69", 10.24, 2.74, 15.76, "robust"),
    ("R7 EOR 80", 9.93, 2.54, 14.72, "robust"),
    ("R8 storage x2", 9.36, 1.53, 17.23, "robust"),
    ("R6 terminal value", 8.67, 3.67, 12.06, "robust"),
    ("Central", 7.00, 1.29, 10.81, "central"),
    ("K commit = 0", 3.05, -2.68, 8.34, "null"),
    ("R3 phi = 1.31", 2.95, 2.94, 6.93, "robust"),
]

# Waterfall component order and display labels (C5 - C1, discounted bn CNY).
WATERFALL = [
    ("clinker_transport", "Clinker delivery", 4.88),
    ("ccs_opex", "Capture O&M", 3.21),
    ("ccs_capex", "Capture capex", 0.72),
    ("transport", "CO2 transport", 1.35),
    ("capacity_retention", "Retention", -1.26),
    ("same_site_renewal_capex", "Renewal", -0.87),
    ("dispatch_fuel", "Dispatch", -0.87),
    ("af_opex", "AF O&M", -0.26),
]


def load_json(scenario: str) -> dict:
    return json.loads(RESULT_JSON[scenario].read_text(encoding="utf-8"))


def operating_sets(scenario: str, year: int) -> set:
    status = pd.read_csv(CSV_DIR[scenario] / "full_operation_status.csv")
    sub = status[(status.period == year) & (status.operating == 1)]
    return set(sub.plant_id)


def annual_capacity_mt() -> pd.Series:
    summary = pd.read_csv(CSV_DIR["C1"] / "full_plant_summary.csv")
    cap = summary.set_index("plant_id")["annual_capacity_kt_per_year"] / 1000.0
    # Static plant attribute: identical across scenario exports.
    cap_c5 = pd.read_csv(CSV_DIR["C5"] / "full_plant_summary.csv")
    cap_c5 = cap_c5.set_index("plant_id")["annual_capacity_kt_per_year"] / 1000.0
    pd.testing.assert_series_equal(cap.sort_index(), cap_c5.sort_index())
    return cap


def af_shares_2030() -> tuple[pd.Series, pd.Series, pd.Series]:
    """2030 realised AF heat share under S1/S4, plus active-plant mask.

    The exported ``af_share`` uses the legacy flat 0.105 tce/t denominator.
    Convert it to the active model denominator
    ``h_i * (1 - EE_2030)`` using the effective heat-intensity tiers recorded
    in each formal result.  The active tier cuts are 4,200/2,000 t/d.
    """
    frames = {}
    masks = {}
    for scenario in ("C1", "C4"):
        raw = pd.read_csv(CSV_DIR[scenario] / "full_af_plant_shares.csv")
        sub = raw[raw.period == 2030].set_index("plant_id")
        result = load_json(scenario)
        heat_tiers = result["effective_config"]["af_plant_heat_intensity_tce_per_t"]
        assert len(heat_tiers) == 3
        plant_heat = np.select(
            [sub.capacity >= 4200, sub.capacity >= 2000],
            [heat_tiers[0], heat_tiers[1]],
            default=heat_tiers[2],
        )
        ee = float(result["summary"]["2030"]["ee_rate"])
        physical_share = sub.af_share * 0.105 / (plant_heat * (1.0 - ee))
        assert physical_share.max() <= 0.600001
        frames[scenario] = physical_share
        masks[scenario] = sub.operating > 0.5
    frames["C1"], frames["C4"] = frames["C1"].align(frames["C4"], join="outer", fill_value=0.0)
    active = (masks["C1"] | masks["C4"]).reindex(frames["C1"].index).fillna(False)
    return frames["C1"], frames["C4"], active


def mitigation_structure() -> dict:
    """Design-B mitigation structure (deliverable 4): AF fossil-abatement
    credit and commercial capture, Mt CO2/yr, by group x scenario x year.

    Group identities are fixed by 2060 operation status; "shared" comprises
    every line outside the two swap groups, so the 2045 values close on the
    national totals (no capture occurs on lines retired by 2060 in both
    scenarios, but those lines still supply AF in 2045).
    """
    c1_only = set(pd.read_csv(SCEN / "data02_C1-only_plants.csv").plant_id)
    c4_only = set(pd.read_csv(SCEN / "data02_C4-only_plants.csv").plant_id)
    struct = {}
    for scen in ("C1", "C4"):
        by_id = {int(pid): entry for pid, entry in load_json(scen)["plants"].items()}
        members = {
            "C1-only": sorted(c1_only),
            "C4-only": sorted(c4_only),
            "shared": sorted(set(by_id) - c1_only - c4_only),
        }
        for year in TASK_YEARS:
            key = str(year)
            for group, ids in members.items():
                af = sum(float(by_id[i]["af_supply_ktce"][key]) for i in ids)
                cap = sum(float(by_id[i]["captured_commercial"][key]) for i in ids)
                struct[(scen, year, group)] = (
                    af * AF_CREDIT_TCO2_PER_TCE / 1000.0,
                    cap / 1000.0,
                )
    # unit_cost_metric_memo.md section 4 (design B), tolerance 0.1 Mt.
    expected = {
        ("C1", 2045, "shared"): (31.2, 191.0), ("C1", 2045, "C1-only"): (3.7, 21.2),
        ("C1", 2045, "C4-only"): (0.1, 0.0),
        ("C4", 2045, "shared"): (42.2, 167.3), ("C4", 2045, "C1-only"): (1.1, 0.0),
        ("C4", 2045, "C4-only"): (4.7, 20.7),
        ("C1", 2060, "shared"): (27.0, 271.4), ("C1", 2060, "C1-only"): (3.9, 33.9),
        ("C1", 2060, "C4-only"): (0.0, 0.0),
        ("C4", 2060, "shared"): (36.8, 263.6), ("C4", 2060, "C1-only"): (0.0, 0.0),
        ("C4", 2060, "C4-only"): (4.6, 33.4),
    }
    for key, (af_ref, cap_ref) in expected.items():
        af, cap = struct[key]
        assert abs(af - af_ref) < 0.1, (key, af, af_ref)
        assert abs(cap - cap_ref) < 0.1, (key, cap, cap_ref)
    return struct


def equalisation_gain() -> pd.DataFrame:
    """AF accessibility ratio of the 77 exchange lines under both conditions.

    ``kA_over_H_C1cond_2060`` is the ratio under real conditions (the S1 plant
    allocation) and ``kA_over_H_C4cond_2060`` the ratio after access
    equalisation; H_i is the 2060 kiln heat demand. The ratio is defined for
    every exchange line, independently of the sink whitelist.
    """
    df = pd.read_csv(
        M2_METRICS,
        usecols=[
            "plant_id", "group", "capacity_td",
            "kA_over_H_C1cond_2060", "kA_over_H_C4cond_2060",
        ],
    )
    assert df["group"].value_counts().to_dict() == {"C1-only": 42, "C4-only": 35}
    assert not df[["kA_over_H_C1cond_2060", "kA_over_H_C4cond_2060"]].isna().any().any()
    for group in ("C1-only", "C4-only"):
        assert df.loc[df.group == group, "capacity_td"].median() == 5000.0
    return df


def capture_task_table() -> dict:
    """Deliverable-1 capture task decomposition: (capture Mt/yr, capturing
    lines) by scenario x year x group, asserted against the notes anchors."""
    raw = pd.read_csv(FIG_DATA / "capture_task_decomposition.csv")
    detail = raw[raw.group != "TOTAL"]
    totals = raw[raw.group == "TOTAL"].set_index(["scenario", "year"])
    assert (detail.capture_lines_gt10kt == detail.capture_lines_gt0).all()
    identity = detail.groupby("group")[
        ["group_lines_2060_identity", "group_capacity_mt_per_yr"]
    ].first()
    for group, lines, cap_ref in (
        ("shared", 294, 459.0), ("C1-only", 42, 63.1), ("C4-only", 35, 59.2)
    ):
        assert identity.loc[group, "group_lines_2060_identity"] == lines
        assert abs(identity.loc[group, "group_capacity_mt_per_yr"] - cap_ref) < 0.1
    for scen, year, ref in (
        ("C1", 2045, 212.2), ("C1", 2060, 305.3),
        ("C4", 2045, 187.9), ("C4", 2060, 297.0),
    ):
        sub = detail[(detail.scenario == scen) & (detail.year == year)]
        group_sum = sub.commercial_capture_mt_per_yr.sum()
        # The CSV is rounded to 1 kt, so exact closure appears as <= 0.002 Mt.
        assert abs(group_sum - totals.loc[(scen, year), "commercial_capture_mt_per_yr"]) < 0.005
        assert abs(group_sum - ref) < 0.1
    table = {}
    for r in detail.itertuples():
        table[(r.scenario, int(r.year), r.group)] = (
            float(r.commercial_capture_mt_per_yr),
            int(r.capture_lines_gt10kt),
        )
    spot = {
        ("C1", 2045, "shared"): (190.993, 200), ("C1", 2045, "C1-only"): (21.240, 24),
        ("C4", 2045, "shared"): (167.254, 177), ("C4", 2045, "C4-only"): (20.660, 22),
        ("C1", 2060, "shared"): (271.357, 287), ("C1", 2060, "C1-only"): (33.897, 40),
        ("C4", 2060, "shared"): (263.596, 287), ("C4", 2060, "C4-only"): (33.431, 35),
    }
    for key, (cap_ref, n_ref) in spot.items():
        cap, n_lines = table[key]
        assert abs(cap - cap_ref) < 0.01 and n_lines == n_ref, key
    return table


# ---------------------------------------------------------------------------
# Fig. 4
# ---------------------------------------------------------------------------

def draw_fig4_scatter(ax, af_c1, af_c4, active, c1_only, c4_only) -> None:
    x = af_c1 * 100.0
    y = af_c4 * 100.0
    lim = (-2.0, 66.0)
    ax.plot(lim, lim, color=COLORS["grey"], lw=0.7, ls=(0, (4, 3)), zorder=1)
    swap_ids = set(c1_only) | set(c4_only)
    background = active & ~pd.Series(active.index.isin(swap_ids), index=active.index)
    ax.scatter(
        x[background], y[background], s=2.2, c="#B5B5B5", alpha=0.30,
        linewidths=0, zorder=2, label=f"Other lines (n={int(background.sum()):,})",
    )
    for ids, color, marker, label in (
        (c1_only, C1_COLOR, "s", f"S1-only (n={len(c1_only)})"),
        (c4_only, C4_COLOR, "o", f"S4-only (n={len(c4_only)})"),
    ):
        ax.scatter(
            x.loc[list(ids)], y.loc[list(ids)], s=13, c=color, marker=marker,
            alpha=0.88, edgecolor="white", linewidth=0.45, zorder=3, label=label,
        )
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xticks(np.arange(0, 61, 20))
    ax.set_yticks(np.arange(0, 61, 20))
    ax.set_xlabel("Realised AF heat share in 2030, S1 (%)")
    ax.set_ylabel("Realised AF heat share in 2030, S4 (%)")
    quiet_grid(ax, "both")
    despine(ax)
    panel_label(ax, "c")
    legend = ax.legend(loc="upper left", handletextpad=0.35, borderaxespad=0.2,
                       labelspacing=0.5, fontsize=FS_LEGEND)
    _legend_frame(legend)


def draw_fig4_map(ax, china, scs, coords, c1_only, c4_only, both) -> None:
    china.plot(ax=ax, color="#FBFBFB", edgecolor="#333333", linewidth=0.30, zorder=0)
    minx, miny, maxx, maxy = china.total_bounds
    # Reserve open water at the bottom for the South-China-Sea inset frame.
    miny = miny - 0.22 * (maxy - miny)
    groups = [
        (both, 2.6, "#A7A7A7", 0.32, ".", 1, 0.0),
        (c1_only, 14.0, C1_COLOR, 0.92, "s", 2.6, 0.4),
        (c4_only, 14.0, C4_COLOR, 0.92, "o", 3, 0.4),
    ]
    for ids, size, color, alpha, marker, zorder, edge_lw in groups:
        subset = coords.loc[coords.plant_id.isin(ids)]
        pts = _project(subset.longitude, subset.latitude)
        ax.scatter(
            pts.x, pts.y, s=size, c=color, marker=marker, alpha=alpha,
            linewidths=edge_lw, edgecolor="white" if edge_lw else "none",
            zorder=zorder,
        )
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal", adjustable="box", anchor="C")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    panel_label(ax, "a")

    inset = _add_south_china_sea_inset(ax, scs, rect=INSET_RECT)
    for ids, size, color, alpha, marker, zorder, edge_lw in groups:
        subset = coords.loc[coords.plant_id.isin(ids)]
        subset = subset[_inside_scs_data(subset.longitude, subset.latitude)]
        if subset.empty:
            continue
        pts = _project(subset.longitude, subset.latitude)
        inset.scatter(
            pts.x, pts.y, s=size * 0.5, c=color, marker=marker, alpha=alpha,
            linewidths=edge_lw * 0.7, edgecolor="white" if edge_lw else "none",
            zorder=zorder,
        )

    handles = [
        Line2D([], [], marker="s", ls="", mfc=C1_COLOR, mec="white", ms=4.6,
               label=f"S1-only (n={len(c1_only)})"),
        Line2D([], [], marker="o", ls="", mfc=C4_COLOR, mec="white", ms=4.6,
               label=f"S4-only (n={len(c4_only)})"),
        Line2D([], [], marker=".", ls="", color="#9A9A9A", ms=5.0,
               label="Operating in both"),
    ]
    # Open water is reserved along the bottom of the map for the South-China-Sea
    # inset, so the lower-left corner carries no thematic record and can hold
    # the legend without covering the mainland outline.
    legend = ax.legend(
        handles=handles, loc="lower left", bbox_to_anchor=(0.006, 0.008),
        handletextpad=0.4, borderaxespad=0.2, labelspacing=0.35,
        fontsize=FS_LEGEND,
    )
    _legend_frame(legend)


def _break_marks(axis, y: float, *, size_pt: float = 3.6) -> None:
    """Slanted break marks of a constant printed size at both x spine ends.

    The offsets are converted from points through the axes box, so the two
    marks of a junction keep the same angle and length even though the body
    and the tail axes differ greatly in height.
    """
    figure = axis.figure
    box = axis.get_position()
    step = size_pt / 72 / np.sqrt(2)
    dx = step / (box.width * figure.get_figwidth())
    dy = step / (box.height * figure.get_figheight())
    mark = dict(color=COLORS["ink"], clip_on=False, lw=0.7,
                transform=axis.transAxes, zorder=5)
    for x in (0.0, 1.0):
        axis.plot([x - dx, x + dx], [y - dy, y + dy], **mark)


def draw_fig4_equalisation(ax, ax_low, gain: pd.DataFrame) -> None:
    """Change in AF accessibility from equalising access, against the real ratio.

    x is the 2060 ratio kappa*A_i/H_i under real conditions, y the change that
    equalisation works on it (equalised minus real), so the reference is the
    zero line rather than a y = x diagonal. Equalisation gives every line
    almost the same ratio (0.694 at the median, a 0.06-wide band), so a line
    gains when its real ratio sits below that common level and loses when it
    sits above it: the panel is read as gain against the real level.

    Five lines with the highest real ratios lose far more than the rest, so
    the y axis is broken: the body of the distribution occupies the upper
    axes and the tail a compressed strip below it.
    """
    x_all = gain["kA_over_H_C1cond_2060"]
    delta = gain["kA_over_H_C4cond_2060"] - x_all
    body_lim = (-0.62, 0.62)
    tail_lim = (-2.60, -0.62)
    in_body = delta >= body_lim[0]

    x_max = float(x_all.max()) * 1.04
    for axis, limits in ((ax, body_lim), (ax_low, tail_lim)):
        axis.set_xlim(0.0, x_max)
        axis.set_ylim(*limits)
        axis.set_xticks([0, 1, 2, 3])
    ax.set_yticks([-0.6, -0.3, 0.0, 0.3, 0.6])
    ax_low.set_yticks([-2.5, -1.5])
    ax.tick_params(axis="x", labelbottom=False, length=0)

    ax.axhline(0, color=COLORS["ink"], lw=0.7, zorder=1)
    for ids, color, marker, label in (
        ("C1-only", C1_COLOR, "s", "S1-only"),
        ("C4-only", C4_COLOR, "o", "S4-only"),
    ):
        selected = gain["group"] == ids
        for axis, mask in ((ax, selected & in_body), (ax_low, selected & ~in_body)):
            if not mask.any():
                continue
            axis.scatter(
                x_all[mask], delta[mask], s=13, c=color, marker=marker,
                alpha=0.88, edgecolor="white", linewidth=0.45, zorder=3,
                label=f"{label} (n={int(selected.sum())})" if axis is ax else None,
            )
        x_median = float(x_all[selected].median())
        for axis, limits in ((ax, body_lim), (ax_low, tail_lim)):
            axis.plot([x_median, x_median], limits, color=color, lw=0.7,
                      ls=(0, (2.5, 1.6)), alpha=0.85, zorder=2)
        ax.plot([0.0, float(x_all.max())],
                [float(delta[selected].median())] * 2, color=color, lw=0.7,
                ls=(0, (2.5, 1.6)), alpha=0.85, zorder=2)
    ax.set_ylabel(r"$\Delta\,\kappa A_i/H_i$ from equalising access to AF")
    ax.yaxis.label.set_fontfamily("Helvetica")
    ax_low.set_xlabel(r"$\kappa A_i/H_i$ in 2060 under real conditions")
    for axis in (ax, ax_low):
        axis.spines["right"].set_visible(False)
        quiet_grid(axis, "y")
    # The two spines facing the break are removed and replaced by the
    # conventional slanted break marks at both ends of the junction.
    ax.spines["bottom"].set_visible(False)
    ax_low.spines["top"].set_visible(False)
    _break_marks(ax, 0.0)
    _break_marks(ax_low, 1.0)
    handles, labels = ax.get_legend_handles_labels()
    handles += [
        Line2D([], [], color=COLORS["ink"], lw=0.7),
        Line2D([], [], color=COLORS["grey"], lw=0.7, ls=(0, (2.5, 1.6))),
    ]
    labels += ["No change", "Group median"]
    legend = ax.legend(
        handles=handles, labels=labels, loc="upper right", ncol=2,
        handletextpad=0.35, borderaxespad=0.2, labelspacing=0.45,
        columnspacing=1.0, fontsize=FS_LEGEND,
    )
    _legend_frame(legend)
    panel_label(ax, "d")

    assert abs(float(x_all[gain.group == "C1-only"].median()) - 0.514) < 1e-3
    assert abs(float(x_all[gain.group == "C4-only"].median()) - 0.437) < 1e-3
    medians = {group: float(delta[gain.group == group].median())
               for group in ("C1-only", "C4-only")}
    assert abs(medians["C1-only"] - 0.179) < 1e-3
    assert abs(medians["C4-only"] - 0.258) < 1e-3
    assert int((delta[gain.group == "C1-only"] > 0).sum()) == 31
    assert int((delta[gain.group == "C4-only"] > 0).sum()) == 32
    assert int(in_body.sum()) == 72 and int((~in_body).sum()) == 5


# Symmetric diverging limit for the provincial capture-change map (Mt CO2 over
# the horizon); the largest provincial change is Jiangsu at -36.1 Mt.
CAPTURE_DELTA_CLIM = 40.0


def cumulative_capture() -> tuple[dict[str, dict[int, float]], dict[int, str]]:
    """Per-plant commercial capture integrated over 2025-2060 (Mt CO2).

    Period flows are integrated with the model's own trapezoidal period
    weights (2.5 years at both horizon ends, 5 years inside), the convention
    the run's cumulative carbon accounting uses.
    """
    weights = {
        year: (2.5 if index in (0, len(YEARS) - 1) else 5.0)
        for index, year in enumerate(YEARS)
    }
    totals = {}
    for scenario in ("C1", "C4"):
        totals[scenario] = {
            int(pid): sum(
                weights[year] * float(entry["captured_commercial"][str(year)])
                for year in YEARS
            ) / 1000.0
            for pid, entry in load_json(scenario)["plants"].items()
        }
    province = (
        pd.read_excel(PLANT_XLSX, usecols=["id", "province"])
        .rename(columns={"id": "plant_id"})
        .set_index("plant_id")["province"]
        .to_dict()
    )
    total_c1 = sum(totals["C1"].values())
    total_c4 = sum(totals["C4"].values())
    assert abs(total_c1 - 4936.7) < 0.5 and abs(total_c4 - 4698.5) < 0.5
    return totals, {int(k): v for k, v in province.items()}


def provincial_capture_delta() -> pd.Series:
    """Provincial cumulative commercial capture, S4 minus S1 (Mt CO2).

    The per-plant totals close on the run's own cumulative capture, and the
    fleet-group split behind the map is asserted here: over the horizon the
    exchange relocates far more capture than it changes (the 42 S1-only lines
    lose 553.3 Mt and the 35 S4-only lines gain 533.7 Mt, nearly cancelling),
    while the retained fleet's substitution supplies most of the national
    reduction.
    """
    totals, province = cumulative_capture()
    c1_only = set(pd.read_csv(SCEN / "data02_C1-only_plants.csv").plant_id)
    c4_only = set(pd.read_csv(SCEN / "data02_C4-only_plants.csv").plant_id)
    ids = set(totals["C1"]) | set(totals["C4"])
    shared = ids - c1_only - c4_only
    for label, members, expected in (
        ("C1-only", c1_only, -553.3),
        ("C4-only", c4_only, 533.7),
        ("shared", shared, -218.6),
    ):
        delta = sum(
            totals["C4"].get(pid, 0.0) - totals["C1"].get(pid, 0.0) for pid in members
        )
        assert abs(delta - expected) < 0.5, (label, delta, expected)
    assert abs(sum(totals["C4"].values()) - sum(totals["C1"].values()) + 238.3) < 0.5

    frames = {
        scenario: pd.Series(values).groupby(province).sum()
        for scenario, values in totals.items()
    }
    index = frames["C1"].index.union(frames["C4"].index)
    delta = (
        frames["C4"].reindex(index, fill_value=0.0)
        - frames["C1"].reindex(index, fill_value=0.0)
    )
    assert abs(float(delta["江苏"]) + 36.1) < 0.1
    assert abs(float(delta["安徽"]) - 15.3) < 0.1
    assert int((delta < -0.05).sum()) == 22 and int((delta > 0.05).sum()) == 6
    return delta


def draw_fig4_capture_map(ax, cax, china, scs, delta: pd.Series) -> None:
    """Provincial change in cumulative commercial capture (S4 - S1, Mt CO2).

    The frame, inset and choropleth treatment are those of panel b and of the
    Fig. 5 maps, so the four maps of the two figures read as one system:
    blue = more capture under real conditions, orange = more under equalised
    access, and the province-level units without a modelled plant (Shanghai,
    Taiwan, Hong Kong, Macao) take the zero value of the scale.
    """
    norm = Normalize(-CAPTURE_DELTA_CLIM, CAPTURE_DELTA_CLIM)
    inset = _mini_map_frame(ax, china, scs, INSET_RECT)
    _choropleth(ax, inset, china, scs, delta.to_dict(), norm,
                zero_fill=ZERO_FILL_PROVINCES)
    panel_label(ax, "b")
    colorbar = ax.figure.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap=DIVERGING_CMAP),
        cax=cax, orientation="horizontal", ticks=[-40, 0, 40],
    )
    colorbar.set_label(
        "Provincial commercial capture, S4 - S1 (Mt CO₂, 2025-2060)",
        labelpad=3, fontsize=FS_LABEL,
    )
    colorbar.ax.xaxis.label.set_fontfamily("Helvetica")
    colorbar.ax.tick_params(labelsize=FS_NOTE, length=1.6, width=0.5, pad=1.2)
    colorbar.outline.set_linewidth(0.4)


def _task_axis_frame(ax) -> dict:
    """Shared x skeleton of Fig. 4c/4d: (2045, 2060) blocks x the three groups."""
    centers, positions, labels, mids = {}, [], [], []
    x = 0.0
    for year in TASK_YEARS:
        block = []
        for group in TASK_GROUPS:
            centers[(year, group)] = x
            positions.append(x)
            labels.append(GROUP_LABEL.get(group, group))
            block.append(x)
            x += 1.0
        mids.append((sum(block) / len(block), str(year)))
        x += 0.9
    ax.set_xticks(positions, labels, fontsize=FS_NOTE)
    for mid, label in mids:
        # Fixed point offset: the year band must clear the group labels by the
        # same distance whatever height the panel is given.
        ax.annotate(
            label, xy=(mid, 0.0), xycoords=("data", "axes fraction"),
            xytext=(0, -14), textcoords="offset points",
            ha="center", va="top", fontsize=FS_LABEL,
        )
    ax.set_xlim(-0.62, x - 1.9 + 0.62)
    return centers


def draw_structure_panel(ax, struct, letter: str) -> None:
    """Design B: AF fossil credit (light) + commercial capture (saturated)."""
    centers = _task_axis_frame(ax)
    for scen, color, offset in (("C1", C1_COLOR, -0.20), ("C4", C4_COLOR, 0.20)):
        for (year, group), xc in centers.items():
            af, cap = struct[(scen, year, group)]
            x = xc + offset
            ax.bar(x, af, 0.36, color=color, alpha=0.40, lw=0, zorder=2)
            ax.bar(x, cap, 0.36, bottom=af, color=color, lw=0, zorder=2)
            if af > 0.05:
                ax.plot([x - 0.18, x + 0.18], [af, af], color="white", lw=0.45, zorder=3)
    ax.set_ylim(0, 330)
    ax.set_yticks([0, 150, 300])
    ax.set_ylabel("AF credit + capture\n(Mt CO₂ yr⁻¹)", fontsize=FS_LABEL)
    ax.yaxis.label.set_fontfamily("Helvetica")
    quiet_grid(ax)
    despine(ax)
    legend = ax.legend(
        handles=[
            Patch(facecolor=C1_COLOR, label="S1 capture"),
            Patch(facecolor=C4_COLOR, label="S4 capture"),
            Patch(facecolor=C1_COLOR, alpha=0.40, label="S1 AF credit"),
            Patch(facecolor=C4_COLOR, alpha=0.40, label="S4 AF credit"),
        ],
        loc="upper left", ncol=2, handlelength=1.0, handletextpad=0.4,
        columnspacing=0.8, borderaxespad=0.15, labelspacing=0.4, fontsize=FS_NOTE,
    )
    _legend_frame(legend)
    panel_label(ax, letter)


def draw_capture_task_panel(ax, table, letter: str) -> None:
    """Commercial capture by group and scenario (bars).

        The capturing-line counts are not drawn on the bars: they are counts, not
        volumes, so a label above a bar reads as a bar value - two bars of
        different height would then carry the same number. The counts are given in
        the caption instead.
        """
    centers = _task_axis_frame(ax)
    for scen, color, offset in (("C1", C1_COLOR, -0.20), ("C4", C4_COLOR, 0.20)):
        for (year, group), xc in centers.items():
            cap, _ = table[(scen, year, group)]
            x = xc + offset
            ax.bar(x, cap, 0.36, color=color, lw=0, zorder=2)
    ax.set_ylim(0, 330)
    ax.set_yticks([0, 150, 300])
    ax.set_ylabel("Commercial capture\n(Mt CO₂ yr⁻¹)", fontsize=FS_LABEL)
    ax.yaxis.label.set_fontfamily("Helvetica")
    quiet_grid(ax)
    despine(ax)
    legend = ax.legend(
        handles=[
            Patch(facecolor=C1_COLOR, label="S1"),
            Patch(facecolor=C4_COLOR, label="S4"),
        ],
        loc="upper left", handlelength=1.0, handletextpad=0.4,
        borderaxespad=0.15, labelspacing=0.4, fontsize=FS_NOTE,
    )
    _legend_frame(legend)
    panel_label(ax, letter)


def make_fig4() -> Path:
    af_c1, af_c4, active = af_shares_2030()
    swap_c1 = pd.read_csv(SCEN / "data02_C1-only_plants.csv")
    swap_c4 = pd.read_csv(SCEN / "data02_C4-only_plants.csv")
    c1_only = list(swap_c1.plant_id)
    c4_only = list(swap_c4.plant_id)
    assert len(c1_only) == 42 and len(c4_only) == 35

    # Anchor: AF-share medians of the swap groups (panel a).
    med_c1 = (af_c1.loc[c1_only].median(), af_c4.loc[c1_only].median())
    med_c4 = (af_c1.loc[c4_only].median(), af_c4.loc[c4_only].median())
    assert abs(med_c1[0] - 0.1767) < 0.002 and abs(med_c1[1] - 0.0212) < 0.002, med_c1
    assert abs(med_c4[0] - 0.0149) < 0.002 and abs(med_c4[1] - 0.3048) < 0.002, med_c4

    # Anchor: swap CSVs reproduce the 2060 operation-status set differences.
    op_c1 = operating_sets("C1", 2060)
    op_c4 = operating_sets("C4", 2060)
    assert set(c1_only) == op_c1 - op_c4
    assert set(c4_only) == op_c4 - op_c1
    both = op_c1 & op_c4

    gain = equalisation_gain()

    coords = pd.read_excel(PLANT_XLSX, usecols=["id", "longitude", "latitude"])
    coords = coords.rename(columns={"id": "plant_id"})
    china, scs = _load_basemap()
    _scs_boundary_layer()  # warm the cache so the inset draws identically

    fig_w = 190 / 25.4
    fig_h = 7.64
    fig = plt.figure(figsize=(fig_w, fig_h))

    def rect(x, y_top, w, h):
        return [x / fig_w, (fig_h - y_top - h) / fig_h, w / fig_w, h / fig_h]

    # Two rows of equal square panels in the order c, d, b, a: the two maps on
    # top (the asset exchange and the provincial capture change), the two
    # quantitative panels below (the behavioural response and the equalisation
    # mechanism).  The mechanism keeps the square footprint of the other panels
    # even though it is drawn as two axes (distribution body and compressed
    # tail), so the grid stays aligned.
    left = 0.52
    col_w = 2.90
    right_col = left + col_w + 0.62
    row1_top = 0.30
    # The row gap holds panel b's colour bar and its label, and still leaves
    # clear space between the two rows.
    row_gap = 0.86
    row2_top = row1_top + col_w + row_gap
    tail_h = 0.40
    body_h = col_w - tail_h - 0.12

    ax_a = fig.add_axes(rect(left, row1_top, col_w, col_w))
    draw_fig4_map(ax_a, china, scs, coords, c1_only, c4_only, both)

    ax_b = fig.add_axes(rect(right_col, row1_top, col_w, col_w))
    cax_b = fig.add_axes(rect(right_col, row1_top + col_w + 0.10, col_w, 0.075))
    draw_fig4_capture_map(ax_b, cax_b, china, scs, provincial_capture_delta())

    ax_c = fig.add_axes(rect(left, row2_top, col_w, col_w))
    draw_fig4_scatter(ax_c, af_c1, af_c4, active, c1_only, c4_only)

    ax_d = fig.add_axes(rect(right_col, row2_top, col_w, body_h))
    ax_d_tail = fig.add_axes(rect(right_col, row2_top + body_h + 0.12, col_w, tail_h))
    draw_fig4_equalisation(ax_d, ax_d_tail, gain)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / "fig4_af_conditioned_asset_selection_v5_20260915.png"
    fig.savefig(path, dpi=600, facecolor="white")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Fig. 5
# ---------------------------------------------------------------------------

def capacity_divergence() -> pd.DataFrame:
    """Per-year operating-capacity split between the S1 and S5 paths (Mt/yr)."""
    cap = annual_capacity_mt()
    status = {"C1": pd.read_csv(CSV_DIR["C1"] / "full_operation_status.csv"),
              "C5": pd.read_csv(CSV_DIR["C5"] / "full_operation_status.csv")}
    rows = []
    for year in YEARS:
        sets = {}
        for scenario, frame in status.items():
            sub = frame[(frame.period == year) & (frame.operating == 1)]
            sets[scenario] = set(sub.plant_id)
        rows.append(
            {
                "year": year,
                "common": float(cap.loc[list(sets["C1"] & sets["C5"])].sum()),
                "only_c1": float(cap.loc[list(sets["C1"] - sets["C5"])].sum()),
                "only_c5": float(cap.loc[list(sets["C5"] - sets["C1"])].sum()),
            }
        )
    frame = pd.DataFrame(rows).set_index("year")
    assert abs(frame.loc[2060, "common"] - 459.0) < 0.1
    assert abs(frame.loc[2060, "only_c1"] - 63.1) < 0.1
    assert abs(frame.loc[2060, "only_c5"] - 59.2) < 0.1
    assert frame.loc[2025, ["only_c1", "only_c5"]].abs().max() < 1e-6
    return frame


def capture_divergence() -> pd.DataFrame:
    """Per-year plant-matched capture split between S1 and S5 (Mt/yr)."""
    plant_results = {
        scenario: load_json(scenario)["plants"] for scenario in ("C1", "C5")
    }
    ids = set(plant_results["C1"]) | set(plant_results["C5"])
    rows = []
    for year in YEARS:
        key = str(year)
        c1 = {
            pid: float(plant_results["C1"].get(pid, {}).get("captured_commercial", {}).get(key, 0.0))
            for pid in ids
        }
        c5 = {
            pid: float(plant_results["C5"].get(pid, {}).get("captured_commercial", {}).get(key, 0.0))
            for pid in ids
        }
        common = sum(min(c1[pid], c5[pid]) for pid in ids) / 1000.0
        total_c1 = sum(c1.values()) / 1000.0
        total_c5 = sum(c5.values()) / 1000.0
        rows.append({
            "year": year,
            "common": common,
            "only_c1": total_c1 - common,
            "only_c5": total_c5 - common,
        })
    frame = pd.DataFrame(rows).set_index("year")
    assert abs(frame.loc[2060, "common"] - 269.223) < 0.002
    assert abs(frame.loc[2060, "only_c1"] - 36.031) < 0.002
    assert abs(frame.loc[2060, "only_c5"] - 37.603) < 0.002
    return frame


def spatial_reconfig() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Provincial production-side reconfiguration and plant-level capture
    relocation, S5 - S1 at 2060 (deliverable 3 of the data pack)."""
    prov = pd.read_csv(FIG_DATA / "fig5b_province_delivery.csv").set_index("province")
    plants = pd.read_csv(FIG_DATA / "fig5b_capture_delta.csv")
    flows = pd.read_csv(FIG_DATA / "fig5b_interprovincial_flow_delta.csv")
    # Demand is exogenous: provincial delivered volumes are identical, so any
    # change is production-side dispatch, distance or inter-provincial flow.
    assert (prov.delivered_in_delta_mt_C5mC1 == 0).all()
    assert abs(prov.dispatched_out_delta_mt_C5mC1.sum()) < 0.05
    assert abs(prov.loc["安徽", "dispatched_out_delta_mt_C5mC1"] - 4.7) < 0.1
    assert abs(prov.loc["江苏", "dispatched_out_delta_mt_C5mC1"] + 4.3) < 0.1
    assert abs(prov.loc["河南", "dispatched_out_delta_mt_C5mC1"] + 3.1) < 0.1
    assert abs(prov.loc["陕西", "delivered_in_wavg_km_delta_C5mC1"] - 30.2) < 0.1
    assert abs(prov.loc["云南", "delivered_in_wavg_km_delta_C5mC1"] - 20.6) < 0.1
    assert abs(prov.loc["贵州", "delivered_in_wavg_km_delta_C5mC1"] - 19.7) < 0.1
    assert abs(flows.flow_mt_C1.sum() - 34.6) < 0.1
    assert abs(flows.flow_mt_C5.sum() - 38.7) < 0.1
    plants["contrib_c1"] = (plants.capture_mt_C1_2060 - plants.capture_mt_C5_2060).clip(lower=0)
    plants["contrib_c5"] = (plants.capture_mt_C5_2060 - plants.capture_mt_C1_2060).clip(lower=0)
    assert abs(plants.contrib_c1.sum() - 36.031) < 0.01
    assert abs(plants.contrib_c5.sum() - 37.603) < 0.01
    c1_only = set(pd.read_csv(SCEN / "data02_C1-only_plants.csv").plant_id)
    c4_only = set(pd.read_csv(SCEN / "data02_C4-only_plants.csv").plant_id)
    assert abs(plants.loc[plants.plant_id.isin(c1_only), "contrib_c1"].sum() - 33.9) < 0.1
    assert abs(plants.loc[plants.plant_id.isin(c4_only), "contrib_c5"].sum() - 34.7) < 0.1
    by_prov = plants.groupby("province")[["contrib_c1", "contrib_c5"]].sum()
    delta_prov = by_prov.contrib_c5 - by_prov.contrib_c1
    assert abs(delta_prov.get("安徽", 0.0) - 3.1) < 0.1
    assert abs(delta_prov.get("江苏", 0.0) + 2.8) < 0.1
    assert abs(delta_prov.get("河南", 0.0) + 1.8) < 0.1
    return prov, plants


def draw_fig5_overview(ax, divergence, summ_c1, summ_c5, rd_c1, rd_c5) -> None:
    """Paired, S1-normalised view of volume and spatial-configuration metrics."""
    c1 = divergence.loc[2060]
    cap_totals = [c1.common + c1.only_c1, c1.common + c1.only_c5]
    delivered = [rd_c1["delivered_kt"] / 1000.0, rd_c5["delivered_kt"] / 1000.0]
    captured = [summ_c1["2060"]["commercial_captured_co2_kt"] / 1000.0,
                summ_c5["2060"]["commercial_captured_co2_kt"] / 1000.0]
    assert abs(delivered[0] - 510.4) < 0.1 and abs(delivered[1] - 510.4) < 0.1
    assert abs(captured[0] - 305.3) < 0.1 and abs(captured[1] - 306.8) < 0.1
    km = [rd_c1["weighted_avg_km"], rd_c5["weighted_avg_km"]]
    assert abs(km[0] - 89.5) < 0.1 and abs(km[1] - 94.7) < 0.1
    share = [100 * rd_c1["inter_provincial_share"], 100 * rd_c5["inter_provincial_share"]]
    assert abs(share[0] - 6.8) < 0.1 and abs(share[1] - 7.6) < 0.1

    labels = [
        "Operating capacity", "Delivered clinker", "Captured CO₂",
        "Delivery distance", "Inter-provincial share",
    ]
    ratios = np.array([
        100 * cap_totals[1] / cap_totals[0],
        100 * delivered[1] / delivered[0],
        100 * captured[1] / captured[0],
        100 * km[1] / km[0],
        100 * share[1] / share[0],
    ])
    ypos = np.arange(len(labels))[::-1]
    ax.axvline(100, color=COLORS["grey"], lw=0.8, ls=(0, (3, 2)), zorder=1)
    for idx, (y, ratio) in enumerate(zip(ypos, ratios)):
        filled = idx >= 3
        ax.plot([100, ratio], [y, y], color=COMMIT_COLOR, lw=1.4, alpha=0.82, zorder=2)
        ax.plot(ratio, y, marker="D", ms=4.1,
                mfc=COMMIT_COLOR if filled else "white", mec=COMMIT_COLOR,
                mew=1.0, zorder=3)
        ax.text(max(ratio, 100.0) + 0.6, y, f"{ratio:.1f}", ha="left",
                va="center", fontsize=FS_NOTE)
    ax.axhline(1.5, color="#D8D8D8", lw=0.6)
    ax.set_yticks(ypos, labels)
    for tick in ax.get_yticklabels():
        fallback_font(tick)
    ax.set_xlim(97, 115)
    ax.set_xticks([100, 105, 110, 115])
    ax.set_xlabel("S5 relative to S1 in 2060 (%)")
    quiet_grid(ax, "x")
    despine(ax)
    legend = ax.legend(
        handles=[
            Line2D([], [], marker="D", ls="", mfc="white", mec=COMMIT_COLOR, mew=1.0, ms=4.2,
                   label="System volumes"),
            Line2D([], [], marker="D", ls="", mfc=COMMIT_COLOR, mec=COMMIT_COLOR, ms=4.2,
                   label="Spatial configuration"),
        ],
        loc="upper right", frameon=True, fontsize=FS_NOTE, handletextpad=0.35,
        labelspacing=0.35, borderaxespad=0.2,
    )
    _legend_frame(legend)
    panel_label(ax, "a")


def _mini_map_frame(ax, china, scs, inset_rect):
    """Miniature China map canvas plus the South-China-Sea inset, mirroring
    the Fig. 4c treatment (open water reserved along the bottom)."""
    minx, miny, maxx, maxy = china.total_bounds
    miny = miny - 0.22 * (maxy - miny)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal", adjustable="box", anchor="C")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    return _add_south_china_sea_inset(ax, scs, rect=inset_rect)


def _choropleth(ax, inset, china, scs, values, norm, *, zero_fill=()) -> None:
    zero_color = DIVERGING_CMAP(norm(0.0))

    def color_of(name):
        if name in zero_fill:
            return zero_color
        value = values.get(name)
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return mcolors.to_rgba(NO_DATA_COLOR)
        return DIVERGING_CMAP(norm(value))

    china.plot(ax=ax, color=[color_of(n) for n in china.short_name],
               edgecolor="#333333", linewidth=0.22, zorder=1)
    scs.plot(ax=inset, color=[color_of(n) for n in scs.short_name],
             edgecolor="#333333", linewidth=0.30, zorder=2)
    _scs_boundary_layer().plot(ax=inset, facecolor="none",
                               edgecolor="#333333", linewidth=0.40, zorder=3)


def draw_fig5_spatial(ax_l, ax_r, cax_l, cax_r, china, scs, prov, plants) -> None:
    """Spatial reconfiguration S5 - S1 at 2060: provincial production dispatch
    (left, with the plant-level capture relocation on top) and proxy delivery
    distance (right).  Delivered volumes are exogenous and identical, so they
    are not shown."""
    norm_mt = Normalize(-5, 5)
    norm_km = Normalize(-30, 30)

    inset_l = _mini_map_frame(ax_l, china, scs, INSET_RECT)
    _choropleth(ax_l, inset_l, china, scs,
                prov.dispatched_out_delta_mt_C5mC1.to_dict(), norm_mt,
                zero_fill=ZERO_FILL_PROVINCES)
    for side, color in (("contrib_c1", JOINT_COLOR), ("contrib_c5", COMMIT_COLOR)):
        sub = plants[plants[side] > 0]
        pts = _project(sub.longitude, sub.latitude)
        ax_l.scatter(pts.x, pts.y, s=0.6 + 4.5 * sub[side], c=color, alpha=0.85,
                     edgecolor="white", linewidth=0.25, zorder=4)
        sub_in = sub[_inside_scs_data(sub.longitude, sub.latitude)]
        if not sub_in.empty:
            pts_in = _project(sub_in.longitude, sub_in.latitude)
            inset_l.scatter(pts_in.x, pts_in.y, s=0.3 + 2.2 * sub_in[side],
                            c=color, alpha=0.85, edgecolor="white",
                            linewidth=0.2, zorder=4)
    panel_label(ax_l, "c")
    legend_l = ax_l.legend(
        handles=[
            Line2D([], [], marker="o", ls="", mfc=JOINT_COLOR, mec="white",
                   mew=0.4, ms=3.4, label="S1 side (36.0 Mt)"),
            Line2D([], [], marker="o", ls="", mfc=COMMIT_COLOR, mec="white",
                   mew=0.4, ms=3.4, label="S5 side (37.6 Mt)"),
        ],
        loc="lower left", bbox_to_anchor=(0.005, 0.008), fontsize=FS_NOTE,
        handletextpad=0.35, borderaxespad=0.15, labelspacing=0.3,
    )
    _legend_frame(legend_l)

    inset_r = _mini_map_frame(ax_r, china, scs, INSET_RECT)
    _choropleth(ax_r, inset_r, china, scs,
                prov.delivered_in_wavg_km_delta_C5mC1.to_dict(), norm_km,
                zero_fill=ZERO_FILL_PROVINCES)
    panel_label(ax_r, "d")

    for cax, norm, ticks, label in (
        (cax_l, norm_mt, [-5, 0, 5],
         "Production dispatch, S5 - S1 (Mt clinker yr⁻¹)"),
        (cax_r, norm_km, [-30, 0, 30],
         "Proxy delivery distance, S5 - S1 (km)"),
    ):
        cbar = cax.figure.colorbar(
            plt.cm.ScalarMappable(norm=norm, cmap=DIVERGING_CMAP),
            cax=cax, orientation="horizontal", ticks=ticks,
        )
        cbar.set_label(label, labelpad=3, fontsize=FS_LABEL)
        cbar.ax.xaxis.label.set_fontfamily("Helvetica")
        cbar.ax.tick_params(labelsize=FS_NOTE, length=1.6, width=0.5, pad=1.2)
        cbar.outline.set_linewidth(0.4)


def waterfall_deltas() -> tuple[list[float], float]:
    c1 = load_json("C1")["cost_breakdown_total"]["components_discounted_kCNY"]
    c5 = load_json("C5")["cost_breakdown_total"]["components_discounted_kCNY"]
    deltas = []
    for key, _, expected in WATERFALL:
        delta = (c5[key] - c1[key]) / 1e6
        assert abs(delta - expected) < 0.02, (key, delta, expected)
        deltas.append(delta)
    total = (sum(c5.values()) - sum(c1.values())) / 1e6
    other = total - sum(deltas)
    deltas.append(other)
    assert abs(total - 7.00) < 0.01, total
    return deltas, total


def draw_fig5_waterfall(ax, deltas, total) -> None:
    # Combine the smaller negative items by decision channel.  This preserves
    # exact closure while preventing a dense list of near-duplicate bars.
    labels = [
        "Clinker\ndelivery", "Capture\nO&M", "Capture\ncapex", "CO₂\ntransport",
        "Capacity\nturnover", "Dispatch\n& AF", "Other", "Total",
    ]
    values = [
        deltas[0], deltas[1], deltas[2], deltas[3],
        deltas[4] + deltas[5], deltas[6] + deltas[7], deltas[8], total,
    ]
    assert abs(sum(values[:-1]) - total) < 1e-8
    cumulative = 0.0
    for index, (label, value) in enumerate(zip(labels, values)):
        if label == "Total":
            bottom, height = 0.0, value
            color = COLORS["ink"]
        else:
            bottom = min(cumulative, cumulative + value)
            height = abs(value)
            color = COLORS["orange"] if value > 0 else COLORS["blue"]
            if label == "Other":
                color = COLORS["grey_light"]
        ax.bar(index, height, bottom=bottom, width=0.60, color=color,
               edgecolor="white", lw=0.35, zorder=2)
        ax.text(
            index, bottom + height + 0.16 if value >= 0 else bottom - 0.16,
            f"{value:+.2f}", ha="center", va="bottom" if value >= 0 else "top",
            fontsize=FS_NOTE,
        )
        if label != "Total":
            cumulative += value
            if index < len(values) - 1:
                ax.plot([index + 0.30, index + 0.70], [cumulative, cumulative],
                        color=COLORS["grey"], lw=0.65, ls=":", zorder=1)
    ax.axhline(0, color=COLORS["ink"], lw=0.7)
    ax.set_xticks(range(len(labels)), labels, fontsize=6.0)
    for tick in ax.get_xticklabels():
        fallback_font(tick)
    ax.set_ylabel("S5 - S1, discounted (bn CNY)")
    ax.set_ylim(-0.8, 12.4)
    quiet_grid(ax)
    despine(ax)
    panel_label(ax, "b")


def draw_figS_forest(ax, ax_far) -> None:
    ypos = np.arange(len(FOREST_ROWS))[::-1].astype(float)
    display_labels = [
        "R5 75-node*", "R4 operating costs", "R1 AF costs",
        "R2 AF effectiveness", "R7 EOR revenue", "R8 storage rate",
        "R6 terminal value", "Central", "K no commitment",
        "R3 biogenic burden",
    ]
    styles = {
        "robust": {"color": COLORS["blue"], "mfc": COLORS["blue"]},
        "central": {"color": COLORS["ink"], "mfc": COLORS["ink"]},
        "null": {"color": COLORS["grey"], "mfc": COLORS["grey"]},
        "bound": {"color": COLORS["blue"], "mfc": COLORS["blue"]},
    }
    for y, (label, point, lower, upper, style) in zip(ypos, FOREST_ROWS):
        spec = styles[style]
        color = spec["color"]
        # The R5 row is the same object as the other rows, only drawn on the
        # broken axis; styling it identically avoids an unexplained hatched
        # block that carries no encoding of its own.
        target = ax_far if style == "bound" else ax
        target.plot([lower, upper], [y, y], color=color, lw=1.7, zorder=2,
                    solid_capstyle="round")
        target.plot(point, y, marker="D", ms=4.6, mfc=spec["mfc"], mec=color,
                    mew=1.0, zorder=3)
    ax.axvline(0, color=COLORS["ink"], lw=0.7, ls="--", zorder=1)
    ax.set_yticks(ypos, display_labels)
    ax.set_xlim(-4, 20)
    ax.set_xticks([0, 10, 20])
    ax_far.set_xlim(65, 80)
    ax_far.set_xticks([70, 80])
    for axis in (ax, ax_far):
        axis.set_ylim(ypos[-1] - 0.62, ypos[0] + 0.62)
        quiet_grid(axis, "x")
        despine(axis)
    ax_far.tick_params(axis="y", left=False, labelleft=False)
    ax_far.spines["left"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # Conventional broken-axis marks retain the R5 interval without compressing
    # the nine central-scale comparisons.
    mark = dict(color=COLORS["ink"], clip_on=False, lw=0.7)
    ax.plot((0.985, 1.015), (-0.015, 0.015), transform=ax.transAxes, **mark)
    ax.plot((0.985, 1.015), (0.985, 1.015), transform=ax.transAxes, **mark)
    ax_far.plot((-0.035, 0.035), (-0.015, 0.015), transform=ax_far.transAxes, **mark)
    ax_far.plot((-0.035, 0.035), (0.985, 1.015), transform=ax_far.transAxes, **mark)


def make_fig5(summ_c1, summ_c5) -> Path:
    divergence = capacity_divergence()
    capture_divergence()  # plant-matched split anchors (269.2 / 36.0 / 37.6 Mt)
    prov, plants = spatial_reconfig()
    rd_c1 = load_json("C1")["regional_demand"]["per_period"]["2060"]
    rd_c5 = load_json("C5")["regional_demand"]["per_period"]["2060"]
    deltas, total = waterfall_deltas()
    china, scs = _load_basemap()
    _scs_boundary_layer()  # warm the cache so the insets draw identically

    fig_w = 190 / 25.4
    fig_h = 6.52
    fig = plt.figure(figsize=(fig_w, fig_h))

    def rect(x, y_top, w, h):
        return [x / fig_w, (fig_h - y_top - h) / fig_h, w / fig_w, h / fig_h]

    # Two rows: the two quantitative summaries on top (a the volume and
    # configuration contrast, b the cost decomposition) and the two maps
    # below, which locate the two largest cost items of the waterfall
    # province by province.  Panel a starts far enough right for its long
    # category labels; the maps keep the Albers aspect of the basemap
    # (height/width 1.048 including the reserved South-China-Sea strip).
    ax_a = fig.add_axes(rect(1.28, 0.38, 2.45, 2.10))
    draw_fig5_overview(ax_a, divergence, summ_c1, summ_c5, rd_c1, rd_c5)

    ax_b = fig.add_axes(rect(4.15, 0.38, 3.05, 2.10))
    draw_fig5_waterfall(ax_b, deltas, total)

    map_h = 2.74
    map_w = map_h / 1.048
    ax_c = fig.add_axes(rect(1.28, 3.10, map_w, map_h))
    ax_d = fig.add_axes(rect(4.15 + (3.05 - map_w) / 2, 3.10, map_w, map_h))
    cax_c = fig.add_axes(rect(1.28, 3.10 + map_h + 0.10, map_w, 0.075))
    cax_d = fig.add_axes(
        rect(4.15 + (3.05 - map_w) / 2, 3.10 + map_h + 0.10, map_w, 0.075)
    )
    draw_fig5_spatial(ax_c, ax_d, cax_c, cax_d, china, scs, prov, plants)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / "fig5_commitment_cost_lockin_v5_20260915.png"
    fig.savefig(path, dpi=600, facecolor="white")
    plt.close(fig)
    return path


def make_figS_sensitivity() -> Path:
    fig_w = 155 / 25.4
    fig_h = 3.55
    fig = plt.figure(figsize=(fig_w, fig_h))
    ax = fig.add_axes([0.34, 0.17, 0.52, 0.76])
    ax_far = fig.add_axes([0.90, 0.17, 0.075, 0.76], sharey=ax)
    draw_figS_forest(ax, ax_far)
    fig.text(0.66, 0.045, "Additional discounted cost vs. joint planning (bn CNY)",
             ha="center", va="center", fontsize=FS_LABEL)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / "figS1_commitment_sensitivity_v5_20260918.png"
    fig.savefig(path, dpi=600, facecolor="white")
    plt.close(fig)
    return path


def make_figS9(summ_c1, summ_c4) -> Path:
    """Former Fig. 4c,4d: mitigation structure and capture task at 155 mm."""
    # Anchor: 2045 commercial capture 212.2 vs 187.9 Mt.
    assert abs(summ_c1["2045"]["commercial_captured_co2_kt"] / 1000.0 - 212.2) < 0.1
    assert abs(summ_c4["2045"]["commercial_captured_co2_kt"] / 1000.0 - 187.9) < 0.1
    struct = mitigation_structure()
    task = capture_task_table()
    # The capture part of the design-B structure must reproduce the
    # deliverable-1 decomposition exactly (same JSON source).
    for key, (_, cap) in struct.items():
        assert abs(cap - task[key][0]) < 0.01, key

    fig_w = 155 / 25.4
    fig_h = 3.30
    fig = plt.figure(figsize=(fig_w, fig_h))

    def rect(x, y_top, w, h):
        return [x / fig_w, (fig_h - y_top - h) / fig_h, w / fig_w, h / fig_h]

    ax_a = fig.add_axes(rect(0.55, 0.42, 2.45, 2.00))
    draw_structure_panel(ax_a, struct, "a")
    ax_b = fig.add_axes(rect(3.50, 0.42, 2.45, 2.00))
    draw_capture_task_panel(ax_b, task, "b")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / "figS9_mitigation_structure_capture_task_20260920.png"
    fig.savefig(path, dpi=600, facecolor="white")
    plt.close(fig)
    return path


def main() -> None:
    apply_style()
    summ_c1 = load_json("C1")["summary"]
    summ_c4 = load_json("C4")["summary"]
    summ_c5 = load_json("C5")["summary"]
    fig4 = make_fig4()
    print(fig4)
    fig5 = make_fig5(summ_c1, summ_c5)
    print(fig5)
    figS = make_figS_sensitivity()
    print(figS)
    figS9 = make_figS9(summ_c1, summ_c4)
    print(figS9)


if __name__ == "__main__":
    main()
