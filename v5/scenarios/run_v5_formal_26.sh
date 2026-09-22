#!/usr/bin/env bash
# FORMAL BATCH -- 26 logical tasks (author-confirmed 2026-09-14, supersedes
# run_v5_core_evidence.sh / run_v5_layer2.sh for manuscript numbers).
#
#   C1-C6 (6) + R1-R8 (8 pairs = 16) + K1/K2 (2) = 24 logical tasks.
#
# STORYLINE (frozen): 需求收缩重塑留存资产；AF空间条件在既定市场与封存条件下改变
# 资产选择；忽略这些条件提前确定产能路径，会产生可量化的后续调整代价。
# P_A = the capacity path selected by C4 (AF spatial equalization); all R-arms fix
# THE SAME P_A (mode-1: "what does THIS commitment cost under condition theta").
# A third run (re-derived equalized path under theta) is added ONLY if an arm
# materially changes the loss or makes the fixed path infeasible (progress.md D).
#
# PREREQUISITES (all closed 2026-09-14):
#   - phi>0 carbon accounting repaired; market override sync; analyzer contract.
#   - Hall certificates: 149-node set feasible under d_high/d_medium/d_low,
#     75-node under d_medium (v5/scenarios/check_arc_feasibility.py).
#   - Arc-economics screen: densified arc set changes delivered cost by 0.503%
#     (v5/scenarios/screen_arc_economics.py).
#   - R6/K code landed: --terminal-value-mode, --ccs-min-operating-years,
#     --storage-rate-scale; verify_pair_configs MUST_MATCH updated.
#
# PRECISION DISCIPLINE (progress.md section 9.8): runs that feed an R interval
# must use the FINAL profile at gap <= 0.005. The C1/C4/C5 triad is the most
# sensitive: R = C5 - C1, and the two gap bands add.
#
#   ./run_v5_formal_26.sh [GAP] [PROFILE] [SECS]
#   default: 0.005 final 7200
#   ROOT_OVERRIDE=<dir> reuses an existing batch root (runs whose result JSON
#   already exists are skipped -- e.g. a finished C1 need not be re-solved).
#
# REUSE RULE: identical frozen-config results (fingerprint-checked) may be
# reused or warm-start the formal run; never re-run just because the schema
# gained fields (progress.md G1).
set -uo pipefail
cd "$(dirname "$0")/../.."

PY=.venv/bin/python
GAP="${1:-0.005}"
PROFILE="${2:-final}"
SECS="${3:-7200}"
ROOT="${ROOT_OVERRIDE:-v5/results/formal_$(date +%Y%m%d_%H%M)}"
ALT_NODES="v5/data/alt_market_75/demand_market_nodes.csv"
ALT_ARCS="v5/data/alt_market_75/demand_market_arcs.csv"
mkdir -p "$ROOT"

echo "[F26] root=${ROOT} gap=${GAP} profile=${PROFILE} limit=${SECS}s"
echo "[F26] central: fc=40 | transport 0.55/0.12/0.05 | 149 nodes | B40 | EOR 0 | u_min 0.30 | phi=0 | TV none | commitment 15"

_solve() {  # _solve <name> <scenario> <demand> <budget> [extra...]
  local name="$1" scen="$2" dem="$3" bud="$4"; shift 4
  local out="${ROOT}/${name}"
  if find "${out}" -name "*_results.json" 2>/dev/null | grep -q .; then
    echo "[F26] ${name}: already present, skipping"; return 0
  fi
  # Fixed-path (remedial) problems are far easier than joint ones -- measured:
  # 72-177 s to gap 0.000% at screen tier. Give them a shorter, still generous
  # limit; joints get the full SECS.
  local limit="${SECS}"
  case " $* " in
    *" --fixed-capacity-path "*) limit="${FIXED_SECS:-1200}" ;;
  esac
  mkdir -p "${out}"
  echo "[F26] === ${name} :: ${scen} ${dem} ${bud} (limit ${limit}s) $* ==="
  PYTHONPATH=v5/model "$PY" -u -m src_v5.main -s "$scen" --demand-scenario "$dem" \
    --budget-case "$bud" -o "${out}" --solver-profile "${PROFILE}" \
    --mip-gap "${GAP}" --time-limit "${limit}" --threads 0 --tee "$@" \
    > "${out}/stdout.log" 2>&1
  local rc=$?
  local dg; dg="$(grep -a "Solver diagnostics:" "${out}/stdout.log" | tail -1)"
  echo "[F26] ${name} rc=${rc} ${dg:-<no diagnostics>}"
  if [[ "${rc}" -ne 0 ]]; then
    echo "[F26] ${name} *** FAILED *** last error:"
    grep -aE "^[A-Za-z_.]*(Error|Exception)" "${out}/stdout.log" | tail -1 | sed 's/^/[F26]   /'
    tail -3 "${out}/stdout.log" | sed 's/^/[F26]   /'
  fi
}

