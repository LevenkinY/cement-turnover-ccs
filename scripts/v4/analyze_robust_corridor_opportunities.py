#!/usr/bin/env python3
"""Post-process canonical plant-to-storage flows into corridor opportunities.

The canonical v4 model optimizes direct plant-to-storage flows. It does not
choose shared trunk-pipeline topology. Therefore this script never labels an
individual optimized edge as a shared pipeline. Instead it aggregates routes
into *corridor families* between source regions and spatially grouped storage
regions, then tests recurrence, flow floors, multi-source use, temporal timing,
aggregation sensitivity, and selected near-optimal solutions.

Outputs are written to a new dated post-processing directory. Frozen canonical
result JSONs are read-only inputs and are never modified.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS = ROOT / "results/v4/final_verified_inputs_20260822"
DEFAULT_OUT = ROOT / "results/v4/postprocess_robust_corridors_bounded_endpoints_20260822"
sys.path.insert(0, str(ROOT / "models/v4"))

from src_v4.data_loader_v4 import load_storage

def case_paths(runs: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    """Return public manuscript case labels mapped to frozen internal files."""
    base = {
        "S1": runs / "full/S1_baseline_results.json",
        "S2": runs / "full/S3_all_spatial_equalized_results.json",
        "S3": runs / "full/S5_offshore_parity_results.json",
        "S4": runs / "demand/d_high/S1_baseline_results.json",
        "S5": runs / "demand/d_low/S1_baseline_results.json",
    }
    near = {
        "S1-near-terminal": runs
        / "near_optimal/s1_farthest_terminal_e0010/S1_baseline_results.json",
        "S1-near-full": runs
        / "near_optimal/s1_farthest_full_e0010/S1_baseline_results.json",
        "S2-near-terminal": runs
        / "near_optimal/s2_closest_terminal_e0010/S3_all_spatial_equalized_results.json",
        "S3-near-terminal": runs
        / "near_optimal/s3_closest_terminal_e0010/S5_offshore_parity_results.json",
    }
    return base, near

WINDOWS = {
    "full_2025_2060": set(range(2025, 2061)),
    "early_2025_2045": set(range(2025, 2046)),
    "late_2050_2060": set(range(2050, 2061)),
}

STORAGE_RADII_KM = (60, 100, 150)
FLOW_THRESHOLDS_MT = (1.0, 5.0, 10.0, 20.0)
FLOW_TOL_MT = 1e-6

warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    message=r"DataFrameGroupBy\.apply operated on the grouping columns.*",
)


def csv_block(df: pd.DataFrame) -> str:
    """Render a compact dependency-free table for the Markdown audit note."""
    return "```csv\n" + df.to_csv(index=False).strip() + "\n```"


def load_metadata() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Reuse the canonical loader because it removes mainland cells from the
    # raw basin-box offshore flag before route costing and result extraction.
    storage = load_storage()
    clusters = pd.read_csv(ROOT / "data/model_input/plants/cluster_assignment.csv")
    fleet = pd.read_csv(
        ROOT / "data/model_input/plants/fusion_2025/plant_fleet_2025_final.csv"
    )
    fleet = fleet.rename(columns={"id": "plant_id"})
    for df, col in ((storage, "storage_idx"), (clusters, "plant_id"), (fleet, "plant_id")):
        df[col] = pd.to_numeric(df[col], errors="raise").astype(int)
    return storage, clusters, fleet


def load_routes(case: str, path: Path) -> tuple[pd.DataFrame, dict]:
    with path.open() as f:
        data = json.load(f)
    weights = {int(k): float(v) for k, v in data["period_weights_years"].items()}
    rows = []
    for year_key, routes in data["co2_flow_routes"].items():
        year = int(year_key)
        for route in routes:
            flow_kt = float(route["flow_kt"])
            if flow_kt <= 1e-6:
                continue
            rows.append(
                {
                    "case": case,
                    "year": year,
                    "plant_id": int(route["plant_id"]),
                    "cluster_id": (
                        int(route["cluster_id"])
                        if route.get("cluster_id") is not None
                        else np.nan
                    ),
                    "storage_idx": int(route["storage_idx"]),
                    "route_type": str(route.get("type", route.get("storage_type", ""))).upper(),
                    "is_offshore": bool(route.get("is_offshore", False)),
                    "flow_kt_yr": flow_kt,
                    "period_years": weights[year],
                    "flow_mt": flow_kt * weights[year] / 1000.0,
                    "distance_km": float(route["distance_km"]),
                    "plant_lon": float(route["plant_longitude"]),
                    "plant_lat": float(route["plant_latitude"]),
                    "storage_lon": float(route["storage_longitude"]),
                    "storage_lat": float(route["storage_latitude"]),
                    "route_definition": str(route.get("route_definition", "unknown")),
                }
            )
    return pd.DataFrame(rows), data


def haversine_distance_matrix(
    latitude: np.ndarray, longitude: np.ndarray
) -> np.ndarray:
    """Return all-pairs great-circle distances in kilometres."""
    lat = np.radians(np.asarray(latitude, dtype=float))
    lon = np.radians(np.asarray(longitude, dtype=float))
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2.0) ** 2
    )
    return 2.0 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def complete_linkage_labels(distance_km: np.ndarray, radius_km: int) -> np.ndarray:
    """Create deterministic regions whose maximum pair separation is bounded."""
    return AgglomerativeClustering(
        n_clusters=None,
        metric="precomputed",
        linkage="complete",
        distance_threshold=float(radius_km),
    ).fit_predict(distance_km)


def build_source_regions(fleet: pd.DataFrame, radius_km: int) -> pd.DataFrame:
    """Group plant locations into bounded endpoint zones independent of use."""
    source = fleet[["plant_id", "longitude", "latitude"]].copy().sort_values("plant_id")
    distance = haversine_distance_matrix(
        source["latitude"].to_numpy(), source["longitude"].to_numpy()
    )
    labels = complete_linkage_labels(distance, radius_km)
    source["component"] = labels
    component_name = source.groupby("component")["plant_id"].min().to_dict()
    source["source_region"] = source["component"].map(
        lambda c: f"SRC_{component_name[c]}"
    )
    diameters = {
        component: float(distance[np.ix_(idx, idx)].max())
        for component, idx in source.groupby("component").indices.items()
    }
    source["source_region_diameter_km"] = source["component"].map(diameters)
    source["source_region_plant_count"] = source["component"].map(
        source.groupby("component")["plant_id"].size().to_dict()
    )
    return source.drop(columns="component")


def build_storage_regions(storage: pd.DataFrame, radius_km: int) -> pd.DataFrame:
    """Create bounded storage endpoint zones by type and land/sea class.

    Complete-linkage clustering avoids the long chaining components produced by
    density clustering on the 40-km storage grid. The maximum pairwise endpoint
    separation within each zone is constrained by the tested radius.
    """
    rows = []
    for route_type, has_col in (("DSA", "has_dsa"), ("EOR", "has_eor")):
        eligible = storage[storage[has_col].astype(bool)].copy()
        for offshore, group in eligible.groupby(eligible["is_offshore"].astype(bool)):
            group = group.copy().sort_values("storage_idx")
            xy = group[["grid_x", "grid_y"]].to_numpy(dtype=float)
            distance = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2)) / 1000.0
            labels = complete_linkage_labels(distance, radius_km)
            group["component"] = labels
            component_name = group.groupby("component")["storage_idx"].min().to_dict()
            group["sink_region"] = group["component"].map(
                lambda c: f"{route_type}_{'offshore' if offshore else 'onshore'}_{component_name[c]}"
            )
            diameters = {
                component: float(distance[np.ix_(idx, idx)].max())
                for component, idx in group.groupby("component").indices.items()
            }
            group["sink_region_diameter_km"] = group["component"].map(diameters)
            group["route_type"] = route_type
            group["offshore_class"] = bool(offshore)
            rows.append(
                group[
                    [
                        "storage_idx",
                        "route_type",
                        "offshore_class",
                        "sink_region",
                        "longitude",
                        "latitude",
                        "grid_x",
                        "grid_y",
                        "sink_region_diameter_km",
                    ]
                ]
            )
    regions = pd.concat(rows, ignore_index=True)
    centers = (
        regions.groupby(["sink_region", "route_type", "offshore_class"], as_index=False)
        .agg(
            sink_region_lon=("longitude", "mean"),
            sink_region_lat=("latitude", "mean"),
            sink_region_node_count=("storage_idx", "nunique"),
        )
    )
    return regions.merge(
        centers, on=["sink_region", "route_type", "offshore_class"], how="left"
    )


def enrich_routes(
    routes: pd.DataFrame,
    clusters: pd.DataFrame,
    fleet: pd.DataFrame,
    source_regions: pd.DataFrame,
    regions: pd.DataFrame,
) -> pd.DataFrame:
    cluster_meta = clusters[["plant_id", "cluster_id", "hub_plant_idx"]].copy()
    fleet_meta = fleet[["plant_id", "province"]].copy()
    out = routes.drop(columns=["cluster_id"], errors="ignore").merge(
        cluster_meta, on="plant_id", how="left", validate="many_to_one"
    )
    out = out.merge(fleet_meta, on="plant_id", how="left", validate="many_to_one")
    out = out.merge(source_regions, on="plant_id", how="left", validate="many_to_one")
    out = out.merge(
        regions,
        left_on=["storage_idx", "route_type", "is_offshore"],
        right_on=["storage_idx", "route_type", "offshore_class"],
        how="left",
        validate="many_to_one",
    )
    return out


def aggregate_routes(df: pd.DataFrame, window: str, level: str) -> pd.DataFrame:
    use = df[df["year"].isin(WINDOWS[window])].copy()
    if level == "exact_route":
        keys = ["plant_id", "storage_idx", "route_type"]
    elif level == "source_region_to_storage_node":
        keys = ["source_region", "storage_idx", "route_type"]
    elif level == "source_region_to_storage_region":
        keys = ["source_region", "sink_region", "route_type"]
    elif level == "province_to_storage_region":
        keys = ["province", "sink_region", "route_type"]
    else:
        raise ValueError(level)

    def summarize(group: pd.DataFrame) -> pd.Series:
        flow = group["flow_mt"].sum()
        return pd.Series(
            {
                "flow_mt": flow,
                "source_count": group["plant_id"].nunique(),
                "sink_node_count_used": group["storage_idx"].nunique(),
                "flow_weighted_distance_km": (
                    np.average(group["distance_km"], weights=group["flow_mt"])
                    if flow > 0
                    else np.nan
                ),
                "origin_lon": np.average(group["plant_lon"], weights=group["flow_mt"]),
                "origin_lat": np.average(group["plant_lat"], weights=group["flow_mt"]),
                "sink_lon": np.average(group["sink_region_lon"], weights=group["flow_mt"]),
                "sink_lat": np.average(group["sink_region_lat"], weights=group["flow_mt"]),
            }
        )

    # Keep grouping columns inside each group because ``source_count`` still
    # needs plant_id when plant_id itself is part of the exact-route key.
    return use.groupby(keys, dropna=False).apply(summarize).reset_index()


def weighted_jaccard(a: pd.Series, b: pd.Series) -> tuple[float, float, float]:
    idx = a.index.union(b.index)
    av = a.reindex(idx, fill_value=0.0).to_numpy(float)
    bv = b.reindex(idx, fill_value=0.0).to_numpy(float)
    common = float(np.minimum(av, bv).sum())
    union = float(np.maximum(av, bv).sum())
    return (common / union if union else np.nan), common, union


def pairwise_overlap(aggregated: dict[str, pd.DataFrame], keys: list[str]) -> pd.DataFrame:
    pairs = [("S1", other) for other in ("S2", "S3", "S4", "S5")]
    rows = []
    for left, right in pairs:
        a = aggregated[left].set_index(keys)["flow_mt"]
        b = aggregated[right].set_index(keys)["flow_mt"]
        value, common, union = weighted_jaccard(a, b)
        rows.append(
            {
                "left_case": left,
                "right_case": right,
                "flow_weighted_jaccard": value,
                "common_flow_mt": common,
                "union_flow_mt": union,
                "left_total_flow_mt": float(a.sum()),
                "right_total_flow_mt": float(b.sum()),
            }
        )
    return pd.DataFrame(rows)


def corridor_matrix(
    aggregated: dict[str, pd.DataFrame], keys: list[str], cases: list[str]
) -> pd.DataFrame:
    parts = []
    for case in cases:
        part = aggregated[case][keys + ["flow_mt", "source_count", "sink_node_count_used",
                                         "flow_weighted_distance_km", "origin_lon", "origin_lat",
                                         "sink_lon", "sink_lat"]].copy()
        part["case"] = case
        parts.append(part)
    long = pd.concat(parts, ignore_index=True)
    flows = long.pivot_table(index=keys, columns="case", values="flow_mt", aggfunc="sum").fillna(0.0)
    sources = long.pivot_table(index=keys, columns="case", values="source_count", aggfunc="max").fillna(0)
    meta = (
        long.groupby(keys, as_index=True)
        .agg(
            mean_distance_km=("flow_weighted_distance_km", "mean"),
            origin_lon=("origin_lon", "mean"),
            origin_lat=("origin_lat", "mean"),
            sink_lon=("sink_lon", "mean"),
            sink_lat=("sink_lat", "mean"),
            sink_node_count_max=("sink_node_count_used", "max"),
        )
    )
    for case in cases:
        if case not in flows:
            flows[case] = 0.0
        if case not in sources:
            sources[case] = 0
    out = flows[cases].copy()
    out.columns = [f"flow_mt_{c}" for c in cases]
    for case in cases:
        out[f"source_count_{case}"] = sources[case].astype(int)
    flow_cols = [f"flow_mt_{c}" for c in cases]
    source_cols = [f"source_count_{c}" for c in cases]
    out["scenario_count"] = (out[flow_cols] > FLOW_TOL_MT).sum(axis=1)
    out["min_flow_mt_all_cases"] = out[flow_cols].min(axis=1)
    out["mean_flow_mt"] = out[flow_cols].mean(axis=1)
    out["min_source_count_all_cases"] = out[source_cols].min(axis=1)
    out["shared_in_all_cases"] = (
        (out["scenario_count"] == len(cases))
        & (out["min_source_count_all_cases"] >= 2)
    )
    out = out.join(meta)
    return out.reset_index().sort_values(
        ["scenario_count", "min_flow_mt_all_cases", "mean_flow_mt"],
        ascending=False,
    )


def coverage_table(
    matrix: pd.DataFrame, keys: list[str], aggregated: dict[str, pd.DataFrame], cases: list[str]
) -> pd.DataFrame:
    rows = []
    for threshold in FLOW_THRESHOLDS_MT:
        robust = matrix[
            matrix["shared_in_all_cases"]
            & (matrix["min_flow_mt_all_cases"] >= threshold)
        ]
        robust_keys = pd.MultiIndex.from_frame(robust[keys])
        for case in cases:
            agg = aggregated[case].set_index(keys)
            total = float(agg["flow_mt"].sum())
            selected = float(agg.reindex(robust_keys)["flow_mt"].fillna(0.0).sum())
            rows.append(
                {
                    "flow_threshold_mt": threshold,
                    "case": case,
                    "robust_corridor_count": len(robust),
                    "flow_on_robust_corridors_mt": selected,
                    "total_flow_mt": total,
                    "flow_coverage_share": selected / total if total else np.nan,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    runs = args.runs.resolve()
    out_dir = args.output_dir.resolve()
    base_cases, near_opt_cases = case_paths(runs)
    out_dir.mkdir(parents=True, exist_ok=True)
    storage, clusters, fleet = load_metadata()

    all_case_paths = {**base_cases, **near_opt_cases}
    raw_routes: dict[str, pd.DataFrame] = {}
    raw_json: dict[str, dict] = {}
    for case, path in all_case_paths.items():
        raw_routes[case], raw_json[case] = load_routes(case, path)

    audits = []
    for case, routes in raw_routes.items():
        route_total = float(routes["flow_mt"].sum())
        expected = 0.0
        weights = {int(k): float(v) for k, v in raw_json[case]["period_weights_years"].items()}
        for year_key, summary in raw_json[case]["summary"].items():
            expected += float(summary["commercial_captured_co2_kt"]) * weights[int(year_key)] / 1000.0
        gap = route_total - expected
        audits.append(
            {
                "check": "route_flow_conservation",
                "case": case,
                "observed": route_total,
                "expected": expected,
                "absolute_gap": gap,
                "status": "PASS" if abs(gap) <= 1e-5 else "FAIL",
            }
        )
        route_class = routes[["storage_idx", "is_offshore"]].drop_duplicates()
        canonical_class = storage[["storage_idx", "is_offshore"]].drop_duplicates()
        class_check = route_class.merge(
            canonical_class,
            on="storage_idx",
            how="left",
            suffixes=("_result", "_loader"),
            validate="many_to_one",
        )
        class_mismatch = int(
            (
                class_check["is_offshore_loader"].isna()
                | (
                    class_check["is_offshore_result"]
                    != class_check["is_offshore_loader"]
                )
            ).sum()
        )
        audits.append(
            {
                "check": "offshore_classification_consistency",
                "case": case,
                "observed": class_mismatch,
                "expected": 0,
                "absolute_gap": class_mismatch,
                "status": "PASS" if class_mismatch == 0 else "FAIL",
            }
        )

    overlap_rows = []
    sensitivity_rows = []
    candidate_outputs = []

    for radius_km in STORAGE_RADII_KM:
        regions = build_storage_regions(storage, radius_km)
        source_regions = build_source_regions(fleet, radius_km)
        source_regions.to_csv(
            out_dir / f"source_endpoint_regions_r{radius_km}.csv", index=False
        )
        regions.to_csv(
            out_dir / f"storage_endpoint_regions_r{radius_km}.csv", index=False
        )
        max_source_diameter = float(source_regions["source_region_diameter_km"].max())
        max_sink_diameter = float(regions["sink_region_diameter_km"].max())
        audits.extend(
            [
                {
                    "check": "source_region_diameter_bound",
                    "case": f"r{radius_km}",
                    "observed": max_source_diameter,
                    "expected": radius_km,
                    "absolute_gap": max(max_source_diameter - radius_km, 0.0),
                    "status": "PASS" if max_source_diameter <= radius_km + 1e-6 else "FAIL",
                },
                {
                    "check": "storage_region_diameter_bound",
                    "case": f"r{radius_km}",
                    "observed": max_sink_diameter,
                    "expected": radius_km,
                    "absolute_gap": max(max_sink_diameter - radius_km, 0.0),
                    "status": "PASS" if max_sink_diameter <= radius_km + 1e-6 else "FAIL",
                },
            ]
        )
        enriched = {
            case: enrich_routes(routes, clusters, fleet, source_regions, regions)
            for case, routes in raw_routes.items()
        }
        for case, df in enriched.items():
            missing_region = int(df["sink_region"].isna().sum())
            missing_cluster = int(df["cluster_id"].isna().sum())
            missing_province = int(df["province"].isna().sum())
            audits.extend(
                [
                    {
                        "check": "storage_region_coverage",
                        "case": f"{case}:r{radius_km}",
                        "observed": missing_region,
                        "expected": 0,
                        "absolute_gap": missing_region,
                        "status": "PASS" if missing_region == 0 else "FAIL",
                    },
                    {
                        "check": "source_metadata_coverage",
                        "case": f"{case}:r{radius_km}",
                        "observed": missing_cluster + missing_province,
                        "expected": 0,
                        "absolute_gap": missing_cluster + missing_province,
                        "status": "PASS" if missing_cluster + missing_province == 0 else "FAIL",
                    },
                ]
            )

        for window in WINDOWS:
            aggregated_by_level = {}
            for level in (
                "exact_route",
                "source_region_to_storage_node",
                "source_region_to_storage_region",
                "province_to_storage_region",
            ):
                aggregated = {
                    case: aggregate_routes(df, window, level)
                    for case, df in enriched.items()
                }
                aggregated_by_level[level] = aggregated
                if level == "exact_route":
                    keys = ["plant_id", "storage_idx", "route_type"]
                elif level == "source_region_to_storage_node":
                    keys = ["source_region", "storage_idx", "route_type"]
                elif level == "source_region_to_storage_region":
                    keys = ["source_region", "sink_region", "route_type"]
                else:
                    keys = ["province", "sink_region", "route_type"]

                pair = pairwise_overlap(aggregated, keys)
                pair.insert(0, "endpoint_radius_km", radius_km)
                pair.insert(1, "window", window)
                pair.insert(2, "aggregation_level", level)
                overlap_rows.append(pair)

                if level == "exact_route":
                    continue

                matrix = corridor_matrix(aggregated, keys, list(base_cases))
                matrix.insert(0, "endpoint_radius_km", radius_km)
                matrix.insert(1, "window", window)
                matrix.insert(2, "aggregation_level", level)
                coverage = coverage_table(matrix, keys, aggregated, list(base_cases))
                coverage.insert(0, "endpoint_radius_km", radius_km)
                coverage.insert(1, "window", window)
                coverage.insert(2, "aggregation_level", level)

                robust_all = matrix[matrix["shared_in_all_cases"]].copy()
                sensitivity_rows.append(
                    pd.DataFrame(
                        [
                            {
                                "endpoint_radius_km": radius_km,
                                "window": window,
                                "aggregation_level": level,
                                "flow_threshold_mt": threshold,
                                "robust_corridor_count": int(
                                    (robust_all["min_flow_mt_all_cases"] >= threshold).sum()
                                ),
                                "median_case_flow_coverage": float(
                                    coverage.loc[
                                        coverage["flow_threshold_mt"] == threshold,
                                        "flow_coverage_share",
                                    ].median()
                                ),
                                "min_case_flow_coverage": float(
                                    coverage.loc[
                                        coverage["flow_threshold_mt"] == threshold,
                                        "flow_coverage_share",
                                    ].min()
                                ),
                            }
                            for threshold in FLOW_THRESHOLDS_MT
                        ]
                    )
                )

                if radius_km == 100 and level == "source_region_to_storage_region":
                    # Add selected near-optimal support for the canonical candidate table.
                    near_matrix = corridor_matrix(aggregated, keys, list(all_case_paths))
                    core_flags = matrix[
                        keys
                        + [
                            "scenario_count",
                            "min_flow_mt_all_cases",
                            "min_source_count_all_cases",
                            "shared_in_all_cases",
                        ]
                    ].rename(
                        columns={
                            "scenario_count": "core_scenario_count",
                            "min_flow_mt_all_cases": "min_flow_mt_core_cases",
                            "min_source_count_all_cases": "min_source_count_core_cases",
                            "shared_in_all_cases": "shared_in_core_cases",
                        }
                    )
                    near_matrix = near_matrix.rename(
                        columns={
                            "scenario_count": "all_selected_scenario_count",
                            "min_flow_mt_all_cases": "min_flow_mt_all_selected_cases",
                            "min_source_count_all_cases": "min_source_count_all_selected_cases",
                            "shared_in_all_cases": "shared_in_all_selected_cases",
                        }
                    ).merge(core_flags, on=keys, how="left", validate="one_to_one")
                    near_matrix.insert(0, "endpoint_radius_km", radius_km)
                    near_matrix.insert(1, "window", window)
                    near_matrix.insert(2, "aggregation_level", level)
                    candidate_outputs.append(near_matrix)
                    coverage.to_csv(
                        out_dir / f"flow_coverage_r100_{window}_{level}.csv", index=False
                    )

    overlap = pd.concat(overlap_rows, ignore_index=True)
    sensitivity = pd.concat(sensitivity_rows, ignore_index=True)
    candidates = pd.concat(candidate_outputs, ignore_index=True)

    overlap.to_csv(out_dir / "pairwise_route_and_corridor_overlap.csv", index=False)
    sensitivity.to_csv(out_dir / "corridor_aggregation_sensitivity.csv", index=False)
    candidates.to_csv(out_dir / "corridor_candidates_r100_with_near_optimal.csv", index=False)
    audit_df = pd.DataFrame(audits)
    audit_df.to_csv(out_dir / "audit_checks.csv", index=False)

    # Compact evidence summary used by manuscript QA.
    full_cluster = sensitivity[
        (sensitivity["endpoint_radius_km"] == 100)
        & (sensitivity["window"] == "full_2025_2060")
        & (sensitivity["aggregation_level"] == "source_region_to_storage_region")
    ]
    early_cluster = sensitivity[
        (sensitivity["endpoint_radius_km"] == 100)
        & (sensitivity["window"] == "early_2025_2045")
        & (sensitivity["aggregation_level"] == "source_region_to_storage_region")
    ]
    pair_full = overlap[
        (overlap["endpoint_radius_km"] == 100)
        & (overlap["window"] == "full_2025_2060")
        & (
            overlap["aggregation_level"].isin(
                ["exact_route", "source_region_to_storage_region"]
            )
        )
        & (overlap["right_case"].isin(["S2", "S3"]))
    ]

    readme = f"""# Robust corridor opportunity post-processing

