#!/usr/bin/env bash
# Single-tiered rerun of the full submission evidence batch after the
# 2026-08-28 fleet-coordinate correction (57 lines relocated).
#
# Public manuscript labels map to frozen model aliases:
#   S1 central                -> S1_baseline / d_medium
#   S2 AF-spatial neutralized -> S3_all_spatial_equalized / d_medium
#   S3 offshore cost parity   -> S5_offshore_parity / d_medium
#   S4 slow contraction       -> S1_baseline / d_high
#   S5 deep contraction       -> S1_baseline / d_low
#
# Precision is tiered by inferential role (balanced protocol, 2026-08-22):
#   core S1/S2 (and S3)      0.10% target, 0.11% acceptance, 3600 s cap
#   fixed-path counterfactuals 0.10% target, 0.12% acceptance, 300 s cap
#   demand / lifetime / utilization 0.20% target, 0.30% acceptance, 1200 s
#   near-optimal identity phase  0.25% gap, 500 s; economic tie-break 0.20%/240 s
#
# This script never copies or reuses pre-correction solutions. It does verify
# and reuse any completed package inside the fresh output roots that passes
# the role-specific gates, so it is safe to re-run after interruption.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH="$ROOT_DIR/models/v4${PYTHONPATH:+:$PYTHONPATH}"
PY_BIN="${CF_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
OUT_ROOT="${CF_OUTPUT_ROOT:-results/v4/final_verified_inputs_20260829}"
UTIL_ROOT="${CF_UTIL_OUTPUT_ROOT:-results/v4/min_utilization_verified_inputs_20260829}"
REVIEW_CSV="data/model_input/plants/fusion_2025/fleet_scope_review_20260822.csv"
DRY_RUN="${CF_DRY_RUN:-0}"
THREADS="${CF_THREADS:-8}"

CORE_GAP=0.001        # target for core identification and fixed paths
CORE_MAX_GAP=0.0011   # acceptance for core joint solves
FIXED_MAX_GAP=0.0012  # acceptance for fixed-path restricted solves
ROBUST_GAP=0.002      # target for descriptive robustness cases
ROBUST_MAX_GAP=0.003  # acceptance for descriptive robustness cases
IDENTITY_GAP=0.0025   # near-optimal identity-phase path gap

case "$DRY_RUN" in 0|1) ;; *) echo "CF_DRY_RUN must be 0 or 1" >&2; exit 2 ;; esac
if [[ "$OUT_ROOT" == "$UTIL_ROOT" ]]; then
    echo "CF_OUTPUT_ROOT and CF_UTIL_OUTPUT_ROOT must differ." >&2; exit 2
fi

print_command() {
    printf 'DRY RUN:'
    printf ' %q' "$@"
    printf '\n'
}

run_cmd() {
    if [[ "$DRY_RUN" == "1" ]]; then print_command "$@"; else "$@"; fi
}

# Solved-result gate: finite incumbent, finite solver bound, plausible metadata.
validate_result() {
    local path="$1" scenario="$2" demand="$3" lifetime="$4" utilization="$5"
    local max_gap="$6" mode="$7"
    "$PY_BIN" - "$path" "$scenario" "$demand" "$lifetime" "$utilization" "$max_gap" "$mode" <<'PY'
import json, math, sys
from pathlib import Path

path = Path(sys.argv[1])
scenario, demand = sys.argv[2], sys.argv[3]
lifetime, utilization = sys.argv[4], sys.argv[5]
max_gap, mode = float(sys.argv[6]), sys.argv[7]
if not path.is_file():
    raise SystemExit(f"missing result: {path}")
with path.open(encoding="utf-8") as handle:
    result = json.load(handle)
solver = result.get("solver") or {}
solutions = int(float(solver.get("solution_count", 0) or 0))
objective = float(solver.get("objective_value", math.inf))
bound = float(solver.get("objective_bound", math.nan))
gap = float(solver.get("mip_gap", math.inf))
errors = []
if result.get("scenario") != scenario: errors.append(f"scenario={result.get('scenario')}")
if result.get("demand_scenario") != demand: errors.append(f"demand={result.get('demand_scenario')}")
if result.get("carbon_budget_case") != "B40": errors.append(f"budget={result.get('carbon_budget_case')}")
if len(result.get("plants") or {}) != 1572: errors.append(f"plants={len(result.get('plants') or {})}")
if solutions < 1 or not math.isfinite(objective) or not math.isfinite(bound):
    errors.append(f"incumbent/bound invalid: solutions={solutions}, objective={objective}, bound={bound}")
if not math.isfinite(gap) or gap > max_gap + 1e-12:
    errors.append(f"gap={gap} exceeds accepted {max_gap}")
assumptions = result.get("model_assumptions") or {}
if int(assumptions.get("plant_lifetime_years", -1)) != int(lifetime):
    errors.append(f"lifetime={assumptions.get('plant_lifetime_years')}")
actual_util = float(assumptions.get("minimum_operating_utilization", math.nan))
if not math.isfinite(actual_util) or abs(actual_util - float(utilization)) > 1e-9:
    errors.append(f"minimum_utilization={actual_util}")
if mode == "fixed" and not bool((result.get("capacity_path_counterfactual") or {}).get("enabled")):
    errors.append("fixed-path metadata is not enabled")
if mode == "near":
    near = result.get("near_optimal_identity") or {}
    if not bool(near.get("enabled")): errors.append("near-optimal metadata is not enabled")
    for phase in ("identity_phase_solver", "economic_tiebreak_solver"):
        if float((near.get(phase) or {}).get("solution_count", 0) or 0) < 1:
            errors.append(f"{phase} has no incumbent")
if errors:
    raise SystemExit(f"invalid reusable result {path}: " + "; ".join(errors))
print(f"RESULT PASS {path}: status={solver.get('status')}, gap={gap:.6g}, solutions={solutions}")
PY
}

