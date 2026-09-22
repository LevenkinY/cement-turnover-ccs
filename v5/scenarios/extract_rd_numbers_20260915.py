#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
extract_rd_numbers_20260915.py — 为论文 Results 提取三组对比数字（DATA-01/02/03）。

数据来源（只读）：
  - 正式结果: v5/results/formal_v1_20260914/<task>/<scenario>/full_*.csv
              v5/results/formal_v1_20260914/<task>/<scenario>_results.json
  - 厂级静态属性: v5/data/model_input/plants/plant_data.xlsx (id, capacity[t/d], 经纬度, year of commissioning)
                  v5/data/plant_af_access_corrected.csv (plant_id, access_ktce 等 AF 可达性)
                  v5/data/model_input/storage/storage_data_tif.csv (封存节点格网)

口径说明：
  - full_operation_status.capacity 单位为 t/d（已核验 = full_plant_summary.capacity_t_per_day）；
    年产能统一用 full_plant_summary.annual_capacity_kt_per_year (= t/d × 0.31, kt/yr)，Mt = kt/1000。
  - "2060 在运集" = full_operation_status.csv 中 period==2060 且 operating==1 的生产线。
  - "距最近合格封存节点距离" = 厂到 storage_data_tif.csv 中 (dsa_capacity+eor_capacity)>0 节点的
    最小 haversine 距离（km）；同时标注是否在模型允许的 500 km (TRANSPORT_MAX_KM) 范围内。
  - "AF 可达性指数" = plant_af_access_corrected.access_ktce（总量口径：50km 内 MSW + 150km 内
    生物质可及能源量, ktce/yr）；另给出单位产能强度 access_ktce / annual_capacity_kt。
  - "代理运距" = 熟料交付代理距离：结果 JSON 的 clinker_delivery_routes（plant→market node,
    flow_kt 加权 distance_km）；全国层面同时抄录 regional_demand.per_period 的
    weighted_avg_km / p50_km / p90_km。
  - "省际代理流份额" = regional_demand.per_period[year].inter_provincial_share。
  - "CO2 运输距离" = full_co2_flows.csv 的 distance_km 按 flow_kt 加权（仅覆盖有捕集流量的厂）。

输出：stdout 报告 + v5/scenarios/rd_numbers_20260915/ 下的机器可读表（新建文件，不改动现有文件）。

运行：.venv/bin/python v5/scenarios/extract_rd_numbers_20260915.py
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "v5" / "results" / "formal_v1_20260914"
OUTDIR = ROOT / "v5" / "scenarios" / "rd_numbers_20260915"

RUNS = {  # label -> (task_dir, scenario_subdir)
    "C1": ("C1_central_J", "S1_baseline"),
    "C2": ("C2_demand_high", "S1_baseline"),
    "C3": ("C3_demand_low", "S1_baseline"),
    "C4": ("C4_equalized_J", "S3_all_spatial_equalized"),
    "C5": ("C5_commitment_cost", "S1_baseline"),
}

TRANSPORT_MAX_KM = 500.0  # v5/model/src_v5/config_v5.py:882


def run_dir(label):
    task, scen = RUNS[label]
    return RESULTS / task / scen


def run_json_path(label):
    task, scen = RUNS[label]
    return RESULTS / task / f"{scen}_results.json"


def load_opstatus(label):
    df = pd.read_csv(run_dir(label) / "full_operation_status.csv")
    return df


def load_plant_summary(label):
    return pd.read_csv(run_dir(label) / "full_plant_summary.csv")


def load_co2_flows(label):
    return pd.read_csv(run_dir(label) / "full_co2_flows.csv")


def load_json(label):
    with open(run_json_path(label)) as f:
        return json.load(f)


def operating_set(label, year):
    """2060 在运集: DataFrame(plant_id, province, capacity_tpd) + annual kt joined."""
    op = load_opstatus(label)
    op = op[(op["period"] == year) & (op["operating"] == 1)].copy()
    ps = load_plant_summary(label)[["plant_id", "capacity_t_per_day", "annual_capacity_kt_per_year"]]
    op = op.merge(ps, on="plant_id", how="left", validate="1:1")
    assert op["annual_capacity_kt_per_year"].notna().all()
    return op


