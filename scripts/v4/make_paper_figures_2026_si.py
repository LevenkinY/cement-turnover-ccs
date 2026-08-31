#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Make corrected-root SI figures S2-S6 for the Applied Energy 2026 submission.

Same task spec as the main-figure scripts: 600-dpi PNG/TIFF plus editable
PDF/SVG,
colourblind-safe (Okabe-Ito / viridis), English labels, no explanatory
text annotations inside panels (numeric data labels are data, not
explanation). Outputs go to the verified figure bundle under ``SI/`` and
every panel's plotted numbers are written to
``paper/applied_energy_2026/submission/source_data_verified_20260829/figS*``.

SI Fig. S1 is rendered by ``make_main_figures_2026_v2.py``.  This script must
never read the superseded 2026-08-16/21 roots.

Derivation notes (口径)
-----------------------
Fig S1  annual_system_evolution.csv (case column), planning cases
        S4 / S1 / S5 (frozen aliases D-high / S1 / D-low).
        A: operating_lines and operating_capacity_mt_per_year paths.
        B: captured_co2_mt paths plus 2060 terminal operating_lines.
Fig S2  public S3 storage-transport corroboration, frozen alias S5
        (EOR qualifier lives in the
        caption only, not inside panels).
        A: nested cost decomposition from analysis_s5/summary_metrics.csv,
        metric = objective_incumbent: direct = pure_direct_effect
        (fixed_dispatch - baseline), dispatch feedback, turnover feedback,
        total effect (billion CNY).
        B: period-weighted cumulative CO2 flow (period weights
        {2025:2.5, 2030-2055:5, 2060:2.5}) from co2_flow_routes of the S1 /
        S5 result JSONs, split by onshore/offshore x DSA/EOR.
        C: offshore increment (S5 - S1) split into EOR vs DSA shares.
Fig S3  35-year lifetime sensitivity for public S2 (frozen alias S3).
        A: S1 per-period operating lines and renewal events, 40y vs 35y.
        40y values from annual_system_evolution.csv; 35y values from
        lifetime35/full/S1_baseline_results.json (summary.n_plants_operating,
        renewal events = sum of plants[*].r per period).
        B: public S2 turnover lock-in loss (fixed-turnover - full, billion CNY):
        point = incumbent difference; interval upper = fixed incumbent -
        full solver bound. 40y: 3.31 [3.31, 4.01]; 35y: 3.83 [3.83, 4.52].
Fig S4  Isolated minimum-utilization sensitivity with early-exit cost fixed
        at 130 CNY/t annual capacity.
        A: public S2 turnover lock-in point and solver-bound interval across u_min.
        B: S1 operating-line counts in 2035/2040/2045 across u_min.
        C: share of S1 operating lines at the utilization floor in the same
        periods. Interpretation belongs in the caption rather than the panels.
Fig S5  near_optimal/analysis/frontier_summary.csv.
        A: identity_distance_incumbent with identity_distance_bound as
        interval whiskers (log scale; kCNY of identity perturbation).
        B: Jaccard similarity columns vs S1 per case.
Fig S6  cross_scenario_overlap.csv: heatmap of the four comparisons x all
        overlap-metric columns.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from figure_system_2026_common import FIGDIR as VERIFIED_FIGDIR, save_figure

# ---------------------------------------------------------------------------
# Paths and style
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "results/v4/writing_ready_storyline_v3_20260829"
RUNS = ROOT / "results/v4/final_verified_inputs_20260829"
UTIL_SENS = ROOT / "results/v4/min_utilization_verified_inputs_20260829"
FIGDIR = VERIFIED_FIGDIR / "SI"
SRCDIR = ROOT / "paper/applied_energy_2026/submission/source_data_verified_20260829"
FIGDIR.mkdir(parents=True, exist_ok=True)
SRCDIR.mkdir(parents=True, exist_ok=True)

