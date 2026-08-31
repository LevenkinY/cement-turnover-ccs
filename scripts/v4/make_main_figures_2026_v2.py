#!/usr/bin/env python3
"""Render the redesigned Applied Energy main Figs. 4--8 and the SI national overview.

Run ``prepare_main_figure_data_2026_v2.py`` first.  This renderer reads only
the resulting auditable source-data CSVs and the province basemap.
"""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import PatchCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon
from matplotlib.transforms import Bbox
from shapely.geometry import box

from figure_system_2026_common import (
    COLORS,
    FIGDIR,
    ROOT,
    SOURCE,
    TIER_COLORS,
    apply_style,
    despine,
    panel_label,
    quiet_grid,
    save_figure,
)


apply_style()

ALBERS = (
    "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 "
    "+datum=WGS84 +units=m +no_defs"
)

# South China Sea inset region (WGS84 lon/lat box): the islands + Hainan at the
# top, so the inset is the sea region, not a duplicate of the whole map. Open
# water is reserved at the bottom of the mainland map (fraction of mainland
# height) so the inset frame sits over clear sea rather than overlapping the
# mainland / islands.
SCS_BOX = (105.0, 2.0, 124.5, 24.5)
SOUTH_BUFFER = 0.22

YEARS = np.array([2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060])
WINDOW_COLORS = {
    "Full period": COLORS["blue"],
    "Early (2025--2045)": COLORS["grey"],
    "Late (2050--2060)": COLORS["orange"],
}
WINDOW_MARKERS = {
    "Full period": "o",
    "Early (2025--2045)": "s",
    "Late (2050--2060)": "D",
}
TIER_MARKERS = {
    "stable_core": "o",
    "conditional_asset": "s",
    "sensitive_margin": "D",
}


def _phase_structure(ax, labels: bool = True) -> None:
    for year in (2045, 2055):
        ax.axvline(year, color="#A7A7A7", lw=0.65, ls=(0, (2, 2)), zorder=1)
    if labels:
        for x, label in ((2035, "P1"), (2050, "P2"), (2057.5, "P3")):
            ax.text(
                x,
                1.015,
                label,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=6.5,
                color=COLORS["grey"],
                clip_on=False,
            )


def _legend_frame(legend) -> None:
    legend.set_frame_on(True)
    legend.get_frame().set_facecolor("white")
    legend.get_frame().set_edgecolor("#D5D5D5")
    legend.get_frame().set_linewidth(0.45)
    legend.get_frame().set_alpha(0.94)


