#!/usr/bin/env python3
"""Build the canonical, writing-ready evidence package for the V4 paper.

V3 (2026-08-22): rebuilt on the coordinate-corrected 1,572-line fleet and
public S1--S5 case sequence, while retaining the recalibrated central parameters
(MIN_OPERATING_UTILIZATION=0.40, EARLY_RETIREMENT=130 CNY/t) and the
final_verified_inputs_20260829 run package (tightened S2/S3, new-parameter demand
sensitivities, 35-year lifetime structural check, reduced near-optimal set).

The package deliberately separates three levels of evidence:

1. demand contraction and the concentration of the surviving fleet;
2. low-carbon-suitability feedback on turnover, CCS responsibility, and routes;
3. robust-versus-conditional near-term planning objects.

The script does not re-solve the model. It freezes a documented set of solved
results, harmonizes definitions, and writes auditable tables for manuscript
figures and claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "results/v4/writing_ready_storyline_v3_20260829"
DEFAULT_PLANTS = PROJECT_ROOT / "data/model_input/plants/plant_data.xlsx"
DEFAULT_NEAROPT_MATRIX = (
    PROJECT_ROOT
    / "results/v4/final_verified_inputs_20260829/near_optimal/analysis/plant_terminal_identity_matrix.csv"
)
DEFAULT_NEAROPT_SUMMARY = (
    PROJECT_ROOT
    / "results/v4/final_verified_inputs_20260829/near_optimal/analysis/frontier_summary.csv"
)
DEFAULT_INPUT_MANIFEST = (
    PROJECT_ROOT
    / "results/v4/final_verified_inputs_20260829/_input_snapshot/final_input_manifest.csv"
)

CAPACITY_TO_KT_YEAR = 330.0 / 1000.0
MATERIAL_CAPTURE_KT = 100.0
FLOW_TOL_KT = 1e-6
YEARS = (2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060)
POST_BASE_YEARS = tuple(year for year in YEARS if year > 2025)
LATE_YEARS = (2050, 2055, 2060)


@dataclass(frozen=True)
class CaseSpec:
    key: str
    label: str
    role: str
    result_json: Path
    input_manifest: Path


@dataclass
class Case:
    spec: CaseSpec
    data: dict[str, Any]
    result_sha256: str
    manifest_sha256: str
    plants: dict[int, dict[str, Any]]
    weights: dict[int, float]


def default_specs() -> list[CaseSpec]:
    return [
        CaseSpec(
            "S1",
            "S1 heterogeneous suitability, D-medium",
            "central baseline",
            PROJECT_ROOT / "results/v4/final_verified_inputs_20260829/full/S1_baseline_results.json",
            DEFAULT_INPUT_MANIFEST,
        ),
        CaseSpec(
            "S2",
            "S2 future AF spatial advantage neutralized, D-medium",
            "primary mechanism counterfactual",
            PROJECT_ROOT / "results/v4/final_verified_inputs_20260829/full/S3_all_spatial_equalized_results.json",
            DEFAULT_INPUT_MANIFEST,
        ),
        CaseSpec(
            "S3",
            "S3 offshore transport/storage cost premia removed, D-medium",
            "secondary storage-side corroboration",
            PROJECT_ROOT / "results/v4/final_verified_inputs_20260829/full/S5_offshore_parity_results.json",
            DEFAULT_INPUT_MANIFEST,
        ),
        CaseSpec(
            "S4",
            "S1 heterogeneous suitability, D-high",
            "demand sensitivity",
            PROJECT_ROOT / "results/v4/final_verified_inputs_20260829/demand/d_high/S1_baseline_results.json",
            DEFAULT_INPUT_MANIFEST,
        ),
        CaseSpec(
            "S5",
            "S1 heterogeneous suitability, D-low",
            "demand sensitivity",
            PROJECT_ROOT / "results/v4/final_verified_inputs_20260829/demand/d_low/S1_baseline_results.json",
            DEFAULT_INPUT_MANIFEST,
        ),
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def value(mapping: Any, key: int, default: Any = 0.0) -> Any:
    if not isinstance(mapping, dict):
        return default
    return mapping.get(str(key), mapping.get(key, default))


def series(case: Case, plant_id: int, variable: str) -> dict[int, float]:
    raw = case.plants[plant_id].get(variable, {})
    return {year: number(value(raw, year)) for year in YEARS}


def summary_year(case: Case, year: int) -> dict[str, Any]:
    raw = value(case.data.get("summary", {}), year, {})
    return raw if isinstance(raw, dict) else {}


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if abs(denominator) > 1e-15 else math.nan


def load_case(spec: CaseSpec) -> Case:
    if not spec.result_json.is_file():
        raise FileNotFoundError(spec.result_json)
    if not spec.input_manifest.is_file():
        raise FileNotFoundError(spec.input_manifest)
    data = json.loads(spec.result_json.read_text(encoding="utf-8"))
    plants = {int(key): row for key, row in data["plants"].items()}
    weights = {int(key): float(val) for key, val in data["period_weights_years"].items()}
    return Case(spec, data, sha256(spec.result_json), sha256(spec.input_manifest), plants, weights)


def load_metadata(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(path).rename(
        columns={
            "id": "plant_id",
            "capacity": "capacity_t_day",
            "year of commissioning": "commission_year",
        }
    )
    expected = [
        "plant_id",
        "name",
        "province",
        "city",
        "capacity_t_day",
        "longitude",
        "latitude",
        "commission_year",
    ]
    frame = frame[expected].copy()
    frame["plant_id"] = frame["plant_id"].astype(int)
    return frame.sort_values("plant_id").reset_index(drop=True)


def hhi_and_top_share(values: Iterable[float], top_n: int = 10) -> tuple[float, float]:
    positive = sorted((max(0.0, float(item)) for item in values), reverse=True)
    total = sum(positive)
    if total <= 0:
        return math.nan, math.nan
    shares = [item / total for item in positive]
    return sum(item * item for item in shares), sum(shares[:top_n])


def route_rows(case: Case) -> Iterable[dict[str, Any]]:
    routes = case.data.get("co2_flow_routes", {})
    if not isinstance(routes, dict):
        return []
    rows: list[dict[str, Any]] = []
    for outer_year, records in routes.items():
        if not isinstance(records, list):
            continue
        for raw in records:
            row = dict(raw)
            row["period"] = int(row.get("period", outer_year))
            row["plant_id"] = int(row["plant_id"])
            row["storage_idx"] = int(row["storage_idx"])
            row["type"] = str(row.get("type", row.get("storage_type", "unknown"))).upper()
            row["flow_kt"] = number(row.get("flow_kt", row.get("flow")))
            row["is_offshore"] = bool(row.get("is_offshore", False))
            rows.append(row)
    return rows


def weighted_jaccard(left: dict[Any, float], right: dict[Any, float]) -> float:
    keys = set(left) | set(right)
    numerator = sum(min(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    denominator = sum(max(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    return safe_div(numerator, denominator)


def shared_mass_overlap(left: dict[Any, float], right: dict[Any, float]) -> float:
    """Shared mass divided by mean total mass, matching the paired analyzers."""
    keys = set(left) | set(right)
    shared = sum(min(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    mean_total = 0.5 * (sum(left.values()) + sum(right.values()))
    return safe_div(shared, mean_total)


def set_jaccard(left: set[Any], right: set[Any]) -> float:
    return safe_div(len(left & right), len(left | right))


def plant_measure(case: Case, metadata: pd.DataFrame, years: Iterable[int], mode: str) -> dict[Any, float]:
    caps = metadata.set_index("plant_id")["capacity_t_day"].to_dict()
    result: dict[Any, float] = {}
    for plant_id in case.plants:
        y = series(case, plant_id, "y")
        u = series(case, plant_id, "u")
        capture = series(case, plant_id, "captured_commercial")
        for year in years:
            weight = case.weights[year]
            if mode == "capacity_path":
                amount = caps[plant_id] * y[year]
                key = (plant_id, year)
            elif mode == "line_path":
                amount = y[year]
                key = (plant_id, year)
            elif mode == "production":
                amount = caps[plant_id] * CAPACITY_TO_KT_YEAR * u[year]
                key = (plant_id, year)
            elif mode == "capture":
                amount = capture[year]
                key = plant_id
            else:
                raise ValueError(mode)
            result[key] = result.get(key, 0.0) + weight * amount
    return result


def route_measure(case: Case, storage_only: bool = False) -> dict[Any, float]:
    result: dict[Any, float] = {}
    for row in route_rows(case):
        year = row["period"]
        if year <= 2025:
            continue
        key = (row["storage_idx"], row["type"])
        if not storage_only:
            key = (row["plant_id"],) + key
        result[key] = result.get(key, 0.0) + case.weights[year] * row["flow_kt"]
    return result


def build_inventory(cases: list[Case]) -> pd.DataFrame:
    rows = []
    for case in cases:
        solver = case.data.get("solver", {})
        rows.append(
            {
                "case": case.spec.key,
                "label": case.spec.label,
                "evidence_role": case.spec.role,
                "scenario": case.data.get("scenario"),
                "demand_scenario": case.data.get("demand_scenario"),
                "carbon_budget_case": case.data.get("carbon_budget_case"),
                "status": case.data.get("status"),
                "solver_status": solver.get("status"),
                "solution_count": int(number(solver.get("solution_count"))),
                "objective_bn_CNY": number(solver.get("objective_value")) / 1e6,
                "objective_bound_bn_CNY": number(solver.get("objective_bound")) / 1e6,
                "mip_gap_percent": 100 * number(solver.get("mip_gap")),
                "solve_time_s": number(solver.get("solve_time_s")),
                "result_sha256": case.result_sha256,
                "input_manifest_sha256": case.manifest_sha256,
                "result_json": str(case.spec.result_json.relative_to(PROJECT_ROOT)),
                "interpretation_limit": (
                    "central quantitative result"
                    if case.spec.key in {"S1", "S2"}
                    else "bound-aware; EOR-mediated"
                    if case.spec.key == "S3"
                    else "directional demand sensitivity; not fine cost comparison"
                ),
            }
        )
    return pd.DataFrame(rows)


def build_annual(cases: list[Case], metadata: pd.DataFrame) -> pd.DataFrame:
    caps = metadata.set_index("plant_id")["capacity_t_day"].to_dict()
    rows: list[dict[str, Any]] = []
    for case in cases:
        terminal = {pid for pid in case.plants if series(case, pid, "y")[2060] > 0.5}
        renew_cumulative = 0
        for year in YEARS:
            operation = {pid: series(case, pid, "y")[year] for pid in case.plants}
            utilization = {pid: series(case, pid, "u")[year] for pid in case.plants}
            renewal = {pid: series(case, pid, "r")[year] for pid in case.plants}
            capture = {
                pid: series(case, pid, "captured_commercial")[year]
                for pid in case.plants
            }
            production = {
                pid: caps[pid] * CAPACITY_TO_KT_YEAR * utilization[pid]
                for pid in case.plants
            }
            operating_capacity = {
                pid: caps[pid] * CAPACITY_TO_KT_YEAR * operation[pid]
                for pid in case.plants
            }
            renew_events = sum(1 for amount in renewal.values() if amount > 0.5)
            renew_cumulative += renew_events
            production_hhi, production_top10 = hhi_and_top_share(production.values())
            capture_hhi, capture_top10 = hhi_and_top_share(capture.values())
            summary = summary_year(case, year)
            rows.append(
                {
                    "case": case.spec.key,
                    "year": year,
                    "demand_scenario": case.data.get("demand_scenario"),
                    "cement_demand_mt": number(summary.get("cement_demand_mt")),
                    "clinker_production_mt": sum(production.values()) / 1000,
                    "operating_lines": sum(1 for amount in operation.values() if amount > 0.5),
                    "productive_lines": sum(1 for amount in production.values() if amount > 1e-6),
                    "operating_capacity_mt_per_year": sum(operating_capacity.values()) / 1000,
                    "renewal_events": renew_events,
                    "cumulative_renewal_events": renew_cumulative,
                    "active_capture_lines": sum(1 for amount in capture.values() if amount >= MATERIAL_CAPTURE_KT),
                    "captured_co2_mt": sum(capture.values()) / 1000,
                    "production_hhi": production_hhi,
                    "production_effective_lines": safe_div(1.0, production_hhi),
                    "production_top10_share": production_top10,
                    "capture_hhi": capture_hhi,
                    "capture_effective_lines": safe_div(1.0, capture_hhi),
                    "capture_top10_share": capture_top10,
                    "terminal_backbone_production_share": safe_div(
                        sum(production[pid] for pid in terminal), sum(production.values())
                    ),
                    "terminal_backbone_capture_share": safe_div(
                        sum(capture[pid] for pid in terminal), sum(capture.values())
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_overlap(cases: list[Case], metadata: pd.DataFrame) -> pd.DataFrame:
    baseline = next(case for case in cases if case.spec.key == "S1")
    caps = metadata.set_index("plant_id")["capacity_t_day"].to_dict()
    rows = []
    for compare in (case for case in cases if case.spec.key != "S1"):
        terminal_left = {pid for pid in baseline.plants if series(baseline, pid, "y")[2060] > 0.5}
        terminal_right = {pid for pid in compare.plants if series(compare, pid, "y")[2060] > 0.5}
        renew_left = {
            (pid, year)
            for pid in baseline.plants
            for year in POST_BASE_YEARS
            if series(baseline, pid, "r")[year] > 0.5
        }
        renew_right = {
            (pid, year)
            for pid in compare.plants
            for year in POST_BASE_YEARS
            if series(compare, pid, "r")[year] > 0.5
        }
        terminal_capacity_left = {pid: caps[pid] for pid in terminal_left}
        terminal_capacity_right = {pid: caps[pid] for pid in terminal_right}
        row = {
            "comparison": f"S1_vs_{compare.spec.key}",
            "comparison_role": compare.spec.role,
            "same_demand_total": baseline.data.get("demand_scenario") == compare.data.get("demand_scenario"),
            "full_period_capacity_path_jaccard": weighted_jaccard(
                plant_measure(baseline, metadata, POST_BASE_YEARS, "capacity_path"),
                plant_measure(compare, metadata, POST_BASE_YEARS, "capacity_path"),
            ),
            "full_period_line_path_jaccard": weighted_jaccard(
                plant_measure(baseline, metadata, POST_BASE_YEARS, "line_path"),
                plant_measure(compare, metadata, POST_BASE_YEARS, "line_path"),
            ),
            "late_2050_2060_capacity_path_jaccard": weighted_jaccard(
                plant_measure(baseline, metadata, LATE_YEARS, "capacity_path"),
                plant_measure(compare, metadata, LATE_YEARS, "capacity_path"),
            ),
            "terminal_site_jaccard": set_jaccard(terminal_left, terminal_right),
            "terminal_capacity_jaccard": weighted_jaccard(
                terminal_capacity_left, terminal_capacity_right
            ),
            "renewal_event_jaccard": set_jaccard(renew_left, renew_right),
            "production_distribution_overlap": shared_mass_overlap(
                plant_measure(baseline, metadata, YEARS, "production"),
                plant_measure(compare, metadata, YEARS, "production"),
            ),
            "capture_responsibility_jaccard": weighted_jaccard(
                plant_measure(baseline, metadata, POST_BASE_YEARS, "capture"),
                plant_measure(compare, metadata, POST_BASE_YEARS, "capture"),
            ),
            "source_sink_route_jaccard": weighted_jaccard(
                route_measure(baseline), route_measure(compare)
            ),
            "storage_node_type_jaccard": weighted_jaccard(
                route_measure(baseline, storage_only=True),
                route_measure(compare, storage_only=True),
            ),
            "terminal_added_lines": len(terminal_right - terminal_left),
            "terminal_lost_lines": len(terminal_left - terminal_right),
            "terminal_shared_lines": len(terminal_left & terminal_right),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def build_mechanism_summary(overlap: pd.DataFrame) -> pd.DataFrame:
    """Unify the paper-facing S2/S3 nested-decomposition metrics."""
    sources = {
        "S2": PROJECT_ROOT / "results/v4/final_verified_inputs_20260829/analysis_s2/summary_metrics.csv",
        "S3": PROJECT_ROOT / "results/v4/final_verified_inputs_20260829/analysis_s3/summary_metrics.csv",
    }
    rows: list[dict[str, Any]] = []
    for key, path in sources.items():
        metrics = pd.read_csv(path).set_index("metric")
        objective = metrics.loc["objective_incumbent"]
        lockin = metrics.loc["turnover_lockin_regret__fixed_turnover_vs_full_treatment"]
        reverse_name = next(
            name
            for name in metrics.index
            if name.startswith("reverse_turnover_sequential_regret__")
        )
        reverse = metrics.loc[reverse_name]
        identity = overlap.loc[overlap["comparison"] == f"S1_vs_{key}"].iloc[0]
        row = {
            "treatment": key,
            "evidence_role": "primary identification" if key == "S2" else "secondary corroboration",
            "total_cost_effect_bn_CNY": objective["total_effect_full_minus_baseline"],
            "pure_fixed_y_r_u_response_bn_CNY": objective["pure_direct_effect_fixed_dispatch_minus_baseline"],
            "dispatch_feedback_bn_CNY": objective["dispatch_feedback_fixed_turnover_minus_fixed_dispatch"],
            "turnover_feedback_bn_CNY": objective["turnover_feedback_full_minus_fixed_turnover"],
            "turnover_lockin_regret_bn_CNY": lockin["comparison_value"],
            "turnover_lockin_regret_lower_bn_CNY": lockin["comparison_lower_bound"],
            "turnover_lockin_regret_upper_bn_CNY": lockin["comparison_upper_bound"],
            "reverse_turnover_regret_bn_CNY": reverse["comparison_value"],
            "reverse_turnover_regret_lower_bn_CNY": reverse["comparison_lower_bound"],
            "reverse_turnover_regret_upper_bn_CNY": reverse["comparison_upper_bound"],
            "full_capacity_path_jaccard": identity["full_period_capacity_path_jaccard"],
            "late_capacity_path_jaccard": identity["late_2050_2060_capacity_path_jaccard"],
            "terminal_site_jaccard": identity["terminal_site_jaccard"],
            "line_path_jaccard": identity["full_period_line_path_jaccard"],
            "renewal_event_jaccard": identity["renewal_event_jaccard"],
            "capture_responsibility_jaccard": identity["capture_responsibility_jaccard"],
            "source_sink_route_jaccard": identity["source_sink_route_jaccard"],
            "interpretation": (
                "AF suitability changes the value of late asset survival; the sign reversal across nested cases identifies adaptation."
                if key == "S2"
                else "Storage-side feedback is reproduced, but its magnitude is strongly mediated by EOR revenues."
            ),
            "mandatory_caveat": (
                "Structural model counterfactual under D-medium/B40; not a causal estimate."
                if key == "S2"
                else "The offshore-cost response is EOR-mediated; use the current storage-feedback analysis for the exact incremental-flow share."
            ),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def build_plant_matrix(
    cases: list[Case], metadata: pd.DataFrame, nearopt_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = metadata.copy()
    for case in cases:
        terminal = []
        ever_capture = []
        early_capture = []
        cumulative_capture = []
        cumulative_production = []
        for plant_id in frame["plant_id"]:
            y = series(case, plant_id, "y")
            u = series(case, plant_id, "u")
            capture = series(case, plant_id, "captured_commercial")
            cap = float(frame.loc[frame["plant_id"] == plant_id, "capacity_t_day"].iloc[0])
            terminal.append(int(y[2060] > 0.5))
            ever_capture.append(int(any(capture[year] >= MATERIAL_CAPTURE_KT for year in POST_BASE_YEARS)))
            early_capture.append(int(any(capture[year] >= MATERIAL_CAPTURE_KT for year in (2030, 2035, 2040, 2045))))
            cumulative_capture.append(sum(case.weights[year] * capture[year] for year in POST_BASE_YEARS) / 1000)
            cumulative_production.append(
                sum(case.weights[year] * cap * CAPACITY_TO_KT_YEAR * u[year] for year in POST_BASE_YEARS) / 1000
            )
        frame[f"terminal_{case.spec.key}"] = terminal
        frame[f"ever_capture_{case.spec.key}"] = ever_capture
        frame[f"early_capture_{case.spec.key}"] = early_capture
        frame[f"cumulative_capture_mt_{case.spec.key}"] = cumulative_capture
        frame[f"cumulative_production_mt_{case.spec.key}"] = cumulative_production

    nearopt = pd.read_csv(nearopt_path)[["plant_id", "generated_case_terminal_status"]]
    frame = frame.merge(nearopt, on="plant_id", how="left", validate="one_to_one")
    case_keys = [case.spec.key for case in cases]
    frame["terminal_scenario_count"] = frame[[f"terminal_{key}" for key in case_keys]].sum(axis=1)
    frame["capture_scenario_count"] = frame[[f"ever_capture_{key}" for key in case_keys]].sum(axis=1)
    frame["early_capture_scenario_count"] = frame[[f"early_capture_{key}" for key in case_keys]].sum(axis=1)

    def asset_tier(row: pd.Series) -> str:
        count = int(row["terminal_scenario_count"])
        if count == len(case_keys) and row["generated_case_terminal_status"] == "always_operating":
            return "stable_core"
        if count >= 4:
            return "conditional_asset"
        if count >= 1:
            return "sensitive_margin"
        return "not_terminal_candidate"

    def ccs_tier(row: pd.Series) -> str:
        count = int(row["capture_scenario_count"])
        early = int(row["early_capture_scenario_count"])
        if early == len(case_keys):
            return "robust_early_source"
        if count == len(case_keys):
            return "robust_late_source"
        if count >= 3:
            return "conditional_source"
        if count >= 1:
            return "sensitive_source"
        return "not_selected"

    frame["asset_tier"] = frame.apply(asset_tier, axis=1)
    frame["ccs_responsibility_tier"] = frame.apply(ccs_tier, axis=1)
    frame["tier_use_limit"] = "scenario-screening category; not a unique plant forecast"

    summary = (
        frame.groupby(["asset_tier", "ccs_responsibility_tier"], dropna=False)
        .agg(
            plant_count=("plant_id", "size"),
            capacity_t_day=("capacity_t_day", "sum"),
            mean_terminal_scenario_count=("terminal_scenario_count", "mean"),
            mean_capture_scenario_count=("capture_scenario_count", "mean"),
        )
        .reset_index()
    )
    summary["capacity_mt_per_year"] = summary["capacity_t_day"] * CAPACITY_TO_KT_YEAR / 1000
    return frame, summary


def build_network_matrix(cases: list[Case]) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: dict[tuple[int, str], dict[str, Any]] = {}
    for case in cases:
        aggregated: dict[tuple[int, str], float] = {}
        early: dict[tuple[int, str], float] = {}
        offshore: dict[tuple[int, str], bool] = {}
        for row in route_rows(case):
            if row["period"] <= 2025:
                continue
            key = (row["storage_idx"], row["type"])
            aggregated[key] = aggregated.get(key, 0.0) + case.weights[row["period"]] * row["flow_kt"] / 1000
            if row["period"] <= 2045:
                early[key] = early.get(key, 0.0) + case.weights[row["period"]] * row["flow_kt"] / 1000
            offshore[key] = row["is_offshore"]
        for key in set(aggregated) | set(records):
            record = records.setdefault(
                key,
                {"storage_idx": key[0], "storage_type": key[1], "is_offshore": offshore.get(key)},
            )
            record[f"cumulative_flow_mt_{case.spec.key}"] = aggregated.get(key, 0.0)
            record[f"early_flow_mt_{case.spec.key}"] = early.get(key, 0.0)
            if record.get("is_offshore") is None and key in offshore:
                record["is_offshore"] = offshore[key]
    frame = pd.DataFrame(records.values()).fillna(0)
    keys = [case.spec.key for case in cases]
    frame["flow_scenario_count"] = sum(
        (frame[f"cumulative_flow_mt_{key}"] > FLOW_TOL_KT / 1000).astype(int)
        for key in keys
    )
    frame["early_flow_scenario_count"] = sum(
        (frame[f"early_flow_mt_{key}"] > FLOW_TOL_KT / 1000).astype(int)
        for key in keys
    )

    def tier(count: int) -> str:
        if count == len(keys):
            return "robust_node_type"
        if count >= 3:
            return "conditional_node_type"
        return "sensitive_node_type"

    frame["network_tier"] = frame["flow_scenario_count"].map(tier)
    frame["tier_use_limit"] = "node/type screening; exact routes remain adaptive"
    summary = (
        frame.groupby(["network_tier", "storage_type", "is_offshore"], dropna=False)
        .agg(
            node_type_count=("storage_idx", "size"),
            mean_scenario_count=("flow_scenario_count", "mean"),
            cumulative_flow_mt_S1=("cumulative_flow_mt_S1", "sum"),
            cumulative_flow_mt_S2=("cumulative_flow_mt_S2", "sum"),
            cumulative_flow_mt_S3=("cumulative_flow_mt_S3", "sum"),
            cumulative_flow_mt_S4=("cumulative_flow_mt_S4", "sum"),
            cumulative_flow_mt_S5=("cumulative_flow_mt_S5", "sum"),
        )
        .reset_index()
    )
    return frame.sort_values(["network_tier", "storage_type", "storage_idx"]), summary


def claim_register() -> pd.DataFrame:
    rows = [
        ("R1", "C1", "ready_with_caveat", "Demand contraction concentrates future production and CCS responsibility in a smaller late-period backbone.", "annual lines/capacity, concentration indices, terminal-backbone shares under S4/S1/S5", "Demand cases use the same absolute B40 budget defined against the central-demand reference BAU.", "Demand alone uniquely determines individual surviving plants."),
        ("R1", "C2", "ready", "The apparently high full-period capacity-path overlap mainly reflects inherited early stock; the turnover-sensitive late margin differs materially.", "full-period versus 2050–2060 and terminal overlaps; renewal-event overlap", "Use full-period overlap as an inertia indicator, not a turnover measure.", "Low-carbon suitability rewrites the entire fleet."),
        ("R2", "C3", "ready", "Spatial AF suitability helps form the surviving fleet rather than merely reallocating abatement across a fixed fleet.", "S2 nested forward/reverse fixed-path regret and survivor sorting", "Structural model counterfactual, not causal estimate.", "The result disproves cost minimization or establishes a causal effect."),
        ("R2", "C4", "ready_with_caveat", "Removing offshore transport/storage cost premia reproduces the capacity-feedback mechanism.", "S3 turnover lock-in regret, reverse cross-fit, survivor sorting", "Keep the current EOR-mediation share in the same paragraph.", "The experiment establishes saline-storage robustness or changes geographic accessibility."),
        ("R2", "C5", "ready", "Small changes in the capacity backbone can amplify into larger changes in plant-level CCS responsibility and source-sink design.", "capacity, survivor, renewal, capture, and route overlap cascade", "Overlaps describe model solution identity, not statistical causal effects.", "National capture totals are independently robust when the carbon budget largely imposes them."),
        ("R3", "C6", "ready_with_caveat", "A stable core can be separated from conditional assets and a sensitive margin for staged planning.", "five-scenario tier matrix plus near-optimal terminal identity", "Use categories and common infrastructure needs; do not publish deterministic plant mandates.", "Every named plant in the stable core is a certain investment target."),
        ("R3", "C7", "not_ready", "Exact plant-to-storage routes are robust near-term commitments.", "route-level scenario and near-optimal presence", "Current route identities are substantially more sensitive than fleet capacity.", "Specific pipelines can be treated as no-regret solely from current results."),
        ("R2", "C8", "not_ready", "S3 demonstrates robustness to saline-storage conditions independent of EOR revenues.", "no-EOR-credit or DSA-only diagnostic", "Not currently identified.", "Generalize the EOR-mediated S3 response to saline storage."),
    ]
    return pd.DataFrame(rows, columns=["results_section", "claim_id", "status", "allowed_claim", "evidence", "required_caveat", "forbidden_overclaim"])


def figure_blueprint() -> pd.DataFrame:
    rows = [
        ("Results 3.1", "Figure 2", "Demand contraction and backbone formation", "A: demand/production; B: operating lines and capacity; C: production and capture concentration; D: terminal-backbone shares", "annual_system_evolution.csv", "S4/S1/S5", "Primary system evolution figure; counts support, not lead."),
        ("Results 3.1", "Figure 3", "Endogenous formation of long-run CCS objects", "A: terminal asset tiers; B: CCS responsibility tiers; C: asset-by-responsibility matrix", "asset_tier_summary.csv; plant_decision_matrix.csv", "all five cases plus near-optimal screen", "Prefer tiered matrix/map; avoid deterministic plant forecast language."),
        ("Results 3.2", "Figure 4", "Capacity-feedback identification", "A: S2 nested cost decomposition; B: forward/reverse lock-in regret intervals", "mechanism_evidence_summary.csv; analysis_s2", "S2 primary", "Main identification figure."),
        ("Results 3.2", "Figure 5", "Identity amplification across planning layers", "capacity path → terminal assets/renewals → capture responsibility → source-sink routes", "cross_scenario_overlap.csv; near_optimal_frontier_summary.csv", "S2 primary, S3 secondary", "Use line-count overlap only as a supporting robustness metric."),
        ("Results 3.2", "Figure 6", "Planning specificity and time-window robustness", "stable assets; recurrent storage node-types; bounded opportunity families; exact routes", "plant/network matrices; corrected corridor post-processing", "all five cases plus near-optimal", "Objects are non-nested; do not imply monotonicity."),
        ("Results 3.3", "Figure 7", "Near-term robust versus adaptive planning objects", "A: stable/conditional/sensitive assets; B: storage node/type tiers; C: decision timing ladder", "plant_decision_matrix.csv; storage_node_decision_matrix.csv", "all five cases plus near-optimal screen", "Recommend staged commitment, not exact route lock-in."),
        ("Methods/Results", "Table 1", "Scenario and evidence hierarchy", "scenario, treatment, controlled elements, role, solver quality", "canonical_run_inventory.csv", "all", "Make S2 primary and S3 corroborative."),
        ("Discussion", "Table 2", "Claim-strength and additional-evidence register", "ready/qualified/not-ready claims and caveats", "writing_claim_register.csv", "all", "Internal drafting table; may move to supplement."),
    ]
    return pd.DataFrame(rows, columns=["section", "item", "working_title", "panels_or_columns", "data_source", "scenario_scope", "writing_note"])


def build_audits(
    cases: list[Case], inventory: pd.DataFrame, annual: pd.DataFrame,
    overlap: pd.DataFrame, plant_matrix: pd.DataFrame, network_matrix: pd.DataFrame,
) -> pd.DataFrame:
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, observed: Any, expected: Any, note: str = "") -> None:
        checks.append({"check": name, "status": status, "observed": observed, "expected": expected, "note": note})

    add("all_result_files_loaded", "PASS", len(cases), 5)
    manifest_count = inventory["input_manifest_sha256"].nunique()
    add("common_input_manifest_sha", "PASS" if manifest_count == 1 else "FAIL", manifest_count, 1)
    for case in cases:
        solver = case.data.get("solver", {})
        count = int(number(solver.get("solution_count")))
        add(f"{case.spec.key}_has_incumbent", "PASS" if count > 0 else "FAIL", count, ">0")
        plant_count = len(case.plants)
        add(f"{case.spec.key}_plant_count", "PASS" if plant_count == 1572 else "FAIL", plant_count, 1572)
        year_count = len(case.weights)
        add(f"{case.spec.key}_period_count", "PASS" if year_count == 8 else "FAIL", year_count, 8)
        gap = 100 * number(solver.get("mip_gap"))
        status = "PASS" if gap <= 0.2 else "WARN" if gap <= 1.0 else "FAIL"
        add(f"{case.spec.key}_mip_gap_percent", status, gap, "<=0.2 preferred; <=1.0 directional", "Demand cases are not used for fine cost comparisons.")
        route_total = sum(case.weights[row["period"]] * row["flow_kt"] for row in route_rows(case) if row["period"] > 2025)
        capture_total = sum(
            case.weights[year] * series(case, pid, "captured_commercial")[year]
            for pid in case.plants for year in POST_BASE_YEARS
        )
        gap_kt_year = abs(route_total - capture_total)
        add(f"{case.spec.key}_route_capture_reconciliation", "PASS" if gap_kt_year <= 1e-2 else "FAIL", gap_kt_year, "<=0.01 kt-year")
    base_anchor = annual[(annual["case"] == "S1") & (annual["year"] == 2025)].iloc[0]
    for key in inventory["case"]:
        anchor = annual[(annual["case"] == key) & (annual["year"] == 2025)].iloc[0]
        differences = max(
            abs(anchor["clinker_production_mt"] - base_anchor["clinker_production_mt"]),
            abs(anchor["operating_capacity_mt_per_year"] - base_anchor["operating_capacity_mt_per_year"]),
        )
        add(f"{key}_2025_anchor_match", "PASS" if differences <= 1e-6 else "FAIL", differences, "<=1e-6 Mt")
    bounds_ok = overlap.select_dtypes(include="number").drop(columns=["terminal_added_lines", "terminal_lost_lines", "terminal_shared_lines"]).apply(lambda col: col.dropna().between(0, 1).all()).all()
    add("overlap_metrics_bounded", "PASS" if bounds_ok else "FAIL", bool(bounds_ok), True)
    add("asset_tiers_exhaustive", "PASS" if len(plant_matrix) == 1572 and plant_matrix["asset_tier"].notna().all() else "FAIL", len(plant_matrix), 1572)
    add("network_tiers_exhaustive", "PASS" if len(network_matrix) > 0 and network_matrix["network_tier"].notna().all() else "FAIL", len(network_matrix), ">0")
    return pd.DataFrame(checks)


def write_readme(output: Path, audits: pd.DataFrame) -> None:
    pass_count = int((audits["status"] == "PASS").sum())
    warn_count = int((audits["status"] == "WARN").sum())
    fail_count = int((audits["status"] == "FAIL").sum())
    text = f"""# Writing-ready storyline evidence package

