"""Build the 50 km demand-node layer for v5 (P0-4).

STATUS (2026-09-12): this layer is DESCRIPTIVE ONLY. It does not enter the
optimization and carries no balance. It supplies (i) the within-province
population shape used to position the ~150 market nodes, (ii) the evidence for
the 65/35 between/within-province variance split, and (iii) figures. The
optimization layer is built by build_market_nodes.py, which clusters this file
within each province and constructs the Hall-feasible candidate arc set.

Design (see v5/parameters/regional_demand_transport_20260911.md):
  - Population raster aggregated to a 50 km grid; nodes are kept until they
    cover >=95% of national population. Measured yields ~1,713 nodes.
  - 50 km is the resolution at which a cell's maximum displacement (~71 km at
    100 km, i.e. 32 CNY/t at 0.45 CNY/t-km) is well below the fixed-cost
    discriminative scale; it is retained as the reference geography for the
    market-node clustering.
  - Node demand is NOT pure population share: this file stores only the
    *geography* (location, population, within-province population share).

Output: v5/data/demand_nodes.csv
    node_id, lon, lat, province, pop, pop_share_national,
    pop_share_within_province

Coordinates are population-weighted centroids inside each cell (not cell
corners), which removes the largest part of the centroid-aggregation error.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point, shape
from shapely.validation import make_valid
from shapely.strtree import STRtree
import json

PROJECT_ROOT = Path(__file__).resolve().parents[3]
V5_DATA = PROJECT_ROOT / "v5" / "data"
DATA_RAW = PROJECT_ROOT / "data" / "raw"

POP_TIF = DATA_RAW / "population" / "chn_pd_2020_1km_UNadj.tif"
PROVINCE_GEOJSON = DATA_RAW / "geography" / "中华人民共和国.geojson"
OUT_CSV = V5_DATA / "demand_nodes.csv"

CELL_KM = 50.0
POPULATION_COVERAGE = 0.95

# Province names in the geojson carry full administrative suffixes.
_SUFFIXES = ("维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区", "自治区",
             "省", "市", "自治州")


def _short_province(name: str) -> str:
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _load_provinces():
    """Read province polygons once; drop Taiwan/HK/Macau and non-province rows."""
    with open(PROVINCE_GEOJSON, encoding="utf-8") as handle:
        features = json.load(handle)["features"]
    polys, labels = [], []
    for feature in features:
        props = feature["properties"]
        if props.get("level") != "province":
            continue
        short = _short_province(props.get("name", ""))
        if short in {"", "台湾", "香港", "澳门"}:
            continue
        geom = shape(feature["geometry"])
        if not geom.is_valid:                # source file has self-intersections
            geom = make_valid(geom)
        geom = geom.buffer(0) if geom.is_empty else geom
        polys.append(geom)
        labels.append(short)
    return polys, labels, STRtree(polys)


def _population_grid():
    """Return (people_per_cell, lat_ascending, lon_ascending, rows, cols)."""
    with rasterio.open(POP_TIF) as src:
        density = src.read(1).astype("float64")
        nodata = src.nodata
        res = src.res[0]
        west, north, south = src.bounds.left, src.bounds.top, src.bounds.bottom
        height, width = density.shape

    density = np.where((density == nodata) | (density < 0), 0.0, density)
    lat_desc = north - (np.arange(height) + 0.5) * res
    lat_asc = lat_desc[::-1].copy()
    lon_asc = west + (np.arange(width) + 0.5) * res
    cell_km = 111.32 * res
    cell_area = (cell_km ** 2 * np.cos(np.radians(lat_desc)))[:, None] * np.ones((1, width))
    people = (density * cell_area)[::-1, :].copy()   # flip rows to ascending latitude
    assert lat_asc[0] < lat_asc[-1]
    assert south < lat_asc[0] < lat_asc[-1] < north
    return people, lat_asc, lon_asc


def _aggregate_grid(people: np.ndarray, n: int):
    """Sum people into n x n blocks; return (blocks, row_edges, col_edges)."""
    height, width = people.shape
    bh, bw = height // n, width // n
    trimmed = people[: bh * n, : bw * n]
    blocks = trimmed.reshape(bh, n, bw, n).sum(axis=(1, 3))
    return blocks, bh, bw


def main(cell_km=None, coverage=None, out_path=None):
    global CELL_KM, POPULATION_COVERAGE, OUT_CSV
    if cell_km is not None:
        CELL_KM = float(cell_km)
    if coverage is not None:
        POPULATION_COVERAGE = float(coverage)
    if out_path is not None:
        OUT_CSV = Path(out_path)
    start = time.time()
    print("=" * 68)
    print("  Demand Node Builder (v5, P0-4 regional demand)")
    print("=" * 68)

    for name, path in [("Population", POP_TIF), ("Provinces", PROVINCE_GEOJSON)]:
        if not path.exists():
            raise SystemExit(f"ERROR: missing {name}: {path}")
        print(f"  found {name:<11} -> {path.name}")

    people, lat_asc, lon_asc = _population_grid()
    national_pop = float(people.sum())
    print(f"\n  population raster: {people.shape[1]}x{people.shape[0]} @ {lat_asc.size} rows")
    print(f"  national population = {national_pop/1e9:.4f} bn")

    res_deg = 111.32 * (lat_asc[1] - lat_asc[0])
    n = max(1, int(round(CELL_KM / res_deg)))
    print(f"  aggregating {n}x{n} cells -> {n * res_deg:.2f} km blocks")

    blocks, bh, bw = _aggregate_grid(people, n)
    flat = blocks.ravel()
    order = np.argsort(flat)[::-1]
    cumulative = np.cumsum(flat[order]) / national_pop
    keep = int(np.searchsorted(cumulative, POPULATION_COVERAGE) + 1)
    kept_idx = np.sort(order[:keep])
    print(f"  blocks with population : {int((flat > 0).sum())}")
    print(f"  nodes for {POPULATION_COVERAGE:.0%} coverage: {keep}")

    # --- population-weighted centroid inside each kept block ---
    block_rows = np.arange(bh * bw) // bw
    block_cols = np.arange(bh * bw) % bw
    records = []
    for flat_idx in kept_idx:
        br, bc = int(block_rows[flat_idx]), int(block_cols[flat_idx])
        block = blocks[br, bc]
        if block <= 0:
            continue
        sub = people[br * n:(br + 1) * n, bc * n:(bc + 1) * n]
        sub_lat = lat_asc[br * n:(br + 1) * n]
        sub_lon = lon_asc[bc * n:(bc + 1) * n]
        total = float(sub.sum())
        if total <= 0:
            continue
        lat_c = float((sub.sum(axis=1) * sub_lat).sum() / total)
        lon_c = float((sub.sum(axis=0) * sub_lon).sum() / total)
        records.append((lat_c, lon_c, total))

    print(f"  nodes with positive population: {len(records)}")

    # --- province assignment (point in polygon) ---
    polys, labels, tree = _load_provinces()
    assigned = []
    misses = 0
    for lat_c, lon_c, total in records:
        point = Point(lon_c, lat_c)
        hit = None
        for candidate in tree.query(point):
            if polys[candidate].contains(point):
                hit = labels[candidate]
                break
        if hit is None:                      # fall back to nearest polygon
            nearest = tree.nearest(point)
            hit = labels[nearest]
            misses += 1
        assigned.append((lat_c, lon_c, total, hit))
    print(f"  province assignment: {len(assigned)} nodes, {misses} by nearest-polygon fallback")

    df = pd.DataFrame(assigned, columns=["lat", "lon", "pop", "province"])
    df = df.sort_values("pop", ascending=False).reset_index(drop=True)
    df["node_id"] = np.arange(1, len(df) + 1)
    df["pop_share_national"] = df["pop"] / df["pop"].sum()
    df["pop_share_within_province"] = df["pop"] / df.groupby("province")["pop"].transform("sum")
    df = df[["node_id", "lon", "lat", "province", "pop",
             "pop_share_national", "pop_share_within_province"]]

    V5_DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    print(f"\n  provinces covered: {df['province'].nunique()}")
    print(f"  top 5 nodes by population share:")
    for row in df.head(5).itertuples():
        print(f"    node {row.node_id:>5} {row.province:<6} "
              f"({row.lat:6.2f},{row.lon:7.2f}) pop={row.pop/1e6:6.2f} M")
    coverage = df["pop"].sum() / national_pop
    print(f"\n  retained population share = {coverage:.4%}")
    print(f"  output -> {OUT_CSV}")
    print(f"  elapsed {time.time() - start:.1f}s")
    print("=" * 68)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build v5 demand nodes. Defaults match the central setting; "
                    "the alternatives exist for the resolution-convergence test."
    )
    parser.add_argument("--cell-km", type=float, default=None,
                        help="Grid cell size in km (central 50; use 100 for the coarse "
                             "convergence run, 25 to refine)")
    parser.add_argument("--coverage", type=float, default=None,
                        help="Population coverage threshold (central 0.95)")
    parser.add_argument("--out", default=None,
                        help="Output CSV path (use a separate file for the coarse run "
                             "so the central demand_nodes.csv is not overwritten)")
    args = parser.parse_args()
    main(cell_km=args.cell_km, coverage=args.coverage, out_path=args.out)
