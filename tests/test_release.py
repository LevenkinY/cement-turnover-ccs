"""Synthetic software checks. No real plant data or optimization outputs."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_case import CASES


class ArchivedV4Checks(unittest.TestCase):
    """The v1.0.0 implementation (models/v4) stays importable in this checkout."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "models/v4"))
        from src_v4.config_v4 import config as v4_config
        cls.config = v4_config

    def test_root_is_release_not_parent_project(self):
        self.assertEqual(self.config.PROJECT_ROOT, ROOT)

    def test_period_weights(self):
        self.assertEqual(sum(self.config.PERIOD_WEIGHTS.values()), 35)
        self.assertEqual(self.config.PERIOD_WEIGHTS[2025], 2.5)

    def test_turnover_configuration(self):
        self.assertEqual(self.config.MIN_OPERATING_UTILIZATION, .40)
        self.assertEqual(self.config.PLANT_LIFETIME_YEARS, 40)
        self.assertEqual(self.config.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY, 130)
        self.assertEqual(self.config.SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY, 400)


class V5Checks(unittest.TestCase):
    """The current implementation (v5) is importable and consistent without data."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "v5/model"))
        from src_v5.config_v5 import config as v5_config
        cls.config = v5_config

    def test_root_is_release_not_parent_project(self):
        self.assertEqual(self.config.PROJECT_ROOT, ROOT)

    def test_period_weights(self):
        self.assertEqual(sum(self.config.PERIOD_WEIGHTS.values()), 35)
        self.assertEqual(self.config.PERIOD_WEIGHTS[2025], 2.5)
        self.assertEqual(self.config.PERIOD_WEIGHTS[2060], 2.5)

    def test_operating_and_capacity_configuration(self):
        self.assertEqual(self.config.PLANT_LIFETIME_YEARS, 40)
        self.assertEqual(self.config.DAYS_PER_YEAR, 310)
        self.assertEqual(self.config.MIN_OPERATING_UTILIZATION, .30)
        self.assertEqual(self.config.SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY, 400.0)
        self.assertEqual(self.config.SAME_SITE_RENEWAL_MIN_CAPACITY_TD, 3200.0)
        self.assertEqual(self.config.CCS_MIN_OPERATING_YEARS, 15)

    def test_absolute_budget_cases_are_ordered(self):
        cases = self.config.CARBON_BUDGET_CASES
        self.assertGreater(cases["B30"]["cumulative_budget_kt_year"],
                           cases["B40"]["cumulative_budget_kt_year"])
        self.assertGreater(cases["B40"]["cumulative_budget_kt_year"],
                           cases["B50"]["cumulative_budget_kt_year"])
        self.assertEqual(self.config.DEMAND_SCENARIO, "d_medium")
        self.assertEqual(set(self.config.VALID_DEMAND_SCENARIOS),
                         {"d_high", "d_medium", "d_low"})

    def test_synthetic_capacity_path(self):
        from src_v5.counterfactual import extract_capacity_turnover_path, CapacityPathError
        fake = {"plants": {"1": {"y": {"2025": 1, "2030": 1},
                                 "r": {"2025": 0, "2030": 0},
                                 "u": {"2025": .5, "2030": .4}}}}
        path = extract_capacity_turnover_path(fake, [1], [2025, 2030], include_utilization=True)
        self.assertEqual(path[("u", 1, 1)], .4)
        broken = copy.deepcopy(fake)
        del broken["plants"]["1"]["u"]["2030"]
        with self.assertRaises(CapacityPathError):
            extract_capacity_turnover_path(broken, [1], [2025, 2030], include_utilization=True)


class PublicCaseMapping(unittest.TestCase):
    """run_case.py follows the manuscript's run register (Supplementary Table S6)."""

    def test_joint_cases(self):
        self.assertEqual(CASES["S1"][:2], ("S1_baseline", "d_medium"))
        self.assertEqual(CASES["S2"][:2], ("S1_baseline", "d_high"))
        self.assertEqual(CASES["S3"][:2], ("S1_baseline", "d_low"))
        self.assertEqual(CASES["S4"][:2], ("S3_all_spatial_equalized", "d_medium"))

    def test_committed_path_cases(self):
        self.assertEqual(CASES["S5"][2], "S4")
        self.assertEqual(CASES["S6"][2], "S1")

    def test_no_research_data_in_release(self):
        for directory in ["data", "input", "results", "output"]:
            self.assertFalse((ROOT / directory).exists())


if __name__ == "__main__":
    unittest.main()
