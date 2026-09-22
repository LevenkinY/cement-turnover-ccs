"""Map the manuscript's public case labels to the unchanged v5 solver.

No data are bundled: every case below needs the study inputs listed in
`docs/INPUTS.md` and a solver licence. The public labels S1-S6 follow the run
register of the manuscript (Supplementary Table S6); the internal scenario names
below are the frozen solver aliases and are not public labels.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

from check_inputs import ROOT, missing_inputs

# public label -> (solver scenario, demand pathway, committed path from)
CASES = {
    "S1": ("S1_baseline", "d_medium", None),
    "S2": ("S1_baseline", "d_high", None),
    "S3": ("S1_baseline", "d_low", None),
    "S4": ("S3_all_spatial_equalized", "d_medium", None),
    "S5": ("S1_baseline", "d_medium", "S4"),
    "S6": ("S1_baseline", "d_medium", "S1"),
}


def result_json(directory: Path) -> Path:
    matches = sorted(directory.glob("*_results.json"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one result JSON in {directory}, found {len(matches)}")
    return matches[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", choices=CASES, required=True)
    ap.add_argument("--output", type=Path,
                    help="result directory; defaults to results/v5/<case>")
    ap.add_argument("--reference", type=Path,
                    help="result directory holding the committed run: S4 for the S5 "
                         "commitment case, S1 for the S6 procedure check")
    ap.add_argument("--solver-profile", default="final", choices=["final", "explore", "screen"])
    ap.add_argument("--mip-gap", default="0.005",
                    help="termination gap; the manuscript runs use 0.005")
    ap.add_argument("--time-limit", type=int, default=7200)
    ap.add_argument("--threads", type=int, default=8,
                    help="0 lets the solver choose every core")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.threads < 0:
        ap.error("--threads must be non-negative")

    scenario, demand, committed_from = CASES[a.case]
    out = (a.output or ROOT / "results/v5" / a.case).resolve()
    if committed_from and not a.reference:
        ap.error(f"--case {a.case} fixes a committed capacity path: supply --reference "
                 f"(the result directory of {committed_from})")
    if a.reference and not committed_from:
        ap.error(f"--case {a.case} is solved jointly and takes no --reference")
    command = [sys.executable, "-m", "src_v5.main",
               "--scenario", scenario,
               "--demand-scenario", demand,
               "--budget-case", "B40",
               "--solver-profile", a.solver_profile,
               "--mip-gap", a.mip_gap,
               "--time-limit", str(a.time_limit),
               "--threads", str(a.threads),
               "--output", str(out)]
    if a.reference:
        reference = a.reference.resolve()
        try:
            reference = result_json(reference)
        except SystemExit:
            if not a.dry_run:
                raise
            reference = reference / "*_results.json"
        command += ["--fixed-capacity-path", str(reference)]
    print(shlex.join(command), flush=True)
    if a.dry_run:
        return
    missing = missing_inputs()
    if missing:
        raise SystemExit("Inputs are not included. Run scripts/check_inputs.py and consult docs/INPUTS.md.")
    # The joint cases share one output name per scenario; protect the exact target result.
    if (out / f"{scenario}_results.json").exists() or (out / scenario).exists():
        raise SystemExit("Refusing to overwrite existing result/table files. Choose a clean output location.")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "v5/model")
    subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