PERIODS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
PERIOD_WEIGHTS = {2025: 2.5, 2030: 5, 2035: 5, 2040: 5,
                  2045: 5, 2050: 5, 2055: 5, 2060: 2.5}

# Okabe-Ito palette
OI = {
    "orange": "#E69F00",
    "sky_blue": "#56B4E9",
    "bluish_green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "reddish_purple": "#CC79A7",
    "black": "#000000",
    "gray": "#999999",
}
DEMAND_COLORS = {"D-high": "#56B4E9", "S1": "#0072B2", "D-low": "#0B3D66"}
CASE_ORDER = ["D-high", "S1", "D-low"]
CASE_DISPLAY = {"D-high": "S4", "S1": "S1", "D-low": "S5"}

plt.rcParams.update(
    {
        "font.family": "Arial",
        "font.size": 7.0,
        "axes.titlesize": 7.5,
        "axes.labelsize": 7.0,
        "xtick.labelsize": 6.5,
        "ytick.labelsize": 6.5,
        "legend.fontsize": 6.3,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "lines.linewidth": 1.4,
        "lines.markersize": 3.0,
        "legend.frameon": False,
        "axes.grid": True,
        "grid.linewidth": 0.4,
        "grid.alpha": 0.35,
        "savefig.dpi": 600,
        "figure.dpi": 300,
        "pdf.fonttype": 42,
        "svg.fonttype": "none",
    }
)


def _panel_label(ax, label):
    ax.set_title(label, loc="left", fontweight="bold", pad=3)


def _save(fig, name):
    out = save_figure(fig, f"SI/{name}")
    plt.close(fig)
    print(f"wrote {out}")


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _objective_bn(json_path):
    d = _load_json(json_path)
    # solver objective is in kCNY; convert to billion CNY
    return d["solver"]["objective_value"] / 1e6, d["solver"]["objective_bound"] / 1e6


def _renewal_events_by_period(json_path):
    d = _load_json(json_path)
    events = {p: 0 for p in PERIODS}
    for plant in d["plants"].values():
        for per, val in plant["r"].items():
            events[int(per)] += int(round(val))
    return events


# ---------------------------------------------------------------------------
# Fig S1: demand scenario detail
# ---------------------------------------------------------------------------
def fig_s1():
    df = pd.read_csv(STORY / "annual_system_evolution.csv")
    df = df[df["case"].isin(CASE_ORDER)]

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6))

    # Panel A: operating lines (solid) and operating capacity (dashed)
    ax = axes[0]
    ax2 = ax.twinx()
    ax2.grid(False)
    for case in CASE_ORDER:
        sub = df[df["case"] == case].sort_values("year")
        ax.plot(sub["year"], sub["operating_lines"], color=DEMAND_COLORS[case],
                marker="o", label=f"{CASE_DISPLAY[case]} lines")
        ax2.plot(sub["year"], sub["operating_capacity_mt_per_year"],
                 color=DEMAND_COLORS[case], marker="s", linestyle="--",
                 label=f"{CASE_DISPLAY[case]} capacity")
    ax.set_xlabel("Year")
    ax.set_ylabel("Operating lines")
    ax2.set_ylabel("Operating capacity (Mt/yr)")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper right", ncol=2, columnspacing=0.8,
              handlelength=1.6)
    _panel_label(ax, "A")

    pa = df[["case", "year", "operating_lines",
             "operating_capacity_mt_per_year"]].sort_values(["case", "year"])
    pa.insert(1, "case_label", pa["case"].map(CASE_DISPLAY))
    pa = pa.rename(columns={"case": "case_internal"})
    pa.to_csv(SRCDIR / "figS1_panel_a_lines_capacity.csv", index=False)

    # Panel B: captured CO2 paths + 2060 terminal operating lines
    ax = axes[1]
    ax2 = ax.twinx()
    ax2.grid(False)
    for case in CASE_ORDER:
        sub = df[df["case"] == case].sort_values("year")
        ax.plot(sub["year"], sub["captured_co2_mt"], color=DEMAND_COLORS[case],
                marker="o", label=f"{CASE_DISPLAY[case]} captured CO2")
    term = df[df["year"] == 2060].set_index("case").loc[CASE_ORDER]
    x = np.array([2058.2, 2060.0, 2061.8])
    ax2.bar(x, term["operating_lines"], width=1.5,
            color=[DEMAND_COLORS[c] for c in CASE_ORDER], alpha=0.45,
            edgecolor="none")
    ax2.bar([], [], color=OI["gray"], alpha=0.45, label="2060 operating lines (bar)")
    ax.set_xlabel("Year")
    ax.set_ylabel("Captured CO2 (Mt/yr)")
    ax2.set_ylabel("Operating lines in 2060")
    ax.set_xlim(2024, 2064)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", handlelength=1.6)
    _panel_label(ax, "B")

    pb = df[["case", "year", "captured_co2_mt", "operating_lines"]].sort_values(
        ["case", "year"])
    pb.insert(1, "case_label", pb["case"].map(CASE_DISPLAY))
    pb = pb.rename(columns={"case": "case_internal"})
    pb.to_csv(SRCDIR / "figS1_panel_b_capture_terminal_lines.csv", index=False)

    fig.tight_layout()
    _save(fig, "figS1_demand_scenario_detail.png")


