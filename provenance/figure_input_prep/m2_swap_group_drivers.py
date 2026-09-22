"""M2 post-processing (2026-09-18): do the 2060 asset-swap groups differ on the
MODEL-EFFECTIVE margins (AF accessibility cap vs heat demand; storage
whitelist access), not just on raw catchment medians?

Inputs (all inside the repo):
  - v5/scenarios/rd_numbers_20260915/data02_C1-only_plants.csv / data02_C4-only_plants.csv
  - v5/results/formal_v1_20260914/{C1_central_J,C4_equalized_J}/... (operation status,
    resource-utilization anchor, ee_rate, heat tiers, equalized pool totals)
  - v5/data/plant_af_access_corrected.csv (plant catchment weights; P0-2 corrected)
  - v5/data/model_input/regional/af_biomass_supply.csv / af_waste_supply.csv (province pools)
  - v5/data/model_input/regional/scm_proxy.csv (province list)
  - v5/data/model_input/storage/storage_data_tif.csv + plant_data.xlsx (whitelist rebuild)

Replicated model logic (sources cited inline):
  - AF allocation cap: af_supply[i,t] <= kappa * (A_bio(p,t)*share_bio[i] + A_wst(p,t)*share_wst[i]),
    kappa = AF_ACCESS_ALLOCATION_HEADROOM = 2   (final_builder.py:686-696)
  - H[i,t] = h_i * (1 - EE_t) * cap_i   (final_builder.py:612, 638-641); h_i tier values from
    the run's effective_config.af_plant_heat_intensity_tce_per_t (cuts 4,200 / 2,000 t/d)
  - Province pools: build_province_af_pool_ktce (data_loader_v5.py:633-673) with the maturity
    schedules in config_v5.py:493-512
  - C4 equalization: main.py:392-503 (capacity-weighted within-province shares; province slices
    equalized by installed capacity, per-channel totals preserved, 2025 anchored unchanged)
  - Plant-sink whitelist: build_plant_storage_assignment (data_loader_v5.py:195-265), 500 km,
    3 nearest per type + 2 highest-capacity, <= 8 pairs/plant, storage nodes >= 10 Mt total
    (STORAGE_MIN_NODE_CAPACITY_MT)

All distances are MODEL-PROXY distances: haversine on the candidate plant-sink arc
whitelist, not routed transport distances.

Outputs: m2_plant_metrics.csv, m2_report.txt (this script prints the same report).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "v5/results/formal_v1_20260914"
SCEN = ROOT / "v5/scenarios/rd_numbers_20260915"
REGIONAL = ROOT / "v5/data/model_input/regional"
OUTDIR = Path(__file__).resolve().parent

YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]

# --- config_v5 constants (copied verbatim) -----------------------------------
KAPPA = 2.0                    # AF_ACCESS_ALLOCATION_HEADROOM
THETA = 0.60                   # AF_TECHNICAL_TSR_CEILING
DAYS_PER_YEAR = 310
GJ_PER_TCE = 29.3076
MSW_TCE_PER_KT = 0.12
AF_WASTE_ACCESS_MATURITY = {2025: 0.10, 2030: 0.25, 2035: 0.40, 2040: 0.45,
                            2045: 0.70, 2050: 1.00, 2055: 1.00, 2060: 1.00}
AF_BIOMASS_ACCESS_MATURITY = {2025: 0.30, 2030: 0.40, 2035: 0.55, 2040: 0.70,
                              2045: 0.85, 2050: 1.00, 2055: 1.00, 2060: 1.00}
TRANSPORT_MAX_KM = 500.0
NEAREST_SINKS_PER_TYPE = 3
HIGH_CAPACITY_SINKS_PER_PLANT = 2
NEAREST_SINKS_PER_PLANT = 8
STORAGE_MIN_NODE_CAPACITY_MT = 10.0

RESULT_JSON = {
    "C1": RUNS / "C1_central_J/S1_baseline_results.json",
    "C4": RUNS / "C4_equalized_J/S3_all_spatial_equalized_results.json",
}
CSV_DIR = {
    "C1": RUNS / "C1_central_J/S1_baseline",
    "C4": RUNS / "C4_equalized_J/S3_all_spatial_equalized",
}


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1r, lat2r = np.radians(lat1), np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def build_province_pools():
    """Replicates data_loader_v5.build_province_af_pool_ktce -> channel dict."""
    bio_df = pd.read_csv(REGIONAL / "af_biomass_supply.csv")
    wst_df = pd.read_csv(REGIONAL / "af_waste_supply.csv")
    prov_list = list(pd.read_csv(REGIONAL / "scm_proxy.csv")["province_cn"].unique())

    biomass_pool = {
        str(r["province_cn"]): float(r["bio_supply_ej_access_base"]) * 1e9 / GJ_PER_TCE / 1000.0
        for _, r in bio_df.iterrows()
    }
    waste_base, waste_high = {}, {}
    sub = wst_df[wst_df["year_hist"] == 2018]
    for _, r in sub.iterrows():
        prov = str(r["province_cn"])
        base = float(r["residual_kt_access_base"])
        high = float(r["residual_kt_access_high"])
        waste_base[prov] = base * MSW_TCE_PER_KT
        waste_high[prov] = high * MSW_TCE_PER_KT

    channel = {}
    for prov in prov_list:
        bio_full = biomass_pool.get(prov, 0.0)
        base = waste_base.get(prov, 0.0)
        high = waste_high.get(prov, base)
        for yr in YEARS:
            bio = bio_full * AF_BIOMASS_ACCESS_MATURITY[yr]
            wst = base + AF_WASTE_ACCESS_MATURITY[yr] * max(0.0, high - base)
            channel[(prov, yr)] = {"bio": bio, "wst": wst}
    return channel, prov_list


def c1_allocations(channel):
    """C1: plant cap slice = raw province pool x within-province accessibility share."""
    alloc_bio = {(p, y): v["bio"] for (p, y), v in channel.items()
                 if v["bio"] > 0 or v["wst"] > 0}
    alloc_wst = {(p, y): v["wst"] for (p, y), v in channel.items()
                 if v["bio"] > 0 or v["wst"] > 0}
    return alloc_bio, alloc_wst


def c4_allocations(channel, alloc_bio, alloc_wst, plants, prov_list):
    """Replicates main.py apply_scenario_modifications('S3_all_spatial_equalized')."""
    share_weight = plants.groupby("province")["capacity"].sum().astype(float).to_dict()

    def rescale(original, kind):
        totals = {}
        for (_, year), value in original.items():
            totals[int(year)] = totals.get(int(year), 0.0) + float(value)
        weights = {p: float(share_weight.get(p, 0.0)) for p in prov_list}
        weight_sum = sum(weights.values()) or 1.0
        result = {}
        for (province, year), value in original.items():
            year = int(year)
            if year == 2025:
                result[(province, year)] = float(value)
                continue
            parts = channel.get((province, year))
            denom = float(parts["bio"]) + float(parts["wst"]) if parts is not None else 0.0
            share_of_channel = (float(parts[kind]) / denom) if denom > 0 else (1.0 if kind == "bio" else 0.0)
            result[(province, year)] = totals.get(year, 0.0) * weights[province] / weight_sum * share_of_channel
        for year, target in totals.items():
            if year == 2025:
                continue
            current = sum(float(v) for (_, y), v in result.items() if int(y) == year)
            if current > 0:
                factor = float(target) / current
                for key in list(result):
                    if int(key[1]) == year:
                        result[key] = float(result[key]) * factor
        return result

    return rescale(alloc_bio, "bio"), rescale(alloc_wst, "wst")


def within_province_shares(plants, col):
    out = {}
    for _, sub in plants.groupby("province"):
        total = float(sub[col].sum())
        for r in sub.itertuples(index=False):
            out[int(r.plant_id)] = (
                float(getattr(r, col)) / total if total > 0 else 1.0 / max(len(sub), 1)
            )
    return out


def build_whitelist(plants, storage):
    """Replicates data_loader_v5.build_plant_storage_assignment."""
    s = storage.copy()
    total_mt = s["dsa_capacity"].fillna(0.0) + s["eor_capacity"].fillna(0.0)
    s = s[total_mt >= STORAGE_MIN_NODE_CAPACITY_MT].reset_index(drop=True)
    s_lat, s_lon = s["latitude"].to_numpy(), s["longitude"].to_numpy()
    s_idx = s["storage_idx"].astype(int).to_numpy()
    s_dsa = s["dsa_capacity"].fillna(0.0).to_numpy()
    s_eor = s["eor_capacity"].fillna(0.0).to_numpy()

    rows = []
    for r in plants.itertuples(index=False):
        pid = int(r.plant_id)
        d = haversine_km(float(r.latitude), float(r.longitude), s_lat, s_lon)
        in_range = d <= TRANSPORT_MAX_KM
        if not (in_range & ((s_dsa + s_eor) > 0)).any():
            rows.append({"plant_id": pid, "n_conn": 0, "n_dsa": 0, "n_eor": 0,
                         "nearest_km": np.nan, "nearest_dsa_km": np.nan,
                         "max_dsa_cap_mt": 0.0, "max_eor_cap_mt": 0.0})
            continue
        candidates = []
        for stype, cap in (("dsa", s_dsa), ("eor", s_eor)):
            valid = np.where(in_range & (cap > 0))[0]
            nearest = valid[np.argsort(d[valid])[:NEAREST_SINKS_PER_TYPE]]
            candidates.extend((int(j), stype) for j in nearest)
        all_routes = [(int(j), st)
                      for st, cap in (("dsa", s_dsa), ("eor", s_eor))
                      for j in np.where(in_range & (cap > 0))[0]]
        top_cap = sorted(all_routes,
                         key=lambda it: s_dsa[it[0]] if it[1] == "dsa" else s_eor[it[0]],
                         reverse=True)[:HIGH_CAPACITY_SINKS_PER_PLANT]
        candidates.extend(top_cap)
        seen, pairs = set(), []
        for j, stype in sorted(candidates, key=lambda it: d[it[0]]):
            key = (int(s_idx[j]), stype)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((int(s_idx[j]), float(d[j]), stype))
            if len(pairs) >= NEAREST_SINKS_PER_PLANT:
                break
        dsa_pairs = [p for p in pairs if p[2] == "dsa"]
        eor_pairs = [p for p in pairs if p[2] == "eor"]
        idx_to_dsa = dict(zip(s_idx.tolist(), s_dsa.tolist()))
        idx_to_eor = dict(zip(s_idx.tolist(), s_eor.tolist()))
        rows.append({
            "plant_id": pid, "n_conn": len(pairs),
            "n_dsa": len(dsa_pairs), "n_eor": len(eor_pairs),
            "nearest_km": min(p[1] for p in pairs),
            "nearest_dsa_km": min((p[1] for p in dsa_pairs), default=np.nan),
            "max_dsa_cap_mt": max((idx_to_dsa[p[0]] for p in dsa_pairs), default=0.0),
            "max_eor_cap_mt": max((idx_to_eor[p[0]] for p in eor_pairs), default=0.0),
        })
    return pd.DataFrame(rows).set_index("plant_id")


def describe(series):
    s = pd.Series(series).dropna()
    return {"n": int(s.size), "median": s.median(), "q1": s.quantile(0.25),
            "q3": s.quantile(0.75), "mean": s.mean()}


def fmt(d, nd=3):
    return (f"n={d['n']:3d}  median={d['median']:.3f}  IQR=[{d['q1']:.3f}, {d['q3']:.3f}]  "
            f"mean={d['mean']:.3f}")


def main():
    lines = []

    def out(text=""):
        print(text)
        lines.append(str(text))

    res_c1 = json.loads(RESULT_JSON["C1"].read_text())
    res_c4 = json.loads(RESULT_JSON["C4"].read_text())
    heat_tiers = [float(x) for x in res_c1["effective_config"]["af_plant_heat_intensity_tce_per_t"]]
    ee = {y: float(res_c1["summary"][str(y)]["ee_rate"]) for y in YEARS}
    assert heat_tiers == [float(x) for x in res_c4["effective_config"]["af_plant_heat_intensity_tce_per_t"]]

    # --- swap groups ----------------------------------------------------------
    c1_only = list(pd.read_csv(SCEN / "data02_C1-only_plants.csv").plant_id)
    c4_only = list(pd.read_csv(SCEN / "data02_C4-only_plants.csv").plant_id)
    op = {}
    for scen in ("C1", "C4"):
        st = pd.read_csv(CSV_DIR[scen] / "full_operation_status.csv")
        op[scen] = set(st[(st.period == 2060) & (st.operating == 1)].plant_id)
    assert set(c1_only) == op["C1"] - op["C4"] and len(c1_only) == 42
    assert set(c4_only) == op["C4"] - op["C1"] and len(c4_only) == 35

    # --- plants, AF pools, shares ----------------------------------------------
    access = pd.read_csv(ROOT / "v5/data/plant_af_access_corrected.csv")
    access["plant_id"] = access["plant_id"].astype(int)
    plants = access[["plant_id", "province", "capacity"]].copy()
    channel, prov_list = build_province_pools()
    alloc_bio_c1, alloc_wst_c1 = c1_allocations(channel)

    # Anchor: replicated C1 province pools vs the exported resource table.
    util = pd.read_csv(CSV_DIR["C1"] / "full_af_resource_utilization.csv")
    max_diff = 0.0
    for r in util.itertuples(index=False):
        pool = channel.get((str(r.province_cn), int(r.period)))
        if pool is None:
            continue
        max_diff = max(max_diff, abs(pool["bio"] + pool["wst"] - float(r.af_pool_ktce)))
    assert max_diff < 1e-6, f"C1 province pool replication off by {max_diff}"
    out(f"[check] C1 province AF pools replicated exactly (max abs diff {max_diff:.2e} ktce)")

    share_bio = within_province_shares(access, "bio_ktce")
    share_wst = within_province_shares(access, "msw_ktce")

    alloc_bio_c4, alloc_wst_c4 = c4_allocations(channel, alloc_bio_c1, alloc_wst_c1, plants, prov_list)
    # Anchor: equalized national totals vs the run's scenario_adjustments record.
    eq_ref = {int(k): float(v) for k, v in
              res_c4["scenario_adjustments"]["_af_equalized_pool_total_ktce_by_year"].items()}
    for y in YEARS:
        tot = sum(alloc_bio_c4.get((p, y), 0.0) + alloc_wst_c4.get((p, y), 0.0) for p in prov_list)
        assert abs(tot - eq_ref[y]) < 1e-6 * max(eq_ref[y], 1.0), (y, tot, eq_ref[y])
    out("[check] C4 equalized pool totals match the run record for all 8 periods")

    capshare = within_province_shares(plants.rename(columns={"capacity": "cap_tmp"})
                                      .assign(cap_tmp=plants["capacity"]), "cap_tmp")

    def plant_A(alloc_bio, alloc_wst, sb, sw, pid, prov, year):
        return (float(alloc_bio.get((prov, year), 0.0)) * sb.get(pid, 0.0)
                + float(alloc_wst.get((prov, year), 0.0)) * sw.get(pid, 0.0))

    # --- heat demand ------------------------------------------------------------
    def heat_intensity(cap_td):
        if cap_td >= 4200:
            return heat_tiers[0]
        if cap_td >= 2000:
            return heat_tiers[1]
        return heat_tiers[2]

    prov_of = dict(zip(plants.plant_id, plants.province))
    cap_td = dict(zip(plants.plant_id, plants.capacity.astype(float)))
    cap_kt = {p: c * DAYS_PER_YEAR / 1000.0 for p, c in cap_td.items()}
    h_i = {p: heat_intensity(c) for p, c in cap_td.items()}

    swap = sorted(set(c1_only) | set(c4_only))
    metrics = {"plant_id": swap,
               "group": ["C1-only" if p in c1_only else "C4-only" for p in swap],
               "province": [prov_of[p] for p in swap],
               "capacity_td": [cap_td[p] for p in swap]}
    for year in (2030, 2060):
        H = {p: h_i[p] * (1.0 - ee[year]) * cap_kt[p] for p in swap}
        metrics[f"H_ktce_{year}"] = [H[p] for p in swap]
        for tag, alloc_bio, alloc_wst, sb, sw in (
            ("C1cond", alloc_bio_c1, alloc_wst_c1, share_bio, share_wst),
            ("C4cond", alloc_bio_c4, alloc_wst_c4, capshare, capshare),
        ):
            A = {p: plant_A(alloc_bio, alloc_wst, sb, sw, p, prov_of[p], year) for p in swap}
            metrics[f"A_{tag}_{year}"] = [A[p] for p in swap]
            metrics[f"kA_over_H_{tag}_{year}"] = [KAPPA * A[p] / H[p] for p in swap]
            metrics[f"eff_max_tsr_{tag}_{year}"] = [min(THETA, KAPPA * A[p] / H[p]) for p in swap]

    df = pd.DataFrame(metrics).set_index("plant_id")

    # --- storage whitelist --------------------------------------------------------
    meta = pd.read_excel(ROOT / "v5/data/model_input/plants/plant_data.xlsx",
                         usecols=["id", "longitude", "latitude"])
    meta = meta.rename(columns={"id": "plant_id"})
    storage = pd.read_csv(ROOT / "v5/data/model_input/storage/storage_data_tif.csv")
    wl = build_whitelist(meta, storage)
    n_no_sink_all = int((wl.n_conn == 0).sum())
    out(f"[check] plants with no whitelisted sink within {TRANSPORT_MAX_KM:.0f} km: "
        f"{n_no_sink_all} of {len(wl)}")
    df = df.join(wl)

    df.to_csv(OUTDIR / "m2_plant_metrics.csv")

    # --- common eligibility set ----------------------------------------------------
    df["has_sink"] = df.n_conn > 0
    elig = df[df.has_sink]
    out()
    out("=" * 88)
    out("M2 SWAP-GROUP DRIVERS  (C1-only n=42 vs C4-only n=35; 2060 operation-status swap)")
    out("Distances are model-proxy: haversine on the candidate plant-sink arc whitelist.")
    out("=" * 88)
    out()
    out("Common eligibility set = swap lines with >=1 whitelisted plant-sink connection.")
    for g in ("C1-only", "C4-only"):
        sub = df[df.group == g]
        out(f"  {g}: {int(sub.has_sink.sum())}/{len(sub)} eligible; "
            f"excluded (no sink within 500 km): "
            f"{sorted(sub.index[~sub.has_sink].tolist())}")
    out("  AF metrics are computable for every swap line (province pool x share, kappa=2);")
    out("  storage metrics are structurally missing only for the no-sink lines above.")

    g1 = elig[elig.group == "C1-only"]
    g4 = elig[elig.group == "C4-only"]

    def block(title, col, nd=3, groups=(g1, g4)):
        out()
        out(title)
        out(f"  C1-only: {fmt(describe(groups[0][col]), nd)}")
        out(f"  C4-only: {fmt(describe(groups[1][col]), nd)}")
        ks = stats.ks_2samp(groups[0][col].dropna(), groups[1][col].dropna())
        out(f"  KS stat={ks.statistic:.3f}  p={ks.pvalue:.4f}  "
            f"(n={len(groups[0])}/{len(groups[1])}; descriptive, small samples)")
        return ks

    for year in (2030, 2060):
        out()
        out("-" * 88)
        out(f"YEAR {year}:  kappa*A_i / H_i   (H_i = h_i*(1-EE_{year})*nameplate; EE={ee[year]:.2f}; "
            f"ratio<1: allocation cap binds below full coverage; eff_max_tsr = min(0.60, ratio))")
        out("-" * 88)
        block(f"[AF] kappa*A/H under C1 (real) conditions, {year}", f"kA_over_H_C1cond_{year}")
        block(f"[AF] kappa*A/H under C4 (equalized) conditions, {year}", f"kA_over_H_C4cond_{year}")
        for tag in ("C1cond", "C4cond"):
            col = f"kA_over_H_{tag}_{year}"
            for g, sub in (("C1-only", g1), ("C4-only", g4)):
                s = sub[col]
                out(f"  share with ratio<1 ({tag}, {g}): {(s < 1).mean():.2f}; "
                    f"ratio<0.60: {(s < THETA).mean():.2f}")

    out()
    out("-" * 88)
    out("STORAGE ACCESS (whitelist eligibility; scenario-invariant)")
    out("-" * 88)
    block("[Storage] whitelisted connections per line", "n_conn", nd=1)
    block("[Storage] nearest whitelisted sink distance (km)", "nearest_km", nd=1)
    block("[Storage] nearest whitelisted DSA sink distance (km)", "nearest_dsa_km", nd=1)
    block("[Storage] max DSA capacity among whitelisted sinks (Mt)", "max_dsa_cap_mt", nd=1)

    # Excluded no-sink lines: AF stats separately.
    excl = df[~df.has_sink]
    if len(excl):
        out()
        out("Excluded no-sink lines (storage metrics structurally missing):")
        for g, sub in excl.groupby("group"):
            out(f"  {g}: n={len(sub)}, plant_ids={sorted(sub.index.tolist())}, "
                f"kA/H C1cond 2060 median={sub['kA_over_H_C1cond_2060'].median():.3f}")

    # --- 2D joint distribution -----------------------------------------------------
    out()
    out("-" * 88)
    out("2D JOINT DISTRIBUTION (2060): x = kappa*A/H (C1 real conditions), y = nearest sink km")
    out("-" * 88)
    x_med = elig["kA_over_H_C1cond_2060"].median()
    y_med = elig["nearest_km"].median()
    out(f"Pooled medians: kA/H={x_med:.3f}, nearest={y_med:.1f} km")
    out(f"{'quadrant':<28}{'C1-only':>9}{'C4-only':>9}")
    for xhi, yhi, label in ((True, False, "high kA/H, near sink"),
                            (True, True, "high kA/H, far sink"),
                            (False, False, "low kA/H, near sink"),
                            (False, True, "low kA/H, far sink")):
        mask = ((elig["kA_over_H_C1cond_2060"] >= x_med) == xhi) & ((elig["nearest_km"] >= y_med) == yhi)
        sub = elig[mask]
        out(f"{label:<28}{(sub.group == 'C1-only').sum():>9}{(sub.group == 'C4-only').sum():>9}")
    # Threshold-based view: ratio >= 1 vs distance <= pooled median.
    out()
    out("Threshold view (ratio >= 1 = full-load heat coverable by accessible AF):")
    out(f"{'quadrant':<34}{'C1-only':>9}{'C4-only':>9}")
    for rhi, yhi, label in ((True, False, "ratio>=1, near sink"),
                            (True, True, "ratio>=1, far sink"),
                            (False, False, "ratio<1, near sink"),
                            (False, True, "ratio<1, far sink")):
        mask = ((elig["kA_over_H_C1cond_2060"] >= 1.0) == rhi) & ((elig["nearest_km"] >= y_med) == yhi)
        sub = elig[mask]
        out(f"{label:<34}{(sub.group == 'C1-only').sum():>9}{(sub.group == 'C4-only').sum():>9}")

    # Equalization gain per group (the mechanism check).
    out()
    out("Equalization effect on the cap ratio, 2060 (C4cond minus C1cond):")
    for g, sub in (("C1-only", g1), ("C4-only", g4)):
        delta = sub["kA_over_H_C4cond_2060"] - sub["kA_over_H_C1cond_2060"]
        out(f"  {g}: median {delta.median():+.3f}, IQR [{delta.quantile(0.25):+.3f}, "
            f"{delta.quantile(0.75):+.3f}], mean {delta.mean():+.3f}")

    (OUTDIR / "m2_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {OUTDIR/'m2_plant_metrics.csv'} and {OUTDIR/'m2_report.txt'}")


if __name__ == "__main__":
    main()
