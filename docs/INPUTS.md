# Required external inputs

No input data are included. Paths below are relative to this repository root and are an interface specification, not evidence that these files are publicly available. `scripts/check_inputs.py` tests the paths marked **required** below.

## Core solve (required)

Read by `v5/model/src_v5/data_loader_v5.py` for every scenario.

| Path | Role |
|---|---|
| `data/model_input/plants/plant_data.xlsx` | Line IDs, names, province/city, capacity, coordinates and commissioning year |
| `data/model_input/plants/1_source_cement.xlsx` | Source workbook with line-level emission factors |
| `data/model_input/plants/plant_af_catchment.csv` | Plant-level AF catchment descriptors |
| `data/model_input/plants/plant_location_tier.csv` | Retained descriptive location tier |
| `data/model_input/plants/plant_data_corrections.csv` | Input correction provenance |
| `data/model_input/plants/cluster_assignment.csv` | Descriptive source cluster assignment (post-processing only) |
| `data/model_input/storage/storage_data_tif.csv` | Storage node capacities, coordinates and type attributes |
| `data/model_input/storage/storage_texture_5km.csv` | Storage texture attribute |
| `data/model_input/storage/cluster_sink_whitelist.csv` | Cluster–storage metadata (post-processing only) |
| `data/model_input/regional/cement_output_2025.csv` | Observed provincial base-year production anchor |
| `data/model_input/regional/scm_proxy.csv` | Provincial clinker-ratio inputs |
| `data/model_input/regional/process_adjustment_path.csv` | Process-emission adjustments |
| `data/model_input/regional/liao_provincial_baseline.csv` | Provincial baseline accounting |
| `data/model_input/regional/af_biomass_supply.csv` | Provincial biomass pools |
| `data/model_input/regional/af_waste_supply.csv` | Provincial waste pools |
| `data/model_input/technology/external_technology_paths.csv` | Exogenous energy-efficiency, alternative-raw-material and CCS cost paths |
| `data/model_input/technology/external_technology_path_sources.csv` | Technology-path source metadata |
| `data/model_input/demand/cement_demand_scenarios_v4.xlsx` | Three demand pathways and their anchors |

## Derived v5 layers (required)

Built by `v5/model/preprocessing/`, then read by every solve.

| Path | Role | Built by |
|---|---|---|
| `v5/data/plant_af_access_corrected.csv` | Plant-level AF accessibility, corrected for population density and overlapping catchments | `build_plant_af_catchment.py` |
| `v5/data/demand_market_nodes.csv` | The market nodes used by the optimization (~150, allocated per province by 2025 demand share) | `build_market_nodes.py` |
| `v5/data/demand_market_arcs.csv` | The plant-to-market-node arc set with distances | `build_market_nodes.py` |
| `v5/data/demand_nodes.csv` | Descriptive 50 km demand-node layer; input to the market-node build, not to a solve | `build_demand_nodes.py` |

## Additional raw inputs, needed only to rebuild the derived layers

| Path | Role |
|---|---|
| `data/raw/geography/中华人民共和国.geojson` | Land boundary used in offshore classification and node masking |
| `data/raw/population/chn_pd_2020_1km_UNadj.tif` | Population raster for demand-node placement and AF accessibility |
| `data/raw/biomass/bioenergy_s1_AFE_max.tif` | Bioenergy potential raster behind the AF accessibility table |

## Input validator and figure programs

- `v5/model/validate_final_inputs.py` additionally fingerprints a private bundle: a coordinate review ledger, `data/model_input/plants/fusion_2025/coordinate_recheck_report_20260828.md`, `scripts/shared/apply_verified_plant_coordinates_20260828.py`, `scripts/v4/audit_verified_submission_batch_20260822.py` and a solver-protocol note. It raises `FileNotFoundError` when that bundle is absent.
- The figure programs read solved results (`v5/results/formal_v1_20260914/`), the derived layers above, the 2025 fleet workbook, and figure-source tables extracted from those results: `v5/scenarios/rd_numbers_20260915/data02_*.csv` (written by `v5/scenarios/extract_rd_numbers_20260915.py`), `tmp/fig_restructure_20260919/fig3b_resource_conditions.csv` and `tmp/m2_analysis_20260918/m2_plant_metrics.csv` (written by the programs in `provenance/figure_input_prep/`). Two arc-certificate logs, `tmp/figS_20260919/check_arc_feasibility_d_medium.log` and `tmp/figS_20260919/screen_arc_economics.log`, supply printed captions in Supplementary Fig. S2 and are reproduced by the corresponding `v5/scenarios/` programs.
- National map rendering requires `input/district.shp` with its `.dbf` and `.shx` components and any accompanying `.prj`/`.cpg` files.

The model can generate solved outputs after valid inputs and a suitable solver licence are supplied. The post-processing programs must then use those outputs consistently, with no mixing of result runs or input versions; the paired-comparison tools in `v5/scenarios/` exist to make that check explicit. Author-supplied data, if obtained separately, retain their own terms; a software licence never grants rights to third-party datasets.
