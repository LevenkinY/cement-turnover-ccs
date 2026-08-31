#!/usr/bin/env python3
"""Analyze the nested capacity-feedback counterfactual used by the paper.

The required comparison is:

* ``baseline``: heterogeneous S1 with fully endogenous turnover and dispatch;
* ``treatment_full``: equalized-resource S3 with fully endogenous turnover;
* ``treatment_fixed_turnover``: S3 with the S1 operation/renewal path (y/r)
  fixed, while dispatch and low-carbon decisions remain adaptive.

An optional dispatch-fixed S3 run fixes y/r/u and separates the direct
technology/network response from within-roster dispatch adaptation.  An
optional null control applies the same fixed-path procedure in the baseline
environment and is used to quantify solver/near-optimal noise.  Symmetric
optional reverse runs apply the fully coupled S3 y/r or y/r/u path under the
actual S1 environment.  These reverse-sequential cases test whether a plan
formed under equalized low-carbon conditions remains suitable when exposed to
the heterogeneous conditions it abstracted from.

All decision comparisons use the compact result JSON directly.  Plant
nameplate capacity is joined only for capacity weighting and production-unit
conversion; it is not used in place of solved JSON decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLANT_METADATA = (
    PROJECT_ROOT / "data" / "model_input" / "plants" / "plant_data.xlsx"
)
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
    "baseline": "S1 heterogeneous, fully coupled",
    "treatment_full": "S3 equalized, fully coupled",
    "treatment_fixed_turnover": "S3 equalized, S1 turnover fixed",
    "treatment_fixed_dispatch": "S3 equalized, S1 turnover and dispatch fixed",
    "null_control": "S1 heterogeneous, S1 turnover fixed",
    "reverse_fixed_turnover": "S1 heterogeneous, S3 turnover fixed",
    "reverse_fixed_dispatch": "S1 heterogeneous, S3 turnover and dispatch fixed",
}
MATERIAL_CAPTURE_KT_PER_YEAR = 100.0
CAPACITY_T_DAY_TO_KT_YEAR = 330.0 / 1000.0
NUMERIC_TOL = 1e-6

# Fixed-u comparisons must accept the full dispatch band released by the
# counterfactual machinery (src_v4.counterfactual.DISPATCH_BAND_TOLERANCE):
# the fixed solve may legitimately sit anywhere inside the band, including at
# its edge, so the audit tolerance is the band plus the old strict residual.
MODEL_ROOT = Path(__file__).resolve().parents[2] / "models" / "v4"
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))
from src_v4.counterfactual import (
    DISPATCH_BAND_TOLERANCE as _DISPATCH_BAND_TOLERANCE,
    REFERENCE_DEMAND_RELATIVE_TOLERANCE,
)

FIXED_U_TOLERANCE = _DISPATCH_BAND_TOLERANCE + 1e-9
RECONCILIATION_TOL_KT = 1e-3


@dataclass(frozen=True)
class Case:
    """One solved JSON result and its normalized indexing metadata."""

    key: str
    path: Path
    sha256: str
    data: dict[str, Any]
    plants: dict[int, dict[str, Any]]
    years: tuple[int, ...]
    weights: dict[int, float]


def _number(value: Any, default: float = math.nan) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _safe_div(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return math.nan
    return numerator / denominator if abs(denominator) > 1e-15 else math.nan


def _json_lookup(mapping: Any, key: int, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    if str(key) in mapping:
        return mapping[str(key)]
    return mapping.get(key, default)


def _series(case: Case, plant_id: int, variable: str) -> dict[int, float]:
    mapping = case.plants[plant_id].get(variable, {})
    return {
        year: _number(_json_lookup(mapping, year, 0.0), 0.0)
        for year in case.years
    }


def _summary_year(case: Case, year: int) -> dict[str, Any]:
    value = _json_lookup(case.data.get("summary", {}), year, {})
    return value if isinstance(value, dict) else {}


def _cost_component(case: Case, name: str) -> float:
    total = case.data.get("cost_breakdown_total", {}) or {}
    components = total.get("components_discounted_kCNY", {}) or {}
    return _number(components.get(name), 0.0)


def _solver_value(case: Case, key: str) -> float:
    solver = case.data.get("solver", {}) or {}
    if key == "objective_value":
        return _number(
            solver.get(key),
            _number(case.data.get("total_cost_kCNY", case.data.get("total_cost"))),
        )
    return _number(solver.get(key))


def load_case(path: Path, key: str) -> Case:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}") from exc
    raw_plants = data.get("plants")
    if not isinstance(raw_plants, dict) or not raw_plants:
        raise ValueError(f"Result has no solved plant mapping: {path}")
    try:
        plants = {int(plant_id): record for plant_id, record in raw_plants.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Result has non-integer plant identifiers: {path}") from exc
    raw_weights = data.get("period_weights_years", {})
    if not isinstance(raw_weights, dict) or not raw_weights:
        raise ValueError(f"Result has no period weights: {path}")
    weights = {int(year): float(weight) for year, weight in raw_weights.items()}
    years = tuple(sorted(weights))
    return Case(
        key=key,
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        data=data,
        plants=plants,
        years=years,
        weights=weights,
    )


def load_plant_metadata(path: Path) -> pd.DataFrame:
    path = path.expanduser().resolve()
    if not path.is_file():
        return pd.DataFrame(
            columns=["plant_id", "capacity_t_day", "province", "city"]
        )
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    else:
        frame = pd.read_excel(path)
    if "plant_id" not in frame.columns and "id" in frame.columns:
        frame = frame.rename(columns={"id": "plant_id"})
    capacity_column = next(
        (
            column
            for column in [
                "capacity_t_day",
                "capacity_t_per_day",
                "capacity",
                "Capacity",
            ]
            if column in frame.columns
        ),
        None,
    )
    if "plant_id" not in frame.columns or capacity_column is None:
        raise ValueError(
            f"Plant metadata must contain plant_id/id and a capacity column: {path}"
        )
    rename = {capacity_column: "capacity_t_day"}
    frame = frame.rename(columns=rename)
    keep = [
        column
        for column in ["plant_id", "capacity_t_day", "province", "city"]
        if column in frame.columns
    ]
    frame = frame[keep].copy()
    frame["plant_id"] = pd.to_numeric(frame["plant_id"], errors="raise").astype(int)
    frame["capacity_t_day"] = pd.to_numeric(
        frame["capacity_t_day"], errors="coerce"
    )
    if frame["plant_id"].duplicated().any():
        duplicates = frame.loc[frame["plant_id"].duplicated(), "plant_id"].tolist()
        raise ValueError(f"Duplicate plant ids in metadata: {duplicates[:10]}")
    return frame.sort_values("plant_id").reset_index(drop=True)


def _route_rows(case: Case) -> Iterable[dict[str, Any]]:
    routes = case.data.get("co2_flow_routes", {})
    if not isinstance(routes, dict):
        return []
    rows: list[dict[str, Any]] = []
    for outer_year, route_values in routes.items():
        try:
            default_year = int(outer_year)
        except (TypeError, ValueError):
            continue
        for raw in route_values or []:
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            row["period"] = int(row.get("period", default_year))
            rows.append(row)
    return rows


def route_frame(case: Case) -> pd.DataFrame:
    rows = []
    for row in _route_rows(case):
        year = int(row["period"])
        flow = max(_number(row.get("flow_kt", row.get("flow")), 0.0), 0.0)
        if flow <= NUMERIC_TOL:
            continue
        distance = _number(row.get("distance_km", row.get("distance")), 0.0)
        sink_type = str(row.get("type", "unknown")).upper()
        rows.append(
            {
                "plant_id": int(row["plant_id"]),
                "storage_idx": int(row["storage_idx"]),
                "type": sink_type,
                "period": year,
                "flow_kt_per_year": flow,
                "period_weight_years": case.weights[year],
                "cumulative_flow_kt": flow * case.weights[year],
                "flow_distance_kt_km": flow * case.weights[year] * distance,
                "distance_km": distance,
                "is_offshore": bool(row.get("is_offshore", False)),
                "storage_type": row.get("storage_type"),
            }
        )
    columns = [
        "plant_id",
        "storage_idx",
        "type",
        "period",
        "flow_kt_per_year",
        "period_weight_years",
        "cumulative_flow_kt",
        "flow_distance_kt_km",
        "distance_km",
        "is_offshore",
        "storage_type",
    ]
    return pd.DataFrame(rows, columns=columns)


def cumulative_route_frame(case: Case) -> pd.DataFrame:
    routes = route_frame(case)
    columns = [
        "plant_id",
        "storage_idx",
        "type",
        "cumulative_flow_kt",
        "flow_weighted_distance_km",
        "is_offshore",
        "storage_type",
    ]
    if routes.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        routes.groupby(["plant_id", "storage_idx", "type"], as_index=False)
        .agg(
            cumulative_flow_kt=("cumulative_flow_kt", "sum"),
            flow_distance_kt_km=("flow_distance_kt_km", "sum"),
            is_offshore=("is_offshore", "max"),
            storage_type=("storage_type", "first"),
        )
        .reset_index(drop=True)
    )
    grouped["flow_weighted_distance_km"] = (
        grouped["flow_distance_kt_km"] / grouped["cumulative_flow_kt"]
    )
    return grouped[columns]


def plant_case_frame(case: Case, metadata: pd.DataFrame) -> pd.DataFrame:
    metadata_index = metadata.set_index("plant_id") if not metadata.empty else None
    rows = []
    for plant_id in sorted(case.plants):
        record = case.plants[plant_id]
        capacity = math.nan
        province = None
        city = None
        if metadata_index is not None and plant_id in metadata_index.index:
            meta = metadata_index.loc[plant_id]
            capacity = _number(meta.get("capacity_t_day"))
            province = meta.get("province")
            city = meta.get("city")
        annual_capacity = capacity * CAPACITY_T_DAY_TO_KT_YEAR
        y = _series(case, plant_id, "y")
        r = _series(case, plant_id, "r")
        u = _series(case, plant_id, "u")
        z = _series(case, plant_id, "z")
        capture = _series(case, plant_id, "captured_commercial")
        gross = _series(case, plant_id, "co2_gross")
        net = _series(case, plant_id, "co2_net")
        af = _series(case, plant_id, "af_supply_ktce")
        design = _series(case, plant_id, "k_ccs")
        additions = _series(case, plant_id, "ccs_new_design")
        if not any(value > NUMERIC_TOL for value in additions.values()):
            previous = 0.0
            additions = {}
            for year in case.years:
                additions[year] = max(design[year] - previous, 0.0)
                previous = design[year]

        renewal_years = [year for year in case.years if r[year] >= 0.5]
        first_ccs = next((year for year in case.years if z[year] >= 0.5), math.nan)
        first_material = next(
            (
                year
                for year in case.years
                if capture[year] >= MATERIAL_CAPTURE_KT_PER_YEAR
            ),
            math.nan,
        )
        exit_year = next(
            (
                year
                for year in case.years
                if year > case.years[0] and y[year] < 0.5
            ),
            math.nan,
        )
        cumulative_capture = sum(
            case.weights[year] * capture[year] for year in case.years
        )
        design_capacity_years = sum(
            case.weights[year] * design[year] for year in case.years
        )
        total_additions = sum(additions.values())
        cumulative_production = (
            sum(case.weights[year] * annual_capacity * u[year] for year in case.years)
            if math.isfinite(annual_capacity)
            else math.nan
        )
        rows.append(
            {
                "plant_id": plant_id,
                "capacity_t_day": capacity,
                "province": province,
                "city": city,
                "y_path": "|".join(f"{year}:{int(round(y[year]))}" for year in case.years),
                "r_path": "|".join(f"{year}:{int(round(r[year]))}" for year in case.years),
                "u_path": "|".join(f"{year}:{u[year]:.12g}" for year in case.years),
                "terminal_operating": int(y[case.years[-1]] >= 0.5),
                "terminal_utilization": u[case.years[-1]],
                "renewal_year": min(renewal_years) if renewal_years else math.nan,
                "exit_year": exit_year,
                "first_ccs_year": first_ccs,
                "first_material_ccs_year": first_material,
                "cumulative_capture_kt": cumulative_capture,
                "capture_2060_kt_per_year": capture[case.years[-1]],
                "cumulative_gross_kt": sum(
                    case.weights[year] * gross[year] for year in case.years
                ),
                "cumulative_net_kt": sum(
                    case.weights[year] * net[year] for year in case.years
                ),
                "cumulative_af_ktce_year": sum(
                    case.weights[year] * af[year] for year in case.years
                ),
                "cumulative_production_kt": cumulative_production,
                "ccs_design_additions_kt_per_year": total_additions,
                "ccs_design_capacity_years_kt": design_capacity_years,
                "ccs_portfolio_load_factor": _safe_div(
                    cumulative_capture, design_capacity_years
                ),
                "ccs_full_load_equivalent_years": _safe_div(
                    cumulative_capture, total_additions
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("plant_id").reset_index(drop=True)


def annual_case_frame(case: Case, metadata: pd.DataFrame) -> pd.DataFrame:
    capacity_map = (
        metadata.set_index("plant_id")["capacity_t_day"].to_dict()
        if not metadata.empty
        else {}
    )
    routes = route_frame(case)
    rows = []
    first_material_by_plant: dict[int, int] = {}
    for plant_id in case.plants:
        capture = _series(case, plant_id, "captured_commercial")
        first = next(
            (
                year
                for year in case.years
                if capture[year] >= MATERIAL_CAPTURE_KT_PER_YEAR
            ),
            None,
        )
        if first is not None:
            first_material_by_plant[plant_id] = first

    for year in case.years:
        operating = 0
        operating_capacity = 0.0
        production = 0.0
        renewal_events = 0
        ccs_installed = 0
        ccs_design = 0.0
        ccs_additions = 0.0
        capture = 0.0
        gross = 0.0
        net = 0.0
        af = 0.0
        material_ccs = 0
        for plant_id in case.plants:
            y = _series(case, plant_id, "y")[year]
            r = _series(case, plant_id, "r")[year]
            u = _series(case, plant_id, "u")[year]
            z = _series(case, plant_id, "z")[year]
            k = _series(case, plant_id, "k_ccs")[year]
            addition = _series(case, plant_id, "ccs_new_design")[year]
            captured = _series(case, plant_id, "captured_commercial")[year]
            capacity = _number(capacity_map.get(plant_id))
            annual_capacity = capacity * CAPACITY_T_DAY_TO_KT_YEAR
            operating += int(y >= 0.5)
            if math.isfinite(annual_capacity):
                operating_capacity += annual_capacity * int(y >= 0.5)
                production += annual_capacity * u
            renewal_events += int(r >= 0.5)
            ccs_installed += int(z >= 0.5)
            ccs_design += k
            ccs_additions += addition
            capture += captured
            gross += _series(case, plant_id, "co2_gross")[year]
            net += _series(case, plant_id, "co2_net")[year]
            af += _series(case, plant_id, "af_supply_ktce")[year]
            material_ccs += int(captured >= MATERIAL_CAPTURE_KT_PER_YEAR)

        annual_routes = routes[routes["period"].eq(year)] if not routes.empty else routes
        route_flow = (
            float(annual_routes["flow_kt_per_year"].sum())
            if not annual_routes.empty
            else 0.0
        )
        weighted_distance = (
            float(
                (
                    annual_routes["flow_kt_per_year"]
                    * annual_routes["distance_km"]
                ).sum()
                / route_flow
            )
            if route_flow > NUMERIC_TOL
            else 0.0
        )
        offshore_flow = (
            float(
                annual_routes.loc[
                    annual_routes["is_offshore"], "flow_kt_per_year"
                ].sum()
            )
            if not annual_routes.empty
            else 0.0
        )
        dsa_flow = (
            float(
                annual_routes.loc[
                    annual_routes["type"].eq("DSA"), "flow_kt_per_year"
                ].sum()
            )
            if not annual_routes.empty
            else 0.0
        )
        summary = _summary_year(case, year)
        rows.append(
            {
                "year": year,
                "n_operating_plants": operating,
                "operating_capacity_mt_per_year": operating_capacity / 1000.0,
                "clinker_production_mt_per_year": production / 1000.0,
                "renewal_events": renewal_events,
                "n_ccs_installed": ccs_installed,
                "n_material_ccs_plants": material_ccs,
                "first_material_ccs_entries": sum(
                    first == year for first in first_material_by_plant.values()
                ),
                "ccs_design_mt_per_year": ccs_design / 1000.0,
                "ccs_design_additions_mt_per_year": ccs_additions / 1000.0,
                "captured_co2_mt_per_year": capture / 1000.0,
                "gross_co2_mt_per_year": gross / 1000.0,
                "net_co2_mt_per_year": net / 1000.0,
                "af_supply_ktce_per_year": af,
                "ccs_load_factor": _safe_div(capture, ccs_design),
                "route_flow_mt_per_year": route_flow / 1000.0,
                "weighted_transport_distance_km": weighted_distance,
                "offshore_flow_share": _safe_div(offshore_flow, route_flow),
                "dsa_flow_share": _safe_div(dsa_flow, route_flow),
                "cement_demand_mt": _number(summary.get("cement_demand_mt")),
                "effective_clinker_ratio": _number(
                    summary.get("effective_clinker_ratio")
                ),
            }
        )
    return pd.DataFrame(rows)


def scalar_case_metrics(
    case: Case,
    annual: pd.DataFrame,
    plants: pd.DataFrame,
    routes: pd.DataFrame,
) -> dict[str, tuple[float, str, str]]:
    """Return metric -> (value, unit, note)."""

    weights = annual["year"].map(case.weights).astype(float)
    cumulative_capture_gt = float(
        (annual["captured_co2_mt_per_year"] * weights).sum() / 1000.0
    )
    cumulative_net_gt = float(
        (annual["net_co2_mt_per_year"] * weights).sum() / 1000.0
    )
    cumulative_gross_gt = float(
        (annual["gross_co2_mt_per_year"] * weights).sum() / 1000.0
    )
    design_capacity_years = float(plants["ccs_design_capacity_years_kt"].sum())
    design_additions = float(plants["ccs_design_additions_kt_per_year"].sum())
    cumulative_capture_kt = float(plants["cumulative_capture_kt"].sum())
    addition_rows = []
    for plant_id in case.plants:
        additions = _series(case, plant_id, "ccs_new_design")
        for year, amount in additions.items():
            if amount > NUMERIC_TOL:
                addition_rows.append((year, amount))
    addition_total = sum(amount for _, amount in addition_rows)
    mean_install_year = _safe_div(
        sum(year * amount for year, amount in addition_rows), addition_total
    )
    share_by_2045 = _safe_div(
        sum(amount for year, amount in addition_rows if year <= 2045), addition_total
    )
    route_flow = float(routes["cumulative_flow_kt"].sum()) if not routes.empty else 0.0
    route_distance = (
        float(
            (
                routes["cumulative_flow_kt"]
                * routes["flow_weighted_distance_km"]
            ).sum()
            / route_flow
        )
        if route_flow > NUMERIC_TOL
        else 0.0
    )
    offshore_share = (
        float(
            routes.loc[routes["is_offshore"], "cumulative_flow_kt"].sum()
            / route_flow
        )
        if route_flow > NUMERIC_TOL and not routes.empty
        else 0.0
    )
    dsa_share = (
        float(
            routes.loc[routes["type"].eq("DSA"), "cumulative_flow_kt"].sum()
            / route_flow
        )
        if route_flow > NUMERIC_TOL and not routes.empty
        else 0.0
    )
    final = annual.loc[annual["year"].idxmax()]
    costs = {
        "discounted_ccs_capex": _cost_component(case, "ccs_capex") / 1e6,
        "discounted_ccs_opex": _cost_component(case, "ccs_opex") / 1e6,
        "discounted_turnover_cost": (
            _cost_component(case, "same_site_renewal_capex")
            + _cost_component(case, "early_retirement")
        )
        / 1e6,
        "discounted_af_cost": (
            _cost_component(case, "af_capex")
            + _cost_component(case, "af_opex")
            + _cost_component(case, "fuel")
        )
        / 1e6,
        "discounted_transport_storage_net_cost": (
            _cost_component(case, "transport")
            + _cost_component(case, "dsa_storage")
            + _cost_component(case, "eor_storage")
            + _cost_component(case, "eor_revenue_credit")
        )
        / 1e6,
    }
    metrics: dict[str, tuple[float, str, str]] = {
        "objective_incumbent": (
            _solver_value(case, "objective_value") / 1e6,
            "billion_CNY",
            "Discounted incremental mitigation cost incumbent.",
        ),
        "objective_bound": (
            _solver_value(case, "objective_bound") / 1e6,
            "billion_CNY",
            "Solver lower bound for the minimization objective.",
        ),
        "mip_gap": (
            _solver_value(case, "mip_gap"),
            "fraction",
            "Relative MIP gap reported by the solver.",
        ),
        "cumulative_capture": (
            cumulative_capture_gt,
            "GtCO2",
            "Trapezoid-weighted commercial capture over 2025-2060.",
        ),
        "cumulative_gross_direct_emissions": (
            cumulative_gross_gt,
            "GtCO2",
            "Trapezoid-weighted gross direct emissions.",
        ),
        "cumulative_net_direct_emissions": (
            cumulative_net_gt,
            "GtCO2",
            "Trapezoid-weighted net direct emissions.",
        ),
        "capture_2060": (
            float(final["captured_co2_mt_per_year"]),
            "MtCO2_per_year",
            "Commercial capture at the terminal model node.",
        ),
        "terminal_operating_plants": (
            float(final["n_operating_plants"]),
            "plants",
            "Plants with y=1 in 2060.",
        ),
        "terminal_operating_capacity": (
            float(final["operating_capacity_mt_per_year"]),
            "Mt_clinker_per_year",
            "Nameplate capacity with y=1 in 2060.",
        ),
        "terminal_clinker_production": (
            float(final["clinker_production_mt_per_year"]),
            "Mt_clinker_per_year",
            "Plant-level capacity times solved utilization in 2060.",
        ),
        "same_site_renewal_events": (
            float(plants["renewal_year"].notna().sum()),
            "plants",
            "Plants with one solved same-site renewal event.",
        ),
        "material_ccs_plants_ever": (
            float(plants["first_material_ccs_year"].notna().sum()),
            "plants",
            "Plants reaching at least 100 ktCO2/yr commercial capture.",
        ),
        "ccs_portfolio_load_factor": (
            _safe_div(cumulative_capture_kt, design_capacity_years),
            "fraction",
            "Capture divided by design-capacity years within the horizon.",
        ),
        "ccs_horizon_design_service_years": (
            _safe_div(design_capacity_years, design_additions),
            "years",
            "Horizon-observed design service years per unit of new design.",
        ),
        "ccs_full_load_equivalent_years": (
            _safe_div(cumulative_capture_kt, design_additions),
            "years",
            "Cumulative capture per unit of new CCS design capacity.",
        ),
        "ccs_design_additions": (
            design_additions / 1000.0,
            "MtCO2_per_year",
            "Sum of plant-level positive commercial design additions.",
        ),
        "ccs_design_weighted_mean_installation_year": (
            mean_install_year,
            "year",
            "Mean addition year weighted by new design capacity.",
        ),
        "ccs_design_addition_share_by_2045": (
            share_by_2045,
            "fraction",
            "Share of new design capacity installed no later than 2045.",
        ),
        "flow_weighted_transport_distance": (
            route_distance,
            "km",
            "Cumulative commercial-flow-weighted direct route distance.",
        ),
        "offshore_flow_share": (
            offshore_share,
            "fraction",
            "Cumulative commercial flow sent to offshore storage.",
        ),
        "dsa_flow_share": (
            dsa_share,
            "fraction",
            "Cumulative commercial flow sent through DSA routes.",
        ),
    }
    for metric, value in costs.items():
        metrics[metric] = (
            value,
            "billion_CNY",
            "Discounted objective-component diagnostic.",
        )
    return metrics


def _set_jaccard(left: set[Any], right: set[Any]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def capacity_path_jaccard(
    left: Case,
    right: Case,
    capacity_map: dict[int, float],
) -> float:
    numerator = 0.0
    denominator = 0.0
    for plant_id in left.plants:
        capacity = _number(capacity_map.get(plant_id))
        if not math.isfinite(capacity):
            continue
        ly = _series(left, plant_id, "y")
        ry = _series(right, plant_id, "y")
        for year in left.years:
            if year == left.years[0]:
                continue
            weight = left.weights[year]
            numerator += weight * capacity * min(ly[year], ry[year])
            denominator += weight * capacity * max(ly[year], ry[year])
    return _safe_div(numerator, denominator)


def production_distribution_overlap(
    left: Case,
    right: Case,
    capacity_map: dict[int, float],
) -> float:
    common = 0.0
    total_left = 0.0
    total_right = 0.0
    for plant_id in left.plants:
        capacity = _number(capacity_map.get(plant_id))
        if not math.isfinite(capacity):
            continue
        annual_capacity = capacity * CAPACITY_T_DAY_TO_KT_YEAR
        lu = _series(left, plant_id, "u")
        ru = _series(right, plant_id, "u")
        for year in left.years:
            weight = left.weights[year]
            lq = annual_capacity * lu[year]
            rq = annual_capacity * ru[year]
            common += weight * min(lq, rq)
            total_left += weight * lq
            total_right += weight * rq
    return _safe_div(common, 0.5 * (total_left + total_right))


def weighted_plant_capture_jaccard(left: Case, right: Case) -> float:
    numerator = 0.0
    denominator = 0.0
    for plant_id in left.plants:
        lc = _series(left, plant_id, "captured_commercial")
        rc = _series(right, plant_id, "captured_commercial")
        left_total = sum(left.weights[year] * lc[year] for year in left.years)
        right_total = sum(right.weights[year] * rc[year] for year in right.years)
        numerator += min(left_total, right_total)
        denominator += max(left_total, right_total)
    return _safe_div(numerator, denominator)


def capture_responsibility_retained(source: Case, availability: Case) -> float:
    retained = 0.0
    total = 0.0
    for plant_id in source.plants:
        capture = _series(source, plant_id, "captured_commercial")
        y = _series(availability, plant_id, "y")
        for year in source.years:
            amount = source.weights[year] * capture[year]
            total += amount
            retained += amount * int(y[year] >= 0.5)
    return _safe_div(retained, total)


def weighted_flow_jaccard(
    left: pd.DataFrame,
    right: pd.DataFrame,
    keys: list[str],
) -> float:
    left_values = (
        left.groupby(keys)["cumulative_flow_kt"].sum()
        if not left.empty
        else pd.Series(dtype=float)
    )
    right_values = (
        right.groupby(keys)["cumulative_flow_kt"].sum()
        if not right.empty
        else pd.Series(dtype=float)
    )
    union = left_values.index.union(right_values.index)
    left_values = left_values.reindex(union, fill_value=0.0)
    right_values = right_values.reindex(union, fill_value=0.0)
    denominator = float(pd.concat([left_values, right_values], axis=1).max(axis=1).sum())
    numerator = float(pd.concat([left_values, right_values], axis=1).min(axis=1).sum())
    return _safe_div(numerator, denominator)


def _retained_set(case: Case) -> set[int]:
    terminal = case.years[-1]
    return {
        plant_id
        for plant_id in case.plants
        if _series(case, plant_id, "y")[terminal] >= 0.5
    }


def _renewal_set(case: Case) -> set[tuple[int, int]]:
    return {
        (plant_id, year)
        for plant_id in case.plants
        for year, value in _series(case, plant_id, "r").items()
        if value >= 0.5
    }


def _path_changed(left: Case, right: Case, plant_id: int, variable: str) -> bool:
    ls = _series(left, plant_id, variable)
    rs = _series(right, plant_id, variable)
    tolerance = FIXED_U_TOLERANCE if variable == "u" else NUMERIC_TOL
    return any(abs(ls[year] - rs[year]) > tolerance for year in left.years)


def _regret_interval(fixed: Case, flexible: Case) -> tuple[float, float, float]:
    fixed_ub = _solver_value(fixed, "objective_value") / 1e6
    fixed_lb = _solver_value(fixed, "objective_bound") / 1e6
    flexible_ub = _solver_value(flexible, "objective_value") / 1e6
    flexible_lb = _solver_value(flexible, "objective_bound") / 1e6
    point = fixed_ub - flexible_ub
    lower = max(0.0, fixed_lb - flexible_ub)
    upper = max(0.0, fixed_ub - flexible_lb)
    return point, lower, upper


def _same_optimization_environment(left: Case, right: Case) -> bool:
    return (
        left.data.get("scenario") == right.data.get("scenario")
        and left.data.get("demand_scenario")
        == right.data.get("demand_scenario")
        and left.data.get("carbon_budget_case")
        == right.data.get("carbon_budget_case")
        and left.data.get("cost_boundary") == right.data.get("cost_boundary")
        and (left.data.get("scenario_adjustments", {}) or {})
        == (right.data.get("scenario_adjustments", {}) or {})
        and left.years == right.years
        and left.weights == right.weights
        and set(left.plants) == set(right.plants)
    )


def _reverse_regret_against_joint(
    fixed: Case,
    joint: Case,
    feasible_control: Case | None,
) -> dict[str, float | str]:
    """Bound reverse regret using the best valid joint-S1 incumbent available.

    A same-environment null-control solution is feasible for the unrestricted
    joint S1 problem even though it fixes a path internally.  Its incumbent can
    therefore tighten the joint problem's feasible upper bound.  Its solver
    lower bound cannot tighten the unrestricted S1 lower bound and is not used.
    """

    fixed_ub = _solver_value(fixed, "objective_value") / 1e6
    fixed_lb = _solver_value(fixed, "objective_bound") / 1e6
    joint_ub = _solver_value(joint, "objective_value") / 1e6
    joint_lb = _solver_value(joint, "objective_bound") / 1e6
    best_joint_ub = joint_ub
    best_source = joint.key
    if feasible_control is not None and _same_optimization_environment(
        feasible_control, joint
    ):
        control_ub = _solver_value(feasible_control, "objective_value") / 1e6
        if math.isfinite(control_ub) and control_ub < best_joint_ub:
            best_joint_ub = control_ub
            best_source = feasible_control.key
    return {
        "designated_point": fixed_ub - joint_ub,
        "best_known_point": fixed_ub - best_joint_ub,
        "lower": max(0.0, fixed_lb - best_joint_ub),
        "upper": max(0.0, fixed_ub - joint_lb),
        "best_joint_ub": best_joint_ub,
        "best_joint_ub_source": best_source,
    }


def build_annual_comparison(
    cases: dict[str, Case], annual_frames: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    rows = []
    metric_columns = [
        column
        for column in annual_frames["baseline"].columns
        if column != "year"
    ]
    for year in cases["baseline"].years:
        values_by_case = {
            key: frame.loc[frame["year"].eq(year)].iloc[0]
            for key, frame in annual_frames.items()
        }
        for metric in metric_columns:
            values = {
                key: _number(row.get(metric)) for key, row in values_by_case.items()
            }
            base = values["baseline"]
            full = values["treatment_full"]
            fixed = values["treatment_fixed_turnover"]
            dispatch = values.get("treatment_fixed_dispatch", math.nan)
            null = values.get("null_control", math.nan)
            reverse_turnover = values.get("reverse_fixed_turnover", math.nan)
            reverse_dispatch = values.get("reverse_fixed_dispatch", math.nan)
            total_effect = full - base
            direct = fixed - base
            turnover_feedback = full - fixed
            pure_direct = dispatch - base if math.isfinite(dispatch) else math.nan
            dispatch_feedback = (
                fixed - dispatch if math.isfinite(dispatch) else math.nan
            )
            reverse_turnover_regret = (
                reverse_turnover - base
                if math.isfinite(reverse_turnover)
                else math.nan
            )
            reverse_dispatch_increment = (
                reverse_dispatch - reverse_turnover
                if math.isfinite(reverse_dispatch)
                and math.isfinite(reverse_turnover)
                else math.nan
            )
            reverse_total_regret = (
                reverse_dispatch - base
                if math.isfinite(reverse_dispatch)
                else math.nan
            )
            rows.append(
                {
                    "year": year,
                    "metric": metric,
                    "baseline_value": base,
                    "treatment_full_value": full,
                    "treatment_fixed_turnover_value": fixed,
                    "treatment_fixed_dispatch_value": dispatch,
                    "null_control_value": null,
                    "reverse_fixed_turnover_value": reverse_turnover,
                    "reverse_fixed_dispatch_value": reverse_dispatch,
                    "total_effect_full_minus_baseline": total_effect,
                    "direct_effect_fixed_turnover_minus_baseline": direct,
                    "turnover_feedback_full_minus_fixed_turnover": turnover_feedback,
                    "pure_direct_effect_fixed_dispatch_minus_baseline": pure_direct,
                    "dispatch_feedback_fixed_turnover_minus_fixed_dispatch": dispatch_feedback,
                    "null_control_delta": null - base if math.isfinite(null) else math.nan,
                    "reverse_turnover_regret_vs_joint_s1": reverse_turnover_regret,
                    "reverse_dispatch_increment": reverse_dispatch_increment,
                    "reverse_total_regret_vs_joint_s1": reverse_total_regret,
                    "two_level_decomposition_residual": total_effect
                    - direct
                    - turnover_feedback,
                    "three_level_decomposition_residual": (
                        total_effect
                        - pure_direct
                        - dispatch_feedback
                        - turnover_feedback
                        if math.isfinite(dispatch)
                        else math.nan
                    ),
                    "reverse_decomposition_residual": (
                        reverse_total_regret
                        - reverse_turnover_regret
                        - reverse_dispatch_increment
                        if math.isfinite(reverse_dispatch)
                        and math.isfinite(reverse_turnover)
                        else math.nan
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_summary_metrics(
    cases: dict[str, Case],
    scalar_metrics: dict[str, dict[str, tuple[float, str, str]]],
    plant_frames: dict[str, pd.DataFrame],
    route_frames: dict[str, pd.DataFrame],
    capacity_map: dict[int, float],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    metric_names = list(scalar_metrics["baseline"])
    for metric in metric_names:
        values = {
            key: metrics[metric][0] for key, metrics in scalar_metrics.items()
        }
        unit = scalar_metrics["baseline"][metric][1]
        note = scalar_metrics["baseline"][metric][2]
        base = values["baseline"]
        full = values["treatment_full"]
        fixed = values["treatment_fixed_turnover"]
        dispatch = values.get("treatment_fixed_dispatch", math.nan)
        null = values.get("null_control", math.nan)
        reverse_turnover = values.get("reverse_fixed_turnover", math.nan)
        reverse_dispatch = values.get("reverse_fixed_dispatch", math.nan)
        total_effect = full - base
        direct = fixed - base
        turnover_feedback = full - fixed
        pure_direct = dispatch - base if math.isfinite(dispatch) else math.nan
        dispatch_feedback = fixed - dispatch if math.isfinite(dispatch) else math.nan
        reverse_turnover_regret = (
            reverse_turnover - base
            if math.isfinite(reverse_turnover)
            else math.nan
        )
        reverse_dispatch_increment = (
            reverse_dispatch - reverse_turnover
            if math.isfinite(reverse_dispatch) and math.isfinite(reverse_turnover)
            else math.nan
        )
        reverse_total_regret = (
            reverse_dispatch - base
            if math.isfinite(reverse_dispatch)
            else math.nan
        )
        rows.append(
            {
                "metric": metric,
                "metric_kind": "case_and_nested_decomposition",
                "unit": unit,
                "baseline_value": base,
                "treatment_full_value": full,
                "treatment_fixed_turnover_value": fixed,
                "treatment_fixed_dispatch_value": dispatch,
                "null_control_value": null,
                "reverse_fixed_turnover_value": reverse_turnover,
                "reverse_fixed_dispatch_value": reverse_dispatch,
                "total_effect_full_minus_baseline": total_effect,
                "direct_effect_fixed_turnover_minus_baseline": direct,
                "turnover_feedback_full_minus_fixed_turnover": turnover_feedback,
                "pure_direct_effect_fixed_dispatch_minus_baseline": pure_direct,
                "dispatch_feedback_fixed_turnover_minus_fixed_dispatch": dispatch_feedback,
                "null_control_delta": null - base if math.isfinite(null) else math.nan,
                "reverse_turnover_regret_vs_joint_s1": reverse_turnover_regret,
                "reverse_dispatch_increment": reverse_dispatch_increment,
                "reverse_total_regret_vs_joint_s1": reverse_total_regret,
                "comparison_value": math.nan,
                "comparison_lower_bound": math.nan,
                "comparison_upper_bound": math.nan,
                "note": note,
            }
        )

    def comparison_row(
        metric: str,
        value: float,
        unit: str,
        note: str,
        lower: float = math.nan,
        upper: float = math.nan,
    ) -> None:
        rows.append(
            {
                "metric": metric,
                "metric_kind": "comparison",
                "unit": unit,
                "baseline_value": math.nan,
                "treatment_full_value": math.nan,
                "treatment_fixed_turnover_value": math.nan,
                "treatment_fixed_dispatch_value": math.nan,
                "null_control_value": math.nan,
                "reverse_fixed_turnover_value": math.nan,
                "reverse_fixed_dispatch_value": math.nan,
                "total_effect_full_minus_baseline": math.nan,
                "direct_effect_fixed_turnover_minus_baseline": math.nan,
                "turnover_feedback_full_minus_fixed_turnover": math.nan,
                "pure_direct_effect_fixed_dispatch_minus_baseline": math.nan,
                "dispatch_feedback_fixed_turnover_minus_fixed_dispatch": math.nan,
                "null_control_delta": math.nan,
                "reverse_turnover_regret_vs_joint_s1": math.nan,
                "reverse_dispatch_increment": math.nan,
                "reverse_total_regret_vs_joint_s1": math.nan,
                "comparison_value": value,
                "comparison_lower_bound": lower,
                "comparison_upper_bound": upper,
                "note": note,
            }
        )

    pairs = {
        "baseline_vs_treatment_full": (cases["baseline"], cases["treatment_full"]),
        "baseline_vs_treatment_fixed_turnover": (
            cases["baseline"],
            cases["treatment_fixed_turnover"],
        ),
        "treatment_full_vs_treatment_fixed_turnover": (
            cases["treatment_full"],
            cases["treatment_fixed_turnover"],
        ),
    }
    if "treatment_fixed_dispatch" in cases:
        pairs["treatment_fixed_turnover_vs_treatment_fixed_dispatch"] = (
            cases["treatment_fixed_turnover"],
            cases["treatment_fixed_dispatch"],
        )
    if "null_control" in cases:
        pairs["baseline_vs_null_control"] = (
            cases["baseline"],
            cases["null_control"],
        )
    if "reverse_fixed_turnover" in cases:
        pairs["baseline_vs_reverse_fixed_turnover"] = (
            cases["baseline"],
            cases["reverse_fixed_turnover"],
        )
        pairs["treatment_full_vs_reverse_fixed_turnover"] = (
            cases["treatment_full"],
            cases["reverse_fixed_turnover"],
        )
    if "reverse_fixed_dispatch" in cases:
        pairs["baseline_vs_reverse_fixed_dispatch"] = (
            cases["baseline"],
            cases["reverse_fixed_dispatch"],
        )
        pairs["treatment_full_vs_reverse_fixed_dispatch"] = (
            cases["treatment_full"],
            cases["reverse_fixed_dispatch"],
        )
        if "reverse_fixed_turnover" in cases:
            pairs["reverse_fixed_turnover_vs_reverse_fixed_dispatch"] = (
                cases["reverse_fixed_turnover"],
                cases["reverse_fixed_dispatch"],
            )

    for label, (left, right) in pairs.items():
        comparison_row(
            f"capacity_path_jaccard__{label}",
            capacity_path_jaccard(left, right, capacity_map),
            "fraction",
            "Capacity-weighted, period-weighted Jaccard of y after 2025.",
        )
        comparison_row(
            f"terminal_retained_set_jaccard__{label}",
            _set_jaccard(_retained_set(left), _retained_set(right)),
            "fraction",
            "Unweighted Jaccard of plants with y=1 in 2060.",
        )
        comparison_row(
            f"renewal_event_jaccard__{label}",
            _set_jaccard(_renewal_set(left), _renewal_set(right)),
            "fraction",
            "Jaccard of exact (plant, renewal-year) events.",
        )
        comparison_row(
            f"production_distribution_overlap__{label}",
            production_distribution_overlap(left, right, capacity_map),
            "fraction",
            "Shared cumulative clinker production mass; 1 equals identical dispatch.",
        )
        comparison_row(
            f"capture_weighted_jaccard__{label}",
            weighted_plant_capture_jaccard(left, right),
            "fraction",
            "Weighted Jaccard of cumulative commercial capture by plant.",
        )
        comparison_row(
            f"route_flow_weighted_jaccard__{label}",
            weighted_flow_jaccard(
                route_frames[left.key],
                route_frames[right.key],
                ["plant_id", "storage_idx", "type"],
            ),
            "fraction",
            "Weighted Jaccard of cumulative direct plant-sink route flows.",
        )
        comparison_row(
            f"storage_node_flow_weighted_jaccard__{label}",
            weighted_flow_jaccard(
                route_frames[left.key],
                route_frames[right.key],
                ["storage_idx", "type"],
            ),
            "fraction",
            "Weighted Jaccard after aggregating flows to storage node and sink type.",
        )

    base_retained = _retained_set(cases["baseline"])
    full_retained = _retained_set(cases["treatment_full"])
    base_renewal = _renewal_set(cases["baseline"])
    full_renewal = _renewal_set(cases["treatment_full"])
    comparison_row(
        "terminal_plants_added__treatment_full_vs_baseline",
        float(len(full_retained - base_retained)),
        "plants",
        "Plants retained in 2060 only by fully coupled S3.",
    )
    comparison_row(
        "terminal_plants_lost__treatment_full_vs_baseline",
        float(len(base_retained - full_retained)),
        "plants",
        "S1 terminal plants not retained by fully coupled S3.",
    )
    comparison_row(
        "renewal_events_added__treatment_full_vs_baseline",
        float(len(full_renewal - base_renewal)),
        "events",
        "New plant-year renewal events in fully coupled S3.",
    )
    comparison_row(
        "renewal_events_lost__treatment_full_vs_baseline",
        float(len(base_renewal - full_renewal)),
        "events",
        "S1 renewal events absent from fully coupled S3.",
    )
    comparison_row(
        "treatment_full_capture_responsibility_compatible_with_baseline_turnover",
        capture_responsibility_retained(
            cases["treatment_full"], cases["baseline"]
        ),
        "fraction",
        "Share of fully coupled S3 capture occurring where the S1 plant is active in the same period.",
    )
    changed = sum(
        _path_changed(
            cases["baseline"], cases["treatment_full"], plant_id, "y"
        )
        or _path_changed(
            cases["baseline"], cases["treatment_full"], plant_id, "r"
        )
        for plant_id in cases["baseline"].plants
    )
    comparison_row(
        "plants_with_turnover_path_change__treatment_full_vs_baseline",
        float(changed),
        "plants",
        "Plants whose y or r path changes under fully coupled S3.",
    )

    point, lower, upper = _regret_interval(
        cases["treatment_fixed_turnover"], cases["treatment_full"]
    )
    comparison_row(
        "turnover_lockin_regret__fixed_turnover_vs_full_treatment",
        point,
        "billion_CNY",
        "Cost of imposing the S1 turnover path in S3; interval uses solver bounds.",
        lower,
        upper,
    )
    full_cost = _solver_value(cases["treatment_full"], "objective_value") / 1e6
    comparison_row(
        "turnover_lockin_regret_share_of_full_treatment_cost",
        _safe_div(point, full_cost),
        "fraction",
        "Point regret divided by the fully coupled S3 incumbent cost.",
        _safe_div(lower, full_cost),
        _safe_div(upper, full_cost),
    )

    if "treatment_fixed_dispatch" in cases:
        point, lower, upper = _regret_interval(
            cases["treatment_fixed_dispatch"],
            cases["treatment_fixed_turnover"],
        )
        comparison_row(
            "dispatch_lockin_regret__fixed_dispatch_vs_fixed_turnover",
            point,
            "billion_CNY",
            "Additional cost of fixing S1 utilization after the turnover path is fixed.",
            lower,
            upper,
        )
        point, lower, upper = _regret_interval(
            cases["treatment_fixed_dispatch"], cases["treatment_full"]
        )
        comparison_row(
            "total_lockin_regret__fixed_dispatch_vs_full_treatment",
            point,
            "billion_CNY",
            "Combined turnover-and-dispatch lock-in cost in S3.",
            lower,
            upper,
        )

    if "null_control" in cases:
        point, lower, upper = _regret_interval(
            cases["null_control"], cases["baseline"]
        )
        comparison_row(
            "null_control_lockin_regret",
            point,
            "billion_CNY",
            "Same-environment fixed-turnover control; use its interval as a solver-noise benchmark.",
            lower,
            upper,
        )

    if "reverse_fixed_turnover" in cases:
        reverse = _reverse_regret_against_joint(
            cases["reverse_fixed_turnover"],
            cases["baseline"],
            cases.get("null_control"),
        )
        comparison_row(
            "joint_s1_best_known_incumbent_for_reverse_regret",
            float(reverse["best_joint_ub"]),
            "billion_CNY",
            f"Best feasible upper bound used for joint S1; source={reverse['best_joint_ub_source']}.",
        )
        comparison_row(
            "reverse_turnover_sequential_regret_designated_run__s3_plan_under_s1_vs_joint_s1",
            float(reverse["designated_point"]),
            "billion_CNY",
            "Incumbent difference against the designated fully coupled S1 run; retained for run-to-run transparency.",
        )
        comparison_row(
            "reverse_turnover_sequential_regret__s3_plan_under_s1_vs_joint_s1",
            float(reverse["best_known_point"]),
            "billion_CNY",
            f"Best-known incumbent difference for imposing S3 y/r under S1; lower bound uses the best feasible joint-S1 upper bound ({reverse['best_joint_ub_source']}) and upper bound uses the unrestricted S1 solver lower bound.",
            float(reverse["lower"]),
            float(reverse["upper"]),
        )
    if "reverse_fixed_dispatch" in cases:
        reverse_total = _reverse_regret_against_joint(
            cases["reverse_fixed_dispatch"],
            cases["baseline"],
            cases.get("null_control"),
        )
        comparison_row(
            "reverse_total_sequential_regret_designated_run__s3_plan_and_dispatch_under_s1_vs_joint_s1",
            float(reverse_total["designated_point"]),
            "billion_CNY",
            "Incumbent difference against the designated fully coupled S1 run; retained for run-to-run transparency.",
        )
        comparison_row(
            "reverse_total_sequential_regret__s3_plan_and_dispatch_under_s1_vs_joint_s1",
            float(reverse_total["best_known_point"]),
            "billion_CNY",
            f"Best-known incumbent difference for imposing S3 y/r/u under S1; lower bound uses the best feasible joint-S1 upper bound ({reverse_total['best_joint_ub_source']}) and upper bound uses the unrestricted S1 solver lower bound.",
            float(reverse_total["lower"]),
            float(reverse_total["upper"]),
        )
        if "reverse_fixed_turnover" in cases:
            point, lower, upper = _regret_interval(
                cases["reverse_fixed_dispatch"],
                cases["reverse_fixed_turnover"],
            )
            comparison_row(
                "reverse_dispatch_sequential_regret__fixed_dispatch_vs_fixed_turnover",
                point,
                "billion_CNY",
                "Additional cost of imposing the S3 utilization path once the S3 turnover path is already fixed under S1.",
                lower,
                upper,
            )
    return pd.DataFrame(rows)


def build_plant_comparison(
    cases: dict[str, Case], plant_frames: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    base = plant_frames["baseline"]
    output = base[["plant_id", "capacity_t_day", "province", "city"]].copy()
    fields = [
        "y_path",
        "r_path",
        "u_path",
        "terminal_operating",
        "terminal_utilization",
        "renewal_year",
        "exit_year",
        "first_ccs_year",
        "first_material_ccs_year",
        "cumulative_capture_kt",
        "capture_2060_kt_per_year",
        "cumulative_gross_kt",
        "cumulative_net_kt",
        "cumulative_af_ktce_year",
        "cumulative_production_kt",
        "ccs_design_additions_kt_per_year",
        "ccs_design_capacity_years_kt",
        "ccs_portfolio_load_factor",
        "ccs_full_load_equivalent_years",
    ]
    case_columns: dict[str, pd.Series] = {}
    for key in CASE_ORDER:
        if key not in plant_frames:
            continue
        frame = plant_frames[key].set_index("plant_id")
        for field in fields:
            case_columns[f"{key}__{field}"] = output["plant_id"].map(frame[field])
    output = pd.concat(
        [output, pd.DataFrame(case_columns, index=output.index)], axis=1
    ).copy()

    output["full_turnover_differs_from_baseline"] = (
        output["baseline__y_path"].ne(output["treatment_full__y_path"])
        | output["baseline__r_path"].ne(output["treatment_full__r_path"])
    ).astype(int)
    output["full_terminal_added_vs_baseline"] = (
        output["treatment_full__terminal_operating"].gt(0)
        & output["baseline__terminal_operating"].eq(0)
    ).astype(int)
    output["full_terminal_lost_vs_baseline"] = (
        output["treatment_full__terminal_operating"].eq(0)
        & output["baseline__terminal_operating"].gt(0)
    ).astype(int)
    output["fixed_turnover_y_matches_baseline"] = output[
        "treatment_fixed_turnover__y_path"
    ].eq(output["baseline__y_path"]).astype(int)
    output["fixed_turnover_r_matches_baseline"] = output[
        "treatment_fixed_turnover__r_path"
    ].eq(output["baseline__r_path"]).astype(int)
    output["total_capture_effect_kt"] = (
        output["treatment_full__cumulative_capture_kt"]
        - output["baseline__cumulative_capture_kt"]
    )
    output["direct_capture_effect_fixed_turnover_kt"] = (
        output["treatment_fixed_turnover__cumulative_capture_kt"]
        - output["baseline__cumulative_capture_kt"]
    )
    output["turnover_feedback_capture_kt"] = (
        output["treatment_full__cumulative_capture_kt"]
        - output["treatment_fixed_turnover__cumulative_capture_kt"]
    )
    if "treatment_fixed_dispatch" in plant_frames:
        output["fixed_dispatch_y_matches_baseline"] = output[
            "treatment_fixed_dispatch__y_path"
        ].eq(output["baseline__y_path"]).astype(int)
        output["fixed_dispatch_r_matches_baseline"] = output[
            "treatment_fixed_dispatch__r_path"
        ].eq(output["baseline__r_path"]).astype(int)
        output["fixed_dispatch_u_matches_baseline"] = output[
            "treatment_fixed_dispatch__u_path"
        ].eq(output["baseline__u_path"]).astype(int)
        output["pure_direct_capture_effect_fixed_dispatch_kt"] = (
            output["treatment_fixed_dispatch__cumulative_capture_kt"]
            - output["baseline__cumulative_capture_kt"]
        )
        output["dispatch_feedback_capture_kt"] = (
            output["treatment_fixed_turnover__cumulative_capture_kt"]
            - output["treatment_fixed_dispatch__cumulative_capture_kt"]
        )
    if "null_control" in plant_frames:
        output["null_y_matches_baseline"] = output["null_control__y_path"].eq(
            output["baseline__y_path"]
        ).astype(int)
        output["null_r_matches_baseline"] = output["null_control__r_path"].eq(
            output["baseline__r_path"]
        ).astype(int)
    if "reverse_fixed_turnover" in plant_frames:
        output["reverse_turnover_y_matches_treatment_full"] = output[
            "reverse_fixed_turnover__y_path"
        ].eq(output["treatment_full__y_path"]).astype(int)
        output["reverse_turnover_r_matches_treatment_full"] = output[
            "reverse_fixed_turnover__r_path"
        ].eq(output["treatment_full__r_path"]).astype(int)
        output["reverse_turnover_capture_regret_kt"] = (
            output["reverse_fixed_turnover__cumulative_capture_kt"]
            - output["baseline__cumulative_capture_kt"]
        )
    if "reverse_fixed_dispatch" in plant_frames:
        output["reverse_dispatch_y_matches_treatment_full"] = output[
            "reverse_fixed_dispatch__y_path"
        ].eq(output["treatment_full__y_path"]).astype(int)
        output["reverse_dispatch_r_matches_treatment_full"] = output[
            "reverse_fixed_dispatch__r_path"
        ].eq(output["treatment_full__r_path"]).astype(int)
        output["reverse_dispatch_u_matches_treatment_full"] = output[
            "reverse_fixed_dispatch__u_path"
        ].eq(output["treatment_full__u_path"]).astype(int)
        output["reverse_total_capture_regret_kt"] = (
            output["reverse_fixed_dispatch__cumulative_capture_kt"]
            - output["baseline__cumulative_capture_kt"]
        )
        if "reverse_fixed_turnover" in plant_frames:
            output["reverse_dispatch_increment_capture_kt"] = (
                output["reverse_fixed_dispatch__cumulative_capture_kt"]
                - output["reverse_fixed_turnover__cumulative_capture_kt"]
            )
    return output.sort_values("plant_id").reset_index(drop=True)


def build_route_comparison(
    cases: dict[str, Case], route_frames: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    keys = ["plant_id", "storage_idx", "type"]
    all_keys = pd.DataFrame(columns=keys)
    for frame in route_frames.values():
        if not frame.empty:
            all_keys = pd.concat([all_keys, frame[keys]], ignore_index=True)
    all_keys = all_keys.drop_duplicates().sort_values(keys).reset_index(drop=True)
    output = all_keys
    for key in CASE_ORDER:
        if key not in route_frames:
            continue
        frame = route_frames[key].copy()
        rename = {
            "cumulative_flow_kt": f"{key}__cumulative_flow_kt",
            "flow_weighted_distance_km": f"{key}__flow_weighted_distance_km",
        }
        keep = keys + ["cumulative_flow_kt", "flow_weighted_distance_km"]
        output = output.merge(frame[keep].rename(columns=rename), on=keys, how="left")
    flow_columns = [column for column in output if column.endswith("__cumulative_flow_kt")]
    output[flow_columns] = output[flow_columns].fillna(0.0)
    output["total_effect_flow_kt"] = (
        output["treatment_full__cumulative_flow_kt"]
        - output["baseline__cumulative_flow_kt"]
    )
    output["direct_effect_fixed_turnover_flow_kt"] = (
        output["treatment_fixed_turnover__cumulative_flow_kt"]
        - output["baseline__cumulative_flow_kt"]
    )
    output["turnover_feedback_flow_kt"] = (
        output["treatment_full__cumulative_flow_kt"]
        - output["treatment_fixed_turnover__cumulative_flow_kt"]
    )
    output["common_flow_baseline_full_kt"] = output[
        ["baseline__cumulative_flow_kt", "treatment_full__cumulative_flow_kt"]
    ].min(axis=1)
    output["union_flow_baseline_full_kt"] = output[
        ["baseline__cumulative_flow_kt", "treatment_full__cumulative_flow_kt"]
    ].max(axis=1)
    if "treatment_fixed_dispatch" in route_frames:
        output["pure_direct_effect_fixed_dispatch_flow_kt"] = (
            output["treatment_fixed_dispatch__cumulative_flow_kt"]
            - output["baseline__cumulative_flow_kt"]
        )
        output["dispatch_feedback_flow_kt"] = (
            output["treatment_fixed_turnover__cumulative_flow_kt"]
            - output["treatment_fixed_dispatch__cumulative_flow_kt"]
        )
    if "null_control" in route_frames:
        output["null_control_delta_flow_kt"] = (
            output["null_control__cumulative_flow_kt"]
            - output["baseline__cumulative_flow_kt"]
        )
    if "reverse_fixed_turnover" in route_frames:
        output["reverse_turnover_regret_flow_kt"] = (
            output["reverse_fixed_turnover__cumulative_flow_kt"]
            - output["baseline__cumulative_flow_kt"]
        )
    if "reverse_fixed_dispatch" in route_frames:
        output["reverse_total_regret_flow_kt"] = (
            output["reverse_fixed_dispatch__cumulative_flow_kt"]
            - output["baseline__cumulative_flow_kt"]
        )
        if "reverse_fixed_turnover" in route_frames:
            output["reverse_dispatch_increment_flow_kt"] = (
                output["reverse_fixed_dispatch__cumulative_flow_kt"]
                - output["reverse_fixed_turnover__cumulative_flow_kt"]
            )
    return output


def _audit_row(
    rows: list[dict[str, Any]],
    scope: str,
    check_id: str,
    status: str,
    observed: Any,
    expected: Any,
    detail: str = "",
) -> None:
    rows.append(
        {
            "scope": scope,
            "check_id": check_id,
            "status": status,
            "observed": observed,
            "expected": expected,
            "detail": detail,
        }
    )


def audit_case(case: Case, rows: list[dict[str, Any]]) -> None:
    required = [
        "y",
        "r",
        "u",
        "z",
        "k_ccs",
        "ccs_new_design",
        "captured_commercial",
        "co2_gross",
        "co2_net",
    ]
    missing = 0
    nonbinary = 0
    state_violations = 0
    ramp_violations = 0
    ccs_violations = 0
    commitment_violations = 0
    emission_identity_violations = 0
    min_u = _number(
        (case.data.get("model_assumptions", {}) or {}).get(
            "minimum_operating_utilization"
        ),
        0.20,
    )
    max_ramp = _number(
        (case.data.get("model_assumptions", {}) or {}).get(
            "maximum_utilization_change_per_period"
        ),
        0.25,
    )
    commitment_years = int(
        round(
            _number(
                (case.data.get("model_assumptions", {}) or {}).get(
                    "ccs_minimum_operating_years"
                ),
                15.0,
            )
        )
    )
    for plant_id, record in case.plants.items():
        for variable in required:
            mapping = record.get(variable)
            if not isinstance(mapping, dict):
                missing += len(case.years)
                continue
            missing += sum(
                int(str(year) not in mapping and year not in mapping)
                for year in case.years
            )
        y = _series(case, plant_id, "y")
        r = _series(case, plant_id, "r")
        u = _series(case, plant_id, "u")
        z = _series(case, plant_id, "z")
        k = _series(case, plant_id, "k_ccs")
        additions = _series(case, plant_id, "ccs_new_design")
        capture = _series(case, plant_id, "captured_commercial")
        gross = _series(case, plant_id, "co2_gross")
        net = _series(case, plant_id, "co2_net")
        nonbinary += sum(
            abs(value - round(value)) > NUMERIC_TOL
            for mapping in [y, r, z]
            for value in mapping.values()
        )
        state_violations += int(sum(value >= 0.5 for value in r.values()) > 1)
        for idx, year in enumerate(case.years):
            if u[year] < -NUMERIC_TOL or u[year] > y[year] + NUMERIC_TOL:
                state_violations += 1
            if year > case.years[0] and y[year] >= 0.5 and u[year] < min_u - NUMERIC_TOL:
                state_violations += 1
            if z[year] > y[year] + NUMERIC_TOL:
                ccs_violations += 1
            if capture[year] > k[year] + RECONCILIATION_TOL_KT:
                ccs_violations += 1
            if k[year] > NUMERIC_TOL and year > case.years[0]:
                if capture[year] < 0.20 * k[year] - RECONCILIATION_TOL_KT:
                    ccs_violations += 1
            if abs(gross[year] - capture[year] - net[year]) > RECONCILIATION_TOL_KT:
                emission_identity_violations += 1
            if idx > 0:
                prior = case.years[idx - 1]
                if y[year] > y[prior] + r[year] + NUMERIC_TOL:
                    state_violations += 1
                if r[year] > y[prior] + NUMERIC_TOL:
                    state_violations += 1
                if u[year] - u[prior] > max_ramp + (1 - y[prior]) + r[year] + NUMERIC_TOL:
                    ramp_violations += 1
                if u[prior] - u[year] > max_ramp + (1 - y[year]) + NUMERIC_TOL:
                    ramp_violations += 1
                if additions[year] + RECONCILIATION_TOL_KT < k[year] - k[prior]:
                    ccs_violations += 1
                addition = max(k[year] - k[prior], 0.0)
                if addition > NUMERIC_TOL:
                    for future in case.years[idx + 1 :]:
                        if future <= year + commitment_years:
                            if k[future] + RECONCILIATION_TOL_KT < addition:
                                commitment_violations += 1

    _audit_row(rows, case.key, "plant_period_completeness", "PASS" if missing == 0 else "FAIL", missing, 0)
    _audit_row(rows, case.key, "binary_decisions", "PASS" if nonbinary == 0 else "FAIL", nonbinary, 0)
    _audit_row(rows, case.key, "capacity_state_integrity", "PASS" if state_violations == 0 else "FAIL", state_violations, 0)
    _audit_row(rows, case.key, "utilization_ramp_integrity", "PASS" if ramp_violations == 0 else "FAIL", ramp_violations, 0)
    _audit_row(rows, case.key, "ccs_capacity_and_load_integrity", "PASS" if ccs_violations == 0 else "FAIL", ccs_violations, 0)
    _audit_row(rows, case.key, "ccs_minimum_commitment_integrity", "PASS" if commitment_violations == 0 else "FAIL", commitment_violations, 0)
    _audit_row(rows, case.key, "plant_emission_identity", "PASS" if emission_identity_violations == 0 else "FAIL", emission_identity_violations, 0)

    routes = route_frame(case)
    flow_by_plant_year = (
        routes.groupby(["plant_id", "period"])["flow_kt_per_year"].sum().to_dict()
        if not routes.empty
        else {}
    )
    max_flow_gap = 0.0
    for plant_id in case.plants:
        capture = _series(case, plant_id, "captured_commercial")
        for year in case.years:
            max_flow_gap = max(
                max_flow_gap,
                abs(capture[year] - flow_by_plant_year.get((plant_id, year), 0.0)),
            )
    _audit_row(
        rows,
        case.key,
        "plant_flow_capture_balance",
        "PASS" if max_flow_gap <= RECONCILIATION_TOL_KT else "FAIL",
        max_flow_gap,
        f"<={RECONCILIATION_TOL_KT} kt/yr",
    )

    max_capture_gap = 0.0
    max_design_gap = 0.0
    max_gross_gap = 0.0
    max_net_gap = 0.0
    max_demand_gap = 0.0
    max_demand_guard = RECONCILIATION_TOL_KT
    demand_balance_ok = True
    for year in case.years:
        summary = _summary_year(case, year)
        capture = sum(
            _series(case, plant_id, "captured_commercial")[year]
            for plant_id in case.plants
        )
        design = sum(
            _series(case, plant_id, "k_ccs")[year] for plant_id in case.plants
        )
        gross = sum(
            _series(case, plant_id, "co2_gross")[year] for plant_id in case.plants
        )
        net = sum(
            _series(case, plant_id, "co2_net")[year] for plant_id in case.plants
        )
        max_capture_gap = max(
            max_capture_gap,
            abs(capture - _number(summary.get("commercial_captured_co2_kt"), 0.0)),
        )
        max_design_gap = max(
            max_design_gap,
            abs(design - _number(summary.get("ccs_design_capacity_kt"), 0.0)),
        )
        max_gross_gap = max(
            max_gross_gap, abs(gross - _number(summary.get("gross_co2_kt"), 0.0))
        )
        max_net_gap = max(
            max_net_gap, abs(net - _number(summary.get("net_co2_kt"), 0.0))
        )
        demand_gap = abs(_number(summary.get("clinker_balance_gap_kt"), 0.0))
        demand_guard = max(
            RECONCILIATION_TOL_KT,
            abs(_number(summary.get("clinker_demand_kt"), 0.0))
            * REFERENCE_DEMAND_RELATIVE_TOLERANCE,
        )
        max_demand_gap = max(max_demand_gap, demand_gap)
        max_demand_guard = max(max_demand_guard, demand_guard)
        demand_balance_ok = demand_balance_ok and demand_gap <= demand_guard
    max_national_gap = max(max_capture_gap, max_design_gap, max_gross_gap, max_net_gap)
    _audit_row(
        rows,
        case.key,
        "plant_to_national_reconciliation",
        "PASS" if max_national_gap <= RECONCILIATION_TOL_KT else "FAIL",
        max_national_gap,
        f"<={RECONCILIATION_TOL_KT} kt/yr",
        f"capture={max_capture_gap}; design={max_design_gap}; gross={max_gross_gap}; net={max_net_gap}",
    )
    _audit_row(
        rows,
        case.key,
        "clinker_demand_balance",
        "PASS" if demand_balance_ok else "FAIL",
        max_demand_gap,
        (
            f"<=max({RECONCILIATION_TOL_KT} kt/yr, "
            f"{REFERENCE_DEMAND_RELATIVE_TOLERANCE:g} × period demand); "
            f"largest guard={max_demand_guard:.6g} kt/yr"
        ),
    )

    budget = case.data.get("cumulative_budget", {}) or {}
    if bool(budget.get("enabled")):
        actual = _number(budget.get("actual_kt_year"))
        target = _number(budget.get("target_kt_year"))
        terminal = _number(budget.get("terminal_2060_actual_kt"))
        terminal_cap = _number(budget.get("terminal_2060_cap_kt"))
        slack = _number(budget.get("slack_kt_year"), 0.0)
        ok = (
            actual <= target + RECONCILIATION_TOL_KT
            and terminal <= terminal_cap + RECONCILIATION_TOL_KT
            and abs(slack) <= RECONCILIATION_TOL_KT
        )
        _audit_row(
            rows,
            case.key,
            "carbon_budget_and_terminal_cap",
            "PASS" if ok else "FAIL",
            f"actual={actual}; terminal={terminal}; slack={slack}",
            f"actual<=target={target}; terminal<=cap={terminal_cap}; zero slack",
        )

    objective = _solver_value(case, "objective_value")
    cost_total = _number(
        (case.data.get("cost_breakdown_total", {}) or {}).get(
            "discounted_total_kCNY"
        )
    )
    objective_gap = abs(objective - cost_total)
    _audit_row(
        rows,
        case.key,
        "objective_cost_reconciliation",
        "PASS" if objective_gap <= 1e-2 else "FAIL",
        objective_gap,
        "<=0.01 kCNY",
    )
    status = str((case.data.get("solver", {}) or {}).get("status", case.data.get("status", ""))).lower()
    gap = _solver_value(case, "mip_gap")
    if status == "optimal" and gap <= 0.02 + NUMERIC_TOL:
        solver_status = "PASS"
    elif math.isfinite(objective) and math.isfinite(gap) and gap <= 0.05:
        solver_status = "WARN"
    else:
        solver_status = "FAIL"
    _audit_row(
        rows,
        case.key,
        "solver_quality",
        solver_status,
        f"status={status}; gap={gap}",
        "optimal with gap<=0.02",
    )


def audit_cross_case(
    cases: dict[str, Case],
    metadata: pd.DataFrame,
    annual_comparison: pd.DataFrame,
    summary_metrics: pd.DataFrame,
    rows: list[dict[str, Any]],
) -> None:
    baseline = cases["baseline"]
    expected_ids = set(baseline.plants)
    expected_years = baseline.years
    expected_weights = baseline.weights
    for key, case in cases.items():
        _audit_row(
            rows,
            "cross_case",
            f"plant_set__{key}",
            "PASS" if set(case.plants) == expected_ids else "FAIL",
            len(case.plants),
            len(expected_ids),
        )
        _audit_row(
            rows,
            "cross_case",
            f"periods_and_weights__{key}",
            "PASS" if case.years == expected_years and case.weights == expected_weights else "FAIL",
            f"years={case.years}; weights={case.weights}",
            f"years={expected_years}; weights={expected_weights}",
        )
        metadata_match = (
            case.data.get("demand_scenario") == baseline.data.get("demand_scenario")
            and case.data.get("carbon_budget_case")
            == baseline.data.get("carbon_budget_case")
            and case.data.get("cost_boundary") == baseline.data.get("cost_boundary")
        )
        _audit_row(
            rows,
            "cross_case",
            f"planning_boundary__{key}",
            "PASS" if metadata_match else "FAIL",
            f"demand={case.data.get('demand_scenario')}; budget={case.data.get('carbon_budget_case')}; cost={case.data.get('cost_boundary')}",
            f"demand={baseline.data.get('demand_scenario')}; budget={baseline.data.get('carbon_budget_case')}; cost={baseline.data.get('cost_boundary')}",
        )

    metadata_ids = set(metadata["plant_id"].astype(int)) if not metadata.empty else set()
    missing_capacity = sorted(expected_ids - metadata_ids)
    if metadata.empty:
        invalid_capacity = len(expected_ids)
    else:
        modeled_capacity = metadata.loc[
            metadata["plant_id"].isin(expected_ids), "capacity_t_day"
        ]
        invalid_capacity = int(
            modeled_capacity.map(
                lambda value: (
                    not math.isfinite(_number(value)) or _number(value) <= 0.0
                )
            ).sum()
        )
    _audit_row(
        rows,
        "cross_case",
        "plant_capacity_metadata_coverage",
        "PASS" if not missing_capacity and invalid_capacity == 0 else "FAIL",
        f"missing_ids={len(missing_capacity)}; invalid_capacity={invalid_capacity}",
        "complete positive-capacity metadata for every modeled plant",
        f"sample_missing={missing_capacity[:10]}",
    )

    treatment_full = cases["treatment_full"]
    full_adjustments = treatment_full.data.get("scenario_adjustments", {}) or {}
    full_equalized = bool(
        full_adjustments.get("_af_spatial_equalized")
        or (treatment_full.data.get("model_assumptions", {}) or {}).get(
            "af_spatial_equalized"
        )
    )
    _audit_row(
        rows,
        "cross_case",
        "treatment_is_equalized_S3",
        "PASS" if full_equalized else "FAIL",
        full_equalized,
        True,
    )
    for key in ["treatment_fixed_turnover", "treatment_fixed_dispatch"]:
        if key not in cases:
            continue
        case = cases[key]
        adjustments = case.data.get("scenario_adjustments", {}) or {}
        same_environment = (
            case.data.get("scenario") == treatment_full.data.get("scenario")
            and adjustments == full_adjustments
        )
        _audit_row(
            rows,
            "cross_case",
            f"same_treatment_environment__{key}",
            "PASS" if same_environment else "FAIL",
            f"scenario={case.data.get('scenario')}; adjustments={adjustments}",
            f"scenario={treatment_full.data.get('scenario')}; adjustments={full_adjustments}",
        )

    baseline_adjustments = baseline.data.get("scenario_adjustments", {}) or {}
    for key in ["reverse_fixed_turnover", "reverse_fixed_dispatch"]:
        if key not in cases:
            continue
        case = cases[key]
        adjustments = case.data.get("scenario_adjustments", {}) or {}
        same_environment = (
            case.data.get("scenario") == baseline.data.get("scenario")
            and adjustments == baseline_adjustments
        )
        _audit_row(
            rows,
            "cross_case",
            f"same_reverse_environment__{key}",
            "PASS" if same_environment else "FAIL",
            f"scenario={case.data.get('scenario')}; adjustments={adjustments}",
            f"scenario={baseline.data.get('scenario')}; adjustments={baseline_adjustments}",
        )

    def fixed_integrity(
        case_key: str, source_key: str, variables: list[str]
    ) -> None:
        case = cases[case_key]
        source = cases[source_key]
        mismatches = {
            variable: sum(
                abs(
                    _series(case, plant_id, variable)[year]
                    - _series(source, plant_id, variable)[year]
                )
                > (FIXED_U_TOLERANCE if variable == "u" else NUMERIC_TOL)
                for plant_id in expected_ids
                for year in expected_years
            )
            for variable in variables
        }
        _audit_row(
            rows,
            "fixed_path",
            f"fixed_values_match_{source_key}__{case_key}",
            "PASS" if sum(mismatches.values()) == 0 else "FAIL",
            mismatches,
            {variable: 0 for variable in variables},
        )
        metadata_block = case.data.get("capacity_path_counterfactual", {}) or {}
        fixed_declared = set(metadata_block.get("fixed_variables", []))
        bounded_declared = set(metadata_block.get("bounded_variables", []))
        exact_required = set(variables) - {"u"}
        dispatch_required = (
            "u" not in variables
            or "u" in bounded_declared
            or "u" in fixed_declared
        )
        metadata_ok = (
            bool(metadata_block.get("enabled"))
            and exact_required.issubset(fixed_declared)
            and dispatch_required
        )
        _audit_row(
            rows,
            "fixed_path",
            f"fixed_path_metadata__{case_key}",
            "PASS" if metadata_ok else "WARN",
            metadata_block,
            "y/r exactly fixed and u declared as bounded when dispatch is imposed",
            "Exact y/r equality plus the shared dispatch-band tolerance is authoritative.",
        )
        source_hash = metadata_block.get("source_sha256")
        if source_hash:
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
        null_case = cases["null_control"]
        same_null_environment = (
            null_case.data.get("scenario") == baseline.data.get("scenario")
            and (null_case.data.get("scenario_adjustments", {}) or {})
            == (baseline.data.get("scenario_adjustments", {}) or {})
        )
        _audit_row(
            rows,
            "cross_case",
            "null_control_same_environment",
            "PASS" if same_null_environment else "FAIL",
            f"scenario={null_case.data.get('scenario')}; adjustments={null_case.data.get('scenario_adjustments')}",
            f"scenario={baseline.data.get('scenario')}; adjustments={baseline.data.get('scenario_adjustments')}",
        )
    if "reverse_fixed_turnover" in cases:
        fixed_integrity(
            "reverse_fixed_turnover", "treatment_full", ["y", "r"]
        )
    if "reverse_fixed_dispatch" in cases:
        fixed_integrity(
            "reverse_fixed_dispatch", "treatment_full", ["y", "r", "u"]
        )

    base_year = expected_years[0]
    for key, case in cases.items():
        max_u_gap = max(
            abs(
                _series(case, plant_id, "u")[base_year]
                - _series(baseline, plant_id, "u")[base_year]
            )
            for plant_id in expected_ids
        )
        max_capture_gap = max(
            abs(
                _series(case, plant_id, "captured_commercial")[base_year]
                - _series(baseline, plant_id, "captured_commercial")[base_year]
            )
            for plant_id in expected_ids
        )
        _audit_row(
            rows,
            "cross_case",
            f"shared_2025_anchor__{key}",
            "PASS" if max(max_u_gap, max_capture_gap) <= RECONCILIATION_TOL_KT else "FAIL",
            f"max_u_gap={max_u_gap}; max_capture_gap={max_capture_gap}",
            "identical base-year utilization and commercial capture",
        )

    max_two_level = float(annual_comparison["two_level_decomposition_residual"].abs().max())
    max_three_level = (
        float(annual_comparison["three_level_decomposition_residual"].abs().max())
        if "treatment_fixed_dispatch" in cases
        else math.nan
    )
    max_reverse = (
        float(annual_comparison["reverse_decomposition_residual"].abs().max())
        if "reverse_fixed_turnover" in cases
        and "reverse_fixed_dispatch" in cases
        else math.nan
    )
    decomposition_ok = max_two_level <= 1e-9 and (
        not math.isfinite(max_three_level) or max_three_level <= 1e-9
    ) and (not math.isfinite(max_reverse) or max_reverse <= 1e-9)
    _audit_row(
        rows,
        "decomposition",
        "nested_decomposition_identity",
        "PASS" if decomposition_ok else "FAIL",
        f"two_level={max_two_level}; three_level={max_three_level}; reverse={max_reverse}",
        "<=1e-9",
    )

    def feasible_subset_check(fixed_key: str, flexible_key: str) -> None:
        fixed_ub = _solver_value(cases[fixed_key], "objective_value")
        flexible_lb = _solver_value(cases[flexible_key], "objective_bound")
        impossible = fixed_ub + 1e-2 < flexible_lb
        _audit_row(
            rows,
            "solver_bounds",
            f"nested_feasible_set_order__{fixed_key}_vs_{flexible_key}",
            "FAIL" if impossible else "PASS",
            f"fixed_UB={fixed_ub}; flexible_LB={flexible_lb}",
            "fixed feasible-set incumbent must not beat flexible lower bound",
        )

    feasible_subset_check("treatment_fixed_turnover", "treatment_full")
    if "treatment_fixed_dispatch" in cases:
        feasible_subset_check(
            "treatment_fixed_dispatch", "treatment_fixed_turnover"
        )
    if "null_control" in cases:
        feasible_subset_check("null_control", "baseline")
    if "reverse_fixed_turnover" in cases:
        feasible_subset_check("reverse_fixed_turnover", "baseline")
    if "reverse_fixed_dispatch" in cases:
        feasible_subset_check("reverse_fixed_dispatch", "baseline")
        if "reverse_fixed_turnover" in cases:
            feasible_subset_check(
                "reverse_fixed_dispatch", "reverse_fixed_turnover"
            )


def render_report(
    cases: dict[str, Case],
    summary: pd.DataFrame,
    audits: pd.DataFrame,
    survivor_sorting: pd.DataFrame | None = None,
) -> str:
    def metric(name: str, field: str = "comparison_value") -> float:
        rows = summary.loc[summary["metric"].eq(name)]
        return _number(rows.iloc[0][field]) if not rows.empty else math.nan

    def scenario_metric(name: str, case_field: str) -> float:
        rows = summary.loc[summary["metric"].eq(name)]
        return _number(rows.iloc[0][case_field]) if not rows.empty else math.nan

    def fmt(value: float, digits: int = 3) -> str:
        return f"{value:.{digits}f}" if math.isfinite(value) else "n/a"

    audit_counts = audits["status"].value_counts().to_dict()
    regret = metric(
        "turnover_lockin_regret__fixed_turnover_vs_full_treatment"
    )
    regret_lower = metric(
        "turnover_lockin_regret__fixed_turnover_vs_full_treatment",
        "comparison_lower_bound",
    )
    regret_upper = metric(
        "turnover_lockin_regret__fixed_turnover_vs_full_treatment",
        "comparison_upper_bound",
    )
    cost_total = scenario_metric(
        "objective_incumbent", "total_effect_full_minus_baseline"
    )
    cost_direct = scenario_metric(
        "objective_incumbent", "direct_effect_fixed_turnover_minus_baseline"
    )
    cost_feedback = scenario_metric(
        "objective_incumbent", "turnover_feedback_full_minus_fixed_turnover"
    )
    capture_total = scenario_metric(
        "cumulative_capture", "total_effect_full_minus_baseline"
    )
    capture_direct = scenario_metric(
        "cumulative_capture", "direct_effect_fixed_turnover_minus_baseline"
    )
    capture_feedback = scenario_metric(
        "cumulative_capture", "turnover_feedback_full_minus_fixed_turnover"
    )
    lines = [
        "# Capacity-feedback counterfactual",
        "",
        "## Design",
        "",
        "The fully coupled S3 result is compared with S3 re-optimized after fixing "
        "the S1 plant-operation and same-site-renewal path. The difference between "
        "full S3 and fixed-turnover S3 is the turnover-feedback component; the "
        "difference between fixed-turnover S3 and S1 is the response available "
        "without changing asset survival. Reverse-sequential cases impose the "
        "fully coupled S3 asset plan under actual S1 conditions and compare it "
        "with jointly optimized S1.",
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
            f"{case.data.get('demand_scenario')} | {case.data.get('carbon_budget_case')} | "
            f"{fmt(_solver_value(case, 'mip_gap'), 4)} | `{case.sha256[:12]}` |"
        )
    lines.extend(
        [
            "",
            "## Main findings",
            "",
            f"- The full S3 cost effect relative to S1 is {fmt(cost_total)} billion CNY. "
            f"The fixed-turnover component is {fmt(cost_direct)} billion CNY and the "
            f"turnover-feedback component is {fmt(cost_feedback)} billion CNY.",
            f"- The corresponding cumulative-capture effects are {fmt(capture_total)} GtCO2 "
            f"in total, {fmt(capture_direct)} GtCO2 without turnover adjustment, and "
            f"{fmt(capture_feedback)} GtCO2 from turnover feedback.",
            f"- Capacity-path overlap between S1 and full S3 is "
            f"{fmt(metric('capacity_path_jaccard__baseline_vs_treatment_full'), 3)}; "
            f"capture-weighted overlap between full and fixed-turnover S3 is "
            f"{fmt(metric('capture_weighted_jaccard__treatment_full_vs_treatment_fixed_turnover'), 3)}; "
            f"route-flow overlap is "
            f"{fmt(metric('route_flow_weighted_jaccard__treatment_full_vs_treatment_fixed_turnover'), 3)}.",
            f"- Turnover lock-in regret is {fmt(regret)} billion CNY. Its solver-bound-aware "
            f"interval is [{fmt(regret_lower)}, {fmt(regret_upper)}] billion CNY.",
        ]
    )
    if regret_lower > 0:
        lines.append(
            "- The lower regret bound is positive, so the cost of retaining the S1 turnover "
            "path under S3 is established beyond the current solver gaps."
        )
    else:
        lines.append(
            "- The regret interval includes zero; treat the point estimate as directional "
            "until the paired solves are tightened."
        )
    if "treatment_fixed_dispatch" in cases:
        dispatch = metric(
            "dispatch_lockin_regret__fixed_dispatch_vs_fixed_turnover"
        )
        dispatch_lower = metric(
            "dispatch_lockin_regret__fixed_dispatch_vs_fixed_turnover",
            "comparison_lower_bound",
        )
        dispatch_upper = metric(
            "dispatch_lockin_regret__fixed_dispatch_vs_fixed_turnover",
            "comparison_upper_bound",
        )
        lines.append(
            f"- Fixing dispatch as well adds {fmt(dispatch)} billion CNY of point regret "
            f"relative to turnover-only fixing, with bounds [{fmt(dispatch_lower)}, "
            f"{fmt(dispatch_upper)}]."
        )
    if "null_control" in cases:
        null = metric("null_control_lockin_regret")
        null_lower = metric("null_control_lockin_regret", "comparison_lower_bound")
        null_upper = metric("null_control_lockin_regret", "comparison_upper_bound")
        lines.append(
            f"- The null-control regret is {fmt(null)} billion CNY with bounds "
            f"[{fmt(null_lower)}, {fmt(null_upper)}]; use this as the numerical-noise benchmark."
        )
    if "reverse_fixed_turnover" in cases:
        reverse_designated = metric(
            "reverse_turnover_sequential_regret_designated_run__s3_plan_under_s1_vs_joint_s1"
        )
        reverse = metric(
            "reverse_turnover_sequential_regret__s3_plan_under_s1_vs_joint_s1"
        )
        best_joint_s1 = metric(
            "joint_s1_best_known_incumbent_for_reverse_regret"
        )
        reverse_lower = metric(
            "reverse_turnover_sequential_regret__s3_plan_under_s1_vs_joint_s1",
            "comparison_lower_bound",
        )
        reverse_upper = metric(
            "reverse_turnover_sequential_regret__s3_plan_under_s1_vs_joint_s1",
            "comparison_upper_bound",
        )
        reverse_capture_overlap = metric(
            "capture_weighted_jaccard__treatment_full_vs_reverse_fixed_turnover"
        )
        reverse_route_overlap = metric(
            "route_flow_weighted_jaccard__treatment_full_vs_reverse_fixed_turnover"
        )
        lines.append(
            f"- In the reverse test, the designated-run incumbent difference for using "
            f"the S3 turnover plan under actual S1 conditions is "
            f"{fmt(reverse_designated)} billion CNY. Using the best same-environment "
            f"feasible joint-S1 incumbent ({fmt(best_joint_s1)} billion CNY) gives a "
            f"best-known difference of {fmt(reverse)} billion CNY and regret bounds "
            f"[{fmt(reverse_lower)}, {fmt(reverse_upper)}]. Capture and route "
            f"overlaps with the source S3 solution are {fmt(reverse_capture_overlap)} "
            f"and {fmt(reverse_route_overlap)}, respectively."
        )
        if reverse_lower > 0:
            lines.append(
                "- The reverse lower bound is positive: the S3 asset plan is "
                "demonstrably suboptimal when transferred back to heterogeneous S1 conditions."
            )
    if "reverse_fixed_dispatch" in cases:
        reverse_total_designated = metric(
            "reverse_total_sequential_regret_designated_run__s3_plan_and_dispatch_under_s1_vs_joint_s1"
        )
        reverse_total = metric(
            "reverse_total_sequential_regret__s3_plan_and_dispatch_under_s1_vs_joint_s1"
        )
        reverse_total_lower = metric(
            "reverse_total_sequential_regret__s3_plan_and_dispatch_under_s1_vs_joint_s1",
            "comparison_lower_bound",
        )
        reverse_total_upper = metric(
            "reverse_total_sequential_regret__s3_plan_and_dispatch_under_s1_vs_joint_s1",
            "comparison_upper_bound",
        )
        lines.append(
            f"- Fixing the S3 dispatch as well gives a designated-run difference of "
            f"{fmt(reverse_total_designated)} billion CNY and a best-known reverse "
            f"total regret of {fmt(reverse_total)} billion CNY, with bounds "
            f"[{fmt(reverse_total_lower)}, {fmt(reverse_total_upper)}]."
        )
    sorting_fields = {
        "group",
        "plants",
        "af_resource_mean",
        "nearest_storage_distance_mean_km",
    }
    if (
        survivor_sorting is not None
        and sorting_fields.issubset(survivor_sorting.columns)
    ):
        indexed_sorting = survivor_sorting.set_index("group")
        if {
            "gained_after_equalization",
            "lost_after_equalization",
        }.issubset(indexed_sorting.index):
            gained = indexed_sorting.loc["gained_after_equalization"]
            lost = indexed_sorting.loc["lost_after_equalization"]
            lines.append(
                f"- Strict 2060 survivor sorting identifies {int(gained['plants'])} "
                f"plants gained and {int(lost['plants'])} lost after equalization. "
                f"Gained plants have a lower mean original AF-resource index "
                f"({fmt(_number(gained['af_resource_mean']))} vs "
                f"{fmt(_number(lost['af_resource_mean']))}) but are markedly closer "
                f"to storage ({fmt(_number(gained['nearest_storage_distance_mean_km']), 1)} "
                f"vs {fmt(_number(lost['nearest_storage_distance_mean_km']), 1)} km)."
            )
    lines.extend(
        [
            "",
            "## Audit",
            "",
            f"PASS={audit_counts.get('PASS', 0)}, WARN={audit_counts.get('WARN', 0)}, "
            f"FAIL={audit_counts.get('FAIL', 0)}.",
            "",
            "The CCS service-year statistics are horizon-observed measures. Investments "
            "committed beyond 2060 are right-censored and should not be interpreted as full "
            "physical asset lifetimes.",
            "",
            "Detailed evidence is in `summary_metrics.csv`, `annual_comparison.csv`, "
            "`plant_comparison.csv`, `route_comparison.csv`, and `audit_checks.csv`.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-json", required=True, type=Path)
    parser.add_argument("--treatment-full-json", required=True, type=Path)
    parser.add_argument("--treatment-fixed-turnover-json", required=True, type=Path)
    parser.add_argument("--treatment-fixed-dispatch-json", type=Path)
    parser.add_argument("--null-control-json", type=Path)
    parser.add_argument("--reverse-fixed-turnover-json", type=Path)
    parser.add_argument("--reverse-fixed-dispatch-json", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--plant-metadata",
        type=Path,
        default=DEFAULT_PLANT_METADATA,
        help=(
            "Plant metadata used only for nameplate-capacity weighting and "
            "capacity-to-production conversion."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    survivor_sorting_path = output_dir / "terminal_survivor_sorting.csv"
    survivor_sorting = (
        pd.read_csv(survivor_sorting_path)
        if survivor_sorting_path.is_file()
        else None
    )
    paths = {
        "baseline": args.baseline_json,
        "treatment_full": args.treatment_full_json,
        "treatment_fixed_turnover": args.treatment_fixed_turnover_json,
    }
    if args.treatment_fixed_dispatch_json:
        paths["treatment_fixed_dispatch"] = args.treatment_fixed_dispatch_json
    if args.null_control_json:
        paths["null_control"] = args.null_control_json
    if args.reverse_fixed_turnover_json:
        paths["reverse_fixed_turnover"] = args.reverse_fixed_turnover_json
    if args.reverse_fixed_dispatch_json:
        paths["reverse_fixed_dispatch"] = args.reverse_fixed_dispatch_json

    cases = {key: load_case(path, key) for key, path in paths.items()}
    metadata = load_plant_metadata(args.plant_metadata)
    capacity_map = (
        metadata.set_index("plant_id")["capacity_t_day"].to_dict()
        if not metadata.empty
        else {}
    )
    plant_frames = {
        key: plant_case_frame(case, metadata) for key, case in cases.items()
    }
    route_frames = {
        key: cumulative_route_frame(case) for key, case in cases.items()
    }
    annual_frames = {
        key: annual_case_frame(case, metadata) for key, case in cases.items()
    }
    scalar_metrics = {
        key: scalar_case_metrics(
            case, annual_frames[key], plant_frames[key], route_frames[key]
        )
        for key, case in cases.items()
    }

    annual_comparison = build_annual_comparison(cases, annual_frames)
    summary_metrics = build_summary_metrics(
        cases, scalar_metrics, plant_frames, route_frames, capacity_map
    )
    plant_comparison = build_plant_comparison(cases, plant_frames)
    route_comparison = build_route_comparison(cases, route_frames)

    audit_rows: list[dict[str, Any]] = []
    for case in cases.values():
        audit_case(case, audit_rows)
    audit_cross_case(
        cases,
        metadata,
        annual_comparison,
        summary_metrics,
        audit_rows,
    )
    audits = pd.DataFrame(audit_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_metrics.to_csv(output_dir / "summary_metrics.csv", index=False)
    annual_comparison.to_csv(output_dir / "annual_comparison.csv", index=False)
    plant_comparison.to_csv(output_dir / "plant_comparison.csv", index=False)
    route_comparison.to_csv(output_dir / "route_comparison.csv", index=False)
    audits.to_csv(output_dir / "audit_checks.csv", index=False)
    (output_dir / "report.md").write_text(
        render_report(
            cases,
            summary_metrics,
            audits,
            survivor_sorting=survivor_sorting,
        ),
        encoding="utf-8",
    )

    failures = int(audits["status"].eq("FAIL").sum())
    print(
        f"Wrote nested counterfactual analysis to {output_dir} "
        f"(PASS={audits['status'].eq('PASS').sum()}, "
        f"WARN={audits['status'].eq('WARN').sum()}, FAIL={failures})"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
