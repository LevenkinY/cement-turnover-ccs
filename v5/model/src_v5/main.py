"""
Main entry point for v4 model.
Runs cement CCS optimization with v4 architecture.
"""

import argparse
import json
import time
import sys
from pathlib import Path

# Ensure src_v5 is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src_v5.provenance import validate_market_inputs, fingerprint, sha256
from src_v5 import config_v5 as _config_module
from src_v5.config_v5 import config, RESULTS_DIR, SOLVER, SOLVER_OPTIONS, SOLVER_PROFILES
from src_v5.data_loader_v5 import load_all
from src_v5.counterfactual import (
    finalize_capacity_path_diagnostics,
    fix_capacity_turnover_from_results,
    validate_exported_capacity_dispatch,
)
from src_v5.near_optimal_identity import (
    configure_near_optimal_identity,
    solve_near_optimal_identity,
)
from src_v5.model.final_builder import V4Model
from src_v5.results.extract import save_scenario_outputs


DEFAULT_OFFSHORE_PARAMS = dict(getattr(config, "OFFSHORE_PARAMS", {}))
DEFAULT_DEMAND_SCENARIO = str(getattr(config, "DEMAND_SCENARIO", "d_medium"))
# Captured at import so per-run overrides can be reset (2026-09-13).
AF_BIOGENIC_CO2_PER_TCE_DEFAULT = float(
    getattr(config, "AF_BIOGENIC_CO2_PER_TCE", 0.0)
)
AF_ENERGY_CALIBER_DEFAULT = str(
    getattr(config, "AF_ENERGY_CALIBER", "plant_heat_demand")
)
SAME_SITE_RENEWAL_WINDOW_DEFAULT = str(
    getattr(config, "SAME_SITE_RENEWAL_WINDOW", "first_after_expiry")
)

# ── Complete snapshot of overridable parameters (2026-09-13) ────────────────
# Captured at import, i.e. from the untouched module state, and re-applied at the
# start of EVERY run. Without this, a process that runs more than one scenario
# inherits the previous one's overrides. Measured leaks before this fix:
#   eor_revenue stayed at 80, u_min at 0.40, discount at 8%, and the short-haul
#   transport rate at 0.675 -- and the transport-scale override COMPOUNDED, because
#   it multiplied the segments that the previous run had already scaled
#   (0.45 -> 0.675 -> 1.0125). `effective_config` records such pollution but cannot
#   prevent it, and a paired comparison built on a polluted run is meaningless.
# The batch script avoids this by using one process per scenario; this makes the
# in-process path safe too, so notebooks and tests cannot silently contaminate.
_CONFIG_OVERRIDE_DEFAULTS = {
    "PLANT_LIFETIME_YEARS": config.PLANT_LIFETIME_YEARS,
    "MIN_OPERATING_UTILIZATION": config.MIN_OPERATING_UTILIZATION,
    "PLANT_FIXED_OPERATING_COST": config.PLANT_FIXED_OPERATING_COST,
    "CCS_COST_DECLINE_CASE": config.CCS_COST_DECLINE_CASE,
    "DISCOUNT_RATE": config.DISCOUNT_RATE,
    "CCR_PATH_CASE": config.CCR_PATH_CASE,
    "SAME_SITE_RENEWAL_WINDOW": config.SAME_SITE_RENEWAL_WINDOW,
    "MAX_ANNUAL_CAPACITY_DECLINE": config.MAX_ANNUAL_CAPACITY_DECLINE,
    "MAX_CAPACITY_DECLINE_PER_PERIOD": config.MAX_CAPACITY_DECLINE_PER_PERIOD,
    "AF_ENERGY_CALIBER": config.AF_ENERGY_CALIBER,
    "AF_INVESTMENT_CNY_PER_TCE": config.AF_INVESTMENT_CNY_PER_TCE,
    "AF_OM_CNY_PER_TCE": config.AF_OM_CNY_PER_TCE,
    "AF_BIOGENIC_CO2_PER_TCE": config.AF_BIOGENIC_CO2_PER_TCE,
    "BETA_AF": config.BETA_AF,
    "PLANNING_MODE": config.PLANNING_MODE,
    "DEMAND_MARKET_NODE_FILE": config.DEMAND_MARKET_NODE_FILE,
    "DEMAND_MARKET_ARC_FILE": config.DEMAND_MARKET_ARC_FILE,
    "DEMAND_TRANSPORT_COST_SEGMENTS": tuple(config.DEMAND_TRANSPORT_COST_SEGMENTS),
    "CCS_MIN_OPERATING_YEARS": config.CCS_MIN_OPERATING_YEARS,
    "TERMINAL_VALUE_MODE": getattr(config, "TERMINAL_VALUE_MODE", "none"),
    "STORAGE_RATE_SCALE": getattr(config, "STORAGE_RATE_SCALE", 1.0),
    "STORAGE_CUMULATIVE_SCALE": getattr(config, "STORAGE_CUMULATIVE_SCALE", 1.0),
}
_CCS_PARAM_DEFAULTS = {
    key: config.CCS_PARAMS[key]
    for key in ("capture_efficiency", "eor_revenue")
    if key in config.CCS_PARAMS
}


def _reset_config_overrides():
    """Restore every overridable parameter to its import-time module default."""
    for key, value in _CONFIG_OVERRIDE_DEFAULTS.items():
        setattr(config, key, value)
        if key in {"DEMAND_MARKET_NODE_FILE", "DEMAND_MARKET_ARC_FILE", "CCR_PATH_CASE"}:
            setattr(_config_module, key, value)
    for key, value in _CCS_PARAM_DEFAULTS.items():
        config.CCS_PARAMS[key] = value
DEFAULT_CARBON_BUDGET_CASE = str(getattr(config, "CARBON_BUDGET_CASE", "B40"))


SCENARIO_ALIASES = {
    # Backward compatibility for earlier v4 runs. The active counterfactual
    # equalizes future AF resource conditions; external ARM/EE and LCC paths
    # are already national and remain unchanged.
    "S3_no_af_het": "S3_all_spatial_equalized",
    "S4": "S4_storage_300km",
    "S5": "S5_offshore_parity",
    "S4_50target": "S4_50target",
    "S5_carbon_price": "S5_carbon_price",
    "S5_50target": "S4_50target",
    "S6": "S5_carbon_price",
    "S6_carbon_price": "S5_carbon_price",
    "S4_af_fixed": "S4_af_fixed",
}


CORE_SCENARIOS = [
    "S1_baseline",
    "S2_front_end",
    "S3_all_spatial_equalized",
    "S4_storage_300km",
    "S5_offshore_parity",
]


SCENARIO_POLICY_DEFAULTS = {
    "S1_baseline": {
        "target_mode": "cumulative_budget",
        "budget_case": "B40",
        "include_carbon_cost": False,
    },
    "S2_front_end": {
        "target_mode": "cumulative_budget",
        "budget_case": "B40",
        "include_carbon_cost": False,
    },
    "S3_all_spatial_equalized": {
        "target_mode": "cumulative_budget",
        "budget_case": "B40",
        "include_carbon_cost": False,
    },
    "S4_storage_300km": {
        "target_mode": "cumulative_budget",
        "budget_case": "B40",
        "include_carbon_cost": False,
    },
    "S5_offshore_parity": {
        "target_mode": "cumulative_budget",
        "budget_case": "B40",
        "include_carbon_cost": False,
    },
    "S4_50target": {
        "target_mode": "cumulative_budget",
        "budget_case": "B50",
        "include_carbon_cost": False,
    },
    "S5_carbon_price": {
        "target_mode": "none",
        "budget_case": "B40",
        "include_carbon_cost": True,
    },
    # Retained as a non-core diagnostic, because the builder still supports
    # fixed-AF experiments when explicitly requested.
    "S4_af_fixed": {
        "target_mode": "cumulative_budget",
        "budget_case": "B40",
        "include_carbon_cost": False,
    },
    # Retained for programmatic backward compatibility; it is not a core paper
    # scenario in the final hierarchy.
    "S5_no_ccs": {
        "target_mode": "cumulative_budget",
        "budget_case": "B40",
        "include_carbon_cost": False,
    },
}


def _sec(seconds):
    return f"{seconds:.1f}s"


def _num(value, digits=3):
    try:
        return f"{float(value):,.{digits}f}"
    except Exception:
        return "n/a"


def _fmt_options(options):
    keys = [
        "MIPGap", "TimeLimit", "Threads", "MIPFocus", "Heuristics",
        "Presolve", "Cuts", "PreSparsify", "NodefileStart", "NumericFocus",
    ]
    return ", ".join(f"{k}={options[k]}" for k in keys if k in options)


