#!/usr/bin/env python3
"""Render SI diagnostics transferred out of the redesigned main figures.

The script reads only audited figure-source CSVs produced by
``prepare_main_figure_data_2026_v2.py`` and the province basemap.
"""

from __future__ import annotations

import math

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import PatchCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from figure_system_2026_common import (
    COLORS,
    SOURCE,
    apply_style,
    despine,
    panel_label,
    quiet_grid,
    save_figure,
)
from make_main_figures_2026_v2 import (
    SOUTH_BUFFER,
    _add_south_china_sea_inset,
    _hex_patch,
    _legend_frame,
    _load_basemap,
    _project,
)


apply_style()


def make_figs7():
    assets = pd.read_csv(SOURCE / "fig3_spatial_assets_v2.csv")
    hexes = pd.read_csv(SOURCE / "fig3_af_hex_v2.csv")
    availability = pd.read_csv(SOURCE / "fig3_storage_availability_v2.csv")
    nodes = pd.read_csv(SOURCE / "fig3_storage_nodes_v2.csv")
    corridors = pd.read_csv(SOURCE / "figS7_all_corridor_opportunities_v2.csv")
    china, full = _load_basemap()

    # Taller canvas: both panels reserve the same southern open-water strip as
    # main Fig. 4 so the South-China-Sea inset sits over clear sea instead of
    # covering the Fujian/Taiwan/Guangdong coast. The height keeps the panel
    # cells matched to the buffered map aspect so no side whitespace appears.
    fig, axes = plt.subplots(1, 2, figsize=(7.48, 4.35))
    fig.subplots_adjust(left=0.015, right=0.985, top=0.94, bottom=0.10, wspace=0.045)
    minx, miny, maxx, maxy = china.total_bounds
    miny = miny - SOUTH_BUFFER * (maxy - miny)

    ax = axes[0]
    china.plot(ax=ax, color="#FBFBFB", edgecolor="#333333", linewidth=0.30, zorder=0)
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "af_access_si", ["#FFFDF6", COLORS["gold_light"], COLORS["gold"]]
    )
    norm = mcolors.Normalize(vmin=0, vmax=1)
    patches = [
        _hex_patch(row.center_x, row.center_y, row.hex_radius_m)
        for row in hexes.itertuples(index=False)
    ]
    collection = PatchCollection(
        patches,
        array=hexes.af_resource_median.to_numpy(),
        cmap=cmap,
        norm=norm,
        edgecolor="none",
        alpha=0.72,
        zorder=0.8,
    )
    ax.add_collection(collection)
    plant_pts = _project(assets.longitude, assets.latitude)
    ax.scatter(plant_pts.x, plant_pts.y, s=1.2, color=COLORS["ink"], alpha=0.25, lw=0, zorder=2)
    cax = ax.inset_axes([0.04, 0.035, 0.29, 0.025])
    cbar = fig.colorbar(collection, cax=cax, orientation="horizontal", ticks=[0, 0.5, 1])
    cbar.set_label("AF resource index", fontsize=6.5, labelpad=1)
    cbar.ax.tick_params(labelsize=6.2, length=1.5, pad=1)
    cbar.outline.set_linewidth(0.4)
    panel_label(ax, "A")

    ax = axes[1]
    china.plot(ax=ax, color="#FBFBFB", edgecolor="#333333", linewidth=0.30, zorder=0)
    availability_pts = _project(availability.longitude, availability.latitude)
    ax.scatter(
        availability_pts.x,
        availability_pts.y,
        s=0.9,
        color=COLORS["teal"],
        alpha=0.16,
        lw=0,
        zorder=0.8,
    )
    for row in corridors.itertuples(index=False):
        pts = _project([row.origin_lon, row.sink_lon], [row.origin_lat, row.sink_lat])
        width = 0.4 + 0.75 * math.sqrt(
            row.min_flow_mt_core_cases / corridors.min_flow_mt_core_cases.max()
        )
        ax.plot(pts.x, pts.y, color=COLORS["blue"], alpha=0.58, lw=width, zorder=2)

    recurrent = nodes[nodes.flow_scenario_count.eq(5)].copy()
    node_pts = _project(recurrent.longitude, recurrent.latitude)
    recurrent["x"] = node_pts.x.to_numpy()
    recurrent["y"] = node_pts.y.to_numpy()
    for storage_type, marker in (("DSA", "o"), ("EOR", "^")):
        subset = recurrent[recurrent.storage_type.eq(storage_type)]
        ax.scatter(
            subset.x,
            subset.y,
            s=6.0,
            marker=marker,
            facecolor="white",
            edgecolor=COLORS["teal"],
            linewidth=0.45,
            alpha=0.86,
            zorder=3,
        )
    handles = [
        Line2D([], [], marker="o", ls="", mfc="white", mec=COLORS["teal"], ms=4, label="Recurrent DSA node--type"),
        Line2D([], [], marker="^", ls="", mfc="white", mec=COLORS["teal"], ms=4.3, label="Recurrent EOR node--type"),
        Line2D([], [], color=COLORS["blue"], lw=1.1, label="All recurrent 100-km opportunity families"),
    ]
    legend = ax.legend(handles=handles, loc="lower left", ncol=1, handletextpad=0.35)
    _legend_frame(legend)
    panel_label(ax, "B")
    _add_south_china_sea_inset(ax, full)

    for ax in axes:
        ax.set_xlim(minx, maxx)
        ax.set_ylim(miny, maxy)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    path = save_figure(fig, "SI/figS7_spatial_layer_diagnostics.png")
    plt.close(fig)
    return path


