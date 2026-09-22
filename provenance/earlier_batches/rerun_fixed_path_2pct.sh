#!/usr/bin/env bash
# Re-run ONLY the two fixed-path tasks at the 2% screening floor.
#
# Why: the first core6 chain launched them WITHOUT forwarding --fixed-capacity-path,
# because _solve in run_v5_core_evidence.sh never appended "$@" (the echo printed the
# full command, so the log looked correct). Both came back with
# capacity_path_counterfactual.enabled = False and byte-identical objectives -- i.e.
# two plain S1_baseline solves. So R_A and the self-check were never measured.
# That bug is fixed in run_v5_core_evidence.sh; this script redoes the two tasks only.
#
# GAP FLOOR 2% (author policy: batch test runs). NOTE this still cannot RESOLVE the
# commitment cost: the effect is ~3 bn on a ~1,754 bn base (0.17%), and at a 2% gap
# each run's band is ~35 bn, so the interval will contain zero. The purpose here is to
# verify the fixing procedure and read the MECHANISM / asset-set answers, not the
# headline number. The final manuscript pair needs gaps around 0.05-0.08%.
#
#   ./rerun_fixed_path_2pct.sh [SOURCE_ROOT]
set -uo pipefail
cd "$(dirname "$0")/../.."

PY=.venv/bin/python
SRC="${1:-}"
if [[ -z "${SRC}" ]]; then
  SRC="$(ls -1dt v5/results/core6_* 2>/dev/null | head -1)"
fi
[[ -d "${SRC}" ]] || { echo "[rerun] source root not found: ${SRC}" >&2; exit 2; }

GAP=0.02
PROFILE=screen
SECS=2400
VOID="v5/results/void_nofixedpath_$(date +%Y%m%d_%H%M)"
mkdir -p "${VOID}"

echo "[rerun] source=${SRC} gap=${GAP} profile=${PROFILE}"
echo "[rerun] 2% floor: R_A will still be UNRESOLVED by construction -- aim is procedure + mechanism"

json_of() { ls -1 "${SRC}/$1"/*_results.json 2>/dev/null | head -1; }

for name in s3path_under_real centralpath_selfcheck; do
  if [[ -d "${SRC}/${name}" ]]; then
    mv "${SRC}/${name}" "${VOID}/${name}"
    echo "[rerun] parked invalid ${name} -> ${VOID}/${name}"
  fi
done

run() {  # run <name> <fixed-path-json>
  local name="$1" ref="$2" out="${SRC}/$1"
  mkdir -p "${out}"
  echo "[rerun] === ${name} : --fixed-capacity-path ${ref} ==="
  PYTHONPATH=v5/model "$PY" -u -m src_v5.main -s S1_baseline \
    --demand-scenario d_medium --budget-case B40 -o "${out}" \
    --solver-profile "${PROFILE}" --mip-gap "${GAP}" --time-limit "${SECS}" \
    --threads 0 --tee --fixed-capacity-path "${ref}" > "${out}/stdout.log" 2>&1
  local rc=$?
  echo "[rerun] ${name} rc=${rc}"
  grep -a "Capacity-turnover counterfactual" "${out}/stdout.log" | head -1 | sed 's/^/[rerun]   /'
  grep -a "Solver diagnostics:" "${out}/stdout.log" | tail -1 | sed 's/^/[rerun]   /'
}

S3="$(json_of s3_equalized_joint)"; J="$(json_of central_J)"
[[ -n "${S3}" ]] || { echo "[rerun] missing s3_equalized_joint JSON" >&2; exit 2; }
[[ -n "${J}"  ]] || { echo "[rerun] missing central_J JSON" >&2; exit 2; }

run s3path_under_real "${S3}"      # A path under REAL conditions -> commitment cost
run centralpath_selfcheck "${J}"   # central path back into central -> procedure check

echo "[rerun] --- verify the fixing actually engaged (enabled must be True) ---"
"$PY" - "${SRC}" <<'PYEOF'
import json, pathlib, sys
D = pathlib.Path(sys.argv[1])
for name in ("s3path_under_real", "centralpath_selfcheck"):
    p = next((D/name).glob("*_results.json"), None)
    if not p:
        print(f"[rerun]   {name}: NO JSON"); continue
    cp = (json.loads(p.read_text()).get("capacity_path_counterfactual") or {})
    print(f"[rerun]   {name}: enabled={cp.get('enabled')} source={cp.get('source_scenario')} "
          f"plants={cp.get('fixed_plants')}")
PYEOF

echo "[rerun] --- refresh analysis ---"
"$PY" v5/scenarios/analyze_runs.py "${SRC}" --reference central_J \
    --out "${SRC}/analysis" --csv 2>&1 | tail -8

echo "[rerun] --- gate: R_A and self-check ---"
for pair in "s3path_under_real:承诺代价 R_A" "centralpath_selfcheck:程序自检"; do
  name="${pair%%:*}"; label="${pair##*:}"
  f="$(json_of ${name})"; j="$(json_of central_J)"
  if [[ -n "${f}" && -n "${j}" ]]; then
    echo "[rerun] --- ${label} ---"
    "$PY" v5/scenarios/report_planning_loss.py "${j}" "${f}" --label "${name}" 2>&1 \
      | grep -aE "point estimate|bound interval|NOTE|RESOLVED|INCONSISTENT|VERDICT"
  fi
done
echo "[rerun] done. report: ${SRC}/analysis/report.md"
