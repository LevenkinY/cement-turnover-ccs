"""Build the distributed market-node layer for v5 (P0-4 v2, 2026-09-12).

Replaces the single-province market unit with ~150 market nodes so that the
average haul distance becomes an endogenous reverse force on fleet
concentration. The mechanism: closing a plant forces the remaining plants to
serve its market from farther away, so transport cost rises with concentration
and trades off against the fixed operating cost.

Design (see v5/parameters/regional_demand_transport_20260911.md v2.0 and the
MarketNodeLayer-v1 entry in v5/parameters/parameter_deduction.md):
  - Nodes: population-weighted k-means clustering of the 1,713-node 50 km layer
    WITHIN each province, cluster counts allocated across provinces in
    proportion to 2025 demand share with a floor of one (largest remainder).
    Target 150 (~5 per province, median 5, range 1-11).
  - Demand is two-level and unchanged in aggregate: province totals from
    official cement-output statistics x Liao effective clinker ratio; the
    within-province shape now comes from the market node's population share, so
    each cluster inherits the population share of its member 50 km nodes.
  - Arcs are built adaptively and verified by an exact transportation
    (Hall) feasibility test, not by a fixed K:
      seed:        nearest DEMAND_ARC_SEED_NEAREST nodes per plant
      node side:   connected capacity >= DEMAND_ARC_NODE_COVERAGE x node demand
      plant side:  candidate demand >= DEMAND_ARC_PLANT_COVERAGE x plant capacity
      corridor:    national top-N demand nodes within DEMAND_ARC_MAX_DISTANCE_KM
      own province: every node in the plant's province
      augment:     Dinic max-flow min-cut rounds that connect spare-capacity
                   plants to the starved nodes until the exact 2025 gap is at
                   the rounding-noise level
    Intra-province distance is the REAL haversine distance, so the retired
    "intra-province transport is zero" rule no longer applies.

Outputs:
  v5/data/demand_market_nodes.csv   node_id, lon, lat, province, pop,
                                    pop_share_national,
                                    pop_share_within_province, n_source_nodes
  v5/data/demand_market_arcs.csv    plant_id, node_id, distance_km

Usage:
  PYTHONPATH=v5/model .venv/bin/python v5/model/preprocessing/build_market_nodes.py
"""
from __future__ import annotations

import argparse
import collections
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "v5" / "model"))

from src_v5 import config_v5 as cfg                                  # noqa: E402
from src_v5 import data_loader_v5 as dl                              # noqa: E402

V5_DATA = PROJECT_ROOT / "v5" / "data"
DEFAULT_NODE_OUT = V5_DATA / "demand_market_nodes.csv"
DEFAULT_ARC_OUT = V5_DATA / "demand_market_arcs.csv"

EARTH_R_KM = 6371.0


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlam = np.radians(lon2 - lon1)
    a = (np.sin((p2 - p1) / 2.0) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2.0) ** 2)
    return 2.0 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def allocate_clusters(province_shares: dict, target: int) -> dict:
    """Allocate `target` clusters across provinces: floor 1, remainder by demand share."""
    provs = sorted(province_shares)
    if target < len(provs):
        raise ValueError(
            f"market-node target {target} is below the province count {len(provs)}"
        )
    counts = {p: 1 for p in provs}
    remainder = target - len(provs)
    exact = {p: float(province_shares[p]) * remainder for p in provs}
    for p in sorted(provs, key=lambda q: -exact[q]):
        add = min(int(np.floor(exact[p])), remainder)
        counts[p] += add
        remainder -= add
        if remainder == 0:
            break
    for p in sorted(provs, key=lambda q: -(exact[q] - np.floor(exact[q]))):
        if remainder == 0:
            break
        counts[p] += 1
        remainder -= 1
    return counts


