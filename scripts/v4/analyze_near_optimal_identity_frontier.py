#!/usr/bin/env python3
"""Audit and summarize the near-optimal operating-capacity identity frontier."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd


CAPACITY_T_DAY_TO_KT_YEAR = 0.33
TOL = 1e-6


def load_json(path: Path) -> tuple[dict, str]:
    path = path.expanduser().resolve()
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def load_capacity(path: Path) -> dict[int, float]:
    frame = pd.read_excel(path)
    if "plant_id" not in frame.columns and "id" in frame.columns:
        frame = frame.rename(columns={"id": "plant_id"})
    capacity_column = next(
        column
        for column in ("capacity_t_day", "capacity_t_per_day", "capacity", "Capacity")
        if column in frame.columns
    )
    return {
        int(row.plant_id): float(getattr(row, capacity_column)) * CAPACITY_T_DAY_TO_KT_YEAR
        for row in frame.itertuples(index=False)
    }


def series(result: dict, plant_id: int, variable: str) -> dict[int, float]:
    record = result["plants"][str(plant_id)]
    return {int(year): float(value) for year, value in record[variable].items()}


def years_weights(result: dict) -> tuple[list[int], dict[int, float]]:
    weights = {int(year): float(value) for year, value in result["period_weights_years"].items()}
    return sorted(weights), weights


def capacity_jaccard(
    left: dict,
    right: dict,
    capacities: dict[int, float],
    years: list[int],
    weights: dict[int, float],
) -> float:
    numerator = denominator = 0.0
    for plant_id, capacity in capacities.items():
        ly = series(left, plant_id, "y")
        ry = series(right, plant_id, "y")
        for year in years:
            numerator += weights[year] * capacity * min(ly[year], ry[year])
            denominator += weights[year] * capacity * max(ly[year], ry[year])
    return numerator / denominator if denominator else 1.0


def capacity_distance(
    left: dict,
    right: dict,
    capacities: dict[int, float],
    years: list[int],
    weights: dict[int, float],
) -> float:
    total = 0.0
    for plant_id, capacity in capacities.items():
        ly = series(left, plant_id, "y")
        ry = series(right, plant_id, "y")
        total += sum(
            weights[year] * capacity * abs(ly[year] - ry[year]) for year in years
        )
    return total


def set_jaccard(left: set, right: set) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def renewal_jaccard(left: dict, right: dict, years: list[int]) -> float:
    def events(result):
        return {
            (int(plant_id), year)
            for plant_id in result["plants"]
            for year, amount in series(result, int(plant_id), "r").items()
            if year in years and amount >= 0.5
        }

    return set_jaccard(events(left), events(right))


def capture_jaccard(left: dict, right: dict, years: list[int], weights: dict[int, float]) -> float:
    numerator = denominator = 0.0
    for plant_id in map(int, left["plants"]):
        lc = series(left, plant_id, "captured_commercial")
        rc = series(right, plant_id, "captured_commercial")
        lv = sum(weights[year] * lc[year] for year in years)
        rv = sum(weights[year] * rc[year] for year in years)
        numerator += min(lv, rv)
        denominator += max(lv, rv)
    return numerator / denominator if denominator else 1.0


def route_totals(result: dict, years: list[int], weights: dict[int, float]) -> dict[tuple, float]:
    totals: dict[tuple, float] = {}
    routes_by_year = result.get("co2_flow_routes", {}) or {}
    for year in years:
        routes = routes_by_year.get(str(year), routes_by_year.get(year, [])) or []
        for route in routes:
            key = (
                int(route["plant_id"]),
                int(route["storage_idx"]),
                str(route.get("type", "")).lower(),
            )
            totals[key] = totals.get(key, 0.0) + weights[year] * float(route["flow_kt"])
    return totals


def route_jaccard(left: dict, right: dict, years: list[int], weights: dict[int, float]) -> float:
    lv = route_totals(left, years, weights)
    rv = route_totals(right, years, weights)
    keys = set(lv) | set(rv)
    denominator = sum(max(lv.get(key, 0.0), rv.get(key, 0.0)) for key in keys)
    numerator = sum(min(lv.get(key, 0.0), rv.get(key, 0.0)) for key in keys)
    return numerator / denominator if denominator else 1.0


def finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def add_audit(rows, case_id, check, passed, detail, warning=False):
    rows.append(
        {
            "case_id": case_id,
            "check": check,
            "status": "PASS" if passed else ("WARN" if warning else "FAIL"),
            "detail": detail,
        }
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-json", type=Path, required=True)
    parser.add_argument("--cases-csv", type=Path, required=True)
    parser.add_argument(
        "--plant-data",
        type=Path,
        default=Path("data/model_input/plants/plant_data.xlsx"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--max-identity-bound-width",
        type=float,
        default=0.01,
        help="Warn when the phase-one distance interval exceeds this share of total exposure.",
    )
    parser.add_argument(
        "--preferred-economic-gap",
        type=float,
        default=0.002,
        help="Warn, but do not fail, when the economic tie-break MIP gap exceeds this value.",
    )
    args = parser.parse_args()

    baseline, baseline_sha = load_json(args.baseline_json)
    capacities = load_capacity(args.plant_data)
    all_years, weights = years_weights(baseline)
    post_years = [year for year in all_years if year > all_years[0]]
    late_years = [year for year in all_years if year >= 2050]
    terminal_year = all_years[-1]
    manifest = pd.read_csv(args.cases_csv)

    summary_rows = []
    audit_rows = []
    terminal_values: dict[str, dict[int, int]] = {
        "S1_reference": {
            plant_id: int(series(baseline, plant_id, "y")[terminal_year] >= 0.5)
            for plant_id in capacities
        }
    }

    for spec in manifest.itertuples(index=False):
        result_path = Path(spec.result_json)
        case_id = str(spec.case_id)
        exists = result_path.is_file()
        add_audit(audit_rows, case_id, "result_exists", exists, str(result_path))
        if not exists:
            continue
        result, _ = load_json(result_path)
        metadata = result.get("near_optimal_identity", {}) or {}
        cost_reference, cost_sha = load_json(Path(spec.cost_reference_json))
        identity_reference, identity_sha = load_json(Path(spec.identity_reference_json))

        add_audit(
            audit_rows,
            case_id,
            "metadata_matches_manifest",
            bool(metadata.get("enabled"))
            and result.get("scenario") == spec.scenario
            and metadata.get("direction") == spec.direction
            and metadata.get("scope") == spec.scope
            and abs(float(metadata.get("cost_tolerance_fraction")) - float(spec.cost_tolerance)) <= TOL,
            f"scenario={result.get('scenario')}; direction={metadata.get('direction')}; scope={metadata.get('scope')}",
        )
        add_audit(
            audit_rows,
            case_id,
            "reference_sha_matches",
            metadata.get("identity_reference_sha256") == identity_sha
            and metadata.get("cost_reference_sha256") == cost_sha,
            f"identity={identity_sha}; cost={cost_sha}",
        )

        solver = result.get("solver", {}) or {}
        identity_solver = metadata.get("identity_phase_solver", {}) or {}
        realized_cost = float(solver.get("objective_value", math.nan))
        cost_cap = float(metadata.get("cost_cap_kCNY", math.nan))
        add_audit(
            audit_rows,
            case_id,
            "both_phases_have_incumbents",
            float(solver.get("solution_count", 0)) > 0
            and float(identity_solver.get("solution_count", 0)) > 0,
            f"identity={identity_solver.get('solution_count')}; economic={solver.get('solution_count')}",
        )
        try:
            economic_gap = float(solver.get("mip_gap"))
        except (TypeError, ValueError):
            economic_gap = math.inf
        add_audit(
            audit_rows,
            case_id,
            "economic_phase_gap_quality",
            math.isfinite(economic_gap)
            and economic_gap <= args.preferred_economic_gap + TOL,
            f"mip_gap={economic_gap}; preferred_max={args.preferred_economic_gap}",
            warning=True,
        )
        add_audit(
            audit_rows,
            case_id,
            "realized_cost_within_cap",
            finite(realized_cost) and finite(cost_cap) and realized_cost <= cost_cap + max(1.0, abs(cost_cap) * 1e-8),
            f"realized={realized_cost}; cap={cost_cap}",
        )

        scope_years = post_years if spec.scope == "full_path" else [terminal_year]
        scope_weights = weights if spec.scope == "full_path" else {terminal_year: 1.0}
        recomputed_distance = capacity_distance(
            identity_reference, result, capacities, scope_years, scope_weights
        )
        incumbent_distance = float(metadata.get("identity_distance_incumbent", math.nan))
        bound_distance = float(metadata.get("identity_distance_bound", math.nan))
        if spec.direction == "closest":
            distance_consistent = (
                recomputed_distance <= incumbent_distance + max(1e-4, abs(incumbent_distance) * 1e-7)
                and (not finite(bound_distance) or recomputed_distance + 1e-4 >= bound_distance)
            )
        else:
            distance_consistent = (
                recomputed_distance + max(1e-4, abs(incumbent_distance) * 1e-7) >= incumbent_distance
                and (not finite(bound_distance) or recomputed_distance <= bound_distance + max(1e-4, abs(bound_distance) * 1e-7))
            )
        add_audit(
            audit_rows,
            case_id,
            "recomputed_identity_within_phase_bounds",
            distance_consistent,
            f"recomputed={recomputed_distance}; incumbent={incumbent_distance}; bound={bound_distance}",
        )
        maximum_distance = sum(
            capacities[plant_id] * scope_weights[year]
            for plant_id in capacities
            for year in scope_years
        )
        bound_width_share = (
            abs(bound_distance - incumbent_distance) / maximum_distance
            if finite(bound_distance) and maximum_distance > 0
            else math.inf
        )
        exact_nonnegative_minimum = (
            spec.direction == "closest" and incumbent_distance <= 1e-6
        )
        add_audit(
            audit_rows,
            case_id,
            "identity_phase_bound_precision",
            exact_nonnegative_minimum
            or bound_width_share <= args.max_identity_bound_width + TOL,
            f"interval_width_share={bound_width_share}; threshold={args.max_identity_bound_width}",
            warning=True,
        )

        terminal_reference = {
            plant_id
            for plant_id in capacities
            if series(identity_reference, plant_id, "y")[terminal_year] >= 0.5
        }
        terminal_case = {
            plant_id
            for plant_id in capacities
            if series(result, plant_id, "y")[terminal_year] >= 0.5
        }
        terminal_values[case_id] = {
            plant_id: int(plant_id in terminal_case) for plant_id in capacities
        }
        gained = terminal_case - terminal_reference
        lost = terminal_reference - terminal_case
        union_capacity = sum(capacities[i] for i in terminal_case | terminal_reference)
        gross_churn = sum(capacities[i] for i in gained | lost)
        changed_path_plants = sum(
            any(
                abs(series(identity_reference, plant_id, "y")[year] - series(result, plant_id, "y")[year]) > TOL
                for year in post_years
            )
            for plant_id in capacities
        )

        reference_cost = float(metadata["reference_cost_kCNY"])
        summary_rows.append(
            {
                "case_id": case_id,
                "scenario": spec.scenario,
                "direction": spec.direction,
                "scope": spec.scope,
                "cost_tolerance_fraction": float(spec.cost_tolerance),
                "realized_cost_increase_fraction": (realized_cost / reference_cost - 1.0),
                "identity_distance_incumbent": incumbent_distance,
                "identity_distance_bound": bound_distance,
                "identity_phase_mip_gap": identity_solver.get("mip_gap"),
                "identity_bound_width_share_of_exposure": bound_width_share,
                "economic_phase_mip_gap": solver.get("mip_gap"),
                "full_path_capacity_jaccard_vs_s1": capacity_jaccard(
                    baseline, result, capacities, post_years, weights
                ),
                "late_2050_2060_capacity_jaccard_vs_s1": capacity_jaccard(
                    baseline, result, capacities, late_years, weights
                ),
                "terminal_capacity_jaccard_vs_s1": capacity_jaccard(
                    baseline, result, capacities, [terminal_year], {terminal_year: 1.0}
                ),
                "terminal_site_jaccard_vs_s1": set_jaccard(
                    {
                        plant_id
                        for plant_id in capacities
                        if series(baseline, plant_id, "y")[terminal_year] >= 0.5
                    },
                    terminal_case,
                ),
                "renewal_event_jaccard_vs_s1": renewal_jaccard(
                    baseline, result, post_years
                ),
                "capture_responsibility_jaccard_vs_s1": capture_jaccard(
                    baseline, result, all_years, weights
                ),
                "route_flow_jaccard_vs_s1": route_jaccard(
                    baseline, result, all_years, weights
                ),
                "changed_y_path_plants_vs_identity_reference": changed_path_plants,
                "terminal_added_plants_vs_identity_reference": len(gained),
                "terminal_lost_plants_vs_identity_reference": len(lost),
                "terminal_gross_churn_share_vs_identity_reference": (
                    gross_churn / union_capacity if union_capacity else 0.0
                ),
                "result_json": str(result_path),
            }
        )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(summary_rows).sort_values(
        ["scope", "cost_tolerance_fraction", "scenario"]
    )
    audits = pd.DataFrame(audit_rows)
    summary.to_csv(output_dir / "frontier_summary.csv", index=False)
    audits.to_csv(output_dir / "audit_checks.csv", index=False)

    matrix = pd.DataFrame({"plant_id": sorted(capacities)})
    for label, values_by_plant in terminal_values.items():
        matrix[label] = matrix["plant_id"].map(values_by_plant).astype(int)
    case_columns = [column for column in matrix if column != "plant_id"]
    matrix["generated_case_terminal_status"] = matrix[case_columns].apply(
        lambda row: "always_operating" if row.min() == 1 else (
            "always_closed" if row.max() == 0 else "case_sensitive"
        ),
        axis=1,
    )
    matrix.to_csv(output_dir / "plant_terminal_identity_matrix.csv", index=False)

    passed = int((audits["status"] == "PASS").sum()) if not audits.empty else 0
    warned = int((audits["status"] == "WARN").sum()) if not audits.empty else 0
    failed = int((audits["status"] == "FAIL").sum()) if not audits.empty else 0
    report = [
        "# Near-optimal operating-capacity identity frontier",
        "",
        f"- Cases summarized: {len(summary)}",
        f"- Audits: PASS={passed}, WARN={warned}, FAIL={failed}",
        f"- S1 identity reference SHA256: `{baseline_sha}`",
        "- `closest` cases estimate the minimum best-known identity deviation within each cost cap.",
        "- `farthest` S1 cases measure how much identity can drift in the unchanged environment.",
        "- Phase-one incumbent/bound intervals must be retained when interpreting unavoidable or possible distance.",
        "",
        "## Files",
        "",
        "- `frontier_summary.csv`: cost–identity frontier and downstream overlaps.",
        "- `plant_terminal_identity_matrix.csv`: terminal status across every generated extremal case.",
        "- `audit_checks.csv`: provenance, feasibility, cap, and distance checks.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Near-optimal identity analysis: {output_dir}")
    print(f"Audits: PASS={passed}, WARN={warned}, FAIL={failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
