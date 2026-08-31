"""Report missing external study inputs without downloading or modifying data."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "plants/plant_data.xlsx", "plants/1_source_cement.xlsx",
    "plants/plant_af_catchment.csv", "plants/plant_location_tier.csv",
    "plants/plant_data_corrections.csv", "plants/cluster_assignment.csv",
    "storage/storage_data_tif.csv", "storage/cluster_sink_whitelist.csv",
    "regional/cement_output_2025.csv", "regional/scm_proxy.csv",
    "regional/process_adjustment_path.csv", "regional/liao_provincial_baseline.csv",
    "regional/af_biomass_supply.csv", "regional/af_waste_supply.csv",
    "technology/external_technology_paths.csv",
    "technology/external_technology_path_sources.csv",
    "demand/cement_demand_scenarios_v4.xlsx",
]


def missing_inputs():
    paths = [ROOT / "data/model_input" / name for name in REQUIRED]
    paths.append(ROOT / "data/raw/geography/中华人民共和国.geojson")
    return [p for p in paths if not p.is_file()]


if __name__ == "__main__":
    missing = missing_inputs()
    for p in missing:
        print(f"MISSING {p.relative_to(ROOT)}")
    print("No data are distributed or downloaded by this package." if missing
          else "Required files present; this does not validate their contents.")
    raise SystemExit(2 if missing else 0)
