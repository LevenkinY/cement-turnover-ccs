"""
Data loader for the final v4 model.

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

from src_v4.config_v4 import (
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
    ARM_USE_CORRIDOR_ENVELOPE, ARM_PROCESS_TERMINAL_BY_CORRIDOR,
    ARM_PROCESS_DIFFUSION_PROFILE,
    ARM_SPATIAL_MODE, ARM_PATH_CASE, EE_PATH_CASE,
    NEAREST_SINKS_PER_TYPE, HIGH_CAPACITY_SINKS_PER_PLANT,
    CAPACITY_T_DAY_TO_KT_YR, TCE_PER_T_CLINKER, INITIAL_AF_RATE,
    AF_ENGINEERING_TSR_PATH,
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


def build_province_corridor_map(scm_df):
    """Build province → corridor mapping from scm_proxy."""
    return dict(zip(scm_df["province_cn"], scm_df["arm_corridor"]))


def build_province_clinker_ratio(scm_df):
    """Build province → recent clinker ratio mapping."""
    return dict(zip(scm_df["province_cn"], scm_df["liao_clinker_ratio_effective"]))


def build_process_adjustment(proc_df, prov_list, years, corridor_map=None):
    """
    Build province × year process adjustment dict from process_adjustment_path.csv.
    v3 style: process_adjustment[i,t] — ARM reduction factor (fraction, 0-1).
    """
    proc = proc_df.copy()
    if 'province_cn' in proc.columns and 'year' in proc.columns:
        result = {}
        for prov in prov_list:
            sub = proc[proc['province_cn'] == prov]
            for _, row in sub.iterrows():
                yr = int(row['year'])
                if yr in years:
                    raw = float(row['process_adjustment'])
                    if ARM_USE_CORRIDOR_ENVELOPE:
                        corridor = (corridor_map or {}).get(prov, "general")
                        lo, hi = ARM_PROCESS_TERMINAL_BY_CORRIDOR.get(
                            corridor,
                            ARM_PROCESS_TERMINAL_BY_CORRIDOR.get("general", (0.02, 0.05)),
                        )
                        score = row.get("process_score", row.get("legacy_process_score", 0.5))
                        score = 0.5 if pd.isna(score) else min(max(float(score), 0.0), 1.0)
                        terminal = float(lo) + score * (float(hi) - float(lo))
                        profile = float(ARM_PROCESS_DIFFUSION_PROFILE.get(yr, 1.0))
                        result[(prov, yr)] = profile * terminal
                    else:
                        result[(prov, yr)] = raw
        return result
    return {}


def build_clinker_ratio_adjustment(proc_df, prov_list, years):
    """
    Build province × year clinker ratio adjustment dict from process_adjustment_path.csv.
    v3 style: clinker_ratio_adjustment — reduction from baseline clinker ratio (fraction, 0-1).
    """
    proc = proc_df.copy()
    if 'province_cn' in proc.columns and 'year' in proc.columns:
        result = {}
        for prov in prov_list:
            sub = proc[proc['province_cn'] == prov]
            for _, row in sub.iterrows():
                yr = int(row['year'])
                if yr in years:
                    val = row.get('clinker_ratio_adjustment', 0.0)
                    if pd.notna(val):
                        result[(prov, yr)] = float(val)
                    else:
                        result[(prov, yr)] = 0.0
        return result
    return {}


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
    """
    df = plants_df[["plant_id", "source_process_ef", "source_fuel_ef"]].copy()
    df["proc_ef"] = pd.to_numeric(df["source_process_ef"], errors="coerce")
    df["fuel_ef"] = pd.to_numeric(df["source_fuel_ef"], errors="coerce")
    if df[["proc_ef", "fuel_ef"]].isna().any().any():
        raise ValueError("Plant emission factors contain missing or non-numeric values")
    return {
        int(row.plant_id): {"proc_ef": float(row.proc_ef), "fuel_ef": float(row.fuel_ef)}
        for row in df.itertuples(index=False)
    }


def build_raw_plant_af_access_ktce(plants_df):
    """Build raw overlapping plant-level AF catchment access in ktce/yr."""
    result = {}
    for row in plants_df.itertuples(index=False):
        msw = float(getattr(row, "msw_kt_yr_50km", 0.0) or 0.0)
        bio = float(getattr(row, "biomass_kt_yr_150km", 0.0) or 0.0)
        result[int(row.plant_id)] = msw * MSW_TCE_PER_KT + bio * BIOMASS_TCE_PER_KT
    return result


