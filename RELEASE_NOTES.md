# v1.0.0 — Code-only manuscript release

Released code covers the final plant-level optimization model, fixed-path counterfactuals, representative near-optimal identity analysis, selected post-processing programs and quantitative figure workflows.

- Seven core model files match the 2026-08-29 corrected-input evidence freeze byte for byte.
- 29 original source files have file-level checksums and source mappings.
- Includes public S1–S5 scenario mapping, requirements snapshots, input-file specifications and workflow instructions.
- Includes six data-free software tests. These do not substitute for empirical validation or a full national solve.
- Licensed under MIT. Third-party software and separately obtained data retain their own terms.

No input datasets, solved outputs, figure-source tables, map files, manuscript drafts, credentials or Gurobi licence files are included. Full numerical reproduction requires the study inputs and a suitable Gurobi licence. Some original audit scripts remain inspection-only without the separately held provenance/input bundle, as explained in `docs/WORKFLOW.md`.

---

# v2.0.0 — v5 model, current manuscript implementation

Released code covers the v5 plant-level optimization model that produced the current manuscript's solved results, its input-preparation programs, the scenario batch driver, the run-comparison tools and the manuscript figure programs.

- 46 v5 source files are byte-identical copies of the author's working sources, with file-level SHA-256 checksums and source mappings; the release manifest now covers 75 files in total.
- Adds the four-layer alternative-fuel structure, the re-anchored capture-cost curves with their scale exponents and decline cases, the capacity-operating parameters, and the distributed market-demand layer.
- Adds the manuscript's public case register S1–S6 (central, slow contraction, deep contraction, AF spatial equalization, planning regret, procedure check) alongside the batch's paired sensitivity arms R1–R8 and the commitment-relaxation runs K1/K2.
- Adds the run-comparison tools that make paired comparisons auditable: paired-configuration verification, bound-aware planning-loss reporting and the run table.
- Adds the figure programs behind manuscript Figs. 2–5 and Supplementary Figs. S1–S9.
- 11 data-free software tests. These do not substitute for empirical validation or a full national solve.
- Licensed under MIT. Third-party software and separately obtained data retain their own terms.

**Public case labels changed.** The manuscript renumbered the public scenarios; the v1.0.0 mapping table is superseded. See the table in `README.md`.

No input datasets, solved results, figure-source tables, geographic layers, manuscript drafts, credentials or Gurobi licence files are included. Full numerical reproduction requires the study inputs and a suitable Gurobi licence. The input validator and some scenario programs remain inspection-only without the separately held provenance bundle, as explained in `docs/INPUTS.md` and `docs/WORKFLOW.md`. The v4 model from v1.0.0 is retained unchanged in the same checkout.