def weighted_kmeans(lat, lon, weight, k, seed):
    """Weighted k-means++ with Lloyd iterations. Deterministic given `seed`."""
    rng = np.random.default_rng(seed)
    n = len(lat)
    k = min(k, n)
    if k == 1:
        w = weight / weight.sum()
        return np.zeros(n, dtype=int), np.array(
            [[(lat * w).sum(), (lon * w).sum()]]
        )
    centers = [int(rng.choice(n, p=weight / weight.sum()))]
    d2 = haversine(lat, lon, lat[centers[0]], lon[centers[0]]) ** 2
    for _ in range(1, k):
        prob = weight * d2
        total = prob.sum()
        prob = prob / total if total > 0 else np.full(n, 1.0 / n)
        centers.append(int(rng.choice(n, p=prob)))
        d2 = np.minimum(d2, haversine(lat, lon, lat[centers[-1]], lon[centers[-1]]) ** 2)
    C = np.array([[lat[c], lon[c]] for c in centers], dtype=float)
    labels = np.zeros(n, dtype=int)
    for _ in range(200):
        D = np.stack([haversine(lat, lon, C[c, 0], C[c, 1]) for c in range(k)], axis=1)
        new_labels = D.argmin(axis=1)
        new_C = C.copy()
        for c in range(k):
            m = new_labels == c
            if not m.any():
                continue
            wc = weight[m]
            new_C[c, 0] = float((lat[m] * wc).sum() / wc.sum())
            new_C[c, 1] = float((lon[m] * wc).sum() / wc.sum())
        converged = np.allclose(new_C, C, atol=1e-9) and np.array_equal(new_labels, labels)
        C, labels = new_C, new_labels
        if converged:
            break
    return labels, C


def build_market_nodes(nodes_df: pd.DataFrame, province_shares: dict, target: int):
    """Aggregate the descriptive node layer into market nodes, per province."""
    counts = allocate_clusters(province_shares, target)
    records, parent = [], {}
    next_id = 0
    for province in sorted(province_shares):
        sub = nodes_df[nodes_df["province"] == province]
        if sub.empty or province_shares.get(province, 0.0) <= 0.0:
            continue
        lat = sub["lat"].to_numpy(float)
        lon = sub["lon"].to_numpy(float)
        pop = sub["pop"].to_numpy(float)
        k = counts[province]
        if len(sub) <= k:
            labels = np.arange(len(sub))
            centers = np.array([[lat[i], lon[i]] for i in range(len(sub))], dtype=float)
        else:
            labels, centers = weighted_kmeans(
                lat, lon, pop, k, seed=zlib.crc32(province.encode("utf-8")) % 100000
            )
        for c in range(centers.shape[0]):
            m = labels == c
            if not m.any():
                continue
            next_id += 1
            records.append({
                "node_id": next_id,
                "lon": float(centers[c, 1]),
                "lat": float(centers[c, 0]),
                "province": province,
                "pop": float(pop[m].sum()),
                "n_source_nodes": int(m.sum()),
            })
            parent[next_id] = list(sub.index[m])
    out = pd.DataFrame(records)
    out["pop_share_national"] = out["pop"] / out["pop"].sum()
    out["pop_share_within_province"] = (
        out["pop"] / out.groupby("province")["pop"].transform("sum")
    )
    out = out[["node_id", "lon", "lat", "province", "pop",
               "pop_share_national", "pop_share_within_province", "n_source_nodes"]]
    # Per-node within-province demand share is the population share of the
    # member 50 km nodes, which is exactly what the two-level allocation needs.
    return out, parent


