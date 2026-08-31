"""Final plant-level cement capacity and decarbonization optimization model.

Endogenous decisions are limited to capacity operation, same-site capacity
renewal, phaseout, AF allocation and capacity, commercial CCS, and direct
plant-to-storage flows. The legacy variable name ``r``/``rebuild`` denotes a
brownfield renewal or replacement investment at the incumbent site, not the
physical restoration of the original kiln. ARM, energy efficiency, and the
national clinker ratio are external paths.
"""

from __future__ import annotations

import os
import tempfile
import time

import numpy as np
import pandas as pd
from pyomo.environ import (
    Binary,
    ConcreteModel,
    Constraint,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
    value,
)


class V4Model:
    """Final v4 MILP used by the paper scenarios."""

    def __init__(self, data, config):
        self.data = data
        self.config = config
        self.demand_scenario = str(config.DEMAND_SCENARIO).lower()
        if self.demand_scenario not in data.get("demand", {}):
            raise ValueError(
                f"Demand scenario {self.demand_scenario!r} is unavailable; "
                f"loaded scenarios are {sorted(data.get('demand', {}))}"
            )
        self.demand_path = data["demand"][self.demand_scenario]
        self.model = None
        self._prepare_data()

    def _prepare_data(self):
        cfg = self.config
        plants = self.data["plants"].copy()
        plants["plant_id"] = plants["plant_id"].astype(int)
        p = plants.set_index("plant_id")
        self.plants = plants
        self.I = plants["plant_id"].tolist()
        self.T = list(range(len(cfg.T_LIST)))
        self.years = list(cfg.T_LIST)
        self.P = sorted(plants["province"].astype(str).unique())
        self.cap = (pd.to_numeric(p["capacity"], errors="coerce") * cfg.CAPACITY_T_DAY_TO_KT_YR).to_dict()
        self.province_map = p["province"].astype(str).to_dict()
        self.lon = p["longitude"].to_dict()
        self.lat = p["latitude"].to_dict()
        default_year = int(cfg.PLANT_DEFAULT_COMMISSION_YEAR)
        commissioning = pd.to_numeric(p.get("commission_year"), errors="coerce")
        self.commission_year = {
            i: int(commissioning.get(i)) if pd.notna(commissioning.get(i)) else default_year
            for i in self.I
        }
        self.emission_factors = self.data["plant_emission_factors"]
        self.baseyear_utilization = {
            int(i): float(v) for i, v in self.data["baseyear_utilization"].items()
        }
        self.baseyear_af_supply = {
            int(i): float(v) for i, v in self.data["baseyear_af_supply_ktce"].items()
        }
        self.plant_af_access = self.data["plant_af_access_ktce"]
        self.province_af_pool = self.data["province_af_pool_ktce"]
        self.arm_path = self.data["process_adjustment"]
        self.ee_path = {int(y): float(v) for y, v in self.data["ee_path"].items()}
        self.clinker_ratio_path = {
            int(y): float(v) for y, v in self.data["national_clinker_ratio_path"].items()
        }
        self.period_weight = {
            int(y): float(cfg.PERIOD_WEIGHTS[int(y)]) for y in self.years
        }

        storage = self.data["storage"].copy()
        storage["storage_idx"] = storage["storage_idx"].astype(int)
        self.storage = storage
        self.storage_by_idx = storage.set_index("storage_idx")
        self.is_offshore = self.storage_by_idx["is_offshore"].astype(bool).to_dict()

        self.ps_dsa = []
        self.ps_eor = []
        self.route_distance = {}
        for plant_id, routes in self.data.get("plant_storage", {}).items():
            for storage_idx, distance, sink_type in routes:
                pair = (int(plant_id), int(storage_idx))
                self.route_distance[(pair[0], pair[1], str(sink_type))] = float(distance)
                if str(sink_type).lower() == "dsa":
                    self.ps_dsa.append(pair)
                elif str(sink_type).lower() == "eor":
                    self.ps_eor.append(pair)
        self.ps_dsa = sorted(set(self.ps_dsa))
        self.ps_eor = sorted(set(self.ps_eor))

        capture_eff = float(cfg.CCS_PARAMS.get("capture_efficiency", 0.90))
        self.plant_big_m = {}
        self.plant_ccs_cost_multiplier = {}
        size_classes = list(cfg.CCS_COST_SCALING_PARAMS.get("plant_size_classes", []))
        for i in self.I:
            ef = self.emission_factors[i]
            maximum = max(
                capture_eff * self.cap[i] * (float(ef["proc_ef"]) + float(ef["fuel_ef"])) * 1.05,
                1.0,
            )
            self.plant_big_m[i] = maximum
            scale_10kt = maximum / 10.0
            multiplier = 1.0
            for cls in size_classes:
                threshold = cls.get("max_10kt")
                multiplier = float(cls.get("multiplier", 1.0))
                if threshold is None or scale_10kt <= float(threshold):
                    break
            self.plant_ccs_cost_multiplier[i] = multiplier

        lifetime = int(cfg.PLANT_LIFETIME_YEARS)
        base_year = int(self.years[0])
        self.effective_commission_year = {
            i: max(self.commission_year[i], base_year - lifetime) for i in self.I
        }
        self.expiry_year = {
            i: self.effective_commission_year[i] + lifetime for i in self.I
        }
        self.same_site_renewal_period = {}
        min_renewal_cap = (
            float(cfg.SAME_SITE_RENEWAL_MIN_CAPACITY_TD)
            * cfg.CAPACITY_T_DAY_TO_KT_YR
        )
        for i in self.I:
            eligible = [
                t for t, year in enumerate(self.years)
                if year > self.expiry_year[i] and self.cap[i] >= min_renewal_cap
            ]
            self.same_site_renewal_period[i] = eligible[0] if eligible else None

        self._observed_pilot_enabled = bool(cfg.OBSERVED_PILOT_CCS_ENABLED)
        self._observed_pilot_include_in_targets = bool(
            cfg.OBSERVED_PILOT_CCS_INCLUDE_IN_TARGET_ACCOUNTING
        )
        self._observed_pilot_persistence = str(cfg.OBSERVED_PILOT_CCS_PERSISTENCE)
        self._observed_pilot_scale_kt = {
            int(i): 10.0 * float(project.get("scale", 0.0))
            for i, project in cfg.INITIAL_CCS_PROJECTS.items()
            if int(i) in self.I
        }
        self._observed_pilot_installed_year = {
            int(i): int(project.get("installed_year", cfg.BASE_YEAR))
            for i, project in cfg.INITIAL_CCS_PROJECTS.items()
            if int(i) in self.I
        }

    def build(self):
        m = ConcreteModel()
        m.I = Set(initialize=self.I)
        m.T = Set(initialize=self.T, ordered=True)
        m.P = Set(initialize=self.P)
        m.S = Set(initialize=self.storage["storage_idx"].tolist())
        m.PS_dsa = Set(initialize=self.ps_dsa, dimen=2)
        m.PS_eor = Set(initialize=self.ps_eor, dimen=2)

        m.y = Var(m.I, m.T, within=Binary)
        m.r = Var(m.I, m.T, within=Binary)
        m.close = Var(m.I, m.T, within=NonNegativeReals, bounds=(0, 1))
        m.u = Var(m.I, m.T, within=NonNegativeReals, bounds=(0, 1))

        m.af_supply = Var(m.I, m.T, within=NonNegativeReals)
        m.k_af = Var(m.I, m.T, within=NonNegativeReals)
        m.af_add = Var(m.I, m.T, within=NonNegativeReals)

        m.z = Var(m.I, m.T, within=Binary)
        m.k_ccs = Var(m.I, m.T, within=NonNegativeReals)
        m.ccs_new_design = Var(m.I, m.T, within=NonNegativeReals)
        m.captured = Var(m.I, m.T, within=NonNegativeReals)
        m.f_p_dsa = Var(m.PS_dsa, m.T, within=NonNegativeReals)
        m.f_p_eor = Var(m.PS_eor, m.T, within=NonNegativeReals)

        m.co2_fuel = Var(m.I, m.T, within=NonNegativeReals)
        m.co2_process = Var(m.I, m.T, within=NonNegativeReals)
        m.co2_total = Var(m.I, m.T, within=NonNegativeReals)
        m.co2_net = Var(m.I, m.T, within=NonNegativeReals)
        m.slack = Var(m.T, within=NonNegativeReals)

        self.model = m
        self._production_constraints(m)
        self._af_constraints(m)
        self._emission_constraints(m)
        self._ccs_constraints(m)
        self._demand_and_target_constraints(m)
        self._objective(m)
        return m

    def _production_constraints(self, m):
        cfg = self.config
        after = [t for t in self.T if t > 0]
        u_min = float(cfg.MIN_OPERATING_UTILIZATION)
        ramp = float(cfg.MAX_UTILIZATION_CHANGE_PER_PERIOD)

        m.util_upper = Constraint(m.I, m.T, rule=lambda mm, i, t: mm.u[i, t] <= mm.y[i, t])

        def utilization_lower(mm, i, t):
            if t == 0:
                return Constraint.Skip
            return mm.u[i, t] >= u_min * mm.y[i, t]
        m.util_lower = Constraint(m.I, m.T, rule=utilization_lower)

        for i in self.I:
            m.y[i, 0].fix(1)
            m.u[i, 0].fix(self.baseyear_utilization[i])
            m.close[i, 0].fix(0)

        m.operating_continuity = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.y[i, t] <= mm.y[i, t - 1] + mm.r[i, t],
        )
        m.same_site_renewal_requires_prior_operation = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.r[i, t] <= mm.y[i, t - 1],
        )

        def same_site_renewal_eligibility(mm, i, t):
            if self.same_site_renewal_period[i] == t:
                return Constraint.Skip
            return mm.r[i, t] == 0
        m.same_site_renewal_eligibility = Constraint(
            m.I, m.T, rule=same_site_renewal_eligibility
        )
        m.at_most_one_same_site_renewal = Constraint(
            m.I, rule=lambda mm, i: sum(mm.r[i, t] for t in mm.T) <= 1
        )

        def retirement(mm, i, t):
            if self.years[t] <= self.expiry_year[i]:
                return Constraint.Skip
            return mm.y[i, t] <= sum(mm.r[i, tau] for tau in self.T if tau <= t)
        m.natural_retirement = Constraint(m.I, m.T, rule=retirement)

        # Renewal restores technical availability after the original line
        # expires. It does not force production through 2060: the ordinary
        # operating-continuity constraint permits a later one-way exit.

        m.close_event = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.close[i, t] >= mm.y[i, t - 1] - mm.y[i, t],
        )
        m.close_prior_operation = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.close[i, t] <= mm.y[i, t - 1],
        )
        m.close_requires_shutdown = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.close[i, t] <= 1 - mm.y[i, t],
        )
        m.util_ramp_up = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.u[i, t] - mm.u[i, t - 1]
            <= ramp + (1 - mm.y[i, t - 1]) + mm.r[i, t],
        )
        m.util_ramp_down = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.u[i, t - 1] - mm.u[i, t]
            <= ramp + (1 - mm.y[i, t]),
        )

    def _af_constraints(self, m):
        cfg = self.config
        tce = float(cfg.TCE_PER_T_CLINKER)
        after = [t for t in self.T if t > 0]

        def engineering_actual(mm, i, t):
            cap = float(cfg.AF_ENGINEERING_TSR_PATH[self.years[t]])
            return mm.af_supply[i, t] <= cap * self.cap[i] * tce * mm.u[i, t]
        m.af_engineering_actual = Constraint(m.I, m.T, rule=engineering_actual)

        def engineering_design(mm, i, t):
            cap = float(cfg.AF_ENGINEERING_TSR_PATH[self.years[t]])
            return mm.k_af[i, t] <= cap * self.cap[i] * tce * mm.y[i, t]
        m.af_engineering_design = Constraint(m.I, m.T, rule=engineering_design)
        m.af_within_design = Constraint(
            m.I, m.T, rule=lambda mm, i, t: mm.af_supply[i, t] <= mm.k_af[i, t]
        )

        def plant_access(mm, i, t):
            return mm.af_supply[i, t] <= float(
                self.plant_af_access.get((i, self.years[t]), 0.0)
            )
        m.af_plant_access = Constraint(m.I, m.T, rule=plant_access)

        province_members = {
            p: [i for i in self.I if self.province_map[i] == p] for p in self.P
        }
        m.af_province_pool = Constraint(
            m.P,
            m.T,
            rule=lambda mm, p, t: sum(mm.af_supply[i, t] for i in province_members[p])
            <= float(self.province_af_pool.get((p, self.years[t]), 0.0)),
        )

        for i in self.I:
            baseline = float(self.baseyear_af_supply.get(i, 0.0))
            m.af_supply[i, 0].fix(baseline)
            m.k_af[i, 0].fix(baseline)
            m.af_add[i, 0].fix(0)

        def af_capacity_persistence(mm, i, t):
            maximum = self.cap[i] * tce * float(cfg.AF_MAX_PER_PLANT)
            return mm.k_af[i, t] >= mm.k_af[i, t - 1] - maximum * (1 - mm.y[i, t])
        m.af_capacity_persistence = Constraint(m.I, after, rule=af_capacity_persistence)
        m.af_capacity_addition = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.af_add[i, t] >= mm.k_af[i, t] - mm.k_af[i, t - 1],
        )

    def _emission_constraints(self, m):
        cfg = self.config
        tce = float(cfg.TCE_PER_T_CLINKER)
        beta_af = float(cfg.BETA_AF)

        def fuel_emission(mm, i, t):
            year = self.years[t]
            ee = float(self.ee_path[year])
            fuel_ef = float(self.emission_factors[i]["fuel_ef"])
            clinker_equivalent_af = mm.af_supply[i, t] / tce
            return mm.co2_fuel[i, t] == fuel_ef * (1 - ee) * (
                self.cap[i] * mm.u[i, t] - beta_af * clinker_equivalent_af
            )
        m.fuel_emission = Constraint(m.I, m.T, rule=fuel_emission)

        def process_emission(mm, i, t):
            year = self.years[t]
            arm = float(self.arm_path.get((self.province_map[i], year), 0.0))
            process_ef = float(self.emission_factors[i]["proc_ef"])
            return mm.co2_process[i, t] == self.cap[i] * process_ef * (1 - arm) * mm.u[i, t]
        m.process_emission = Constraint(m.I, m.T, rule=process_emission)
        m.total_emission = Constraint(
            m.I,
            m.T,
            rule=lambda mm, i, t: mm.co2_total[i, t]
            == mm.co2_fuel[i, t] + mm.co2_process[i, t],
        )

    def _ccs_constraints(self, m):
        cfg = self.config
        after = [t for t in self.T if t > 0]
        efficiency = float(cfg.CCS_PARAMS.get("capture_efficiency", 0.90))
        min_design = float(cfg.CCS_PARAMS.get("min_active_design_kt", 30.0))

        m.ccs_operating = Constraint(m.I, m.T, rule=lambda mm, i, t: mm.z[i, t] <= mm.y[i, t])
        m.ccs_design_upper = Constraint(
            m.I,
            m.T,
            rule=lambda mm, i, t: mm.k_ccs[i, t] <= self.plant_big_m[i] * mm.z[i, t],
        )
        m.ccs_design_lower = Constraint(
            m.I,
            m.T,
            rule=lambda mm, i, t: mm.k_ccs[i, t]
            >= min(min_design, self.plant_big_m[i]) * mm.z[i, t],
        )
        m.ccs_status_persistence = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.z[i, t] >= mm.z[i, t - 1] - (1 - mm.y[i, t]),
        )
        m.ccs_capacity_persistence = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.k_ccs[i, t]
            >= mm.k_ccs[i, t - 1] - self.plant_big_m[i] * (1 - mm.y[i, t]),
        )

        min_operating_years = int(cfg.CCS_MIN_OPERATING_YEARS)
        if min_operating_years < 0:
            raise ValueError("CCS_MIN_OPERATING_YEARS must be non-negative")
        commitment_periods = [
            (i, t, tau)
            for i in self.I
            for t in after
            for tau in self.T
            if t < tau
            and self.years[tau] <= self.years[t] + min_operating_years
        ]
        m.ccs_minimum_operating_commitment = Constraint(
            commitment_periods,
            rule=lambda mm, i, t, tau: mm.k_ccs[i, tau]
            >= mm.k_ccs[i, t] - mm.k_ccs[i, t - 1],
        )
        for i in self.I:
            m.z[i, 0].fix(0)
            m.k_ccs[i, 0].fix(0)
            m.ccs_new_design[i, 0].fix(0)

        m.ccs_design_addition = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.ccs_new_design[i, t]
            >= mm.k_ccs[i, t] - mm.k_ccs[i, t - 1],
        )
        m.capture_by_design = Constraint(
            m.I, m.T, rule=lambda mm, i, t: mm.captured[i, t] <= mm.k_ccs[i, t]
        )
        m.capture_by_emission = Constraint(
            m.I,
            m.T,
            rule=lambda mm, i, t: mm.captured[i, t] <= efficiency * mm.co2_total[i, t],
        )
        m.capture_rollout = Constraint(
            m.I,
            m.T,
            rule=lambda mm, i, t: mm.captured[i, t]
            <= float(cfg.CCS_SCALE_LIMITS[self.years[t]]) * mm.co2_total[i, t],
        )
        m.capture_minimum_load = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.captured[i, t]
            >= float(cfg.CCS_MIN_CAPTURE_LOAD) * mm.k_ccs[i, t],
        )

        gate = cfg.CCS_ROLLOUT_PARAMS.get("min_capacity_td_by_period", {})
        for i in self.I:
            for t in self.T:
                minimum = gate.get(self.years[t])
                if minimum is not None and self.cap[i] < float(minimum) * cfg.CAPACITY_T_DAY_TO_KT_YR:
                    m.z[i, t].fix(0)

        if self.data.get("_no_ccs", False):
            for i in self.I:
                for t in self.T:
                    m.z[i, t].fix(0)

        dsa_by_plant = {i: [] for i in self.I}
        eor_by_plant = {i: [] for i in self.I}
        for i, s in self.ps_dsa:
            dsa_by_plant[i].append(s)
        for i, s in self.ps_eor:
            eor_by_plant[i].append(s)

        def plant_flow_balance(mm, i, t):
            return (
                sum(mm.f_p_dsa[i, s, t] for s in dsa_by_plant[i])
                + sum(mm.f_p_eor[i, s, t] for s in eor_by_plant[i])
                == mm.captured[i, t]
            )
        m.plant_flow_balance = Constraint(m.I, m.T, rule=plant_flow_balance)

        mt_to_kt = float(cfg.STORAGE_MT_TO_KT)
        rate_scale = float(cfg.STORAGE_RATE_SCALE)
        capacity_scale = float(cfg.STORAGE_CUMULATIVE_SCALE)
        dsa_rate = (self.storage_by_idx["dsa_rate"] * mt_to_kt * rate_scale).to_dict()
        eor_rate = (self.storage_by_idx["eor_rate"] * mt_to_kt * rate_scale).to_dict()
        dsa_capacity = (self.storage_by_idx["dsa_capacity"] * mt_to_kt * capacity_scale).to_dict()
        eor_capacity = (self.storage_by_idx["eor_capacity"] * mt_to_kt * capacity_scale).to_dict()
        dsa_by_sink = {s: [] for s in set(s for _, s in self.ps_dsa)}
        eor_by_sink = {s: [] for s in set(s for _, s in self.ps_eor)}
        for i, s in self.ps_dsa:
            dsa_by_sink[s].append(i)
        for i, s in self.ps_eor:
            eor_by_sink[s].append(i)

        if bool(cfg.USE_STORAGE_RATE_CONSTRAINT):
            m.dsa_rate_cap = Constraint(
                list(dsa_by_sink),
                m.T,
                rule=lambda mm, s, t: sum(mm.f_p_dsa[i, s, t] for i in dsa_by_sink[s])
                <= float(dsa_rate.get(s, 0.0)),
            )
            m.eor_rate_cap = Constraint(
                list(eor_by_sink),
                m.T,
                rule=lambda mm, s, t: sum(mm.f_p_eor[i, s, t] for i in eor_by_sink[s])
                <= float(eor_rate.get(s, 0.0)),
            )

        def dsa_cumulative(mm, s, t):
            return sum(
                self.period_weight[self.years[tau]]
                * sum(mm.f_p_dsa[i, s, tau] for i in dsa_by_sink[s])
                for tau in self.T if tau <= t
            ) <= float(dsa_capacity.get(s, 0.0))
        m.dsa_cumulative_cap = Constraint(list(dsa_by_sink), m.T, rule=dsa_cumulative)

        def eor_cumulative(mm, s, t):
            return sum(
                self.period_weight[self.years[tau]]
                * sum(mm.f_p_eor[i, s, tau] for i in eor_by_sink[s])
                for tau in self.T if tau <= t
            ) <= float(eor_capacity.get(s, 0.0))
        m.eor_cumulative_cap = Constraint(list(eor_by_sink), m.T, rule=eor_cumulative)

        m.net_emission = Constraint(
            m.I,
            m.T,
            rule=lambda mm, i, t: mm.co2_net[i, t] == mm.co2_total[i, t] - mm.captured[i, t],
        )

    def _demand_and_target_constraints(self, m):
        cfg = self.config

        def demand_balance(mm, t):
            year = self.years[t]
            target = float(self.demand_path[year]) * 1000.0 * self.clinker_ratio_path[year]
            return sum(self.cap[i] * mm.u[i, t] for i in self.I) == target
        m.demand_balance = Constraint(m.T, rule=demand_balance)

        mode = str(cfg.EMISSION_TARGET_MODE).lower()
        if mode not in {"cumulative_budget", "milestone", "both", "none"}:
            raise ValueError(f"Unknown emission target mode: {mode}")
        cumulative_enabled = mode in {"cumulative_budget", "both"}
        milestone_enabled = mode in {"milestone", "both"}

        baseyear_production = {
            i: self.cap[i] * self.baseyear_utilization[i] for i in self.I
        }
        total_baseyear_production = sum(baseyear_production.values())
        average_bau_ef = sum(
            baseyear_production[i]
            * (self.emission_factors[i]["proc_ef"] + self.emission_factors[i]["fuel_ef"])
            for i in self.I
        ) / max(total_baseyear_production, 1e-9)
        self._bau_emission_factor = average_bau_ef
        baseline_ratio = float(cfg.BASELINE_CLINKER_RATIO)
        self._bau_by_year = {
            year: float(self.demand_path[year]) * 1000.0 * baseline_ratio * average_bau_ef
            for year in self.years
        }
        self._cumulative_bau = sum(
            self.period_weight[year] * self._bau_by_year[year] for year in self.years
        )
        budget_case = str(cfg.CARBON_BUDGET_CASE).upper()
        budget_cases = dict(cfg.CARBON_BUDGET_CASES)
        if budget_case not in budget_cases:
            raise ValueError(
                f"Unknown carbon budget case {budget_case!r}; "
                f"expected one of {sorted(budget_cases)}"
            )
        budget = budget_cases[budget_case]
        reduction = float(budget["reference_reduction"])
        self._cumulative_target = float(budget["cumulative_budget_kt_year"])
        self._terminal_2060_cap = float(budget["terminal_2060_cap_kt"])
        if cumulative_enabled:
            m.cumulative_budget = Constraint(
                expr=sum(
                    self.period_weight[self.years[t]]
                    * sum(m.co2_net[i, t] for i in self.I)
                    for t in self.T
                )
                <= self._cumulative_target
            )
            terminal_t = self.years.index(2060)
            m.terminal_emission_cap = Constraint(
                expr=sum(m.co2_net[i, terminal_t] for i in self.I)
                <= self._terminal_2060_cap
            )

        milestones = {
            2030: float(cfg.MILESTONE_2030),
            2050: float(cfg.MILESTONE_2050),
            2060: float(cfg.MILESTONE_2060),
        }
        use_slack = bool(cfg.MILESTONE_USE_SLACK)

        def milestone(mm, t):
            year = self.years[t]
            if not milestone_enabled or year not in milestones:
                return Constraint.Skip
            rhs = milestones[year] * sum(mm.co2_net[i, 0] for i in self.I)
            if use_slack:
                rhs += mm.slack[t]
            return sum(mm.co2_net[i, t] for i in self.I) <= rhs
        m.milestone = Constraint(m.T, rule=milestone)
        if not (milestone_enabled and use_slack):
            m.zero_slack = Constraint(m.T, rule=lambda mm, t: mm.slack[t] == 0)

        self._emission_target_mode = mode
        self._cumulative_budget_enabled = cumulative_enabled
        self._cumulative_reduction_target = reduction
        self._carbon_budget_case = budget_case
        self._milestone_enabled = milestone_enabled
        self._milestones = milestones

    def _cost_components(self, mm, t):
        cfg = self.config
        year = self.years[t]
        weight = self.period_weight[year]
        tce = float(cfg.TCE_PER_T_CLINKER)
        ccs = cfg.CCS_PARAMS
        capex_multiplier = float(cfg.CCS_LEARNING_CURVE["investment_multiplier"][year])
        opex_multiplier = float(cfg.CCS_LEARNING_CURVE["om_multiplier"][year])
        offshore_pipeline = float(cfg.OFFSHORE_PARAMS.get("pipeline_cost_factor", 1.0))
        offshore_storage = float(cfg.OFFSHORE_PARAMS.get("storage_cost_factor", 1.0))

        ccs_capex = sum(
            float(ccs["capture_investment"])
            * capex_multiplier
            * self.plant_ccs_cost_multiplier[i]
            * mm.ccs_new_design[i, t]
            for i in self.I
        )
        ccs_opex = weight * float(ccs["capture_om"]) * opex_multiplier * sum(
            mm.captured[i, t] for i in self.I
        )
        same_site_renewal_capex = float(
            cfg.SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY
        ) * sum(
            self.cap[i] * mm.r[i, t] for i in self.I
        )
        early_retirement = sum(
            float(cfg.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY)
            * self.cap[i]
            * max(self.expiry_year[i] - year, 0)
            / max(float(cfg.PLANT_LIFETIME_YEARS), 1.0)
            * mm.close[i, t]
            for i in self.I
        )

        af_capex = float(cfg.AF_INVESTMENT) / tce * sum(mm.af_add[i, t] for i in self.I)
        af_opex = weight * float(cfg.AF_OM) / tce * sum(mm.af_supply[i, t] for i in self.I)
        coal_price = float(cfg.COAL_PRICE_SCHEDULE.get(year, cfg.COAL_PRICE))
        af_price = float(cfg.AF_FUEL_PRICE[year])
        af_fuel_delta = weight * (af_price - coal_price) * sum(
            mm.af_supply[i, t] for i in self.I
        )
        baseline_fuel = weight * coal_price * tce * sum(
            self.cap[i] * mm.u[i, t] for i in self.I
        )

        pipeline_unit = float(ccs["pipeline_investment"]) + float(ccs.get("pipeline_om", 0.0))
        transport = weight * (
            sum(
                mm.f_p_dsa[i, s, t]
                * self.route_distance[(i, s, "dsa")]
                * pipeline_unit
                * (offshore_pipeline if self.is_offshore.get(s, False) else 1.0)
                for i, s in self.ps_dsa
            )
            + sum(
                mm.f_p_eor[i, s, t]
                * self.route_distance[(i, s, "eor")]
                * pipeline_unit
                * (offshore_pipeline if self.is_offshore.get(s, False) else 1.0)
                for i, s in self.ps_eor
            )
        )
        dsa_storage = weight * float(ccs["dsa_cost"]) * sum(
            mm.f_p_dsa[i, s, t]
            * (offshore_storage if self.is_offshore.get(s, False) else 1.0)
            for i, s in self.ps_dsa
        )
        eor_storage = weight * float(ccs["eor_storage_cost"]) * sum(
            mm.f_p_eor[i, s, t]
            * (offshore_storage if self.is_offshore.get(s, False) else 1.0)
            for i, s in self.ps_eor
        )
        eor_credit = -weight * float(ccs["eor_revenue"]) * sum(
            mm.f_p_eor[i, s, t] for i, s in self.ps_eor
        )
        carbon = weight * float(self.data.get("_carbon_price", cfg.CARBON_PRICE)[year]) * sum(
            mm.co2_net[i, t] for i in self.I
        )
        slack = (
            weight * float(cfg.MILESTONE_SLACK_PENALTY) * mm.slack[t]
            if self._milestone_enabled and bool(cfg.MILESTONE_USE_SLACK)
            else 0.0
        )
        fuel = baseline_fuel + af_fuel_delta if bool(cfg.INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE) else af_fuel_delta
        components = {
            "ccs_capex": ccs_capex,
            "ccs_opex": ccs_opex,
            "same_site_renewal_capex": same_site_renewal_capex,
            "early_retirement": early_retirement,
            "af_capex": af_capex,
            "af_opex": af_opex,
            "fuel": fuel,
            "transport": transport,
            "dsa_storage": dsa_storage,
            "eor_storage": eor_storage,
            "eor_revenue_credit": eor_credit,
            "milestone_slack_penalty": slack,
        }
        if bool(cfg.INCLUDE_CARBON_COST_IN_OBJECTIVE):
            components["carbon"] = carbon
        diagnostics = {
            "fuel_baseline_coal": baseline_fuel,
            "af_fuel_delta": af_fuel_delta,
            "carbon": carbon,
        }
        return components, diagnostics

    def _objective(self, m):
        discount = {
            t: 1.0 / (1 + float(self.config.DISCOUNT_RATE)) ** (self.years[t] - self.years[0])
            for t in self.T
        }
        m.total_cost = Objective(
            expr=sum(
                discount[t] * sum(self._cost_components(m, t)[0].values()) for t in self.T
            ),
            sense=minimize,
        )

    def solve(self, solver=None, options=None, mip_start=None):
        import gurobipy as gp

        opts = dict(self.config.SOLVER_OPTIONS)
        if options:
            opts.update(options)
        self._solver_options = dict(opts)
        with tempfile.NamedTemporaryFile(suffix=".mps", delete=False) as file:
            mps_path = file.name
        print("  [solver] Writing final model to MPS...")
        self.model.write(mps_path, io_options={"symbolic_solver_labels": True})
        gm = gp.read(mps_path)
        applied_start = 0
        if mip_start:
            for variable_name, start_value in mip_start.items():
                variable = gm.getVarByName(str(variable_name))
                if variable is None:
                    continue
                try:
                    variable.Start = float(start_value)
                    applied_start += 1
                except (TypeError, ValueError):
                    continue
        self._last_mip_start_applied = applied_start
        for key, setting in opts.items():
            if key != "tee":
                gm.setParam(key, setting)
        gm.setParam("OutputFlag", 1 if opts.get("tee", False) else 0)
        gm.setParam("DualReductions", 0)
        gm.optimize()
        status_map = {
            2: "optimal",
            3: "infeasible",
            4: "infeasibleOrUnbounded",
            5: "unbounded",
            9: "timeLimit",
            11: "noSolution",
            13: "suboptimal",
        }
        status = status_map.get(gm.Status, "unknown")
        if gm.Status == 3:
            try:
                gm.computeIIS()
                gm.write(mps_path.replace(".mps", "_iis.ilp"))
            except Exception as exc:
                print(f"  IIS computation failed: {exc}")
        self._gm = gm
        self._solve_status = status
        os.unlink(mps_path)

        class Results:
            def __init__(self, current_status, objective):
                self.solver = type(
                    "SolverStatus",
                    (),
                    {"status": current_status, "termination_condition": current_status},
                )()
                self._objval = objective

        objective = gm.ObjVal if gm.SolCount > 0 else None
        return Results(status, objective)

    def _solution_value(self, name, *indices):
        variable_name = f"{name}(" + "_".join(str(index) for index in indices) + ")"
        variable = self._gm.getVarByName(variable_name)
        if variable is not None:
            return self._snap_utilization(name, float(variable.X))
        try:
            component = getattr(self.model, name)[indices]
            if component.fixed:
                return self._snap_utilization(name, float(value(component)))
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _snap_utilization(name, value):
        # Utilization residuals below the counterfactual dispatch band
        # (DISPATCH_BAND_TOLERANCE = 1e-5) are solver integer-tolerance noise
        # (e.g. u=4.45e-6 where y=0); snap them so every derived quantity and
        # downstream audit sees an exact zero.
        if name == "u" and abs(value) < 1e-5:
            return 0.0
        return value

    def _observed_pilot_capture(self, plant_id, t):
        if not self._observed_pilot_enabled:
            return 0.0
        scale = float(self._observed_pilot_scale_kt.get(int(plant_id), 0.0))
        if scale <= 0:
            return 0.0
        year = self.years[t]
        installed = self._observed_pilot_installed_year.get(int(plant_id), self.years[0])
        active = (
            year >= installed
            if self._observed_pilot_persistence == "installed_year_onward"
            else t == 0 and year >= installed
        )
        if not active:
            return 0.0
        return scale * self._solution_value("y", plant_id, t)

    def _numeric_cost_components(self, t):
        cfg = self.config
        year = self.years[t]
        weight = self.period_weight[year]
        tce = float(cfg.TCE_PER_T_CLINKER)
        ccs = cfg.CCS_PARAMS
        capex_multiplier = float(cfg.CCS_LEARNING_CURVE["investment_multiplier"][year])
        opex_multiplier = float(cfg.CCS_LEARNING_CURVE["om_multiplier"][year])
        offshore_pipeline = float(cfg.OFFSHORE_PARAMS.get("pipeline_cost_factor", 1.0))
        offshore_storage = float(cfg.OFFSHORE_PARAMS.get("storage_cost_factor", 1.0))

        ccs_capex = sum(
            float(ccs["capture_investment"])
            * capex_multiplier
            * self.plant_ccs_cost_multiplier[i]
            * self._solution_value("ccs_new_design", i, t)
            for i in self.I
        )
        commercial_capture = sum(self._solution_value("captured", i, t) for i in self.I)
        ccs_opex = weight * float(ccs["capture_om"]) * opex_multiplier * commercial_capture
        same_site_renewal_capex = float(
            cfg.SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY
        ) * sum(
            self.cap[i] * self._solution_value("r", i, t) for i in self.I
        )
        early_retirement = sum(
            float(cfg.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY)
            * self.cap[i]
            * max(self.expiry_year[i] - year, 0)
            / max(float(cfg.PLANT_LIFETIME_YEARS), 1.0)
            * self._solution_value("close", i, t)
            for i in self.I
        )
        af_add = sum(self._solution_value("af_add", i, t) for i in self.I)
        af_supply = sum(self._solution_value("af_supply", i, t) for i in self.I)
        af_capex = float(cfg.AF_INVESTMENT) / tce * af_add
        af_opex = weight * float(cfg.AF_OM) / tce * af_supply
        coal_price = float(cfg.COAL_PRICE_SCHEDULE.get(year, cfg.COAL_PRICE))
        af_price = float(cfg.AF_FUEL_PRICE[year])
        af_fuel_delta = weight * (af_price - coal_price) * af_supply
        production = sum(self.cap[i] * self._solution_value("u", i, t) for i in self.I)
        baseline_fuel = weight * coal_price * tce * production

        pipeline_unit = float(ccs["pipeline_investment"]) + float(ccs.get("pipeline_om", 0.0))
        transport = weight * (
            sum(
                self._solution_value("f_p_dsa", i, s, t)
                * self.route_distance[(i, s, "dsa")]
                * pipeline_unit
                * (offshore_pipeline if self.is_offshore.get(s, False) else 1.0)
                for i, s in self.ps_dsa
            )
            + sum(
                self._solution_value("f_p_eor", i, s, t)
                * self.route_distance[(i, s, "eor")]
                * pipeline_unit
                * (offshore_pipeline if self.is_offshore.get(s, False) else 1.0)
                for i, s in self.ps_eor
            )
        )
        dsa_storage = weight * float(ccs["dsa_cost"]) * sum(
            self._solution_value("f_p_dsa", i, s, t)
            * (offshore_storage if self.is_offshore.get(s, False) else 1.0)
            for i, s in self.ps_dsa
        )
        eor_storage = weight * float(ccs["eor_storage_cost"]) * sum(
            self._solution_value("f_p_eor", i, s, t)
            * (offshore_storage if self.is_offshore.get(s, False) else 1.0)
            for i, s in self.ps_eor
        )
        eor_credit = -weight * float(ccs["eor_revenue"]) * sum(
            self._solution_value("f_p_eor", i, s, t) for i, s in self.ps_eor
        )
        carbon = weight * float(self.data.get("_carbon_price", cfg.CARBON_PRICE)[year]) * sum(
            self._solution_value("co2_net", i, t) for i in self.I
        )
        slack = (
            weight * float(cfg.MILESTONE_SLACK_PENALTY) * self._solution_value("slack", t)
            if self._milestone_enabled and bool(cfg.MILESTONE_USE_SLACK)
            else 0.0
        )
        fuel = baseline_fuel + af_fuel_delta if bool(cfg.INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE) else af_fuel_delta
        components = {
            "ccs_capex": ccs_capex,
            "ccs_opex": ccs_opex,
            "same_site_renewal_capex": same_site_renewal_capex,
            "early_retirement": early_retirement,
            "af_capex": af_capex,
            "af_opex": af_opex,
            "fuel": fuel,
            "transport": transport,
            "dsa_storage": dsa_storage,
            "eor_storage": eor_storage,
            "eor_revenue_credit": eor_credit,
            "milestone_slack_penalty": slack,
        }
        if bool(cfg.INCLUDE_CARBON_COST_IN_OBJECTIVE):
            components["carbon"] = carbon
        diagnostics = {
            "fuel_baseline_coal": baseline_fuel,
            "af_fuel_delta": af_fuel_delta,
            "carbon": carbon,
            "arm_external_rate": np.mean([
                self.arm_path.get((province, year), 0.0) for province in self.P
            ]),
            "ee_external_rate": self.ee_path[year],
        }
        return components, diagnostics

    def get_results(self):
        status = getattr(self, "_solve_status", "unknown")
        if not hasattr(self, "_gm") or self._gm.SolCount <= 0:
            return {"status": status}

        cfg = self.config
        objective = float(self._gm.ObjVal)
        results = {
            "status": status,
            "model_protocol": "final_v4_endogenous_capacity_af_ccs_direct_storage",
            "total_cost": objective,
            "total_cost_kCNY": objective,
            "total_cost_CNY": objective * 1000.0,
            "cost_unit_note": "Model quantities are kt and unit costs are CNY/t; objective values are kCNY.",
            "cost_boundary": cfg.COST_BOUNDARY,
            "include_full_fuel_cost_in_objective": bool(cfg.INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE),
            "include_carbon_cost_in_objective": bool(cfg.INCLUDE_CARBON_COST_IN_OBJECTIVE),
            "demand_scenario": self.demand_scenario,
            "period_weights_years": dict(self.period_weight),
            "summary": {},
            "plants": {},
        }

        observed_projects = []
        for i in sorted(self._observed_pilot_scale_kt):
            observed_projects.append({
                "plant_id": i,
                "province": self.province_map[i],
                "installed_year": self._observed_pilot_installed_year[i],
                "reported_scale_kt_per_year": self._observed_pilot_scale_kt[i],
                "captured_2025_kt": self._observed_pilot_capture(i, 0),
                "operating_2025": True,
            })
        results["observed_initial_ccs_projects"] = {
            "enabled": self._observed_pilot_enabled,
            "treatment": "reported_demo_only_not_counted_as_permanent_mitigation",
            "persistence": self._observed_pilot_persistence,
            "include_in_target_accounting": self._observed_pilot_include_in_targets,
            "n_projects": len(observed_projects),
            "total_reported_scale_kt_per_year": sum(
                p["reported_scale_kt_per_year"] for p in observed_projects
            ),
            "total_captured_2025_kt": sum(self._observed_pilot_capture(i, 0) for i in self.I),
            "projects": observed_projects,
        }

        tce = float(cfg.TCE_PER_T_CLINKER)
        total_capacity = sum(self.cap.values())
        province_capacity = {
            p: sum(self.cap[i] for i in self.I if self.province_map[i] == p) for p in self.P
        }
        for t, year in enumerate(self.years):
            y = {i: self._solution_value("y", i, t) for i in self.I}
            u = {i: self._solution_value("u", i, t) for i in self.I}
            z = {i: self._solution_value("z", i, t) for i in self.I}
            gross = sum(self._solution_value("co2_total", i, t) for i in self.I)
            net = sum(self._solution_value("co2_net", i, t) for i in self.I)
            capture = sum(self._solution_value("captured", i, t) for i in self.I)
            observed = sum(self._observed_pilot_capture(i, t) for i in self.I)
            production = sum(self.cap[i] * u[i] for i in self.I)
            operating_capacity = sum(self.cap[i] * y[i] for i in self.I)
            af_supply = sum(self._solution_value("af_supply", i, t) for i in self.I)
            fuel_energy = production * tce
            arm_average = sum(
                province_capacity[p] * float(self.arm_path.get((p, year), 0.0)) for p in self.P
            ) / max(sum(province_capacity.values()), 1e-9)
            results["summary"][year] = {
                "gross_co2_kt": gross,
                "net_co2_kt": net,
                "net_co2_commercial_kt": net,
                "captured_co2_kt": capture,
                "commercial_captured_co2_kt": capture,
                "observed_pilot_captured_co2_kt": observed,
                "reported_capture_including_nonverified_pilots_kt": capture + observed,
                "n_plants_operating": int(sum(round(v) for v in y.values())),
                "n_plants_positive_production": int(sum(v > 1e-8 for v in u.values())),
                "n_plants_ccs": int(sum(round(v) for v in z.values())),
                "n_plants_ccs_installed": int(sum(round(v) for v in z.values())),
                "n_plants_ccs_commercial": int(sum(round(v) for v in z.values())),
                "n_plants_ccs_observed_pilot": int(sum(self._observed_pilot_capture(i, t) > 0 for i in self.I)),
                "n_plants_ccs_active": int(sum(self._solution_value("captured", i, t) > 1e-6 for i in self.I)),
                "ccs_design_capacity_kt": sum(self._solution_value("k_ccs", i, t) for i in self.I),
                "ccs_idle_capacity_kt": sum(
                    max(
                        self._solution_value("k_ccs", i, t)
                        - self._solution_value("captured", i, t),
                        0.0,
                    )
                    for i in self.I
                ),
                "avg_utilization": production / max(operating_capacity, 1e-9),
                "capacity_weighted_utilization": production / max(operating_capacity, 1e-9),
                "fleet_utilization": production / max(total_capacity, 1e-9),
                "simple_average_utilization": sum(u.values()) / max(sum(round(v) for v in y.values()), 1),
                "cement_demand_mt": float(self.demand_path[year]),
                "effective_clinker_ratio": self.clinker_ratio_path[year],
                "baseline_clinker_ratio": float(cfg.BASELINE_CLINKER_RATIO),
                "lcc_clinker_ratio_reduction": float(cfg.BASELINE_CLINKER_RATIO) - self.clinker_ratio_path[year],
                "lcc_min_clinker_ratio": float(cfg.LCC_MIN_CLINKER_RATIO),
                "province_min_clinker_ratio": self.clinker_ratio_path[year],
                "province_max_clinker_ratio": self.clinker_ratio_path[year],
                "clinker_demand_kt": float(self.demand_path[year]) * 1000.0 * self.clinker_ratio_path[year],
                "clinker_production_kt": production,
                "clinker_balance_gap_kt": production
                - float(self.demand_path[year]) * 1000.0 * self.clinker_ratio_path[year],
                "total_af_supply_ktce": af_supply,
                "total_fuel_energy_ktce": fuel_energy,
                "national_af_rate": af_supply / max(fuel_energy, 1e-9),
                "ee_rate": self.ee_path[year],
                "utilization_shortfall": 0.0,
                "avg_arm_realized": arm_average,
                "avg_arm_cap": arm_average,
            }

        cumulative_actual = sum(
            self.period_weight[year] * results["summary"][year]["net_co2_kt"]
            for year in self.years
        )
        actual_reduction = 1 - cumulative_actual / self._cumulative_bau
        reference_actual_reduction = (
            1 - cumulative_actual / float(cfg.REFERENCE_CUMULATIVE_BAU_KT_YEAR)
        )
        results["emission_target_mode"] = self._emission_target_mode
        results["cumulative_budget"] = {
            "enabled": self._cumulative_budget_enabled,
            "budget_case": self._carbon_budget_case,
            "metric": "net_direct",
            "baseline": "fixed_d_medium_reference_bau",
            "reduction_target": self._cumulative_reduction_target,
            "reference_bau_kt_year": float(cfg.REFERENCE_CUMULATIVE_BAU_KT_YEAR),
            "active_demand_bau_kt_year": self._cumulative_bau,
            "bau_kt_year": self._cumulative_bau,
            "target_kt_year": self._cumulative_target,
            "actual_kt_year": cumulative_actual,
            "actual_reduction": actual_reduction,
            "actual_reduction_vs_active_demand_bau": actual_reduction,
            "actual_reduction_vs_fixed_reference_bau": reference_actual_reduction,
            "slack_kt_year": max(cumulative_actual - self._cumulative_target, 0.0),
            "terminal_2060_cap_kt": self._terminal_2060_cap,
            "terminal_2060_actual_kt": results["summary"][2060]["net_co2_kt"],
            "terminal_2060_slack_kt": max(
                results["summary"][2060]["net_co2_kt"] - self._terminal_2060_cap,
                0.0,
            ),
            "bau_by_year_kt": self._bau_by_year,
            "bau_emission_factor_tco2_per_t_clinker": self._bau_emission_factor,
            "bau_emission_factor_weighting": "observed_2025_plant_production",
            "actual_by_year_kt": {
                year: results["summary"][year]["net_co2_kt"] for year in self.years
            },
            "period_weights_years": dict(self.period_weight),
        }
        results["baseline_2025_co2_kt"] = self._bau_by_year[2025]
        results["endo_baseline_2025_co2_kt"] = results["summary"][2025]["net_co2_kt"]
        results["total_slack_kt"] = sum(self._solution_value("slack", t) for t in self.T)
        results["total_penalty_nominal_kCNY"] = 0.0
        results["total_penalty_discounted_kCNY"] = 0.0
        results["real_cost_kCNY"] = objective
        results["real_cost_CNY"] = objective * 1000.0

        cost_breakdown = {}
        component_totals = {}
        diagnostic_totals = {}
        objective_check = 0.0
        for t, year in enumerate(self.years):
            components, diagnostics = self._numeric_cost_components(t)
            discount = 1.0 / (1 + float(cfg.DISCOUNT_RATE)) ** (year - self.years[0])
            discounted = {name: amount * discount for name, amount in components.items()}
            discounted_diagnostics = {name: amount * discount for name, amount in diagnostics.items()}
            for name, amount in discounted.items():
                component_totals[name] = component_totals.get(name, 0.0) + amount
            for name, amount in discounted_diagnostics.items():
                diagnostic_totals[name] = diagnostic_totals.get(name, 0.0) + amount
            objective_check += sum(discounted.values())
            cost_breakdown[year] = {
                "period_weight_years": self.period_weight[year],
                "discount_factor": discount,
                "components_nominal_kCNY": components,
                "components_discounted_kCNY": discounted,
                "diagnostics_nominal_kCNY": diagnostics,
                "diagnostics_discounted_kCNY": discounted_diagnostics,
                "nominal_total_kCNY": sum(components.values()),
                "discounted_total_kCNY": sum(discounted.values()),
            }
        results["cost_breakdown"] = cost_breakdown
        results["cost_breakdown_total"] = {
            "components_discounted_kCNY": component_totals,
            "diagnostics_discounted_kCNY": diagnostic_totals,
            "cost_boundary": cfg.COST_BOUNDARY,
            "include_full_fuel_cost_in_objective": bool(cfg.INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE),
            "include_carbon_cost_in_objective": bool(cfg.INCLUDE_CARBON_COST_IN_OBJECTIVE),
            "discounted_total_kCNY": objective_check,
            "discounted_total_CNY": objective_check * 1000.0,
            "objective_gap_kCNY": objective_check - objective,
        }

        self._extract_flow_results(results)
        self._extract_plant_results(results)
        self._extract_external_and_resource_results(results)
        return results

    def _extract_flow_results(self, results):
        cfg = self.config
        mt_to_kt = float(cfg.STORAGE_MT_TO_KT)
        rate_scale = float(cfg.STORAGE_RATE_SCALE)
        capacity_scale = float(cfg.STORAGE_CUMULATIVE_SCALE)
        dsa_rate = (self.storage_by_idx["dsa_rate"] * mt_to_kt * rate_scale).to_dict()
        eor_rate = (self.storage_by_idx["eor_rate"] * mt_to_kt * rate_scale).to_dict()
        dsa_capacity = (self.storage_by_idx["dsa_capacity"] * mt_to_kt * capacity_scale).to_dict()
        eor_capacity = (self.storage_by_idx["eor_capacity"] * mt_to_kt * capacity_scale).to_dict()
        cluster_map = self.data.get("plant_cluster_map", {})
        hub_map = self.data.get("cluster_hub_map", {})

        transport_storage = {}
        route_output = {}
        storage_output = {}
        for t, year in enumerate(self.years):
            rows = []
            dsa_total = eor_total = offshore_total = distance_flow = 0.0
            for sink_type, pairs, variable_name in (
                ("DSA", self.ps_dsa, "f_p_dsa"),
                ("EOR", self.ps_eor, "f_p_eor"),
            ):
                for plant_id, storage_idx in pairs:
                    flow = max(self._solution_value(variable_name, plant_id, storage_idx, t), 0.0)
                    if flow <= 1e-6:
                        continue
                    route_type = sink_type.lower()
                    distance = self.route_distance[(plant_id, storage_idx, route_type)]
                    sink = self.storage_by_idx.loc[storage_idx]
                    cluster_id = cluster_map.get(plant_id)
                    rows.append({
                        "period": year,
                        "plant_id": int(plant_id),
                        "plant_idx": int(plant_id),
                        "cluster_id": int(cluster_id) if cluster_id is not None else None,
                        "hub_plant_idx": int(hub_map.get(cluster_id)) if cluster_id in hub_map else None,
                        "storage_idx": int(storage_idx),
                        "flow_kt": flow,
                        "type": sink_type,
                        "distance_km": distance,
                        "plant_longitude": float(self.lon[plant_id]),
                        "plant_latitude": float(self.lat[plant_id]),
                        "hub_longitude": float(self.lon[plant_id]),
                        "hub_latitude": float(self.lat[plant_id]),
                        "storage_longitude": float(sink["longitude"]),
                        "storage_latitude": float(sink["latitude"]),
                        "is_offshore": bool(self.is_offshore.get(storage_idx, False)),
                        "storage_type": str(sink.get("storage_type", route_type)),
                        "route_definition": "direct_plant_to_storage",
                    })
                    if sink_type == "DSA":
                        dsa_total += flow
                    else:
                        eor_total += flow
                    if self.is_offshore.get(storage_idx, False):
                        offshore_total += flow
                    distance_flow += flow * distance
            total = dsa_total + eor_total
            route_output[year] = rows

            storage_rows = []
            used_sinks = sorted({row["storage_idx"] for row in rows})
            max_rate_util = 0.0
            max_cumulative_util = 0.0
            for storage_idx in used_sinks:
                dsa_annual = sum(
                    self._solution_value("f_p_dsa", i, s, t)
                    for i, s in self.ps_dsa if s == storage_idx
                )
                eor_annual = sum(
                    self._solution_value("f_p_eor", i, s, t)
                    for i, s in self.ps_eor if s == storage_idx
                )
                dsa_cumulative = sum(
                    self.period_weight[self.years[tau]]
                    * sum(
                        self._solution_value("f_p_dsa", i, s, tau)
                        for i, s in self.ps_dsa if s == storage_idx
                    )
                    for tau in self.T if tau <= t
                )
                eor_cumulative = sum(
                    self.period_weight[self.years[tau]]
                    * sum(
                        self._solution_value("f_p_eor", i, s, tau)
                        for i, s in self.ps_eor if s == storage_idx
                    )
                    for tau in self.T if tau <= t
                )
                dsa_rate_cap = float(dsa_rate.get(storage_idx, 0.0))
                eor_rate_cap = float(eor_rate.get(storage_idx, 0.0))
                dsa_capacity_cap = float(dsa_capacity.get(storage_idx, 0.0))
                eor_capacity_cap = float(eor_capacity.get(storage_idx, 0.0))
                if bool(cfg.USE_STORAGE_RATE_CONSTRAINT):
                    if dsa_rate_cap > 0:
                        max_rate_util = max(max_rate_util, dsa_annual / dsa_rate_cap)
                    if eor_rate_cap > 0:
                        max_rate_util = max(max_rate_util, eor_annual / eor_rate_cap)
                if dsa_capacity_cap > 0:
                    max_cumulative_util = max(max_cumulative_util, dsa_cumulative / dsa_capacity_cap)
                if eor_capacity_cap > 0:
                    max_cumulative_util = max(max_cumulative_util, eor_cumulative / eor_capacity_cap)
                sink = self.storage_by_idx.loc[storage_idx]
                storage_rows.append({
                    "period": year,
                    "storage_idx": int(storage_idx),
                    "longitude": float(sink["longitude"]),
                    "latitude": float(sink["latitude"]),
                    "is_offshore": bool(self.is_offshore.get(storage_idx, False)),
                    "storage_type": str(sink.get("storage_type", "unknown")),
                    "dsa_flow_kt": dsa_annual,
                    "eor_flow_kt": eor_annual,
                    "total_flow_kt": dsa_annual + eor_annual,
                    "dsa_cumulative_stored_kt": dsa_cumulative,
                    "eor_cumulative_stored_kt": eor_cumulative,
                    "total_cumulative_stored_kt": dsa_cumulative + eor_cumulative,
                    "dsa_rate_capacity_kt_per_year": dsa_rate_cap,
                    "eor_rate_capacity_kt_per_year": eor_rate_cap,
                    "annual_rate_constraint_enabled": bool(cfg.USE_STORAGE_RATE_CONSTRAINT),
                    "dsa_cumulative_capacity_kt": dsa_capacity_cap,
                    "eor_cumulative_capacity_kt": eor_capacity_cap,
                    "dsa_rate_utilization": (
                        dsa_annual / dsa_rate_cap
                        if bool(cfg.USE_STORAGE_RATE_CONSTRAINT) and dsa_rate_cap > 0 else None
                    ),
                    "eor_rate_utilization": (
                        eor_annual / eor_rate_cap
                        if bool(cfg.USE_STORAGE_RATE_CONSTRAINT) and eor_rate_cap > 0 else None
                    ),
                    "dsa_cumulative_utilization": dsa_cumulative / dsa_capacity_cap if dsa_capacity_cap > 0 else 0.0,
                    "eor_cumulative_utilization": eor_cumulative / eor_capacity_cap if eor_capacity_cap > 0 else 0.0,
                })
            storage_output[year] = storage_rows
            commercial = results["summary"][year]["commercial_captured_co2_kt"]
            transport_storage[year] = {
                "dsa_flow_kt": dsa_total,
                "eor_flow_kt": eor_total,
                "total_flow_kt": total,
                "captured_co2_kt": commercial,
                "commercial_captured_co2_kt": commercial,
                "observed_pilot_captured_co2_kt": results["summary"][year]["observed_pilot_captured_co2_kt"],
                "flow_capture_gap_kt": total - commercial,
                "definition_note": "Direct plant-to-storage flows cover commercial CCS only.",
                "offshore_flow_kt": offshore_total,
                "onshore_flow_kt": total - offshore_total,
                "weighted_avg_transport_km": distance_flow / total if total > 1e-9 else 0.0,
                "max_sink_rate_utilization": max_rate_util if bool(cfg.USE_STORAGE_RATE_CONSTRAINT) else None,
                "max_sink_cumulative_utilization": max_cumulative_util,
            }
        results["ccs_transport_storage"] = transport_storage
        results["co2_flow_routes"] = route_output
        results["storage_utilization"] = storage_output

    def _extract_plant_results(self, results):
        cfg = self.config
        tce = float(cfg.TCE_PER_T_CLINKER)
        for i in self.I:
            x_af = {}
            uaf = {}
            k_af_rate = {}
            for t, year in enumerate(self.years):
                u = self._solution_value("u", i, t)
                supply = self._solution_value("af_supply", i, t)
                fuel = self.cap[i] * u * tce
                x_af[year] = supply / fuel if fuel > 1e-9 else 0.0
                uaf[year] = supply / max(self.cap[i] * tce, 1e-9)
                k_af_rate[year] = self._solution_value("k_af", i, t) / max(self.cap[i] * tce, 1e-9)
            results["plants"][i] = {
                "y": {year: int(round(self._solution_value("y", i, t))) for t, year in enumerate(self.years)},
                "r": {year: int(round(self._solution_value("r", i, t))) for t, year in enumerate(self.years)},
                "close": {year: self._solution_value("close", i, t) for t, year in enumerate(self.years)},
                "u": {year: self._solution_value("u", i, t) for t, year in enumerate(self.years)},
                "uee": {
                    year: self._solution_value("u", i, t) * self.ee_path[year]
                    for t, year in enumerate(self.years)
                },
                "z": {year: int(round(self._solution_value("z", i, t))) for t, year in enumerate(self.years)},
                "k_ccs": {year: self._solution_value("k_ccs", i, t) for t, year in enumerate(self.years)},
                "ccs_new_design": {
                    year: self._solution_value("ccs_new_design", i, t)
                    for t, year in enumerate(self.years)
                },
                "x_af": x_af,
                "uaf": uaf,
                "k_af_rate": k_af_rate,
                "k_af_ktce": {year: self._solution_value("k_af", i, t) for t, year in enumerate(self.years)},
                "af_add": {year: self._solution_value("af_add", i, t) for t, year in enumerate(self.years)},
                "af_add_ktce": {year: self._solution_value("af_add", i, t) for t, year in enumerate(self.years)},
                "af_supply_ktce": {
                    year: self._solution_value("af_supply", i, t)
                    for t, year in enumerate(self.years)
                },
                "co2_fuel": {year: self._solution_value("co2_fuel", i, t) for t, year in enumerate(self.years)},
                "co2_process": {year: self._solution_value("co2_process", i, t) for t, year in enumerate(self.years)},
                "co2_gross": {year: self._solution_value("co2_total", i, t) for t, year in enumerate(self.years)},
                "co2_net_commercial": {year: self._solution_value("co2_net", i, t) for t, year in enumerate(self.years)},
                "co2_net": {year: self._solution_value("co2_net", i, t) for t, year in enumerate(self.years)},
                "captured_commercial": {
                    year: self._solution_value("captured", i, t)
                    for t, year in enumerate(self.years)
                },
                "captured_observed_pilot": {
                    year: self._observed_pilot_capture(i, t)
                    for t, year in enumerate(self.years)
                },
                "captured": {
                    year: self._solution_value("captured", i, t)
                    for t, year in enumerate(self.years)
                },
            }

    def _extract_external_and_resource_results(self, results):
        province_capacity = {
            p: sum(self.cap[i] for i in self.I if self.province_map[i] == p) for p in self.P
        }
        results["province_arm"] = {
            p: {
                year: {
                    "realized": float(self.arm_path.get((p, year), 0.0)),
                    "cap": float(self.arm_path.get((p, year), 0.0)),
                    "treatment": "exogenous",
                }
                for year in self.years
            }
            for p in self.P
        }
        af_resource = {}
        for p in self.P:
            members = [i for i in self.I if self.province_map[i] == p]
            af_resource[p] = {}
            for t, year in enumerate(self.years):
                used = sum(self._solution_value("af_supply", i, t) for i in members)
                pool = float(self.province_af_pool.get((p, year), 0.0))
                af_resource[p][year] = {
                    "used_ktce": used,
                    "pool_ktce": pool,
                    "utilization": used / pool if pool > 1e-9 else 0.0,
                }
        results["af_resource_utilization"] = af_resource
        results["ccs_learning"] = {
            year: {
                "new_design_capacity_kt": sum(
                    self._solution_value("ccs_new_design", i, t) for i in self.I
                ),
                "selected_stage": "exogenous_maturity",
                "time_capex_multiplier": float(
                    self.config.CCS_LEARNING_CURVE["investment_multiplier"][year]
                ),
                "time_opex_multiplier": float(
                    self.config.CCS_LEARNING_CURVE["om_multiplier"][year]
                ),
                "plant_scale_multiplier_min": min(self.plant_ccs_cost_multiplier.values()),
                "plant_scale_multiplier_max": max(self.plant_ccs_cost_multiplier.values()),
            }
            for t, year in enumerate(self.years)
        }
        results["external_technology_paths"] = {
            "energy_efficiency_case": str(self.data.get("ee_path_case", "unspecified")),
            "energy_efficiency": dict(self.ee_path),
            "national_clinker_ratio": dict(self.clinker_ratio_path),
            "arm_path_case": str(self.data.get("arm_path_case", "unspecified")),
            "arm_spatial_mode": str(self.config.ARM_SPATIAL_MODE),
            "arm_capacity_weighted_average": {
                year: sum(
                    province_capacity[p] * float(self.arm_path.get((p, year), 0.0))
                    for p in self.P
                ) / max(sum(province_capacity.values()), 1e-9)
                for year in self.years
            },
        }
        results["model_assumptions"] = {
            "endogenous_modules": [
                "plant_operation_exit_same_site_capacity_renewal",
                "alternative_fuel_allocation_and_capacity",
                "commercial_ccs_design_and_capture",
                "direct_plant_to_storage_flow",
            ],
            "external_modules": ["arm", "energy_efficiency", "national_clinker_ratio"],
            "energy_efficiency_path_case": str(
                self.data.get("ee_path_case", "unspecified")
            ),
            "arm_path_case": str(self.data.get("arm_path_case", "unspecified")),
            "baseyear_production_anchor": "2025_province_output_capacity_proportional_within_province",
            "baseyear_af_anchor_rate": float(self.config.INITIAL_AF_RATE),
            "af_plant_access_mode": str(
                self.data.get(
                    "_af_plant_access_mode",
                    self.config.AF_PLANT_ACCESS_MODE,
                )
            ),
            "af_spatial_equalized": bool(
                self.data.get("_af_spatial_equalized", False)
            ),
            "minimum_operating_utilization": float(self.config.MIN_OPERATING_UTILIZATION),
            "early_retirement_cost_cny_per_t_annual_capacity": float(
                self.config.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY
            ),
            "maximum_utilization_change_per_period": float(
                self.config.MAX_UTILIZATION_CHANGE_PER_PERIOD
            ),
            "ccs_minimum_operating_years": int(
                self.config.CCS_MIN_OPERATING_YEARS
            ),
            "ccs_minimum_operating_period_definition": (
                "each commercial CCS design-capacity addition must persist for "
                "at least the configured commitment period"
            ),
            "ccs_terminal_commitment_treatment": str(
                self.config.CCS_TERMINAL_COMMITMENT_MODE
            ),
            "plant_lifetime_years": int(self.config.PLANT_LIFETIME_YEARS),
            "same_site_capacity_renewal_definition": (
                "brownfield renewal or replacement at the incumbent plant site; "
                "plant identity, location and nameplate capacity are retained"
            ),
            "same_site_capacity_renewal_legacy_variable": "r/rebuild",
            "same_site_capacity_renewal_minimum_capacity_td": float(
                self.config.SAME_SITE_RENEWAL_MIN_CAPACITY_TD
            ),
            "post_renewal_exit_allowed": True,
            "storage_rate_constraint_enabled": bool(self.config.USE_STORAGE_RATE_CONSTRAINT),
            "storage_capacity_constraint_enabled": True,
            "offshore_classification_method": "basin_box_excluding_china_land",
            "source_sink_matching": "direct_plant_to_storage",
            "transport_maximum_distance_km": float(
                self.data.get("_storage_max_distance_km", self.config.TRANSPORT_MAX_KM)
            ),
            "plants_without_sink_within_maximum_distance": int(
                sum(
                    1
                    for plant_id in self.I
                    if not self.data.get("plant_storage", {}).get(plant_id, [])
                )
            ),
            "cluster_role": "postprocessing_only",
            "bau_emission_factor_weighting": "observed_2025_plant_production",
            "observed_pilots_in_target_accounting": bool(
                self.config.OBSERVED_PILOT_CCS_INCLUDE_IN_TARGET_ACCOUNTING
            ),
        }
