"""
V4 result extraction and saving.

The solver writes one compact ``<scenario>_results.json`` file.  This module
expands that JSON into V3-style semantic tables for validation, plotting, and
paper diagnostics.  It does not change model logic or solved values.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src_v4.config_v4 import (
    BASE_YEAR,
    CAPACITY_T_DAY_TO_KT_YR,
    CCS_ROLLOUT_PARAMS,
    CCS_SCALE_LIMITS,
    PERIOD_WEIGHTS,
    PLANT_DEFAULT_COMMISSION_YEAR,
    PLANT_LIFETIME_YEARS,
    PROJECT_ROOT,
)

YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
PRODUCTION_ACTIVE_UTILIZATION = 0.01
SCENARIOS = [
    "S1_baseline",
    "S2_front_end",
    "S3_all_spatial_equalized",
    "S4_storage_300km",
    "S5_offshore_parity",
]
ROOT = PROJECT_ROOT
PLANT_DATA_PATH = ROOT / "data" / "model_input" / "plants" / "plant_data.xlsx"
PLANT_TIER_PATH = ROOT / "data" / "model_input" / "plants" / "plant_location_tier.csv"
SCM_PROXY_PATH = ROOT / "data" / "model_input" / "regional" / "scm_proxy.csv"
DEFAULT_COLUMNS = {
    "same_site_renewal_decisions": [
        "period", "plant_idx", "plant_id", "province", "capacity", "operating",
        "renewal_investment",
    ],
    "ccs_decisions": [
        "period", "plant_idx", "plant_id", "province", "capacity", "operating",
        "captured", "captured_commercial", "k_ccs_kt", "new_installation", "is_initial_ccs_site",
    ],
    "ccs_plant_details": [
        "period", "plant_idx", "plant_id", "province", "capacity", "ccs_eligible",
        "is_initial_ccs", "commercial_ccs_installed", "operating", "utilization",
        "k_ccs_kt", "captured_endogenous", "captured_commercial",
        "captured_observed_pilot", "captured", "actual_emission", "net_emission",
        "capture_rate", "commercial_capture_load",
    ],
    "observed_initial_ccs_projects": [
        "plant_idx", "plant_id", "province", "installed_year", "reported_scale_kt_per_year",
        "reported_scale_10kt_per_year", "captured_2025_kt", "operating_2025", "ccs_eligible",
    ],
    "observed_pilot_ccs": [
        "period", "plant_idx", "plant_id", "province", "operating", "reported_capture",
        "is_initial_ccs_site", "ccs_eligible",
    ],
    "storage_utilization": [
        "period", "storage_idx", "longitude", "latitude", "is_offshore", "storage_type",
        "dsa_flow_kt", "eor_flow_kt", "total_flow_kt",
        "dsa_cumulative_stored_kt", "eor_cumulative_stored_kt", "total_cumulative_stored_kt",
        "dsa_rate_capacity_kt_per_year", "eor_rate_capacity_kt_per_year",
        "dsa_cumulative_capacity_kt", "eor_cumulative_capacity_kt",
        "dsa_rate_utilization", "eor_rate_utilization",
        "dsa_cumulative_utilization", "eor_cumulative_utilization",
    ],
    "af_resource_utilization": [
        "province_cn", "province", "period", "af_used_ktce", "af_pool_ktce", "af_resource_utilization",
    ],
}


def load_results(results_dir, scenario):
    """Load compact V4 JSON for one scenario."""
    path = Path(results_dir) / f"{scenario}_results.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_all_results(results_dir):
    """Load all known scenario result JSONs present in a directory."""
    return {s: load_results(results_dir, s) for s in SCENARIOS}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        if np.isnan(out):
            return default
        return out
    except Exception:
        return default


def _period_dict(data: dict | None, year: int, default=0.0):
    if not isinstance(data, dict):
        return default
    return data.get(str(year), data.get(year, default))


def _year_rows(mapping: dict | None):
    if not isinstance(mapping, dict):
        return []
    rows = []
    for key, value in mapping.items():
        try:
            rows.append((int(key), value))
        except Exception:
            continue
    return sorted(rows)


def _flatten(prefix: str, mapping: dict | None):
    if not isinstance(mapping, dict):
        return {}
    return {f"{prefix}_{k}": v for k, v in mapping.items()}


def _clean_nonnegative(value: Any, tol: float = 1e-6) -> float:
    out = _num(value)
    if abs(out) <= tol:
        return 0.0
    return max(out, 0.0)


def _load_plant_metadata() -> pd.DataFrame:
    if not PLANT_DATA_PATH.exists():
        return pd.DataFrame(columns=["plant_id", "capacity", "province"])
    df = pd.read_excel(PLANT_DATA_PATH)
    if "id" in df.columns and "plant_id" not in df.columns:
        df = df.rename(columns={"id": "plant_id"})
    if "year of commissioning" in df.columns and "commission_year" not in df.columns:
        df = df.rename(columns={"year of commissioning": "commission_year"})
    keep = [
        c
        for c in [
            "plant_id",
            "capacity",
            "province",
            "city",
            "longitude",
            "latitude",
            "commission_year",
        ]
        if c in df.columns
    ]
    df = df[keep].copy()
    df["plant_id"] = df["plant_id"].astype(str)
    return df


def _load_location_tier_map() -> dict[str, str]:
    if not PLANT_TIER_PATH.exists():
        return {}
    try:
        df = pd.read_csv(PLANT_TIER_PATH)
    except Exception:
        return {}
    if "plant_id" not in df.columns:
        return {}
    tier_col = next((c for c in ["location_tier", "tier", "plant_location_tier"] if c in df.columns), None)
    if tier_col is None:
        return {}
    df = df[["plant_id", tier_col]].dropna()
    return {str(int(r["plant_id"])): str(r[tier_col]) for _, r in df.iterrows()}


def _load_province_corridor_map() -> dict[str, str]:
    if not SCM_PROXY_PATH.exists():
        return {}
    try:
        df = pd.read_csv(SCM_PROXY_PATH)
    except Exception:
        return {}
    if not {"province_cn", "arm_corridor"}.issubset(df.columns):
        return {}
    return dict(zip(df["province_cn"].astype(str), df["arm_corridor"].astype(str)))


def _plant_meta_maps(meta: pd.DataFrame):
    if meta.empty:
        return {}, {}, {}
    cap = meta.set_index("plant_id").get("capacity", pd.Series(dtype=float)).to_dict()
    prov = meta.set_index("plant_id").get("province", pd.Series(dtype=object)).to_dict()
    city = meta.set_index("plant_id").get("city", pd.Series(dtype=object)).to_dict()
    return cap, prov, city


def _ccs_learning_config():
    try:
        from src_v4 import config_v4 as cfg

        scaling = getattr(cfg, "CCS_COST_SCALING_PARAMS", {})
        curve = getattr(cfg, "CCS_LEARNING_CURVE", {})
        stages = scaling.get("experience_stages", [])
        om_pass = float(scaling.get("om_learning_pass_through", 0.0) or 0.0)
        return scaling, curve, stages, om_pass
    except Exception:
        return {}, {}, [], 0.0


def _stage_multipliers(stage_name):
    _, _, stages, om_pass = _ccs_learning_config()
    for stage in stages:
        if stage.get("name") == stage_name:
            capex = float(stage.get("investment_multiplier", stage.get("multiplier", 1.0)) or 1.0)
            return capex, 1.0 - om_pass * (1.0 - capex)
    return 1.0, 1.0


def _plant_ids(results):
    return sorted(results.get("plants", {}), key=lambda x: int(x) if str(x).isdigit() else str(x))


def _plant_value(pdata, key, year, default=0.0):
    return _period_dict(pdata.get(key, {}), year, default)


def national_summary(results):
    """Build national annual summary. Keeps legacy name used by V4 figures."""
    rows = []
    for yr, s in _year_rows(results.get("summary", {})):
        row = {
            "year": yr,
            "gross_co2_kt": _num(s.get("gross_co2_kt")),
            "gross_co2_mt": _num(s.get("gross_co2_kt")) / 1000.0,
            "net_co2_kt": _num(s.get("net_co2_kt")),
            "net_co2_mt": _num(s.get("net_co2_kt")) / 1000.0,
            "net_co2_commercial_kt": _num(s.get("net_co2_commercial_kt", s.get("net_co2_kt"))),
            "captured_co2_kt": _num(s.get("captured_co2_kt")),
            "captured_co2_mt": _num(s.get("captured_co2_kt")) / 1000.0,
            "commercial_captured_co2_kt": _num(s.get("commercial_captured_co2_kt")),
            "observed_pilot_captured_co2_kt": _num(s.get("observed_pilot_captured_co2_kt")),
            "reduction_vs_baseline": s.get("reduction_vs_baseline"),
            "n_plants_operating": int(round(_num(s.get("n_plants_operating")))),
            "n_plants_ccs": int(round(_num(s.get("n_plants_ccs")))),
            "n_plants_ccs_installed": int(round(_num(s.get("n_plants_ccs_installed", s.get("n_plants_ccs"))))),
            "n_plants_ccs_commercial": int(round(_num(s.get("n_plants_ccs_commercial", s.get("n_plants_ccs"))))),
            "n_plants_ccs_observed_pilot": int(round(_num(s.get("n_plants_ccs_observed_pilot")))),
            "n_plants_ccs_installed_total": int(round(_num(s.get("n_plants_ccs_installed_total", s.get("n_plants_ccs"))))),
            "n_plants_ccs_active": int(round(_num(s.get("n_plants_ccs_active")))),
            "ccs_design_capacity_kt": _num(s.get("ccs_design_capacity_kt")),
            "ccs_idle_capacity_kt": _num(s.get("ccs_idle_capacity_kt")),
            "cement_demand_mt": _num(s.get("cement_demand_mt")),
            "effective_clinker_ratio": s.get("effective_clinker_ratio"),
            "baseline_clinker_ratio": s.get("baseline_clinker_ratio"),
            "lcc_clinker_ratio_reduction": s.get("lcc_clinker_ratio_reduction"),
            "lcc_reduction_vs_baseline": s.get("lcc_reduction_vs_baseline"),
            "lcc_min_clinker_ratio": s.get("lcc_min_clinker_ratio"),
            "province_min_clinker_ratio": s.get("province_min_clinker_ratio"),
            "province_max_clinker_ratio": s.get("province_max_clinker_ratio"),
            "clinker_demand_kt": _num(s.get("clinker_demand_kt")),
            "clinker_production_kt": _num(s.get("clinker_production_kt")),
            "clinker_balance_gap_kt": _num(s.get("clinker_balance_gap_kt")),
            "total_af_supply_ktce": _num(s.get("total_af_supply_ktce")),
            "total_fuel_energy_ktce": _num(s.get("total_fuel_energy_ktce")),
            "national_af_rate": s.get("national_af_rate"),
            "ee_rate": s.get("ee_rate"),
            "avg_arm_realized": s.get("avg_arm_realized"),
            "avg_arm_cap": s.get("avg_arm_cap"),
            "avg_utilization": s.get("avg_utilization"),
            "utilization_shortfall": s.get("utilization_shortfall"),
            "milestone_target_kt": s.get("milestone_target_kt"),
            "milestone_actual_kt": s.get("milestone_actual_kt"),
            "milestone_slack_kt": s.get("milestone_slack_kt", 0.0),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def plant_summary(results, cap_map=None):
    """Wide plant summary retained for existing V4 plotting helpers."""
    cap_map = cap_map or {}
    rows = []
    for pid in _plant_ids(results):
        pdata = results["plants"][pid]
        capacity_t_per_day = _num(cap_map.get(str(pid)), np.nan)
        row = {
            "plant_id": pid,
            "capacity_t_per_day": capacity_t_per_day,
            "annual_capacity_kt_per_year": (
                capacity_t_per_day * CAPACITY_T_DAY_TO_KT_YR
                if pd.notna(capacity_t_per_day)
                else np.nan
            ),
        }
        for yr in [2025, 2030, 2040, 2050, 2060]:
            row[f"y_{yr}"] = _plant_value(pdata, "y", yr)
            row[f"u_{yr}"] = round(_num(_plant_value(pdata, "u", yr)), 4)
            row[f"z_{yr}"] = _plant_value(pdata, "z", yr)
            row[f"x_af_{yr}"] = round(_num(_plant_value(pdata, "x_af", yr)), 4)
            row[f"gross_co2_{yr}"] = round(_num(_plant_value(pdata, "co2_gross", yr)), 4)
            row[f"net_co2_{yr}"] = round(_num(_plant_value(pdata, "co2_net", yr)), 4)
            row[f"captured_{yr}"] = round(_num(_plant_value(pdata, "captured", yr)), 4)
        row["cumulative_net_co2_kt_year"] = sum(
            PERIOD_WEIGHTS.get(int(year), 0.0) * _num(value)
            for year, value in pdata.get("co2_net", {}).items()
        )
        row["cumulative_gross_co2_kt_year"] = sum(
            PERIOD_WEIGHTS.get(int(year), 0.0) * _num(value)
            for year, value in pdata.get("co2_gross", {}).items()
        )
        xaf = [_num(v) for v in pdata.get("x_af", {}).values()]
        row["avg_x_af"] = float(np.mean([v for v in xaf if v > 0])) if any(v > 0 for v in xaf) else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def operation_status(results, meta):
    cap, prov, city = _plant_meta_maps(meta)
    rows = []
    observed_sites = {
        str(p.get("plant_id"))
        for p in results.get("observed_initial_ccs_projects", {}).get("projects", [])
    }
    for pid in _plant_ids(results):
        pdata = results["plants"][pid]
        for yr in YEARS:
            operating = int(round(_num(_plant_value(pdata, "y", yr))))
            rows.append({
                "period": yr,
                "plant_idx": pid,
                "plant_id": pid,
                "province": prov.get(str(pid)),
                "city": city.get(str(pid)),
                "capacity": cap.get(str(pid), np.nan),
                "operating": operating,
                "utilization": _num(_plant_value(pdata, "u", yr)),
                "is_ccs_plant": int(round(_num(_plant_value(pdata, "z", yr)))),
                "is_observed_initial_ccs_site": int(str(pid) in observed_sites),
                "retired": int(operating == 0),
            })
    return pd.DataFrame(rows)


def same_site_renewal_decisions(results, meta):
    """Extract brownfield renewal events stored under the legacy variable ``r``."""
    cap, prov, _ = _plant_meta_maps(meta)
    rows = []
    for pid in _plant_ids(results):
        pdata = results["plants"][pid]
        for yr in YEARS:
            r = int(round(_num(_plant_value(pdata, "r", yr))))
            if r or _plant_value(pdata, "r", yr, None) is not None:
                rows.append({
                    "period": yr,
                    "plant_idx": pid,
                    "plant_id": pid,
                    "province": prov.get(str(pid)),
                    "capacity": cap.get(str(pid), np.nan),
                    "operating": int(round(_num(_plant_value(pdata, "y", yr)))),
                    "renewal_investment": r,
                })
    return pd.DataFrame(rows)


def af_plant_shares(results, meta):
    cap, prov, _ = _plant_meta_maps(meta)
    rows = []
    for pid in _plant_ids(results):
        pdata = results["plants"][pid]
        for yr in YEARS:
            rows.append({
                "period": yr,
                "plant_idx": pid,
                "plant_id": pid,
                "province": prov.get(str(pid)),
                "capacity": cap.get(str(pid), np.nan),
                "operating": int(round(_num(_plant_value(pdata, "y", yr)))),
                "utilization": _num(_plant_value(pdata, "u", yr)),
                "af_share": _num(_plant_value(pdata, "x_af", yr)),
                "af_add": _num(_plant_value(pdata, "af_add", yr)),
                "u_af": _num(_plant_value(pdata, "uaf", yr)),
                "z_u_af": _num(_plant_value(pdata, "uaf", yr)),
                "af_supply_ktce": _num(_plant_value(pdata, "af_supply_ktce", yr)),
            })
    return pd.DataFrame(rows)


def ccs_plant_details(results, meta):
    cap, prov, _ = _plant_meta_maps(meta)
    observed_sites = {
        str(p.get("plant_id"))
        for p in results.get("observed_initial_ccs_projects", {}).get("projects", [])
    }
    rows = []
    for pid in _plant_ids(results):
        pdata = results["plants"][pid]
        for yr in YEARS:
            captured = _num(_plant_value(pdata, "captured", yr))
            commercial = _num(_plant_value(pdata, "captured_commercial", yr))
            observed = _num(_plant_value(pdata, "captured_observed_pilot", yr))
            gross = _num(_plant_value(pdata, "co2_gross", yr))
            z = int(round(_num(_plant_value(pdata, "z", yr))))
            k = _num(_plant_value(pdata, "k_ccs", yr))
            if not (z or k > 1e-9 or captured > 1e-9 or str(pid) in observed_sites):
                continue
            rows.append({
                "period": yr,
                "plant_idx": pid,
                "plant_id": pid,
                "province": prov.get(str(pid)),
                "capacity": cap.get(str(pid), np.nan),
                "ccs_eligible": 1,
                "is_initial_ccs": int(str(pid) in observed_sites),
                "commercial_ccs_installed": z,
                "operating": int(round(_num(_plant_value(pdata, "y", yr)))),
                "utilization": _num(_plant_value(pdata, "u", yr)),
                "k_ccs_kt": k,
                "captured_endogenous": commercial,
                "captured_commercial": commercial,
                "captured_observed_pilot": observed,
                "captured": captured,
                "actual_emission": gross,
                "net_emission": _num(_plant_value(pdata, "co2_net", yr)),
                "capture_rate": captured / gross if gross > 1e-9 else 0.0,
                "commercial_capture_load": commercial / k if k > 1e-9 else 0.0,
            })
    return pd.DataFrame(rows)


def ccs_decisions(results, meta):
    details = ccs_plant_details(results, meta)
    if details.empty:
        return pd.DataFrame(columns=[
            "period", "plant_idx", "plant_id", "province", "capacity", "operating",
            "captured", "new_installation", "is_initial_ccs_site",
        ])
    details = details.sort_values(["plant_id", "period"]).copy()
    rows = []
    for pid, group in details.groupby("plant_id", sort=False):
        prev_z = 0
        for _, row in group.iterrows():
            z = int(row["commercial_ccs_installed"])
            rows.append({
                "period": int(row["period"]),
                "plant_idx": row["plant_idx"],
                "plant_id": row["plant_id"],
                "province": row["province"],
                "capacity": row["capacity"],
                "operating": row["operating"],
                "captured": row["captured"],
                "captured_commercial": row["captured_commercial"],
                "k_ccs_kt": row["k_ccs_kt"],
                "new_installation": int(z == 1 and prev_z == 0),
                "is_initial_ccs_site": row["is_initial_ccs"],
            })
            prev_z = max(prev_z, z)
    return pd.DataFrame(rows)


def plant_emission_balance(results, meta):
    cap, prov, _ = _plant_meta_maps(meta)
    rows = []
    for pid in _plant_ids(results):
        pdata = results["plants"][pid]
        for yr in YEARS:
            gross = _num(_plant_value(pdata, "co2_gross", yr))
            commercial = _num(_plant_value(pdata, "captured_commercial", yr))
            observed = _num(_plant_value(pdata, "captured_observed_pilot", yr))
            rows.append({
                "period": yr,
                "plant_idx": pid,
                "plant_id": pid,
                "province": prov.get(str(pid)),
                "entity_type": "plant",
                "capacity": cap.get(str(pid), np.nan),
                "operating": int(round(_num(_plant_value(pdata, "y", yr)))),
                "utilization": _num(_plant_value(pdata, "u", yr)),
                "co2_fuel": _num(_plant_value(pdata, "co2_fuel", yr)),
                "co2_process": _num(_plant_value(pdata, "co2_process", yr)),
                "actual_direct_emissions": gross,
                "captured_commercial": commercial,
                "captured_observed_pilot": observed,
                "captured": commercial + observed,
                "residual_after_capture": _num(_plant_value(pdata, "co2_net", yr)),
                "residual_after_commercial_capture": _num(_plant_value(pdata, "co2_net_commercial", yr)),
            })
    return pd.DataFrame(rows)


def emissions(results):
    rows = []
    for yr, s in _year_rows(results.get("summary", {})):
        rows.append({
            "period": yr,
            "gross_direct_emission": _num(s.get("gross_co2_kt")),
            "commercial_captured_co2": _num(s.get("commercial_captured_co2_kt")),
            "observed_pilot_captured_co2": _num(s.get("observed_pilot_captured_co2_kt")),
            "captured_co2": _num(s.get("captured_co2_kt")),
            "residual_direct_emission_after_capture": _num(s.get("net_co2_kt")),
            "direct_emission": _num(s.get("net_co2_kt")),
            "electricity_emission": 0.0,
            "ccs_energy_emission": 0.0,
            "elec_energy_emission": 0.0,
            "h2_energy_emission": 0.0,
            "indirect_emission": 0.0,
            "total_emission": _num(s.get("net_co2_kt")),
            "captured": _num(s.get("captured_co2_kt")),
            "net_emission": _num(s.get("net_co2_kt")),
            "reduction_vs_baseline": s.get("reduction_vs_baseline"),
        })
    return pd.DataFrame(rows)


def production_demand(results):
    rows = []
    for yr, s in _year_rows(results.get("summary", {})):
        rows.append({
            "period": yr,
            "raw_cement_demand": _num(s.get("cement_demand_mt")),
            "cement_demand": _num(s.get("cement_demand_mt")),
            "cement_demand_adjustment": 0.0,
            "demand_preprocess_mode": "v4_direct_demand",
            "clinker_ratio": s.get("effective_clinker_ratio"),
            "baseline_clinker_ratio": s.get("baseline_clinker_ratio"),
            "lcc_clinker_ratio_reduction": s.get("lcc_clinker_ratio_reduction"),
            "lcc_reduction_vs_baseline": s.get("lcc_reduction_vs_baseline"),
            "province_min_clinker_ratio": s.get("province_min_clinker_ratio"),
            "province_max_clinker_ratio": s.get("province_max_clinker_ratio"),
            "raw_clinker_demand_proxy": _num(s.get("clinker_demand_kt")),
            "clinker_demand": _num(s.get("clinker_demand_kt")),
            "clinker_production": _num(s.get("clinker_production_kt")),
            "production_surplus": _num(s.get("clinker_balance_gap_kt")),
            "u_shortfall": _num(s.get("utilization_shortfall")),
            "utilization_rate": _num(s.get("avg_utilization")),
            "operating_capacity_proxy": (
                _num(s.get("clinker_production_kt")) / max(_num(s.get("avg_utilization")), 1e-9)
            ),
        })
    return pd.DataFrame(rows)


def industry_tech(results):
    rows = []
    for yr, s in _year_rows(results.get("summary", {})):
        rows.append({
            "period": yr,
            "ee_rate": s.get("ee_rate"),
            "af_rate": s.get("national_af_rate"),
            "arm_rate": s.get("avg_arm_realized"),
            "arm_cap": s.get("avg_arm_cap"),
            "clinker_ratio": s.get("effective_clinker_ratio"),
            "baseline_clinker_ratio": s.get("baseline_clinker_ratio"),
            "clinker_ratio_novel_component": s.get("lcc_clinker_ratio_reduction"),
            "clinker_ratio_novel_cap": (
                _num(s.get("baseline_clinker_ratio")) - _num(s.get("lcc_min_clinker_ratio"))
            ),
            "clinker_ratio_novel_utilization": (
                _num(s.get("lcc_clinker_ratio_reduction"))
                / max(_num(s.get("baseline_clinker_ratio")) - _num(s.get("lcc_min_clinker_ratio")), 1e-9)
            ),
            "process_adjustment_avg": s.get("avg_arm_realized"),
            "ccs_installed_plants": s.get("n_plants_ccs_installed_total"),
            "ccs_active_plants": s.get("n_plants_ccs_active"),
            "ccs_design_capacity_kt": s.get("ccs_design_capacity_kt"),
            "ccs_idle_capacity_kt": s.get("ccs_idle_capacity_kt"),
        })
    return pd.DataFrame(rows)


def novel_lcc_realization(results):
    rows = []
    for yr, s in _year_rows(results.get("summary", {})):
        rows.append({
            "period": yr,
            "baseline_clinker_ratio": s.get("baseline_clinker_ratio"),
            "effective_clinker_ratio": s.get("effective_clinker_ratio"),
            "clinker_ratio_reduction": s.get("lcc_clinker_ratio_reduction"),
            "reduction_vs_baseline": s.get("lcc_reduction_vs_baseline"),
            "minimum_allowed_clinker_ratio": s.get("lcc_min_clinker_ratio"),
            "province_min_clinker_ratio": s.get("province_min_clinker_ratio"),
            "province_max_clinker_ratio": s.get("province_max_clinker_ratio"),
        })
    return pd.DataFrame(rows)


def costs(results):
    rows = []
    for yr, data in _year_rows(results.get("cost_breakdown", {})):
        components = data.get("components_nominal_kCNY", {}) or {}
        discounted = data.get("components_discounted_kCNY", {}) or {}
        diagnostics = data.get("diagnostics_nominal_kCNY", {}) or {}
        diagnostics_disc = data.get("diagnostics_discounted_kCNY", {}) or {}
        ccs_cost = sum(_num(components.get(k)) for k in ["ccs_capex", "ccs_opex"])
        storage_cost = sum(_num(components.get(k)) for k in ["dsa_storage", "eor_storage"])
        row = {
            "period": yr,
            "ee_cost": _num(components.get("ee_capex")) + _num(components.get("ee_opex")),
            "af_cost": _num(components.get("af_capex")) + _num(components.get("af_opex")) + _num(components.get("fuel")),
            "arm_cost": _num(components.get("arm_capex")) + _num(components.get("arm_opex")),
            "lcc_cost": 0.0,
            "ccs_cost": ccs_cost,
            "elec_cost": 0.0,
            "h2_cost": 0.0,
            "pipeline_cost": _num(components.get("transport")) + _num(components.get("hub")),
            "storage_cost": storage_cost,
            "carbon_cost": _num(diagnostics.get("carbon")),
            "shutdown_cost": 0.0,
            "same_site_renewal_cost": _num(
                components.get(
                    "same_site_renewal_capex",
                    components.get("rebuild_capex"),
                )
            ),
            "util_anchor_cost": _num(components.get("utilization_shortfall")),
            "eor_revenue": _num(components.get("eor_revenue_credit")),
            "discount_factor": data.get("discount_factor"),
            "net_cost": data.get("nominal_total_kCNY"),
            "discounted_cost": data.get("discounted_total_kCNY"),
            "system_cost": data.get("nominal_total_kCNY"),
            "discounted_system_cost": data.get("discounted_total_kCNY"),
            "discounted_carbon_cost": _num(diagnostics_disc.get("carbon")),
        }
        row.update(_flatten("nominal", components))
        row.update(_flatten("discounted", discounted))
        row.update(_flatten("diagnostic_nominal", diagnostics))
        row.update(_flatten("diagnostic_discounted", diagnostics_disc))
        rows.append(row)
    return pd.DataFrame(rows)


def co2_flows(results):
    routes = results.get("co2_flow_routes")
    if isinstance(routes, dict):
        rows = []
        for yr, route_rows in _year_rows(routes):
            for row in route_rows or []:
                out = dict(row)
                out.setdefault("period", yr)
                if "flow_kt" in out and "flow" not in out:
                    out["flow"] = _clean_nonnegative(out.get("flow_kt"))
                if "distance_km" in out and "distance" not in out:
                    out["distance"] = out.get("distance_km")
                rows.append(out)
        if rows:
            return pd.DataFrame(rows)

    rows = []
    for yr, data in _year_rows(results.get("ccs_transport_storage", {})):
        total_flow = _clean_nonnegative(data.get("total_flow_kt"))
        avg_distance = _num(data.get("weighted_avg_transport_km")) if total_flow > 1e-6 else 0.0
        rows.append({
            "period": yr,
            "cluster_id": None,
            "hub_plant_idx": None,
            "plant_idx": None,
            "storage_idx": None,
            "flow": _clean_nonnegative(data.get("dsa_flow_kt")),
            "type": "DSA_total",
            "distance": avg_distance,
            **{k: v for k, v in data.items()},
        })
        rows.append({
            "period": yr,
            "cluster_id": None,
            "hub_plant_idx": None,
            "plant_idx": None,
            "storage_idx": None,
            "flow": _clean_nonnegative(data.get("eor_flow_kt")),
            "type": "EOR_total",
            "distance": avg_distance,
            **{k: v for k, v in data.items()},
        })
    return pd.DataFrame(rows)


def ccs_transport_storage(results):
    rows = []
    for yr, data in _year_rows(results.get("ccs_transport_storage", {})):
        row = {"period": yr, **data}
        for key in ["dsa_flow_kt", "eor_flow_kt", "total_flow_kt", "offshore_flow_kt", "onshore_flow_kt"]:
            if key in row:
                row[key] = _clean_nonnegative(row[key])
        if _clean_nonnegative(row.get("total_flow_kt")) <= 1e-6:
            row["weighted_avg_transport_km"] = 0.0
        if abs(_num(row.get("flow_capture_gap_kt"))) <= 1e-6:
            row["flow_capture_gap_kt"] = 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def ccs_learning(results):
    rows = []
    _, curve, _, _ = _ccs_learning_config()
    lc_inv = curve.get("investment_multiplier", {}) if isinstance(curve, dict) else {}
    lc_om = curve.get("om_multiplier", {}) if isinstance(curve, dict) else {}
    for yr, data in _year_rows(results.get("ccs_learning", {})):
        row = {"period": yr, **data}
        capex_stage = row.get("capex_stage_multiplier")
        opex_stage = row.get("opex_stage_multiplier")
        if capex_stage is None or opex_stage is None:
            capex_stage, opex_stage = _stage_multipliers(row.get("selected_stage"))
            row["capex_stage_multiplier"] = capex_stage
            row["opex_stage_multiplier"] = opex_stage
        row.setdefault("time_capex_multiplier", lc_inv.get(yr, 1.0))
        row.setdefault("time_opex_multiplier", lc_om.get(yr, 1.0))
        row.setdefault("combined_capex_multiplier", _num(row.get("time_capex_multiplier"), 1.0) * _num(capex_stage, 1.0))
        row.setdefault("combined_opex_multiplier", _num(row.get("time_opex_multiplier"), 1.0) * _num(opex_stage, 1.0))
        rows.append(row)
    return pd.DataFrame(rows)


def storage_utilization(results):
    rows = []
    storage = results.get("storage_utilization")
    if isinstance(storage, dict):
        for yr, items in _year_rows(storage):
            for item in items or []:
                row = dict(item)
                row.setdefault("period", yr)
                rows.append(row)
    return pd.DataFrame(rows, columns=DEFAULT_COLUMNS["storage_utilization"] if not rows else None)


def province_arm(results):
    rows = []
    for province, pdata in (results.get("province_arm", {}) or {}).items():
        for yr, ydata in _year_rows(pdata):
            rows.append({
                "province_cn": province,
                "province": province,
                "period": yr,
                "arm_realized": ydata.get("realized"),
                "arm_cap": ydata.get("cap"),
                "arm_utilization": _num(ydata.get("realized")) / max(_num(ydata.get("cap")), 1e-9),
            })
    return pd.DataFrame(rows)


def af_resource_utilization(results):
    rows = []
    data = results.get("af_resource_utilization")
    if isinstance(data, dict):
        for province, pdata in data.items():
            for yr, ydata in _year_rows(pdata):
                rows.append({
                    "province_cn": province,
                    "province": province,
                    "period": yr,
                    "af_used_ktce": _num(ydata.get("used_ktce")),
                    "af_pool_ktce": _num(ydata.get("pool_ktce")),
                    "af_resource_utilization": _num(ydata.get("utilization")),
                })
        return pd.DataFrame(rows)

    bridge = None
    try:
        bridge = province_frontend_ccs_bridge(results, _load_plant_metadata())
    except Exception:
        bridge = pd.DataFrame()
    if bridge is None or bridge.empty:
        return pd.DataFrame(columns=DEFAULT_COLUMNS["af_resource_utilization"])
    out = bridge[["province_cn", "period", "af_supply_ktce"]].copy()
    out["province"] = out["province_cn"]
    out = out.rename(columns={"af_supply_ktce": "af_used_ktce"})
    out["af_pool_ktce"] = np.nan
    out["af_resource_utilization"] = np.nan
    return out[["province_cn", "province", "period", "af_used_ktce", "af_pool_ktce", "af_resource_utilization"]]


def residual_emissions_by_province(results, meta):
    balance = plant_emission_balance(results, meta)
    if balance.empty:
        return balance
    grouped = balance.groupby(["province", "period"], dropna=False).agg(
        capacity=("capacity", "sum"),
        operating_plants=("operating", "sum"),
        utilization=("utilization", "mean"),
        gross_direct_emission=("actual_direct_emissions", "sum"),
        co2_fuel=("co2_fuel", "sum"),
        co2_process=("co2_process", "sum"),
        commercial_captured_co2=("captured_commercial", "sum"),
        observed_pilot_captured_co2=("captured_observed_pilot", "sum"),
        captured_co2=("captured", "sum"),
        residual_direct_emission_after_capture=("residual_after_capture", "sum"),
    ).reset_index()
    grouped = grouped.rename(columns={"province": "province_cn"})
    arm = province_arm(results)
    if not arm.empty:
        grouped = grouped.merge(
            arm[["province_cn", "period", "arm_realized", "arm_cap", "arm_utilization"]],
            on=["province_cn", "period"],
            how="left",
        )
    grouped["capture_share_of_direct"] = grouped["captured_co2"] / grouped["gross_direct_emission"].replace(0, np.nan)
    return grouped.fillna({"capture_share_of_direct": 0.0})


def province_frontend_ccs_bridge(results, meta):
    prov = residual_emissions_by_province(results, meta)
    if prov.empty:
        return prov
    af = af_plant_shares(results, meta)
    if not af.empty:
        af_agg = af.groupby(["province", "period"], dropna=False).agg(
            af_supply_ktce=("af_supply_ktce", "sum"),
            avg_af_share=("af_share", "mean"),
        ).reset_index().rename(columns={"province": "province_cn"})
        prov = prov.merge(af_agg, on=["province_cn", "period"], how="left")
    nat = national_summary(results)[[
        "year", "effective_clinker_ratio", "lcc_clinker_ratio_reduction",
        "province_min_clinker_ratio", "province_max_clinker_ratio",
    ]].rename(columns={"year": "period"})
    prov = prov.merge(nat, on="period", how="left")
    prov["actual_direct_emissions"] = prov["gross_direct_emission"]
    prov["actual_captured"] = prov["captured_co2"]
    prov["actual_residual_after_capture"] = prov["residual_direct_emission_after_capture"]
    prov["capture_share_of_direct"] = prov["actual_captured"] / prov["actual_direct_emissions"].replace(0, np.nan)
    return prov.fillna({"capture_share_of_direct": 0.0, "af_supply_ktce": 0.0, "avg_af_share": 0.0})


def national_frontend_ccs_bridge(results):
    nat = national_summary(results)
    rows = []
    for _, s in nat.iterrows():
        gross = _num(s.get("gross_co2_kt"))
        captured = _num(s.get("captured_co2_kt"))
        rows.append({
            "period": int(s["year"]),
            "cement_production_proxy": s.get("cement_demand_mt"),
            "gross_direct_baseline_proxy": results.get("baseline_2025_co2_kt"),
            "gross_direct_emission": gross,
            "commercial_captured_co2": s.get("commercial_captured_co2_kt"),
            "observed_pilot_captured_co2": s.get("observed_pilot_captured_co2_kt"),
            "captured_co2": captured,
            "residual_direct_emission_after_capture": s.get("net_co2_kt"),
            "actual_direct_emissions": gross,
            "actual_captured": captured,
            "actual_residual_after_capture": s.get("net_co2_kt"),
            "ee_rate": s.get("ee_rate"),
            "af_rate": s.get("national_af_rate"),
            "clinker_ratio": s.get("effective_clinker_ratio"),
            "process_adjustment_avg": s.get("avg_arm_realized"),
            "clinker_ratio_novel_component": s.get("lcc_clinker_ratio_reduction"),
            "raw_cement_demand": s.get("cement_demand_mt"),
            "cement_demand": s.get("cement_demand_mt"),
            "clinker_demand": s.get("clinker_demand_kt"),
            "clinker_production": s.get("clinker_production_kt"),
            "operating_capacity": s.get("clinker_production_kt") / max(_num(s.get("avg_utilization")), 1e-9),
            "production_surplus": s.get("clinker_balance_gap_kt"),
            "capture_share_of_direct": captured / gross if gross > 1e-9 else 0.0,
            "direct_emission": s.get("net_co2_kt"),
            "captured": captured,
            "indirect_emission": 0.0,
            "total_emission": s.get("net_co2_kt"),
            "net_emission": s.get("net_co2_kt"),
        })
    return pd.DataFrame(rows)


def _frontend_component_rows(results, meta, by_province=False):
    try:
        from src_v4 import config_v4 as cfg
        beta_af = float(getattr(cfg, "BETA_AF", 0.55))
        beta_ee = float(getattr(cfg, "BETA_EE", 1.0))
    except Exception:
        beta_af = 0.55
        beta_ee = 1.0

    cap, prov, _ = _plant_meta_maps(meta)
    arm = province_arm(results)
    arm_map = {}
    if not arm.empty:
        arm_map = {
            (str(r["province_cn"]), int(r["period"])): _num(r["arm_realized"])
            for _, r in arm.iterrows()
        }
    rows_by_key = {}
    for pid in _plant_ids(results):
        pdata = results["plants"][pid]
        province = prov.get(str(pid), "unknown")
        for yr in YEARS:
            u = _num(_plant_value(pdata, "u", yr))
            fuel_after = _num(_plant_value(pdata, "co2_fuel", yr))
            process_after = _num(_plant_value(pdata, "co2_process", yr))
            commercial_capture = _num(_plant_value(pdata, "captured_commercial", yr))
            observed_capture = _num(_plant_value(pdata, "captured_observed_pilot", yr))
            uaf = _num(_plant_value(pdata, "uaf", yr))
            uee = _num(_plant_value(pdata, "uee", yr))

            if u > 1e-9:
                af_intensity = uaf / u
                ee_intensity = uee / u
                denom = 1.0 - beta_af * af_intensity - beta_ee * ee_intensity
                fuel_no_af_ee = fuel_after / denom if denom > 1e-6 else fuel_after
                af_reduction = beta_af * fuel_no_af_ee * af_intensity
                ee_reduction = beta_ee * fuel_no_af_ee * ee_intensity
            else:
                fuel_no_af_ee = fuel_after
                af_reduction = 0.0
                ee_reduction = 0.0

            arm_realized = arm_map.get((str(province), yr), 0.0)
            process_no_arm = process_after / (1.0 - arm_realized) if arm_realized < 0.999999 else process_after
            arm_reduction = max(process_no_arm - process_after, 0.0)

            key = (province, yr) if by_province else ("national", yr)
            row = rows_by_key.setdefault(key, {
                "province_cn": province if by_province else "national",
                "period": yr,
                "fuel_emission_without_af_ee_kt": 0.0,
                "process_emission_without_arm_kt": 0.0,
                "af_fuel_reduction_proxy_kt": 0.0,
                "ee_fuel_reduction_proxy_kt": 0.0,
                "arm_process_reduction_proxy_kt": 0.0,
                "gross_direct_emission_kt": 0.0,
                "commercial_ccs_capture_kt": 0.0,
                "observed_pilot_capture_kt": 0.0,
            })
            row["fuel_emission_without_af_ee_kt"] += fuel_no_af_ee
            row["process_emission_without_arm_kt"] += process_no_arm
            row["af_fuel_reduction_proxy_kt"] += af_reduction
            row["ee_fuel_reduction_proxy_kt"] += ee_reduction
            row["arm_process_reduction_proxy_kt"] += arm_reduction
            row["gross_direct_emission_kt"] += fuel_after + process_after
            row["commercial_ccs_capture_kt"] += commercial_capture
            row["observed_pilot_capture_kt"] += observed_capture

    rows = []
    nat = national_summary(results).set_index("year") if not national_summary(results).empty else pd.DataFrame()
    cumulative = results.get("cumulative_budget", {}) or {}
    bau_by_year = cumulative.get("bau_by_year_kt", {}) or {}
    for (province, yr), row in rows_by_key.items():
        no_lcc_proxy = row["fuel_emission_without_af_ee_kt"] + row["process_emission_without_arm_kt"]
        if by_province:
            baseline_proxy = no_lcc_proxy
            lcc_proxy = np.nan
        else:
            baseline_proxy = _num(bau_by_year.get(str(yr), bau_by_year.get(yr, np.nan)), np.nan)
            if np.isnan(baseline_proxy):
                baseline_proxy = no_lcc_proxy
            lcc_proxy = max(baseline_proxy - no_lcc_proxy, 0.0)
        total_capture = row["commercial_ccs_capture_kt"] + row["observed_pilot_capture_kt"]
        net = row["gross_direct_emission_kt"] - total_capture
        row.update({
            "baseline_emission_proxy_kt": baseline_proxy,
            "lcc_demand_clinker_reduction_proxy_kt": lcc_proxy,
            "front_end_reduction_proxy_kt": (
                _num(row["af_fuel_reduction_proxy_kt"])
                + _num(row["ee_fuel_reduction_proxy_kt"])
                + _num(row["arm_process_reduction_proxy_kt"])
                + (0.0 if np.isnan(_num(lcc_proxy, np.nan)) else _num(lcc_proxy))
            ),
            "total_ccs_capture_kt": total_capture,
            "net_emission_kt": net,
            "note": "Front-end components are model-consistent proxies; AF/EE/ARM are reconstructed from solved emissions equations, LCC is a national BAU-to-no-LCC residual proxy.",
        })
        rows.append(row)
    df = pd.DataFrame(rows)
    if not by_province and "province_cn" in df.columns:
        df = df.drop(columns=["province_cn"])
    return df.sort_values(["period"] if not by_province else ["province_cn", "period"])


def emission_contribution(results, meta):
    return _frontend_component_rows(results, meta, by_province=False)


def province_emission_contribution(results, meta):
    return _frontend_component_rows(results, meta, by_province=True)


def has_incumbent_solution(results):
    """Return True when the compact result JSON contains solved plant/year data."""
    if not isinstance(results, dict):
        return False
    solver = results.get("solver") or {}
    try:
        if int(solver.get("solution_count") or 0) <= 0:
            return False
    except Exception:
        pass
    return bool(results.get("summary")) and bool(results.get("plants"))


def observed_initial_ccs_projects(results):
    projects = results.get("observed_initial_ccs_projects", {}).get("projects", [])
    rows = []
    for p in projects:
        rows.append({
            "plant_idx": p.get("plant_id"),
            "plant_id": p.get("plant_id"),
            "province": p.get("province"),
            "installed_year": p.get("installed_year"),
            "reported_scale_kt_per_year": p.get("reported_scale_kt_per_year"),
            "reported_scale_10kt_per_year": _num(p.get("reported_scale_kt_per_year")) / 10.0,
            "captured_2025_kt": p.get("captured_2025_kt"),
            "operating_2025": p.get("operating_2025"),
            "ccs_eligible": 1,
        })
    return pd.DataFrame(rows)


def observed_pilot_ccs(results):
    projects = results.get("observed_initial_ccs_projects", {}).get("projects", [])
    rows = []
    for p in projects:
        for yr in YEARS:
            rows.append({
                "period": yr,
                "plant_idx": p.get("plant_id"),
                "plant_id": p.get("plant_id"),
                "province": p.get("province"),
                "operating": p.get("operating_2025") if yr == 2025 else None,
                "reported_capture": p.get("captured_2025_kt") if yr == 2025 else 0.0,
                "is_initial_ccs_site": 1,
                "ccs_eligible": 1,
            })
    return pd.DataFrame(rows)


def ccs_rollout_cap_check(results, meta):
    """Check the time-varying plant-size gate and actual CCS additions."""
    cap, _, _ = _plant_meta_maps(meta)
    gate = CCS_ROLLOUT_PARAMS.get("min_capacity_td_by_period", {})
    rows = []
    for yr, s in _year_rows(results.get("summary", {})):
        minimum = gate.get(yr)
        operating = 0
        eligible = 0
        installed = 0
        new_installations = 0
        invalid_below_gate = 0
        for pid in _plant_ids(results):
            pdata = results["plants"][pid]
            y = int(round(_num(_plant_value(pdata, "y", yr))))
            z = int(round(_num(_plant_value(pdata, "z", yr))))
            prior_year = max((year for year in YEARS if year < yr), default=None)
            prior_z = (
                int(round(_num(_plant_value(pdata, "z", prior_year))))
                if prior_year is not None
                else 0
            )
            plant_capacity = _num(cap.get(str(pid)))
            size_eligible = minimum is None or plant_capacity >= float(minimum)
            operating += y
            eligible += int(y and size_eligible)
            installed += z
            new_installations += int(z and not prior_z)
            invalid_below_gate += int(z and not size_eligible)
        rows.append({
            "period": yr,
            "operating_plants": operating,
            "size_eligible_operating_plants": eligible,
            "commercial_ccs_installed_plants": installed,
            "new_ccs_installations": new_installations,
            "new_ccs_design_capacity_kt": _num(
                _period_dict(results.get("ccs_learning", {}), yr, {}).get(
                    "new_design_capacity_kt"
                )
            ),
            "invalid_installed_below_size_gate": invalid_below_gate,
            "rollout_min_capacity_td": minimum,
            "capture_scale_limit": CCS_SCALE_LIMITS.get(yr),
        })
    return pd.DataFrame(rows)


def _plant_role_from_metrics(operating, utilization, front_end_index, ccs_capture_share, captured_commercial):
    """Classify plant-year roles for the paper's heterogeneity storyline."""
    if operating < 0.5 or utilization < 0.05:
        return "phase_down_low_retrofit_priority"
    if ccs_capture_share >= 0.40 or captured_commercial >= 50.0:
        if front_end_index >= 0.15:
            return "hybrid_transition"
        return "ccus_backbone"
    if ccs_capture_share >= 0.10 and front_end_index >= 0.10:
        return "hybrid_transition"
    if front_end_index >= 0.15:
        return "front_end_first"
    return "residual_unabated_monitor"