def _warn(message):
    print(f"  Warning: {message}")


def _summarize_input_data(data):
    plants = data.get("plants")
    storage = data.get("storage")
    demand = data.get("demand", {})
    plant_storage = data.get("plant_storage", {})
    n_plants = len(plants) if plants is not None else 0
    n_storage = len(storage) if storage is not None else 0
    n_assigned = len(plant_storage)
    n_pairs = sum(len(v) for v in plant_storage.values())
    print(
        "  Data summary: "
        f"plants={n_plants:,}, storage={n_storage:,}, "
        f"plant_sink_assigned={n_assigned:,}/{n_plants:,}, "
        f"plant_sink_pairs={n_pairs:,}, "
        f"demand_scenarios={list(demand.keys())}"
    )
    if n_plants and n_assigned < n_plants:
        _warn(f"{n_plants - n_assigned:,} plants have no sink within the assignment radius.")
    if not demand:
        _warn("no demand scenarios were loaded.")
    if n_plants and n_pairs == 0:
        _warn("plant sink whitelist is empty.")


def _scenario_notes(scenario_name):
    notes = {
        "S1_baseline": "observed-base-year capacity planning with endogenous AF, CCS, and direct source-sink matching.",
        "S2_front_end": "AF availability and exogenous ARM realization constrained; demand and LCC unchanged.",
        "S3_all_spatial_equalized": "future AF resource pools are spatially equalized; plants share provincial pools under a common engineering ceiling.",
        "S4_storage_300km": "storage-accessibility stress test; direct plant-to-sink distance capped at 300 km.",
        "S5_offshore_parity": "offshore-accessibility case; offshore transport and storage cost multipliers set equal to onshore.",
        "S4_50target": "central technology setting with a stricter 50% cumulative reduction target.",
        "S5_carbon_price": "no mandatory emissions target; medium carbon price drives deployment.",
        "S4_af_fixed": "AF fixed at the 2025 baseline rate.",
        "S5_no_ccs": "legacy no-new-commercial-CCS diagnostic; observed demo accounting retained.",
    }
    return notes.get(scenario_name, "custom scenario settings.")


def _summarize_solution(results_dict):
    solver = results_dict.get("solver", {})
    if "objective_value" in solver:
        print(
            "  Solver diagnostics: "
            f"objective={_num(solver.get('objective_value'), 2)} kCNY, "
            f"bound={_num(solver.get('objective_bound'), 2)} kCNY, "
            f"gap={_num(solver.get('mip_gap'), 6)}, "
            f"nodes={_num(solver.get('node_count'), 0)}, "
            f"solutions={solver.get('solution_count', 'n/a')}"
        )
    status = str(solver.get("status", results_dict.get("status", ""))).lower()
    sol_count = solver.get("solution_count")
    if "infeasible" in status:
        _warn("solver reported infeasible or infeasible/unbounded status.")
    if "timelimit" in status or "time" in status:
        _warn("solver stopped at the time limit; inspect MIP gap before comparing costs.")
    if sol_count == 0:
        _warn("solver did not report an incumbent solution.")

    summary = results_dict.get("summary", {})
    if summary:
        years = sorted(int(y) for y in summary if str(y).isdigit())
        def _summary_year(yr):
            return summary.get(yr, summary.get(str(yr), {}))
        first = _summary_year(years[0]) if years else {}
        last = _summary_year(years[-1]) if years else {}
        print(
            "  Result snapshot: "
            f"{years[0] if years else 'n/a'} net={_num(first.get('net_co2_kt'), 1)} kt, "
            f"{years[-1] if years else 'n/a'} net={_num(last.get('net_co2_kt'), 1)} kt, "
            f"capture={_num(last.get('captured_co2_kt'), 1)} kt, "
            f"AF={_num(last.get('national_af_rate'), 4)}, "
            f"ARM={_num(last.get('avg_arm_realized'), 4)}, "
            f"clinker_ratio={_num(last.get('effective_clinker_ratio'), 4)}, "
            f"active_CCS={last.get('n_plants_ccs_active', 'n/a')}"
        )

    slack = float(results_dict.get("total_slack_kt") or 0.0)
    if abs(slack) > 1e-6:
        _warn(f"emission target slack is nonzero: {slack:,.3f} kt.")
    obj_gap = (
        results_dict.get("cost_breakdown_total", {})
        .get("objective_gap_kCNY")
    )
    if obj_gap is not None and abs(float(obj_gap)) > 1e-2:
        _warn(f"cost breakdown does not exactly match objective: gap={obj_gap:,.4f} kCNY.")
    flow = results_dict.get("ccs_transport_storage", {})
    flow_gap = 0.0
    for row in flow.values():
        try:
            flow_gap = max(flow_gap, abs(float(row.get("flow_capture_gap_kt", 0.0))))
        except Exception:
            pass
    if flow_gap > 1e-3:
        _warn(f"commercial CCS flow-capture gap exceeds tolerance: {flow_gap:,.6f} kt.")


def canonical_scenario_name(scenario_name):
    """Return canonical scenario name, accepting legacy aliases."""
    return SCENARIO_ALIASES.get(scenario_name, scenario_name)