def make_figs8():
    counts = pd.read_csv(SOURCE / "figS8_storage_recurrence_counts_v2.csv")
    sensitivity = pd.read_csv(SOURCE / "figS8_corridor_threshold_sensitivity_v2.csv")

    counts["class"] = np.select(
        [
            counts.storage_type.eq("DSA") & ~counts.is_offshore.astype(bool),
            counts.storage_type.eq("EOR") & ~counts.is_offshore.astype(bool),
            counts.storage_type.eq("DSA") & counts.is_offshore.astype(bool),
            counts.storage_type.eq("EOR") & counts.is_offshore.astype(bool),
        ],
        ["Onshore DSA", "Onshore EOR", "Offshore DSA", "Offshore EOR"],
        default="Other",
    )
    class_order = ["Onshore DSA", "Onshore EOR", "Offshore DSA", "Offshore EOR"]
    class_colors = {
        "Onshore DSA": COLORS["teal"],
        "Onshore EOR": COLORS["blue"],
        "Offshore DSA": COLORS["gold"],
        "Offshore EOR": COLORS["orange"],
    }
    pivot = (
        counts.pivot_table(
            index="flow_scenario_count",
            columns="class",
            values="node_type_count",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(index=[1, 2, 3, 4, 5], columns=class_order, fill_value=0)
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.48, 3.23))
    fig.subplots_adjust(left=0.075, right=0.985, top=0.92, bottom=0.20, wspace=0.34)

    ax = axes[0]
    bottom = np.zeros(len(pivot))
    for cls in class_order:
        values = pivot[cls].to_numpy()
        ax.bar(
            pivot.index,
            values,
            bottom=bottom,
            width=0.68,
            color=class_colors[cls],
            edgecolor="white",
            lw=0.35,
            label=cls,
        )
        bottom += values
    ax.set_xlabel("Number of core scenarios using the node--type")
    ax.set_ylabel("Storage node--type count")
    ax.set_xticks([1, 2, 3, 4, 5])
    quiet_grid(ax)
    despine(ax)
    panel_label(ax, "A")
    legend = ax.legend(loc="upper left", ncol=2, columnspacing=0.7, handletextpad=0.3)
    _legend_frame(legend)

    ax = axes[1]
    radius_colors = {60: COLORS["grey"], 100: COLORS["blue"], 150: COLORS["orange"]}
    for radius, color in radius_colors.items():
        for window, ls, marker in (
            ("full_2025_2060", "-", "o"),
            ("late_2050_2060", "--", "s"),
        ):
            subset = sensitivity[
                sensitivity.endpoint_radius_km.eq(radius)
                & sensitivity.window.eq(window)
            ].sort_values("flow_threshold_mt")
            ax.plot(
                subset.flow_threshold_mt,
                subset.min_case_flow_coverage,
                color=color,
                ls=ls,
                marker=marker,
                mfc=color if window == "full_2025_2060" else "white",
                mec=color,
                mew=0.8,
            )
    ax.set_xlabel("Minimum cumulative family flow (Mt)")
    ax.set_ylabel("Minimum cross-scenario captured-flow coverage")
    ax.set_xticks([1, 5, 10, 20])
    ax.set_ylim(0, 0.66)
    quiet_grid(ax)
    despine(ax)
    panel_label(ax, "B")
    handles = [
        Line2D([], [], color=color, marker="o", label=f"{radius} km")
        for radius, color in radius_colors.items()
    ] + [
        Line2D([], [], color=COLORS["ink"], ls="-", marker="o", label="Full period"),
        Line2D([], [], color=COLORS["ink"], ls="--", marker="s", mfc="white", label="2050--2060"),
    ]
    legend = ax.legend(handles=handles, loc="lower left", ncol=2, columnspacing=0.7, handletextpad=0.3)
    _legend_frame(legend)

    path = save_figure(fig, "SI/figS8_storage_corridor_diagnostics.png")
    plt.close(fig)
    return path


