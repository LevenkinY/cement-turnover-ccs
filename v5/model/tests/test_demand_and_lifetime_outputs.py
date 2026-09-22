"""Regression checks for revised demand inputs and lifetime-aware outputs."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "v5" / "model"))

from src_v5.data_loader_v5 import load_demand
from src_v5.config_v5 import config
from src_v5.results.extract import (
    _load_plant_metadata,
    capacity_transition_summary,
    plant_role_transition,
)


class DemandScenarioTests(unittest.TestCase):
    def test_active_scenarios_use_actual_data_through_2025(self):
        demand = load_demand()
        expected_actuals = {
            2022: 2129.27182,
            2023: 2022.93,
            2024: 1825.0,
            2025: 1693.0,
        }
        self.assertEqual(
            set(demand),
            {"d_high", "d_medium", "d_low"},
        )
        for pathway in demand.values():
            for year, actual in expected_actuals.items():
                self.assertAlmostEqual(pathway[year], actual, places=5)

    def test_final_demand_anchors_and_ordering(self):
        demand = load_demand()
        anchors = {
            "d_high": {2030: 1593.919521, 2050: 1252.287702, 2060: 1110.0},
            "d_medium": {2030: 1415.209878, 2035: 1183.0, 2050: 928.0, 2060: 928.0},
            "d_low": {2030: 1344.449385, 2035: 1064.7, 2050: 750.0, 2060: 708.735638},
        }
        for scenario, expected in anchors.items():
            for year, value in expected.items():
                self.assertAlmostEqual(demand[scenario][year], value, places=5)
        for year in range(2026, 2061):
            self.assertGreater(demand["d_high"][year], demand["d_medium"][year])
            self.assertGreater(demand["d_medium"][year], demand["d_low"][year])

    def test_model_period_cumulative_demand(self):
        demand = load_demand()
        expected_mt_year = {
            "d_high": 48_351.453960,
            "d_medium": 39_309.837510,
            "d_low": 34_417.603175,
        }
        for scenario, expected in expected_mt_year.items():
            actual = sum(
                config.PERIOD_WEIGHTS[year] * demand[scenario][year]
                for year in config.T_LIST
            )
            self.assertAlmostEqual(actual, expected, places=5)


class LifetimeOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (
            PROJECT_ROOT
            / "results"
            / "v4"
            / "results_v4_finalcheck"
            / "S1_baseline_results.json"
        )
        if not path.exists():
            raise unittest.SkipTest("Final-check S1 result is not available.")
        with path.open(encoding="utf-8") as f:
            cls.results = json.load(f)
        cls.meta = _load_plant_metadata()
        cls.transitions = plant_role_transition(cls.results, cls.meta)
        cls.summary = capacity_transition_summary(cls.results, cls.meta)

    def test_every_plant_has_one_lifetime_status(self):
        plant_count = len(self.results.get("plants", {}))
        self.assertEqual(len(self.transitions), plant_count)
        self.assertEqual(self.transitions["plant_id"].nunique(), plant_count)
        self.assertFalse(self.transitions["capacity_status"].isna().any())
        self.assertEqual(int(self.summary["plants"].sum()), plant_count)

    def test_long_term_status_requires_productive_operation(self):
        long_term = self.transitions["capacity_status"].str.startswith(
            "long_term_production"
        )
        self.assertTrue((self.transitions.loc[long_term, "productive_2060"] == 1).all())
        self.assertFalse(
            (
                (self.transitions["productive_2060"] == 1)
                & ~long_term
            ).any()
        )

    def test_early_exit_precedes_natural_retirement(self):
        early = self.transitions[
            self.transitions["capacity_status"] == "early_optimized_phaseout"
        ]
        finite = early[np.isfinite(early["years_early_vs_natural_retirement"])]
        self.assertTrue((finite["years_early_vs_natural_retirement"] > 0).all())


if __name__ == "__main__":
    unittest.main()
