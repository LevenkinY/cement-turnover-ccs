"""Cross-scenario CCS backbone plant analysis for v4 results.

The module reads saved scenario CSV outputs and derives plant-level backbone
signals, tier labels, province summaries, and a short markdown interpretation.
It is intentionally downstream of optimization and does not modify model
outputs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from src_v5.config_v5 import PERIOD_WEIGHTS, PROJECT_ROOT


SCENARIOS = [
    "S1_baseline",
    "S2_front_end",
    "S3_all_spatial_equalized",
    "S4_storage_300km",
    "S5_offshore_parity",
]

SCENARIO_SHORT = {
    "S1_baseline": "s1",
    "S2_front_end": "s2",
    "S3_all_spatial_equalized": "s3",
    "S4_storage_300km": "s4",
    "S5_offshore_parity": "s5",
}

LATE_YEARS = [2050, 2055, 2060]
@dataclass(frozen=True)
class BackboneThresholds:
    cumulative_capture_kt_year: float = 5_000.0
    active_capture_kt: float = 100.0
    min_late_active_periods: int = 2
    min_signal_scenarios: int = 3


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return pd.read_csv(path)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if float(den) else 0.0


def _weighted_avg(values: pd.Series, weights: pd.Series) -> float:
    weights = _num(weights)
    values = _num(values)
    total = weights.sum()
    if total <= 0:
        return 0.0
    return float((values * weights).sum() / total)


def _load_cluster_assignment() -> pd.DataFrame:
    path = PROJECT_ROOT / "data/model_input/plants/cluster_assignment.csv"
    if not path.exists():
        return pd.DataFrame(columns=["plant_id", "cluster_id", "hub_plant_idx", "is_hub", "dist_to_hub_km"])
    clusters = pd.read_csv(path)
    keep = ["plant_id", "cluster_id", "hub_plant_idx", "is_hub", "dist_to_hub_km"]
    for col in keep:
        if col not in clusters.columns:
            clusters[col] = np.nan
    return clusters[keep]


def _scenario_dir(results_dir: Path, scenario: str) -> Path:
    return results_dir / scenario / "data"


def _scenario_status(results_dir: Path, scenario: str) -> dict:
    summary = _read_csv(_scenario_dir(results_dir, scenario) / "scenario_summary.csv")
    row = summary.iloc[0].to_dict()
    prefix = SCENARIO_SHORT[scenario]
    return {
        "scenario": scenario,
        "status": row.get("status"),
        "solver_term_cond": row.get("solver_term_cond"),
        "solve_time_s": row.get("solve_time_s"),
        "mip_gap": row.get("mip_gap"),
        "final_capture_mt": _safe_div(row.get("final_capture_kt", 0.0), 1000.0),
        "final_ccs_active_plants": row.get("final_ccs_active_plants"),
        "final_af_rate": row.get("final_af_rate"),
        "final_clinker_ratio": row.get("final_clinker_ratio"),
        f"{prefix}_scenario": scenario,
    }


def _load_storage_metrics(results_dir: Path, scenario: str) -> pd.DataFrame:
    prefix = SCENARIO_SHORT[scenario]
    flows_path = _scenario_dir(results_dir, scenario) / "co2_flows.csv"
    if not flows_path.exists():
        return pd.DataFrame(columns=["cluster_id"])

    flows = pd.read_csv(flows_path)
    if flows.empty:
        return pd.DataFrame(columns=["cluster_id"])
    flows["flow_kt"] = _num(flows.get("flow_kt", flows.get("flow", 0.0))).clip(lower=0.0)
    flows["distance_km"] = _num(flows.get("distance_km", flows.get("distance", 0.0)))
    flows["period_weight_years"] = _num(flows["period"].map(PERIOD_WEIGHTS))
    flows["weighted_flow_kt_year"] = flows["flow_kt"] * flows["period_weight_years"]
    flows["is_offshore"] = flows.get("is_offshore", False).astype(bool)
    flows["type"] = flows.get("type", "").astype(str).str.upper()

    rows = []
    for cluster_id, group in flows.groupby("cluster_id", dropna=False):
        total_flow = float(group["weighted_flow_kt_year"].sum())
        offshore_flow = float(group.loc[group["is_offshore"], "weighted_flow_kt_year"].sum())
        dsa_flow = float(group.loc[group["type"].eq("DSA"), "weighted_flow_kt_year"].sum())
        eor_flow = float(group.loc[group["type"].eq("EOR"), "weighted_flow_kt_year"].sum())
        rows.append({
            "cluster_id": cluster_id,
            f"{prefix}_cluster_flow_kt_year": total_flow,
            f"{prefix}_cluster_avg_storage_distance_km": _weighted_avg(
                group["distance_km"], group["weighted_flow_kt_year"]
            ),
            f"{prefix}_cluster_offshore_share": _safe_div(offshore_flow, total_flow),
            f"{prefix}_cluster_dsa_share": _safe_div(dsa_flow, total_flow),
            f"{prefix}_cluster_eor_share": _safe_div(eor_flow, total_flow),
        })
    return pd.DataFrame(rows)


def _load_scenario_plant_metrics(
    results_dir: Path,
    scenario: str,
    thresholds: BackboneThresholds,
) -> pd.DataFrame:
    prefix = SCENARIO_SHORT[scenario]
    scen_dir = _scenario_dir(results_dir, scenario)
    transition = _read_csv(scen_dir / "plant_role_transition.csv")
    roles = _read_csv(scen_dir / "plant_role_classification.csv")
    ccs = _read_csv(scen_dir / "ccs_plant_details.csv")

    base_cols = [
        "plant_id",
        "plant_idx",
        "province",
        "city",
        "location_tier",
        "arm_corridor",
        "capacity",
        "first_active_year",
        "last_active_year",
        "first_commercial_ccs_year",
        "first_front_end_year",
        "terminal_role",
        "cumulative_gross_direct_kt_year",
        "cumulative_residual_kt_year",
    ]
    for col in base_cols:
        if col not in transition.columns:
            transition[col] = np.nan
    plant = transition[base_cols].copy()

    ccs["captured_commercial"] = _num(ccs["captured_commercial"])
    ccs["period_weight_years"] = _num(ccs["period"].map(PERIOD_WEIGHTS))
    ccs["weighted_capture_kt_year"] = ccs["captured_commercial"] * ccs["period_weight_years"]
    ccs["commercial_ccs_installed"] = _num(ccs.get("commercial_ccs_installed", 0.0))
    ccs["k_ccs_kt"] = _num(ccs.get("k_ccs_kt", 0.0))

    ccs_agg = ccs.groupby("plant_id", as_index=False).agg(
        cumulative_capture_kt_year=("weighted_capture_kt_year", "sum"),
        active_capture_periods=("captured_commercial", lambda x: int((x >= thresholds.active_capture_kt).sum())),
        peak_capture_kt=("captured_commercial", "max"),
        max_k_ccs_kt=("k_ccs_kt", "max"),
    )
    late = (
        ccs[ccs["period"].isin(LATE_YEARS)]
        .groupby("plant_id")["captured_commercial"]
        .apply(lambda x: int((x >= thresholds.active_capture_kt).sum()))
        .rename("late_active_periods")
        .reset_index()
    )
    cap2060 = (
        ccs[ccs["period"].eq(2060)][["plant_id", "captured_commercial"]]
        .rename(columns={"captured_commercial": "capture_2060_kt"})
    )
    first_material = (
        ccs[ccs["captured_commercial"].ge(thresholds.active_capture_kt)]
        .groupby("plant_id")["period"]
        .min()
        .rename("first_material_ccs_year")
        .reset_index()
    )
    ccs_agg = (
        ccs_agg.merge(late, on="plant_id", how="outer")
        .merge(cap2060, on="plant_id", how="outer")
        .merge(first_material, on="plant_id", how="outer")
    )

    for col in [
        "cumulative_capture_kt_year",
        "active_capture_periods",
        "peak_capture_kt",
        "max_k_ccs_kt",
        "late_active_periods",
        "capture_2060_kt",
    ]:
        ccs_agg[col] = _num(ccs_agg[col])

    roles = roles.copy()
    for col in [
        "front_end_index",
        "af_share",
        "arm_realized",
        "lcc_clinker_ratio_reduction",
        "effective_clinker_ratio",
        "gross_direct_emission_kt",
        "captured_commercial_kt",
        "residual_after_capture_kt",
    ]:
        if col not in roles.columns:
            roles[col] = 0.0
        roles[col] = _num(roles[col])

    role_2060 = roles[roles["period"].eq(2060)][[
        "plant_id",
        "front_end_index",
        "af_share",
        "arm_realized",
        "lcc_clinker_ratio_reduction",
        "effective_clinker_ratio",
        "residual_after_capture_kt",
    ]].rename(columns={
        "front_end_index": "front_end_index_2060",
        "af_share": "af_share_2060",
        "arm_realized": "arm_realized_2060",
        "lcc_clinker_ratio_reduction": "lcc_reduction_2060",
        "effective_clinker_ratio": "effective_clinker_ratio_2060",
        "residual_after_capture_kt": "residual_after_capture_2060_kt",
    })
    role_avg = roles.groupby("plant_id", as_index=False).agg(
        avg_front_end_index=("front_end_index", "mean"),
        avg_af_share=("af_share", "mean"),
        avg_arm_realized=("arm_realized", "mean"),
        avg_lcc_reduction=("lcc_clinker_ratio_reduction", "mean"),
    )

    plant = (
        plant.merge(ccs_agg, on="plant_id", how="left")
        .merge(role_2060, on="plant_id", how="left")
        .merge(role_avg, on="plant_id", how="left")
    )
    fill_cols = [
        "cumulative_capture_kt_year",
        "active_capture_periods",
        "peak_capture_kt",
        "max_k_ccs_kt",
        "late_active_periods",
        "capture_2060_kt",
        "front_end_index_2060",
        "af_share_2060",
        "arm_realized_2060",
        "lcc_reduction_2060",
        "effective_clinker_ratio_2060",
        "residual_after_capture_2060_kt",
        "avg_front_end_index",
        "avg_af_share",
        "avg_arm_realized",
        "avg_lcc_reduction",
    ]
    for col in fill_cols:
        plant[col] = _num(plant[col])

    plant["backbone_signal"] = (
        plant["cumulative_capture_kt_year"].ge(thresholds.cumulative_capture_kt_year)
        & plant["late_active_periods"].ge(thresholds.min_late_active_periods)
        & plant["capture_2060_kt"].ge(thresholds.active_capture_kt)
    )

    rename = {
        col: f"{prefix}_{col}"
        for col in plant.columns
        if col not in ["plant_id", "plant_idx", "province", "city", "location_tier", "arm_corridor", "capacity"]
    }
    return plant.rename(columns=rename)


def _merge_scenario_metrics(results_dir: Path, thresholds: BackboneThresholds) -> pd.DataFrame:
    frames = [
        _load_scenario_plant_metrics(results_dir, scenario, thresholds)
        for scenario in SCENARIOS
    ]

    base = frames[0]
    meta_cols = ["plant_id", "plant_idx", "province", "city", "location_tier", "arm_corridor", "capacity"]
    out = base.copy()
    for frame in frames[1:]:
        out = out.merge(
            frame.drop(columns=[c for c in meta_cols[1:] if c in frame.columns]),
            on="plant_id",
            how="outer",
        )

    clusters = _load_cluster_assignment()
    out = out.merge(clusters, on="plant_id", how="left")
    for scenario in SCENARIOS:
        storage = _load_storage_metrics(results_dir, scenario)
        if not storage.empty:
            out = out.merge(storage, on="cluster_id", how="left")

    for col in out.columns:
        if col.endswith("_backbone_signal"):
            out[col] = out[col].fillna(False).astype(bool)
        elif any(token in col for token in ["capture", "front_end", "af_share", "arm_", "lcc_", "distance", "flow", "share", "residual"]):
            if col not in ["arm_corridor"]:
                out[col] = _num(out[col])

    return out


def _classify_plants(df: pd.DataFrame, thresholds: BackboneThresholds) -> pd.DataFrame:
    df = df.copy()
    signal_cols = [f"{SCENARIO_SHORT[s]}_backbone_signal" for s in SCENARIOS]
    for col in signal_cols:
        if col not in df.columns:
            df[col] = False
    df["backbone_signal_count"] = df[signal_cols].sum(axis=1).astype(int)

    df["core_ccs_backbone"] = (
        df["s1_backbone_signal"]
        & df["backbone_signal_count"].ge(thresholds.min_signal_scenarios)
    )
    df["strict_storage_backbone"] = (
        df["core_ccs_backbone"]
        & df["s4_backbone_signal"]
        & df["s5_backbone_signal"]
    )
    df["storage_sensitive_backbone"] = df["core_ccs_backbone"] & ~df["s4_backbone_signal"]
    df["front_end_contingent_ccs"] = ~df["s1_backbone_signal"] & df["s2_backbone_signal"]

    df["s2_minus_s1_cum_capture_mt"] = (
        df["s2_cumulative_capture_kt_year"] - df["s1_cumulative_capture_kt_year"]
    ) / 1000.0
    df["s2_minus_s1_capture_2060_mt"] = (
        df["s2_capture_2060_kt"] - df["s1_capture_2060_kt"]
    ) / 1000.0
    df["s4_minus_s1_cum_capture_mt"] = (
        df["s4_cumulative_capture_kt_year"] - df["s1_cumulative_capture_kt_year"]
    ) / 1000.0
    df["s5_minus_s1_cum_capture_mt"] = (
        df["s5_cumulative_capture_kt_year"] - df["s1_cumulative_capture_kt_year"]
    ) / 1000.0

    df["s2_new_signal_vs_s1"] = ~df["s1_backbone_signal"] & df["s2_backbone_signal"]
    df["s4_lost_signal_vs_s1"] = df["s1_backbone_signal"] & ~df["s4_backbone_signal"]
    df["s5_new_signal_vs_s1"] = ~df["s1_backbone_signal"] & df["s5_backbone_signal"]
    df["s5_strengthened_vs_s1"] = (
        df["s5_backbone_signal"]
        & df["s5_minus_s1_cum_capture_mt"].ge(1.0)
    )
    df["offshore_enabled_candidate"] = df["s5_new_signal_vs_s1"] | df["s5_strengthened_vs_s1"]

    df["front_end_contingent_storage_robust"] = (
        df["front_end_contingent_ccs"] & df["s4_backbone_signal"]
    )
    df["front_end_contingent_offshore_enabled"] = (
        df["front_end_contingent_ccs"] & df["s5_backbone_signal"]
    )

    conditions = [
        df["strict_storage_backbone"],
        df["storage_sensitive_backbone"],
        df["core_ccs_backbone"],
        df["front_end_contingent_ccs"],
        df["offshore_enabled_candidate"],
    ]
    choices = [
        "strict_storage_backbone",
        "storage_sensitive_backbone",
        "core_ccs_backbone",
        "front_end_contingent_ccs",
        "offshore_enabled_candidate",
    ]
    df["backbone_tier"] = np.select(conditions, choices, default="other")
    return df


def _plant_outputs(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_cols = [
        "plant_id",
        "plant_idx",
        "province",
        "city",
        "location_tier",
        "arm_corridor",
        "capacity",
        "cluster_id",
        "hub_plant_idx",
        "is_hub",
        "dist_to_hub_km",
        "backbone_tier",
        "core_ccs_backbone",
        "strict_storage_backbone",
        "storage_sensitive_backbone",
        "front_end_contingent_ccs",
        "offshore_enabled_candidate",
        "backbone_signal_count",
    ]
    signal_cols = [f"{SCENARIO_SHORT[s]}_backbone_signal" for s in SCENARIOS]
    metric_cols = []
    for prefix in [SCENARIO_SHORT[s] for s in SCENARIOS]:
        metric_cols.extend([
            f"{prefix}_first_commercial_ccs_year",
            f"{prefix}_first_material_ccs_year",
            f"{prefix}_last_active_year",
            f"{prefix}_cumulative_capture_kt_year",
            f"{prefix}_capture_2060_kt",
            f"{prefix}_late_active_periods",
            f"{prefix}_front_end_index_2060",
            f"{prefix}_af_share_2060",
            f"{prefix}_arm_realized_2060",
            f"{prefix}_lcc_reduction_2060",
            f"{prefix}_cluster_avg_storage_distance_km",
            f"{prefix}_cluster_offshore_share",
            f"{prefix}_cluster_flow_kt_year",
        ])
    delta_cols = [
        "s2_minus_s1_cum_capture_mt",
        "s2_minus_s1_capture_2060_mt",
        "s4_minus_s1_cum_capture_mt",
        "s5_minus_s1_cum_capture_mt",
        "s2_new_signal_vs_s1",
        "s4_lost_signal_vs_s1",
        "s5_new_signal_vs_s1",
        "s5_strengthened_vs_s1",
        "front_end_contingent_storage_robust",
        "front_end_contingent_offshore_enabled",
    ]
    cols = [c for c in base_cols + signal_cols + metric_cols + delta_cols if c in df.columns]
    full = df[cols].sort_values(
        ["core_ccs_backbone", "backbone_signal_count", "s1_cumulative_capture_kt_year"],
        ascending=[False, False, False],
    )
    core = full[full["core_ccs_backbone"]].copy()
    mechanism = full[
        full["core_ccs_backbone"]
        | full["front_end_contingent_ccs"]
        | full["offshore_enabled_candidate"]
        | full["s4_lost_signal_vs_s1"]
    ].copy()
    return full, core, mechanism


def _province_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for province, g in df.groupby("province", dropna=False):
        core = g[g["core_ccs_backbone"]]
        s1_signal = g[g["s1_backbone_signal"]]
        rows.append({
            "province": province,
            "plants": int(g["plant_id"].nunique()),
            "core_backbone_plants": int(core["plant_id"].nunique()),
            "strict_storage_backbone_plants": int(g["strict_storage_backbone"].sum()),
            "storage_sensitive_backbone_plants": int(g["storage_sensitive_backbone"].sum()),
            "front_end_contingent_plants": int(g["front_end_contingent_ccs"].sum()),
            "offshore_enabled_candidate_plants": int(g["offshore_enabled_candidate"].sum()),
            "s1_signal_plants": int(g["s1_backbone_signal"].sum()),
            "s2_signal_plants": int(g["s2_backbone_signal"].sum()),
            "s4_signal_plants": int(g["s4_backbone_signal"].sum()),
            "s5_signal_plants": int(g["s5_backbone_signal"].sum()),
            "s1_core_cum_capture_gt": float(core["s1_cumulative_capture_kt_year"].sum() / 1_000_000.0),
            "s1_core_capture_2060_mt": float(core["s1_capture_2060_kt"].sum() / 1000.0),
            "s4_retention_rate_among_core": float(core["s4_backbone_signal"].mean()) if len(core) else 0.0,
            "s5_retention_rate_among_core": float(core["s5_backbone_signal"].mean()) if len(core) else 0.0,
            "s2_new_signal_vs_s1_plants": int(g["s2_new_signal_vs_s1"].sum()),
            "s4_lost_signal_vs_s1_plants": int(g["s4_lost_signal_vs_s1"].sum()),
            "s5_new_signal_vs_s1_plants": int(g["s5_new_signal_vs_s1"].sum()),
            "avg_s1_front_end_index_2060_core": float(core["s1_front_end_index_2060"].mean()) if len(core) else 0.0,
            "avg_s1_cluster_distance_km_core": float(core["s1_cluster_avg_storage_distance_km"].mean()) if len(core) else 0.0,
            "avg_dist_to_hub_km_core": float(core["dist_to_hub_km"].mean()) if len(core) else 0.0,
            "s1_signal_to_core_rate": _safe_div(len(core), len(s1_signal)),
        })
    return pd.DataFrame(rows).sort_values(
        ["core_backbone_plants", "s1_core_cum_capture_gt"],
        ascending=[False, False],
    )


def _tier_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier, g in df.groupby("backbone_tier", dropna=False):
        rows.append({
            "backbone_tier": tier,
            "plants": int(g["plant_id"].nunique()),
            "s1_cum_capture_gt": float(g["s1_cumulative_capture_kt_year"].sum() / 1_000_000.0),
            "s1_capture_2060_mt": float(g["s1_capture_2060_kt"].sum() / 1000.0),
            "avg_signal_count": float(g["backbone_signal_count"].mean()) if len(g) else 0.0,
            "avg_s1_front_end_index_2060": float(g["s1_front_end_index_2060"].mean()) if len(g) else 0.0,
            "avg_s1_storage_distance_km": float(g["s1_cluster_avg_storage_distance_km"].mean()) if len(g) else 0.0,
            "avg_dist_to_hub_km": float(g["dist_to_hub_km"].mean()) if len(g) else 0.0,
        })
    order = {
        "strict_storage_backbone": 0,
        "storage_sensitive_backbone": 1,
        "core_ccs_backbone": 2,
        "front_end_contingent_ccs": 3,
        "offshore_enabled_candidate": 4,
        "other": 5,
    }
    out = pd.DataFrame(rows)
    out["_order"] = out["backbone_tier"].map(order).fillna(99)
    return out.sort_values("_order").drop(columns="_order")


def _mechanism_summary(df: pd.DataFrame) -> pd.DataFrame:
    core = df[df["core_ccs_backbone"]]
    front = df[df["front_end_contingent_ccs"]]
    sensitive = df[df["storage_sensitive_backbone"]]
    analysis_pool = df[df[[
        "s1_backbone_signal",
        "s2_backbone_signal",
        "s4_backbone_signal",
        "s5_backbone_signal",
    ]].any(axis=1)]

    def corr(x: str, y: str, data: pd.DataFrame = analysis_pool) -> float:
        if len(data) < 3:
            return 0.0
        a = pd.to_numeric(data[x], errors="coerce")
        b = pd.to_numeric(data[y], errors="coerce")
        if a.nunique(dropna=True) < 2 or b.nunique(dropna=True) < 2:
            return 0.0
        value = a.corr(b)
        return 0.0 if pd.isna(value) else float(value)

    return pd.DataFrame([{
        "core_backbone_plants": int(len(core)),
        "strict_storage_backbone_plants": int(df["strict_storage_backbone"].sum()),
        "storage_sensitive_backbone_plants": int(len(sensitive)),
        "front_end_contingent_plants": int(len(front)),
        "offshore_enabled_candidate_plants": int(df["offshore_enabled_candidate"].sum()),
        "front_end_contingent_s4_signal_share": float(front["s4_backbone_signal"].mean()) if len(front) else 0.0,
        "front_end_contingent_s5_signal_share": float(front["s5_backbone_signal"].mean()) if len(front) else 0.0,
        "avg_front_end_index_core": float(core["s1_front_end_index_2060"].mean()) if len(core) else 0.0,
        "avg_front_end_index_storage_sensitive": float(sensitive["s1_front_end_index_2060"].mean()) if len(sensitive) else 0.0,
        "avg_front_end_index_front_contingent": float(front["s1_front_end_index_2060"].mean()) if len(front) else 0.0,
        "corr_front_end_index_vs_s1_cum_capture": corr("s1_front_end_index_2060", "s1_cumulative_capture_kt_year"),
        "corr_front_end_index_vs_s2_delta_capture": corr("s1_front_end_index_2060", "s2_minus_s1_cum_capture_mt"),
        "corr_s2_delta_capture_vs_s4_signal": corr("s2_minus_s1_cum_capture_mt", "s4_backbone_signal"),
        "corr_s1_storage_distance_vs_s4_lost": corr("s1_cluster_avg_storage_distance_km", "s4_lost_signal_vs_s1"),
        "corr_dist_to_hub_vs_core": corr("dist_to_hub_km", "core_ccs_backbone", df),
    }])


def _top_provinces_text(province: pd.DataFrame, n: int = 8) -> str:
    top = province.head(n)
    return "; ".join(
        f"{row.province} {int(row.core_backbone_plants)}"
        for row in top.itertuples(index=False)
    )


def _format_cell(value) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, (np.floating,)):
        return f"{float(value):.3f}"
    if pd.isna(value):
        return ""
    return str(value)


def _markdown_table(df: pd.DataFrame) -> str:
    """Render a compact GitHub markdown table without optional dependencies."""
    if df.empty:
        return "_No rows._"
    headers = [str(c) for c in df.columns]
    rows = [[_format_cell(v) for v in row] for row in df.itertuples(index=False, name=None)]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _write_markdown(
    output_dir: Path,
    plant_full: pd.DataFrame,
    province: pd.DataFrame,
    tiers: pd.DataFrame,
    mechanism: pd.DataFrame,
    status: pd.DataFrame,
    thresholds: BackboneThresholds,
) -> Path:
    core = plant_full[plant_full["core_ccs_backbone"]]
    s1_total_capture_gt = plant_full["s1_cumulative_capture_kt_year"].sum() / 1_000_000.0
    core_capture_gt = core["s1_cumulative_capture_kt_year"].sum() / 1_000_000.0
    s1_2060_capture_mt = plant_full["s1_capture_2060_kt"].sum() / 1000.0
    core_2060_capture_mt = core["s1_capture_2060_kt"].sum() / 1000.0
    mech = mechanism.iloc[0].to_dict()

    if abs(mech["corr_s2_delta_capture_vs_s4_signal"]) >= 0.2:
        interaction = (
            "前端约束带来的 CCS 增量与 S4 保留存在一定相关性，说明前端不足更容易把责任推向"
            "封存条件仍可承接的厂群。"
        )
    else:
        interaction = (
            "前端资源与封存禀赋没有表现为强线性协同，更适合表述为双重筛选机制："
            "前端条件决定残余排放和 CCS 需求，封存禀赋决定这些需求能否稳定转化为长期捕集责任。"
        )

    lines = [
        "# CCS 骨干厂初步识别与机制分析",
        "",
        "## 识别规则",
        (
            f"厂级情景信号 `backbone_signal` 同时要求：累计商业捕集量 >= "
            f"{thresholds.cumulative_capture_kt_year / 1000:.1f} MtCO2；"
            f"{LATE_YEARS} 中至少 {thresholds.min_late_active_periods} 期商业捕集 "
            f">= {thresholds.active_capture_kt:.0f} ktCO2/yr；2060 年商业捕集 "
            f">= {thresholds.active_capture_kt:.0f} ktCO2/yr。"
        ),
        (
            f"核心骨干厂要求 S1 满足 `backbone_signal`，且五个情景中至少 "
            f"{thresholds.min_signal_scenarios} 个情景满足该信号。"
        ),
        "",
        "## 求解状态",
        _markdown_table(status[[
            "scenario",
            "status",
            "solver_term_cond",
            "solve_time_s",
            "mip_gap",
            "final_capture_mt",
            "final_ccs_active_plants",
        ]]),
        "",
        "## 主要发现",
        (
            f"- 识别出核心 CCS 骨干厂 {len(core)} 个。它们贡献 S1 累计商业捕集 "
            f"{core_capture_gt:.2f} GtCO2，占 S1 全部商业捕集的 "
            f"{core_capture_gt / s1_total_capture_gt:.1%}。"
        ),
        (
            f"- 到 2060 年，核心骨干厂捕集 {core_2060_capture_mt:.1f} MtCO2/yr，占 S1 "
            f"商业捕集的 {core_2060_capture_mt / s1_2060_capture_mt:.1%}，说明晚期捕集责任高度集中。"
        ),
        f"- 核心骨干厂数量最高的省份为：{_top_provinces_text(province)}。",
        (
            f"- 严格封存稳健骨干厂 {int(mech['strict_storage_backbone_plants'])} 个；"
            f"封存敏感型骨干厂 {int(mech['storage_sensitive_backbone_plants'])} 个。"
        ),
        (
            f"- 前端约束触发型厂 {int(mech['front_end_contingent_plants'])} 个，其 S1 2060 "
            f"平均前端指数为 {mech['avg_front_end_index_front_contingent']:.3f}，低于核心骨干厂均值 "
            f"{mech['avg_front_end_index_core']:.3f}。其中 "
            f"{mech['front_end_contingent_s4_signal_share']:.1%} 也满足 S4，"
            f"{mech['front_end_contingent_s5_signal_share']:.1%} 满足 S5。"
        ),
        (
            f"- S5 海上封存平价新增或强化的候选厂共 "
            f"{int(mech['offshore_enabled_candidate_plants'])} 个；其中未被更高优先级标签覆盖、"
            f"作为主标签呈现的 offshore-enabled 厂见 tier summary。"
        ),
        "",
        "## 机制解释",
        (
            "- 前端资源条件：S2 识别了 S1 下不构成骨干、但在 AF/ARM/LCC 等前端减排受限后转为 "
            "backbone-like 的厂。这些厂代表前端资源不足引致的额外 CCS 责任。"
        ),
        (
            "- 地理封存禀赋：S4 检验核心骨干是否能在 300 km 封存可达约束下保留；S5 检验海上封存"
            "成本下降是否扩展或强化沿海/近海 CCS 选择。"
        ),
        (
            f"- 二者关系：S2 捕集增量与 S4 是否保留的相关系数为 "
            f"{mech['corr_s2_delta_capture_vs_s4_signal']:.3f}，S1 集群封存距离与 S4 掉出的相关系数为 "
            f"{mech['corr_s1_storage_distance_vs_s4_lost']:.3f}。{interaction}"
        ),
        "",
        "## 分层汇总",
        _markdown_table(tiers),
        "",
        "## 输出文件",
        "- `plant_backbone_classification.csv`：全部厂的情景信号、分层标签和机制标记。",
        "- `core_backbone_plants.csv`：主结论使用的核心骨干厂名单。",
        "- `province_backbone_summary.csv`：省级骨干厂数量、捕集贡献和情景保留率。",
        "- `mechanism_diagnostics.csv`：厂级 S2/S4/S5 相对 S1 的变化和协同标记。",
        "- `mechanism_summary.csv`：全国层面的机制诊断指标。",
        "- `scenario_solver_status.csv`：用于结果解释的求解状态和终点指标。",
        "",
    ]

    path = output_dir / "backbone_preliminary_findings.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_analysis(
    results_dir: Path,
    output_dir: Path | None = None,
    thresholds: BackboneThresholds | None = None,
) -> dict[str, Path]:
    thresholds = thresholds or BackboneThresholds()
    results_dir = Path(results_dir)
    output_dir = Path(output_dir or results_dir / "cross_scenario" / "backbone_analysis")
    output_dir.mkdir(parents=True, exist_ok=True)

    status = pd.DataFrame([_scenario_status(results_dir, scenario) for scenario in SCENARIOS])
    plants = _merge_scenario_metrics(results_dir, thresholds)
    plants = _classify_plants(plants, thresholds)
    plant_full, core, mechanism = _plant_outputs(plants)
    province = _province_summary(plants)
    tiers = _tier_summary(plants)
    mechanism_summary = _mechanism_summary(plants)

    paths = {
        "plant_backbone_classification": output_dir / "plant_backbone_classification.csv",
        "core_backbone_plants": output_dir / "core_backbone_plants.csv",
        "province_backbone_summary": output_dir / "province_backbone_summary.csv",
        "mechanism_diagnostics": output_dir / "mechanism_diagnostics.csv",
        "tier_summary": output_dir / "tier_summary.csv",
        "mechanism_summary": output_dir / "mechanism_summary.csv",
        "scenario_solver_status": output_dir / "scenario_solver_status.csv",
    }

    plant_full.to_csv(paths["plant_backbone_classification"], index=False, encoding="utf-8-sig")
    core.to_csv(paths["core_backbone_plants"], index=False, encoding="utf-8-sig")
    province.to_csv(paths["province_backbone_summary"], index=False, encoding="utf-8-sig")
    mechanism.to_csv(paths["mechanism_diagnostics"], index=False, encoding="utf-8-sig")
    tiers.to_csv(paths["tier_summary"], index=False, encoding="utf-8-sig")
    mechanism_summary.to_csv(paths["mechanism_summary"], index=False, encoding="utf-8-sig")
    status.to_csv(paths["scenario_solver_status"], index=False, encoding="utf-8-sig")
    paths["markdown_findings"] = _write_markdown(
        output_dir, plant_full, province, tiers, mechanism_summary, status, thresholds
    )

    return paths


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=PROJECT_ROOT / "results/v4/results_v4_finalcheck",
        help="Directory containing S1-S5 scenario result folders.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to <results-dir>/cross_scenario/backbone_analysis.",
    )
    parser.add_argument("--cum-threshold-kt", type=float, default=5_000.0)
    parser.add_argument("--active-threshold-kt", type=float, default=100.0)
    parser.add_argument("--min-late-periods", type=int, default=2)
    parser.add_argument("--min-signal-scenarios", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    thresholds = BackboneThresholds(
        cumulative_capture_kt_year=args.cum_threshold_kt,
        active_capture_kt=args.active_threshold_kt,
        min_late_active_periods=args.min_late_periods,
        min_signal_scenarios=args.min_signal_scenarios,
    )
    paths = run_analysis(args.results_dir, args.output_dir, thresholds)
    print("Backbone analysis outputs:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