class _Dinic:
    """Max-flow with the min-cut reachable set (scipy's maximum_flow misfires here)."""

    def __init__(self, n):
        self.n = n
        self.to, self.cap, self.head, self.nxt = [], [], [-1] * n, []

    def add(self, u, v, c):
        self.to.append(v); self.cap.append(float(c))
        self.nxt.append(self.head[u]); self.head[u] = len(self.to) - 1
        self.to.append(u); self.cap.append(0.0)
        self.nxt.append(self.head[v]); self.head[v] = len(self.to) - 1

    def _bfs(self, s, t):
        self.level = [-1] * self.n
        self.level[s] = 0
        dq = collections.deque([s])
        while dq:
            u = dq.popleft()
            e = self.head[u]
            while e != -1:
                v = self.to[e]
                if self.cap[e] > 1e-12 and self.level[v] < 0:
                    self.level[v] = self.level[u] + 1
                    dq.append(v)
                e = self.nxt[e]
        return self.level[t] >= 0

    def _dfs(self, u, t, f):
        if u == t:
            return f
        e = self.it[u]
        while e != -1:
            v = self.to[e]
            if self.cap[e] > 1e-12 and self.level[v] == self.level[u] + 1:
                d = self._dfs(v, t, f if f < self.cap[e] else self.cap[e])
                if d > 1e-12:
                    self.cap[e] -= d
                    self.cap[e ^ 1] += d
                    self.it[u] = e
                    return d
            e = self.nxt[e]
            self.it[u] = e
        return 0.0

    def run(self, s, t):
        """Return (flow_value, min_cut_reachable_boolean_list)."""
        sys.setrecursionlimit(max(10000, 4 * self.n))
        flow = 0.0
        while self._bfs(s, t):
            self.it = list(self.head)
            while True:
                f = self._dfs(s, t, 1e18)
                if f <= 1e-12:
                    break
                flow += f
        reach = [False] * self.n
        reach[s] = True
        stack = [s]
        while stack:
            u = stack.pop()
            e = self.head[u]
            while e != -1:
                if self.cap[e] > 1e-12 and not reach[self.to[e]]:
                    reach[self.to[e]] = True
                    stack.append(self.to[e])
                e = self.nxt[e]
        return flow, reach


def build_arcs(dist, supply_by_period, plant_cap_full, demand_by_period,
               node_province, plant_province, d_max, top_n, tol_kt):
    """Adaptive arc set with a PERIOD-AWARE exact Hall-feasibility loop.

    Every period is checked, not just 2025. This matters because lines below the
    renewal capacity gate cannot renew and die at their original expiry, so a
    market node whose only nearby suppliers are small lines becomes unreachable
    in the late periods even though it is amply served in 2025. The augmentation
    therefore connects starved nodes to plants that are ALIVE IN THAT PERIOD.
    """
    n_plants, n_nodes = dist.shape
    n_periods = supply_by_period.shape[1]
    demand0 = demand_by_period[:, 0]
    supply0 = supply_by_period[:, 0]
    arcs = set()
    for i in range(n_plants):
        for j in np.argsort(dist[i])[:cfg.DEMAND_ARC_SEED_NEAREST]:
            if dist[i, j] <= d_max:
                arcs.add((i, int(j)))

    node_conn = collections.defaultdict(list)
    for (i, j) in arcs:
        node_conn[j].append(i)

    # node side: connected capacity >= coverage x 2025 demand
    for j in range(n_nodes):
        have = sum(supply0[i] for i in node_conn[j])
        if have >= cfg.DEMAND_ARC_NODE_COVERAGE * demand0[j]:
            continue
        for i in np.argsort(dist[:, j]):
            if have >= cfg.DEMAND_ARC_NODE_COVERAGE * demand0[j]:
                break
            if dist[int(i), j] > d_max:
                break
            if (int(i), j) not in arcs:
                arcs.add((int(i), j))
                node_conn[j].append(int(i))
                have += supply0[i]

    # plant side: candidate 2025 demand >= coverage x nameplate capacity
    for i in range(n_plants):
        cum = sum(demand0[k] for k in range(n_nodes) if (i, k) in arcs)
        if cum >= cfg.DEMAND_ARC_PLANT_COVERAGE * plant_cap_full[i]:
            continue
        for k in np.argsort(dist[i]):
            if cum >= cfg.DEMAND_ARC_PLANT_COVERAGE * plant_cap_full[i]:
                break
            if dist[i, int(k)] > d_max:
                break
            if (i, int(k)) not in arcs:
                arcs.add((i, int(k)))
                cum += demand0[k]

    # long-distance corridors: the national top-N 2025 demand nodes
    for j in np.argsort(demand0)[::-1][:top_n]:
        for i in range(n_plants):
            if dist[i, j] <= d_max:
                arcs.add((i, int(j)))

    # own-province market access (still inside the declared maximum distance)
    if cfg.DEMAND_ARC_OWN_PROVINCE:
        for i in range(n_plants):
            for j in range(n_nodes):
                if plant_province[i] == node_province[j] and dist[i, j] <= d_max:
                    arcs.add((i, j))

    arcs, worst = _augment(arcs, dist, supply_by_period, demand_by_period, tol_kt, d_max)
    return arcs, worst