def plant_role_classification(results, meta):
    """
    Plant-period role table for the main story.

    Roles are descriptive diagnostics derived from solved variables. They do not
    affect the optimization:
      - front_end_first: high front-end mitigation, little/no commercial CCS
      - ccus_backbone: large CCS role with limited front-end mitigation
      - hybrid_transition: front-end mitigation and CCS are both material
      - phase_down_low_retrofit_priority: inactive or near-inactive plants
      - residual_unabated_monitor: operating residual emitters without a strong
        front-end or CCS signal; useful for policy triage rather than a headline role
    """
    cap, prov, city = _plant_meta_maps(meta)
    tier_map = _load_location_tier_map()
    corridor_map = _load_province_corridor_map()
    arm = province_arm(results)
    arm_map = {}
    if not arm.empty:
        arm_map = {
            (str(r["province_cn"]), int(r["period"])): {
                "arm_realized": _num(r.get("arm_realized")),
                "arm_cap": _num(r.get("arm_cap")),
                "arm_utilization": _num(r.get("arm_utilization")),
            }
            for _, r in arm.iterrows()
        }
    nat = national_summary(results)
    nat_map = {}
    if not nat.empty:
        for _, r in nat.iterrows():
            yr = int(r["year"])
            nat_map[yr] = {
                "ee_rate": _num(r.get("ee_rate")),
                "lcc_clinker_ratio_reduction": _num(r.get("lcc_clinker_ratio_reduction")),
                "effective_clinker_ratio": _num(r.get("effective_clinker_ratio")),
            }

    rows = []
    for pid in _plant_ids(results):
        pdata = results["plants"][pid]
        province = prov.get(str(pid))
        for yr in YEARS:
            operating = int(round(_num(_plant_value(pdata, "y", yr))))
            utilization = _num(_plant_value(pdata, "u", yr))
            af_share = _num(_plant_value(pdata, "x_af", yr))
            gross = _num(_plant_value(pdata, "co2_gross", yr))
            commercial_capture = _num(_plant_value(pdata, "captured_commercial", yr))
            observed_capture = _num(_plant_value(pdata, "captured_observed_pilot", yr))
            captured = commercial_capture + observed_capture
            residual = _num(_plant_value(pdata, "co2_net", yr))
            k_ccs = _num(_plant_value(pdata, "k_ccs", yr))
            ccs_installed = int(round(_num(_plant_value(pdata, "z", yr))))
            ccs_capture_share = commercial_capture / gross if gross > 1e-9 else 0.0
            capture_share_total = captured / gross if gross > 1e-9 else 0.0
            arm_vals = arm_map.get((str(province), yr), {})
            nat_vals = nat_map.get(yr, {})
            arm_realized = _num(arm_vals.get("arm_realized"))
            lcc_reduction = _num(nat_vals.get("lcc_clinker_ratio_reduction"))
            ee_rate = _num(nat_vals.get("ee_rate"))
            # Weighted index is intentionally simple and transparent: AF is a
            # plant choice, ARM is province-specific, LCC/EE are system-wide.
            front_end_index = max(af_share, arm_realized, lcc_reduction, ee_rate)
            role = _plant_role_from_metrics(
                operating, utilization, front_end_index, ccs_capture_share, commercial_capture
            )
            rows.append({
                "period": yr,
                "plant_idx": pid,
                "plant_id": pid,
                "province": province,
                "city": city.get(str(pid)),
                "location_tier": tier_map.get(str(pid)),
                "arm_corridor": corridor_map.get(str(province)),
                "capacity": cap.get(str(pid), np.nan),
                "operating": operating,
                "utilization": utilization,
                "af_share": af_share,
                "arm_realized": arm_realized,
                "arm_cap": _num(arm_vals.get("arm_cap")),
                "arm_utilization": _num(arm_vals.get("arm_utilization")),
                "ee_rate": ee_rate,
                "lcc_clinker_ratio_reduction": lcc_reduction,
                "effective_clinker_ratio": _num(nat_vals.get("effective_clinker_ratio")),
                "front_end_index": front_end_index,
                "commercial_ccs_installed": ccs_installed,
                "k_ccs_kt": k_ccs,
                "gross_direct_emission_kt": gross,
                "captured_commercial_kt": commercial_capture,
                "captured_observed_pilot_kt": observed_capture,
                "captured_total_kt": captured,
                "residual_after_capture_kt": residual,
                "commercial_capture_share_of_gross": ccs_capture_share,
                "total_capture_share_of_gross": capture_share_total,
                "role": role,
                "headline_role": role,
                "is_headline_role": int(role != "residual_unabated_monitor"),
            })
    return pd.DataFrame(rows)