# Reuse an existing package when it passes the gates; otherwise solve fresh.
run_or_reuse() {
    local scenario="$1" demand="$2" lifetime="$3" utilization="$4" mode="$5"
    local target_gap="$6" max_gap="$7" time_limit="$8" output_dir="$9"
    shift 9
    local result_path="$output_dir/${scenario}_results.json"

    if [[ -f "$result_path" ]]; then
        if validate_result "$result_path" "$scenario" "$demand" "$lifetime" "$utilization" "$max_gap" "$mode"; then
            echo "REUSE: $result_path"
            return 0
        fi
        if [[ "$DRY_RUN" == "1" ]]; then
            echo "DRY RUN: invalid result would be quarantined and re-solved: $result_path"
        else
            local quarantine_dir="$output_dir/_invalid_reuse_quarantine"
            local timestamp
            timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
            mkdir -p "$quarantine_dir"
            mv "$result_path" "$quarantine_dir/$(basename "$result_path").${timestamp}.invalid"
            echo "QUARANTINE: invalid reusable result moved aside; solving fresh."
        fi
    fi

    local -a command=("$PY_BIN" -m src_v4.main
        --scenario "$scenario" --demand-scenario "$demand" --budget-case B40
        --solver-profile final --mip-gap "$target_gap" --threads "$THREADS"
        --time-limit "$time_limit" --output "$output_dir")
    if [[ "$lifetime" != "40" ]]; then command+=(--plant-lifetime "$lifetime"); fi
    if [[ "$utilization" != "0.40" ]]; then command+=(--min-operating-utilization "$utilization"); fi
    command+=("$@")

    if [[ "$DRY_RUN" == "1" ]]; then
        print_command "${command[@]}"
    else
        "${command[@]}"
        validate_result "$result_path" "$scenario" "$demand" "$lifetime" "$utilization" "$max_gap" "$mode"
    fi
}

# ---- Preflight -------------------------------------------------------------
"$PY_BIN" scripts/v4/validate_final_inputs.py
"$PY_BIN" -m unittest models.v4.tests.test_final_protocol

# Reuse provenance gate.  Once a result root has an input snapshot, every
# mutable input and key code/workflow hash must still match before any package
# can be reused.  The snapshot is not silently refreshed after code drift.
if [[ -f "$OUT_ROOT/_input_snapshot/final_input_manifest.csv" ]]; then
    "$PY_BIN" - "$OUT_ROOT/_input_snapshot/final_input_manifest.csv" <<'PY'
import csv, hashlib, sys
from pathlib import Path

