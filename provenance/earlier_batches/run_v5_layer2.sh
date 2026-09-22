#!/usr/bin/env bash
# LAYER 2 -- targeted sensitivities, batched at the 2% screening floor.
#
# Author policy: pre-final / batch runs use gap >= 2%. These numbers are for
# MECHANISM and ROBUSTNESS checking, NOT for the manuscript. Note the commitment
# cost (~0.17% of total) cannot be resolved at 2%; only the "does the conclusion
# move" question is answerable here.
#
# TWO TESTING MODES (must be labelled correctly in the text):
#   MODE 2 (re-run the whole resource-ignoring decision rule):
#       joint(param) -> equalized_joint(param) -> fixed_path_from_that_equalized(param)
#       Answers: "is the LOSS from ignoring spatial conditions robust?"
#   MODE 1 (fix ONE committed path, re-optimise the remedies):
#       joint(param) -> fixed_path_from_CENTRAL_equalized(param)
#       Answers: "what does THIS commitment cost under different conditions?"
#       Must NOT be called "full strategy robustness".
#
# Which items use which, and why:
#   AF cost / beta / phi  -> MODE 2 (core mechanism; GPT: "核心技术权衡是否可靠")
#   fixed cost / transport -> MODE 1 (guard: is the conclusion only an artefact of
#                            the new central 40+0.55?)
#   spatial aggregation    -> MODE 2 at 75 nodes (is the asset ranking manufactured
#                            by the candidate network?)
#
# DELIBERATELY NOT RUN (with the claim this forces us to drop): offshore parity,
# EOR revenue, B30/B50, capture efficiency 0.95, CCS decline-speed suite, clinker
# ratio / EE / ARM multi-levels, zero-freight / province / neighbour-province demand
# modes, the two u_min levels, annual and five-year exit caps, the old AF-caliber
# re-run, any_after_expiry. RULE: cutting runs must cut claims too.
#
#   ./run_v5_layer2.sh [GAP] [PROFILE] [SECONDS]
set -uo pipefail
cd "$(dirname "$0")/../.."

PY=.venv/bin/python
GAP="${1:-0.02}"
PROFILE="${2:-screen}"
SECS="${3:-2400}"
ROOT="v5/results/layer2_$(date +%Y%m%d_%H%M)"
CENTRAL_ROOT="v5/results/core6_20260913_2334"
CENTRAL_S3="${CENTRAL_ROOT}/s3_equalized_joint/S3_all_spatial_equalized_results.json"
ALT_NODES="v5/data/alt_market_75/demand_market_nodes.csv"
ALT_ARCS="v5/data/alt_market_75/demand_market_arcs.csv"
mkdir -p "$ROOT"

echo "[L2] root=${ROOT} gap=${GAP} profile=${PROFILE} limit=${SECS}s"
echo "[L2] central reference: ${CENTRAL_ROOT}/central_J"
[[ -e "${CENTRAL_S3}" ]] || echo "[L2] WARN: central equalized path missing -> MODE 1 pair will be skipped"
[[ -e "${ALT_NODES}" ]] || echo "[L2] WARN: 75-node build missing -> spatial check will be skipped"

# ── solver wrapper: forwards extra args (a previous version dropped "$@" and two
#    runs silently became plain S1_baseline solves) ────────────────────────────
_solve() {  # _solve <name> <scenario> <demand> <budget> [extra...]
  local name="$1" scen="$2" dem="$3" bud="$4"; shift 4
  local out="${ROOT}/${name}"
  if find "${out}" -name "*_results.json" 2>/dev/null | grep -q .; then
    echo "[L2] ${name}: already present, skipping"; return 0
  fi
  mkdir -p "${out}"
  echo "[L2] === ${name} :: ${scen} ${dem} ${bud} $* ==="
  PYTHONPATH=v5/model "$PY" -u -m src_v5.main -s "$scen" --demand-scenario "$dem" \
    --budget-case "$bud" -o "${out}" --solver-profile "${PROFILE}" \
    --mip-gap "${GAP}" --time-limit "${SECS}" --threads 0 --tee "$@" \
    > "${out}/stdout.log" 2>&1
  local rc=$?
  local dg; dg="$(grep -a "Solver diagnostics:" "${out}/stdout.log" | tail -1)"
  echo "[L2] ${name} rc=${rc} ${dg:-<no diagnostics>}"
  # A non-zero rc with no diagnostics means the run SOLVED and then died during
  # extraction/saving -- i.e. the whole solve time was wasted with no output.
  # Surface the error immediately instead of leaving it in the log: this is exactly
  # how the NameError-on-Path defect burned a full 2400 s solve.
  if [[ "${rc}" -ne 0 ]]; then
    echo "[L2] ${name} *** FAILED *** last error:"
    grep -aE "^[A-Za-z_.]*(Error|Exception)" "${out}/stdout.log" | tail -1 | sed 's/^/[L2]   /'
    tail -3 "${out}/stdout.log" | sed 's/^/[L2]   /'
  fi
}

