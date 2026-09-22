"""Deliverable 1 (Fig. 4d data source): capture-task decomposition by
2060-retention-identity groups, C1 vs C4, 2045 and 2060.

Groups are FIXED by 2060 operating identity:
  shared   = operating in both C1 and C4 in 2060 (expect 294 lines, 459.0 Mt/yr)
  C1-only  = operating in C1 2060 only (42 lines, 63.1 Mt/yr; rd_numbers CSV)
  C4-only  = operating in C4 2060 only (35 lines, 59.2 Mt/yr; rd_numbers CSV)

For each scenario x year x group:
  - commercial capture total (Mt CO2/yr), from the result-JSON per-plant
    `captured_commercial` (identical source to the Fig. 5 capture split);
  - number of capture lines under two calibers: >10 kt/yr (primary) and >0
    (comparison). Positive commercial capture is bounded below by
    CCS_MIN_CAPTURE_LOAD x min_active_design = 0.20 x 100 = 20 kt/yr, so the
    two calibers coincide in practice (verified below);
  - number of group lines actually operating in that scenario-year (2045
    activity taken from the realized results, not assumed).

Closure check: group capture sums must equal national commercial capture
(C1: 2045=212.2, 2060=305.3; C4: 2045=187.9, 2060=297.0 Mt; tol 0.1 Mt).

No optimization is run; only formal results in v5/results/formal_v1_20260914.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "v5/results/formal_v1_20260914"
SCEN = ROOT / "v5/scenarios/rd_numbers_20260915"
OUTDIR = Path(__file__).resolve().parent

RESULT_JSON = {
    "C1": RUNS / "C1_central_J/S1_baseline_results.json",
    "C4": RUNS / "C4_equalized_J/S3_all_spatial_equalized_results.json",
}
CSV_DIR = {
    "C1": RUNS / "C1_central_J/S1_baseline",
    "C4": RUNS / "C4_equalized_J/S3_all_spatial_equalized",
}
YEARS = [2045, 2060]
EXPECTED_NATIONAL = {  # Mt CO2/yr, manuscript Sec. 3.2
    ("C1", 2045): 212.2, ("C1", 2060): 305.3,
    ("C4", 2045): 187.9, ("C4", 2060): 297.0,
}
EXPECTED_GROUP_CAPACITY_MT = {"shared": 459.0, "C1-only": 63.1, "C4-only": 59.2}
EXPECTED_GROUP_LINES = {"shared": 294, "C1-only": 42, "C4-only": 35}
CAPTURE_LINE_THRESHOLD_KT = 10.0


def operating_set(scenario: str, year: int) -> set[int]:
    status = pd.read_csv(CSV_DIR[scenario] / "full_operation_status.csv")
    sub = status[(status.period == year) & (status.operating == 1)]
    return set(sub.plant_id.astype(int))


def plant_capture(scenario: str, year: int) -> dict[int, float]:
    """plant_id -> commercial capture (kt CO2/yr) in the given year."""
    plants = json.loads(RESULT_JSON[scenario].read_text())["plants"]
    key = str(year)
    return {
        int(pid): float(entry.get("captured_commercial", {}).get(key, 0.0))
        for pid, entry in plants.items()
    }


def main() -> None:
    op_c1_2060 = operating_set("C1", 2060)
    op_c4_2060 = operating_set("C4", 2060)
    groups = {
        "shared": op_c1_2060 & op_c4_2060,
        "C1-only": op_c1_2060 - op_c4_2060,
        "C4-only": op_c4_2060 - op_c1_2060,
    }
    # Cross-check against the registered swap-group CSVs.
    c1_only_csv = set(pd.read_csv(SCEN / "data02_C1-only_plants.csv").plant_id.astype(int))
    c4_only_csv = set(pd.read_csv(SCEN / "data02_C4-only_plants.csv").plant_id.astype(int))
    assert groups["C1-only"] == c1_only_csv and groups["C4-only"] == c4_only_csv

    cap = (
        pd.read_csv(CSV_DIR["C1"] / "full_plant_summary.csv")
        .set_index("plant_id")["annual_capacity_kt_per_year"] / 1000.0
    )
    print("--- group identity check (2060 retention) ---")
    for name, ids in groups.items():
        cap_sum = float(cap.loc[list(ids)].sum())
        print(f"  {name}: {len(ids)} lines, {cap_sum:.1f} Mt/yr")
        assert len(ids) == EXPECTED_GROUP_LINES[name], (name, len(ids))
        assert abs(cap_sum - EXPECTED_GROUP_CAPACITY_MT[name]) < 0.1, (name, cap_sum)

    summaries = {
        scen: json.loads(RESULT_JSON[scen].read_text())["summary"] for scen in ("C1", "C4")
    }
    op_status = {
        scen: pd.read_csv(CSV_DIR[scen] / "full_operation_status.csv")
        for scen in ("C1", "C4")
    }

    rows = []
    print("\n--- capture decomposition ---")
    for scen in ("C1", "C4"):
        for year in YEARS:
            cap_by_plant = plant_capture(scen, year)
            active = set(
                op_status[scen]
                .loc[(op_status[scen].period == year) & (op_status[scen].operating == 1),
                     "plant_id"]
                .astype(int)
            )
            national = sum(cap_by_plant.values()) / 1000.0
            expected = EXPECTED_NATIONAL[(scen, year)]
            json_total = summaries[scen][str(year)]["commercial_captured_co2_kt"] / 1000.0
            assert abs(national - json_total) < 1e-6, (scen, year, national, json_total)
            group_sum = 0.0
            for name, ids in groups.items():
                ids = sorted(ids)
                values = pd.Series({pid: cap_by_plant.get(pid, 0.0) for pid in ids})
                total_mt = float(values.sum()) / 1000.0
                group_sum += total_mt
                n_gt10 = int((values > CAPTURE_LINE_THRESHOLD_KT).sum())
                n_gt0 = int((values > 0.0).sum())
                min_positive = float(values[values > 0].min()) if n_gt0 else float("nan")
                n_operating = len(set(ids) & active)
                rows.append({
                    "scenario": scen,
                    "year": year,
                    "group": name,
                    "group_lines_2060_identity": len(ids),
                    "group_capacity_mt_per_yr": round(float(cap.loc[ids].sum()), 3),
                    "lines_operating_in_scenario_year": n_operating,
                    "capture_lines_gt10kt": n_gt10,
                    "capture_lines_gt0": n_gt0,
                    "commercial_capture_mt_per_yr": round(total_mt, 3),
                    "min_positive_capture_kt": round(min_positive, 1) if n_gt0 else "",
                })
            assert abs(group_sum - national) < 1e-6, (scen, year, group_sum, national)
            assert abs(group_sum - expected) < 0.1, (scen, year, group_sum, expected)
            print(f"  {scen} {year}: groups sum {group_sum:.3f} Mt = national "
                  f"{national:.3f} Mt (expected {expected})  OK")
            rows.append({
                "scenario": scen,
                "year": year,
                "group": "TOTAL",
                "group_lines_2060_identity": sum(len(v) for v in groups.values()),
                "group_capacity_mt_per_yr": round(float(cap.loc[sorted(set().union(*groups.values()))].sum()), 3),
                "lines_operating_in_scenario_year": len(active),
                "capture_lines_gt10kt": int(sum(r["capture_lines_gt10kt"] for r in rows
                                                if r["scenario"] == scen and r["year"] == year)),
                "capture_lines_gt0": int(sum(r["capture_lines_gt0"] for r in rows
                                             if r["scenario"] == scen and r["year"] == year)),
                "commercial_capture_mt_per_yr": round(national, 3),
                "min_positive_capture_kt": "",
            })

    df = pd.DataFrame(rows)
    out = OUTDIR / "capture_task_decomposition.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