def base2025_capacity():
    """2025 基年各厂年产能（kt/yr），用 C1 的 2025 在运集（=全部 1572 条）。"""
    op = operating_set("C1", 2025)
    return op[["plant_id", "province", "capacity_t_per_day", "annual_capacity_kt_per_year"]]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1r, lat2r = np.radians(lat1), np.radians(lat2)
    dlat = lat2r - lat1r
    dlon = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def nearest_storage_distance():
    """每厂到最近合格封存节点(dsa+eor>0)的距离 km，及是否在 500km 模型范围内。"""
    plants = pd.read_excel(ROOT / "v5" / "data" / "model_input" / "plants" / "plant_data.xlsx")
    plants = plants.rename(columns={"id": "plant_id"})
    stor = pd.read_csv(ROOT / "v5" / "data" / "model_input" / "storage" / "storage_data_tif.csv")
    qual = stor[(stor["dsa_capacity"] + stor["eor_capacity"]) > 0]
    s_lat = qual["latitude"].values
    s_lon = qual["longitude"].values
    recs = []
    for r in plants.itertuples(index=False):
        d = haversine_km(r.latitude, r.longitude, s_lat, s_lon)
        dmin = float(np.min(d))
        recs.append({
            "plant_id": int(r.plant_id),
            "nearest_storage_km": dmin,
            "storage_within_500km": bool(dmin <= TRANSPORT_MAX_KM),
        })
    return pd.DataFrame(recs)


def load_static_plant_attrs():
    """厂龄/投产年、AF 可达性、最近封存距离，合并为一张厂级表。"""
    plants = pd.read_excel(ROOT / "v5" / "data" / "model_input" / "plants" / "plant_data.xlsx")
    plants = plants.rename(columns={"id": "plant_id", "year of commissioning": "commission_year"})
    af = pd.read_csv(ROOT / "v5" / "data" / "plant_af_access_corrected.csv")
    af = af[["plant_id", "access_ktce", "msw_ktce", "bio_ktce"]]
    stor = nearest_storage_distance()
    out = plants[["plant_id", "province", "commission_year", "longitude", "latitude"]]
    out = out.merge(af, on="plant_id", how="left").merge(stor, on="plant_id", how="left")
    return out


def proxy_delivery_distance_per_plant(label, year):
    """熟料交付代理运距：JSON clinker_delivery_routes, 按 plant 流量加权平均 distance_km。"""
    routes = load_json(label)["clinker_delivery_routes"]
    df = pd.DataFrame(routes)
    df = df[df["year"] == year]
    g = df.groupby("plant_id").apply(
        lambda x: np.average(x["distance_km"], weights=x["flow_kt"]), include_groups=False
    )
    g.name = "proxy_delivery_km"
    return g.reset_index()


def size_bin(tpd):
    if tpd < 3200:
        return "<3200 t/d"
    if tpd <= 5000:
        return "3200-5000 t/d"
    return ">5000 t/d"