def plant_role_transition(results, meta):
    roles = plant_role_classification(results, meta)
    if roles.empty:
        return roles
    commission_map = (
        pd.to_numeric(
            meta.set_index("plant_id").get(
                "commission_year",
                pd.Series(dtype=float),
            ),
            errors="coerce",
        ).to_dict()
        if not meta.empty
        else {}
    )
    rows = []
    for pid, g in roles.sort_values("period").groupby("plant_id", sort=False):
        g = g.sort_values("period")
        plant_result = results.get("plants", {}).get(
            str(pid),
            results.get("plants", {}).get(pid, {}),
        )
        role_by_year = {int(r["period"]): r["role"] for _, r in g.iterrows()}
        active = g[g["operating"] >= 0.5]
        producing = g[
            (g["operating"] >= 0.5)
            & (g["utilization"] >= PRODUCTION_ACTIVE_UTILIZATION)
        ]
        ccs_years = g.loc[g["captured_commercial_kt"] > 1e-6, "period"]
        high_af_years = g.loc[g["af_share"] >= 0.20, "period"]
        front_end_years = g.loc[g["front_end_index"] >= 0.15, "period"]
        role_changes = sum(
            1
            for prev, curr in zip(g["role"].tolist()[:-1], g["role"].tolist()[1:])
            if prev != curr
        )
        terminal = g[g["period"] == YEARS[-1]]
        terminal_row = terminal.iloc[0] if not terminal.empty else g.iloc[-1]

        raw_commission_year = commission_map.get(str(pid), PLANT_DEFAULT_COMMISSION_YEAR)
        commission_year = (
            int(raw_commission_year)
            if pd.notna(raw_commission_year)
            else int(PLANT_DEFAULT_COMMISSION_YEAR)
        )
        effective_commission_year = max(
            commission_year,
            int(BASE_YEAR) - int(PLANT_LIFETIME_YEARS),
        )
        natural_retirement_year = effective_commission_year + int(PLANT_LIFETIME_YEARS)
        forced_retirement_period = next(
            (
                year
                for year in YEARS
                if year - effective_commission_year > int(PLANT_LIFETIME_YEARS)
            ),
            np.nan,
        )

        physical_exit_year = next(
            (
                int(row.period)
                for row in g.itertuples(index=False)
                if int(row.period) > int(BASE_YEAR) and _num(row.operating) < 0.5
            ),
            np.nan,
        )
        renewal_years = [
            int(year)
            for year, val in _year_rows(plant_result.get("r", {}))
            if _num(val) >= 0.5
        ]
        renewal_year = min(renewal_years) if renewal_years else np.nan
        last_production_year = (
            int(producing["period"].max()) if not producing.empty else np.nan
        )
        production_exit_year = (
            next((year for year in YEARS if year > last_production_year), np.nan)
            if pd.notna(last_production_year) and last_production_year < YEARS[-1]
            else np.nan
        )
        productive_2060 = bool(
            _num(terminal_row.get("operating")) >= 0.5
            and _num(terminal_row.get("utilization")) >= PRODUCTION_ACTIVE_UTILIZATION
        )
        physically_available_2060 = bool(_num(terminal_row.get("operating")) >= 0.5)

        if productive_2060:
            capacity_status = (
                "long_term_production_renewed"
                if renewal_years
                else "long_term_production_original"
            )
        elif physically_available_2060:
            capacity_status = "idle_reserve_2060"
        elif renewal_years:
            capacity_status = "post_renewal_phaseout"
        elif pd.notna(production_exit_year):
            capacity_status = (
                "natural_lifetime_phaseout"
                if int(production_exit_year) >= int(natural_retirement_year)
                else "early_optimized_phaseout"
            )
        elif producing.empty:
            capacity_status = "never_productive_phaseout"
        else:
            capacity_status = "other_phaseout"

        years_early_vs_natural = (
            max(0.0, float(natural_retirement_year) - float(production_exit_year))
            if pd.notna(production_exit_year)
            else np.nan
        )
        first_ccs_year = int(ccs_years.min()) if not ccs_years.empty else np.nan
        remaining_original_life_at_ccs = (
            float(natural_retirement_year) - float(first_ccs_year)
            if pd.notna(first_ccs_year)
            else np.nan
        )
        rows.append({
            "plant_id": pid,
            "plant_idx": pid,
            "province": terminal_row.get("province"),
            "city": terminal_row.get("city"),
            "location_tier": terminal_row.get("location_tier"),
            "arm_corridor": terminal_row.get("arm_corridor"),
            "capacity": terminal_row.get("capacity"),
            "first_active_year": int(active["period"].min()) if not active.empty else np.nan,
            "last_active_year": int(active["period"].max()) if not active.empty else np.nan,
            "first_production_year": int(producing["period"].min()) if not producing.empty else np.nan,
            "last_production_year": last_production_year,
            "production_exit_year": production_exit_year,
            "first_commercial_ccs_year": first_ccs_year,
            "first_high_af_year": int(high_af_years.min()) if not high_af_years.empty else np.nan,
            "first_front_end_year": int(front_end_years.min()) if not front_end_years.empty else np.nan,
            "commission_year": commission_year,
            "model_effective_commission_year": effective_commission_year,
            "age_2025": int(BASE_YEAR) - commission_year,
            "remaining_model_life_2025": max(
                0,
                natural_retirement_year - int(BASE_YEAR),
            ),
            "natural_retirement_year": natural_retirement_year,
            "first_forced_retirement_period": forced_retirement_period,
            "physical_exit_year": physical_exit_year,
            "same_site_renewal_year": renewal_year,
            "years_early_vs_natural_retirement": years_early_vs_natural,
            "remaining_original_life_at_first_ccs": remaining_original_life_at_ccs,
            "physically_available_2060": int(physically_available_2060),
            "productive_2060": int(productive_2060),
            "capacity_status": capacity_status,
            "terminal_role": terminal_row.get("role"),
            "terminal_headline_role": terminal_row.get("headline_role"),
            "role_changes": role_changes,
            "cumulative_gross_direct_kt_year": float(
                (g["gross_direct_emission_kt"] * g["period"].map(PERIOD_WEIGHTS)).sum()
            ),
            "cumulative_commercial_capture_kt_year": float(
                (g["captured_commercial_kt"] * g["period"].map(PERIOD_WEIGHTS)).sum()
            ),
            "cumulative_residual_kt_year": float(
                (g["residual_after_capture_kt"] * g["period"].map(PERIOD_WEIGHTS)).sum()
            ),
            **{f"role_{yr}": role_by_year.get(yr) for yr in YEARS},
        })
    return pd.DataFrame(rows)