# ---------------------------------------------------------------------------
# Fig S2: public S3 storage-transport corroboration (frozen alias S5)
# ---------------------------------------------------------------------------
def _weighted_route_flows(json_path):
    d = _load_json(json_path)
    out = {}
    for per, recs in d["co2_flow_routes"].items():
        w = PERIOD_WEIGHTS[int(per)]
        for r in recs:
            key = ("Offshore" if r["is_offshore"] else "Onshore", r["type"])
            out[key] = out.get(key, 0.0) + r["flow_kt"] * w
    return out  # kt CO2


def fig_s2():
    fig, axes = plt.subplots(1, 3, figsize=(7.48, 2.6),
                             gridspec_kw={"width_ratios": [1.1, 1.0, 0.7]})

    # Panel A: nested cost decomposition (waterfall), billion CNY
    sm = pd.read_csv(RUNS / "analysis_s3/summary_metrics.csv")
    row = sm[sm["metric"] == "objective_incumbent"].iloc[0]
    direct = row["pure_direct_effect_fixed_dispatch_minus_baseline"]
    dispatch = row["dispatch_feedback_fixed_turnover_minus_fixed_dispatch"]
    turnover = row["turnover_feedback_full_minus_fixed_turnover"]
    total = row["total_effect_full_minus_baseline"]

    ax = axes[0]
    labels = ["Direct", "Dispatch\nfeedback", "Turnover\nfeedback", "Total"]
    vals = [direct, dispatch, turnover]
    bottoms, heights = [], []
    cum = 0.0
    for v in vals:
        bottoms.append(min(cum, cum + v))
        heights.append(abs(v))
        cum += v
    colors = [OI["blue"], OI["sky_blue"], OI["orange"]]
    x = np.arange(4)
    ax.bar(x[:3], heights, bottom=bottoms, color=colors, width=0.62,
           edgecolor="none")
    ax.bar(x[3], abs(total), bottom=min(0.0, total), color=OI["bluish_green"],
           width=0.62, edgecolor="none")
    for xi, v, b, h in zip(x[:3], vals, bottoms, heights):
        ax.text(xi, b + h + 0.25, f"{v:.2f}", ha="center", va="bottom",
                fontsize=6.0)
    ax.text(x[3], min(0.0, total) + abs(total) + 0.25, f"{total:.2f}",
            ha="center", va="bottom", fontsize=6.0)
    ax.axhline(0, color="black", linewidth=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Cost effect vs S1 (billion CNY)")
    ax.set_ylim(min(0.0, total) - 1.2, 1.6)
    _panel_label(ax, "A")

    pd.DataFrame(
        {"component": ["direct", "dispatch_feedback", "turnover_feedback",
                       "total_effect"],
         "billion_CNY": [direct, dispatch, turnover, total]}
    ).to_csv(SRCDIR / "figS2_panel_a_cost_decomposition.csv", index=False)

    # Panel B: cumulative flows by onshore/offshore x DSA/EOR
    s1 = _weighted_route_flows(RUNS / "full/S1_baseline_results.json")
    s5 = _weighted_route_flows(RUNS / "full/S5_offshore_parity_results.json")
    cats = [("Onshore", "DSA"), ("Onshore", "EOR"),
            ("Offshore", "DSA"), ("Offshore", "EOR")]
    cat_colors = {"Onshore DSA": OI["blue"], "Onshore EOR": OI["sky_blue"],
                  "Offshore DSA": OI["orange"], "Offshore EOR": OI["vermillion"]}

    ax = axes[1]
    x = np.arange(2)
    for case_i, flows in enumerate([s1, s5]):
        bottom = 0.0
        for c in cats:
            v = flows.get(c, 0.0) / 1e6  # Gt CO2
            ax.bar(case_i, v, bottom=bottom, width=0.55,
                   color=cat_colors[f"{c[0]} {c[1]}"], edgecolor="white",
                   linewidth=0.4,
                   label=f"{c[0]} {c[1]}" if case_i == 0 else None)
            bottom += v
        ax.text(case_i, bottom + 0.08, f"{bottom:.2f}", ha="center",
                va="bottom", fontsize=6.0)
    ax.set_xticks(x)
    ax.set_xticklabels(["S1", "S3"])
    ax.set_ylabel("Cumulative CO2 flow 2025-2060 (Gt)")
    ax.set_ylim(0, 5.9)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2,
              handlelength=1.2)
    _panel_label(ax, "B")

    pb_rows = []
    for case_internal, case_label, flows in [("S1", "S1", s1),
                                              ("S5", "S3", s5)]:
        for c in cats:
            pb_rows.append({"case_internal": case_internal,
                            "case_label": case_label,
                            "shore": c[0], "sink_type": c[1],
                            "cumulative_flow_GtCO2": flows.get(c, 0.0) / 1e6})
    pd.DataFrame(pb_rows).to_csv(SRCDIR / "figS2_panel_b_flow_structure.csv",
                                 index=False)

    # Panel C: offshore increment (public S3 - S1), EOR vs DSA share
    inc = {c: s5.get(c, 0.0) - s1.get(c, 0.0) for c in cats}
    off_eor = inc[("Offshore", "EOR")] / 1e6
    off_dsa = inc[("Offshore", "DSA")] / 1e6
    tot = off_eor + off_dsa
    ax = axes[2]
    ax.bar(0, off_eor, width=0.45, color=cat_colors["Offshore EOR"],
           edgecolor="white", linewidth=0.4, label="EOR")
    ax.bar(0, off_dsa, bottom=off_eor, width=0.45,
           color=cat_colors["Offshore DSA"], edgecolor="white", linewidth=0.4)
    ax.text(0.28, off_eor / 2, f"EOR {off_eor / tot * 100:.1f}%", ha="left",
            va="center", fontsize=6.5)
    ax.text(0.28, off_eor + off_dsa / 2, f"DSA {off_dsa / tot * 100:.1f}%",
            ha="left", va="center", fontsize=6.5)
    ax.set_xticks([0])
    ax.set_xticklabels(["Offshore\nincrement"])
    ax.set_xlim(-0.55, 1.35)
    ax.set_ylabel("S3 minus S1 offshore flow (Gt)")
    _panel_label(ax, "C")

    pd.DataFrame(
        {"sink_type": ["EOR", "DSA"],
         "offshore_increment_GtCO2": [off_eor, off_dsa],
         "share": [off_eor / tot, off_dsa / tot]}
    ).to_csv(SRCDIR / "figS2_panel_c_offshore_increment_share.csv", index=False)

    fig.tight_layout()
    _save(fig, "figS2_s3_storage_transport_corroboration.png")


