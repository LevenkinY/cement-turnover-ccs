# Execution and figure workflow

Run commands from this repository root with the environment activated. Everything after the data-free tests requires external inputs or solved outputs, which are not distributed here. The run scripts call `.venv/bin/python` relative to the repository root, matching the documented environment.

## 1. Core model

```bash
# Public case wrapper: maps S1-S6 to the unchanged solver.
python scripts/run_case.py --case S1 --dry-run
python scripts/check_inputs.py
python scripts/run_case.py --case S1

# Equivalent direct call (single-scenario runner):
bash v5/scenarios/run_v5_s1.sh my_run
PYTHONPATH=v5/model python -m src_v5.main --help
```

The central configuration used by the manuscript is the model default: plant lifetime 40 years, same-site renewal available from 3,200 t/d, minimum operating utilization 0.30, fixed operating cost 40 CNY per tonne of annual capacity, early-retirement cost 17 CNY/t scaled by remaining life, 310 operating days per year, a minimum commercial-capture operating commitment of 15 years, and short/medium/long-haul transport rates of 0.55/0.12/0.05 CNY per tonne-kilometre over the 200 km and 600 km breaks. All of these are scalar constants in `v5/model/src_v5/config_v5.py`, which is the authoritative list; every run also dumps its `effective_config` block into the result JSON, and that dump — not this paragraph — is what a paired comparison checks.

The central configuration builds to 445,480 variables (37,728 binary) and 388,042 constraints. Solver profiles are `screen` (3% gap, screening only — no number from it enters the manuscript), `explore` (6%, mechanism checks) and `final` (MIPFocus 2), as defined in `config_v5.py`; the manuscript runs pass the `final` profile together with `--mip-gap 0.005`, a 7,200 s limit for joint runs and a 1,200 s limit for fixed-path runs.

## 2. Derived input layers

Rebuild these before a first solve; each writes into `v5/data/` or `data/model_input/`.

```bash
PYTHONPATH=v5/model python v5/model/preprocessing/build_demand_nodes.py       # 50 km descriptive nodes
PYTHONPATH=v5/model python v5/model/preprocessing/build_market_nodes.py       # market nodes + candidate arcs
python v5/model/preprocessing/build_plant_af_catchment.py                     # corrected AF accessibility
python v5/model/preprocessing/build_plant_location_tier.py                    # location tier
python v5/model/preprocessing/build_source_clusters.py                        # source clusters and sink whitelist
```

Run them in that order: the market-node build consumes the 50 km layer, and a solve consumes all five outputs plus the core-solve tables listed in `docs/INPUTS.md`. Two certificate programs test the market layer before it is used: `check_arc_feasibility.py` (exact Hall feasibility of the arc set under each demand pathway, using Gurobi) and `screen_arc_economics.py` (delivered-cost comparison between the frozen and a densified arc set from a fixed incumbent).

## 3. Full experimental design

