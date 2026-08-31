"""
Main entry point for v4 model.
Runs cement CCS optimization with v4 architecture.
"""

import argparse
import json
import time
import sys
from pathlib import Path

# Ensure src_v4 is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src_v4.config_v4 import config, RESULTS_DIR, SOLVER, SOLVER_OPTIONS, SOLVER_PROFILES
from src_v4.data_loader_v4 import load_all
from src_v4.counterfactual import (
    finalize_capacity_path_diagnostics,
    fix_capacity_turnover_from_results,
    validate_exported_capacity_dispatch,
)
from src_v4.near_optimal_identity import (
    configure_near_optimal_identity,
    solve_near_optimal_identity,
)
from src_v4.model.final_builder import V4Model
from src_v4.results.extract import save_scenario_outputs


DEFAULT_OFFSHORE_PARAMS = dict(getattr(config, "OFFSHORE_PARAMS", {}))
DEFAULT_DEMAND_SCENARIO = str(getattr(config, "DEMAND_SCENARIO", "d_medium"))
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

    def uniform_engineering_plant_access():
        plants = data["plants"][["plant_id", "province", "capacity"]].copy()
        plants["plant_id"] = plants["plant_id"].astype(int)
        plants["capacity"] = plants["capacity"].astype(float)
        result = {}
        for row in plants.itertuples(index=False):
            annual_capacity_kt = (
                float(row.capacity) * float(config.CAPACITY_T_DAY_TO_KT_YR)
            )
            for yr in config.T_LIST:
                result[(int(row.plant_id), int(yr))] = (
                    float(config.AF_ENGINEERING_TSR_PATH[int(yr)])
                    * annual_capacity_kt
                    * float(config.TCE_PER_T_CLINKER)
                )
        return result

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
        data["plant_af_access_ktce"] = {
            key: (float(value) if int(key[1]) == 2025 else 0.6 * float(value))
            for key, value in data["plant_af_access_ktce"].items()
        }

    elif scenario_name == "S3_all_spatial_equalized":
        # S3 all-spatial-equalized counterfactual:
        # Preserve national AF totals while removing future resource-location
        # advantages. Province pools are equalized by installed capacity. Plants
        # then share each province pool and face only the common engineering TSR
        # ceiling, rather than a pre-assigned, non-transferable plant quota.
        # ARM and EE are already external national paths; LCC remains national.
        original_pool = dict(data["province_af_pool_ktce"])
        original_access = dict(data["plant_af_access_ktce"])
        equal_pool = capacity_share_pool_by_year(original_pool)
        equal_access = uniform_engineering_plant_access()
        data["province_af_pool_ktce"] = {
            key: (original_pool[key] if int(key[1]) == 2025 else value)
            for key, value in equal_pool.items()
        }
        data["plant_af_access_ktce"] = {
            key: (original_access.get(key, value) if int(key[1]) == 2025 else value)
            for key, value in equal_access.items()
        }
        data["_af_spatial_equalized"] = True
        data["_af_plant_access_mode"] = (
            "uniform_engineering_ceiling_with_shared_equalized_province_pool"
        )
        data["_af_equalized_pool_total_ktce_by_year"] = {
            int(year): sum(
                float(value)
                for (province, pool_year), value in data["province_af_pool_ktce"].items()
                if int(pool_year) == int(year)
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
    config.EMISSION_TARGET_MODE = policy_defaults["target_mode"]
    config.CARBON_BUDGET_CASE = str(policy_defaults["budget_case"]).upper()
    config.INCLUDE_CARBON_COST_IN_OBJECTIVE = bool(policy_defaults["include_carbon_cost"])
    config.INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE = False
    config.COST_BOUNDARY = "incremental_mitigation"
    config.OFFSHORE_PARAMS = dict(DEFAULT_OFFSHORE_PARAMS)
    config.DEMAND_SCENARIO = str(
        demand_scenario or DEFAULT_DEMAND_SCENARIO
    ).lower()

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
    results_dict["near_optimal_identity"] = near_optimal_identity
    results_dict["scenario_adjustments"] = {
        k: v for k, v in data.items()
        if str(k).startswith("_") and isinstance(v, (int, float, str, bool, dict))
    }
    results_dict["capacity_dispatch_export_validation"] = (
        validate_exported_capacity_dispatch(
            results_dict,
            model.cap,
            model.years,
            minimum_utilization=float(config.MIN_OPERATING_UTILIZATION),
            maximum_utilization_change=float(
                config.MAX_UTILIZATION_CHANGE_PER_PERIOD
            ),
        )
    )
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
                        choices=["explore", "final"],
                        help="Use a predefined Gurobi runtime profile.")
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
    )


if __name__ == "__main__":
    main()
