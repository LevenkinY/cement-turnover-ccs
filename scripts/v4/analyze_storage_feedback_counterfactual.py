#!/usr/bin/env python3
"""Analyze the nested S5 offshore-storage feedback counterfactual.

Required cases
--------------
``baseline``
    Fully coupled S1 under heterogeneous storage costs.
``s5_full``
    Fully coupled S5 with offshore pipeline and storage cost multipliers set
    equal to their onshore counterparts.
``s5_fixed_turnover``
    S5 re-optimized after fixing the S1 y/r path.

Optional cases add the stricter S5 y/r/u counterfactual, the same-environment
S1 null control, and reverse cross-fits that impose the fully coupled S5 y/r or
y/r/u plan under actual S1 conditions.  Exact solved JSON decision mappings
are authoritative.  Plant/storage metadata are used only to characterize the
sorting mechanism, never to reconstruct solved decisions.

The script deliberately lives beside, rather than inside, the S3 analyzer.
It reuses its audited JSON readers and within-case checks while keeping S3
scenario labels and outputs unchanged.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
MODEL_ROOT = PROJECT_ROOT / "models" / "v4"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))

import analyze_capacity_feedback_counterfactual as core  # noqa: E402
from src_v4 import config_v4 as cfg  # noqa: E402


Case = core.Case
CASE_ORDER = [
    "baseline",
    "treatment_full",
    "treatment_fixed_turnover",
    "treatment_fixed_dispatch",
    "null_control",
    "reverse_fixed_turnover",
    "reverse_fixed_dispatch",
]
CASE_LABELS = {
    "baseline": "S1 heterogeneous storage, fully coupled",
    "treatment_full": "S5 removal of offshore cost premia, fully coupled",
    "treatment_fixed_turnover": "S5 removal of offshore cost premia, S1 turnover fixed",
    "treatment_fixed_dispatch": "S5 removal of offshore cost premia, S1 turnover and dispatch fixed",
    "null_control": "S1 heterogeneous storage, S1 turnover fixed",
    "reverse_fixed_turnover": "S1 heterogeneous storage, S5 turnover fixed",
    "reverse_fixed_dispatch": "S1 heterogeneous storage, S5 turnover and dispatch fixed",
}
EXPECTED_S5_ADJUSTMENTS = {
    "_offshore_pipeline_cost_factor": 1.0,
    "_offshore_storage_cost_factor": 1.0,
}
DEFAULT_PLANT_METADATA = core.DEFAULT_PLANT_METADATA
TOL = 1e-6


def _number(value: Any, default: float = math.nan) -> float:
    return core._number(value, default)


def _safe_div(numerator: float, denominator: float) -> float:
    return core._safe_div(numerator, denominator)


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return bool(int(value))
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _route_generalized_cost_per_t(
    distance_km: float,
    route_type: str,
    *,
    pipeline_factor: float,
    storage_factor: float,
) -> float:
    """Per-ton transport + storage cost net of EOR credit."""

    route_type = str(route_type).upper()
    transport = (
        distance_km
        * (
            float(cfg.CCS_PARAMS["pipeline_investment"])
            + float(cfg.CCS_PARAMS["pipeline_om"])
        )
        * pipeline_factor
    )
    if route_type == "EOR":
        return (
            transport
            + float(cfg.CCS_PARAMS["eor_storage_cost"]) * storage_factor
            - float(cfg.CCS_PARAMS["eor_revenue"])
        )
    return transport + float(cfg.CCS_PARAMS["dsa_cost"]) * storage_factor


def load_storage_features(
    feature_csv: Path | None,
) -> tuple[pd.DataFrame, str]:
    """Load or derive model-feasible offshore-route features by plant."""

    if feature_csv is not None:
        path = feature_csv.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = pd.read_csv(path)
        aliases = {
            "has_offshore_route": "offshore_route_eligible",
            "offshore_eligible": "offshore_route_eligible",
            "nearest_offshore_km": "nearest_offshore_distance_km",
            "nearest_storage_km": "nearest_storage_distance_km",
        }
        frame = frame.rename(
            columns={key: value for key, value in aliases.items() if key in frame}
        )
        required = {
            "plant_id",
            "offshore_route_eligible",
            "nearest_offshore_distance_km",
            "nearest_storage_distance_km",
        }
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(
                f"Storage feature CSV lacks required columns {missing}: {path}"
            )
        if "nearest_onshore_distance_km" not in frame:
            frame["nearest_onshore_distance_km"] = math.nan
        if "offshore_route_count" not in frame:
            frame["offshore_route_count"] = frame[
                "offshore_route_eligible"
            ].map(_bool_value).astype(int)
        if "nearest_storage_is_offshore" not in frame:
            frame["nearest_storage_is_offshore"] = False
        for column in [
            "min_offshore_parity_generalized_cost_CNY_per_t",
            "min_onshore_generalized_cost_CNY_per_t",
            "offshore_competitiveness_CNY_per_t",
            "min_offshore_premium_removed_CNY_per_t",
        ]:
            if column not in frame:
                frame[column] = math.nan
        source = f"provided_csv:{path}"
    else:
        from src_v4.data_loader_v4 import (  # noqa: E402
            build_plant_storage_assignment,
            load_plants,
            load_storage,
        )

        plants = load_plants()
        storage = load_storage()
        assignments = build_plant_storage_assignment(
            plants,
            storage,
            max_km=float(cfg.TRANSPORT_MAX_KM),
            k_nearest=int(cfg.NEAREST_SINKS_PER_PLANT),
        )
        storage_index = storage.set_index("storage_idx")
        rows: list[dict[str, Any]] = []
        for plant_id in plants["plant_id"].astype(int):
            routes = assignments.get(int(plant_id), [])
            offshore = [
                (int(storage_idx), float(distance), str(route_type).upper())
                for storage_idx, distance, route_type in routes
                if _bool_value(storage_index.loc[int(storage_idx), "is_offshore"])
            ]
            onshore = [
                (int(storage_idx), float(distance), str(route_type).upper())
                for storage_idx, distance, route_type in routes
                if not _bool_value(
                    storage_index.loc[int(storage_idx), "is_offshore"]
                )
            ]
            nearest = min(routes, key=lambda item: float(item[1])) if routes else None
            offshore_parity_costs = [
                _route_generalized_cost_per_t(
                    distance,
                    route_type,
                    pipeline_factor=1.0,
                    storage_factor=1.0,
                )
                for _, distance, route_type in offshore
            ]
            offshore_baseline_costs = [
                _route_generalized_cost_per_t(
                    distance,
                    route_type,
                    pipeline_factor=float(
                        cfg.OFFSHORE_PARAMS["pipeline_cost_factor"]
                    ),
                    storage_factor=float(
                        cfg.OFFSHORE_PARAMS["storage_cost_factor"]
                    ),
                )
                for _, distance, route_type in offshore
            ]
            onshore_costs = [
                _route_generalized_cost_per_t(
                    distance,
                    route_type,
                    pipeline_factor=1.0,
                    storage_factor=1.0,
                )
                for _, distance, route_type in onshore
            ]
            min_offshore_cost = (
                min(offshore_parity_costs)
                if offshore_parity_costs
                else math.nan
            )
            min_onshore_cost = min(onshore_costs) if onshore_costs else math.nan
            rows.append(
                {
                    "plant_id": int(plant_id),
                    "offshore_route_eligible": bool(offshore),
                    "offshore_route_count": len(offshore),
                    "nearest_offshore_distance_km": (
                        min(item[1] for item in offshore) if offshore else math.nan
                    ),
                    "nearest_onshore_distance_km": (
                        min(item[1] for item in onshore) if onshore else math.nan
                    ),
                    "nearest_storage_distance_km": (
                        float(nearest[1]) if nearest else math.nan
                    ),
                    "nearest_storage_is_offshore": (
                        _bool_value(storage_index.loc[int(nearest[0]), "is_offshore"])
                        if nearest
                        else False
                    ),
                    "min_offshore_parity_generalized_cost_CNY_per_t": min_offshore_cost,
                    "min_onshore_generalized_cost_CNY_per_t": min_onshore_cost,
                    "offshore_competitiveness_CNY_per_t": (
                        min_onshore_cost - min_offshore_cost
                        if math.isfinite(min_onshore_cost)
                        and math.isfinite(min_offshore_cost)
                        else math.nan
                    ),
                    "min_offshore_premium_removed_CNY_per_t": (
                        min(
                            baseline - parity
                            for baseline, parity in zip(
                                offshore_baseline_costs,
                                offshore_parity_costs,
                            )
                        )
                        if offshore_parity_costs
                        else math.nan
                    ),
                }
            )
        frame = pd.DataFrame(rows)
        source = (
            "derived_model_whitelist:"
            f"plants={cfg.PLANT_SOURCE_XLSX};storage={cfg.STORAGE_CSV};"
            f"land_mask={cfg.CHINA_LAND_GEOJSON};max_km={cfg.TRANSPORT_MAX_KM};"
            f"routes_per_plant={cfg.NEAREST_SINKS_PER_PLANT}"
        )

    frame = frame.copy()
    frame["plant_id"] = pd.to_numeric(frame["plant_id"], errors="raise").astype(int)
    if frame["plant_id"].duplicated().any():
        duplicates = frame.loc[frame["plant_id"].duplicated(), "plant_id"].tolist()
        raise ValueError(f"Duplicate plant ids in storage features: {duplicates[:10]}")
    frame["offshore_route_eligible"] = frame["offshore_route_eligible"].map(
        _bool_value
    )
    frame["nearest_storage_is_offshore"] = frame[
        "nearest_storage_is_offshore"
    ].map(_bool_value)
    for column in [
        "offshore_route_count",
        "nearest_offshore_distance_km",
        "nearest_onshore_distance_km",
        "nearest_storage_distance_km",
        "min_offshore_parity_generalized_cost_CNY_per_t",
        "min_onshore_generalized_cost_CNY_per_t",
        "offshore_competitiveness_CNY_per_t",
        "min_offshore_premium_removed_CNY_per_t",
    ]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    columns = [
        "plant_id",
        "offshore_route_eligible",
        "offshore_route_count",
        "nearest_offshore_distance_km",
        "nearest_onshore_distance_km",
        "nearest_storage_distance_km",
        "nearest_storage_is_offshore",
        "min_offshore_parity_generalized_cost_CNY_per_t",
        "min_onshore_generalized_cost_CNY_per_t",
        "offshore_competitiveness_CNY_per_t",
        "min_offshore_premium_removed_CNY_per_t",
    ]
    return frame[columns].sort_values("plant_id").reset_index(drop=True), source


def capture_identity_overlap(left: Case, right: Case) -> float:
    numerator = 0.0
    denominator = 0.0
    for plant_id in left.plants:
        left_capture = core._series(left, plant_id, "captured_commercial")
        right_capture = core._series(right, plant_id, "captured_commercial")
        for year in left.years:
            weight = left.weights[year]
            numerator += weight * min(left_capture[year], right_capture[year])
            denominator += weight * max(left_capture[year], right_capture[year])
    return _safe_div(numerator, denominator)


def route_identity_overlap(
    left: Case,
    right: Case,
    *,
    offshore_only: bool = False,
) -> float:
    keys = ["plant_id", "storage_idx", "type", "period"]

    def values(case: Case) -> pd.Series:
        routes = core.route_frame(case)
        if offshore_only and not routes.empty:
            routes = routes.loc[routes["is_offshore"]]
        if routes.empty:
            return pd.Series(dtype=float)
        return routes.groupby(keys)["cumulative_flow_kt"].sum()

    left_values = values(left)
    right_values = values(right)
    union = left_values.index.union(right_values.index)
    left_values = left_values.reindex(union, fill_value=0.0)
    right_values = right_values.reindex(union, fill_value=0.0)
    paired = pd.concat([left_values, right_values], axis=1)
    return _safe_div(float(paired.min(axis=1).sum()), float(paired.max(axis=1).sum()))


def _append_comparison_metric(
    summary: pd.DataFrame,
    metric: str,
    value: float,
    unit: str,
    note: str,
    lower: float = math.nan,
    upper: float = math.nan,
) -> pd.DataFrame:
    row = {column: math.nan for column in summary.columns}
    row.update(
        {
            "metric": metric,
            "metric_kind": "comparison",
            "unit": unit,
            "comparison_value": value,
            "comparison_lower_bound": lower,
            "comparison_upper_bound": upper,
            "note": note,
        }
    )
    return pd.concat([summary, pd.DataFrame([row])], ignore_index=True)


def build_summary_metrics(
    cases: dict[str, Case],
    scalar_metrics: dict[str, dict[str, tuple[float, str, str]]],
    plant_frames: dict[str, pd.DataFrame],
    route_frames: dict[str, pd.DataFrame],
    capacity_map: dict[int, float],
) -> pd.DataFrame:
    summary = core.build_summary_metrics(
        cases,
        scalar_metrics,
        plant_frames,
        route_frames,
        capacity_map,
    ).copy()
    summary["metric"] = (
        summary["metric"].astype(str).str.replace("s3_plan", "s5_plan", regex=False)
    )
    summary["note"] = (
        summary["note"]
        .fillna("")
        .astype(str)
        .str.replace("S3", "S5", regex=False)
        .str.replace("equalized", "offshore-premium-removal", regex=False)
    )

    pairs = {
        "baseline_vs_treatment_full": (
            cases["baseline"],
            cases["treatment_full"],
        ),
        "treatment_full_vs_treatment_fixed_turnover": (
            cases["treatment_full"],
            cases["treatment_fixed_turnover"],
        ),
    }
    if "treatment_fixed_dispatch" in cases:
        pairs["treatment_full_vs_treatment_fixed_dispatch"] = (
            cases["treatment_full"],
            cases["treatment_fixed_dispatch"],
        )
    if "reverse_fixed_turnover" in cases:
        pairs["treatment_full_vs_reverse_fixed_turnover"] = (
            cases["treatment_full"],
            cases["reverse_fixed_turnover"],
        )
    if "reverse_fixed_dispatch" in cases:
        pairs["treatment_full_vs_reverse_fixed_dispatch"] = (
            cases["treatment_full"],
            cases["reverse_fixed_dispatch"],
        )

    for label, (left, right) in pairs.items():
        summary = _append_comparison_metric(
            summary,
            f"capture_plant_period_identity_overlap__{label}",
            capture_identity_overlap(left, right),
            "fraction",
            "Weighted Jaccard on exact (plant, period) commercial capture decisions.",
        )
        summary = _append_comparison_metric(
            summary,
            f"route_plant_sink_period_identity_overlap__{label}",
            route_identity_overlap(left, right),
            "fraction",
            "Weighted Jaccard on exact (plant, storage node, route type, period) commercial flows.",
        )
        summary = _append_comparison_metric(
            summary,
            f"offshore_route_identity_overlap__{label}",
            route_identity_overlap(left, right, offshore_only=True),
            "fraction",
            "Exact route-identity overlap restricted to offshore commercial flows.",
        )

    def cross_environment_effect(
        left: Case,
        right: Case,
    ) -> dict[str, float | str]:
        left_ub = core._solver_value(left, "objective_value") / 1e6
        left_lb = core._solver_value(left, "objective_bound") / 1e6
        right_ub = core._solver_value(right, "objective_value") / 1e6
        right_lb = core._solver_value(right, "objective_bound") / 1e6
        best_right_ub = right_ub
        source = right.key
        control = cases.get("null_control")
        if control is not None and core._same_optimization_environment(
            control, right
        ):
            control_ub = core._solver_value(control, "objective_value") / 1e6
            if math.isfinite(control_ub) and control_ub < best_right_ub:
                best_right_ub = control_ub
                source = control.key
        return {
            "designated": left_ub - right_ub,
            "best_known": left_ub - best_right_ub,
            "lower": left_lb - best_right_ub,
            "upper": left_ub - right_lb,
            "right_ub_source": source,
        }

    total_effect = cross_environment_effect(
        cases["treatment_full"], cases["baseline"]
    )
    summary = _append_comparison_metric(
        summary,
        "total_s5_cost_effect_designated_run",
        float(total_effect["designated"]),
        "billion_CNY",
        "Incumbent difference between the designated fully coupled S5 and S1 runs.",
    )
    summary = _append_comparison_metric(
        summary,
        "total_s5_cost_effect_bound_aware",
        float(total_effect["best_known"]),
        "billion_CNY",
        f"Best-known incumbent difference; lower bound uses joint-S1 feasible upper bound from {total_effect['right_ub_source']} and upper bound uses unrestricted S1 lower bound.",
        float(total_effect["lower"]),
        float(total_effect["upper"]),
    )
    fixed_effect = cross_environment_effect(
        cases["treatment_fixed_turnover"], cases["baseline"]
    )
    summary = _append_comparison_metric(
        summary,
        "fixed_turnover_s5_cost_effect_designated_run",
        float(fixed_effect["designated"]),
        "billion_CNY",
        "Incumbent difference for S5 with S1 y/r fixed versus the designated joint-S1 run.",
    )
    summary = _append_comparison_metric(
        summary,
        "fixed_turnover_s5_cost_effect_bound_aware",
        float(fixed_effect["best_known"]),
        "billion_CNY",
        f"Bound-aware S5 response without turnover adaptation; joint-S1 feasible upper bound source={fixed_effect['right_ub_source']}.",
        float(fixed_effect["lower"]),
        float(fixed_effect["upper"]),
    )
    point, regret_lower, regret_upper = core._regret_interval(
        cases["treatment_fixed_turnover"], cases["treatment_full"]
    )
    summary = _append_comparison_metric(
        summary,
        "turnover_feedback_cost_effect_bound_aware",
        -point,
        "billion_CNY",
        "Full S5 minus fixed-turnover S5; interval is the sign-reversed nested lock-in-regret interval.",
        -regret_upper,
        -regret_lower,
    )
    if "treatment_fixed_dispatch" in cases:
        dispatch_effect = cross_environment_effect(
            cases["treatment_fixed_dispatch"], cases["baseline"]
        )
        summary = _append_comparison_metric(
            summary,
            "fixed_dispatch_s5_cost_effect_bound_aware",
            float(dispatch_effect["best_known"]),
            "billion_CNY",
            f"Bound-aware S5 response with S1 y/r/u fixed; joint-S1 feasible upper bound source={dispatch_effect['right_ub_source']}.",
            float(dispatch_effect["lower"]),
            float(dispatch_effect["upper"]),
        )
        point, regret_lower, regret_upper = core._regret_interval(
            cases["treatment_fixed_dispatch"],
            cases["treatment_fixed_turnover"],
        )
        summary = _append_comparison_metric(
            summary,
            "dispatch_feedback_cost_effect_bound_aware",
            -point,
            "billion_CNY",
            "Fixed-turnover S5 minus fixed-dispatch S5; interval is the sign-reversed nested dispatch-regret interval.",
            -regret_upper,
            -regret_lower,
        )
    return summary


RAW_COST_COMPONENTS = [
    "ccs_capex",
    "ccs_opex",
    "same_site_renewal_capex",
    "early_retirement",
    "af_capex",
    "af_opex",
    "fuel",
    "transport",
    "dsa_storage",
    "eor_storage",
    "eor_revenue_credit",
    "milestone_slack_penalty",
]
COST_AGGREGATES = {
    "capture_system_subtotal": ["ccs_capex", "ccs_opex"],
    "turnover_subtotal": ["same_site_renewal_capex", "early_retirement"],
    "alternative_fuel_subtotal": ["af_capex", "af_opex", "fuel"],
    "transport_storage_net": [
        "transport",
        "dsa_storage",
        "eor_storage",
        "eor_revenue_credit",
    ],
}


def build_cost_component_mechanism(cases: dict[str, Case]) -> pd.DataFrame:
    component_values: dict[str, dict[str, float]] = {}
    for key, case in cases.items():
        raw = {
            component: core._cost_component(case, component) / 1e6
            for component in RAW_COST_COMPONENTS
        }
        values = dict(raw)
        values.update(
            {
                aggregate: sum(raw[item] for item in components)
                for aggregate, components in COST_AGGREGATES.items()
            }
        )
        values["objective_incumbent"] = (
            core._solver_value(case, "objective_value") / 1e6
        )
        component_values[key] = values

    rows: list[dict[str, Any]] = []
    components = RAW_COST_COMPONENTS + list(COST_AGGREGATES) + [
        "objective_incumbent"
    ]
    for component in components:
        values = {
            key: by_component[component]
            for key, by_component in component_values.items()
        }
        base = values["baseline"]
        full = values["treatment_full"]
        fixed = values["treatment_fixed_turnover"]
        dispatch = values.get("treatment_fixed_dispatch", math.nan)
        reverse_turnover = values.get("reverse_fixed_turnover", math.nan)
        reverse_dispatch = values.get("reverse_fixed_dispatch", math.nan)
        rows.append(
            {
                "component": component,
                "component_kind": (
                    "aggregate"
                    if component in COST_AGGREGATES or component == "objective_incumbent"
                    else "reported_component"
                ),
                "unit": "billion_CNY_discounted",
                "baseline_value": base,
                "treatment_full_value": full,
                "treatment_fixed_turnover_value": fixed,
                "treatment_fixed_dispatch_value": dispatch,
                "null_control_value": values.get("null_control", math.nan),
                "reverse_fixed_turnover_value": reverse_turnover,
                "reverse_fixed_dispatch_value": reverse_dispatch,
                "total_effect_full_minus_baseline": full - base,
                "direct_effect_fixed_turnover_minus_baseline": fixed - base,
                "turnover_feedback_full_minus_fixed_turnover": full - fixed,
                "pure_direct_effect_fixed_dispatch_minus_baseline": (
                    dispatch - base if math.isfinite(dispatch) else math.nan
                ),
                "dispatch_feedback_fixed_turnover_minus_fixed_dispatch": (
                    fixed - dispatch if math.isfinite(dispatch) else math.nan
                ),
                "reverse_turnover_delta_vs_joint_s1": (
                    reverse_turnover - base
                    if math.isfinite(reverse_turnover)
                    else math.nan
                ),
                "reverse_dispatch_increment": (
                    reverse_dispatch - reverse_turnover
                    if math.isfinite(reverse_dispatch)
                    and math.isfinite(reverse_turnover)
                    else math.nan
                ),
                "reverse_total_delta_vs_joint_s1": (
                    reverse_dispatch - base
                    if math.isfinite(reverse_dispatch)
                    else math.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def _discounted_period_cost(case: Case, year: int, component: str) -> float:
    period = core._json_lookup(case.data.get("cost_breakdown", {}), year, {})
    components = (
        period.get("components_discounted_kCNY", {})
        if isinstance(period, dict)
        else {}
    )
    return _number(components.get(component), 0.0) / 1e6


def _offshore_factors(case: Case) -> tuple[float, float]:
    adjustments = case.data.get("scenario_adjustments", {}) or {}
    pipeline = _number(
        adjustments.get("_offshore_pipeline_cost_factor"),
        float(cfg.OFFSHORE_PARAMS["pipeline_cost_factor"]),
    )
    storage = _number(
        adjustments.get("_offshore_storage_cost_factor"),
        float(cfg.OFFSHORE_PARAMS["storage_cost_factor"]),
    )
    return pipeline, storage


def _eor_route_net_unit_cost(
    case: Case,
    distance_km: float,
    is_offshore: bool,
) -> float:
    """Per-ton generalized EOR route cost net of the unchanged EOR credit."""

    pipeline_factor, storage_factor = _offshore_factors(case)
    if not is_offshore:
        pipeline_factor = 1.0
        storage_factor = 1.0
    return _route_generalized_cost_per_t(
        distance_km,
        "EOR",
        pipeline_factor=pipeline_factor,
        storage_factor=storage_factor,
    )


def build_storage_route_mechanism(cases: dict[str, Case]) -> pd.DataFrame:
    """Split DSA/EOR and onshore/offshore flows and their route economics."""

    annual_rows: list[dict[str, Any]] = []
    for key in CASE_ORDER:
        if key not in cases:
            continue
        case = cases[key]
        routes = core.route_frame(case)
        pipeline_factor, storage_factor = _offshore_factors(case)
        for year in case.years:
            annual = routes.loc[routes["period"].eq(year)].copy()
            if annual.empty:
                annual = pd.DataFrame(
                    columns=[
                        "flow_kt_per_year",
                        "type",
                        "is_offshore",
                        "distance_km",
                    ]
                )
            flow = pd.to_numeric(
                annual["flow_kt_per_year"], errors="coerce"
            ).fillna(0.0)
            is_offshore = annual["is_offshore"].map(_bool_value)
            is_dsa = annual["type"].astype(str).str.upper().eq("DSA")
            is_eor = annual["type"].astype(str).str.upper().eq("EOR")
            offshore_dsa = float(flow.loc[is_offshore & is_dsa].sum())
            offshore_eor = float(flow.loc[is_offshore & is_eor].sum())
            onshore_dsa = float(flow.loc[~is_offshore & is_dsa].sum())
            onshore_eor = float(flow.loc[~is_offshore & is_eor].sum())
            offshore_total = offshore_dsa + offshore_eor
            negative_eor_flow = 0.0
            removed_premium_flow = 0.0
            for row in annual.loc[is_offshore].itertuples(index=False):
                distance = _number(row.distance_km, 0.0)
                route_type = str(row.type).upper()
                baseline_cost = _route_generalized_cost_per_t(
                    distance,
                    route_type,
                    pipeline_factor=float(
                        cfg.OFFSHORE_PARAMS["pipeline_cost_factor"]
                    ),
                    storage_factor=float(
                        cfg.OFFSHORE_PARAMS["storage_cost_factor"]
                    ),
                )
                parity_cost = _route_generalized_cost_per_t(
                    distance,
                    route_type,
                    pipeline_factor=1.0,
                    storage_factor=1.0,
                )
                removed_premium_flow += _number(
                    row.flow_kt_per_year, 0.0
                ) * (baseline_cost - parity_cost)
            for row in annual.loc[is_offshore & is_eor].itertuples(index=False):
                if (
                    _eor_route_net_unit_cost(
                        case,
                        _number(row.distance_km, 0.0),
                        True,
                    )
                    < -TOL
                ):
                    negative_eor_flow += _number(row.flow_kt_per_year, 0.0)

            transport = _discounted_period_cost(case, year, "transport")
            dsa_storage = _discounted_period_cost(case, year, "dsa_storage")
            eor_storage = _discounted_period_cost(case, year, "eor_storage")
            eor_credit = _discounted_period_cost(
                case, year, "eor_revenue_credit"
            )
            gross_network = transport + dsa_storage + eor_storage
            annual_rows.append(
                {
                    "case": key,
                    "case_label": CASE_LABELS[key],
                    "period": year,
                    "flow_basis": "annual_kt_per_year",
                    "period_weight_years": case.weights[year],
                    "total_flow_kt": float(flow.sum()),
                    "onshore_dsa_flow_kt": onshore_dsa,
                    "onshore_eor_flow_kt": onshore_eor,
                    "offshore_dsa_flow_kt": offshore_dsa,
                    "offshore_eor_flow_kt": offshore_eor,
                    "offshore_total_flow_kt": offshore_total,
                    "offshore_eor_share": _safe_div(
                        offshore_eor, offshore_total
                    ),
                    "negative_net_offshore_eor_flow_kt": negative_eor_flow,
                    "negative_net_eor_share_of_offshore_flow": _safe_div(
                        negative_eor_flow, offshore_total
                    ),
                    "offshore_removed_premium_flow_weighted_numerator": removed_premium_flow,
                    "offshore_flow_weighted_removed_premium_CNY_per_t": _safe_div(
                        removed_premium_flow, offshore_total
                    ),
                    "gross_transport_storage_billion_CNY": gross_network,
                    "eor_revenue_credit_billion_CNY": eor_credit,
                    "net_route_cost_billion_CNY": gross_network + eor_credit,
                    "offshore_pipeline_cost_factor": pipeline_factor,
                    "offshore_storage_cost_factor": storage_factor,
                }
            )

    annual_frame = pd.DataFrame(annual_rows)
    cumulative_rows: list[dict[str, Any]] = []
    flow_columns = [
        "total_flow_kt",
        "onshore_dsa_flow_kt",
        "onshore_eor_flow_kt",
        "offshore_dsa_flow_kt",
        "offshore_eor_flow_kt",
        "offshore_total_flow_kt",
        "negative_net_offshore_eor_flow_kt",
        "offshore_removed_premium_flow_weighted_numerator",
    ]
    cost_columns = [
        "gross_transport_storage_billion_CNY",
        "eor_revenue_credit_billion_CNY",
        "net_route_cost_billion_CNY",
    ]
    for key in CASE_ORDER:
        if key not in cases:
            continue
        group = annual_frame.loc[annual_frame["case"].eq(key)].copy()
        weights = group["period_weight_years"]
        totals = {
            column: float((group[column] * weights).sum())
            for column in flow_columns
        }
        costs = {column: float(group[column].sum()) for column in cost_columns}
        cumulative_rows.append(
            {
                "case": key,
                "case_label": CASE_LABELS[key],
                "period": "cumulative",
                "flow_basis": "cumulative_kt_year",
                "period_weight_years": float(weights.sum()),
                **totals,
                "offshore_eor_share": _safe_div(
                    totals["offshore_eor_flow_kt"],
                    totals["offshore_total_flow_kt"],
                ),
                "negative_net_eor_share_of_offshore_flow": _safe_div(
                    totals["negative_net_offshore_eor_flow_kt"],
                    totals["offshore_total_flow_kt"],
                ),
                "offshore_flow_weighted_removed_premium_CNY_per_t": _safe_div(
                    totals["offshore_removed_premium_flow_weighted_numerator"],
                    totals["offshore_total_flow_kt"],
                ),
                **costs,
                "offshore_pipeline_cost_factor": _offshore_factors(
                    cases[key]
                )[0],
                "offshore_storage_cost_factor": _offshore_factors(
                    cases[key]
                )[1],
            }
        )
    frame = pd.concat(
        [annual_frame, pd.DataFrame(cumulative_rows)], ignore_index=True
    )

    baseline = frame.loc[frame["case"].eq("baseline")].set_index(
        ["period", "flow_basis"]
    )
    frame["incremental_offshore_flow_vs_baseline_kt"] = math.nan
    frame["incremental_offshore_eor_flow_vs_baseline_kt"] = math.nan
    frame["incremental_offshore_flow_attributable_to_eor_share"] = math.nan
    for idx, row in frame.iterrows():
        lookup = (row["period"], row["flow_basis"])
        if lookup not in baseline.index:
            continue
        base = baseline.loc[lookup]
        delta_total = row["offshore_total_flow_kt"] - base[
            "offshore_total_flow_kt"
        ]
        delta_eor = row["offshore_eor_flow_kt"] - base[
            "offshore_eor_flow_kt"
        ]
        frame.at[idx, "incremental_offshore_flow_vs_baseline_kt"] = delta_total
        frame.at[idx, "incremental_offshore_eor_flow_vs_baseline_kt"] = delta_eor
        frame.at[
            idx, "incremental_offshore_flow_attributable_to_eor_share"
        ] = _safe_div(delta_eor, delta_total)
    return frame


def _group_route_statistics(
    case: Case,
    plant_ids: set[int],
) -> tuple[float, float]:
    routes = core.route_frame(case)
    if routes.empty or not plant_ids:
        return math.nan, math.nan
    routes = routes.loc[routes["plant_id"].isin(plant_ids)]
    total = float(routes["cumulative_flow_kt"].sum())
    offshore = float(
        routes.loc[routes["is_offshore"], "cumulative_flow_kt"].sum()
    )
    distance = _safe_div(
        float(routes["flow_distance_kt_km"].sum()),
        total,
    )
    return _safe_div(offshore, total), distance


def build_survivor_sorting(
    cases: dict[str, Case],
    metadata: pd.DataFrame,
    storage_features: pd.DataFrame,
    plant_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    baseline = cases["baseline"]
    treatment = cases["treatment_full"]
    base_set = core._retained_set(baseline)
    treatment_set = core._retained_set(treatment)
    groups = {
        "retained_in_both": base_set & treatment_set,
        "gained_in_s5": treatment_set - base_set,
        "lost_in_s5": base_set - treatment_set,
        "s1_terminal_all": base_set,
        "s5_terminal_all": treatment_set,
    }
    features = storage_features.merge(
        metadata[[column for column in ["plant_id", "capacity_t_day", "province", "city"] if column in metadata]],
        on="plant_id",
        how="left",
    )
    base_plants = plant_frames["baseline"].set_index("plant_id")
    full_plants = plant_frames["treatment_full"].set_index("plant_id")
    rows: list[dict[str, Any]] = []
    for label, plant_ids in groups.items():
        plant_id_list = sorted(plant_ids)
        group = features.loc[features["plant_id"].isin(plant_ids)].copy()
        eligible = group.loc[group["offshore_route_eligible"]]
        base_offshore_share, base_route_distance = _group_route_statistics(
            baseline, plant_ids
        )
        full_offshore_share, full_route_distance = _group_route_statistics(
            treatment, plant_ids
        )
        rows.append(
            {
                "group": label,
                "plants": len(plant_ids),
                "capacity_mean_t_day": group["capacity_t_day"].mean(),
                "offshore_route_eligible_plants": int(
                    group["offshore_route_eligible"].sum()
                ),
                "offshore_route_eligible_share": group[
                    "offshore_route_eligible"
                ].mean(),
                "nearest_offshore_distance_mean_km": eligible[
                    "nearest_offshore_distance_km"
                ].mean(),
                "nearest_offshore_distance_median_km": eligible[
                    "nearest_offshore_distance_km"
                ].median(),
                "nearest_storage_distance_mean_km": group[
                    "nearest_storage_distance_km"
                ].mean(),
                "nearest_storage_distance_median_km": group[
                    "nearest_storage_distance_km"
                ].median(),
                "nearest_storage_offshore_share": group[
                    "nearest_storage_is_offshore"
                ].mean(),
                "offshore_parity_generalized_cost_mean_CNY_per_t": eligible[
                    "min_offshore_parity_generalized_cost_CNY_per_t"
                ].mean(),
                "offshore_competitiveness_mean_CNY_per_t": eligible[
                    "offshore_competitiveness_CNY_per_t"
                ].mean(),
                "offshore_premium_removed_mean_CNY_per_t": eligible[
                    "min_offshore_premium_removed_CNY_per_t"
                ].mean(),
                "baseline_cumulative_capture_gt": (
                    base_plants.reindex(plant_id_list)["cumulative_capture_kt"].sum()
                    / 1e6
                ),
                "s5_cumulative_capture_gt": (
                    full_plants.reindex(plant_id_list)["cumulative_capture_kt"].sum()
                    / 1e6
                ),
                "baseline_optimized_offshore_flow_share": base_offshore_share,
                "s5_optimized_offshore_flow_share": full_offshore_share,
                "baseline_flow_weighted_distance_km": base_route_distance,
                "s5_flow_weighted_distance_km": full_route_distance,
                "top_provinces": "|".join(
                    group.groupby("province").size().nlargest(5).index.astype(str)
                )
                if "province" in group
                else "",
            }
        )
    return pd.DataFrame(rows)


def _audit_row(
    rows: list[dict[str, Any]],
    scope: str,
    check_id: str,
    status: str,
    observed: Any,
    expected: Any,
    detail: str = "",
) -> None:
    core._audit_row(rows, scope, check_id, status, observed, expected, detail)


def audit_cross_case(
    cases: dict[str, Case],
    metadata: pd.DataFrame,
    storage_features: pd.DataFrame,
    annual_comparison: pd.DataFrame,
    cost_mechanism: pd.DataFrame,
    survivor_sorting: pd.DataFrame,
    storage_route_mechanism: pd.DataFrame,
    summary: pd.DataFrame,
    rows: list[dict[str, Any]],
) -> None:
    baseline = cases["baseline"]
    treatment = cases["treatment_full"]
    expected_ids = set(baseline.plants)
    for key, case in cases.items():
        _audit_row(
            rows,
            "cross_case",
            f"plant_set__{key}",
            "PASS" if set(case.plants) == expected_ids else "FAIL",
            len(case.plants),
            len(expected_ids),
        )
        period_match = case.years == baseline.years and case.weights == baseline.weights
        _audit_row(
            rows,
            "cross_case",
            f"periods_and_weights__{key}",
            "PASS" if period_match else "FAIL",
            f"years={case.years}; weights={case.weights}",
            f"years={baseline.years}; weights={baseline.weights}",
        )
        boundary_match = (
            case.data.get("demand_scenario")
            == baseline.data.get("demand_scenario")
            and case.data.get("carbon_budget_case")
            == baseline.data.get("carbon_budget_case")
            and case.data.get("cost_boundary")
            == baseline.data.get("cost_boundary")
        )
        _audit_row(
            rows,
            "cross_case",
            f"planning_boundary__{key}",
            "PASS" if boundary_match else "FAIL",
            (
                f"demand={case.data.get('demand_scenario')}; "
                f"budget={case.data.get('carbon_budget_case')}; "
                f"cost={case.data.get('cost_boundary')}"
            ),
            (
                f"demand={baseline.data.get('demand_scenario')}; "
                f"budget={baseline.data.get('carbon_budget_case')}; "
                f"cost={baseline.data.get('cost_boundary')}"
            ),
        )

    adjustments = treatment.data.get("scenario_adjustments", {}) or {}
    values_ok = all(
        abs(_number(adjustments.get(key)) - expected) <= TOL
        for key, expected in EXPECTED_S5_ADJUSTMENTS.items()
    )
    extra_adjustments = sorted(set(adjustments) - set(EXPECTED_S5_ADJUSTMENTS))
    s5_ok = (
        treatment.data.get("scenario") == "S5_offshore_parity"
        and values_ok
        and not extra_adjustments
    )
    _audit_row(
        rows,
        "scenario",
        "s5_offshore_parity_is_pure_storage_cost_treatment",
        "PASS" if s5_ok else "FAIL",
        f"scenario={treatment.data.get('scenario')}; adjustments={adjustments}",
        f"scenario=S5_offshore_parity; adjustments={EXPECTED_S5_ADJUSTMENTS}",
    )
    treatment_gap = core._solver_value(treatment, "mip_gap")
    if treatment_gap <= 0.001 + 1e-9:
        treatment_gap_status = "PASS"
    elif math.isfinite(treatment_gap) and treatment_gap <= 0.02 + 1e-9:
        treatment_gap_status = "WARN"
    else:
        treatment_gap_status = "FAIL"
    _audit_row(
        rows,
        "solver_quality",
        "full_s5_confirmatory_gap_target",
        treatment_gap_status,
        treatment_gap,
        "<=0.001 (0.1%)",
        "The 0.1% target is preferred; a time-limit incumbent up to 2% is retained with an explicit warning because inference uses solver-bound intervals.",
    )

    for key in ["treatment_fixed_turnover", "treatment_fixed_dispatch"]:
        if key not in cases:
            continue
        same = core._same_optimization_environment(cases[key], treatment)
        _audit_row(
            rows,
            "cross_case",
            f"same_s5_environment__{key}",
            "PASS" if same else "FAIL",
            f"scenario={cases[key].data.get('scenario')}; adjustments={cases[key].data.get('scenario_adjustments')}",
            f"scenario={treatment.data.get('scenario')}; adjustments={adjustments}",
        )
        fixed_gap = core._solver_value(cases[key], "mip_gap")
        _audit_row(
            rows,
            "solver_quality",
            f"fixed_case_gap_target__{key}",
            "PASS" if fixed_gap <= 0.001 + 1e-9 else "FAIL",
            fixed_gap,
            "<=0.001 (0.1%)",
        )
    for key in ["null_control", "reverse_fixed_turnover", "reverse_fixed_dispatch"]:
        if key not in cases:
            continue
        same = core._same_optimization_environment(cases[key], baseline)
        _audit_row(
            rows,
            "cross_case",
            f"same_s1_environment__{key}",
            "PASS" if same else "FAIL",
            f"scenario={cases[key].data.get('scenario')}; adjustments={cases[key].data.get('scenario_adjustments')}",
            f"scenario={baseline.data.get('scenario')}; adjustments={baseline.data.get('scenario_adjustments')}",
        )
        fixed_gap = core._solver_value(cases[key], "mip_gap")
        _audit_row(
            rows,
            "solver_quality",
            f"fixed_case_gap_target__{key}",
            "PASS" if fixed_gap <= 0.001 + 1e-9 else "FAIL",
            fixed_gap,
            "<=0.001 (0.1%)",
        )

    def fixed_integrity(
        case_key: str,
        source_key: str,
        variables: list[str],
    ) -> None:
        case = cases[case_key]
        source = cases[source_key]
        mismatch = {
            variable: sum(
                abs(
                    core._series(case, plant_id, variable)[year]
                    - core._series(source, plant_id, variable)[year]
                )
                > (core.FIXED_U_TOLERANCE if variable == "u" else TOL)
                for plant_id in expected_ids
                for year in baseline.years
            )
            for variable in variables
        }
        _audit_row(
            rows,
            "fixed_path",
            f"fixed_values_match_{source_key}__{case_key}",
            "PASS" if sum(mismatch.values()) == 0 else "FAIL",
            mismatch,
            {variable: 0 for variable in variables},
        )
        block = case.data.get("capacity_path_counterfactual", {}) or {}
        fixed_declared = set(block.get("fixed_variables", []))
        bounded_declared = set(block.get("bounded_variables", []))
        exact_required = set(variables) - {"u"}
        dispatch_required = (
            "u" not in variables
            or "u" in bounded_declared
            or "u" in fixed_declared
        )
        metadata_ok = (
            bool(block.get("enabled"))
            and exact_required.issubset(fixed_declared)
            and dispatch_required
        )
        _audit_row(
            rows,
            "fixed_path",
            f"fixed_path_metadata__{case_key}",
            "PASS" if metadata_ok else "WARN",
            block,
            "y/r exactly fixed and u declared as bounded when dispatch is imposed",
            "Exact y/r equality plus the shared dispatch-band tolerance is authoritative.",
        )
        source_hash = block.get("source_sha256")
        _audit_row(
            rows,
            "fixed_path",
            f"source_hash_matches_{source_key}__{case_key}",
            "PASS" if source_hash == source.sha256 else "FAIL",
            source_hash,
            source.sha256,
        )

    fixed_integrity("treatment_fixed_turnover", "baseline", ["y", "r"])
    if "treatment_fixed_dispatch" in cases:
        fixed_integrity(
            "treatment_fixed_dispatch", "baseline", ["y", "r", "u"]
        )
    if "null_control" in cases:
        fixed_integrity("null_control", "baseline", ["y", "r"])
    if "reverse_fixed_turnover" in cases:
        fixed_integrity(
            "reverse_fixed_turnover", "treatment_full", ["y", "r"]
        )
    if "reverse_fixed_dispatch" in cases:
        fixed_integrity(
            "reverse_fixed_dispatch", "treatment_full", ["y", "r", "u"]
        )

    metadata_ids = set(metadata["plant_id"].astype(int))
    storage_ids = set(storage_features["plant_id"].astype(int))
    _audit_row(
        rows,
        "metadata",
        "plant_metadata_coverage",
        "PASS" if expected_ids.issubset(metadata_ids) else "FAIL",
        len(expected_ids & metadata_ids),
        len(expected_ids),
    )
    missing_storage = sorted(expected_ids - storage_ids)
    invalid_offshore_distance = storage_features.loc[
        storage_features["offshore_route_eligible"]
        & (
            storage_features["nearest_offshore_distance_km"].isna()
            | storage_features[
                "min_offshore_parity_generalized_cost_CNY_per_t"
            ].isna()
        )
    ]
    storage_ok = not missing_storage and invalid_offshore_distance.empty
    _audit_row(
        rows,
        "metadata",
        "storage_feature_coverage_and_eligibility",
        "PASS" if storage_ok else "FAIL",
        (
            f"missing_plants={len(missing_storage)}; "
            f"eligible_without_distance_or_cost={len(invalid_offshore_distance)}"
        ),
        "complete plant coverage; every eligible plant has offshore distance and parity generalized cost",
        f"sample_missing={missing_storage[:10]}",
    )

    base_year = baseline.years[0]
    for key, case in cases.items():
        max_u = max(
            abs(
                core._series(case, plant_id, "u")[base_year]
                - core._series(baseline, plant_id, "u")[base_year]
            )
            for plant_id in expected_ids
        )
        max_capture = max(
            abs(
                core._series(case, plant_id, "captured_commercial")[base_year]
                - core._series(baseline, plant_id, "captured_commercial")[base_year]
            )
            for plant_id in expected_ids
        )
        _audit_row(
            rows,
            "cross_case",
            f"shared_base_year_anchor__{key}",
            "PASS" if max(max_u, max_capture) <= core.RECONCILIATION_TOL_KT else "FAIL",
            f"max_u_gap={max_u}; max_capture_gap={max_capture}",
            "identical base-year utilization and commercial capture",
        )

    annual_residuals = [
        "two_level_decomposition_residual",
        "three_level_decomposition_residual",
        "reverse_decomposition_residual",
    ]
    annual_max = {
        column: float(annual_comparison[column].abs().max())
        for column in annual_residuals
        if column in annual_comparison
        and annual_comparison[column].notna().any()
    }
    annual_ok = all(value <= 1e-9 for value in annual_max.values())
    _audit_row(
        rows,
        "decomposition",
        "annual_nested_decomposition_identity",
        "PASS" if annual_ok else "FAIL",
        annual_max,
        "all available residuals <=1e-9",
    )

    total = cost_mechanism["total_effect_full_minus_baseline"]
    direct = cost_mechanism["direct_effect_fixed_turnover_minus_baseline"]
    feedback = cost_mechanism["turnover_feedback_full_minus_fixed_turnover"]
    cost_two = float((total - direct - feedback).abs().max())
    if cost_mechanism["treatment_fixed_dispatch_value"].notna().any():
        pure = cost_mechanism["pure_direct_effect_fixed_dispatch_minus_baseline"]
        dispatch = cost_mechanism[
            "dispatch_feedback_fixed_turnover_minus_fixed_dispatch"
        ]
        cost_three = float((total - pure - dispatch - feedback).abs().max())
    else:
        cost_three = math.nan
    cost_ok = cost_two <= 1e-9 and (
        not math.isfinite(cost_three) or cost_three <= 1e-9
    )
    _audit_row(
        rows,
        "decomposition",
        "cost_component_nested_decomposition_identity",
        "PASS" if cost_ok else "FAIL",
        f"two_level={cost_two}; three_level={cost_three}",
        "<=1e-9 billion CNY",
    )

    def feasible_subset(fixed_key: str, flexible_key: str) -> None:
        fixed_ub = core._solver_value(cases[fixed_key], "objective_value")
        flexible_lb = core._solver_value(cases[flexible_key], "objective_bound")
        impossible = fixed_ub + 1e-2 < flexible_lb
        _audit_row(
            rows,
            "solver_bounds",
            f"nested_feasible_set_order__{fixed_key}_vs_{flexible_key}",
            "FAIL" if impossible else "PASS",
            f"fixed_UB={fixed_ub}; flexible_LB={flexible_lb}",
            "fixed feasible-set incumbent must not beat flexible lower bound",
        )

    feasible_subset("treatment_fixed_turnover", "treatment_full")
    if "treatment_fixed_dispatch" in cases:
        feasible_subset("treatment_fixed_dispatch", "treatment_fixed_turnover")
    if "null_control" in cases:
        feasible_subset("null_control", "baseline")
    if "reverse_fixed_turnover" in cases:
        feasible_subset("reverse_fixed_turnover", "baseline")
    if "reverse_fixed_dispatch" in cases:
        feasible_subset("reverse_fixed_dispatch", "baseline")
        if "reverse_fixed_turnover" in cases:
            feasible_subset("reverse_fixed_dispatch", "reverse_fixed_turnover")

    base_terminal = int(
        survivor_sorting.set_index("group").loc["s1_terminal_all", "plants"]
    )
    full_terminal = int(
        survivor_sorting.set_index("group").loc["s5_terminal_all", "plants"]
    )
    retained = int(
        survivor_sorting.set_index("group").loc["retained_in_both", "plants"]
    )
    gained = int(
        survivor_sorting.set_index("group").loc["gained_in_s5", "plants"]
    )
    lost = int(
        survivor_sorting.set_index("group").loc["lost_in_s5", "plants"]
    )
    partition_ok = retained + lost == base_terminal and retained + gained == full_terminal
    _audit_row(
        rows,
        "sorting",
        "terminal_survivor_partition_identity",
        "PASS" if partition_ok else "FAIL",
        f"retained={retained}; gained={gained}; lost={lost}",
        f"retained+lost={base_terminal}; retained+gained={full_terminal}",
    )

    overlap_rows = summary.loc[summary["metric"].str.contains("identity_overlap")]
    overlap_values = pd.to_numeric(
        overlap_rows["comparison_value"], errors="coerce"
    ).dropna()
    overlap_ok = bool(((overlap_values >= -TOL) & (overlap_values <= 1 + TOL)).all())
    _audit_row(
        rows,
        "identity",
        "capture_and_route_identity_overlap_bounds",
        "PASS" if overlap_ok else "FAIL",
        f"min={overlap_values.min()}; max={overlap_values.max()}",
        "all identity overlaps within [0,1]",
    )

    split_gap = (
        storage_route_mechanism[
            [
                "onshore_dsa_flow_kt",
                "onshore_eor_flow_kt",
                "offshore_dsa_flow_kt",
                "offshore_eor_flow_kt",
            ]
        ].sum(axis=1)
        - storage_route_mechanism["total_flow_kt"]
    ).abs()
    _audit_row(
        rows,
        "storage_mechanism",
        "dsa_eor_onshore_offshore_flow_partition",
        "PASS" if float(split_gap.max()) <= core.RECONCILIATION_TOL_KT else "FAIL",
        float(split_gap.max()),
        f"<={core.RECONCILIATION_TOL_KT} kt on annual and cumulative rows",
    )
    cumulative_routes = storage_route_mechanism.loc[
        storage_route_mechanism["period"].eq("cumulative")
    ].set_index("case")
    cost_index = cost_mechanism.set_index("component")
    max_gross_gap = 0.0
    max_credit_gap = 0.0
    max_net_gap = 0.0
    for key in cases:
        gross_expected = sum(
            _number(cost_index.loc[component, f"{key}_value"])
            for component in ["transport", "dsa_storage", "eor_storage"]
        )
        credit_expected = _number(
            cost_index.loc["eor_revenue_credit", f"{key}_value"]
        )
        observed = cumulative_routes.loc[key]
        max_gross_gap = max(
            max_gross_gap,
            abs(
                _number(observed["gross_transport_storage_billion_CNY"])
                - gross_expected
            ),
        )
        max_credit_gap = max(
            max_credit_gap,
            abs(
                _number(observed["eor_revenue_credit_billion_CNY"])
                - credit_expected
            ),
        )
        max_net_gap = max(
            max_net_gap,
            abs(
                _number(observed["net_route_cost_billion_CNY"])
                - gross_expected
                - credit_expected
            ),
        )
    cost_route_gap = max(max_gross_gap, max_credit_gap, max_net_gap)
    _audit_row(
        rows,
        "storage_mechanism",
        "gross_credit_net_route_cost_reconciliation",
        "PASS" if cost_route_gap <= 1e-9 else "FAIL",
        (
            f"gross={max_gross_gap}; credit={max_credit_gap}; "
            f"net={max_net_gap}"
        ),
        "<=1e-9 billion CNY versus reported discounted cost components",
    )
    negative_shares = pd.to_numeric(
        storage_route_mechanism["negative_net_eor_share_of_offshore_flow"],
        errors="coerce",
    ).dropna()
    negative_share_ok = bool(
        ((negative_shares >= -TOL) & (negative_shares <= 1 + TOL)).all()
    )
    _audit_row(
        rows,
        "storage_mechanism",
        "negative_net_eor_flow_share_bounds",
        "PASS" if negative_share_ok else "FAIL",
        f"min={negative_shares.min()}; max={negative_shares.max()}",
        "all defined shares within [0,1]",
    )
    removed_premium = pd.to_numeric(
        storage_route_mechanism[
            "offshore_flow_weighted_removed_premium_CNY_per_t"
        ],
        errors="coerce",
    ).dropna()
    premium_ok = bool((removed_premium >= -TOL).all())
    _audit_row(
        rows,
        "storage_mechanism",
        "removed_offshore_premium_is_nonnegative",
        "PASS" if premium_ok else "FAIL",
        f"min={removed_premium.min()}; max={removed_premium.max()}",
        "all defined flow-weighted removed premia >=0 CNY/tCO2",
    )

    bounded = summary.loc[
        summary["comparison_lower_bound"].notna()
        & summary["comparison_upper_bound"].notna()
    ].copy()
    bound_order = bounded["comparison_lower_bound"].le(
        bounded["comparison_upper_bound"] + TOL
    )
    point_inside = bounded["comparison_value"].ge(
        bounded["comparison_lower_bound"] - TOL
    ) & bounded["comparison_value"].le(
        bounded["comparison_upper_bound"] + TOL
    )
    null_noise_exception = (
        bounded["metric"].eq("null_control_lockin_regret")
        & bounded["comparison_value"].lt(0.0)
        & bounded["comparison_lower_bound"].abs().le(TOL)
    )
    point_inside = point_inside | null_noise_exception
    bound_ok = bool(bound_order.all() and point_inside.all())
    _audit_row(
        rows,
        "solver_bounds",
        "bound_aware_effect_intervals_well_formed",
        "PASS" if bound_ok else "FAIL",
        f"metrics={len(bounded)}; ordered={int(bound_order.sum())}; point_inside={int(point_inside.sum())}",
        "all intervals ordered and all reported points inside their intervals",
    )
    if "null_control" in cases:
        regret_lower_rows = summary.loc[
            summary["metric"].eq(
                "turnover_lockin_regret__fixed_turnover_vs_full_treatment"
            )
        ]
        null_rows = summary.loc[
            summary["metric"].eq("null_control_lockin_regret")
        ]
        regret_lower = _number(
            regret_lower_rows.iloc[0]["comparison_lower_bound"]
        )
        null_upper = _number(null_rows.iloc[0]["comparison_upper_bound"])
        separated = (
            math.isfinite(regret_lower)
            and math.isfinite(null_upper)
            and regret_lower > null_upper
        )
        _audit_row(
            rows,
            "inference",
            "turnover_regret_exceeds_null_control_noise_bound",
            "PASS" if separated else "WARN",
            f"turnover_lower={regret_lower}; null_upper={null_upper}",
            "turnover regret lower bound > null-control upper bound",
        )


def _metric(
    summary: pd.DataFrame,
    name: str,
    field: str = "comparison_value",
) -> float:
    row = summary.loc[summary["metric"].eq(name)]
    return _number(row.iloc[0][field]) if not row.empty else math.nan


def _case_metric(
    summary: pd.DataFrame,
    name: str,
    field: str,
) -> float:
    return _metric(summary, name, field)


def render_report(
    cases: dict[str, Case],
    summary: pd.DataFrame,
    cost_mechanism: pd.DataFrame,
    sorting: pd.DataFrame,
    storage_route_mechanism: pd.DataFrame,
    audits: pd.DataFrame,
    storage_feature_source: str,
) -> str:
    def fmt(value: float, digits: int = 3) -> str:
        return f"{value:.{digits}f}" if math.isfinite(value) else "n/a"

    sorting_index = sorting.set_index("group")
    gained = sorting_index.loc["gained_in_s5"]
    lost = sorting_index.loc["lost_in_s5"]
    costs = cost_mechanism.set_index("component")
    cumulative_routes = storage_route_mechanism.loc[
        storage_route_mechanism["period"].eq("cumulative")
    ].set_index("case")
    baseline_routes = cumulative_routes.loc["baseline"]
    s5_routes = cumulative_routes.loc["treatment_full"]
    cost_total = _case_metric(
        summary, "objective_incumbent", "total_effect_full_minus_baseline"
    )
    cost_direct = _case_metric(
        summary,
        "objective_incumbent",
        "direct_effect_fixed_turnover_minus_baseline",
    )
    cost_feedback = _case_metric(
        summary,
        "objective_incumbent",
        "turnover_feedback_full_minus_fixed_turnover",
    )
    total_bound = _metric(summary, "total_s5_cost_effect_bound_aware")
    total_lower = _metric(
        summary,
        "total_s5_cost_effect_bound_aware",
        "comparison_lower_bound",
    )
    total_upper = _metric(
        summary,
        "total_s5_cost_effect_bound_aware",
        "comparison_upper_bound",
    )
    direct_bound = _metric(
        summary, "fixed_turnover_s5_cost_effect_bound_aware"
    )
    direct_lower = _metric(
        summary,
        "fixed_turnover_s5_cost_effect_bound_aware",
        "comparison_lower_bound",
    )
    direct_upper = _metric(
        summary,
        "fixed_turnover_s5_cost_effect_bound_aware",
        "comparison_upper_bound",
    )
    feedback_bound = _metric(
        summary, "turnover_feedback_cost_effect_bound_aware"
    )
    feedback_lower = _metric(
        summary,
        "turnover_feedback_cost_effect_bound_aware",
        "comparison_lower_bound",
    )
    feedback_upper = _metric(
        summary,
        "turnover_feedback_cost_effect_bound_aware",
        "comparison_upper_bound",
    )
    regret = _metric(
        summary, "turnover_lockin_regret__fixed_turnover_vs_full_treatment"
    )
    regret_lower = _metric(
        summary,
        "turnover_lockin_regret__fixed_turnover_vs_full_treatment",
        "comparison_lower_bound",
    )
    regret_upper = _metric(
        summary,
        "turnover_lockin_regret__fixed_turnover_vs_full_treatment",
        "comparison_upper_bound",
    )
    capture_identity = _metric(
        summary,
        "capture_plant_period_identity_overlap__baseline_vs_treatment_full",
    )
    route_identity = _metric(
        summary,
        "route_plant_sink_period_identity_overlap__baseline_vs_treatment_full",
    )
    offshore_identity = _metric(
        summary,
        "offshore_route_identity_overlap__baseline_vs_treatment_full",
    )
    baseline_offshore = _case_metric(
        summary, "offshore_flow_share", "baseline_value"
    )
    s5_offshore = _case_metric(
        summary, "offshore_flow_share", "treatment_full_value"
    )
    audit_counts = audits["status"].value_counts().to_dict()
    lines = [
        "# S5 removal of offshore transport/storage cost premia: storage-feedback counterfactual",
        "",
        "## Design",
        "",
        "The forward comparison holds the S1 y/r asset path fixed while re-optimizing "
        "all adaptive decisions after removing offshore transport and storage cost premia. Full S5 minus fixed-path "
        "S5 is the endogenous turnover-feedback component. Reverse cross-fits impose the "
        "joint S5 plan under heterogeneous S1 storage conditions.",
        "",
        "| Case | Scenario | Demand | Budget | MIP gap | JSON SHA256 |",
        "|---|---|---|---|---:|---|",
    ]
    for key in CASE_ORDER:
        if key not in cases:
            continue
        case = cases[key]
        lines.append(
            f"| {CASE_LABELS[key]} | {case.data.get('scenario')} | "
            f"{case.data.get('demand_scenario')} | "
            f"{case.data.get('carbon_budget_case')} | "
            f"{fmt(core._solver_value(case, 'mip_gap'), 4)} | "
            f"`{case.sha256[:12]}` |"
        )
    lines.extend(
        [
            "",
            "## Main findings",
            "",
            f"- Full S5 changes discounted system cost by {fmt(cost_total)} billion CNY "
            f"relative to S1. The response available with S1 turnover fixed is "
            f"{fmt(cost_direct)} billion CNY; endogenous turnover feedback contributes "
            f"{fmt(cost_feedback)} billion CNY.",
            f"- With the best valid joint-S1 feasible upper bound, the full S5 effect is "
            f"{fmt(total_bound)} billion CNY with bounds [{fmt(total_lower)}, "
            f"{fmt(total_upper)}]. The fixed-turnover component is {fmt(direct_bound)} "
            f"[{fmt(direct_lower)}, {fmt(direct_upper)}], and turnover feedback is "
            f"{fmt(feedback_bound)} [{fmt(feedback_lower)}, {fmt(feedback_upper)}].",
            f"- Imposing the S1 turnover path in S5 has point regret "
            f"{fmt(regret)} billion CNY, with solver-bound-aware interval "
            f"[{fmt(regret_lower)}, {fmt(regret_upper)}].",
            f"- S1-to-S5 exact plant-period capture identity overlap is "
            f"{fmt(capture_identity)}. Exact plant-sink-period route overlap is "
            f"{fmt(route_identity)}, and offshore-only route overlap is "
            f"{fmt(offshore_identity)}. Offshore flow share changes from "
            f"{fmt(100 * baseline_offshore, 1)}% to {fmt(100 * s5_offshore, 1)}%.",
            f"- Strict terminal-survivor sorting identifies {int(gained['plants'])} "
            f"plants gained and {int(lost['plants'])} lost in S5. Offshore-route "
            f"eligibility is {fmt(100 * _number(gained['offshore_route_eligible_share']), 1)}% "
            f"among gained plants and "
            f"{fmt(100 * _number(lost['offshore_route_eligible_share']), 1)}% among lost "
            f"plants; their mean nearest-offshore distances are "
            f"{fmt(_number(gained['nearest_offshore_distance_mean_km']), 1)} and "
            f"{fmt(_number(lost['nearest_offshore_distance_mean_km']), 1)} km. Mean "
            f"offshore competitiveness (minimum onshore cost minus minimum parity "
            f"offshore cost) is "
            f"{fmt(_number(gained['offshore_competitiveness_mean_CNY_per_t']), 1)} "
            f"versus {fmt(_number(lost['offshore_competitiveness_mean_CNY_per_t']), 1)} "
            f"CNY/tCO2.",
            f"- The transport-and-storage subtotal changes by "
            f"{fmt(_number(costs.loc['transport_storage_net', 'total_effect_full_minus_baseline']))} "
            f"billion CNY, while capture-system and turnover subtotals change by "
            f"{fmt(_number(costs.loc['capture_system_subtotal', 'total_effect_full_minus_baseline']))} "
            f"and {fmt(_number(costs.loc['turnover_subtotal', 'total_effect_full_minus_baseline']))} "
            f"billion CNY. See `cost_component_mechanism.csv` for the nested split.",
            f"- Cumulative offshore DSA/EOR flow changes from "
            f"{fmt(_number(baseline_routes['offshore_dsa_flow_kt']) / 1e6)} / "
            f"{fmt(_number(baseline_routes['offshore_eor_flow_kt']) / 1e6)} GtCO2 "
            f"in S1 to {fmt(_number(s5_routes['offshore_dsa_flow_kt']) / 1e6)} / "
            f"{fmt(_number(s5_routes['offshore_eor_flow_kt']) / 1e6)} GtCO2 in S5. "
            f"EOR accounts for "
            f"{fmt(100 * _number(s5_routes['incremental_offshore_flow_attributable_to_eor_share']), 1)}% "
            f"of the incremental offshore flow. The S5 offshore-flow-weighted removed "
            f"premium is "
            f"{fmt(_number(s5_routes['offshore_flow_weighted_removed_premium_CNY_per_t']), 1)} "
            f"CNY/tCO2.",
            f"- In S5, {fmt(100 * _number(s5_routes['negative_net_eor_share_of_offshore_flow']), 1)}% "
            f"of offshore flow uses EOR routes whose per-ton generalized transport + "
            f"storage cost is below the EOR credit. System-wide gross route cost, EOR credit, and "
            f"net route cost change from "
            f"{fmt(_number(baseline_routes['gross_transport_storage_billion_CNY']))} / "
            f"{fmt(_number(baseline_routes['eor_revenue_credit_billion_CNY']))} / "
            f"{fmt(_number(baseline_routes['net_route_cost_billion_CNY']))} billion CNY "
            f"in S1 to {fmt(_number(s5_routes['gross_transport_storage_billion_CNY']))} / "
            f"{fmt(_number(s5_routes['eor_revenue_credit_billion_CNY']))} / "
            f"{fmt(_number(s5_routes['net_route_cost_billion_CNY']))} in S5; "
            f"these are reported separately to prevent the credit from being mistaken "
            f"for a transport/storage cost reduction.",
        ]
    )
    eor_attribution = _number(
        s5_routes["incremental_offshore_flow_attributable_to_eor_share"]
    )
    if math.isfinite(eor_attribution) and eor_attribution > 0.5:
        lines.append(
            "- More than half of incremental offshore flow is attributable to EOR. "
            "The defensible mechanism claim is therefore about removal of offshore "
            "cost premia interacting with EOR economics, not saline storage alone; a "
            "no-EOR-credit or DSA-only diagnostic would be needed for that extension."
        )
    full_gap = core._solver_value(cases["treatment_full"], "mip_gap")
    if full_gap > 0.001 + 1e-9:
        lines.append(
            f"- Solver caveat: the full S5 run reached its time limit at a "
            f"{100 * full_gap:.3f}% MIP gap, above the preferred 0.1% target. "
            "Point estimates are retained as incumbents, while inferential claims use "
            "the reported solver-bound intervals."
        )
    if "reverse_fixed_turnover" in cases:
        designated = _metric(
            summary,
            "reverse_turnover_sequential_regret_designated_run__s5_plan_under_s1_vs_joint_s1",
        )
        reverse = _metric(
            summary,
            "reverse_turnover_sequential_regret__s5_plan_under_s1_vs_joint_s1",
        )
        lower = _metric(
            summary,
            "reverse_turnover_sequential_regret__s5_plan_under_s1_vs_joint_s1",
            "comparison_lower_bound",
        )
        upper = _metric(
            summary,
            "reverse_turnover_sequential_regret__s5_plan_under_s1_vs_joint_s1",
            "comparison_upper_bound",
        )
        lines.append(
            f"- Reverse cross-fit turnover regret has designated-run difference "
            f"{fmt(designated)} billion CNY and best-known difference {fmt(reverse)}, "
            f"with bounds [{fmt(lower)}, {fmt(upper)}]."
        )
    if "reverse_fixed_dispatch" in cases:
        reverse = _metric(
            summary,
            "reverse_total_sequential_regret__s5_plan_and_dispatch_under_s1_vs_joint_s1",
        )
        lower = _metric(
            summary,
            "reverse_total_sequential_regret__s5_plan_and_dispatch_under_s1_vs_joint_s1",
            "comparison_lower_bound",
        )
        upper = _metric(
            summary,
            "reverse_total_sequential_regret__s5_plan_and_dispatch_under_s1_vs_joint_s1",
            "comparison_upper_bound",
        )
        lines.append(
            f"- Reverse y/r/u total regret is {fmt(reverse)} billion CNY, with bounds "
            f"[{fmt(lower)}, {fmt(upper)}]."
        )
    lines.extend(
        [
            "",
            "## Audit and provenance",
            "",
            f"PASS={audit_counts.get('PASS', 0)}, WARN={audit_counts.get('WARN', 0)}, "
            f"FAIL={audit_counts.get('FAIL', 0)}.",
            "",
            f"Storage sorting features: `{storage_feature_source}`.",
            "",
            "Detailed evidence is in `summary_metrics.csv`, `annual_comparison.csv`, "
            "`plant_comparison.csv`, `route_comparison.csv`, `survivor_sorting.csv`, "
            "`cost_component_mechanism.csv`, `storage_route_mechanism.csv`, and "
            "`audit_checks.csv`.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-json", required=True, type=Path)
    parser.add_argument("--s5-full-json", required=True, type=Path)
    parser.add_argument("--s5-fixed-turnover-json", required=True, type=Path)
    parser.add_argument("--s5-fixed-dispatch-json", type=Path)
    parser.add_argument("--null-control-json", type=Path)
    parser.add_argument("--reverse-fixed-turnover-json", type=Path)
    parser.add_argument("--reverse-fixed-dispatch-json", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--plant-metadata",
        type=Path,
        default=DEFAULT_PLANT_METADATA,
        help="Plant metadata used only for capacity weighting and survivor descriptions.",
    )
    parser.add_argument(
        "--storage-features-csv",
        type=Path,
        help=(
            "Optional precomputed plant storage features. If omitted, features are "
            "derived from the current v4 plant-to-storage whitelist inputs."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = {
        "baseline": args.baseline_json,
        "treatment_full": args.s5_full_json,
        "treatment_fixed_turnover": args.s5_fixed_turnover_json,
    }
    optional_paths = {
        "treatment_fixed_dispatch": args.s5_fixed_dispatch_json,
        "null_control": args.null_control_json,
        "reverse_fixed_turnover": args.reverse_fixed_turnover_json,
        "reverse_fixed_dispatch": args.reverse_fixed_dispatch_json,
    }
    paths.update({key: path for key, path in optional_paths.items() if path})
    cases = {key: core.load_case(path, key) for key, path in paths.items()}
    metadata = core.load_plant_metadata(args.plant_metadata)
    storage_features, storage_feature_source = load_storage_features(
        args.storage_features_csv
    )
    capacity_map = metadata.set_index("plant_id")["capacity_t_day"].to_dict()

    plant_frames = {
        key: core.plant_case_frame(case, metadata) for key, case in cases.items()
    }
    route_frames = {
        key: core.cumulative_route_frame(case) for key, case in cases.items()
    }
    annual_frames = {
        key: core.annual_case_frame(case, metadata) for key, case in cases.items()
    }
    scalar_metrics = {
        key: core.scalar_case_metrics(
            case,
            annual_frames[key],
            plant_frames[key],
            route_frames[key],
        )
        for key, case in cases.items()
    }

    annual_comparison = core.build_annual_comparison(cases, annual_frames)
    summary = build_summary_metrics(
        cases,
        scalar_metrics,
        plant_frames,
        route_frames,
        capacity_map,
    )
    plant_comparison = core.build_plant_comparison(cases, plant_frames).merge(
        storage_features,
        on="plant_id",
        how="left",
        validate="one_to_one",
    )
    route_comparison = core.build_route_comparison(cases, route_frames)
    cost_mechanism = build_cost_component_mechanism(cases)
    storage_route_mechanism = build_storage_route_mechanism(cases)
    survivor_sorting = build_survivor_sorting(
        cases,
        metadata,
        storage_features,
        plant_frames,
    )

    audit_rows: list[dict[str, Any]] = []
    for case in cases.values():
        core.audit_case(case, audit_rows)
    audit_cross_case(
        cases,
        metadata,
        storage_features,
        annual_comparison,
        cost_mechanism,
        survivor_sorting,
        storage_route_mechanism,
        summary,
        audit_rows,
    )
    audits = pd.DataFrame(audit_rows)

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / "summary_metrics.csv", index=False)
    annual_comparison.to_csv(output_dir / "annual_comparison.csv", index=False)
    plant_comparison.to_csv(output_dir / "plant_comparison.csv", index=False)
    route_comparison.to_csv(output_dir / "route_comparison.csv", index=False)
    survivor_sorting.to_csv(output_dir / "survivor_sorting.csv", index=False)
    cost_mechanism.to_csv(
        output_dir / "cost_component_mechanism.csv", index=False
    )
    storage_route_mechanism.to_csv(
        output_dir / "storage_route_mechanism.csv", index=False
    )
    audits.to_csv(output_dir / "audit_checks.csv", index=False)
    (output_dir / "report.md").write_text(
        render_report(
            cases,
            summary,
            cost_mechanism,
            survivor_sorting,
            storage_route_mechanism,
            audits,
            storage_feature_source,
        ),
        encoding="utf-8",
    )
    failures = int(audits["status"].eq("FAIL").sum())
    print(
        f"Wrote S5 storage-feedback analysis to {output_dir} "
        f"(PASS={audits['status'].eq('PASS').sum()}, "
        f"WARN={audits['status'].eq('WARN').sum()}, FAIL={failures})"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
