#!/usr/bin/env python3
"""Freeze-gate audit for the coordinate-corrected 2026-08-29 submission batch.

This audit reflects the manuscript-facing S1--S5 design rather than the
obsolete five-switch scenario set used by ``audit_final_results.py``.
It never changes solved outputs.  It writes an inspectable registry, checks,
hash manifest, and evidence-lock report under the result root.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


PROJECT = Path(__file__).resolve().parents[2]
MAIN = PROJECT / os.environ.get(
    "CF_OUTPUT_ROOT", "results/v4/final_verified_inputs_20260829"
)
UTIL = PROJECT / os.environ.get(
    "CF_UTIL_OUTPUT_ROOT", "results/v4/min_utilization_verified_inputs_20260829"
)
OUT = MAIN / "_submission_audit"
YEARS = list(range(2025, 2061, 5))
TOL = 1e-5
DEMAND_BALANCE_RELATIVE_TOLERANCE = 5e-8


@dataclass(frozen=True)
class Case:
    case_id: str
    public_case: str
    role: str
    path: Path
    scenario: str
    demand: str = "d_medium"
    lifetime: int = 40
    min_util: float = 0.40
    max_gap: float = 0.003
    mode: str = "normal"


def cases() -> list[Case]:
    m = MAIN
    u = UTIL
    rows = [
        Case("core_s1", "S1", "core", m / "full/S1_baseline_results.json", "S1_baseline", max_gap=0.0011),
        Case("core_s2", "S2", "core", m / "full/S3_all_spatial_equalized_results.json", "S3_all_spatial_equalized", max_gap=0.0011),
        Case("core_s3", "S3", "core_auxiliary", m / "full/S5_offshore_parity_results.json", "S5_offshore_parity", max_gap=0.0011),
        Case("s2_fixed_s1_turnover", "S2", "fixed_path", m / "s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json", "S3_all_spatial_equalized", max_gap=0.0012, mode="fixed"),
        Case("s2_fixed_s1_dispatch", "S2", "fixed_path", m / "s2_fixed_s1_dispatch/S3_all_spatial_equalized_results.json", "S3_all_spatial_equalized", max_gap=0.0012, mode="fixed"),
        Case("s3_fixed_s1_turnover", "S3", "fixed_path_auxiliary", m / "s3_fixed_s1_turnover/S5_offshore_parity_results.json", "S5_offshore_parity", max_gap=0.0012, mode="fixed"),
        Case("s3_fixed_s1_dispatch", "S3", "fixed_path_auxiliary", m / "s3_fixed_s1_dispatch/S5_offshore_parity_results.json", "S5_offshore_parity", max_gap=0.0012, mode="fixed"),
        Case("s1_fixed_s1_turnover_control", "S1", "null_control", m / "s1_fixed_s1_turnover_control/S1_baseline_results.json", "S1_baseline", max_gap=0.0012, mode="fixed"),
        Case("s1_fixed_s2_turnover", "S1", "reverse_fixed_path", m / "s1_fixed_s2_turnover/S1_baseline_results.json", "S1_baseline", max_gap=0.0012, mode="fixed"),
        Case("s1_fixed_s2_dispatch", "S1", "reverse_fixed_path", m / "s1_fixed_s2_dispatch/S1_baseline_results.json", "S1_baseline", max_gap=0.0012, mode="fixed"),
        Case("s1_fixed_s3_turnover", "S1", "reverse_fixed_path_auxiliary", m / "s1_fixed_s3_turnover/S1_baseline_results.json", "S1_baseline", max_gap=0.0012, mode="fixed"),
        Case("s1_fixed_s3_dispatch", "S1", "reverse_fixed_path_auxiliary", m / "s1_fixed_s3_dispatch/S1_baseline_results.json", "S1_baseline", max_gap=0.0012, mode="fixed"),
        Case("d_high", "S4", "demand_sensitivity", m / "demand/d_high/S1_baseline_results.json", "S1_baseline", demand="d_high"),
        Case("d_low", "S5", "demand_sensitivity", m / "demand/d_low/S1_baseline_results.json", "S1_baseline", demand="d_low"),
        Case("l35_s1", "S1", "lifetime_sensitivity", m / "lifetime35/full/S1_baseline_results.json", "S1_baseline", lifetime=35),
        Case("l35_s2", "S2", "lifetime_sensitivity", m / "lifetime35/full/S3_all_spatial_equalized_results.json", "S3_all_spatial_equalized", lifetime=35),
        Case("l35_s2_fixed_s1_turnover", "S2", "lifetime_fixed_path", m / "lifetime35/s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json", "S3_all_spatial_equalized", lifetime=35, max_gap=0.0012, mode="fixed"),
        Case("near_s1_farthest_terminal", "S1", "near_optimal_representative", m / "near_optimal/s1_farthest_terminal_e0010/S1_baseline_results.json", "S1_baseline", mode="near"),
        Case("near_s2_closest_terminal", "S2", "near_optimal_representative", m / "near_optimal/s2_closest_terminal_e0010/S3_all_spatial_equalized_results.json", "S3_all_spatial_equalized", mode="near"),
        Case("near_s3_closest_terminal", "S3", "near_optimal_representative_auxiliary", m / "near_optimal/s3_closest_terminal_e0010/S5_offshore_parity_results.json", "S5_offshore_parity", mode="near"),
        Case("near_s1_farthest_full", "S1", "near_optimal_representative", m / "near_optimal/s1_farthest_full_e0010/S1_baseline_results.json", "S1_baseline", mode="near"),
    ]
    for value in (0.20, 0.30, 0.50):
        tag = f"u{round(value * 100):03d}"
        root = u / tag
        rows.extend(
            [
                Case(f"{tag}_s1", "S1", "utilization_sensitivity", root / "full/S1_baseline_results.json", "S1_baseline", min_util=value),
                Case(f"{tag}_s2", "S2", "utilization_sensitivity", root / "full/S3_all_spatial_equalized_results.json", "S3_all_spatial_equalized", min_util=value),
                Case(f"{tag}_s2_fixed_s1_turnover", "S2", "utilization_fixed_path", root / "s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json", "S3_all_spatial_equalized", min_util=value, max_gap=0.0012, mode="fixed"),
            ]
        )
    return rows


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def num(value, default=math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def add(checks: list[dict], scope: str, check: str, status: str, observed, expected, detail=""):
    checks.append({"scope": scope, "check": check, "status": status, "observed": observed, "expected": expected, "detail": detail})


def audit_case(case: Case, checks: list[dict]) -> dict:
    if not case.path.is_file():
        add(checks, case.case_id, "result_exists", "FAIL", "missing", str(case.path.relative_to(PROJECT)))
        return {"case_id": case.case_id, "public_case": case.public_case, "role": case.role, "path": str(case.path.relative_to(PROJECT)), "exists": False}
    d = json.loads(case.path.read_text(encoding="utf-8"))
    solver = d.get("solver") or {}
    assumptions = d.get("model_assumptions") or {}
    summary = {int(k): v for k, v in (d.get("summary") or {}).items()}
    plants = d.get("plants") or {}
    add(checks, case.case_id, "result_exists", "PASS", "present", "present")
    metadata_ok = d.get("scenario") == case.scenario and d.get("demand_scenario") == case.demand and d.get("carbon_budget_case") == "B40"
    add(checks, case.case_id, "scenario_metadata", "PASS" if metadata_ok else "FAIL", f"{d.get('scenario')};{d.get('demand_scenario')};{d.get('carbon_budget_case')}", f"{case.scenario};{case.demand};B40")
    solver_ok = str(solver.get("status", "")).lower() == "optimal" and str(solver.get("term_cond", "")).lower() == "optimal" and num(solver.get("solution_count"), 0) >= 1
    add(checks, case.case_id, "solver_incumbent", "PASS" if solver_ok else "FAIL", f"{solver.get('status')}/{solver.get('term_cond')}; n={solver.get('solution_count')}", "optimal/optimal; n>=1")
    gap = num(solver.get("mip_gap"))
    bounds_ok = math.isfinite(num(solver.get("objective_value"))) and math.isfinite(num(solver.get("objective_bound"))) and math.isfinite(gap) and gap <= case.max_gap + 1e-12
    add(checks, case.case_id, "solver_bound_and_gap", "PASS" if bounds_ok else "FAIL", f"gap={gap:.9g}; UB={solver.get('objective_value')}; LB={solver.get('objective_bound')}", f"finite; gap<={case.max_gap}")
    assumptions_ok = len(plants) == 1572 and int(assumptions.get("plant_lifetime_years", -1)) == case.lifetime and abs(num(assumptions.get("minimum_operating_utilization")) - case.min_util) <= 1e-10 and abs(num(assumptions.get("early_retirement_cost_cny_per_t_annual_capacity")) - 130.0) <= 1e-10
    add(checks, case.case_id, "turnover_assumptions", "PASS" if assumptions_ok else "FAIL", f"plants={len(plants)}; life={assumptions.get('plant_lifetime_years')}; min_util={assumptions.get('minimum_operating_utilization')}; exit={assumptions.get('early_retirement_cost_cny_per_t_annual_capacity')}", "1572; lifetime as registered; min utilization as registered; exit=130")
    years_ok = sorted(summary) == YEARS
    add(checks, case.case_id, "time_horizon", "PASS" if years_ok else "FAIL", sorted(summary), YEARS)
    demand_balance_rows = [
        (
            abs(num(summary[y].get("clinker_balance_gap_kt"), math.inf)),
            max(
                1e-4,
                abs(num(summary[y].get("clinker_demand_kt"), 0.0))
                * DEMAND_BALANCE_RELATIVE_TOLERANCE,
            ),
        )
        for y in YEARS
    ]
    max_demand_gap = max((gap for gap, _ in demand_balance_rows), default=math.inf)
    max_demand_guard = max((guard for _, guard in demand_balance_rows), default=1e-4)
    demand_balance_ok = all(gap <= guard for gap, guard in demand_balance_rows)
    max_national_emission_gap = max((abs(num(summary[y].get("gross_co2_kt")) - num(summary[y].get("commercial_captured_co2_kt")) - num(summary[y].get("net_co2_kt"))) for y in YEARS), default=math.inf)
    add(
        checks,
        case.case_id,
        "national_balances",
        "PASS" if demand_balance_ok and max_national_emission_gap <= 1e-4 else "FAIL",
        f"demand={max_demand_gap:.6g}; emissions={max_national_emission_gap:.6g}",
        (
            f"demand<=max(1e-4 kt, {DEMAND_BALANCE_RELATIVE_TOLERANCE:g} × period demand) "
            f"(largest guard={max_demand_guard:.6g} kt); emissions<=1e-4 kt"
        ),
    )
    budget = d.get("cumulative_budget") or {}
    fixed_reference_reduction = num(
        budget.get("actual_reduction_vs_fixed_reference_bau"), -math.inf
    )
    budget_ok = (
        bool(budget.get("enabled"))
        and budget.get("baseline") == "fixed_d_medium_reference_bau"
        and abs(num(budget.get("reduction_target")) - 0.40) <= 1e-10
        and fixed_reference_reduction >= 0.40 - 1e-9
        and abs(num(budget.get("slack_kt_year"), math.inf)) <= 1e-4
    )
    add(
        checks,
        case.case_id,
        "carbon_budget",
        "PASS" if budget_ok else "FAIL",
        (
            f"baseline={budget.get('baseline')}; target={budget.get('reduction_target')}; "
            f"vs_fixed={fixed_reference_reduction}; "
            f"vs_active={budget.get('actual_reduction_vs_active_demand_bau')}; "
            f"slack={budget.get('slack_kt_year')}"
        ),
        "40% relative to frozen d_medium reference BAU; slack<=1e-4",
    )
    max_flow_gap = max((abs(num(v.get("flow_capture_gap_kt"), math.inf)) for v in (d.get("ccs_transport_storage") or {}).values()), default=math.inf)
    add(checks, case.case_id, "capture_flow_balance", "PASS" if max_flow_gap <= 1e-4 else "FAIL", max_flow_gap, "<=1e-4 kt")
    state_errors = 0
    plant_emission_gap = 0.0
    for pdata in plants.values():
        y = {int(k): num(v) for k, v in pdata["y"].items()}
        r = {int(k): num(v) for k, v in pdata["r"].items()}
        util = {int(k): num(v) for k, v in pdata["u"].items()}
        z = {int(k): num(v) for k, v in pdata["z"].items()}
        gross = {int(k): num(v) for k, v in pdata["co2_gross"].items()}
        process = {int(k): num(v) for k, v in pdata["co2_process"].items()}
        fuel = {int(k): num(v) for k, v in pdata["co2_fuel"].items()}
        capture = {int(k): num(v) for k, v in pdata["captured_commercial"].items()}
        net = {int(k): num(v) for k, v in pdata["co2_net"].items()}
        state_errors += sum(abs(v - round(v)) > 1e-6 for mapping in (y, r, z) for v in mapping.values())
        state_errors += int(sum(v > 0.5 for v in r.values()) > 1)
        for idx, year in enumerate(YEARS):
            plant_emission_gap = max(plant_emission_gap, abs(fuel[year] + process[year] - gross[year]), abs(gross[year] - capture[year] - net[year]))
            state_errors += int(year > 2025 and y[year] > 0.5 and util[year] < case.min_util - 1e-6)
            state_errors += int(y[year] < 0.5 and abs(util[year]) > 1e-6)
            state_errors += int(z[year] > 0.5 and y[year] < 0.5)
            if idx:
                prior = YEARS[idx - 1]
                state_errors += int(y[year] > 0.5 and y[prior] < 0.5 and r[year] < 0.5)
    add(checks, case.case_id, "plant_state_and_emission_integrity", "PASS" if state_errors == 0 and plant_emission_gap <= 1e-4 else "FAIL", f"state_errors={state_errors}; max_emission_gap={plant_emission_gap:.6g}", "0; <=1e-4 kt")
    cf = d.get("capacity_path_counterfactual") or {}
    mode_ok = (case.mode != "fixed" and not bool(cf.get("enabled"))) or (case.mode == "fixed" and bool(cf.get("enabled")) and int(cf.get("fixed_plants", -1)) == 1572)
    if case.mode == "near":
        near = d.get("near_optimal_identity") or {}
        econ = near.get("economic_tiebreak_solver") or {}
        mode_ok = bool(near.get("enabled")) and num(econ.get("solution_count"), 0) >= 1 and num(near.get("realized_cost_kCNY"), math.inf) <= num(near.get("cost_cap_kCNY"), -math.inf) + 1e-3
        ident = near.get("identity_phase_solver") or {}
        ident_status = "PASS" if num(ident.get("solution_count"), 0) >= 1 else "FAIL"
        add(checks, case.case_id, "near_optimal_identity_incumbent", ident_status, f"status={ident.get('status')}; gap={ident.get('mip_gap')}; incumbent={near.get('identity_distance_incumbent')}; bound={near.get('identity_distance_bound')}", "feasible representative; not a strict frontier bound", "Identity phase time limits require representative-only interpretation.")
    add(checks, case.case_id, "experiment_metadata", "PASS" if mode_ok else "FAIL", case.mode, "metadata consistent with registered mode")
    objective_gap = abs(num((d.get("cost_breakdown_total") or {}).get("objective_gap_kCNY"), math.inf))
    add(checks, case.case_id, "objective_reconciliation", "PASS" if objective_gap <= 1e-3 else "FAIL", objective_gap, "<=1e-3 kCNY")
    return {
        "case_id": case.case_id, "public_case": case.public_case, "role": case.role,
        "path": str(case.path.relative_to(PROJECT)), "exists": True,
        "internal_scenario": d.get("scenario"), "demand": d.get("demand_scenario"),
        "lifetime": assumptions.get("plant_lifetime_years"), "minimum_utilization": assumptions.get("minimum_operating_utilization"),
        "solver_gap": gap, "objective_kCNY": solver.get("objective_value"), "objective_bound_kCNY": solver.get("objective_bound"),
        "sha256": sha256(case.path),
    }


def audit_input_manifest(checks: list[dict]) -> list[dict]:
    manifest = PROJECT / "results/v4/final_protocol_validation/final_input_manifest.csv"
    rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
    mismatches = []
    for row in rows:
        path = PROJECT / row["path"]
        if not path.is_file() or sha256(path) != row["sha256"] or path.stat().st_size != int(row["size_bytes"]):
            mismatches.append(row["path"])
    add(checks, "provenance", "input_and_code_manifest_unchanged", "PASS" if not mismatches else "FAIL", f"entries={len(rows)}; mismatches={len(mismatches)}", "all frozen inputs/code/workflow hashes match", "; ".join(mismatches[:20]))
    return rows


def audit_analysis(checks: list[dict]):
    roots = [MAIN / "analysis_s2", MAIN / "analysis_s3", MAIN / "lifetime35/analysis_s2"] + [UTIL / f"u{v:03d}/analysis_s2" for v in (20, 30, 50)]
    for root in roots:
        path = root / "audit_checks.csv"
        if not path.is_file():
            add(checks, str(root.relative_to(PROJECT)), "analysis_audit", "FAIL", "missing", "audit_checks.csv present")
            continue
        df = pd.read_csv(path)
        counts = df["status"].value_counts().to_dict()
        ok = counts.get("FAIL", 0) == 0 and counts.get("WARN", 0) == 0 and counts.get("PASS", 0) == len(df)
        add(checks, str(root.relative_to(PROJECT)), "analysis_audit", "PASS" if ok else "FAIL", counts, "all rows PASS")


def write_outputs(registry: pd.DataFrame, checks: pd.DataFrame, input_rows: list[dict]):
    OUT.mkdir(parents=True, exist_ok=True)
    registry.to_csv(OUT / "result_registry.csv", index=False)
    checks.to_csv(OUT / "audit_checks.csv", index=False)
    artifact_rows = []
    for root in (MAIN, UTIL):
        for path in sorted(root.rglob("*")):
            if path.is_file() and OUT not in path.parents:
                artifact_rows.append({"path": str(path.relative_to(PROJECT)), "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    pd.DataFrame(artifact_rows).to_csv(OUT / "artifact_manifest.csv", index=False)
    pd.DataFrame(input_rows).to_csv(OUT / "frozen_input_code_manifest.csv", index=False)
    counts = checks["status"].value_counts().to_dict()
    failures = checks[checks.status == "FAIL"]
    warnings = checks[checks.status == "WARN"]
    near = checks[checks.check == "near_optimal_identity_incumbent"]
    text = [
        "# Submission evidence freeze audit — 2026-08-29 corrected-input batch", "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}", "",
        f"**Freeze decision: {'PASS' if failures.empty else 'FAIL'}**", "",
        f"- Registered solved result packages: {len(registry)} (main 21; utilization sensitivity 9).",
        f"- Automated freeze-gate checks: PASS {counts.get('PASS', 0)}, WARN {counts.get('WARN', 0)}, FAIL {counts.get('FAIL', 0)}.",
        f"- Frozen artifact files hashed: {len(artifact_rows)}.",
        "- Public scenario mapping: S1 central; S2 AF-spatial neutralization; S3 offshore cost parity (auxiliary); S4 slow contraction; S5 deep contraction.", "",
        "## Evidence boundaries", "",
        "1. S2 is the primary turnover–suitability identification experiment. S3 is auxiliary because offshore cost parity can alter DSA/EOR allocation.",
        "2. Near-optimal identity cases are feasible representative solutions inside a 0.1% cost envelope. Their identity phases reached time limits with non-tight bounds, so they do not define strict extrema or complete identity ranges.",
        "3. S4/S5 demand sensitivities retain the same absolute B40 budget defined against the frozen central-demand reference BAU. Their reductions relative to their own active-demand BAU therefore need not equal 40%.",
        "4. Annual storage injectivity remains disabled because the available raster represents theoretical maxima; cumulative storage capacity is enforced.",
        "5. Forty-six plants have no eligible storage candidate within 500 km. This is the expected spatial cascade after the verified 57-coordinate update, not a failed solve.",
        "6. No constraint prohibiting CCS additions after 2045 is part of the registered protocol.", "",
        "## Near-optimal diagnostic status", "",
    ]
    for row in near.itertuples(index=False):
        text.append(f"- {row.scope}: {row.observed}. {row.detail}")
    text += ["", "## Frozen evidence roots", "", f"- `{MAIN.relative_to(PROJECT)}`", f"- `{UTIL.relative_to(PROJECT)}`", "", "All quantitative manuscript and figure refreshes must trace to the registry and artifact manifest in this directory. Results dated 2026-08-16 or earlier remain historical layout evidence only."]
    (OUT / "EVIDENCE_FREEZE.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def main():
    checks: list[dict] = []
    registry = pd.DataFrame([audit_case(case, checks) for case in cases()])
    input_rows = audit_input_manifest(checks)
    audit_analysis(checks)
    checks_df = pd.DataFrame(checks)
    write_outputs(registry, checks_df, input_rows)
    print(checks_df["status"].value_counts().to_string())
    print(f"Registered results: {len(registry)}")
    print(f"Audit: {OUT / 'EVIDENCE_FREEZE.md'}")
    if (checks_df["status"] == "FAIL").any():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