def capacity_transition_summary(results, meta):
    """Summarize lifetime-aware capacity roles for the full plant fleet."""
    transitions = plant_role_transition(results, meta)
    if transitions.empty:
        return transitions

    transitions = transitions.copy()
    transitions["capacity"] = pd.to_numeric(transitions["capacity"], errors="coerce")
    transitions["annual_capacity_kt_per_year"] = (
        transitions["capacity"] * CAPACITY_T_DAY_TO_KT_YR
    )
    transitions["has_same_site_renewal"] = (
        transitions["same_site_renewal_year"].notna().astype(int)
    )
    transitions["has_commercial_ccs"] = (
        transitions["first_commercial_ccs_year"].notna().astype(int)
    )

    grouped = transitions.groupby("capacity_status", dropna=False).agg(
        plants=("plant_id", "nunique"),
        capacity_t_per_day=("capacity", "sum"),
        mean_capacity_t_per_day=("capacity", "mean"),
        capacity_kt_per_year=("annual_capacity_kt_per_year", "sum"),
        mean_capacity_kt_per_year=("annual_capacity_kt_per_year", "mean"),
        mean_age_2025=("age_2025", "mean"),
        median_age_2025=("age_2025", "median"),
        mean_remaining_model_life_2025=("remaining_model_life_2025", "mean"),
        renewed_plants=("has_same_site_renewal", "sum"),
        commercial_ccs_plants=("has_commercial_ccs", "sum"),
        productive_plants_2060=("productive_2060", "sum"),
        cumulative_commercial_capture_kt_year=(
            "cumulative_commercial_capture_kt_year",
            "sum",
        ),
    ).reset_index()

    fleet_plants = transitions["plant_id"].nunique()
    fleet_capacity = transitions["annual_capacity_kt_per_year"].sum()
    fleet_capture = transitions["cumulative_commercial_capture_kt_year"].sum()
    grouped["plant_share"] = grouped["plants"] / max(fleet_plants, 1)
    grouped["capacity_share"] = grouped["capacity_kt_per_year"] / max(
        fleet_capacity,
        1e-9,
    )
    grouped["commercial_capture_share"] = (
        grouped["cumulative_commercial_capture_kt_year"] / max(fleet_capture, 1e-9)
    )
    return grouped.sort_values(
        ["productive_plants_2060", "plants"],
        ascending=[False, False],
    ).reset_index(drop=True)


