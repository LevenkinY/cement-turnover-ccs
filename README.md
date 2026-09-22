# Capacity turnover, plant-level resources and CCS planning

Code accompanying **Co-optimizing capacity turnover and carbon capture to avoid lock-in in China's shrinking cement sector**.

In a contracting cement industry, future CCS investment priorities depend on which industrial assets remain in operation. This study co-optimizes plant-level capacity turnover, alternative-fuel use and carbon capture for China's 1,572 inherited clinker lines over 2025–2060 under a common carbon budget, and traces how spatial differences in fuel access — by changing plants' pre-capture abatement opportunities — reshape which lines survive and what the surviving fleet must capture. A resource-neglect counterfactual commits a capacity path selected with AF spatial differences neutralized, and measures the additional discounted cost of honouring that commitment under real resource conditions (planning regret), reported with solver-bound intervals across eight paired sensitivity arms.

This code-only distribution contains the plant-level, multi-period mixed-integer optimization model, its input-preparation programs, the structural counterfactual and near-optimal identity interfaces, the scenario batch drivers, the run-comparison analysis tools and the manuscript figure programs. See `provenance/source_code_manifest.json` for the file-level correspondence between every released file and its source in the author's project.

## Release status

Version **1.0.0** is the single code-only release for this study. It carries two model generations.

| Model | Location | Role |
|---|---|---|
| **v5** | `v5/`, `paper/RCR/figure_build/` | the model behind the current manuscript's solved results (batch `formal_v1_20260914`) |
| **v4** | `models/v4/`, `scripts/v4/`, `scripts/advanced/` | the earlier implementation, retained unchanged from the release's first publication |

Both generations remain in the checkout: the v4 files are the ones first published, and the v5 model was added to the same version on 2026-09-22 rather than issued as a new one. The manuscript's numbers and figures come from the **v5** model; the v4-only state as first published remains reachable at commit `9f104a244c844d21d73876c9d28fdb75f8322c63`.

> **Public case labels were renumbered for the current manuscript.** The table below follows the manuscript's run register (Supplementary Table S6). The mapping published with the first version of this release was different: S2 meant AF equalization, S3 offshore parity, S4 slow contraction and S5 deep contraction. When in doubt, use the table below and the solver alias it names.

## Access and reproducibility boundary

**Input datasets, solved results, figure-source tables, geographic layers, manuscript drafts and solver licences are not included.** Without the study inputs, this repository supports code inspection and data-free tests, not numerical reproduction of the manuscript. The configuration file necessarily includes model parameters and reference-budget constants; these are part of the released model, not a release of the underlying datasets.

The data-free tests are synthetic software checks, not empirical validation. Full model runs require the separately obtained study inputs and a valid Gurobi licence. Installing `gurobipy` does not provide an unrestricted solver licence; the full national model exceeds the size of a restricted trial licence.

Released files are byte-identical copies of the author's working sources, so a comment inside one may refer to an internal development document, data ledger or scratch directory that is not part of this distribution. Those references are development history, not instructions; `docs/INPUTS.md` lists the paths that actually matter for a run.

## Installation

The packaging environment uses Python 3.13.5. Python 3.11 or later is recommended; only the documented packaging environment has been checked for this distribution.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python scripts/verify_release.py
python -m unittest discover -s tests -v
```

`requirements.txt` pins the direct dependencies of the released code. `requirements-lock.txt` records their installed transitive dependencies on the packaging machine. It does not lock platform-specific GDAL/PROJ binaries or proprietary fonts and is not represented as a recovered lockfile for every historical solve. Gurobi and third-party libraries remain subject to their own licences.

## Public scenario names

All six cases share the central resource configuration and the same absolute B40 carbon budget; they differ in the demand pathway or in the committed capacity path.

| Manuscript case | Meaning | Internal solver name | Demand | Committed path |
|---|---|---|---|---|
| S1 | Central joint optimization | `S1_baseline` | `d_medium` | — |
| S2 | Slow contraction | `S1_baseline` | `d_high` | — |
| S3 | Deep contraction | `S1_baseline` | `d_low` | — |
| S4 | AF spatial equalization (source of the committed path) | `S3_all_spatial_equalized` | `d_medium` | — |
| S5 | Planning regret: S4's path fixed under real AF conditions | `S1_baseline` | `d_medium` | from S4 |
| S6 | Procedure check: S1's own path fixed back into S1 | `S1_baseline` | `d_medium` | from S1 |

Legacy options named `S2_front_end` or `S4_storage_300km` in the unchanged solver are **not** manuscript S2 or S4, and several bare numeric aliases still resolve to those legacy cases. Always pass the full internal name, as `scripts/run_case.py` does.

Use the public wrapper below. It never searches the author's parent project for missing data, never downloads data, and refuses to overwrite an existing result directory for the selected case. It uses the model unchanged; raw solver outputs and regenerated tables remain local and are excluded by `.gitignore`.

```bash
# Data-free command preview; no optimization is launched.
python scripts/run_case.py --case S1 --dry-run