json_of() { find "${ROOT}/$1" -name "*_results.json" 2>/dev/null | head -1; }

assert_engaged() {  # assert_engaged <run-name> <expected key>=<expected value>...
  local name="$1"; shift
  local f; f="$(json_of "${name}")"
  if [[ -z "${f}" ]]; then echo "[F26] ASSERT ${name}: no JSON"; return 0; fi
  "$PY" - "$name" "$f" "$@" <<'PYEOF'
import json, sys
name, path = sys.argv[1], sys.argv[2]
checks = dict(item.partition("=")[0:3:2] for item in sys.argv[3:])
d = json.loads(open(path).read())
cfg = d.get("effective_config") or {}
cp = d.get("capacity_path_counterfactual") or {}
problems = []
for k, want in checks.items():
    got = str(bool(cp.get("enabled"))) if k == "fixed_path_enabled" else str(cfg.get(k))
    if got != want:
        problems.append(f"{k}: got {got!r} want {want!r}")
print(f"[F26] ASSERT {name}: " + ("*** FAILED *** " + "; ".join(problems) if problems else f"ok ({checks})"))
PYEOF
}

# ═══ CORE EVIDENCE CHAIN (C1-C6) ════════════════════════════════════════════
_solve C1_central_J S1_baseline d_medium B40
_solve C4_equalized_J S3_all_spatial_equalized d_medium B40
PA="$(json_of C4_equalized_J)"          # P_A: the AF-equalized capacity path
if [[ -n "${PA}" ]]; then
  _solve C5_commitment_cost S1_baseline d_medium B40 --fixed-capacity-path "${PA}"
  assert_engaged C5_commitment_cost fixed_path_enabled=True
else
  echo "[F26] SKIP C5 (and all R-fixed runs): no C4 JSON"
fi
C1J="$(json_of C1_central_J)"
if [[ -n "${C1J}" ]]; then
  _solve C6_selfcheck S1_baseline d_medium B40 --fixed-capacity-path "${C1J}"
  assert_engaged C6_selfcheck fixed_path_enabled=True
fi
_solve C2_demand_high S1_baseline d_high B40
_solve C3_demand_low  S1_baseline d_low  B40

# ═══ TARGETED SENSITIVITIES R1-R8 (each: joint + fixed P_A) ═════════════════
arm() {  # arm <tag> [extra args...]
  local tag="$1"; shift
  _solve "${tag}_joint" S1_baseline d_medium B40 "$@"
  if [[ -n "${PA}" ]]; then
    _solve "${tag}_fixed" S1_baseline d_medium B40 --fixed-capacity-path "${PA}" "$@"
    assert_engaged "${tag}_fixed" fixed_path_enabled=True
  fi
}

arm R1_af_high_cost   --af-investment-per-tce 1400 --af-om-per-tce 120
arm R2_beta_high      --beta-af 0.69
arm R3_phi_131        --af-biogenic-co2-per-tce 1.31
arm R4_opex_combo     --fixed-operating-cost 53.2 --demand-transport-scale 0.8181818181818182
if [[ -e "${ALT_NODES}" && -e "${ALT_ARCS}" ]]; then
  arm R5_node75 --demand-market-node-file "${ALT_NODES}" --demand-market-arc-file "${ALT_ARCS}"
else
  echo "[F26] SKIP R5: alternate 75-node build missing"
fi
arm R6_terminal_value --terminal-value-mode annuity_consistent_guarded
arm R7_eor80          --eor-revenue 80
arm R8_storage_rate2x --storage-rate-scale 2.0

# ═══ LOCK-IN COMMITMENT RELAXATION (K1/K2) ══════════════════════════════════
_solve K1_commit0_J S1_baseline d_medium B40 --ccs-min-operating-years 0
if [[ -n "${PA}" ]]; then
  _solve K2_commit0_fixed S1_baseline d_medium B40 \
    --ccs-min-operating-years 0 --fixed-capacity-path "${PA}"
  assert_engaged K2_commit0_fixed fixed_path_enabled=True ccs_min_operating_years=0
fi

# ═══ SUMMARY ════════════════════════════════════════════════════════════════
echo "[F26] ================= SUMMARY ================="
"$PY" v5/scenarios/analyze_runs.py "${ROOT}" --reference C1_central_J \
    --out "${ROOT}/analysis" --csv 2>&1 | tail -30
echo "[F26] done. report: ${ROOT}/analysis/report.md"
