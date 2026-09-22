"""Report missing external study inputs without downloading or modifying data.

Paths are an interface specification, not evidence that the files exist publicly.
The core-solve list is what the v5 model reads for a scenario run; the rebuild
list is what the preprocessing programs additionally need.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_INPUT = [
    "plants/plant_data.xlsx", "plants/1_source_cement.xlsx",
    "plants/plant_af_catchment.csv", "plants/plant_location_tier.csv",
    "plants/plant_data_corrections.csv", "plants/cluster_assignment.csv",
    "storage/storage_data_tif.csv", "storage/storage_texture_5km.csv",
    "storage/cluster_sink_whitelist.csv",
    "regional/cement_output_2025.csv", "regional/scm_proxy.csv",
    "regional/process_adjustment_path.csv", "regional/liao_provincial_baseline.csv",
    "regional/af_biomass_supply.csv", "regional/af_waste_supply.csv",
    "technology/external_technology_paths.csv",
    "technology/external_technology_path_sources.csv",
    "demand/cement_demand_scenarios_v4.xlsx",
]
# Derived v5 layers, written by v5/model/preprocessing/ and read by every solve.
V5_DERIVED = [
    "v5/data/plant_af_access_corrected.csv",
    "v5/data/demand_market_nodes.csv",
    "v5/data/demand_market_arcs.csv",
]
REBUILD = [
    "data/raw/geography/中华人民共和国.geojson",
    "data/raw/population/chn_pd_2020_1km_UNadj.tif",
    "data/raw/biomass/bioenergy_s1_AFE_max.tif",
]


def missing_inputs():
    paths = [ROOT / "data/model_input" / name for name in MODEL_INPUT]
    paths += [ROOT / name for name in V5_DERIVED]
    return [p for p in paths if not p.is_file()]


if __name__ == "__main__":
    missing = missing_inputs()
    for p in missing:
        print(f"MISSING {p.relative_to(ROOT)}")
    print("No data are distributed or downloaded by this package." if missing
          else "Required files present; this does not validate their contents.")
    print("\nNeeded only to rebuild the derived layers (not to run a solve):")
    for name in REBUILD:
        state = "present" if (ROOT / name).is_file() else "missing"
        print(f"  {state:>7}  {name}")
    raise SystemExit(2 if missing else 0)
