# Execution and figure workflow

Run commands from this repository root with the environment activated. Steps after the data-free tests require external inputs or solved outputs, which are not distributed here.

## 1. Core model

`scripts/run_case.py` selects the public S1–S5 cases and the paper's role-specific solve settings. Use `--dry-run` before starting a solve. The unchanged solver interface is also available:

```bash
export PYTHONPATH="$PWD/models/v4"
python -m src_v4.main --help
```

The retained core settings are minimum utilization 0.40, early-exit cost 130 CNY/t annual capacity, same-site renewal cost 400 CNY/t annual capacity, and a 40-year lifetime. No ban on CCS additions after 2045 is imposed. Structural counterfactuals are not causal estimates.

## 2. Full experimental design

The original frozen batch script is provided under `provenance/original_workflows/`. It records five core cases, nested fixed-turnover/fixed-dispatch comparisons, reverse commitments and the null control, the 35-year lifetime case, four representative near-optimal cases, and utilization settings 0.20/0.30/0.50. Together these comprise the 30 registered solved packages.

Those archival scripts retain their original repository-relative assumptions. **Do not execute them from the provenance directory.** Exact audit replay requires restoring them to their recorded `scripts/v4/` paths and obtaining the full private audit/input companion bundle. For public inspection and individual reproduction, use `scripts/run_case.py` and the original solver's documented options instead. Nothing in this package bypasses the original consistency checks.

Fixed-turnover cases use `--fixed-capacity-path PATH --fixed-capacity-mode turnover`; fixed-dispatch cases use `turnover_and_dispatch`. The latter retains the frozen numerical-tolerance handling in `counterfactual.py`. Numerical diagnostics must be checked before interpreting cost differences.

Near-optimal cases use the original `--near-opt-identity-reference`, `--near-opt-cost-reference`, `--near-opt-cost-tolerance 0.001`, direction and scope options. Their identity objectives differ from the economic objective and may have wide time-limit bounds. Record both phases; never call representative solutions a complete near-optimal frontier.

## 3. Analysis order

1. `analyze_capacity_feedback_counterfactual.py` for public S2 and each turnover sensitivity.
2. `analyze_storage_feedback_counterfactual.py` for public S3 with EOR qualification.
3. `analyze_near_optimal_identity_frontier.py` using a case manifest with columns `case_id`, `scenario`, `direction`, `scope`, `cost_tolerance`, `result_json`, `cost_reference_json`, `identity_reference_json`.
4. `analyze_writing_ready_storyline_v2.py` for five-case identity, responsibility and tier tables.
5. `build_utilization_postprocess_20260822.py` for utilization-floor summaries.
6. Bounded-endpoint opportunities, explicitly overriding this script's historical defaults:

```bash
python scripts/v4/analyze_robust_corridor_opportunities.py \
  --runs results/v4/final_verified_inputs_20260829 \
  --output-dir results/v4/postprocess_robust_corridors_bounded_endpoints_20260829
```

Use `--help` for each argument-taking analysis. Case/result metadata must match the exact reference files. Some original programs emit analytical reports containing numerical findings, but no such outputs are included in this code release.

## 4. Rebuild source tables, then plot

```bash
python scripts/v4/prepare_main_figure_data_2026_v2.py
python scripts/advanced/build_advanced_figure_interfaces.py \
  --result-dir results/v4/final_verified_inputs_20260829/full/S1_baseline \
  --spatial-assets paper/applied_energy_2026/submission/source_data_verified_20260829/fig3_spatial_assets_v2.csv \
  --output-dir paper/applied_energy_2026/submission/source_data_verified_20260829/advanced_interfaces \
  --public-case S1 --evidence-status canonical --expected-lines 1572
python scripts/advanced/plot_advanced_layout_prototypes.py \
  --interface-dir paper/applied_energy_2026/submission/source_data_verified_20260829/advanced_interfaces \
  --output-dir paper/applied_energy_2026/submission/figures \
  --main-figure-names --submission-formats
python scripts/v4/make_main_figures_2026_v2.py
python scripts/v4/make_si_figures_2026_v2.py
python scripts/v4/make_paper_figures_2026_si.py
python scripts/v4/make_fig_source_field_evolution.py
```

Preserved plotting programs generate submission formats and do not change the optimization. They may overwrite previously generated local graphics, so use a clean reproduction checkout. Matplotlib falls back if Arial is unavailable; font differences can change layout and require manual review.

| Manuscript figure | Source workflow |
|---|---|
| Fig. 1 | Author-designed conceptual diagram; not included |
| Figs. 2–3 | Advanced plant/province interfaces |
| Figs. 4–7, Supplementary Fig. S10 | Main quantitative plotting program |
| Fig. 8 | Source-field evolution program |
| Supplementary Fig. S1 | National overview in main plotting program |
| Supplementary Figs. S2–S6 | `make_paper_figures_2026_si.py` |
| Supplementary Figs. S7–S9 | `make_si_figures_2026_v2.py` |

## Validation limits

The release tests check source integrity, scenario mapping, configuration and synthetic path extraction. They do not validate a national solve or image layout without data. Exact plant identities can vary between near-optimal solutions, platforms and solver versions; use solver bounds and the manuscript's stated comparison metrics rather than assuming deterministic identity reproduction.
