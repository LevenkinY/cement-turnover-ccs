#!/usr/bin/env bash
# Core evidence chain -- 6 tasks + automatic extraction/analysis (2026-09-13).
#
# STORYLINE (narrowed, author + GPT):
#   需求收缩改变留存资产；AF 空间差异在既定市场与封存条件下改变资产选择；
#   提前固化错误路径增加后续减排负担。
# Wording constraint: this establishes the cost of a commitment made while IGNORING
# AF spatial conditions. It does NOT show that stepwise planning is generally
# inefficient. Do not write it that way.
#
# The 6 tasks and the claim each supports:
#   1 central_J               产能/AF/CCS 如何共同演化        (基准)
#   2 s3_equalized_joint      A: 忽略 AF 空间差异, 选厂是否改变
#   3 s3path_under_real       A 路径固定回真实条件 -> 承诺代价  <-- 最关键
#   4 centralpath_selfcheck   固定路径程序是否正确            (程序检查, 一次)
#   5 demand_high_J           收缩较慢时哪些资产保留
#   6 demand_low_J            收缩较快时哪些资产保留
#
# DELIBERATELY NOT RUN HERE (each with the claim it forces us to drop):
#   * stepwise_s1 / stepwise_s2  (广义 J/S)  -> 暂缓; 措辞收窄为 "忽略 AF 空间条件的
#       资产承诺代价", 不主张所有分步规划低效. 第一批撑不住主线时才讨论转向.
#   * 海上成本平价 / EOR 80      -> 不主张其因果效应
#   * B30 / B50 / 95% 捕集率     -> 不讨论全预算区间或极深减排可行性
#   * CCS 快慢整套 / 熟料系数 high / EE / ARM 多档 -> 不主张精确年份; 条件于外生路径
#   * 零运费 / 省级 / 邻省多套    -> 只保留一个针对性空间检验
#   * u_min 两档 / 年退出上限 / 五年退出上限 -> 不作为贡献
#   * 旧 AF 口径复跑 / any_after_expiry      -> 开发审计; 结构下无效
# RULE: 减少运行必须同时减少主张. 不能只删实验、保留宽泛结论.
#
# MIP GAP: 粗筛阶段一切运行都用 screen 档 (3%). 定稿阶段对承载正文数字的少量运行
# 改回 final 档 + 0.5% 或更低 -- 尤其"承诺代价"那一对, 因为 R 是两个优化值之差,
# 两次的 gap 带会相加, 3% 下区间必然含 0 而判为"未判定".
#
#   ./run_v5_core_evidence.sh [GAP] [PROFILE] [SECONDS]
set -uo pipefail
cd "$(dirname "$0")/../.."

PY=.venv/bin/python
GAP="${1:-0.03}"
PROFILE="${2:-screen}"
SECS="${3:-2400}"
ROOT="v5/results/core6_$(date +%Y%m%d_%H%M)"
mkdir -p "$ROOT"
echo "[core6] root=$ROOT  gap=${GAP} profile=${PROFILE} limit=${SECS}s"
echo "[core6] settings: fixed cost 40 | transport 0.55/0.12/0.05 | AF new caliber | EOR 0 | u_min 0.30"
echo "[core6] TIER: $( [[ "${PROFILE}" == screen ]] && echo '粗筛 (数字不进正文; R 区间在 3% 下必然含 0)' || echo '定稿档' )"

_solve() {  # _solve <name> <scenario> <demand> <budget> [extra...]
  local name="$1" scen="$2" dem="$3" bud="$4"; shift 4
  local out="${ROOT}/${name}"
  mkdir -p "$out"
  echo "[core6] === ${name} : ${scen} ${dem} ${bud} $* ==="
  PYTHONPATH=v5/model "$PY" -u -m src_v5.main -s "$scen" --demand-scenario "$dem" \
    --budget-case "$bud" -o "$out" --solver-profile "${PROFILE}" \
    --mip-gap "${GAP}" --time-limit "${SECS}" --threads 0 --tee "$@" \
    > "${out}/stdout.log" 2>&1
  local rc=$?
  local line
  line="$(grep -aE "Solver diagnostics" "${out}/stdout.log" | tail -1)"
  echo "[core6] ${name} rc=${rc} ${line:-<no diagnostics>}"
  # analyse after EVERY solve, so a partial chain still yields a usable report
  "$PY" v5/scenarios/analyze_runs.py "${ROOT}" --reference central_J \
      --out "${ROOT}/analysis" >/dev/null 2>&1 \
    && echo "[core6] ${name}: analysis refreshed -> ${ROOT}/analysis/report.md"
}
json_of() { ls -1 "${ROOT}/$1"/*_results.json 2>/dev/null | head -1; }

# ── 1. baseline ────────────────────────────────────────────────────────────
_solve central_J S1_baseline d_medium B40

# ── 2-3. resource-ignoring counterfactual -> commitment cost (critical path) ─
_solve s3_equalized_joint S3_all_spatial_equalized d_medium B40
S3_JSON="$(json_of s3_equalized_joint)"
if [[ -n "${S3_JSON}" ]]; then
  _solve s3path_under_real S1_baseline d_medium B40 --fixed-capacity-path "${S3_JSON}"
else
  echo "[core6] SKIP s3path_under_real: no S3 result JSON"
fi

# ── 4. procedural check ────────────────────────────────────────────────────
# Expect the cost within the COMBINED solver error of central_J. Do NOT demand
# exact equality: re-optimisation may land below central_J's INCUMBENT.
J_JSON="$(json_of central_J)"
if [[ -n "${J_JSON}" ]]; then
  _solve centralpath_selfcheck S1_baseline d_medium B40 --fixed-capacity-path "${J_JSON}"
else
  echo "[core6] SKIP centralpath_selfcheck: no central_J result JSON"
fi

# ── 5-6. demand endpoints (same ABSOLUTE budget; bracket the retention set) ─
_solve demand_high_J S1_baseline d_high B40
_solve demand_low_J  S1_baseline d_low  B40

# ── final analysis + gate summary ──────────────────────────────────────────
"$PY" v5/scenarios/analyze_runs.py "${ROOT}" --reference central_J \
    --out "${ROOT}/analysis" --csv
echo "[core6] ================= GATE SUMMARY ================="
for pair in "s3path_under_real:承诺代价 R_A" "centralpath_selfcheck:程序自检"; do
  name="${pair%%:*}"; label="${pair##*:}"
  j="$(json_of central_J)"; f="$(json_of ${name})"
  if [[ -n "${j}" && -n "${f}" ]]; then
    echo "[core6] --- ${label} (${name}) ---"
    "$PY" v5/scenarios/report_planning_loss.py "${j}" "${f}" --label "${name}" 2>&1 \
      | grep -aE "point estimate|bound interval|RESOLVED|NOT RESOLVED|INCONSISTENT|VERDICT"
  else
    echo "[core6] --- ${label}: missing JSON, pair not evaluated ---"
  fi
done
echo "[core6] done. report: ${ROOT}/analysis/report.md"
