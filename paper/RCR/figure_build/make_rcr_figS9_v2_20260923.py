"""RCR Fig. S9 v2 (2026-09-23): mitigation-structure change and capture-task
redistribution between the reference (S1) and the AF-access-equalized
counterfactual (S4), from the frozen v5 formal run pack
(``v5/results/formal_v1_20260914``).

Why the figure changed (2026-09-22 review, author decision): v1 plotted two
panels of absolute Mt CO2/yr, so its second panel repeated the dark segments of
its first and the quantity that matters -- the S4 - S1 difference -- had to be
computed by the reader.  v2 plots differences only, in two complementary
panels: (a) how the mitigation *components* move at the 2045 and 2060 nodes,
and (b) how the *cumulative* capture task is redistributed across fleet groups
over 2025-2060.

Grouping.  Groups are fixed by 2060 operating status and are constant across
years: the 42 S1-only lines, the 35 S4-only lines, and "Other lines" = every
line outside those two groups (1,495 of the 1,572), which is what v1 labelled
"shared" and mis-described as 294 lines.  The 294-line figure is the subset of
the other lines that operates in 2060 under both scenarios; it is not the group
plotted here.  Counts appear in the caption, never in the artwork.

Colours.  The paper already spends blue on S1 and on capture, orange on S4/S5
and green on AF.  Because both panels encode S4 - S1, scenario hues must not be
reused: AF keeps the AF green of Fig. 2, capture takes the project's magenta
(the one Okabe-Ito hue the paper had not yet used in a figure), and the national
row is dark grey.  Green and magenta therefore encode *component*, not scenario.

Two quantities, two calibers.  The AF component is the accounted fossil-CO2
reduction of AF substitution, COAL_EF x BETA_AF = 1.46322 t CO2 per tce of AF
supply, read live from the model configuration; the capture component is
commercial capture.  They are separate accounting quantities, not a conversion
pair, and the panels carry different units (annual flow vs cumulative total).
Neither is a "net emission reduction" of the sector: the accounting boundary is
the one fixed in the main text and SI Section S6.

Outputs (PNG only, 155 mm wide, 600 dpi, into ``paper/RCR/figures/``):
  - figS9_mitigation_redistribution_v2_20260923.png
  - paper/common/source_data/figS9_mitigation_redistribution_v2.csv
    (companion table: both scenarios' absolute values, the plotted deltas, the
    cumulative values and the group line counts)

---------------------------------------------------------------------------
FIGURE CAPTION (single source of truth)

Fig. S9 | How AF spatial conditions redistribute mitigation (companion to
main-text Fig. 4). (a) Change in the two mitigation components between the
access-equalized counterfactual (S4) and the reference (S1), at the 2045 and
2060 decision nodes, by fleet group; every bar is S4 - S1 on one shared axis,
so bars to the right are increases under equalized access. The AF component is
the accounted fossil-CO2 reduction of AF substitution (1.46322 t CO2 per tce of
AF supply) and the capture component is commercial capture; the two are
distinct accounting quantities, not a conversion pair. (b) Change in cumulative
commercial capture over 2025-2060, S4 - S1, on the model's trapezoidal period
weights; the national row is the sum of the three group rows and is separated
by a gap. Fleet groups are fixed by 2060 operating status: 42 S1-only lines,
35 S4-only lines and 1,495 other lines, of which 294 operate in 2060 under both
scenarios. Panel a is an annual flow and panel b a cumulative quantity over the
whole horizon, so the two panels carry different units and are not comparable
bar for bar. Taken together: equalized access raises AF fossil-CO2 reduction at
the other lines and reallocates the capture task between the two exchanged
groups, where the cumulative changes nearly cancel, so the national cumulative
capture reduction is delivered mainly by the other lines.

Verification anchors asserted below (Mt CO2, from the frozen formal batch)
---------------------------------------------------------------------------
Panel a, S4 - S1 (annual): Other lines AF +11.02 / capture -23.74 at 2045 and
+9.76 / -7.76 at 2060; S1-only -2.52 / -21.24 and -3.94 / -33.90; S4-only
+4.57 / +20.66 and +4.56 / +33.43. National AF +13.07 (2045) and +10.38
(2060); national capture -24.32 and -8.22.
Panel b, S4 - S1 (cumulative): S1-only -553.3, S4-only +533.7, other lines
-218.6, national -238.3 (S1 4,936.7 -> S4 4,698.4 Mt).

Run:  .venv/bin/python paper/RCR/figure_build/make_rcr_figS9_v2_20260923.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def _repo_root() -> Path:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "v4" / "figure_system_2026_common.py").exists():
            return _p
    raise RuntimeError("repo root with scripts/v4 not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "scripts" / "v4"))
sys.path.insert(0, str(ROOT / "v5" / "model" / "src_v5"))

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
from config_v5 import BETA_AF, COAL_EF_TCO2_PER_TCE  # noqa: E402

AF_CREDIT_TCO2_PER_TCE = COAL_EF_TCO2_PER_TCE * BETA_AF   # 1.46322

RUNS = {
    "S1": "v5/results/formal_v1_20260914/C1_central_J/S1_baseline",
    "S4": "v5/results/formal_v1_20260914/C4_equalized_J/S3_all_spatial_equalized",
}
SCEN = "v5/scenarios/rd_numbers_20260915"
OUTDIR = ROOT / "paper" / "RCR" / "figures"
SOURCEDIR = ROOT / "paper" / "common" / "source_data"

YEARS = (2045, 2060)
NODES = (2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060)
WEIGHTS = {t: (2.5 if t in (2025, 2060) else 5.0) for t in NODES}

GROUP_ORDER = ("Other lines", "S1-only lines", "S4-only lines")
COMPONENTS = ("AF fossil-CO\u2082 reduction", "CO\u2082 capture")
COMPONENT_COLOR = {COMPONENTS[0]: "#58A88A", COMPONENTS[1]: COLORS["magenta"]}
TOTAL_COLOR = "#4D4D4D"

EXPECTED = {   # frozen-batch anchors, Mt CO2
    ("a", 2045, "Other lines"): (11.02, -23.74),
    ("a", 2045, "S1-only lines"): (-2.52, -21.24),
    ("a", 2045, "S4-only lines"): (4.57, 20.66),
    ("a", 2060, "Other lines"): (9.76, -7.76),
    ("a", 2060, "S1-only lines"): (-3.94, -33.90),
    ("a", 2060, "S4-only lines"): (4.56, 33.43),
    ("b", "S1-only lines"): -553.3,
    ("b", "S4-only lines"): 533.7,
    ("b", "Other lines"): -218.6,
    ("b", "National total"): -238.3,
}
TOL = 0.15


def read_rows(rel: str) -> list[dict]:
    with open(ROOT / rel) as fh:
        return list(csv.DictReader(fh))


def fleet_and_groups() -> tuple[set[int], set[int], set[int]]:
    role = read_rows(f"{RUNS['S1']}/full_plant_role_classification.csv")
    fleet = {int(r["plant_id"]) for r in role}
    c1_only = {int(r["plant_id"]) for r in read_rows(f"{SCEN}/data02_C1-only_plants.csv")}
    c4_only = {int(r["plant_id"]) for r in read_rows(f"{SCEN}/data02_C4-only_plants.csv")}
    assert len(fleet) == 1572, len(fleet)
    assert (len(c1_only), len(c4_only)) == (42, 35), (len(c1_only), len(c4_only))
    assert c1_only <= fleet and c4_only <= fleet
    return fleet, c1_only, c4_only


def scenario_series(scen: str) -> dict:
    """Per-line AF supply (ktce) and commercial capture (kt) at the two
    plotted nodes, plus cumulative capture over 2025-2060 (kt)."""
    run = RUNS[scen]
    af = {t: {} for t in YEARS}
    for r in read_rows(f"{run}/full_af_plant_shares.csv"):
        t = int(r["period"])
        if t in af:
            af[t][int(r["plant_id"])] = float(r["af_supply_ktce"] or 0.0)
    cap = {t: {} for t in YEARS}
    cumulative: dict[int, float] = {}
    for r in read_rows(f"{run}/full_ccs_plant_details.csv"):
        t = int(r["period"])
        pid = int(r["plant_id"])
        value = float(r["captured_commercial"] or 0.0)
        if t in cap:
            cap[t][pid] = value
        cumulative[pid] = cumulative.get(pid, 0.0) + WEIGHTS[t] * value
    return {"af": af, "capture": cap, "cumulative": cumulative}


def build() -> dict:
    fleet, c1_only, c4_only = fleet_and_groups()
    other = fleet - c1_only - c4_only
    assert len(other) == 1495, len(other)
    members = {"Other lines": other, "S1-only lines": c1_only, "S4-only lines": c4_only}
    series = {s: scenario_series(s) for s in RUNS}

    def total(scen: str, key: str, year=None) -> float:
        """Fleet total in kt (AF credits converted to kt CO2)."""
        if key == "af":
            return sum(series[scen]["af"][year].values()) * AF_CREDIT_TCO2_PER_TCE
        if key == "capture":
            return sum(series[scen]["capture"][year].values())
        return sum(series[scen]["cumulative"].values())

    data: dict = {"members": members, "panel_a": {}, "panel_b": {}, "totals": {}}
    for year in YEARS:
        for group, ids in members.items():
            vals = {}
            for scen in RUNS:
                af = sum(series[scen]["af"][year].get(i, 0.0) for i in ids) * AF_CREDIT_TCO2_PER_TCE
                cap = sum(series[scen]["capture"][year].get(i, 0.0) for i in ids)
                vals[scen] = (af / 1000.0, cap / 1000.0)
            data["panel_a"][(year, group)] = {
                "S1": vals["S1"], "S4": vals["S4"],
                "delta": (vals["S4"][0] - vals["S1"][0], vals["S4"][1] - vals["S1"][1]),
            }
        data["totals"][("a", year)] = {}
        for scen in RUNS:
            data["totals"][("a", year)][scen] = (total(scen, "af", year) / 1000.0,
                                                 total(scen, "capture", year) / 1000.0)
        data["totals"][("a", year)]["delta"] = (
            data["totals"][("a", year)]["S4"][0] - data["totals"][("a", year)]["S1"][0],
            data["totals"][("a", year)]["S4"][1] - data["totals"][("a", year)]["S1"][1],
        )

    for group, ids in members.items():
        vals = {scen: sum(series[scen]["cumulative"].get(i, 0.0) for i in ids) / 1000.0
                for scen in RUNS}
        data["panel_b"][group] = {"S1": vals["S1"], "S4": vals["S4"],
                                  "delta": vals["S4"] - vals["S1"],
                                  "n_lines": len(ids)}
    vals = {scen: total(scen, "cumulative") / 1000.0 for scen in RUNS}
    data["panel_b"]["National total"] = {"S1": vals["S1"], "S4": vals["S4"],
                                         "delta": vals["S4"] - vals["S1"],
                                         "n_lines": len(fleet)}

    # --- verification: group sums close on the national totals -------------
    for year in YEARS:
        for idx, quantity in enumerate(("AF reduction", "capture")):
            group_sum = sum(data["panel_a"][(year, g)]["delta"][idx] for g in GROUP_ORDER)
            national = data["totals"][("a", year)]["delta"][idx]
            assert abs(group_sum - national) < 0.05, (year, quantity, group_sum, national)
    group_sum = sum(data["panel_b"][g]["delta"] for g in GROUP_ORDER)
    national = data["panel_b"]["National total"]["delta"]
    assert abs(group_sum - national) < 0.05, (group_sum, national)

    # --- verification: frozen anchors -------------------------------------
    for key, expected in EXPECTED.items():
        if key[0] == "a":
            got = data["panel_a"][(key[1], key[2])]["delta"]
            ok = abs(got[0] - expected[0]) < TOL and abs(got[1] - expected[1]) < TOL
        else:
            got = data["panel_b"][key[1]]["delta"]
            ok = abs(got - expected) < TOL
        assert ok, (key, got, expected)
    return data


def draw(data: dict) -> Path:
    apply_style()
    fig = plt.figure(figsize=(6.102, 3.307))          # 155 x 84 mm at 600 dpi
    left, right, top, bottom = 0.172, 0.988, 0.792, 0.178
    outer = fig.add_gridspec(1, 2, width_ratios=[1.55, 1.0], wspace=0.32,
                             left=left, right=right, top=top, bottom=bottom)
    inner = outer[0].subgridspec(1, 2, wspace=0.075)
    ax_a1 = fig.add_subplot(inner[0])
    ax_a2 = fig.add_subplot(inner[1], sharey=ax_a1)
    ax_b = fig.add_subplot(outer[1])

    # ---------------- panel a: annual change by component -------------------
    ypos = {g: len(GROUP_ORDER) - 1 - k for k, g in enumerate(GROUP_ORDER)}
    height, dodge, lim = 0.30, 0.185, 36.0
    for ax, year in ((ax_a1, YEARS[0]), (ax_a2, YEARS[1])):
        for group in GROUP_ORDER:
            y = ypos[group]
            for k, comp in enumerate(COMPONENTS):
                value = data["panel_a"][(year, group)]["delta"][k]
                ax.barh(y + (dodge if k == 0 else -dodge), value, height=height,
                        color=COMPONENT_COLOR[comp], edgecolor="none", zorder=3)
        ax.set_xlim(-lim, lim)
        ax.set_xticks([-30, -20, -10, 0, 10, 20, 30])
        ax.axvline(0.0, color=COLORS["ink"], linewidth=0.7, zorder=4)
        quiet_grid(ax, axis="x")
        despine(ax)
        ax.set_ylim(-0.62, len(GROUP_ORDER) - 0.38)
        ax.set_yticks([ypos[g] for g in GROUP_ORDER])
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", labelsize=FS_NOTE)
        for lbl in ax.get_xticklabels():
            fallback_font(lbl)
        # year marker inside the axes, clear of the top-row bars
        ax.text(0.985, 0.975, str(year), transform=ax.transAxes, ha="right", va="top",
                fontsize=FS_LABEL)
    ax_a1.set_yticklabels(list(GROUP_ORDER))
    for lbl in ax_a1.get_yticklabels():
        fallback_font(lbl)
    ax_a2.tick_params(axis="y", labelleft=False)
    ax_a2.spines["left"].set_visible(False)

    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=COMPONENT_COLOR[c], edgecolor="none")
               for c in COMPONENTS]
    legend = ax_a1.legend(handles, list(COMPONENTS), loc="lower left",
                          bbox_to_anchor=(0.0, 1.012), ncol=2, frameon=False,
                          fontsize=FS_LEGEND, handlelength=1.1, handleheight=0.9,
                          columnspacing=1.4, borderpad=0.0, handletextpad=0.5)
    for text in legend.get_texts():
        fallback_font(text)

    # ---------------- panel b: cumulative capture redistribution ------------
    rows = [("S1-only lines", 3.4), ("S4-only lines", 2.4), ("Other lines", 1.4)]
    for group, y in rows:
        value = data["panel_b"][group]["delta"]
        ax_b.barh(y, value, height=0.52, color=COMPONENT_COLOR[COMPONENTS[1]],
                  edgecolor="none", zorder=3)
        ax_b.text(value + (13 if value < 0 else -13), y, f"{value:,.1f}".replace("-", "\u2212"),
                  ha="left" if value < 0 else "right", va="center", fontsize=FS_NOTE,
                  color=COLORS["ink"], zorder=5)
    national = data["panel_b"]["National total"]["delta"]
    ax_b.barh(0.0, national, height=0.52, color=TOTAL_COLOR, edgecolor="none", zorder=3)
    ax_b.text(national + 13, 0.0, f"{national:,.1f}".replace("-", "\u2212"), ha="left",
              va="center", fontsize=FS_NOTE, color="white", zorder=5)
    ax_b.set_xlim(-580.0, 580.0)
    ax_b.set_xticks([-400, -200, 0, 200, 400])
    for lbl in ax_b.get_xticklabels():
        fallback_font(lbl)
    ax_b.axvline(0.0, color=COLORS["ink"], linewidth=0.7, zorder=4)
    quiet_grid(ax_b, axis="x")
    despine(ax_b)
    ax_b.set_ylim(-0.70, 4.10)
    ax_b.set_yticks([y for _, y in rows] + [0.0])
    ax_b.set_yticklabels([g for g, _ in rows] + ["National total"])
    ax_b.tick_params(axis="y", length=0)
    for lbl in list(ax_b.get_yticklabels()) + list(ax_b.get_xticklabels()):
        fallback_font(lbl)
    ax_b.get_yticklabels()[-1].set_fontweight("bold")
    ax_b.set_xlabel("Change in cumulative capture, S4 \u2212 S1\n"
                    "(Mt CO\u2082, 2025\u20132060)", fontsize=FS_LABEL, labelpad=3.0)
    fallback_font(ax_b.xaxis.label)

    # titles above the panels; panel a's x label spans both facets
    pos_a1, pos_a2, pos_b = ax_a1.get_position(), ax_a2.get_position(), ax_b.get_position()
    fig.text(pos_a1.x0, 0.962, "a  Changes in mitigation components",
             fontsize=FS_LABEL, fontweight="bold", ha="left", va="top")
    fig.text(pos_b.x0, 0.962, "b  Redistribution of\ncumulative capture",
             fontsize=FS_LABEL, fontweight="bold", ha="left", va="top", linespacing=1.35)
    label = fig.text((pos_a1.x0 + pos_a2.x1) / 2.0, bottom - 0.062,
                     "Change relative to S1 (Mt CO\u2082 yr\u207b\u00b9)",
                     fontsize=FS_LABEL, ha="center", va="top")
    fallback_font(label)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    output = OUTDIR / "figS9_mitigation_redistribution_v2_20260923.png"
    fig.savefig(output, dpi=600, facecolor="white")
    plt.close(fig)
    return output


def write_source_data(data: dict) -> Path:
    """Companion table: absolute values of both scenarios, the plotted deltas,
    the cumulative totals and the group line counts."""
    SOURCEDIR.mkdir(parents=True, exist_ok=True)
    path = SOURCEDIR / "figS9_mitigation_redistribution_v2.csv"
    fields = ["panel", "group", "year", "scenario", "n_lines",
              "af_reduction_mt_co2", "capture_mt_co2", "cumulative_capture_mt_co2"]
    rows = []
    for year in YEARS:
        for group in GROUP_ORDER + ("National total",):
            ids = data["members"].get(group)
            n = len(ids) if ids is not None else sum(len(v) for v in [data["members"]["Other lines"]]) + 0
            if group == "National total":
                n = data["panel_b"]["National total"]["n_lines"]
            entry = (data["panel_a"][(year, group)] if group != "National total"
                     else {k: data["totals"][("a", year)][k] for k in ("S1", "S4", "delta")})
            for scen in ("S1", "S4"):
                rows.append(["a", group, year, scen, n,
                             f"{entry[scen][0]:.3f}", f"{entry[scen][1]:.3f}", ""])
            rows.append(["a", group, year, "S4-S1", n,
                         f"{entry['delta'][0]:.3f}", f"{entry['delta'][1]:.3f}", ""])
    for group in GROUP_ORDER + ("National total",):
        entry = data["panel_b"][group]
        for scen in ("S1", "S4"):
            rows.append(["b", group, "", scen, entry["n_lines"], "", "",
                         f"{entry[scen]:.3f}"])
        rows.append(["b", group, "", "S4-S1", entry["n_lines"], "", "",
                     f"{entry['delta']:.3f}"])
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(fields)
        writer.writerows(rows)
    return path


def main() -> int:
    data = build()
    png = draw(data)
    table = write_source_data(data)
    print("wrote", png.relative_to(ROOT))
    print("wrote", table.relative_to(ROOT))
    print("\npanel a, S4 - S1 (Mt CO2/yr)")
    for year in YEARS:
        for group in GROUP_ORDER:
            d = data["panel_a"][(year, group)]["delta"]
            print(f"  {year} {group:14s} AF {d[0]:+7.2f}   capture {d[1]:+7.2f}")
        dt = data["totals"][("a", year)]["delta"]
        print(f"  {year} {'National':14s} AF {dt[0]:+7.2f}   capture {dt[1]:+7.2f}")
    print("\npanel b, cumulative 2025-2060 (Mt CO2)")
    for group in GROUP_ORDER + ("National total",):
        e = data["panel_b"][group]
        print(f"  {group:14s} S1 {e['S1']:8.1f}  S4 {e['S4']:8.1f}  delta {e['delta']:+8.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
