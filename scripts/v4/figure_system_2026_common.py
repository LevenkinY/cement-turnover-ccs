"""Shared publication style for the Applied Energy 2026 figure system."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl


ROOT = Path(__file__).resolve().parents[2]
FIGROOT = ROOT / "paper/applied_energy_2026/submission/figures"
FIGDIR = FIGROOT
SOURCE = ROOT / "paper/applied_energy_2026/submission/source_data_verified_20260829"

COLORS = {
    "blue": "#0072B2",
    "blue_light": "#8CC7E8",
    "blue_open": "#E8F3F9",
    "gold": "#E69F00",
    "gold_light": "#F8E3AC",
    "orange": "#D55E00",
    "teal": "#009E73",
    "teal_light": "#B9E3D6",
    "magenta": "#CC79A7",
    "grey": "#8A8A8A",
    "grey_light": "#D9D9D9",
    "grey_xlight": "#F2F2F2",
    "ink": "#2B2B2B",
    "white": "#FFFFFF",
}

TIER_COLORS = {
    "stable_core": COLORS["blue"],
    "conditional_asset": COLORS["gold"],
    "sensitive_margin": COLORS["magenta"],
}

STYLE = {
    "font.family": "Arial",
    "font.size": 7.0,
    "axes.titlesize": 7.0,
    "axes.labelsize": 7.0,
    "xtick.labelsize": 7.0,
    "ytick.labelsize": 7.0,
    "legend.fontsize": 6.7,
    "axes.linewidth": 0.75,
    "xtick.major.width": 0.75,
    "ytick.major.width": 0.75,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "lines.linewidth": 1.35,
    "lines.markersize": 3.6,
    "legend.frameon": False,
    "axes.grid": False,
    "savefig.dpi": 600,
    "figure.dpi": 160,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "text.color": COLORS["ink"],
    "axes.labelcolor": COLORS["ink"],
    "xtick.color": COLORS["ink"],
    "ytick.color": COLORS["ink"],
}


def apply_style() -> None:
    mpl.rcParams.update(STYLE)


def panel_label(ax, label: str) -> None:
    ax.set_title(label, loc="left", fontsize=9, fontweight="bold", pad=3)


def despine(ax, right: bool = True, top: bool = True) -> None:
    if top:
        ax.spines["top"].set_visible(False)
    if right:
        ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)


def quiet_grid(ax, axis: str = "y") -> None:
    ax.grid(axis=axis, color="#E3E3E3", linewidth=0.45, zorder=0)


def save_figure(fig, filename: str) -> Path:
    FIGDIR.mkdir(parents=True, exist_ok=True)
    path = FIGDIR / filename
    fig.savefig(path, dpi=600, facecolor="white")
    stem = path.with_suffix("")
    fig.savefig(stem.with_suffix(".pdf"), facecolor="white")
    fig.savefig(stem.with_suffix(".svg"), facecolor="white")
    fig.savefig(
        stem.with_suffix(".tiff"),
        dpi=600,
        facecolor="white",
        pil_kwargs={"compression": "tiff_lzw"},
    )
    return path