def role_summary_by_period(results, meta):
    roles = plant_role_classification(results, meta)
    if roles.empty:
        return roles
    grouped = roles.groupby(["period", "role"], dropna=False).agg(
        plants=("plant_id", "nunique"),
        operating_plants=("operating", "sum"),
        capacity=("capacity", "sum"),
        gross_direct_emission_kt=("gross_direct_emission_kt", "sum"),
        captured_commercial_kt=("captured_commercial_kt", "sum"),
        captured_total_kt=("captured_total_kt", "sum"),
        residual_after_capture_kt=("residual_after_capture_kt", "sum"),
        avg_af_share=("af_share", "mean"),
        avg_front_end_index=("front_end_index", "mean"),
    ).reset_index()
    totals = grouped.groupby("period").agg(
        total_plants=("plants", "sum"),
        total_capacity=("capacity", "sum"),
        total_gross=("gross_direct_emission_kt", "sum"),
    ).reset_index()
    grouped = grouped.merge(totals, on="period", how="left")
    grouped["plant_share"] = grouped["plants"] / grouped["total_plants"].replace(0, np.nan)
    grouped["capacity_share"] = grouped["capacity"] / grouped["total_capacity"].replace(0, np.nan)
    grouped["gross_emission_share"] = grouped["gross_direct_emission_kt"] / grouped["total_gross"].replace(0, np.nan)
    return grouped.fillna({"plant_share": 0.0, "capacity_share": 0.0, "gross_emission_share": 0.0})