# ---------------------------------------------------------------------------
# Fig S3: 35-year lifetime sensitivity
# ---------------------------------------------------------------------------
def fig_s3():
    df = pd.read_csv(STORY / "annual_system_evolution.csv")
    s1_40 = df[df["case"] == "S1"].sort_values("year")

    j35 = _load_json(RUNS / "lifetime35/full/S1_baseline_results.json")
    lines35 = [j35["summary"][str(p)]["n_plants_operating"] for p in PERIODS]
    ev35 = _renewal_events_by_period(RUNS / "lifetime35/full/S1_baseline_results.json")

    fig, axes = plt.subplots(1, 2, figsize=(7.48, 2.6))

    # Panel A: operating lines + renewal events, 40y vs 35y
    ax = axes[0]
    ax2 = ax.twinx()
    ax2.grid(False)
    ax.plot(s1_40["year"], s1_40["operating_lines"], color=OI["blue"],
            marker="o", label="Lines, 40-y lifetime")
    ax.plot(PERIODS, lines35, color=OI["vermillion"], marker="s",
            label="Lines, 35-y lifetime")
    w = 1.4
    ax2.bar(np.array(PERIODS) - w / 2 - 0.1, s1_40["renewal_events"], width=w,
            color=OI["blue"], alpha=0.4, edgecolor="none",
            label="Renewals, 40-y")
    ax2.bar(np.array(PERIODS) + w / 2 + 0.1, [ev35[p] for p in PERIODS],
            width=w, color=OI["vermillion"], alpha=0.4, edgecolor="none",
            label="Renewals, 35-y")
    ax.set_xlabel("Year")
    ax.set_ylabel("Operating lines (S1)")
    ax2.set_ylabel("Renewal events per period")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="center left", handlelength=1.6)
    _panel_label(ax, "A")

    pd.DataFrame({
        "year": PERIODS,
        "operating_lines_40y": s1_40["operating_lines"].values,
        "operating_lines_35y": lines35,
        "renewal_events_40y": s1_40["renewal_events"].values,
        "renewal_events_35y": [ev35[p] for p in PERIODS],
    }).to_csv(SRCDIR / "figS3_panel_a_lines_renewals.csv", index=False)

    # Panel B: public S2 turnover lock-in loss, 40y vs 35y
    s3_full_40 = _objective_bn(RUNS / "full/S3_all_spatial_equalized_results.json")
    s3_fix_40 = _objective_bn(
        RUNS / "s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json")
    s3_full_35 = _objective_bn(
        RUNS / "lifetime35/full/S3_all_spatial_equalized_results.json")
    s3_fix_35 = _objective_bn(
        RUNS / "lifetime35/s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json")

    def lockin(fix, full):
        point = fix[0] - full[0]
        upper = fix[0] - full[1]
        return point, upper

    p40, u40 = lockin(s3_fix_40, s3_full_40)
    p35, u35 = lockin(s3_fix_35, s3_full_35)

    ax = axes[1]
    x = np.arange(2)
    points = [p40, p35]
    uppers = [u40, u35]
    colors = [OI["blue"], OI["vermillion"]]
    for xi, pt, up, c in zip(x, points, uppers, colors):
        ax.errorbar(xi, pt, yerr=[[0.0], [up - pt]], color=c, marker="o",
                    markersize=4.5, capsize=3, linewidth=1.2,
                    linestyle="none")
        ax.text(xi + 0.07, pt, f"{pt:.2f}", ha="left", va="center",
                fontsize=6.5)
        ax.text(xi + 0.07, up, f"{up:.2f}", ha="left", va="center",
                fontsize=6.0, color=OI["gray"])
    ax.set_xticks(x)
    ax.set_xticklabels(["40-y lifetime", "35-y lifetime"])
    ax.set_ylabel("S2 turnover lock-in loss (billion CNY)")
    ax.set_xlim(-0.5, 1.9)
    ax.set_ylim(0, 5.2)
    _panel_label(ax, "B")

    pd.DataFrame({
        "lifetime": ["40y", "35y"],
        "lockin_loss_incumbent_bn": points,
        "lockin_loss_upper_bound_bn": uppers,
    }).to_csv(SRCDIR / "figS3_panel_b_lockin_loss.csv", index=False)

    fig.tight_layout()
    _save(fig, "figS3_lifetime35_sensitivity.png")