## Scope

The canonical model optimizes direct plant-to-storage flows and does not choose
shared trunk-pipeline topology. These outputs therefore identify **corridor
opportunity families**, not optimized or engineering-feasible shared pipelines.

Corridor family = bounded source endpoint zone × bounded storage endpoint zone
× storage type. Plant and storage endpoints are grouped with complete-linkage
clustering at 60/100/150 km maximum pairwise-separation thresholds. This avoids
both dependence on the model's broad descriptive plant clusters and the chain
merging of dense storage grids. A shared family must carry flow in all five core
scenarios and have at least two contributing plants in every scenario. Results
are tested at cumulative-flow floors of 1/5/10/20 Mt.

## Canonical 100-km bounded-endpoint screen

Full-period sensitivity rows:

{csv_block(full_cluster)}

Early-period sensitivity rows:

{csv_block(early_cluster)}

Exact-route versus aggregated-corridor overlap:

{csv_block(pair_full)}

## Interpretation rule

- If aggregation materially raises overlap and a non-trivial flow share remains
  on multi-source families across aggregation radii and flow floors, the paper
  may report robust **corridor opportunity zones** or **corridor reservation
  value**.
- It may not claim that a specific pipeline alignment, trunk diameter, or
  investment is robust, because those are not model decisions.
- A near-term build-out claim additionally requires recurrence in the
  2025-2045 window. Long-term cumulative recurrence alone supports reservation
  or option-preservation language, not immediate construction.

## Audit

PASS={int((audit_df['status'] == 'PASS').sum())}, FAIL={int((audit_df['status'] == 'FAIL').sum())}.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    print(readme)


if __name__ == "__main__":
    main()