This directory freezes the analytical evidence for manuscript drafting. It does not change or re-solve the optimization model.

## Canonical evidence hierarchy

- S1 and S2 are the central, tightly solved mechanism evidence.
- S3 is secondary storage-side corroboration and must be interpreted with the EOR mediation caveat.
- S4 and S5 support demand-direction and concentration claims under the common absolute B40 budget.
- Near-optimal results limit plant-level identity claims and support tiered rather than deterministic planning recommendations.

## Storyline

The defensible mechanism is **stable inherited core → selective late-turnover reordering → amplified CCS responsibility and network change**. High whole-horizon overlap is an inertia measure; it is not evidence that turnover feedback is absent.

## Audit result

PASS={pass_count}, WARN={warn_count}, FAIL={fail_count}. Any FAIL blocks writing from this package.

## Files

- `canonical_run_inventory.csv`: source and solver-quality register.
- `annual_system_evolution.csv`: demand, fleet, renewal, concentration, and backbone metrics.
- `cross_scenario_overlap.csv`: harmonized identity and overlap metrics.
- `mechanism_evidence_summary.csv`: unified S2/S3 decomposition, regret, and amplification evidence.
- `plant_decision_matrix.csv` and `asset_tier_summary.csv`: asset and CCS responsibility tiers.
- `storage_node_decision_matrix.csv` and `network_tier_summary.csv`: storage node/type tiers.
- `near_optimal_frontier_summary.csv`: copied canonical near-optimal summary.
- `writing_claim_register.csv`: permitted claims, caveats, and prohibited overclaims.
- `figure_table_blueprint.csv`: proposed Results/Discussion exhibit structure.
- `audit_checks.csv`: reproducibility and quality checks.
- `journal_fit_matrix.csv` and `journal_positioning.md`: target-journal decision record (maintained separately from the analytical rebuild).

