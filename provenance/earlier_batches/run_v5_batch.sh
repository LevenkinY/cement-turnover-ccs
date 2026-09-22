#!/usr/bin/env bash
# v5 batch driver: the five public planning scenarios plus the six sensitivity
# groups. Run from the repository root, or pass a group name.
#
#   bash v5/scenarios/run_v5_batch.sh public        # 5 public scenarios
#   bash v5/scenarios/run_v5_batch.sh sensitivity   # 6 sensitivity groups
#   bash v5/scenarios/run_v5_batch.sh all
#
# ---------------------------------------------------------------------------
# PUBLIC SCENARIO SET (renumbered for the paper; one per perturbation)
# ---------------------------------------------------------------------------
# The paper's public labels are an editorial renumbering of the frozen internal
# case aliases (documented in the RCR SI, Table S2). This script always uses the
# FULL internal name: several bare numeric aliases still resolve to legacy cases
# that are NOT the public scenarios (e.g. `-s S5` -> S5_offshore_parity, which is
# public S3, not public S5). The guard below refuses such input.
#
#   public | meaning                       | command line
#   -------|-------------------------------|----------------------------------------
#   S1     | central                       | -s S1_baseline            -d d_medium
#   S2     | AF spatial neutralisation     | -s S3_all_spatial_equalized -d d_medium
#   S3     | offshore storage cost parity  | -s S5_offshore_parity     -d d_medium
#   S4     | slow contraction              | -s S1_baseline            -d d_high
#   S5     | deep contraction              | -s S1_baseline            -d d_low
#
# All five share B40 and the central resource settings. S2 and S3 perturb one
# resource dimension each; S4/S5 vary demand while keeping S1 resource settings.
# Market accessibility is deliberately NOT a scenario: it is a property of the
# demand layer that applies uniformly across all five, and its influence is
# tested once as a sensitivity (group `market_neutral`) instead.
#
# ---------------------------------------------------------------------------
# SENSITIVITY GROUPS (one axis at a time; nothing else changes)
# ---------------------------------------------------------------------------
#   radius          F/t retention radius, collapsed to a single axis:
#                   32/0.45 = 71 km, 53.2/0.45 = 118 km (central), 79/0.45 = 176 km
#                   The retention decision compares F with t*d, so the ratio is
#                   the first-order driver. One validation pair with the same
#                   ratio but different levels (53.2/0.45 vs 106.4/0.90) confirms
#                   the collapse; drop it if the retained fleet already matches.
#   umin            utilization floor (central 0.30; 0.20 / 0.40 sensitivity). An
#                   ASSUMPTION about the minimum annual activity level of a
#                   'retained and producing' line -- NOT a kiln technical minimum
#                   load and NOT derived from the MIIT replacement rule.
#   resolution      market nodes at a ~2x coarser cluster target (convergence
#                   test, <=5%): rebuild with
#                   build_market_nodes.py --target 75 --out-nodes/--out-arcs,
#                   rerun S1. Not a CLI switch on the run itself.
#   ccs_decline     slow / central / fast CCS cost decline
#   budget          B30 / B40 (central) / B50
#   ccr_high        clinker/cement ratio slow-blending variant (GB 175-2023-
#                   consistent: 2030 held at the 2025 level, 0.590 by 2060 vs
#                   central 0.550). CCR is the largest exogenous abatement
#                   lever (~15% of BAU at 2060), so its rate shapes turnover.
#   market_neutral  transport cost -> 0, i.e. clinker is nationally fungible.
#                   This is exactly the pre-P0-4 model assumption, so the
#                   difference vs S1 measures what the demand layer is worth.
#   renewal_window  same-site renewal allowed in ANY period after expiry instead
#                   of only the first one (central unchanged); a strong
#                   determinant of the 2060 spatial pattern.
#   eor_revenue     EOR external-revenue offset (80 CNY/tCO2). Central credits
#                   ZERO: a payment between agents is a transfer, not a resource
#                   cost reduction, and 80 would give EOR an ~85 CNY/tCO2 edge
#                   over DSA and change source-sink / plant choices.
#   decline_pace    VALIDATION ONLY: cap the national active-capacity decline at
#                   10%/yr (observed 2016-2020 band 5-10%). Never a central
#                   setting; the unconstrained pace is always reported under
#                   capacity_decline_diagnostic.
#   discount        3% / 5% (central) / 8%
#
# NOT run (decided against, to keep the design bounded): provincial demand-share
# convergence, alternative EOR accounting, uniform 0.20 CNY/t-km transport.
# Capture efficiency 0.95 IS run (above): it is the B50 feasibility boundary.
set -euo pipefail
cd "$(dirname "$0")/../.."

