#!/usr/bin/env python
"""Report the planning loss R = C_fixed - C_joint with solver-error bounds.

Why this exists
---------------
R is the paper's core number, and it is the difference of two OPTIMISED costs.
Each is only known to within its own MIP gap, so a point difference is not a
result. For a minimisation problem with objective bounds [L, U] on each run:

    R = C_fixed - C_joint  in  [ L_fixed - U_joint ,  U_fixed - L_joint ]

The interval can easily contain zero even when both runs report a "small" gap.
If it does, the honest statement is that the loss is not resolved at the current
precision -- not that it is zero, and not that a parameter should be retuned until
it becomes positive. The output says which of those applies.

A theoretical check is also enforced: the fixed-path run is a RESTRICTION of the
joint problem's feasible set, so at optimality R >= 0 MUST hold. A point estimate
below zero therefore indicates an unconverged incumbent, and is reported as such
rather than as evidence that sequential planning is cheaper.

Usage
-----
    python v5/scenarios/report_planning_loss.py JOINT.json FIXED.json [--label NAME]

The two files must be a legitimate pair (same demand, carbon accounting, cost
accounting, technology settings). The comparability gate from
verify_pair_configs.py is run first and a failing pair is REFUSED, because a
difference taken across incomparable runs is meaningless.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comparison_contract import classify
import verify_pair_configs as vpc  # noqa: E402


def _diag(payload: dict) -> dict:
    solver = payload.get("solver") or {}
    objective = solver.get("objective_value")
    bound = solver.get("objective_bound")
    gap = solver.get("mip_gap")
    status = solver.get("status")
    if objective is None or bound is None:
        raise SystemExit(
            "report_planning_loss: a run has no objective/bound -- it did not "
            "produce an incumbent, so R cannot be bounded."
        )
    return {
        "objective": float(objective),
        "bound": float(bound),
        "gap": float(gap) if gap is not None else None,
        "status": status,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("joint", type=Path, help="joint (J) result JSON")
    parser.add_argument("fixed", type=Path, help="fixed-path result JSON")
    parser.add_argument("--label", default="R", help="label for the reported loss")
    args = parser.parse_args(argv)

    a = json.loads(args.joint.read_text())
    b = json.loads(args.fixed.read_text())
    kind = classify(a, b)
    if kind != "fixed_path_loss":
        print(f"REFUSED: comparison type is {kind}, not a same-setting fixed-path loss.")
        return 1
    # Comparability gate first: refuse to difference incomparable runs.
    gate = vpc.main([str(args.joint), str(args.fixed)])
    if gate != 0:
        print(
            "\nREFUSED: the two runs are not a controlled pair, so R is not "
            "interpretable. Fix the invocation and rerun.",
            file=sys.stderr,
        )
        return 1

    j_payload = json.loads(args.joint.read_text())
    f_payload = json.loads(args.fixed.read_text())
    j, f = _diag(j_payload), _diag(f_payload)

    l_j, u_j = j["bound"], j["objective"]
    l_f, u_f = f["bound"], f["objective"]
    # Guard against a solver reporting a bound above the incumbent (can happen with
    # tolerances); the bracket must be ordered for the interval arithmetic to mean
    # anything.
    if l_j > u_j + max(1e-6, abs(u_j)*1e-8) or l_f > u_f + max(1e-6, abs(u_f)*1e-8):
        raise SystemExit("Invalid solver interval: bound exceeds incumbent")

    r_point = f["objective"] - j["objective"]
    r_low = l_f - u_j
    r_high = u_f - l_j

    print()
    print(f"=== {args.label} = C_fixed - C_joint ===")
    print(f"  joint : objective {j['objective']/1e6:,.2f} bn | bound {l_j/1e6:,.2f} bn | "
          f"gap {100*(j['gap'] or 0):.3f}% | {j['status']}")
    print(f"  fixed : objective {f['objective']/1e6:,.2f} bn | bound {l_f/1e6:,.2f} bn | "
          f"gap {100*(f['gap'] or 0):.3f}% | {f['status']}")
    print()
    print(f"  point estimate        {r_point/1e6:+,.2f} bn"
          f"   ({100*r_point/abs(j['objective']):+.3f}% of C_joint)")
    print(f"  bound interval        [{r_low/1e6:+,.2f}, {r_high/1e6:+,.2f}] bn"
          f"   (width {abs(r_high-r_low)/1e6:,.2f} bn)")

    # Theory: the fixed path restricts the feasible set, so R >= 0 at optimality.
    # A negative POINT estimate therefore cannot mean "sequential is cheaper". It has
    # two innocent readings, so judge it against solver error rather than treating it
    # as a verdict:
    #   (a) the joint objective is an INCUMBENT, so a tighter re-optimisation on the
    #       fixed path may land below it;
    #   (b) each reported objective carries its own gap.
    # This matters most for the SELF-CHECK pair (central path fixed back into the
    # central problem), where the original incumbent can improve after continuous re-optimization.
    if r_point < 0:
        print(
            "\n  NOTE: the point estimate is NEGATIVE. Since the fixed-path run is a "
            "restriction of the joint problem, R >= 0 must hold at optimality, so a "
            "negative point estimate is NOT evidence that sequential planning is "
            "cheaper. It means the comparison is limited by solver error: either the "
            "joint run's incumbent is loose, or both gaps are wide. Judge with the "
            "interval below, not with the point estimate."
        )

    print()
    if r_low > 0:
        print(f"  RESOLVED: the whole interval is positive, so {args.label} > 0 "
              f"is established at this precision.")
        print(f"  Reportable lower bound on the loss: {r_low/1e6:,.2f} bn.")
        verdict = "resolved"
    elif r_high < 0:
        print(f"  INCONSISTENT: the whole interval is negative, which contradicts "
              f"R >= 0. Model comparability, numerical validity, or recorded bounds are incorrect; do not "
              f"report this interval.")
        verdict = "inconsistent"
    else:
        print(f"  NOT RESOLVED: the interval contains zero, so this pair does not "
              f"establish a positive {args.label}.")
        print("  Options, in order of preference:")
        print("    1. tighten the gaps on THESE two runs only (raise L_fixed or lower U_joint "
              "to improve the loss lower bound);")
        print("    2. report honestly that the loss is not confirmed at the current "
              "precision;")
        print("    3. do NOT retune parameters to make the loss appear.")
        verdict = "unresolved"

    print()
    print("  Reminder: this is a planning loss under the model's declared cost and "
          "emission boundary. It is not a social-cost saving, and a fixed path drawn "
          "from one near-optimal solution is one commitment among several.")
    print(f"  VERDICT={verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
