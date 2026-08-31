#!/usr/bin/env python3
"""Validate and fingerprint the final V4 inputs before paper runs."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "models" / "v4"))

from src_v4.config_v4 import config
from src_v4.data_loader_v4 import load_all
from src_v4.main import apply_scenario_modifications


OUTPUT_DIR = PROJECT_ROOT / "results" / "v4" / "final_protocol_validation"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_all()
    plants = data["plants"].copy()
    storage = data["storage"].copy()
    checks: list[dict] = []

    def record(check_id, condition, observed, expected, detail="", warning=False):
        status = "PASS" if condition else ("WARN" if warning else "FAIL")
        checks.append({
            "check_id": check_id,
            "status": status,
            "observed": observed,
            "expected": expected,
            "detail": detail,
        })

    # 2026-08-22 fleet-scope ruling: 1,572 inherited clinker-line records after
    # excluding one long-term-stopped line and one grinding-station record.
    # See fusion_2025/verified_fleet_scope_exclusions_20260822.csv.
    record("plant_count", len(plants) == 1572, len(plants), 1572)
    record(
        "plant_id_unique",
        plants["plant_id"].is_unique,
        int(plants["plant_id"].nunique()),
        len(plants),
    )
    coordinate_ledger_path = (
        PROJECT_ROOT
        / "data/model_input/plants/fusion_2025/verified_coordinate_corrections_20260828.csv"
    )
    coordinate_ledger = pd.read_csv(coordinate_ledger_path)
    coordinate_rows = coordinate_ledger[
        coordinate_ledger["action"].astype(str).str.startswith("CORRECT_TO")
    ].copy()
    label_rows = coordinate_ledger[
        coordinate_ledger["action"].astype(str).eq("LABEL_FIX")
    ].copy()
    record(
        "coordinate_ledger_20260828_scope",
        len(coordinate_rows) == 57 and len(label_rows) == 2,
        {"coordinate_updates": len(coordinate_rows), "label_updates": len(label_rows)},
        {"coordinate_updates": 57, "label_updates": 2},
    )
    plant_index = plants.set_index("plant_id")
    coordinate_mismatches = []
    for row in coordinate_rows.itertuples(index=False):
        plant_id = int(row.plant_id)
        if plant_id not in plant_index.index:
            coordinate_mismatches.append(f"missing:{plant_id}")
            continue
        if (
            abs(float(plant_index.at[plant_id, "longitude"]) - float(row.new_longitude)) > 1e-6
            or abs(float(plant_index.at[plant_id, "latitude"]) - float(row.new_latitude)) > 1e-6
        ):
            coordinate_mismatches.append(str(plant_id))
    record(
        "verified_coordinates_applied_to_active_fleet",
        not coordinate_mismatches,
        f"matched={57 - len(coordinate_mismatches)}/57",
        "57/57",
        ";".join(coordinate_mismatches[:20]),
    )

    plant_dir = PROJECT_ROOT / "data/model_input/plants"
    catchment = pd.read_csv(plant_dir / "plant_af_catchment.csv")
    tiers = pd.read_csv(plant_dir / "plant_location_tier.csv")
    clusters = pd.read_csv(plant_dir / "cluster_assignment.csv")
    whitelist = pd.read_csv(
        PROJECT_ROOT / "data/model_input/storage/cluster_sink_whitelist.csv"
    )
    expected_ids = set(plants["plant_id"].astype(int))
    derived_coverage_ok = all(
        len(frame) == 1572
        and frame["plant_id"].astype(int).is_unique
        and set(frame["plant_id"].astype(int)) == expected_ids
        for frame in (catchment, tiers, clusters)
    )
    record(
        "derived_plant_inputs_cover_active_fleet",
        derived_coverage_ok,
        {
            "af_catchment": len(catchment),
            "location_tier": len(tiers),
            "cluster_assignment": len(clusters),
        },
        "1,572 unique active plant IDs in each table",
    )
    cluster_coordinates = clusters.set_index("plant_id")[["longitude", "latitude"]]
    max_cluster_coordinate_gap = max(
        abs(float(cluster_coordinates.at[plant_id, field]) - float(plant_index.at[plant_id, field]))
        for plant_id in expected_ids
        for field in ("longitude", "latitude")
    )
    record(
        "cluster_coordinates_match_active_fleet",
        max_cluster_coordinate_gap <= 1e-9,
        max_cluster_coordinate_gap,
        "<=1e-9 degrees",
    )
    record(
        "spatial_cascade_expected_counts",
        clusters["cluster_id"].nunique() == 249 and len(whitelist) == 1145,
        {"clusters": int(clusters["cluster_id"].nunique()), "whitelist_pairs": len(whitelist)},
        {"clusters": 249, "whitelist_pairs": 1145},
        "Expected cascade from the verified 57-coordinate update; do not tune it away.",
    )
    missing_ef = int(plants[["source_process_ef", "source_fuel_ef"]].isna().any(axis=1).sum())
    record("plant_emission_factors_complete", missing_ef == 0, missing_ef, 0)
    record(
        "ccs_min_active_design_explicit",
        abs(float(config.CCS_PARAMS["min_active_design_kt"]) - 30.0) <= 1e-9,
        float(config.CCS_PARAMS["min_active_design_kt"]),
        "30 ktCO2/yr",
        "The threshold must be explicit in configuration, not supplied only by a builder fallback.",
    )
    missing_commission = int(pd.to_numeric(plants["commission_year"], errors="coerce").isna().sum())
    missing_ids = plants.loc[
        pd.to_numeric(plants["commission_year"], errors="coerce").isna(), "plant_id"
    ].astype(int).tolist()
    record(
        "commission_year_complete",
        missing_commission == 0,
        missing_commission,
        0,
        (
            f"Missing plant IDs: {missing_ids}; model fallback={config.PLANT_DEFAULT_COMMISSION_YEAR}"
            if missing_ids else "All commissioning years are populated."
        ),
        warning=True,
    )

    capacity = plants.set_index("plant_id")["capacity"] * config.CAPACITY_T_DAY_TO_KT_YR
    clinker_2025 = sum(
        float(capacity.loc[i]) * float(u)
        for i, u in data["baseyear_utilization"].items()
    )
    expected_clinker_2025 = (
        data["demand"][config.DEMAND_SCENARIO][2025]
        * 1000.0
        * data["national_clinker_ratio_path"][2025]
    )
    record(
        "baseyear_clinker_anchor_kt",
        abs(clinker_2025 - expected_clinker_2025) <= 0.01,
        round(clinker_2025, 6),
        round(expected_clinker_2025, 6),
    )
    max_province_gap = max(abs(float(v)) for v in data["baseyear_province_gap_kt"].values())
    record(
        "baseyear_max_province_gap_kt",
        max_province_gap <= 5.0,
        round(max_province_gap, 6),
        "<=5 kt",
        "The residual is caused by clipping Tianjin utilization at 1.0.",
    )
    af_rate_2025 = sum(data["baseyear_af_supply_ktce"].values()) / (
        clinker_2025 * config.TCE_PER_T_CLINKER
    )
    record(
        "baseyear_af_rate",
        abs(af_rate_2025 - config.INITIAL_AF_RATE) <= 1e-9,
        round(af_rate_2025, 10),
        config.INITIAL_AF_RATE,
    )

    record("storage_id_unique", storage["storage_idx"].is_unique, storage["storage_idx"].nunique(), len(storage))
    corrected_offshore = int((storage["offshore_box_candidate"] & ~storage["is_offshore"]).sum())
    record(
        "offshore_land_false_positives_removed",
        corrected_offshore > 0,
        corrected_offshore,
        ">0 corrected",
        f"Final offshore nodes={int(storage['is_offshore'].sum())}",
    )
    record(
        "storage_rate_constraint_evidence",
        bool(config.USE_STORAGE_RATE_CONSTRAINT),
        config.USE_STORAGE_RATE_CONSTRAINT,
        "weighted-average injection-rate raster required",
        "Only the DSA maximum-injection raster is available; cumulative capacity remains active.",
        warning=True,
    )

    all_routes = [
        (int(pid), int(sink), float(distance), str(sink_type).lower())
        for pid, routes in data["plant_storage"].items()
        for sink, distance, sink_type in routes
    ]
    routed_plants = {row[0] for row in all_routes}
    route_counts = pd.Series([row[0] for row in all_routes]).value_counts()
    route_protocol = {
        "cap_per_plant": int(config.NEAREST_SINKS_PER_PLANT),
        "nearest_per_type": int(config.NEAREST_SINKS_PER_TYPE),
        "large_capacity_quota": int(config.HIGH_CAPACITY_SINKS_PER_PLANT),
        "compatibility_mirror": int(config.CCS_PARAMS["nearest_storages"]),
    }
    record(
        "route_candidate_protocol_aligned",
        (route_protocol["cap_per_plant"] == 8
         and route_protocol["nearest_per_type"] == 3
         and route_protocol["large_capacity_quota"] == 2
         and route_protocol["compatibility_mirror"] == 8
         and int(route_counts.max()) <= 8),
        {**route_protocol, "observed_max_routes": int(route_counts.max())},
        "3 nearest/type + 2 high-capacity routes; deduplicated union capped at 8",
    )
    record(
        "plant_sink_distance_limit",
        max(row[2] for row in all_routes) <= config.TRANSPORT_MAX_KM + 1e-9,
        round(max(row[2] for row in all_routes), 6),
        f"<={config.TRANSPORT_MAX_KM} km",
    )
    record(
        "plants_without_sink_candidate",
        len(routed_plants) == len(plants),
        len(plants) - len(routed_plants),
        0,
        "These plants cannot deploy commercial CCS under the central 500 km route boundary.",
        warning=True,
    )
    route_types = {}
    for pid, sink, _, sink_type in all_routes:
        route_types.setdefault((pid, sink), set()).add(sink_type)
    dual_routes = sum(types == {"dsa", "eor"} for types in route_types.values())
    record("dual_dsa_eor_routes_preserved", dual_routes > 0, dual_routes, ">0")

    route_rows = pd.DataFrame(all_routes, columns=[
        "plant_id", "storage_idx", "distance_km", "sink_type"
    ])
    route_coverage = route_rows.groupby("plant_id").agg(
        candidate_routes=("storage_idx", "size"),
        nearest_sink_km=("distance_km", "min"),
        farthest_candidate_km=("distance_km", "max"),
        candidate_sink_types=("sink_type", lambda x: ";".join(sorted(set(x)))),
    ).reset_index()
    plant_sink_coverage = plants[[
        "plant_id", "province", "capacity", "longitude", "latitude"
    ]].merge(route_coverage, on="plant_id", how="left")
    plant_sink_coverage["ccs_route_eligible_500km"] = (
        plant_sink_coverage["candidate_routes"].fillna(0).gt(0)
    )
    plant_sink_coverage.to_csv(OUTPUT_DIR / "plant_sink_coverage.csv", index=False)

    corrected_storage = storage.loc[
        storage["offshore_box_candidate"] & ~storage["is_offshore"],
        ["storage_idx", "longitude", "latitude", "storage_type", "offshore_classification_method"],
    ]
    corrected_storage.to_csv(OUTPUT_DIR / "corrected_offshore_nodes.csv", index=False)

    demand_2025 = {name: float(path[2025]) for name, path in data["demand"].items()}
    record(
        "demand_2025_actual_consistency",
        len(set(demand_2025.values())) == 1 and next(iter(demand_2025.values())) == 1693.0,
        demand_2025,
        "all pathways=1693 Mt",
    )
    demand_order_ok = all(
        data["demand"]["d_high"][year]
        > data["demand"]["d_medium"][year]
        > data["demand"]["d_low"][year]
        for year in range(2026, 2061)
    )
    record(
        "demand_path_order_after_2025",
        demand_order_ok,
        demand_order_ok,
        "D-H > D-M > D-L for every year from 2026 to 2060",
    )
    record(
        "central_planning_case",
        config.DEMAND_SCENARIO == "d_medium" and config.CARBON_BUDGET_CASE == "B40",
        {"demand": config.DEMAND_SCENARIO, "budget": config.CARBON_BUDGET_CASE},
        {"demand": "d_medium", "budget": "B40"},
    )
    budgets = config.CARBON_BUDGET_CASES
    budget_order_ok = (
        budgets["B30"]["cumulative_budget_kt_year"]
        > budgets["B40"]["cumulative_budget_kt_year"]
        > budgets["B50"]["cumulative_budget_kt_year"]
        and budgets["B30"]["terminal_2060_cap_kt"]
        > budgets["B40"]["terminal_2060_cap_kt"]
        > budgets["B50"]["terminal_2060_cap_kt"]
    )
    record(
        "absolute_budget_case_order",
        budget_order_ok,
        {
            case: {
                "budget_kt_year": round(values["cumulative_budget_kt_year"], 3),
                "terminal_2060_cap_kt": round(values["terminal_2060_cap_kt"], 3),
            }
            for case, values in budgets.items()
        },
        "B30 > B40 > B50 for both cumulative and terminal limits",
    )
    baseyear_output = {
        int(plant_id): float(capacity.loc[plant_id]) * float(utilization)
        for plant_id, utilization in data["baseyear_utilization"].items()
    }
    total_baseyear_output = sum(baseyear_output.values())
    average_direct_ef = sum(
        baseyear_output[plant_id]
        * (
            data["plant_emission_factors"][plant_id]["proc_ef"]
            + data["plant_emission_factors"][plant_id]["fuel_ef"]
        )
        for plant_id in baseyear_output
    ) / total_baseyear_output
    reconstructed_reference_bau = sum(
        config.PERIOD_WEIGHTS[year]
        * data["demand"]["d_medium"][year]
        * 1000.0
        * config.BASELINE_CLINKER_RATIO
        * average_direct_ef
        for year in config.T_LIST
    )
    reconstructed_2025_reference = (
        data["demand"]["d_medium"][2025]
        * 1000.0
        * config.BASELINE_CLINKER_RATIO
        * average_direct_ef
    )
    reference_alignment_ok = (
        abs(reconstructed_reference_bau - config.REFERENCE_CUMULATIVE_BAU_KT_YEAR)
        <= 0.01
        and abs(
            reconstructed_2025_reference - config.REFERENCE_2025_DIRECT_EMISSIONS_KT
        ) <= 0.01
    )
    record(
        "fixed_budget_reference_alignment",
        reference_alignment_ok,
        {
            "cumulative_bau_kt_year": round(reconstructed_reference_bau, 6),
            "emissions_2025_kt": round(reconstructed_2025_reference, 6),
        },
        {
            "cumulative_bau_kt_year": config.REFERENCE_CUMULATIVE_BAU_KT_YEAR,
            "emissions_2025_kt": config.REFERENCE_2025_DIRECT_EMISSIONS_KT,
        },
        "Fails if final demand or plant emission inputs change without re-basing the fixed budgets.",
    )
    record("period_weight_horizon", sum(config.PERIOD_WEIGHTS.values()) == 35.0, sum(config.PERIOD_WEIGHTS.values()), 35.0)
    record("arm_external", config.ARM_ENDOGENOUS is False, config.ARM_ENDOGENOUS, False)
    active_arm_2060 = float(next(
        value for (province, year), value in data["process_adjustment"].items()
        if int(year) == 2060
    ))
    record(
        "arm_external_central_path",
        data["arm_path_case"] == "central" and abs(active_arm_2060 - 0.053457) <= 1e-9,
        {"case": data["arm_path_case"], "2060": active_arm_2060},
        {"case": "central", "2060": 0.053457},
    )
    record(
        "ee_external_central_path",
        data["ee_path_case"] == "central" and abs(data["ee_path"][2060] - 0.10) <= 1e-9,
        {"case": data["ee_path_case"], "2060": data["ee_path"][2060]},
        {"case": "central", "2060": 0.10},
    )
    record("pilot_not_target_credit", config.OBSERVED_PILOT_CCS_INCLUDE_IN_TARGET_ACCOUNTING is False, config.OBSERVED_PILOT_CCS_INCLUDE_IN_TARGET_ACCOUNTING, False)
    record("storage_rate_constraint_disabled", config.USE_STORAGE_RATE_CONSTRAINT is False, config.USE_STORAGE_RATE_CONSTRAINT, False)

    s2 = apply_scenario_modifications(copy.deepcopy(data), "S2_front_end")
    s2_base_unchanged = all(
        abs(s2["plant_af_access_ktce"][key] - value) <= 1e-9
        for key, value in data["plant_af_access_ktce"].items()
        if key[1] == 2025
    )
    record("s2_preserves_2025", s2_base_unchanged, s2_base_unchanged, True)

    s3 = apply_scenario_modifications(copy.deepcopy(data), "S3_all_spatial_equalized")
    s3_pool_gaps = {}
    provinces = sorted(plants["province"].astype(str).unique())
    for year in config.T_LIST:
        before = sum(data["province_af_pool_ktce"].get((p, year), 0.0) for p in provinces)
        after = sum(s3["province_af_pool_ktce"].get((p, year), 0.0) for p in provinces)
        s3_pool_gaps[year] = after - before
    record(
        "s3_preserves_national_af_pool",
        max(abs(v) for v in s3_pool_gaps.values()) <= 1e-6,
        {str(k): round(v, 9) for k, v in s3_pool_gaps.items()},
        "absolute gap<=1e-6 ktce",
    )

    s4 = apply_scenario_modifications(copy.deepcopy(data), "S4_storage_300km")
    record(
        "s4_direct_distance_filter",
        all(distance <= 300.0 for routes in s4["plant_storage"].values() for _, distance, _ in routes),
        s4["_plant_sink_pairs_after_filter"],
        f"all routes<=300 km; before={s4['_plant_sink_pairs_before_filter']}",
    )

    # Fingerprint every mutable table read by load_all(), plus the executable
    # model/code closure used by the submission batch. The earlier manifest
    # omitted plant_data.xlsx and the cluster tables, which allowed a passing
    # validation record to be detached from the exact active input state.
    input_paths = [
        ("data", config.PLANT_CSV),
        ("data", config.DATA_INPUT / "plants" / "plant_data.xlsx"),
        ("data", config.TIER_CSV),
        ("data", config.PLANT_SOURCE_XLSX),
        ("data", config.PLANT_CORRECTIONS_CSV),
        ("data", config.DATA_INPUT / "plants" / "cluster_assignment.csv"),
        ("data", config.DATA_INPUT / "storage" / "cluster_sink_whitelist.csv"),
        ("data", config.BASEYEAR_OUTPUT_CSV),
        ("data", config.EXTERNAL_TECH_PATH_CSV),
        ("data", config.EXTERNAL_TECH_SOURCE_CSV),
        ("data", config.SCM_CSV),
        ("data", config.PROCESS_ADJ_CSV),
        ("data", config.LIAO_CSV),
        ("data", config.AF_BIOMASS_CSV),
        ("data", config.AF_WASTE_CSV),
        ("data", config.DEMAND_XLSX),
        ("data", config.STORAGE_CSV),
        ("data", config.CHINA_LAND_GEOJSON),
        ("provenance", coordinate_ledger_path),
        ("provenance", PROJECT_ROOT / "data/model_input/plants/fusion_2025/coordinate_recheck_report_20260828.md"),
        ("provenance", PROJECT_ROOT / "scripts/shared/apply_verified_plant_coordinates_20260828.py"),
        ("model_code", PROJECT_ROOT / "models/v4/src_v4/config_v4.py"),
        ("model_code", PROJECT_ROOT / "models/v4/src_v4/data_loader_v4.py"),
        ("model_code", PROJECT_ROOT / "models/v4/src_v4/main.py"),
        ("model_code", PROJECT_ROOT / "models/v4/src_v4/model/final_builder.py"),
        ("model_code", PROJECT_ROOT / "models/v4/src_v4/counterfactual.py"),
        ("model_code", PROJECT_ROOT / "models/v4/src_v4/near_optimal_identity.py"),
        ("model_code", PROJECT_ROOT / "models/v4/src_v4/results/extract.py"),
        ("workflow", PROJECT_ROOT / "scripts/v4/run_tiered_batch_20260829.sh"),
        ("workflow", PROJECT_ROOT / "scripts/v4/audit_verified_submission_batch_20260822.py"),
        ("workflow", PROJECT_ROOT / "scripts/v4/analyze_capacity_feedback_counterfactual.py"),
        ("workflow", PROJECT_ROOT / "scripts/v4/analyze_storage_feedback_counterfactual.py"),
        ("workflow", PROJECT_ROOT / "paper/applied_energy_2026/archive/notes/balanced_solver_protocol_20260822.md"),
        ("workflow", Path(__file__).resolve()),
    ]
    missing_manifest_paths = [str(path) for _, path in input_paths if not path.is_file()]
    if missing_manifest_paths:
        raise FileNotFoundError(
            "Final provenance manifest contains missing files: "
            + "; ".join(missing_manifest_paths)
        )
    manifest = pd.DataFrame([
        {
            "kind": kind,
            "path": str(path.relative_to(PROJECT_ROOT)),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for kind, path in input_paths
    ])

    checks_df = pd.DataFrame(checks)
    checks_df.to_csv(OUTPUT_DIR / "final_input_checks.csv", index=False)
    manifest.to_csv(OUTPUT_DIR / "final_input_manifest.csv", index=False)
    summary = {
        "status_counts": checks_df["status"].value_counts().to_dict(),
        "plant_count": len(plants),
        "storage_node_count": len(storage),
        "offshore_node_count": int(storage["is_offshore"].sum()),
        "plant_sink_pair_count": len(all_routes),
        "routed_plant_count": len(routed_plants),
        "period_weight_years": sum(config.PERIOD_WEIGHTS.values()),
        "demand_scenario": config.DEMAND_SCENARIO,
        "carbon_budget_case": config.CARBON_BUDGET_CASE,
        "cumulative_budget_kt_year": config.CARBON_BUDGET_CASES[
            config.CARBON_BUDGET_CASE
        ]["cumulative_budget_kt_year"],
        "terminal_2060_cap_kt": config.CARBON_BUDGET_CASES[
            config.CARBON_BUDGET_CASE
        ]["terminal_2060_cap_kt"],
        "baseyear_clinker_mt": clinker_2025 / 1000.0,
        "baseyear_af_rate": af_rate_2025,
        "unresolved_items": checks_df.loc[checks_df["status"].eq("WARN"), "detail"].tolist(),
    }
    with (OUTPUT_DIR / "final_input_validation_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(checks_df.to_string(index=False))
    print(f"\nValidation artifacts: {OUTPUT_DIR}")
    return 1 if checks_df["status"].eq("FAIL").any() else 0


if __name__ == "__main__":
    raise SystemExit(main())