root = Path.cwd()
manifest = Path(sys.argv[1])
bad = []
with manifest.open(encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        path = root / row["path"]
        if not path.is_file():
            bad.append(f"missing:{row['path']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"] or path.stat().st_size != int(row["size_bytes"]):
            bad.append(f"changed:{row['path']}")
if bad:
    raise SystemExit(
        "Reuse provenance gate failed; start a new result root after code/input drift:\n- "
        + "\n- ".join(bad[:30])
    )
print(f"Reuse provenance gate PASS: {len(list(csv.DictReader(manifest.open(encoding='utf-8'))))} hashes.")
PY
fi

# Fleet-scope gate (as in the 2026-08-22 batch): refuse to start unless every
# review decision is explicit and reflected in the active fleet.
CF_DRY_RUN="$DRY_RUN" "$PY_BIN" - "$REVIEW_CSV" <<'PY'
import os
import sys
from pathlib import Path

import pandas as pd

review_path = Path(sys.argv[1])
review = pd.read_csv(review_path)
plants = pd.read_excel("data/model_input/plants/plant_data.xlsx")
active = set(plants["id"].astype(int))
dry_run = os.environ.get("CF_DRY_RUN") == "1"
allowed = {"exclude_inactive", "exclude_non_clinker", "keep_verified"}
pending, errors = [], []
for row in review.itertuples(index=False):
    plant_id = int(row.plant_id)
    decision = str(row.author_decision).strip()
    if decision == "pending" or not decision:
        pending.append(plant_id)
        continue
    if decision not in allowed:
        errors.append(f"ID {plant_id}: unsupported author_decision={decision!r}")
    elif decision.startswith("exclude_") and plant_id in active:
        errors.append(f"ID {plant_id}: decision is {decision}, but the record remains active")
    elif decision == "keep_verified" and plant_id not in active:
        errors.append(f"ID {plant_id}: decision is keep_verified, but the record is absent")
if errors:
    raise SystemExit("Fleet-scope preflight failed:\n- " + "\n- ".join(errors))
if pending:
    message = f"Fleet-scope decisions remain pending for IDs {pending}."
    if dry_run:
        print("DRY-RUN WARNING:", message)
    else:
        raise SystemExit(message + " Refusing to start optimization.")
print("Fleet-scope preflight PASS.")
PY

# Input snapshot for provenance (2026-08-28 coordinate ledger included).
# Create once; never overwrite it during resume.
if [[ ! -f "$OUT_ROOT/_input_snapshot/final_input_manifest.csv" ]]; then
run_cmd mkdir -p "$OUT_ROOT/_input_snapshot"
run_cmd cp \
    results/v4/final_protocol_validation/final_input_checks.csv \
    results/v4/final_protocol_validation/final_input_manifest.csv \
    results/v4/final_protocol_validation/final_input_validation_summary.json \
    results/v4/final_protocol_validation/route_boundary_exposure_summary_20260822.csv \
    results/v4/final_protocol_validation/route_boundary_exposure_focus_20260822.csv \
    data/model_input/plants/fusion_2025/verified_coordinate_corrections_20260822.csv \
    data/model_input/plants/fusion_2025/new_line_coordinate_verification_20260822.csv \
    data/model_input/plants/fusion_2025/verified_replacement_pairing_overrides_20260822.csv \
    data/model_input/plants/fusion_2025/verified_fleet_scope_exclusions_20260822.csv \
    data/model_input/plants/fusion_2025/verified_coordinate_corrections_20260828.csv \
    data/model_input/plants/fusion_2025/coordinate_recheck_20260828.csv \
    data/model_input/plants/fusion_2025/coordinate_recheck_report_20260828.md \
    "$REVIEW_CSV" \
    scripts/v4/run_tiered_batch_20260829.sh \
    paper/applied_energy_2026/archive/notes/balanced_solver_protocol_20260822.md \
    "$OUT_ROOT/_input_snapshot/"
fi

COMMON=(--demand-scenario d_medium --budget-case B40 --solver-profile final
        --threads "$THREADS")

# ---- Tier 1: core joint solves (0.10% target) ------------------------------
run_or_reuse S1_baseline d_medium 40 0.40 normal "$CORE_GAP" "$CORE_MAX_GAP" 3600 "$OUT_ROOT/full"
run_or_reuse S3_all_spatial_equalized d_medium 40 0.40 normal "$CORE_GAP" "$CORE_MAX_GAP" 3600 "$OUT_ROOT/full"
run_or_reuse S5_offshore_parity d_medium 40 0.40 normal "$CORE_GAP" "$CORE_MAX_GAP" 3600 "$OUT_ROOT/full"

S1_REF="$OUT_ROOT/full/S1_baseline_results.json"
S2_REF="$OUT_ROOT/full/S3_all_spatial_equalized_results.json"
S3_REF="$OUT_ROOT/full/S5_offshore_parity_results.json"

# ---- Tier 2: high-precision fixed-path identification (0.10%, 300 s) ------
run_or_reuse S3_all_spatial_equalized d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s2_fixed_s1_turnover" --fixed-capacity-path "$S1_REF" --fixed-capacity-mode turnover
run_or_reuse S3_all_spatial_equalized d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s2_fixed_s1_dispatch" --fixed-capacity-path "$S1_REF" --fixed-capacity-mode turnover_and_dispatch
run_or_reuse S5_offshore_parity d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s3_fixed_s1_turnover" --fixed-capacity-path "$S1_REF" --fixed-capacity-mode turnover
run_or_reuse S5_offshore_parity d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s3_fixed_s1_dispatch" --fixed-capacity-path "$S1_REF" --fixed-capacity-mode turnover_and_dispatch
run_or_reuse S1_baseline d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s1_fixed_s1_turnover_control" --fixed-capacity-path "$S1_REF" --fixed-capacity-mode turnover
run_or_reuse S1_baseline d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s1_fixed_s2_turnover" --fixed-capacity-path "$S2_REF" --fixed-capacity-mode turnover
run_or_reuse S1_baseline d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s1_fixed_s2_dispatch" --fixed-capacity-path "$S2_REF" --fixed-capacity-mode turnover_and_dispatch
run_or_reuse S1_baseline d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s1_fixed_s3_turnover" --fixed-capacity-path "$S3_REF" --fixed-capacity-mode turnover
run_or_reuse S1_baseline d_medium 40 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/s1_fixed_s3_dispatch" --fixed-capacity-path "$S3_REF" --fixed-capacity-mode turnover_and_dispatch

run_cmd "$PY_BIN" scripts/v4/analyze_capacity_feedback_counterfactual.py \
    --baseline-json "$S1_REF" --treatment-full-json "$S2_REF" \
    --treatment-fixed-turnover-json "$OUT_ROOT/s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json" \
    --treatment-fixed-dispatch-json "$OUT_ROOT/s2_fixed_s1_dispatch/S3_all_spatial_equalized_results.json" \
    --null-control-json "$OUT_ROOT/s1_fixed_s1_turnover_control/S1_baseline_results.json" \
    --reverse-fixed-turnover-json "$OUT_ROOT/s1_fixed_s2_turnover/S1_baseline_results.json" \
    --reverse-fixed-dispatch-json "$OUT_ROOT/s1_fixed_s2_dispatch/S1_baseline_results.json" \
    --output-dir "$OUT_ROOT/analysis_s2"
run_cmd "$PY_BIN" scripts/v4/analyze_storage_feedback_counterfactual.py \
    --baseline-json "$S1_REF" --s5-full-json "$S3_REF" \
    --s5-fixed-turnover-json "$OUT_ROOT/s3_fixed_s1_turnover/S5_offshore_parity_results.json" \
    --s5-fixed-dispatch-json "$OUT_ROOT/s3_fixed_s1_dispatch/S5_offshore_parity_results.json" \
    --null-control-json "$OUT_ROOT/s1_fixed_s1_turnover_control/S1_baseline_results.json" \
    --reverse-fixed-turnover-json "$OUT_ROOT/s1_fixed_s3_turnover/S1_baseline_results.json" \
    --reverse-fixed-dispatch-json "$OUT_ROOT/s1_fixed_s3_dispatch/S1_baseline_results.json" \
    --output-dir "$OUT_ROOT/analysis_s3"

# ---- Tier 3: descriptive robustness (0.20% target, 0.30% acceptance) ------
run_or_reuse S1_baseline d_high 40 0.40 normal "$ROBUST_GAP" "$ROBUST_MAX_GAP" 1200 "$OUT_ROOT/demand/d_high"
run_or_reuse S1_baseline d_low 40 0.40 normal "$ROBUST_GAP" "$ROBUST_MAX_GAP" 1200 "$OUT_ROOT/demand/d_low"
run_or_reuse S1_baseline d_medium 35 0.40 normal "$ROBUST_GAP" "$ROBUST_MAX_GAP" 1200 "$OUT_ROOT/lifetime35/full"
run_or_reuse S3_all_spatial_equalized d_medium 35 0.40 normal "$ROBUST_GAP" "$ROBUST_MAX_GAP" 1200 "$OUT_ROOT/lifetime35/full"
S1_L35="$OUT_ROOT/lifetime35/full/S1_baseline_results.json"
run_or_reuse S3_all_spatial_equalized d_medium 35 0.40 fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$OUT_ROOT/lifetime35/s2_fixed_s1_turnover" --fixed-capacity-path "$S1_L35" --fixed-capacity-mode turnover
run_cmd "$PY_BIN" scripts/v4/analyze_capacity_feedback_counterfactual.py \
    --baseline-json "$S1_L35" \
    --treatment-full-json "$OUT_ROOT/lifetime35/full/S3_all_spatial_equalized_results.json" \
    --treatment-fixed-turnover-json "$OUT_ROOT/lifetime35/s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json" \
    --output-dir "$OUT_ROOT/lifetime35/analysis_s2"

# ---- Tier 4: representative near-optimal identities (0.25% identity gap) --
NEAR=(--near-opt-path-mip-gap "$IDENTITY_GAP" --near-opt-path-time-limit 500)
run_or_reuse S1_baseline d_medium 40 0.40 near "$ROBUST_GAP" "$ROBUST_MAX_GAP" 240 "$OUT_ROOT/near_optimal/s1_farthest_terminal_e0010" "${NEAR[@]}" --near-opt-identity-reference "$S1_REF" --near-opt-cost-reference "$S1_REF" --near-opt-cost-tolerance 0.001 --near-opt-direction farthest --near-opt-scope terminal
run_or_reuse S3_all_spatial_equalized d_medium 40 0.40 near "$ROBUST_GAP" "$ROBUST_MAX_GAP" 240 "$OUT_ROOT/near_optimal/s2_closest_terminal_e0010" "${NEAR[@]}" --near-opt-identity-reference "$S1_REF" --near-opt-cost-reference "$S2_REF" --near-opt-cost-tolerance 0.001 --near-opt-direction closest --near-opt-scope terminal
run_or_reuse S5_offshore_parity d_medium 40 0.40 near "$ROBUST_GAP" "$ROBUST_MAX_GAP" 240 "$OUT_ROOT/near_optimal/s3_closest_terminal_e0010" "${NEAR[@]}" --near-opt-identity-reference "$S1_REF" --near-opt-cost-reference "$S3_REF" --near-opt-cost-tolerance 0.001 --near-opt-direction closest --near-opt-scope terminal
run_or_reuse S1_baseline d_medium 40 0.40 near "$ROBUST_GAP" "$ROBUST_MAX_GAP" 240 "$OUT_ROOT/near_optimal/s1_farthest_full_e0010" "${NEAR[@]}" --near-opt-identity-reference "$S1_REF" --near-opt-cost-reference "$S1_REF" --near-opt-cost-tolerance 0.001 --near-opt-direction farthest --near-opt-scope full_path

# ---- Tier 5: isolated minimum-utilization sensitivity (0.20% target) -----
for UTIL in 0.20 0.30 0.50; do
    TAG="u$(printf '%03d' "$($PY_BIN -c "print(round(float('$UTIL') * 100))")")"
    CASE_ROOT="$UTIL_ROOT/$TAG"
    run_or_reuse S1_baseline d_medium 40 "$UTIL" normal "$ROBUST_GAP" "$ROBUST_MAX_GAP" 1200 "$CASE_ROOT/full"
    run_or_reuse S3_all_spatial_equalized d_medium 40 "$UTIL" normal "$ROBUST_GAP" "$ROBUST_MAX_GAP" 1200 "$CASE_ROOT/full"
    UTIL_S1="$CASE_ROOT/full/S1_baseline_results.json"
    run_or_reuse S3_all_spatial_equalized d_medium 40 "$UTIL" fixed "$CORE_GAP" "$FIXED_MAX_GAP" 300 "$CASE_ROOT/s2_fixed_s1_turnover" --fixed-capacity-path "$UTIL_S1" --fixed-capacity-mode turnover
    run_cmd "$PY_BIN" scripts/v4/analyze_capacity_feedback_counterfactual.py \
        --baseline-json "$UTIL_S1" \
        --treatment-full-json "$CASE_ROOT/full/S3_all_spatial_equalized_results.json" \
        --treatment-fixed-turnover-json "$CASE_ROOT/s2_fixed_s1_turnover/S3_all_spatial_equalized_results.json" \
        --output-dir "$CASE_ROOT/analysis_s2"
done

# ---- Freeze-gate audit ------------------------------------------------------
run_cmd env CF_OUTPUT_ROOT="$OUT_ROOT" CF_UTIL_OUTPUT_ROOT="$UTIL_ROOT" \
    "$PY_BIN" scripts/v4/audit_verified_submission_batch_20260822.py

echo "Tiered coordinate-corrected evidence package complete: $OUT_ROOT"
echo "Tiered utilization-sensitivity package complete: $UTIL_ROOT"