# After the required data have been obtained and placed as documented:
python scripts/check_inputs.py
python scripts/run_case.py --case S1     # central joint optimum
python scripts/run_case.py --case S2     # slow contraction
python scripts/run_case.py --case S3     # deep contraction
python scripts/run_case.py --case S4     # AF spatial equalization

# The commitment case fixes S4's capacity path under real resource conditions:
python scripts/run_case.py --case S5 --reference results/v5/S4

# The procedure check fixes S1's own path back into S1:
python scripts/run_case.py --case S6 --reference results/v5/S1
```

The manuscript additionally reports eight paired sensitivity arms — R1–R8 covering AF cost, AF effectiveness, the physical carbon burden of the captured stream, operating economics, spatial resolution, terminal treatment, EOR revenue and storage injection rates — and two commitment-relaxation runs (K1/K2). These are driven by `v5/scenarios/run_v5_formal_26.sh`, which re-optimizes each arm jointly and again with S4's path fixed, so that every premium compares the same commitment under changed conditions.

## Contents

- `v5/model/src_v5/`: the optimization formulation (`model/final_builder.py`, `model/carbon_streams.py`), input loader, parameter configuration (`config_v5.py`), fixed-path and near-optimal interfaces, result extraction and backbone analysis.
- `v5/model/preprocessing/`: programs that build the derived input layers — plant-level AF accessibility, the market-node and arc layer, plant location tiers and source clusters.
- `v5/model/validate_final_inputs.py`, `v5/model/closure_example_af_ccs.py`: the input validator and a single-plant arithmetic closure example for the two capture calibres.
- `v5/model/tests/`: original integration tests. They load study data and some need a solver licence.
- `v5/scenarios/`: the manuscript batch driver, a single-scenario runner and the comparison tools (run table and bound-aware planning loss, paired-configuration verification, arc-feasibility and arc-economics certificates, manuscript number extraction).
- `paper/RCR/figure_build/`: the programs that generate manuscript Figs. 2–5 and Supplementary Figs. S1–S9. The conceptual Fig. 1 is author-designed and is not generated by these programs.
- `scripts/v4/`: the figure style hub and shared plotting helpers imported by the figure programs, retained from the previous release.
- `provenance/`: the file-level source manifest, the superseded batch drivers of earlier design generations, and the figure-input preparation programs.
- `docs/INPUTS.md`: required external files and their roles.
- `docs/WORKFLOW.md`: scenario execution, comparison and figure sequence.
- `models/v4/`, `scripts/advanced/`: the earlier implementation, kept unchanged from the release's first publication.

## Interpretation

S1–S5 form the evidence chain: S4 is the resource-neglect counterfactual used as the identification experiment, S5 carries the planning-regret estimate, and S6 is a procedural check that the fixed-path machinery reproduces the joint solution. The near-optimal identity interface produces representative diagnostics, not strict identity extrema. Aggregated source–storage opportunities are not optimized shared-pipeline routes: the model assigns direct plant-to-storage flows. This is a system-planning model, not a unique plant-level forecast.

Carbon lock-in risk refers here to the risk that mismatched capacity commitments increase reliance on compensatory abatement. Planning regret measures the associated cost penalty, not a probability of lock-in or an inevitable increase in net emissions. Premiums are reported as solver-bound intervals; an interval containing zero is reported as unconfirmed and is never resolved by adjusting a parameter. The model supports staged appraisal and preservation of options, rather than approval of specific infrastructure projects.

## Citation, release and licence

Repository: https://github.com/LevenkinY/cement-turnover-ccs

Version **1.0.0** is the code-only release accompanying this study, first published on 2026-08-31 and updated on 2026-09-22 with the v5 model that produced the current manuscript's results. The released code and accompanying documentation are provided under the **MIT License** (see `LICENSE`). This licence does not cover third-party libraries, Gurobi, or any separately obtained datasets.

See `CITATION.md` and `CITATION.cff` for software citation metadata. The software maintainer is identified by the verified GitHub account `LevenkinY`; this is not a statement of the associated manuscript's full author list. Please cite the versioned software release and the associated article when available. Because the release carries two model generations, cite the version and state which model reproduces the numbers you use when that matters.