def make_si_national_overview() -> Path:
    system = pd.read_csv(SOURCE / "fig2_system_envelope_v2.csv")
    turnover = pd.read_csv(SOURCE / "fig2_turnover_capture_v2.csv")

    fig = plt.figure(figsize=(7.48, 4.18))  # 190 x 106 mm
    outer = fig.add_gridspec(
        2,
        1,
        height_ratios=[1.03, 1.22],
        left=0.115,
        right=0.985,
        top=0.95,
        bottom=0.105,
        hspace=0.28,
    )

    ax = fig.add_subplot(outer[0])
    prod_low = system[["clinker_d_low_mt", "clinker_s1_mt", "clinker_d_high_mt"]].min(axis=1)
    prod_high = system[["clinker_d_low_mt", "clinker_s1_mt", "clinker_d_high_mt"]].max(axis=1)
    cap_low = system[["capacity_d_low_mt_y", "capacity_s1_mt_y", "capacity_d_high_mt_y"]].min(axis=1)
    cap_high = system[["capacity_d_low_mt_y", "capacity_s1_mt_y", "capacity_d_high_mt_y"]].max(axis=1)
    ax.fill_between(
        system.year,
        prod_low,
        prod_high,
        color=COLORS["grey_light"],
        alpha=0.62,
        lw=0,
        label="Clinker-production range",
        zorder=1,
    )
    ax.fill_between(
        system.year,
        cap_low,
        cap_high,
        color=COLORS["blue_light"],
        alpha=0.24,
        lw=0,
        label="Operating-capacity range",
        zorder=1,
    )
    ax.fill_between(
        system.year,
        system.clinker_s1_mt,
        system.capacity_s1_mt_y,
        color=COLORS["grey_xlight"],
        alpha=0.9,
        lw=0,
        zorder=1.2,
    )
    ax.plot(
        system.year,
        system.clinker_s1_mt,
        color=COLORS["ink"],
        marker="o",
        label="Clinker production (S1)",
        zorder=3,
    )
    ax.plot(
        system.year,
        system.capacity_s1_mt_y,
        color=COLORS["blue"],
        marker="s",
        label="Operating capacity (S1)",
        zorder=3,
    )
    ax.set_ylabel("Clinker production / capacity\n(Mt yr$^{-1}$)", fontsize=8.6)
    ax.set_xlim(2023.5, 2061.5)
    ax.set_ylim(0, 2100)
    ax.set_xticks(YEARS)
    ax.tick_params(axis="x", labelbottom=False)
    _phase_structure(ax)
    quiet_grid(ax)
    despine(ax)
    panel_label(ax, "A")
    legend = ax.legend(ncol=2, loc="upper right", columnspacing=0.9, handlelength=1.7)
    _legend_frame(legend)

    lower = outer[1].subgridspec(2, 1, height_ratios=[1.0, 0.95], hspace=0.08)
    ax_event = fig.add_subplot(lower[0])
    x = turnover.year.to_numpy()
    early = turnover.early_exit_capacity_mt_y.to_numpy()
    natural = turnover.natural_retirement_capacity_mt_y.to_numpy()
    renewal = turnover.renewal_capacity_mt_y.to_numpy()
    width = 3.25
    ax_event.bar(
        x,
        -early,
        width=width,
        color=COLORS["gold"],
        edgecolor="white",
        lw=0.35,
        label="Early exit",
    )
    ax_event.bar(
        x,
        -natural,
        width=width,
        bottom=-early,
        color=COLORS["grey"],
        edgecolor="white",
        lw=0.35,
        label="Natural retirement",
    )
    ax_event.bar(
        x,
        renewal,
        width=width,
        color=COLORS["teal"],
        edgecolor="white",
        lw=0.35,
        label="Same-site renewal",
    )
    ax_event.axhline(0, color=COLORS["ink"], lw=0.65)
    ax_event.set_ylabel("Turnover\n(Mt yr$^{-1}$)", fontsize=8.6)
    ax_event.set_xlim(2023.5, 2061.5)
    ax_event.set_ylim(-500, 340)
    ax_event.set_xticks(YEARS)
    ax_event.tick_params(axis="x", labelbottom=False)
    _phase_structure(ax_event)
    quiet_grid(ax_event)
    despine(ax_event)
    panel_label(ax_event, "B")
    legend = ax_event.legend(ncol=3, loc="upper left", columnspacing=0.8, handlelength=1.4)
    _legend_frame(legend)

    ax_capture = fig.add_subplot(lower[1], sharex=ax_event)
    ax_capture.fill_between(
        turnover.year,
        turnover.capture_demand_range_low_mt_y,
        turnover.capture_demand_range_high_mt_y,
        color=COLORS["grey_light"],
        alpha=0.55,
        lw=0,
        label="S4--S5 range",
        zorder=0.5,
    )
    ax_capture.stackplot(
        turnover.year,
        turnover.nonterminal_capture_mt_y,
        turnover.terminal_inherited_phase_capture_mt_y,
        turnover.terminal_renewed_phase_capture_mt_y,
        colors=[COLORS["gold_light"], COLORS["blue_light"], COLORS["orange"]],
        labels=["Non-terminal", "Terminal, inherited", "Terminal, renewed"],
        edgecolor="white",
        linewidth=0.25,
        alpha=0.94,
        zorder=2,
    )
    ax_capture.set_ylabel("Capture\n(Mt CO$_2$ yr$^{-1}$)", fontsize=8.6)
    ax_capture.set_xlabel("Year")
    ax_capture.set_xlim(2023.5, 2061.5)
    ax_capture.set_ylim(0, 510)
    ax_capture.set_xticks(YEARS)
    _phase_structure(ax_capture, labels=False)
    quiet_grid(ax_capture)
    despine(ax_capture)
    legend = ax_capture.legend(
        ncol=2,
        loc="upper left",
        columnspacing=0.65,
        handlelength=1.2,
        fontsize=5.8,
    )
    _legend_frame(legend)

    path = save_figure(fig, "SI/figS1_national_demand_turnover_overview.png")
    plt.close(fig)
    return path


