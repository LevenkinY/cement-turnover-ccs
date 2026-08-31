#!/usr/bin/env python3
"""Render layout-development prototypes from the audited figure interfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, ListedColormap, PowerNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.transforms import Bbox
import numpy as np
import pandas as pd
from PIL import Image, ImageEnhance, ImageOps


MM = 1 / 25.4
YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
EXPORT_SUBMISSION_FORMATS = False
STATE_ORDER = ["inactive", "inherited_operating", "renewed_operating"]
STATE_COLORS = {
    "inactive": "#D9D9D9",
    "inherited_operating": "#335C81",
    "renewed_operating": "#58A88A",
}
TIER_ORDER = ["stable_core", "conditional_asset", "sensitive_margin", "not_terminal_candidate"]
TIER_LABELS = {
    "stable_core": "Stable",
    "conditional_asset": "Conditional",
    "sensitive_margin": "Sensitive",
    "not_terminal_candidate": "Other",
}
TIER_COLORS = {
    "stable_core": "#1F4E79",
    "conditional_asset": "#E69F00",
    "sensitive_margin": "#8F3F71",
    "not_terminal_candidate": "#BDBDBD",
}
REGION_ORDER = ["North", "Northeast", "East", "Central", "South", "Southwest", "Northwest"]
PROVISIONAL = "PROVISIONAL — LAYOUT DEVELOPMENT · HISTORICAL PRE-CORRECTION RESULTS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument(
        "--main-figure-names",
        action="store_true",
        help="Render only the approved main-text atlas and province matrix with final stems.",
    )
    parser.add_argument(
        "--submission-formats",
        action="store_true",
        help="Also export PDF, SVG and lossless TIFF copies for manuscript delivery.",
    )
    return parser.parse_args()


def configure_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "Arial",
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
            "savefig.dpi": 600,
            "font.size": 7.0,
            "axes.titlesize": 7.5,
            "axes.labelsize": 7.0,
            "xtick.labelsize": 6.5,
            "ytick.labelsize": 6.5,
            "legend.fontsize": 6.5,
            "axes.linewidth": 0.55,
            "xtick.major.width": 0.5,
            "ytick.major.width": 0.5,
            "xtick.major.size": 2.2,
            "ytick.major.size": 2.2,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
        }
    )


def panel_label(ax: mpl.axes.Axes, label: str, x: float = -0.10, y: float = 1.04) -> None:
    ax.text(x, y, label, transform=ax.transAxes, fontsize=9.0, fontweight="bold", va="bottom", ha="left")


def evidence_banner(fig: mpl.figure.Figure, line_count: int, evidence_status: str) -> None:
    if evidence_status == "historical_layout_only":
        fig.text(
            0.5,
            0.993,
            f"{PROVISIONAL} · n = {line_count:,} inherited lines",
            ha="center",
            va="top",
            fontsize=7.1,
            color="#A51C30",
            fontweight="bold",
        )


def save_png(fig: mpl.figure.Figure, path: Path, dpi: int, tight: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if tight:
        fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.035)
    else:
        fig.savefig(path, dpi=dpi)
    if EXPORT_SUBMISSION_FORMATS:
        for suffix in (".pdf", ".svg", ".tiff"):
            extra_path = path.with_suffix(suffix)
            save_kwargs = {"bbox_inches": "tight", "pad_inches": 0.035} if tight else {}
            if suffix == ".tiff":
                save_kwargs.update({"dpi": dpi, "pil_kwargs": {"compression": "tiff_lzw"}})
            fig.savefig(extra_path, **save_kwargs)
    plt.close(fig)


def build_qa_previews(path: Path, output_dir: Path) -> list[Path]:
    image = Image.open(path).convert("RGB")
    reduced_width = max(1, int(round(image.width * 85 / 190)))
    reduced_height = max(1, int(round(image.height * 85 / 190)))
    reduced = image.resize((reduced_width, reduced_height), Image.Resampling.LANCZOS)
    reduced_path = output_dir / f"{path.stem}_85mm_stress.png"
    reduced.save(reduced_path, dpi=(600, 600))
    grey = ImageOps.grayscale(image)
    grey = ImageEnhance.Contrast(grey).enhance(1.05)
    grey_path = output_dir / f"{path.stem}_greyscale.png"
    grey.save(grey_path, dpi=(600, 600))
    return [reduced_path, grey_path]


def plot_atlas(
    plant_year: pd.DataFrame,
    plant_static: pd.DataFrame,
    output: Path,
    dpi: int,
    evidence_status: str,
) -> Path:
    line_count = plant_static["plant_id"].nunique()
    ordered_ids = plant_static.sort_values("plant_sort_index")["plant_id"].tolist()
    row_lookup = {plant_id: row for row, plant_id in enumerate(ordered_ids)}
    state_codes = {name: index for index, name in enumerate(STATE_ORDER)}

    state = np.full((line_count, len(YEARS)), np.nan)
    residual = np.zeros_like(state, dtype=float)
    for row in plant_year.itertuples(index=False):
        r = row_lookup[row.plant_id]
        c = YEARS.index(row.year)
        state[r, c] = state_codes[row.lifecycle_state]
        residual[r, c] = row.residual_after_commercial_capture_mt_y

    fig = plt.figure(figsize=(190 * MM, 150 * MM))
    grid = fig.add_gridspec(
        3,
        3,
        height_ratios=[3.15, 1.02, 0.19],
        width_ratios=[1.10, 0.94, 0.045],
        left=0.10,
        right=0.935,
        top=0.945,
        bottom=0.055,
        hspace=0.38,
        wspace=0.28,
    )
    ax_state = fig.add_subplot(grid[0, 0])
    ax_residual = fig.add_subplot(grid[0, 1], sharey=ax_state)
    ax_capacity = fig.add_subplot(grid[1, 0])
    # Retain the full modeled horizon while compressing the pre-capture interval.
    # The explicit break prevents the unequal horizontal scales from being read as continuous.
    tier_grid = grid[1, 1:].subgridspec(1, 2, width_ratios=[0.20, 0.80], wspace=0.05)
    ax_tier_early = fig.add_subplot(tier_grid[0, 0])
    ax_tier_late = fig.add_subplot(tier_grid[0, 1], sharey=ax_tier_early)
    ax_residual_colorbar = fig.add_subplot(grid[0, 2])
    ax_lifecycle_legend = fig.add_subplot(grid[2, 0])
    ax_tier_legend = fig.add_subplot(grid[2, 1:])

    state_map = ListedColormap([STATE_COLORS[name] for name in STATE_ORDER])
    image_args = dict(aspect="auto", interpolation="nearest", origin="upper", extent=(-0.5, 7.5, line_count - 0.5, -0.5))
    ax_state.imshow(state, cmap=state_map, vmin=-0.5, vmax=2.5, **image_args)
    residual_cmap = LinearSegmentedColormap.from_list("residual", ["#FFFFFF", "#DDD1E7", "#6F2C7F"])
    residual_positive = residual[residual > 0]
    residual_vmax = float(np.quantile(residual_positive, 0.995)) if residual_positive.size else 1.0
    im_residual = ax_residual.imshow(
        residual, cmap=residual_cmap, norm=PowerNorm(gamma=0.50, vmin=0, vmax=residual_vmax, clip=True), **image_args
    )

    for ax, title in [
        (ax_state, "Lifecycle state"),
        (ax_residual, "Residual direct emissions"),
    ]:
        ax.set_title(title, pad=4)
        ax.set_xticks(
            range(len(YEARS)),
            [str(year) for year in YEARS],
            rotation=45,
            ha="right",
            rotation_mode="anchor",
        )
        ax.tick_params(axis="x", length=0)
        ax.spines[:].set_visible(False)

    tier_boundaries = []
    tier_midpoints = []
    for tier in TIER_ORDER:
        rows = plant_static.loc[plant_static["asset_tier"].eq(tier), "plant_sort_index"]
        if len(rows):
            tier_midpoints.append((tier, (rows.min() + rows.max()) / 2))
            tier_boundaries.append(rows.max() + 0.5)
    for boundary in tier_boundaries[:-1]:
        for ax in [ax_state, ax_residual]:
            ax.axhline(boundary, color="white", lw=0.55, alpha=0.95)
    ax_state.set_yticks([mid for _, mid in tier_midpoints], [TIER_LABELS[tier] for tier, _ in tier_midpoints])
    ax_state.set_ylabel("Inherited lines")
    plt.setp(ax_residual.get_yticklabels(), visible=False)
    ax_residual.tick_params(axis="y", length=0)

    cbar_residual = fig.colorbar(
        im_residual,
        cax=ax_residual_colorbar,
        orientation="vertical",
    )
    cbar_residual.set_label("Mt CO2 per year per line\n(square-root scale)", labelpad=4)
    cbar_residual.ax.tick_params(labelsize=5.8, length=1.8)

    panel_label(ax_state, "A")
    panel_label(ax_residual, "B")

    state_capacity = (
        plant_year.groupby(["year", "lifecycle_state"], as_index=False)["capacity_mt_y"].sum()
        .pivot(index="year", columns="lifecycle_state", values="capacity_mt_y")
        .reindex(index=YEARS, columns=STATE_ORDER, fill_value=0.0)
        .fillna(0.0)
    )
    denominator = state_capacity.sum(axis=1)
    shares = state_capacity.div(denominator, axis=0)
    ax_capacity.stackplot(
        YEARS,
        [shares[name] for name in STATE_ORDER],
        colors=[STATE_COLORS[name] for name in STATE_ORDER],
        linewidth=0,
    )
    inherited_2025_capacity = float(
        plant_year.loc[plant_year["year"].eq(2025), "capacity_mt_y"].sum()
    )
    production_share = (
        plant_year.groupby("year")["production_mt_y"].sum().reindex(YEARS)
        / inherited_2025_capacity
    )
    ax_capacity.plot(
        YEARS,
        production_share,
        color="#202020",
        marker="o",
        markersize=2.5,
        linewidth=1.0,
        zorder=4,
    )
    ax_capacity.set_ylim(0, 1)
    ax_capacity.set_yticks([0, 0.5, 1], ["0", "50", "100"])
    ax_capacity.set_ylabel("Inherited capacity (%)")
    ax_capacity.set_xticks(YEARS)
    ax_capacity.set_title("Capacity-weighted lifecycle margin", loc="left", pad=4)
    ax_capacity.spines[["top", "right"]].set_visible(False)
    panel_label(ax_capacity, "C", x=-0.065, y=1.03)
    production_handle = Line2D(
        [0], [0], color="#202020", marker="o", markersize=2.5, lw=1.0,
        label="Production"
    )
    prod_legend = ax_capacity.legend(
        handles=[production_handle],
        loc="upper left",
        frameon=True,
        framealpha=0.92,
        borderaxespad=0.3,
        handlelength=1.4,
        handletextpad=0.4,
        labelspacing=0.3,
    )
    prod_legend.get_frame().set_facecolor("white")
    prod_legend.get_frame().set_edgecolor("#D5D5D5")
    prod_legend.get_frame().set_linewidth(0.45)

    tier_capture = (
        plant_year.groupby(["year", "asset_tier"], as_index=False)["commercial_capture_mt_y"].sum()
        .pivot(index="year", columns="asset_tier", values="commercial_capture_mt_y")
        .reindex(index=YEARS, columns=TIER_ORDER, fill_value=0.0)
        .fillna(0.0)
    )
    early_capture_years = [year for year in YEARS if year <= 2040]
    late_capture_years = [year for year in YEARS if year >= 2040]
    for axis, plotted_years in [
        (ax_tier_early, early_capture_years),
        (ax_tier_late, late_capture_years),
    ]:
        axis.stackplot(
            plotted_years,
            [tier_capture.loc[plotted_years, tier] for tier in TIER_ORDER],
            colors=[TIER_COLORS[tier] for tier in TIER_ORDER],
            linewidth=0,
        )
        axis.spines["top"].set_visible(False)
    ax_tier_early.set_xlim(2025, 2040)
    ax_tier_early.set_xticks([2025])
    ax_tier_early.set_ylabel("Commercial capture\n(Mt CO2 per year)")
    ax_tier_early.set_title("Capture responsibility by asset tier", loc="left", pad=4)
    ax_tier_early.spines["right"].set_visible(False)
    ax_tier_late.set_xlim(2040, 2060)
    ax_tier_late.set_xticks(late_capture_years)
    ax_tier_late.spines["left"].set_visible(False)
    ax_tier_late.spines["right"].set_visible(False)
    ax_tier_late.tick_params(axis="y", left=False, labelleft=False)
    break_size = 0.025
    break_kwargs = {"color": "#1A1A1A", "clip_on": False, "lw": 0.7}
    ax_tier_early.plot(
        (1 - break_size, 1 + break_size),
        (-break_size, +break_size),
        transform=ax_tier_early.transAxes,
        **break_kwargs,
    )
    ax_tier_late.plot(
        (-break_size, +break_size),
        (-break_size, +break_size),
        transform=ax_tier_late.transAxes,
        **break_kwargs,
    )
    panel_label(ax_tier_early, "D", x=-0.27, y=1.03)

    lifecycle_legend = [
        Patch(facecolor=STATE_COLORS["inherited_operating"], label="Inherited operation"),
        Patch(facecolor=STATE_COLORS["renewed_operating"], label="Same-site renewal"),
        Patch(facecolor=STATE_COLORS["inactive"], label="Inactive / exited"),
    ]
    tier_legend = [Patch(facecolor=TIER_COLORS[tier], label=TIER_LABELS[tier]) for tier in TIER_ORDER]
    ax_lifecycle_legend.axis("off")
    ax_tier_legend.axis("off")
    lifecycle_legend_artist = ax_lifecycle_legend.legend(
        handles=lifecycle_legend,
        loc="center left",
        ncol=3,
        frameon=False,
        borderaxespad=0,
        handlelength=1.4,
        columnspacing=1.2,
    )
    tier_legend_artist = ax_tier_legend.legend(
        handles=tier_legend,
        loc="center right",
        ncol=4,
        frameon=False,
        borderaxespad=0,
        handlelength=1.4,
        columnspacing=1.0,
    )
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    collision_pairs = [
        (
            "Lifecycle legend versus panel c",
            lifecycle_legend_artist.get_window_extent(renderer),
            ax_capacity.get_tightbbox(renderer),
        ),
        (
            "Tier legend versus panel d",
            tier_legend_artist.get_window_extent(renderer),
            Bbox.union(
                [
                    ax_tier_early.get_tightbbox(renderer),
                    ax_tier_late.get_tightbbox(renderer),
                ]
            ),
        ),
    ]
    residual_x_labels = [
        label.get_window_extent(renderer)
        for label in ax_residual.get_xticklabels()
        if label.get_visible() and label.get_text()
    ]
    if residual_x_labels:
        collision_pairs.append(
            (
                "Panel b year labels versus colour scale",
                Bbox.union(residual_x_labels),
                ax_residual_colorbar.get_window_extent(renderer),
            )
        )
    collisions = [name for name, first, second in collision_pairs if first.overlaps(second)]
    if collisions:
        raise RuntimeError("Atlas layout collision: " + "; ".join(collisions))
    evidence_banner(fig, line_count, evidence_status)
    save_png(fig, output, dpi, tight=False)
    return output


def _province_order(metrics: pd.DataFrame) -> list[str]:
    return metrics.sort_values("province_sort_index")["province"].tolist()


def plot_ranked_province_multiples(
    province_year: pd.DataFrame,
    metrics: pd.DataFrame,
    line_count: int,
    output: Path,
    dpi: int,
    evidence_status: str,
) -> Path:
    order = _province_order(metrics)
    metadata = metrics.set_index("province")
    fig, axes = plt.subplots(5, 6, figsize=(190 * MM, 150 * MM), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.88, bottom=0.12, wspace=0.12, hspace=0.30)
    for index, (province, ax) in enumerate(zip(order, axes.flat)):
        data = province_year[province_year["province"].eq(province)].sort_values("year")
        ax.stackplot(
            data["year"],
            data["inherited_operating_capacity_share"],
            data["renewed_operating_capacity_share"],
            data["inactive_capacity_share"],
            colors=[STATE_COLORS["inherited_operating"], STATE_COLORS["renewed_operating"], STATE_COLORS["inactive"]],
            linewidth=0,
        )
        ax.plot(data["year"], data["commercial_capture_fraction_of_gross"], color="#D55E00", lw=0.85)
        capacity = metadata.loc[province, "inherited_capacity_mt_y"]
        title = f"{metadata.loc[province, 'province_en']}  {capacity:.0f}"
        ax.set_title(title, loc="left", fontsize=6.3, pad=1.5)
        ax.set_ylim(0, 1)
        ax.set_xlim(2025, 2060)
        ax.set_xticks([2025, 2045, 2060], ["25", "45", "60"])
        ax.set_yticks([0, 0.5, 1], ["0", "50", "100"])
        ax.grid(axis="y", color="#FFFFFF", lw=0.35, alpha=0.8)
        ax.tick_params(length=0, pad=1)
        ax.spines[:].set_visible(False)
    for ax in axes.flat[len(order) :]:
        ax.axis("off")
    fig.text(
        0.01,
        0.51,
        "Capacity share / capture fraction (%)",
        rotation=90,
        rotation_mode="anchor",
        va="center",
        fontsize=7,
    )
    fig.text(0.51, 0.075, "Modeled period (20xx)", ha="center", fontsize=7)
    fig.text(0.06, 0.93, "Province-ranked lifecycle and capture profiles", ha="left", va="top", fontsize=8.2, fontweight="bold")
    legend = [
        Patch(facecolor=STATE_COLORS["inherited_operating"], label="Inherited operation"),
        Patch(facecolor=STATE_COLORS["renewed_operating"], label="Same-site renewal"),
        Patch(facecolor=STATE_COLORS["inactive"], label="Inactive / exited"),
        Line2D([0], [0], color="#D55E00", lw=1.1, label="Commercial capture / gross direct emissions"),
    ]
    fig.legend(handles=legend, ncol=4, frameon=False, loc="lower center", bbox_to_anchor=(0.53, 0.018))
    evidence_banner(fig, line_count, evidence_status)
    # Preserve the declared 190-mm canvas for the publication figure.  Tight
    # cropping previously reduced the delivered width to about 168 mm.
    save_png(fig, output, dpi, tight=False)
    return output


def plot_region_multiples(
    region_year: pd.DataFrame,
    line_count: int,
    output: Path,
    dpi: int,
    evidence_status: str,
) -> Path:
    fig, axes = plt.subplots(2, 4, figsize=(190 * MM, 92 * MM), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.88, bottom=0.22, wspace=0.16, hspace=0.28)
    for region, ax in zip(REGION_ORDER, axes.flat):
        data = region_year[region_year["macro_region"].eq(region)].sort_values("year")
        ax.stackplot(
            data["year"],
            data["inherited_operating_capacity_share"],
            data["renewed_operating_capacity_share"],
            data["inactive_capacity_share"],
            colors=[STATE_COLORS["inherited_operating"], STATE_COLORS["renewed_operating"], STATE_COLORS["inactive"]],
            linewidth=0,
        )
        ax.plot(data["year"], data["commercial_capture_fraction_of_gross"], color="#D55E00", lw=1.05)
        ax.set_title(region, loc="left", fontsize=7.2, pad=2)
        ax.set_ylim(0, 1)
        ax.set_xlim(2025, 2060)
        ax.set_xticks([2025, 2045, 2060])
        ax.set_yticks([0, 0.5, 1], ["0", "50", "100"])
        ax.grid(axis="y", color="#FFFFFF", lw=0.45, alpha=0.8)
        ax.tick_params(length=0)
        ax.spines[:].set_visible(False)
    axes.flat[-1].axis("off")
    fig.text(
        0.015,
        0.51,
        "Capacity share / capture fraction (%)",
        rotation=90,
        rotation_mode="anchor",
        va="center",
        fontsize=7,
    )
    fig.text(0.50, 0.15, "Modeled period", ha="center", fontsize=7)
    fig.text(0.075, 0.925, "Region-grouped lifecycle and capture profiles", ha="left", fontsize=8.2, fontweight="bold")
    legend = [
        Patch(facecolor=STATE_COLORS["inherited_operating"], label="Inherited operation"),
        Patch(facecolor=STATE_COLORS["renewed_operating"], label="Same-site renewal"),
        Patch(facecolor=STATE_COLORS["inactive"], label="Inactive / exited"),
        Line2D([0], [0], color="#D55E00", lw=1.2, label="Commercial capture / gross direct emissions"),
    ]
    fig.legend(handles=legend, ncol=4, frameon=False, loc="lower center", bbox_to_anchor=(0.52, 0.025))
    evidence_banner(fig, line_count, evidence_status)
    # Preserve the declared 190-mm submission width.  A tight bounding box
    # previously shrank this dense matrix to about 168 mm, making its type
    # materially smaller than the other main figures.
    save_png(fig, output, dpi, tight=False)
    return output


def plot_province_matrix(
    metrics: pd.DataFrame,
    line_count: int,
    output: Path,
    dpi: int,
    evidence_status: str,
) -> Path:
    data = metrics.sort_values("province_sort_index").reset_index(drop=True)
    columns = [
        "idle_headroom_share_2040",
        "exit_capacity_share_by_2045",
        "late_renewal_capacity_share",
        "terminal_capacity_share_2060",
        "late_capture_share_national",
    ]
    labels = [
        "Idle headroom\n2040",
        "Exited capacity\nby 2045",
        "Late renewal\n2045–2060",
        "Terminal capacity\n2060",
        "Late capture\nshare",
    ]
    matrix = data[columns].to_numpy(float)
    fig = plt.figure(figsize=(190 * MM, 145 * MM))
    grid = fig.add_gridspec(1, 2, width_ratios=[4.3, 1.0], left=0.19, right=0.98, top=0.84, bottom=0.10, wspace=0.08)
    ax = fig.add_subplot(grid[0, 0])
    ax_bar = fig.add_subplot(grid[0, 1], sharey=ax)
    cmap = LinearSegmentedColormap.from_list("fraction", ["#F7FBFF", "#A6CEE3", "#2166AC"])
    ax.imshow(matrix, aspect="auto", cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            value = matrix[row, column]
            ax.text(column, row, f"{100 * value:.0f}", ha="center", va="center", fontsize=5.6, color="white" if value >= 0.55 else "#1A1A1A")
    ax.set_xticks(range(len(labels)), labels)
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", length=0, pad=4)
    ax.set_yticks(range(len(data)), data["province_en"])
    ax.tick_params(axis="y", length=0, pad=3)
    ax.spines[:].set_visible(False)
    for boundary in np.arange(0.5, len(data), 1):
        ax.axhline(boundary, color="white", lw=0.35)
    for boundary in np.arange(0.5, len(columns), 1):
        ax.axvline(boundary, color="white", lw=0.55)
    ax.axvline(3.5, color="#6A6A6A", lw=0.9)
    ax.text(
        1.5,
        1.105,
        "% of inherited 2025 provincial capacity",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="bottom",
        fontsize=6.4,
        color="#555555",
    )
    ax.text(
        4.0,
        1.105,
        "% of national 2050–2060 capture",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="bottom",
        fontsize=6.4,
        color="#555555",
    )
    panel_label(ax, "A", x=-0.075, y=1.13)

    left = np.zeros(len(data))
    tier_columns = [
        ("stable_capacity_mt_y", "stable_core"),
        ("conditional_capacity_mt_y", "conditional_asset"),
        ("sensitive_capacity_mt_y", "sensitive_margin"),
        ("other_capacity_mt_y", "not_terminal_candidate"),
    ]
    for column, tier in tier_columns:
        values = data[column].to_numpy()
        ax_bar.barh(
            np.arange(len(data)),
            values,
            left=left,
            color=TIER_COLORS[tier],
            height=0.68,
            linewidth=0,
        )
        left += values
    ax_bar.set_ylim(len(data) - 0.5, -0.5)
    ax_bar.set_xlabel("Inherited 2025 capacity\n(Mt clinker per year)")
    ax_bar.xaxis.set_label_position("top")
    ax_bar.xaxis.tick_top()
    ax_bar.tick_params(axis="y", left=False, labelleft=False)
    ax_bar.spines[["left", "right", "bottom"]].set_visible(False)
    ax_bar.tick_params(axis="x", length=2)
    panel_label(ax_bar, "B", x=-0.08, y=1.13)
    fig.legend(
        handles=[Patch(facecolor=TIER_COLORS[tier], label=TIER_LABELS[tier]) for tier in TIER_ORDER],
        ncol=4,
        frameon=False,
        loc="lower right",
        bbox_to_anchor=(0.985, 0.022),
    )
    evidence_banner(fig, line_count, evidence_status)
    # Preserve the declared 190-mm submission width.  A tight bounding box
    # previously shrank this dense matrix to about 168 mm, making its type
    # materially smaller than the other main figures.
    save_png(fig, output, dpi, tight=False)
    return output


def main() -> None:
    global EXPORT_SUBMISSION_FORMATS
    args = parse_args()
    EXPORT_SUBMISSION_FORMATS = args.submission_formats
    configure_style()
    interface_dir = args.interface_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((interface_dir / "interface_manifest.json").read_text(encoding="utf-8"))
    plant_year = pd.read_csv(interface_dir / "plant_year_interface.csv")
    plant_static = pd.read_csv(interface_dir / "plant_static_interface.csv")
    province_year = pd.read_csv(interface_dir / "province_year_interface.csv")
    region_year = pd.read_csv(interface_dir / "region_year_interface.csv")
    metrics = pd.read_csv(interface_dir / "province_mechanism_metrics.csv")
    line_count = int(manifest["line_count"])

    if args.main_figure_names:
        paths = [
            plot_atlas(
                plant_year,
                plant_static,
                output_dir / "fig2_capacity_turnover_emissions_capture_atlas.png",
                args.dpi,
                manifest["evidence_status"],
            ),
            plot_province_matrix(
                metrics,
                line_count,
                output_dir / "fig3_provincial_turnover_capture_mechanism.png",
                args.dpi,
                manifest["evidence_status"],
            ),
        ]
    else:
        paths = [
            plot_atlas(
                plant_year,
                plant_static,
                output_dir / "candidate_fig2_capacity_turnover_emissions_capture_atlas.png",
                args.dpi,
                manifest["evidence_status"],
            ),
            plot_ranked_province_multiples(
                province_year,
                metrics,
                line_count,
                output_dir / "candidate_province_ranked_small_multiples.png",
                args.dpi,
                manifest["evidence_status"],
            ),
            plot_region_multiples(
                region_year,
                line_count,
                output_dir / "candidate_region_grouped_small_multiples.png",
                args.dpi,
                manifest["evidence_status"],
            ),
            plot_province_matrix(
                metrics,
                line_count,
                output_dir / "candidate_province_metric_matrix.png",
                args.dpi,
                manifest["evidence_status"],
            ),
        ]
    qa_dir = output_dir.parent / "qa" / "visual_previews"
    qa_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        build_qa_previews(path, qa_dir)


if __name__ == "__main__":
    main()