All asset and network tiers are scenario-screening categories, not unique plant-level forecasts.
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def write_report_snapshot(
    output: Path,
    annual: pd.DataFrame,
    overlap: pd.DataFrame,
    mechanism: pd.DataFrame,
    assets: pd.DataFrame,
    claims: pd.DataFrame,
    journals: pd.DataFrame,
    audits: pd.DataFrame,
) -> None:
    """Write bounded, reviewed rows for the in-app technical report."""
    annual_subset = annual.loc[
        annual["case"].isin(["S4", "S1", "S5"]),
        [
            "case", "year", "cement_demand_mt", "operating_lines",
            "operating_capacity_mt_per_year", "active_capture_lines",
            "captured_co2_mt", "production_hhi", "capture_hhi",
            "terminal_backbone_production_share",
            "terminal_backbone_capture_share",
        ],
    ]
    layers = [
        ("Full-period capacity path", "full_period_capacity_path_jaccard"),
        ("Late capacity path", "late_2050_2060_capacity_path_jaccard"),
        ("Terminal plants", "terminal_site_jaccard"),
        ("Renewal events", "renewal_event_jaccard"),
        ("Capture responsibility", "capture_responsibility_jaccard"),
        ("Source-sink routes", "source_sink_route_jaccard"),
    ]
    cascade = []
    for _, row in overlap.loc[overlap["comparison"].isin(["S1_vs_S2", "S1_vs_S3"])].iterrows():
        for order, (label, column) in enumerate(layers, 1):
            cascade.append(
                {
                    "treatment": str(row["comparison"]).replace("S1_vs_", ""),
                    "layer_order": order,
                    "planning_layer": label,
                    "overlap": float(row[column]),
                }
            )

    def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        return frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")

    snapshot = {
        "annual": records(annual_subset),
        "cascade": cascade,
        "mechanism": records(mechanism),
        "assets": records(assets),
        "claims": records(claims),
        "journal": records(journals),
        "audit": records(audits),
    }
    (output / "report_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plant-metadata", type=Path, default=DEFAULT_PLANTS)
    parser.add_argument("--nearopt-matrix", type=Path, default=DEFAULT_NEAROPT_MATRIX)
    parser.add_argument("--nearopt-summary", type=Path, default=DEFAULT_NEAROPT_SUMMARY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = [load_case(spec) for spec in default_specs()]
    metadata = load_metadata(args.plant_metadata)

    inventory = build_inventory(cases)
    annual = build_annual(cases, metadata)
    overlap = build_overlap(cases, metadata)
    plant_matrix, asset_summary = build_plant_matrix(cases, metadata, args.nearopt_matrix)
    network_matrix, network_summary = build_network_matrix(cases)
    mechanism = build_mechanism_summary(overlap)
    claims = claim_register()
    figures = figure_blueprint()
    audits = build_audits(cases, inventory, annual, overlap, plant_matrix, network_matrix)

    outputs = {
        "canonical_run_inventory.csv": inventory,
        "annual_system_evolution.csv": annual,
        "cross_scenario_overlap.csv": overlap,
        "plant_decision_matrix.csv": plant_matrix,
        "asset_tier_summary.csv": asset_summary,
        "storage_node_decision_matrix.csv": network_matrix,
        "network_tier_summary.csv": network_summary,
        "mechanism_evidence_summary.csv": mechanism,
        "writing_claim_register.csv": claims,
        "figure_table_blueprint.csv": figures,
        "audit_checks.csv": audits,
    }
    for filename, frame in outputs.items():
        frame.to_csv(output / filename, index=False)
    journal_path = output / "journal_fit_matrix.csv"
    if journal_path.is_file():
        journals = pd.read_csv(journal_path)
        write_report_snapshot(
            output, annual, overlap, mechanism, asset_summary, claims, journals, audits
        )
    pd.read_csv(args.nearopt_summary).to_csv(output / "near_optimal_frontier_summary.csv", index=False)
    write_readme(output, audits)

    pass_count = int((audits["status"] == "PASS").sum())
    warn_count = int((audits["status"] == "WARN").sum())
    fail_count = int((audits["status"] == "FAIL").sum())
    print(f"Writing-ready package: {output}")
    print(f"Audit: PASS={pass_count}, WARN={warn_count}, FAIL={fail_count}")
    if fail_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
