# Required external inputs

No input data are included. Paths below are relative to this repository root and are an interface specification, not evidence that these files are publicly available.

## Core solve

| Path | Role |
|---|---|
| `data/model_input/plants/plant_data.xlsx` | Line IDs, names, province/city, capacity, coordinates and commissioning year |
| `data/model_input/plants/1_source_cement.xlsx` | Source workbook with line-level emission factors |
| `data/model_input/plants/plant_af_catchment.csv` | Plant ID and MSW/biomass accessibility weights |
| `data/model_input/plants/plant_location_tier.csv` | Retained descriptive location tier |
| `data/model_input/plants/plant_data_corrections.csv` | Input correction provenance |
| `data/model_input/plants/cluster_assignment.csv` | Descriptive source cluster/hub assignment |
| `data/model_input/storage/storage_data_tif.csv` | Storage node capacities, coordinates and type attributes |
| `data/model_input/storage/cluster_sink_whitelist.csv` | Cluster–storage metadata |
| `data/model_input/regional/cement_output_2025.csv` | Observed provincial base-year production anchor |
| `data/model_input/regional/scm_proxy.csv` | Provincial clinker-ratio inputs |
| `data/model_input/regional/process_adjustment_path.csv` | Process-emission adjustments |
| `data/model_input/regional/liao_provincial_baseline.csv` | Provincial baseline accounting |
| `data/model_input/regional/af_biomass_supply.csv` | Provincial biomass pools |
| `data/model_input/regional/af_waste_supply.csv` | Provincial waste pools |
| `data/model_input/technology/external_technology_paths.csv` | Exogenous technology paths |
| `data/model_input/technology/external_technology_path_sources.csv` | Technology-path source metadata |
| `data/model_input/demand/cement_demand_scenarios_v4.xlsx` | Three demand paths and their anchors |
| `data/raw/geography/中华人民共和国.geojson` | Land boundary used in offshore classification |

The exact columns, workbook handling and unit conversions are defined in `models/v4/src_v4/data_loader_v4.py`. The original national fleet contains 1,572 lines; substituting a different fleet requires recalibration and cannot reproduce the paper simply by retaining B40.

## Additional post-processing inputs

- `data/model_input/plants/fusion_2025/plant_fleet_2025_final.csv` is required by the bounded-opportunity analysis.
- `input/district.shp`, its `.dbf` and `.shx` components, and any accompanying `.prj`/`.cpg` files are required by national map rendering.
- The frozen input/code manifest and result JSON packages are required by source-verification and figure-data workflows.
- The original full-batch audit also requires private fleet-scope/coordinate review ledgers and protocol documentation. These are **not** silently replaced by fabricated files in this distribution.

The model can generate solved outputs after valid inputs and a suitable solver licence are supplied. The post-processing scripts must then use those outputs consistently, with no mixing of result runs or input versions. Author-supplied data, if obtained separately, retain their own terms; a software licence never grants rights to third-party datasets.
