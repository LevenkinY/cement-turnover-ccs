"""Regression checks for the final data and model protocol."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pyomo.environ import Binary, ConcreteModel, Objective, RangeSet, Var, value


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "v5" / "model"))

from src_v5.config_v5 import config
from src_v5.counterfactual import (
    CapacityPathError,
    DISPATCH_BAND_TOLERANCE,
    _reference_dispatch_preflight,
    extract_capacity_turnover_path,
    validate_reference_incumbent,
)
from src_v5.data_loader_v5 import load_all
from src_v5.main import apply_scenario_modifications
from src_v5.model.final_builder import V4Model
from src_v5.near_optimal_identity import (
    _fix_phase_one_binary_path,
    configure_near_optimal_identity,
)


class FinalProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_all()

    def test_period_weights_cover_2025_to_2060_once(self):
        self.assertAlmostEqual(sum(config.PERIOD_WEIGHTS.values()), 35.0)
        self.assertAlmostEqual(config.PERIOD_WEIGHTS[2025], 2.5)
        self.assertAlmostEqual(config.PERIOD_WEIGHTS[2060], 2.5)

    def test_default_planning_case_is_medium_demand_and_b40(self):
        self.assertEqual(config.DEMAND_SCENARIO, "d_medium")
        self.assertEqual(config.CARBON_BUDGET_CASE, "B40")
        self.assertEqual(
            set(config.VALID_DEMAND_SCENARIOS),
            {"d_high", "d_medium", "d_low"},
        )

    def test_absolute_budget_cases_are_fixed_and_ordered(self):
        cases = config.CARBON_BUDGET_CASES
        self.assertGreater(
            cases["B30"]["cumulative_budget_kt_year"],
            cases["B40"]["cumulative_budget_kt_year"],
        )
        self.assertGreater(
            cases["B40"]["cumulative_budget_kt_year"],
            cases["B50"]["cumulative_budget_kt_year"],
        )
        self.assertAlmostEqual(
            cases["B40"]["cumulative_budget_kt_year"],
            config.REFERENCE_CUMULATIVE_BAU_KT_YEAR * 0.60,
        )
        self.assertAlmostEqual(
            cases["B40"]["terminal_2060_cap_kt"],
            config.REFERENCE_2025_DIRECT_EMISSIONS_KT * 0.10,
        )

    def test_external_technology_paths_use_versioned_central_cases(self):
        self.assertEqual(self.data["arm_path_case"], "central")
        self.assertEqual(self.data["ee_path_case"], "central")
        arm_2060 = {
            round(float(value), 9)
            for (province, year), value in self.data["process_adjustment"].items()
            if int(year) == 2060
        }
        self.assertEqual(arm_2060, {0.053457})
        self.assertAlmostEqual(self.data["ee_path"][2060], 0.10)

    def test_observed_base_year_production_and_af_are_anchored(self):
        plants = self.data["plants"].set_index("plant_id")
        annual_capacity = plants["capacity"] * config.CAPACITY_T_DAY_TO_KT_YR
        clinker_kt = sum(
            float(annual_capacity.loc[i]) * float(u)
            for i, u in self.data["baseyear_utilization"].items()
        )
        expected_kt = (
            self.data["demand"][config.DEMAND_SCENARIO][2025]
            * 1000.0
            * self.data["national_clinker_ratio_path"][2025]
        )
        self.assertAlmostEqual(clinker_kt, expected_kt, places=3)

        # 2026-09-13: the anchor rate is defined on the plant-heat-demand caliber
        # H = sum_i h_i * (1-EE) * Q, with h_i = fuel_ef_i / COAL_EF. Using a flat
        # TCE_PER_T_CLINKER here would no longer match: the fleet-mean intensity is
        # 0.1069, not 0.105, so the flat denominator understates heat demand.
        coal_ef = float(config.COAL_EF_TCO2_PER_TCE)
        ef = self.data["plant_emission_factors"]
        fuel_ktce = sum(
            float(ef[i]["fuel_ef"]) / coal_ef
            * float(annual_capacity.loc[i])
            * float(u)
            for i, u in self.data["baseyear_utilization"].items()
        )
        af_ktce = sum(self.data["baseyear_af_supply_ktce"].values())
        self.assertAlmostEqual(af_ktce / fuel_ktce, config.INITIAL_AF_RATE, places=8)

    def test_storage_offshore_flags_exclude_land_false_positives(self):
        storage = self.data["storage"]
        self.assertTrue((~storage["is_offshore"] | storage["offshore_box_candidate"]).all())
        # Since the 2026-09-12 storage_data_tif rebuild the CSV itself carries the
        # China-land screening, so the loader's compensating correction is a no-op
        # (corrected == 0); the substantive invariant "no offshore node on land"
        # is asserted by the validator check offshore_nodes_exclude_china_land.
        corrected = storage["offshore_box_candidate"] & ~storage["is_offshore"]
        self.assertEqual(int(corrected.sum()), 0)
        self.assertTrue(
            storage["offshore_classification_method"]
            .eq("basin_box_excluding_china_land")
            .all()
        )

    def test_dual_resource_storage_routes_keep_both_types(self):
        route_types = {}
        for plant_id, routes in self.data["plant_storage"].items():
            for storage_idx, _, sink_type in routes:
                route_types.setdefault((int(plant_id), int(storage_idx)), set()).add(
                    str(sink_type).lower()
                )
        self.assertTrue(any(types == {"dsa", "eor"} for types in route_types.values()))

    def test_front_end_stress_preserves_2025_and_scales_future(self):
        original = self.data
        stressed = apply_scenario_modifications(copy.deepcopy(original), "S2_front_end")
        for mapping_name, scale in [
            ("province_af_pool_ktce", 0.6),
            ("af_alloc_bio", 0.6),
            ("af_alloc_wst", 0.6),
            ("process_adjustment", 0.5),
        ]:
            source = original[mapping_name]
            changed = stressed[mapping_name]
            for key, value in source.items():
                expected = float(value) if int(key[1]) == 2025 else scale * float(value)
                self.assertAlmostEqual(changed[key], expected, places=9)

    def test_spatial_equalization_preserves_national_af_and_base_year(self):
        """S3 equalises the spatial pattern while preserving the national total.

        v5 (P0-2): the plant-level cap is kappa * (A_bio*share_bio + A_wst*share_wst),
        so S3 (a) redistributes each period's national allocation across provinces by
        installed capacity and (b) replaces the accessibility shares with capacity
        shares. The 2025 base year is untouched.
        """
        original = self.data
        equalized = apply_scenario_modifications(
            copy.deepcopy(original), "S3_all_spatial_equalized"
        )
        provinces = sorted(original["plants"]["province"].astype(str).unique())

        def allocation_total(frame, year):
            return sum(
                float(frame["af_alloc_bio"].get((p, year), 0.0))
                + float(frame["af_alloc_wst"].get((p, year), 0.0))
                for p in provinces
            )

        for year in config.T_LIST:
            self.assertAlmostEqual(
                allocation_total(original, year),
                allocation_total(equalized, year),
                places=6,
            )
        # 2025 must be preserved exactly (both the province allocation and the shares)
        for key, value in original["af_alloc_bio"].items():
            if int(key[1]) == 2025:
                self.assertAlmostEqual(equalized["af_alloc_bio"][key], value, places=9)
        for key, value in original["af_alloc_wst"].items():
            if int(key[1]) == 2025:
                self.assertAlmostEqual(equalized["af_alloc_wst"][key], value, places=9)

        # accessibility shares are replaced by within-province capacity shares
        plants = equalized["plants"].set_index("plant_id")
        for province, members in plants.groupby("province"):
            total_capacity = float(members["capacity"].astype(float).sum())
            for plant_id, row in members.iterrows():
                expected = float(row["capacity"]) / total_capacity
                self.assertAlmostEqual(
                    equalized["af_share_bio"][int(plant_id)], expected, places=9
                )
                self.assertAlmostEqual(
                    equalized["af_share_wst"][int(plant_id)], expected, places=9
                )

        self.assertEqual(
            equalized["_af_plant_access_mode"],
            "capacity_share_within_province_and_equalised_province_allocation",
        )

    def test_storage_distance_stress_filters_direct_routes(self):
        stressed = apply_scenario_modifications(
            copy.deepcopy(self.data), "S4_storage_300km"
        )
        distances = [
            distance
            for routes in stressed["plant_storage"].values()
            for _, distance, _ in routes
        ]
        self.assertLessEqual(max(distances), 300.0)
        self.assertLess(
            stressed["_plant_sink_pairs_after_filter"],
            stressed["_plant_sink_pairs_before_filter"],
        )

    def test_active_builder_contains_only_final_endogenous_modules(self):
        model = V4Model(copy.deepcopy(self.data), config)
        instance = model.build()
        variable_names = {
            component.local_name
            for component in instance.component_objects(Var, active=True)
        }
        expected_variables = {
            "y", "r", "close", "u",
            "af_supply", "k_af", "af_add",
            "z", "k_ccs", "ccs_new_design", "captured",
            "f_p_dsa", "f_p_eor",
            "co2_fuel", "co2_process", "co2_total", "co2_net", "slack",
        }
        if model.regional_demand_enabled:
            expected_variables.add("f_dem")
        self.assertEqual(variable_names, expected_variables)
        for plant_id in model.I:
            self.assertTrue(instance.y[plant_id, 0].fixed)
            self.assertTrue(instance.u[plant_id, 0].fixed)

    def test_default_emission_constraints_exclude_intermediate_milestones(self):
        model = V4Model(copy.deepcopy(self.data), config)
        instance = model.build()
        self.assertTrue(hasattr(instance, "cumulative_budget"))
        self.assertTrue(hasattr(instance, "terminal_emission_cap"))
        self.assertEqual(len(instance.milestone), 0)
        self.assertAlmostEqual(
            model._cumulative_target,
            config.CARBON_BUDGET_CASES["B40"]["cumulative_budget_kt_year"],
        )

    def test_ccs_size_gate_persists_from_2035_onward(self):
        model = V4Model(copy.deepcopy(self.data), config)
        instance = model.build()
        small_plants = [
            plant_id
            for plant_id in model.I
            if model.cap[plant_id]
            < config.SAME_SITE_RENEWAL_MIN_CAPACITY_TD
            * config.CAPACITY_T_DAY_TO_KT_YR
        ]
        self.assertTrue(small_plants)
        for plant_id in small_plants:
            for period_idx, year in enumerate(model.years):
                if year >= 2035:
                    self.assertTrue(instance.z[plant_id, period_idx].fixed)
                    self.assertEqual(instance.z[plant_id, period_idx].value, 0)

    def test_same_site_renewal_does_not_force_operation_to_2060(self):
        model = V4Model(copy.deepcopy(self.data), config)
        instance = model.build()
        self.assertTrue(hasattr(instance, "same_site_renewal_eligibility"))
        self.assertTrue(hasattr(instance, "at_most_one_same_site_renewal"))
        self.assertFalse(hasattr(instance, "rebuilt_asset_persists"))

    def test_capacity_counterfactual_requires_complete_binary_turnover_path(self):
        reference = {
            "plants": {
                "1": {
                    "y": {"2025": 1, "2030": 0},
                    "r": {"2025": 0, "2030": 0},
                },
                "2": {
                    "y": {"2025": 1, "2030": 1},
                    "r": {"2025": 0, "2030": 1},
                },
            }
        }
        path = extract_capacity_turnover_path(reference, [1, 2], [2025, 2030])
        self.assertEqual(path[("y", 1, 1)], 0)
        self.assertEqual(path[("r", 2, 1)], 1)
        self.assertEqual(len(path), 8)

        with_dispatch = copy.deepcopy(reference)
        for record in with_dispatch["plants"].values():
            record["u"] = {"2025": 0.5, "2030": 0.2}
        path = extract_capacity_turnover_path(
            with_dispatch, [1, 2], [2025, 2030], include_utilization=True
        )
        self.assertAlmostEqual(path[("u", 1, 0)], 0.5)
        self.assertEqual(len(path), 12)

        incomplete = copy.deepcopy(reference)
        del incomplete["plants"]["2"]["r"]["2030"]
        with self.assertRaises(CapacityPathError):
            extract_capacity_turnover_path(incomplete, [1, 2], [2025, 2030])

        nonbinary = copy.deepcopy(reference)
        nonbinary["plants"]["1"]["y"]["2030"] = 0.4
        with self.assertRaises(CapacityPathError):
            extract_capacity_turnover_path(nonbinary, [1, 2], [2025, 2030])

    def test_capacity_counterfactual_accepts_bounded_time_limit_incumbent(self):
        validate_reference_incumbent(
            {
                "status": "timeLimit",
                "solver": {
                    "status": "timeLimit",
                    "objective_value": 123.0,
                    "objective_bound": 120.0,
                    "mip_gap": 0.025,
                    "solution_count": 2,
                },
            }
        )

        invalid_references = [
            {
                "status": "infeasible",
                "solver": {"objective_value": 123.0, "solution_count": 1},
            },
            {
                "status": "timeLimit",
                "solver": {"objective_value": 123.0, "solution_count": 0},
            },
            {
                "status": "timeLimit",
                "solver": {"objective_value": float("nan"), "solution_count": 1},
            },
        ]
        for reference in invalid_references:
            with self.subTest(reference=reference):
                with self.assertRaises(CapacityPathError):
                    validate_reference_incumbent(reference)

    def test_dispatch_preflight_accepts_only_numerical_demand_gap_reachable_by_band(self):
        wrapper = SimpleNamespace(
            I=[1, 2],
            years=[2025, 2030],
            cap={1: 1_000_000.0, 2: 1_000_000.0},
            demand_path={2025: 1000.0, 2030: 1000.0},
            clinker_ratio_path={2025: 1.0, 2030: 1.0},
            config=SimpleNamespace(
                MIN_OPERATING_UTILIZATION=0.40,
                PLANT_FIXED_OPERATING_COST=53.2,
            ),
        )
        path = {
            ("y", 1, 0): 1, ("r", 1, 0): 0, ("u", 1, 0): 0.5,
            ("y", 2, 0): 1, ("r", 2, 0): 0, ("u", 2, 0): 0.5,
            ("y", 1, 1): 0, ("r", 1, 1): 0, ("u", 1, 1): 0.0,
            ("y", 2, 1): 1, ("r", 2, 1): 1, ("u", 2, 1): 0.99999999,
        }
        _, _, report = _reference_dispatch_preflight(
            wrapper,
            path,
            dispatch_band_tolerance=DISPATCH_BAND_TOLERANCE,
            reference_repair_tolerance=DISPATCH_BAND_TOLERANCE,
        )
        self.assertAlmostEqual(report["max_abs_raw_demand_gap_kt"], 0.01, places=6)
        self.assertEqual(
            report["checks"]["reference_demand_balance"],
            "PASS_WITHIN_DECLARED_NUMERICAL_GUARD",
        )

        materially_unbalanced = dict(path)
        materially_unbalanced[("u", 2, 1)] = 0.999999
        with self.assertRaises(CapacityPathError):
            _reference_dispatch_preflight(
                wrapper,
                materially_unbalanced,
                dispatch_band_tolerance=DISPATCH_BAND_TOLERANCE,
                reference_repair_tolerance=DISPATCH_BAND_TOLERANCE,
            )

    def test_near_optimal_identity_builds_cost_cap_and_unfixed_path_objective(self):
        years = [2025, 2030, 2060]
        plants = {
            "1": {
                "y": {"2025": 1, "2030": 1, "2060": 0},
                "r": {"2025": 0, "2030": 0, "2060": 0},
                "z": {"2025": 0, "2030": 0, "2060": 0},
            },
            "2": {
                "y": {"2025": 1, "2030": 0, "2060": 1},
                "r": {"2025": 0, "2030": 0, "2060": 1},
                "z": {"2025": 0, "2030": 0, "2060": 1},
            },
        }
        reference = {
            "status": "optimal",
            "scenario": "S1_baseline",
            "demand_scenario": "d_medium",
            "carbon_budget_case": "B40",
            "cost_boundary": "incremental_mitigation",
            "include_carbon_cost_in_objective": False,
            "include_full_fuel_cost_in_objective": False,
            "solver": {
                "objective_value": 1000.0,
                "solution_count": 1,
            },
            "plants": plants,
        }
        model = ConcreteModel()
        model.I = RangeSet(1, 2)
        model.T = RangeSet(0, 2)
        model.y = Var(model.I, model.T, bounds=(0, 1))
        model.total_cost = Objective(
            expr=100.0 + sum(model.y[i, t] for i in model.I for t in model.T)
        )
        wrapper = SimpleNamespace(
            model=model,
            I=[1, 2],
            T=[0, 1, 2],
            years=years,
            cap={1: 10.0, 2: 20.0},
            period_weight={2025: 2.5, 2030: 5.0, 2060: 2.5},
            demand_scenario="d_medium",
            config=SimpleNamespace(
                CARBON_BUDGET_CASE="B40",
                COST_BOUNDARY="incremental_mitigation",
                INCLUDE_CARBON_COST_IN_OBJECTIVE=False,
                INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE=False,
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reference.json"
            path.write_text(json.dumps(reference), encoding="utf-8")
            study = configure_near_optimal_identity(
                wrapper,
                active_scenario="S1_baseline",
                identity_reference_path=path,
                cost_reference_path=path,
                cost_tolerance=0.001,
                direction="closest",
                scope="full_path",
            )

        self.assertFalse(model.total_cost.active)
        self.assertTrue(model.near_optimal_identity_objective.active)
        self.assertFalse(any(model.y[i, t].fixed for i in model.I for t in model.T))
        self.assertAlmostEqual(study["public"]["cost_cap_kCNY"], 1002.0)
        for i in model.I:
            for t in model.T:
                model.y[i, t].set_value(plants[str(i)]["y"][str(years[t])])
        self.assertAlmostEqual(value(model.near_optimal_identity_distance), 0.0)
        self.assertEqual(len(study["mip_start"]), 18)

    def test_near_optimal_tiebreak_fallback_fixes_phase_one_binary_path(self):
        model = ConcreteModel()
        model.I = RangeSet(1, 2)
        model.T = RangeSet(0, 1)
        for name in ("y", "r", "z"):
            setattr(model, name, Var(model.I, model.T, within=Binary))
        wrapper = SimpleNamespace(model=model)
        start = {
            f"{name}({plant_id}_{period})": float((plant_id + period) % 2)
            for name in ("y", "r", "z")
            for plant_id in model.I
            for period in model.T
        }
        fixed = _fix_phase_one_binary_path(wrapper, start)
        self.assertEqual(fixed, 12)
        for name in ("y", "r", "z"):
            component = getattr(model, name)
            for plant_id in model.I:
                for period in model.T:
                    self.assertTrue(component[plant_id, period].fixed)
                    self.assertEqual(
                        component[plant_id, period].value,
                        int(start[f"{name}({plant_id}_{period})"]),
                    )

    def test_ccs_additions_have_fifteen_year_operating_commitment(self):
        self.assertEqual(config.CCS_MIN_OPERATING_YEARS, 15)
        self.assertEqual(
            config.CCS_TERMINAL_COMMITMENT_MODE,
            "continue_beyond_horizon",
        )
        model = V4Model(copy.deepcopy(self.data), config)
        instance = model.build()
        plant_id = model.I[0]
        year_to_period = {year: t for t, year in enumerate(model.years)}

        start = year_to_period[2045]
        for year in (2050, 2055, 2060):
            self.assertIn(
                (plant_id, start, year_to_period[year]),
                instance.ccs_minimum_operating_commitment,
            )

        start = year_to_period[2050]
        self.assertIn(
            (plant_id, start, year_to_period[2060]),
            instance.ccs_minimum_operating_commitment,
        )


if __name__ == "__main__":
    unittest.main()
