"""RCR SI Figures S2–S6, v5 formal-run caliber (PNG only, 155 mm, 600 dpi).

All numbers come from the frozen v5 formal run pack
(``v5/results/formal_v1_20260914``), the frozen market-layer data
(``v5/data/demand_market_*.csv``), the demand workbook
(``v5/data/model_input/demand/cement_demand_scenarios_v4.xlsx``) and the M2
post-processing export (``tmp/m2_analysis_20260918/m2_plant_metrics.csv``).
Two quick LP certificates are parsed from logs regenerated on 2026-09-19:

    PYTHONPATH=v5/model .venv/bin/python v5/scenarios/check_arc_feasibility.py \
        --scenario d_medium --nodes v5/data/demand_market_nodes.csv \
        --arcs v5/data/demand_market_arcs.csv \
        > tmp/figS_20260919/check_arc_feasibility_d_medium.log 2>&1
    PYTHONPATH=v5/model:v5/scenarios .venv/bin/python \
        v5/scenarios/screen_arc_economics.py \
        > tmp/figS_20260919/screen_arc_economics.log 2>&1

Outputs (into ``paper/RCR/figures/``)
-------------------------------------
figS2_demand_market_layer_v5_20260919.png
figS3_baseyear_calibration_feasibility_v5_20260919.png
figS4_c1_cost_constraint_detail_v5_20260919.png
figS5_m2_swap_group_drivers_v5_20260919.png
figS6_af_storage_binding_v5_20260919.png

FIGURE CAPTIONS (manuscript SI; this docstring is the single source of truth)
-----------------------------------------------------------------------------
Fig. S2 | Demand pathways and the market-node layer. (a) National cement
demand under the high, central and low pathways (annual series, 2025–2060)
against observed national cement production, 1980–2025 (2,492.1 Mt peak in
2014; 1,825.0 Mt in 2024 and 1,693.0 Mt in 2025). Observed production is the
model's base-year anchor and replaces the projections as demand through 2025,
so all three pathways start from the same 2025 value. Cumulative 2025–2060
demand on the model's trapezoidal period weights (2.5 yr endpoints, 5 yr
interior nodes) is 48.35, 39.31 and 34.42 Gt, respectively. (b) The 149
demand-market nodes; marker area is proportional to each node's national
demand-proxy share. The 1,572-plant fleet connects to the nodes through the
20,188-arc candidate set. Boundary: Tianditu basemap (review-grade depiction
subject to the competent map-review authority); South China Sea shown in the
inset with the discontinuous line.

Fig. S3 | Base-year calibration and market-layer verification. (a) Provincial
base-year calibration gap (provincial clinker demand minus aggregate design
capacity at the truncated utilisation ceiling, kt): only Zhejiang (-1,044.6),
Jiangsu (-596.8) and Tianjin (-104.2) required truncation at u = 1; all other
provinces close exactly. (b) Hall feasibility certificate for the frozen
20,188-arc set under the central demand pathway: per-period node demand
against available plant supply; the minimum-gap transportation LP closes with
0.0000 kt undelivered in every period (tolerance 2.0 kt). (c) Economic
screening of the arc set: per-period delivered transport cost of the incumbent
production pattern on the frozen 20,188-arc set versus a densified 41,020-arc
set (per plant, 20 nearest nodes + nodes within 400 km + same-province nodes).
The undiscounted eight-period delivered-cost difference is 1.108 bn CNY,
0.503% of the frozen-set total (220.5 bn CNY).

Fig. S4 | Central-pathway cost structure and constraint margins (S1).
(a) Discounted system cost partitioned into the four accounting calibers:
mitigation-measure expenditure (583.2 bn CNY), capacity turnover (634.5),
market logistics (506.9) and dispatch efficiency (-9.3); the diamond marks
the reported total (1,715.4 bn CNY), and the caliber decomposition closes to
it exactly (|closure| < 10⁻³ kCNY). (b) Component-level discounted costs
grouped by caliber; components with zero value (fuel term, EOR revenue
credit, milestone slack penalty) are omitted. (c) Carbon-constraint margins:
the cumulative budget binds exactly (actual = target = 12,214,879 kt·yr),
while the 2060 endpoint cap stays slack by 46.6 Mt. (d) Annualised
operating-capacity decline per five-year interval; the shaded band is the
observed 2016–2020 policy reference range of 5–10% per year, shown for
context only — the model is not constrained to it. The 2025→2030 interval
averages 13.0% per year.

Fig. S5 | What does and does not distinguish the 2060 swap groups
(statistical companion to main-text Fig. 4c, d). (a) Empirical cumulative
distributions of the 2060 AF accessibility ratio κAᵢ/Hᵢ under real (S1)
resource conditions for the S1-only lines (blue, n = 40) and S4-only lines
(orange, n = 35); two S1-only lines (584, 778) have no whitelisted sink
within 500 km and are excluded from all storage metrics. Vertical references:
the 0.60 technical-substitution ceiling and full-heat coverage (ratio = 1).
Medians: 0.514 (S1-only) versus 0.437 (S4-only); 68% versus 91% of lines sit
below the 0.60 ceiling. (b) Joint distribution of the accessibility ratio and
the nearest whitelisted sink distance (model-proxy haversine on the candidate
arc whitelist). Median nearest-sink distances are 119.0 and 123.9 km; the
median equalisation gain in κAᵢ/Hᵢ (equalised minus real conditions) is
+0.179 for S1-only and +0.258 for S4-only lines. Panel a is the distributional counterpart of the per-line view in
main-text Fig. 4d, and panel b is the storage-access control behind the
statement that the two groups differ on the AF margin but not on sink
distance.

Fig. S6 | AF deployment limits and storage-rate binding (S1). (a) National AF
heat substitution against the national expansion ceiling (initial 5% of 2025
heat demand, plus 10% of contemporaneous national heat demand per period, in
cumulative terms). The ceiling binds exactly through 2035 and stays slack
thereafter; the realised AF rate reaches 44.9% in 2060. (b) Per-period
composition of operating lines by binding AF layer (supply within 0.1% of the
layer cap): accessibility allocation κAᵢ (blue), technical ceiling 0.60·Hᵢ
(orange), or neither (grey). The shaded periods (2030, 2035) are where the
national expansion ceiling binds. (c) Used (sink, period) pairs partitioned
into rate-binding (annual injection within 0.1% of the effective DSA or EOR
rate capacity) and slack: 499 of 834 used pairs (59.8%) bind across the
horizon.

Verification anchors asserted in this script
--------------------------------------------
Fig. S2: 2060 demand 1110.0/928.0/708.74 Mt; 2025 = 1693.0 Mt in all
pathways; trapezoidal cumulative 48.35/39.31/34.42 Gt (±0.01); 149 nodes;
20,188 arcs; observed 1980-2025 reproduced from the raw demand workbook
(1980 = 79.86, 2014 peak = 2492.07, 2020 = 2394.71, 2025 = 1693.0 Mt; the
2022-2025 model anchors equal the raw series exactly).
Fig. S3: max |province gap| = 1044.6 kt (Zhejiang); truncated provinces =
{Zhejiang, Jiangsu, Tianjin}; Hall log certificate PASS with worst gap
0.0000 kt; screening log dense set = 41,020 arcs, total gap 0.503%.
Fig. S4: calibers 583.2326/634.4890/506.9063/-9.2592 bn (±0.001);
|closure| < 1e-3 kCNY; cumulative budget actual == target (±0.01 kt·yr);
2060 endpoint slack 46,624.6 kt (±1); 2025→2030 annualised decline 12.97%
(±0.05 pp).
Fig. S5: group sizes 42/35, eligible 40/35 with excluded ids [584, 778];
κA/H medians 0.514/0.437; equalisation-gain medians +0.179/+0.258; nearest
-sink medians 119.0/123.9 km; sub-0.60 shares 0.675/0.914.
Fig. S6: AF rate 2025 = 5.0%, 2060 = 44.9% (±0.1 pp); expansion ceiling
binding 2025–2035 (|supply - ceiling| < 1 kt), slack > 100 kt from 2040;
binding-layer shares recomputed from the frozen S1 export (values embedded,
±0.5 pp); storage rate-binding pairs 499/834.

Note on the AF binding structure: the 2026-09-14 pre-final review quotes
mid-period accessibility binding of 47.5–74.0% and 2060 technical binding of
55.7%. The panel-b values here are recomputed line-by-line from the frozen S1
export (per-plant supply vs the replicated κAᵢ and 0.60·Hᵢ caps, 0.1%
tolerance) and differ from those quoted numbers; the recomputed series is the
one asserted and plotted.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "scripts" / "v4" / "figure_system_2026_common.py").exists():
            return candidate
    raise RuntimeError("repository root not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "scripts" / "v4"))
from figure_system_2026_common import (  # noqa: E402
    COLORS,
    DEMAND_COLORS,
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
    SOUTH_BUFFER,
    _add_south_china_sea_inset,
    _inside_scs_data,
    _legend_frame,
    _load_basemap,
    _project,
    _scs_boundary_layer,
)

RESULTS = ROOT / "v5" / "results" / "formal_v1_20260914"
C1_DIR = RESULTS / "C1_central_J" / "S1_baseline"
C1_JSON = RESULTS / "C1_central_J" / "S1_baseline_results.json"
C4_JSON = RESULTS / "C4_equalized_J" / "S3_all_spatial_equalized_results.json"
DEMAND_XLSX = ROOT / "v5" / "data" / "model_input" / "demand" / "cement_demand_scenarios_v4.xlsx"
RAW_DEMAND_XLSX = ROOT / "data" / "raw" / "demand" / "cement_demand_analysis.xlsx"
NODES_CSV = ROOT / "v5" / "data" / "demand_market_nodes.csv"
ARCS_CSV = ROOT / "v5" / "data" / "demand_market_arcs.csv"
M2_CSV = ROOT / "tmp" / "m2_analysis_20260918" / "m2_plant_metrics.csv"
HALL_LOG = ROOT / "tmp" / "figS_20260919" / "check_arc_feasibility_d_medium.log"
SCREEN_LOG = ROOT / "tmp" / "figS_20260919" / "screen_arc_economics.log"
OUTDIR = ROOT / "paper" / "RCR" / "figures"

YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
MM = 1 / 25.4
FIG_W = 155 * MM

C1_COLOR = COLORS["blue"]
# Display names follow the S-numbering of the scenarios.
GROUP_LABEL = {"C1-only": "S1-only", "C4-only": "S4-only"}
C4_COLOR = COLORS["orange"]
CALIBER_COLORS = {
    "measures": COLORS["blue"],
    "turnover": COLORS["teal"],
    "logistics": COLORS["gold"],
    "dispatch": COLORS["grey"],
}


def load_c1() -> dict:
    return json.loads(C1_JSON.read_text(encoding="utf-8"))


def save(fig, name: str) -> Path:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / name
    fig.savefig(path, dpi=600, facecolor="white")
    plt.close(fig)
    print(path)
    return path


# ---------------------------------------------------------------------------
# Fig. S2: demand pathways and the market-node layer
# ---------------------------------------------------------------------------

def demand_scenarios() -> pd.DataFrame:
    df = pd.read_excel(DEMAND_XLSX, sheet_name="demand_scenarios")
    sub = df.set_index("year")
    assert abs(sub.loc[2060, "d_high_mt"] - 1110.0) < 0.01
    assert abs(sub.loc[2060, "d_medium_mt"] - 928.0) < 0.01
    assert abs(sub.loc[2060, "d_low_mt"] - 708.74) < 0.01
    for col in ("d_high_mt", "d_medium_mt", "d_low_mt"):
        assert abs(sub.loc[2025, col] - 1693.0) < 0.01
    weights = pd.Series(5.0, index=YEARS)
    weights.iloc[0] = weights.iloc[-1] = 2.5
    cumulative = {
        "high": (sub.loc[YEARS, "d_high_mt"] * weights).sum() / 1000.0,
        "central": (sub.loc[YEARS, "d_medium_mt"] * weights).sum() / 1000.0,
        "low": (sub.loc[YEARS, "d_low_mt"] * weights).sum() / 1000.0,
    }
    assert abs(cumulative["high"] - 48.35) < 0.01, cumulative
    assert abs(cumulative["central"] - 39.31) < 0.01, cumulative
    assert abs(cumulative["low"] - 34.42) < 0.01, cumulative
    return df


def historical_production() -> pd.Series:
    """Observed national cement production, 1980-2025 (Mt).

    The upstream workbook keeps the observed series in two places: annual
    production to 2023 in ``historical_cement_prod`` and the 2024-2025 values
    appended to the ``Historical production`` column of ``model_output``.
    Production through 2025 is the model's base-year anchor and replaces the
    projections as demand through that year.
    """
    history = pd.read_excel(RAW_DEMAND_XLSX, sheet_name="historical_cement_prod")
    series = history.set_index("Year")["Historical cement production"]
    model_output = pd.read_excel(RAW_DEMAND_XLSX, sheet_name="model_output")
    recent = model_output.set_index("Year")["Historical production"].dropna()
    series = pd.concat([
        series.astype(float),
        pd.Series(recent.to_numpy(dtype=float), index=[int(year) for year in recent.index]),
    ]).sort_index()
    series = series.loc[1980:2025].astype(float)
    assert list(series.index) == list(range(1980, 2026)), series.index.to_list()
    # Peak-and-decline shape of the observed series (NBS cement output, Mt).
    assert abs(series.loc[1980] - 79.86) < 0.01 and abs(series.loc[2014] - 2492.07) < 0.01
    assert abs(series.loc[2020] - 2394.71) < 0.01 and abs(series.loc[2025] - 1693.0) < 0.01
    assert series.idxmax() == 2014, series.idxmax()
    return series


def observed_production(df: pd.DataFrame) -> pd.Series:
    """Audit the modelled observed anchors against the raw demand workbook.

    The 2022-2023 values must reproduce the ``historical_cement_prod`` sheet of
    ``data/raw/demand/cement_demand_analysis.xlsx`` (official production in Mt)
    and the 2024-2025 values the ``Historical production`` column of its
    ``model_output`` sheet, i.e. the raw workbook does carry history through
    2025 rather than stopping at 2023.
    """
    raw = pd.read_excel(RAW_DEMAND_XLSX, sheet_name="model_output")
    real = raw.set_index("Year")["Real historical"].dropna() / 1e6  # t -> Mt
    history = historical_production()

    observed = df.dropna(subset=["actual_cement_mt"]).set_index("year")["actual_cement_mt"]
    assert list(observed.index) == [2022, 2023, 2024, 2025], observed.index.to_list()
    assert {2022, 2023} <= set(real.index.astype(int))
    for year, value in observed.items():
        assert abs(history.loc[int(year)] - value) < 0.01, (year, value, history.loc[int(year)])
        if float(year) in real.index:
            assert abs(real.loc[float(year)] - value) < 0.01, (year, value, real.loc[float(year)])
    return history


def make_figS2() -> Path:
    demand = demand_scenarios()
    nodes = pd.read_csv(NODES_CSV)
    arcs = pd.read_csv(ARCS_CSV)
    assert len(nodes) == 149 and len(arcs) == 20188
    assert abs(nodes["pop_share_national"].sum() - 1.0) < 0.01

    china, scs = _load_basemap()
    _scs_boundary_layer()

    # Panel a carries a 46-year observed series plus three 36-year pathways, so
    # it is given more width than the map facet beside it.
    fig = plt.figure(figsize=(FIG_W, 72 * MM))
    grid = fig.add_gridspec(
        1, 2, width_ratios=[1.35, 1.00],
        left=0.085, right=0.985, top=0.93, bottom=0.13, wspace=0.10,
    )
    ax_lines = fig.add_subplot(grid[0, 0])
    ax_map = fig.add_subplot(grid[0, 1])

    history = observed_production(demand)
    ax_lines.plot(
        history.index, history.to_numpy(), color=COLORS["ink"], lw=1.2,
    )
    # Pathways start at the 2025 base-year anchor, where the observed series ends.
    projection = demand[demand["year"] >= 2025]
    for col, key in (("d_high_mt", "high"), ("d_medium_mt", "central"), ("d_low_mt", "low")):
        ax_lines.plot(
            projection["year"], projection[col], color=DEMAND_COLORS[key], lw=1.3,
        )
    ax_lines.set_xlim(1980, 2060)
    ax_lines.set_ylim(0, 2750)
    ax_lines.set_yticks([0, 1000, 2000])
    ax_lines.set_xticks([1980, 2000, 2020, 2040, 2060])
    ax_lines.set_ylabel("Cement demand (Mt yr⁻¹)", fontsize=FS_LABEL)
    ax_lines.yaxis.label.set_fontfamily("Helvetica")
    quiet_grid(ax_lines)
    despine(ax_lines)
    panel_label(ax_lines, "a")
    legend = ax_lines.legend(
        handles=[
            Line2D([], [], color=COLORS["ink"], lw=1.2, label="Observed"),
            Line2D([], [], color=DEMAND_COLORS["high"], lw=1.3, label="High"),
            Line2D([], [], color=DEMAND_COLORS["central"], lw=1.3, label="Central"),
            Line2D([], [], color=DEMAND_COLORS["low"], lw=1.3, label="Low"),
        ],
        loc="upper right", fontsize=FS_LEGEND, handletextpad=0.4,
        borderaxespad=0.15, labelspacing=0.35,
    )
    _legend_frame(legend)

    china.plot(ax=ax_map, color="#FBFBFB", edgecolor="#333333", linewidth=0.30, zorder=0)
    minx, miny, maxx, maxy = china.total_bounds
    miny = miny - SOUTH_BUFFER * (maxy - miny)
    points = _project(nodes["lon"], nodes["lat"])
    sizes = 3000.0 * nodes["pop_share_national"].clip(lower=0.0004)
    ax_map.scatter(
        points.x, points.y, s=sizes, c=C1_COLOR, alpha=0.55,
        edgecolor="white", linewidth=0.25, zorder=2,
    )
    ax_map.set_xlim(minx, maxx)
    ax_map.set_ylim(miny, maxy)
    ax_map.set_aspect("equal", adjustable="box", anchor="C")
    ax_map.set_xticks([])
    ax_map.set_yticks([])
    for spine in ax_map.spines.values():
        spine.set_visible(False)
    panel_label(ax_map, "b")

    inset = _add_south_china_sea_inset(ax_map, scs, rect=(0.755, 0.015, 0.235, 0.27))
    mask = _inside_scs_data(nodes["lon"], nodes["lat"])
    if mask.any():
        inset.scatter(
            points.x[mask], points.y[mask], s=sizes[mask] * 0.5,
            c=C1_COLOR, alpha=0.55, edgecolor="white", linewidth=0.15, zorder=2,
        )

    size_handles = [
        Line2D([], [], marker="o", ls="", mfc=C1_COLOR, mec="white",
               alpha=0.6, ms=np.sqrt(3000 * v), label=f"{100 * v:g}%")
        for v in (0.002, 0.01, 0.02)
    ]
    # Two-line title and single-line spacing keep the box inside the reserved
    # southern buffer instead of reaching into the Yunnan/Guangxi coastline.
    size_legend = ax_map.legend(
        handles=size_handles, loc="lower left", bbox_to_anchor=(0.0, 0.0),
        fontsize=FS_NOTE, handletextpad=0.5, borderaxespad=0.15, labelspacing=0.45,
        title="National\ndemand share", title_fontsize=FS_NOTE,
    )
    _legend_frame(size_legend)

    return save(fig, "figS2_demand_market_layer_v5_20260919.png")


# ---------------------------------------------------------------------------
# Fig. S3: base-year calibration and market-layer verification
# ---------------------------------------------------------------------------

PROVINCE_EN = {
    "北京": "Beijing", "天津": "Tianjin", "河北": "Hebei", "山西": "Shanxi",
    "内蒙古": "Inner Mongolia", "辽宁": "Liaoning", "吉林": "Jilin",
    "黑龙江": "Heilongjiang", "上海": "Shanghai", "江苏": "Jiangsu",
    "浙江": "Zhejiang", "安徽": "Anhui", "福建": "Fujian", "江西": "Jiangxi",
    "山东": "Shandong", "河南": "Henan", "湖北": "Hubei", "湖南": "Hunan",
    "广东": "Guangdong", "广西": "Guangxi", "海南": "Hainan", "重庆": "Chongqing",
    "四川": "Sichuan", "贵州": "Guizhou", "云南": "Yunnan", "西藏": "Tibet",
    "陕西": "Shaanxi", "甘肃": "Gansu", "青海": "Qinghai", "宁夏": "Ningxia",
    "新疆": "Xinjiang",
}


def parse_hall_log() -> pd.DataFrame:
    text = HALL_LOG.read_text(encoding="utf-8", errors="replace")
    assert "certificate PASS" in text, "Hall certificate not PASS"
    rows = []
    pattern = re.compile(
        r"^\s+(20\d\d)\s+([\d,]+\.\d)\s+([\d,]+\.\d)\s+(-?[\d.]+)\s*$", re.M
    )
    for year, demand, supply, gap in pattern.findall(text):
        rows.append({
            "year": int(year),
            "demand_kt": float(demand.replace(",", "")),
            "supply_kt": float(supply.replace(",", "")),
            "gap_kt": float(gap),
        })
    frame = pd.DataFrame(rows).set_index("year")
    assert list(frame.index) == YEARS, frame.index
    assert frame["gap_kt"].abs().max() < 0.001, frame["gap_kt"]
    return frame


def parse_screen_log() -> pd.DataFrame:
    text = SCREEN_LOG.read_text(encoding="utf-8", errors="replace")
    assert "dense arcs 41,020" in text
    assert "frozen arcs 20,188" in text
    rows = []
    pattern = re.compile(
        r"^\s+(20\d\d)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)%", re.M
    )
    for year, frozen, dense, diff, pct in pattern.findall(text):
        rows.append({
            "year": int(year), "frozen_bn": float(frozen),
            "dense_bn": float(dense), "diff_bn": float(diff),
            "diff_pct": float(pct),
        })
    frame = pd.DataFrame(rows).set_index("year")
    assert list(frame.index) == YEARS
    total_pct = 100.0 * frame["diff_bn"].sum() / frame["frozen_bn"].sum()
    assert abs(total_pct - 0.503) < 0.01, total_pct
    return frame


def make_figS3(c1: dict) -> Path:
    calib = c1["baseyear_calibration"]
    assert abs(calib["max_abs_province_gap_kt"] - 1044.6) < 0.1
    truncated = set(calib["provinces_truncated"])
    assert truncated == {"浙江", "江苏", "天津"}, truncated
    gaps = pd.Series(calib["province_gap_kt"]).rename(index=PROVINCE_EN)
    assert len(gaps) == 30  # Shanghai uses the clinker-ratio fallback, no gap entry
    rest = gaps.drop(index=[PROVINCE_EN[p] for p in truncated])
    assert rest.abs().max() < 1e-6  # all other provinces close exactly
    shown = gaps.loc[["Zhejiang", "Jiangsu", "Tianjin"]]
    bar_labels = ["Zhejiang", "Jiangsu", "Tianjin",
                  "Other 27 provinces\n(gap = 0)"]
    bar_values = list(shown / 1000.0) + [0.0]

    hall = parse_hall_log()
    screen = parse_screen_log()

    fig = plt.figure(figsize=(FIG_W, 62 * MM))
    grid = fig.add_gridspec(
        1, 3, width_ratios=[1.05, 1.0, 1.0],
        left=0.135, right=0.985, top=0.90, bottom=0.17, wspace=0.42,
    )
    ax_gap = fig.add_subplot(grid[0, 0])
    ax_hall = fig.add_subplot(grid[0, 1])
    ax_screen = fig.add_subplot(grid[0, 2])

    ypos = np.arange(4)
    colors = [C4_COLOR] * 3 + [COLORS["grey_light"]]
    ax_gap.barh(ypos, bar_values, color=colors, height=0.62, lw=0)
    for y, v in zip(ypos, bar_values):
        if v != 0.0:
            ax_gap.text(v - 0.03, y, f"{v:.2f}", ha="right", va="center",
                        fontsize=FS_NOTE, color=C4_COLOR)
    ax_gap.set_yticks(ypos, bar_labels, fontsize=FS_NOTE)
    ax_gap.set_xlim(-1.5, 0.1)
    ax_gap.set_xticks([-1.0, -0.5, 0.0])
    ax_gap.set_xlabel("Provincial calibration gap (Mt clinker)", fontsize=FS_LABEL)
    ax_gap.axvline(0, color=COLORS["ink"], lw=0.7)
    quiet_grid(ax_gap, "x")
    despine(ax_gap)
    panel_label(ax_gap, "a")
    ax_gap.set_title("Base-year truncation", pad=3)

    ax_hall.plot(YEARS, hall["supply_kt"] / 1000.0, color=COLORS["grey"],
                 marker="s", ms=2.6, lw=1.1, label="Available supply")
    ax_hall.plot(YEARS, hall["demand_kt"] / 1000.0, color=C1_COLOR,
                 marker="o", ms=2.6, lw=1.1, label="Node demand")
    ax_hall.set_xlim(2023.5, 2061.5)
    ax_hall.set_xticks([2030, 2045, 2060])
    ax_hall.set_ylim(0, 2000)
    ax_hall.set_yticks([0, 1000, 2000])
    ax_hall.set_ylabel("Clinker (Mt yr⁻¹)", fontsize=FS_LABEL)
    ax_hall.yaxis.label.set_fontfamily("Helvetica")
    quiet_grid(ax_hall)
    despine(ax_hall)
    panel_label(ax_hall, "b")
    ax_hall.set_title("Hall certificate (gap = 0)", pad=3)
    legend = ax_hall.legend(loc="lower right", fontsize=FS_NOTE, handletextpad=0.4,
                            borderaxespad=0.15, labelspacing=0.35)
    _legend_frame(legend)

    x = np.arange(len(YEARS))
    width = 0.38
    ax_screen.bar(x - width / 2, screen["frozen_bn"], width=width,
                  color=C1_COLOR, lw=0, label="Frozen (20,188 arcs)")
    ax_screen.bar(x + width / 2, screen["dense_bn"], width=width,
                  color=COLORS["gold"], lw=0, label="Densified (41,020 arcs)")
    ax_screen.set_xticks(x, [str(y) for y in YEARS], rotation=45,
                         ha="right", rotation_mode="anchor", fontsize=FS_NOTE)
    ax_screen.set_ylim(0, 82)
    ax_screen.set_yticks([0, 20, 40, 60])
    ax_screen.set_ylabel("Delivered transport cost\n(bn CNY, undiscounted)",
                         fontsize=FS_LABEL)
    quiet_grid(ax_screen)
    despine(ax_screen)
    panel_label(ax_screen, "c")
    ax_screen.set_title("Arc-set screening", pad=3)
    legend = ax_screen.legend(loc="upper right", fontsize=FS_NOTE,
                              borderaxespad=0.15, labelspacing=0.35)
    _legend_frame(legend)

    return save(fig, "figS3_baseyear_calibration_feasibility_v5_20260919.png")


# ---------------------------------------------------------------------------
# Fig. S4: C1 cost calibers, constraint margins and exit pace
# ---------------------------------------------------------------------------

CALIBER_OF_COMPONENT = {
    "ccs_capex": "measures", "ccs_opex": "measures", "transport": "measures",
    "dsa_storage": "measures", "eor_storage": "measures",
    "eor_revenue_credit": "measures", "early_retirement": "measures",
    "af_capex": "measures", "af_opex": "measures",
    "capacity_retention": "turnover", "same_site_renewal_capex": "turnover",
    "clinker_transport": "logistics",
    "dispatch_fuel": "dispatch", "fuel": "dispatch",
    "milestone_slack_penalty": "other",
}

COMPONENT_LABELS = {
    "capacity_retention": "Capacity retention",
    "clinker_transport": "Clinker delivery",
    "ccs_opex": "Capture O&M",
    "ccs_capex": "Capture capex",
    "same_site_renewal_capex": "Same-site renewal",
    "transport": "CO₂ transport",
    "dsa_storage": "DSA storage",
    "af_capex": "AF capex",
    "af_opex": "AF O&M",
    "early_retirement": "Early retirement",
    "dispatch_fuel": "Dispatch fuel (net)",
    "eor_storage": "EOR storage",
}


def make_figS4(c1: dict) -> Path:
    calibers = c1["cost_calibers"]
    measures = calibers["measure_expenditure_kCNY"] / 1e6
    turnover = calibers["capacity_turnover_cost_kCNY"] / 1e6
    logistics = calibers["market_logistics_cost_kCNY"] / 1e6
    dispatch = calibers["dispatch_efficiency_kCNY"] / 1e6
    total = calibers["model_cost_kCNY"] / 1e6
    assert abs(measures - 583.2326) < 0.001, measures
    assert abs(turnover - 634.4890) < 0.001, turnover
    assert abs(logistics - 506.9063) < 0.001, logistics
    assert abs(dispatch - (-9.2592)) < 0.001, dispatch
    assert abs(calibers["closure_check_kCNY"]) < 1e-3
    assert abs(measures + turnover + logistics + dispatch - total) < 1e-3

    components = {
        key: value / 1e6
        for key, value in c1["cost_breakdown_total"]["components_discounted_kCNY"].items()
    }
    shown = {k: v for k, v in components.items() if abs(v) > 1e-6}
    assert len(components) - len(shown) == 3  # fuel, eor credit, slack penalty
    group_sums = {"measures": 0.0, "turnover": 0.0, "logistics": 0.0,
                  "dispatch": 0.0}
    for key, value in components.items():
        group = CALIBER_OF_COMPONENT[key]
        if group in group_sums:
            group_sums[group] += value
    assert abs(group_sums["measures"] - measures) < 1e-6
    assert abs(group_sums["turnover"] - turnover) < 1e-6
    assert abs(group_sums["logistics"] - logistics) < 1e-6
    assert abs(group_sums["dispatch"] - dispatch) < 1e-6

    headroom = c1["constraint_headroom"]
    budget_target = headroom["cumulative_budget_target_kt_year"] / 1e6  # Gt·yr
    budget_actual = headroom["cumulative_budget_actual_kt_year"] / 1e6
    assert abs(budget_actual - budget_target) < 1e-8
    assert abs(budget_target - 12.214879489924198) < 1e-6
    terminal_cap = headroom["terminal_2060_cap_kt"] / 1000.0  # Mt
    terminal_actual = headroom["terminal_2060_actual_kt"] / 1000.0
    terminal_slack = headroom["terminal_2060_headroom_kt"] / 1000.0
    assert abs(terminal_slack - 46.6246) < 0.001, terminal_slack

    decline = c1["capacity_decline_diagnostic"]
    band = decline["reference_annual_band"]
    assert band == [0.05, 0.1]
    intervals = list(decline["per_interval"].keys())
    rates = np.array([
        decline["per_interval"][key]["annualised_decline_rate"] for key in intervals
    ])
    assert abs(rates[0] - 0.1297) < 0.0005, rates[0]
    assert len(intervals) == 7

    fig = plt.figure(figsize=(FIG_W, 108 * MM))
    # Panel b carries the longest tick labels of the figure ("Same-site
    # renewal", 18.1 mm); the gutter is sized from that width so the labels no
    # longer reach into panel a, and panel a keeps enough width for its five
    # category labels to stay separated.
    grid = fig.add_gridspec(
        2, 2, height_ratios=[1.05, 0.85], width_ratios=[0.686, 1.00],
        left=0.075, right=0.975, top=0.95, bottom=0.10,
        hspace=0.52, wspace=0.364,
    )
    ax_cal = fig.add_subplot(grid[0, 0])
    ax_comp = fig.add_subplot(grid[0, 1])
    ax_head = fig.add_subplot(grid[1, 0])
    ax_exit = fig.add_subplot(grid[1, 1])

    names = ["Mitigation", "Turnover", "Logistics", "Dispatch", "Total"]
    values = [measures, turnover, logistics, dispatch]
    colors = [CALIBER_COLORS[k] for k in ("measures", "turnover", "logistics", "dispatch")]
    cumulative = 0.0
    for index, (value, color) in enumerate(zip(values, colors)):
        bottom = min(cumulative, cumulative + value)
        ax_cal.bar(index, abs(value), bottom=bottom, width=0.62, color=color,
                   edgecolor="white", lw=0.4, zorder=2)
        ax_cal.text(index, bottom + abs(value) + 16 if value >= 0 else bottom - 16,
                    f"{value:+,.0f}", ha="center",
                    va="bottom" if value >= 0 else "top", fontsize=FS_NOTE)
        cumulative += value
        ax_cal.plot([index + 0.31, index + 0.69], [cumulative, cumulative],
                    color=COLORS["grey"], lw=0.65, ls=":", zorder=1)
    assert abs(cumulative - total) < 1e-6
    ax_cal.bar(4, total, width=0.62, color=COLORS["ink"], edgecolor="white",
               lw=0.4, zorder=2)
    ax_cal.text(4, total + 16, f"{total:,.0f}", ha="center", va="bottom",
                fontsize=FS_NOTE)
    ax_cal.axhline(0, color=COLORS["ink"], lw=0.7)
    ax_cal.set_xticks(range(5), names, fontsize=FS_NOTE)
    ax_cal.set_xlim(-0.45, 4.45)
    ax_cal.set_ylim(0, 2050)
    ax_cal.set_yticks([0, 1000, 2000])
    ax_cal.set_ylabel("Discounted cost (bn CNY)")
    quiet_grid(ax_cal)
    despine(ax_cal)
    panel_label(ax_cal, "a")
    ax_cal.set_title("Four accounting calibers", pad=3)

    ordered = sorted(shown.items(), key=lambda kv: kv[1])
    labels = [COMPONENT_LABELS[k] for k, _ in ordered]
    vals = np.array([v for _, v in ordered])
    cols = [CALIBER_COLORS[CALIBER_OF_COMPONENT[k]] for k, _ in ordered]
    ypos = np.arange(len(ordered))
    ax_comp.barh(ypos, vals, color=cols, height=0.68, lw=0)
    ax_comp.set_yticks(ypos, labels, fontsize=FS_NOTE)
    for tick in ax_comp.get_yticklabels():
        fallback_font(tick)
    ax_comp.axvline(0, color=COLORS["ink"], lw=0.7)
    ax_comp.set_xlim(-40, 700)
    ax_comp.set_xticks([0, 300, 600])
    ax_comp.set_xlabel("Discounted cost (bn CNY)")
    quiet_grid(ax_comp, "x")
    despine(ax_comp)
    panel_label(ax_comp, "b")
    ax_comp.set_title("Component detail (non-zero)", pad=3)

    xpos = np.arange(2)
    share_of_limit = [100.0 * budget_actual / budget_target,
                      100.0 * terminal_actual / terminal_cap]
    xpos = np.arange(2)
    ax_head.bar(xpos, share_of_limit, width=0.52,
                color=[C1_COLOR, COLORS["gold"]], edgecolor="white", lw=0.4)
    for xi, v in zip(xpos, share_of_limit):
        ax_head.text(xi, v + 2.5, f"{v:.1f}", ha="center", va="bottom",
                     fontsize=FS_NOTE)
    ax_head.axhline(100, color=COLORS["ink"], lw=0.7, ls=(0, (4, 3)))
    ax_head.set_xticks(xpos, ["Cumulative budget\n2025–2060",
                              "2060 endpoint cap"], fontsize=FS_NOTE)
    ax_head.set_ylim(0, 118)
    ax_head.set_yticks([0, 50, 100])
    ax_head.set_ylabel("Realised as share of limit (%)", fontsize=FS_LABEL)
    quiet_grid(ax_head)
    despine(ax_head)
    panel_label(ax_head, "c")
    ax_head.set_title("Carbon-constraint margins", pad=3)

    mid_years = [2027.5 + 5 * i for i in range(7)]
    ax_exit.axhspan(100 * band[0], 100 * band[1], color=COLORS["grey_light"],
                    alpha=0.7, lw=0, zorder=0)
    ax_exit.plot(mid_years, 100 * rates, color=C1_COLOR, marker="o", ms=3.0,
                 lw=1.2, zorder=3)
    ax_exit.axhline(0, color=COLORS["ink"], lw=0.6)
    ax_exit.set_xlim(2025, 2060)
    ax_exit.set_xticks([2030, 2045, 2060])
    ax_exit.set_ylim(0, 15)
    ax_exit.set_yticks([0, 5, 10, 15])
    ax_exit.set_ylabel("Annualised capacity decline (% yr⁻¹)", fontsize=FS_LABEL)
    ax_exit.yaxis.label.set_fontfamily("Helvetica")
    quiet_grid(ax_exit)
    despine(ax_exit)
    panel_label(ax_exit, "d")
    ax_exit.set_title("Exit pace vs 2016–2020 band", pad=3)

    return save(fig, "figS4_c1_cost_constraint_detail_v5_20260919.png")


# ---------------------------------------------------------------------------
# Fig. S5: M2 swap-group joint distribution
# ---------------------------------------------------------------------------

def m2_metrics() -> pd.DataFrame:
    frame = pd.read_csv(M2_CSV)
    sizes = frame.groupby("group").size().to_dict()
    assert sizes == {"C1-only": 42, "C4-only": 35}, sizes
    eligible = frame[frame["n_conn"] > 0]
    n_eligible = eligible.groupby("group").size().to_dict()
    assert n_eligible == {"C1-only": 40, "C4-only": 35}
    excluded = frame.loc[frame["n_conn"] == 0, "plant_id"].tolist()
    assert sorted(excluded) == [584, 778]
    med = eligible.groupby("group")["kA_over_H_C1cond_2060"].median()
    assert abs(med["C1-only"] - 0.514) < 0.002, med
    assert abs(med["C4-only"] - 0.437) < 0.002, med
    gain = (
        eligible.set_index("plant_id")["kA_over_H_C4cond_2060"]
        - eligible.set_index("plant_id")["kA_over_H_C1cond_2060"]
    )
    gain_med = gain.groupby(eligible.set_index("plant_id")["group"]).median()
    assert abs(gain_med["C1-only"] - 0.179) < 0.005, gain_med
    assert abs(gain_med["C4-only"] - 0.258) < 0.005, gain_med
    dist = eligible.groupby("group")["nearest_km"].median()
    assert abs(dist["C1-only"] - 119.0) < 0.2, dist
    assert abs(dist["C4-only"] - 123.9) < 0.2, dist
    below = eligible.groupby("group")["kA_over_H_C1cond_2060"].apply(
        lambda s: (s < 0.60).mean()
    )
    assert abs(below["C1-only"] - 0.675) < 0.01, below
    assert abs(below["C4-only"] - 0.914) < 0.01, below
    return frame


def make_figS5() -> Path:
    frame = m2_metrics()
    groups = {
        "C1-only": frame[(frame["group"] == "C1-only") & (frame["n_conn"] > 0)],
        "C4-only": frame[(frame["group"] == "C4-only") & (frame["n_conn"] > 0)],
    }

    fig = plt.figure(figsize=(FIG_W, 64 * MM))
    grid = fig.add_gridspec(
        1, 2, left=0.085, right=0.975, top=0.90, bottom=0.16, wspace=0.30,
    )
    ax_ecdf = fig.add_subplot(grid[0, 0])
    ax_scatter = fig.add_subplot(grid[0, 1])

    for name, color, marker in (("C1-only", C1_COLOR, "s"), ("C4-only", C4_COLOR, "o")):
        display = GROUP_LABEL[name]
        values = np.sort(groups[name]["kA_over_H_C1cond_2060"].to_numpy())
        ecdf = np.arange(1, len(values) + 1) / len(values)
        ax_ecdf.step(np.concatenate([[0.0], values]),
                     np.concatenate([[0.0], ecdf]),
                     where="post", color=color, lw=1.3,
                     label=f"{display} (n={len(values)})")
    for xref, ls in ((0.60, (0, (4, 3))), (1.0, (0, (1, 1.5)))):
        ax_ecdf.axvline(xref, color=COLORS["grey"], lw=0.7, ls=ls, zorder=1)
    ax_ecdf.set_xlim(0, 2.1)
    ax_ecdf.set_ylim(0, 1.02)
    ax_ecdf.set_xticks([0, 0.6, 1.0, 1.5, 2.0])
    ax_ecdf.set_xticklabels(["0", "0.6", "1", "1.5", "2"])
    ax_ecdf.set_xlabel("AF accessibility ratio κA/H, S1 conditions, 2060")
    ax_ecdf.set_ylabel("Share of lines")
    quiet_grid(ax_ecdf, "both")
    despine(ax_ecdf)
    panel_label(ax_ecdf, "a")
    legend = ax_ecdf.legend(loc="lower right", fontsize=FS_LEGEND,
                            handletextpad=0.4, borderaxespad=0.2,
                            labelspacing=0.4)
    _legend_frame(legend)

    for name, color, marker in (("C1-only", C1_COLOR, "s"), ("C4-only", C4_COLOR, "o")):
        display = GROUP_LABEL[name]
        sub = groups[name]
        ax_scatter.scatter(
            sub["kA_over_H_C1cond_2060"], sub["nearest_km"],
            s=13, c=color, marker=marker, alpha=0.85,
            edgecolor="white", linewidth=0.45, zorder=3,
            label=f"{display} (n={len(sub)})",
        )
    ax_scatter.axvline(0.60, color=COLORS["grey"], lw=0.7, ls=(0, (4, 3)), zorder=1)
    ax_scatter.set_xlim(0, 2.1)
    ax_scatter.set_xticks([0, 0.6, 1.0, 1.5, 2.0])
    ax_scatter.set_xticklabels(["0", "0.6", "1", "1.5", "2"])
    ax_scatter.set_ylim(0, 520)
    ax_scatter.set_yticks([0, 250, 500])
    ax_scatter.set_xlabel("AF accessibility ratio κA/H, S1 conditions, 2060")
    ax_scatter.set_ylabel("Nearest whitelisted sink (km)")
    quiet_grid(ax_scatter, "both")
    despine(ax_scatter)
    panel_label(ax_scatter, "b")
    legend = ax_scatter.legend(loc="upper right", fontsize=FS_LEGEND,
                               handletextpad=0.4, borderaxespad=0.2,
                               labelspacing=0.4)
    _legend_frame(legend)

    return save(fig, "figS5_m2_swap_group_drivers_v5_20260919.png")


# ---------------------------------------------------------------------------
# Fig. S6: AF expansion ceiling and storage-rate binding
# ---------------------------------------------------------------------------

KAPPA = 2.0
THETA = 0.60
GJ_PER_TCE = 29.3076
MSW_TCE_PER_KT = 0.12
AF_WASTE_ACCESS_MATURITY = {2025: 0.10, 2030: 0.25, 2035: 0.40, 2040: 0.45,
                            2045: 0.70, 2050: 1.00, 2055: 1.00, 2060: 1.00}
AF_BIOMASS_ACCESS_MATURITY = {2025: 0.30, 2030: 0.40, 2035: 0.55, 2040: 0.70,
                              2045: 0.85, 2050: 1.00, 2055: 1.00, 2060: 1.00}

# Recomputed binding-layer shares of operating lines (%) from the frozen C1
# export; asserted in af_binding_shares() at ±0.5 pp. These supersede the
# quoted review ranges (see module docstring).
BINDING_ANCHOR = {
    2025: {"access": 0.0, "technical": 1.5},
    2030: {"access": 43.8, "technical": 0.3},
    2035: {"access": 71.9, "technical": 15.1},
    2040: {"access": 73.2, "technical": 25.9},
    2045: {"access": 66.8, "technical": 33.2},
    2050: {"access": 64.1, "technical": 35.9},
    2055: {"access": 66.7, "technical": 33.3},
    2060: {"access": 61.9, "technical": 38.1},
}


def province_af_pools() -> dict:
    """Replicates data_loader_v5.build_province_af_pool_ktce (per channel)."""
    regional = ROOT / "v5" / "data" / "model_input" / "regional"
    bio_df = pd.read_csv(regional / "af_biomass_supply.csv")
    wst_df = pd.read_csv(regional / "af_waste_supply.csv")
    prov_list = list(pd.read_csv(regional / "scm_proxy.csv")["province_cn"].unique())
    biomass_pool = {
        str(r["province_cn"]): float(r["bio_supply_ej_access_base"]) * 1e9 / GJ_PER_TCE / 1000.0
        for _, r in bio_df.iterrows()
    }
    waste_base, waste_high = {}, {}
    for _, r in wst_df[wst_df["year_hist"] == 2018].iterrows():
        prov = str(r["province_cn"])
        waste_base[prov] = float(r["residual_kt_access_base"]) * MSW_TCE_PER_KT
        waste_high[prov] = float(r["residual_kt_access_high"]) * MSW_TCE_PER_KT
    channel = {}
    for prov in prov_list:
        bio_full = biomass_pool.get(prov, 0.0)
        base = waste_base.get(prov, 0.0)
        high = waste_high.get(prov, base)
        for year in YEARS:
            channel[(prov, year)] = {
                "bio": bio_full * AF_BIOMASS_ACCESS_MATURITY[year],
                "wst": base + AF_WASTE_ACCESS_MATURITY[year] * max(0.0, high - base),
            }
    return channel


def af_binding_shares(c1: dict) -> pd.DataFrame:
    """Per-period share of operating lines bound at the accessibility or the
    technical AF layer (supply within 0.1% of the layer cap; the smaller cap
    is assigned when both bind)."""
    channel = province_af_pools()
    access = pd.read_csv(ROOT / "v5" / "data" / "plant_af_access_corrected.csv")
    access["plant_id"] = access["plant_id"].astype(int)

    def within_province_share(col):
        out = {}
        for _, sub in access.groupby("province"):
            total = float(sub[col].sum())
            for r in sub.itertuples(index=False):
                out[int(r.plant_id)] = (
                    float(getattr(r, col)) / total if total > 0 else 1.0 / len(sub)
                )
        return out

    share_bio = within_province_share("bio_ktce")
    share_wst = within_province_share("msw_ktce")

    summary = c1["summary"]
    tiers = [float(x) for x in c1["effective_config"]["af_plant_heat_intensity_tce_per_t"]]
    shares = pd.read_csv(C1_DIR / "full_af_plant_shares.csv")
    rows = {}
    for year in YEARS:
        sub = shares[(shares.period == year) & (shares.operating > 0.5)]
        ee = float(summary[str(year)]["ee_rate"])
        heat_intensity = np.select(
            [sub.capacity >= 4200, sub.capacity >= 2000],
            [tiers[0], tiers[1]], default=tiers[2],
        )
        heat = (heat_intensity * (1 - ee) * sub.capacity.to_numpy()
                * 310 / 1000.0 * sub.utilization.to_numpy())
        tech_cap = THETA * heat
        access_cap = KAPPA * np.array([
            channel[(r.province, year)]["bio"] * share_bio.get(int(r.plant_id), 0.0)
            + channel[(r.province, year)]["wst"] * share_wst.get(int(r.plant_id), 0.0)
            for r in sub.itertuples()
        ])
        supply = sub.af_supply_ktce.to_numpy()
        min_cap = np.minimum(tech_cap, access_cap)
        bound = supply >= 0.999 * min_cap
        rows[year] = {
            "technical": 100.0 * (bound & (tech_cap <= access_cap)).mean(),
            "access": 100.0 * (bound & (tech_cap > access_cap)).mean(),
            "unbound": 100.0 * (~bound).mean(),
            "n_operating": len(sub),
        }
    frame = pd.DataFrame(rows).T
    for year in YEARS:
        assert abs(frame.loc[year, "access"] - BINDING_ANCHOR[year]["access"]) < 0.5, (
            year, frame.loc[year])
        assert abs(frame.loc[year, "technical"] - BINDING_ANCHOR[year]["technical"]) < 0.5, (
            year, frame.loc[year])
    return frame


def make_figS6(c1: dict) -> Path:
    summary = c1["summary"]
    af_supply = np.array([summary[str(y)]["total_af_supply_ktce"] for y in YEARS])
    heat = np.array([summary[str(y)]["total_fuel_energy_ktce"] for y in YEARS])
    af_rate = 100.0 * af_supply / heat
    assert abs(af_rate[0] - 5.0) < 0.01 and abs(af_rate[-1] - 44.9) < 0.05, af_rate

    ceiling = np.zeros(len(YEARS))
    ceiling[0] = 0.05 * heat[0]
    for t in range(1, len(YEARS)):
        ceiling[t] = ceiling[t - 1] + 0.10 * heat[t]
    ceiling_rate = 100.0 * ceiling / heat
    for t in (0, 1, 2):
        assert abs(af_supply[t] - ceiling[t]) < 1.0, (YEARS[t], af_supply[t], ceiling[t])
    assert (ceiling[3:] - af_supply[3:] > 100.0).all()

    binding = af_binding_shares(c1)

    used_bound, used_slack = [], []
    for year in YEARS:
        bound_n = slack_n = 0
        for row in c1["storage_utilization"][str(year)]:
            if row["total_flow_kt"] <= 1e-6:
                continue
            hit = False
            if (row["dsa_flow_kt"] > 1e-6 and row["dsa_rate_capacity_kt_per_year"] > 0
                    and row["dsa_flow_kt"] >= 0.999 * row["dsa_rate_capacity_kt_per_year"]):
                hit = True
            if (row["eor_flow_kt"] > 1e-6 and row["eor_rate_capacity_kt_per_year"] > 0
                    and row["eor_flow_kt"] >= 0.999 * row["eor_rate_capacity_kt_per_year"]):
                hit = True
            bound_n, slack_n = bound_n + hit, slack_n + (not hit)
        used_bound.append(bound_n)
        used_slack.append(slack_n)
    total_used = sum(used_bound) + sum(used_slack)
    assert total_used == 834 and sum(used_bound) == 499, (sum(used_bound), total_used)

    fig = plt.figure(figsize=(FIG_W, 68 * MM))
    grid = fig.add_gridspec(
        1, 3, width_ratios=[1.0, 1.0, 0.92],
        left=0.075, right=0.975, top=0.93, bottom=0.27, wspace=0.38,
    )
    ax_rate = fig.add_subplot(grid[0, 0])
    ax_layer = fig.add_subplot(grid[0, 1])
    ax_store = fig.add_subplot(grid[0, 2])

    ax_rate.plot(YEARS, ceiling_rate, color=COLORS["grey"], lw=1.1,
                 ls=(0, (4, 3)), label="Expansion ceiling")
    ax_rate.plot(YEARS, af_rate, color=C1_COLOR, marker="o", ms=2.8, lw=1.3,
                 label="Realised AF rate")
    ax_rate.set_xlim(2023.5, 2061.5)
    ax_rate.set_xticks([2030, 2045, 2060])
    # Head-room above the 104% ceiling endpoint keeps the legend clear of both
    # the dashed ceiling and the 100% gridline.
    ax_rate.set_ylim(0, 126)
    ax_rate.set_yticks([0, 50, 100])
    ax_rate.set_ylabel("Share of national heat demand (%)", fontsize=FS_LABEL)
    quiet_grid(ax_rate)
    despine(ax_rate)
    panel_label(ax_rate, "a")
    ax_rate.set_title("AF rate vs expansion ceiling", pad=3)
    legend = ax_rate.legend(loc="upper left", fontsize=FS_NOTE, handletextpad=0.4,
                            borderaxespad=0.15, labelspacing=0.35)
    _legend_frame(legend)

    x = np.arange(len(YEARS))
    access_share = binding["access"].to_numpy()
    tech_share = binding["technical"].to_numpy()
    unbound_share = binding["unbound"].to_numpy()
    for year in (2030, 2035):
        ax_layer.axvspan(YEARS.index(year) - 0.5, YEARS.index(year) + 0.5,
                         color=COLORS["grey_light"], alpha=0.5, zorder=0)
    ax_layer.bar(x, access_share, width=0.66, color=C1_COLOR, lw=0,
                 label="Accessibility bound")
    ax_layer.bar(x, tech_share, width=0.66, bottom=access_share,
                 color=C4_COLOR, lw=0, label="Technical bound")
    ax_layer.bar(x, unbound_share, width=0.66, bottom=access_share + tech_share,
                 color=COLORS["grey_light"], lw=0, label="Unbound")
    ax_layer.set_xticks(x, [str(y) for y in YEARS], rotation=45, ha="right",
                        rotation_mode="anchor", fontsize=FS_NOTE)
    ax_layer.set_ylim(0, 100)
    ax_layer.set_yticks([0, 50, 100])
    ax_layer.set_ylabel("Operating lines (%)", fontsize=FS_LABEL)
    despine(ax_layer)
    panel_label(ax_layer, "b")
    ax_layer.set_title("Binding AF layer", pad=3)

    ax_store.bar(x, used_bound, width=0.66, color=C1_COLOR, lw=0,
                 label="Rate binding")
    ax_store.bar(x, used_slack, width=0.66, bottom=used_bound,
                 color=COLORS["grey_light"], lw=0, label="Slack")
    ax_store.set_xticks(x, [str(y) for y in YEARS], rotation=45, ha="right",
                        rotation_mode="anchor", fontsize=FS_NOTE)
    ax_store.set_ylim(0, 250)
    ax_store.set_yticks([0, 100, 200])
    ax_store.set_ylabel("Used (sink, period) pairs", fontsize=FS_LABEL)
    quiet_grid(ax_store)
    despine(ax_store)
    panel_label(ax_store, "c")
    ax_store.set_title("Storage-rate binding", pad=3)
    legend = ax_store.legend(loc="upper left", fontsize=FS_NOTE, borderaxespad=0.2,
                             labelspacing=0.3)
    _legend_frame(legend)

    fig.legend(
        handles=[
            Patch(facecolor=C1_COLOR, label="Accessibility bound"),
            Patch(facecolor=C4_COLOR, label="Technical bound"),
            Patch(facecolor=COLORS["grey_light"], label="Unbound"),
        ],
        loc="lower center", bbox_to_anchor=(0.53, 0.015), ncol=3, frameon=False,
        fontsize=FS_NOTE, handlelength=1.1, handletextpad=0.4, columnspacing=0.9,
    )

    return save(fig, "figS6_af_storage_binding_v5_20260919.png")


def main() -> None:
    apply_style()
    c1 = load_c1()
    make_figS2()
    make_figS3(c1)
    make_figS4(c1)
    make_figS5()
    make_figS6(c1)


if __name__ == "__main__":
    main()
