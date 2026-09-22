"""Terminal-value (R6) and commitment-relaxation (K) registration tests.

No solver calls: factor algebra, commitment-set construction, config plumbing,
and pair-checker key coverage. Registered 2026-09-14 in
parameters/terminal_value_commitment_20260914.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scenarios'))

from src_v5 import config_v5 as config
from verify_pair_configs import MUST_MATCH


def _factor(year, life, end_year=2060, min_service=15, d=0.05, mode="annuity_consistent_guarded"):
    """Mirror of FinalBuilder._terminal_charge_factor without building the model."""
    if mode != "annuity_consistent_guarded":
        return 1.0
    in_service = end_year + 1 - year
    if in_service < min_service or in_service >= life:
        return 1.0
    base = 1.0 - (1.0 + d) ** (-1.0)
    a_in = (1.0 - (1.0 + d) ** (-in_service)) / base
    a_full = (1.0 - (1.0 + d) ** (-life)) / base
    return a_in / a_full


def test_terminal_factor_matches_registered_table():
    # parameters/terminal_value_commitment_20260914.md section 4
    assert abs(_factor(2045, 25) - 0.768966) < 1e-4
    assert abs(_factor(2040, 25) - 0.909698) < 1e-4
    assert abs(_factor(2030, 40) - 0.908717) < 1e-4
    assert abs(_factor(2035, 40) - 0.837756) < 1e-4
    assert abs(_factor(2040, 40) - 0.747171) < 1e-4
    assert abs(_factor(2045, 40) - 0.631627) < 1e-4


def test_terminal_factor_guard_blocks_late_vintages():
    # vintages whose in-horizon service is shorter than the 15-year commitment
    # caliber get no salvage -- the free-investment guard
    for year in (2050, 2055, 2060):
        assert _factor(year, 25) == 1.0
        assert _factor(year, 40) == 1.0


def test_terminal_factor_central_mode_is_identity():
    for year in (2030, 2040, 2045, 2050, 2060):
        assert _factor(year, 25, mode="none") == 1.0


def test_commitment_set_empty_at_zero_years():
    # K1/K2 arm: CCS_MIN_OPERATING_YEARS = 0 empties the commitment index set
    # by construction (tau must satisfy t < tau and year[tau] <= year[t] + 0).
    years = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060]
    T = list(range(len(years)))
    for min_years, expected in ((15, True), (0, False)):
        pairs = [
            (t, tau)
            for t in T if t > 0
            for tau in T
            if t < tau and years[tau] <= years[t] + min_years
        ]
        assert bool(pairs) is expected


def test_config_defaults_and_registry():
    assert config.TERMINAL_VALUE_MODE == "none"
    assert dict(config.TERMINAL_VALUE_ASSET_LIVES) == {"ccs": 25, "renewal": 40}
    assert int(config.TERMINAL_VALUE_MIN_INHORIZON_SERVICE) == 15
    assert float(config.STORAGE_RATE_SCALE) == 1.0
    assert float(config.STORAGE_CUMULATIVE_SCALE) == 1.0
    assert int(config.CCS_MIN_OPERATING_YEARS) == 15
    # removed dead constants stay removed (tombstone assertions)
    for name in ("ARM_ENDOGENOUS", "CUMULATIVE_REDUCTION_TARGET", "CLOSURE_YEAR",
                 "REBUILD_MIN_CAPACITY_TD", "REBUILD_COST_CNY_PER_T_ANNUAL_CAPACITY",
                 "CCS_CAPTURE_BASE_2025", "CCS_CAPTURE_BASE_2025_CAPEX_HEAVY",
                 "CLUSTER_PARAMS", "T_IDX", "PERIOD_YEARS",
                 "TRANSPORT_COST_PER_T_KM", "CATCHMENT_RADIUS_SENSITIVITY",
                 "CARBON_PRICE_SENSITIVITY", "MSW_RADIUS_KM", "BIO_RADIUS_KM",
                 "OBSERVED_PILOT_CCS_COST_IN_OBJECTIVE",
                 "DEMAND_NODE_RESOLUTION_KM", "DEMAND_NODE_POPULATION_COVERAGE",
                 "CCS_MIN_CAPACITY_T_DAY_2030", "CCS_MIN_CAPACITY_T_DAY_2035"):
        assert not hasattr(config, name), f"dead constant re-appeared: {name}"
    assert "min_capacity" not in config.CCS_PARAMS


def test_pair_checker_covers_new_treatments():
    for key in ("terminal_value_mode", "storage_rate_scale",
                "storage_cumulative_scale", "ccs_min_operating_years"):
        assert key in MUST_MATCH, f"verify_pair_configs must-match missing {key}"
