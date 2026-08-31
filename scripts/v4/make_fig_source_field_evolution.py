#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Main-text Fig. 9: endogenous emission source-field evolution (S1/S2/S3 x 2035/2050/2060).

3 x 3 map grid visualising how the plant-level emission source field is formed
endogenously under the three core scenarios. Rows are the manuscript's core
scenarios and columns are the three reporting years (2035 / 2050 / 2060). Each
panel is a map of the operating (emitting) plant set: marker area encodes the
plant's gross CO2 emission (kt CO2/yr, pre-capture), so the panels show both
the contraction of the fleet and the spatial reconfiguration of the remaining
sources.

For S2 and S3, points are coloured by their set membership relative to S1 in
the same year, reusing the entering/leaving colour language of main-text
Fig. 6A (blue circles = entering, gold squares = leaving):
    grey  = present in S1 and in the scenario (common; background mass),
    blue  = present only in the scenario (added vs S1),
    gold  = present only in S1 (removed vs S1).
The S1 row is the reference (all sources grey). Point size is the plant's gross
emission; for a removed source the S1 emission is used (the magnitude retired).

Derivation notes (口径)
-----------------------
- Scenario labels follow the canonical run inventory
  (results/v4/writing_ready_storyline_v3_20260829/canonical_run_inventory.csv):
      S1 -> full/S1_baseline_results.json        (heterogeneous suitability)
      S2 -> full/S3_all_spatial_equalized_results.json (AF advantage neutralized)
      S3 -> full/S5_offshore_parity_results.json (offshore cost parity)
- Plant coordinates come from the frozen
  results/v4/writing_ready_storyline_v3_20260829/plant_decision_matrix.csv
  (verified 1,572-line fleet).
- Per-plant gross emission = plants[*].co2_gross (kt CO2/yr) read directly from
  each results JSON for years 2035/2050/2060; a plant is part of a source field
  when its gross emission is positive (operating and producing).
- Basemap: input/district.shp (province level, treated as EPSG:4326, Albers
  equal-area lon_0=105 lat_1=25 lat_2=47). The mainland panel is clipped to
  y >= 17 deg N and shares the exact extent of main-text Fig. 4 (SOUTH_BUFFER
  open-water strip). One framed South-China-Sea inset (bottom-right of the
  bottom-right panel) serves the whole grid: the panels are identical base maps
  and no source data fall in the South China Sea, so a single locator inset is
  sufficient and nine duplicates would only add clutter.

Style follows the Applied Energy 2026 figure system
(figure_system_2026_common.py: Arial 7 pt, Okabe-Ito palette, 600 dpi);
delivered in the canonical four-format bundle as
``fig9_source_field_evolution.*`` on the 190-mm canvas.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from shapely.geometry import box

from figure_system_2026_common import COLORS, FIGDIR, ROOT, SOURCE, apply_style, save_figure
from make_main_figures_2026_v2 import _add_south_china_sea_inset

apply_style()

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
RUN_ROOT = ROOT / "results/v4/final_verified_inputs_20260829/full"
PLANT_MATRIX = (
    ROOT / "results/v4/writing_ready_storyline_v3_20260829/plant_decision_matrix.csv"
)

ALBERS = (
    "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 "
    "+datum=WGS84 +units=m +no_defs"
)

# South China Sea inset region (WGS84 lon/lat box): islands + Hainan at top.
SCS_BOX = (105.0, 2.0, 124.5, 24.5)
# Open water reserved at the bottom of the main map for the inset (fraction of
# the mainland map height). Matches main-text Fig. 4 so every main-text map
# shares one extent.
SOUTH_BUFFER = 0.22

SCENARIOS = ["S1", "S2", "S3"]
RUN_JSON = {
    "S1": RUN_ROOT / "S1_baseline_results.json",
    "S2": RUN_ROOT / "S3_all_spatial_equalized_results.json",
    "S3": RUN_ROOT / "S5_offshore_parity_results.json",
}
YEARS = [2035, 2050, 2060]
NROWS, NCOLS = 3, 3