LIFECYCLE_COLORS = {
    "inherited": "#335C81",
    "renewed": "#58A88A",
    "inactive": "#D9D9D9",
}


def make_figs9():
    """SI Fig. S9 — province-ranked capacity-turnover and capture profiles.

    Reads only the audited advanced-figure interfaces under ``SOURCE`` (the
    same canonical tables behind main Figs. 2--3), so the lifecycle palette
    matches main Fig. 2. Explanatory text lives in the SI caption, not in
    the figure (AGENTS.md).
    """
    province_year = pd.read_csv(SOURCE / "advanced_interfaces/province_year_interface.csv")
    metrics = pd.read_csv(SOURCE / "advanced_interfaces/province_mechanism_metrics.csv")

    order = metrics.sort_values("province_sort_index")
    meta = order.set_index("province_en")

    fig, axes = plt.subplots(5, 6, figsize=(7.48, 5.75), sharex=True, sharey=True)
    # Wide wspace keeps the compact year tick labels ("25 45 60") of adjacent
    # bottom-row panels from running together; right=0.99 keeps the last "60"
    # inside the 190-mm export boundary.
    fig.subplots_adjust(left=0.062, right=0.99, top=0.972, bottom=0.105, wspace=0.20, hspace=0.34)
    for province_en, ax in zip(order["province_en"], axes.flat):
        data = province_year[province_year["province_en"].eq(province_en)].sort_values("year")
        ax.stackplot(
            data["year"],
            data["inherited_operating_capacity_share"],
            data["renewed_operating_capacity_share"],
            data["inactive_capacity_share"],
            colors=[
                LIFECYCLE_COLORS["inherited"],
                LIFECYCLE_COLORS["renewed"],
                LIFECYCLE_COLORS["inactive"],
            ],
            linewidth=0,
        )
        ax.plot(
            data["year"],
            data["commercial_capture_fraction_of_gross"],
            color=COLORS["orange"],
            lw=1.0,
            solid_capstyle="round",
        )
        capacity = float(meta.loc[province_en, "inherited_capacity_mt_y"])
        ax.set_title(f"{province_en} · {capacity:.0f} Mt", loc="left", fontsize=6.5, pad=1.6)
        ax.set_ylim(0, 1)
        ax.set_xlim(2025, 2060)
        ax.set_xticks([2025, 2045, 2060], ["25", "45", "60"])
        ax.set_yticks([0, 0.5, 1], ["0", "50", "100"])
        ax.grid(axis="y", color="#FFFFFF", lw=0.35, alpha=0.8)
        ax.tick_params(length=0, pad=1)
        ax.spines[:].set_visible(False)

    fig.text(
        0.012,
        0.53,
        "Capacity share / capture fraction (%)",
        rotation=90,
        rotation_mode="anchor",
        va="center",
        fontsize=7,
    )
    fig.text(0.53, 0.043, "Modeled period (20xx)", ha="center", fontsize=7)
    handles = [
        Patch(facecolor=LIFECYCLE_COLORS["inherited"], label="Inherited operation"),
        Patch(facecolor=LIFECYCLE_COLORS["renewed"], label="Same-site renewal"),
        Patch(facecolor=LIFECYCLE_COLORS["inactive"], label="Inactive / exited"),
        Line2D([], [], color=COLORS["orange"], lw=1.2, label="Commercial capture / gross direct emissions"),
    ]
    fig.legend(handles=handles, ncol=4, frameon=False, loc="lower center", bbox_to_anchor=(0.53, 0.008))

    path = save_figure(fig, "SI/figS9_province_lifecycle_capture_small_multiples.png")
    plt.close(fig)
    return path


def main() -> None:
    for path in (make_figs7(), make_figs8(), make_figs9()):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