def fmt_mt(kt):
    return kt / 1000.0


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    static = load_static_plant_attrs()
    base = base2025_capacity()
    base_prov = base.groupby("province")["annual_capacity_kt_per_year"].sum()

    # ------------------------------------------------------------------ DATA-01
    section("DATA-01  C1/C2/C3 共同留存的区域或资产类型模式")
    ops = {lab: operating_set(lab, 2060) for lab in ("C1", "C2", "C3")}

    print("\n[DATA-01.1] 2060 在运集省级产能分布 (full_operation_status: period==2060 & operating==1;")
    print("            产能列=full_plant_summary.annual_capacity_kt_per_year, 折算 Mt;")
    print("            基年比例=该省2060在运产能 / 该省2025基年产能[C1 2025在运全集])")
    prov_tables = {}
    for lab in ("C1", "C2", "C3"):
        op = ops[lab]
        t = op.groupby("province")["annual_capacity_kt_per_year"].sum().rename("op2060_kt")
        t = t.to_frame()
        t["op2060_mt"] = fmt_mt(t["op2060_kt"])
        t["base2025_kt"] = base_prov
        t["base2025_mt"] = fmt_mt(t["base2025_kt"])
        t["share_of_province_base"] = t["op2060_kt"] / t["base2025_kt"]
        t["share_of_national_op2060"] = t["op2060_kt"] / t["op2060_kt"].sum()
        prov_tables[lab] = t.sort_values("op2060_kt", ascending=False)
        print(f"\n--- {lab} ({RUNS[lab][0]}): 2060 在运 {len(op)} 条线, "
              f"{fmt_mt(op['annual_capacity_kt_per_year'].sum()):.1f} Mt/yr ---")
        pt = prov_tables[lab].copy()
        pt["share_of_province_base"] = (pt["share_of_province_base"] * 100).round(1)
        pt["share_of_national_op2060"] = (pt["share_of_national_op2060"] * 100).round(1)
        pt["op2060_mt"] = pt["op2060_mt"].round(2)
        pt["base2025_mt"] = pt["base2025_mt"].round(2)
        pt.columns = ["op2060_kt", "op2060_Mt", "base2025_kt", "base2025_Mt",
                      "survival_%", "national_share_%"]
        print(pt.drop(columns=["op2060_kt", "base2025_kt"]).to_string())
        prov_tables[lab].to_csv(OUTDIR / f"data01_province_2060_{lab}.csv")

    print("\n[DATA-01.2] 三情景交集（C1∩C2∩C3 均在运 2060）")
    sets = {lab: set(ops[lab]["plant_id"]) for lab in ("C1", "C2", "C3")}
    inter = sets["C1"] & sets["C2"] & sets["C3"]
    idf = base[base["plant_id"].isin(inter)].copy()
    idf = idf.merge(static[["plant_id", "commission_year"]], on="plant_id", how="left")
    print(f"交集线数: {len(idf)} 条; 交集产能: {fmt_mt(idf['annual_capacity_kt_per_year'].sum()):.1f} Mt/yr")
    ip = idf.groupby("province")["annual_capacity_kt_per_year"].sum().sort_values(ascending=False)
    ipt = (ip / 1000).round(2).rename("cap_Mt").to_frame()
    ipt["share_%"] = (ip / ip.sum() * 100).round(1)
    print("\n交集省级构成 (top 10):")
    print(ipt.head(10).to_string())
    top5_share = ip.head(5).sum() / ip.sum()
    print(f"\n交集 top5 省产能占比: {top5_share*100:.1f}%  "
          f"({', '.join(f'{p}{(v/ip.sum()*100):.0f}%' for p, v in ip.head(5).items())})")

    print("\n[DATA-01.3] 资产类型模式：窑规模档构成（档界 <3200 / 3200-5000 / >5000 t/d）")
    idf["size_bin"] = idf["capacity_t_per_day"].map(size_bin)
    bin_order = ["<3200 t/d", "3200-5000 t/d", ">5000 t/d"]
    comp_rows = {}
    comp_rows["intersection(C1∩C2∩C3)"] = idf.groupby("size_bin")["annual_capacity_kt_per_year"].sum()
    for lab in ("C1", "C2", "C3"):
        o = ops[lab].copy()
        comp_rows[f"{lab} 2060 op"] = o.groupby(o["capacity_t_per_day"].map(size_bin))[
            "annual_capacity_kt_per_year"].sum()
    b25 = base.copy()
    comp_rows["2025 base"] = b25.groupby(b25["capacity_t_per_day"].map(size_bin))[
        "annual_capacity_kt_per_year"].sum()
    comp = pd.DataFrame(comp_rows).reindex(bin_order).fillna(0)
    comp_mt = (comp / 1000).round(2)
    comp_pct = (comp / comp.sum() * 100).round(1)
    print("\n产能 (Mt/yr):")
    print(comp_mt.to_string())
    print("\n占比 (%):")
    print(comp_pct.to_string())
    comp_mt.to_csv(OUTDIR / "data01_sizebin_mt.csv")
    comp_pct.to_csv(OUTDIR / "data01_sizebin_pct.csv")

    inter_kt = idf["annual_capacity_kt_per_year"].sum()
    print("\n交集产能占各情景 2060 在运产能份额:")
    for lab in ("C1", "C2", "C3"):
        tot = ops[lab]["annual_capacity_kt_per_year"].sum()
        print(f"  {lab}: {inter_kt/tot*100:.1f}%  ({fmt_mt(inter_kt):.1f} / {fmt_mt(tot):.1f} Mt)")
    big = idf[idf["capacity_t_per_day"] > 5000]["annual_capacity_kt_per_year"].sum() / inter_kt
    small_base = comp_pct.loc["<3200 t/d", "2025 base"]
    big_base = comp_pct.loc[">5000 t/d", "2025 base"]
    big_inter = comp_pct.loc[">5000 t/d", "intersection(C1∩C2∩C3)"]
    print(f"\n交集 >5000 t/d 产能占比 {big_inter}% vs 2025基年 {big_base}% "
          f"(<3200 t/d: 交集 {comp_pct.loc['<3200 t/d','intersection(C1∩C2∩C3)']}% vs 基年 {small_base}%)")
    print(f"交集厂龄: 投产年中位数 {idf['commission_year'].median():.0f}, "
          f"均值 {idf['commission_year'].mean():.1f}")

    # ------------------------------------------------------------------ DATA-02
    section("DATA-02  C1 vs C4 的 2060 在运集交换")
    op1, op4 = operating_set("C1", 2060), operating_set("C4", 2060)
    s1, s4 = set(op1["plant_id"]), set(op4["plant_id"])
    only1, only4 = s1 - s4, s4 - s1

    def group_table(ids, name):
        g = base[base["plant_id"].isin(ids)].copy()
        g = g.merge(static.drop(columns=["province"]), on="plant_id", how="left")
        proxy = proxy_delivery_distance_per_plant(
            "C1" if name == "C1-only" else "C4", 2060)
        g = g.merge(proxy, on="plant_id", how="left")
        return g

    g1, g4 = group_table(only1, "C1-only"), group_table(only4, "C4-only")
    for g, name in ((g1, "C1-only (在C1在运、C4退出)"), (g4, "C4-only (在C4在运、C1退出)")):
        kt = g["annual_capacity_kt_per_year"].sum()
        print(f"\n--- {name}: {len(g)} 条线, {fmt_mt(kt):.2f} Mt/yr ---")
        tp = g.groupby("province")["annual_capacity_kt_per_year"].sum().sort_values(ascending=False)
        tpt = (tp / 1000).round(2).rename("cap_Mt").to_frame()
        tpt["share_%"] = (tp / tp.sum() * 100).round(1)
        print("top 省:", ", ".join(f"{p} {r.cap_Mt}Mt({r._2}%)" if hasattr(r, '_2') else
              f"{p} {r['cap_Mt']}Mt({r['share_%']}%)"
              for p, r in list(tpt.head(5).iterrows())))
        print(tpt.head(8).to_string())
        print(f"距最近合格封存节点 km: 中位数 {g['nearest_storage_km'].median():.1f}, "
              f"均值 {g['nearest_storage_km'].mean():.1f} "
              f"(500km内覆盖率 {g['storage_within_500km'].mean()*100:.0f}%)")
        print(f"AF可达性 access_ktce(总量口径): 中位数 {g['access_ktce'].median():.0f}, "
              f"均值 {g['access_ktce'].mean():.0f}")
        inten = g["access_ktce"] / g["annual_capacity_kt_per_year"]
        print(f"AF可达性强度 access_ktce/kt产能: 中位数 {inten.median():.3f}, 均值 {inten.mean():.3f}")
        pdist = g["proxy_delivery_km"].dropna()
        print(f"熟料代理运距(2060,厂级流量加权后再简单平均): "
              f"均值 {pdist.mean():.1f} km, 中位数 {pdist.median():.1f} km (覆盖 {len(pdist)}/{len(g)} 条)")
        print(f"投产年: 中位数 {g['commission_year'].median():.0f}, 均值 {g['commission_year'].mean():.1f}")
        g.to_csv(OUTDIR / f"data02_{name.split(' ')[0]}_plants.csv", index=False)

    # CO2 运输距离（仅捕集厂），2060
    print("\n--- CO2 运输距离 (full_co2_flows.distance_km 按 flow_kt 加权, period==2060) ---")
    for lab, ids, name in (("C1", only1, "C1-only"), ("C4", only4, "C4-only")):
        fl = load_co2_flows(lab)
        fl = fl[(fl["period"] == 2060) & (fl["plant_id"].isin(ids)) & (fl["flow_kt"] > 0)]
        if len(fl):
            w = np.average(fl["distance_km"], weights=fl["flow_kt"])
            print(f"{name}: {len(fl)} 条流量记录, {fl['plant_id'].nunique()} 个捕集厂, "
                  f"流量加权均值 {w:.1f} km, 捕集量合计 {fl['flow_kt'].sum()/1000:.2f} Mt")
        else:
            print(f"{name}: 2060 无 CO2 流量记录")

    print(f"\n对照: C1 2060 总在运 {len(op1)} 条 / {fmt_mt(op1['annual_capacity_kt_per_year'].sum()):.1f} Mt; "
          f"C4 2060 总在运 {len(op4)} 条 / {fmt_mt(op4['annual_capacity_kt_per_year'].sum()):.1f} Mt; "
          f"两情景共同在运 {len(s1 & s4)} 条 / "
          f"{fmt_mt(base[base['plant_id'].isin(s1 & s4)]['annual_capacity_kt_per_year'].sum()):.1f} Mt")

    # ------------------------------------------------------------------ DATA-03
    section("DATA-03  C1 vs C5 '总量相近、配置不同'")
    print("设计口径: 依 batch.log, C5_commitment_cost 以 "
          "--fixed-capacity-path C4_equalized_J/S3_all_spatial_equalized_results.json 运行,")
    print("即 C5 的产能路径(开停)被固定为 C4 的解, 其余决策重优化。下面先核验这一点。")
    _c4op = load_opstatus("C4")[["period", "plant_id", "operating"]].rename(
        columns={"operating": "op_c4"})
    _c5op = load_opstatus("C5")[["period", "plant_id", "operating"]].rename(
        columns={"operating": "op_c5"})
    _mm = _c4op.merge(_c5op, on=["period", "plant_id"])
    print(f"核验: C4 与 C5 全周期 operating 一致率 "
          f"{(_mm.op_c4 == _mm.op_c5).sum()}/{len(_mm)} "
          f"({(_mm.op_c4 == _mm.op_c5).mean()*100:.1f}%) -> C1vsC5 的在运集差异 = C1vsC4 的路径差异")

    op5 = operating_set("C5", 2060)
    s5 = set(op5["plant_id"])
    j1, j5 = load_json("C1"), load_json("C5")

    for yr in (2050, 2060):
        o1, o5 = operating_set("C1", yr), operating_set("C5", yr)
        a, b = set(o1["plant_id"]), set(o5["plant_id"])
        cap = lambda ids: fmt_mt(base[base["plant_id"].isin(ids)]["annual_capacity_kt_per_year"].sum())
        print(f"\n[{yr}] C1 在运 {len(a)} 条 / {cap(a):.1f} Mt;  C5 在运 {len(b)} 条 / {cap(b):.1f} Mt")
        print(f"  共同在运: {len(a & b)} 条 / {cap(a & b):.1f} Mt;  "
              f"仅C1: {len(a - b)} 条 / {cap(a - b):.2f} Mt;  仅C5: {len(b - a)} 条 / {cap(b - a):.2f} Mt")

    print("\n[全国捕集总量] (结果JSON summary[year].captured_co2_kt / commercial_captured_co2_kt)")
    for yr in ("2050", "2060"):
        for lab, j in (("C1", j1), ("C5", j5)):
            s = j["summary"][yr]
            print(f"  {lab} {yr}: captured {s['captured_co2_kt']/1000:.2f} Mt "
                  f"(commercial {s['commercial_captured_co2_kt']/1000:.2f} Mt, "
                  f"observed-pilot {s['observed_pilot_captured_co2_kt']/1000:.2f} Mt); "
                  f"gross {s['gross_co2_kt']/1000:.1f} Mt, net {s['net_co2_kt']/1000:.1f} Mt")

    print("\n[熟料代理运距] (结果JSON regional_demand.per_period[year])")
    for yr in ("2050", "2060"):
        for lab, j in (("C1", j1), ("C5", j5)):
            p = j["regional_demand"]["per_period"][yr]
            print(f"  {lab} {yr}: weighted_avg {p['weighted_avg_km']:.1f} km, "
                  f"p50 {p['p50_km']:.1f} km, p90 {p['p90_km']:.1f} km, "
                  f"delivered {p['delivered_kt']/1000:.1f} Mt")
    # 2050+2060 合并流量加权
    for lab in ("C1", "C5"):
        routes = pd.DataFrame(load_json(lab)["clinker_delivery_routes"])
        r = routes[routes["year"].isin([2050, 2060])]
        w = np.average(r["distance_km"], weights=r["flow_kt"])
        kms = np.sort(r["distance_km"].values)
        wts = r["flow_kt"].values[np.argsort(r["distance_km"].values)]
        cum = np.cumsum(wts) / wts.sum()
        p50 = kms[np.searchsorted(cum, 0.5)]
        p90 = kms[np.searchsorted(cum, 0.9)]
        print(f"  {lab} 2050+2060 合并(clinker_delivery_routes): 流量加权均值 {w:.1f} km, "
              f"p50 {p50:.1f} km, p90 {p90:.1f} km")

    print("\n[省际代理流份额] (regional_demand.per_period[year].inter_provincial_share)")
    for yr in ("2050", "2060"):
        for lab, j in (("C1", j1), ("C5", j5)):
            p = j["regional_demand"]["per_period"][yr]
            print(f"  {lab} {yr}: inter_provincial_share {p['inter_provincial_share']*100:.1f}% "
                  f"({p['inter_provincial_kt']/1000:.1f} Mt of {p['delivered_kt']/1000:.1f} Mt)")
    print("\n  2060 top5 省际流 (inter_provincial_flows_kt):")
    for lab, j in (("C1", j1), ("C5", j5)):
        flows = list(j["inter_provincial_flows_kt"]["2060"].items())[:5]
        print(f"  {lab}: " + ", ".join(f"{k} {v/1000:.2f}Mt" for k, v in flows))

    # aggregate-vs-configuration 摘要
    o1, o5 = operating_set("C1", 2060), operating_set("C5", 2060)
    a, b = set(o1["plant_id"]), set(o5["plant_id"])
    cap = lambda ids: base[base["plant_id"].isin(ids)]["annual_capacity_kt_per_year"].sum()
    c1kt, c5kt = cap(a), cap(b)
    diff_share = (cap(a - b) + cap(b - a)) / ((c1kt + c5kt) / 2)
    cap1 = j1["summary"]["2060"]["captured_co2_kt"]
    cap5 = j5["summary"]["2060"]["captured_co2_kt"]
    p1 = j1["regional_demand"]["per_period"]["2060"]
    p5 = j5["regional_demand"]["per_period"]["2060"]
    print("\n[aggregate-vs-configuration 摘要, 2060]")
    print(f"  在运产能: C1 {fmt_mt(c1kt):.1f} Mt vs C5 {fmt_mt(c5kt):.1f} Mt "
          f"(相差 {abs(c1kt-c5kt)/((c1kt+c5kt)/2)*100:.1f}%)")
    print(f"  捕集总量: C1 {cap1/1000:.2f} Mt vs C5 {cap5/1000:.2f} Mt "
          f"(相差 {abs(cap1-cap5)/((cap1+cap5)/2)*100:.1f}%)")
    print(f"  独有产能(仅一侧在运)合计: {fmt_mt(cap(a-b)+cap(b-a)):.1f} Mt "
          f"= 平均在运产能的 {diff_share*100:.1f}%")
    print(f"  代理运距 p90: C1 {p1['p90_km']:.0f} km vs C5 {p5['p90_km']:.0f} km")
    print(f"  省际流份额: C1 {p1['inter_provincial_share']*100:.1f}% vs "
          f"C5 {p5['inter_provincial_share']*100:.1f}%")
    tc1, tc5 = j1["total_cost_kCNY"], j5["total_cost_kCNY"]
    print(f"  [补充] 全期总成本 (JSON total_cost_kCNY, kCNY): C1 {tc1*1e3/1e12:.3f} 万亿CNY vs "
          f"C5 {tc5*1e3/1e12:.3f} 万亿CNY -> 承诺成本 {(tc5-tc1)*1e3/1e9:.1f} 十亿CNY "
          f"(+{(tc5/tc1-1)*100:.2f}%)")

    # 机器可读汇总
    summary = {
        "units": {"capacity": "kt/yr (Mt=kt/1000)", "emission": "kt", "distance": "km",
                  "op_status_capacity_column": "t/d (converted via annual_capacity_kt_per_year)"},
        "data01": {
            "op2060": {lab: {"lines": len(ops[lab]),
                             "mt": fmt_mt(ops[lab]["annual_capacity_kt_per_year"].sum())}
                       for lab in ("C1", "C2", "C3")},
            "intersection": {"lines": len(idf), "mt": fmt_mt(inter_kt),
                             "top5_province_share": top5_share,
                             "share_of_C1": inter_kt / ops["C1"]["annual_capacity_kt_per_year"].sum(),
                             "share_of_C2": inter_kt / ops["C2"]["annual_capacity_kt_per_year"].sum(),
                             "share_of_C3": inter_kt / ops["C3"]["annual_capacity_kt_per_year"].sum(),
                             "gt5000_share": big},
        },
        "data02": {
            "C1_only": {"lines": len(g1), "mt": fmt_mt(g1["annual_capacity_kt_per_year"].sum()),
                        "median_storage_km": float(g1["nearest_storage_km"].median()),
                        "median_access_ktce": float(g1["access_ktce"].median()),
                        "median_commission_year": float(g1["commission_year"].median())},
            "C4_only": {"lines": len(g4), "mt": fmt_mt(g4["annual_capacity_kt_per_year"].sum()),
                        "median_storage_km": float(g4["nearest_storage_km"].median()),
                        "median_access_ktce": float(g4["access_ktce"].median()),
                        "median_commission_year": float(g4["commission_year"].median())},
        },
        "data03": {
            "design_note": ("C5 run with --fixed-capacity-path from C4 results "
                            "(batch.log); C4/C5 operating sets agree 12576/12576 rows"),
            "op2060_C1_mt": fmt_mt(c1kt), "op2060_C5_mt": fmt_mt(c5kt),
            "common_mt": fmt_mt(cap(a & b)),
            "only_C1_mt": fmt_mt(cap(a - b)), "only_C5_mt": fmt_mt(cap(b - a)),
            "captured2060_C1_mt": cap1 / 1000, "captured2060_C5_mt": cap5 / 1000,
            "proxy_p90_C1_km": p1["p90_km"], "proxy_p90_C5_km": p5["p90_km"],
            "inter_share_C1": p1["inter_provincial_share"],
            "inter_share_C5": p5["inter_provincial_share"],
            "total_cost_trillion_CNY_C1": tc1 * 1e3 / 1e12,
            "total_cost_trillion_CNY_C5": tc5 * 1e3 / 1e12,
            "commitment_cost_billion_CNY": (tc5 - tc1) * 1e3 / 1e9,
        },
    }
    with open(OUTDIR / "rd_numbers_summary.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n机器可读汇总已写入 {OUTDIR}/rd_numbers_summary.json")