# Set-membership categories relative to S1. Colors and markers reuse the
# entering/leaving language of main-text Fig. 6A: blue circles enter,
# gold squares leave; the common mass recedes to grey.
CATEGORY_ORDER = ["common", "added", "removed"]
CAT_COLOR = {
    "common": COLORS["grey"],         # present in S1 and in the scenario
    "added": COLORS["blue"],          # present only in the scenario
    "removed": COLORS["gold"],        # present only in S1
}
CAT_MARKER = {"common": "o", "added": "o", "removed": "s"}
CAT_ALPHA = {"common": 0.60, "added": 0.88, "removed": 0.92}
CAT_LABEL = {
    "common": "Present in both",
    "added": "Added vs S1",
    "removed": "Removed vs S1",
}

# Marker area (matplotlib ``s``) as a function of gross emission. Area is set
# proportional to emission (linear), kept small so overlapping sources stay
# legible; the few large late-period sources still stand out. GMAX is the global
# maximum over all panels so every panel is directly comparable.
AREA_FLOOR = 1.2
AREA_SCALE = 28.0

# Legend anchors (gross emission, kt CO2/yr)
LEGEND_VALUES = [100, 300, 1000, 2500]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_plants() -> pd.DataFrame:
    cols = ["plant_id", "name", "province", "longitude", "latitude"]
    return pd.read_csv(PLANT_MATRIX, usecols=cols)


def load_emissions() -> dict[str, dict[int, dict[int, float]]]:
    """Return per[scenario][year] = {plant_id: gross_co2_kt} for lines with y == 1.

    Membership follows the binary operating status y (the plotted quantity is the
    operating source set), not a positive-gross-emission filter.
    """
    per = {s: {yr: {} for yr in YEARS} for s in SCENARIOS}
    for scen, path in RUN_JSON.items():
        with open(path, encoding="utf-8") as fh:
            res = json.load(fh)
        for pid_str, p in res["plants"].items():
            pid = int(pid_str)
            for yr in YEARS:
                if float(p["y"][str(yr)]) > 0.5:
                    per[scen][yr][pid] = float(p["co2_gross"][str(yr)])
    return per


def build_point_frame(per: dict) -> pd.DataFrame:
    """Long frame [scenario, year, plant_id, gross_co2_kt, category].

    For S2/S3 the source set is the union of the scenario set and the S1 set,
    categorised by membership (common / added / removed). Size uses the scenario
    emission for points present in the scenario, and the S1 emission for removed
    points (the magnitude retired).
    """
    s1 = per["S1"]
    rows = []
    for scen in SCENARIOS:
        for yr in YEARS:
            if scen == "S1":
                for pid, g in s1[yr].items():
                    rows.append((scen, yr, pid, g, "common"))
            else:
                scn = per[scen][yr]
                for pid in set(scn) | set(s1[yr]):
                    in_s1 = pid in s1[yr]
                    in_scn = pid in scn
                    if in_scn and in_s1:
                        rows.append((scen, yr, pid, scn[pid], "common"))
                    elif in_scn:
                        rows.append((scen, yr, pid, scn[pid], "added"))
                    else:
                        rows.append((scen, yr, pid, s1[yr][pid], "removed"))
    return pd.DataFrame(
        rows, columns=["scenario", "year", "plant_id", "gross_co2_kt", "category"]
    )


