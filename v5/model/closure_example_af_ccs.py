#!/usr/bin/env python
"""Single-plant closure example for the AF-CCS carbon-flow calibers.

Why this exists
---------------
The capture unit at a cement kiln sees ONE physical flue-gas stream. That stream
contains CO2 from three sources:

    calcination (process)   always fossil
    coal combustion         always fossil
    AF combustion           partly fossil, partly biogenic

The carbon budget in this model is a NET DIRECT emissions budget, so it may only
deduct the fossil part. But the pipeline and the storage site must carry and
inject the WHOLE captured stream. Treating the budget-credited tonnage as if it
were also the physically handled tonnage therefore under-counts the service the
transport and storage system has to provide.

This script makes that gap explicit and arithmetically closed for one plant-period,
so that the relation can be stated in the paper instead of asserted. It does NOT
change any result: it reads a solved result package and reports both calibers.

The conversion coefficient `AF_BIOGENIC_CO2_PER_TCE` (tCO2 physically released per
tce of AF energy) is an OPEN EVIDENCE GAP -- see v5/progress.md. Its central value
is 0.0, which makes the two calibers coincide. This script reports the gap at
whatever value the run actually used, and prints the MOEE-mix-based illustrative
value (grade C) alongside so the size of the un-modelled flow is visible.

Usage
-----
    python v5/model/closure_example_af_ccs.py RESULT.json [--plant ID] [--year YYYY]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# MOEE《企业温室气体排放核算与报告填报说明 水泥熟料生产》附录B gives per-fuel total
# emission factors and a non-biogenic ("非生物质") carbon share. A waste-dominated
# Chinese mix (illustratively 90% MSW-RDF at 39% non-biogenic + 10% industrial
# waste at 100%) works out to ~2.57 tCO2/tce total, of which ~1.26 fossil and
# ~1.31 biogenic. GRADE C: the per-fuel factors are grade A, the MIX is a
# construction -- no China-specific AF energy-share breakdown exists.
ILLUSTRATIVE_BIOGENIC_TCO2_PER_TCE = 1.31
ILLUSTRATIVE_FOSSIL_TCO2_PER_TCE = 1.26


def _fmt(label, value, unit=""):
    return f"    {label:<44} {value:>16,.4f} {unit}".rstrip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("result", type=Path, help="solved v5 result JSON")
    parser.add_argument(
        "--plant", type=int, default=None,
        help="plant id; default = the plant with the largest gross captured flow "
             "in the selected year",
    )
    parser.add_argument("--year", type=int, default=2060, help="model year")
    args = parser.parse_args(argv)

    payload = json.loads(args.result.read_text())
    plants = payload.get("plants") or {}
    if not plants:
        raise SystemExit("closure_example_af_ccs: no `plants` block in the result file")

    cfg = payload.get("effective_config") or payload.get("model_assumptions") or {}
    year_key = str(args.year)
    efficiency = float(cfg.get("capture_efficiency", 0.90))
    bio_coef = float(cfg.get("af_biogenic_co2_per_tce", 0.0))
    beta = float(cfg.get("beta_af", 0.55))

    def _gross(rec):
        captured = float(rec["captured"][year_key])
        af = float(rec["af_supply_ktce"][year_key])
        return captured + efficiency * bio_coef * af, captured, af

    candidates = {pid: _gross(rec) for pid, rec in plants.items()}
    if args.plant is not None:
        pid = str(args.plant)
        if pid not in candidates:
            raise SystemExit(f"closure_example_af_ccs: plant {pid} not found")
    else:
        pid = max(candidates, key=lambda k: candidates[k][0])
    gross, captured, af = candidates[pid]
    rec = plants[pid]

    print(f"File        : {args.result}")
    print(f"Plant       : {pid}")
    print(f"Year        : {args.year}")
    print(
        f"Caliber     : af_biogenic_co2_per_tce = {bio_coef:.4f} tCO2/tce "
        f"(central is 0.0), capture_efficiency = {efficiency:.3f}, beta_af = {beta:.2f}"
    )
    print()

    gross_emission = float(rec["co2_gross"][year_key])
    net_emission = float(rec["co2_net"][year_key])
    fuel_emission = float(rec["co2_fuel"][year_key])
    process_emission = float(rec["co2_process"][year_key])
    unit = "ktCO2/yr"

    print("  CLOSURE, BUDGET CALIBER (what the carbon budget sees)")
    print(_fmt("process CO2 (calcination, fossil)", process_emission, unit))
    print(
        _fmt(
            f"fuel CO2 after the AF fossil credit (beta={beta:.2f})",
            fuel_emission,
            unit,
        )
    )
    print(_fmt("= net direct emissions (co2_net)", net_emission, unit))
    print(_fmt("captured (deducted from the budget)", captured, unit))
    print(_fmt("= budget-credited abatement", captured, unit))
    print()

    biogenic_physical = efficiency * bio_coef * af
    print("  CLOSURE, PHYSICAL CALIBER (what the pipeline and storage site handle)")
    print(_fmt("AF energy burned", af, "ktce/yr"))
    print(
        _fmt(
            f"biogenic CO2 in the flue gas ({bio_coef:.4f} tCO2/tce)",
            bio_coef * af,
            unit,
        )
    )
    print(
        _fmt(
            f"of which captured at {efficiency:.0%}",
            biogenic_physical,
            unit,
        )
    )
    print(_fmt("captured, budget caliber", captured, unit))
    print(_fmt("= captured_gross, physically transported+stored", gross, unit))
    print()

    print("  THE GAP")
    print(_fmt("gap = captured_gross - captured", gross - captured, unit))
    share = (gross - captured) / gross if gross > 0 else 0.0
    print(_fmt("gap as a share of the physical flow", share * 100.0, "%"))
    print()

    print("  WHAT THE FLOW WOULD BE AT THE ILLUSTRATIVE MOEE-BASED MIX")
    print(
        "    (GRADE C: per-fuel factors are grade A, but no China-specific AF "
        "energy-share breakdown exists)"
    )
    illus_bio = efficiency * ILLUSTRATIVE_BIOGENIC_TCO2_PER_TCE * af
    print(
        _fmt(
            f"biogenic per tce = {ILLUSTRATIVE_BIOGENIC_TCO2_PER_TCE}",
            illus_bio,
            unit,
        )
    )
    print(_fmt("implied captured_gross", captured + illus_bio, unit))
    illus_share = illus_bio / (captured + illus_bio) if captured + illus_bio > 0 else 0.0
    print(_fmt("implied under-count as a share", illus_share * 100.0, "%"))
    print(
        _fmt(
            f"fossil per tce (cross-check) = {ILLUSTRATIVE_FOSSIL_TCO2_PER_TCE}",
            ILLUSTRATIVE_FOSSIL_TCO2_PER_TCE * af,
            unit,
        )
    )
    print()

    print("  HOW TO READ THIS")
    print(
        "    With the central coefficient of 0.0 the two calibers are identical by\n"
        "    construction: the model charges transport and storage on the same\n"
        "    tonnage it deducts from the budget, so the physical service is\n"
        "    under-counted by the biogenic part. That part is NOT a BECCS credit --\n"
        "    nothing is deducted twice and no negative emission is claimed; it is\n"
        "    additional TONNAGE the pipeline and the reservoir must handle.\n"
        "    Report the gap, do not call the budget tonnage the physical flow, and\n"
        "    do not quote an under-count from this script as a result: the mix is a\n"
        "    construction, and the run's own coefficient is what the model used."
    )
    print()
    print(f"  gross emission (all sources, pre-capture): {gross_emission:,.1f} {unit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