if __name__ == "__main__":
    main()
    data02_mechanism()


# ── DATA-02 mechanism-consistent addendum (2026-09-15) ─────────────────────
# The static-endowment comparison (storage distance, catchment access, age) is
# the WRONG instrument for the equalization treatment: the treatment changes
# the allocation RULE, not endowments. The consistent diagnostic compares each
# swapped group's REALIZED AF supply under each scenario. Result: C1-only
# plants lose their concentrated AF advantage (median realized 2030 AF share
# 16.6% -> 2.0%), C4-only plants gain it (1.4% -> 28.7%).
def data02_mechanism():
    import pandas as pd
    def shares(run, sub):
        df = pd.read_csv(f'{RESULTS}/{run}/{sub}/full_af_plant_shares.csv')
        return df[df.period == 2030][['plant_id', 'af_share', 'af_supply_ktce']]
    a1 = shares('C1_central_J', 'S1_baseline')
    a4 = shares('C4_equalized_J', 'S3_all_spatial_equalized')
    out = {}
    for nm, f in [('C1-only', 'data02_C1-only_plants.csv'),
                  ('C4-only', 'data02_C4-only_plants.csv')]:
        grp = pd.read_csv(f'{OUTDIR}/{f}')
        pid = set(grp['plant_id'])
        g1 = a1[a1.plant_id.isin(pid)]
        g4 = a4[a4.plant_id.isin(pid)]
        out[nm] = {
            'n': len(pid),
            'af_share_median_real': float(g1.af_share.median()),
            'af_share_median_equalized': float(g4.af_share.median()),
            'af_supply_median_ktce_real': float(g1.af_supply_ktce.median()),
            'af_supply_median_ktce_equalized': float(g4.af_supply_ktce.median()),
        }
    print('[DATA-02 mechanism] ', out)
    return out
