"""
Build source clusters from plant地理位置.
Generates:
  - cluster_assignment.csv  (plant_id, cluster_id, hub_plant_id, is_hub, dist_to_hub_km)
  - cluster_sink_whitelist.csv (cluster_id, storage_idx, hub_distance_km, sink_type)

Run once:  PYTHONPATH=v5/model python3 -m src_v5.build_source_clusters
"""

import sys, time, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src_v5.config_v5 import DATA_INPUT

# ── Config ────────────────────────────────────────────────────────────────
CLUSTER_PARAMS = {
    'enable_source_clustering': True,
    'optics_min_samples': 3,
    'optics_min_cluster_size': 4,
    'optics_xi': 0.035,
    # Maximum hub-to-sink route distance for the baseline whitelist.
    # Scenario S4_storage_300km applies the stricter 300 km screen at runtime.
    'max_cluster_radius_km': 500,
    'hub_selection_method': 'min_total_distance',
    'cluster_dsa_candidates': 3,
    'cluster_eor_candidates': 2,
    'enable_noise_merge': True,
    'noise_merge_radius_km': 150,
    'target_n_clusters': (220, 350),
    'singleton_ratio_max': 0.25,
}

STORAGE_CSV = DATA_INPUT / "storage" / "storage_data_tif.csv"
OUTPUT_CLUSTERS = DATA_INPUT / "plants" / "cluster_assignment.csv"
OUTPUT_WHITELIST = DATA_INPUT / "storage" / "cluster_sink_whitelist.csv"


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    lat1r, lat2r = np.radians(lat1), np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def _run_optics(xy, min_samples, min_cluster_size, xi):
    from sklearn.cluster import OPTICS
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=RuntimeWarning, module=r'sklearn\.cluster\._optics')
        return OPTICS(min_samples=int(min_samples), min_cluster_size=min_cluster_size, xi=float(xi)).fit_predict(xy).astype(int)


def _merge_noise(ccs_df, labels, radius_km):
    merged = labels.copy()
    noise_idx = np.where(merged == -1)[0]
    if len(noise_idx) == 0:
        return merged, 0
    non_noise = ccs_df[merged != -1].copy()
    if len(non_noise) == 0:
        return merged, 0
    non_noise['label'] = merged[merged != -1]
    centroids = {}
    for lb, grp in non_noise.groupby('label'):
        w = grp['annual_capacity'].values
        lon_c = np.average(grp['longitude'].values, weights=w) if w.sum() > 0 else grp['longitude'].mean()
        lat_c = np.average(grp['latitude'].values, weights=w) if w.sum() > 0 else grp['latitude'].mean()
        centroids[lb] = (float(lon_c), float(lat_c))
    merged_ignored = 0
    for ni in noise_idx:
        lon_n, lat_n = float(ccs_df.iloc[ni]['longitude']), float(ccs_df.iloc[ni]['latitude'])
        best_d, best_lb = float('inf'), None
        for lb, (lon_c, lat_c) in centroids.items():
            d = haversine_km(lon_n, lat_n, lon_c, lat_c)
            if d < best_d:
                best_d, best_lb = d, lb
        if best_lb is not None and best_d <= radius_km:
            merged[ni] = best_lb
        else:
            merged_ignored += 1
    return merged, merged_ignored


def _cluster_score(n_clusters, singleton_ratio, target_low=220, target_high=350, singleton_max=0.25):
    if n_clusters < target_low or n_clusters > target_high:
        return float('inf')
    r = singleton_ratio / singleton_max
    return r if r <= 1.0 else float('inf')


def _select_hub(members_idx, ccs_df, method):
    if len(members_idx) == 1:
        return int(members_idx[0])
    weights = np.array([float(ccs_df.at[i, 'annual_capacity']) for i in members_idx])
    lons = np.array([float(ccs_df.at[i, 'longitude']) for i in members_idx])
    lats = np.array([float(ccs_df.at[i, 'latitude']) for i in members_idx])
    if method == 'weighted_centroid_nearest':
        lon_c = float(np.average(lons, weights=weights))
        lat_c = float(np.average(lats, weights=weights))
        scores = [haversine_km(lon_c, lat_c, float(ccs_df.at[i, 'longitude']), float(ccs_df.at[i, 'latitude'])) for i in members_idx]
        return int(members_idx[int(np.argmin(scores))])
    best_score = None
    best_hub = int(members_idx[0])
    for cand in members_idx:
        lon_c, lat_c = float(ccs_df.at[cand, 'longitude']), float(ccs_df.at[cand, 'latitude'])
        score = sum(w * haversine_km(lon_c, lat_c, float(ccs_df.at[i, 'longitude']), float(ccs_df.at[i, 'latitude'])) for i, w in zip(members_idx, weights))
        if best_score is None or score < best_score:
            best_score = score
            best_hub = int(cand)
    return best_hub


