"""Counterfactual controls for separating capacity and decarbonization choices.

The paper's main model jointly chooses capacity turnover and low-carbon
investments.  For the headline feedback counterfactual, this module fixes only
the discrete capacity-turnover path (operation ``y`` and same-site renewal
``r``) from a previously solved reference case.  Utilization, AF, CCS, and
transport and storage decisions remain endogenous.  A stricter secondary mode
also fixes utilization to separate dispatch from asset-turnover feedback.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

# Width of the slack band released around a fixed utilization target.  Gurobi
# can return u residuals up to ~5e-6 on inactive units (y=0), so the band must
# stay above the integer-feasibility tolerance; audits that compare fixed u
# against the reference path must accept the same span.
DISPATCH_BAND_TOLERANCE = 1e-5
# A snapped reference can miss an equality by a few kilograms on a national
# row measured in hundreds of millions of tonnes.  The dispatch band remains
# the authoritative feasibility test, but a separate relative guard prevents
# material reference-demand inconsistencies from being hidden by that band.
REFERENCE_DEMAND_ABSOLUTE_TOLERANCE_KT = 1e-3
REFERENCE_DEMAND_RELATIVE_TOLERANCE = 5e-8


class CapacityPathError(ValueError):
    """Raised when a reference result cannot define a valid capacity path."""


def validate_reference_incumbent(results):
    """Require a complete, finite incumbent, including at solver limits.

    A time-limit or suboptimal status does not invalidate the plant decisions
    when Gurobi reports a positive solution count and finite incumbent.  The
    objective bound and MIP gap remain available for uncertainty accounting.
    """

    solver = results.get("solver")
    if not isinstance(solver, dict):
        raise CapacityPathError("reference result has no solver diagnostics")

    raw_status = results.get("status", solver.get("status", ""))
    status = "".join(character for character in str(raw_status).lower() if character.isalnum())
    usable_statuses = {"optimal", "feasible", "timelimit", "suboptimal"}
    if status not in usable_statuses:
        raise CapacityPathError(
            f"reference result does not contain a usable incumbent (status={raw_status!r})"
        )

    try:
        solution_count = float(solver["solution_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CapacityPathError(
            "reference solver has no valid incumbent solution count"
        ) from exc
    if not math.isfinite(solution_count) or solution_count <= 0:
        raise CapacityPathError("reference solver reports zero incumbent solutions")

    try:
        objective_value = float(solver["objective_value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CapacityPathError(
            "reference solver has no finite incumbent objective"
        ) from exc
    if not math.isfinite(objective_value):
        raise CapacityPathError("reference solver has no finite incumbent objective")


def _binary(value, label, tolerance=1e-6):
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise CapacityPathError(f"{label} is not numeric: {value!r}") from exc
    rounded = int(round(numeric))
    if rounded not in (0, 1) or abs(numeric - rounded) > tolerance:
        raise CapacityPathError(f"{label} is not binary: {value!r}")
    return rounded


def _unit_interval(value, label, tolerance=1e-6):
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise CapacityPathError(f"{label} is not numeric: {value!r}") from exc
    if numeric < -tolerance or numeric > 1 + tolerance:
        raise CapacityPathError(f"{label} is outside [0, 1]: {value!r}")
    return min(1.0, max(0.0, numeric))


def extract_capacity_turnover_path(
    results, plant_ids, years, include_utilization=False
):
    """Validate and extract capacity decisions from a solved result.

    The reference must cover the exact plant set and every model period.  This
    prevents a stale result file from silently fixing only part of a new model.
    """

    plants = results.get("plants")
    if not isinstance(plants, dict):
        raise CapacityPathError("reference result has no 'plants' mapping")

    expected_ids = {int(plant_id) for plant_id in plant_ids}
    try:
        available_ids = {int(plant_id) for plant_id in plants}
    except (TypeError, ValueError) as exc:
        raise CapacityPathError("reference result contains a non-integer plant id") from exc

    missing = sorted(expected_ids - available_ids)
    extra = sorted(available_ids - expected_ids)
    if missing or extra:
        raise CapacityPathError(
            "reference plant set does not match the active model "
            f"(missing={missing[:10]}, extra={extra[:10]})"
        )

    path = {}
    for plant_id in sorted(expected_ids):
        record = plants[str(plant_id)] if str(plant_id) in plants else plants[plant_id]
        if not isinstance(record, dict):
            raise CapacityPathError(f"plant {plant_id} record is not a mapping")
        variables = ("y", "r", "u") if include_utilization else ("y", "r")
        for variable in variables:
            series = record.get(variable)
            if not isinstance(series, dict):
                raise CapacityPathError(
                    f"plant {plant_id} has no '{variable}' period mapping"
                )
            for period_idx, year in enumerate(years):
                key = str(year) if str(year) in series else year
                if key not in series:
                    raise CapacityPathError(
                        f"plant {plant_id} {variable} is missing period {year}"
                    )
                label = f"plant {plant_id} {variable}[{year}]"
                converter = _unit_interval if variable == "u" else _binary
                path[(variable, plant_id, period_idx)] = converter(series[key], label)
    return path


def _reference_dispatch_preflight(
    v4_model,
    path,
    *,
    dispatch_band_tolerance,
    reference_repair_tolerance,
):
    """Repair solver-rounding residue and prove that the dispatch band is usable.

    Exported binary variables are rounded to exact 0/1 values, whereas a solver
    can legally return a small continuous utilization alongside a binary value
    that is within its integrality tolerance of zero.  Only such bounded
    residue is repaired.  Material contradictions still fail before any
    variables are fixed.
    """

    band = float(dispatch_band_tolerance)
    repair_tolerance = float(reference_repair_tolerance)
    if not 0.0 < band <= 1e-4:
        raise CapacityPathError(
            "dispatch_band_tolerance must be in (0, 1e-4]"
        )
    if repair_tolerance < band or repair_tolerance > 1e-4:
        raise CapacityPathError(
            "reference_repair_tolerance must be >= dispatch_band_tolerance "
            "and <=1e-4"
        )

    repaired = dict(path)
    repairs = []
    u_min = float(v4_model.config.MIN_OPERATING_UTILIZATION)
    ramp = float(v4_model.config.MAX_UTILIZATION_CHANGE_PER_PERIOD)

    for plant_id in v4_model.I:
        renewal_count = sum(
            path[("r", plant_id, period_idx)]
            for period_idx in range(len(v4_model.years))
        )
        if renewal_count > 1:
            raise CapacityPathError(
                f"reference plant {plant_id} contains {renewal_count} renewals"
            )
        for period_idx, year in enumerate(v4_model.years):
            y_value = path[("y", plant_id, period_idx)]
            r_value = path[("r", plant_id, period_idx)]
            u_value = path[("u", plant_id, period_idx)]
            repaired_u = u_value
            reason = None

            if y_value == 0 and u_value > 0.0:
                if u_value > repair_tolerance:
                    raise CapacityPathError(
                        f"plant {plant_id} u[{year}]={u_value} exceeds y=0 "
                        f"by more than the repair tolerance {repair_tolerance}"
                    )
                repaired_u = 0.0
                reason = "solver_integrality_rounding_residue_above_rounded_y_zero"
            elif period_idx > 0 and y_value == 1 and u_value < u_min:
                if u_min - u_value > repair_tolerance:
                    raise CapacityPathError(
                        f"plant {plant_id} u[{year}]={u_value} is materially "
                        f"below u_min={u_min} with y=1"
                    )
                repaired_u = u_min
                reason = "solver_feasibility_rounding_residue_below_u_min"

            if reason is not None:
                repaired[("u", plant_id, period_idx)] = repaired_u
                repairs.append({
                    "plant_id": int(plant_id),
                    "year": int(year),
                    "original_u": float(u_value),
                    "repaired_u": float(repaired_u),
                    "absolute_repair": abs(float(repaired_u) - float(u_value)),
                    "reason": reason,
                })

            if period_idx == 0:
                if y_value != 1:
                    raise CapacityPathError(
                        f"reference plant {plant_id} has y[2025]={y_value}, expected 1"
                    )
                continue

            prior_y = path[("y", plant_id, period_idx - 1)]
            if y_value > prior_y + r_value:
                raise CapacityPathError(
                    f"reference plant {plant_id} violates operating continuity at {year}"
                )
            if r_value > prior_y:
                raise CapacityPathError(
                    f"reference plant {plant_id} renews without prior operation at {year}"
                )

    # Verify utilization bounds and ramps after the narrowly defined repair.
    for plant_id in v4_model.I:
        for period_idx, year in enumerate(v4_model.years):
            y_value = path[("y", plant_id, period_idx)]
            u_value = repaired[("u", plant_id, period_idx)]
            if u_value < -1e-12 or u_value > y_value + 1e-12:
                raise CapacityPathError(
                    f"repaired plant {plant_id} u[{year}]={u_value} violates u<=y={y_value}"
                )
            if period_idx > 0 and u_value < u_min * y_value - 1e-12:
                raise CapacityPathError(
                    f"repaired plant {plant_id} u[{year}]={u_value} violates "
                    f"u>=u_min*y={u_min * y_value}"
                )
            if period_idx == 0:
                continue
            prior_u = repaired[("u", plant_id, period_idx - 1)]
            prior_y = path[("y", plant_id, period_idx - 1)]
            r_value = path[("r", plant_id, period_idx)]
            up_limit = ramp + (1 - prior_y) + r_value
            down_limit = ramp + (1 - y_value)
            if u_value - prior_u > up_limit + 1e-12:
                raise CapacityPathError(
                    f"repaired plant {plant_id} violates utilization ramp-up at {year}"
                )
            if prior_u - u_value > down_limit + 1e-12:
                raise CapacityPathError(
                    f"repaired plant {plant_id} violates utilization ramp-down at {year}"
                )

    dispatch_bounds = {}
    raw_demand_gaps = {}
    repaired_demand_gaps = {}
    demand_band_margins = {}
    for period_idx, year in enumerate(v4_model.years):
        target = (
            float(v4_model.demand_path[year])
            * 1000.0
            * float(v4_model.clinker_ratio_path[year])
        )
        raw_total = 0.0
        repaired_total = 0.0
        lower_total = 0.0
        upper_total = 0.0
        for plant_id in v4_model.I:
            capacity = float(v4_model.cap[plant_id])
            y_value = path[("y", plant_id, period_idx)]
            raw_u = path[("u", plant_id, period_idx)]
            reference_u = repaired[("u", plant_id, period_idx)]
            raw_total += capacity * raw_u
            repaired_total += capacity * reference_u
            if period_idx == 0:
                lower = upper = reference_u
            elif y_value == 0:
                lower = upper = 0.0
            else:
                lower = max(u_min, reference_u - band)
                upper = min(1.0, reference_u + band)
            if lower > upper + 1e-15:
                raise CapacityPathError(
                    f"empty utilization band for plant {plant_id} in {year}: "
                    f"[{lower}, {upper}]"
                )
            dispatch_bounds[(plant_id, period_idx)] = (lower, upper)
            lower_total += capacity * lower
            upper_total += capacity * upper

        raw_gap = raw_total - target
        repaired_gap = repaired_total - target
        raw_demand_gaps[int(year)] = raw_gap
        repaired_demand_gaps[int(year)] = repaired_gap
        if target < lower_total - 1e-6 or target > upper_total + 1e-6:
            raise CapacityPathError(
                f"dispatch tolerance bands cannot satisfy demand in {year}: "
                f"target={target}, feasible=[{lower_total}, {upper_total}]"
            )
        raw_gap_tolerance = max(
            REFERENCE_DEMAND_ABSOLUTE_TOLERANCE_KT,
            abs(target) * REFERENCE_DEMAND_RELATIVE_TOLERANCE,
        )
        if abs(raw_gap) > raw_gap_tolerance:
            raise CapacityPathError(
                f"reference dispatch violates demand balance in {year} by "
                f"{raw_gap:.6g} kt, beyond the numerical guard "
                f"{raw_gap_tolerance:.6g} kt"
            )
        demand_band_margins[int(year)] = {
            "target_minus_lower_kt": target - lower_total,
            "upper_minus_target_kt": upper_total - target,
            "raw_gap_tolerance_kt": raw_gap_tolerance,
        }

    report = {
        "strategy": "narrow_bounds_around_constraint_consistent_reference_dispatch",
        "dispatch_band_tolerance": band,
        "reference_repair_tolerance": repair_tolerance,
        "reference_repairs": repairs,
        "reference_repair_count": len(repairs),
        "max_abs_reference_u_repair": max(
            (row["absolute_repair"] for row in repairs), default=0.0
        ),
        "max_abs_raw_demand_gap_kt": max(
            (abs(value) for value in raw_demand_gaps.values()), default=0.0
        ),
        "max_abs_raw_demand_gap_fraction": max(
            (
                abs(raw_demand_gaps[int(year)])
                / max(
                    abs(float(v4_model.demand_path[year]) * 1000.0
                        * float(v4_model.clinker_ratio_path[year])),
                    1e-12,
                )
                for year in v4_model.years
            ),
            default=0.0,
        ),
        "raw_demand_gap_absolute_tolerance_kt": (
            REFERENCE_DEMAND_ABSOLUTE_TOLERANCE_KT
        ),
        "raw_demand_gap_relative_tolerance": (
            REFERENCE_DEMAND_RELATIVE_TOLERANCE
        ),
        "max_abs_repaired_point_demand_gap_kt": max(
            (abs(value) for value in repaired_demand_gaps.values()), default=0.0
        ),
        "raw_demand_gap_kt_by_year": raw_demand_gaps,
        "repaired_point_demand_gap_kt_by_year": repaired_demand_gaps,
        "demand_band_margins_kt_by_year": demand_band_margins,
        "checks": {
            "u_le_y": "PASS",
            "u_ge_u_min_y": "PASS",
            "utilization_ramps": "PASS",
            "turnover_continuity": "PASS",
            "reference_demand_balance": "PASS_WITHIN_DECLARED_NUMERICAL_GUARD",
            "demand_reachable_within_dispatch_bands": "PASS",
        },
    }
    return repaired, dispatch_bounds, report


def finalize_capacity_path_diagnostics(results, metadata, capacities):
    """Attach realized dispatch-deviation evidence after a successful solve."""

    if not metadata.get("dispatch_fixing"):
        return metadata
    source_path = Path(metadata["source_path"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    repairs = {
        (int(row["plant_id"]), int(row["year"])): float(row["repaired_u"])
        for row in metadata["dispatch_fixing"].get("reference_repairs", [])
    }
    years = sorted(int(year) for year in results.get("summary", {}))
    max_raw_u = 0.0
    max_repaired_u = 0.0
    max_plant_production = 0.0
    max_system_production = 0.0
    max_absolute_reallocation = 0.0
    yr_mismatch = 0
    for year in years:
        system_delta = 0.0
        absolute_reallocation = 0.0
        for raw_plant_id, current in results["plants"].items():
            plant_id = int(raw_plant_id)
            source_record = source["plants"].get(
                str(plant_id), source["plants"].get(plant_id)
            )
            current_u = float(current["u"].get(str(year), current["u"].get(year)))
            raw_u = float(
                source_record["u"].get(str(year), source_record["u"].get(year))
            )
            repaired_u = repairs.get((plant_id, year), raw_u)
            max_raw_u = max(max_raw_u, abs(current_u - raw_u))
            max_repaired_u = max(max_repaired_u, abs(current_u - repaired_u))
            production_delta = float(capacities[plant_id]) * (current_u - raw_u)
            max_plant_production = max(
                max_plant_production, abs(production_delta)
            )
            system_delta += production_delta
            absolute_reallocation += abs(production_delta)
            for variable in ("y", "r"):
                current_value = current[variable].get(
                    str(year), current[variable].get(year)
                )
                source_value = source_record[variable].get(
                    str(year), source_record[variable].get(year)
                )
                yr_mismatch += int(int(current_value) != int(source_value))
        max_system_production = max(max_system_production, abs(system_delta))
        max_absolute_reallocation = max(
            max_absolute_reallocation, absolute_reallocation
        )

    band = float(metadata["dispatch_fixing"]["dispatch_band_tolerance"])
    repair = float(metadata["dispatch_fixing"]["max_abs_reference_u_repair"])
    realized = {
        "exact_y_r_mismatch_count": yr_mismatch,
        "max_abs_u_deviation_from_raw_source": max_raw_u,
        "max_abs_u_deviation_from_repaired_reference": max_repaired_u,
        "maximum_allowed_raw_source_u_deviation": band + repair,
        "max_abs_plant_production_deviation_kt": max_plant_production,
        "max_abs_system_production_deviation_kt": max_system_production,
        "max_total_absolute_plant_production_reallocation_kt": max_absolute_reallocation,
        "interpretation": (
            "y/r are exact; u remains within the declared narrow band around "
            "the constraint-consistent reference, with solver-rounding repairs "
            "reported separately."
        ),
    }
    if yr_mismatch:
        raise CapacityPathError(
            f"solved fixed-path result has {yr_mismatch} y/r mismatches"
        )
    if max_repaired_u > band + 1e-8:
        raise CapacityPathError(
            "solved utilization left the declared dispatch band: "
            f"{max_repaired_u} > {band}"
        )
    metadata["dispatch_fixing"]["realized_diagnostics"] = realized
    return metadata


def validate_exported_capacity_dispatch(
    results,
    capacities,
    years,
    *,
    minimum_utilization,
    maximum_utilization_change,
    tolerance=1e-7,
):
    """Fail before export when rounded states contradict continuous dispatch."""

    errors = []
    max_u_upper = 0.0
    max_u_lower = 0.0
    max_ramp = 0.0
    max_demand_gap = 0.0
    max_demand_gap_fraction = 0.0
    plants = results.get("plants") or {}
    for raw_plant_id, record in plants.items():
        plant_id = int(raw_plant_id)
        for period_idx, year in enumerate(years):
            y_value = float(record["y"].get(str(year), record["y"].get(year)))
            r_value = float(record["r"].get(str(year), record["r"].get(year)))
            u_value = float(record["u"].get(str(year), record["u"].get(year)))
            if abs(y_value - round(y_value)) > tolerance:
                errors.append(f"plant {plant_id} y[{year}] is not binary")
            if abs(r_value - round(r_value)) > tolerance:
                errors.append(f"plant {plant_id} r[{year}] is not binary")
            max_u_upper = max(max_u_upper, u_value - y_value)
            if u_value > y_value + tolerance:
                errors.append(
                    f"plant {plant_id} u[{year}]={u_value} exceeds y={y_value}"
                )
            if period_idx > 0:
                lower_gap = minimum_utilization * y_value - u_value
                max_u_lower = max(max_u_lower, lower_gap)
                if lower_gap > tolerance:
                    errors.append(
                        f"plant {plant_id} u[{year}]={u_value} is below u_min*y"
                    )
                prior_year = years[period_idx - 1]
                prior_y = float(
                    record["y"].get(str(prior_year), record["y"].get(prior_year))
                )
                prior_u = float(
                    record["u"].get(str(prior_year), record["u"].get(prior_year))
                )
                up_gap = (
                    u_value
                    - prior_u
                    - maximum_utilization_change
                    - (1 - prior_y)
                    - r_value
                )
                down_gap = (
                    prior_u
                    - u_value
                    - maximum_utilization_change
                    - (1 - y_value)
                )
                max_ramp = max(max_ramp, up_gap, down_gap)
                if up_gap > tolerance or down_gap > tolerance:
                    errors.append(
                        f"plant {plant_id} utilization ramp violation at {year}"
                    )

    for year in years:
        production = sum(
            float(capacities[int(plant_id)])
            * float(record["u"].get(str(year), record["u"].get(year)))
            for plant_id, record in plants.items()
        )
        summary = results["summary"].get(str(year), results["summary"].get(year))
        demand = float(summary["clinker_demand_kt"])
        gap = production - demand
        max_demand_gap = max(max_demand_gap, abs(gap))
        max_demand_gap_fraction = max(
            max_demand_gap_fraction, abs(gap) / max(abs(demand), 1e-12)
        )
        demand_tolerance = max(
            1e-4, abs(demand) * REFERENCE_DEMAND_RELATIVE_TOLERANCE
        )
        if abs(gap) > demand_tolerance:
            errors.append(f"system demand balance gap in {year}: {gap} kt")

    if errors:
        raise CapacityPathError(
            "exported capacity/dispatch consistency failed: "
            + "; ".join(errors[:20])
        )
    return {
        "status": "PASS",
        "tolerance": float(tolerance),
        "max_u_minus_y": max(0.0, max_u_upper),
        "max_u_min_y_minus_u": max(0.0, max_u_lower),
        "max_utilization_ramp_violation": max(0.0, max_ramp),
        "max_abs_reconstructed_demand_gap_kt": max_demand_gap,
        "max_abs_reconstructed_demand_gap_fraction": max_demand_gap_fraction,
        "demand_gap_relative_tolerance": REFERENCE_DEMAND_RELATIVE_TOLERANCE,
    }


def fix_capacity_turnover_from_results(
    v4_model,
    source_path,
    include_utilization=False,
    dispatch_band_tolerance=DISPATCH_BAND_TOLERANCE,
    reference_repair_tolerance=DISPATCH_BAND_TOLERANCE,
    expected_provenance_sha256=None,
):
    """Fix a built V4 model's capacity-turnover path from a result JSON file."""

    if v4_model.model is None:
        raise CapacityPathError("the V4 model must be built before fixing a path")

    source_path = Path(source_path).expanduser().resolve()
    if not source_path.is_file():
        raise CapacityPathError(f"capacity-path reference does not exist: {source_path}")

    raw = source_path.read_bytes()
    try:
        results = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CapacityPathError(
            f"capacity-path reference is not valid JSON: {source_path}"
        ) from exc

    validate_reference_incumbent(results)

    if expected_provenance_sha256 is not None:
        observed_provenance = (
            (results.get("run_provenance") or {}).get("sha256")
        )
        if observed_provenance != expected_provenance_sha256:
            raise CapacityPathError(
                "reference result provenance does not match the active run "
                f"({observed_provenance!r} != {expected_provenance_sha256!r})"
            )

    reference_demand = results.get("demand_scenario")
    if reference_demand is None:
        raise CapacityPathError("reference result has no demand_scenario metadata")
    if str(reference_demand) != str(v4_model.demand_scenario):
        raise CapacityPathError(
            "reference demand scenario does not match the active model "
            f"({reference_demand!r} != {v4_model.demand_scenario!r})"
        )

    reference_budget = results.get("carbon_budget_case")
    active_budget = getattr(v4_model.config, "CARBON_BUDGET_CASE", None)
    if reference_budget is None:
        raise CapacityPathError("reference result has no carbon_budget_case metadata")
    if active_budget and str(reference_budget) != str(active_budget):
        raise CapacityPathError(
            "reference carbon budget does not match the active model "
            f"({reference_budget!r} != {active_budget!r})"
        )

    path = extract_capacity_turnover_path(
        results,
        v4_model.I,
        v4_model.years,
        include_utilization=include_utilization,
    )
    dispatch_report = None
    dispatch_bounds = None
    if include_utilization:
        for plant_id in v4_model.I:
            reference_u = path[("u", plant_id, 0)]
            anchored_u = float(v4_model.baseyear_utilization[plant_id])
            if abs(reference_u - anchored_u) > 1e-6:
                raise CapacityPathError(
                    "reference 2025 utilization differs from the active observed "
                    f"anchor for plant {plant_id}: {reference_u} != {anchored_u}"
                )
        _, dispatch_bounds, dispatch_report = _reference_dispatch_preflight(
            v4_model,
            path,
            dispatch_band_tolerance=dispatch_band_tolerance,
            reference_repair_tolerance=reference_repair_tolerance,
        )
    for (variable, plant_id, period_idx), fixed_value in path.items():
        if variable == "u" and include_utilization:
            if period_idx == 0:
                continue
            lower, upper = dispatch_bounds[(plant_id, period_idx)]
            variable_data = v4_model.model.u[plant_id, period_idx]
            if abs(upper - lower) <= 1e-15:
                variable_data.fix(lower)
            else:
                variable_data.setlb(lower)
                variable_data.setub(upper)
            continue
        getattr(v4_model.model, variable)[plant_id, period_idx].fix(fixed_value)

    fixed_variables = ["y", "r"]
    bounded_variables = ["u"] if include_utilization else []
    adaptive_variables = [
        "af_supply",
        "k_af",
        "z",
        "k_ccs",
        "captured",
        "plant_to_storage_flows",
    ]
    if not include_utilization:
        adaptive_variables.insert(0, "u")

    return {
        "enabled": True,
        "design": (
            "reference_capacity_turnover_and_dispatch_fixed_before_low_carbon_reoptimization"
            if include_utilization
            else "reference_capacity_turnover_fixed_before_low_carbon_reoptimization"
        ),
        "source_path": str(source_path),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_scenario": results.get("scenario"),
        "source_demand_scenario": reference_demand,
        "source_carbon_budget_case": reference_budget,
        "fixed_variables": fixed_variables,
        "bounded_variables": bounded_variables,
        "adaptive_variables": adaptive_variables,
        "fixed_plant_period_values": 2 * len(v4_model.I) * len(v4_model.years),
        "bounded_plant_period_values": (
            len(v4_model.I) * (len(v4_model.years) - 1)
            if include_utilization else 0
        ),
        "fixed_plants": len(v4_model.I),
        "fixed_periods": len(v4_model.years),
        "dispatch_fixing": dispatch_report,
        "interpretation": (
            "Plant operation and same-site renewal are inherited from the "
            "reference case; "
            + (
                f"utilization is constrained to an audited ±{dispatch_band_tolerance:g} "
                "band around the constraint-consistent reference dispatch, while all "
                "low-carbon decisions are re-optimized under the active scenario."
                if include_utilization
                else "dispatch and all low-carbon decisions are re-optimized "
                "under the active scenario."
            )
        ),
    }
