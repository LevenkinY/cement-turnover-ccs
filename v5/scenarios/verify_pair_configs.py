#!/usr/bin/env python
"""Verify that paired v5 runs are comparable before a difference is taken.

Why this exists
---------------
R = C_S - C_J (the co-optimisation value) is the difference between TWO runs.
The difference is only interpretable if the pair shares everything except the
decision structure: same demand proxy, same transport parameters, same cost
accounting, same carbon budget. That is easy to get wrong -- this project has
already shipped one result whose "different" scenario had silently failed to
apply its override, and the only symptom was a cost line that happened to match
the baseline.

Every v5 result since 2026-09-12 therefore carries an `effective_config` block
recording what the run ACTUALLY used. This script diffs those blocks, so a pair
is checked against the run's own record rather than against the invocation you
think you typed.

Usage
-----
    python v5/scenarios/verify_pair_configs.py RUN_A.json RUN_B.json [--allow K=V ...]

Exit codes: 0 = pair is comparable, 1 = a must-match key differs, 2 = bad input.

Keys that are EXPECTED to differ between a J and an S pair (the decision
structure itself) are listed in STRUCTURAL_KEYS and are reported informationally.
Anything else that differs is an error unless explicitly listed with --allow,
which prints the override so the exception is visible in the log.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Config keys that ARE the treatment: allow them to differ, report them.
STRUCTURAL_KEYS = {
    "planning_mode",
    "carbon_target_active",
    # the S stage-2 run inherits its fleet from S stage 1, so its fixed-path block
    # differs by construction
    "capacity_path_fixed",
}

# Cost/emission/accounting keys that must match for a difference to be meaningful.
MUST_MATCH = (
    # demand proxy
    "demand_scenario",
    "regional_demand_enabled",
    "demand_market_node_count",
    "demand_market_node_file",
    "demand_market_arc_file",
    "demand_arc_count",
    "demand_transport_mode",
    "demand_transport_segments",
    # carbon accounting
    "carbon_budget_case",
    "emission_target_mode",
    "cumulative_budget_metric",
    # cost accounting
    "discount_rate",
    "cost_boundary",
    "include_carbon_cost_in_objective",
    "include_full_fuel_cost_in_objective",
    # technology / operations
    "min_operating_utilization",
    "days_per_year",
    "plant_fixed_operating_cost_cny_per_t_capacity_yr",
    "early_retirement_cost_cny_per_t_annual_capacity",
    "capture_efficiency",
    "ccs_cost_decline_case",
    "ccs_min_operating_years",
    "same_site_renewal_window",
    "same_site_renewal_max_count",
    "max_annual_capacity_decline",
    "max_capacity_decline_per_period",
    # AF caliber and cost (2026-09-13)
    "af_energy_caliber",
    "af_technical_tsr_ceiling",
    "af_access_allocation_headroom",
    "af_expansion_fraction_of_heat",
    "beta_af",
    "af_investment_cny_per_tce",
    "af_om_cny_per_tce",
    "af_biogenic_co2_per_tce",
    "coal_ef_tco2_per_tce",
    # EOR
    "eor_revenue_cny_per_tco2",
    "eor_storage_cost_cny_per_tco2",
    "eor_storage_retention",
    # end-of-horizon and storage treatments (2026-09-14; R6/R8 arms)
    "terminal_value_mode",
    "storage_rate_scale",
    "storage_cumulative_scale",
)


def _load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"verify_pair_configs: file not found: {path}")
    with path.open() as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"verify_pair_configs: not a result JSON object: {path}")
    return payload


def _canonical(value):
    """Normalise for comparison: ints/floats, tuples-as-lists, inf-as-None."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 12)
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    return value


def _effective(payload: dict) -> dict:
    """Prefer effective_config; fall back to the older model_assumptions dump."""
    for key in ("effective_config", "model_assumptions"):
        block = payload.get(key)
        if isinstance(block, dict) and block:
            return block
    return {}