# ---------------------------------------------------------------------------
# Fig S4: isolated minimum-utilization sensitivity
# ---------------------------------------------------------------------------
def fig_s4():
    summary = pd.read_csv(UTIL_SENS / "utilization_sensitivity_summary.csv")
    binding = pd.read_csv(UTIL_SENS / "utilization_floor_binding.csv")
    # The verified-input package contains the S1 binding diagnostic only; it
    # therefore has no redundant scenario column.  Restrict by model period
    # without recreating the obsolete pre-verification schema.
    binding = binding[binding["year"].isin([2035, 2040, 2045])]
    summary = summary.sort_values("minimum_operating_utilization")
    u = summary["minimum_operating_utilization"].to_numpy(float)

    fig, axes = plt.subplots(
        1,
        3,
        figsize=(7.48, 2.45),
        gridspec_kw={"width_ratios": [1.0, 1.05, 1.05], "wspace": 0.34},
    )

    # Panel A: bound-aware turnover lock-in interval.
    ax = axes[0]
    point = summary["turnover_lockin_regret_bn_cny"].to_numpy(float)
    lower = summary["turnover_lockin_lower_bn_cny"].to_numpy(float)
    upper = summary["turnover_lockin_upper_bn_cny"].to_numpy(float)
    ax.errorbar(
        u,
        point,
        yerr=np.vstack([point - lower, upper - point]),
        color=OI["blue"],
        marker="o",
        markerfacecolor="white",
        markeredgewidth=1.0,
        markersize=4.5,
        capsize=3,
        linewidth=1.2,
        linestyle="none",
    )
    ax.axhline(0, color="#555555", linewidth=0.7)
    ax.set_xlabel("Minimum operating utilization")
    ax.set_ylabel("S2 turnover lock-in loss\n(billion CNY)")
    ax.set_xticks(u)
    ax.set_xticklabels([f"{value:.2f}" for value in u])
    ax.set_ylim(0, max(4.8, upper.max() + 0.25))
    _panel_label(ax, "A")

    panel_a = summary[
        [
            "minimum_operating_utilization",
            "turnover_lockin_regret_bn_cny",
            "turnover_lockin_lower_bn_cny",
            "turnover_lockin_upper_bn_cny",
            "s1_terminal_lines",
            "s1_renewal_events",
        ]
    ].copy()
    panel_a.to_csv(SRCDIR / "figS4_panel_a_lockin_intervals.csv", index=False)

    years = [2035, 2040, 2045]
    colors = {2035: OI["blue"], 2040: OI["sky_blue"], 2045: OI["orange"]}
    markers = {2035: "o", 2040: "s", 2045: "^"}

    # Panel B: mid-horizon line counts.
    ax = axes[1]
    for year in years:
        sub = binding[binding["year"] == year].sort_values(
            "minimum_operating_utilization"
        )
        ax.plot(
            sub["minimum_operating_utilization"],
            sub["operating_lines"],
            color=colors[year],
            marker=markers[year],
            markerfacecolor="white",
            markeredgewidth=0.9,
            label=str(year),
        )
    ax.set_xlabel("Minimum operating utilization")
    ax.set_ylabel("S1 operating lines")
    ax.set_xticks(u)
    ax.set_xticklabels([f"{value:.2f}" for value in u])
    ax.set_ylim(0, 1600)
    ax.legend(title="Period", loc="lower left", ncol=1, handlelength=1.4)
    _panel_label(ax, "B")

    panel_b = binding[
        ["minimum_operating_utilization", "year", "operating_lines"]
    ].sort_values(["year", "minimum_operating_utilization"])
    panel_b.to_csv(SRCDIR / "figS4_panel_b_operating_lines.csv", index=False)

    # Panel C: floor-binding share at the same model periods.
    ax = axes[2]
    for year in years:
        sub = binding[binding["year"] == year].sort_values(
            "minimum_operating_utilization"
        )
        ax.plot(
            sub["minimum_operating_utilization"],
            100.0 * sub["share_operating_lines_at_floor"],
            color=colors[year],
            marker=markers[year],
            markerfacecolor="white",
            markeredgewidth=0.9,
            label=str(year),
        )
    ax.set_xlabel("Minimum operating utilization")
    ax.set_ylabel("Operating lines at floor (%)")
    ax.set_xticks(u)
    ax.set_xticklabels([f"{value:.2f}" for value in u])
    ax.set_ylim(0, 105)
    _panel_label(ax, "C")

    panel_c = binding[
        [
            "minimum_operating_utilization",
            "year",
            "share_operating_lines_at_floor",
        ]
    ].sort_values(["year", "minimum_operating_utilization"])
    panel_c.to_csv(SRCDIR / "figS4_panel_c_floor_binding.csv", index=False)

    fig.subplots_adjust(left=0.075, right=0.99, bottom=0.20, top=0.91, wspace=0.38)
    _save(fig, "figS4_min_utilization_sensitivity.png")