def apply_scenario_modifications(data, scenario_name):
    """Apply scenario-specific modifications to data."""
    def capacity_share_pool_by_year(pool):
        plants = data["plants"]
        if "capacity" in plants.columns:
            province_weight = plants.groupby("province")["capacity"].sum().to_dict()
        else:
            province_weight = plants.groupby("province").size().to_dict()
        provinces = list(data["prov_corridor"].keys())
        total_weight = sum(province_weight.get(prov, 0.0) for prov in provinces)
        years = sorted({yr for (_, yr) in pool})
        result = {}
        for yr in years:
            total_pool = sum(pool.get((prov, yr), 0.0) for prov in provinces)
            for prov in provinces:
                share = province_weight.get(prov, 0.0) / total_weight if total_weight else 0.0
                result[(prov, yr)] = total_pool * share
        return result

    def capacity_weighted_plant_shares():
        """Within-province capacity shares, replacing accessibility shares (S3).

        In the v5 four-layer structure the plant-level cap is
        kappa * (A_bio*share_bio + A_wst*share_wst), so removing the accessibility
        advantage means replacing share_bio/share_wst with capacity shares — there is
        no separate absolute plant access cap to delete any more.
        """
        plants = data["plants"][["plant_id", "province", "capacity"]].copy()
        plants["plant_id"] = plants["plant_id"].astype(int)
        plants["capacity"] = plants["capacity"].astype(float)
        share_bio, share_wst = {}, {}
        for _, sub in plants.groupby("province"):
            total = float(sub["capacity"].sum())
            for row in sub.itertuples(index=False):
                value = (
                    float(row.capacity) / total if total > 0 else 1.0 / max(len(sub), 1)
                )
                share_bio[int(row.plant_id)] = value
                share_wst[int(row.plant_id)] = value
        return share_bio, share_wst

    def filter_plant_storage_whitelist(max_distance_km):
        whitelist = data.get("plant_storage", {})
        before = sum(len(routes) for routes in whitelist.values())
        filtered = {
            int(pid): [
                (int(s), float(d), str(stype))
                for s, d, stype in routes
                if float(d) <= float(max_distance_km)
            ]
            for pid, routes in whitelist.items()
        }
        after = sum(len(routes) for routes in filtered.values())
        data["plant_storage"] = filtered
        data["_storage_max_distance_km"] = float(max_distance_km)
        data["_plant_sink_pairs_before_filter"] = int(before)
        data["_plant_sink_pairs_after_filter"] = int(after)

    if scenario_name == "S2_front_end":
        # Front-end infrastructure constrained scenario.
        # NOT a demand reduction (demand identical to S1) — instead, weaker
        # front-end mitigation potential (AF and external ARM realization) to test how much
        # CCS is needed when production-side levers are constrained.
        #
        # Mechanism (v3 model_builder.py:1089 used material_side_scale on
        # process_adjustment and clinker_ratio_adjustment):
        #   - ARM (process_adjustment) × 0.5        → process-side reduction halved
        #   - AF resource/access pools × 0.6        → final AF potential remains constrained
        # Demand stays at D-M (same as the core S1 run).
        data["_arm_external_scale"] = 0.5
        data["_af_resource_scale"] = 0.6
        data["process_adjustment"] = {
            key: (float(value) if int(key[1]) == 2025 else 0.5 * float(value))
            for key, value in data["process_adjustment"].items()
        }
        data["province_af_pool_ktce"] = {
            key: (float(value) if int(key[1]) == 2025 else 0.6 * float(value))
            for key, value in data["province_af_pool_ktce"].items()
        }
        # v5 (P0-2): the plant cap is a share-weighted slice of the province
        # allocation, so the front-end shortfall is applied there. The accessibility
        # shares stay unchanged (the relative pattern is a physical property).
        data["af_alloc_bio"] = {
            key: (float(value) if int(key[1]) == 2025 else 0.6 * float(value))
            for key, value in data["af_alloc_bio"].items()
        }
        data["af_alloc_wst"] = {
            key: (float(value) if int(key[1]) == 2025 else 0.6 * float(value))
            for key, value in data["af_alloc_wst"].items()
        }

    elif scenario_name == "S3_all_spatial_equalized":
        # S3 all-spatial-equalized counterfactual:
        # Preserve national AF totals while removing future resource-location
        # advantages. Province pools are equalized by installed capacity. Plants
        # then share each province pool and face only the common engineering TSR
        # ceiling, rather than a pre-assigned, non-transferable plant quota.
        # ARM and EE are already external national paths; LCC remains national.
        # v5 (P0-2): in the four-layer structure the spatial advantage enters through
        # (a) the province allocation A_x[p,t] and (b) the within-province
        # accessibility shares. S3 removes both while preserving the national total.
        original_pool = dict(data["province_af_pool_ktce"])
        original_bio = dict(data["af_alloc_bio"])
        original_wst = dict(data["af_alloc_wst"])
        channel = dict(data.get("province_af_pool_channel", {}))
        equal_pool = capacity_share_pool_by_year(original_pool)
        share_bio, share_wst = capacity_weighted_plant_shares()
        province_weight = (
            data["plants"].groupby("province")["capacity"].sum().to_dict()
            if "capacity" in data["plants"].columns
            else data["plants"].groupby("province").size().to_dict()
        )
        share_weight = {str(k): float(v) for k, v in province_weight.items()}

        provinces_all = list(data["prov_corridor"].keys())

        def rescale(original, kind):
            """Equalise the spatial distribution while preserving each period's total.

            The national allocation total per period (= ceiling(t) x national fuel) is
            redistributed across provinces by installed capacity, then split between
            the biomass and waste channels using each province's original channel
            ratio. Only the *spatial pattern* changes.
            """
            totals = {}
            for (_, year), value in original.items():
                totals[int(year)] = totals.get(int(year), 0.0) + float(value)
            weights = {}
            for province in provinces_all:
                weights[province] = float(share_weight.get(province, 0.0))
            weight_sum = sum(weights.values()) or 1.0
            result = {}
            for (province, year), value in original.items():
                year = int(year)
                if year == 2025:
                    result[(province, year)] = float(value)
                    continue
                parts = channel.get((province, year), None)
                denom = (
                    float(parts["bio"]) + float(parts["wst"]) if parts is not None else 0.0
                )
                if denom <= 0:
                    # no channel information (zero-resource province): put this
                    # province's equalised slice entirely in the biomass channel.
                    share_of_channel = (
                        1.0 if kind == "bio" else 0.0
                    )
                else:
                    share_of_channel = float(parts[kind]) / denom
                result[(province, year)] = (
                    totals.get(year, 0.0)
                    * weights[province]
                    / weight_sum
                    * share_of_channel
                )
            # Renormalise per period so the national total is preserved exactly even
            # when a resource province has no plants (zero capacity weight).
            for year, target in totals.items():
                if year == 2025:
                    continue
                current = sum(
                    float(value)
                    for (_, y), value in result.items()
                    if int(y) == year
                )
                if current > 0:
                    factor = float(target) / current
                    for key in list(result):
                        if int(key[1]) == year:
                            result[key] = float(result[key]) * factor
            return result

        data["province_af_pool_ktce"] = {
            key: (original_pool[key] if int(key[1]) == 2025 else value)
            for key, value in equal_pool.items()
        }
        # The 2025 BASE YEAR must keep the ORIGINAL plant shares. S3 changes the
        # within-province shares to capacity weights, but m.af_supply[i, 0] is FIXED
        # to the observed allocation, which the loader built against the ORIGINAL
        # shares (capped at kappa * alloc * share). Applying the modified shares at
        # t = 0 can therefore make that fixed value violate its own cap -- measured:
        # 29 of 1,572 plants, which made every S3 run INFEASIBLE (Gurobi IIS = 1
        # constraint, no bounds, i.e. a pure structural contradiction). The S3 intent
        # is to remove FUTURE location advantages, so the base year is stashed here
        # and the builder keeps using the original shares at t = 0.
        data["af_share_bio_base_year"] = dict(data["af_share_bio"])
        data["af_share_wst_base_year"] = dict(data["af_share_wst"])
        data["af_alloc_bio"] = rescale(original_bio, "bio")
        data["af_alloc_wst"] = rescale(original_wst, "wst")
        data["af_share_bio"] = dict(share_bio)
        data["af_share_wst"] = dict(share_wst)
        data["_af_spatial_equalized"] = True
        data["_af_plant_access_mode"] = (
            "capacity_share_within_province_and_equalised_province_allocation"
        )
        data["_af_equalized_pool_total_ktce_by_year"] = {
            int(year): sum(
                float(data["af_alloc_bio"].get((province, year), 0.0))
                + float(data["af_alloc_wst"].get((province, year), 0.0))
                for province in data["prov_corridor"]
            )
            for year in config.T_LIST
        }

    elif scenario_name == "S4_storage_300km":
        # Storage accessibility stress test:
        # keep the S1 front-end resource and carbon-budget settings, but restrict
        # feasible direct plant-to-sink routes to storage nodes within 300 km.
        filter_plant_storage_whitelist(300.0)

    elif scenario_name == "S5_offshore_parity":
        # Offshore accessibility case:
        # keep storage geography unchanged, but remove offshore transport and
        # storage cost premia so offshore DSA/EOR nodes have onshore-equivalent
        # route and storage unit costs.
        config.OFFSHORE_PARAMS["pipeline_cost_factor"] = 1.0
        config.OFFSHORE_PARAMS["storage_cost_factor"] = 1.0
        data["_offshore_pipeline_cost_factor"] = 1.0
        data["_offshore_storage_cost_factor"] = 1.0

    elif scenario_name == "S4_af_fixed":
        # AF fixed at modeled 2025 baseline rate; CCS remains endogenous.
        data["_af_fixed_rate"] = float(getattr(config, "INITIAL_AF_RATE", 0.05))

    elif scenario_name == "S5_no_ccs":
        # Robustness counterfactual: no new CCS, except observed demo projects.
        data["_no_ccs"] = True

    return data


def _planning_counterfactual_report(config, results_dict, capacity_path_counterfactual):
    """Declare the planning mode and what the J/S comparison requires.

    R = C_S - C_J is a CROSS-RUN quantity. This block states which stage the run
    is, so that a paired comparison can be checked before the difference is taken
    (see v5/scenarios/verify_pair_configs.py).
    """
    mode = str(getattr(config, "PLANNING_MODE", "joint"))
    summary = results_dict.get("summary") or {}
    weights = results_dict.get("period_weights_years") or {}

    def _by_year(mapping, year):
        """Look up a period-keyed mapping whose keys may be int OR str.

        In memory the model writes int year keys; json.dump stringifies them on
        save. Reading only one form silently yields an empty sum (0), which is
        indistinguishable from "no emissions" -- it produced exactly that bug.
        """
        if year in mapping:
            return mapping[year]
        return mapping.get(str(year))

    cumulative_actual = None
    if summary and weights:
        terms = []
        for year in sorted(int(y) for y in summary):
            entry = _by_year(summary, year)
            if not isinstance(entry, dict) or "net_co2_kt" not in entry:
                continue
            weight = _by_year(weights, year)
            if weight is None:
                continue
            terms.append(float(weight) * float(entry["net_co2_kt"]))
        if terms:
            cumulative_actual = float(sum(terms))
    budget_target = None
    cb = results_dict.get("cumulative_budget")
    if isinstance(cb, dict):
        budget_target = cb.get("target_kt_year")
    report = {
        "planning_mode": mode,
        "stage": {
            "joint": "J - joint capacity-turnover and low-carbon optimisation",
            "stepwise_capacity": "S1 - capacity path on conventional resource cost only",
            "stepwise_low_carbon": "S2 - low-carbon retrofit on a fixed capacity path",
        }[mode],
        "carbon_target_active": str(config.EMISSION_TARGET_MODE).lower() != "none",
        "capacity_path_fixed": bool(capacity_path_counterfactual.get("enabled")),
        "cumulative_emissions_kt_year": cumulative_actual,
        "cumulative_budget_target_kt_year": budget_target,
        "cumulative_emissions_gap_kt_year": (
            (cumulative_actual - budget_target)
            if (cumulative_actual is not None and budget_target is not None)
            else None
        ),
        "note": (
            "R = C_S - C_J is computed ACROSS runs, not here. The paired S2 run must "
            "use the same demand scenario, transport parameters, cost accounting and "
            "carbon budget as its J counterpart; run "
            "v5/scenarios/verify_pair_configs.py on the two result files before "
            "differencing. If S2 cannot meet the budget with the stage-1 fleet, the "
            "run is infeasible: report that outcome, and if a quantified gap is "
            "needed, rerun S2 with EMISSION_TARGET_MODE='none' and read "
            "cumulative_emissions_gap_kt_year from that run rather than relaxing the "
            "budget silently."
        ),
    }
    if mode in {"stepwise_capacity", "stepwise_low_carbon"}:
        print(
            f"  [planning] mode={mode} | stage={report['stage']} | "
            f"carbon_target_active={report['carbon_target_active']} | "
            f"capacity_path_fixed={report['capacity_path_fixed']}"
        )
    return report


