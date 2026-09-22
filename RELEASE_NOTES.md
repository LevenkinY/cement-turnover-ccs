# v1.0.0 — Code-only manuscript release

Code accompanying **Co-optimizing capacity turnover and carbon capture to avoid lock-in in China's shrinking cement sector**. First published 2026-08-31; the v5 model, its batch drivers and the manuscript figure programs were added to the same version on 2026-09-22.

The release carries two model generations. The **v5** model produced the current manuscript's solved results; the earlier **v4** model is retained unchanged so that the analysis that preceded the current manuscript remains inspectable.

- 75 source files with file-level SHA-256 checksums and source mappings.
- **v5 (current)**: the plant-level optimization formulation, input-preparation programs, the scenario batch driver, the run-comparison tools and the figure programs behind manuscript Figs. 2–5 and Supplementary Figs. S1–S9. It adds the four-layer alternative-fuel structure, the re-anchored capture-cost curves with their scale exponents and decline cases, the capacity-operating parameters, and the distributed market-demand layer.
- **v4 (earlier)**: the model, counterfactual analyses and figure workflow first published in this release. Reachable as published at commit `9f104a244c844d21d73876c9d28fdb75f8322c63`.
- Public case register S1–S6 (central, slow contraction, deep contraction, AF spatial equalization, planning regret, procedure check), the paired sensitivity arms R1–R8 and the commitment-relaxation runs K1/K2. The labels were renumbered for the current manuscript; the mapping in the first publication of this release is superseded.
- 11 data-free software tests. These do not substitute for empirical validation or a full national solve.
- Licensed under MIT. Third-party software and separately obtained data retain their own terms.

No input datasets, solved outputs, figure-source tables, map files, manuscript drafts, credentials or Gurobi licence files are included. Full numerical reproduction requires the study inputs and a suitable Gurobi licence. Some original audit and validator scripts remain inspection-only without the separately held provenance/input bundle, as explained in `docs/INPUTS.md` and `docs/WORKFLOW.md`.
