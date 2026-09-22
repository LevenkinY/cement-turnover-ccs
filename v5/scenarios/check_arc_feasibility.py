"""P0-1: Hall feasibility certification for the frozen market-node arc sets.

For a given market-node layer (nodes + arcs csv) and demand scenario, solve a
per-period minimum-gap transportation LP (Gurobi):

    min   sum_j s_j                                  (total undelivered demand, kt)
    s.t.  sum_i f_ij + s_j = D_j[t]     for each node j
          sum_j f_ij        <= S_i[t]   for each plant i
          f, s >= 0

S_i[t] mirrors build_market_nodes.py:463-492 (t=0: nameplate x u0 observed
utilisation; t>0: nameplate x 310 d x renewal eligibility). D_j[t] mirrors
final_builder.py:1017-1026 (national path x 1000 x clinker-ratio path x node
share, shares normalised per year as in build_market_node_shares_by_year).

If a period has a gap above tolerance, the starved nodes (slack > tol) are
listed together with the nearest alive plants with spare capacity inside
DEMAND_ARC_MAX_DISTANCE_KM that are not yet connected -- the augmentation rule
of build_market_nodes.py:_augment (up to DEMAND_ARC_MIN_CUT_ADD_PER_ROUND per
starved node). Nothing is written back to the data files.

Usage:
    PYTHONPATH=v5/model .venv/bin/python v5/scenarios/check_arc_feasibility.py \
        --scenario d_medium \
        --nodes v5/data/demand_market_nodes.csv \
        --arcs v5/data/demand_market_arcs.csv
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "v5" / "model"))

from src_v5 import config_v5 as cfg                                  # noqa: E402
from src_v5 import data_loader_v5 as dl                              # noqa: E402

import gurobipy as gp                                                # noqa: E402
from gurobipy import GRB                                             # noqa: E402

EARTH_R_KM = 6371.0
TOL_KT = float(cfg.DEMAND_ARC_FEASIBILITY_TOL_KT)


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km (same formula as build_market_nodes.haversine)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlam = np.radians(lon2 - lon1)
    a = (np.sin((p2 - p1) / 2.0) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2.0) ** 2)
    return 2.0 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def period_supplies(plants, liao):
    """{(plant_id, t_idx): available supply kt}; mirrors build_market_nodes.py:463-492."""
    u0, _realized, ratio0, _gap = dl.build_baseyear_plant_utilization(
        plants, liao, cfg.BASEYEAR_OUTPUT_CSV)
    indexed = plants.set_index("plant_id")
    plant_ids = [int(p) for p in indexed.index]
    capacity_td = pd.to_numeric(indexed["capacity"], errors="coerce").to_numpy(float)
    cap_full = capacity_td * cfg.CAPACITY_T_DAY_TO_KT_YR
    commission = pd.to_numeric(
        indexed["commission_year"], errors="coerce"
    ).fillna(float(cfg.PLANT_DEFAULT_COMMISSION_YEAR)).to_numpy(float)
    lifetime = int(getattr(cfg, "PLANT_LIFETIME_YEARS", 40))
    base_year = int(cfg.T_LIST[0])
    min_renew_td = float(getattr(cfg, "SAME_SITE_RENEWAL_MIN_CAPACITY_TD", 3200.0))
    max_renewals = int(getattr(cfg, "SAME_SITE_RENEWAL_MAX_COUNT", 1) or 0)
    effective_commission = np.maximum(commission, base_year - lifetime)
    expiry = effective_commission + lifetime
    supply = {}
    for k, pid in enumerate(plant_ids):
        eligible = [y for y in cfg.T_LIST if y > expiry[k]]
        first_renew = eligible[0] if eligible else None
        for t, year in enumerate(cfg.T_LIST):
            if t == 0:
                avail, base = 1.0, cap_full[k] * float(u0[pid])
            elif expiry[k] >= year:
                avail, base = 1.0, cap_full[k]
            elif (max_renewals >= 1 and capacity_td[k] >= min_renew_td
                  and first_renew is not None and first_renew <= year):
                avail, base = 1.0, cap_full[k]
            else:
                avail, base = 0.0, cap_full[k]
            supply[(pid, t)] = base * avail
    return supply, ratio0


def node_demands(market, liao, ratio0, scenario):
    """{t_idx: {node_id: demand kt}}; mirrors final_builder.py:1017-1026."""
    province_shares, _clinker_kt = dl.build_province_demand_shares(
        liao, cfg.BASEYEAR_OUTPUT_CSV,
        output_override=cfg.DEMAND_PROVINCE_OUTPUT_OVERRIDE,
        ratio_fallback=cfg.DEMAND_PROVINCE_RATIO_FALLBACK)
    descriptive = dl.load_demand_nodes()
    shares_by_year = dl.build_province_shares_by_year(
        province_shares, cfg.T_LIST, nodes_df=descriptive,
        convergence=cfg.DEMAND_PROVINCIAL_SHARE_CONVERGENCE)
    node_shares = dl.build_market_node_shares_by_year(market, shares_by_year)
    demand_path = dl.load_demand()[scenario]
    external_paths, _src = dl.load_external_technology_paths()
    ccr_case = str(getattr(cfg, "CCR_PATH_CASE", "central")).lower()
    ratio_path = (
        external_paths.set_index("year")[f"clinker_ratio_{ccr_case}"]
        .astype(float).to_dict()
    )
    ratio_path[int(cfg.T_LIST[0])] = float(ratio0)
    demand = {}
    for t, year in enumerate(cfg.T_LIST):
        national_kt = float(demand_path[year]) * 1000.0 * float(ratio_path[year])
        demand[t] = {
            nid: float(node_shares[int(year)].get(nid, 0.0)) * national_kt
            for nid in node_shares[int(year)]
        }
    return demand


def min_gap_lp(arcs, supply_t, demand_t):
    """Minimum total undelivered demand (kt) for one period. Gurobi LP."""
    plants_with_arcs = sorted({i for i, _ in arcs})
    by_plant = collections.defaultdict(list)
    by_node = collections.defaultdict(list)
    for a in arcs:
        by_plant[a[0]].append(a)
        by_node[a[1]].append(a)
    m = gp.Model("hall_gap")
    m.Params.OutputFlag = 0
    f = m.addVars(arcs, lb=0.0, name="f")
    s = m.addVars(list(demand_t), lb=0.0, name="s")
    m.setObjective(s.sum(), GRB.MINIMIZE)
    for j, d in demand_t.items():
        m.addConstr(gp.quicksum(f[a] for a in by_node[j]) + s[j] == d,
                    name=f"node[{j}]")
    shipped = {}
    for i in plants_with_arcs:
        expr = gp.quicksum(f[a] for a in by_plant[i])
        cap_i = float(supply_t.get(i, 0.0))
        m.addConstr(expr <= cap_i, name=f"plant[{i}]")
        shipped[i] = expr
    m.optimize()
    if m.Status != GRB.OPTIMAL:
        raise RuntimeError(f"gap LP not optimal, status {m.Status}")
    slack = {j: s[j].X for j in demand_t}
    gap = float(sum(slack.values()))
    shipped_qty = {i: shipped[i].getValue() for i in plants_with_arcs}
    return gap, slack, shipped_qty


def augmentation_advice(starved, slack, shipped_qty, supply_t, arcs, market, plants):
    """Nearest alive spare-capacity plants per starved node (build_market_nodes rule)."""
    indexed = plants.set_index("plant_id")
    have_arc = collections.defaultdict(set)
    for i, j in arcs:
        have_arc[j].add(i)
    node_geo = market.set_index("node_id")[["lat", "lon", "province"]]
    d_max = float(cfg.DEMAND_ARC_MAX_DISTANCE_KM)
    per_round = int(cfg.DEMAND_ARC_MIN_CUT_ADD_PER_ROUND)
    spare = [i for i, q in shipped_qty.items()
             if float(supply_t.get(i, 0.0)) - q > TOL_KT]
    advice = []
    for j in sorted(starved):
        lat_j, lon_j = float(node_geo.loc[j, "lat"]), float(node_geo.loc[j, "lon"])
        cand = []
        for i in spare:
            if i in have_arc[j] or i not in indexed.index:
                continue
            d = float(haversine_km(float(indexed.loc[i, "latitude"]),
                                   float(indexed.loc[i, "longitude"]), lat_j, lon_j))
            if d <= d_max:
                cand.append((d, i))
        cand.sort()
        advice.append({
            "node_id": int(j),
            "province": str(node_geo.loc[j, "province"]),
            "gap_kt": float(slack[j]),
            "add": [(int(i), round(d, 1)) for d, i in cand[:per_round]],
        })
    return advice


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", required=True,
                    choices=["d_high", "d_medium", "d_low"])
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--arcs", required=True)
    ap.add_argument("--label", default=None)
    args = ap.parse_args()
    label = args.label or f"{Path(args.nodes).parent.name}/{args.scenario}"

    print("=" * 72)
    print(f"  P0-1 Hall feasibility: {label}")
    print("=" * 72)

    plants = dl.load_plants()
    _scm, _pa, liao, _afb, _afw = dl.load_regional()
    market = dl.load_market_nodes(path=args.nodes)
    arc_df = pd.read_csv(args.arcs)
    arcs = [(int(r.plant_id), int(r.node_id))
            for r in arc_df.itertuples(index=False)]
    assert len(set(arcs)) == len(arcs), "duplicate arcs in file"

    supply, ratio0 = period_supplies(plants, liao)
    demand = node_demands(market, liao, ratio0, args.scenario)

    n_plants = len(plants)
    plants_with_arcs = {i for i, _ in arcs}
    print(f"\n  plants {n_plants}, nodes {len(market)}, arcs {len(arcs):,}, "
          f"plants with arcs {len(plants_with_arcs)}")
    print(f"\n  {'year':>6} {'demand kt':>14} {'supply kt':>14} {'gap kt':>12}")
    worst = 0.0
    all_advice = {}
    for t, year in enumerate(cfg.T_LIST):
        supply_t = {pid: supply[(pid, t)] for pid in plants_with_arcs}
        supply_total = sum(supply[(pid, t)] for pid in
                           [int(p) for p in plants["plant_id"]])
        demand_total = sum(demand[t].values())
        gap, slack, shipped_qty = min_gap_lp(arcs, supply_t, demand[t])
        worst = max(worst, gap)
        print(f"  {year:>6} {demand_total:>14,.1f} {supply_total:>14,.1f} "
              f"{gap:>12,.4f}")
        if gap > TOL_KT:
            starved = {j for j, v in slack.items() if v > TOL_KT}
            all_advice[year] = augmentation_advice(
                starved, slack, shipped_qty, supply_t, arcs, market, plants)

    print(f"\n  worst per-period gap: {worst:,.4f} kt "
          f"(tol {TOL_KT:.1f} kt; certificate {'PASS' if worst <= TOL_KT else 'FAIL'})")
    if all_advice:
        print("\n  augmentation advice (per starved node, nearest alive spare "
              f"plants <= {cfg.DEMAND_ARC_MAX_DISTANCE_KM:.0f} km, "
              f"<= {cfg.DEMAND_ARC_MIN_CUT_ADD_PER_ROUND} per node):")
        for year, rows in all_advice.items():
            print(f"    {year}:")
            for row in rows:
                adds = ", ".join(f"plant {i} @ {d} km" for i, d in row["add"])
                print(f"      node {row['node_id']} ({row['province']}) "
                      f"gap {row['gap_kt']:,.1f} kt -> {adds or 'NO SPARE PLANT IN RANGE'}")
    return 0 if worst <= TOL_KT else 1


if __name__ == "__main__":
    raise SystemExit(main())
