"""Build plant-level AF accessibility for v5 (P0-2 data-pipeline fix).

Two defects in the v4 builder are corrected here:

1. **Unit error.** ``chn_pd_2020_1km_UNadj.tif`` is a population DENSITY raster
   (people/km2), but v4 summed the raw pixel values as if they were per-pixel
   counts. Summing raw density gives 2.013 bn people; summing density x cell area
   gives 1.439 bn (China 2020 = 1.412 bn). v4 therefore overstated catchment
   population, and hence the MSW resource, by a factor of 1.40.

2. **Overlap double counting.** v4 summed each plant's disc independently. With
   1,572 overlapping discs a single grid cell can be covered by up to 50 discs
   (MSW, 50 km) or 153 discs (biomass, 150 km), so the national total was
   inflated to 35,147 ktce. This version apportions each cell equally among the
   discs that cover it (the convention already stated in the project's own
   REALISM_STRUCTURE_UPDATE.md M2'), giving 1,455 ktce.

The output gives each plant's accessibility PER CHANNEL (MSW and biomass, in
ktce/yr). It is used as a *relative* weight within each province to allocate the
province resource pool — the raster is a technical-potential atlas, ~25-66x the
statistics-based deployable pool, so its absolute level must not be used as a cap.

Output: v5/data/plant_af_access_corrected.csv
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

PROJECT_ROOT = Path(__file__).resolve().parents[3]
V5_DATA = PROJECT_ROOT / "v5" / "data"
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_INPUT = PROJECT_ROOT / "data" / "model_input"

POP_TIF = DATA_RAW / "population" / "chn_pd_2020_1km_UNadj.tif"
BIO_TIF = DATA_RAW / "biomass" / "bioenergy_s1_AFE_max.tif"
PLANT_XLSX = DATA_INPUT / "plants" / "plant_data.xlsx"
OUT_CSV = V5_DATA / "plant_af_access_corrected.csv"

MSW_RADIUS_KM = 50.0
BIO_RADIUS_KM = 150.0
MSW_KG_PER_PERSON_YR = 450.0
BIO_GJ_PER_TONNE = 20.0
GJ_PER_TCE = 29.3076
MSW_TCE_PER_KT = 0.12
BIO_TCE_PER_KT = BIO_GJ_PER_TONNE / GJ_PER_TCE
GRID_DEG = 0.01


def _disc(lat0, lon0, radius_km, lat_c, lon_c, shape):
    """Bounding-box pre-filtered disc mask; returns (window, within-mask)."""
    km_lat = 111.0
    km_lon = 111.0 * max(np.cos(np.radians(lat0)), 0.05)
    m = radius_km * 1.15
    i0 = max(0, int(np.searchsorted(-lat_c, -(lat0 + m / km_lat))))
    i1 = min(shape[0], int(np.searchsorted(-lat_c, -(lat0 - m / km_lat))))
    j0 = max(0, int(np.searchsorted(lon_c, lon0 - m / km_lon)))
    j1 = min(shape[1], int(np.searchsorted(lon_c, lon0 + m / km_lon)))
    if i1 <= i0 or j1 <= j0:
        return None
    la = lat_c[i0:i1][:, None]
    lo = lon_c[j0:j1][None, :]
    dlat = np.radians(la - lat0)
    dlon = np.radians(lo - lon0)
    a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(lat0)) * np.cos(np.radians(la)) * np.sin(dlon / 2) ** 2
    within = 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))) <= radius_km * 1000.0
    return (i0, i1, j0, j1), within


def main() -> None:
    t0 = time.time()
    V5_DATA.mkdir(parents=True, exist_ok=True)
    print("=" * 72)
    print("  v5 plant AF accessibility builder (overlap- and area-corrected)")
    print("=" * 72)

    with rasterio.open(BIO_TIF) as src:
        bio = src.read(1).astype(np.float64)
        btr = src.transform
        bnod = src.nodata
    H, W = bio.shape
    if bnod is not None:
        bio = np.where(bio == bnod, 0.0, bio)
    bio = np.where(np.isfinite(bio) & (bio > 0), bio, 0.0)
    lat_c = btr.f + btr.e * (np.arange(H) + 0.5)
    lon_c = btr.c + btr.a * (np.arange(W) + 0.5)
    print(f"  grid {H}x{W} @ {GRID_DEG} deg")

    with rasterio.open(POP_TIF) as src:
        pop = src.read(1).astype(np.float64)
        ptr = src.transform
        pnod = src.nodata
    pop = np.where(pop == pnod, np.nan, pop)
    pop = np.where(np.isfinite(pop) & (pop > 0), pop, 0.0)
    hp, wp = pop.shape
    p_lat = ptr.f + ptr.e * (np.arange(hp) + 0.5)
    p_lon = ptr.c + ptr.a * (np.arange(wp) + 0.5)
    cell_km = abs(ptr.a) * 111.0
    pop_people = pop * (cell_km ** 2 * np.cos(np.radians(p_lat))[:, None])
    pj = np.floor((p_lon - btr.c) / btr.a).astype(np.int64)
    pi = np.floor((btr.f - p_lat) / (-btr.e)).astype(np.int64)
    sel = (pi >= 0)[:, None] & (pi < H)[:, None] & (pj >= 0)[None, :] & (pj < W)[None, :]
    pop_grid = np.zeros((H, W), dtype=np.float64)
    np.add.at(pop_grid,
              (np.broadcast_to(pi[:, None], pop.shape)[sel],
               np.broadcast_to(pj[None, :], pop.shape)[sel]),
              pop_people[sel])
    print(f"  population on grid: {pop_grid.sum()/1e9:.4f} bn  (China 2020 = 1.412 bn; "
          f"v4 raw-sum method would give {pop.sum()/1e9:.4f} bn)")

    plants = pd.read_excel(PLANT_XLSX).dropna(subset=["longitude", "latitude"]).copy()
    plants["longitude"] = pd.to_numeric(plants["longitude"], errors="coerce")
    plants["latitude"] = pd.to_numeric(plants["latitude"], errors="coerce")
    plants = plants.dropna(subset=["longitude", "latitude"])

    cnt_msw = np.zeros((H, W), dtype=np.uint16)
    cnt_bio = np.zeros((H, W), dtype=np.uint16)
    for r in plants.itertuples(index=False):
        for radius, cnt in ((MSW_RADIUS_KM, cnt_msw), (BIO_RADIUS_KM, cnt_bio)):
            got = _disc(float(r.latitude), float(r.longitude), radius, lat_c, lon_c, (H, W))
            if got is None:
                continue
            (i0, i1, j0, j1), within = got
            cnt[i0:i1, j0:j1] += within.astype(np.uint16)
    print(f"  coverage counts: max MSW={int(cnt_msw.max())}, biomass={int(cnt_bio.max())}")

    rows = []
    for r in plants.itertuples(index=False):
        lat0, lon0 = float(r.latitude), float(r.longitude)
        got = _disc(lat0, lon0, MSW_RADIUS_KM, lat_c, lon_c, (H, W))
        if got is None:
            msw_people = 0.0
        else:
            (i0, i1, j0, j1), within = got
            c = cnt_msw[i0:i1, j0:j1].astype(np.float64)
            share = np.divide(within, c, out=np.zeros_like(c), where=c > 0)
            msw_people = float((pop_grid[i0:i1, j0:j1] * share)[within].sum())
        got = _disc(lat0, lon0, BIO_RADIUS_KM, lat_c, lon_c, (H, W))
        if got is None:
            bio_gj = 0.0
        else:
            (i0, i1, j0, j1), within = got
            c = cnt_bio[i0:i1, j0:j1].astype(np.float64)
            share = np.divide(within, c, out=np.zeros_like(c), where=c > 0)
            bio_gj = float((bio[i0:i1, j0:j1] * share)[within].sum())
        rows.append({
            "plant_id": int(r.id),
            "province": str(r.province),
            "capacity": float(r.capacity),
            "msw_pop_50km": msw_people,
            "msw_kt_yr_50km": msw_people * MSW_KG_PER_PERSON_YR / 1e6,
            "biomass_kt_yr_150km": bio_gj / BIO_GJ_PER_TONNE / 1000.0,
        })

    df = pd.DataFrame(rows)
    df["msw_ktce"] = df.msw_kt_yr_50km * MSW_TCE_PER_KT
    df["bio_ktce"] = df.biomass_kt_yr_150km * BIO_TCE_PER_KT
    df["access_ktce"] = df.msw_ktce + df.bio_ktce
    df.to_csv(OUT_CSV, index=False)

    total = df.access_ktce.sum() / 1000.0
    fuel_2025 = 1096.769 * 0.105 * 1000.0
    print(f"\n  national accessibility: {total:,.1f} Mtce/yr "
          f"(v4 double-counted: 35,147.1 -> divide by {35147.1/total:.1f})")
    print(f"  channel split: MSW {df.msw_ktce.sum()/df.access_ktce.sum()*100:.1f}% / "
          f"biomass {df.bio_ktce.sum()/df.access_ktce.sum()*100:.1f}%")
    print(f"  2025 national fuel demand: {fuel_2025:,.1f} Mtce -> access/fuel = "
          f"x{total*1000/fuel_2025:.1f}")
    print(f"\n  output: {OUT_CSV}  ({len(df)} rows, {time.time()-t0:.1f}s)")
    print("=" * 72)


if __name__ == "__main__":
    main()