def run_scenario(
    scenario_name="S1_baseline",
    output_dir=None,
    solver=None,
    solver_profile=None,
    time_limit=None,
    mip_gap=None,
    threads=None,
    tee=False,
    target_mode=None,
    cumulative_reduction=None,
    budget_case=None,
    cost_boundary=None,
    include_carbon_cost=False,
    include_full_fuel_cost=False,
    demand_scenario=None,
    fixed_capacity_path=None,
    fixed_capacity_mode="turnover",
    near_opt_identity_reference=None,
    near_opt_cost_reference=None,
    near_opt_cost_tolerance=0.0,
    near_opt_direction="closest",
    near_opt_scope="full_path",
    near_opt_path_time_limit=None,
    near_opt_path_mip_gap=None,
    plant_lifetime=None,
    min_operating_utilization=None,
    fixed_operating_cost=None,
    ccs_decline=None,
    demand_transport_mode=None,
    discount_rate=None,
    capture_efficiency=None,
    ccr_path_case=None,
    same_site_renewal_window=None,
    max_annual_capacity_decline=None,
    max_capacity_decline_per_period=None,
    af_energy_caliber=None,
    af_biogenic_co2_per_tce=None,
    af_investment_per_tce=None,
    af_om_per_tce=None,
    beta_af=None,
    planning_mode=None,
    demand_market_node_file=None,
    demand_market_arc_file=None,
    demand_transport_scale=None,
    eor_revenue=None,
    ccs_min_operating_years=None,
    terminal_value_mode=None,
    storage_rate_scale=None,
):
    """Run a single scenario and save results."""
    requested_scenario = scenario_name
    scenario_name = canonical_scenario_name(scenario_name)
    if scenario_name != requested_scenario:
        print(f"  Scenario alias: {requested_scenario} -> {scenario_name}")

    t_start = time.time()
    print(f"\n{'='*60}")
    print(f"  V4 Model Run: {scenario_name}")
    print(f"{'='*60}")
    print(f"  Scenario setup: {_scenario_notes(scenario_name)}")

    policy_defaults = SCENARIO_POLICY_DEFAULTS.get(
        scenario_name,
        {
            "target_mode": getattr(config, "EMISSION_TARGET_MODE", "cumulative_budget"),
            "budget_case": getattr(config, "CARBON_BUDGET_CASE", "B40"),
            "include_carbon_cost": getattr(config, "INCLUDE_CARBON_COST_IN_OBJECTIVE", False),
        },
    )
    # Reset mutable config switches on every run so batch runs do not inherit
    # target/carbon-price settings from the previous scenario.
    _reset_config_overrides()
    config.EMISSION_TARGET_MODE = policy_defaults["target_mode"]
    config.CARBON_BUDGET_CASE = str(policy_defaults["budget_case"]).upper()
    config.INCLUDE_CARBON_COST_IN_OBJECTIVE = bool(policy_defaults["include_carbon_cost"])
    config.INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE = False
    config.COST_BOUNDARY = "incremental_mitigation"
    config.OFFSHORE_PARAMS = dict(DEFAULT_OFFSHORE_PARAMS)
    config.DEMAND_SCENARIO = str(
        demand_scenario or DEFAULT_DEMAND_SCENARIO
    ).lower()
    # 2026-09-13: the AF-caliber, planning-mode and decline-cap overrides are also
    # per-run state. Reset them here so a multi-scenario process (tests, notebooks)
    # cannot inherit a caliber or a counterfactual from the previous call.
    config.PLANNING_MODE = "joint"
    config.AF_BIOGENIC_CO2_PER_TCE = float(AF_BIOGENIC_CO2_PER_TCE_DEFAULT)
    config.AF_ENERGY_CALIBER = str(AF_ENERGY_CALIBER_DEFAULT)
    config.MAX_CAPACITY_DECLINE_PER_PERIOD = None
    config.MAX_ANNUAL_CAPACITY_DECLINE = None
    config.SAME_SITE_RENEWAL_WINDOW = str(SAME_SITE_RENEWAL_WINDOW_DEFAULT)

    if target_mode is not None:
        config.EMISSION_TARGET_MODE = target_mode
    if budget_case is not None:
        config.CARBON_BUDGET_CASE = str(budget_case).upper()
    if cumulative_reduction is not None:
        legacy_budget_map = {0.30: "B30", 0.40: "B40", 0.50: "B50"}
        matched = next(
            (name for value, name in legacy_budget_map.items()
             if abs(float(cumulative_reduction) - value) <= 1e-9),
            None,
        )
        if matched is None:
            raise ValueError(
                "Fixed absolute budgets only support legacy reductions "
                "0.30, 0.40, and 0.50; use --budget-case B30/B40/B50."
            )
        if budget_case is not None and config.CARBON_BUDGET_CASE != matched:
            raise ValueError("--budget-case conflicts with --cumulative-reduction")
        config.CARBON_BUDGET_CASE = matched
    valid_budgets = tuple(getattr(config, "VALID_CARBON_BUDGET_CASES", ()))
    if valid_budgets and config.CARBON_BUDGET_CASE not in valid_budgets:
        raise ValueError(
            f"Unknown carbon budget case {config.CARBON_BUDGET_CASE!r}; "
            f"expected one of {list(valid_budgets)}"
        )
    if cost_boundary is not None:
        config.COST_BOUNDARY = cost_boundary
    if plant_lifetime is not None:
        plant_lifetime = int(plant_lifetime)
        if plant_lifetime <= 0:
            raise ValueError("--plant-lifetime must be a positive integer")
        config.PLANT_LIFETIME_YEARS = plant_lifetime
        print(f"  Plant lifetime override: {plant_lifetime} years")
    if min_operating_utilization is not None:
        min_operating_utilization = float(min_operating_utilization)
        if not 0.0 < min_operating_utilization <= 1.0:
            raise ValueError("--min-operating-utilization must be in (0, 1]")
        config.MIN_OPERATING_UTILIZATION = min_operating_utilization
        print(
            "  Minimum operating utilization override: "
            f"{min_operating_utilization:.3f}"
        )
    if fixed_operating_cost is not None:
        config.PLANT_FIXED_OPERATING_COST = float(fixed_operating_cost)
        print(f"  Plant fixed operating cost override: {config.PLANT_FIXED_OPERATING_COST:.1f} CNY/t-yr")
    if ccs_decline is not None:
        case = str(ccs_decline).lower()
        if case not in config.CCS_COST_DECLINE_SCENARIOS:
            raise ValueError(
                f"Unknown CCS decline case {case!r}; "
                f"expected {sorted(config.CCS_COST_DECLINE_SCENARIOS)}"
            )
        config.CCS_COST_DECLINE_CASE = case
        print(f"  CCS cost decline case: {case}")
    if demand_transport_mode is not None:
        mode = str(demand_transport_mode).lower()
        if mode == "zero":
            # market-side neutralisation: clinker becomes nationally fungible,
            # i.e. exactly the pre-P0-4 assumption.
            config.DEMAND_TRANSPORT_COST_SEGMENTS = ((float("inf"), 0.0),)
            config.DEMAND_TRANSPORT_MODE = "segmented"
            print("  Demand transport cost override: 0 (market-side neutralisation)")
        elif mode in {"segmented", "uniform"}:
            config.DEMAND_TRANSPORT_MODE = mode
            print(f"  Demand transport mode override: {mode}")
        else:
            raise ValueError("--demand-transport-mode expects segmented|uniform|zero")
    if discount_rate is not None:
        config.DISCOUNT_RATE = float(discount_rate)
        print(f"  Discount rate override: {config.DISCOUNT_RATE:.3f}")
    if capture_efficiency is not None:
        eff = float(capture_efficiency)
        if not 0.0 < eff <= 1.0:
            raise ValueError("--capture-efficiency must be in (0, 1]")
        config.CCS_PARAMS["capture_efficiency"] = eff
        print(f"  Capture efficiency override: {eff:.3f}")
    if ccr_path_case is not None:
        ccr = str(ccr_path_case).lower()
        if ccr not in ("central", "high"):
            raise ValueError("--ccr-path-case expects central|high")
        # Dual binding: the Config instance (builder metadata) and the module
        # attribute (the loader reads CCR_PATH_CASE at call time via the config
        # module -- the same call-time pattern as ENABLE_REGIONAL_DEMAND).
        config.CCR_PATH_CASE = ccr
        _config_module.CCR_PATH_CASE = ccr
        print(f"  Clinker-ratio (CCR) path case: {ccr}")
    if same_site_renewal_window is not None:
        window = str(same_site_renewal_window).lower()
        if window not in {"first_after_expiry", "any_after_expiry"}:
            raise ValueError(
                "--same-site-renewal-window expects first_after_expiry|any_after_expiry"
            )
        config.SAME_SITE_RENEWAL_WINDOW = window
        print(f"  Same-site renewal window: {window}")
    if max_annual_capacity_decline is not None:
        rate = float(max_annual_capacity_decline)
        if not 0.0 <= rate < 1.0:
            raise ValueError("--max-annual-capacity-decline must be in [0, 1)")
        config.MAX_ANNUAL_CAPACITY_DECLINE = rate
        print(
            "  VALIDATION ONLY: national active-capacity decline capped at "
            f"{rate:.3%} per year"
        )
    if max_capacity_decline_per_period is not None:
        period_rate = float(max_capacity_decline_per_period)
        if not 0.0 <= period_rate < 1.0:
            raise ValueError("--max-capacity-decline-per-period must be in [0, 1)")
        config.MAX_CAPACITY_DECLINE_PER_PERIOD = period_rate
        annual_equiv = 1.0 - (1.0 - period_rate) ** (1.0 / 5.0)
        print(
            "  SCENARIO ONLY (slow-exit institutional friction): national "
            f"active-capacity decline capped at {period_rate:.2%} per FIVE-YEAR "
            f"period (= {annual_equiv:.4%}/yr equivalent). This retains idle "
            "capacity by construction; the resulting utilisation is a consequence "
            "of the cap and is NOT a central finding."
        )
    if af_energy_caliber is not None:
        caliber = str(af_energy_caliber)
        if caliber not in {"plant_heat_demand", "flat_tce"}:
            raise ValueError(
                "--af-energy-caliber expects plant_heat_demand|flat_tce"
            )
        config.AF_ENERGY_CALIBER = caliber
        print(
            f"  AF energy caliber: {caliber}"
            + (
                "  [LEGACY: flat 0.105 tce/t for every plant, no EE -- audit only]"
                if caliber == "flat_tce"
                else "  [central: per-plant heat intensity x (1-EE)]"
            )
        )
    if af_biogenic_co2_per_tce is not None:
        bio = float(af_biogenic_co2_per_tce)
        if bio < 0.0:
            raise ValueError("--af-biogenic-co2-per-tce must be non-negative")
        config.AF_BIOGENIC_CO2_PER_TCE = bio
        print(
            "  AF biogenic CO2: "
            f"{bio:.4f} tCO2/tce (capture/pipeline/storage sized on the GROSS "
            "flow; the carbon budget still deducts only the fossil part)"
        )
    if af_investment_per_tce is not None:
        value = float(af_investment_per_tce)
        if value <= 0.0:
            raise ValueError("--af-investment-per-tce must be positive")
        config.AF_INVESTMENT_CNY_PER_TCE = value
        print(f"  AF investment: {value:.2f} CNY per (tce/yr) of added capacity")
    if af_om_per_tce is not None:
        value = float(af_om_per_tce)
        if value < 0.0:
            raise ValueError("--af-om-per-tce must be non-negative")
        config.AF_OM_CNY_PER_TCE = value
        print(f"  AF O&M: {value:.2f} CNY per tce handled")
    if beta_af is not None:
        value = float(beta_af)
        if not 0.0 <= value <= 1.0:
            raise ValueError("--beta-af must be in [0, 1]")
        config.BETA_AF = value
        print(f"  BETA_AF: {value:.4f} (central 0.55 is grade C; range 0.55-0.69)")
    if planning_mode is not None:
        mode = str(planning_mode)
        if mode not in {"joint", "stepwise_capacity", "stepwise_low_carbon"}:
            raise ValueError(
                "--planning-mode expects joint|stepwise_capacity|stepwise_low_carbon"
            )
        config.PLANNING_MODE = mode
        if mode == "stepwise_capacity":
            # Stage 1 must see a world without a carbon constraint, otherwise the
            # "capacity chosen without foresight of the constraint" reading fails.
            config.EMISSION_TARGET_MODE = "none"
            config.MILESTONE_USE_SLACK = False
            print(
                "  Planning mode stepwise STAGE 1: EMISSION_TARGET_MODE -> none; "
                "CCS and AF fixed to zero for t>0 (see _apply_planning_mode)"
            )
        elif mode == "stepwise_low_carbon" and fixed_capacity_path is None:
            raise ValueError(
                "--planning-mode stepwise_low_carbon requires --fixed-capacity-path "
                "pointing at the stage-1 (stepwise_capacity) result JSON."
            )
        else:
            print(f"  Planning mode: {mode}")
    if demand_market_node_file is not None or demand_market_arc_file is not None:
        if demand_market_node_file is None or demand_market_arc_file is None:
            raise ValueError(
                "The market node and arc files must be switched together: a node "
                "set and an arc set built for a different node count are not "
                "compatible."
            )
        node_path = Path(demand_market_node_file)
        arc_path = Path(demand_market_arc_file)
        for label, path in (("nodes", node_path), ("arcs", arc_path)):
            if not path.exists():
                raise FileNotFoundError(
                    f"alternate market {label} file not found: {path}"
                )
        # The loader reads these at call time through the config module, so setting
        # the module attribute is enough (no import-time rebinding needed).
        config.DEMAND_MARKET_NODE_FILE = node_path
        config.DEMAND_MARKET_ARC_FILE = arc_path
        _config_module.DEMAND_MARKET_NODE_FILE = node_path
        _config_module.DEMAND_MARKET_ARC_FILE = arc_path
        print(
            "  Market layer OVERRIDE (spatial robustness): "
            f"nodes={node_path.name} arcs={arc_path.name}"
        )
    if demand_transport_scale is not None:
        scale = float(demand_transport_scale)
        if scale <= 0.0:
            raise ValueError("--demand-transport-scale must be positive")
        # Scale the segmented clinker transport rates (e.g. 1.5 = the measured
        # upper range, 2.0 = the non-measured diagnostic). Set on the config
        # INSTANCE used by V4Model. The short-haul rate is the one that governs
        # the retention radius F/t and hence utilization.
        config.DEMAND_TRANSPORT_COST_SEGMENTS = tuple(
            (float(upper), float(rate) * scale)
            for upper, rate in config.DEMAND_TRANSPORT_COST_SEGMENTS
        )
        print(
            "  Clinker transport rate scale: "
            f"x{scale:.2f} -> {config.DEMAND_TRANSPORT_COST_SEGMENTS}"
        )
    if eor_revenue is not None:
        value = float(eor_revenue)
        if value < 0.0:
            raise ValueError("--eor-revenue must be non-negative")
        # Central default is 0 (no external revenue credited; see v5/progress.md
        # §2.2). Pass --eor-revenue 80 (EOR_REVENUE_REFERENCE) for the "external
        # revenue offset" sensitivity.
        config.CCS_PARAMS["eor_revenue"] = value
        print(f"  EOR revenue credit override: {value:.2f} CNY/tCO2")
    if ccs_min_operating_years is not None:
        years = int(ccs_min_operating_years)
        if years < 0:
            raise ValueError("--ccs-min-operating-years must be non-negative")
        config.CCS_MIN_OPERATING_YEARS = years
        print(
            f"  CCS minimum operating commitment override: {years} years "
            "(K1/K2 arm: 0 removes the commitment set by construction; "
            "central is 15)"
        )
    if terminal_value_mode is not None:
        tv_mode = str(terminal_value_mode)
        if tv_mode not in {"none", "annuity_consistent_guarded"}:
            raise ValueError(
                "--terminal-value-mode expects none|annuity_consistent_guarded"
            )
        config.TERMINAL_VALUE_MODE = tv_mode
        print(
            f"  Terminal value mode: {tv_mode} (R6 arm; factor table and guard "
            "rule registered in parameters/terminal_value_commitment_20260914.md)"
        )
    if storage_rate_scale is not None:
        scale = float(storage_rate_scale)
        if not 0.0 < scale <= 10.0:
            raise ValueError("--storage-rate-scale must be in (0, 10]")
        config.STORAGE_RATE_SCALE = scale
        print(
            f"  Storage injection-rate scale: {scale:.3f} (R8 arm; multiplies "
            "the effective per-sink rate cap)"
        )
    if include_carbon_cost:
        config.INCLUDE_CARBON_COST_IN_OBJECTIVE = True
    if include_full_fuel_cost:
        config.INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE = True
    print(
        "  Emission target: "
        f"{getattr(config, 'EMISSION_TARGET_MODE', 'milestone')}"
        f" (fixed_budget_case={getattr(config, 'CARBON_BUDGET_CASE', None)})"
    )
    print(
        "  Cost boundary: "
        f"{getattr(config, 'COST_BOUNDARY', 'incremental_mitigation')}"
        f" (carbon_in_objective={getattr(config, 'INCLUDE_CARBON_COST_IN_OBJECTIVE', False)}, "
        f"full_fuel_in_objective={getattr(config, 'INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE', False)})"
    )

    # Load data
    print("\n[1/6] Loading and preprocessing data...")
    t_phase = time.time()
    data = load_all()
    data["market_input_provenance"] = validate_market_inputs(data, config)
    valid_demand = tuple(getattr(config, "VALID_DEMAND_SCENARIOS", ()))
    if valid_demand and config.DEMAND_SCENARIO not in valid_demand:
        raise ValueError(
            f"Unknown demand scenario {config.DEMAND_SCENARIO!r}; "
            f"expected one of {list(valid_demand)}"
        )
    if config.DEMAND_SCENARIO not in data.get("demand", {}):
        raise ValueError(
            f"Demand scenario {config.DEMAND_SCENARIO!r} was not loaded from "
            f"{getattr(config, 'DEMAND_XLSX', 'the demand workbook')}"
        )
    _summarize_input_data(data)
    print(f"  Active demand scenario: {config.DEMAND_SCENARIO}")
    print(f"  Data phase complete in {_sec(time.time() - t_phase)}")

    # Apply scenario-specific modifications
    print("\n[2/6] Applying scenario switches...")
    t_phase = time.time()
    data = apply_scenario_modifications(data, scenario_name)
    data["model_input_sha256"] = fingerprint({k: v for k, v in data.items() if k != "market_input_provenance"})
    source_root = Path(__file__).resolve().parent
    data["model_code_sha256"] = fingerprint({str(p.relative_to(source_root)): sha256(p) for p in sorted(source_root.rglob("*.py"))})
    active_flags = sorted(k for k in data if str(k).startswith("_"))
    print(
        f"  Scenario switches complete in {_sec(time.time() - t_phase)}"
        + (f"; active flags={active_flags}" if active_flags else "; active flags=[]")
    )

    # Build model
    print("\n[3/6] Building optimization model...")
    t_phase = time.time()
    model = V4Model(data, config)
    m = model.build()
    capacity_path_counterfactual = {"enabled": False}
    near_optimal_identity = {"enabled": False}
    if fixed_capacity_path is not None and near_opt_identity_reference is not None:
        raise ValueError(
            "--fixed-capacity-path and --near-opt-identity-reference are mutually exclusive"
        )
    if fixed_capacity_path is not None:
        capacity_path_counterfactual = fix_capacity_turnover_from_results(
            model,
            fixed_capacity_path,
            include_utilization=(fixed_capacity_mode == "turnover_and_dispatch"),
        )
        print(
            "  Capacity-turnover counterfactual: fixed "
            f"{'/'.join(capacity_path_counterfactual['fixed_variables'])} for "
            f"{capacity_path_counterfactual['fixed_plants']} plants "
            f"from {capacity_path_counterfactual['source_scenario']}"
        )
    near_optimal_study = None
    if near_opt_identity_reference is not None:
        if near_opt_cost_reference is None:
            raise ValueError(
                "--near-opt-cost-reference is required with --near-opt-identity-reference"
            )
        near_optimal_study = configure_near_optimal_identity(
            model,
            active_scenario=scenario_name,
            identity_reference_path=near_opt_identity_reference,
            cost_reference_path=near_opt_cost_reference,
            cost_tolerance=near_opt_cost_tolerance,
            direction=near_opt_direction,
            scope=near_opt_scope,
        )
        near_optimal_identity = dict(near_optimal_study["public"])
        print(
            "  Near-optimal identity experiment: "
            f"{near_opt_direction} {near_opt_scope} path within "
            f"{100 * float(near_opt_cost_tolerance):.3f}% of the active-scenario incumbent"
        )
    print(f"  Model construction complete in {_sec(time.time() - t_phase)}")

    # Scenario flags are applied inside builder where they touch model variables.

    # Count vars
    print("  Counting variables and constraints...")
    t_count = time.time()
    n_binary = n_continuous = n_con = 0
    from pyomo.environ import Var, Constraint, Binary
    for v in m.component_objects(Var, active=True):
        for idx in v:
            try:
                if v[idx].domain == Binary:
                    n_binary += 1
                else:
                    n_continuous += 1
            except:
                n_continuous += 1
    for c in m.component_objects(Constraint, active=True):
        for idx in c:
            n_con += 1

    print(f"  Model stats: {n_binary} binary + {n_continuous} continuous = {n_binary+n_continuous} vars")
    print(f"  Constraints: {n_con}")
    print(f"  Count phase complete in {_sec(time.time() - t_count)}")

    # Solve
    print("\n[4/6] Configuring and starting solver...")
    solver_name = solver or SOLVER
    opts = dict(SOLVER_OPTIONS)
    profile_name = solver_profile or "default"
    if solver_profile:
        if solver_profile not in SOLVER_PROFILES:
            raise ValueError(f"Unknown solver profile: {solver_profile}")
        opts.update(SOLVER_PROFILES[solver_profile])
    if time_limit is not None:
        opts["TimeLimit"] = time_limit
    if mip_gap is not None:
        opts["MIPGap"] = mip_gap
    if threads is not None:
        opts["Threads"] = threads
    opts["tee"] = tee

    print(
        f"  Solver profile: {profile_name}; "
        f"{_fmt_options(opts)}"
    )
    print(f"  Solving with {solver_name}...")
    t0 = time.time()
    if near_optimal_study is None:
        results = model.solve(solver=solver_name, options=opts)
    else:
        results, near_optimal_identity = solve_near_optimal_identity(
            model,
            solver=solver_name,
            cost_options=opts,
            study=near_optimal_study,
            path_time_limit=near_opt_path_time_limit,
            path_mip_gap=near_opt_path_mip_gap,
        )
    solve_time = time.time() - t0

    print(f"  Solve time: {solve_time:.1f}s")
    print(f"  Solver status: {results.solver.status} / {results.solver.termination_condition}")

    # Extract results
    print("\n[5/6] Extracting and validating solved results...")
    t_phase = time.time()
    results_dict = model.get_results()
    gm = getattr(model, "_gm", None)
    solver_diagnostics = {}
    if gm is not None:
        for attr, key in [
            ("ObjVal", "objective_value"),
            ("ObjBound", "objective_bound"),
            ("MIPGap", "mip_gap"),
            ("NodeCount", "node_count"),
            ("IterCount", "iteration_count"),
            ("SolCount", "solution_count"),
        ]:
            try:
                solver_diagnostics[key] = getattr(gm, attr)
            except Exception:
                pass
        if (
            "mip_gap" not in solver_diagnostics
            and str(results.solver.status).lower() == "optimal"
            and "objective_value" in solver_diagnostics
            and "objective_bound" in solver_diagnostics
            and abs(
                float(solver_diagnostics["objective_value"])
                - float(solver_diagnostics["objective_bound"])
            ) <= 1e-6
        ):
            # Gurobi omits MIPGap when presolve fixes every integer variable;
            # an optimal solve with identical incumbent and bound has zero gap.
            solver_diagnostics["mip_gap"] = 0.0
    results_dict["solver"] = {
        "status": str(results.solver.status),
        "term_cond": str(results.solver.termination_condition),
        "solve_time_s": solve_time,
        "name": solver_name,
        "profile": profile_name,
        "options": opts,
        **solver_diagnostics,
    }
    results_dict["scenario"] = scenario_name
    results_dict["demand_scenario"] = config.DEMAND_SCENARIO
    results_dict["carbon_budget_case"] = config.CARBON_BUDGET_CASE
    capacity_path_counterfactual = finalize_capacity_path_diagnostics(
        results_dict,
        capacity_path_counterfactual,
        model.cap,
    )
    results_dict["capacity_path_counterfactual"] = capacity_path_counterfactual
    results_dict["planning_counterfactual"] = _planning_counterfactual_report(
        config, results_dict, capacity_path_counterfactual
    )
    results_dict["near_optimal_identity"] = near_optimal_identity
    results_dict["scenario_adjustments"] = {
        k: v for k, v in data.items()
        if str(k).startswith("_") and isinstance(v, (int, float, str, bool, dict))
    }
    if results_dict.get("summary") and results_dict.get("plants"):
        results_dict["capacity_dispatch_export_validation"] = (
            validate_exported_capacity_dispatch(
                results_dict,
                model.cap,
                model.years,
                minimum_utilization=float(config.MIN_OPERATING_UTILIZATION),
                # P0-3: the utilisation ramp constraint was removed, so None disables
                # the ramp check (see counterfactual.validate_exported_capacity_dispatch).
                maximum_utilization_change=None,
            )
        )
    else:
        results_dict["capacity_dispatch_export_validation"] = {
            "status": "not_run_no_incumbent",
            "reason": "The solver did not return a feasible incumbent.",
        }
    _summarize_solution(results_dict)
    print(f"  Extraction phase complete in {_sec(time.time() - t_phase)}")

    # Save
    print("\n[6/6] Saving JSON and analysis tables...")
    t_phase = time.time()
    output_dir = Path(output_dir) if output_dir else RESULTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{scenario_name}_results.json"
    with open(out_path, "w") as f:
        json.dump(results_dict, f, indent=2)
    print(f"  JSON saved: {out_path}")

    try:
        tables_dir = save_scenario_outputs(results_dict, output_dir, scenario_name)
        print(f"  Tables: {tables_dir}")
    except Exception as exc:
        print(f"  Warning: comprehensive result tables were not saved: {exc}")

    total_time = time.time() - t_start
    print(f"  Save phase complete in {_sec(time.time() - t_phase)}")
    print(f"\n  Output: {out_path}")
    print(f"  Total time: {total_time:.1f}s")

    return results_dict