# ---------------------------------------------------------------------------
# Basemap helpers
# ---------------------------------------------------------------------------
def load_basemap() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return (mainland clipped to y>=17N, South-China-Sea inset)."""
    raw = gpd.read_file(ROOT / "input/district.shp").set_crs(epsg=4326)
    province = raw.dissolve(by="pr_adcode").reset_index()
    parts = province.explode(index_parts=False)
    main = parts[parts.geometry.representative_point().y >= 17.0]
    scs = gpd.clip(parts, box(*SCS_BOX))
    return (
        gpd.GeoDataFrame(main, geometry="geometry", crs=4326).to_crs(ALBERS),
        gpd.GeoDataFrame(scs, geometry="geometry", crs=4326).to_crs(ALBERS),
    )


def project(lon, lat) -> gpd.GeoSeries:
    return gpd.GeoSeries(
        gpd.points_from_xy(np.asarray(lon), np.asarray(lat)), crs="EPSG:4326"
    ).to_crs(ALBERS)


def add_north_arrow(ax, x=0.955, y=0.985) -> None:
    ax.annotate(
        "",
        xy=(x, y - 0.045),
        xytext=(x, y - 0.145),
        xycoords="axes fraction",
        arrowprops=dict(arrowstyle="-|>", color=COLORS["ink"], lw=0.9,
                        mutation_scale=7),
        annotation_clip=False,
        zorder=8,
    )
    ax.text(x, y, "N", transform=ax.transAxes, ha="center", va="top",
            fontsize=7.0, fontweight="bold", zorder=8)


def add_scale_bar(ax, minx, miny, maxx, maxy, length_km=500,
                  fx=0.13, fy=0.050) -> None:
    L = length_km * 1000.0
    x0 = minx + fx * (maxx - minx)
    y0 = miny + fy * (maxy - miny)
    dy = 0.010 * (maxy - miny)
    ax.plot([x0, x0 + L], [y0, y0], color=COLORS["ink"], lw=1.4,
            solid_capstyle="butt", zorder=8)
    for xx in (x0, x0 + L):
        ax.plot([xx, xx], [y0, y0 + dy], color=COLORS["ink"], lw=1.0, zorder=8)
    ax.text(x0 + L / 2, y0 + 1.6 * dy, f"{length_km} km", ha="center",
            va="bottom", fontsize=6.5, zorder=8)


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------
def make_fig() -> Path:
    china, scs = load_basemap()
    per = load_emissions()
    frame = build_point_frame(per)
    meta = load_plants()
    coords = meta.set_index("plant_id")

    gmax = float(frame["gross_co2_kt"].max())

    def marker_area(v: np.ndarray) -> np.ndarray:
        return AREA_FLOOR + AREA_SCALE * (np.maximum(v, 0.0) / gmax)

    minx, miny, maxx, maxy = china.total_bounds
    miny = miny - SOUTH_BUFFER * (maxy - miny)
    data_aspect = (maxx - minx) / (maxy - miny)

    # 190-mm canvas; height chosen so each grid cell matches the data aspect
    # (no distortion, minimal letterboxing).
    W = 7.48
    left, right, top, bottom = 0.075, 0.99, 0.955, 0.155
    wspace, hspace = 0.045, 0.06
    cell_w = W * (right - left) / (NCOLS + (NCOLS - 1) * wspace)
    cell_h = cell_w / data_aspect
    grid_h = NROWS * cell_h + (NROWS - 1) * hspace * cell_h
    H = grid_h / (top - bottom)

    fig = plt.figure(figsize=(W, H))
    gs = fig.add_gridspec(
        NROWS, NCOLS, left=left, right=right, top=top, bottom=bottom,
        wspace=wspace, hspace=hspace,
    )

    axes = np.empty((NROWS, NCOLS), dtype=object)
    for r in range(NROWS):
        for c in range(NCOLS):
            ax = fig.add_subplot(gs[r, c])
            axes[r, c] = ax

            # Clearer province boundaries on a light fill.
            china.plot(ax=ax, color="#FBFBFB", edgecolor="#333333",
                       linewidth=0.42, zorder=0)

            scen = SCENARIOS[r]
            yr = YEARS[c]
            sub = frame[(frame.scenario == scen) & (frame.year == yr)].copy()
            sub["lon"] = sub["plant_id"].map(coords["longitude"])
            sub["lat"] = sub["plant_id"].map(coords["latitude"])
            pts = project(sub["lon"], sub["lat"])
            sub["x"] = pts.x.to_numpy()
            sub["y"] = pts.y.to_numpy()
            # Grey common mass first; entering/leaving points on top.
            for cat in CATEGORY_ORDER:
                part = sub[sub.category.eq(cat)].sort_values("gross_co2_kt")
                if not len(part):
                    continue
                ax.scatter(
                    part["x"], part["y"],
                    s=marker_area(part["gross_co2_kt"].to_numpy()),
                    c=CAT_COLOR[cat], marker=CAT_MARKER[cat],
                    alpha=CAT_ALPHA[cat], edgecolors="white",
                    linewidths=0.30, zorder=3 if cat == "common" else 4,
                )

            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)
            ax.set_aspect("equal")
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)

            if r == 0:
                ax.text(0.5, 1.035, str(yr), transform=ax.transAxes,
                        ha="center", va="bottom", fontsize=9, fontweight="bold",
                        color=COLORS["ink"])
            if c == 0:
                ax.text(-0.14, 0.5, scen, transform=ax.transAxes,
                        ha="right", va="center", fontsize=9, fontweight="bold",
                        color=COLORS["ink"])

    # One South-China-Sea locator inset serves the whole grid.
    _add_south_china_sea_inset(axes[2, 2], scs)

    add_north_arrow(axes[0, 0])
    add_scale_bar(axes[0, 0], minx, miny, maxx, maxy)

    # Category legend (left) + size legend (right), side by side at bottom.
    cat_handles = [
        Line2D([], [], marker=CAT_MARKER[k], ls="", markerfacecolor=CAT_COLOR[k],
               markeredgecolor="white", markeredgewidth=0.3, markersize=4.5,
               label=CAT_LABEL[k])
        for k in CATEGORY_ORDER
    ]
    cat_leg = fig.legend(
        handles=cat_handles, loc="lower center", bbox_to_anchor=(0.5, 0.085),
        ncol=3, frameon=True, handletextpad=0.5, borderaxespad=0.1,
        labelspacing=0.35, columnspacing=1.0,
    )
    cat_leg.get_frame().set_facecolor("white")
    cat_leg.get_frame().set_edgecolor("#D5D5D5")
    cat_leg.get_frame().set_linewidth(0.45)
    cat_leg.get_frame().set_alpha(0.94)
    cat_leg.set_title("Source set vs S1", prop={"size": 7.0})

    size_handles = [
        Line2D([], [], marker="o", ls="", markerfacecolor="#9A9A9A",
               markeredgecolor="white", markeredgewidth=0.3,
               markersize=np.sqrt(marker_area(np.array([v]))[0]), label=f"{v}")
        for v in LEGEND_VALUES
    ]
    size_leg = fig.legend(
        handles=size_handles, loc="lower center", bbox_to_anchor=(0.5, 0.012),
        ncol=len(LEGEND_VALUES), frameon=True, handletextpad=0.4,
        borderaxespad=0.1, labelspacing=0.5, columnspacing=1.1,
    )
    size_leg.get_frame().set_facecolor("white")
    size_leg.get_frame().set_edgecolor("#D5D5D5")
    size_leg.get_frame().set_linewidth(0.45)
    size_leg.get_frame().set_alpha(0.94)
    size_leg.set_title("Plant gross CO$_2$ emissions (kt CO$_2$ yr$^{-1}$)",
                       prop={"size": 7.0})

    # Auditable source data (includes the category).
    out_data = frame.merge(meta, on="plant_id", how="left")[
        ["scenario", "year", "plant_id", "category", "gross_co2_kt",
         "name", "province", "longitude", "latitude"]]
    SOURCE.mkdir(parents=True, exist_ok=True)
    out_data.to_csv(SOURCE / "fig_source_field_evolution.csv", index=False)

    path = save_figure(fig, "fig8_source_field_evolution.png")
    plt.close(fig)
    return path


if __name__ == "__main__":
    path = make_fig()
    print("wrote", path)