def province_role_summary(results, meta):
    roles = plant_role_classification(results, meta)
    if roles.empty:
        return roles
    grouped = roles.groupby(["province", "period", "role"], dropna=False).agg(
        plants=("plant_id", "nunique"),
        operating_plants=("operating", "sum"),
        capacity=("capacity", "sum"),
        gross_direct_emission_kt=("gross_direct_emission_kt", "sum"),
        captured_commercial_kt=("captured_commercial_kt", "sum"),
        residual_after_capture_kt=("residual_after_capture_kt", "sum"),
        avg_af_share=("af_share", "mean"),
        avg_front_end_index=("front_end_index", "mean"),
    ).reset_index().rename(columns={"province": "province_cn"})
    idx = grouped.groupby(["province_cn", "period"])["gross_direct_emission_kt"].idxmax()
    dominant = grouped.loc[idx, ["province_cn", "period", "role"]].rename(columns={"role": "dominant_role_by_gross"})
    grouped = grouped.merge(dominant, on=["province_cn", "period"], how="left")
    return grouped


def scenario_summary(results, scenario):
    nat = national_summary(results)
    final = nat[nat["year"] == nat["year"].max()].iloc[0].to_dict() if not nat.empty else {}
    total = results.get("cost_breakdown_total", {})
    cumulative = results.get("cumulative_budget", {})
    solver = results.get("solver") or {}
    return pd.DataFrame([{
        "scenario": scenario,
        "status": results.get("status"),
        "solver_status": solver.get("status"),
        "solver_term_cond": solver.get("term_cond"),
        "solver_profile": solver.get("profile"),
        "solve_time_s": solver.get("solve_time_s"),
        "mip_gap": solver.get("mip_gap"),
        "objective_value_kCNY": solver.get("objective_value"),
        "objective_bound_kCNY": solver.get("objective_bound"),
        "node_count": solver.get("node_count"),
        "solution_count": solver.get("solution_count"),
        "time_limit_s": (solver.get("options") or {}).get("TimeLimit"),
        "threads": (solver.get("options") or {}).get("Threads"),
        "emission_target_mode": results.get("emission_target_mode"),
        "cumulative_budget_enabled": cumulative.get("enabled"),
        "cumulative_reduction_target": cumulative.get("reduction_target"),
        "cumulative_actual_reduction": cumulative.get("actual_reduction"),
        "total_cost_kCNY": results.get("total_cost_kCNY", results.get("total_cost")),
        "real_cost_kCNY": results.get("real_cost_kCNY"),
        "cost_boundary": results.get("cost_boundary"),
        "include_full_fuel_cost_in_objective": results.get("include_full_fuel_cost_in_objective"),
        "include_carbon_cost_in_objective": results.get("include_carbon_cost_in_objective"),
        "demand_scenario": results.get("demand_scenario"),
        "objective_gap_kCNY": total.get("objective_gap_kCNY"),
        "final_year": final.get("year"),
        "final_net_co2_kt": final.get("net_co2_kt"),
        "final_gross_co2_kt": final.get("gross_co2_kt"),
        "final_capture_kt": final.get("captured_co2_kt"),
        "final_af_rate": final.get("national_af_rate"),
        "final_arm_rate": final.get("avg_arm_realized"),
        "final_clinker_ratio": final.get("effective_clinker_ratio"),
        "final_ccs_active_plants": final.get("n_plants_ccs_active"),
        "total_slack_kt": results.get("total_slack_kt"),
    }])


