"""Near-optimal capacity-identity experiments for the final V4 model.

The experiment adds an epsilon cost constraint around an already solved
scenario and then extremizes operating-capacity identity relative to a
reference plan.  A second solve fixes the best-known identity distance and
restores the economic objective, so exported results remain interpretable in
the model's original cost units.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from pyomo.environ import Constraint, Expression, Objective, maximize, minimize

from src_v5.counterfactual import (
    CapacityPathError,
    extract_capacity_turnover_path,
    validate_reference_incumbent,
)


class NearOptimalIdentityError(ValueError):
    """Raised when a near-optimal identity experiment is not well defined."""


def _load_results(path, label):
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise NearOptimalIdentityError(f"{label} does not exist: {source_path}")
    raw = source_path.read_bytes()
    try:
        results = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NearOptimalIdentityError(f"{label} is not valid JSON: {source_path}") from exc
    try:
        validate_reference_incumbent(results)
    except CapacityPathError as exc:
        raise NearOptimalIdentityError(f"{label} has no usable incumbent: {exc}") from exc
    return source_path, raw, results


def _require_shared_policy(results, v4_model, label):
    demand = results.get("demand_scenario")
    if str(demand) != str(v4_model.demand_scenario):
        raise NearOptimalIdentityError(
            f"{label} demand mismatch ({demand!r} != {v4_model.demand_scenario!r})"
        )
    budget = results.get("carbon_budget_case")
    active_budget = getattr(v4_model.config, "CARBON_BUDGET_CASE", None)
    if str(budget) != str(active_budget):
        raise NearOptimalIdentityError(
            f"{label} carbon-budget mismatch ({budget!r} != {active_budget!r})"
        )


def _finite_solver_value(results, key, label):
    try:
        number = float((results.get("solver") or {})[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise NearOptimalIdentityError(f"{label} has no valid solver.{key}") from exc
    if not math.isfinite(number):
        raise NearOptimalIdentityError(f"{label} solver.{key} is not finite")
    return number


def _binary_mip_start(results, v4_model):
    """Return a partial Gurobi start for the active scenario incumbent."""

    plants = results.get("plants") or {}
    start = {}
    for plant_id in v4_model.I:
        record = plants.get(str(plant_id), plants.get(plant_id, {}))
        for variable in ("y", "r", "z"):
            series = record.get(variable) or {}
            for period_idx, year in enumerate(v4_model.years):
                key = str(year) if str(year) in series else year
                if key not in series:
                    continue
                start[f"{variable}({plant_id}_{period_idx})"] = float(series[key])
    return start


def configure_near_optimal_identity(
    v4_model,
    *,
    active_scenario,
    identity_reference_path,
    cost_reference_path,
    cost_tolerance,
    direction="closest",
    scope="full_path",
):
    """Attach the cost cap and identity objective to a built V4 model."""

    if v4_model.model is None:
        raise NearOptimalIdentityError("the V4 model must be built first")
    if direction not in {"closest", "farthest"}:
        raise NearOptimalIdentityError("direction must be 'closest' or 'farthest'")
    if scope not in {"full_path", "terminal"}:
        raise NearOptimalIdentityError("scope must be 'full_path' or 'terminal'")
    try:
        epsilon = float(cost_tolerance)
    except (TypeError, ValueError) as exc:
        raise NearOptimalIdentityError("cost tolerance must be numeric") from exc
    if not math.isfinite(epsilon) or epsilon < 0:
        raise NearOptimalIdentityError("cost tolerance must be finite and non-negative")

    identity_path, identity_raw, identity_results = _load_results(
        identity_reference_path, "identity reference"
    )
    cost_path, cost_raw, cost_results = _load_results(
        cost_reference_path, "cost reference"
    )
    _require_shared_policy(identity_results, v4_model, "identity reference")
    _require_shared_policy(cost_results, v4_model, "cost reference")

    if str(cost_results.get("scenario")) != str(active_scenario):
        raise NearOptimalIdentityError(
            "cost reference scenario does not match the active scenario "
            f"({cost_results.get('scenario')!r} != {active_scenario!r})"
        )
    active_boundary = str(getattr(v4_model.config, "COST_BOUNDARY", ""))
    if str(cost_results.get("cost_boundary")) != active_boundary:
        raise NearOptimalIdentityError(
            "cost reference boundary does not match the active model "
            f"({cost_results.get('cost_boundary')!r} != {active_boundary!r})"
        )
    for key, active in (
        (
            "include_carbon_cost_in_objective",
            bool(getattr(v4_model.config, "INCLUDE_CARBON_COST_IN_OBJECTIVE", False)),
        ),
        (
            "include_full_fuel_cost_in_objective",
            bool(getattr(v4_model.config, "INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE", False)),
        ),
    ):
        if bool(cost_results.get(key, False)) != active:
            raise NearOptimalIdentityError(
                f"cost reference {key} does not match the active model"
            )

    reference_path = extract_capacity_turnover_path(
        identity_results, v4_model.I, v4_model.years, include_utilization=False
    )
    reference_cost = _finite_solver_value(cost_results, "objective_value", "cost reference")
    absolute_guard = max(1.0, abs(reference_cost) * 1e-9)
    cost_cap = reference_cost * (1.0 + epsilon) + absolute_guard

    m = v4_model.model
    m.near_optimal_cost_cap = Constraint(expr=m.total_cost.expr <= cost_cap)

    if scope == "terminal":
        periods = [v4_model.T[-1]]
        objective_units = "kt_per_year_capacity_symmetric_difference"
    else:
        periods = [t for t in v4_model.T if t > 0]
        objective_units = "kt_capacity_year_symmetric_difference"

    terms = []
    for plant_id in v4_model.I:
        for period_idx in periods:
            reference_y = reference_path[("y", plant_id, period_idx)]
            mismatch = 1 - m.y[plant_id, period_idx] if reference_y else m.y[plant_id, period_idx]
            weight = float(v4_model.cap[plant_id])
            if scope == "full_path":
                weight *= float(v4_model.period_weight[v4_model.years[period_idx]])
            terms.append(weight * mismatch)

    m.near_optimal_identity_distance = Expression(expr=sum(terms))
    m.total_cost.deactivate()
    m.near_optimal_identity_objective = Objective(
        expr=m.near_optimal_identity_distance,
        sense=minimize if direction == "closest" else maximize,
    )

    public = {
        "enabled": True,
        "design": "epsilon_constrained_operating_capacity_identity_extremum",
        "active_scenario": str(active_scenario),
        "direction": direction,
        "scope": scope,
        "identity_variable": "y",
        "identity_metric": "capacity_weighted_symmetric_difference",
        "objective_units": objective_units,
        "base_year_excluded": scope == "full_path",
        "cost_tolerance_fraction": epsilon,
        "reference_cost_kCNY": reference_cost,
        "cost_cap_kCNY": cost_cap,
        "absolute_cost_guard_kCNY": absolute_guard,
        "identity_reference_path": str(identity_path),
        "identity_reference_sha256": hashlib.sha256(identity_raw).hexdigest(),
        "identity_reference_scenario": identity_results.get("scenario"),
        "cost_reference_path": str(cost_path),
        "cost_reference_sha256": hashlib.sha256(cost_raw).hexdigest(),
        "cost_reference_scenario": cost_results.get("scenario"),
        "interpretation": (
            "The first phase extremizes operating-capacity identity within an "
            "epsilon cost cap. The second phase fixes the best-known identity "
            "distance and minimizes the original system cost."
        ),
    }
    return {
        "public": public,
        "direction": direction,
        "mip_start": _binary_mip_start(cost_results, v4_model),
    }


def _solver_diagnostics(v4_model):
    gm = getattr(v4_model, "_gm", None)
    diagnostics = {"status": getattr(v4_model, "_solve_status", "unknown")}
    if gm is None:
        return diagnostics
    for attr, key in (
        ("ObjVal", "objective_value"),
        ("ObjBound", "objective_bound"),
        ("MIPGap", "mip_gap"),
        ("NodeCount", "node_count"),
        ("IterCount", "iteration_count"),
        ("SolCount", "solution_count"),
        ("Runtime", "runtime_s"),
    ):
        try:
            diagnostics[key] = float(getattr(gm, attr))
        except Exception:
            pass
    diagnostics["mip_start_values_applied"] = int(
        getattr(v4_model, "_last_mip_start_applied", 0)
    )
    if (
        "mip_gap" not in diagnostics
        and str(diagnostics.get("status", "")).lower() == "optimal"
        and "objective_value" in diagnostics
        and "objective_bound" in diagnostics
        and abs(
            float(diagnostics["objective_value"])
            - float(diagnostics["objective_bound"])
        ) <= 1e-6
    ):
        diagnostics["mip_gap"] = 0.0
    return diagnostics


def _fix_phase_one_binary_path(v4_model, phase_one_start):
    """Fix the complete phase-one binary path for a guaranteed tie-break fallback.

    The preferred second phase fixes only the optimized identity distance.  If
    that razor-thin face yields no incumbent, the already feasible phase-one
    y/r/z path defines a conservative representative subset of the same face.
    Re-optimizing continuous decisions and costs on that subset preserves the
    epsilon-cost and identity claims without pretending to search a wider
    near-optimal frontier.
    """

    fixed = 0
    model = v4_model.model
    for variable_name in ("y", "r", "z"):
        component = getattr(model, variable_name)
        for index in component:
            indices = index if isinstance(index, tuple) else (index,)
            solver_name = (
                f"{variable_name}("
                + "_".join(str(value) for value in indices)
                + ")"
            )
            if solver_name not in phase_one_start:
                continue
            component[index].fix(int(round(float(phase_one_start[solver_name]))))
            fixed += 1
    if fixed == 0:
        raise NearOptimalIdentityError(
            "phase-one binary-path fallback could not map any solver variables"
        )
    return fixed


def solve_near_optimal_identity(
    v4_model,
    *,
    solver,
    cost_options,
    study,
    path_time_limit=None,
    path_mip_gap=None,
):
    """Run identity extremization followed by an economic tie-break solve."""

    path_options = dict(cost_options)
    if study["direction"] == "farthest":
        # The cost-reference start has zero distance in the S1 null case, so
        # the first phase must prioritize finding alternative incumbents.
        path_options["MIPFocus"] = 1
        path_options["Heuristics"] = max(
            0.5, float(path_options.get("Heuristics", 0.0))
        )
    else:
        # Closest-path cases need a strong lower bound on unavoidable distance.
        path_options["MIPFocus"] = 2
        path_options["Heuristics"] = max(
            0.2, float(path_options.get("Heuristics", 0.0))
        )
    if path_time_limit is not None:
        path_options["TimeLimit"] = int(path_time_limit)
    if path_mip_gap is not None:
        path_options["MIPGap"] = float(path_mip_gap)

    first = v4_model.solve(
        solver=solver,
        options=path_options,
        mip_start=study.get("mip_start"),
    )
    phase_one = _solver_diagnostics(v4_model)
    if float(phase_one.get("solution_count", 0)) <= 0:
        raise NearOptimalIdentityError(
            "identity-extremum phase produced no feasible incumbent within the cost cap"
        )

    identity_incumbent = float(phase_one["objective_value"])
    numerical_lock = max(1e-6, abs(identity_incumbent) * 1e-8)
    m = v4_model.model
    if study["direction"] == "closest":
        m.near_optimal_identity_lock = Constraint(
            expr=m.near_optimal_identity_distance <= identity_incumbent + numerical_lock
        )
    else:
        m.near_optimal_identity_lock = Constraint(
            expr=m.near_optimal_identity_distance >= identity_incumbent - numerical_lock
        )
    m.near_optimal_identity_objective.deactivate()
    m.total_cost.activate()

    gm = getattr(v4_model, "_gm", None)
    phase_one_start = {}
    if gm is not None:
        for variable in gm.getVars():
            try:
                phase_one_start[variable.VarName] = float(variable.X)
            except Exception:
                pass

    second = v4_model.solve(
        solver=solver,
        options=cost_options,
        mip_start=phase_one_start,
    )
    phase_two = _solver_diagnostics(v4_model)
    if float(phase_two.get("solution_count", 0)) <= 0:
        # The identity lock leaves a razor-thin feasible set; the bound-focused
        # cost profile can fail to reproduce the phase-one incumbent.  Restrict
        # the fallback to the already feasible phase-one binary path, then
        # re-optimize continuous decisions and the economic objective.  This is
        # conservative for identity flexibility and remains within the same
        # epsilon cost cap.
        fixed_binary_values = _fix_phase_one_binary_path(
            v4_model, phase_one_start
        )
        retry_options = dict(cost_options)
        retry_options["MIPFocus"] = 1
        retry_options["Heuristics"] = max(
            0.5, float(retry_options.get("Heuristics", 0.0))
        )
        retry_options["TimeLimit"] = int(retry_options.get("TimeLimit", 240)) * 2
        second = v4_model.solve(
            solver=solver,
            options=retry_options,
            mip_start=phase_one_start,
        )
        phase_two = _solver_diagnostics(v4_model)
        phase_two["tiebreak_retry"] = True
        phase_two["tiebreak_recovery_mode"] = (
            "phase_one_binary_path_fixed"
        )
        phase_two["fixed_phase_one_binary_values"] = fixed_binary_values
        if float(phase_two.get("solution_count", 0)) <= 0:
            raise NearOptimalIdentityError(
                "economic tie-break produced no incumbent even after fixing "
                "the feasible phase-one binary path"
            )

    public = dict(study["public"])
    public.update(
        {
            "identity_phase_solver": phase_one,
            "identity_distance_incumbent": identity_incumbent,
            "identity_distance_bound": phase_one.get("objective_bound"),
            "identity_lock_numerical_tolerance": numerical_lock,
            "economic_tiebreak_solver": phase_two,
            "realized_cost_kCNY": phase_two.get("objective_value"),
        }
    )
    return second, public