def main():
    parser = argparse.ArgumentParser(description="V4 Cement CCS Optimization")
    parser.add_argument("--scenario", "-s", default="S1_baseline",
                        choices=sorted(set(
                            CORE_SCENARIOS
                            + list(SCENARIO_ALIASES)
                            + list(SCENARIO_POLICY_DEFAULTS)
                        )))
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--solver", default=None)
    parser.add_argument("--solver-profile", default=None,
                        choices=["screen", "explore", "final"],
                        help=("Predefined Gurobi runtime profile. screen = 3%% gap, "
                              "short warm-up: PRE-FINAL screening only, its numbers "
                              "must not enter the paper and the commitment-cost "
                              "interval cannot resolve at that gap. explore = 6%%. "
                              "final = 2%% base, for manuscript runs."))
    parser.add_argument("--time-limit", type=int, default=None)
    parser.add_argument("--mip-gap", type=float, default=None,
                        help="Override Gurobi MIPGap.")
    parser.add_argument("--threads", type=int, default=None,
                        help="Override Gurobi Threads. Use 0 for all available threads.")
    parser.add_argument("--tee", action="store_true",
                        help="Show Gurobi solver log.")
    parser.add_argument("--target-mode", default=None,
                        choices=["cumulative_budget", "milestone", "both", "none"])
    parser.add_argument(
        "--cumulative-reduction",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--budget-case",
        default=None,
        choices=list(getattr(config, "VALID_CARBON_BUDGET_CASES", ())),
        help="Select the fixed absolute carbon budget independently of demand.",
    )
    parser.add_argument("--cost-boundary", default=None,
                        choices=["incremental_mitigation", "full_accounting"])
    parser.add_argument("--include-carbon-cost", action="store_true",
                        help="Include carbon payments in the optimization objective.")
    parser.add_argument("--include-full-fuel-cost", action="store_true",
                        help="Include full net fuel expenditure in the optimization objective.")
    parser.add_argument(
        "--fixed-operating-cost", type=float, default=None,
        help="Override PLANT_FIXED_OPERATING_COST (CNY per t-yr of capacity).",
    )
    parser.add_argument(
        "--ccs-decline", default=None,
        help="Override the CCS cost decline case: slow | central | fast.",
    )
    parser.add_argument(
        "--demand-transport-mode", default=None,
        help=(
            "Override the clinker transport cost form: segmented | uniform | zero. "
            "'zero' is the market-side neutralisation sensitivity (clinker becomes "
            "nationally fungible, the pre-P0-4 assumption)."
        ),
    )
    parser.add_argument(
        "--discount-rate", type=float, default=None,
        help="Override DISCOUNT_RATE (e.g. 0.03 / 0.05 / 0.08).",
    )
    parser.add_argument(
        "--capture-efficiency", type=float, default=None,
        help=(
            "Override CCS capture efficiency. 0.90 is the central value (every "
            "published cement pathway model verified uses 0.90); 0.95 is the "
            "advanced-technology sensitivity that decides whether B50 is feasible."
        ),
    )
    parser.add_argument(
        "--ccr-path-case", default=None,
        help=(
            "Override the exogenous clinker/cement-ratio pathway: central "
            "(0.648 -> 0.550 by 2060) | high (GB 175-2023-consistent slow "
            "blending: 2030 held at the 2025 level, 0.590 by 2060)."
        ),
    )
    parser.add_argument(
        "--same-site-renewal-window", default=None,
        choices=["first_after_expiry", "any_after_expiry"],
        help=(
            "Renewal eligibility window. Central is first_after_expiry (one "
            "renewal, only in the first period after the 40-year expiry). "
            "any_after_expiry is the sensitivity that removes that timing friction."
        ),
    )
    parser.add_argument(
        "--max-annual-capacity-decline", type=float, default=None,
        help=(
            "VALIDATION ONLY: cap the national active-capacity decline at this "
            "annual rate (observed 2016-2020 band 0.05-0.10). Not used in the "
            "central scenario; the unconstrained decline is always reported under "
            "capacity_decline_diagnostic."
        ),
    )
    parser.add_argument(
        "--max-capacity-decline-per-period", type=float, default=None,
        help=(
            "SCENARIO ONLY (slow-exit institutional friction): cap the national "
            "active-capacity decline at this fraction per FIVE-YEAR period "
            "(0.10 = -10%% every five years = 2.085%%/yr equivalent). Takes the "
            "five-year fraction directly, unlike --max-annual-capacity-decline, "
            "which is per year and easy to mis-enter. Retains idle capacity by "
            "construction, so the resulting utilisation is an artefact of the cap."
        ),
    )
    parser.add_argument(
        "--af-energy-caliber", default=None,
        choices=["plant_heat_demand", "flat_tce"],
        help=(
            "Heat-demand caliber for the AF constraints. plant_heat_demand "
            "(central, 2026-09-13) uses each plant's own intensity "
            "h_i = fuel_ef/COAL_EF times (1-EE) and a single COAL_EF AF credit. "
            "flat_tce reproduces the pre-2026-09-13 behaviour (flat 0.105 tce/t, "
            "no EE) and exists only for audit comparison."
        ),
    )
    parser.add_argument(
        "--af-biogenic-co2-per-tce", type=float, default=None,
        help=(
            "Biogenic CO2 physically released per tce of AF burned, in tCO2/tce. "
            "This is the conversion between the budget-credited tonnage and the "
            "physical flue-gas tonnage the capture unit, pipeline and storage site "
            "handle. OPEN EVIDENCE GAP: the central value is 0.0 (the two calibers "
            "coincide); a MOEE-mix-based sensitivity is ~1.31. No BECCS negative "
            "emission credit is granted at any value."
        ),
    )
    parser.add_argument(
        "--af-investment-per-tce", type=float, default=None,
        help=(
            "AF retrofit investment in CNY per (tce/yr) of ADDED nameplate handling "
            "capacity. Central 790.48 (bottom-up range 121-1400: no-pretreatment "
            "projects to full-prepare projects). Stated in the model's own unit so "
            "no hidden division by the clinker heat intensity sits in the chain."
        ),
    )
    parser.add_argument(
        "--af-om-per-tce", type=float, default=None,
        help=(
            "AF handling O&M in CNY per tce ACTUALLY handled. Central 40.0, which "
            "sits at the bottom of the 42-305 evidence range (grade C, low)."
        ),
    )
    parser.add_argument(
        "--beta-af", type=float, default=None,
        help=("AF fossil-CO2 displacement coefficient: substituting 1 tce of AF for "
              "1 tce of coal reduces ACCOUNTING CO2 by beta * COAL_EF. Central 0.55, "
              "but that value is GRADE C (it sits at the LOWER EDGE of the "
              "defensible 0.55-0.69 range; see config_v5 BETA_AF). Sensitivity 0.69."),
    )
    parser.add_argument(
        "--planning-mode", default=None,
        choices=["joint", "stepwise_capacity", "stepwise_low_carbon"],
        help=(
            "J/S counterfactual (2026-09-13). joint = the central model. "
            "stepwise_capacity = S stage 1: carbon target OFF and CCS/AF fixed to "
            "zero, so the fleet is chosen on conventional resource cost alone. "
            "stepwise_low_carbon = S stage 2: requires --fixed-capacity-path; AF and "
            "CCS re-enabled under the SAME budget. Both stages must share demand, "
            "transport, cost accounting and budget for R = C_S - C_J to be "
            "interpretable."
        ),
    )
    parser.add_argument(
        "--demand-market-node-file", default=None,
        help=("Alternate market-node CSV (see build_market_nodes.py --out-nodes). "
              "Used for the spatial robustness check, e.g. the ~75-node aggregation: "
              "point the run at an alternative build instead of overwriting the "
              "central inputs. The effective path is recorded in effective_config."),
    )
    parser.add_argument(
        "--demand-market-arc-file", default=None,
        help="Alternate market-arc CSV, paired with --demand-market-node-file.",
    )
    parser.add_argument(
        "--ccs-min-operating-years", type=int, default=None,
        help=(
            "Override CCS_MIN_OPERATING_YEARS (central 15). 0 removes the "
            "commitment constraint set by construction -- the K1/K2 lock-in "
            "counterfactual arm (registered 2026-09-14)."
        ),
    )
    parser.add_argument(
        "--terminal-value-mode", default=None,
        choices=["none", "annuity_consistent_guarded"],
        help=(
            "R6 end-of-horizon arm: annuity_consistent_guarded charges stock "
            "investments (CCS additions, same-site renewal) at their "
            "within-horizon annuity share, with no salvage for vintages whose "
            "in-horizon service is shorter than 15 years. Central is none."
        ),
    )
    parser.add_argument(
        "--storage-rate-scale", type=float, default=None,
        help=(
            "Scale the effective per-sink injection-rate cap (central 1.0; "
            "R8 sensitivity arm uses 2.0). The rate constraint binds on ~60% "
            "of used sink-periods, so this tests whether CCS siting is an "
            "artifact of the injection-rate calibration."
        ),
    )
    parser.add_argument(
        "--demand-transport-scale", type=float, default=None,
        help=(
            "Scale the clinker transport rates. 1.5 puts the short-haul road rate "
            "at the measured upper range (0.675) and materially opens utilization; "
            "2.0 is a non-measured diagnostic. The short-haul rate governs the "
            "retention radius F/t and hence u."
        ),
    )
    parser.add_argument(
        "--eor-revenue", type=float, default=None,
        help=(
            "EOR external-revenue credit in CNY/tCO2. Central default is 0 (not "
            "credited; a payment between agents is a transfer, not a resource-cost "
            "reduction). Pass 80 for the 'external revenue offset' sensitivity."
        ),
    )
    parser.add_argument(
        "--demand-scenario",
        default=None,
        choices=list(getattr(config, "VALID_DEMAND_SCENARIOS", ())),
        help="Select the national cement-demand pathway independently of S1-S5.",
    )
    parser.add_argument(
        "--fixed-capacity-path",
        default=None,
        help=(
            "Reference result JSON whose plant operation (y) and same-site "
            "renewal (r) path is fixed before re-optimizing the active scenario."
        ),
    )
    parser.add_argument(
        "--fixed-capacity-mode",
        default="turnover",
        choices=["turnover", "turnover_and_dispatch"],
        help=(
            "Fix y/r only (turnover) or y/r/u "
            "(turnover_and_dispatch) from the reference result."
        ),
    )
    parser.add_argument(
        "--near-opt-identity-reference",
        default=None,
        help=(
            "Reference result JSON whose operating-capacity identity is used "
            "for a near-optimal closest/farthest path experiment."
        ),
    )
    parser.add_argument(
        "--near-opt-cost-reference",
        default=None,
        help="Active-scenario result JSON that defines the epsilon cost cap.",
    )
    parser.add_argument(
        "--near-opt-cost-tolerance",
        type=float,
        default=0.0,
        help="Allowed fractional cost increase above the cost-reference incumbent.",
    )
    parser.add_argument(
        "--near-opt-direction",
        choices=["closest", "farthest"],
        default="closest",
        help="Minimize or maximize operating-capacity identity distance.",
    )
    parser.add_argument(
        "--near-opt-scope",
        choices=["full_path", "terminal"],
        default="full_path",
        help="Extremize the full post-2025 path or only the 2060 backbone.",
    )
    parser.add_argument(
        "--plant-lifetime",
        type=int,
        default=None,
        help=(
            "Override PLANT_LIFETIME_YEARS for structural sensitivity runs. "
            "The value is recorded in the result metadata."
        ),
    )
    parser.add_argument(
        "--min-operating-utilization",
        type=float,
        default=None,
        help=(
            "Override MIN_OPERATING_UTILIZATION for isolated structural "
            "sensitivity runs. The value is recorded in result metadata."
        ),
    )
    parser.add_argument(
        "--near-opt-path-time-limit",
        type=int,
        default=None,
        help="Optional time limit for the identity-extremum phase.",
    )
    parser.add_argument(
        "--near-opt-path-mip-gap",
        type=float,
        default=None,
        help="Optional MIP gap for the identity-extremum phase.",
    )
    args = parser.parse_args()

    run_scenario(
        scenario_name=args.scenario,
        output_dir=args.output,
        solver=args.solver,
        solver_profile=args.solver_profile,
        time_limit=args.time_limit,
        mip_gap=args.mip_gap,
        threads=args.threads,
        tee=args.tee,
        target_mode=args.target_mode,
        cumulative_reduction=args.cumulative_reduction,
        budget_case=args.budget_case,
        cost_boundary=args.cost_boundary,
        include_carbon_cost=args.include_carbon_cost,
        include_full_fuel_cost=args.include_full_fuel_cost,
        demand_scenario=args.demand_scenario,
        fixed_capacity_path=args.fixed_capacity_path,
        fixed_capacity_mode=args.fixed_capacity_mode,
        near_opt_identity_reference=args.near_opt_identity_reference,
        near_opt_cost_reference=args.near_opt_cost_reference,
        near_opt_cost_tolerance=args.near_opt_cost_tolerance,
        near_opt_direction=args.near_opt_direction,
        near_opt_scope=args.near_opt_scope,
        near_opt_path_time_limit=args.near_opt_path_time_limit,
        near_opt_path_mip_gap=args.near_opt_path_mip_gap,
        plant_lifetime=args.plant_lifetime,
        min_operating_utilization=args.min_operating_utilization,
        fixed_operating_cost=args.fixed_operating_cost,
        ccs_decline=args.ccs_decline,
        demand_transport_mode=args.demand_transport_mode,
        discount_rate=args.discount_rate,
        capture_efficiency=args.capture_efficiency,
        ccr_path_case=args.ccr_path_case,
        same_site_renewal_window=args.same_site_renewal_window,
        max_annual_capacity_decline=args.max_annual_capacity_decline,
        max_capacity_decline_per_period=args.max_capacity_decline_per_period,
        af_energy_caliber=args.af_energy_caliber,
        af_biogenic_co2_per_tce=args.af_biogenic_co2_per_tce,
        af_investment_per_tce=args.af_investment_per_tce,
        af_om_per_tce=args.af_om_per_tce,
        beta_af=args.beta_af,
        planning_mode=args.planning_mode,
        demand_market_node_file=args.demand_market_node_file,
        demand_market_arc_file=args.demand_market_arc_file,
        demand_transport_scale=args.demand_transport_scale,
        eor_revenue=args.eor_revenue,
        ccs_min_operating_years=args.ccs_min_operating_years,
        terminal_value_mode=args.terminal_value_mode,
        storage_rate_scale=args.storage_rate_scale,
    )


if __name__ == "__main__":
    main()