`v5/scenarios/run_v5_formal_26.sh` is the batch that produced the manuscript numbers. It defines the core chain (C1 central, C2 high demand, C3 low demand, C4 AF-spatial equalization, C5 the equalized path fixed back under real conditions, C6 the self-check that fixes S1's own path back into S1), eight paired sensitivity arms (R1 AF cost, R2 AF effectiveness, R3 physical carbon burden of the captured stream, R4 operating economics, R5 spatial resolution, R6 terminal treatment, R7 EOR revenue, R8 storage injection rate) and the two commitment-relaxation runs K1/K2. Each arm is solved twice — jointly and with S4's path fixed — so the premium compares the same commitment under changed conditions.

```bash
bash v5/scenarios/run_v5_formal_26.sh                # 0.005 gap, final profile, 7,200 s
ROOT_OVERRIDE=v5/results/formal_v1_20260914 \
  bash v5/scenarios/run_v5_formal_26.sh 0.005 final 7200    # reuse finished runs
```

Runs whose result JSON already exists are skipped, so a partial batch resumes. Fixed-path runs are much easier than joint ones and receive a shorter limit (`FIXED_SECS`, default 1,200 s). The batch deliberately skips the 75-node spatial arm when `v5/data/alt_market_75/` is absent, which is the case in a data-free checkout.

Two notes on the shipped script text: its header calls the design "26 logical tasks" although the enumerated list sums to 24 solves, and it refers to internal documents that are not distributed here. Neither affects execution.

The superseded batch drivers of earlier design generations are kept under `provenance/earlier_batches/` for inspection: `run_v5_batch.sh` (an earlier public five-scenario set whose labels predate the manuscript's renumbering — do not read its mapping table as the manuscript's), `run_v5_layer2.sh`, `run_v5_core_evidence.sh` and `rerun_fixed_path_2pct.sh`. They still resolve the repository root, but their hard-coded run directories refer to result trees that are not part of this distribution.

## 4. Comparison discipline

Numbers that pair two optimized runs are reported as solver-bound intervals, never as single values. Three tools make that explicit.

```bash
# 1. Run table, cost calibers, asset overlap and bound-valid premiums:
python v5/scenarios/analyze_runs.py v5/results/formal_v1_20260914 \
  --reference C1_central_J --out v5/results/formal_v1_20260914/analysis --csv

# 2. Per-pair configuration check before interpreting any premium:
python v5/scenarios/verify_pair_configs.py JOINT.json FIXED.json

# 3. Planning loss with its bound interval and a resolution verdict:
python v5/scenarios/report_planning_loss.py JOINT.json FIXED.json --label R1
```

A pair whose `effective_config` blocks differ in anything other than the intended treatment is not comparable, and `verify_pair_configs.py` fails it. A premium whose interval contains zero is reported as unconfirmed; it is never resolved by relaxing a parameter. `comparison_contract.py` holds the classification rules that both tools apply. `extract_rd_numbers_20260915.py` extracts the manuscript's comparison tables from a finished batch and writes them to `v5/scenarios/rd_numbers_20260915/`.

## 5. Figures

Figure inputs are extracted from a finished batch first, then the figure programs run. All of them are PNG-only, 190 mm (main) or 155 mm (supplementary) at 600 dpi, and each carries numeric assertions that stop the render when a value has moved.

```bash
python v5/scenarios/extract_rd_numbers_20260915.py                  # group tables (data02_*.csv)
python provenance/figure_input_prep/m2_swap_group_drivers.py        # plant-level metric table
python provenance/figure_input_prep/extract_fig3b_resource_conditions.py
python provenance/figure_input_prep/extract_capture_task_decomposition.py
python provenance/figure_input_prep/extract_fig5b_spatial_reconfig.py

python paper/RCR/figure_build/make_rcr_fig23_v5_20260915.py         # Figs. 2-3
python paper/RCR/figure_build/make_rcr_fig45_v5_20260915.py         # Figs. 4-5, Fig. S1
python paper/RCR/figure_build/make_rcr_figS_v5_20260919.py          # Figs. S2-S6
python paper/RCR/figure_build/make_rcr_figS7_v5_20260919.py         # Figs. S7-S8
python paper/RCR/figure_build/make_rcr_figS9_v2_20260923.py         # Fig. S9 (current version)
```

The figure-input programs are the ones the author ran from a scratch directory; they resolve the repository root from their own location and write their tables next to themselves. They must run in the order above, because the resource-condition table consumes the metric table.

| Manuscript figure | Source workflow |
|---|---|
| Fig. 1 | Author-designed conceptual diagram; not generated by these programs |
| Figs. 2–3 | `make_rcr_fig23_v5_20260915.py` |
| Figs. 4–5, Supplementary Fig. S1 | `make_rcr_fig45_v5_20260915.py` |
| Supplementary Figs. S2–S6 | `make_rcr_figS_v5_20260919.py` |
| Supplementary Figs. S7–S8 | `make_rcr_figS7_v5_20260919.py` |
| Supplementary Fig. S9 | `make_rcr_figS9_v2_20260923.py` (the earlier S9 panel set inside `make_rcr_fig45_v5_20260915.py` is superseded) |

The style hub is `scripts/v4/figure_system_2026_common.py`, imported by every figure program together with shared map helpers in `scripts/v4/make_main_figures_2026_v2.py`. Matplotlib falls back if Arial is unavailable; font differences can change layout and require manual review. The figure programs write to `paper/RCR/figures/`, which is ignored by `.gitignore`.

## 6. Validation limits

The released data-free tests check source integrity, the public case mapping, the configuration and synthetic path extraction. The original integration tests under `v5/model/tests/` load study data through `load_all()` and are not runnable without it. Neither validates a national solve or image layout. Exact plant identities can vary between near-optimal solutions, platforms and solver versions; use solver bounds and the manuscript's stated comparison metrics rather than assuming deterministic identity reproduction.