def solver_diagnostics(results, scenario):
    solver = results.get("solver") or {}
    options = solver.get("options") or {}
    cumulative = results.get("cumulative_budget", {}) or {}
    return pd.DataFrame([{
        "scenario": scenario,
        "status": results.get("status"),
        "solver_status": solver.get("status"),
        "solver_term_cond": solver.get("term_cond"),
        "solver_name": solver.get("name"),
        "solver_profile": solver.get("profile"),
        "objective_value_kCNY": solver.get("objective_value"),
        "objective_bound_kCNY": solver.get("objective_bound"),
        "mip_gap": solver.get("mip_gap"),
        "solve_time_s": solver.get("solve_time_s"),
        "node_count": solver.get("node_count"),
        "iteration_count": solver.get("iteration_count"),
        "solution_count": solver.get("solution_count"),
        "mip_gap_target": options.get("MIPGap"),
        "time_limit_s": options.get("TimeLimit"),
        "threads": options.get("Threads"),
        "mip_focus": options.get("MIPFocus"),
        "heuristics": options.get("Heuristics"),
        "presolve": options.get("Presolve"),
        "cuts": options.get("Cuts"),
        "cumulative_reduction_target": cumulative.get("reduction_target"),
        "cumulative_actual_reduction": cumulative.get("actual_reduction"),
        "cumulative_slack_kt_year": cumulative.get("slack_kt_year"),
        "total_slack_kt": results.get("total_slack_kt"),
    }])


def build_tables(results, scenario, meta=None):
    """Build V3-style tables from compact V4 JSON."""
    if not has_incumbent_solution(results):
        return {
            "scenario_summary": scenario_summary(results, scenario),
            "solver_diagnostics": solver_diagnostics(results, scenario),
        }
    meta = _load_plant_metadata() if meta is None else meta
    cap, prov, _ = _plant_meta_maps(meta)
    return {
        "national_summary": national_summary(results),
        "plant_summary": plant_summary(results, cap),
        "provincial_summary": provincial_summary(results, prov),
        "scenario_summary": scenario_summary(results, scenario),
        "solver_diagnostics": solver_diagnostics(results, scenario),
        "industry_tech": industry_tech(results),
        "ccs_decisions": ccs_decisions(results, meta),
        "same_site_renewal_decisions": same_site_renewal_decisions(results, meta),
        "operation_status": operation_status(results, meta),
        "emissions": emissions(results),
        "emission_contribution": emission_contribution(results, meta),
        "province_emission_contribution": province_emission_contribution(results, meta),
        "co2_flows": co2_flows(results),
        "ccs_transport_storage": ccs_transport_storage(results),
        "storage_utilization": storage_utilization(results),
        "ccs_learning": ccs_learning(results),
        "costs": costs(results),
        "af_plant_shares": af_plant_shares(results, meta),
        "af_resource_utilization": af_resource_utilization(results),
        "novel_lcc_realization": novel_lcc_realization(results),
        "province_arm": province_arm(results),
        "observed_initial_ccs_projects": observed_initial_ccs_projects(results),
        "observed_pilot_ccs": observed_pilot_ccs(results),
        "production_demand": production_demand(results),
        "ccs_plant_details": ccs_plant_details(results, meta),
        "plant_emission_balance": plant_emission_balance(results, meta),
        "residual_emissions_by_province": residual_emissions_by_province(results, meta),
        "province_frontend_ccs_bridge": province_frontend_ccs_bridge(results, meta),
        "national_frontend_ccs_bridge": national_frontend_ccs_bridge(results),
        "ccs_rollout_cap_check": ccs_rollout_cap_check(results, meta),
        "plant_role_classification": plant_role_classification(results, meta),
        "plant_role_transition": plant_role_transition(results, meta),
        "capacity_transition_summary": capacity_transition_summary(results, meta),
        "role_summary_by_period": role_summary_by_period(results, meta),
        "province_role_summary": province_role_summary(results, meta),
    }