def build_plant_af_access_ktce(plants_df, province_pool_ktce, years):
    """
    Build conserved plant-level AF access caps.

    Raw catchments overlap across nearby plants, so their absolute sum should
    not be interpreted as available supply. In the default mode, raw catchment
    values become accessibility weights used to allocate each province-year AF
    pool across plants.
    """
    raw = build_raw_plant_af_access_ktce(plants_df)
    if AF_PLANT_ACCESS_MODE == "raw_catchment":
        return {
            (int(pid), int(yr)): float(access)
            for pid, access in raw.items()
            for yr in years
        }

    df = plants_df[["plant_id", "province", "capacity"]].copy()
    df["plant_id"] = df["plant_id"].astype(int)
    df["raw_access"] = df["plant_id"].map(raw).fillna(0.0)
    df["capacity"] = pd.to_numeric(df["capacity"], errors="coerce").fillna(0.0)

    result = {}
    for prov, sub in df.groupby("province"):
        raw_sum = float(sub["raw_access"].sum())
        cap_sum = float(sub["capacity"].sum())
        for yr in years:
            pool = float(province_pool_ktce.get((prov, int(yr)), 0.0))
            for row in sub.itertuples(index=False):
                if raw_sum > 0:
                    share = float(row.raw_access) / raw_sum
                elif cap_sum > 0:
                    share = float(row.capacity) / cap_sum
                else:
                    share = 1.0 / len(sub)
                result[(int(row.plant_id), int(yr))] = pool * share
    return result


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


def build_external_arm_path(process_adjustment, plants_df, years):
    """Create the exogenous ARM process-emission adjustment used by the model."""
    if ARM_SPATIAL_MODE == "province_corridor":
        return dict(process_adjustment)
    cap = plants_df.groupby("province")["capacity"].sum().to_dict()
    provinces = sorted(cap)
    result = {}
    for year in years:
        denom = sum(float(cap[p]) for p in provinces)
        mean = sum(
            float(cap[p]) * float(process_adjustment.get((p, int(year)), 0.0))
            for p in provinces
        ) / max(denom, 1e-9)
        for province in provinces:
            result[(province, int(year))] = mean
    return result


