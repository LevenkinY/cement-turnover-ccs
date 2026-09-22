"""P0-2: economic screening of the frozen market arc set (missed-arc cost).

Fixes the incumbent production pattern of
v5/results/core6_20260913_2334/central_J/S1_baseline_results.json
(supply_i[t] = cap_i x u_i[t]) and the d_medium market-node demands, then solves
the per-period minimum-cost transportation LP twice:

  min   sum_(i,j) cost_per_t(km_ij) x f_ij        (f in kt; cost in CNY/t)
  s.t.  sum_i f_ij = D_j[t]     node demand (final_builder.py:1017-1026)
        sum_j f_ij <= S_i[t]    incumbent plant supply

once on the FROZEN 20,188-arc set and once on a DENSIFIED set = frozen plus,
per plant, its 20 nearest nodes + all nodes <= 400 km + all same-province
nodes (great-circle, deduplicated). Arc unit cost is the cumulative piecewise
integral of DEMAND_TRANSPORT_COST_SEGMENTS (final_builder.py:256-269).

Also reports frozen-set arcs sitting at the DEMAND_ARC_MAX_DISTANCE_KM cap
(>= 1199 km) and their per-period flows / share of delivered tonnage.

Cost caliber: UNDISCOUNTED single-period delivered transport cost, no period
weights, in 10^9 CNY (B CNY). This is the transportation subproblem cost only,
not the model objective.

Usage:
    PYTHONPATH=v5/model .venv/bin/python v5/scenarios/screen_arc_economics.py
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "v5" / "model"))
sys.path.insert(0, str(PROJECT_ROOT / "v5" / "scenarios"))

from src_v5 import config_v5 as cfg                                  # noqa: E402
from src_v5 import data_loader_v5 as dl                              # noqa: E402
from check_arc_feasibility import haversine_km, node_demands         # noqa: E402

import gurobipy as gp                                                # noqa: E402
from gurobipy import GRB                                             # noqa: E402

RESULTS_JSON = (PROJECT_ROOT / "v5" / "results" / "core6_20260913_2334"
                / "central_J" / "S1_baseline_results.json")
NODES_CSV = PROJECT_ROOT / "v5" / "data" / "demand_market_nodes.csv"
ARCS_CSV = PROJECT_ROOT / "v5" / "data" / "demand_market_arcs.csv"

K_NEAREST = 20          # per-plant nearest nodes added to the dense set
RADIUS_KM = 400.0       # per-plant radius added to the dense set
CAP_EDGE_KM = 1199.0    # "at the 1,200 km cap" reporting threshold


def cost_per_t(km):
    """Cumulative piecewise integral of the segmented rate (final_builder._cost_per_t)."""
    d = float(km)
    if d <= 0.0:
        return 0.0
    cost, prev = 0.0, 0.0
    for upper, rate in cfg.DEMAND_TRANSPORT_COST_SEGMENTS:
        if d > prev:
            cost += (min(d, float(upper)) - prev) * float(rate)
        prev = float(upper)
        if d <= float(upper):
            break
    return cost


def incumbent_supply(plants, results):
    """{(plant_id, t_idx): cap_i x u_i[t] in kt}; self-checked against the summary."""
    years = [int(y) for y in cfg.T_LIST]
    cap = (pd.to_numeric(plants.set_index("plant_id")["capacity"], errors="coerce")
           * cfg.CAPACITY_T_DAY_TO_KT_YR)
    supply = {}
    for pid_str, rec in results["plants"].items():
        pid = int(pid_str)
        for t, year in enumerate(years):
            supply[(pid, t)] = float(cap.loc[pid]) * float(rec["u"][str(year)])
    print("\n  supply self-check vs results summary (clinker_production_kt):")
    for t, year in enumerate(years):
        got = sum(supply[(pid, t)] for pid in
                  [int(p) for p in plants["plant_id"]])
        want = float(results["summary"][str(year)]["clinker_production_kt"])
        print(f"    {year}: cap*u {got:>14,.2f} kt  vs  summary {want:>14,.2f} kt  "
              f"(diff {got - want:+.4f} kt)")
    return supply


def build_dense_arcs(plants, market, frozen):
    """Frozen + per-plant 20 nearest + all <=400 km + same-province (dedup)."""
    indexed = plants.set_index("plant_id")
    plant_ids = [int(p) for p in indexed.index]
    plat = indexed["latitude"].astype(float).to_numpy(float)
    plon = indexed["longitude"].astype(float).to_numpy(float)
    pprov = indexed["province"].astype(str).to_numpy()
    node_ids = market["node_id"].astype(int).tolist()
    nlat = market["lat"].to_numpy(float)
    nlon = market["lon"].to_numpy(float)
    nprov = market["province"].astype(str).to_numpy()
    dist = haversine_km(np.repeat(plat[:, None], len(node_ids), 1),
                        np.repeat(plon[:, None], len(node_ids), 1),
                        np.repeat(nlat[None, :], len(plant_ids), 0),
                        np.repeat(nlon[None, :], len(plant_ids), 0))
    dense = dict(frozen)   # (plant_id, node_id) -> km
    n_new = 0
    for k, pid in enumerate(plant_ids):
        added = set(np.argsort(dist[k])[:K_NEAREST])
        added |= set(np.where(dist[k] <= RADIUS_KM)[0])
        added |= {j for j in range(len(node_ids)) if nprov[j] == pprov[k]}
        for j in added:
            key = (pid, node_ids[int(j)])
            if key not in dense:
                dense[key] = float(dist[k, int(j)])
                n_new += 1
    return dense, n_new, dist.max()


def mincost_lp(arcs, supply_t, demand_t):
    """Min-cost transport LP for one period. Returns (cost_B_CNY, flows dict)."""
    by_plant = collections.defaultdict(list)
    by_node = collections.defaultdict(list)
    for a in arcs:
        by_plant[a[0]].append(a)
        by_node[a[1]].append(a)
    m = gp.Model("transport")
    m.Params.OutputFlag = 0
    f = m.addVars(arcs, lb=0.0, name="f")
    m.setObjective(
        gp.quicksum(cost_per_t(arcs[a]) * f[a] for a in arcs), GRB.MINIMIZE)
    for j, d in demand_t.items():
        m.addConstr(gp.quicksum(f[a] for a in by_node[j]) == d, name=f"node[{j}]")
    for i, lst in by_plant.items():
        m.addConstr(gp.quicksum(f[a] for a in lst)
                    <= float(supply_t.get(i, 0.0)), name=f"plant[{i}]")
    m.optimize()
    if m.Status != GRB.OPTIMAL:
        raise RuntimeError(f"transport LP not optimal, status {m.Status}")
    flows = {a: f[a].X for a in arcs if f[a].X > 1e-9}
    # f in kt, cost_per_t in CNY/t -> CNY = x1000; report in 1e9 CNY
    return float(m.ObjVal) * 1000.0 / 1e9, flows


def main():
    print("=" * 72)
    print("  P0-2 arc-set economic screening (fixed S1_baseline incumbent)")
    print("=" * 72)

    results = json.loads(RESULTS_JSON.read_text())
    print(f"  incumbent: {RESULTS_JSON.relative_to(PROJECT_ROOT)} "
          f"(status {results['status']}, demand {results['demand_scenario']})")
    plants = dl.load_plants()
    _scm, _pa, liao, _afb, _afw = dl.load_regional()
    market = dl.load_market_nodes(path=str(NODES_CSV))

    supply = incumbent_supply(plants, results)
    u0, _r, ratio0, _g = dl.build_baseyear_plant_utilization(
        plants, liao, cfg.BASEYEAR_OUTPUT_CSV)
    demand = node_demands(market, liao, ratio0, results["demand_scenario"])

    arc_df = pd.read_csv(ARCS_CSV)
    frozen = {(int(r.plant_id), int(r.node_id)): float(r.distance_km)
              for r in arc_df.itertuples(index=False)}
    dense, n_new, max_pair_km = build_dense_arcs(plants, market, frozen)
    added_dist = [d for (k, d) in dense.items() if k not in frozen]
    print(f"\n  frozen arcs {len(frozen):,}; dense arcs {len(dense):,} "
          f"(+{n_new:,}); new-arc distance p50 "
          f"{np.median(added_dist):.0f} km, max {max(added_dist):.0f} km "
          f"(full plant-node max {max_pair_km:.0f} km)")

    cap_arcs = {a: d for a, d in frozen.items() if d >= CAP_EDGE_KM}
    print(f"  frozen arcs at the 1,200 km cap (>= {CAP_EDGE_KM:.0f} km): "
          f"{len(cap_arcs)}")

    years = [int(y) for y in cfg.T_LIST]
    plant_ids = [int(p) for p in plants["plant_id"]]
    print(f"\n  {'year':>6} {'frozen B CNY':>13} {'dense B CNY':>12} "
          f"{'diff B CNY':>11} {'diff %':>8} {'cap-arc kt':>11} {'share %':>8}")
    tot_f = tot_d = 0.0
    rows = []
    cap_flow_by_year = {}
    for t, year in enumerate(years):
        supply_t = {pid: supply[(pid, t)] for pid in plant_ids}
        cost_f, flows_f = mincost_lp(frozen, supply_t, demand[t])
        cost_d, _flows_d = mincost_lp(dense, supply_t, demand[t])
        cap_flow = sum(v for a, v in flows_f.items() if a in cap_arcs)
        delivered = sum(flows_f.values())
        share = 100.0 * cap_flow / delivered if delivered else 0.0
        cap_flow_by_year[year] = cap_flow
        diff = cost_f - cost_d
        pct = 100.0 * diff / cost_f if cost_f else 0.0
        tot_f += cost_f
        tot_d += cost_d
        rows.append((year, cost_f, cost_d, diff, pct))
        print(f"  {year:>6} {cost_f:>13,.3f} {cost_d:>12,.3f} {diff:>11,.3f} "
              f"{pct:>7.3f}% {cap_flow:>11,.1f} {share:>7.3f}%")
    tdiff = tot_f - tot_d
    tpct = 100.0 * tdiff / tot_f
    worst = max(rows, key=lambda r: r[3])
    print(f"  {'TOTAL':>6} {tot_f:>13,.3f} {tot_d:>12,.3f} {tdiff:>11,.3f} "
          f"{tpct:>7.3f}%")
    print(f"\n  8-period delivered-cost gap (frozen - dense): {tdiff:,.3f} B CNY "
          f"= {tpct:.3f}% of frozen ({tot_f:,.3f} B CNY, undiscounted)")
    print(f"  largest single-period gap: {worst[0]} with {worst[3]:,.3f} B CNY "
          f"({worst[4]:.3f}%)")
    print(f"\n  1,200 km cap arcs: {len(cap_arcs)} arcs "
          f"(plant, node, km): "
          + ", ".join(f"{i}-{j}@{d:.0f}" for (i, j), d in
                      sorted(cap_arcs.items(), key=lambda kv: -kv[1])[:20]))
    print("  cap-arc flow by period (kt): "
          + ", ".join(f"{y} {v:,.1f}" for y, v in cap_flow_by_year.items()))


if __name__ == "__main__":
    main()