GROUP="${1:-all}"
STAMP="$(date +%Y%m%d)"
ROOT="v5/results/batch_${STAMP}"

run() {  # run <run-name> <scenario> <demand> <budget> [extra args...]
  local name="$1" scen="$2" demand="$3" budget="$4"; shift 4
  case "${scen}" in
    [0-9]*) echo "REFUSING bare numeric alias '${scen}': it does not mean the public scenario." >&2; exit 2 ;;
  esac
  local out="${ROOT}/${name}"
  mkdir -p "${out}"
  echo "[v5] ${name}: ${scen} / ${demand} / ${budget} $*"
  PYTHONPATH=v5/model .venv/bin/python -m src_v5.main \
    -s "${scen}" --demand-scenario "${demand}" --budget-case "${budget}" \
    -o "${out}" --solver-profile final --mip-gap 0.005 --threads 0 "$@" \
    2>&1 | tee "${out}/run.log"
}

public() {
  run s1_central            S1_baseline             d_medium B40
  run s2_af_neutral         S3_all_spatial_equalized d_medium B40
  run s3_offshore_parity    S5_offshore_parity      d_medium B40
  run s4_slow_contraction   S1_baseline             d_high   B40
  run s5_deep_contraction   S1_baseline             d_low    B40
}

sensitivity() {
  # retention radius F/t  (same scenario, different fixed cost)
  run sens_radius_71        S1_baseline d_medium B40 --fixed-operating-cost 32.0
  run sens_radius_176       S1_baseline d_medium B40 --fixed-operating-cost 79.0
  # utilization floor (central 0.30 = 90/310 rounded; an ASSUMPTION about the
  # minimum annual activity level of a 'retained and producing' line, not a kiln
  # technical minimum load and not derived from the MIIT replacement rule)
  run sens_umin_020         S1_baseline d_medium B40 --min-operating-utilization 0.20
  run sens_umin_040         S1_baseline d_medium B40 --min-operating-utilization 0.40
  # resolution convergence is produced by rebuilding the market-node layer with a
  # coarser cluster target (build_market_nodes.py --target 75) and rerunning S1;
  # not a CLI switch.
  # CCS cost decline speed
  run sens_decline_slow     S1_baseline d_medium B40 --ccs-decline slow
  run sens_decline_fast     S1_baseline d_medium B40 --ccs-decline fast
  # carbon budget stringency
  run sens_budget_b30       S1_baseline d_medium B30
  run sens_ccr_high         S1_baseline d_medium B40 --ccr-path-case high
  # capture efficiency: 0.90 central (all published cement pathway models
  # verified use 0.90); 0.95 is the advanced case and is the single parameter that
  # decides whether B50 is feasible at all (the 2060 floor is exactly
  # (1 - efficiency) x gross emissions).
  run sens_eff_095          S1_baseline d_medium B40 --capture-efficiency 0.95
  run sens_eff_095_b50      S1_baseline d_medium B50 --capture-efficiency 0.95
  # market-side neutralisation (the pre-P0-4 assumption)
  run sens_market_neutral   S1_baseline d_medium B40 --demand-transport-mode zero
  # same-site renewal window: WITHDRAWN 2026-09-13. "any_after_expiry" is not a
  # valid sensitivity under the current state constraints -- a line that exits
  # cannot return, so a renewal placed later than the first post-expiry period is
  # only reachable if the line produced continuously in the interim. Testing it
  # would need an explicit idle state, which is out of scope for v5. See config_v5.
  # (run sens_renewal_window ... --same-site-renewal-window any_after_expiry)
  # EOR external-revenue offset scenario (central credits NO EOR revenue; see
  # v5/progress.md §2.2 -- a payment between agents is a transfer, not a resource
  # cost reduction, and 80 CNY/tCO2 would give EOR an ~85 CNY/tCO2 spatial edge)
  run sens_eor_revenue_80   S1_baseline d_medium B40 --eor-revenue 80
  # VALIDATION ONLY: policy-feasible contraction pace
  run sens_decline_pace     S1_baseline d_medium B40 --max-annual-capacity-decline 0.10
  # discount rate
  run sens_discount_3pct    S1_baseline d_medium B40 --discount-rate 0.03
  run sens_discount_8pct    S1_baseline d_medium B40 --discount-rate 0.08
  # ── AF caliber (2026-09-13) ─────────────────────────────────────────────
  # Legacy caliber, audit only: reproduces the pre-2026-09-13 result so the size
  # of the caliber fix can be read off directly.
  run sens_af_caliber_flat  S1_baseline d_medium B40 --af-energy-caliber flat_tce
  # AF cost coefficients in the model's own unit (CNY per tce/yr of added
  # nameplate handling capacity). Central 790.48 sits inside the bottom-up range
  # 121-1400; this bracket spans no-pretreatment and full-prepare projects.
  run sens_af_capex_low     S1_baseline d_medium B40 --af-investment-per-tce 121
  run sens_af_capex_high    S1_baseline d_medium B40 --af-investment-per-tce 1400
  # O&M per tce handled: central 40 is at the bottom of the 42-305 range.
  run sens_af_om_high       S1_baseline d_medium B40 --af-om-per-tce 120
  # biogenic CO2 physically released per tce of AF: the unverified conversion
  # between budget-credited and physically handled tonnage. Central 0.0 keeps the
  # two calibers identical; 1.31 is the MOEE-mix-based value (grade C).
  run sens_af_biogenic_131  S1_baseline d_medium B40 --af-biogenic-co2-per-tce 1.31
  # ── Institutional friction: slow capacity exit (2026-09-13) ─────────────
  # NOT a central setting. Caps the decline at 10% per FIVE-YEAR period, which
  # retains idle capacity by construction, so the low utilisation it produces is a
  # consequence of the cap. Pair it with a J/S comparison to price the friction.
  run scen_slow_exit        S1_baseline d_medium B40 --max-capacity-decline-per-period 0.10
  # ── J/S counterfactual pair (2026-09-13) ────────────────────────────────
  # Stage 1: fleet chosen on conventional resource cost only (carbon target OFF,
  # CCS and AF fixed to zero). Stage 2: y/r inherited, AF+CCS re-enabled under the
  # SAME budget. R = C_S - C_J requires stage 2 to use stage 1's JSON, so these two
  # are sequential and must be run in order; verify the pair with
  # v5/scenarios/verify_pair_configs.py before differencing.
  run js_stage1_capacity    S1_baseline d_medium B40 --planning-mode stepwise_capacity
  js_stage2_low_carbon() {
    local s1_json
    s1_json="$(ls -1 "${ROOT}/js_stage1_capacity/S1_baseline_results.json" 2>/dev/null | head -1)"
    if [[ -z "${s1_json}" ]]; then
      echo "[v5] skipping js_stage2_low_carbon: stage 1 output not found under ${ROOT}/js_stage1_capacity" >&2
      return 0
    fi
    run js_stage2_low_carbon S1_baseline d_medium B40 \
      --planning-mode stepwise_low_carbon --fixed-capacity-path "${s1_json}"
  }
  js_stage2_low_carbon
}

case "${GROUP}" in
  public)      public ;;
  sensitivity) sensitivity ;;
  all)         public; sensitivity ;;
  *) echo "unknown group '${GROUP}' (public | sensitivity | all)" >&2; exit 2 ;;
esac

echo "[v5] batch complete -> ${ROOT}"
