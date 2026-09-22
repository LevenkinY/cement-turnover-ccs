"""Deliverable 2 (Fig. 3b data source): per-scenario 2060 operating lines with
model-effective resource conditions, for the C1/C2/C3 demand-pathway scatter.

Metrics per line (scenario-invariant, computed once; scenarios differ only in
WHICH lines operate in 2060):
  - kappa*A/H in 2060 under REAL AF conditions (M2 caliber):
      A_i = province AF pool(prov, 2060, real) x within-province accessibility
            share (bio share for the bio channel, MSW share for waste);
      H_i = h_i * (1 - EE_2060) * nameplate_kt;  kappa = 2 (allocation headroom);
      h_i from the run's effective_config heat-intensity tiers (cuts 4200/2000 t/d).
    Reuses tmp/m2_analysis_20260918/m2_swap_group_drivers.py functions verbatim
    (import, not copy) so the M2 pool replication and its anchor checks apply.
  - nearest whitelisted sink distance (km), model-proxy haversine on the
    candidate plant-sink arc whitelist (500 km, 3 nearest/type + 2 high-cap,
    <=8 pairs, sinks >= 10 Mt). 46 of 1572 lines have no whitelisted sink:
    nearest_km = NaN, has_sink = False (they remain in the file).
  - annual nameplate capacity (Mt/yr; full_plant_summary export).
  - in_shared_213: line operating in 2060 under ALL of C1/C2/C3.

Anchors asserted: operating sets 408/336/262 lines; shared set 213 lines,
327.081 Mt/yr; 46 no-sink lines; C1/C2/C3 share identical heat tiers and EE path.

Summary: per-scenario medians (unweighted) vs capacity-weighted statistics for
kA/H and distance, written to fig3b_resource_conditions_summary.md.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "v5/results/formal_v1_20260914"
OUTDIR = Path(__file__).resolve().parent

# Import the M2 module (functions only; main() is __main__-guarded).
spec = importlib.util.spec_from_file_location(
    "m2", ROOT / "tmp/m2_analysis_20260918/m2_swap_group_drivers.py"
)
m2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m2)

SCEN_CSV_DIR = {
    "C2": RUNS / "C2_demand_high/S1_baseline",
    "C1": RUNS / "C1_central_J/S1_baseline",
    "C3": RUNS / "C3_demand_low/S1_baseline",
}
SCEN_JSON = {
    "C2": RUNS / "C2_demand_high/S1_baseline_results.json",
    "C1": RUNS / "C1_central_J/S1_baseline_results.json",
    "C3": RUNS / "C3_demand_low/S1_baseline_results.json",
}
EXPECTED_LINES = {"C2": 408, "C1": 336, "C3": 262}


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    order = np.argsort(values.to_numpy())
    v, w = values.to_numpy()[order], weights.to_numpy()[order]
    cum = np.cumsum(w) - 0.5 * w
    return float(np.interp(0.5 * w.sum(), cum, v))


def main() -> None:
    res_c1 = json.loads(SCEN_JSON["C1"].read_text())
    heat_tiers = [float(x) for x in res_c1["effective_config"]["af_plant_heat_intensity_tce_per_t"]]
    ee = {y: float(res_c1["summary"][str(y)]["ee_rate"]) for y in m2.YEARS}
    for scen in ("C2", "C3"):
        res = json.loads(SCEN_JSON[scen].read_text())
        assert heat_tiers == [float(x) for x in res["effective_config"]["af_plant_heat_intensity_tce_per_t"]]
        for y in m2.YEARS:
            assert abs(ee[y] - float(res["summary"][str(y)]["ee_rate"])) < 1e-12
    print("[check] C1/C2/C3 share identical heat tiers and EE path")

    # --- all-plant resource metrics under real (C1) conditions, 2060 ---------
    access = pd.read_csv(ROOT / "v5/data/plant_af_access_corrected.csv")
    access["plant_id"] = access["plant_id"].astype(int)
    plants = access[["plant_id", "province", "capacity"]].copy()
    channel, prov_list = m2.build_province_pools()
    alloc_bio_c1, alloc_wst_c1 = m2.c1_allocations(channel)

    # Anchor to the run's exported AF pool table (same check as M2).
    util = pd.read_csv(SCEN_CSV_DIR["C1"] / "full_af_resource_utilization.csv")
    max_diff = 0.0
    for r in util.itertuples(index=False):
        pool = channel.get((str(r.province_cn), int(r.period)))
        if pool is None:
            continue
        max_diff = max(max_diff, abs(pool["bio"] + pool["wst"] - float(r.af_pool_ktce)))
    assert max_diff < 1e-6
    print(f"[check] province AF pools replicated (max abs diff {max_diff:.2e} ktce)")

    share_bio = m2.within_province_shares(access, "bio_ktce")
    share_wst = m2.within_province_shares(access, "msw_ktce")

    prov_of = dict(zip(plants.plant_id, plants.province))
    cap_td = dict(zip(plants.plant_id, plants.capacity.astype(float)))
    cap_kt = {p: c * m2.DAYS_PER_YEAR / 1000.0 for p, c in cap_td.items()}
    h_i = {p: (heat_tiers[0] if c >= 4200 else heat_tiers[1] if c >= 2000 else heat_tiers[2])
           for p, c in cap_td.items()}

    year = 2060
    all_ids = sorted(cap_td)
    A = {p: (float(alloc_bio_c1.get((prov_of[p], year), 0.0)) * share_bio.get(p, 0.0)
             + float(alloc_wst_c1.get((prov_of[p], year), 0.0)) * share_wst.get(p, 0.0))
         for p in all_ids}
    H = {p: h_i[p] * (1.0 - ee[year]) * cap_kt[p] for p in all_ids}
    ratio = {p: m2.KAPPA * A[p] / H[p] for p in all_ids}

    # --- storage whitelist (M2 caliber) --------------------------------------
    meta = pd.read_excel(ROOT / "v5/data/model_input/plants/plant_data.xlsx",
                         usecols=["id", "longitude", "latitude"])
    meta = meta.rename(columns={"id": "plant_id"})
    storage = pd.read_csv(ROOT / "v5/data/model_input/storage/storage_data_tif.csv")
    wl = m2.build_whitelist(meta, storage)
    n_no_sink = int((wl.n_conn == 0).sum())
    assert n_no_sink == 46, n_no_sink
    print(f"[check] no-sink lines: {n_no_sink} of {len(wl)}")

    # Cross-check the swap-line values against the M2 export itself.
    m2_csv = pd.read_csv(ROOT / "tmp/m2_analysis_20260918/m2_plant_metrics.csv").set_index("plant_id")
    for pid in m2_csv.index:
        assert abs(ratio[pid] - m2_csv.loc[pid, "kA_over_H_C1cond_2060"]) < 1e-9
        if not np.isnan(m2_csv.loc[pid, "nearest_km"]):
            assert abs(wl.loc[pid, "nearest_km"] - m2_csv.loc[pid, "nearest_km"]) < 1e-9
    print("[check] all-plant metrics reproduce m2_plant_metrics.csv on the 77 swap lines")

    # --- scenario operating sets ----------------------------------------------
    op_sets = {}
    for scen, csv_dir in SCEN_CSV_DIR.items():
        st = pd.read_csv(csv_dir / "full_operation_status.csv")
        op_sets[scen] = set(st[(st.period == 2060) & (st.operating == 1)].plant_id.astype(int))
        assert len(op_sets[scen]) == EXPECTED_LINES[scen], scen
    shared = set.intersection(*op_sets.values())
    assert len(shared) == 213
    cap_mt_series = (
        pd.read_csv(SCEN_CSV_DIR["C1"] / "full_plant_summary.csv")
        .set_index("plant_id")["annual_capacity_kt_per_year"] / 1000.0
    )
    assert abs(float(cap_mt_series.loc[list(shared)].sum()) - 327.081) < 0.001
    print("[check] operating sets 408/336/262; shared 213 lines, 327.081 Mt/yr")

    # --- assemble the long table ----------------------------------------------
    frames = []
    for scen in ("C2", "C1", "C3"):
        ids = sorted(op_sets[scen])
        frames.append(pd.DataFrame({
            "scenario": scen,
            "plant_id": ids,
            "province": [prov_of[p] for p in ids],
            "capacity_t_per_day": [cap_td[p] for p in ids],
            "annual_capacity_mt_per_yr": [round(cap_kt[p] / 1000.0, 4) for p in ids],
            "A_real_2060_ktce": [round(A[p], 4) for p in ids],
            "H_2060_ktce": [round(H[p], 4) for p in ids],
            "kA_over_H_real_2060": [round(ratio[p], 6) for p in ids],
            "eff_max_tsr_real_2060": [round(min(m2.THETA, ratio[p]), 6) for p in ids],
            "n_whitelisted_conns": [int(wl.loc[p, "n_conn"]) for p in ids],
            "has_sink": [bool(wl.loc[p, "n_conn"] > 0) for p in ids],
            "nearest_sink_km": [round(float(wl.loc[p, "nearest_km"]), 3)
                                if wl.loc[p, "n_conn"] > 0 else np.nan for p in ids],
            "in_shared_213": [p in shared for p in ids],
        }))
    df = pd.concat(frames, ignore_index=True)
    out = OUTDIR / "fig3b_resource_conditions.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}  ({len(df)} rows)")

    # --- summary: unweighted vs capacity-weighted ------------------------------
    lines = ["# Fig. 3b 资源条件散点：统计摘要（交付 2 附属）",
             "",
             "口径：κA/H = 2 ×（省 AF 池×厂可达份额）/（h_i×(1−EE_2060)×铭牌产能），2060 真实条件；",
             "距离 = 白名单最近合格汇 haversine 代理距离（km），46 条无汇线全船队剔除距离统计。",
             "κA/H 为情景不变量（资源条件，非情景结果），三情景差异仅来自在运集合不同。",
             ""]
    for scen in ("C2", "C1", "C3"):
        sub = df[df.scenario == scen]
        w = sub["annual_capacity_mt_per_yr"]
        x = sub["kA_over_H_real_2060"]
        d = sub["nearest_sink_km"].dropna()
        wd = sub.loc[d.index, "annual_capacity_mt_per_yr"]
        n_nosink = int((~sub.has_sink).sum())
        lines.append(
            f"**{scen}**（{len(sub)} 线在运，无汇 {n_nosink} 条）："
            f"κA/H 中位数 {x.median():.3f}，均值 {x.mean():.3f}，产能加权均值 "
            f"{(x*w).sum()/w.sum():.3f}，产能加权中位数 {weighted_median(x, w):.3f}；"
            f"最近汇距离中位数 {d.median():.1f} km，均值 {d.mean():.1f} km，"
            f"产能加权均值 {(d*wd).sum()/wd.sum():.1f} km，产能加权中位数 "
            f"{weighted_median(d, wd):.1f} km。"
        )
        print(lines[-1])
    sub213 = df[(df.scenario == "C1") & (df.in_shared_213)]
    lines.append(
        f"**对照**：213 条共同留存线（C1 视图）κA/H 中位数 {sub213['kA_over_H_real_2060'].median():.3f}，"
        f"最近汇距离中位数 {sub213['nearest_sink_km'].median():.1f} km；"
        f"无汇线 {int((~sub213.has_sink).sum())} 条。"
    )
    lines.append("")
    lines.append("**加权建议**：散点图若用点大小=产能已可视化加权，统计数值建议报未加权中位数"
                 "（与 M2 报告口径一致），加权中位数仅作敏感性附注；两口径差异见上。")
    (OUTDIR / "fig3b_resource_conditions_summary.md").write_text("\n".join(lines) + "\n",
                                                                 encoding="utf-8")
    print(f"wrote {OUTDIR/'fig3b_resource_conditions_summary.md'}")


if __name__ == "__main__":
    main()
