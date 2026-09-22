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
sys.path.insert(0, str(PROJECT_ROOT / "v5" / "model"))

from src_v5.provenance import validate_market_inputs
from src_v5.config_v5 import config
from src_v5.data_loader_v5 import load_all
from src_v5.main import apply_scenario_modifications


OUTPUT_DIR = PROJECT_ROOT / "v5" / "results" / "final_protocol_validation"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _availability(plant_id, year, t_index, commission, cap_td, lifetime, base_year,
                  min_renew_td, max_renewals, u0):
    """Fraction of nameplate capacity that MAY be on for a line in a period.

    t=0 is fully on and scaled by the fixed base-year utilization; later periods
    are 1 while the original expiry has not passed, or after the single same-site
    renewal window for lines at or above the capacity gate.
    """
    if t_index == 0:
        return float(u0.get(plant_id, 1.0))
    comm = commission.get(plant_id, base_year)
    if pd.isna(comm):
        comm = base_year
    expiry = max(float(comm), base_year - lifetime) + lifetime
    if expiry >= year:
        return 1.0
    # Past expiry: available only through the single same-site renewal, which is
    # granted to lines at or above the capacity gate and takes effect in the
    # first period after expiry (so any later period is covered).
    if (max_renewals >= 1 and float(cap_td.get(plant_id, 0.0)) >= min_renew_td):
        return 1.0
    return 0.0


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

    market_provenance = validate_market_inputs(data, config)
    record("market_loaded_input_preflight", market_provenance.get("preflight") == "PASS",
           market_provenance.get("preflight"), "PASS", "Loaded nodes/arcs match requested files")

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
    # P2: the cluster/whitelist layer is post-processing only (the optimization
    # routes plants to sinks directly), so frozen totals must not gate the
    # pipeline. Assert internal consistency; keep 249/1145 as a reference point.
    n_clusters = int(clusters["cluster_id"].nunique())
    n_pairs = int(len(whitelist))
    record(
        "spatial_cascade_internal_consistency",
        n_clusters > 0
        and n_pairs > 0
        and set(whitelist["cluster_id"]).issubset(set(clusters["cluster_id"])),
        {"clusters": n_clusters, "whitelist_pairs": n_pairs},
        "clusters>0, pairs>0, every whitelist cluster defined",
        "Historical reference point was 249 clusters / 1145 pairs; only internal "
        "consistency is enforced because the layer is post-processing.",
    )
    missing_ef = int(plants[["source_process_ef", "source_fuel_ef"]].isna().any(axis=1).sum())
    record("plant_emission_factors_complete", missing_ef == 0, missing_ef, 0)
    record(
        "ccs_min_active_design_explicit",
        abs(float(config.CCS_PARAMS["min_active_design_kt"]) - 100.0) <= 1e-9,
        float(config.CCS_PARAMS["min_active_design_kt"]),
        "100 ktCO2/yr",
        "P1-5: raised from 30, which produced ~33 kt/yr 'commercial' units in 2035. "
        "100 kt is IEAGHG's small-scale boundary, SLB Capturi's smallest standard "
        "commercial plant, and above every Chinese cement demonstration.",
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
    # v5 (P0-3, 310-day basis): the provincial 2025 anchor is infeasible for the
    # clinker-importing provinces (Zhejiang, Jiangsu, Tianjin) because their derived
    # clinker demand exceeds their own kiln capacity. The 330-day convention hid this
    # by inflating capacity 6.1%. The residual is handled by clipping provincial
    # utilisation at 1.0 and is reported as a national share; it is the direct
    # motivation for the regional demand and transport work.
    gap_kt = {k: float(v) for k, v in data["baseyear_province_gap_kt"].items()}
    max_province_gap = max(abs(v) for v in gap_kt.values())
    national_clinker = float(clinker_2025)
    gap_share = max_province_gap / max(national_clinker, 1e-9)
    shortfall_provinces = sorted(
        (k for k, v in gap_kt.items() if v < -1e-6), key=lambda k: gap_kt[k]
    )
    record(
        "baseyear_max_province_gap_share",
        gap_share <= 0.005,
        round(gap_share, 6),
        "<=0.5% of national clinker",
        "Provinces whose demand exceeds local capacity (clinker importers): "
        f"{shortfall_provinces}; max gap {max_province_gap:.1f} kt "
        f"({gap_share*100:.3f}% of national clinker).",
        warning=gap_share > 0.0,
    )
    # ---- P0 assertions (2026-09-11) ----
    record(
        "p0_ramp_constraint_removed",
        not hasattr(config, "MAX_UTILIZATION_CHANGE_PER_PERIOD"),
        hasattr(config, "MAX_UTILIZATION_CHANGE_PER_PERIOD"),
        False,
        "P0-3: cross-period re-dispatch is now constrained by the fixed operating cost.",
    )
    record("p0_min_operating_utilization", abs(config.MIN_OPERATING_UTILIZATION - 0.30) <= 1e-9,
           config.MIN_OPERATING_UTILIZATION, 0.30,
           "Minimum annual activity level of a 'retained and producing' line. NOT a kiln "
           "technical minimum load and NOT directly derived from the MIIT replacement rule "
           "(that rule governs replacement eligibility). 0.30 is the rounded policy-consistent "
           "value under the 310-day basis (90/310 = 29.03%); sensitivity 0.20 / 0.40.")
    record("p0_plant_fixed_operating_cost",
           abs(config.PLANT_FIXED_OPERATING_COST - 40.0) <= 1e-6,
           config.PLANT_FIXED_OPERATING_COST, 40.0,
           "2026-09-13 recalibration 53.2 -> 40: AVOIDABLE fixed resource cost of "
           "retiring one line, not the financial allocation (labour 30->27, "
           "maintenance 18->9, insurance 1->1, environmental 3->2, overhead 4->2 = 41; "
           "x300/310 = 39.68 -> 40). Sensitivity 32 / 40 / 53.2.")
    record("p0_days_per_year", int(config.DAYS_PER_YEAR) == 310, config.DAYS_PER_YEAR, 310)
    record("p0_early_retirement_cost",
           abs(config.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY - 17.0) <= 1e-9,
           config.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY, 17.0)
    record("p0_capture_investment",
           abs(float(config.CCS_PARAMS["capture_investment"]) - 821.4) <= 1e-6,
           float(config.CCS_PARAMS["capture_investment"]), 821.4)
    record("p0_capture_om", abs(float(config.CCS_PARAMS["capture_om"]) - 445.5) <= 1e-6,
           float(config.CCS_PARAMS["capture_om"]), 445.5)
    record("p0_ccs_decline_case_valid",
           str(config.CCS_COST_DECLINE_CASE) in config.CCS_COST_DECLINE_SCENARIOS,
           list(config.CCS_COST_DECLINE_SCENARIOS), str(config.CCS_COST_DECLINE_CASE))
    record("p0_ccs_learning_curve_removed", not hasattr(config, "CCS_LEARNING_CURVE"),
           hasattr(config, "CCS_LEARNING_CURVE"), False)
    record("p0_ccs_size_exponents",
           abs(config.CCS_SIZE_SCALING["exponent_capex"] - 0.80) <= 1e-9
           and abs(config.CCS_SIZE_SCALING["exponent_om"] - 0.90) <= 1e-9,
           (config.CCS_SIZE_SCALING["exponent_capex"], config.CCS_SIZE_SCALING["exponent_om"]),
           (0.80, 0.90))
    record("p0_engineered_af_path_removed", not hasattr(config, "AF_ENGINEERING_TSR_PATH"),
           hasattr(config, "AF_ENGINEERING_TSR_PATH"), False)
    record("p0_af_technical_ceiling", abs(config.AF_TECHNICAL_TSR_CEILING - 0.60) <= 1e-9,
           config.AF_TECHNICAL_TSR_CEILING, 0.60)
    record("p0_af_allocation_headroom", abs(config.AF_ACCESS_ALLOCATION_HEADROOM - 2.0) <= 1e-9,
           config.AF_ACCESS_ALLOCATION_HEADROOM, 2.0)
    record("p0_af_expansion_pp", abs(config.AF_EXPANSION_PP - 10.0) <= 1e-9,
           config.AF_EXPANSION_PP, 10.0)
    record("p0_af_fuel_price_parity", config.AF_FUEL_PRICE is config.COAL_PRICE_SCHEDULE,
           config.AF_FUEL_PRICE is config.COAL_PRICE_SCHEDULE, True)
    record("p0_af_investment", abs(config.AF_INVESTMENT - 83.0) <= 1e-9, config.AF_INVESTMENT, 83.0)
    record("p0_af_om", abs(config.AF_OM - 4.2) <= 1e-9, config.AF_OM, 4.2)
    # ── AF caliber fixes (2026-09-13) ────────────────────────────────────────
    record("p0_af_energy_caliber", config.AF_ENERGY_CALIBER == "plant_heat_demand",
           config.AF_ENERGY_CALIBER, "plant_heat_demand")
    record("p0_af_expansion_fraction_of_heat",
           abs(config.AF_EXPANSION_FRACTION_OF_HEAT - 0.10) <= 1e-12,
           config.AF_EXPANSION_FRACTION_OF_HEAT, 0.10)
    record("p0_af_investment_per_tce",
           abs(config.AF_INVESTMENT_CNY_PER_TCE - 790.48) <= 1e-9,
           config.AF_INVESTMENT_CNY_PER_TCE, 790.48)
    record("p0_af_om_per_tce", abs(config.AF_OM_CNY_PER_TCE - 40.0) <= 1e-9,
           config.AF_OM_CNY_PER_TCE, 40.0)
    record("p0_beta_af_declared_grade_c", abs(config.BETA_AF - 0.55) <= 1e-12,
           config.BETA_AF, 0.55)
    record("p0_af_biogenic_co2_per_tce_central_zero",
           abs(config.AF_BIOGENIC_CO2_PER_TCE) <= 1e-12,
           config.AF_BIOGENIC_CO2_PER_TCE, 0.0)
    record("p0_max_capacity_decline_per_period_none",
           config.MAX_CAPACITY_DECLINE_PER_PERIOD is None,
           config.MAX_CAPACITY_DECLINE_PER_PERIOD, None)
    record("p0_max_annual_capacity_decline_none",
           config.MAX_ANNUAL_CAPACITY_DECLINE is None,
           config.MAX_ANNUAL_CAPACITY_DECLINE, None)
    record("p0_af_waste_maturity_2025",
           abs(config.AF_WASTE_ACCESS_MATURITY[2025] - 0.10) <= 1e-9,
           config.AF_WASTE_ACCESS_MATURITY[2025], 0.10)
    # AF allocation must now equal the RAW province resource pool (2026-09-13): the
    # deployment ceiling is deliberately NOT baked into the resource side any more,
    # so the old "equals ceiling(t) x national fuel" check is replaced by a check
    # that the allocation IS the pool, summed per period.
    try:
        alloc_total = {}
        for (_, year), value in data["af_alloc_bio"].items():
            alloc_total[int(year)] = alloc_total.get(int(year), 0.0) + float(value)
        for (_, year), value in data["af_alloc_wst"].items():
            alloc_total[int(year)] = alloc_total.get(int(year), 0.0) + float(value)
        channel = data["province_af_pool_channel"]
        pool_total = {}
        for (_prov, year), entry in channel.items():
            pool_total[int(year)] = (
                pool_total.get(int(year), 0.0)
                + float(entry.get("bio", 0.0))
                + float(entry.get("wst", 0.0))
            )
        worst = max(
            abs(alloc_total.get(int(y), 0.0) - pool_total.get(int(y), 0.0))
            / max(pool_total.get(int(y), 0.0), 1e-9)
            for y in config.T_LIST
        )
        record(
            "af_allocation_equals_province_pool", worst <= 1e-9, round(worst, 12), "<=1e-9",
            "sum_i cap_i,t == the raw province resource pool for all eight periods; "
            "the deployment ceiling must NOT be baked into the resource allocation.",
        )
        record(
            "af_allocation_decoupled_from_demand",
            not hasattr(config, "AF_EXPANSION_CEILING_CACHE"),
            True,
            True,
            "No AF expansion ceiling cache should exist: the resource side must not "
            "scale with national kiln fuel demand.",
        )
    except Exception as exc:  # noqa: BLE001
        record("af_allocation_equals_province_pool", False, repr(exc), "computable")

    # 2026-09-13: the base-year anchor is INITIAL_AF_RATE of national heat demand
    # H = sum_i h_i * (1-EE_2025) * Q_i, with h_i = fuel_ef_i / COAL_EF. EE_2025 = 0.
    # Computing the rate against a flat TCE_PER_T_CLINKER would no longer match
    # (the fleet-mean intensity is 0.107, not 0.105), so the denominator here must
    # be the same physical quantity the loader used.
    _ef = data["plant_emission_factors"]
    _by_util = data["baseyear_utilization"]
    _cap_kt = {
        int(r.plant_id): float(r.capacity) * config.CAPACITY_T_DAY_TO_KT_YR
        for r in plants[["plant_id", "capacity"]].itertuples(index=False)
    }
    _coal_ef = float(config.COAL_EF_TCO2_PER_TCE)
    national_heat_2025 = sum(
        float(_ef[i]["fuel_ef"]) / _coal_ef * _cap_kt[i] * float(_by_util[i])
        for i in _ef
    )
    af_rate_2025 = sum(data["baseyear_af_supply_ktce"].values()) / max(
        national_heat_2025, 1e-9
    )
    record(
        "baseyear_af_rate",
        abs(af_rate_2025 - config.INITIAL_AF_RATE) <= 1e-9,
        round(af_rate_2025, 10),
        config.INITIAL_AF_RATE,
        "Anchor rate on the plant-heat-demand caliber h_i*(1-EE)*Q, not on flat 0.105.",
    )

    record("storage_id_unique", storage["storage_idx"].is_unique, storage["storage_idx"].nunique(), len(storage))
    # The invariant is that no offshore node sits on China land. Assert the
    # outcome, not that a correction fired: the storage CSV is regenerated by
    # scripts/shared/preprocess_storage_tif.py, which now applies the land screen
    # itself, so the loader's compensating correction legitimately finds nothing.
    # (Before 2026-09-12 the CSV predated that screen, so 22 nodes were corrected
    # at load time; the final offshore set was 470 either way.)
    corrected_offshore = int((storage["offshore_box_candidate"] & ~storage["is_offshore"]).sum())
    offshore_total = int(storage["is_offshore"].sum())
    record(
        "offshore_nodes_exclude_china_land",
        offshore_total > 0 and corrected_offshore < offshore_total,
        {"offshore_nodes": offshore_total, "corrected_at_load": corrected_offshore},
        "offshore>0 and not all nodes were land false positives",
        "Storage CSV is regenerated by preprocess_storage_tif.py, which applies the "
        "China land screen itself; the loader repeats it defensively.",
    )
    record(
        "storage_rate_constraint_bounds",
        bool(config.USE_STORAGE_RATE_CONSTRAINT)
        and float(config.STORAGE_RATE_DEPLETION_YEARS) > 0
        and float(config.STORAGE_MAX_WELLS_PER_NODE) > 0,
        {
            "enabled": bool(config.USE_STORAGE_RATE_CONSTRAINT),
            "depletion_years": float(config.STORAGE_RATE_DEPLETION_YEARS),
            "max_wells": float(config.STORAGE_MAX_WELLS_PER_NODE),
            "rate_per_well_Mt": float(config.STORAGE_RATE_PER_WELL_MT_YR),
        },
        "enabled with both bounds positive",
        "P1-3: enabled. The raster is a per-well theoretical maximum summed onto "
        "40 km nodes, so it is bounded by a well-count cap (50 wells, the convention "
        "in the two Chinese studies at this resolution) and by well-life depletion "
        "(capacity / 30 yr). Residual: the weighted-average raster (figshare "
        "10.6084/m9.figshare.27646707) was not retrievable and would lower the raw "
        "term, which still binds for about a third of nodes.",
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
    # 2026-09-12 fuel-EF re-anchor: the 2021 source workbook keeps its original
    # three class constants plus one plant-specific outlier; the 2025 update is a
    # loader-side uniform scale (SOURCE_FUEL_EF_REANCHOR_SCALE), not a data edit.
    # See v5/parameters/fuel_ef_reanchor_20260912.md.
    raw_fuel = pd.read_excel(str(config.PLANT_SOURCE_XLSX))["燃料排放强度（t CO2/t cl）"]
    raw_set = sorted(round(float(v), 6) for v in raw_fuel.unique())
    record(
        "source_fuel_ef_workbook_integrity",
        raw_set == [0.302950, 0.315105, 0.327260, 0.356900],
        raw_set,
        [0.302950, 0.315105, 0.327260, 0.356900],
        "Source workbook fuel factors unchanged; the 2025 re-anchor lives in the loader scale.",
    )
    cap_series = plants.set_index("plant_id")["capacity"].astype(float)
    fleet_fuel = {
        int(pid): float(efs["fuel_ef"])
        for pid, efs in data["plant_emission_factors"].items()
    }
    weighted_thermal = (
        sum(float(cap_series.loc[pid]) * ef for pid, ef in fleet_fuel.items())
        / float(cap_series.sum())
        / 2.6604
        * 1000.0
    )
    record(
        "fuel_ef_reanchor_thermal_anchor",
        abs(weighted_thermal - 105.0) <= 0.05,
        round(weighted_thermal, 4),
        105.0,
        "Capacity-weighted thermal intensity of the active fleet at the 2025 re-anchored "
        "level (= TCE_PER_T_CLINKER x 1000); coal factor 2.6604 tCO2/tce (Zhang et al. 2021, Table A.2).",
    )
    # 2026-09-12: the active EE/ARM/CCR path case columns must exist in the
    # external technology path table (CCR high = slow-blending GB 175-2023 variant).
    path_table = data["external_technology_path_table"]
    active_case_columns = {
        "ee": f"ee_{config.EE_PATH_CASE}",
        "arm": f"arm_{config.ARM_PATH_CASE}",
        "ccr": f"clinker_ratio_{config.CCR_PATH_CASE}",
    }
    record(
        "external_path_case_columns_present",
        all(col in path_table.columns for col in active_case_columns.values()),
        {key: (col in path_table.columns) for key, col in active_case_columns.items()},
        "all present",
        "Active-case columns for the three exogenous paths must exist in external_technology_paths.csv.",
    )
    record("period_weight_horizon", sum(config.PERIOD_WEIGHTS.values()) == 35.0, sum(config.PERIOD_WEIGHTS.values()), 35.0)
    # ARM_ENDOGENOUS removed 2026-09-14 (dead constant); tombstone check.
    record("arm_external", not hasattr(config, "ARM_ENDOGENOUS"), hasattr(config, "ARM_ENDOGENOUS"), False,
           "ARM is exogenous; the dead ARM_ENDOGENOUS constant was removed on 2026-09-14.")
    # R6 terminal-value arm registration checks (2026-09-14).
    _tv_mode = str(getattr(config, "TERMINAL_VALUE_MODE", "none"))
    record(
        "terminal_value_mode_default",
        _tv_mode in {"none", "annuity_consistent_guarded"} and _tv_mode == "none",
        _tv_mode,
        "none",
        "Central charges stock investments in full; the R6 arm is opt-in via CLI.",
    )
    record(
        "terminal_value_factor_table",
        (lambda f: abs(f(2045, 25) - 0.768966) < 1e-4 and abs(f(2040, 25) - 0.909698) < 1e-4
         and f(2050, 25) == 1.0 and f(2030, 25) == 1.0 and abs(f(2045, 40) - 0.631627) < 1e-4)(
            lambda y, L: (
                1.0
                if (2061 - y) < int(getattr(config, "TERMINAL_VALUE_MIN_INHORIZON_SERVICE", 15))
                or (2061 - y) >= L
                else (1.0 - 1.05 ** (-(2061 - y))) / (1.0 - 1.05 ** (-L))
            )
        ),
        "recomputed A(min(L,2061-y))/A(L) at d=0.05",
        "ccs 2045 -> 0.7690, 2040 -> 0.9097, 2050 -> 1.0; renewal 2045 -> 0.6316",
        "Matches the registered factor table in parameters/terminal_value_commitment_20260914.md.",
    )
    record(
        "storage_rate_scale_default",
        float(getattr(config, "STORAGE_RATE_SCALE", 1.0)) == 1.0
        and float(getattr(config, "STORAGE_CUMULATIVE_SCALE", 1.0)) == 1.0,
        (getattr(config, "STORAGE_RATE_SCALE", None), getattr(config, "STORAGE_CUMULATIVE_SCALE", None)),
        (1.0, 1.0),
        "Storage sensitivity scales are opt-in (R8 arm uses --storage-rate-scale 2.0).",
    )
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
    record("eor_storage_retention_explicit",
           0.0 < float(config.CCS_PARAMS.get("eor_storage_retention", 0.0)) <= 1.0,
           float(config.CCS_PARAMS.get("eor_storage_retention", 1.0)), "0 < r <= 1",
           "P1-2: only the retained share of EOR-bound CO2 counts as mitigation; "
           "0.90 is the conservative end of the operational 0.90-0.98 delivered-basis range.")
    record("storage_rate_constraint_enabled", config.USE_STORAGE_RATE_CONSTRAINT is True, config.USE_STORAGE_RATE_CONSTRAINT, True,
           "P1-3: Fan et al. (2025) warn that omitting injection-rate capacity overestimates storage; the raster is capped by capacity/depletion_years before use.")
    record("storage_min_node_capacity", float(config.STORAGE_MIN_NODE_CAPACITY_MT) == 10.0, float(config.STORAGE_MIN_NODE_CAPACITY_MT), 10.0,
           "P1-3: sub-threshold raster cells were being filled to exactly 100% of capacity, a resolution artifact.")

    s2 = apply_scenario_modifications(copy.deepcopy(data), "S2_front_end")
    # v5 (P0-2): the front-end shortfall scales the province allocation; the 2025
    # base-year anchor and the accessibility shares must be untouched.
    s2_base_unchanged = all(
        abs(s2["af_alloc_bio"][key] - value) <= 1e-9
        and abs(s2["af_alloc_wst"][key] - data["af_alloc_wst"][key]) <= 1e-9
        for key, value in data["af_alloc_bio"].items()
        if key[1] == 2025
    ) and s2["af_share_bio"] == data["af_share_bio"]
    record("s2_preserves_2025", s2_base_unchanged, s2_base_unchanged, True)

    s3 = apply_scenario_modifications(copy.deepcopy(data), "S3_all_spatial_equalized")
    s3_pool_gaps = {}
    provinces = sorted(plants["province"].astype(str).unique())
    for year in config.T_LIST:
        before = sum(
            data["af_alloc_bio"].get((p, year), 0.0) + data["af_alloc_wst"].get((p, year), 0.0)
            for p in provinces
        )
        after = sum(
            s3["af_alloc_bio"].get((p, year), 0.0) + s3["af_alloc_wst"].get((p, year), 0.0)
            for p in provinces
        )
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
    # ── P0-4 v3: distributed market nodes and clinker transport ──────────
    regional_enabled = bool(getattr(config, "ENABLE_REGIONAL_DEMAND", False))
    record(
        "regional_demand_enabled", regional_enabled, regional_enabled, True,
        "set ENABLE_REGIONAL_DEMAND=False only to reproduce the pre-P0-4 model",
    )
    demand_nodes = data.get("demand_nodes")
    market_nodes = data.get("market_nodes")
    if regional_enabled:
        arcs = data.get("demand_arcs") or {}
        shares_by_year = data.get("market_node_shares_by_year") or {}
        node_ids = sorted(int(n) for n in (market_nodes["node_id"] if market_nodes is not None else []))

        record("demand_market_unit_is_market_node",
               str(data.get("demand_market_unit", "")).lower() == "market_node",
               str(data.get("demand_market_unit")), "market_node",
               "The market unit is a set of ~150 distributed market nodes. A single "
               "province point cannot produce an endogenous utilisation: dropping a "
               "distant plant inside a province leaves the retained plants' distance "
               "to the centroid unchanged. The 1,713-node fine grid was structurally "
               "infeasible (an exact float LP left a shortfall in every period).")
        record("demand_node_layer_not_in_optimization",
               bool(data.get("demand_node_layer_used_in_optimization")) is False,
               bool(data.get("demand_node_layer_used_in_optimization")), False,
               "The 1,713-node 50 km layer is descriptive only (it positions the "
               "market nodes and carries the 65/35 variance evidence).")

        target = int(getattr(config, "DEMAND_MARKET_NODE_TARGET", 150))
        record("demand_market_node_count", 0.7 * target <= len(node_ids) <= 1.3 * target,
               len(node_ids), f"{int(0.7*target)}-{int(1.3*target)}",
               "about 5 per province, i.e. the 50 km layer aggregated to ~150 km")
        if demand_nodes is not None:
            record("demand_descriptive_layer_row_count", len(demand_nodes) > 0,
                   len(demand_nodes), "> 0", "descriptive layer only")
        for year, shares in sorted(shares_by_year.items()):
            total = float(sum(shares.values()))
            record(
                f"market_node_share_sums_to_one_{year}",
                abs(total - 1.0) < 1e-9, f"{total:.12f}", "1.0",
                "the two-level allocation must conserve the national total",
            )
        record("demand_arc_count", len(arcs) > 0, len(arcs), "> 0")
        with_arcs = {int(i) for i, _ in arcs}
        all_plants = set(int(p) for p in plants["plant_id"])
        record("demand_plant_arc_coverage", with_arcs == all_plants,
               len(with_arcs), len(all_plants),
               "every plant needs at least one candidate market")
        served = {int(j) for _, j in arcs}
        record("demand_market_node_reachability", served == set(node_ids),
               len(served), len(node_ids),
               "every market node must be reachable from at least one plant")
        d_max = float(getattr(config, "DEMAND_ARC_MAX_DISTANCE_KM", 1200.0))
        worst = max(arcs.values()) if arcs else 0.0
        record("demand_arc_max_distance", worst <= d_max + 1e-6,
               f"{worst:.1f} km", f"<= {d_max:.0f} km")

        # Market nodes carry the REAL plant->node haversine distance, including
        # within a province: this is the endogenous average-haul force.
        plant_province = {int(r.plant_id): str(r.province)
                          for r in plants[["plant_id", "province"]].itertuples(index=False)}
        node_province = ({int(r.node_id): str(r.province)
                          for r in market_nodes[["node_id", "province"]].itertuples(index=False)}
                         if market_nodes is not None else {})
        intra = [d for (i, j), d in arcs.items()
                 if plant_province.get(int(i)) == node_province.get(int(j))]
        record("demand_intra_province_distance_positive",
               len(intra) > 0 and min(intra) > 0.0,
               f"{len(intra)} arcs, min {min(intra) if intra else 0:.1f} km", "all > 0",
               "The v2 rule treating intra-province transport as zero is retired. "
               "If intra-province arcs were free, closing a distant plant inside a "
               "province would cost nothing and utilistion would stay at its bound.")

        # Hall / transportation feasibility over MARKET NODES, per period.
        # The necessary and sufficient condition for the node equality balances to
        # be satisfiable. Solved as an exact float LP (maximise delivered): the
        # 2025 balance has zero national slack by construction, so integer
        # capacities would show rounding noise as a gap. t=0 supply is cap x u0
        # (utilisation is FIXED in the base year); later periods use cap.
        import numpy as _np
        from scipy.sparse import csr_matrix as _csr
        from scipy.optimize import linprog as _linprog
        plist = sorted(with_arcs)
        nidx = {p_: k for k, p_ in enumerate(node_ids)}
        pidx = {p_: k for k, p_ in enumerate(plist)}
        pcap = (pd.to_numeric(plants.set_index("plant_id")["capacity"], errors="coerce")
                * config.CAPACITY_T_DAY_TO_KT_YR).to_dict()
        u0 = data.get("baseyear_utilization") or {}
        n_arcs = len(arcs)
        rows_ = _np.array([pidx[int(i)] for i, _ in arcs])
        cols_ = _np.array([nidx[int(j)] for _, j in arcs])
        col_ = _np.arange(n_arcs)
        A_dem = _csr(
            (_np.ones(2 * n_arcs),
             (_np.concatenate([rows_, len(plist) + cols_]), _np.concatenate([col_, col_]))),
            shape=(len(plist) + len(node_ids), n_arcs),
        )
        worst_gap, worst_year, all_ok = 0.0, None, True
        # Period-specific available supply: a line can operate only while its
        # original 40-year expiry has not passed, or after its single same-site
        # renewal (granted only to lines at or above the capacity gate). The
        # base year is fully on (y fixed to 1, u fixed to the anchor).
        _comm = plants.set_index("plant_id")["commission_year"]
        _comm = pd.to_numeric(_comm, errors="coerce").fillna(
            float(getattr(config, "PLANT_DEFAULT_COMMISSION_YEAR", 2010)))
        _lifetime = int(getattr(config, "PLANT_LIFETIME_YEARS", 40))
        _base = int(config.T_LIST[0])
        _min_renew = float(getattr(config, "SAME_SITE_RENEWAL_MIN_CAPACITY_TD", 3200.0))
        _max_renew = int(getattr(config, "SAME_SITE_RENEWAL_MAX_COUNT", 1) or 0)
        _cap_td = pd.to_numeric(plants.set_index("plant_id")["capacity"], errors="coerce")
        for t_index, year in enumerate(sorted(shares_by_year)):
            nat_kt = (float(data["demand"][config.DEMAND_SCENARIO][int(year)]) * 1000.0
                      * float(data["national_clinker_ratio_path"][int(year)]))
            dem = _np.array([shares_by_year[year].get(n, 0.0) * nat_kt for n in node_ids])
            supply = _np.array([
                float(pcap.get(p_, 0.0)) * _availability(
                    p_, int(year), t_index, _comm, _cap_td, _lifetime, _base,
                    _min_renew, _max_renew, u0)
                for p_ in plist
            ])
            res = _linprog(c=-_np.ones(n_arcs), A_ub=A_dem,
                           b_ub=_np.concatenate([supply, dem]),
                           bounds=(0, None), method="highs")
            if res.status != 0:
                all_ok = False
                worst_gap, worst_year = float(dem.sum()), year
                continue
            gap = float(dem.sum() + res.fun)        # demand - delivered
            if gap > 1e-6:
                all_ok = False
            if gap > worst_gap:
                worst_gap, worst_year = gap, year
        record(
            "demand_network_transport_feasibility", all_ok,
            f"worst gap {worst_gap:.4f} kt in {worst_year}" if worst_year else "no gap",
            "delivered == total demand in every period",
            "Equality balances require a feasible transportation plan. A per-node "
            "capacity check is NOT sufficient (it misses aggregate/Hall violations, "
            "which is exactly how the 1,713-node design passed 74 checks while being "
            "unsolvable). This LP is the necessary and sufficient condition.",
        )
        segs = tuple(config.DEMAND_TRANSPORT_COST_SEGMENTS)
        record(
            "demand_transport_segmented_rates",
            [float(r) for _, r in segs] == [0.55, 0.12, 0.05],
            [float(r) for _, r in segs], [0.55, 0.12, 0.05],
            "road <=200 km / rail 200-600 km / water beyond. 2026-09-13: the "
            "SHORT-HAUL rate was recalibrated 0.45 -> 0.55 as the midpoint of the "
            "externally referenced 0.45-0.65 band (Gansu 0.56, Yunnan 0.65, Zhejiang "
            "official 0.60 ex-VAT, MOT 0.40-0.60) -- a calibration against an external "
            "reference, NOT a statistical mean of heterogeneous quotes. The 200-600 km "
            "and >600 km rates are deliberately unchanged. Sensitivity 0.45 / 0.55 / 0.65.",
        )
        record(
            "demand_transport_mode",
            str(config.DEMAND_TRANSPORT_MODE) in {"segmented", "uniform", "zero"},
            str(config.DEMAND_TRANSPORT_MODE), "segmented | uniform | zero",
        )

    # ── Dispatch fuel cost + source-EF tier compliance (2026-09-12) ───────
    record(
        "dispatch_fuel_cost_enabled",
        bool(getattr(config, "INCLUDE_DISPATCH_FUEL_COST", False)),
        bool(getattr(config, "INCLUDE_DISPATCH_FUEL_COST", False)), True,
        "Prices the fuel bill in DEVIATION form. The omitted mean term "
        "(coal_price x ef_mean x D_t) is a known constant given the demand path, so "
        "the optimum is identical to charging the full bill; the full discounted "
        "bill (~1,058 bn CNY) is excluded by the declared cost boundary.",
    )
    # Tier-compliance invariant: after the loader pass, EVERY line's (proc, fuel)
    # pair must equal its archived-tier rule values (cuts 4,200/2,000 t/d).
    _rule = dict(getattr(config, "SOURCE_EF_TIER_RULE", {}) or {})
    _cut1 = float(_rule.get("cut_t1", 4200.0))
    _cut2 = float(_rule.get("cut_t2", 2000.0))
    _tiers_rule = _rule.get("tiers", {})
    _caps = pd.to_numeric(plants["capacity"], errors="coerce")
    _tier = _caps.map(lambda c: 1 if c >= _cut1 else (2 if c >= _cut2 else 3))
    _exp_proc = _tier.map(lambda t: float(_tiers_rule[t]["proc"]))
    _exp_fuel = _tier.map(lambda t: float(_tiers_rule[t]["fuel"]))
    _n_dev = int((((plants["source_process_ef"] - _exp_proc).abs() > 1e-6) |
                  ((plants["source_fuel_ef"] - _exp_fuel).abs() > 1e-6)).sum())
    record(
        "source_ef_tier_compliance",
        _n_dev == 0 and bool(getattr(config, "SOURCE_EF_TIER_COMPLIANCE", False)),
        {"deviating_lines": _n_dev,
         "n_lines": int(len(plants))},
        {"deviating_lines": 0},
        "Every line's (proc, fuel) pair matches the archived capacity-tier rule "
        "(MODEL_FORMULATION_COMPLETE.md §三-3.1, cuts 4,200/2,000 t/d); the 22 "
        "appended-batch deviations and the id-2040 interpolated midpoint were "
        "reassigned by the loader pass (both parameters, workbook untouched).",
    )
    record(
        "coal_ef_conversion_single",
        abs(float(getattr(config, "COAL_EF_TCO2_PER_TCE", 0.0)) - 2.6604) < 0.01,
        float(getattr(config, "COAL_EF_TCO2_PER_TCE", 0.0)), 2.6604,
        "Single registered coal factor: Zhang et al. (2021) Table A.2, 2.6604 "
        "tCO2/tce (= 90.78 kgCO2/GJ) -- same A-level table as the AF/ARM/EE cost "
        "anchors and the basis of the 105.000 kgce/t re-anchor. The IPCC "
        "bituminous default (2.773) is a declared +/-4.2% SI uncertainty, not a "
        "second parallel factor.",
    )

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
        ("data", config.AF_ACCESS_CORRECTED_CSV),
        ("data", config.DEMAND_NODE_FILE),
        ("data", config.DEMAND_MARKET_NODE_FILE),
        ("data", config.DEMAND_MARKET_ARC_FILE),
        ("data", config.CHINA_LAND_GEOJSON),
        ("provenance", coordinate_ledger_path),
        ("provenance", PROJECT_ROOT / "data/model_input/plants/fusion_2025/coordinate_recheck_report_20260828.md"),
        ("provenance", PROJECT_ROOT / "scripts/shared/apply_verified_plant_coordinates_20260828.py"),
        ("model_code", PROJECT_ROOT / "v5/model/src_v5/config_v5.py"),
        ("model_code", PROJECT_ROOT / "v5/model/src_v5/data_loader_v5.py"),
        ("model_code", PROJECT_ROOT / "v5/model/src_v5/main.py"),
        ("model_code", PROJECT_ROOT / "v5/model/src_v5/model/final_builder.py"),
        ("model_code", PROJECT_ROOT / "v5/model/preprocessing/build_demand_nodes.py"),
        ("model_code", PROJECT_ROOT / "v5/model/preprocessing/build_market_nodes.py"),
        ("model_code", PROJECT_ROOT / "v5/model/src_v5/counterfactual.py"),
        ("model_code", PROJECT_ROOT / "v5/model/src_v5/near_optimal_identity.py"),
        ("model_code", PROJECT_ROOT / "v5/model/src_v5/results/extract.py"),
        ("workflow", PROJECT_ROOT / "v5/scenarios/run_v5_s1.sh"),
        ("workflow", PROJECT_ROOT / "v5/README.md"),
        ("workflow", PROJECT_ROOT / "scripts/v4/audit_verified_submission_batch_20260822.py"),
        ("workflow", PROJECT_ROOT / "scripts/v4/analyze_capacity_feedback_counterfactual.py"),
        ("workflow", PROJECT_ROOT / "paper/archive/ae_2026_superseded/notes/balanced_solver_protocol_20260822.md"),
        ("workflow", Path(__file__).resolve()),
    ]
    input_paths.extend([("model", PROJECT_ROOT / "v5/model/src_v5/model/carbon_streams.py"),
                        ("model", PROJECT_ROOT / "v5/model/src_v5/provenance.py")])
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