def build_baseyear_af_supply(
    plants_df,
    baseyear_utilization,
    plant_access_ktce,
    province_pool_ktce,
):
    """Allocate the observed national 2025 AF rate without optimizing it."""
    year = 2025
    engineering_cap = float(AF_ENGINEERING_TSR_PATH[year])
    rows = []
    for row in plants_df.itertuples(index=False):
        pid = int(row.plant_id)
        fuel = (
            float(row.capacity)
            * CAPACITY_T_DAY_TO_KT_YR
            * float(baseyear_utilization[pid])
            * TCE_PER_T_CLINKER
        )
        access = float(plant_access_ktce.get((pid, year), 0.0))
        rows.append({
            "plant_id": pid,
            "province": str(row.province),
            "fuel": fuel,
            "limit": min(access, engineering_cap * fuel),
        })
    df = pd.DataFrame(rows)
    df["allocation"] = np.minimum(INITIAL_AF_RATE * df["fuel"], df["limit"])

    for province, idx in df.groupby("province").groups.items():
        pool = float(province_pool_ktce.get((province, year), 0.0))
        current = float(df.loc[idx, "allocation"].sum())
        if current > pool and current > 0:
            df.loc[idx, "allocation"] *= pool / current

    target = INITIAL_AF_RATE * float(df["fuel"].sum())
    remaining = target - float(df["allocation"].sum())
    if remaining > 1e-9:
        province_available = {}
        for province, idx in df.groupby("province").groups.items():
            plant_headroom = float((df.loc[idx, "limit"] - df.loc[idx, "allocation"]).clip(lower=0).sum())
            pool_headroom = max(
                float(province_pool_ktce.get((province, year), 0.0))
                - float(df.loc[idx, "allocation"].sum()),
                0.0,
            )
            province_available[province] = min(plant_headroom, pool_headroom)
        available_total = sum(province_available.values())
        if remaining > available_total + 1e-6:
            raise ValueError(
                "The observed 2025 national AF rate is infeasible under plant access "
                f"and province pools: shortfall={remaining-available_total:.3f} ktce"
            )
        for province, available in province_available.items():
            if available <= 0:
                continue
            province_add = remaining * available / available_total
            idx = list(df.index[df["province"] == province])
            headroom = (df.loc[idx, "limit"] - df.loc[idx, "allocation"]).clip(lower=0)
            df.loc[idx, "allocation"] += province_add * headroom / max(float(headroom.sum()), 1e-9)

    realized_rate = float(df["allocation"].sum()) / max(float(df["fuel"].sum()), 1e-9)
    print(
        "  [data_loader] 2025 AF anchor: "
        f"rate={realized_rate:.6f}, supply={df['allocation'].sum():.3f} ktce"
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
    return result


def load_all():
    """
    Load all data needed for v4 model.
    Returns a dict with all data structures.
    """
    t0 = time.time()
    print("\n" + "=" * 60)
    print("  Data Loader v4")
    print("=" * 60)

    plants = load_plants()
    tier_map = load_location_tier()
    storage = load_storage()
    scm, proc_adj, liao, af_biomass, af_waste = load_regional()
    external_paths, external_path_sources = load_external_technology_paths()
    demand = load_demand()

    prov_corridor = build_province_corridor_map(scm)
    prov_clinker = build_province_clinker_ratio(scm)
    plant_emission_factors = build_plant_emission_factors(plants, liao)
    plant_af_access_raw_ktce = build_raw_plant_af_access_ktce(plants)

    # Province list for ARM/LCC parameter indexing
    prov_list = list(scm['province_cn'].unique())
    province_af_pool_ktce = build_province_af_pool_ktce(af_biomass, af_waste, prov_list, T_LIST)
    plant_af_access_ktce = build_plant_af_access_ktce(plants, province_af_pool_ktce, T_LIST)

    # Exogenous front-end/product-side paths.
    process_adj_envelope = build_process_adjustment(proc_adj, prov_list, T_LIST, prov_corridor)
    arm_column = f"arm_{ARM_PATH_CASE}"
    ee_column = f"ee_{EE_PATH_CASE}"
    if arm_column not in external_paths.columns or ee_column not in external_paths.columns:
        raise ValueError(
            f"Unknown external path cases: ARM={ARM_PATH_CASE!r}, EE={EE_PATH_CASE!r}"
        )
    arm_national_path = external_paths.set_index("year")[arm_column].astype(float).to_dict()
    ee_external_path = external_paths.set_index("year")[ee_column].astype(float).to_dict()
    arm_external_path = {
        (str(province), int(year)): float(arm_national_path[int(year)])
        for province in prov_list
        for year in T_LIST
    }
    clinker_ratio_adj = build_clinker_ratio_adjustment(proc_adj, prov_list, T_LIST)

    (
        baseyear_utilization,
        baseyear_province_clinker_kt,
        baseyear_clinker_ratio,
        baseyear_province_gap_kt,
    ) = build_baseyear_plant_utilization(plants, liao, BASEYEAR_OUTPUT_CSV)
    national_clinker_ratio_path = (
        external_paths.set_index("year")["clinker_ratio_central"].astype(float).to_dict()
    )
    national_clinker_ratio_path[2025] = float(baseyear_clinker_ratio)
    baseyear_af_supply_ktce = build_baseyear_af_supply(
        plants,
        baseyear_utilization,
        plant_af_access_ktce,
        province_af_pool_ktce,
    )

    # Source-sink assignment
    from src_v4.config_v4 import (
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
        raise ValueError(
            f"[data_loader] {len(mismatch)} whitelist storage_idx not in storage table: "
            f"{sorted(mismatch)[:10]}..."
        )

    data = {
        "plants": plants,
        "tier_map": tier_map,
        "storage": storage,
        "plant_storage": plant_storage,
        "scm": scm,
        "proc_adj": proc_adj,          # raw DataFrame for ARM corridor info
        "liao": liao,
        "af_biomass": af_biomass,
        "af_waste": af_waste,
        "demand": demand,
        "prov_corridor": prov_corridor,
        "prov_clinker": prov_clinker,
        "plant_emission_factors": plant_emission_factors,
        "plant_af_access_raw_ktce": plant_af_access_raw_ktce,
        "plant_af_access_ktce": plant_af_access_ktce,
        "province_af_pool_ktce": province_af_pool_ktce,
        # Observed base year and external technology paths
        "baseyear_utilization": baseyear_utilization,
        "baseyear_province_clinker_kt": baseyear_province_clinker_kt,
        "baseyear_province_gap_kt": baseyear_province_gap_kt,
        "baseyear_af_supply_ktce": baseyear_af_supply_ktce,
        "national_clinker_ratio_path": national_clinker_ratio_path,
        "ee_path": ee_external_path,
        "external_technology_path_table": external_paths,
        "external_technology_path_sources": external_path_sources,
        "arm_path_case": str(ARM_PATH_CASE),
        "ee_path_case": str(EE_PATH_CASE),
        "process_adjustment_envelope": process_adj_envelope,
        "process_adjustment": arm_external_path,
        "clinker_ratio_adjustment": clinker_ratio_adj,  # {(prov, year): float}
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
