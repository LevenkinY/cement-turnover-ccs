#!/usr/bin/env python3
"""Prepare auditable source data for Applied Energy main Figs. 2--7.

This is a post-processing script only.  It reads the corrected and frozen
2026-08-22 canonical results, utilization sensitivity package and the
bounded-endpoint corridor package.  It never solves or modifies the model.

The outputs deliberately distinguish exact plant--storage routes from
bounded-endpoint corridor-opportunity families, core scenarios from the
representative near-optimal solutions, and full-period exposure from the
late turnover margin.
"""

from __future__ import annotations

import json
import hashlib
import math
import sys
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "results/v4/final_verified_inputs_20260829"
STORY = ROOT / "results/v4/writing_ready_storyline_v3_20260829"
CORRIDORS = ROOT / "results/v4/postprocess_robust_corridors_bounded_endpoints_20260829"
UTIL = ROOT / "results/v4/min_utilization_verified_inputs_20260829"
SOURCE = ROOT / "paper/applied_energy_2026/submission/source_data_verified_20260829"

MODEL_ROOT = ROOT / "models/v4"
sys.path.insert(0, str(MODEL_ROOT))

from src_v4 import config_v4 as cfg  # noqa: E402
from src_v4.data_loader_v4 import load_all  # noqa: E402


YEARS = (2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060)
WINDOWS = {
    "Full period": set(YEARS),
    "Early (2025--2045)": {2025, 2030, 2035, 2040, 2045},
    "Late (2050--2060)": {2050, 2055, 2060},
}
WINDOW_FILE_LABELS = {
    "Full period": "full_2025_2060",
    "Early (2025--2045)": "early_2025_2045",
    "Late (2050--2060)": "late_2050_2060",
}

CORE_PATHS = {
    "S1": RUNS / "full/S1_baseline_results.json",
    "S2": RUNS / "full/S3_all_spatial_equalized_results.json",
    "S3": RUNS / "full/S5_offshore_parity_results.json",
    "S4": RUNS / "demand/d_high/S1_baseline_results.json",
    "S5": RUNS / "demand/d_low/S1_baseline_results.json",
}
NEAR_PATHS = {
    "S1-near-terminal": RUNS
    / "near_optimal/s1_farthest_terminal_e0010/S1_baseline_results.json",
    "S1-near-full": RUNS
    / "near_optimal/s1_farthest_full_e0010/S1_baseline_results.json",
    "S2-near-terminal": RUNS
    / "near_optimal/s2_closest_terminal_e0010/S3_all_spatial_equalized_results.json",
    "S3-near-terminal": RUNS
    / "near_optimal/s3_closest_terminal_e0010/S5_offshore_parity_results.json",
}
CASE_SETS = {
    "Core scenarios": list(CORE_PATHS),
    "Core + near-optimal": [*CORE_PATHS, *NEAR_PATHS],
}

ALBERS = (
    "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 "
    "+datum=WGS84 +units=m +no_defs"
)
FLOW_TOL_MT = 1e-9
CAPACITY_TO_MT_YEAR = 330.0 / 1_000_000.0
LIFETIME_YEARS = 40
CORRIDOR_FLOW_FLOOR_MT = 10.0