def _maxflow_cut(arcs, n_plants, n_nodes, supply, demand):
    al = sorted(arcs)
    s, t = 0, n_plants + n_nodes + 1
    g = _Dinic(n_plants + n_nodes + 2)
    for i in range(n_plants):
        if supply[i] > 0:
            g.add(s, 1 + i, supply[i])
    for (i, j) in al:
        g.add(1 + i, 1 + n_plants + j, 1e18)
    for j in range(n_nodes):
        g.add(1 + n_plants + j, t, demand[j])
    delivered, reach = g.run(s, t)
    starved = [j for j in range(n_nodes) if not reach[1 + n_plants + j]]
    spare = [i for i in range(n_plants) if reach[1 + i]]
    return delivered, starved, spare


def _augment(arcs, dist, supply_by_period, demand_by_period, tol_kt, d_max,
             max_rounds=400):
    """Grow the arc set until EVERY period is Hall-feasible.

    Each round finds the worst period by exact max-flow, then connects the
    starved nodes of that period to the nearest plants that are alive in it.
    """
    n_plants, n_nodes = dist.shape
    n_periods = supply_by_period.shape[1]
    worst = float("inf")
    for rnd in range(max_rounds):
        deficits = []
        cuts = []
        for t in range(n_periods):
            delivered, starved, spare = _maxflow_cut(
                arcs, n_plants, n_nodes, supply_by_period[:, t], demand_by_period[:, t])
            deficits.append(float(demand_by_period[:, t].sum()) - delivered)
            cuts.append((starved, spare))
        t_worst = int(np.argmax(deficits))
        worst = deficits[t_worst]
        if rnd % 20 == 0 or worst <= tol_kt:
            print(f"    augment round {rnd:>3}: worst gap {worst:12,.2f} kt "
                  f"(period {t_worst}), starved {len(cuts[t_worst][0]):>3}, "
                  f"spare {len(cuts[t_worst][1]):>4}, arcs {len(arcs)}")
        if worst <= tol_kt:
            return arcs, worst
        starved, spare = cuts[t_worst]
        if not starved or not spare:
            return arcs, worst
        spare = np.array(spare)
        for j in starved:
            have = {a[0] for a in arcs if a[1] == j}
            n_added = 0
            for i in np.argsort(dist[spare, j]):
                pi = int(spare[i])
                if dist[pi, j] > d_max:
                    break
                if pi not in have:
                    arcs.add((pi, j))
                    n_added += 1
                if n_added >= cfg.DEMAND_ARC_MIN_CUT_ADD_PER_ROUND:
                    break
    return arcs, worst