def _planning_mode(payload: dict) -> str:
    """Planning mode of a run: from the counterfactual block, else the config dump."""
    block = payload.get("planning_counterfactual")
    if isinstance(block, dict) and block.get("planning_mode"):
        return str(block["planning_mode"])
    cfg = _effective(payload)
    return str(cfg.get("planning_mode", "joint"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_a", type=Path, help="result JSON of run A")
    parser.add_argument("run_b", type=Path, help="result JSON of run B")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="KEY=VALUE_A|VALUE_B",
        help=(
            "Explicitly permit KEY to differ, giving the two expected values. "
            "Repeatable. Use sparingly: every entry is an admission that the pair "
            "is not fully controlled."
        ),
    )
    args = parser.parse_args(argv)

    a_payload, b_payload = _load(args.run_a), _load(args.run_b)
    a_cfg, b_cfg = _effective(a_payload), _effective(b_payload)
    from comparison_contract import invalid_carbon_run
    if invalid_carbon_run(a_payload) or invalid_carbon_run(b_payload):
        print("FAIL: legacy phi>0 run credits biogenic storage; not comparable.")
        return 1

    a_mode = _planning_mode(a_payload)
    b_mode = _planning_mode(b_payload)
    # In a J/S pair, S stage 1 DELIBERATELY runs with the carbon target switched
    # off -- the absence of the constraint IS the treatment. So emission_target_mode
    # is structural for a stage-1 run and must-match for every other combination
    # (in particular for J vs S stage 2, where both carry the same budget).
    structural = set(STRUCTURAL_KEYS)
    if "stepwise_capacity" in {a_mode, b_mode}:
        structural.add("emission_target_mode")

    print(f"A: {args.run_a}")
    print(f"B: {args.run_b}")
    print(f"  scenario  A={a_payload.get('scenario')}  B={b_payload.get('scenario')}")
    print(f"  planning  A={a_mode}  B={b_mode}")
    for label, mode in (("A", a_mode), ("B", b_mode)):
        if mode == "stepwise_capacity":
            print(
                f"    note: {label} is S stage 1 -> emission_target_mode is treated "
                "as part of the treatment (carbon target OFF by construction)"
            )

    if not a_cfg or not b_cfg:
        print(
            "\nFAIL: at least one run has no effective_config/model_assumptions block, "
            "so comparability cannot be checked. Pre-2026-09-12 result files do not "
            "carry it; rerun those scenarios.",
            file=sys.stderr,
        )
        return 1

    allowed = {}
    for entry in args.allow:
        if "=" not in entry:
            print(f"FAIL: --allow expects KEY=VALUE_A|VALUE_B, got {entry!r}", file=sys.stderr)
            return 2
        key, _, values = entry.partition("=")
        if "|" not in values:
            print("FAIL: --allow requires the expected A|B values", file=sys.stderr)
            return 2
        def parsed(text):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        allowed[key.strip()] = tuple(parsed(v) for v in values.split("|", 1))

    failures = []
    informational = []
    checked = 0

    keys = set(a_cfg) | set(b_cfg)
    # File labels and absolute paths are provenance, not model coefficients.
    keys -= {"demand_market_node_file", "demand_market_arc_file", "market_input_provenance"}
    for key in ("nodes_sha256", "arcs_sha256"):
        av = (a_cfg.get("market_input_provenance") or {}).get(key)
        bv = (b_cfg.get("market_input_provenance") or {}).get(key)
        if av and bv and av != bv:
            failures.append((key, av, bv, "differs"))
    if not any(float(c.get("af_biogenic_co2_per_tce", 0) or 0) for c in (a_cfg, b_cfg)):
        keys -= {"carbon_flow_accounting_version", "capture_stream_assumption"}
    for key in ("model_input_sha256", "model_code_sha256"):
        if not a_cfg.get(key) or not b_cfg.get(key):
            keys.discard(key)
            print(f"WARNING: {key} unavailable; configuration match is not proof of identical models.")
    keys = sorted(keys)
    for key in keys:
        av, bv = _canonical(a_cfg.get(key)), _canonical(b_cfg.get(key))
        if av == bv:
            checked += 1
            continue
        if key in allowed and (av, bv) != tuple(_canonical(v) for v in allowed[key]):
            failures.append((key, av, bv, "does not match explicitly allowed values"))
            continue
        if key in structural or key in allowed:
            informational.append((key, a_cfg.get(key), b_cfg.get(key)))
            continue
        failures.append((key, a_cfg.get(key), b_cfg.get(key), "differs"))

    # Also flag any MUST_MATCH key that is absent from BOTH dumps: an absent key
    # is not agreement, it is an unverified assumption.
    missing = [
        k
        for k in MUST_MATCH
        if k not in a_cfg and k not in b_cfg
        and k not in structural
        and k not in {"demand_market_node_file", "demand_market_arc_file"}
    ]

    print(f"\n  keys compared: {len(keys)}  identical: {checked}")
    if informational:
        print("\n  EXPECTED DIFFERENCES (decision structure):")
        for key, av, bv in informational:
            print(f"    {key}: A={av!r}  B={bv!r}")
    if failures:
        print("\n  UNEXPECTED DIFFERENCES (breaks comparability):")
        for key, av, bv, _ in failures:
            print(f"    {key}: A={av!r}  B={bv!r}")
    if missing:
        print("\n  NOT RECORDED IN EITHER RUN (comparability unverified):")
        for key in missing:
            print(f"    {key}")

    if failures or missing:
        print(
            "\nFAIL: the pair is not controlled. Fix the invocation, or add "
            "--allow KEY=valueA|valueB and say so in the text.",
            file=sys.stderr,
        )
        return 1

    print("\nPASS: effective configurations agree on every must-match key.")
    print("       Cost comparison still requires the correct comparison type and valid solver bounds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