def _load_basemap() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return (mainland clipped to y>=17N, South-China-Sea inset region)."""
    raw = gpd.read_file(ROOT / "input/district.shp").set_crs(epsg=4326)
    province = raw.dissolve(by="pr_adcode").reset_index()
    parts = province.explode(index_parts=False)
    main = parts[parts.geometry.representative_point().y >= 17.0]
    # South China Sea inset: territory clipped to the SE box (islands + Hainan).
    scs = gpd.clip(parts, box(*SCS_BOX))
    return (
        gpd.GeoDataFrame(main, geometry="geometry", crs=4326).to_crs(ALBERS),
        gpd.GeoDataFrame(scs, geometry="geometry", crs=4326).to_crs(ALBERS),
    )


def _project(lon, lat) -> gpd.GeoSeries:
    return gpd.GeoSeries(
        gpd.points_from_xy(np.asarray(lon), np.asarray(lat)), crs="EPSG:4326"
    ).to_crs(ALBERS)


_JD_CACHE: dict[str, gpd.GeoDataFrame] = {}


def _scs_boundary_layer() -> gpd.GeoDataFrame:
    """Ten-segment-line slivers (national geojson feature 100000_JD) in ALBERS."""
    if "jd" not in _JD_CACHE:
        raw = gpd.read_file(ROOT / "data/raw/geography/中华人民共和国.geojson")
        jd = raw[raw["adcode"].astype(str).eq("100000_JD")]
        _JD_CACHE["jd"] = jd.to_crs(ALBERS)
    return _JD_CACHE["jd"]


def _add_south_china_sea_inset(ax, scs: gpd.GeoDataFrame) -> None:
    """South-China-Sea inset (bottom-right, over open water): islands + Hainan.

    White background (no sea fill); the SCS islands + Hainan are drawn as grey
    land outlines, and the framed box has a solid clear border. The official
    ten-segment-line slivers (national boundary feature 100000_JD from the
    geography geojson, the same layer used by the fleet-location reference
    map) are rendered inside the box; their segmented geometry reads as the
    conventional dashed boundary.

    The inset keeps the true Albers aspect of ``scs`` and, because the SCS box
    is taller than wide, anchors to the south-east corner of the reserved
    rectangle so the frame sits snugly in the map corner instead of floating
    centred with uneven margins.
    """
    inset = ax.inset_axes([0.79, 0.02, 0.20, 0.24])
    inset.set_facecolor("white")
    scs.plot(ax=inset, color="white", edgecolor="#333333", linewidth=0.38)
    _scs_boundary_layer().plot(
        ax=inset, facecolor="none", edgecolor="#333333", linewidth=0.40
    )
    frame = gpd.GeoSeries(
        pd.concat([scs.geometry, _scs_boundary_layer().geometry], ignore_index=True),
        crs=scs.crs,
    )
    minx, miny, maxx, maxy = frame.total_bounds
    inset.set_xlim(minx - 0.03 * (maxx - minx), maxx + 0.03 * (maxx - minx))
    inset.set_ylim(miny - 0.03 * (maxy - miny), maxy + 0.03 * (maxy - miny))
    inset.set_aspect("equal", adjustable="box", anchor="SE")
    inset.set_xticks([])
    inset.set_yticks([])
    for spine in inset.spines.values():
        spine.set_color("#55606B")
        spine.set_linewidth(0.6)


def _hex_patch(x: float, y: float, radius: float) -> Polygon:
    angles = np.radians(np.arange(0, 360, 60) + 30)
    return Polygon(np.column_stack([x + radius * np.cos(angles), y + radius * np.sin(angles)]))


def make_fig4() -> Path:
    assets = pd.read_csv(SOURCE / "fig3_spatial_assets_v2.csv")
    hexes = pd.read_csv(SOURCE / "fig3_af_hex_v2.csv")
    availability = pd.read_csv(SOURCE / "fig3_storage_availability_v2.csv")
    storage_nodes = pd.read_csv(SOURCE / "fig3_storage_nodes_v2.csv")
    matrix = pd.read_csv(SOURCE / "fig3_suitability_matrix_v2.csv")
    china, scs = _load_basemap()

    fig = plt.figure(figsize=(7.48, 4.9))  # 190 x ~125 mm
    gs = fig.add_gridspec(
        1,
        2,
        width_ratios=[2.55, 1.0],
        left=0.012,
        # Keep the matrix colorbar and its 1.0 tick clear of the export edge.
        right=0.94,
        top=0.96,
        bottom=0.09,
        wspace=0.12,
    )

    ax = fig.add_subplot(gs[0])
    china.plot(ax=ax, color="#FBFBFB", edgecolor="#333333", linewidth=0.30, zorder=0)
    minx, miny, maxx, maxy = china.total_bounds
    # Reserve open water below the mainland so the South China Sea inset frame
    # sits over clear sea instead of overlapping the mainland / island outlines.
    miny = miny - SOUTH_BUFFER * (maxy - miny)

    hex_cmap = mcolors.LinearSegmentedColormap.from_list(
        "af_access", ["#FFFDF6", COLORS["gold_light"], COLORS["gold"]]
    )
    hex_norm = mcolors.Normalize(vmin=0, vmax=1)
    patches = [
        _hex_patch(row.center_x, row.center_y, row.hex_radius_m)
        for row in hexes.itertuples(index=False)
    ]
    collection = PatchCollection(
        patches,
        array=hexes.af_resource_median.to_numpy(),
        cmap=hex_cmap,
        norm=hex_norm,
        edgecolor="none",
        alpha=0.38,
        zorder=0.7,
    )
    ax.add_collection(collection)

    available_pts = _project(availability.longitude, availability.latitude)
    ax.scatter(
        available_pts.x,
        available_pts.y,
        s=0.7,
        c=COLORS["teal"],
        alpha=0.16,
        linewidths=0,
        zorder=1,
    )

    recurrent_nodes = storage_nodes[storage_nodes.flow_scenario_count.eq(5)].copy()
    recurrent_nodes = recurrent_nodes.sort_values("mean_cumulative_flow_mt", ascending=False)
    recurrent_nodes["cumulative_share"] = recurrent_nodes.mean_cumulative_flow_mt.cumsum() / recurrent_nodes.mean_cumulative_flow_mt.sum()
    recurrent_nodes = recurrent_nodes[
        recurrent_nodes.cumulative_share.le(0.50)
        | recurrent_nodes.cumulative_share.shift(fill_value=0).lt(0.50)
    ].copy()
    node_pts = _project(recurrent_nodes.longitude, recurrent_nodes.latitude)
    recurrent_nodes["x"] = node_pts.x.to_numpy()
    recurrent_nodes["y"] = node_pts.y.to_numpy()
    node_max = max(float(recurrent_nodes.mean_cumulative_flow_mt.max()), 1.0)
    for (storage_type, offshore), subset in recurrent_nodes.groupby(["storage_type", "is_offshore"]):
        ax.scatter(
            subset.x,
            subset.y,
            s=8 + 24 * np.sqrt(subset.mean_cumulative_flow_mt / node_max),
            marker="^" if storage_type == "DSA" else "v",
            facecolor="white" if bool(offshore) else COLORS["teal"],
            edgecolor=COLORS["teal"],
            linewidth=0.65,
            alpha=0.92,
            zorder=2.7,
        )

    inherited_pts = _project(assets.longitude, assets.latitude)
    ax.scatter(
        inherited_pts.x,
        inherited_pts.y,
        s=1.0,
        c="#A7A7A7",
        alpha=0.32,
        linewidths=0,
        zorder=1.4,
    )

    selected_assets = assets[assets.terminal_scenario_count.gt(0)].copy()
    asset_pts = _project(selected_assets.longitude, selected_assets.latitude)
    selected_assets["x"] = asset_pts.x.to_numpy()
    selected_assets["y"] = asset_pts.y.to_numpy()
    cap_max = max(selected_assets.mean_cumulative_capture_mt.max(), 1.0)
    for tier in ("sensitive_margin", "conditional_asset", "stable_core"):
        subset = selected_assets[selected_assets.asset_tier.eq(tier)]
        sizes = 3.0 + 35.0 * np.sqrt(subset.mean_cumulative_capture_mt / cap_max)
        ax.scatter(
            subset.x,
            subset.y,
            s=sizes,
            marker=TIER_MARKERS[tier],
            color=TIER_COLORS[tier],
            alpha=0.86,
            edgecolor="white",
            linewidth=0.38,
            zorder=3,
        )

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    panel_label(ax, "A")
    _add_south_china_sea_inset(ax, scs)

    asset_handles = [
        Line2D(
            [],
            [],
            marker=TIER_MARKERS[tier],
            ls="",
            markerfacecolor=TIER_COLORS[tier],
            markeredgecolor="white",
            markersize=4.5,
            label=label,
        )
        for tier, label in (
            ("stable_core", "Stable core"),
            ("conditional_asset", "Conditional"),
            ("sensitive_margin", "Sensitive margin"),
        )
    ]
    inherited_handle = Line2D(
        [], [], marker=".", ls="", color="#9A9A9A", ms=4.5, label="Inherited stock"
    )
    legend1 = ax.legend(
        handles=[inherited_handle, *asset_handles],
        loc="upper left",
        ncol=2,
        columnspacing=0.9,
        labelspacing=0.42,
        handletextpad=0.4,
        borderaxespad=0.1,
    )
    _legend_frame(legend1)
    ax.add_artist(legend1)
    network_handles = [
        Line2D([], [], marker="o", ls="", mfc=COLORS["teal"], mec=COLORS["teal"], ms=3.4, alpha=0.45, label="Eligible storage (DSA/EOR)"),
        Line2D([], [], marker="^", ls="", mfc=COLORS["teal"], mec=COLORS["teal"], ms=4.0, label="Recurrent DSA (onshore)"),
        Line2D([], [], marker="^", ls="", mfc="white", mec=COLORS["teal"], ms=4.0, label="Recurrent DSA (offshore)"),
        Line2D([], [], marker="v", ls="", mfc=COLORS["teal"], mec=COLORS["teal"], ms=4.0, label="Recurrent EOR (onshore)"),
        Line2D([], [], marker="v", ls="", mfc="white", mec=COLORS["teal"], ms=4.0, label="Recurrent EOR (offshore)"),
    ]
    legend2 = ax.legend(
        handles=network_handles,
        loc="upper left",
        bbox_to_anchor=(0.02, 0.33),
        ncol=1,
        fontsize=6.0,
        labelspacing=0.58,
        handletextpad=0.45,
        borderaxespad=0.25,
    )
    _legend_frame(legend2)
    cbar_ax = ax.inset_axes([0.02, 0.075, 0.22, 0.025])
    cbar = fig.colorbar(collection, cax=cbar_ax, orientation="horizontal", ticks=[0, 0.5, 1])
    cbar.set_label("AF resource index", fontsize=6.5, labelpad=1)
    cbar.ax.tick_params(labelsize=6.2, length=1.5, pad=1)
    cbar.outline.set_linewidth(0.4)

    axm = fig.add_subplot(gs[1])
    af_order = ["AF Q1", "AF Q2", "AF Q3", "AF Q4"]
    distance_order = ["Distance Q4", "Distance Q3", "Distance Q2", "Distance Q1"]
    heat = matrix.pivot(
        index="distance_quartile", columns="af_quartile", values="mean_survival_frequency"
    ).reindex(index=distance_order, columns=af_order)
    capture = matrix.pivot(
        index="distance_quartile", columns="af_quartile", values="mean_cumulative_capture_mt"
    ).reindex(index=distance_order, columns=af_order)
    survival_cmap = mcolors.LinearSegmentedColormap.from_list(
        "survival", ["#F8FBFD", COLORS["blue_light"], COLORS["blue"]]
    )
    image = axm.imshow(heat.to_numpy(), cmap=survival_cmap, vmin=0, vmax=1, aspect="equal")
    max_capture = max(float(np.nanmax(capture.to_numpy())), 1.0)
    for iy in range(4):
        for ix in range(4):
            value = float(capture.iloc[iy, ix])
            if value <= 0:
                continue
            axm.scatter(
                ix,
                iy,
                s=8 + 145 * value / max_capture,
                facecolor="none",
                edgecolor=COLORS["orange"],
                linewidth=0.8,
                zorder=3,
            )
    axm.set_xticks(range(4), ["Q1", "Q2", "Q3", "Q4"])
    axm.set_yticks(range(4), ["Far Q4", "Q3", "Q2", "Near Q1"])
    axm.set_xlabel("AF resource quartile (low to high)")
    axm.set_ylabel("Nearest eligible storage distance")
    axm.set_xticks(np.arange(-0.5, 4, 1), minor=True)
    axm.set_yticks(np.arange(-0.5, 4, 1), minor=True)
    axm.grid(which="minor", color="white", linewidth=0.8)
    axm.tick_params(which="minor", bottom=False, left=False)
    panel_label(axm, "B")
    cbar = fig.colorbar(image, ax=axm, fraction=0.055, pad=0.04, ticks=[0, 0.5, 1])
    cbar.set_label("Mean terminal survival frequency", fontsize=6.5)
    cbar.ax.tick_params(labelsize=6.2, length=1.5)
    cbar.outline.set_linewidth(0.4)
    bubble_handles = [
        plt.scatter([], [], s=8 + 145 * value / max_capture, facecolor="none", edgecolor=COLORS["orange"], linewidth=0.8, label=f"{value} Mt")
        for value in (200, 500, 800)
    ]
    legend = axm.legend(
        handles=bubble_handles,
        title="Mean cumulative capture",
        title_fontsize=6.5,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.21),
        ncol=3,
        columnspacing=0.6,
        handletextpad=0.25,
        borderaxespad=0,
    )
    _legend_frame(legend)

    path = save_figure(fig, "fig4_spatial_suitability_conditional_priorities.png")
    plt.close(fig)
    return path


def make_fig5() -> Path:
    decomposition = pd.read_csv(SOURCE / "fig4_cost_decomposition_v2.csv")
    regret = pd.read_csv(SOURCE / "fig4_regret_intervals_v2.csv")

    fig = plt.figure(figsize=(7.48, 3.15))  # 190 x 80 mm
    gs = fig.add_gridspec(
        1,
        2,
        width_ratios=[0.92, 1.35],
        left=0.09,
        right=0.985,
        top=0.94,
        bottom=0.22,
        wspace=0.48,
    )

    ax = fig.add_subplot(gs[0])
    cumulative = 0.0
    for index, row in decomposition.iterrows():
        delta = float(row.delta_billion_cny)
        if row.step == "Total effect":
            bottom = min(0.0, delta)
            height = abs(delta)
            color = COLORS["ink"]
        else:
            bottom = min(cumulative, cumulative + delta)
            height = abs(delta)
            color = COLORS["orange"] if delta > 0 else COLORS["blue"]
        ax.bar(index, height, bottom=bottom, width=0.62, color=color, edgecolor="white", lw=0.35)
        ax.text(
            index,
            bottom + height + 0.11 if delta >= 0 else bottom - 0.11,
            f"{delta:+.2f}",
            ha="center",
            va="bottom" if delta >= 0 else "top",
            fontsize=6.7,
        )
        if row.step != "Total effect":
            cumulative += delta
            if index < len(decomposition) - 1:
                ax.plot([index + 0.31, index + 0.69], [cumulative, cumulative], color=COLORS["grey"], lw=0.65, ls=":")
    ax.axhline(0, color=COLORS["ink"], lw=0.7)
    ax.set_xticks(range(len(decomposition)), [label.replace(" ", "\n") for label in decomposition.step])
    ax.set_ylabel("Cost change relative to S1 (billion CNY)")
    ax.set_ylim(-3.25, 1.75)
    quiet_grid(ax)
    despine(ax)
    panel_label(ax, "A")

    ax = fig.add_subplot(gs[1])
    mapping = [
        ("S2 forward lock-in loss", "S2 forward lock-in", COLORS["blue"], True),
        ("S2 reverse planning regret", "S2 reverse regret", COLORS["blue"], True),
        ("S3 forward lock-in loss", "S3 forward lock-in", COLORS["orange"], False),
        ("S3 reverse planning regret", "S3 reverse regret", COLORS["orange"], False),
        ("Null control", "Null control", COLORS["grey"], True),
    ]
    ypos = np.arange(len(mapping))[::-1]
    for y, (source_label, _, color, filled) in zip(ypos, mapping):
        row = regret[regret.label.eq(source_label)].iloc[0]
        ax.plot(
            [row.lower_bound_billion_cny, row.upper_bound_billion_cny],
            [y, y],
            color=color,
            lw=1.7,
        )
        ax.plot(
            row.point_billion_cny,
            y,
            marker="D" if source_label != "Null control" else "o",
            ms=4.3,
            mfc=color if filled else "white",
            mec=color,
            mew=0.9,
            zorder=3,
        )
    ax.axvline(0, color=COLORS["ink"], lw=0.7, ls="--")
    ax.set_yticks(ypos, [label for _, label, _, _ in mapping])
    ax.set_xlabel("Fixed-path loss or planning regret (billion CNY)")
    ax.set_xlim(-0.5, 6.4)
    quiet_grid(ax, "x")
    despine(ax)
    panel_label(ax, "B")

    path = save_figure(fig, "fig5_turnover_suitability_feedback_identification.png")
    plt.close(fig)
    return path


def make_fig6() -> Path:
    swaps = pd.read_csv(SOURCE / "fig5_asset_swaps_v2.csv")
    overlap = pd.read_csv(SOURCE / "fig5_overlap_profile_v2.csv")

    fig = plt.figure(figsize=(7.48, 3.55))  # 190 x 90 mm
    gs = fig.add_gridspec(
        1,
        2,
        width_ratios=[0.95, 1.45],
        left=0.115,
        right=0.985,
        top=0.94,
        bottom=0.18,
        wspace=0.54,
    )

    ax = fig.add_subplot(gs[0])
    for group, color, marker in (
        ("Swap-in", COLORS["blue"], "o"),
        ("Swap-out", COLORS["gold"], "s"),
    ):
        subset = swaps[swaps.swap_group.eq(group)]
        sizes = 11 + 30 * (subset.capacity_t_day / swaps.capacity_t_day.max())
        ax.scatter(
            subset.af_resource_index,
            subset.nearest_storage_distance_km,
            s=sizes,
            c=color,
            marker=marker,
            alpha=0.78,
            edgecolor="white",
            linewidth=0.45,
            label=f"{group} (n={len(subset)})",
            zorder=3,
        )
        mx = subset.af_resource_index.median()
        my = subset.nearest_storage_distance_km.median()
        ax.plot([subset.af_resource_index.min(), subset.af_resource_index.max()], [my, my], color=color, lw=0.75, ls="--", alpha=0.85)
        ax.plot([mx, mx], [subset.nearest_storage_distance_km.min(), subset.nearest_storage_distance_km.max()], color=color, lw=0.75, ls="--", alpha=0.85)
    ax.set_xlabel("AF resource index")
    ax.set_ylabel("Storage distance (km)")
    ax.set_xlim(0, 1.0)
    ax.set_ylim(510, -10)
    quiet_grid(ax)
    despine(ax)
    panel_label(ax, "A")
    legend = ax.legend(loc="lower left")
    _legend_frame(legend)

    ax = fig.add_subplot(gs[1])
    metric_order = overlap[overlap.comparison.eq("S1 vs S2")].metric.tolist()
    y = np.arange(len(metric_order))[::-1]
    values = {
        comparison: subset.set_index("metric").reindex(metric_order).overlap.to_numpy()
        for comparison, subset in overlap.groupby("comparison")
    }
    for yy, metric in zip(y, metric_order):
        group = overlap[(overlap.comparison.eq("S1 vs S2")) & (overlap.metric.eq(metric))].iloc[0].metric_group
        if group == "Inherited stock":
            ax.axhspan(yy - 0.45, yy + 0.45, color=COLORS["grey_xlight"], zorder=0)
    ax.scatter(values["S1 vs S2"], y + 0.11, color=COLORS["blue"], s=23, marker="o", label="S1 vs S2", zorder=3)
    ax.scatter(values["S1 vs S3"], y - 0.11, facecolor="white", edgecolor=COLORS["orange"], linewidth=0.9, s=24, marker="s", label="S1 vs S3", zorder=3)
    ax.set_yticks(y, metric_order)
    ax.set_xlabel("Overlap with S1")
    ax.set_xlim(0, 1.02)
    ax.set_xticks(np.arange(0, 1.01, 0.2))
    quiet_grid(ax, "x")
    despine(ax)
    panel_label(ax, "B")
    legend = ax.legend(loc="lower left")
    _legend_frame(legend)

    ordered_groups = overlap[overlap.comparison.eq("S1 vs S2")].metric_group.tolist()
    for index in range(len(metric_order) - 1):
        if ordered_groups[index] != ordered_groups[index + 1]:
            boundary_y = (y[index] + y[index + 1]) / 2
            ax.axhline(boundary_y, color="#D2D2D2", lw=0.55)

    # The longest panel-B tick label extends well left of its axes.  Guard
    # against it entering the panel-A legend, which occurred in the previous
    # render despite both objects being individually inside the canvas.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    panel_b_labels = [
        label.get_window_extent(renderer)
        for label in ax.get_yticklabels()
        if label.get_visible() and label.get_text()
    ]
    if panel_b_labels and legend.get_window_extent(renderer).overlaps(Bbox.union(panel_b_labels)):
        raise RuntimeError("Fig. 6 layout collision: panel-A legend versus panel-B metric labels")

    path = save_figure(fig, "fig6_asset_reranking_ccs_amplification.png")
    plt.close(fig)
    return path


def make_fig7() -> Path:
    specificity = pd.read_csv(SOURCE / "fig6_planning_specificity_coverage_v2.csv")
    sensitivity = pd.read_csv(SOURCE / "figS8_corridor_threshold_sensitivity_v2.csv")

    fig = plt.figure(figsize=(7.48, 3.43))  # 190 x 87 mm
    gs = fig.add_gridspec(
        1,
        2,
        width_ratios=[1.22, 1.0],
        left=0.115,
        right=0.93,
        top=0.80,
        bottom=0.22,
        wspace=0.33,
    )

    levels = [
        "Stable terminal sites",
        "Recurrent storage node--types",
        "100-km opportunity families",
        "Exact plant--storage routes",
    ]
    x = np.arange(len(levels))
    offsets = {
        ("Full period", "Core scenarios"): -0.19,
        ("Full period", "Core + near-optimal"): -0.09,
        ("Late (2050--2060)", "Core scenarios"): 0.09,
        ("Late (2050--2060)", "Core + near-optimal"): 0.19,
    }
    ax = fig.add_subplot(gs[0])
    for window in ("Full period", "Late (2050--2060)"):
        for case_set in ("Core scenarios", "Core + near-optimal"):
            subset = (
                specificity[
                    specificity.window.eq(window) & specificity.case_set.eq(case_set)
                ]
                .set_index("planning_level")
                .reindex(levels)
            )
            filled = case_set == "Core scenarios"
            ax.scatter(
                x + offsets[(window, case_set)],
                subset.minimum_flow_coverage,
                s=24,
                marker=WINDOW_MARKERS[window],
                facecolor=WINDOW_COLORS[window] if filled else "white",
                edgecolor=WINDOW_COLORS[window],
                linewidth=0.8,
                zorder=3,
            )
    ax.set_xticks(
        x,
        [
            "Stable\nterminal sites",
            "Storage\nnode\u2013types",
            "100-km\nopportunity families",
            "Exact\nroutes",
        ],
    )
    ax.set_ylabel("Minimum captured-flow coverage")
    ax.set_ylim(-0.02, 0.86)
    quiet_grid(ax)
    despine(ax)
    panel_label(ax, "A")
    handles = [
        Line2D(
            [],
            [],
            marker=WINDOW_MARKERS[window],
            ls="",
            mfc=color,
            mec=color,
            ms=4.2,
            label=window.replace("--", "\u2013"),
        )
        for window, color in (
            (w, WINDOW_COLORS[w]) for w in ("Full period", "Late (2050--2060)")
        )
    ] + [
        Line2D([], [], marker="h", ls="", mfc=COLORS["ink"], mec=COLORS["ink"], ms=4.5, label="Core (filled)"),
        Line2D([], [], marker="h", ls="", mfc="white", mec=COLORS["ink"], ms=4.5, label="Core + near-opt. (open)"),
    ]

    heat_gs = gs[1].subgridspec(1, 2, wspace=0.12)
    heat_axes = [fig.add_subplot(heat_gs[0]), fig.add_subplot(heat_gs[1])]
    heat_cmap = mcolors.LinearSegmentedColormap.from_list(
        "coverage", ["#F7FAFC", COLORS["blue_light"], COLORS["blue"]]
    )
    window_specs = [
        ("full_2025_2060", "2025\u20132060"),
        ("late_2050_2060", "2050\u20132060"),
    ]
    image = None
    for index, (axh, (window_key, title)) in enumerate(zip(heat_axes, window_specs)):
        subset = sensitivity[sensitivity.window.eq(window_key)]
        grid = (
            subset.pivot(
                index="flow_threshold_mt",
                columns="endpoint_radius_km",
                values="min_case_flow_coverage",
            )
            .reindex(index=[20.0, 10.0, 5.0, 1.0], columns=[60, 100, 150])
        )
        image = axh.imshow(grid.to_numpy(), cmap=heat_cmap, vmin=0, vmax=0.6, aspect="auto")
        axh.set_xticks(range(3), [60, 100, 150])
        if index == 0:
            axh.set_yticks(range(4), [20, 10, 5, 1])
            axh.set_ylabel("Flow floor\n(Mt CO$_2$)", fontsize=8.6)
            panel_label(axh, "B")
        else:
            axh.set_yticks(range(4), [])
        axh.set_xlabel("Endpoint diameter (km)")
        axh.set_title(title, fontsize=6.7, pad=3)
        axh.set_xticks(np.arange(-0.5, 3, 1), minor=True)
        axh.set_yticks(np.arange(-0.5, 4, 1), minor=True)
        axh.grid(which="minor", color="white", linewidth=0.8)
        axh.tick_params(which="minor", bottom=False, left=False)
        reference_y = [20.0, 10.0, 5.0, 1.0].index(10.0)
        reference_x = [60, 100, 150].index(100)
        axh.add_patch(
            plt.Rectangle(
                (reference_x - 0.46, reference_y - 0.46),
                0.92,
                0.92,
                fill=False,
                edgecolor=COLORS["orange"],
                linewidth=1.0,
            )
        )
    cbar = fig.colorbar(image, ax=heat_axes, fraction=0.045, pad=0.025, ticks=[0, 0.3, 0.6])
    cbar.set_label("Minimum core-case captured-flow coverage", fontsize=6.4)
    cbar.ax.tick_params(labelsize=6.2, length=1.5)
    cbar.outline.set_linewidth(0.4)
    legend = fig.legend(
        handles=handles,
        ncol=5,
        loc="upper center",
        bbox_to_anchor=(0.53, 0.99),
        columnspacing=0.8,
        handletextpad=0.3,
    )
    _legend_frame(legend)

    path = save_figure(fig, "fig7_planning_object_robustness.png")
    plt.close(fig)
    return path


def make_fig8() -> Path:
    parameter = pd.read_csv(SOURCE / "fig7_parameter_regret_intervals_v2.csv")
    binding = pd.read_csv(SOURCE / "fig7_floor_binding_v2.csv")
    identity = pd.read_csv(SOURCE / "fig7_near_optimal_identity_v2.csv")
    fig = plt.figure(figsize=(7.48, 3.55))  # 190 x 90 mm
    outer = fig.add_gridspec(
        1,
        2,
        width_ratios=[1.12, 1.0],
        left=0.145,
        right=0.985,
        top=0.94,
        bottom=0.18,
        wspace=0.45,
    )
    left = outer[0].subgridspec(2, 1, height_ratios=[1.45, 0.85], hspace=0.34)

    ax = fig.add_subplot(left[0])
    parameter = parameter.reset_index(drop=True)
    y = np.arange(len(parameter))[::-1]
    for yy, row in zip(y, parameter.itertuples(index=False)):
        is_baseline = row.setting == "Minimum utilization = 0.40"
        is_lifetime = row.parameter_family == "Technical lifetime"
        color = COLORS["blue"] if is_baseline else COLORS["teal"] if is_lifetime else COLORS["grey"]
        ax.plot([row.lower_bn_cny, row.upper_bn_cny], [yy, yy], color=color, lw=1.7)
        ax.plot(
            row.point_bn_cny,
            yy,
            marker="D",
            ms=4.3,
            mfc=color if is_baseline or is_lifetime else "white",
            mec=color,
            mew=0.8,
            zorder=3,
        )
    ax.axvline(0, color=COLORS["ink"], lw=0.7, ls="--")
    labels = (
        parameter.setting
        .str.replace("Minimum utilization = ", "u_min = ", regex=False)
        .str.replace("Technical lifetime = 35 y", "Lifetime = 35 y", regex=False)
    )
    ax.set_yticks(y, labels)
    ax.set_xlabel("Fixed-turnover loss (billion CNY)")
    ax.set_xlim(-0.1, 4.9)
    quiet_grid(ax, "x")
    despine(ax)
    panel_label(ax, "A")

    axb = fig.add_subplot(left[1])
    year_styles = [
        (2035, COLORS["grey"], "s"),
        (2040, COLORS["teal"], "o"),
        (2045, COLORS["orange"], "D"),
    ]
    for year, color, marker in year_styles:
        subset = binding[binding.year.eq(year)].sort_values("minimum_operating_utilization")
        axb.plot(
            subset.minimum_operating_utilization,
            subset.share_operating_lines_at_floor,
            color=color,
            marker=marker,
            label=str(year),
        )
    axb.set_xlabel("Minimum operating utilization")
    axb.set_ylabel("Share at floor")
    axb.set_xticks(sorted(binding.minimum_operating_utilization.unique()))
    axb.set_ylim(0, 1.04)
    axb.set_yticks([0, 0.5, 1.0])
    axb.set_xlim(0.185, 0.535)
    label_offsets = {2035: 0.035, 2040: -0.025, 2045: 0.0}
    for year, color, _ in year_styles:
        subset = binding[binding.year.eq(year)].sort_values("minimum_operating_utilization")
        axb.text(
            0.507,
            float(subset.share_operating_lines_at_floor.iloc[-1]) + label_offsets[year],
            str(year),
            color=color,
            fontsize=6.1,
            ha="left",
            va="center",
        )
    quiet_grid(axb)
    despine(axb)

    ax = fig.add_subplot(outer[1])
    label_order = [
        "S1 farthest full-path",
        "S1 farthest terminal",
        "S2 closest terminal",
        "S3 closest terminal",
    ]
    y = np.arange(len(label_order))[::-1]
    for metric, color, marker, offset in (
        ("Terminal-site identity", COLORS["blue"], "o", 0.09),
        ("Route-flow identity", COLORS["orange"], "D", -0.09),
    ):
        subset = identity[identity.metric.eq(metric)].set_index("label").reindex(label_order)
        ax.scatter(
            subset.overlap_vs_s1,
            y + offset,
            color=color,
            marker=marker,
            s=24,
            label=metric,
            zorder=3,
        )
    ax.axhspan(1.55, 3.45, color=COLORS["grey_xlight"], zorder=0)
    ax.axhline(1.5, color="#D2D2D2", lw=0.55)
    ax.set_yticks(y, label_order)
    ax.set_xlabel("Overlap with S1")
    ax.set_xlim(0.65, 1.01)
    ax.set_xticks([0.7, 0.8, 0.9, 1.0])
    quiet_grid(ax, "x")
    despine(ax)
    panel_label(ax, "B")
    legend = ax.legend(loc="upper left")
    _legend_frame(legend)

    path = save_figure(fig, "SI/figS10_parameter_identity_robustness.png")
    plt.close(fig)
    return path


def main() -> None:
    outputs = [
        make_si_national_overview(),
        make_fig4(),
        make_fig5(),
        make_fig6(),
        make_fig7(),
        make_fig8(),
    ]
    for path in outputs:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