# ---------------------------------------------------------------------------
# Fig S5: near-optimal frontier
# ---------------------------------------------------------------------------
def fig_s5():
    fs = pd.read_csv(RUNS / "near_optimal/analysis/frontier_summary.csv")
    scen_short = {"S1_baseline": "S1", "S3_all_spatial_equalized": "S2",
                  "S5_offshore_parity": "S3"}
    fs["label"] = (
        fs["scenario"].map(scen_short)
        + " "
        + fs["direction"]
        + "\n"
        + fs["scope"].str.replace("_", " ", regex=False)
    )
    fs = fs.sort_values("identity_distance_incumbent",
                        ascending=False).reset_index(drop=True)

    fig, axes = plt.subplots(1, 2, figsize=(7.48, 2.6),
                             gridspec_kw={"width_ratios": [1.0, 1.35]})

    # Panel A: identity distance with bound whiskers (log scale)
    ax = axes[0]
    x = np.arange(len(fs))
    for xi, (_, row) in zip(x, fs.iterrows()):
        lo = min(row["identity_distance_incumbent"],
                 row["identity_distance_bound"])
        hi = max(row["identity_distance_incumbent"],
                 row["identity_distance_bound"])
        ax.errorbar(xi, row["identity_distance_incumbent"],
                    yerr=[[row["identity_distance_incumbent"] - lo],
                          [hi - row["identity_distance_incumbent"]]],
                    color=OI["blue"], marker="o", markersize=4.5, capsize=3,
                    linewidth=1.2, linestyle="none")
    if (fs[["identity_distance_incumbent", "identity_distance_bound"]] <= 0).any().any():
        raise ValueError("Fig. S5 log-scale identity distances must be positive")
    ax.set_yscale("log")
    # Mathtext log exponents shrink relative to their parent tick label.  A
    # 7.2-pt parent keeps the embedded PDF exponent runs above the 5-pt floor.
    ax.tick_params(axis="y", labelsize=7.2)
    ax.set_xticks(x)
    ax.set_xticklabels(fs["label"], fontsize=6.0)
    ax.set_ylabel("Identity distance\n(kt/yr capacity, log scale)")
    _panel_label(ax, "A")

    fs[["label", "identity_distance_incumbent", "identity_distance_bound"]
       ].to_csv(SRCDIR / "figS5_panel_a_identity_distance.csv", index=False)

    # Panel B: Jaccard columns
    jac_cols = [
        ("full_path_capacity_jaccard_vs_s1", "Full-path capacity"),
        ("terminal_capacity_jaccard_vs_s1", "Terminal capacity"),
        ("terminal_site_jaccard_vs_s1", "Terminal sites"),
        ("renewal_event_jaccard_vs_s1", "Renewal events"),
        ("capture_responsibility_jaccard_vs_s1", "Capture responsibility"),
        ("route_flow_jaccard_vs_s1", "Route flows"),
    ]
    palette = [OI["blue"], OI["sky_blue"], OI["bluish_green"], OI["orange"],
               OI["vermillion"], OI["reddish_purple"]]
    ax = axes[1]
    x = np.arange(len(fs))
    n = len(jac_cols)
    w = 0.8 / n
    for j, ((col, lab), c) in enumerate(zip(jac_cols, palette)):
        ax.bar(x + (j - (n - 1) / 2) * w, fs[col], width=w * 0.92, color=c,
               edgecolor="none", label=lab)
    ax.set_xticks(x)
    ax.set_xticklabels(fs["label"], fontsize=6.0)
    ax.set_ylabel("Jaccard similarity vs S1")
    ax.set_ylim(0, 1.05)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.24), ncol=3,
              handlelength=1.0, columnspacing=0.8)
    _panel_label(ax, "B")

    out = fs[["label"] + [c for c, _ in jac_cols]]
    out.to_csv(SRCDIR / "figS5_panel_b_jaccard.csv", index=False)

    fig.tight_layout()
    _save(fig, "figS5_near_optimal_frontier.png")