def provincial_summary(results, province_map):
    """Wide province summary retained for existing V4 plotting helpers."""
    plants = results.get("plants", {})
    prov_data = {}
    for pid, pdata in plants.items():
        prov = province_map.get(str(pid), "unknown")
        prov_data.setdefault(prov, {"co2": {}, "x_af": {}, "z": {}})
        for yr in YEARS:
            s = str(yr)
            prov_data[prov]["co2"][s] = prov_data[prov]["co2"].get(s, 0.0) + _num(_plant_value(pdata, "co2_net", yr))
            prov_data[prov]["x_af"].setdefault(s, [])
            prov_data[prov]["z"][s] = prov_data[prov]["z"].get(s, 0) + int(round(_num(_plant_value(pdata, "z", yr))))
            if int(round(_num(_plant_value(pdata, "y", yr)))):
                prov_data[prov]["x_af"][s].append(_num(_plant_value(pdata, "x_af", yr)))
    rows = []
    for prov, data in prov_data.items():
        row = {"province": prov}
        for yr in [2025, 2030, 2040, 2050, 2060]:
            s = str(yr)
            row[f"co2_{yr}"] = round(_num(data["co2"].get(s)) / 1000.0, 4)
            xaf_vals = data["x_af"].get(s, [])
            row[f"avg_x_af_{yr}"] = round(float(np.mean(xaf_vals)), 4) if xaf_vals else 0.0
            row[f"n_ccs_{yr}"] = data["z"].get(s, 0)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("province") if rows else pd.DataFrame()


def _summary_json(results, scenario):
    """Compact summary JSON compatible with V3 manifest-based readers."""
    return {
        "scenario": scenario,
        "status": results.get("status"),
        "solver": results.get("solver", {}),
        "model_structure": {
            "version": "v4",
            "demand_scenario": results.get("demand_scenario"),
            "emission_target_mode": results.get("emission_target_mode"),
            "cost_boundary": results.get("cost_boundary"),
            "include_full_fuel_cost_in_objective": results.get("include_full_fuel_cost_in_objective"),
            "include_carbon_cost_in_objective": results.get("include_carbon_cost_in_objective"),
        },
        "cost_unit_note": results.get("cost_unit_note"),
        "discounted_total_cost": results.get("total_cost_kCNY", results.get("total_cost")),
        "discounted_system_cost": results.get("real_cost_kCNY", results.get("total_cost_kCNY")),
        "discounted_carbon_cost": (
            (results.get("cost_breakdown_total", {}).get("diagnostics_discounted_kCNY", {}) or {}).get("carbon", 0.0)
        ),
        "cost_breakdown": results.get("cost_breakdown_total", {}),
        "emissions": {
            "baseline_2025": results.get("baseline_2025_co2_kt"),
            "initial_total": results.get("endo_baseline_2025_co2_kt"),
            "cumulative_budget": results.get("cumulative_budget", {}),
        },
        "annual_summary": results.get("summary", {}),
        "observed_initial_ccs_projects": results.get("observed_initial_ccs_projects", {}),
    }


def save_scenario_outputs(results, output_dir, scenario, prefix="full"):
    """
    Save one scenario as V3-style tables.

    Output structure:
      <output_dir>/<scenario>/data/<table>.csv
      <output_dir>/<scenario>/full_<table>.csv
      <output_dir>/<scenario>/summary/summary.json
      <output_dir>/<scenario>/results_manifest.json
    """
    output_dir = Path(output_dir)
    sc_dir = output_dir / scenario
    data_dir = sc_dir / "data"
    summary_dir = sc_dir / "summary"
    data_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    # Avoid mixing stale tables from a previous solved run with a current
    # time-limit/no-incumbent diagnostic package.
    for old_csv in data_dir.glob("*.csv"):
        old_csv.unlink()
    for old_csv in sc_dir.glob(f"{prefix}_*.csv"):
        old_csv.unlink()

    tables = build_tables(results, scenario)
    table_paths = {}
    for key, df in tables.items():
        if df is None:
            continue
        if not isinstance(df, pd.DataFrame):
            continue
        if df.empty and len(df.columns) == 0 and key in DEFAULT_COLUMNS:
            df = pd.DataFrame(columns=DEFAULT_COLUMNS[key])
        data_path = data_dir / f"{key}.csv"
        df.to_csv(data_path, index=False)
        table_paths[key] = str(data_path.relative_to(sc_dir))
        legacy_path = sc_dir / f"{prefix}_{key}.csv"
        df.to_csv(legacy_path, index=False)

    summary = _summary_json(results, scenario)
    with open(summary_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(sc_dir / f"{prefix}_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    manifest = {
        "scenario": scenario,
        "model_version": "v4",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_json": f"../{scenario}_results.json",
        "summary": "summary/summary.json",
        "tables": table_paths,
        "legacy_prefix": prefix,
        "notes": [
            "Tables are derived from compact V4 result JSON; no model logic is changed.",
            "Costs are kCNY unless field names explicitly say CNY.",
            "CO2 quantities are kt unless field names explicitly say Mt.",
            "Plant capacity fields retain explicit t/day or annual kt/year suffixes.",
            "Plant-role tables are heuristic diagnostics; they do not implement the final backbone rule and their front_end_index is not a raw resource-endowment index.",
        ],
    }
    with open(sc_dir / "results_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return sc_dir


def save_all_csvs(results_dir, output_dir=None):
    """Load all available compact V4 JSON files and save comprehensive CSV packages."""
    results_dir = Path(results_dir)
    output_dir = Path(output_dir or results_dir)
    valid = {s: r for s, r in load_all_results(results_dir).items() if r is not None}
    if not valid:
        print(f"  No results found in {results_dir}")
        return
    for scenario, results in valid.items():
        sc_dir = save_scenario_outputs(results, output_dir, scenario)
        print(f"  {scenario}: saved V3-style outputs to {sc_dir}")

    cross_dir = output_dir / "cross_scenario"
    cross_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    annual = []
    role_rows = []
    meta = _load_plant_metadata()
    for scenario, results in valid.items():
        ssum = scenario_summary(results, scenario)
        if not ssum.empty:
            summaries.append(ssum)
        if not has_incumbent_solution(results):
            print(f"  {scenario}: no incumbent solution; skipped annual and role cross-scenario tables.")
            continue
        nat = national_summary(results)
        if not nat.empty:
            keep = [
                "year", "gross_co2_kt", "net_co2_kt", "captured_co2_kt",
                "commercial_captured_co2_kt", "national_af_rate", "avg_arm_realized",
                "effective_clinker_ratio", "ee_rate", "n_plants_ccs_active",
                "ccs_design_capacity_kt", "cement_demand_mt",
            ]
            annual.append(nat[[c for c in keep if c in nat.columns]].assign(scenario=scenario))
        role = role_summary_by_period(results, meta)
        if not role.empty:
            role_rows.append(role.assign(scenario=scenario))

    if summaries:
        comp = pd.concat(summaries, ignore_index=True)
        comp.to_csv(cross_dir / "scenario_comparison_summary.csv", index=False)
        if "S1_baseline" in set(comp["scenario"]):
            ref = comp[comp["scenario"] == "S1_baseline"].iloc[0]
            delta_rows = []
            for _, row in comp.iterrows():
                out = {"scenario": row["scenario"], "reference": "S1_baseline"}
                for col in [
                    "total_cost_kCNY", "real_cost_kCNY", "final_net_co2_kt",
                    "final_gross_co2_kt", "final_capture_kt", "final_af_rate",
                    "final_arm_rate", "final_clinker_ratio", "final_ccs_active_plants",
                    "cumulative_actual_reduction",
                ]:
                    if col in comp.columns:
                        out[f"{col}_value"] = row.get(col)
                        out[f"{col}_delta_vs_s1"] = _num(row.get(col), np.nan) - _num(ref.get(col), np.nan)
                delta_rows.append(out)
            pd.DataFrame(delta_rows).to_csv(cross_dir / "scenario_delta_vs_s1.csv", index=False)

    if annual:
        annual_df = pd.concat(annual, ignore_index=True)
        cols = ["scenario"] + [c for c in annual_df.columns if c != "scenario"]
        annual_df[cols].to_csv(cross_dir / "scenario_annual_technology_emissions.csv", index=False)

    if role_rows:
        role_df = pd.concat(role_rows, ignore_index=True)
        cols = ["scenario"] + [c for c in role_df.columns if c != "scenario"]
        role_df[cols].to_csv(cross_dir / "scenario_role_summary_by_period.csv", index=False)

    if summaries or annual or role_rows:
        with open(cross_dir / "README.md", "w", encoding="utf-8") as f:
            f.write(
                "# Cross-scenario outputs\n\n"
                "These tables are derived from per-scenario compact V4 JSON files. "
                "They are intended for the paper storyline: comparing policy settings, "
                "technology portfolios, residual emissions, CCS burden, and plant-role "
                "composition across scenarios.\n"
            )
        print(f"  cross-scenario: saved comparison tables to {cross_dir}")


if __name__ == "__main__":
    import sys

    results_dir = sys.argv[1] if len(sys.argv) > 1 else str(PROJECT_ROOT / "results" / "v4" / "results_v4")
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    save_all_csvs(results_dir, output_dir)