json_of() { find "${ROOT}/$1" -name "*_results.json" 2>/dev/null | head -1; }

# ── switch-effect assertions (the lesson of the fixed-path incident) ─────────
assert_engaged() {  # assert_engaged <run-name> <expected key>=<expected value>...
  local name="$1"; shift
  local f; f="$(json_of "${name}")"
  if [[ -z "${f}" ]]; then echo "[L2] ASSERT ${name}: no JSON"; return 0; fi
  "$PY" - "$name" "$f" "$@" <<'PYEOF'
import json, sys
name, path = sys.argv[1], sys.argv[2]
checks = {}
for item in sys.argv[3:]:
    k, _, v = item.partition("=")
    checks[k] = v
d = json.loads(open(path).read())
cfg = d.get("effective_config") or {}
cp = d.get("capacity_path_counterfactual") or {}
problems = []
for k, want in checks.items():
    if k == "fixed_path_enabled":
        got = str(bool(cp.get("enabled")))
    else:
        got = str(cfg.get(k))
    if got != want:
        problems.append(f"{k}: got {got!r} want {want!r}")
if problems:
    print(f"[L2] ASSERT {name}: *** FAILED *** " + "; ".join(problems))
else:
    print(f"[L2] ASSERT {name}: ok ({', '.join(checks)})")
PYEOF
}

# ── MODE 2 helper: joint -> equalized -> fixed(equalized) ────────────────────
mode2() {  # mode2 <tag> [extra solver args...]
  local tag="$1"; shift
  _solve "m2_${tag}_joint"     S1_baseline             d_medium B40 "$@"
  _solve "m2_${tag}_equalized" S3_all_spatial_equalized d_medium B40 "$@"
  local eq; eq="$(json_of "m2_${tag}_equalized")"
  if [[ -n "${eq}" ]]; then
    _solve "m2_${tag}_fixed" S1_baseline d_medium B40 --fixed-capacity-path "${eq}" "$@"
    assert_engaged "m2_${tag}_fixed" fixed_path_enabled=True
  else
    echo "[L2] SKIP m2_${tag}_fixed: no equalized JSON"
  fi
}

# ── MODE 1 helper: joint -> fixed(CENTRAL equalized path) ───────────────────
mode1() {  # mode1 <tag> [extra solver args...]
  local tag="$1"; shift
  _solve "m1_${tag}_joint" S1_baseline d_medium B40 "$@"
  if [[ -e "${CENTRAL_S3}" ]]; then
    _solve "m1_${tag}_fixed" S1_baseline d_medium B40 \
      --fixed-capacity-path "${CENTRAL_S3}" "$@"
    assert_engaged "m1_${tag}_fixed" fixed_path_enabled=True
  else
    echo "[L2] SKIP m1_${tag}_fixed: central equalized path missing"
  fi
}

# ═══ GROUP A -- AF cost / beta / phi  (MODE 2, core mechanism) ═══════════════
mode2 afcapex_low   --af-investment-per-tce 121
mode2 afcapex_high  --af-investment-per-tce 1400
mode2 afom_high     --af-om-per-tce 120
mode2 beta_high     --beta-af 0.69
mode2 phi_131       --af-biogenic-co2-per-tce 1.31

# ═══ GROUP B -- fixed cost / transport, single axis (MODE 1) ═════════════════
mode1 fc40_tp045    --fixed-operating-cost 40   --demand-transport-scale 0.8181818181818182
mode1 fc532_tp055   --fixed-operating-cost 53.2

# ═══ GROUP C -- spatial aggregation at ~75 nodes (MODE 2) ════════════════════
if [[ -e "${ALT_NODES}" && -e "${ALT_ARCS}" ]]; then
  SPATIAL=(--demand-market-node-file "${ALT_NODES}" --demand-market-arc-file "${ALT_ARCS}")
  mode2 node75 "${SPATIAL[@]}"
else
  echo "[L2] SKIP node75: alternate market build missing"
fi

# ═══ SUMMARY ═════════════════════════════════════════════════════════════════
echo "[L2] ================= SUMMARY ================="
"$PY" v5/scenarios/analyze_runs.py "${ROOT}" "${CENTRAL_ROOT}" \
    --reference central_J --out "${ROOT}/analysis" --csv 2>&1 | tail -40
echo "[L2] done. report: ${ROOT}/analysis/report.md"
