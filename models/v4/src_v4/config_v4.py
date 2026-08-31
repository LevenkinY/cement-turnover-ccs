"""
Configuration file for v4 model.
Flat parameter structure — no nested classes.
v3 CCS parameters fully migrated (Phase A+B+C).
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_INPUT = PROJECT_ROOT / "data" / "model_input"
DATA_RAW = PROJECT_ROOT / "data" / "raw"

# ── Time ────────────────────────────────────────────────────────────────
T_LIST = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
YEARS = {t: i for i, t in enumerate(T_LIST)}
T_IDX = {i: t for t, i in YEARS.items()}
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
RESULTS_DIR = PROJECT_ROOT / "results" / "v4" / "results_v4"

# ── Catchment radii (km) ────────────────────────────────────────────────
MSW_RADIUS_KM = 50.0
BIO_RADIUS_KM = 150.0

# ── AF engineering ceiling ─────────────────────────────────────────────
# A common engineering maturity path avoids duplicating plant catchment
# heterogeneity with an administrative-name tier. The path is the
# capacity-weighted envelope of the previously used tier assumptions.
AF_ENGINEERING_TSR_PATH = {
    2025: 0.221779,
    2030: 0.221779,
    2035: 0.278395,
    2040: 0.348374,
    2045: 0.416339,
    2050: 0.489800,
    2055: 0.563718,
    2060: 0.630774,
}

# Retained only for descriptive backward compatibility. The final model does
# not use location tiers as plant constraints.
TIER_TSR_CEILING = {
    "metro": 0.35,
    "city": 0.22,
    "county": 0.10,
    "remote": 0.05,
}

# Long-run AF technical envelope. The province/plant resource constraints still
# bind actual use; these values only prevent the old static tier caps from
# mechanically blocking mature 2050-2060 TSR levels documented in sector
# roadmaps and project guidelines.
TIER_TSR_CEILING_BY_YEAR = {
    2025: {"metro": 0.35, "city": 0.22, "county": 0.10, "remote": 0.05},
    2030: {"metro": 0.35, "city": 0.22, "county": 0.10, "remote": 0.05},
    2035: {"metro": 0.40, "city": 0.28, "county": 0.15, "remote": 0.08},
    2040: {"metro": 0.48, "city": 0.35, "county": 0.22, "remote": 0.12},
    2045: {"metro": 0.55, "city": 0.42, "county": 0.28, "remote": 0.16},
    2050: {"metro": 0.60, "city": 0.50, "county": 0.35, "remote": 0.20},
    2055: {"metro": 0.65, "city": 0.58, "county": 0.42, "remote": 0.25},
    2060: {"metro": 0.70, "city": 0.65, "county": 0.50, "remote": 0.30},
}

# ── AF supply caps (fraction of plant fuel demand) ────────────────────
AF_MAX_PER_PLANT = 0.70  # plant-level hard cap

# AF fossil CO2 reduction coefficient.
# Aligned to the current v3 source:
# src/config.py::AF_MIX_PROPERTIES['fossil_co2_reduction'] = 0.55.
BETA_AF = 0.55

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
    'capture_investment': 739,      # CNY/(tCO2·yr) — was 250 in v4 (severely underestimated)
    'capture_om': 445,              # CNY/tCO2 — was 40 in v4 (severely underestimated)
    'min_active_design_kt': 30.0,   # ktCO2/yr; minimum nonzero design increment
    'utilization_penalty_rate': 0.0,
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
    'eor_revenue': 80,              # CNY/tCO2 — conservative national average

    # Threshold — aligned with CCS_ROLLOUT_PARAMS gate (4000/3200 t/d from 2030/2035)
    # Using 3200 as consistent minimum; actual deployment gate controlled by rollout params
    'min_capacity': 3200,           # t/d — aligned with size gate
}

# CCS design stock must be backed by actual capture after the observed 2025
# demo period. This keeps endogenous learning tied to used capacity, while
# allowing base-year pilots to remain observed installations.
CCS_MIN_CAPTURE_LOAD = 0.20

# Commercial CCS additions must remain in operation for at least 15 years.
# This is aligned with the China cement retrofit screen in Mao et al. (2025),
# which requires at least 15 years of remaining plant life and uses a 15-year
# payback period. Commitments extending beyond the 2060 model horizon are
# treated as continuing after 2060; the plant must remain active through 2060.
CCS_MIN_OPERATING_YEARS = 15
CCS_TERMINAL_COMMITMENT_MODE = "continue_beyond_horizon"

# Observed pre-2025 cement capture pilots are retained as deployment context
# and learning seeds. They are excluded from the carbon target unless project-
# level evidence verifies durable storage or mineralization.
OBSERVED_PILOT_CCS_ENABLED = True
OBSERVED_PILOT_CCS_INCLUDE_IN_TARGET_ACCOUNTING = False
OBSERVED_PILOT_CCS_PERSISTENCE = "base_year_only"  # options: base_year_only, installed_year_onward
OBSERVED_PILOT_CCS_COST_IN_OBJECTIVE = False

# ── Offshore parameters (migrated from v3) ─────────────────────────────
# Source: Mao et al. (2025) Table 3 footnote; GCCSI 2025
OFFSHORE_PARAMS = {
    'pipeline_cost_factor': 1.55,   # 海上 vs 陆上管道成本倍率
    'storage_cost_factor': 3.00,     # 海上储存成本倍率（更复杂的海床基础设施）
}

# ── CCS scale limits (时变捕集规模上限, migrated from v3) ──────────────
# Replaces v4's dumb 100 kt min/max block constraints
# CBMA 2023; CCUS 报告趋势
CCS_SCALE_LIMITS = {
    2025: 0.10,   # 示范阶段：≤10%排放
    2030: 0.25,   # 规模化初期：≤25%排放
    2035: 0.50,   # 快速扩张：≤50%排放
    2040: 0.75,   # 规模化：≤75%排放
    2045: 0.90,   # 深度脱碳：≤90%排放
    2050: 0.95,   # 成熟阶段：≤95%排放
    2055: 0.95,
    2060: 0.95,
}

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

# ── CCS learning curve (外生成熟, migrated from v3) ───────────────────
# Source: IEA 2021; GCCA 2025
# A2 终校（2026-08-11）：改为与 parameter_deduction.md §2.1b 一致的文档化路径
#（CAPEX 1.00→0.75、OM 1.00→0.80，八期线性插值；2030 年前降幅温和，符合
# GCCA 2025“2030 前仍为早期商业化”的校准说明）。原代码值（2060 年 0.93/0.965，
# 自称同一来源但无任何文档论证）保留为投稿前稳健性包的高成本敏感性档：
# investment: 2030 0.99 ... 2060 0.93；om: 2030 0.995 ... 2060 0.965。
CCS_LEARNING_CURVE = {
    'investment_multiplier': {
        2025: 1.00, 2030: 0.964, 2035: 0.929, 2040: 0.893,
        2045: 0.857, 2050: 0.821, 2055: 0.786, 2060: 0.75,
    },
    'om_multiplier': {
        2025: 1.00, 2030: 0.971, 2035: 0.943, 2040: 0.914,
        2045: 0.886, 2050: 0.857, 2055: 0.829, 2060: 0.80,
    },
}

# ── CCS cost scaling (内生经验+规模效应, migrated from v3) ────────────
# Source: IEA 2021; Brevik CCS 2025; 本模型观测41万t/yr示范项目
CCS_COST_SCALING_PARAMS = {
    'mode': 'exogenous_maturity_static_plant_scale',
    'enable_endogenous_learning': False,
    'enable_plant_size_scaling': True,
    # O&M is only partly learnable because energy, reagents, and labor have
    # physical/input-price floors. Apply 40% of the CAPEX stage learning effect.
    'apply_endogenous_learning_to_om': True,
    'om_learning_pass_through': 0.40,
    'seed_from_observed_projects': True,
    'experience_seed_10kt_per_year': 41.0,   # ~41万t/yr from corrected observed demo projects
    'experience_stages': [
        {'name': 'pilot',             'lower_bound': 0.0,    'upper_bound': 50.0,    'multiplier': 1.00},
        {'name': 'early_commercial',  'lower_bound': 50.0,   'upper_bound': 200.0,   'multiplier': 0.95},
        {'name': 'first_wave',         'lower_bound': 200.0,  'upper_bound': 1000.0,  'multiplier': 0.90},
        {'name': 'network_buildout',   'lower_bound': 1000.0, 'upper_bound': 5000.0,  'multiplier': 0.85},
        {'name': 'industrial_scaleup','lower_bound': 5000.0, 'upper_bound': 15000.0, 'multiplier': 0.80},
        {'name': 'mature_rollout',    'lower_bound': 15000.0,'upper_bound': None,    'multiplier': 0.75},
    ],
    'plant_size_classes': [
        {'name': 'small_ccs_unit',     'max_10kt': 90.0,  'multiplier': 1.08},
        {'name': 'mid_ccs_unit',       'max_10kt': 140.0, 'multiplier': 1.00},
        {'name': 'large_ccs_unit',     'max_10kt': 200.0, 'multiplier': 0.93},
        {'name': 'very_large_ccs_unit', 'max_10kt': None, 'multiplier': 0.88},
    ],
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

# ── Source clustering parameters (Phase C) ─────────────────────────────
# Source: Wang et al. 2025 supplemental
CLUSTER_PARAMS = {
    'enable_source_clustering': True,
    'optics_min_samples': 3,
    'optics_min_cluster_size': 4,
    'optics_xi': 0.035,
    'max_cluster_radius_km': 250,
    'hub_selection_method': 'min_total_distance',
}

# ── Cost boundary ───────────────────────────────────────────────────────
# Default paper objective: incremental real mitigation resource cost.
# Full baseline coal expenditure and carbon-price payments are retained as
# diagnostics, and can be included for accounting/policy variants.
COST_BOUNDARY = "incremental_mitigation"  # options: incremental_mitigation, full_accounting
INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE = False
INCLUDE_CARBON_COST_IN_OBJECTIVE = False

# ── AF fuel price (CNY/tce) — v3 aligned trajectory ──────────────────
# Coal enters the default objective only through AF substitution economics:
# (AF_FUEL_PRICE[year] - COAL_PRICE_SCHEDULE[year]) × displaced coal.
AF_FUEL_PRICE = {
    2025: 640, 2030: 680, 2035: 700, 2040: 720,
    2045: 740, 2050: 760, 2055: 800, 2060: 840,
}
COAL_PRICE_SCHEDULE = {
    2025: 707, 2030: 760, 2035: 800, 2040: 850,
    2045: 900, 2050: 950, 2055: 1000, 2060: 1050,
}
COAL_PRICE = 1000.0  # CNY/tce legacy fallback if a year is absent

# ── AF resource accounting (ktce/yr) ───────────────────────────────────
TCE_PER_T_CLINKER = 0.105
# Modeled operable baseline for the optimization horizon, not a strict
# statistical estimate of the current national TSR.
INITIAL_AF_RATE = 0.05
AF_INVESTMENT = 150.0  # CNY/t annual clinker capacity, includes pretreatment/logistics
AF_OM = 18.0           # CNY/t clinker using AF, central conservative setting
GJ_PER_TCE = 29.3076
BIOMASS_LHV_GJ_PER_TONNE = 20.0
BIOMASS_TCE_PER_KT = BIOMASS_LHV_GJ_PER_TONNE / GJ_PER_TCE
MSW_TCE_PER_KT = 0.12
AF_BIOMASS_POOL_COLUMN = "bio_supply_ej_access_base"
AF_WASTE_POOL_COLUMN = "residual_kt_access_base"
AF_WASTE_POOL_HIGH_COLUMN = "residual_kt_access_high"
AF_WASTE_REFERENCE_YEAR = 2018
AF_WASTE_ACCESS_MATURITY = {
    2025: 0.00,
    2030: 0.00,
    2035: 0.20,
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

# ── Process-side envelope corridors ────────────────────────────────────
CORRIDOR_UPPER = {
    "carbide":  1.00,
    "steel":    0.30,
    "flyash":   0.25,
    "chem_ore": 0.25,
    "general":  0.08,
}
CORRIDOR_LOWER = {
    "carbide":  0.50,
    "steel":    0.20,
    "flyash":   0.15,
    "chem_ore": 0.15,
    "general":  0.03,
}

# ARM process-emission reduction envelope by resource corridor. These are
# model-side terminal caps for realized process mitigation, not raw material
# replacement shares. They keep carbide-slag provinces materially stronger while
# avoiding the unrealistically broad 0.50-1.00 raw corridor values in the
# descriptive table.
ARM_USE_CORRIDOR_ENVELOPE = True
ARM_PROCESS_TERMINAL_BY_CORRIDOR = {
    "carbide":  (0.12, 0.30),
    "steel":    (0.08, 0.15),
    "flyash":   (0.06, 0.12),
    "chem_ore": (0.06, 0.12),
    "general":  (0.02, 0.05),
}
ARM_PROCESS_DIFFUSION_PROFILE = {
    2025: 0.00,
    2030: 0.15,
    2035: 0.32,
    2040: 0.52,
    2045: 0.70,
    2050: 0.85,
    2055: 0.95,
    2060: 1.00,
}

# ── Exogenous ARM realization ──────────────────────────────────────────
# Current data do not contain plant-level chemistry or material logistics.
# The central path uses a conservative share of the capacity-weighted evidence
# envelope without ranking plants or provinces by a weak proxy. The full
# envelope and provincial corridor remain sensitivity-only evidence cases.
ARM_ENDOGENOUS = False
ARM_SPATIAL_MODE = "national_mean"  # options: national_mean, province_corridor
ARM_PATH_CASE = "central"  # options: central, high
ARM_FRONT_END_CONSTRAINED_SCALE = 0.50
ARM_ADOPTION_STEPS = [0.0, 0.25, 0.50, 0.75, 1.0]
ARM_REFERENCE_MAX = 0.30              # v3 ARM_LEVELS maximum
ARM_MAX_INCREASE_PER_PERIOD = 0.07    # v3 diffusion step, per 5-year period
ARM_INVESTMENT = 33.0                 # CNY/t annual clinker capacity
ARM_OM = 1.5                          # CNY/t clinker at full ARM reference
ARM_LOGISTICS = 15.0                  # CNY/t clinker at full ARM reference

# ── Exogenous energy-efficiency path ───────────────────────────────────
EE_INITIAL_RATE = 0.0
EE_MAX_RATE = 0.20
EE_MAX_INCREASE_PER_PERIOD = 0.05
EE_PATH_CASE = "central"  # options: central, high
EE_PATH = {
    2025: 0.00,
    2030: 0.03,
    2035: 0.05,
    2040: 0.07,
    2045: 0.09,
    2050: 0.10,
    2055: 0.10,
    2060: 0.10,
}
EE_INVESTMENT = 60.0                  # CNY/t annual clinker capacity
EE_OM = 3.0                           # CNY/t clinker, scaled by realized EE rate
BETA_EE = 1.0

# ── Emission target formulation ─────────────────────────────────────────
# All five core scenarios use the same fixed B40 absolute carbon budget. The
# budget is anchored to a documented D-M no-new-mitigation reference and does
# not move with the active demand scenario. This lets demand sensitivities test
# planning pressure under a common climate constraint.
EMISSION_TARGET_MODE = "cumulative_budget"  # options: cumulative_budget, milestone, both, none
CUMULATIVE_BUDGET_METRIC = "net_direct"
CUMULATIVE_BUDGET_BASELINE = "fixed_d_medium_reference_bau"

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
REFERENCE_CUMULATIVE_BAU_KT_YEAR = 21_215_824.089272
REFERENCE_2025_DIRECT_EMISSIONS_KT = 913_725.226516
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

# Retained for backward-compatible result readers and command-line aliases.
# The active cumulative constraint is taken from CARBON_BUDGET_CASES.
CUMULATIVE_REDUCTION_TARGET = CARBON_BUDGET_CASES[CARBON_BUDGET_CASE][
    "reference_reduction"
]

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
CLINKER_RATIO_PATH = {
    2025: 0.647826,
    2030: 0.633851,
    2035: 0.619877,
    2040: 0.605901,
    2045: 0.591926,
    2050: 0.577951,
    2055: 0.563975,
    2060: 0.550000,
}

# ── Plant lifetime and same-site capacity renewal ──────────────────────────────
PLANT_LIFETIME_YEARS = 40
PLANT_DEFAULT_COMMISSION_YEAR = 2010
SAME_SITE_RENEWAL_MIN_CAPACITY_TD = 3200.0
SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY = 400.0

# Backward-compatible names for historical scripts and result files.
# "Rebuild" now denotes brownfield renewal/replacement at the incumbent site,
# not physical restoration of the original kiln for another full lifetime.
REBUILD_MIN_CAPACITY_TD = SAME_SITE_RENEWAL_MIN_CAPACITY_TD
REBUILD_COST_CNY_PER_T_ANNUAL_CAPACITY = (
    SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY
)
# Recalibrated 2026-08-15 (see docs/model_turnover_setting_evaluation_20260815.md):
# 0.40 follows the project's own sourced value (parameter_deduction.md §10.1,
# ccement.com 2025) and the 2024 capacity-replacement rule that capacity
# running <90 days/yr (~25-27%) for two consecutive years loses quota
# eligibility. The former 0.20 hard floor let 55-76% of 2040-2045 operating
# lines sit exactly at the floor, i.e. the bound—not the optimization—was
# determining survival.
MIN_OPERATING_UTILIZATION = 0.40
MAX_UTILIZATION_CHANGE_PER_PERIOD = 0.25
# Recalibrated 2026-08-15: 130 CNY/t follows the transparent component
# derivation in parameter_deduction.md §10.2 (worker resettlement ~50,
# environmental restoration ~25, demolition ~15, capacity-quota opportunity
# cost ~40). The former 400 CNY/t had no documented bridge from 130 and
# coincided with the same-site renewal cost.
EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY = 130.0

# ── Production unit conversion ─────────────────────────────────────────
DAYS_PER_YEAR = 330
CAPACITY_T_DAY_TO_KT_YR = DAYS_PER_YEAR / 1000.0

# ── Source-sink matching ─────────────────────────────────────────────────
TRANSPORT_MAX_KM = 500.0
NEAREST_SINKS_PER_PLANT = 8
NEAREST_SINKS_PER_TYPE = 3
HIGH_CAPACITY_SINKS_PER_PLANT = 2
TRANSPORT_COST_PER_T_KM = 0.05
# Archived builder compatibility only. Active cumulative calculations must use
# PERIOD_WEIGHTS and must not multiply all model nodes by this constant.
PERIOD_YEARS = 5
STORAGE_MT_TO_KT = 1000.0
STORAGE_CUMULATIVE_SCALE = 1.0
STORAGE_RATE_SCALE = 1.0
# The available DSA rate raster is a theoretical maximum, not a defensible
# engineering limit. Cumulative capacity remains binding; annual-rate limits
# are re-enabled only after a weighted-average or conservative dataset exists.
USE_STORAGE_RATE_CONSTRAINT = False

# ── CCS plant size gate (retained from v4, driven by CCS_ROLLOUT_PARAMS) ─
CCS_MIN_CAPACITY_T_DAY_2030 = 4000.0
CCS_MIN_CAPACITY_T_DAY_2035 = 3200.0

# ── Production closure ──────────────────────────────────────────────────
BASE_YEAR = 2025
CLOSURE_YEAR = 2060

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
    # Fast screening: prioritize feasible, mechanism-level solutions.
    "explore": {
        "MIPGap": 0.06,
        "TimeLimit": 1800,
        "Threads": 8,
        "MIPFocus": 1,
        "Heuristics": 0.25,
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
        "Presolve": 2,
        "Cuts": -1,
        "PreSparsify": 1,
        "NodefileStart": 0.5,
        "NumericFocus": 0,
    },
}

# ── Sensitivity defaults ─────────────────────────────────────────────────
CATCHMENT_RADIUS_SENSITIVITY = [30, 50, 70, 100, 150]
CARBON_PRICE_SENSITIVITY = [0.5, 1.0, 1.5, 2.0]


class Config:
    """Container for all config parameters — passed to V4Model."""

    def __init__(self):
        import sys as _sys
        _mod = _sys.modules[self.__module__]
        for _name in dir(_mod):
            if _name.isupper():
                setattr(self, _name, getattr(_mod, _name))


config = Config()