# ---------------------------------------------------------------------------
# Fig S6: full overlap matrix heatmap
# ---------------------------------------------------------------------------
def fig_s6():
    ov = pd.read_csv(STORY / "cross_scenario_overlap.csv")
    metric_cols = [
        ("full_period_capacity_path_jaccard", "Full-period\ncapacity path"),
        ("full_period_line_path_jaccard", "Full-period\nline path"),
        ("late_2050_2060_capacity_path_jaccard", "Late 2050-2060\ncapacity path"),
        ("terminal_site_jaccard", "Terminal\nsites"),
        ("terminal_capacity_jaccard", "Terminal\ncapacity"),
        ("renewal_event_jaccard", "Renewal\nevents"),
        ("production_distribution_overlap", "Production\ndistribution"),
        ("capture_responsibility_jaccard", "Capture\nresponsibility"),
        ("source_sink_route_jaccard", "Source-sink\nroutes"),
        ("storage_node_type_jaccard", "Storage node\ntypes"),
    ]
    rows = ["S1_vs_S2", "S1_vs_S3", "S1_vs_S4", "S1_vs_S5"]
    row_labels = ["S1 vs S2", "S1 vs S3", "S1 vs S4", "S1 vs S5"]
    ov = ov.set_index("comparison").loc[rows]

    mat = ov[[c for c, _ in metric_cols]].to_numpy(dtype=float)

    fig, ax = plt.subplots(figsize=(7.48, 2.4))
    im = ax.imshow(mat, cmap="viridis", vmin=0.0, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(metric_cols)))
    ax.set_xticklabels([lab.replace("\n", " ") for _, lab in metric_cols],
                       fontsize=6.0, rotation=28, ha="right",
                       rotation_mode="anchor")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(row_labels, fontsize=6.5)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=5.8,
                    color="white" if v < 0.55 else "black")
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("Overlap (Jaccard / share)", fontsize=6.5)
    cbar.ax.tick_params(labelsize=6.0)

    out = ov[[c for c, _ in metric_cols]].reset_index()
    out.insert(1, "comparison_label", row_labels)
    out.columns = ["comparison_internal", "comparison_label"] + [
        lab.replace("\n", " ") for _, lab in metric_cols
    ]
    out.to_csv(SRCDIR / "figS6_overlap_matrix.csv", index=False)

    fig.tight_layout()
    _save(fig, "figS6_full_overlap_matrix.png")


if __name__ == "__main__":
    fig_s2()
    fig_s3()
    fig_s4()
    fig_s5()
    fig_s6()
