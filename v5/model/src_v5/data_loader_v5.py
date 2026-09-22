"""
Data loader for the v5 model.

The active model uses observed 2025 production, raw plant AF accessibility plus
province resource conservation, exogenous ARM/EE/LCC paths, and direct
plant-to-storage candidate routes.

Loads:
  Plant data, storage nodes, AF catchment, location tiers, regional SCM/Liao,
  ARM/LCC exogenous paths, initial CCS projects, cluster/hub structure.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time
import numpy as np
import pandas as pd

from src_v5 import config_v5 as _cfg_runtime
from src_v5.config_v5 import (
    V5_DATA, AF_ACCESS_CORRECTED_CSV, AF_TECHNICAL_TSR_CEILING,
    AF_ACCESS_ALLOCATION_HEADROOM, DEMAND_SCENARIO,
    PLANT_CSV, TIER_CSV, PLANT_SOURCE_XLSX, BASEYEAR_OUTPUT_CSV,
    EXTERNAL_TECH_PATH_CSV, EXTERNAL_TECH_SOURCE_CSV,
    SCM_CSV, PROCESS_ADJ_CSV,
    LIAO_CSV, AF_BIOMASS_CSV, AF_WASTE_CSV, DEMAND_XLSX,
    STORAGE_CSV, STORAGE_TEXTURE_CSV, CHINA_LAND_GEOJSON, T_LIST, INITIAL_CCS_PROJECTS,
    DATA_INPUT, BIOMASS_TCE_PER_KT, MSW_TCE_PER_KT, GJ_PER_TCE,
    AF_BIOMASS_POOL_COLUMN, AF_WASTE_POOL_COLUMN, AF_WASTE_POOL_HIGH_COLUMN,
    AF_WASTE_REFERENCE_YEAR, AF_WASTE_ACCESS_MATURITY,
    AF_BIOMASS_ACCESS_MATURITY,
    AF_PLANT_ACCESS_MODE,
    ARM_PATH_CASE, EE_PATH_CASE,
    SOURCE_FUEL_EF_REANCHOR_SCALE,
    NEAREST_SINKS_PER_TYPE, HIGH_CAPACITY_SINKS_PER_PLANT,
    CAPACITY_T_DAY_TO_KT_YR, TCE_PER_T_CLINKER, INITIAL_AF_RATE,
    COAL_EF_TCO2_PER_TCE,
    ENABLE_REGIONAL_DEMAND, DEMAND_NODE_FILE, DEMAND_PROVINCE_OUTPUT_OVERRIDE,
    DEMAND_PROVINCE_RATIO_FALLBACK, DEMAND_PROVINCIAL_SHARE_CONVERGENCE,
    DEMAND_MARKET_UNIT,
    DEMAND_MARKET_NODE_FILE, DEMAND_MARKET_ARC_FILE,
    DEMAND_NODE_LAYER_USED_IN_OPTIMIZATION,
)


def load_plants():
    """Load plant metadata, catchments, and source emission factors."""
    t0 = time.time()
    catchment = pd.read_csv(PLANT_CSV)
    meta = pd.read_excel(str(DATA_INPUT / "plants" / "plant_data.xlsx"))
    source = pd.read_excel(str(PLANT_SOURCE_XLSX))
    cols = ["id", "province", "capacity", "longitude", "latitude"]
    if "year of commissioning" in meta.columns:
        cols.append("year of commissioning")
    df = catchment.merge(meta[cols], left_on="plant_id", right_on="id", how="left")
    if "year of commissioning" in df.columns:
        df = df.rename(columns={"year of commissioning": "commission_year"})
    source_cols = {
        "id": "plant_id",
        "工艺排放强度（t CO2/t cl）": "source_process_ef",
        "燃料排放强度（t CO2/t cl）": "source_fuel_ef",
    }
    missing = [c for c in source_cols if c not in source.columns]
    if missing:
        raise ValueError(f"Source plant workbook is missing emission fields: {missing}")
    ef = source[list(source_cols)].rename(columns=source_cols)
    df = df.merge(ef, on="plant_id", how="left", validate="one_to_one")
    # Tier-compliance pass (2026-09-12, author-approved): reassign BOTH source
    # parameters of every line that deviates from the archived capacity-tier
    # rule (config_v5.SOURCE_EF_TIER_RULE, cuts at >=4,200 / 2,000 t/d; see
    # v5/parameters/fuel_ef_reanchor_20260912.md §3). Measured scope: 22
    # appended-batch lines (id >= 2,000) plus line id 2040, whose two values are
    # the exact midpoints of adjacent tiers in BOTH parameters -- an
    # interpolated fill, not a measurement. The raw workbook is untouched.
    if bool(getattr(_cfg_runtime, "SOURCE_EF_TIER_COMPLIANCE", False)):
        rule = dict(getattr(_cfg_runtime, "SOURCE_EF_TIER_RULE", {}) or {})
        cut1 = float(rule.get("cut_t1", 4200.0))
        cut2 = float(rule.get("cut_t2", 2000.0))
        tiers = rule.get("tiers", {})
        caps = pd.to_numeric(df["capacity"], errors="coerce")
        tier = caps.map(lambda c: 1 if c >= cut1 else (2 if c >= cut2 else 3))
        exp_proc = tier.map(lambda t: float(tiers[t]["proc"]))
        exp_fuel = tier.map(lambda t: float(tiers[t]["fuel"]))
        dev = ((df["source_process_ef"] - exp_proc).abs() > 1e-6) | (
            (df["source_fuel_ef"] - exp_fuel).abs() > 1e-6
        )
        if dev.any():
            for idx in df.index[dev]:
                print(
                    "  [data_loader] EF tier compliance: plant "
                    f"{int(df.loc[idx, 'plant_id'])} ({caps.loc[idx]:.0f} t/d, "
                    f"tier {tier.loc[idx]}) proc "
                    f"{df.loc[idx, 'source_process_ef']:.6f} -> {exp_proc.loc[idx]:.6f}, "
                    f"fuel {df.loc[idx, 'source_fuel_ef']:.6f} -> {exp_fuel.loc[idx]:.6f}"
                )
            df.loc[dev, "source_process_ef"] = exp_proc[dev]
            df.loc[dev, "source_fuel_ef"] = exp_fuel[dev]
            print(
                f"  [data_loader] EF tier compliance: {int(dev.sum())} line(s) "
                "reassigned to the archived tier rule "
                f"(cuts {cut1:.0f} / {cut2:.0f} t/d); workbook untouched"
            )
    if df[["source_process_ef", "source_fuel_ef"]].isna().any().any():
        bad = df.loc[
            df[["source_process_ef", "source_fuel_ef"]].isna().any(axis=1),
            "plant_id",
        ].tolist()
        raise ValueError(f"Missing source emission factors for plant ids: {bad[:10]}")
    print(f"  [data_loader] plants: {len(df)} rows loaded in {time.time()-t0:.2f}s")
    return df


def load_location_tier():
    """Load plant location tier classification."""
    df = pd.read_csv(TIER_CSV)
    return df.set_index("plant_id")["location_tier"].to_dict()


def load_storage():
    """Load storage nodes and exclude mainland cells from offshore candidates."""
    df = pd.read_csv(STORAGE_CSV)
    if "is_offshore" not in df.columns:
        df["is_offshore"] = False
    raw_flag = df["is_offshore"].astype(str).str.lower().isin({"true", "1", "yes"})
    df["offshore_box_candidate"] = raw_flag

    if not CHINA_LAND_GEOJSON.exists():
        raise FileNotFoundError(
            f"China land boundary is required for offshore classification: {CHINA_LAND_GEOJSON}"
        )
    try:
        import shapely
        from shapely.geometry import shape

        with open(CHINA_LAND_GEOJSON, encoding="utf-8") as f:
            geojson = json.load(f)
        features = geojson.get("features", [])
        land = shapely.union_all([
            shapely.make_valid(shape(feature["geometry"]))
            for feature in features
            if feature.get("geometry")
        ])
        points = shapely.points(
            pd.to_numeric(df["longitude"], errors="coerce").to_numpy(),
            pd.to_numeric(df["latitude"], errors="coerce").to_numpy(),
        )
        on_land = np.asarray(shapely.covers(land, points), dtype=bool)
    except Exception as exc:
        raise RuntimeError("Failed to classify storage nodes against China land boundary") from exc

    df["is_offshore"] = raw_flag.to_numpy() & ~on_land
    df["offshore_classification_method"] = "basin_box_excluding_china_land"
    corrected = int((raw_flag.to_numpy() & on_land).sum())
    print(
        f"  [data_loader] storage nodes: {len(df)}; offshore={int(df['is_offshore'].sum())}; "
        f"land false positives corrected={corrected}"
    )
    # P1-3: drop storage nodes too small to host a normal project. Sub-threshold
    # raster cells were being filled to exactly 100% of their capacity, which is a
    # grid-resolution artifact rather than an engineering constraint.
    min_mt = float(getattr(_cfg_runtime, "STORAGE_MIN_NODE_CAPACITY_MT", 10.0))
    if min_mt > 0:
        before = len(df)
        total_mt = (
            pd.to_numeric(df["dsa_capacity"], errors="coerce").fillna(0.0)
            + pd.to_numeric(df["eor_capacity"], errors="coerce").fillna(0.0)
        )
        keep = total_mt >= min_mt
        dropped = df.loc[~keep]
        df = df.loc[keep].reset_index(drop=True)
        dropped_max = float(total_mt[~keep].max()) if (~keep).any() else 0.0
        print(
            f"  [data_loader] storage node size filter (>={min_mt:.0f} Mt total): "
            f"dropped {before - len(df)} of {before} nodes; largest dropped node "
            f"{dropped_max:.2f} Mt; remaining capacity "
            f"{float(total_mt[keep].sum())/1000.0:.0f} Gt"
        )
    return df


def haversine_km(lat1, lon1, lat2, lon2):
    """Vectorized haversine distance in km."""
    R = 6371.0
    lat1r = np.radians(lat1)
    lat2r = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def build_plant_storage_assignment(plants_df, storage_df, max_km=500.0, k_nearest=8):
    """
    Build a compact, type-preserving direct plant-to-storage whitelist.

    Candidate routes are the union of nearest DSA routes, nearest EOR routes,
    and high-capacity routes. A dual-resource grid can appear once for each
    storage type; it is never forced into a single type.
    Returns:
        assignment: dict {plant_id: [(storage_idx, distance_km, type), ...]}
    """
    t0 = time.time()
    plant_lat = plants_df["latitude"].values if "latitude" in plants_df.columns else None
    plant_lon = plants_df["longitude"].values if "longitude" in plants_df.columns else None
    plant_ids = plants_df["plant_id"].tolist()

    if plant_lat is None or plant_lon is None:
        meta = pd.read_excel(str(DATA_INPUT / "plants" / "plant_data.xlsx"))
        meta = meta.set_index("id")[["latitude", "longitude"]]
        plant_lat = np.array([meta.loc[i, "latitude"] if i in meta.index else np.nan for i in plant_ids])
        plant_lon = np.array([meta.loc[i, "longitude"] if i in meta.index else np.nan for i in plant_ids])

    s_lat = storage_df["latitude"].values
    s_lon = storage_df["longitude"].values
    s_idx = storage_df["storage_idx"].values
    s_dsa = storage_df["dsa_capacity"].values
    s_eor = storage_df["eor_capacity"].values

    assignment = {}
    n_pairs = 0
    for k, pid in enumerate(plant_ids):
        if np.isnan(plant_lat[k]) or np.isnan(plant_lon[k]):
            continue
        d = haversine_km(plant_lat[k], plant_lon[k], s_lat, s_lon)
        in_range = d <= max_km
        if not (in_range & ((s_dsa + s_eor) > 0)).any():
            continue
        route_candidates = []
        for stype, capacity in (("dsa", s_dsa), ("eor", s_eor)):
            valid = np.where(in_range & (capacity > 0))[0]
            nearest = valid[np.argsort(d[valid])[:NEAREST_SINKS_PER_TYPE]]
            for j in nearest:
                route_candidates.append((int(j), stype))

        all_routes = [
            (int(j), stype)
            for stype, capacity in (("dsa", s_dsa), ("eor", s_eor))
            for j in np.where(in_range & (capacity > 0))[0]
        ]
        top_capacity = sorted(
            all_routes,
            key=lambda item: s_dsa[item[0]] if item[1] == "dsa" else s_eor[item[0]],
            reverse=True,
        )[:HIGH_CAPACITY_SINKS_PER_PLANT]
        route_candidates.extend(top_capacity)

        seen = set()
        pairs = []
        for j, stype in sorted(route_candidates, key=lambda item: d[item[0]]):
            key = (int(s_idx[j]), stype)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((int(s_idx[j]), float(d[j]), stype))
            if len(pairs) >= k_nearest:
                break
        assignment[pid] = pairs
        n_pairs += len(pairs)

    print(f"  [data_loader] plant-storage assignment: {len(assignment)}/{len(plant_ids)} plants with sinks, "
          f"{n_pairs} (plant,sink) pairs in {time.time()-t0:.1f}s")
    return assignment


def load_regional():
    """Load all regional tables."""
    scm = pd.read_csv(SCM_CSV)
    proc = pd.read_csv(PROCESS_ADJ_CSV)
    liao = pd.read_csv(LIAO_CSV)
    biomass = pd.read_csv(AF_BIOMASS_CSV)
    waste = pd.read_csv(AF_WASTE_CSV)
    return scm, proc, liao, biomass, waste


def load_external_technology_paths():
    """Load versioned national ARM, EE, and clinker-ratio pathways."""
    paths = pd.read_csv(EXTERNAL_TECH_PATH_CSV)
    required = {
        "year",
        "ee_central",
        "ee_high",
        "arm_central",
        "arm_high",
        "clinker_ratio_central",
        "clinker_ratio_high",
    }
    missing = required - set(paths.columns)
    if missing:
        raise ValueError(f"External technology path table is missing columns: {sorted(missing)}")
    paths["year"] = pd.to_numeric(paths["year"], errors="raise").astype(int)
    if paths["year"].duplicated().any() or set(paths["year"]) != set(T_LIST):
        raise ValueError(
            "External technology path years must uniquely match the model periods: "
            f"{T_LIST}"
        )
    for col in required - {"year"}:
        paths[col] = pd.to_numeric(paths[col], errors="raise")
    if not EXTERNAL_TECH_SOURCE_CSV.exists():
        raise FileNotFoundError(
            f"External technology source register is missing: {EXTERNAL_TECH_SOURCE_CSV}"
        )
    sources = pd.read_csv(EXTERNAL_TECH_SOURCE_CSV)
    return paths.sort_values("year").reset_index(drop=True), sources


def load_demand():
    """Load annual cement-demand pathways from Excel (Mt cement/yr)."""
    scenes = {}
    with pd.ExcelFile(DEMAND_XLSX) as xl:
        for sheet in xl.sheet_names:
            df = xl.parse(sheet)
            if {
                "year",
                "d_high_mt",
                "d_medium_mt",
                "d_low_mt",
            }.issubset(df.columns):
                df = df.dropna(subset=["year"])
                indexed = df.set_index("year")
                scenes["d_high"] = indexed["d_high_mt"].to_dict()
                scenes["d_medium"] = indexed["d_medium_mt"].to_dict()
                scenes["d_low"] = indexed["d_low_mt"].to_dict()
                break
            elif "Year" in df.columns and "Baseline" in df.columns:
                df = df.dropna(subset=["Year"])
                scenes["baseline"] = df.set_index("Year")["Baseline"].to_dict()
                scenes["msp_2c"] = df.set_index("Year")["MSP-2C"].to_dict()
                scenes["tip_2c"] = df.set_index("Year")["TIP-2C"].to_dict()
                scenes["enzp_1p5c"] = df.set_index("Year")["ENZP-1.5C or UDP-B1.5C"].to_dict()
                break
            elif "年份" in df.columns and "需求基准" in df.columns:
                df = df.dropna(subset=["年份"])
                scenes[sheet] = df.set_index("年份")["需求基准"].to_dict()
    print(f"  [data_loader] demand: {list(scenes.keys())}")
    return scenes


# 2026-09-12 cleanup (author-approved): build_province_clinker_ratio,
# build_process_adjustment (corridor-envelope branch) and
# build_clinker_ratio_adjustment were removed as dead code — their outputs
# (data["prov_clinker"], data["process_adjustment_envelope"],
# data["clinker_ratio_adjustment"], data["proc_adj"]) had no consumer in the
# builder, extractor, scenarios or tests. build_province_corridor_map is
# RETAINED: data["prov_corridor"] is the canonical 30-province list consumed by
# the S2/S3/S5 scenario machinery in main.py (keys only; the corridor values
# are not read). Removed values are preserved in parameter_deduction.md
# (ExoPath-cleanup-20260912).


def build_province_corridor_map(scm_df):
    """Province → corridor mapping from scm_proxy (used as the province list)."""
    return dict(zip(scm_df["province_cn"], scm_df["arm_corridor"]))


def _emission_level(capacity_td):
    """v3-compatible emission class by clinker capacity."""
    if capacity_td >= 4000:
        return 1
    if capacity_td >= 2000:
        return 2
    return 3


def build_plant_emission_factors(plants_df, liao_df):
    """
    Use the complete source-workbook process and fuel emission factors.

    This avoids the previous hybrid of size-class factors and a second
    province-level process calibration. Liao factors remain available for
    sensitivity checks, but are not mixed into the central plant series.

    2026-09-12 fuel re-anchor: the workbook's 2021-vintage class constants are
    scaled uniformly by SOURCE_FUEL_EF_REANCHOR_SCALE so the active fleet's
    capacity-weighted thermal intensity equals TCE_PER_T_CLINKER x 1000
    (105.0 kgce/t clinker). Process factors are stoichiometric and are NOT
    scaled. See v5/parameters/fuel_ef_reanchor_20260912.md.
    """
    df = plants_df[["plant_id", "source_process_ef", "source_fuel_ef"]].copy()
    df["proc_ef"] = pd.to_numeric(df["source_process_ef"], errors="coerce")
    df["fuel_ef"] = pd.to_numeric(df["source_fuel_ef"], errors="coerce")
    if df[["proc_ef", "fuel_ef"]].isna().any().any():
        raise ValueError("Plant emission factors contain missing or non-numeric values")
    df["fuel_ef"] = df["fuel_ef"] * float(SOURCE_FUEL_EF_REANCHOR_SCALE)
    return {
        int(row.plant_id): {"proc_ef": float(row.proc_ef), "fuel_ef": float(row.fuel_ef)}
        for row in df.itertuples(index=False)
    }


def load_corrected_af_access(path=None):
    """Load the v5 overlap- and area-corrected plant AF accessibility (P0-2).

    Produced by v5/model/preprocessing/build_plant_af_catchment.py. It corrects two
    v4 defects: the population raster was read as per-pixel counts although it is a
    density (1.40x overstatement), and overlapping catchments were summed
    independently (24.2x overstatement nationally).

    The raster is a technical-potential atlas whose national total (1,455 Mtce/yr) is
    ~25-66x the statistics-based deployable pool, so only its RELATIVE within-province
    pattern is used — as weights that allocate the province resource pool to plants.
    """
    path = Path(path) if path else AF_ACCESS_CORRECTED_CSV
    if not path.exists():
        raise FileNotFoundError(
            f"v5 corrected AF accessibility is missing: {path}. "
            "Run: python v5/model/preprocessing/build_plant_af_catchment.py"
        )
    df = pd.read_csv(path)
    required = {"plant_id", "province", "msw_ktce", "bio_ktce"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Corrected AF accessibility is missing columns: {sorted(missing)}")
    print(f"  [data_loader] corrected AF accessibility: {len(df)} plants, "
          f"national total {df['access_ktce'].sum()/1000:,.1f} Mtce/yr")
    return df


def build_af_access_shares(plants_df, access_df):
    """Within-province accessibility shares per channel (time-invariant).

    share_x[i] = W_x[i] / sum_{j in p} W_x[j].  These are the weights that couple the
    plant-level cap to the province resource pool (option (b)); they are NOT absolute
    caps. Plants with zero accessibility fall back to an equal share.
    """
    df = plants_df[["plant_id", "province"]].copy()
    df["plant_id"] = df["plant_id"].astype(int)
    acc = access_df.set_index("plant_id")
    df["w_bio"] = df["plant_id"].map(acc["bio_ktce"]).fillna(0.0)
    df["w_wst"] = df["plant_id"].map(acc["msw_ktce"]).fillna(0.0)
    share_bio, share_wst = {}, {}
    for prov, sub in df.groupby("province"):
        for col, out in (("w_bio", share_bio), ("w_wst", share_wst)):
            total = float(sub[col].sum())
            for row in sub.itertuples(index=False):
                value = float(getattr(row, col))
                out[int(row.plant_id)] = (
                    value / total if total > 0 else 1.0 / max(len(sub), 1)
                )
    return share_bio, share_wst


def build_af_expansion_ceiling(years):
    """REMOVED 2026-09-13 (checklist item 3) -- do not reinstate.

    This returned ceiling(t) = min(INITIAL_AF_RATE + AF_EXPANSION_PP/100 * idx, theta),
    i.e. 5/15/25/35/45/55/60/60%, and was used as the total the province resource
    pools were scaled to. That made a policy PACE schedule the effective resource
    endowment and let a demand scenario rescale it. Both couplings are removed:
    the resource side is now the raw province pool, and the pace lives only in
    m.af_expansion_cap. The function is kept as an explicit tombstone so that the
    change is visible in the diff and nobody re-adds the coupling by accident.
    """
    raise NotImplementedError(
        "build_af_expansion_ceiling was removed on 2026-09-13: the deployment "
        "ceiling must not be baked into the plant resource allocation. See "
        "build_af_province_allocation."
    )


def build_af_province_allocation(province_af_pool_channel, years):
    """Split the PROVINCE RESOURCE POOL into per-province, per-channel allocations.

    A_x[p,t] = R_x[p,t]   (the statistics-based provincial resource pool itself)

    2026-09-13 change (checklist item 3). Previously this was

        A_x[p,t] = ceiling(t) * national_fuel(t) * R_x[p,t] / sum_q R_q,t

    which coupled the physically accessible resource to two things it should not
    depend on: the national deployment ceiling (a policy-pace object) and national
    kiln fuel demand (a demand object). Consequences of the old form that this
    change removes: (i) a demand scenario mechanically rescaled the resource
    endowment, so "d_high" quietly implied more biomass; (ii) the plant-level
    accessibility cap inherited the deployment schedule, so a pace assumption
    constrained a resource constraint; (iii) as demand fell, the plant cap fell
    with it even though the resource pool did not.

    The province pool R_x[p,t] is already time-varying on its own, through the
    biomass/waste ACCESS MATURITY schedules in build_province_af_pool_ktce. So the
    deployment pace is now carried ONLY by the national expansion constraint
    (m.af_expansion_cap) and the resource side is purely physical.

    The plant cap remains kappa * (A_bio*share_bio + A_wst*share_wst); with KAPPA=2
    that still permits within-province reallocation of up to 2x a plant's
    accessibility-proportional share, bounded by the province pool guard.
    """
    alloc_bio, alloc_wst = {}, {}
    for (prov, year), entry in province_af_pool_channel.items():
        if int(year) not in set(int(y) for y in years):
            continue
        bio = float(entry.get("bio", 0.0)) if isinstance(entry, dict) else float(entry)
        wst = float(entry.get("wst", 0.0)) if isinstance(entry, dict) else 0.0
        if bio <= 0 and wst <= 0:
            continue
        alloc_bio[(prov, int(year))] = bio
        alloc_wst[(prov, int(year))] = wst
    return alloc_bio, alloc_wst


def pools_present(pools):
    return sorted({p for (p, _) in pools})


def build_baseyear_plant_utilization(plants_df, liao_df, cement_output_path):
    """Construct a feasible, province-anchored 2025 utilization vector."""
    output = pd.read_csv(cement_output_path)
    ratio = liao_df.set_index("province_cn")["liao_clinker_ratio_effective"].to_dict()
    cement_mt = output.set_index("province_cn")["cement_output_10kt"] / 100.0
    clinker_kt = {
        str(prov): float(value) * 1000.0 * float(ratio[str(prov)])
        for prov, value in cement_mt.items()
    }

    df = plants_df[["plant_id", "province", "capacity"]].copy()
    df["annual_capacity_kt"] = pd.to_numeric(df["capacity"], errors="coerce") * CAPACITY_T_DAY_TO_KT_YR
    province_capacity = df.groupby("province")["annual_capacity_kt"].sum().to_dict()
    utilization = {}
    realized_by_province = {}
    for prov, sub in df.groupby("province"):
        target = float(clinker_kt.get(str(prov), 0.0))
        capacity = float(province_capacity.get(prov, 0.0))
        u = min(target / capacity, 1.0) if capacity > 0 else 0.0
        for row in sub.itertuples(index=False):
            utilization[int(row.plant_id)] = u
        realized_by_province[str(prov)] = u * capacity

    total_realized_kt = sum(realized_by_province.values())
    national_cement_mt = 1693.0
    effective_ratio = total_realized_kt / (national_cement_mt * 1000.0)
    province_gap = {
        prov: realized_by_province.get(prov, 0.0) - target
        for prov, target in clinker_kt.items()
    }
    print(
        "  [data_loader] 2025 production anchor: "
        f"clinker={total_realized_kt/1000.0:.3f} Mt, "
        f"effective clinker ratio={effective_ratio:.6f}, "
        f"max province gap={max(abs(v) for v in province_gap.values()):.3f} kt"
    )
    return utilization, realized_by_province, effective_ratio, province_gap


def build_baseyear_af_supply(
    plants_df,
    baseyear_utilization,
    share_bio,
    share_wst,
    alloc_bio,
    alloc_wst,
    plant_emission_factors=None,
    af_energy_caliber="plant_heat_demand",
):
    """Allocate the observed national 2025 AF rate by accessibility share.

    Replaces the v4 three-step patch (uniform 5%, then province-pool scaling, then a
    residual re-allocation). Total stays at INITIAL_AF_RATE of national 2025 fuel
    energy; the distribution is now data-driven rather than uniform.

    2026-09-13: the "fuel" denominator is the plant's own heat demand,
    h_i * (1 - EE_2025) * Q_i, with h_i = plant_fuel_ef[i]/COAL_EF, instead of a
    flat TCE_PER_T_CLINKER * Q_i (see config AF_ENERGY_CALIBER). EE_2025 = 0, so
    the base-year anchor is numerically unchanged; the change matters only for
    consistency with the constraint set.
    """
    year = int(min(alloc_bio, key=lambda k: k[1])[1]) if alloc_bio else 2025
    rows = []
    for row in plants_df.itertuples(index=False):
        pid = int(row.plant_id)
        prov = str(row.province)
        clinker = float(row.capacity) * CAPACITY_T_DAY_TO_KT_YR * float(baseyear_utilization[pid])
        if plant_emission_factors is not None and pid in plant_emission_factors:
            intensity = (
                float(plant_emission_factors[pid]["fuel_ef"]) / float(COAL_EF_TCO2_PER_TCE)
                if af_energy_caliber == "plant_heat_demand"
                else TCE_PER_T_CLINKER
            )
        else:
            intensity = TCE_PER_T_CLINKER
        fuel = clinker * intensity
        cap_value = (
            float(alloc_bio.get((prov, year), 0.0)) * float(share_bio.get(pid, 0.0))
            + float(alloc_wst.get((prov, year), 0.0)) * float(share_wst.get(pid, 0.0))
        )
        rows.append({"plant_id": pid, "province": prov, "fuel": fuel, "cap": cap_value})
    df = pd.DataFrame(rows)
    total_fuel = float(df["fuel"].sum())
    target = float(INITIAL_AF_RATE) * total_fuel
    if float(df["cap"].sum()) <= 0:
        raise ValueError("Accessibility allocation is zero for every plant in 2025")

    # The base year is an observation, so it is fixed; it must nevertheless respect
    # both the technical ceiling and the accessibility cap. Accessibility shares are
    # not proportional to capacity, so a handful of very small lines (down to 50 t/d)
    # in resource-rich provinces receive slices larger than they can physically burn.
    # Cap them, then redistribute the residual to plants that still have headroom.
    theta_limit = float(AF_TECHNICAL_TSR_CEILING) * df["fuel"]
    kappa_limit = float(AF_ACCESS_ALLOCATION_HEADROOM) * df["cap"]
    limit = np.minimum(theta_limit, kappa_limit)      # per-plant feasible bound
    # The base year is an OBSERVATION, so the allocation must hit `target` exactly.
    # Normalise the accessibility weights to `target` FIRST, then apply the physics
    # bound: since min() can only reduce the total, the residual is then >= 0 and the
    # single redistribution pass below is sufficient. (Without this normalisation the
    # raw province pool, which is now decoupled from any deployment ceiling, would
    # let the 2025 anchor land far above the observed rate.)
    weights = df["cap"].to_numpy(dtype=float)
    weight_sum = float(weights.sum())
    if weight_sum <= 0:
        raise ValueError("Accessibility allocation is zero for every plant in 2025")
    allocation = np.minimum(weights * (target / weight_sum), limit)
    residual = target - float(allocation.sum())
    if residual > 1e-9:
        headroom = (limit - allocation).clip(lower=0.0)
        if float(headroom.sum()) < residual - 1e-6:
            raise ValueError(
                "The observed 2025 national AF rate is infeasible under the technical "
                f"ceiling and accessibility caps: shortfall={residual - headroom.sum():.3f} ktce"
            )
        allocation = allocation + residual * headroom / max(float(headroom.sum()), 1e-9)
    df["allocation"] = allocation
    realized = float(df["allocation"].sum())
    n_capped = int((df["cap"] > theta_limit + 1e-9).sum())
    print(
        "  [data_loader] 2025 AF anchor (share-based): "
        f"rate={realized/max(total_fuel,1e-9):.6f}, supply={realized:.3f} ktce, "
        f"capped-by-technical-ceiling={n_capped}, residual redistributed={max(residual,0.0):.3f} ktce"
    )
    return dict(zip(df["plant_id"].astype(int), df["allocation"].astype(float)))


def build_province_af_pool_ktce(biomass_df, waste_df, prov_list, years):
    """
    Build conserved province-level AF pools in ktce/yr.

    Biomass source is an accessible EJ/year field; waste source is accessible
    kt/year for the reference year. Waste gradually moves from base to high
    accessibility following the v3 maturity schedule.
    """
    biomass_pool = {}
    if not biomass_df.empty and AF_BIOMASS_POOL_COLUMN in biomass_df.columns:
        for _, row in biomass_df.iterrows():
            prov = str(row["province_cn"])
            ej = float(row.get(AF_BIOMASS_POOL_COLUMN, 0.0) or 0.0)
            biomass_pool[prov] = ej * 1e9 / GJ_PER_TCE / 1000.0

    waste_base = {}
    waste_high = {}
    if not waste_df.empty and "year_hist" in waste_df.columns:
        sub = waste_df[waste_df["year_hist"] == AF_WASTE_REFERENCE_YEAR]
        for _, row in sub.iterrows():
            prov = str(row["province_cn"])
            base_kt = float(row.get(AF_WASTE_POOL_COLUMN, 0.0) or 0.0)
            high_kt = float(row.get(AF_WASTE_POOL_HIGH_COLUMN, base_kt) or base_kt)
            waste_base[prov] = base_kt * MSW_TCE_PER_KT
            waste_high[prov] = high_kt * MSW_TCE_PER_KT

    result = {}
    channel = {}
    for prov in prov_list:
        prov = str(prov)
        bio_full = biomass_pool.get(prov, 0.0)
        base = waste_base.get(prov, 0.0)
        high = waste_high.get(prov, base)
        for yr in years:
            bio_maturity = float(AF_BIOMASS_ACCESS_MATURITY.get(int(yr), 1.0))
            waste_maturity = float(AF_WASTE_ACCESS_MATURITY.get(int(yr), 0.0))
            bio = bio_full * bio_maturity
            waste = base + waste_maturity * max(0.0, high - base)
            result[(prov, int(yr))] = bio + waste
            channel[(prov, int(yr))] = {"bio": bio, "wst": waste}
    return result, channel


# ── P0-4: regional demand and clinker transport (province market units) ──────
# The market unit is a set of ~150 DISTRIBUTED MARKET NODES (2026-09-12), built
# by v5/model/preprocessing/build_market_nodes.py. The province single point was
# retired because it could not produce an endogenous utilisation: dropping a
# distant plant inside a province leaves the retained plants' distance to the
# province centroid unchanged. The 1,713-node 50 km grid was retired because its
# equality balances were structurally infeasible and its gradient competed with
# the resource conditions the study identifies. See config_v5.

def load_demand_nodes(path=None):
    """Load the demand-node geography (DESCRIPTIVE ONLY, not used in the model).

    Supplies the 50 km population shape used to build the market nodes, the
    evidence for the 65/35 variance split, and figures.
    """
    target = Path(path) if path is not None else Path(DEMAND_NODE_FILE)
    if not target.exists():
        raise FileNotFoundError(
            f"demand-node file not found: {target}\n"
            f"  build it with: python v5/model/preprocessing/build_demand_nodes.py"
        )
    df = pd.read_csv(target)
    required = {
        "node_id", "lon", "lat", "province", "pop",
        "pop_share_national", "pop_share_within_province",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"demand_nodes.csv is missing columns: {sorted(missing)}")
    df["node_id"] = df["node_id"].astype(int)
    df["province"] = df["province"].astype(str)
    print(
        f"  [data_loader] demand nodes (descriptive layer): {len(df)} in "
        f"{df['province'].nunique()} provinces"
    )
    return df


def load_market_nodes(path=None):
    """Load the optimization market-node geography.

    Columns: node_id, lon, lat, province, pop, pop_share_national,
    pop_share_within_province, n_source_nodes. The within-province population
    share is the shape that turns province totals into node demand.
    """
    target = Path(path) if path is not None else Path(DEMAND_MARKET_NODE_FILE)
    if not target.exists():
        raise FileNotFoundError(
            f"market-node file not found: {target}\n"
            f"  build it with: python v5/model/preprocessing/build_market_nodes.py"
        )
    df = pd.read_csv(target)
    required = {"node_id", "lon", "lat", "province", "pop",
                "pop_share_within_province"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"demand_market_nodes.csv is missing columns: {sorted(missing)}")
    df["node_id"] = df["node_id"].astype(int)
    df["province"] = df["province"].astype(str)
    print(
        f"  [data_loader] market nodes: {len(df)} in {df['province'].nunique()} "
        f"provinces (target {int(getattr(_cfg_runtime, 'DEMAND_MARKET_NODE_TARGET', len(df)))})"
    )
    return df


def build_market_node_shares_by_year(market_nodes_df, province_shares_by_year):
    """{year: {node_id: share}} with share = province share x within-province shape.

    This is exactly the two-level allocation: node demand =
    national clinker(t) x share. Each year's shares sum to one, so the node
    balances together conserve the national total and no separate national
    balance is needed.
    """
    province_of = dict(zip(market_nodes_df["node_id"].astype(int),
                           market_nodes_df["province"].astype(str)))
    shape = dict(zip(market_nodes_df["node_id"].astype(int),
                     market_nodes_df["pop_share_within_province"].astype(float)))
    out = {}
    for year, prov_shares in province_shares_by_year.items():
        shares = {
            nid: float(prov_shares.get(province_of[nid], 0.0)) * float(shape[nid])
            for nid in province_of
        }
        total = sum(shares.values())
        if total <= 0:
            raise ValueError(f"market-node shares sum to zero in {year}")
        out[int(year)] = {nid: value / total for nid, value in shares.items()}
    print(
        f"  [data_loader] market-node demand shares: {len(out)} periods, "
        f"sum={sum(out[min(out)].values()):.6f}, "
        f"max node share={max(out[min(out)].values()):.4f}"
    )
    return out


def load_market_arcs(path=None):
    """Candidate (plant, market node) arcs with haversine distance in km.

    The set is built adaptively and gated by an exact transportation (Hall)
    feasibility test in build_market_nodes.py; here it is only read and checked
    for structural consistency (every plant has an arc, every node is reachable,
    no distance exceeds the declared maximum, distances positive).
    """
    target = Path(path) if path is not None else Path(DEMAND_MARKET_ARC_FILE)
    if not target.exists():
        raise FileNotFoundError(
            f"market-arc file not found: {target}\n"
            f"  build it with: python v5/model/preprocessing/build_market_nodes.py"
        )
    df = pd.read_csv(target)
    required = {"plant_id", "node_id", "distance_km"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"demand_market_arcs.csv is missing columns: {sorted(missing)}")
    arcs = {
        (int(r.plant_id), int(r.node_id)): float(r.distance_km)
        for r in df.itertuples(index=False)
    }
    if len(arcs) != len(df):
        raise ValueError("demand_market_arcs.csv contains duplicate (plant, node) pairs")
    if any(d <= 0 for d in arcs.values()):
        raise ValueError("demand_market_arcs.csv contains non-positive distances")
    print(
        f"  [data_loader] market arcs: {len(arcs):,} (plant, node) pairs, "
        f"median distance {np.median(list(arcs.values())):.0f} km"
    )
    return arcs


def build_province_demand_shares(liao_df, cement_output_path=None, output_override=None,
                                 ratio_fallback=None):
    """2025 provincial clinker demand shares from official cement-output statistics.

    Province totals come from statistics rather than from population so that the
    baseyear anchor (build_baseyear_plant_utilization) stays consistent and the
    known net-import provinces keep their demand. Population enters only through
    the province market point (see build_province_market_points).
    """
    path = Path(cement_output_path) if cement_output_path else Path(BASEYEAR_OUTPUT_CSV)
    output = pd.read_csv(path)
    ratio = liao_df.set_index("province_cn")["liao_clinker_ratio_effective"].to_dict()
    cement_10kt = {
        str(k): float(v)
        for k, v in output.set_index("province_cn")["cement_output_10kt"].items()
    }
    for prov, value in dict(output_override or {}).items():
        cement_10kt.setdefault(str(prov), float(value))

    fallback = float(ratio_fallback if ratio_fallback is not None
                     else DEMAND_PROVINCE_RATIO_FALLBACK)
    clinker_kt, used_fallback = {}, []
    for prov, value in cement_10kt.items():
        prov_ratio = ratio.get(prov)
        if prov_ratio is None:
            prov_ratio = fallback
            used_fallback.append(prov)
        clinker_kt[prov] = float(value) / 100.0 * 1000.0 * float(prov_ratio)

    total = sum(clinker_kt.values())
    if total <= 0:
        raise ValueError("provincial clinker totals are empty")
    if used_fallback:
        print(f"  [data_loader] clinker-ratio fallback {fallback:.2f} used for: {used_fallback}")
    print(
        f"  [data_loader] provincial demand shares: {len(clinker_kt)} provinces, "
        f"total clinker {total/1000.0:.1f} Mt"
    )
    return {p: v / total for p, v in clinker_kt.items()}, clinker_kt


def build_province_shares_by_year(province_shares, years, nodes_df=None, convergence=0.0):
    """{year: {province: share}}.

    With convergence = 0 the 2025 shares are held for all periods (the same
    time-invariant convention as Wang et al. 2026). With convergence > 0 the
    shares move linearly toward population shares, reaching that fraction of the
    way by the final period.
    """
    years = [int(y) for y in years]
    first, last = years[0], years[-1]
    population = {}
    if nodes_df is not None and len(nodes_df):
        population = (
            nodes_df.groupby("province")["pop"].sum() / nodes_df["pop"].sum()
        ).to_dict()

    out = {}
    for year in years:
        w = (float(convergence) * (year - first) / (last - first)
             if (convergence and last > first) else 0.0)
        adjusted = {}
        for prov in set(province_shares) | set(population):
            base = float(province_shares.get(prov, population.get(prov, 0.0)))
            pop = float(population.get(prov, base))
            adjusted[prov] = (1.0 - w) * base + w * pop
        total = sum(adjusted.values())
        if total <= 0:
            raise ValueError("province shares sum to zero")
        out[year] = {p: v / total for p, v in adjusted.items()}
    print(
        f"  [data_loader] provincial shares by year: {len(out[first])} provinces, "
        f"sum={sum(out[first].values()):.6f}, convergence={convergence:.2f}"
    )
    return out


def build_province_market_points(nodes_df):
    """Demand-weighted centroid (lon, lat) per province, from the node layer."""
    points = {}
    for prov, sub in nodes_df.groupby("province"):
        w = sub["pop_share_within_province"].to_numpy(dtype=float)
        total = float(w.sum())
        if total <= 0:
            w = np.ones(len(sub), dtype=float)
            total = float(len(sub))
        points[str(prov)] = (
            float((sub["lon"].to_numpy(dtype=float) * w).sum() / total),
            float((sub["lat"].to_numpy(dtype=float) * w).sum() / total),
        )
    return points


def load_all():
    """
    Load all data needed for v5 model.
    Returns a dict with all data structures.
    """
    t0 = time.time()
    print("\n" + "=" * 60)
    print("  Data Loader v5")
    print("=" * 60)

    plants = load_plants()
    tier_map = load_location_tier()
    storage = load_storage()
    # process_adjustment_path.csv stays on disk as provenance but is no longer
    # read into the model (its consumers were removed 2026-09-12).
    scm, _proc_adj_unused, liao, af_biomass, af_waste = load_regional()
    external_paths, external_path_sources = load_external_technology_paths()
    demand = load_demand()

    prov_corridor = build_province_corridor_map(scm)
    plant_emission_factors = build_plant_emission_factors(plants, liao)
    af_access_df = load_corrected_af_access()
    af_share_bio, af_share_wst = build_af_access_shares(plants, af_access_df)
    # build_af_expansion_ceiling was removed on 2026-09-13 (see its tombstone): the
    # deployment ceiling must not be baked into the plant resource allocation.

    # Province list for ARM/LCC parameter indexing
    prov_list = list(scm['province_cn'].unique())
    province_af_pool_ktce, province_af_pool_channel = build_province_af_pool_ktce(
        af_biomass, af_waste, prov_list, T_LIST
    )

    # Exogenous front-end/product-side paths.
    arm_column = f"arm_{ARM_PATH_CASE}"
    ee_column = f"ee_{EE_PATH_CASE}"
    # The CCR (clinker-ratio) case is read at CALL time through the config
    # module so that main.py --ccr-path-case can switch it per run (the same
    # call-time pattern as ENABLE_REGIONAL_DEMAND).
    ccr_case = str(getattr(_cfg_runtime, "CCR_PATH_CASE", "central")).lower()
    clinker_ratio_column = f"clinker_ratio_{ccr_case}"
    if (
        arm_column not in external_paths.columns
        or ee_column not in external_paths.columns
        or clinker_ratio_column not in external_paths.columns
    ):
        raise ValueError(
            f"Unknown external path cases: ARM={ARM_PATH_CASE!r}, EE={EE_PATH_CASE!r}, "
            f"CCR={ccr_case!r}"
        )
    arm_national_path = external_paths.set_index("year")[arm_column].astype(float).to_dict()
    ee_external_path = external_paths.set_index("year")[ee_column].astype(float).to_dict()
    arm_external_path = {
        (str(province), int(year)): float(arm_national_path[int(year)])
        for province in prov_list
        for year in T_LIST
    }

    (
        baseyear_utilization,
        baseyear_province_clinker_kt,
        baseyear_clinker_ratio,
        baseyear_province_gap_kt,
    ) = build_baseyear_plant_utilization(plants, liao, BASEYEAR_OUTPUT_CSV)
    national_clinker_ratio_path = (
        external_paths.set_index("year")[clinker_ratio_column].astype(float).to_dict()
    )
    national_clinker_ratio_path[2025] = float(baseyear_clinker_ratio)

    # ── P0-4 v3: distributed market nodes and clinker transport arcs ─────
    # Read at call time (not import time) so a run can switch the layer off, or
    # change the transport-cost form, purely through the config module.
    regional_demand_on = bool(
        getattr(_cfg_runtime, "ENABLE_REGIONAL_DEMAND", ENABLE_REGIONAL_DEMAND)
    )
    if regional_demand_on:
        # Descriptive 50 km layer: positions the market nodes, carries the 65/35
        # variance evidence, feeds figures. Not balanced in the model.
        demand_nodes = load_demand_nodes()
        province_demand_shares, _ = build_province_demand_shares(
            liao,
            BASEYEAR_OUTPUT_CSV,
            output_override=DEMAND_PROVINCE_OUTPUT_OVERRIDE,
            ratio_fallback=DEMAND_PROVINCE_RATIO_FALLBACK,
        )
        province_shares_by_year = build_province_shares_by_year(
            province_demand_shares, T_LIST, nodes_df=demand_nodes,
            convergence=DEMAND_PROVINCIAL_SHARE_CONVERGENCE,
        )
        province_market_points = build_province_market_points(demand_nodes)
        # Optimization layer: ~150 market nodes with a Hall-feasible arc set.
        # 2026-09-14: the paths are read at CALL time through the config module (the
        # same pattern as CCR_PATH_CASE) so a run can be pointed at an alternative
        # node/arc build -- e.g. the ~75-node aggregation used as the spatial
        # robustness check -- without editing data files in place. Important because
        # the aggregation-robustness test must NOT mutate the central inputs.
        market_nodes = load_market_nodes(
            getattr(_cfg_runtime, "DEMAND_MARKET_NODE_FILE", None)
        )
        market_node_shares_by_year = build_market_node_shares_by_year(
            market_nodes, province_shares_by_year
        )
        demand_arcs = load_market_arcs(
            getattr(_cfg_runtime, "DEMAND_MARKET_ARC_FILE", None)
        )
    else:
        demand_nodes, province_demand_shares = None, None
        province_shares_by_year, province_market_points = None, None
        market_nodes, market_node_shares_by_year, demand_arcs = None, None, None

    # P0-2 option (b): the plant cap is a share-weighted slice of the province
    # resource pool, not an independent absolute cap. Since 2026-09-13 the pool is
    # the RAW province resource (no deployment ceiling, no demand scaling) -- see
    # build_af_province_allocation. The deployment pace is carried only by the
    # model's national expansion constraint.
    af_alloc_bio, af_alloc_wst = build_af_province_allocation(
        province_af_pool_channel, T_LIST,
    )
    baseyear_af_supply_ktce = build_baseyear_af_supply(
        plants,
        baseyear_utilization,
        af_share_bio,
        af_share_wst,
        af_alloc_bio,
        af_alloc_wst,
        plant_emission_factors=plant_emission_factors,
        af_energy_caliber=str(getattr(_cfg_runtime, "AF_ENERGY_CALIBER", "plant_heat_demand")),
    )

    # Source-sink assignment
    from src_v5.config_v5 import (
        TRANSPORT_MAX_KM, NEAREST_SINKS_PER_PLANT,
    )
    plant_storage = build_plant_storage_assignment(
        plants, storage,
        max_km=TRANSPORT_MAX_KM,
        k_nearest=NEAREST_SINKS_PER_PLANT,
    )

    # ── v3 CCS additions ─────────────────────────────────────────────────
    # Mark initial CCS projects
    initial_ccs_ids = set(INITIAL_CCS_PROJECTS.keys())
    plants['is_initial_ccs'] = plants['plant_id'].isin(initial_ccs_ids)
    initial_ccs_list = plants[plants['is_initial_ccs']]['plant_id'].tolist()
    print(f"  [data_loader] initial CCS projects: {initial_ccs_list}")

    # Offshore storage flag (default False if column missing)
    if 'is_offshore' not in storage.columns:
        storage['is_offshore'] = False
    n_offshore = storage['is_offshore'].sum()
    print(f"  [data_loader] offshore storage nodes: {n_offshore}/{len(storage)}")

    # Cluster metadata are retained for post-processing only. The optimization
    # uses direct plant-to-storage routes and does not require these files.
    cluster_csv = DATA_INPUT / "plants" / "cluster_assignment.csv"
    whitelist_csv = DATA_INPUT / "storage" / "cluster_sink_whitelist.csv"

    cluster_df = pd.read_csv(cluster_csv)
    whitelist_df = pd.read_csv(whitelist_csv)

    # plant_id → cluster_id
    plant_cluster_map = dict(zip(cluster_df["plant_id"], cluster_df["cluster_id"]))
    # cluster_id → [plant_ids]
    cluster_member_map = {}
    for cid in cluster_df["cluster_id"].unique():
        cluster_member_map[cid] = cluster_df[cluster_df["cluster_id"] == cid]["plant_id"].tolist()
    # cluster_id → hub_plant_id
    cluster_hub_map = dict(zip(cluster_df["cluster_id"], cluster_df["hub_plant_idx"]))
    cluster_hub_map = {int(k): int(v) for k, v in cluster_hub_map.items()}
    # cluster_id → {dsa: [(storage_idx, dist), ...], eor: [(storage_idx, dist), ...]}
    cluster_storage_whitelist = {}
    for cid in whitelist_df["cluster_id"].unique():
        sub = whitelist_df[whitelist_df["cluster_id"] == cid]
        dsa_list = sub[sub["sink_type"] == "dsa"][["storage_idx", "hub_distance_km"]].values.tolist()
        eor_list = sub[sub["sink_type"] == "eor"][["storage_idx", "hub_distance_km"]].values.tolist()
        cluster_storage_whitelist[int(cid)] = {
            "dsa": [(int(s), float(d)) for s, d in dsa_list],
            "eor": [(int(s), float(d)) for s, d in eor_list],
        }

    n_clusters = cluster_df["cluster_id"].nunique()
    print(f"  [data_loader] clusters: {n_clusters}, whitelist pairs: {len(whitelist_df)}")

    storage_idx_set = set(storage["storage_idx"].astype(int).tolist())
    wl_idx_set = set()
    for sinks in cluster_storage_whitelist.values():
        for s, _ in sinks.get("dsa", []) + sinks.get("eor", []):
            wl_idx_set.add(int(s))
    mismatch = wl_idx_set - storage_idx_set
    if mismatch:
        # The cluster/whitelist layer is post-processing only (the optimization
        # routes plants to sinks directly), so a stale entry must not become a
        # pipeline gate. Drop the entries that no longer resolve and keep going.
        for cid, sinks in cluster_storage_whitelist.items():
            for route_type in ("dsa", "eor"):
                routes = sinks.get(route_type, [])
                sinks[route_type] = [r for r in routes if int(r[0]) in storage_idx_set]
        print(
            f"  [data_loader] cluster whitelist: dropped references to "
            f"{len(mismatch)} storage node(s) no longer present (post-processing layer)"
        )

    data = {
        "plants": plants,
        "tier_map": tier_map,
        "storage": storage,
        "plant_storage": plant_storage,
        "scm": scm,
        "proc_adj_removed_20260912": "process_adjustment_path.csv no longer read into the model (dead-key cleanup); file kept on disk as provenance",
        "liao": liao,
        "af_biomass": af_biomass,
        "af_waste": af_waste,
        "demand": demand,
        "prov_corridor": prov_corridor,
        "plant_emission_factors": plant_emission_factors,
        "af_share_bio": af_share_bio,
        "af_share_wst": af_share_wst,
        "af_alloc_bio": af_alloc_bio,
        "af_alloc_wst": af_alloc_wst,
        "province_af_pool_channel": province_af_pool_channel,
        "province_af_pool_ktce": province_af_pool_ktce,
        # Observed base year and external technology paths
        "baseyear_utilization": baseyear_utilization,
        "baseyear_province_clinker_kt": baseyear_province_clinker_kt,
        "baseyear_province_gap_kt": baseyear_province_gap_kt,
        "baseyear_af_supply_ktce": baseyear_af_supply_ktce,
        "national_clinker_ratio_path": national_clinker_ratio_path,
        # P0-4 v3 distributed market nodes
        "demand_nodes": demand_nodes,                     # descriptive 50 km layer
        "province_demand_shares": province_demand_shares,
        "province_shares_by_year": province_shares_by_year,   # {year: {province: share}}
        "province_market_points": province_market_points,     # descriptive centroids
        "market_nodes": market_nodes,                 # optimization geography
        "market_node_shares_by_year": market_node_shares_by_year,  # {year: {node_id: share}}
        "demand_arcs": demand_arcs,                   # {(plant_id, node_id): km}
        "demand_market_unit": str(DEMAND_MARKET_UNIT),
        "demand_node_layer_used_in_optimization": bool(DEMAND_NODE_LAYER_USED_IN_OPTIMIZATION),
        "regional_demand_enabled": regional_demand_on,
        "ee_path": ee_external_path,
        "external_technology_path_table": external_paths,
        "external_technology_path_sources": external_path_sources,
        "arm_path_case": str(ARM_PATH_CASE),
        "ee_path_case": str(EE_PATH_CASE),
        "ccr_path_case": str(ccr_case),
        "process_adjustment": arm_external_path,
        # CCS
        "initial_ccs_list": initial_ccs_list,
        # v3 cluster/hub
        "plant_cluster_map": plant_cluster_map,      # {plant_id: cluster_id}
        "cluster_member_map": cluster_member_map,    # {cluster_id: [plant_ids]}
        "cluster_hub_map": cluster_hub_map,          # {cluster_id: hub_plant_id}
        "cluster_storage_whitelist": cluster_storage_whitelist,  # {cluster_id: {dsa:[], eor:[]}}
    }

    print(f"\n  Total load time: {time.time()-t0:.2f}s")
    print("=" * 60)
    return data