def _normalize_province_name(value: Any) -> str:
    text = str(value)
    for suffix in ("壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "特别行政区", "省", "市"):
        text = text.replace(suffix, "")
    return text


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _value(mapping: Any, year: int, default: float = 0.0) -> float:
    if not isinstance(mapping, dict):
        return default
    value = mapping.get(str(year), mapping.get(year, default))
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _weighted_jaccard(left: dict[Any, float], right: dict[Any, float]) -> float:
    keys = set(left) | set(right)
    common = sum(min(left.get(k, 0.0), right.get(k, 0.0)) for k in keys)
    union = sum(max(left.get(k, 0.0), right.get(k, 0.0)) for k in keys)
    return common / union if union > 0 else np.nan


def _routes(case: str, data: dict[str, Any]) -> pd.DataFrame:
    weights = {int(k): float(v) for k, v in data["period_weights_years"].items()}
    rows: list[dict[str, Any]] = []
    for year_key, records in data.get("co2_flow_routes", {}).items():
        year = int(year_key)
        for record in records:
            flow_kt_yr = float(record.get("flow_kt", 0.0))
            if flow_kt_yr <= 1e-6:
                continue
            rows.append(
                {
                    "case": case,
                    "year": year,
                    "plant_id": int(record["plant_id"]),
                    "storage_idx": int(record["storage_idx"]),
                    "route_type": str(
                        record.get("type", record.get("storage_type", ""))
                    ).upper(),
                    "flow_mt": flow_kt_yr * weights[year] / 1000.0,
                }
            )
    return pd.DataFrame(rows)


def _terminal_set(data: dict[str, Any]) -> set[int]:
    return {
        int(plant_id)
        for plant_id, row in data["plants"].items()
        if _value(row.get("y", {}), 2060) > 0.5
    }


def _feature_tables(model_data: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    plants = model_data["plants"][["plant_id", "province", "capacity"]].copy()
    plants["plant_id"] = plants["plant_id"].astype(int)
    plants["annual_capacity_kt"] = plants["capacity"] * cfg.CAPACITY_T_DAY_TO_KT_YR
    province_capacity = plants.groupby("province")["annual_capacity_kt"].sum()
    terminal_tsr = min(cfg.AF_MAX_PER_PLANT, cfg.AF_ENGINEERING_TSR_PATH[2060])

    resource_rows = []
    storage = model_data["storage"].set_index("storage_idx")
    for row in plants.itertuples(index=False):
        plant_denominator = (
            row.annual_capacity_kt * cfg.TCE_PER_T_CLINKER * terminal_tsr
        )
        province_denominator = (
            province_capacity.loc[row.province]
            * cfg.TCE_PER_T_CLINKER
            * terminal_tsr
        )
        access = float(model_data["plant_af_access_ktce"][(row.plant_id, 2060)])
        pool = float(model_data["province_af_pool_ktce"][(row.province, 2060)])
        catchment = access / plant_denominator if plant_denominator else 0.0
        pool_coverage = pool / province_denominator if province_denominator else 0.0
        routes = model_data["plant_storage"].get(row.plant_id, [])
        if routes:
            sink, distance, route_type = min(routes, key=lambda item: item[1])
            sink_row = storage.loc[int(sink)]
            nearest_distance = float(distance)
            nearest_type = str(route_type).upper()
            nearest_offshore = bool(sink_row.get("is_offshore", False))
        else:
            nearest_distance = np.nan
            nearest_type = "NONE"
            nearest_offshore = False
        resource_rows.append(
            {
                "plant_id": row.plant_id,
                "af_resource_index": min(catchment, pool_coverage, 1.0),
                "af_access_2060_ktce": access,
                "af_province_pool_2060_ktce": pool,
                "nearest_storage_distance_km": nearest_distance,
                "nearest_storage_type": nearest_type,
                "nearest_storage_offshore": nearest_offshore,
            }
        )

    storage_out = model_data["storage"].copy()
    storage_out["storage_idx"] = storage_out["storage_idx"].astype(int)
    return pd.DataFrame(resource_rows), storage_out


def _axial_round(q: float, r: float) -> tuple[int, int]:
    x, z = q, r
    y = -x - z
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return int(rx), int(rz)


def _hex_grid(plants: pd.DataFrame, radius_m: float = 50_000.0) -> pd.DataFrame:
    points = gpd.GeoDataFrame(
        plants[["plant_id", "af_resource_index"]].copy(),
        geometry=gpd.points_from_xy(plants["longitude"], plants["latitude"]),
        crs="EPSG:4326",
    ).to_crs(ALBERS)
    rows = []
    for row in points.itertuples(index=False):
        x, y = row.geometry.x, row.geometry.y
        qf = (math.sqrt(3.0) / 3.0 * x - y / 3.0) / radius_m
        rf = (2.0 / 3.0 * y) / radius_m
        q, r = _axial_round(qf, rf)
        rows.append(
            {
                "plant_id": int(row.plant_id),
                "q": q,
                "r": r,
                "af_resource_index": float(row.af_resource_index),
            }
        )
    assigned = pd.DataFrame(rows)
    grid = (
        assigned.groupby(["q", "r"], as_index=False)
        .agg(
            plant_count=("plant_id", "size"),
            af_resource_median=("af_resource_index", "median"),
            af_resource_mean=("af_resource_index", "mean"),
        )
    )
    grid["center_x"] = radius_m * math.sqrt(3.0) * (grid["q"] + grid["r"] / 2.0)
    grid["center_y"] = radius_m * 1.5 * grid["r"]
    grid["hex_radius_m"] = radius_m
    grid["hex_definition"] = "fixed 100-km vertex-to-vertex cell in China Albers equal-area"
    return grid


def _prepare_fig2(core: dict[str, dict[str, Any]], plants: pd.DataFrame) -> None:
    annual = pd.read_csv(STORY / "annual_system_evolution.csv")
    piv = annual.pivot(index="year", columns="case")
    system = pd.DataFrame(
        {
            "year": YEARS,
            "demand_d_low_mt": [piv.loc[y, ("cement_demand_mt", "S5")] for y in YEARS],
            "demand_d_medium_mt": [piv.loc[y, ("cement_demand_mt", "S1")] for y in YEARS],
            "demand_d_high_mt": [piv.loc[y, ("cement_demand_mt", "S4")] for y in YEARS],
            "clinker_d_low_mt": [piv.loc[y, ("clinker_production_mt", "S5")] for y in YEARS],
            "clinker_s1_mt": [piv.loc[y, ("clinker_production_mt", "S1")] for y in YEARS],
            "clinker_d_high_mt": [piv.loc[y, ("clinker_production_mt", "S4")] for y in YEARS],
            "capacity_d_low_mt_y": [piv.loc[y, ("operating_capacity_mt_per_year", "S5")] for y in YEARS],
            "capacity_s1_mt_y": [piv.loc[y, ("operating_capacity_mt_per_year", "S1")] for y in YEARS],
            "capacity_d_high_mt_y": [piv.loc[y, ("operating_capacity_mt_per_year", "S4")] for y in YEARS],
        }
    )
    system.to_csv(SOURCE / "fig2_system_envelope_v2.csv", index=False)

    meta = plants.set_index("plant_id")
    s1 = core["S1"]
    event = {
        year: {
            "early_exit_capacity_mt_y": 0.0,
            "natural_retirement_capacity_mt_y": 0.0,
            "renewal_capacity_mt_y": 0.0,
        }
        for year in YEARS
    }
    for pid_key, row in s1["plants"].items():
        pid = int(pid_key)
        capacity = float(meta.loc[pid, "capacity_t_day"]) * CAPACITY_TO_MT_YEAR
        commission_year = int(meta.loc[pid, "commission_year"])
        due = next((year for year in YEARS if year - commission_year > LIFETIME_YEARS), None)
        for year in YEARS:
            if _value(row.get("close", {}), year) > 0.5:
                key = (
                    "natural_retirement_capacity_mt_y"
                    if due is not None and year >= due
                    else "early_exit_capacity_mt_y"
                )
                event[year][key] += capacity
            if _value(row.get("r", {}), year) > 0.5:
                event[year]["renewal_capacity_mt_y"] += capacity

    terminal = _terminal_set(s1)
    rows = []
    for year in YEARS:
        inherited_backbone = 0.0
        renewed_backbone = 0.0
        nonterminal = 0.0
        new_capture_site_count = 0
        for pid_key, row in s1["plants"].items():
            value = _value(row.get("captured_commercial", {}), year) / 1000.0
            previous_year = YEARS[YEARS.index(year) - 1] if year != YEARS[0] else None
            previous_value = (
                _value(row.get("captured_commercial", {}), previous_year) / 1000.0
                if previous_year is not None
                else 0.0
            )
            if value > 1e-12 and previous_value <= 1e-12:
                new_capture_site_count += 1
            renewed_by_year = any(
                _value(row.get("r", {}), event_year) > 0.5
                for event_year in YEARS
                if event_year <= year
            )
            if int(pid_key) in terminal and renewed_by_year:
                renewed_backbone += value
            elif int(pid_key) in terminal:
                inherited_backbone += value
            else:
                nonterminal += value
        s4_capture = float(piv.loc[year, ("captured_co2_mt", "S4")])
        s5_capture = float(piv.loc[year, ("captured_co2_mt", "S5")])
        rows.append(
            {
                "year": year,
                **event[year],
                "terminal_inherited_phase_capture_mt_y": inherited_backbone,
                "terminal_renewed_phase_capture_mt_y": renewed_backbone,
                "nonterminal_capture_mt_y": nonterminal,
                "total_capture_mt_y": inherited_backbone + renewed_backbone + nonterminal,
                "capture_s4_slow_mt_y": s4_capture,
                "capture_s5_deep_mt_y": s5_capture,
                "capture_demand_range_low_mt_y": min(s4_capture, s5_capture),
                "capture_demand_range_high_mt_y": max(s4_capture, s5_capture),
                "new_capture_site_count": new_capture_site_count,
                "terminal_set_definition": "S1 sites operating in 2060",
                "renewed_phase_definition": "at least one same-site renewal by the plotted year",
            }
        )
    pd.DataFrame(rows).to_csv(SOURCE / "fig2_turnover_capture_v2.csv", index=False)


def _prepare_fig3_and_fig5(
    features: pd.DataFrame,
    storage: pd.DataFrame,
    plants: pd.DataFrame,
) -> None:
    matrix = pd.read_csv(STORY / "plant_decision_matrix.csv")
    capture_cols = [f"cumulative_capture_mt_{case}" for case in CORE_PATHS]
    matrix["mean_cumulative_capture_mt"] = matrix[capture_cols].mean(axis=1)
    spatial = matrix.merge(features, on="plant_id", how="left", validate="one_to_one")
    spatial["survival_frequency"] = spatial["terminal_scenario_count"] / len(CORE_PATHS)
    spatial.to_csv(SOURCE / "fig3_spatial_assets_v2.csv", index=False)
    _hex_grid(spatial).to_csv(SOURCE / "fig3_af_hex_v2.csv", index=False)

    eligible_storage = storage[
        storage["has_dsa"].astype(bool) | storage["has_eor"].astype(bool)
    ].copy()
    eligible_storage.to_csv(SOURCE / "fig3_storage_availability_v2.csv", index=False)
    node_matrix = pd.read_csv(STORY / "storage_node_decision_matrix.csv")
    coords = storage[["storage_idx", "longitude", "latitude"]].drop_duplicates("storage_idx")
    nodes = node_matrix.merge(coords, on="storage_idx", how="left", validate="many_to_one")
    flow_cols = [f"cumulative_flow_mt_{case}" for case in CORE_PATHS]
    nodes["mean_cumulative_flow_mt"] = nodes[flow_cols].mean(axis=1)
    nodes.to_csv(SOURCE / "fig3_storage_nodes_v2.csv", index=False)
    storage_counts = (
        nodes.groupby(
            ["flow_scenario_count", "storage_type", "is_offshore"],
            as_index=False,
        )
        .size()
        .rename(columns={"size": "node_type_count"})
    )
    storage_counts.to_csv(
        SOURCE / "figS8_storage_recurrence_counts_v2.csv", index=False
    )

    corridors = pd.read_csv(CORRIDORS / "corridor_candidates_r100_with_near_optimal.csv")
    robust = corridors[
        corridors["window"].eq("full_2025_2060")
        & corridors["shared_in_core_cases"].astype(bool)
        & corridors["min_source_count_core_cases"].ge(2)
        & corridors["min_flow_mt_core_cases"].ge(CORRIDOR_FLOW_FLOOR_MT)
    ].copy()
    robust = robust.sort_values("min_flow_mt_core_cases", ascending=False)
    robust.to_csv(SOURCE / "figS7_all_corridor_opportunities_v2.csv", index=False)
    robust["cumulative_min_flow_share"] = (
        robust["min_flow_mt_core_cases"].cumsum()
        / robust["min_flow_mt_core_cases"].sum()
    )
    n_major = int(np.searchsorted(robust["cumulative_min_flow_share"].to_numpy(), 0.5) + 1)
    major = robust.head(n_major).copy()
    major["selection_rule"] = (
        "smallest ranked set reaching 50% of minimum flow across core-robust "
        "100-km opportunity families with >=10 Mt and >=2 sources"
    )
    major.to_csv(SOURCE / "fig3_major_corridor_opportunities_v2.csv", index=False)

    source_regions = pd.read_csv(CORRIDORS / "source_endpoint_regions_r100.csv")
    bridge_assets = spatial.merge(
        source_regions[["plant_id", "source_region"]],
        on="plant_id",
        how="left",
        validate="one_to_one",
    )
    bridge_assets["is_terminal_candidate"] = bridge_assets["terminal_scenario_count"].gt(0)
    asset_summary = (
        bridge_assets.groupby("source_region", as_index=False)
        .agg(
            inherited_plant_count=("plant_id", "size"),
            terminal_candidate_count=("is_terminal_candidate", "sum"),
            stable_core_count=("asset_tier", lambda values: int((values == "stable_core").sum())),
            conditional_asset_count=("asset_tier", lambda values: int((values == "conditional_asset").sum())),
            sensitive_margin_count=("asset_tier", lambda values: int((values == "sensitive_margin").sum())),
            mean_af_resource_index=("af_resource_index", "mean"),
            median_storage_distance_km=("nearest_storage_distance_km", "median"),
            mean_cumulative_capture_mt=("mean_cumulative_capture_mt", "sum"),
        )
    )
    family_summary = (
        robust.groupby("source_region", as_index=False)
        .agg(
            robust_opportunity_family_count=("sink_region", "size"),
            connected_storage_region_count=("sink_region", "nunique"),
            minimum_core_flow_mt=("min_flow_mt_core_cases", "sum"),
            dsa_family_count=("route_type", lambda values: int((values == "DSA").sum())),
            eor_family_count=("route_type", lambda values: int((values == "EOR").sum())),
        )
    )
    bridge = asset_summary.merge(family_summary, on="source_region", how="left", validate="one_to_one")
    count_columns = [
        "robust_opportunity_family_count",
        "connected_storage_region_count",
        "dsa_family_count",
        "eor_family_count",
    ]
    bridge[count_columns] = bridge[count_columns].fillna(0).astype(int)
    bridge["minimum_core_flow_mt"] = bridge["minimum_core_flow_mt"].fillna(0.0)
    province_shapes = gpd.read_file(ROOT / "data/raw/geography/中华人民共和国.geojson")[["name", "geometry"]]
    bridge_points = gpd.GeoDataFrame(
        bridge_assets[["plant_id", "source_region", "province"]].copy(),
        geometry=gpd.points_from_xy(bridge_assets["longitude"], bridge_assets["latitude"]),
        crs="EPSG:4326",
    )
    bridge_geo = gpd.sjoin(bridge_points, province_shapes, predicate="within", how="left")
    bridge_geo["coordinate_province_mismatch"] = bridge_geo.apply(
        lambda row: _normalize_province_name(row["province"])
        != _normalize_province_name(row["name"]),
        axis=1,
    )
    mismatch_summary = (
        bridge_geo.groupby("source_region", as_index=False)["coordinate_province_mismatch"]
        .sum()
        .rename(columns={"coordinate_province_mismatch": "coordinate_province_mismatch_count"})
    )
    bridge = bridge.merge(mismatch_summary, on="source_region", how="left", validate="one_to_one")
    bridge["object_scope"] = "bounded 100-km source regions and source--storage opportunity families; not optimized pipelines"
    bridge["regional_claim_status"] = np.where(
        bridge["coordinate_province_mismatch_count"].gt(0),
        "AUTHOR_REVIEW_REQUIRED: frozen coordinate/province mismatch",
        "screened",
    )
    bridge.to_csv(SOURCE / "fig3_regional_mechanism_bridge_v3.csv", index=False)

    corridor_sensitivity = pd.read_csv(CORRIDORS / "corridor_aggregation_sensitivity.csv")
    corridor_sensitivity = corridor_sensitivity[
        corridor_sensitivity["aggregation_level"].eq(
            "source_region_to_storage_region"
        )
    ].copy()
    corridor_sensitivity.to_csv(
        SOURCE / "figS8_corridor_threshold_sensitivity_v2.csv", index=False
    )

    ccs_eligible = spatial[
        spatial["capacity_t_day"].ge(3200)
        & spatial["nearest_storage_distance_km"].notna()
    ].copy()
    ccs_eligible["af_quartile"] = pd.qcut(
        ccs_eligible["af_resource_index"].rank(method="first"),
        4,
        labels=["AF Q1", "AF Q2", "AF Q3", "AF Q4"],
    )
    ccs_eligible["distance_quartile"] = pd.qcut(
        ccs_eligible["nearest_storage_distance_km"].rank(method="first"),
        4,
        labels=["Distance Q1", "Distance Q2", "Distance Q3", "Distance Q4"],
    )
    grid = (
        ccs_eligible.groupby(
            ["af_quartile", "distance_quartile"], observed=False, as_index=False
        )
        .agg(
            plants=("plant_id", "size"),
            mean_survival_frequency=("survival_frequency", "mean"),
            mean_cumulative_capture_mt=("mean_cumulative_capture_mt", "sum"),
            median_af_resource_index=("af_resource_index", "median"),
            median_storage_distance_km=("nearest_storage_distance_km", "median"),
        )
    )
    grid.to_csv(SOURCE / "fig3_suitability_matrix_v2.csv", index=False)

    comparison = pd.read_csv(RUNS / "analysis_s2/plant_comparison.csv")
    swap_in = comparison[
        comparison["treatment_full__terminal_operating"].eq(1)
        & comparison["baseline__terminal_operating"].eq(0)
    ].copy()
    swap_out = comparison[
        comparison["treatment_full__terminal_operating"].eq(0)
        & comparison["baseline__terminal_operating"].eq(1)
    ].copy()
    swaps = pd.concat(
        [swap_in.assign(swap_group="Swap-in"), swap_out.assign(swap_group="Swap-out")],
        ignore_index=True,
    )
    swaps = swaps[["plant_id", "capacity_t_day", "province", "city", "swap_group"]]
    swaps = swaps.merge(features, on="plant_id", how="left", validate="many_to_one")
    swaps.to_csv(SOURCE / "fig5_asset_swaps_v2.csv", index=False)

    overlap = pd.read_csv(STORY / "cross_scenario_overlap.csv").set_index("comparison")
    corridor_overlap = pd.read_csv(CORRIDORS / "pairwise_route_and_corridor_overlap.csv")
    rows = []
    definitions = [
        ("Inherited stock", "Full-period capacity path", "full_period_capacity_path_jaccard", "capacity-weighted Jaccard"),
        ("Turnover margin", "2050--2060 capacity path", "late_2050_2060_capacity_path_jaccard", "capacity-weighted Jaccard"),
        ("Turnover margin", "Terminal sites", "terminal_site_jaccard", "set Jaccard"),
        ("Turnover margin", "Renewal events", "renewal_event_jaccard", "set Jaccard"),
        ("Responsibility", "Production distribution", "production_distribution_overlap", "shared-mass overlap"),
        ("Responsibility", "Cumulative capture", "capture_responsibility_jaccard", "flow-weighted Jaccard"),
        ("Network", "Exact source--sink routes", "source_sink_route_jaccard", "flow-weighted Jaccard"),
    ]
    for comparison_name, label, public_case, internal_case_alias in [
        ("S1_vs_S2", "S1 vs S2", "S2", "S3"),
        ("S1_vs_S3", "S1 vs S3", "S3", "S5"),
    ]:
        for group, metric_label, column, measure_type in definitions:
            rows.append(
                {
                    "comparison": label,
                    "public_case": public_case,
                    "internal_case_alias": internal_case_alias,
                    "metric_group": group,
                    "metric": metric_label,
                    "overlap_measure": measure_type,
                    "overlap": float(overlap.loc[comparison_name, column]),
                }
            )
        right = comparison_name.split("_vs_")[1]
        selected = corridor_overlap[
            corridor_overlap["endpoint_radius_km"].eq(100)
            & corridor_overlap["window"].eq("full_2025_2060")
            & corridor_overlap["aggregation_level"].eq("source_region_to_storage_region")
            & corridor_overlap["left_case"].eq("S1")
            & corridor_overlap["right_case"].eq(right)
        ]
        rows.append(
            {
                "comparison": label,
                "public_case": public_case,
                "internal_case_alias": internal_case_alias,
                "metric_group": "Network",
                "metric": "100-km opportunity families",
                "overlap_measure": "flow-weighted Jaccard",
                "overlap": float(selected.iloc[0]["flow_weighted_jaccard"]),
            }
        )
    pd.DataFrame(rows).to_csv(SOURCE / "fig5_overlap_profile_v2.csv", index=False)


def _aggregate_corridors(
    routes: pd.DataFrame,
    source_regions: pd.DataFrame,
    storage_regions: pd.DataFrame,
) -> pd.DataFrame:
    out = routes.merge(
        source_regions[["plant_id", "source_region"]],
        on="plant_id",
        how="left",
        validate="many_to_one",
    )
    out = out.merge(
        storage_regions[["storage_idx", "route_type", "sink_region"]],
        on=["storage_idx", "route_type"],
        how="left",
        validate="many_to_one",
    )
    if out[["source_region", "sink_region"]].isna().any().any():
        raise ValueError("Corridor endpoint mapping is incomplete.")
    return (
        out.groupby(["source_region", "sink_region", "route_type"], as_index=False)
        .agg(flow_mt=("flow_mt", "sum"), source_count=("plant_id", "nunique"))
    )


def _minimum_coverage(
    case_names: list[str],
    route_frames: dict[str, pd.DataFrame],
    result_data: dict[str, dict[str, Any]],
    years: set[int],
    radius: int = 100,
) -> list[dict[str, Any]]:
    filtered = {
        case: route_frames[case][route_frames[case]["year"].isin(years)].copy()
        for case in case_names
    }
    totals = {case: float(frame["flow_mt"].sum()) for case, frame in filtered.items()}

    stable_sites = set.intersection(*(_terminal_set(result_data[case]) for case in case_names))
    site_shares = {
        case: frame.loc[frame["plant_id"].isin(stable_sites), "flow_mt"].sum() / totals[case]
        if totals[case] > 0
        else np.nan
        for case, frame in filtered.items()
    }

    storage_sets = {
        case: set(zip(frame["storage_idx"], frame["route_type"]))
        for case, frame in filtered.items()
    }
    common_storage = set.intersection(*(storage_sets[case] for case in case_names))
    storage_shares = {
        case: frame.loc[
            pd.MultiIndex.from_frame(frame[["storage_idx", "route_type"]]).isin(common_storage),
            "flow_mt",
        ].sum()
        / totals[case]
        if totals[case] > 0
        else np.nan
        for case, frame in filtered.items()
    }

    route_sets = {
        case: set(zip(frame["plant_id"], frame["storage_idx"], frame["route_type"]))
        for case, frame in filtered.items()
    }
    common_routes = set.intersection(*(route_sets[case] for case in case_names))
    route_shares = {}
    for case, frame in filtered.items():
        keys = pd.MultiIndex.from_frame(frame[["plant_id", "storage_idx", "route_type"]])
        route_shares[case] = (
            frame.loc[keys.isin(common_routes), "flow_mt"].sum() / totals[case]
            if totals[case] > 0
            else np.nan
        )

    source_regions = pd.read_csv(CORRIDORS / f"source_endpoint_regions_r{radius}.csv")
    storage_regions = pd.read_csv(CORRIDORS / f"storage_endpoint_regions_r{radius}.csv")
    aggregated = {
        case: _aggregate_corridors(frame, source_regions, storage_regions)
        for case, frame in filtered.items()
    }
    corridor_sets = {
        case: set(
            zip(frame["source_region"], frame["sink_region"], frame["route_type"])
        )
        for case, frame in aggregated.items()
    }
    common_corridors = set.intersection(*(corridor_sets[case] for case in case_names))
    robust_corridors = set()
    for key in common_corridors:
        flows = []
        sources = []
        for case in case_names:
            frame = aggregated[case].set_index(
                ["source_region", "sink_region", "route_type"]
            )
            flows.append(float(frame.loc[key, "flow_mt"]))
            sources.append(int(frame.loc[key, "source_count"]))
        if min(flows) >= CORRIDOR_FLOW_FLOOR_MT and min(sources) >= 2:
            robust_corridors.add(key)
    corridor_shares = {}
    for case, frame in aggregated.items():
        keys = pd.MultiIndex.from_frame(
            frame[["source_region", "sink_region", "route_type"]]
        )
        corridor_shares[case] = (
            frame.loc[keys.isin(robust_corridors), "flow_mt"].sum() / totals[case]
            if totals[case] > 0
            else np.nan
        )

    def row(level: str, shares: dict[str, float], count: int) -> dict[str, Any]:
        valid = [float(value) for value in shares.values() if np.isfinite(value)]
        return {
            "planning_level": level,
            "minimum_flow_coverage": min(valid) if valid else np.nan,
            "common_object_count": count,
            "case_count": len(case_names),
        }

    return [
        row("Stable terminal sites", site_shares, len(stable_sites)),
        row("Recurrent storage node--types", storage_shares, len(common_storage)),
        row("100-km opportunity families", corridor_shares, len(robust_corridors)),
        row("Exact plant--storage routes", route_shares, len(common_routes)),
    ]


def _prepare_fig6(
    result_data: dict[str, dict[str, Any]],
    route_frames: dict[str, pd.DataFrame],
) -> None:
    specificity_rows = []
    sensitivity_rows = []
    for case_set, cases in CASE_SETS.items():
        for window, years in WINDOWS.items():
            for row in _minimum_coverage(cases, route_frames, result_data, years, radius=100):
                specificity_rows.append(
                    {"case_set": case_set, "window": window, **row}
                )
            for radius in (60, 100, 150):
                rows = _minimum_coverage(cases, route_frames, result_data, years, radius=radius)
                corridor = next(
                    row for row in rows if row["planning_level"] == "100-km opportunity families"
                )
                sensitivity_rows.append(
                    {
                        "case_set": case_set,
                        "window": window,
                        "endpoint_radius_km": radius,
                        "minimum_flow_coverage": corridor["minimum_flow_coverage"],
                        "robust_corridor_count": corridor["common_object_count"],
                        "flow_threshold_mt": CORRIDOR_FLOW_FLOOR_MT,
                    }
                )
    pd.DataFrame(specificity_rows).to_csv(
        SOURCE / "fig6_planning_specificity_coverage_v2.csv", index=False
    )
    pd.DataFrame(sensitivity_rows).to_csv(
        SOURCE / "fig6_corridor_sensitivity_v2.csv", index=False
    )


def _objective(data: dict[str, Any], kind: str) -> float:
    solver = data.get("solver", {})
    if kind == "incumbent":
        for key in ("objective_value", "objective_incumbent", "objective"):
            if key in solver:
                return float(solver[key]) / 1_000_000.0
        return float(data["total_cost_kCNY"]) / 1_000_000.0
    for key in ("objective_bound", "best_bound", "dual_bound"):
        if key in solver:
            return float(solver[key]) / 1_000_000.0
    raise KeyError("No objective bound in solver diagnostics")


def _prepare_fig7() -> None:
    util = pd.read_csv(UTIL / "utilization_sensitivity_summary.csv")
    parameter = util[
        [
            "minimum_operating_utilization",
            "turnover_lockin_regret_bn_cny",
            "turnover_lockin_lower_bn_cny",
            "turnover_lockin_upper_bn_cny",
        ]
    ].copy()
    parameter["setting"] = parameter["minimum_operating_utilization"].map(
        lambda value: f"Minimum utilization = {value:.2f}"
    )
    parameter["parameter_family"] = "Minimum utilization"
    parameter = parameter.rename(
        columns={
            "turnover_lockin_regret_bn_cny": "point_bn_cny",
            "turnover_lockin_lower_bn_cny": "lower_bn_cny",
            "turnover_lockin_upper_bn_cny": "upper_bn_cny",
        }
    )

    lifetime_full = _load_json(
        RUNS / "lifetime35/full/S3_all_spatial_equalized_results.json"
    )
    lifetime_fixed = _load_json(
        RUNS / "lifetime35/s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json"
    )
    lifetime_row = pd.DataFrame(
        [
            {
                "minimum_operating_utilization": np.nan,
                "point_bn_cny": _objective(lifetime_fixed, "incumbent")
                - _objective(lifetime_full, "incumbent"),
                "lower_bn_cny": _objective(lifetime_fixed, "bound")
                - _objective(lifetime_full, "incumbent"),
                "upper_bn_cny": _objective(lifetime_fixed, "incumbent")
                - _objective(lifetime_full, "bound"),
                "setting": "Technical lifetime = 35 y",
                "parameter_family": "Technical lifetime",
            }
        ]
    )
    parameter = pd.concat([parameter, lifetime_row], ignore_index=True)
    parameter.to_csv(SOURCE / "fig7_parameter_regret_intervals_v2.csv", index=False)

    operating = pd.read_csv(UTIL / "utilization_floor_binding.csv")
    operating.to_csv(SOURCE / "fig7_floor_binding_v2.csv", index=False)
    operating_2045 = operating[operating["year"].eq(2045)][
        ["minimum_operating_utilization", "operating_lines"]
    ].rename(columns={"operating_lines": "operating_lines_2045"})
    boundary = util[
        ["minimum_operating_utilization", "s1_terminal_lines"]
    ].rename(columns={"s1_terminal_lines": "operating_lines_2060"})
    boundary = boundary.merge(
        operating_2045,
        on="minimum_operating_utilization",
        how="left",
        validate="one_to_one",
    )
    boundary["public_case"] = "S1"
    boundary["boundary_definition"] = "operating lines in 2045 versus terminal operating lines in 2060"
    boundary.to_csv(SOURCE / "fig7_parameter_path_boundary_v3.csv", index=False)

    near = pd.read_csv(STORY / "near_optimal_frontier_summary.csv")
    label_map = {
        "S1_farthest_full": ("Self-drift", "S1 farthest full-path", "S1", "S1"),
        "S1_farthest_terminal": ("Self-drift", "S1 farthest terminal", "S1", "S1"),
        "S2_closest_terminal": ("Closest return to S1", "S2 closest terminal", "S2", "S3"),
        "S3_closest_terminal": ("Closest return to S1", "S3 closest terminal", "S3", "S5"),
    }
    rows = []
    for row in near.itertuples(index=False):
        group, label, public_case, internal_case_alias = label_map[row.case_id]
        for metric, value in [
            ("Terminal-site identity", row.terminal_site_jaccard_vs_s1),
            ("Route-flow identity", row.route_flow_jaccard_vs_s1),
        ]:
            rows.append(
                {
                    "case_id": row.case_id,
                    "group": group,
                    "label": label,
                    "public_case": public_case,
                    "internal_case_alias": internal_case_alias,
                    "metric": metric,
                    "overlap_vs_s1": value,
                    "cost_tolerance_fraction": row.cost_tolerance_fraction,
                    "realized_cost_increase_fraction": row.realized_cost_increase_fraction,
                    "identity_phase_mip_gap": row.identity_phase_mip_gap,
                    "identity_bound_width_share_of_exposure": row.identity_bound_width_share_of_exposure,
                }
            )
    pd.DataFrame(rows).to_csv(SOURCE / "fig7_near_optimal_identity_v2.csv", index=False)


def _prepare_fig3_geographic_qa(
    spatial: pd.DataFrame,
    route_frames: dict[str, pd.DataFrame],
) -> None:
    province_shapes = gpd.read_file(ROOT / "data/raw/geography/中华人民共和国.geojson")[["name", "geometry"]]
    points = gpd.GeoDataFrame(
        spatial[
            [
                "plant_id",
                "name",
                "province",
                "city",
                "longitude",
                "latitude",
                "asset_tier",
                "terminal_scenario_count",
                "mean_cumulative_capture_mt",
            ]
        ].copy(),
        geometry=gpd.points_from_xy(spatial["longitude"], spatial["latitude"]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(points, province_shapes, predicate="within", how="left").rename(
        columns={"name_left": "plant_name", "name_right": "coordinate_province"}
    )
    joined["province_match"] = joined.apply(
        lambda row: _normalize_province_name(row["province"])
        == _normalize_province_name(row["coordinate_province"]),
        axis=1,
    )
    flagged = joined[~joined["province_match"]].drop(columns=["geometry", "index_right"])
    source_regions = pd.read_csv(CORRIDORS / "source_endpoint_regions_r100.csv")
    flagged = flagged.merge(
        source_regions[["plant_id", "source_region"]],
        on="plant_id",
        how="left",
        validate="one_to_one",
    )
    robust = pd.read_csv(SOURCE / "figS7_all_corridor_opportunities_v2.csv")
    family_counts = robust.groupby("source_region").size().rename("robust_family_count_in_flagged_region")
    flagged = flagged.merge(family_counts, on="source_region", how="left")
    flagged["robust_family_count_in_flagged_region"] = (
        flagged["robust_family_count_in_flagged_region"].fillna(0).astype(int)
    )
    for case in CORE_PATHS:
        frame = route_frames[case]
        plant_flow = frame.groupby("plant_id")["flow_mt"].sum()
        flagged[f"cumulative_route_flow_mt_{case}"] = flagged["plant_id"].map(plant_flow).fillna(0.0)
        total_flow = float(frame["flow_mt"].sum())
        flagged[f"national_route_flow_share_{case}"] = (
            flagged[f"cumulative_route_flow_mt_{case}"] / total_flow if total_flow > 0 else np.nan
        )
    flagged["frozen_output_handling"] = "not silently corrected; requires corrected-input decision and, if accepted, a new model run"
    flagged.to_csv(SOURCE / "fig3_geographic_provenance_audit_v3.csv", index=False)

    storage_regions = pd.read_csv(CORRIDORS / "storage_endpoint_regions_r100.csv")
    flagged_ids = set(flagged["plant_id"].astype(int))
    aggregated = {
        case: _aggregate_corridors(frame, source_regions, storage_regions)
        for case, frame in route_frames.items()
        if case in CORE_PATHS
    }
    excluded = {
        case: _aggregate_corridors(
            frame[~frame["plant_id"].isin(flagged_ids)], source_regions, storage_regions
        )
        for case, frame in route_frames.items()
        if case in CORE_PATHS
    }
    suspect_regions = set(flagged["source_region"])
    keys = set()
    for frame in aggregated.values():
        keys.update(
            key
            for key in zip(frame["source_region"], frame["sink_region"], frame["route_type"])
            if key[0] in suspect_regions
        )
    rows = []
    for key in sorted(keys):
        before_flow = []
        after_flow = []
        before_sources = []
        after_sources = []
        per_case = {}
        for case in CORE_PATHS:
            before = aggregated[case].set_index(["source_region", "sink_region", "route_type"])
            after = excluded[case].set_index(["source_region", "sink_region", "route_type"])
            bf = float(before.loc[key, "flow_mt"]) if key in before.index else 0.0
            af = float(after.loc[key, "flow_mt"]) if key in after.index else 0.0
            bs = int(before.loc[key, "source_count"]) if key in before.index else 0
            ass = int(after.loc[key, "source_count"]) if key in after.index else 0
            before_flow.append(bf)
            after_flow.append(af)
            before_sources.append(bs)
            after_sources.append(ass)
            per_case[f"flagged_flow_mt_{case}"] = bf - af
        robust_before = min(before_flow) >= CORRIDOR_FLOW_FLOOR_MT and min(before_sources) >= 2
        robust_after = min(after_flow) >= CORRIDOR_FLOW_FLOOR_MT and min(after_sources) >= 2
        if not (robust_before or robust_after):
            continue
        rows.append(
            {
                "source_region": key[0],
                "sink_region": key[1],
                "route_type": key[2],
                "robust_before_exclusion": robust_before,
                "robust_after_excluding_all_flagged_plants": robust_after,
                "minimum_core_flow_mt_before": min(before_flow),
                "minimum_core_flow_mt_after": min(after_flow),
                "minimum_source_count_before": min(before_sources),
                "minimum_source_count_after": min(after_sources),
                **per_case,
                "interpretation_limit": "exclusion-only post-processing; it does not emulate corrected coordinates or re-optimization",
            }
        )
    pd.DataFrame(rows).to_csv(SOURCE / "fig3_flagged_asset_corridor_impact_v3.csv", index=False)


def _prepare_fig4() -> None:
    s2 = pd.read_csv(RUNS / "analysis_s2/summary_metrics.csv")
    s3 = pd.read_csv(RUNS / "analysis_s3/summary_metrics.csv")

    def metric(table: pd.DataFrame, name: str) -> pd.Series:
        selected = table.loc[table["metric"].eq(name)]
        if len(selected) != 1:
            raise ValueError(f"Expected one row for {name!r}; found {len(selected)}")
        return selected.iloc[0]

    objective = metric(s2, "objective_incumbent")
    baseline = float(objective["baseline_value"])
    full = float(objective["treatment_full_value"])
    fixed_turnover = float(objective["treatment_fixed_turnover_value"])
    fixed_dispatch = float(objective["treatment_fixed_dispatch_value"])
    decomposition = pd.DataFrame(
        [
            {"step": "Direct effect", "delta_billion_cny": fixed_dispatch - baseline},
            {
                "step": "Dispatch feedback",
                "delta_billion_cny": fixed_turnover - fixed_dispatch,
            },
            {"step": "Turnover feedback", "delta_billion_cny": full - fixed_turnover},
            {"step": "Total effect", "delta_billion_cny": full - baseline},
        ]
    )
    decomposition["cumulative_billion_cny"] = [
        decomposition.loc[0, "delta_billion_cny"],
        decomposition.loc[:1, "delta_billion_cny"].sum(),
        decomposition.loc[:2, "delta_billion_cny"].sum(),
        decomposition.loc[3, "delta_billion_cny"],
    ]
    decomposition.to_csv(SOURCE / "fig4_cost_decomposition_v2.csv", index=False)

    specs = [
        (
            s2,
            "S2 forward lock-in loss",
            "turnover_lockin_regret__fixed_turnover_vs_full_treatment",
        ),
        (
            s2,
            "S2 reverse planning regret",
            "reverse_turnover_sequential_regret__s3_plan_under_s1_vs_joint_s1",
        ),
        (
            s3,
            "S3 forward lock-in loss",
            "turnover_lockin_regret__fixed_turnover_vs_full_treatment",
        ),
        (
            s3,
            "S3 reverse planning regret",
            "reverse_turnover_sequential_regret__s5_plan_under_s1_vs_joint_s1",
        ),
        (s2, "Null control", "null_control_lockin_regret"),
    ]
    rows = []
    for table, label, name in specs:
        row = metric(table, name)
        public_case = "S1" if label == "Null control" else label.split()[0]
        internal_case_alias = {"S1": "S1", "S2": "S3", "S3": "S5"}[public_case]
        rows.append(
            {
                "label": label,
                "public_case": public_case,
                "internal_case_alias": internal_case_alias,
                "metric": name,
                "point_billion_cny": float(row["comparison_value"]),
                "lower_bound_billion_cny": float(row["comparison_lower_bound"]),
                "upper_bound_billion_cny": float(row["comparison_upper_bound"]),
            }
        )
    pd.DataFrame(rows).to_csv(SOURCE / "fig4_regret_intervals_v2.csv", index=False)


def _write_source_manifest() -> None:
    rows = [
        ("Fig. 2", "fig2_system_envelope_v2.csv", "writing_ready_storyline_v3_20260829"),
        ("Fig. 2", "fig2_turnover_capture_v2.csv", "final_verified_inputs_20260829; writing_ready_storyline_v3_20260829"),
        ("Fig. 3", "fig3_af_hex_v2.csv", "final_verified_inputs_20260829/_input_snapshot (hash-validated inputs); writing_ready_storyline_v3_20260829"),
        ("Fig. 3", "fig3_spatial_assets_v2.csv", "final_verified_inputs_20260829/_input_snapshot (hash-validated inputs); writing_ready_storyline_v3_20260829"),
        ("Fig. 3", "fig3_storage_availability_v2.csv", "final_verified_inputs_20260829/_input_snapshot (hash-validated inputs)"),
        ("Fig. 3", "fig3_storage_nodes_v2.csv", "final_verified_inputs_20260829/_input_snapshot (hash-validated inputs); writing_ready_storyline_v3_20260829"),
        ("Fig. 3", "fig3_major_corridor_opportunities_v2.csv", "postprocess_robust_corridors_bounded_endpoints_20260829"),
        ("Fig. 3", "fig3_suitability_matrix_v2.csv", "final_verified_inputs_20260829/_input_snapshot (hash-validated inputs); writing_ready_storyline_v3_20260829"),
        ("Fig. 3 / SI diagnostic", "fig3_regional_mechanism_bridge_v3.csv", "final_verified_inputs_20260829/_input_snapshot (hash-validated inputs); writing_ready_storyline_v3_20260829; postprocess_robust_corridors_bounded_endpoints_20260829"),
        ("Fig. 3 QA", "fig3_geographic_provenance_audit_v3.csv", "frozen plant coordinates and province labels; project province GeoJSON"),
        ("Fig. 3 QA", "fig3_flagged_asset_corridor_impact_v3.csv", "frozen core route outputs; bounded-endpoint corridor mapping; exclusion-only post-processing"),
        ("Fig. 4", "fig4_cost_decomposition_v2.csv", "final_verified_inputs_20260829/analysis_s2"),
        ("Fig. 4", "fig4_regret_intervals_v2.csv", "final_verified_inputs_20260829/analysis_s2; final_verified_inputs_20260829/analysis_s3"),
        ("Fig. 5", "fig5_asset_swaps_v2.csv", "final_verified_inputs_20260829/analysis_s2; final_verified_inputs_20260829/_input_snapshot (hash-validated inputs)"),
        ("Fig. 5", "fig5_overlap_profile_v2.csv", "writing_ready_storyline_v3_20260829; postprocess_robust_corridors_bounded_endpoints_20260829"),
        ("Fig. 6", "fig6_planning_specificity_coverage_v2.csv", "final_verified_inputs_20260829; postprocess_robust_corridors_bounded_endpoints_20260829"),
        ("Fig. 6", "fig6_corridor_sensitivity_v2.csv", "final_verified_inputs_20260829; postprocess_robust_corridors_bounded_endpoints_20260829"),
        ("Fig. 7", "fig7_parameter_regret_intervals_v2.csv", "final_verified_inputs_20260829/lifetime35; min_utilization_verified_inputs_20260829"),
        ("Fig. 7", "fig7_parameter_path_boundary_v3.csv", "min_utilization_verified_inputs_20260829/utilization_floor_binding.csv"),
        ("Fig. 7", "fig7_floor_binding_v2.csv", "min_utilization_verified_inputs_20260829/utilization_floor_binding.csv"),
        ("Fig. 7", "fig7_near_optimal_identity_v2.csv", "writing_ready_storyline_v3_20260829"),
        ("Fig. S7", "figS7_all_corridor_opportunities_v2.csv", "postprocess_robust_corridors_bounded_endpoints_20260829"),
        ("Fig. S8", "figS8_storage_recurrence_counts_v2.csv", "final_verified_inputs_20260829/_input_snapshot (hash-validated inputs); writing_ready_storyline_v3_20260829"),
        ("Fig. S8", "figS8_corridor_threshold_sensitivity_v2.csv", "postprocess_robust_corridors_bounded_endpoints_20260829"),
    ]
    pd.DataFrame(rows, columns=["figure", "source_data_file", "frozen_evidence"]).to_csv(
        SOURCE / "main_figure_source_manifest_20260829.csv", index=False
    )


def _write_audit(
    core: dict[str, dict[str, Any]],
    spatial: pd.DataFrame,
    route_frames: dict[str, pd.DataFrame],
) -> None:
    checks = []

    def check(name: str, observed: Any, expected: Any, passed: bool, note: str = "") -> None:
        checks.append(
            {
                "check": name,
                "status": "PASS" if passed else "FAIL",
                "observed": observed,
                "expected": expected,
                "note": note,
            }
        )

    def review(name: str, observed: Any, expected: Any, note: str) -> None:
        checks.append(
            {
                "check": name,
                "status": "AUTHOR_REVIEW_REQUIRED",
                "observed": observed,
                "expected": expected,
                "note": note,
            }
        )

    check(
        "minimum_operating_utilization",
        cfg.MIN_OPERATING_UTILIZATION,
        0.40,
        math.isclose(cfg.MIN_OPERATING_UTILIZATION, 0.40),
    )
    check(
        "early_exit_cost",
        cfg.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY,
        130.0,
        math.isclose(
            cfg.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY,
            130.0,
        ),
    )
    recorded_utilization = [
        float(core[case]["model_assumptions"]["minimum_operating_utilization"])
        for case in CORE_PATHS
    ]
    check(
        "core_result_utilization_assumption",
        sorted(set(recorded_utilization)),
        [0.40],
        all(math.isclose(value, 0.40) for value in recorded_utilization),
    )

    manifest = pd.read_csv(RUNS / "_input_snapshot/final_input_manifest.csv")
    hash_matches = []
    for row in manifest.itertuples(index=False):
        path = ROOT / str(row.path)
        observed_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
        hash_matches.append(observed_hash == str(row.sha256))
    check(
        "frozen_input_manifest_hashes_match",
        sum(hash_matches),
        len(hash_matches),
        all(hash_matches),
        "Current AF, storage, plant and geography inputs reproduce the frozen central input manifest.",
    )

    for name, path in (
        ("writing_ready_audit_failures", STORY / "audit_checks.csv"),
        ("corridor_postprocess_audit_failures", CORRIDORS / "audit_checks.csv"),
        ("utilization_sensitivity_audit_failures", UTIL / "audit_checks.csv"),
    ):
        package_audit = pd.read_csv(path)
        failures = int(package_audit["status"].astype(str).str.upper().eq("FAIL").sum())
        check(name, failures, 0, failures == 0)
    check("plant_grain", len(spatial), 1572, len(spatial) == 1572)
    check(
        "plant_id_unique",
        spatial["plant_id"].nunique(),
        len(spatial),
        spatial["plant_id"].is_unique,
    )
    check(
        "feature_join_coverage",
        int(spatial["af_resource_index"].notna().sum()),
        len(spatial),
        spatial["af_resource_index"].notna().all(),
    )
    annual = pd.read_csv(STORY / "annual_system_evolution.csv")
    for case in CORE_PATHS:
        weighted_routes = float(route_frames[case]["flow_mt"].sum())
        expected_capture = 0.0
        data = core[case]
        for year in YEARS:
            expected_capture += (
                float(data["summary"][str(year)]["commercial_captured_co2_kt"])
                * float(data["period_weights_years"][str(year)])
                / 1000.0
            )
        check(
            f"route_capture_reconciliation_{case}",
            weighted_routes,
            expected_capture,
            abs(weighted_routes - expected_capture) <= 1e-5,
        )
        case_annual = annual[annual["case"].eq(case)]
        check(
            f"annual_period_count_{case}",
            len(case_annual),
            len(YEARS),
            len(case_annual) == len(YEARS),
        )
    coverage = pd.read_csv(SOURCE / "fig6_planning_specificity_coverage_v2.csv")
    bounded = coverage["minimum_flow_coverage"].dropna().between(0, 1).all()
    check("coverage_metrics_bounded", bool(bounded), True, bool(bounded))
    check(
        "all_fig6_case_sets_present",
        coverage["case_set"].nunique(),
        2,
        coverage["case_set"].nunique() == 2,
    )
    turnover = pd.read_csv(SOURCE / "fig2_turnover_capture_v2.csv")
    capture_components = turnover[
        [
            "terminal_inherited_phase_capture_mt_y",
            "terminal_renewed_phase_capture_mt_y",
            "nonterminal_capture_mt_y",
        ]
    ].sum(axis=1)
    check(
        "fig2_capture_state_reconciliation",
        float((capture_components - turnover["total_capture_mt_y"]).abs().max()),
        0.0,
        np.allclose(capture_components, turnover["total_capture_mt_y"], atol=1e-9),
    )
    overlap_source = pd.read_csv(SOURCE / "fig5_overlap_profile_v2.csv")
    renewal_definitions = set(
        overlap_source.loc[overlap_source["metric"].eq("Renewal events"), "overlap_measure"]
    )
    check(
        "fig5_renewal_event_overlap_definition",
        sorted(renewal_definitions),
        ["set Jaccard"],
        renewal_definitions == {"set Jaccard"},
    )
    check(
        "fig5_terminal_capacity_duplicate_removed",
        int(overlap_source["metric"].eq("Terminal capacity").sum()),
        0,
        not overlap_source["metric"].eq("Terminal capacity").any(),
    )
    boundary = pd.read_csv(SOURCE / "fig7_parameter_path_boundary_v3.csv")
    check(
        "fig7_parameter_boundary_complete",
        int(boundary[["operating_lines_2045", "operating_lines_2060"]].notna().all(axis=1).sum()),
        len(boundary),
        boundary[["operating_lines_2045", "operating_lines_2060"]].notna().all().all(),
    )
    geo_qa = pd.read_csv(SOURCE / "fig3_geographic_provenance_audit_v3.csv")
    if len(geo_qa):
        review(
            "fig3_coordinate_province_consistency",
            len(geo_qa),
            0,
            "Four frozen plant records cross province boundaries; two are stable-core assets. Fig. 3 regional and corridor interpretation remains blocked pending an author decision.",
        )
    else:
        check("fig3_coordinate_province_consistency", 0, 0, True)
    pd.DataFrame(checks).to_csv(SOURCE / "main_figure_data_audit_20260829.csv", index=False)
    if any(row["status"] == "FAIL" for row in checks):
        failed = [row["check"] for row in checks if row["status"] == "FAIL"]
        raise RuntimeError(f"Figure-data audit failed: {failed}")


def main() -> None:
    SOURCE.mkdir(parents=True, exist_ok=True)
    core = {case: _load_json(path) for case, path in CORE_PATHS.items()}
    near = {case: _load_json(path) for case, path in NEAR_PATHS.items()}
    result_data = {**core, **near}
    route_frames = {case: _routes(case, data) for case, data in result_data.items()}

    model_data = load_all()
    features, storage = _feature_tables(model_data)
    plants = pd.read_csv(STORY / "plant_decision_matrix.csv")[
        [
            "plant_id",
            "province",
            "city",
            "capacity_t_day",
            "longitude",
            "latitude",
            "commission_year",
        ]
    ].copy()
    plants["plant_id"] = plants["plant_id"].astype(int)

    _prepare_fig2(core, plants)
    _prepare_fig3_and_fig5(features, storage, plants)
    spatial = pd.read_csv(SOURCE / "fig3_spatial_assets_v2.csv")
    _prepare_fig3_geographic_qa(spatial, route_frames)
    _prepare_fig4()
    _prepare_fig6(result_data, route_frames)
    _prepare_fig7()
    _write_source_manifest()

    _write_audit(core, spatial, route_frames)
    print(f"Wrote Fig. 2--7 source data to {SOURCE}")


if __name__ == "__main__":
    main()