def build_clusters():
    t0 = time.time()
    print("Loading plant data...")

    # Load plant metadata (all 1620 plants for clustering)
    meta = pd.read_excel(str(DATA_INPUT / "plants" / "plant_data.xlsx"))
    required = ['id', 'longitude', 'latitude', 'capacity']
    for c in required:
        if c not in meta.columns:
            raise ValueError(f"Missing column: {c}")

    # Build ccs_df for clustering (all plants with valid coords)
    ccs_df = meta[['id', 'longitude', 'latitude', 'capacity']].copy()
    ccs_df = ccs_df.rename(columns={'id': 'plant_idx', 'capacity': 'annual_capacity'})
    ccs_df['annual_capacity'] = ccs_df['annual_capacity'].fillna(0.0)
    valid = ccs_df.dropna(subset=['longitude', 'latitude']).copy()
    print(f"  {len(valid)}/{len(ccs_df)} plants with valid coordinates")

    xy = valid[['longitude', 'latitude']].values

    # ── Grid search over OPTICS params ──────────────────────────────────
    min_samples_cands = [3, 4, 5]
    min_cluster_size_cands = [4, 5, 6]
    xi_cands = [0.03, 0.035, 0.04, 0.05]
    noise_merge_cands = [150.0, None]  # None = no noise merge

    best_overall = None
    best_labels = None
    target_low, target_high = CLUSTER_PARAMS['target_n_clusters']
    singleton_max = CLUSTER_PARAMS['singleton_ratio_max']

    print("Searching OPTICS parameters...")
    for ms in min_samples_cands:
        for mcs in min_cluster_size_cands:
            for xi in xi_cands:
                labels_raw = _run_optics(xy, ms, mcs, xi)
                for nm_r in noise_merge_cands:
                    if nm_r is not None:
                        labels, _ = _merge_noise(valid.reset_index(drop=True), labels_raw, nm_r)
                    else:
                        labels = labels_raw

                    labels = np.where(labels == -1, labels, labels)  # keep -1 for noise
                    unique_labels = set(labels)
                    n_clusters = len([l for l in unique_labels if l != -1])
                    n_singleton = sum(1 for l in unique_labels if l != -1 and np.sum(labels == l) == 1)
                    singleton_ratio = n_singleton / n_clusters if n_clusters > 0 else 1.0

                    score = _cluster_score(n_clusters, singleton_ratio, target_low, target_high, singleton_max)

                    if best_overall is None or score < best_overall:
                        best_overall = score
                        best_labels = labels.copy()
                        best_params = {'min_samples': ms, 'min_cluster_size': mcs, 'xi': xi, 'noise_merge_radius_km': nm_r}
                        best_stats = {'n_clusters': n_clusters, 'n_singleton': n_singleton, 'singleton_ratio': singleton_ratio}

    print(f"  Best: clusters={best_stats['n_clusters']}, singletons={best_stats['n_singleton']} ({best_stats['singleton_ratio']:.1%}), params={best_params}")
    print(f"  Score={best_overall:.4f}")

    # ── Assign cluster IDs ───────────────────────────────────────────────
    unique_cids = sorted(set(best_labels[best_labels != -1]))
    cid_map = {old: new for new, old in enumerate(unique_cids)}
    final_labels = np.array([cid_map.get(l, -1) for l in best_labels])

    valid = valid.reset_index(drop=True)
    valid['cluster_id'] = final_labels

    # ── Noise points → singleton clusters ────────────────────────────────
    noise_mask = final_labels == -1
    if noise_mask.any():
        n_noise = noise_mask.sum()
        print(f"  {n_noise} noise points → treating as singleton clusters")
        noise_cid_start = len(unique_cids)
        for ni, is_noise in enumerate(noise_mask):
            if is_noise:
                final_labels[ni] = noise_cid_start
                noise_cid_start += 1
        valid['cluster_id'] = final_labels

    valid['cluster_id'] = valid['cluster_id'].astype(int)

    # ── Hub selection ─────────────────────────────────────────────────────
    print("Selecting hub plants...")
    hub_method = CLUSTER_PARAMS['hub_selection_method']
    plant_cluster_map = {}
    cluster_hubs = {}

    for cid, grp in valid.groupby('cluster_id'):
        members = grp['plant_idx'].tolist()
        hub_idx = _select_hub(members, valid.set_index('plant_idx'), hub_method)
        is_hub = (grp['plant_idx'] == hub_idx).values
        for pid, hub_flag in zip(grp['plant_idx'], is_hub):
            plant_cluster_map[int(pid)] = int(cid)
        lon_h = float(valid.set_index('plant_idx').at[hub_idx, 'longitude'])
        lat_h = float(valid.set_index('plant_idx').at[hub_idx, 'latitude'])
        cluster_hubs[int(cid)] = {'hub_plant_idx': int(hub_idx), 'longitude': lon_h, 'latitude': lat_h}

    valid['hub_plant_idx'] = valid['cluster_id'].map(lambda c: cluster_hubs[c]['hub_plant_idx'])
    valid['is_hub'] = valid['plant_idx'] == valid['hub_plant_idx']
    valid['dist_to_hub_km'] = valid.apply(
        lambda r: haversine_km(float(valid.set_index('plant_idx').at[r['plant_idx'], 'longitude']),
                               float(valid.set_index('plant_idx').at[r['plant_idx'], 'latitude']),
                               cluster_hubs[r['cluster_id']]['longitude'],
                               cluster_hubs[r['cluster_id']]['latitude']), axis=1)

    # ── Cluster-sink whitelist ─────────────────────────────────────────────
    print("Building cluster-sink whitelist...")
    storage_df = pd.read_csv(STORAGE_CSV)
    if 'is_offshore' not in storage_df.columns:
        storage_df['is_offshore'] = False

    n_dsa = CLUSTER_PARAMS['cluster_dsa_candidates']
    n_eor = CLUSTER_PARAMS['cluster_eor_candidates']
    max_dist = CLUSTER_PARAMS['max_cluster_radius_km']

    wl_rows = []
    for cid, hub in cluster_hubs.items():
        lon_h, lat_h = hub['longitude'], hub['latitude']
        temp = storage_df.copy()
        temp['hub_distance'] = temp.apply(lambda r: haversine_km(lon_h, lat_h, float(r['longitude']), float(r['latitude'])), axis=1)
        temp = temp[temp['hub_distance'] <= max_dist]

        dsa_cand = temp[temp['has_dsa']].copy() if 'has_dsa' in temp.columns else temp[temp.get('dsa_capacity', 0) > 0].copy()
        if len(dsa_cand) > 0:
            dsa_cand['score'] = dsa_cand['hub_distance'] / np.sqrt(dsa_cand.get('dsa_capacity', 1).clip(lower=1.0))
            dsa_sel = dsa_cand.nsmallest(n_dsa, ['score', 'hub_distance'])
        else:
            dsa_sel = dsa_cand

        eor_cand = temp[temp['has_eor']].copy() if 'has_eor' in temp.columns else temp[temp.get('eor_capacity', 0) > 0].copy()
        if len(eor_cand) > 0:
            eor_cand['score'] = eor_cand['hub_distance'] / np.sqrt(eor_cand.get('eor_capacity', 1).clip(lower=1.0))
            eor_sel = eor_cand.nsmallest(n_eor, ['score', 'hub_distance'])
        else:
            eor_sel = eor_cand

        for _, r in dsa_sel.iterrows():
            wl_rows.append({'cluster_id': int(cid), 'storage_idx': int(r['storage_idx']), 'hub_distance_km': float(r['hub_distance']), 'sink_type': 'dsa'})
        for _, r in eor_sel.iterrows():
            wl_rows.append({'cluster_id': int(cid), 'storage_idx': int(r['storage_idx']), 'hub_distance_km': float(r['hub_distance']), 'sink_type': 'eor'})

    wl_df = pd.DataFrame(wl_rows)
    if wl_df.empty:
        print("  WARNING: no cluster-sink pairs found — check storage_data_tif.csv")
    else:
        print(f"  {len(wl_df)} cluster-sink pairs ({wl_df['sink_type'].value_counts().to_dict()})")

    # ── Save ───────────────────────────────────────────────────────────────
    OUTPUT_CLUSTERS.parent.mkdir(parents=True, exist_ok=True)
    cluster_out = valid[['plant_idx', 'cluster_id', 'hub_plant_idx', 'is_hub', 'dist_to_hub_km', 'longitude', 'latitude']].copy()
    cluster_out = cluster_out.rename(columns={'plant_idx': 'plant_id'})
    cluster_out['plant_id'] = cluster_out['plant_id'].astype(int)
    cluster_out['cluster_id'] = cluster_out['cluster_id'].astype(int)
    cluster_out['hub_plant_idx'] = cluster_out['hub_plant_idx'].astype(int)
    cluster_out['is_hub'] = cluster_out['is_hub'].astype(bool)
    cluster_out.to_csv(OUTPUT_CLUSTERS, index=False)
    print(f"\n  Saved: {OUTPUT_CLUSTERS}")

    OUTPUT_WHITELIST.parent.mkdir(parents=True, exist_ok=True)
    wl_df.to_csv(OUTPUT_WHITELIST, index=False)
    print(f"  Saved: {OUTPUT_WHITELIST}")

    # ── Summary ────────────────────────────────────────────────────────────
    n_clusters = valid['cluster_id'].nunique()
    n_singletons = (valid.groupby('cluster_id').size() == 1).sum()
    print(f"\n  Total plants: {len(valid)}")
    print(f"  Clusters: {n_clusters}")
    print(f"  Singletons: {n_singletons} ({n_singletons/n_clusters:.1%})")
    print(f"  Hubs: {(valid['is_hub']).sum()}")
    print(f"  Time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    build_clusters()