def _hall_gap_lp(arcs, supply, demand):
    """Exact float LP check: gap = demand not deliverable (0 means feasible)."""
    from scipy.sparse import csr_matrix
    from scipy.optimize import linprog
    al = sorted(arcs)
    n_plants, n_nodes = len(supply), len(demand)
    r = np.array([a[0] for a in al])
    c = np.array([a[1] for a in al])
    idx = np.arange(len(al))
    A = csr_matrix(
        (np.ones(2 * len(al)),
         (np.concatenate([r, n_plants + c]), np.concatenate([idx, idx]))),
        shape=(n_plants + n_nodes, len(al)),
    )
    res = linprog(-np.ones(len(al)), A_ub=A,
                  b_ub=np.concatenate([supply, demand]),
                  bounds=(0, None), method="highs")
    if res.status != 0:
        return float(demand.sum())
    return float(demand.sum() + res.fun)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=cfg.DEMAND_MARKET_NODE_TARGET)
    parser.add_argument("--out-nodes", default=str(DEFAULT_NODE_OUT))
    parser.add_argument("--out-arcs", default=str(DEFAULT_ARC_OUT))
    args = parser.parse_args()

    t0 = time.time()
    print("=" * 72)
    print("  Market Node Builder (v5 P0-4 v2: distributed market nodes)")
    print("=" * 72)

    plants = dl.load_plants()
    _scm, _pa, liao, _afb, _afw = dl.load_regional()
    u0, _realized, ratio0, _gap = dl.build_baseyear_plant_utilization(
        plants, liao, cfg.BASEYEAR_OUTPUT_CSV)
    descriptive = dl.load_demand_nodes()
    province_shares, _clinker_kt = dl.build_province_demand_shares(
        liao, cfg.BASEYEAR_OUTPUT_CSV,
        output_override=cfg.DEMAND_PROVINCE_OUTPUT_OVERRIDE,
        ratio_fallback=cfg.DEMAND_PROVINCE_RATIO_FALLBACK)
    shares_by_year = dl.build_province_shares_by_year(
        province_shares, cfg.T_LIST, nodes_df=descriptive,
        convergence=cfg.DEMAND_PROVINCIAL_SHARE_CONVERGENCE)
    demand_path = dl.load_demand()[cfg.DEMAND_SCENARIO]
    # Year-specific national clinker ratio (the 2025 value is the base-year anchor).
    external_paths, _src = dl.load_external_technology_paths()
    ccr_case = str(getattr(cfg, "CCR_PATH_CASE", "central")).lower()
    ratio_path = (
        external_paths.set_index("year")[f"clinker_ratio_{ccr_case}"]
        .astype(float).to_dict()
    )
    ratio_path[int(cfg.T_LIST[0])] = float(ratio0)

    market, _parent = build_market_nodes(descriptive, province_shares, args.target)
    n_nodes = len(market)
    print(f"\n  market nodes: {n_nodes} across {market['province'].nunique()} provinces "
          f"(target {args.target})")
    print("  nodes per province:", dict(sorted(
        market.groupby("province").size().items(), key=lambda kv: -kv[1])[:8]), "...")

    node_province = market["province"].astype(str).tolist()
    plant_ids = plants["plant_id"].astype(int).tolist()
    indexed = plants.set_index("plant_id")
    plat = indexed["latitude"].astype(float).loc[plant_ids].to_numpy(float)
    plon = indexed["longitude"].astype(float).loc[plant_ids].to_numpy(float)
    plant_province = indexed["province"].astype(str).loc[plant_ids].to_numpy()
    capacity_td = pd.to_numeric(indexed["capacity"], errors="coerce").loc[plant_ids].to_numpy(float)
    cap_full = capacity_td * cfg.CAPACITY_T_DAY_TO_KT_YR
    cap_max = cap_full * np.array([float(u0[int(i)]) for i in plant_ids])
    lat_n = market["lat"].to_numpy(float)
    lon_n = market["lon"].to_numpy(float)
    dist = haversine(np.repeat(plat[:, None], n_nodes, 1),
                     np.repeat(plon[:, None], n_nodes, 1),
                     np.repeat(lat_n[None, :], len(plant_ids), 0),
                     np.repeat(lon_n[None, :], len(plant_ids), 0))

    # Plant availability by period. At t=0 every line is on (y fixed to 1, u fixed
    # to the base-year anchor). Later a line may operate only if its original
    # 40-year expiry has not passed, or it is large enough to renew at the site
    # (SAME_SITE_RENEWAL_MIN_CAPACITY_TD) and its single renewal window has come.
    commission = pd.to_numeric(
        indexed["commission_year"], errors="coerce"
    ).loc[plant_ids].fillna(float(cfg.PLANT_DEFAULT_COMMISSION_YEAR)).to_numpy(float)
    lifetime = int(getattr(cfg, "PLANT_LIFETIME_YEARS", 40))
    base_year = int(cfg.T_LIST[0])
    min_renew_td = float(getattr(cfg, "SAME_SITE_RENEWAL_MIN_CAPACITY_TD", 3200.0))
    max_renewals = int(getattr(cfg, "SAME_SITE_RENEWAL_MAX_COUNT", 1) or 0)
    effective_commission = np.maximum(commission, base_year - lifetime)
    expiry = effective_commission + lifetime
    first_renew_year = {}
    for i in range(len(plant_ids)):
        eligible = [y for y in cfg.T_LIST if y > expiry[i]]
        first_renew_year[i] = eligible[0] if eligible else None
    avail = np.zeros((len(plant_ids), len(cfg.T_LIST)))
    for t, year in enumerate(cfg.T_LIST):
        for i in range(len(plant_ids)):
            if t == 0:
                avail[i, t] = 1.0
            elif expiry[i] >= year:
                avail[i, t] = 1.0
            elif (max_renewals >= 1 and capacity_td[i] >= min_renew_td
                  and first_renew_year[i] is not None and first_renew_year[i] <= year):
                avail[i, t] = 1.0
    supply_by_period = np.where(
        np.arange(len(cfg.T_LIST))[None, :] == 0, cap_max[:, None], cap_full[:, None]
    ) * avail

    shape = market["pop_share_within_province"].to_numpy(float)
    demand_by_period = np.zeros((n_nodes, len(cfg.T_LIST)))
    for t, year in enumerate(cfg.T_LIST):
        nat = float(demand_path[year]) * 1000.0 * float(ratio_path[year])
        share_p = shares_by_year[year]
        demand_by_period[:, t] = [
            float(share_p.get(node_province[j], 0.0)) * shape[j] * nat
            for j in range(n_nodes)
        ]

    print(f"\n  D(2025) = {demand_by_period[:, 0].sum():,.1f} kt; "
          f"supply = {supply_by_period[:, 0].sum():,.1f} kt")
    print(f"  D(2060) = {demand_by_period[:, -1].sum():,.1f} kt; "
          f"supply = {supply_by_period[:, -1].sum():,.1f} kt "
          f"({int(avail[:, -1].sum())} lines alive)")
    print(f"  haul distance: median {np.median(dist):,.0f} km, "
          f"p90 {np.percentile(dist, 90):,.0f} km")

    print("\n  building adaptive arcs ...")
    arcs, deficit = build_arcs(
        dist, supply_by_period, cap_full, demand_by_period, node_province,
        plant_province, cfg.DEMAND_ARC_MAX_DISTANCE_KM,
        cfg.DEMAND_ARC_TOP_NATIONAL_NODES, cfg.DEMAND_ARC_FEASIBILITY_TOL_KT)

    candidates = np.array([sum(1 for a in arcs if a[0] == i) for i in range(len(plant_ids))])
    print(f"\n  arcs: {len(arcs):,} (median {np.median(candidates):.0f} candidates/plant, "
          f"p90 {np.percentile(candidates, 90):.0f}, max {candidates.max()})")
    print(f"  f_dem variables: {len(arcs) * len(cfg.T_LIST):,} (no new binaries)")

    # Exact Hall gate for every period, with the period-specific available supply.
    print("\n  Hall feasibility (exact float LP):")
    worst = 0.0
    for t, year in enumerate(cfg.T_LIST):
        gap = _hall_gap_lp(arcs, supply_by_period[:, t], demand_by_period[:, t])
        worst = max(worst, abs(gap))
        print(f"    {year}: demand {demand_by_period[:, t].sum():12,.1f} kt, "
              f"supply {supply_by_period[:, t].sum():12,.1f} kt, gap {gap:12,.4f} kt")
    if worst > 1.0:
        raise SystemExit(f"ERROR: Hall gap {worst:.3f} kt exceeds 1 kt; arcs are not feasible")

    nodes_out = Path(args.out_nodes)
    arcs_out = Path(args.out_arcs)
    nodes_out.parent.mkdir(parents=True, exist_ok=True)
    market.to_csv(nodes_out, index=False)
    # Arcs are built on positional node indices; map back to the exported node_id.
    node_id_of = market["node_id"].astype(int).tolist()
    pd.DataFrame(
        [(int(plant_ids[i]), int(node_id_of[j]), float(dist[i, j]))
         for (i, j) in sorted(arcs)],
        columns=["plant_id", "node_id", "distance_km"],
    ).to_csv(arcs_out, index=False)
    print(f"\n  wrote {nodes_out}")
    print(f"  wrote {arcs_out}")
    print(f"  elapsed {time.time() - t0:.1f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
