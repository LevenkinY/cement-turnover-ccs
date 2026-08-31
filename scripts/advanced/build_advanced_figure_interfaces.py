#!/usr/bin/env python3
"""Build auditable, refreshable figure interfaces without running the model.

The script is deliberately result-root agnostic.  It reads exported result CSVs,
performs deterministic joins and aggregations, and writes plot-ready tables plus
machine-readable QA.  Historical result roots must be labelled
``historical_layout_only``; they are never promoted to canonical evidence here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PERIODS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
PUBLIC_CASE_MAP = {
    "S1": "S1",
    "S2": "S3",
    "S3": "S5",
    "S4": "D-high",
    "S5": "D-low",
}

PROVINCE_META = {
    "北京": ("Beijing", "North"),
    "天津": ("Tianjin", "North"),
    "河北": ("Hebei", "North"),
    "山西": ("Shanxi", "North"),
    "内蒙古": ("Inner Mongolia", "North"),
    "辽宁": ("Liaoning", "Northeast"),
    "吉林": ("Jilin", "Northeast"),
    "黑龙江": ("Heilongjiang", "Northeast"),
    "上海": ("Shanghai", "East"),
    "江苏": ("Jiangsu", "East"),
    "浙江": ("Zhejiang", "East"),
    "安徽": ("Anhui", "East"),
    "福建": ("Fujian", "East"),
    "江西": ("Jiangxi", "East"),
    "山东": ("Shandong", "East"),
    "河南": ("Henan", "Central"),
    "湖北": ("Hubei", "Central"),
    "湖南": ("Hunan", "Central"),
    "广东": ("Guangdong", "South"),
    "广西": ("Guangxi", "South"),
    "海南": ("Hainan", "South"),
    "重庆": ("Chongqing", "Southwest"),
    "四川": ("Sichuan", "Southwest"),
    "贵州": ("Guizhou", "Southwest"),
    "云南": ("Yunnan", "Southwest"),
    "西藏": ("Tibet", "Southwest"),
    "陕西": ("Shaanxi", "Northwest"),
    "甘肃": ("Gansu", "Northwest"),
    "青海": ("Qinghai", "Northwest"),
    "宁夏": ("Ningxia", "Northwest"),
    "新疆": ("Xinjiang", "Northwest"),
}
REGION_ORDER = ["North", "Northeast", "East", "Central", "South", "Southwest", "Northwest"]
TIER_ORDER = {
    "stable_core": 0,
    "conditional_asset": 1,
    "sensitive_margin": 2,
    "not_terminal_candidate": 3,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--spatial-assets", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--public-case", choices=list(PUBLIC_CASE_MAP), default="S1")
    parser.add_argument(
        "--evidence-status",
        choices=["historical_layout_only", "canonical"],
        required=True,
    )
    parser.add_argument("--expected-lines", type=int)
    return parser.parse_args()


def read_required(root: Path, name: str) -> pd.DataFrame:
    path = root / name
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


def add_qa(rows: list[dict], check: str, actual, expected, tolerance=0.0, detail="") -> None:
    if isinstance(actual, (float, np.floating)) or isinstance(expected, (float, np.floating)):
        delta = abs(float(actual) - float(expected))
        passed = bool(delta <= tolerance)
    else:
        delta = 0 if actual == expected else 1
        passed = bool(actual == expected)
    rows.append(
        {
            "check": check,
            "status": "PASS" if passed else "FAIL",
            "actual": actual,
            "expected": expected,
            "absolute_difference": delta,
            "tolerance": tolerance,
            "detail": detail,
        }
    )


def sha256_columns(frame: pd.DataFrame, columns: list[str]) -> str:
    payload = frame.loc[:, columns].to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_interfaces(args: argparse.Namespace) -> None:
    root = args.result_dir.resolve()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa: list[dict] = []

    operation = read_required(root, "full_operation_status.csv")
    emissions = read_required(root, "full_plant_emission_balance.csv")
    renewals = read_required(root, "full_same_site_renewal_decisions.csv")
    transitions = read_required(root, "full_plant_role_transition.csv")
    national_production = read_required(root, "full_production_demand.csv")
    national_emissions = read_required(root, "full_emissions.csv")

    require_columns(operation, ["period", "plant_id", "province", "capacity", "operating", "utilization"], "operation")
    require_columns(
        emissions,
        [
            "period",
            "plant_id",
            "actual_direct_emissions",
            "captured_commercial",
            "residual_after_commercial_capture",
        ],
        "emissions",
    )
    require_columns(renewals, ["period", "plant_id", "renewal_investment"], "renewals")
    require_columns(
        transitions,
        [
            "plant_id",
            "province",
            "city",
            "natural_retirement_year",
            "physical_exit_year",
            "same_site_renewal_year",
            "capacity_status",
            "cumulative_commercial_capture_kt_year",
        ],
        "transitions",
    )

    for frame, name in [(operation, "operation"), (emissions, "emissions"), (renewals, "renewals")]:
        duplicate_count = int(frame.duplicated(["plant_id", "period"]).sum())
        add_qa(qa, f"{name}_unique_plant_period", duplicate_count, 0)

    plant_year = operation.merge(
        emissions[
            [
                "plant_id",
                "period",
                "actual_direct_emissions",
                "captured_commercial",
                "residual_after_commercial_capture",
            ]
        ],
        on=["plant_id", "period"],
        how="left",
        validate="one_to_one",
    ).merge(
        renewals[["plant_id", "period", "renewal_investment"]],
        on=["plant_id", "period"],
        how="left",
        validate="one_to_one",
    )

    static_columns = [
        "plant_id",
        "commission_year",
        "natural_retirement_year",
        "physical_exit_year",
        "same_site_renewal_year",
        "capacity_status",
        "terminal_role",
        "terminal_headline_role",
        "cumulative_commercial_capture_kt_year",
    ]
    static = transitions[static_columns].copy()
    plant_year = plant_year.merge(static, on="plant_id", how="left", validate="many_to_one")

    if args.spatial_assets:
        spatial = pd.read_csv(args.spatial_assets)
        require_columns(spatial, ["plant_id", "asset_tier"], "spatial assets")
        spatial_keep = [
            column
            for column in [
                "plant_id",
                "asset_tier",
                "ccs_responsibility_tier",
                "mean_cumulative_capture_mt",
                "af_resource_index",
                "af_access_2060_ktce",
                "nearest_storage_distance_km",
                "nearest_storage_type",
                "nearest_storage_offshore",
                "survival_frequency",
            ]
            if column in spatial.columns
        ]
        add_qa(qa, "spatial_asset_unique_plant", int(spatial.duplicated("plant_id").sum()), 0)
        plant_year = plant_year.merge(
            spatial[spatial_keep], on="plant_id", how="left", validate="many_to_one"
        )
    else:
        plant_year["asset_tier"] = "not_available"

    province_values = sorted(plant_year["province"].dropna().unique())
    unknown_provinces = [province for province in province_values if province not in PROVINCE_META]
    add_qa(qa, "province_dictionary_complete", len(unknown_provinces), 0, detail=";".join(unknown_provinces))
    plant_year["province_en"] = plant_year["province"].map(lambda value: PROVINCE_META.get(value, (value, "Unknown"))[0])
    plant_year["macro_region"] = plant_year["province"].map(lambda value: PROVINCE_META.get(value, (value, "Unknown"))[1])

    plant_year = plant_year.rename(columns={"period": "year", "capacity": "capacity_t_day"})
    plant_year["public_case"] = args.public_case
    plant_year["internal_result_alias"] = PUBLIC_CASE_MAP[args.public_case]
    plant_year["evidence_status"] = args.evidence_status
    plant_year["capacity_mt_y"] = plant_year["capacity_t_day"] * 330.0 / 1_000_000.0
    plant_year["production_mt_y"] = plant_year["capacity_mt_y"] * plant_year["utilization"]
    plant_year["gross_direct_mt_y"] = plant_year["actual_direct_emissions"] / 1000.0
    plant_year["commercial_capture_mt_y"] = plant_year["captured_commercial"] / 1000.0
    plant_year["residual_after_commercial_capture_mt_y"] = (
        plant_year["residual_after_commercial_capture"] / 1000.0
    )
    plant_year["renewal_event"] = plant_year["renewal_investment"].fillna(0).astype(int)
    renewed = (
        plant_year["same_site_renewal_year"].notna()
        & (plant_year["year"] >= plant_year["same_site_renewal_year"])
        & plant_year["operating"].eq(1)
    )
    inherited = plant_year["operating"].eq(1) & ~renewed
    plant_year["lifecycle_state"] = np.select(
        [inherited, renewed], ["inherited_operating", "renewed_operating"], default="inactive"
    )

    late = plant_year[plant_year["year"].between(2050, 2060)].pivot(
        index="plant_id", columns="year", values="commercial_capture_mt_y"
    )
    late_capture = pd.Series(0.0, index=transitions["plant_id"].astype(int), name="late_capture_mt")
    if set([2050, 2055, 2060]).issubset(late.columns):
        late_capture = (2.5 * late[2050] + 5.0 * late[2055] + 2.5 * late[2060]).rename("late_capture_mt")
    plant_year = plant_year.merge(late_capture, left_on="plant_id", right_index=True, how="left", validate="many_to_one")
    plant_year["late_capture_mt"] = plant_year["late_capture_mt"].fillna(0.0)
    plant_year["tier_rank"] = plant_year["asset_tier"].map(TIER_ORDER).fillna(4).astype(int)
    plant_year["region_rank"] = pd.Categorical(
        plant_year["macro_region"], categories=REGION_ORDER, ordered=True
    ).codes
    plant_year["renewal_sort"] = plant_year["same_site_renewal_year"].fillna(9999)
    plant_year["exit_sort"] = plant_year["physical_exit_year"].fillna(9999)

    plant_sort = (
        plant_year.drop_duplicates("plant_id")
        .sort_values(
            [
                "tier_rank",
                "late_capture_mt",
                "renewal_sort",
                "exit_sort",
                "region_rank",
                "province_en",
                "capacity_t_day",
                "plant_id",
            ],
            ascending=[True, False, True, False, True, True, False, True],
            kind="mergesort",
        )[["plant_id"]]
        .reset_index(drop=True)
    )
    plant_sort["plant_sort_index"] = np.arange(len(plant_sort), dtype=int)
    plant_year = plant_year.merge(plant_sort, on="plant_id", how="left", validate="many_to_one")
    plant_year = plant_year.sort_values(["plant_sort_index", "year"], kind="mergesort")

    n_lines = int(plant_year["plant_id"].nunique())
    expected_lines = args.expected_lines if args.expected_lines is not None else n_lines
    add_qa(qa, "line_count", n_lines, expected_lines)
    add_qa(qa, "plant_year_row_count", len(plant_year), expected_lines * len(PERIODS))
    add_qa(qa, "period_set", sorted(plant_year["year"].unique().tolist()), PERIODS)
    add_qa(qa, "join_missing_emissions", int(plant_year["actual_direct_emissions"].isna().sum()), 0)
    add_qa(qa, "join_missing_transition", int(plant_year["capacity_status"].isna().sum()), 0)
    if args.spatial_assets:
        add_qa(qa, "join_missing_asset_tier", int(plant_year["asset_tier"].isna().sum()), 0)

    # National source reconciliation (all source files use kt; interfaces use Mt).
    prod_check = (
        plant_year.groupby("year", as_index=False)
        .agg(
            production_mt_y=("production_mt_y", "sum"),
            operating_capacity_mt_y=("capacity_mt_y", lambda values: values[plant_year.loc[values.index, "operating"].eq(1)].sum()),
        )
        .merge(
            national_production[["period", "clinker_production", "operating_capacity_proxy"]].rename(columns={"period": "year"}),
            on="year",
            validate="one_to_one",
        )
    )
    for row in prod_check.itertuples(index=False):
        add_qa(qa, f"production_conservation_{row.year}", row.production_mt_y, row.clinker_production / 1000.0, 1e-8)
        add_qa(
            qa,
            f"operating_capacity_conservation_{row.year}",
            row.operating_capacity_mt_y,
            row.operating_capacity_proxy / 1000.0,
            1e-8,
        )

    emission_check = (
        plant_year.groupby("year", as_index=False)
        .agg(
            gross_mt=("gross_direct_mt_y", "sum"),
            capture_mt=("commercial_capture_mt_y", "sum"),
            residual_mt=("residual_after_commercial_capture_mt_y", "sum"),
        )
        .merge(
            national_emissions[
                [
                    "period",
                    "gross_direct_emission",
                    "commercial_captured_co2",
                    "residual_direct_emission_after_capture",
                ]
            ].rename(columns={"period": "year"}),
            on="year",
            validate="one_to_one",
        )
    )
    for row in emission_check.itertuples(index=False):
        add_qa(qa, f"gross_emission_conservation_{row.year}", row.gross_mt, row.gross_direct_emission / 1000.0, 1e-8)
        add_qa(qa, f"capture_conservation_{row.year}", row.capture_mt, row.commercial_captured_co2 / 1000.0, 1e-8)
        add_qa(
            qa,
            f"residual_conservation_{row.year}",
            row.residual_mt,
            row.residual_direct_emission_after_capture / 1000.0,
            1e-8,
        )
        add_qa(qa, f"commercial_balance_{row.year}", row.gross_mt, row.capture_mt + row.residual_mt, 1e-8)

    # Province-year table: every share denominator is explicit and common across years.
    province_denominator = (
        plant_year[plant_year["year"].eq(2025)]
        .groupby(["province", "province_en", "macro_region"], as_index=False)
        .agg(inherited_capacity_mt_y=("capacity_mt_y", "sum"))
    )
    province_year = (
        plant_year.assign(
            inherited_capacity_mt_y=np.where(
                plant_year["lifecycle_state"].eq("inherited_operating"), plant_year["capacity_mt_y"], 0.0
            ),
            renewed_capacity_mt_y=np.where(
                plant_year["lifecycle_state"].eq("renewed_operating"), plant_year["capacity_mt_y"], 0.0
            ),
            inactive_capacity_mt_y=np.where(
                plant_year["lifecycle_state"].eq("inactive"), plant_year["capacity_mt_y"], 0.0
            ),
        )
        .groupby(["province", "province_en", "macro_region", "year"], as_index=False)
        .agg(
            inherited_operating_capacity_mt_y=("inherited_capacity_mt_y", "sum"),
            renewed_operating_capacity_mt_y=("renewed_capacity_mt_y", "sum"),
            inactive_capacity_mt_y=("inactive_capacity_mt_y", "sum"),
            production_mt_y=("production_mt_y", "sum"),
            gross_direct_mt_y=("gross_direct_mt_y", "sum"),
            commercial_capture_mt_y=("commercial_capture_mt_y", "sum"),
            residual_after_commercial_capture_mt_y=("residual_after_commercial_capture_mt_y", "sum"),
            operating_line_count=("operating", "sum"),
        )
        .merge(province_denominator, on=["province", "province_en", "macro_region"], validate="many_to_one")
    )
    for prefix in ["inherited_operating", "renewed_operating", "inactive"]:
        province_year[f"{prefix}_capacity_share"] = (
            province_year[f"{prefix}_capacity_mt_y"] / province_year["inherited_capacity_mt_y"]
        )
    province_year["commercial_capture_fraction_of_gross"] = np.where(
        province_year["gross_direct_mt_y"] > 0,
        province_year["commercial_capture_mt_y"] / province_year["gross_direct_mt_y"],
        0.0,
    )
    province_year["public_case"] = args.public_case
    province_year["internal_result_alias"] = PUBLIC_CASE_MAP[args.public_case]
    province_year["evidence_status"] = args.evidence_status

    # Region-year uses the same inherited-capacity denominator logic.
    region_denominator = (
        province_denominator.groupby("macro_region", as_index=False)
        .agg(inherited_capacity_mt_y=("inherited_capacity_mt_y", "sum"))
    )
    region_year = (
        province_year.groupby(["macro_region", "year"], as_index=False)
        .agg(
            inherited_operating_capacity_mt_y=("inherited_operating_capacity_mt_y", "sum"),
            renewed_operating_capacity_mt_y=("renewed_operating_capacity_mt_y", "sum"),
            inactive_capacity_mt_y=("inactive_capacity_mt_y", "sum"),
            production_mt_y=("production_mt_y", "sum"),
            gross_direct_mt_y=("gross_direct_mt_y", "sum"),
            commercial_capture_mt_y=("commercial_capture_mt_y", "sum"),
        )
        .merge(region_denominator, on="macro_region", validate="many_to_one")
    )
    for prefix in ["inherited_operating", "renewed_operating", "inactive"]:
        region_year[f"{prefix}_capacity_share"] = (
            region_year[f"{prefix}_capacity_mt_y"] / region_year["inherited_capacity_mt_y"]
        )
    region_year["commercial_capture_fraction_of_gross"] = np.where(
        region_year["gross_direct_mt_y"] > 0,
        region_year["commercial_capture_mt_y"] / region_year["gross_direct_mt_y"],
        0.0,
    )
    region_year["public_case"] = args.public_case
    region_year["internal_result_alias"] = PUBLIC_CASE_MAP[args.public_case]
    region_year["evidence_status"] = args.evidence_status

    # Province mechanism matrix: one row per province; all capacity shares use 2025 inherited capacity.
    state_wide = province_year.pivot(index="province", columns="year")
    line_2025 = plant_year[plant_year["year"].eq(2025)][["plant_id", "province", "capacity_mt_y"]].copy()
    state_2045 = plant_year[plant_year["year"].eq(2045)][["plant_id", "operating"]].rename(columns={"operating": "operating_2045"})
    exit_by_2045 = line_2025.merge(state_2045, on="plant_id", validate="one_to_one")
    exit_by_2045["exit_capacity_mt_y"] = np.where(exit_by_2045["operating_2045"].eq(0), exit_by_2045["capacity_mt_y"], 0.0)
    exit_by_2045 = exit_by_2045.groupby("province", as_index=False).agg(exit_capacity_mt_y=("exit_capacity_mt_y", "sum"))
    renewal_late = (
        plant_year[plant_year["renewal_event"].eq(1) & plant_year["year"].between(2045, 2060)]
        .drop_duplicates("plant_id")
        .groupby("province", as_index=False)
        .agg(late_renewal_capacity_mt_y=("capacity_mt_y", "sum"))
    )
    late_province = (
        province_year[province_year["year"].isin([2050, 2055, 2060])]
        .pivot(index="province", columns="year", values="commercial_capture_mt_y")
        .reindex(columns=[2050, 2055, 2060], fill_value=0.0)
    )
    late_province["late_capture_mt"] = 2.5 * late_province[2050] + 5.0 * late_province[2055] + 2.5 * late_province[2060]
    total_late_capture = float(late_province["late_capture_mt"].sum())
    province_metrics = province_denominator.merge(exit_by_2045, on="province", how="left", validate="one_to_one").merge(
        renewal_late, on="province", how="left", validate="one_to_one"
    )
    province_metrics = province_metrics.merge(
        late_province[["late_capture_mt"]].reset_index(), on="province", how="left", validate="one_to_one"
    )
    province_metrics[["exit_capacity_mt_y", "late_renewal_capacity_mt_y", "late_capture_mt"]] = province_metrics[
        ["exit_capacity_mt_y", "late_renewal_capacity_mt_y", "late_capture_mt"]
    ].fillna(0.0)
    tier_capacity = (
        plant_year[plant_year["year"].eq(2025)]
        .groupby(["province", "asset_tier"], as_index=False)["capacity_mt_y"]
        .sum()
        .pivot(index="province", columns="asset_tier", values="capacity_mt_y")
        .reindex(columns=list(TIER_ORDER), fill_value=0.0)
        .fillna(0.0)
        .rename(
            columns={
                "stable_core": "stable_capacity_mt_y",
                "conditional_asset": "conditional_capacity_mt_y",
                "sensitive_margin": "sensitive_capacity_mt_y",
                "not_terminal_candidate": "other_capacity_mt_y",
            }
        )
        .reset_index()
    )
    province_metrics = province_metrics.merge(tier_capacity, on="province", how="left", validate="one_to_one")
    province_metrics["idle_headroom_share_2040"] = (
        (
            province_year[province_year["year"].eq(2040)]
            .set_index("province")
            .eval("inherited_operating_capacity_mt_y + renewed_operating_capacity_mt_y - production_mt_y")
        )
        / province_metrics.set_index("province")["inherited_capacity_mt_y"]
    ).reindex(province_metrics["province"]).to_numpy()
    province_metrics["exit_capacity_share_by_2045"] = province_metrics["exit_capacity_mt_y"] / province_metrics["inherited_capacity_mt_y"]
    province_metrics["late_renewal_capacity_share"] = province_metrics["late_renewal_capacity_mt_y"] / province_metrics["inherited_capacity_mt_y"]
    terminal_2060 = province_year[province_year["year"].eq(2060)].set_index("province")
    province_metrics["terminal_capacity_share_2060"] = (
        terminal_2060["inherited_operating_capacity_mt_y"] + terminal_2060["renewed_operating_capacity_mt_y"]
    ).reindex(province_metrics["province"]).to_numpy() / province_metrics["inherited_capacity_mt_y"]
    province_metrics["late_capture_share_national"] = np.where(
        total_late_capture > 0, province_metrics["late_capture_mt"] / total_late_capture, 0.0
    )
    province_metrics["public_case"] = args.public_case
    province_metrics["internal_result_alias"] = PUBLIC_CASE_MAP[args.public_case]
    province_metrics["evidence_status"] = args.evidence_status
    province_metrics = province_metrics.sort_values(
        ["late_capture_share_national", "terminal_capacity_share_2060", "inherited_capacity_mt_y", "province_en"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    province_metrics["province_sort_index"] = np.arange(len(province_metrics), dtype=int)

    for year, group in province_year.groupby("year"):
        cap_sum = (
            group["inherited_operating_capacity_mt_y"]
            + group["renewed_operating_capacity_mt_y"]
            + group["inactive_capacity_mt_y"]
        ).sum()
        add_qa(qa, f"province_capacity_partition_{year}", cap_sum, plant_year[plant_year["year"].eq(year)]["capacity_mt_y"].sum(), 1e-10)
        add_qa(qa, f"province_production_sum_{year}", group["production_mt_y"].sum(), plant_year[plant_year["year"].eq(year)]["production_mt_y"].sum(), 1e-10)
        add_qa(qa, f"province_capture_sum_{year}", group["commercial_capture_mt_y"].sum(), plant_year[plant_year["year"].eq(year)]["commercial_capture_mt_y"].sum(), 1e-10)
    add_qa(qa, "province_denominators_positive", int((province_metrics["inherited_capacity_mt_y"] <= 0).sum()), 0)
    add_qa(
        qa,
        "province_asset_tier_capacity_closure",
        float(
            province_metrics[
                [
                    "stable_capacity_mt_y",
                    "conditional_capacity_mt_y",
                    "sensitive_capacity_mt_y",
                    "other_capacity_mt_y",
                ]
            ].sum(axis=1).sum()
        ),
        float(province_metrics["inherited_capacity_mt_y"].sum()),
        1e-10,
    )
    add_qa(qa, "late_capture_share_closure", province_metrics["late_capture_share_national"].sum(), 1.0 if total_late_capture > 0 else 0.0, 1e-10)
    add_qa(qa, "public_case_mapping", PUBLIC_CASE_MAP[args.public_case], PUBLIC_CASE_MAP[args.public_case])
    add_qa(qa, "evidence_status", args.evidence_status, args.evidence_status)

    plant_static_columns = [
        "public_case",
        "internal_result_alias",
        "evidence_status",
        "plant_id",
        "province",
        "province_en",
        "macro_region",
        "city",
        "capacity_t_day",
        "commission_year",
        "natural_retirement_year",
        "physical_exit_year",
        "same_site_renewal_year",
        "capacity_status",
        "terminal_role",
        "terminal_headline_role",
        "asset_tier",
        "late_capture_mt",
        "plant_sort_index",
    ]
    optional_static = [
        "ccs_responsibility_tier",
        "mean_cumulative_capture_mt",
        "af_resource_index",
        "af_access_2060_ktce",
        "nearest_storage_distance_km",
        "nearest_storage_type",
        "nearest_storage_offshore",
        "survival_frequency",
    ]
    plant_static = plant_year.drop_duplicates("plant_id")[
        plant_static_columns + [column for column in optional_static if column in plant_year.columns]
    ].sort_values("plant_sort_index")

    export_plant_year = plant_year[
        [
            "public_case",
            "internal_result_alias",
            "evidence_status",
            "plant_id",
            "plant_sort_index",
            "province",
            "province_en",
            "macro_region",
            "year",
            "capacity_t_day",
            "capacity_mt_y",
            "operating",
            "utilization",
            "production_mt_y",
            "gross_direct_mt_y",
            "commercial_capture_mt_y",
            "residual_after_commercial_capture_mt_y",
            "renewal_event",
            "lifecycle_state",
            "asset_tier",
            "natural_retirement_year",
            "physical_exit_year",
            "same_site_renewal_year",
            "late_capture_mt",
        ]
    ].copy()

    export_plant_year.to_csv(out / "plant_year_interface.csv", index=False)
    plant_static.to_csv(out / "plant_static_interface.csv", index=False)
    province_year.to_csv(out / "province_year_interface.csv", index=False)
    region_year.to_csv(out / "region_year_interface.csv", index=False)
    province_metrics.to_csv(out / "province_mechanism_metrics.csv", index=False)
    qa_frame = pd.DataFrame(qa)
    qa_frame.to_csv(out / "interface_qa.csv", index=False)

    sort_hash = sha256_columns(plant_static, ["plant_id", "plant_sort_index"])
    province_sort_hash = sha256_columns(province_metrics, ["province", "province_sort_index"])
    manifest = {
        "schema_version": "advanced_figures_v1",
        "result_root": str(root),
        "spatial_assets": str(args.spatial_assets.resolve()) if args.spatial_assets else None,
        "public_case": args.public_case,
        "internal_result_alias": PUBLIC_CASE_MAP[args.public_case],
        "evidence_status": args.evidence_status,
        "periods": PERIODS,
        "line_count": n_lines,
        "plant_year_rows": len(export_plant_year),
        "province_count": int(province_metrics["province"].nunique()),
        "plant_sort_sha256": sort_hash,
        "province_sort_sha256": province_sort_hash,
        "qa_failures": int(qa_frame["status"].eq("FAIL").sum()),
        "denominators": {
            "province_capacity_shares": "sum of inherited 2025 line capacities in each province (Mt clinker yr-1 at 330 d yr-1)",
            "national_late_capture_share": "trapezoidal commercial capture integral, 2050-2060, summed across all provinces",
            "capture_fraction_of_gross": "province or region commercial capture divided by gross direct emissions in the same modeled period",
        },
        "sorting": {
            "plant_rows": "asset tier; late-capture integral descending; renewal year; physical-exit year descending; macro-region; province; capacity descending; plant_id",
            "province_rows": "late-capture national share descending; 2060 terminal-capacity share descending; inherited capacity descending; English province name",
        },
        "warning": (
            "HISTORICAL PACKAGE: layout development only; not canonical evidence for the corrected 1,572-line manifest."
            if args.evidence_status == "historical_layout_only"
            else "Canonical status is asserted by caller and still requires external freeze approval."
        ),
    }
    (out / "interface_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if manifest["qa_failures"]:
        failures = qa_frame[qa_frame["status"].eq("FAIL")]
        raise SystemExit(f"Interface QA failed:\n{failures.to_string(index=False)}")


if __name__ == "__main__":
    build_interfaces(parse_args())
