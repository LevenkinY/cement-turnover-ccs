"""Deliverable 3 (Fig. 5b candidate data): C1 vs C5 spatial reconfiguration at
2060 -- provincial delivery, proxy-distance and capture reallocation.

Sources (read-only):
  - result JSON `clinker_delivery_routes` (plant->market-node proxy flows with
    from/to province and arc distance_km) for delivered/dispatched volumes and
    flow-weighted proxy distances;
  - result JSON `inter_provincial_flows_kt["2060"]` for pair-level changes;
  - result JSON `plants[pid].captured_commercial["2060"]` for plant-matched
    capture (identical source to the current Fig. 5b bottom panel);
  - result JSON `regional_demand.per_period["2060"]` for national anchors
    (delivered 510.4 Mt; weighted 89.5 vs 94.7 km; inter share 6.8% vs 7.6%).

Outputs:
  fig5b_province_delivery.csv        one row per province (C1, C5, C5-C1)
  fig5b_interprovincial_flow_delta.csv  one row per from->to pair
  fig5b_capture_delta.csv            one row per plant with 2060 capture in
                                     either scenario (only_c1/only_c5 flags sum
                                     to the 36.0 / 37.6 Mt manuscript anchors)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "v5/results/formal_v1_20260914"
OUTDIR = Path(__file__).resolve().parent

RESULT_JSON = {
    "C1": RUNS / "C1_central_J/S1_baseline_results.json",
    "C5": RUNS / "C5_commitment_cost/S1_baseline_results.json",
}
YEAR = 2060


def load(scen: str) -> dict:
    return json.loads(RESULT_JSON[scen].read_text())


def routes_frame(res: dict) -> pd.DataFrame:
    df = pd.DataFrame(res["clinker_delivery_routes"])
    return df[df.year == YEAR].copy()


def wavg(df: pd.DataFrame, value: str, weight: str) -> float:
    w = df[weight]
    return float((df[value] * w).sum() / w.sum()) if w.sum() > 0 else np.nan


def main() -> None:
    res = {scen: load(scen) for scen in ("C1", "C5")}

    # --- national anchors -----------------------------------------------------
    for scen in ("C1", "C5"):
        rd = res[scen]["regional_demand"]["per_period"][str(YEAR)]
        expect_km = 89.5 if scen == "C1" else 94.7
        expect_share = 6.8 if scen == "C1" else 7.6
        assert abs(rd["delivered_kt"] / 1000.0 - 510.4) < 0.1
        assert abs(rd["weighted_avg_km"] - expect_km) < 0.1, (scen, rd["weighted_avg_km"])
        assert abs(100 * rd["inter_provincial_share"] - expect_share) < 0.1
    print("[check] national delivery anchors 510.4 Mt; 89.5 vs 94.7 km; 6.8% vs 7.6%")

    # --- province delivery table ----------------------------------------------
    routes = {scen: routes_frame(res[scen]) for scen in ("C1", "C5")}
    provinces = sorted(set(routes["C1"].to_province) | set(routes["C5"].to_province)
                       | set(routes["C1"].from_province) | set(routes["C5"].from_province))
    rows = []
    for prov in provinces:
        row = {"province": prov}
        for scen in ("C1", "C5"):
            df = routes[scen]
            inbound = df[df.to_province == prov]
            outbound = df[df.from_province == prov]
            inter = df[(df.from_province != df.to_province)]
            row[f"delivered_in_mt_{scen}"] = round(inbound.flow_kt.sum() / 1000.0, 3)
            row[f"delivered_in_wavg_km_{scen}"] = round(wavg(inbound, "distance_km", "flow_kt"), 1)
            row[f"dispatched_out_mt_{scen}"] = round(outbound.flow_kt.sum() / 1000.0, 3)
            row[f"dispatched_out_wavg_km_{scen}"] = round(wavg(outbound, "distance_km", "flow_kt"), 1)
            row[f"inter_sent_mt_{scen}"] = round(
                inter[inter.from_province == prov].flow_kt.sum() / 1000.0, 3)
            row[f"inter_received_mt_{scen}"] = round(
                inter[inter.to_province == prov].flow_kt.sum() / 1000.0, 3)
        row["delivered_in_delta_mt_C5mC1"] = round(
            row["delivered_in_mt_C5"] - row["delivered_in_mt_C1"], 3)
        row["delivered_in_wavg_km_delta_C5mC1"] = round(
            row["delivered_in_wavg_km_C5"] - row["delivered_in_wavg_km_C1"], 1)
        row["dispatched_out_delta_mt_C5mC1"] = round(
            row["dispatched_out_mt_C5"] - row["dispatched_out_mt_C1"], 3)
        row["inter_sent_delta_mt_C5mC1"] = round(
            row["inter_sent_mt_C5"] - row["inter_sent_mt_C1"], 3)
        row["inter_received_delta_mt_C5mC1"] = round(
            row["inter_received_mt_C5"] - row["inter_received_mt_C1"], 3)
        rows.append(row)
    prov_df = pd.DataFrame(rows)
    for scen in ("C1", "C5"):
        total = prov_df[f"delivered_in_mt_{scen}"].sum()
        assert abs(total - 510.4) < 0.1, (scen, total)
    out1 = OUTDIR / "fig5b_province_delivery.csv"
    prov_df.to_csv(out1, index=False)
    print(f"wrote {out1} ({len(prov_df)} provinces; delivered totals close at 510.4 Mt)")

    # --- inter-provincial pair flows -------------------------------------------
    pairs = set(res["C1"]["inter_provincial_flows_kt"][str(YEAR)]) | \
        set(res["C5"]["inter_provincial_flows_kt"][str(YEAR)])
    pair_rows = []
    for pair in sorted(pairs):
        c1 = res["C1"]["inter_provincial_flows_kt"][str(YEAR)].get(pair, 0.0) / 1000.0
        c5 = res["C5"]["inter_provincial_flows_kt"][str(YEAR)].get(pair, 0.0) / 1000.0
        frm, to = pair.split("->")
        pair_rows.append({"from_province": frm, "to_province": to,
                          "flow_mt_C1": round(c1, 3), "flow_mt_C5": round(c5, 3),
                          "delta_mt_C5mC1": round(c5 - c1, 3)})
    pair_df = pd.DataFrame(pair_rows)
    rd1 = res["C1"]["regional_demand"]["per_period"][str(YEAR)]
    rd5 = res["C5"]["regional_demand"]["per_period"][str(YEAR)]
    # Values are rounded to 0.001 Mt per pair, so closure holds to rounding slack.
    assert abs(pair_df["flow_mt_C1"].sum() - rd1["inter_provincial_kt"] / 1000.0) < 0.05
    assert abs(pair_df["flow_mt_C5"].sum() - rd5["inter_provincial_kt"] / 1000.0) < 0.05
    out2 = OUTDIR / "fig5b_interprovincial_flow_delta.csv"
    pair_df.to_csv(out2, index=False)
    print(f"wrote {out2} ({len(pair_df)} pairs; C1 total {pair_df.flow_mt_C1.sum():.1f} Mt, "
          f"C5 {pair_df.flow_mt_C5.sum():.1f} Mt)")

    # --- plant-matched capture delta --------------------------------------------
    coords = pd.read_excel(ROOT / "v5/data/model_input/plants/plant_data.xlsx",
                           usecols=["id", "province", "longitude", "latitude", "capacity"])
    coords = coords.rename(columns={"id": "plant_id", "capacity": "capacity_t_per_day"})
    coords["plant_id"] = coords["plant_id"].astype(int)

    ids = set(res["C1"]["plants"]) | set(res["C5"]["plants"])
    cap_rows = []
    for pid in sorted(int(p) for p in ids):
        c1 = float(res["C1"]["plants"].get(str(pid), {}).get("captured_commercial", {}).get(str(YEAR), 0.0))
        c5 = float(res["C5"]["plants"].get(str(pid), {}).get("captured_commercial", {}).get(str(YEAR), 0.0))
        if c1 <= 0.0 and c5 <= 0.0:
            continue
        meta = coords[coords.plant_id == pid].iloc[0]
        cap_rows.append({
            "plant_id": pid,
            "province": meta.province,
            "longitude": meta.longitude,
            "latitude": meta.latitude,
            "capacity_t_per_day": meta.capacity_t_per_day,
            "capture_mt_C1_2060": round(c1 / 1000.0, 4),
            "capture_mt_C5_2060": round(c5 / 1000.0, 4),
            "delta_mt_C5mC1": round((c5 - c1) / 1000.0, 4),
            "contributes_only_c1_36mt": c1 > c5,
            "contributes_only_c5_37_6mt": c5 > c1,
        })
    cap_df = pd.DataFrame(cap_rows)
    only_c1 = cap_df.loc[cap_df.contributes_only_c1_36mt, "delta_mt_C5mC1"].sum()
    only_c5 = cap_df.loc[cap_df.contributes_only_c5_37_6mt, "delta_mt_C5mC1"].sum()
    # Per-plant values rounded to 0.1 kt; closure holds to accumulated rounding slack.
    assert abs(-only_c1 - 36.031) < 0.05, only_c1
    assert abs(only_c5 - 37.603) < 0.05, only_c5
    assert abs(cap_df.capture_mt_C1_2060.sum() - 305.254) < 0.05
    assert abs(cap_df.capture_mt_C5_2060.sum() - 306.827) < 0.05
    out3 = OUTDIR / "fig5b_capture_delta.csv"
    cap_df.to_csv(out3, index=False)
    print(f"wrote {out3} ({len(cap_df)} plants; only-C1 {-only_c1:.3f} Mt, "
          f"only-C5 {only_c5:.3f} Mt match 36.0/37.6 anchors)")

    # --- province-level capture aggregation (for the map/面板备选) ----------------
    prov_cap = (cap_df.groupby("province")[["capture_mt_C1_2060", "capture_mt_C5_2060",
                                            "delta_mt_C5mC1"]].sum().round(3).reset_index())
    out4 = OUTDIR / "fig5b_capture_delta_by_province.csv"
    prov_cap.to_csv(out4, index=False)
    print(f"wrote {out4} ({len(prov_cap)} provinces)")

    # quick console summary for the evaluation note
    top = prov_df.reindex(prov_df.delivered_in_wavg_km_delta_C5mC1.abs().sort_values(ascending=False).index)
    print("\nlargest inbound proxy-distance increases (C5-C1, km; provinces with delivered>=5 Mt):")
    print(top[top.delivered_in_mt_C1 >= 5][
        ["province", "delivered_in_mt_C1", "delivered_in_mt_C5",
         "delivered_in_wavg_km_C1", "delivered_in_wavg_km_C5",
         "delivered_in_wavg_km_delta_C5mC1"]].head(8).to_string(index=False))
    print("\nlargest capture-province deltas (|C5-C1|, Mt):")
    print(prov_cap.reindex(prov_cap.delta_mt_C5mC1.abs().sort_values(ascending=False).index)
          .head(8).to_string(index=False))


if __name__ == "__main__":
    main()
