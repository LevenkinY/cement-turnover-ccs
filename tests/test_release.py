"""Synthetic software checks. No real plant data or optimization outputs."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "models/v4"))
sys.path.insert(0, str(ROOT / "scripts"))
from src_v4.config_v4 import config
from src_v4.counterfactual import extract_capacity_turnover_path, CapacityPathError
from run_case import CASES


class CodeOnlyChecks(unittest.TestCase):
    def test_root_is_release_not_parent_project(self):
        self.assertEqual(config.PROJECT_ROOT, ROOT)

    def test_period_weights(self):
        self.assertEqual(sum(config.PERIOD_WEIGHTS.values()), 35)
        self.assertEqual(config.PERIOD_WEIGHTS[2025], 2.5)

    def test_turnover_configuration(self):
        self.assertEqual(config.MIN_OPERATING_UTILIZATION, .40)
        self.assertEqual(config.PLANT_LIFETIME_YEARS, 40)
        self.assertEqual(config.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY, 130)
        self.assertEqual(config.SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY, 400)

    def test_public_mapping(self):
        self.assertEqual(CASES["S2"][0], "S3_all_spatial_equalized")
        self.assertEqual(CASES["S3"][0], "S5_offshore_parity")
        self.assertEqual(CASES["S4"][1], "d_high")
        self.assertEqual(CASES["S5"][1], "d_low")

    def test_synthetic_capacity_path(self):
        fake = {"plants": {"1": {"y": {"2025": 1, "2030": 1},
                                 "r": {"2025": 0, "2030": 0},
                                 "u": {"2025": .5, "2030": .4}}}}
        path = extract_capacity_turnover_path(fake, [1], [2025, 2030], include_utilization=True)
        self.assertEqual(path[("u", 1, 1)], .4)
        broken = copy.deepcopy(fake)
        del broken["plants"]["1"]["u"]["2030"]
        with self.assertRaises(CapacityPathError):
            extract_capacity_turnover_path(broken, [1], [2025, 2030], include_utilization=True)

    def test_no_research_data_in_release(self):
        for directory in ["data", "input", "results"]:
            self.assertFalse((ROOT / directory).exists())


if __name__ == "__main__":
    unittest.main()
