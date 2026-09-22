"""
Configuration file for v5 model (2026-09-11 version migration).

Flat parameter structure. P0 changes landed here (see `v5/README.md` and
`v5/parameters/` for the derivation of every value):
  P0-1 CCS capture cost: dimension fix + three cost-decline scenarios + continuous size scaling
  P0-2 Alternative fuels: four-layer constraint structure; engineered TSR path removed
  P0-3 Operations: u_min 0.25, ramp constraint removed, plant fixed operating cost added,
       days_per_year unified to 310, early-retirement cost re-based to physical resource cost
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# v5 working root. Inputs that v5 derives itself (not shared with v4) live here;
# shared, code-read input tables stay in data/model_input and are referenced by path
# (see v5/data/README.md for the index).
V5_ROOT = PROJECT_ROOT / "v5"
V5_DATA = V5_ROOT / "data"
V5_RESULTS = V5_ROOT / "results"
DATA_INPUT = PROJECT_ROOT / "data" / "model_input"
DATA_RAW = PROJECT_ROOT / "data" / "raw"
# v5-specific derived input: overlap- and area-corrected AF accessibility (P0-2)
AF_ACCESS_CORRECTED_CSV = V5_DATA / "plant_af_access_corrected.csv"

# ── Time ────────────────────────────────────────────────────────────────
T_LIST = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
YEARS = {t: i for i, t in enumerate(T_LIST)}
N_T = len(T_LIST)
# Trapezoidal integration over the 2025-2060 node horizon. Flow quantities
# use these weights; stock investments are charged once in their decision year.
PERIOD_WEIGHTS = {
    year: (T_LIST[1] - T_LIST[0]) / 2.0
    if idx in {0, len(T_LIST) - 1}
    else (T_LIST[idx + 1] - T_LIST[idx - 1]) / 2.0
    for idx, year in enumerate(T_LIST)
}

# ── Plant set ───────────────────────────────────────────────────────────
PLANT_CSV = DATA_INPUT / "plants" / "plant_af_catchment.csv"
TIER_CSV = DATA_INPUT / "plants" / "plant_location_tier.csv"
PLANT_SOURCE_XLSX = DATA_INPUT / "plants" / "1_source_cement.xlsx"
PLANT_CORRECTIONS_CSV = DATA_INPUT / "plants" / "plant_data_corrections.csv"
BASEYEAR_OUTPUT_CSV = DATA_INPUT / "regional" / "cement_output_2025.csv"
EXTERNAL_TECH_PATH_CSV = DATA_INPUT / "technology" / "external_technology_paths.csv"
EXTERNAL_TECH_SOURCE_CSV = DATA_INPUT / "technology" / "external_technology_path_sources.csv"

# ── CCS supply nodes ────────────────────────────────────────────────────
STORAGE_CSV = DATA_INPUT / "storage" / "storage_data_tif.csv"
STORAGE_TEXTURE_CSV = DATA_INPUT / "storage" / "storage_texture_5km.csv"
CHINA_LAND_GEOJSON = DATA_RAW / "geography" / "中华人民共和国.geojson"

# ── Regional data ───────────────────────────────────────────────────────
REGIONAL_DIR = DATA_INPUT / "regional"
SCM_CSV = REGIONAL_DIR / "scm_proxy.csv"
PROCESS_ADJ_CSV = REGIONAL_DIR / "process_adjustment_path.csv"
LIAO_CSV = REGIONAL_DIR / "liao_provincial_baseline.csv"
AF_BIOMASS_CSV = REGIONAL_DIR / "af_biomass_supply.csv"
AF_WASTE_CSV = REGIONAL_DIR / "af_waste_supply.csv"
DEMAND_XLSX = DATA_INPUT / "demand" / "cement_demand_scenarios_v4.xlsx"

# Demand sensitivity is selected independently from the S1-S5 technology and
# storage cases. All paths use observed production through 2025. D-M is the
# central planning path; D-H and D-L are demand sensitivities.
DEMAND_SCENARIO = "d_medium"
VALID_DEMAND_SCENARIOS = ("d_high", "d_medium", "d_low")

# ── Output ──────────────────────────────────────────────────────────────
RESULTS_DIR = V5_RESULTS


# ── AF energy caliber (2026-09-13) ─────────────────────────────────────
# WHICH heat demand the AF constraints act on. The two calibers answer different
# questions and must not be mixed:
#   "plant_heat_demand" (central): H[i,t] = h_i * (1-EE_t) * Q[i,t], where
#       h_i = plant_fuel_ef[i]/COAL_EF_TCO2_PER_TCE is the plant's OWN kiln heat
#       intensity (measured tiers: 101.7/109.9/119.8 kgce/t; n=686/781/105) and
#       EE_t is the exogenous energy-efficiency path. Both the technical ceiling
#       and the AF CO2 credit are computed on this H.
#   "flat_tce" (legacy, audit only): H[i,t] = TCE_PER_T_CLINKER * Q[i,t] with a
#       constant 0.105 tce/t for every plant and no EE. This is what the model
#       used before 2026-09-13: it overstated heat demand (by 12.2% in 2060,
#       since 0.105 < the fleet-mean 0.107 and EE reduces the rest), and it made
#       the AF credit plant-tier- and EE-dependent because the credit was
#       fuel_ef*(1-EE)/0.105 per tce instead of COAL_EF.
# Set to "flat_tce" ONLY to reproduce pre-2026-09-13 results.
AF_ENERGY_CALIBER = "plant_heat_demand"

# ── AF technical ceiling (P0-2) ────────────────────────────────────────
# Physical substitution potential of a precalciner kiln equipped with an AF
# feed system. Replaces AF_ENGINEERING_TSR_PATH (a per-plant engineered 8-node
# path that was itself the sole determinant of the national AF trajectory:
# it bound 86.6%-100% of operating lines in 2030-2050).
# Source: 中国建筑材料联合会《水泥行业碳减排技术指南》(2022-11): 燃料替代率 20~60%
#   (standard crush/screen/classify + feed route), >50% (pre-calcination route);
#   华新地维 measured 10% -> 63.43% (2024-03); Cement Europe (2025) EU 2023
#   average 56%; JRC (2023) kilns can burn up to 100% with full configuration.
# Applied as  af_supply <= theta * H[i,t]  (see AF_ENERGY_CALIBER).
# Sensitivity 0.40 / 0.60 / 0.80.
AF_TECHNICAL_TSR_CEILING = 0.60

# ── AF accessibility allocation (P0-2, option (b)) ─────────────────────
# Plant-level accessible resource is used as a *relative* weight to allocate the
# provincial resource pool, so that the plant-level constraint is coupled to the
# pool instead of being placed in parallel (and thus permanently slack).
# KAPPA caps how far a single plant may concentrate beyond its accessibility
# proportional share. KAPPA=1 -> fully rigid; KAPPA->inf -> free reallocation
# within the province (the S3 counterfactual limit). Sensitivity 1.0 / 2.0 / 4.0.
AF_ACCESS_ALLOCATION_HEADROOM = 2.0

# ── AF national expansion rate (P0-2) ──────────────────────────────────
# Per-period cap on the GROWTH of national AF energy in ABSOLUTE terms, expressed
# as a fraction of the SAME period's national kiln heat demand:
#   sum_i af_supply[i,t] <= sum_i af_supply[i,t-1] + AF_EXPANSION_FRACTION_OF_HEAT * sum_i H[i,t]
# NAME IT CORRECTLY (2026-09-13 rename from AF_EXPANSION_PP): this is NOT a "10 pp
# per period" cap on the substitution rate, because the RHS base (H_t) falls as
# output falls while the LHS increment is an absolute energy amount. The realized
# RATE increase can therefore exceed or fall short of 10 pp in any period.
# Value 0.10 is the register's v2.33 AF_DIFFUSION_SCHEDULE (late) value
# (RMI 2022 p.24 Fig.21); that pair of parameters had been idled when the model
# switched to the engineered path. Reference points: measured 2021->2023 +1.5 pp/yr
# (=7.5 pp/period), 2023->2025 policy target +2.5 pp/yr (=12.5 pp/period),
# RMI 2030->2050 +1.8 pp/yr (=9 pp/period). Sensitivity 0.07 / 0.10 / 0.14.
AF_EXPANSION_FRACTION_OF_HEAT = 0.10
# DEPRECATED alias, retained so old scripts/validators do not break. Do not use in
# new code; the underlying quantity is a fraction of heat, not percentage points.
AF_EXPANSION_PP = AF_EXPANSION_FRACTION_OF_HEAT * 100.0

# ── AF supply caps (fraction of plant fuel demand) ────────────────────

# AF fossil CO2 reduction coefficient: substituting 1 tce of AF for 1 tce of coal
# reduces ACCOUNTING (fossil) CO2 by BETA_AF * COAL_EF_TCO2_PER_TCE.
# EVIDENCE STATUS: grade C, NOT a source value (2026-09-13 review). The v3
# provenance (archive/v3_20260911/v3_model/src/config.py:569-580) assumed 74%
# biogenic carbon and then asserted 0.55 with unresolved arithmetic; evaluated
# against MOEE《企业温室气体排放核算与报告填报说明 水泥熟料生产》附录B per-fuel
# defaults (non-biogenic carbon content, grade A), that same assumed mix implies
# beta ~0.78-0.87, not 0.55. A waste-dominated Chinese mix instead gives
# beta ~0.55-0.69, i.e. 0.55 sits at the LOWER EDGE of the defensible range.
# Residual on 0.55 per author decision 2026-09-13 ("temporarily keep"); the range
# is declared as a sensitivity and the value must not be cited as sourced.
# Sensitivity 0.55 / 0.60 / 0.69.
BETA_AF = 0.55

# Biogenic CO2 physically released per tce of AF burned (tCO2/tce of AF energy).
# The capture unit sees GROSS flue gas (process + fossil fuel + biogenic fuel); the
# carbon budget only deducts the fossil part. This parameter is the conversion
# between the two calibers, and it is an OPEN EVIDENCE GAP -- do NOT treat the
# central value as verified:
#   * MOEE 附录B gives per-fuel total EF and non-biogenic carbon share (grade A),
#     from which a 90% MSW-RDF + 10% industrial-waste mix yields ~1.3 tCO2/tce of
#     biogenic CO2 (total ~2.57, fossil ~1.26).
#   * But NO China-specific energy-share breakdown of the AF mix exists (searched:
#     repo library, Zotero collections 12/21/50/51/86, web). The mix is grade C.
# Central therefore stays 0.0 = reproduce the current behaviour (captured tonnage
# equals the budget-credited tonnage); the sensitivity quantifies the under-count.
# Sensitivity 0.0 / 0.65 / 1.31 (tCO2/tce).
# Repair-20260914: phi>0 uses annual treated-stream accounting with a common
# capture efficiency. Fossil retained flow alone earns budget credit. See
# parameters/repair_carbon_and_comparisons_20260914.md; all legacy phi>0 runs invalid.
AF_BIOGENIC_CO2_PER_TCE = 0.0

# ── CCS parameters (migrated from v3 src/config.py) ────────────────────
# Source: Mao et al. (2025) Earth's Future Table 3; Dong et al. (2025) LCA;
#         CBMA 2023; GCCSI 2025. Mao reports 451.3 CNY/t cement capture
#         investment and 244.8 CNY/t cement O&M. The normalized reference-
#         plant values below use clinker/cement=0.74, direct emissions=0.825
#         tCO2/t clinker and capture efficiency=0.90:
#         451.3/(0.74*0.825)=739; 244.8/(0.74*0.825*0.90)=445.
CCS_PARAMS = {
    # Capture
    'capture_efficiency': 0.90,     # 捕集效率 (Mao et al. 2025 Table 3)
    # Mao et al. (2025) Table 3: 451.3 CNY/t cement (one-off capex) and 244.8 CNY/t cement
    # (annual O&M). Mao Eq. 4/17/18 confirm the one-off/annual split. Both must use the SAME
    # normalisation denominator: 0.74 clinker/cement x 0.825 tCO2/t clinker x 0.90 capture rate
    # = 0.54945 tCO2/t cement. 451.3/0.54945 = 821.4; 244.8/0.54945 = 445.5.
    # The former 739 omitted the /0.90 (dimension error, 11% understatement).
    # Implied capture LCOC = 821.4 x 0.0593 + 445.5 = 494 CNY/tCO2.
    'capture_investment': 821.4,    # CNY/(tCO2·yr)
    'capture_om': 445.5,            # CNY/tCO2
    # P1-5: minimum capture-train design size. 30 ktCO2/yr let the model report
    # three commercial CCS units of ~33 kt/yr in 2035, which is MIP noise, not a
    # decision. 100 ktCO2/yr is supported four ways: it is IEAGHG/Element Energy
    # (2024) small-scale boundary (sites emitting up to 100 kt/yr); it is the
    # smallest standard commercial capture plant offered (SLB Capturi "Just Catch
    # 100"); it is the small/large boundary in observed European deployment
    # (<=1 kt pilot, 1-100 kt medium, >100 kt large); and it sits above every
    # Chinese cement demonstration (Anhui Conch Wuhu 50 kt) while below every
    # commercial cement project (Brevik 400, Padeswood 800, Obourg 1,000,
    # Aalborg 1,500 kt/yr). Applied as min(value, plant_big_m) so no line becomes
    # infeasible; 100 kt is ~10-12% of the capturable CO2 of a 3,200 t/d line.
    'min_active_design_kt': 100.0,
    'base_margin_per_ton': 0.0,

    # Transport
    'pipeline_investment': 0.26,   # CNY/(tCO2·km) — Dong et al. 2025 全生命周期成本
    'pipeline_om': 0.00,
    'max_distance': 500,           # km — Mao et al. 2025
    # Compatibility mirror of the active route cap. Candidate construction is
    # governed by the explicit constants below (3/type + 2 high-capacity;
    # deduplicated union capped at 8).
    'nearest_storages': 8,

    # Storage (onshore base cost)
    'dsa_cost': 25,                 # CNY/tCO2 — GCCSI 2025, 陆上开放边界
    'eor_storage_cost': 20,         # CNY/tCO2 — Mao et al. 2025 Table 3
    # EOR revenue credited in the CENTRAL objective: ZERO (author decision
    # 2026-09-12, see v5/progress.md §2.2). Rationale: 80 CNY/tCO2 is a
    # conservative "revenue-side" calibration from project cases, NOT a verified
    # national-average NET RESOURCE benefit. A payment from an oilfield to a
    # cement firm is a transfer between agents; in a social-planner resource-cost
    # model it does not reduce the resources consumed by capture/transport/
    # injection by 80 CNY/t. Crediting it would also give EOR a ~85 CNY/tCO2
    # spatial advantage over DSA (20 - 80 = -60 vs +25), changing source-sink and
    # plant-level choices -- so it cannot be dismissed as a sub-1% effect.
    # The 80 CNY/t case is retained as the named sensitivity
    # EOR_REVENUE_REFERENCE ("external revenue offset scenario").
    'eor_revenue': 0,               # CNY/tCO2 — central: no external revenue credited

    # P1-2: share of CO2 DELIVERED to an EOR site that counts as permanent
    # mitigation. EOR recycles produced CO2 back into the reservoir, so gross
    # injection is not net storage. The basis matters and is the usual source of
    # confusion: per tonne GROSS INJECTED only 0.2-0.6 is net new storage in a
    # mature flood, but per tonne DELIVERED (which is what f_p_eor measures, since
    # recycled CO2 is internal to the EOR operation) 0.90-0.98 is trapped over the
    # project life (IEA 2015 Storing CO2 through EOR: 0.98 t/t delivered; Melzer
    # 2012: 90-95% of purchased CO2 remains trapped). 0.90 is the conservative end
    # of the operational range and is used here; the flow still pays transport and
    # storage cost and still earns the EOR credit, only the mitigation credit is
    # scaled. Range for sensitivity: 0.70 / 0.90 / 1.00.
    'eor_storage_retention': 0.90,

}

# EOR external-revenue offset, retained as a NAMED sensitivity only (not central;
# see the 'eor_revenue' comment above and v5/progress.md §2.2). The sensitivity run
# is "external revenue offset scenario": CCS_PARAMS['eor_revenue'] = this value.
EOR_REVENUE_REFERENCE = 80          # CNY/tCO2 — project-case conservative calibration

# CCS_MIN_CAPTURE_LOAD: once a capture train is built it must run at least at
# this fraction of its design capacity. Rationale corrected 2026-09-12: the
# original justification ("keeps endogenous learning tied to used capacity") died
# when CCS_LEARNING_CURVE was removed in P0-1. The constraint is retained on
# different grounds -- an installed train should not be left idle (the same logic
# as the kiln's own MIN_OPERATING_UTILIZATION = 0.30), and together with
# CCS_MIN_OPERATING_YEARS = 15 it is part of the lock-in mechanism the paper
# studies. Unlike the removed capture-fraction ceiling, this one is active: in the
# 2026-09-11 solution 5 plant-periods sit exactly at 0.20.
CCS_MIN_CAPTURE_LOAD = 0.20

# Commercial CCS additions must remain in operation for at least 15 years.
# This is aligned with the China cement retrofit screen in Mao et al. (2025),
# which requires at least 15 years of remaining plant life and uses a 15-year
# payback period. Commitments extending beyond the 2060 model horizon are
# treated as continuing after 2060; the plant must remain active through 2060.
CCS_MIN_OPERATING_YEARS = 15
CCS_TERMINAL_COMMITMENT_MODE = "continue_beyond_horizon"

# Terminal-value sensitivity arm (R6, registered 2026-09-14; derivation and
# guard rule: parameters/terminal_value_commitment_20260914.md). Central "none"
# charges stock investments in full at the decision year (status quo). The arm
# "annuity_consistent_guarded" charges only the within-horizon annuity share,
# charge_factor(y, L) = A(min(L, 2061-y)) / A(L) with A(n) = sum_k (1+d)^-k,
# and credits NO salvage for vintages whose in-horizon service window is
# shorter than TERMINAL_VALUE_MIN_INHORIZON_SERVICE (the model's own 15-year
# commitment caliber) -- this guard blocks near-free end-of-horizon investment.
TERMINAL_VALUE_MODE = "none"  # options: none, annuity_consistent_guarded
TERMINAL_VALUE_ASSET_LIVES = {"ccs": 25, "renewal": 40}  # years; AF excluded
TERMINAL_VALUE_MIN_INHORIZON_SERVICE = 15

# Observed pre-2025 cement capture pilots are retained as REPORTING CONTEXT
# ONLY: they enter no constraint, no target accounting and no objective term.
# (The earlier "learning seeds" role ended when CCS_LEARNING_CURVE was removed
# in P0-1.)
OBSERVED_PILOT_CCS_ENABLED = True
OBSERVED_PILOT_CCS_INCLUDE_IN_TARGET_ACCOUNTING = False
OBSERVED_PILOT_CCS_PERSISTENCE = "base_year_only"  # options: base_year_only, installed_year_onward

# ── Offshore parameters (migrated from v3) ─────────────────────────────
# Source: Mao et al. (2025) Table 3 footnote; GCCSI 2025
OFFSHORE_PARAMS = {
    'pipeline_cost_factor': 1.55,   # 海上 vs 陆上管道成本倍率
    'storage_cost_factor': 3.00,     # 海上储存成本倍率（更复杂的海床基础设施）
}

# ── CCS scale limits (时变捕集规模上限, migrated from v3) ──────────────
# Replaces v4's dumb 100 kt min/max block constraints
# CBMA 2023; CCUS 报告趋势
# CCS_SCALE_LIMITS was removed on 2026-09-12 (capture-constraint review). It
# imposed `captured <= limit[year] * co2_total` per plant -- a capture-fraction
# ceiling that ramps with the CALENDAR YEAR. Three reasons it went:
#   1. It never bound. Across the 2026-09-11 v5 solution (1,572 plants x 8
#      periods, 4,851 plant-periods with gross emissions > 0) the constraint was
#      active in 0 cases, while the capture_efficiency cap was active in 978
#      (20.2%). After 2045 it is slack by arithmetic (limit 0.95 > efficiency
#      0.90); before 2040 the model captures nothing anyway.
#   2. It acts on the wrong object. A plant's capture fraction is a design
#      property of the installed train (= capture_efficiency), not something that
#      rises with the calendar for an already-built unit. The intended meaning --
#      "the industry cannot deploy this fast" -- is a DEPLOYMENT-PACE limit on
#      how much design capacity gets built, not a throttle on how hard existing
#      capacity may run.
#   3. Its original rationale is superseded. It was introduced as a staged
#      design-scale / investment-scale PROXY under an earlier binary-installation
#      formulation; the model now has k_ccs, priced ccs_new_design, the
#      CCS_ROLLOUT_PARAMS size gate and a 15-year minimum operating commitment.
# The removed values were 2025: 0.10, 2030: 0.25, 2035: 0.50, 2040: 0.75,
# 2045: 0.90, 2050-2060: 0.95 (no source was ever recorded for them).

# ── CCS rollout params ─────────────────────────────────────────────────
# Replaces v4's hardcoded size gate
CCS_ROLLOUT_PARAMS = {
    'min_capacity_td_by_period': {
        2025: None,
        2030: 4000,
        2035: 3200,
        2040: 3200,
        2045: 3200,
        2050: 3200,
        2055: 3200,
        2060: 3200,
    },
}

# ── CCS cost decline scenarios (P0-1) ─────────────────────────────────
# Three decline-speed scenarios replace the former single curve (CAPEX 1.00->0.75,
# OM 1.00->0.80). 2060 factors are anchored on CBMA (2023) 表9: the central scenario
# reproduces its midpoint trajectory (470->290 = 0.617); slow/fast bracket its
# upper/lower bounds. Implied 2060 capture LCOC: 395 / 306 / 237 CNY/tCO2, spanning
# CBMA's 2060 band of 150-430. The fast case's 2060 O&M (214 CNY/tCO2) sits on the
# bottom-up physical floor (steam 3.3 GJ/tCO2 + 56 kWh/tCO2 + solvent/labour/maintenance
# = 180-220), so it cannot go faster.
# The single multiplier is applied to capture CAPEX, capture O&M, and the transport
# and storage unit costs (Mao's alpha/beta are full-chain).
# See v5/parameters/parameters0911.md §5.
CCS_COST_DECLINE_CASE = "central"
CCS_COST_DECLINE_SCENARIOS = {
    "slow": {2025: 1.000, 2030: 0.969, 2035: 0.938, 2040: 0.909,
             2045: 0.880, 2050: 0.853, 2055: 0.826, 2060: 0.800},
    "central": {2025: 1.000, 2030: 0.934, 2035: 0.872, 2040: 0.815,
                2045: 0.761, 2050: 0.711, 2055: 0.664, 2060: 0.620},
    "fast": {2025: 1.000, 2030: 0.900, 2035: 0.811, 2040: 0.730,
             2045: 0.658, 2050: 0.592, 2055: 0.533, 2060: 0.480},
}

# ── CCS plant-size scaling (P0-1) ─────────────────────────────────────
# Continuous power law replacing the former four-bin step table (1.08/1.00/0.93/0.88),
# which implied b ~= 0.84 over the eligible size range. NETL QGESS Rev 4b gives b = 0.60
# for the capture island equipment account; a 50/50 blend with near-proportional
# BOP/EPC (b ~= 0.95) gives b ~= 0.79. Central b_capex = 0.80 (sensitivity 0.70/0.90).
# O&M: variable O&M is linear in captured CO2, only the fixed share (22%) has scale
# economies -> b_om = 0.22*0.60 + 0.78*1.00 ~= 0.90 (sensitivity 0.85/0.95).
# NOTE: a SMALLER b means STRONGER scale economies (specific cost ~ S^(b-1)).
CCS_SIZE_SCALING = {
    "reference_design_kt": 1000.0,
    "exponent_capex": 0.80,
    "exponent_om": 0.90,
    "clip": (0.60, 1.30),
}

# ── CCS cost scaling (内生经验+规模效应, migrated from v3) ────────────
# Source: IEA 2021; Brevik CCS 2025; 本模型观测41万t/yr示范项目
# Size scaling is now a continuous power law (see CCS_SIZE_SCALING); the former
# four-bin step table and the dormant endogenous-learning / experience-stage
# machinery were removed in P0-1 as unused (learning is OFF, size classes replaced).
CCS_COST_SCALING_PARAMS = {
    'mode': 'exogenous_maturity_static_plant_scale',
    'enable_endogenous_learning': False,
    'enable_plant_size_scaling': True,
}

# ── Initial CCS projects (observed cement CO2 capture demos) ───────────
# Source: references/library/CCS_projects_CHN.xlsx
# These are stable source ids in plant_data/1_source_cement. For project-level
# demos spanning multiple same-site kiln lines, assign the observed project
# scale to the largest line to avoid double-counting public project capacities.
INITIAL_CCS_PROJECTS = {
    845: {'installed_year': 2018, 'scale': 5,  'desc': '白马山水泥厂CO2捕集纯化示范项目'},
    1359: {'installed_year': 2024, 'scale': 20, 'desc': '青州中联20万吨CO2全氧燃烧富集提纯示范项目'},
    496: {'installed_year': 2025, 'scale': 10, 'desc': '金隅北水10万吨/年CO2捕集、封存及资源化利用示范项目'},
    25: {'installed_year': 2025, 'scale': 6,   'desc': '华润水泥（昌江）碳中和研发平台一期CCUS示范项目'},
}


# ── Cost boundary ───────────────────────────────────────────────────────
# Default paper objective: incremental real mitigation resource cost of the
# ENDOGENOUS decisions. 2026-09-12 declaration (author decision, option b):
# the three EXOGENOUS mitigation paths -- energy efficiency (EE), alternative
# raw materials (ARM) and the clinker/cement ratio (CCR) -- contribute their
# emission reductions to the carbon budget, but their investment and O&M costs
# are NOT part of the objective. They are reported as order-of-magnitude
# diagnostics in results["exogenous_path_indicative_costs"] (discounted, ~1-2%
# of the system cost combined) with an explicit rate-normalization convention;
# the paper SI must state this boundary. Full baseline coal expenditure and
# carbon-price payments are retained as diagnostics, and can be included for
# accounting/policy variants.
COST_BOUNDARY = "incremental_mitigation"  # options: incremental_mitigation, full_accounting
INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE = False
INCLUDE_CARBON_COST_IN_OBJECTIVE = False

# ── AF fuel price (CNY/tce) — v3 aligned trajectory ──────────────────
# Coal enters the default objective only through AF substitution economics:
# (AF_FUEL_PRICE[year] - COAL_PRICE_SCHEDULE[year]) × displaced coal.
COAL_PRICE_SCHEDULE = {
    2025: 707, 2030: 760, 2035: 800, 2040: 850,
    2045: 900, 2050: 950, 2055: 1000, 2060: 1050,
}
COAL_PRICE = 1000.0  # CNY/tce legacy fallback if a year is absent

# AF fuel price differential is set to ZERO (AF and coal at cost parity) — P0-2.
# Evidence for parity: RMI (2022) p.22 the plant's own MSW treatment cost is
# 130-200 CNY/t and "仅能勉强达到收支平衡点"; 水泥网 2025-08-12 (interview with
# 王俊杰, 中科院工程热物理研究所) "单位热值替代燃料的价格与煤价相当，甚至还高于煤价，
# 水泥企业利用替代燃料无利可图"; RMI (2022) p.21 "使用固废与燃煤有类似的成本结构".
# Raw material and processing costs are not reliably determinable in China (no public
# RDF market price; sewage sludge has only disposal fees), so parity is the conservative
# mid-point and avoids pseudo-precision.
# Consequence: AF levelised abatement cost = (AF_OM 40.0 + capex 47.0)/1.463 = 59.5
# CNY/tCO2 (denominator = BETA_AF 0.55 x COAL_EF 2.6604; corrected 2026-09-14 from a
# stale 1.639), constant over the horizon, ~1/8.3 of CCS (494).
# Keep AF_FUEL_PRICE as a parameter (pointing at COAL_PRICE_SCHEDULE) so that the
# full_accounting cost boundary remains available.
# Sensitivity (not central): two-tier prices 600 / 1500 CNY/tce with a per-line 30%
# injection-grade step — see v5/parameters/af_structure_20260911.md §5.6.6.
AF_FUEL_PRICE = COAL_PRICE_SCHEDULE

# ── AF resource accounting (ktce/yr) ───────────────────────────────────
TCE_PER_T_CLINKER = 0.105
# Modeled operable baseline for the optimization horizon, not a strict
# statistical estimate of the current national TSR.
INITIAL_AF_RATE = 0.05
# ── AF cost (2026-09-13: caliber made explicit; provenance corrected) ───
# Structure: C_AF = AF_INVESTMENT_CNY_PER_TCE * SUM(af_add) + AF_OM_CNY_PER_TCE * SUM(af_supply)
# i.e. investment is charged on ADDED AF handling capacity (nameplate, tce/yr) and
# O&M on ACTUAL AF handled (tce). The two coefficients are stated directly in the
# model's own unit so that no hidden /TCE_PER_T_CLINKER conversion sits between the
# source and the coefficient.
#
# PROVENANCE CORRECTION (2026-09-13 review). The previous pair (AF_INVESTMENT = 83
# CNY/t clinker, AF_OM = 4.2 CNY/t clinker, divided by 0.105) was presented as a
# Zhang et al. (2021) Table A.1 value. That is a CALIBER ERROR, not a units slip:
#   * Zhang's AF row carries CC = -7.35 kgce/t clinker, i.e. the device it prices
#     delivers only ~6.7% thermal substitution (7.35/109.5), and the same paper
#     reports the AF scenario at 456.10 (2035) / 652.89 (2050) CNY/tCO2, "much
#     larger than that of other scenarios". Its own implicit capital cost is
#     83/0.00735 = 11,293 CNY per tce substituted -- two orders above what the
#     model charged. Do NOT rescale to that number (author decision: rejected).
#   * The model's af_supply can reach theta = 0.60, so the coefficient must be read
#     on a NAMEPLATE / full-capability basis, which is what 83/0.105 = 790.48 is.
#     Under that reading the value is defensible and is RETAINED; only its stated
#     source changes from "Zhang Table A.1" to the bottom-up project evidence.
# Bottom-up evidence for the nameplate coefficient (CNY per (tce/yr) of added
# AF handling capacity, all conversions in v5/parameters/af_cost_review_20260913.md):
#   阳春海螺 12,000 t/d, purchased finished RDF, receiving/conveying only ...  24.6
#   江西亚东 4x4,200 + 2x6,000 t/d, kiln-side incinerator, no pretreatment .... 121
#   华新地维 2,500 t/d single line, full prep + kiln-tail bypass + desalting ... 905-1,378
#   IFC (2017) MBT preparation subsystem, per 100 kt/yr ....................... 2,285-3,047
# Centered on the 华新-style full-prepare scope, 790.48 sits inside the range.
# NOTE (corrected input, was wrong in the register): 华新地维 is 2,500 t/d and ONE
# line, not "~5,000 t/d/line" -- confirmed by the equipment supplier (斯瑞德
# 2024-07-26) and 中国建筑材料联合会 (2024-06-04). The earlier bottom-up figures
# 2.9-26.3 CNY/(t/yr) and "22-44 per unit TSR" were understated ~3.6-5.5x and are
# withdrawn. The 8,680万元 scope also includes a cement vertical mill (not AF), so
# the AF-only share is below the quoted total.
# Sensitivity AF_INVESTMENT_CNY_PER_TCE: 121 / 790.48 / 1400 (no-prep / central /
# full-prepare-incl-non-AF-scope).
AF_INVESTMENT_CNY_PER_TCE = 790.48
# AF handling O&M, per tce actually handled. Evidence range 42-305 CNY/tce
# (RDF preparation 30-60 CNY/t fuel + electricity; IFC 2017 liquid-AF handling
# Opex EUR 5-20/t fuel = 76-305 CNY/tce at 15 GJ/t). The central 40.0 sits at,
# marginally below, the bottom of that range: it is the least defensible of the
# two coefficients and is flagged as such (grade C, low).
# Sensitivity AF_OM_CNY_PER_TCE: 40 / 60 / 120.
AF_OM_CNY_PER_TCE = 40.0

# DEPRECATED (2026-09-13). Retained only so that older scripts and the audit trail
# still resolve; the model no longer reads them. The per-t-clinker decomposition is
# exactly what obscured the caliber error above.
AF_INVESTMENT = 83.0   # = AF_INVESTMENT_CNY_PER_TCE * TCE_PER_T_CLINKER, rounded
AF_OM = 4.2            # = AF_OM_CNY_PER_TCE * TCE_PER_T_CLINKER
GJ_PER_TCE = 29.3076
BIOMASS_LHV_GJ_PER_TONNE = 20.0
BIOMASS_TCE_PER_KT = BIOMASS_LHV_GJ_PER_TONNE / GJ_PER_TCE
MSW_TCE_PER_KT = 0.12
AF_BIOMASS_POOL_COLUMN = "bio_supply_ej_access_base"
AF_WASTE_POOL_COLUMN = "residual_kt_access_base"
AF_WASTE_POOL_HIGH_COLUMN = "residual_kt_access_high"
AF_WASTE_REFERENCE_YEAR = 2018
# 2025/2030 were 0.00, i.e. "no waste-based fuel before 2030", contradicting the
# measured national TSR of ~5% in 2022/2023 (waste-dominated) and the 2025 policy
# target of 10%. In v5 the absolute pace is carried by AF_EXPANSION_PP; this schedule
# now only shapes the inter-provincial split between the biomass and waste channels.
AF_WASTE_ACCESS_MATURITY = {
    2025: 0.10,
    2030: 0.25,
    2035: 0.40,
    2040: 0.45,
    2045: 0.70,
    2050: 1.00,
    2055: 1.00,
    2060: 1.00,
}
AF_BIOMASS_ACCESS_MATURITY = {
    2025: 0.30,
    2030: 0.40,
    2035: 0.55,
    2040: 0.70,
    2045: 0.85,
    2050: 1.00,
    2055: 1.00,
    2060: 1.00,
}

# Plant catchment rasters overlap heavily in dense cement clusters. Treat raw
# catchment supply as an intra-province accessibility weight, then conserve the
# province AF pool across plants. This preserves v3 province resource accounting
# while giving v4 real plant-level heterogeneity.
AF_PLANT_ACCESS_MODE = "raw_catchment"  # province pool separately prevents double counting

# ── Exogenous ARM realization ──────────────────────────────────────────
# 2026-09-12 cleanup (author-approved): the province-corridor envelope machinery
# below was removed as dead code. The corridor terminals, diffusion profile and
# raw material corridors (CORRIDOR_UPPER/LOWER, ARM_USE_CORRIDOR_ENVELOPE,
# ARM_PROCESS_TERMINAL_BY_CORRIDOR, ARM_PROCESS_DIFFUSION_PROFILE,
# ARM_FRONT_END_CONSTRAINED_SCALE, ARM_ADOPTION_STEPS, ARM_REFERENCE_MAX,
# ARM_MAX_INCREASE_PER_PERIOD; former values 0.014-0.049 per class at 2060 and
# carbide (0.12,0.30) / steel (0.08,0.15) / flyash (0.06,0.12) / chem_ore
# (0.06,0.12) / general (0.02,0.05)) fed only `build_process_adjustment`, whose
# output (`data["process_adjustment_envelope"]`) is read by no module, and
# `build_external_arm_path` (the only ARM_SPATIAL_MODE branch consumer) was
# never called. The live ARM path is the national CSV series applied uniformly
# to all provinces (data["process_adjustment"]); measured realized values match
# it exactly. Removed values are preserved in parameter_deduction.md
# (ExoPath-cleanup-20260912) as provenance.
# Current data do not contain plant-level chemistry or material logistics.
# Declared spatial treatment: the national ARM path is applied uniformly to all
# provinces (no province differentiation in the central model).
ARM_SPATIAL_MODE = "national_mean"
ARM_PATH_CASE = "central"  # options: central, high (external_technology_paths.csv)
# Clinker-ratio (CCR) path case, read by the loader at call time via the config
# module so a run can switch it (main.py --ccr-path-case sets BOTH the instance
# attribute and the module attribute). central: 0.648 -> 0.550 (2025 basis);
# high: 2030 held at the 2025 level per GB 175-2023 (in force 2024-06-01, P.O
# 42.5 clinker+gypsum >= 80%, industry estimate ~+5pp clinker content), then
# decline to 0.590 by 2060 (slow LC3 scaling, RMI/Randol 2024). See
# v5/parameters/exogenous_path_adjustments_20260912.md.
CCR_PATH_CASE = "central"  # options: central, high
# Indicative cost anchors for the exogenous paths (REPORTING ONLY -- they do
# not enter the objective; see COST_BOUNDARY below). Sourced from the v4
# parameter register (Zhang et al. 2021 Table A.1; IEA 2018; GCCA 2021;
# RMI 2024). Their rate normalization is NOT defined by the sources, so the
# results block exogenous_path_indicative_costs applies the simple convention
# documented there and the numbers are order-of-magnitude diagnostics only.
LCC_INVESTMENT = 40.0                 # CNY/t cement capacity (register: LCC_investment)
LCC_OM = 2.5                          # CNY/t cement at the terminal ratio reduction
ARM_INVESTMENT = 33.0                 # CNY/t annual clinker capacity
ARM_OM = 1.5                          # CNY/t clinker at full ARM reference
ARM_LOGISTICS = 15.0                  # CNY/t clinker at full ARM reference

# ── Exogenous energy-efficiency path ───────────────────────────────────
# 2026-09-12 cleanup: EE_INITIAL_RATE (0.0), EE_MAX_RATE (0.20) and
# EE_MAX_INCREASE_PER_PERIOD (0.05) and the EE_PATH dict (0/3/5/7/9/10/10/10%,
# identical to the live external_technology_paths.csv ee_central column) were
# dead v4 diffusion machinery with zero references; removed as provenance
# (parameter_deduction.md, ExoPath-cleanup-20260912). The live path is the CSV
# column selected by EE_PATH_CASE below.
EE_PATH_CASE = "central"  # options: central, high (external_technology_paths.csv)
# NOTE: EE_PATH_CASE / ARM_PATH_CASE are read by the loader via from-import
# (import-time binding); only CCR_PATH_CASE is wired for call-time CLI
# overrides. Expose the other two only after switching them to _cfg_runtime
# reads (see exogenous_path_adjustments_20260912.md §4).
EE_INVESTMENT = 60.0                  # CNY/t annual clinker capacity (indicative diagnostics)
EE_OM = 3.0                           # CNY/t clinker at full EE rate (indicative diagnostics)
BETA_EE = 1.0

# ── Emission target formulation ─────────────────────────────────────────
# All five core scenarios use the same fixed B40 absolute carbon budget. The
# budget is anchored to a documented D-M no-new-mitigation reference and does
# not move with the active demand scenario. This lets demand sensitivities test
# planning pressure under a common climate constraint.
EMISSION_TARGET_MODE = "cumulative_budget"  # options: cumulative_budget, milestone, both, none
CUMULATIVE_BUDGET_METRIC = "net_direct"

# ── Planning mode: the J/S counterfactual (2026-09-13) ──────────────────
# The paper's core identification is R = C_S - C_J, where J decides capacity
# turnover and low-carbon configuration jointly and S decides them in sequence.
# Both stages must use the SAME demand proxy, transport parameters and cost
# accounting; only the information/commitment structure differs.
#
#   "joint"                  : the central model. One decision, full objective.
#   "stepwise_capacity"      : STAGE 1 of S. Choose the capacity path (y, r, u) on
#                              CONVENTIONAL production resource cost alone:
#                              the carbon target is switched off and every
#                              low-carbon variable is fixed to zero (CCS status,
#                              design, AF supply and AF design), so the plant
#                              fleet is sized and placed as if carbon were free.
#                              The 2025 base-year AF observation is NOT zeroed --
#                              the base year stays observed.
#   "stepwise_low_carbon"    : STAGE 2 of S. Requires --fixed-capacity-path
#                              pointing at the stage-1 result. y and r are fixed,
#                              AF and CCS are re-enabled, and the SAME carbon
#                              budget must be met. If it cannot be met with the
#                              inherited fleet the run is infeasible and the
#                              emissions gap is reported rather than silently
#                              relaxed (see planning_counterfactual in results).
#
# Stage 1 objective composition: with z = 0 and af = 0, the CCS, pipeline,
# storage and AF cost terms are identically zero, so the remaining objective is
# exactly capacity_retention + same_site_renewal_capex + early_retirement +
# clinker_transport + dispatch_fuel. early_retirement is kept because it is a
# real resource cost of the turnover decision, not a low-carbon measure.
PLANNING_MODE = "joint"

# Fixed reference values in model units (ktCO2-year and ktCO2/yr). They are
# frozen from the final D-M reference calculation rather than recalculated from
# each active demand path.
# 2026-08-22 re-anchored by the final-input validator after the author-approved
# exclusions and the verified R5 correction that restores Fujian Caoxi lines
# 542/543 and retires Hunan Liangtian predecessors 934/935. The active fleet
# remains 1,572 lines with unchanged national capacity; only the province-level
# production/emission-factor allocation changes. The reference uses the
# unchanged D-medium demand path. Pre-R5-correction 1,572-line values:
# cumulative 21,215,700.385806; 2025 reference 913,719.898843. Previous
# 1,574-line values: cumulative 21,215,658.097495; 2025 reference
# 913,718.077566. Earlier 2021-fleet values: cumulative 21,216,348.574303;
# 2025 reference 913,747.815090.
# 2026-09-11 re-anchored for v5 after the DAYS_PER_YEAR 330 -> 310 change
# (capacity base 1,918.2 -> 1,802.0 Mt/yr). The 2025 clinker anchor is unchanged
# (provincial observed output x clinker ratio), but the three capacity-short
# provinces (Zhejiang, Jiangsu, Tianjin) now clip at u=1.0, so the production-weighted
# BAU emission factor and hence the reference path move slightly.
# Previous values (330-day basis): cumulative 21,215,824.089272;
# 2025 reference 913,725.226516. Earlier fleet/口径 variants are recorded in the
# parameter register's update log.
# 2026-09-12 re-anchored again after the fuel-emission-factor re-anchor
# (SOURCE_FUEL_EF_REANCHOR_SCALE: capacity-weighted fleet thermal intensity
# 117.695 -> 105.000 kgce/t clinker; see v5/parameters/fuel_ef_reanchor_20260912.md).
# The production-weighted BAU direct factor moves 0.833108 -> 0.799364 tCO2/t
# clinker (-4.05%); the 2025 clinker anchor and every other input are unchanged,
# so the budget scales by the same ratio and the relative constraint is intact.
# Previous values (2021-vintage fuel factors): cumulative 21,215,870.822368;
# 2025 reference 913,727.239222.
# 2026-09-12: re-based after the fuel-emission-factor re-anchor
# (SOURCE_FUEL_EF_REANCHOR_SCALE, capacity-weighted fleet thermal intensity
# -> 105.000 kgce/t clinker) AND the tier-compliance pass
# (SOURCE_EF_TIER_COMPLIANCE: 22 appended-batch lines + line id 2040 reassigned
# to the archived 4,200/2,000 tier rule, both parameters). The
# production-weighted BAU direct factor is 0.799426 tCO2/t clinker; the 2025
# clinker anchor and every other input are unchanged, so the budget scales with
# the reference and the relative constraint is intact. Historical values:
# 2021-vintage factors: cumulative 21,215,870.822368; 2025 913,727.239222.
# Post-re-anchor, pre-compliance: cumulative 20,356,541.751658; 2025 876,717.569153.
# Post-re-anchor + fuel-only single-point merge (superseded): cumulative
# 20,356,355.993467; 2025 876,709.568900.
REFERENCE_CUMULATIVE_BAU_KT_YEAR = 20_358_132.483207
REFERENCE_2025_DIRECT_EMISSIONS_KT = 876_786.078938
CARBON_BUDGET_CASE = "B40"
CARBON_BUDGET_CASES = {
    "B30": {
        "reference_reduction": 0.30,
        "cumulative_budget_kt_year": REFERENCE_CUMULATIVE_BAU_KT_YEAR * 0.70,
        "terminal_2060_cap_kt": REFERENCE_2025_DIRECT_EMISSIONS_KT * 0.20,
    },
    "B40": {
        "reference_reduction": 0.40,
        "cumulative_budget_kt_year": REFERENCE_CUMULATIVE_BAU_KT_YEAR * 0.60,
        "terminal_2060_cap_kt": REFERENCE_2025_DIRECT_EMISSIONS_KT * 0.10,
    },
    "B50": {
        "reference_reduction": 0.50,
        "cumulative_budget_kt_year": REFERENCE_CUMULATIVE_BAU_KT_YEAR * 0.50,
        "terminal_2060_cap_kt": REFERENCE_2025_DIRECT_EMISSIONS_KT * 0.02,
    },
}
VALID_CARBON_BUDGET_CASES = tuple(CARBON_BUDGET_CASES)


# Existing milestone targets retained as an option.
# Baseline = model's own t=0 (2025) sum(co2_net) — endogenous, v3-aligned
# (replaces deterministic baseline_u × cap × (proc_ef+fuel_ef) anchor that
# caused asymmetric comparison and made S1/S3 infeasible).
MILESTONE_2030 = 0.85   # ≤ 85% of 2025 baseline → −15%
MILESTONE_2050 = 0.30   # ≤ 30% of 2025 baseline → −70%
MILESTONE_2060 = 0.10   # ≤ 10% of 2025 baseline → −90%

# v3 used hard milestone constraints, with no milestone slack. Keep slack as an
# explicit diagnostic fallback only; main paper runs should leave it disabled.
MILESTONE_USE_SLACK = False

# Slack penalty for diagnostic soft-violation runs (CNY/tCO2). If enabled, this
# is applied to annual slack using the common trapezoidal period weights.
MILESTONE_SLACK_PENALTY = 5000.0

# ── National clinker-ratio path ────────────────────────────────────────
# The 2025 value is recalculated by the loader from observed provincial cement
# output and effective clinker ratios after a small feasibility correction.
BASELINE_CLINKER_RATIO = 0.647826
LCC_MIN_CLINKER_RATIO = 0.50
# P1-7: CLINKER_RATIO_PATH was removed here. It was never referenced by any
# module, so it could not affect results, but it duplicated the effective path in
# data/model_input/technology/external_technology_paths.csv (column
# clinker_ratio_central) and invited "I changed the config and nothing happened".
# The removed values are recorded in parameter_deduction.md (review P1-7) so the
# dead copy is preserved as documented provenance rather than as live-looking code.
# 2025: 0.647826, 2030: 0.633851, 2035: 0.619877, 2040: 0.605901,
# 2045: 0.591926, 2050: 0.577951, 2055: 0.563975, 2060: 0.550000

# ── Plant lifetime and same-site capacity renewal ──────────────────────────────
PLANT_LIFETIME_YEARS = 40
PLANT_DEFAULT_COMMISSION_YEAR = 2010
SAME_SITE_RENEWAL_MIN_CAPACITY_TD = 3200.0
SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY = 400.0
# Renewal window and count (2026-09-12; sensitivity withdrawn 2026-09-13).
# Central keeps the original behaviour: a line may renew at most once, and only in
# the FIRST period after its original 40-year expiry (further renewal periods are
# fixed to zero by same_site_renewal_eligibility). This is a strong friction that
# determines most of the 2060 spatial pattern.
# WITHDRAWN SENSITIVITY: "any_after_expiry" is NOT a valid sensitivity under the
# current state constraints. A line that exits (y goes 1->0) cannot return to
# operation, so a renewal placed in any period LATER than the first one after
# expiry is only reachable if the line produced continuously in the interim --
# which is exactly the state we are trying to vary. The mode therefore does not
# test what its name suggests. Testing it properly would require an explicit
# idle/mothballed state (a third state beside operating and permanently closed),
# which is out of scope for v5. The CLI value is retained only so that historical
# result files remain reproducible; the batch sensitivity has been removed.
SAME_SITE_RENEWAL_WINDOW = "first_after_expiry"   # | "any_after_expiry" (withdrawn)
SAME_SITE_RENEWAL_MAX_COUNT = 1                    # renewals per line over the horizon

# ── End-of-horizon robustness (2026-09-13) ────────────────────────────
# No terminal value is assigned to any asset, and the CCS minimum-operating
# commitment is enforced only inside the horizon. This is a CONVENTION, not an
# established direction of bias: assets built near 2060 are charged in full while
# their service is truncated (over-costing late investment), but the absence of any
# salvage value also removes the incentive to build late (under-costing the option
# to wait), and post-2060 commitments are simply unmodelled. The net sign is not
# asserted. To make the exposure measurable rather than argued, the results report
# the discounted spend on assets whose service is truncated inside this window.
TERMINAL_TRUNCATION_WINDOW_YEARS = 20

# P0-3 (2026-09-11; justification revised 2026-09-12 after the GPT utilization
# review). WHAT IT IS: the minimum annual activity level assumed for a line in the
# "retained and producing" state. It is NOT a kiln technical minimum load and it is
# NOT directly derived from the MIIT capacity-replacement rule. That rule ("<90
# operating days/yr for two consecutive years") governs REPLACEMENT ELIGIBILITY,
# not a mandatory operating floor; the earlier "90/300 = 30%" reading as a direct
# derivation is WITHDRAWN. Under the model's own 310-day design-capacity basis,
# 90 days = 90/310 = 29.03%, so 0.30 is the policy-consistent rounded value -- but
# it remains an ASSUMPTION (source grade: author judgement, calibrated), not a
# measurement of any kiln's minimum stable load.
# Central 0.30 (author decision 2026-09-12); sensitivity 0.20 / 0.30 / 0.40.
# Measured behaviour in the previous baseline: the floor was almost never binding
# (about 5 of 3,265 operating line-periods sat at the floor), so it shapes the
# feasible set rather than the central result. Note the interaction with the
# 310-day basis: because u <= 1, the days basis also sets each line's maximum
# annual output, so this parameter and DAYS_PER_YEAR are NOT cosmetic.
MIN_OPERATING_UTILIZATION = 0.30
# MAX_UTILIZATION_CHANGE_PER_PERIOD removed in P0-3: its role (blocking costless
# cross-period utilisation re-dispatch) is now carried by the fixed operating cost.
# Measured binding rate before removal: 21.5% (2030), 44.3% (2045), 62.2% (2050) of
# continuously-operating lines.

# Plant fixed annual operating cost (P0-3), charged per tonne of annual clinker
# capacity for every line in operation. This is what makes exit an economic choice.
#
# 2026-09-13 RECALIBRATION 53.2 -> 40. The 55 CNY/t build-up below is a FINANCIAL
# allocation of corporate fixed cost to capacity; what the model needs is the
# AVOIDABLE fixed resource cost of retiring one line, which is smaller, because
# part of the allocated cost does not disappear when a single line closes (group
# overhead, shared utilities, insurance/environmental obligations that continue).
# Re-derived item by item from the same build-up:
#   labour 30 -> 27 (keep 90%: some sales/HQ and cross-line-shared staff are not
#                     avoided by closing one line)
#   maintenance 18 -> 9 (about half is genuinely fixed upkeep; refractories, wear
#                     parts and the rest move with production and belong in the
#                     production cost, not here)
#   insurance 1 -> 1
#   environmental compliance 3 -> 2 (keep fixed monitoring/permits, drop the
#                     production-linked spend)
#   plant overhead 4 -> 2 (about half is avoidable at the single-line level)
#   sum 56 -> 41   (NOTE: the original itemisation actually sums to 56, not the 55
#                   written below -- a pre-existing arithmetic slip, recorded here)
# Converted to the model's 310-day capacity basis: 41 x 300/310 = 39.68 -> 40
# (rounded; a false precision of 39.68 is not supported because the underlying
# report capacity denominators were never re-verified line by line).
# The 90%/50% avoidable shares are TRANSPARENT CALIBRATION ASSUMPTIONS, not
# reported figures, and must be declared as such (grade D).
# Direction: a LOWER avoidable cost weakens the incentive to concentrate
# production and therefore favours retaining more capacity. It does NOT follow
# that utilisation must land in any particular band.
# Sensitivity 32 / 40 / 53.2 (old value retained as the upper bound).
# See v5/parameters/fixed_cost_transport_recalibration_20260913.md.
PLANT_FIXED_OPERATING_COST = 40.0

# Early-retirement cost (P0-3), rescoped to the PHYSICAL RESOURCE cost of closure.
# The model is a social-planner resource-cost model, so the undepreciated book value
# of a line is an accounting writedown, not a resource cost, and is excluded.
# Component build-up (2024 price level): worker resettlement +28 (劳动合同法 §47 plus
# annual-report wage data; no Chinese per-plant figure exists) + soil investigation +3
# (土壤污染防治法 §59/§67: cement is NOT on the mandatory-remediation list; the only
# Chinese cement case found was investigation-only) + demolition and clearance NET
# RECOVERY -20 (every observed "整体拆除外售" transaction has the SELLER receiving cash
# and the BUYER bearing demolition/transport/disposal; measured 15.0 and 26.0 CNY/t)
# + mine-fund top-up / permits / hazardous waste +6 = +17 CNY/t.
# Sensitivity -4 / +17 / +78.
# Excluded from the central objective as transfers outside the model boundary
# (same_site_capacity_renewal_definition.md excludes cross-region quota trading):
# capacity-replacement quota receipt -54, industrial land residual -10.
# NOTE: this cannot balance PLANT_FIXED_OPERATING_COST — its absolute value is 1-2
# orders of magnitude smaller than the fixed cost's present value. The only correct
# counterweight is regional demand and transport cost (see
# v5/parameters/regional_demand_transport_20260911.md, pending decision).
EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY = 17.0

# ── Change 3 (2026-09-12): capacity-retirement pace, VALIDATION ONLY ─────
# Reality check on the model's own contraction path: Chinese cement capacity fell
# roughly 5-10% per year over 2016-2020, while the central v5 solve retires about
# half of the fleet within the first five-year period. This is a policy
# feasibility screen, not a central-setting constraint. The diagnostic below is
# always reported (active capacity by period, annualised decline rate, and
# whether each period sits inside the observed band). Set
# MAX_ANNUAL_CAPACITY_DECLINE to a number to ADD the constraint for a dedicated
# validation run only; None keeps the central model unconstrained.
CAPACITY_DECLINE_REFERENCE_ANNUAL = (0.05, 0.10)   # observed 2016-2020 policy band
MAX_ANNUAL_CAPACITY_DECLINE = None                 # None = central (unconstrained)

# ── Change 3b (2026-09-13): PER-PERIOD (five-year) decline cap ───────────
# Requested because MAX_ANNUAL_CAPACITY_DECLINE is easy to misuse: entering 0.10
# there means 10%/yr, i.e. a 41% fall over one five-year period, when the intended
# "10% every five years" policy reading is a 2.09%/yr equivalent. This parameter
# takes the FIVE-YEAR fraction directly and is applied as
#   sum_i cap_i*y[i,t] >= (1 - MAX_CAPACITY_DECLINE_PER_PERIOD) * sum_i cap_i*y[i,t-1]
# so there is no annualisation to get wrong. None = central (unconstrained).
# This is the *slow-exit institutional-friction scenario*, NOT a central setting:
# by construction it forces idle capacity to be retained, so a low utilisation
# becomes a consequence of the constraint rather than a model finding.
# 10%/5yr = 0.0208516/yr equivalent. Sensitivity 0.10 / 0.20 / 0.30 (per 5 years).
MAX_CAPACITY_DECLINE_PER_PERIOD = None

# ── Production unit conversion ─────────────────────────────────────────
# P0-3: unified to 310 days, matching the fleet-build scripts
# (build_plant_fleet_2025.py / fuse_plant_databases.py). The register previously
# said 365 and the model used 330 — a three-way inconsistency. Capacity base:
# 5,812,755 t/d x 310 = 1,802.0 Mt/yr (was 1,918.2 at 330 d). The 2025 base-year
# utilisation becomes 1,096.769/1,801.954 = 0.609 (was 0.572), closer to the
# observed 59% (2023) / 53% (2024). Note the MIIT policy itself uses 300 days, so a
# 3.3% gap remains when comparing with policy documents directly.
DAYS_PER_YEAR = 310
CAPACITY_T_DAY_TO_KT_YR = DAYS_PER_YEAR / 1000.0

# ── Plant fuel-emission-intensity re-anchor (2026-09-12) ────────────────
# The 2021 source workbook (1_source_cement.xlsx) carries fuel emission factors
# as three size-class constants (L1>=4000 t/d: 0.302950, L2 2000-4000: 0.327260,
# L3<2000: 0.356900 tCO2/t clinker; one plant-specific outlier 0.315105). Their
# capacity-weighted thermal intensity over the active 1,572-line fleet is
# 117.695 kgce/t clinker (at the Zhang et al. 2021 Table A.2 coal factor
# 2.6604 tCO2/tce), i.e. at the TOP of the CBMA (2023) national-average band
# (0.290-0.317 tCO2/t clinker = 107-117 kgce/t) and above what the >=4000 t/d
# class can physically carry under GB 16780-2021 by 2025 (comprehensive-energy
# limit 117 kgce/t; benchmark 100).
# Re-anchoring (author decision, option "thermal 105"): the loader scales the
# workbook fuel factors uniformly by the constant below so that the
# capacity-weighted thermal intensity of the active fleet equals
# TCE_PER_T_CLINKER x 1000 = 105.0 kgce/t clinker. This simultaneously
#   (a) updates the energy baseline to the 2025 fleet that the 1,572-line
#       plant database already represents,
#   (b) closes the 12% inconsistency between the emission side (fuel_ef) and
#       the AF energy side (TCE_PER_T_CLINKER),
#   (c) puts L1 at comprehensive ~108.7 and L2 at ~116.8 kgce/t (both within
#       the GB 16780-2021 limit of 117; L3, 6% of capacity, stays above as the
#       legacy small-kiln stock slated for exit).
# The workbook itself is NOT edited (source integrity + SHA-256 manifest
# unaffected); process and electricity factors are untouched; the EE path
# applies multiplicatively and needs no recalibration. The frozen carbon-budget
# references (REFERENCE_CUMULATIVE_BAU_KT_YEAR / REFERENCE_2025_DIRECT_EMISSIONS_KT)
# were re-based to the re-anchored factors on 2026-09-12 -- see
# v5/parameters/fuel_ef_reanchor_20260912.md. Uniform scaling preserves the
# class structure and every plant's relative fuel intensity.
SOURCE_FUEL_EF_REANCHOR_SCALE = 0.89299372

# ── Source-sink matching ─────────────────────────────────────────────────
TRANSPORT_MAX_KM = 500.0
NEAREST_SINKS_PER_PLANT = 8
NEAREST_SINKS_PER_TYPE = 3
HIGH_CAPACITY_SINKS_PER_PLANT = 2
STORAGE_MT_TO_KT = 1000.0
STORAGE_CUMULATIVE_SCALE = 1.0
STORAGE_RATE_SCALE = 1.0
# The available DSA rate raster is a theoretical maximum, not a defensible
# engineering limit. Cumulative capacity remains binding; annual-rate limits
# are re-enabled only after a weighted-average or conservative dataset exists.
# P1-3: enabled. Fan et al. (2025) warn that omitting injection-rate capacity
# overestimates what can be stored, and two Chinese studies at the same 40 km
# resolution impose a rate constraint. The available raster is however a per-well
# per-5-km-cell theoretical MAXIMUM (their Eq. 8, with drawdown capped at 50% of
# hydrostatic) that this pipeline SUMMED onto 40 km nodes, so it is
# non-conservative on two counts. It is therefore capped by a transparent physical
# bounds: a well-count cap (50 wells x 0.7 Mt/yr, the convention in the two
# Chinese studies at this resolution) and a depletion cap (capacity / 30 yr).
# Remaining upgrade (not done, needs the weighted-average raster from
# figshare 10.6084/m9.figshare.27646707): rebuild with Fan's own aggregation rule
# (county = max, province = mean of counties; never summed).
USE_STORAGE_RATE_CONSTRAINT = True
STORAGE_RATE_DEPLETION_YEARS = 30.0
# P1-3: injection-point (well) cap. A 40 km node holds many potential 5 km
# injection points, so the summed rate is not wrong per se -- what is missing is
# a well-count limit. The two Chinese studies that impose a rate constraint at
# this exact 40 km resolution use a cap of 50 injection wells per site
# (Wang et al. 2025, iScience 28:113315; Fan/Zhang 2024, iScience 27:110978),
# combined here with the Ringrose et al. (2019) single-well mean of 0.7 Mt/yr.
# The three terms (raw raster, well cap, depletion cap) bind for roughly equal
# shares of nodes, so no single one dominates.
STORAGE_MAX_WELLS_PER_NODE = 50
STORAGE_RATE_PER_WELL_MT_YR = 0.7

# P1-3: minimum storage node capacity. Nodes below this cannot host a normal
# project (one 0.7 Mt/yr well over a 25-30 year life needs ~17-20 Mt) and small
# raster cells were being filled to exactly 100%, i.e. a grid-resolution artifact
# rather than an engineering constraint. US DOE CarbonSAFE uses 50 Mt as its
# commercial-scale definition; 10 Mt is the permissive engineering floor, and the
# nodes it removes carry well under 1% of national capacity.
STORAGE_MIN_NODE_CAPACITY_MT = 10.0

# ── Dispatch fuel cost (Change 1, 2026-09-12) ─────────────────────────────
# The objective previously contained NO cost that varies with output: the full
# fuel bill was excluded (INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE=False) and the AF
# fuel differential is zero at price parity (AF_FUEL_PRICE == COAL_PRICE_SCHEDULE).
# So producing one more tonne from an already-open line was free, which forces
# u -> 1 and makes fleet size a mechanical consequence of F. This block prices
# the fuel bill so dispatch and retention respond to plant-level energy intensity.
#
# DEVIATION FORM, and why it is exact: for any constant ef_mean,
#     Sum_i ef_i * cap_i * u_i  ==  ef_mean * Sum_i cap_i * u_i
#                                  + Sum_i (ef_i - ef_mean) * cap_i * u_i
# and Sum_i cap_i * u_i == national clinker demand D_t is an EQUALITY in this
# model, so the first term is a KNOWN CONSTANT given the demand path. Charging
# only the deviation therefore yields the SAME optimal solution as charging the
# full bill, while leaving the reported cost level comparable to v4 (the full
# discounted bill is ~1,058 bn CNY, the same order as the entire mitigation
# cost, and including it would roughly double the headline).
# Consequence worth stating in the SI: for any two runs with the SAME demand
# path, the omitted mean term cancels exactly in every reported difference
# (planning regret, scenario cost gaps). It does NOT cancel across demand
# scenarios, where the omitted term scales with D_t.
INCLUDE_DISPATCH_FUEL_COST = True
# Physical conversion CO2 <-> standard-coal energy for the dispatch fuel bill.
# 2026-09-12 (author ruling, single-factor): the registered anchor is Zhang et
# al. (2021) Table A.2, coal = 2.6604 tCO2/tce (= 90.78 kgCO2/GJ, consistent
# with China's provincial GHG-inventory raw-coal factor) -- the same A-level
# table as the AF/ARM/EE cost anchors and the basis of the fleet re-anchor
# (weighted thermal intensity = 105.000 kgce/t clinker) and of the CBMA band
# comparison. The IPCC bituminous default (94.6 kgCO2/GJ = 2.773 tCO2/tce) is a
# declared +/-4.2% uncertainty on fuel-side CO2<->energy conversions, reported
# in the SI -- it must NOT run as a second parallel factor in the code.
COAL_EF_TCO2_PER_TCE = 2.6604

# ── Plant source emission-factor tier compliance (2026-09-12) ─────────────
# The source workbook assigns emission factors by CAPACITY TIER per the archived
# formulation (archive/docs/MODEL_FORMULATION_COMPLETE.md §三-3.1 "排放等级定义"):
#     tier 1  >= 4,200 t/d   proc 0.522020  fuel 0.302950   (697 lines)
#     tier 2  2,000-4,200    proc 0.517410  fuel 0.327260   (850 lines)
#     tier 3  < 2,000 t/d    proc 0.520120  fuel 0.356900   (114 lines)
# Measured compliance with the archived rule (current capacity, 4,200/2,000
# cuts): 99.0% of the 1,662 rows. The 1,618 original rows are 100% compliant;
# 22 of the 44 appended-batch rows (id >= 2,000, commissioned 2021-2025) deviate
# in one or both parameters -- mostly tier-2 factors on tier-1-scale lines
# (e.g. id 2005, 8,000 t/d, carries 0.327260/0.517410). Line id 2040 (Shaanxi
# Shengwei, 4,500 t/d, 2025) carries values that are the EXACT midpoints of
# tiers 1 and 2 in BOTH parameters ((0.302950+0.327260)/2 and
# (0.522020+0.517410)/2) -- an interpolated fill, not a measurement.
# SOURCE_EF_TIER_COMPLIANCE reassigns BOTH parameters of every deviating line
# to its archived-tier values (workbook untouched; every reassignment logged).
# The earlier "tiers carry information beyond size" reading (87.0% agreement
# under a guessed 4,000/1,800 cut) was a cut-point error and is withdrawn;
# 4,000-4,200 t/d lines holding tier-2 factors are CORRECT under the 4,200 cut.
# Superseded constant (provenance, parameter_deduction.md):
# SOURCE_FUEL_EF_TIER_MERGE = {0.315105: 0.302950} -- a fuel-only single-point
# merge that left the line's interpolated process factor in place; superseded
# by the general rule below.
SOURCE_EF_TIER_COMPLIANCE = True
SOURCE_EF_TIER_RULE = {
    "cut_t1": 4200.0,  # t/d, >= cut -> tier 1
    "cut_t2": 2000.0,  # t/d, >= cut and < cut_t1 -> tier 2; below -> tier 3
    "tiers": {
        1: {"proc": 0.522020, "fuel": 0.302950},
        2: {"proc": 0.517410, "fuel": 0.327260},
        3: {"proc": 0.520120, "fuel": 0.356900},
    },
}

# ── Regional demand and clinker transport (P0-4 / v3: distributed market nodes) ─
# Derivation and the change of spatial unit: v5/parameters/regional_demand_transport_20260911.md
# and the MarketNodeLayer-v1 entry in v5/parameters/parameter_deduction.md.
#
# Why a demand layer at all: with a single national balance, clinker is perfectly
# fungible and any plant can serve the whole country at zero cost. Once the fixed
# operating cost makes fleet size an economic decision, that assumption -- not the
# economics -- drives which lines survive (first v5 solve: 1,572 -> 326 lines by
# 2060, fleet-wide u ~ 1.00).
#
# Why DISTRIBUTED MARKET NODES (~150) and not the province (2026-09-12, v3):
#   (a) The province could not produce an endogenous utilization: with one market
#       point per province, dropping a distant plant inside a province leaves the
#       retained plants' distance to that province's centroid unchanged, so there
#       is no force that raises marginal cost with concentration and u sits at its
#       upper bound (measured 0.995). Equal-cost plants inside a province also
#       compete only on fuel access, storage distance and scale.
#   (b) The 1,713-node 50 km grid is not the answer either: its equality balances
#       require an exact bipartite b-matching and were structurally infeasible
#       (an exact float LP left a shortfall in every period, 10.69% of national
#       clinker in 2025), and its market gradient is a plant-level selector that
#       competes with the resource conditions this study identifies.
#   (c) ~150 nodes is the middle resolution: ~5 per province, i.e. the 50 km layer
#       aggregated to roughly 150 km. Node demand (~7 Mt/yr) is large relative to
#       a plant, so the equal-cost collapse of (a) cannot recur, while the node
#       count is small enough that the balance stays feasible and the arc set
#       stays modest. See DEMAND_MARKET_NODE_TARGET.
#   (d) The corridor evidence we validate against (Guangxi->Guangdong,
#       Anhui->Jiangsu/Zhejiang, Northeast->East) is still reported at the
#       province level; market nodes aggregate cleanly to it.
ENABLE_REGIONAL_DEMAND = True
DEMAND_MARKET_UNIT = "market_node"       # "market_node" (active)

# Market-node geography and the adaptive candidate-arc set, both built by
# v5/model/preprocessing/build_market_nodes.py.
DEMAND_MARKET_NODE_TARGET = 150          # clusters, allocated per province by 2025 demand share (floor 1)
DEMAND_MARKET_NODE_FILE = V5_DATA / "demand_market_nodes.csv"
DEMAND_MARKET_ARC_FILE = V5_DATA / "demand_market_arcs.csv"

# Adaptive arc construction (design doc §3.3, v3). A fixed nearest-K rule is
# deliberately not used: the radius a fixed K covers shrinks with resolution, so
# the arc set is grown by coverage rules and then made Hall-feasible by exact
# min-cut augmentation. Measured outcome: ~20,200 arcs, median 13 candidates per
# plant, zero 2025 gap, ~162k continuous f_dem variables and no new binaries.
DEMAND_ARC_SEED_NEAREST = 3              # seed arcs: nearest nodes per plant
DEMAND_ARC_NODE_COVERAGE = 1.5           # connected capacity >= 1.5 x node demand
DEMAND_ARC_PLANT_COVERAGE = 1.0          # candidate demand >= 1.0 x plant capacity
DEMAND_ARC_TOP_NATIONAL_NODES = 10       # long-distance corridor access (water / rail)
DEMAND_ARC_MAX_DISTANCE_KM = 1200.0      # no arc beyond this distance
DEMAND_ARC_OWN_PROVINCE = True           # every plant reaches every node in its province
DEMAND_ARC_MIN_CUT_ADD_PER_ROUND = 5     # spare-capacity plants added per starved node
DEMAND_ARC_FEASIBILITY_TOL_KT = 2.0      # exact 2025 Hall gap accepted (rounding noise)

# Demand-node geography (DESCRIPTIVE ONLY, not in the optimization). This layer
# supplies (i) the 50 km population shape that positions the market nodes, (ii)
# the 65/35 between/within-province variance evidence, and (iii) figures.
DEMAND_NODE_FILE = V5_DATA / "demand_nodes.csv"
DEMAND_NODE_LAYER_USED_IN_OPTIMIZATION = False

# Two-level allocation: province totals from official statistics (cement output
# x effective clinker ratio), within-province shape from the population raster.
# Using statistics for the level keeps the baseyear anchor in
# build_baseyear_plant_utilization consistent and preserves the known net-import
# provinces. National statistics list 30 provinces; the reported 2025 output
# fills Shanghai (same statistical series).
DEMAND_PROVINCE_OUTPUT_OVERRIDE = {"上海": 325.73}   # in cement_output_2025.csv units (10 kt)
# Shanghai is also absent from the Liao et al. baseline, so its effective clinker
# ratio uses the grinding-type benchmark (Jiangsu, Zhejiang and Tianjin all sit at
# 0.45 there), matching Shanghai's role as a blending/grinding municipality.
# Shanghai is 0.19% of national cement output, so this is not material.
DEMAND_PROVINCE_RATIO_FALLBACK = 0.45

# Future provincial shares: 2025 shares held constant (same convention as
# Wang et al. 2026, whose ProvinceRatio is time-invariant). Du et al. (2019) show
# provincial peaks are staggered, so this is a declared assumption and converging
# partway to population shares is the sensitivity that tests it.
DEMAND_PROVINCIAL_SHARE_CONVERGENCE = 0.0    # 0.0 central; 0.5 sensitivity

# Clinker transport cost, distance-segmented and anchored on observed market radii
# (sources in the design doc 3.2): road <=200 km, rail 200-600 km, water/rail-sea
# beyond. Distance is a parameter, so segmentation introduces no non-convexity.
# Intra-province arcs now carry the REAL plant->node haversine distance (the v2
# "intra-province transport is zero" rule is retired): that distance is the
# endogenous average-haul force this layer exists to create.
DEMAND_TRANSPORT_MODE = "segmented"          # "segmented" | "uniform" | "zero"
# 2026-09-13 RECALIBRATION of the SHORT-HAUL rate only: 0.45 -> 0.55.
# What this rate is: a PROXY for the market-service cost of serving a demand node,
# not a national average road-freight invoice. Evidence for the 0.45-0.65 band:
# Gansu cement road 0.56 (excl. loading/unloading), Yunnan 0.65 (incl. handling and
# tolls), Zhejiang 2023 official construction-material price schedule 0.60 ex-VAT /
# 0.65 incl. VAT (>=25 km), MOT survey 0.40-0.60. 0.55 is the MIDPOINT OF THE BAND
# chosen against an external reference, NOT a statistical mean of heterogeneous
# quotes, and must not be presented as a national constant-price freight rate.
# Why not just take the top of the band (0.65): part of the spread is tax basis,
# region and commodity caliber, and the proxy already excludes handling/toll add-ons
# (which are NOT stacked on top, to avoid double counting).
# The 200-600 km (0.12) and >600 km (0.05) rates are deliberately NOT raised: no
# evidence requires it, and scaling the whole chain would conflate a short-haul
# calibration with a global cost inflation.
# Cumulative-rate consequence (CNY/t delivered): 50 km 22.5->27.5, 100 km 45->55,
# 200 km 90->110, 600 km 138->158, 1,000 km 158->178.
# Direction: a higher short-haul rate penalises long-distance centralised supply and
# therefore favours retaining more local capacity. It does not guarantee any
# particular utilisation level.
# Sensitivity 0.45 / 0.55 / 0.65 (0.45 retained as the lower bound, 0.65 upper).
# See v5/parameters/fixed_cost_transport_recalibration_20260913.md.
DEMAND_TRANSPORT_COST_SEGMENTS = (
    (200.0, 0.55),            # CNY per t-km; road (observed road market radius <=200 km)
    (600.0, 0.12),            # rail
    (float("inf"), 0.05),     # water / rail-sea
)
# Uniform alternative for direct comparison with Wang et al. (2026) tc_cement = 0.2.
DEMAND_TRANSPORT_COST_UNIFORM = 0.20


# ── Production closure ──────────────────────────────────────────────────
BASE_YEAR = 2025

# ── Carbon price ─────────────────────────────────────────────────────────
CARBON_PRICE = {
    2025: 80,  2030: 120, 2035: 180, 2040: 250,
    2045: 320, 2050: 400, 2055: 450, 2060: 500,
}

# ── Discount rate ─────────────────────────────────────────────────────────
DISCOUNT_RATE = 0.05

# ── Solver ───────────────────────────────────────────────────────────────
SOLVER = "gurobi"
SOLVER_OPTIONS = {"MIPGap": 0.01, "Threads": 4, "TimeLimit": 300}
SOLVER_PROFILES = {
    # 2026-09-13, pre-final screening tier (author policy: before the definitive
    # runs, gaps of a few percent are acceptable). Distinct from "explore" because
    # the NoRel warm-up is shortened: at a 3% target, spending 400-600 s of
    # no-relaxation search to reach a gap we do not need is pure waste. Use this for
    # scenario screening, asset-set questions and mechanism checks -- NOT for any
    # number that goes in the paper, and NOT for the two runs whose difference is
    # the commitment cost (their gap bands add; see report_planning_loss.py).
    "screen": {
        "MIPGap": 0.03,
        "TimeLimit": 2400,
        "Threads": 8,
        "MIPFocus": 1,
        "Heuristics": 0.25,
        # 400 s, NOT 150. The warm-up length and the gap target are independent
        # knobs, and cutting the warm-up was a mistake: measured on the layer-2
        # batch, a 150 s warm-up produced NO solution for a harder instance, which
        # then ran 4,740 branch-and-bound nodes with no incumbent and would have hit
        # the time limit having written nothing. central_J's single solution came
        # from this heuristic (log: "Solution count 1" at node 1), so the warm-up is
        # what sets feasibility, not the gap target.
        "NoRelHeurTime": 400,
        "Presolve": 2,
        "Cuts": 1,
        "PreSparsify": 1,
        "NodefileStart": 0.5,
    },
    # Fast screening: prioritize feasible, mechanism-level solutions.
    "explore": {
        "MIPGap": 0.06,
        "TimeLimit": 1800,
        "Threads": 8,
        "MIPFocus": 1,
        "Heuristics": 0.25,
        # The distributed market-node layer makes the root LP degenerate and the
        # incumbent search the bottleneck: measured, the default heuristics found
        # NO incumbent in ~8 min, while Gurobi's no-relaxation heuristic produced
        # one at ~280 s. The warm-up is therefore part of the profile.
        "NoRelHeurTime": 400,
        "Presolve": 2,
        "Cuts": 1,
        "PreSparsify": 1,
        "NodefileStart": 0.5,
    },
    # Publication runs: paper-quality gap with emphasis on bound improvement.
    "final": {
        "MIPGap": 0.02,
        "TimeLimit": 7200,
        "Threads": 8,
        "MIPFocus": 2,
        "Heuristics": 0.10,
        # See the explore note: without this the market-node model can spend hours
        # with no incumbent and save only {"status": ...} at the time limit.
        "NoRelHeurTime": 600,
        "Presolve": 2,
        "Cuts": -1,
        "PreSparsify": 1,
        "NodefileStart": 0.5,
        "NumericFocus": 0,
    },
}



class Config:
    """Container for all config parameters — passed to V4Model."""

    def __init__(self):
        import sys as _sys
        _mod = _sys.modules[self.__module__]
        for _name in dir(_mod):
            if _name.isupper():
                setattr(self, _name, getattr(_mod, _name))


config = Config()
