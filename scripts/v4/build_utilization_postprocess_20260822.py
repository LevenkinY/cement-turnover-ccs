#!/usr/bin/env python3
"""Build audited utilization-floor summaries from the corrected 2026-08-22 runs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CENTRAL = ROOT / "results/v4/final_verified_inputs_20260829"
UTIL = ROOT / "results/v4/min_utilization_verified_inputs_20260829"
YEARS = (2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060)

SPECS = {
    0.20: UTIL / "u020",
    0.30: UTIL / "u030",
    0.40: CENTRAL,
    0.50: UTIL / "u050",
}


def one_metric(table: pd.DataFrame, name: str) -> pd.Series:
    selected = table.loc[table["metric"].eq(name)]
    if len(selected) != 1:
        raise ValueError(f"Expected one row for {name}; found {len(selected)}")
    return selected.iloc[0]


def main() -> None:
    summary_rows = []
    status_rows = []
    checks = []
    for floor, root in SPECS.items():
        metrics = pd.read_csv(root / "analysis_s2/summary_metrics.csv")
        audit = pd.read_csv(root / "analysis_s2/audit_checks.csv")
        failures = int(audit["status"].astype(str).str.upper().eq("FAIL").sum())
        checks.append(
            {
                "check": f"analysis_s2_failures_u{int(floor * 100):03d}",
                "status": "PASS" if failures == 0 else "FAIL",
                "observed": failures,
                "expected": 0,
            }
        )
        lock = one_metric(
            metrics, "turnover_lockin_regret__fixed_turnover_vs_full_treatment"
        )
        objective = one_metric(metrics, "objective_incumbent")
        terminal = one_metric(metrics, "terminal_operating_plants")
        renewals = one_metric(metrics, "same_site_renewal_events")
        operation = pd.read_csv(root / "full/S1_baseline/data/operation_status.csv")
        operation["period"] = operation["period"].astype(int)
        operation["operating"] = pd.to_numeric(operation["operating"], errors="coerce")
        operation["utilization"] = pd.to_numeric(operation["utilization"], errors="coerce")
        for year in YEARS:
            frame = operation.loc[operation["period"].eq(year)].copy()
            active = frame.loc[frame["operating"].gt(0.5)]
            at_floor = np.isclose(active["utilization"], floor, atol=1e-6, rtol=0.0)
            status_rows.append(
                {
                    "minimum_operating_utilization": floor,
                    "year": year,
                    "operating_lines": len(active),
                    "lines_at_floor": int(at_floor.sum()),
                    "share_operating_lines_at_floor": float(at_floor.mean()) if len(active) else np.nan,
                    "floor_tolerance": 1e-6,
                }
            )
        summary_rows.append(
            {
                "minimum_operating_utilization": floor,
                "turnover_lockin_regret_bn_cny": float(lock["comparison_value"]),
                "turnover_lockin_lower_bn_cny": float(lock["comparison_lower_bound"]),
                "turnover_lockin_upper_bn_cny": float(lock["comparison_upper_bound"]),
                "s1_terminal_lines": int(round(float(terminal["baseline_value"]))),
                "s1_renewal_events": int(round(float(renewals["baseline_value"]))),
                "s1_cost_bn_cny": float(objective["baseline_value"]),
                "source_root": str(root.relative_to(ROOT)),
            }
        )

    summary = pd.DataFrame(summary_rows).sort_values("minimum_operating_utilization")
    status = pd.DataFrame(status_rows).sort_values(
        ["minimum_operating_utilization", "year"]
    )
    summary.to_csv(UTIL / "utilization_sensitivity_summary.csv", index=False)
    status.to_csv(UTIL / "utilization_floor_binding.csv", index=False)
    pd.DataFrame(checks).to_csv(UTIL / "audit_checks.csv", index=False)
    if any(row["status"] == "FAIL" for row in checks):
        raise RuntimeError("Utilization post-processing audit failed")
    print(summary.to_string(index=False))
    print(status[status["year"].isin([2035, 2040, 2045])].to_string(index=False))


if __name__ == "__main__":
    main()
