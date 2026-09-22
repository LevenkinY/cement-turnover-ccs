"""Loaded-input assertions and deterministic provenance, without solving."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import numpy as np


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    def normalize(x):
        if isinstance(x, pd.DataFrame):
            return {'columns': list(x.columns), 'rows': normalize(x.values.tolist())}
        if isinstance(x, pd.Series):
            return normalize(x.to_dict())
        if isinstance(x, dict):
            return [[str(k), normalize(v)] for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))]
        if isinstance(x, (tuple, list, np.ndarray)):
            return [normalize(v) for v in x]
        if isinstance(x, (set, frozenset)):
            return sorted((normalize(v) for v in x), key=str)
        if isinstance(x, np.generic):
            return x.item()
        if isinstance(x, Path):
            return str(x.resolve())
        return x
    return hashlib.sha256(json.dumps(normalize(value), sort_keys=True,
                                    ensure_ascii=False, default=str).encode()).hexdigest()


def validate_market_inputs(data, config):
    if not data.get('regional_demand_enabled', False):
        return {}
    node_path = Path(config.DEMAND_MARKET_NODE_FILE).resolve()
    arc_path = Path(config.DEMAND_MARKET_ARC_FILE).resolve()
    expected_nodes = pd.read_csv(node_path)
    actual_nodes = data['market_nodes']
    cols = ['node_id', 'lon', 'lat', 'province', 'pop', 'pop_share_within_province']
    pd.testing.assert_frame_equal(
        actual_nodes[cols].sort_values('node_id').reset_index(drop=True),
        expected_nodes[cols].sort_values('node_id').reset_index(drop=True),
        check_dtype=False, check_exact=True)
    frame = pd.read_csv(arc_path)
    expected_arcs = {(int(r.plant_id), int(r.node_id)): float(r.distance_km)
                     for r in frame.itertuples(index=False)}
    if len(expected_arcs) != len(frame):
        raise ValueError('duplicate market arcs in requested file')
    if data['demand_arcs'] != expected_arcs:
        raise ValueError('loaded market arcs differ from requested file')
    return {'nodes_path': str(node_path), 'arcs_path': str(arc_path),
            'nodes_sha256': sha256(node_path), 'arcs_sha256': sha256(arc_path),
            'nodes_loaded': len(actual_nodes), 'arcs_loaded': len(expected_arcs),
            'preflight': 'PASS'}
