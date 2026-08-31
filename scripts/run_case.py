"""Map manuscript labels to the unchanged solver; no data are bundled."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

from check_inputs import ROOT, missing_inputs

CASES = {
    "S1": ("S1_baseline", "d_medium", "full"),
    "S2": ("S3_all_spatial_equalized", "d_medium", "full"),
    "S3": ("S5_offshore_parity", "d_medium", "full"),
    "S4": ("S1_baseline", "d_high", "demand/d_high"),
    "S5": ("S1_baseline", "d_low", "demand/d_low"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", choices=CASES, required=True)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--reference", type=Path)
    ap.add_argument("--fix", choices=["turnover", "turnover_and_dispatch"])
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if bool(a.reference) != bool(a.fix):
        ap.error("--reference and --fix must be supplied together")
    if a.reference and not a.output:
        ap.error("Counterfactuals require an explicit separate --output directory")
    if a.fix and a.case in {"S4", "S5"}:
        ap.error("The published fixed-path experiments use S1, S2 or S3, not demand sensitivities")
    if a.threads < 1:
        ap.error("--threads must be positive")
    scenario, demand, suffix = CASES[a.case]
    out = (a.output or ROOT / "results/v4/final_verified_inputs_20260829" / suffix).resolve()
    gap = "0.002" if a.case in {"S4", "S5"} else "0.001"
    time_limit = "300" if a.fix else ("1200" if a.case in {"S4", "S5"} else "3600")
    command = [sys.executable, "-m", "src_v4.main", "--scenario", scenario,
               "--demand-scenario", demand, "--budget-case", "B40",
               "--solver-profile", "final", "--mip-gap", gap,
               "--time-limit", time_limit, "--threads", str(a.threads),
               "--output", str(out)]
    if a.reference:
        command += ["--fixed-capacity-path", str(a.reference.resolve()),
                    "--fixed-capacity-mode", a.fix]
    print(shlex.join(command), flush=True)
    if a.dry_run:
        return
    missing = missing_inputs()
    if missing:
        raise SystemExit("Inputs are not included. Run scripts/check_inputs.py and consult docs/INPUTS.md.")
    # Core cases deliberately share 'full'; protect the exact target result.
    if (out / f"{scenario}_results.json").exists() or (out / scenario).exists():
        raise SystemExit("Refusing to overwrite existing result/table files. Choose a clean output location.")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "models/v4")
    subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
