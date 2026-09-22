"""v5 plant-level cement capacity and decarbonization optimization model.

P0 changes landed 2026-09-11 (see v5/README.md and v5/parameters/):
  P0-1 CCS cost: Mao dimension fix, three cost-decline scenarios, continuous size scaling.
  P0-2 AF: four-layer structure (technical / accessibility allocation / national expansion
           rate / province-pool guard); the engineered per-plant TSR path is gone.
  P0-3 Operations: no utilisation ramp; plant fixed operating cost added; u_min 0.25.

Original module docstring follows.
Final plant-level cement capacity and decarbonization optimization model.

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
from pathlib import Path
from .carbon_streams import add_carbon_streams, fossil_flow_value

import numpy as np
import pandas as pd
from pyomo.environ import (
    Binary,
    ConcreteModel,
    Constraint,
    Expression,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
    value,
)


class _HighsVariable:
    """Small Gurobi-compatible view used by the existing result pipeline."""

    def __init__(self, name, value):
        self.VarName = name
        self.X = float(value)


class _HighsResultAdapter:
    """Expose the solver facts consumed by the existing v4 pipeline."""

    def __init__(self, highs, runtime_s):
        import highspy

        info = highs.getInfo()
        solution = highs.getSolution()
        names = list(highs.getLp().col_names_)
        values = list(solution.col_value) if solution.value_valid else []
        self._variables = {
            name: _HighsVariable(name, values[index])
            for index, name in enumerate(names)
            if index < len(values)
        }
        self.ObjVal = float(info.objective_function_value) if solution.value_valid else None
        self.ObjBound = float(info.mip_dual_bound)
        self.MIPGap = float(info.mip_gap)
        self.NodeCount = float(info.mip_node_count)
        self.IterCount = float(info.simplex_iteration_count + info.ipm_iteration_count)
        self.SolCount = int(
            solution.value_valid
            and info.primal_solution_status == highspy.kSolutionStatusFeasible
        )
        self.Runtime = float(runtime_s)
        self.Status = highs.getModelStatus()

    def getVarByName(self, name):
        return self._variables.get(str(name))

    def getVars(self):
        return list(self._variables.values())


def _highs_options(options):
    """Translate the portable subset of the established Gurobi profiles."""
    mapping = {
        "TimeLimit": "time_limit",
        "MIPGap": "mip_rel_gap",
        "Threads": "threads",
        "Seed": "random_seed",
    }
    translated = {
        mapping[key]: setting for key, setting in options.items() if key in mapping
    }
    if "HiGHSParallel" in options:
        translated["parallel"] = options["HiGHSParallel"]
    translated["output_flag"] = bool(options.get("tee", False))
    return translated


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
        # Dispatch fuel cost (see config_v5): plant fuel intensity and the 2025
        # PRODUCTION-weighted fleet mean that defines the deviation. Using a fixed
        # 2025-basis mean makes (ef_i - ef_mean) a time-invariant plant attribute.
        self.plant_fuel_ef = {
            i: float(self.emission_factors[i]["fuel_ef"]) for i in self.I
        }
        _w = sum(self.cap[i] * self.baseyear_utilization[i] for i in self.I)
        self.fuel_ef_mean = (
            sum(self.plant_fuel_ef[i] * self.cap[i] * self.baseyear_utilization[i]
                for i in self.I) / _w
            if _w > 0 else 0.0
        )
        self.province_af_pool = self.data["province_af_pool_ktce"]
        # P0-2 AF structure inputs
        self.af_share_bio = {int(k): float(v) for k, v in self.data["af_share_bio"].items()}
        self.af_share_wst = {int(k): float(v) for k, v in self.data["af_share_wst"].items()}
        self.af_alloc_bio = dict(self.data["af_alloc_bio"])
        self.af_alloc_wst = dict(self.data["af_alloc_wst"])
        # ── AF energy caliber (2026-09-13) ────────────────────────────────
        # One heat-demand definition shared by the technical ceiling, the national
        # expansion cap and the fuel-emission AF credit, so that a single physical
        # quantity is never given two different denominators:
        #   H[i,t] = h_i * (1 - EE_t) * cap_i * u[i,t]        [ktce/yr]
        #   h_i    = plant_fuel_ef[i] / COAL_EF               [tce/t clinker]
        # h_i is therefore the plant's OWN kiln heat intensity (the measured tiers
        # are 101.7/109.9/119.8 kgce/t). The legacy caliber used a flat 0.105 for
        # every plant and ignored EE; "flat_tce" reproduces it for audit only.
        self.af_energy_caliber = str(
            getattr(cfg, "AF_ENERGY_CALIBER", "plant_heat_demand")
        )
        self.coal_ef = float(getattr(cfg, "COAL_EF_TCO2_PER_TCE", 2.6604))
        self.plant_heat_intensity = {
            i: (
                self.plant_fuel_ef[i] / self.coal_ef
                if self.af_energy_caliber == "plant_heat_demand"
                else float(cfg.TCE_PER_T_CLINKER)
            )
            for i in self.I
        }
        # Biogenic CO2 released per tce of AF (open evidence gap; central 0.0 --
        # see config_v5 AF_BIOGENIC_CO2_PER_TCE).
        self.af_biogenic_co2_per_tce = float(
            getattr(cfg, "AF_BIOGENIC_CO2_PER_TCE", 0.0)
        )
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

        # ── P0-4 v3: distributed market nodes and clinker transport ──────────
        # ~150 market nodes, each with an EQUALITY balance, so distance to market
        # enters the turnover decision. The province single point could not do
        # this: dropping a distant plant inside a province left the retained
        # plants' distance to the province centroid unchanged, so no force raised
        # marginal cost with concentration and u sat at its bound (0.995). Node
        # demand is roughly 7 Mt/yr, large relative to a plant, so the equal-cost
        # collapse cannot recur. Market nodes carry the REAL plant->node
        # haversine distance, including within a province; the v2 rule that
        # treated intra-province transport as zero is retired.
        self.regional_demand_enabled = bool(
            getattr(cfg, "ENABLE_REGIONAL_DEMAND",
                    self.data.get("regional_demand_enabled", False))
        )
        plant_set = set(self.I)
        if self.regional_demand_enabled:
            arcs = {
                (int(i), int(j)): float(d)
                for (i, j), d in (self.data.get("demand_arcs") or {}).items()
                if int(i) in plant_set
            }
            if not arcs:
                raise ValueError(
                    "regional demand is enabled but no candidate arcs were loaded; "
                    "check the loader and v5/data/demand_market_arcs.csv"
                )
            self.dem_arc_distance = arcs
            # The unit rate is resolved here rather than in the loader, so the
            # transport-cost sensitivity is a pure config switch with no data rebuild.
            mode = str(getattr(cfg, "DEMAND_TRANSPORT_MODE", "segmented")).lower()
            if mode not in {"segmented", "uniform"}:
                # Guard (2026-09-14): previously any other string (e.g. "zero")
                # silently fell into the segmented branch. The CLI translates
                # "zero" into a zero-rate segment list with mode "segmented";
                # reaching this branch with an unknown mode is a wiring bug.
                raise ValueError(
                    f"Unknown DEMAND_TRANSPORT_MODE {mode!r}; expected "
                    "'segmented' or 'uniform' (pass zero rates via the segments)"
                )
            uniform = float(getattr(cfg, "DEMAND_TRANSPORT_COST_UNIFORM", 0.20))
            segments = tuple(getattr(cfg, "DEMAND_TRANSPORT_COST_SEGMENTS",
                                    ((float("inf"), uniform),)))
            # Cost per TONNE: the cumulative piecewise integral of the
            # distance-segmented rate (200 km -> 90, 600 km -> 138, 1000 km -> 158
            # CNY/t). Using the marginal band rate as if it were CNY/t would drop
            # the distance factor entirely and make transport distance-independent.
            def _cost_per_t(km):
                d = float(km)
                if d <= 0.0:
                    return 0.0
                if mode == "uniform":
                    return uniform * d
                cost, prev = 0.0, 0.0
                for upper, rate in segments:
                    if d > prev:
                        cost += (min(d, float(upper)) - prev) * float(rate)
                    prev = float(upper)
                    if d <= float(upper):
                        break
                return cost
            self.dem_arc_cost_per_t = {key: _cost_per_t(km) for key, km in arcs.items()}
            self.dem_transport_mode = mode
            self.dem_arcs = sorted(arcs)
            self.dem_nodes = sorted({j for _, j in arcs})
            self.dem_node_shares = {
                int(y): {int(k): float(v) for k, v in shares.items()}
                for y, shares in self.data["market_node_shares_by_year"].items()
            }
            self.dem_arcs_by_plant = {i: [] for i in self.I}
            self.dem_arcs_by_node = {j: [] for j in self.dem_nodes}
            for i, j in self.dem_arcs:
                self.dem_arcs_by_plant[i].append(j)
                self.dem_arcs_by_node[j].append(i)
            # Province attribution is only for reporting inter-provincial flows.
            market_nodes = self.data.get("market_nodes")
            self.dem_node_province = ({
                int(r.node_id): str(r.province)
                for r in market_nodes[["node_id", "province"]].itertuples(index=False)
            } if market_nodes is not None else {})
        else:
            self.dem_arc_distance = {}
            self.dem_arc_cost_per_t = {}
            self.dem_arcs = []
            self.dem_nodes = []
            self.dem_node_shares = {}
            self.dem_node_province = {}
            self.dem_transport_mode = None
            self.dem_arcs_by_plant = {i: [] for i in self.I}
            self.dem_arcs_by_node = {}

        capture_eff = float(cfg.CCS_PARAMS.get("capture_efficiency", 0.90))
        self.plant_big_m = {}
        self.plant_ccs_cost_multiplier = {}
        self.plant_ccs_om_multiplier = {}
        # P0-1: continuous power law on specific cost, replacing the four-bin step table.
        # specific_cost_multiplier = clip((S / S_ref) ** (b - 1), lo, hi); a SMALLER b
        # means STRONGER scale economies. Central b_capex = 0.80, b_om = 0.90.
        scaling = dict(cfg.CCS_SIZE_SCALING)
        ref_kt = float(scaling["reference_design_kt"])
        b_capex = float(scaling["exponent_capex"])
        b_om = float(scaling["exponent_om"])
        clip_lo, clip_hi = scaling["clip"]
        for i in self.I:
            ef = self.emission_factors[i]
            # Nameplate design bound. Must cover the GROSS flow the capture unit can
            # see: the fossil/process part plus the biogenic part of the maximum AF
            # burn (theta * h_i * cap_i). With AF_BIOGENIC_CO2_PER_TCE = 0 the second
            # term vanishes and this reduces to the previous bound.
            bio_term = (
                capture_eff
                * float(getattr(cfg, "AF_BIOGENIC_CO2_PER_TCE", 0.0))
                * float(cfg.AF_TECHNICAL_TSR_CEILING)
                * self.plant_heat_intensity[i]
                * self.cap[i]
            )
            maximum = max(
                capture_eff * self.cap[i] * (float(ef["proc_ef"]) + float(ef["fuel_ef"])) * 1.05
                + bio_term,
                1.0,
            )
            self.plant_big_m[i] = maximum
            ratio = maximum / ref_kt
            self.plant_ccs_cost_multiplier[i] = min(
                max(ratio ** (b_capex - 1.0), clip_lo), clip_hi
            )
            self.plant_ccs_om_multiplier[i] = min(
                max(ratio ** (b_om - 1.0), clip_lo), clip_hi
            )

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

        # P0-4 v3: clinker shipped from plant i to market node j (kt/yr)
        if self.regional_demand_enabled:
            m.DEM_ARC = Set(initialize=self.dem_arcs, dimen=2)
            m.DEM_NODE = Set(initialize=self.dem_nodes)
            m.f_dem = Var(m.DEM_ARC, m.T, within=NonNegativeReals)

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
        self._apply_planning_mode(m)
        self._objective(m)
        return m

    def _apply_planning_mode(self, m):
        """Stage-1 of the stepwise (S) counterfactual: no low-carbon measures.

        Applied AFTER the ordinary constraint set so that it only fixes variables
        that already exist and already have their bounds set. The carbon target is
        switched off in main.py (EMISSION_TARGET_MODE="none"), because it is read
        inside _demand_and_target_constraints.

        WHAT IS FIXED, AND WHY NOT MORE
        -------------------------------
        af_supply = 0 and af_add = 0, and z = k_ccs = ccs_new_design = 0. With those
        at zero the AF capex/O&M, all CCS terms, the CO2 pipeline and both storage
        terms are identically zero, so the remaining objective is exactly
        capacity_retention + same_site_renewal_capex + early_retirement +
        clinker_transport + dispatch_fuel -- the conventional production resource
        cost. (early_retirement is kept: it is a real resource cost of the turnover
        decision, not a low-carbon measure.)

        k_af is deliberately NOT fixed to zero. Doing so is INFEASIBLE: the AF
        capacity-persistence constraint reads
            k_af[i,t] >= k_af[i,t-1] - maximum * (1 - y[i,t]),
        and k_af[i,0] is pinned to the OBSERVED 2025 allocation, so forcing
        k_af[i,t] = 0 requires (1 - y[i,t]) >= k_af[i,0]/maximum > 0, i.e. y = 0.
        Every line that burned any AF in 2025 would be forced to shut down in 2030
        purely as an artefact of the fixing. That is what made the first stage-1 run
        report infeasible (reproduced, and confirmed by releasing k_af alone).
        Leaving k_af free is also the CORRECT economics: the 2025 AF handling
        capacity is already sunk, it costs nothing to leave standing (capex is
        charged on af_add, O&M on af_supply), and stage 1 is about not building NEW
        low-carbon capital.
        """
        mode = str(getattr(self.config, "PLANNING_MODE", "joint"))
        self._planning_mode = mode
        if mode != "stepwise_capacity":
            return
        after = [t for t in self.T if t > 0]
        for i in self.I:
            for t in after:
                m.z[i, t].fix(0)
                m.k_ccs[i, t].fix(0)
                m.ccs_new_design[i, t].fix(0)
                m.af_supply[i, t].fix(0)
                m.af_add[i, t].fix(0)
        print(
            "  [planning] stepwise STAGE 1: carbon target OFF; CCS off and no AF "
            "burned or built for t>0 (k_af left free -- fixing it is infeasible "
            "against capacity persistence, see the docstring); the fleet is chosen "
            "on conventional resource cost only"
        )

    def _production_constraints(self, m):
        cfg = self.config
        after = [t for t in self.T if t > 0]
        u_min = float(cfg.MIN_OPERATING_UTILIZATION)

        m.util_upper = Constraint(m.I, m.T, rule=lambda mm, i, t: mm.u[i, t] <= mm.y[i, t])

        def utilization_lower(mm, i, t):
            if t == 0:
                return Constraint.Skip
            return mm.u[i, t] >= u_min * mm.y[i, t]
        m.util_lower = Constraint(m.I, m.T, rule=utilization_lower)

        # Change 3 (2026-09-12, VALIDATION ONLY): optional cap on the national
        # active-capacity decline pace. Off in the central model (config None); a
        # dedicated validation run can switch it on to test whether the model's
        # contraction path is inside the observed 5-10%/yr 2016-2020 policy band.
        max_decline = getattr(cfg, "MAX_ANNUAL_CAPACITY_DECLINE", None)
        if max_decline is not None:
            rate = float(max_decline)

            def capacity_decline(mm, t):
                dy = float(self.years[t] - self.years[t - 1])
                return (
                    sum(self.cap[i] * mm.y[i, t] for i in self.I)
                    >= (1.0 - rate) ** dy
                    * sum(self.cap[i] * mm.y[i, t - 1] for i in self.I)
                )
            m.capacity_decline_pace = Constraint(after, rule=capacity_decline)

        # Change 3b (2026-09-13, SCENARIO ONLY): per-period (five-year) decline cap.
        # Takes the five-year fraction directly, so there is no annualisation step to
        # mis-specify (--max-annual-capacity-decline 0.10 means 10%/yr = -41% over a
        # period, when the intended policy reading is -10% over five years).
        # IMPORTANT: by construction this constraint RETAINS idle capacity, so a low
        # utilisation becomes an artefact of the cap rather than a model finding. It
        # defines the "slow-exit institutional friction" scenario; it must never be
        # read as a calibration of the central utilisation path.
        max_decline_period = getattr(cfg, "MAX_CAPACITY_DECLINE_PER_PERIOD", None)
        if max_decline_period is not None:
            period_rate = float(max_decline_period)
            if not 0.0 <= period_rate < 1.0:
                raise ValueError(
                    "MAX_CAPACITY_DECLINE_PER_PERIOD must be in [0, 1)"
                )

            def capacity_decline_period(mm, t):
                return (
                    sum(self.cap[i] * mm.y[i, t] for i in self.I)
                    >= (1.0 - period_rate)
                    * sum(self.cap[i] * mm.y[i, t - 1] for i in self.I)
                )
            m.capacity_decline_pace_period = Constraint(
                after, rule=capacity_decline_period
            )

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

        renewal_window = str(
            getattr(self.config, "SAME_SITE_RENEWAL_WINDOW", "first_after_expiry")
        ).lower()
        renewal_max = int(
            getattr(self.config, "SAME_SITE_RENEWAL_MAX_COUNT", 1) or 0
        )

        def same_site_renewal_eligibility(mm, i, t):
            first = self.same_site_renewal_period[i]
            if first is None or t < first:
                return mm.r[i, t] == 0
            if renewal_window == "any_after_expiry":
                return Constraint.Skip
            return Constraint.Skip if t == first else mm.r[i, t] == 0
        m.same_site_renewal_eligibility = Constraint(
            m.I, m.T, rule=same_site_renewal_eligibility
        )
        m.at_most_one_same_site_renewal = Constraint(
            m.I, rule=lambda mm, i: sum(mm.r[i, t] for t in mm.T) <= renewal_max
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
        # P0-3: the utilisation ramp constraints were removed. Their role (blocking
        # costless cross-period re-dispatch) is now carried by
        # PLANT_FIXED_OPERATING_COST. Measured binding rate before removal: 21.5% of
        # continuously-operating lines in 2030, 44.3% in 2045, 62.2% in 2050.

    def _af_constraints(self, m):
        """Alternative-fuel constraints: four layers (P0-2).

        (1) technical   af_supply <= theta * H[i,t]                   theta = 0.60
        (2) allocation  af_supply <= kappa * (A_bio*share_bio + A_wst*share_wst)
        (3) expansion   sum_i af_supply[t] <= sum_i af_supply[t-1] + phi * sum_i H[i,t]
        (4) pool guard  sum_{i in p} af_supply <= province resource pool

        H[i,t] = h_i * (1 - EE_t) * cap_i * u[i,t] is the plant's own kiln heat
        demand (see __init__), used consistently here, in the expansion cap and in
        the fuel-emission AF credit. Before 2026-09-13 layer (1) and (3) used a flat
        TCE_PER_T_CLINKER = 0.105 and ignored EE, so the AF ceiling was shifted
        across plants by their heat-intensity tier and drifted with EE (measured:
        true heat demand was 87.8% of the model's caliber by 2060).

        Layer (2) replaces v4's absolute raw-catchment cap, which was placed in
        parallel with the province pool and never bound (measured max supply/access
        0.68). Layer (3) replaces AF_ENGINEERING_TSR_PATH, the per-plant engineered
        path that had itself become the sole determinant of the national AF
        trajectory (binding 86.6%-100% of operating lines in 2030-2050). Since
        2026-09-13 layer (2) is fed by the RAW province resource pool, so the
        deployment pace in layer (3) no longer constrains the resource endowment.
        """
        cfg = self.config
        after = [t for t in self.T if t > 0]
        theta = float(cfg.AF_TECHNICAL_TSR_CEILING)
        kappa = float(cfg.AF_ACCESS_ALLOCATION_HEADROOM)
        # Fraction of current-period national heat demand by which national AF energy
        # may grow in one period. NOT a percentage-point cap on the substitution rate.
        expansion = float(
            getattr(cfg, "AF_EXPANSION_FRACTION_OF_HEAT", cfg.AF_EXPANSION_PP / 100.0)
        )
        h = self.plant_heat_intensity

        def heat_demand(mm, i, t):
            """Plant kiln heat demand in ktce/yr: h_i * (1 - EE_t) * Q[i,t]."""
            ee = float(self.ee_path[self.years[t]])
            return h[i] * (1.0 - ee) * self.cap[i] * mm.u[i, t]

        # (1) technical ceiling — physical substitution potential of the kiln line
        def technical_actual(mm, i, t):
            return mm.af_supply[i, t] <= theta * heat_demand(mm, i, t)
        m.af_technical_actual = Constraint(m.I, m.T, rule=technical_actual)

        def technical_design(mm, i, t):
            # Design envelope on nameplate output at the plant's own intensity.
            return mm.k_af[i, t] <= theta * h[i] * self.cap[i] * mm.y[i, t]
        m.af_technical_design = Constraint(m.I, m.T, rule=technical_design)
        m.af_within_design = Constraint(
            m.I, m.T, rule=lambda mm, i, t: mm.af_supply[i, t] <= mm.k_af[i, t]
        )

        # Base-year shares. A scenario branch may deliberately reshape the
        # WITHIN-PROVINCE accessibility shares for the decision horizon (S3 swaps
        # them to capacity weights), but the 2025 anchor is an OBSERVATION whose
        # af_supply is FIXED, and the loader built it against the ORIGINAL shares.
        # Re-using modified shares at t = 0 lets that fixed value violate its own cap
        # -- measured under S3: 29 of 1,572 plants, enough to make the run INFEASIBLE.
        # Branches that reshape shares stash the originals; the base year uses them.
        self.af_share_bio_base_year = {
            int(k): float(v)
            for k, v in (self.data.get("af_share_bio_base_year") or {}).items()
        }
        self.af_share_wst_base_year = {
            int(k): float(v)
            for k, v in (self.data.get("af_share_wst_base_year") or {}).items()
        }

        # (2) accessibility allocation — share-weighted slice of the province pool
        def access_shares(i, t):
            """Plant accessibility shares for period t.

            The base year uses the ORIGINAL shares (stashed by any scenario branch
            that reshapes them), every later period uses the active shares.
            """
            if t == 0 and self.af_share_bio_base_year:
                return (
                    self.af_share_bio_base_year.get(i, self.af_share_bio.get(i, 0.0)),
                    self.af_share_wst_base_year.get(i, self.af_share_wst.get(i, 0.0)),
                )
            return self.af_share_bio.get(i, 0.0), self.af_share_wst.get(i, 0.0)

        def access_cap(i, t):
            province = self.province_map[i]
            year = self.years[t]
            sb, sw = access_shares(i, t)
            return float(self.af_alloc_bio.get((province, year), 0.0)) * sb + float(
                self.af_alloc_wst.get((province, year), 0.0)
            ) * sw

        def accessibility(mm, i, t):
            return mm.af_supply[i, t] <= kappa * access_cap(i, t)
        m.af_accessibility = Constraint(m.I, m.T, rule=accessibility)

        # (3) national expansion rate limit
        def expansion_cap(mm, t):
            allowed = expansion * sum(heat_demand(mm, i, t) for i in self.I)
            total = sum(mm.af_supply[i, t] for i in self.I)
            if t == 0:
                anchor = float(cfg.INITIAL_AF_RATE) * sum(
                    heat_demand(mm, i, t) for i in self.I
                )
                return total <= anchor
            return total <= sum(mm.af_supply[i, t - 1] for i in self.I) + allowed
        m.af_expansion_cap = Constraint(m.T, rule=expansion_cap)

        # (4) province resource pool — physical resource guard (expected slack)
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

        # Consistency guard (2026-09-13). The base-year supply is FIXED, so it must
        # satisfy its own accessibility cap. If a scenario branch reshapes the shares
        # without stashing the originals, the model simply returns INFEASIBLE with a
        # one-constraint IIS, which is slow and confusing to diagnose -- measured
        # under S3: 29 of 1,572 plants. Fail loudly with the offending plants instead.
        offenders = []
        for i in self.I:
            baseline = float(self.baseyear_af_supply.get(i, 0.0))
            if baseline <= 0.0:
                continue
            cap = kappa * access_cap(i, 0)
            if baseline > cap + 1e-6:
                offenders.append((i, baseline, cap))
        if offenders:
            worst = max(offenders, key=lambda o: o[1] - o[2])
            raise ValueError(
                "Base-year AF supply violates the accessibility cap at t=0 for "
                f"{len(offenders)} plant(s); worst: plant {worst[0]} supply="
                f"{worst[1]:.4f} > cap={worst[2]:.4f}. The 2025 anchor is an "
                "observation and must be built against the SAME shares the t=0 "
                "constraint uses. A scenario branch that reshapes the shares must "
                "stash the originals in data['af_share_bio_base_year'] / "
                "data['af_share_wst_base_year']."
            )

        def af_capacity_persistence(mm, i, t):
            maximum = self.cap[i] * h[i] * theta
            return mm.k_af[i, t] >= mm.k_af[i, t - 1] - maximum * (1 - mm.y[i, t])
        m.af_capacity_persistence = Constraint(m.I, after, rule=af_capacity_persistence)
        m.af_capacity_addition = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.af_add[i, t] >= mm.k_af[i, t] - mm.k_af[i, t - 1],
        )

    def _emission_constraints(self, m):
        """Fuel and process CO2 on ONE heat-demand caliber (2026-09-13).

        E^F[i,t] = COAL_EF * ( H[i,t] - BETA_AF * A[i,t] )

        H[i,t] = h_i * (1 - EE_t) * Q[i,t] is the plant's own kiln heat demand and
        A[i,t] = af_supply[i,t] is AF energy substituted for coal at the same
        efficiency. Because COAL_EF * H = plant_fuel_ef[i] * (1 - EE) * Q, the
        first term is numerically identical to the old formulation, so only the AF
        credit changes: it becomes COAL_EF * BETA_AF per tce of AF instead of
        plant_fuel_ef[i] * (1 - EE) * BETA_AF / 0.105.

        Why that matters: the old credit carried BOTH a plant-tier factor and an EE
        factor, so the same physical tonne of AF displaced a different amount of CO2
        depending on which plant burned it and on the year's energy-efficiency level.
        The physical credit per tce substituted is a property of the fuel pair
        (coal vs AF), not of the kiln's intensity, and must not be re-scaled by EE:
        EE reduces the TOTAL heat demand, not the emissivity of the displaced fuel.
        """
        cfg = self.config
        beta_af = float(cfg.BETA_AF)
        h = self.plant_heat_intensity
        coal_ef = self.coal_ef

        def heat_demand(mm, i, t):
            ee = float(self.ee_path[self.years[t]])
            return h[i] * (1.0 - ee) * self.cap[i] * mm.u[i, t]

        self._heat_demand = heat_demand

        def fuel_emission(mm, i, t):
            return mm.co2_fuel[i, t] == coal_ef * (
                heat_demand(mm, i, t) - beta_af * mm.af_supply[i, t]
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
        min_design = float(cfg.CCS_PARAMS.get("min_active_design_kt", 100.0))

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
        # Repair-20260914: physical streams share one capture efficiency;
        # only fossil retained flow earns budget credit. See parameter record.
        bio_coef = float(self.af_biogenic_co2_per_tce)
        self._af_biogenic_co2_per_tce = bio_coef
        if bio_coef > 0.0:
            add_carbon_streams(self, m, efficiency, bio_coef)
        else:
            m.captured_gross = Expression(
                m.I, m.T, rule=lambda mm, i, t: mm.captured[i, t])
            m.fossil_flow_dsa = Expression(
                m.PS_dsa, m.T, rule=lambda mm, i, s, t: mm.f_p_dsa[i, s, t])
            m.fossil_flow_eor = Expression(
                m.PS_eor, m.T, rule=lambda mm, i, s, t: mm.f_p_eor[i, s, t])

        m.capture_by_design = Constraint(
            m.I, m.T, rule=lambda mm, i, t: mm.captured_gross[i, t] <= mm.k_ccs[i, t]
        )
        # The single, sourced capture-fraction ceiling. A per-plant calendar ramp
        # (CCS_SCALE_LIMITS / capture_rollout) was removed on 2026-09-12: it bound
        # in 0 of 4,851 plant-periods and acted on the wrong object -- see config_v5.
        # Applies to the BUDGET caliber: at most `efficiency` of the accounted CO2
        # can be removed. The gross flow is bounded separately, by the design
        # capacity above, because the biogenic part is not part of co2_total.
        m.capture_by_emission = Constraint(
            m.I,
            m.T,
            rule=lambda mm, i, t: mm.captured[i, t] <= efficiency * mm.co2_total[i, t],
        )
        m.capture_minimum_load = Constraint(
            m.I,
            after,
            rule=lambda mm, i, t: mm.captured_gross[i, t]
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
            # The pipeline and the storage site see the GROSS flow (see above).
            return (
                sum(mm.f_p_dsa[i, s, t] for s in dsa_by_plant[i])
                + sum(mm.f_p_eor[i, s, t] for s in eor_by_plant[i])
                == mm.captured_gross[i, t]
            )
        m.plant_flow_balance = Constraint(m.I, m.T, rule=plant_flow_balance)

        mt_to_kt = float(cfg.STORAGE_MT_TO_KT)
        rate_scale = float(cfg.STORAGE_RATE_SCALE)
        capacity_scale = float(cfg.STORAGE_CUMULATIVE_SCALE)
        dsa_capacity = (self.storage_by_idx["dsa_capacity"] * mt_to_kt * capacity_scale).to_dict()
        eor_capacity = (self.storage_by_idx["eor_capacity"] * mt_to_kt * capacity_scale).to_dict()
        # P1-3: cap the (summed theoretical maximum) raster rate by a well-life
        # depletion bound, so the rate constraint cannot be looser than physics.
        depletion_years = float(getattr(cfg, "STORAGE_RATE_DEPLETION_YEARS", 30.0))
        n_wells = float(getattr(cfg, "STORAGE_MAX_WELLS_PER_NODE", 50))
        mt_per_well = float(getattr(cfg, "STORAGE_RATE_PER_WELL_MT_YR", 0.7))
        well_cap = n_wells * mt_per_well * mt_to_kt

        def _capped_rate(column, capacity):
            """Raw raster rate, bounded by well count and by well-life depletion."""
            raw = (self.storage_by_idx[column] * mt_to_kt * rate_scale).to_dict()
            return {
                s: min(float(raw.get(s, 0.0)),
                       well_cap,
                       float(capacity.get(s, 0.0)) / depletion_years)
                for s in raw
            }
        dsa_rate = _capped_rate("dsa_rate", dsa_capacity)
        eor_rate = _capped_rate("eor_rate", eor_capacity)
        # Publish the EFFECTIVE caps so the results layer reports utilisation against
        # the number the constraint actually enforces (2026-09-13). Previously
        # _extract_flow_results recomputed the RAW raster rate, so
        # dsa_rate_utilization / eor_rate_utilization / max_sink_rate_utilization
        # were divided by a looser bound than the one binding the model -- the
        # reported utilisation was understated whenever the well-count or
        # well-life cap was the active one.
        self._storage_effective_rate = {"dsa": dsa_rate, "eor": eor_rate}
        self._storage_effective_capacity = {
            "dsa": dsa_capacity,
            "eor": eor_capacity,
        }
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

        # P1-2: only the retained share of EOR-bound CO2 counts as mitigation.
        # EOR returns produced CO2 to the reservoir, so gross injection is not net
        # storage; the flow still pays transport/storage and still earns the EOR
        # credit, only the mitigation credit is scaled (see config_v5 for the basis
        # discussion and sources).
        eor_retention = float(cfg.CCS_PARAMS.get("eor_storage_retention", 1.0))
        m.net_emission = Constraint(
            m.I,
            m.T,
            rule=lambda mm, i, t: mm.co2_net[i, t]
            == mm.co2_total[i, t]
            - sum(mm.fossil_flow_dsa[i, s, t] for s in dsa_by_plant[i])
            - eor_retention * sum(mm.fossil_flow_eor[i, s, t] for s in eor_by_plant[i]),
        )

    def _demand_and_target_constraints(self, m):
        cfg = self.config

        if self.regional_demand_enabled:
            # P0-4 v3: replace the single national balance with a MARKET-NODE
            # balance. (1) and (2) together already conserve the national total,
            # so a separate national balance would be redundant and is
            # deliberately not added.
            def node_balance(mm, j, t):
                year = self.years[t]
                national_kt = (
                    float(self.demand_path[year]) * 1000.0
                    * self.clinker_ratio_path[year]
                )
                target = self.dem_node_shares[year].get(int(j), 0.0) * national_kt
                return sum(mm.f_dem[i, j, t] for i in self.dem_arcs_by_node[j]) == target

            m.demand_node_balance = Constraint(m.DEM_NODE, m.T, rule=node_balance)

            def plant_output_balance(mm, i, t):
                # what a plant produces must be shipped somewhere
                return (
                    sum(mm.f_dem[i, j, t] for j in self.dem_arcs_by_plant[i])
                    == self.cap[i] * mm.u[i, t]
                )

            m.plant_output_balance = Constraint(m.I, m.T, rule=plant_output_balance)
            self._national_demand_balance_enabled = False
        else:
            def demand_balance(mm, t):
                year = self.years[t]
                target = float(self.demand_path[year]) * 1000.0 * self.clinker_ratio_path[year]
                return sum(self.cap[i] * mm.u[i, t] for i in self.I) == target
            m.demand_balance = Constraint(m.T, rule=demand_balance)
            self._national_demand_balance_enabled = True

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

    def _terminal_charge_factor(self, asset, year):
        """R6 terminal-value arm (registered 2026-09-14; derivation and guard in
        parameters/terminal_value_commitment_20260914.md).

        Central mode "none" charges stock investments in full at the decision
        year. Mode "annuity_consistent_guarded" charges only the within-horizon
        share of the asset's levelized cost:
            factor = A(min(L, end+1-y)) / A(L),  A(n) = sum_{k=0}^{n-1} (1+d)^-k
        which is the OSeMOSYS DM=1 / TIMES / MESSAGEix end-of-horizon factor.
        Guard: vintages whose in-horizon service window is shorter than the
        model's own commitment caliber get no salvage (factor = 1), blocking
        near-free end-of-horizon investment.
        """
        cfg = self.config
        if str(getattr(cfg, "TERMINAL_VALUE_MODE", "none")) != "annuity_consistent_guarded":
            return 1.0
        lives = getattr(cfg, "TERMINAL_VALUE_ASSET_LIVES", {"ccs": 25, "renewal": 40})
        life = int(lives[asset])
        end_year = int(self.years[-1])
        in_service = end_year + 1 - int(year)
        min_service = int(getattr(cfg, "TERMINAL_VALUE_MIN_INHORIZON_SERVICE", 15))
        if in_service < min_service or in_service >= life:
            return 1.0
        d = float(cfg.DISCOUNT_RATE)
        base = 1.0 - (1.0 + d) ** (-1.0)
        a_in = (1.0 - (1.0 + d) ** (-in_service)) / base
        a_full = (1.0 - (1.0 + d) ** (-life)) / base
        return a_in / a_full

    def _cost_components(self, mm, t):
        cfg = self.config
        year = self.years[t]
        weight = self.period_weight[year]
        tce = float(cfg.TCE_PER_T_CLINKER)
        ccs = cfg.CCS_PARAMS
        # P0-1: one decline curve for the whole CCS chain (Mao's alpha/beta are
        # full-chain); the size effect is a continuous power law, and O&M now also
        # carries a (weaker) size term.
        decline = float(
            cfg.CCS_COST_DECLINE_SCENARIOS[cfg.CCS_COST_DECLINE_CASE][year]
        )
        offshore_pipeline = float(cfg.OFFSHORE_PARAMS.get("pipeline_cost_factor", 1.0))
        offshore_storage = float(cfg.OFFSHORE_PARAMS.get("storage_cost_factor", 1.0))

        ccs_capex = self._terminal_charge_factor("ccs", year) * sum(
            float(ccs["capture_investment"])
            * decline
            * self.plant_ccs_cost_multiplier[i]
            * mm.ccs_new_design[i, t]
            for i in self.I
        )
        ccs_opex = weight * float(ccs["capture_om"]) * decline * sum(
            # O&M is a service cost of the flow the capture unit actually treats,
            # i.e. the GROSS flow (2026-09-13). With AF_BIOGENIC_CO2_PER_TCE = 0 this
            # equals `captured` and reproduces the previous behaviour.
            self.plant_ccs_om_multiplier[i] * mm.captured_gross[i, t] for i in self.I
        )
        same_site_renewal_capex = self._terminal_charge_factor(
            "renewal", year
        ) * float(
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

        # AF cost on the model's own unit (2026-09-13): CNY per (tce/yr) of ADDED
        # nameplate handling capacity, and CNY per tce actually handled. The old
        # form AF_INVESTMENT / TCE_PER_T_CLINKER hid the conversion and carried a
        # source-caliber error -- see config_v5.
        af_capex = float(cfg.AF_INVESTMENT_CNY_PER_TCE) * sum(
            mm.af_add[i, t] for i in self.I
        )
        af_opex = weight * float(cfg.AF_OM_CNY_PER_TCE) * sum(
            mm.af_supply[i, t] for i in self.I
        )
        coal_price = float(cfg.COAL_PRICE_SCHEDULE.get(year, cfg.COAL_PRICE))
        af_price = float(cfg.AF_FUEL_PRICE[year])
        af_fuel_delta = weight * (af_price - coal_price) * sum(
            mm.af_supply[i, t] for i in self.I
        )
        baseline_fuel = weight * coal_price * tce * sum(
            self.cap[i] * mm.u[i, t] for i in self.I
        )

        # The same decline curve applies to transport and storage unit costs.
        pipeline_unit = (
            float(ccs["pipeline_investment"]) + float(ccs.get("pipeline_om", 0.0))
        ) * decline
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
        # P0-4: clinker delivery to demand nodes. Distance is a parameter and the
        # loader has already resolved it into a segmented per-tonne-km rate, so the
        # term is linear. kt x CNY/t = kCNY, the same unit as every other component.
        clinker_transport = (
            weight * sum(
                mm.f_dem[i, j, t] * self.dem_arc_cost_per_t[(i, j)]
                for i, j in self.dem_arcs
            )
            if self.regional_demand_enabled
            else 0.0
        )
        dsa_storage = weight * float(ccs["dsa_cost"]) * decline * sum(
            mm.f_p_dsa[i, s, t]
            * (offshore_storage if self.is_offshore.get(s, False) else 1.0)
            for i, s in self.ps_dsa
        )
        eor_storage = weight * float(ccs["eor_storage_cost"]) * decline * sum(
            mm.f_p_eor[i, s, t]
            * (offshore_storage if self.is_offshore.get(s, False) else 1.0)
            for i, s in self.ps_eor
        )
        eor_credit = -weight * float(ccs["eor_revenue"]) * sum(
            mm.f_p_eor[i, s, t] for i, s in self.ps_eor
        )
        # Dispatch fuel cost, DEVIATION form: the omitted mean term
        # (coal_price x ef_mean x D_t) is a known constant given the demand path,
        # so charging only the deviation leaves the optimum unchanged while keeping
        # the reported level comparable to v4. See config_v5 for the identity.
        dispatch_fuel = 0.0
        if bool(getattr(cfg, "INCLUDE_DISPATCH_FUEL_COST", False)):
            coal_ef = float(getattr(cfg, "COAL_EF_TCO2_PER_TCE", 2.6604))
            price = float(cfg.COAL_PRICE_SCHEDULE.get(year, cfg.COAL_PRICE))
            dispatch_fuel = (
                weight * price * (1.0 - float(self.ee_path[year])) / coal_ef
                * sum(
                    (self.plant_fuel_ef[i] - self.fuel_ef_mean)
                    * self.cap[i] * mm.u[i, t]
                    for i in self.I
                )
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
        # P0-3: plant fixed annual operating cost, charged per tonne of annual capacity
        # for every line in operation (a flow, so period-weighted). Reported separately
        # from the mitigation terms because its magnitude dwarfs them.
        capacity_retention = (
            weight * float(cfg.PLANT_FIXED_OPERATING_COST)
            * sum(self.cap[i] * mm.y[i, t] for i in self.I)
        )
        components = {
            "capacity_retention": capacity_retention,
            "ccs_capex": ccs_capex,
            "ccs_opex": ccs_opex,
            "same_site_renewal_capex": same_site_renewal_capex,
            "early_retirement": early_retirement,
            "af_capex": af_capex,
            "af_opex": af_opex,
            "dispatch_fuel": dispatch_fuel,
            "fuel": fuel,
            "transport": transport,
            "clinker_transport": clinker_transport,
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
        opts = dict(self.config.SOLVER_OPTIONS)
        if options:
            opts.update(options)
        self._solver_options = dict(opts)
        with tempfile.NamedTemporaryFile(suffix=".mps", delete=False) as file:
            mps_path = file.name
        print("  [solver] Writing final model to MPS...")
        self.model.write(mps_path, io_options={"symbolic_solver_labels": True})
        solver_name = str(solver or self.config.SOLVER).lower()
        if solver_name in {"highs", "highspy"}:
            return self._solve_highs(mps_path, opts, mip_start)

        import gurobipy as gp

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

    def _solve_highs(self, mps_path, opts, mip_start):
        import highspy

        highs = highspy.Highs()
        for key, setting in _highs_options(opts).items():
            status = highs.setOptionValue(key, setting)
            if status != highspy.HighsStatus.kOk:
                raise ValueError(f"HiGHS rejected option {key}={setting!r}")
        if highs.readModel(mps_path) != highspy.HighsStatus.kOk:
            raise RuntimeError(f"HiGHS could not read exported model {mps_path}")
        applied_start = 0
        if mip_start:
            indices = []
            values = []
            for name, start_value in mip_start.items():
                status, index = highs.getColByName(str(name))
                if status != highspy.HighsStatus.kOk or index < 0:
                    continue
                try:
                    values.append(float(start_value))
                    indices.append(index)
                    applied_start += 1
                except (TypeError, ValueError):
                    continue
            if indices:
                highs.setSolution(
                    len(indices),
                    np.asarray(indices, dtype=np.int32),
                    np.asarray(values, dtype=np.float64),
                )
        self._last_mip_start_applied = applied_start
        started = time.time()
        try:
            run_status = highs.run()
        except KeyboardInterrupt:
            # HiGHS may consume SIGINT inside native code and only return the
            # pending Python interrupt after it has produced a valid terminal
            # status. Preserve the available bound/incumbent diagnostics.
            print("  [solver] Interrupt received; preserving available HiGHS results.")
            run_status = highspy.HighsStatus.kWarning
        runtime = time.time() - started
        if run_status == highspy.HighsStatus.kError:
            raise RuntimeError("HiGHS returned an error while solving the model")
        model_status = highs.getModelStatus()
        status_map = {
            highspy.HighsModelStatus.kOptimal: "optimal",
            highspy.HighsModelStatus.kInfeasible: "infeasible",
            highspy.HighsModelStatus.kUnbounded: "unbounded",
            highspy.HighsModelStatus.kUnboundedOrInfeasible: "infeasibleOrUnbounded",
            highspy.HighsModelStatus.kTimeLimit: "timeLimit",
            highspy.HighsModelStatus.kIterationLimit: "noSolution",
            highspy.HighsModelStatus.kMemoryLimit: "noSolution",
            highspy.HighsModelStatus.kSolutionLimit: "suboptimal",
            highspy.HighsModelStatus.kInterrupt: "interrupted",
            highspy.HighsModelStatus.kHighsInterrupt: "interrupted",
        }
        status = status_map.get(model_status, "unknown")
        if model_status == highspy.HighsModelStatus.kInfeasible:
            try:
                highs.writeIisModel(mps_path.replace(".mps", "_iis.mps"))
            except Exception as exc:
                print(f"  IIS computation failed: {exc}")
        self._gm = _HighsResultAdapter(highs, runtime)
        self._highs = highs
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

        objective = self._gm.ObjVal if self._gm.SolCount > 0 else None
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

    def _captured_gross_value(self, plant_id, t):
        """Physical CO2 flow to transport/storage at a plant-period.

        Budget caliber `captured` plus biogenic CO2 captured in the same
        treated annual production streams, at the same capture efficiency. With
        AF_BIOGENIC_CO2_PER_TCE = 0 (central) this is exactly `captured`. Kept as a
        helper so the results layer cannot quietly report one caliber under the
        other's name.
        """
        captured = self._solution_value("captured", plant_id, t)
        if self.af_biogenic_co2_per_tce <= 0.0:
            return captured
        efficiency = float(
            self.config.CCS_PARAMS.get("capture_efficiency", 0.90)
        )
        af_captured_energy = self._solution_value(
            "af_captured_energy", plant_id, t
        )
        return captured + efficiency * self.af_biogenic_co2_per_tce * af_captured_energy

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
        decline = float(
            cfg.CCS_COST_DECLINE_SCENARIOS[cfg.CCS_COST_DECLINE_CASE][year]
        )
        offshore_pipeline = float(cfg.OFFSHORE_PARAMS.get("pipeline_cost_factor", 1.0))
        offshore_storage = float(cfg.OFFSHORE_PARAMS.get("storage_cost_factor", 1.0))

        ccs_capex = self._terminal_charge_factor("ccs", year) * sum(
            float(ccs["capture_investment"])
            * decline
            * self.plant_ccs_cost_multiplier[i]
            * self._solution_value("ccs_new_design", i, t)
            for i in self.I
        )
        commercial_capture = sum(self._solution_value("captured", i, t) for i in self.I)
        # Gross-flow basis, matching the objective (2026-09-14): with phi = 0 this
        # equals `captured`; with phi > 0 the biogenic part travels through the
        # capture unit too and must pay O&M. af_captured_energy is a Var, so its
        # solution value is available directly.
        bio_phi = float(getattr(self, "af_biogenic_co2_per_tce", 0.0))

        def _captured_gross_value(i):
            val = self._solution_value("captured", i, t)
            if bio_phi > 0.0:
                val += float(ccs.get("capture_efficiency", 0.90)) * bio_phi * (
                    self._solution_value("af_captured_energy", i, t)
                )
            return val

        ccs_opex = weight * float(ccs["capture_om"]) * decline * sum(
            self.plant_ccs_om_multiplier[i] * _captured_gross_value(i)
            for i in self.I
        )
        same_site_renewal_capex = self._terminal_charge_factor(
            "renewal", year
        ) * float(
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
        af_capex = float(cfg.AF_INVESTMENT_CNY_PER_TCE) * af_add
        af_opex = weight * float(cfg.AF_OM_CNY_PER_TCE) * af_supply
        coal_price = float(cfg.COAL_PRICE_SCHEDULE.get(year, cfg.COAL_PRICE))
        af_price = float(cfg.AF_FUEL_PRICE[year])
        af_fuel_delta = weight * (af_price - coal_price) * af_supply
        production = sum(self.cap[i] * self._solution_value("u", i, t) for i in self.I)
        baseline_fuel = weight * coal_price * tce * production

        pipeline_unit = (
            float(ccs["pipeline_investment"]) + float(ccs.get("pipeline_om", 0.0))
        ) * decline
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
        clinker_transport = (
            weight * sum(
                self._solution_value("f_dem", i, j, t) * self.dem_arc_cost_per_t[(i, j)]
                for i, j in self.dem_arcs
            )
            if self.regional_demand_enabled
            else 0.0
        )
        dsa_storage = weight * float(ccs["dsa_cost"]) * decline * sum(
            self._solution_value("f_p_dsa", i, s, t)
            * (offshore_storage if self.is_offshore.get(s, False) else 1.0)
            for i, s in self.ps_dsa
        )
        eor_storage = weight * float(ccs["eor_storage_cost"]) * decline * sum(
            self._solution_value("f_p_eor", i, s, t)
            * (offshore_storage if self.is_offshore.get(s, False) else 1.0)
            for i, s in self.ps_eor
        )
        eor_credit = -weight * float(ccs["eor_revenue"]) * sum(
            self._solution_value("f_p_eor", i, s, t) for i, s in self.ps_eor
        )
        dispatch_fuel = 0.0
        if bool(getattr(cfg, "INCLUDE_DISPATCH_FUEL_COST", False)):
            coal_ef = float(getattr(cfg, "COAL_EF_TCO2_PER_TCE", 2.6604))
            price = float(cfg.COAL_PRICE_SCHEDULE.get(year, cfg.COAL_PRICE))
            dispatch_fuel = (
                weight * price * (1.0 - float(self.ee_path[year])) / coal_ef
                * sum(
                    (self.plant_fuel_ef[i] - self.fuel_ef_mean)
                    * self.cap[i] * self._solution_value("u", i, t)
                    for i in self.I
                )
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
        capacity_retention = (
            weight * float(cfg.PLANT_FIXED_OPERATING_COST)
            * sum(self.cap[i] * self._solution_value("y", i, t) for i in self.I)
        )
        components = {
            "capacity_retention": capacity_retention,
            "ccs_capex": ccs_capex,
            "ccs_opex": ccs_opex,
            "same_site_renewal_capex": same_site_renewal_capex,
            "early_retirement": early_retirement,
            "af_capex": af_capex,
            "af_opex": af_opex,
            "dispatch_fuel": dispatch_fuel,
            "fuel": fuel,
            "transport": transport,
            "clinker_transport": clinker_transport,
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
            # 2026-09-13: the GROSS (physical) flow the capture unit, pipeline and
            # storage site actually handle. Equals `capture` while
            # AF_BIOGENIC_CO2_PER_TCE = 0.
            capture_gross = sum(
                self._captured_gross_value(i, t) for i in self.I
            )
            observed = sum(self._observed_pilot_capture(i, t) for i in self.I)
            production = sum(self.cap[i] * u[i] for i in self.I)
            operating_capacity = sum(self.cap[i] * y[i] for i in self.I)
            af_supply = sum(self._solution_value("af_supply", i, t) for i in self.I)
            # 2026-09-13: the AF rate must be quoted against the SAME heat demand
            # the constraints use, otherwise the reported rate is divided by a
            # different number than the ceiling it is compared with. `fuel_energy`
            # is the modeled heat demand H = sum_i h_i*(1-EE)*Q_i; the legacy flat
            # caliber is reported alongside so the two cannot be confused again.
            fuel_energy = sum(
                self.plant_heat_intensity[i]
                * (1.0 - float(self.ee_path[year]))
                * self.cap[i]
                * u[i]
                for i in self.I
            )
            fuel_energy_flat_caliber = production * tce
            arm_average = sum(
                province_capacity[p] * float(self.arm_path.get((p, year), 0.0)) for p in self.P
            ) / max(sum(province_capacity.values()), 1e-9)
            results["summary"][year] = {
                "gross_co2_kt": gross,
                "net_co2_kt": net,
                "net_co2_commercial_kt": net,
                "captured_co2_kt": capture,
                "commercial_captured_co2_kt": capture,
                "captured_co2_gross_kt": capture_gross,
                "captured_biogenic_co2_kt": max(capture_gross - capture, 0.0),
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
                "total_fuel_energy_flat_caliber_ktce": fuel_energy_flat_caliber,
                "fuel_energy_caliber": str(self.af_energy_caliber),
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

        # Cost calibers (2026-09-12, checklist item 4; T1 renamed 2026-09-13).
        # After the demand-side layer, the headline total is only ~1/3 abatement
        # cost, so a single number is not interpretable. The components are grouped
        # into four calibers that must sum EXACTLY to the reported total; "planning
        # regret" (C_S - C_J) is a CROSS-RUN quantity and is not produced here.
        #
        # RENAME: T1 was "incremental_abatement_cost". That name claims the bucket
        # IS an incremental abatement cost, but it also contains af_capex /
        # af_opex / early_retirement and a signed EOR credit, and it is measured
        # against a counterfactual this single run does not contain. It is an
        # EXPENDITURE on mitigation measures, so it is now named as one. Dividing
        # it by cumulative abatement (kt) is a separate step the writer must do and
        # must label as such.
        _C1_MEASURES = ("ccs_capex", "ccs_opex", "transport", "dsa_storage",
                        "eor_storage", "eor_revenue_credit", "early_retirement",
                        "af_capex", "af_opex")
        _C2_TURNOVER = ("capacity_retention", "same_site_renewal_capex")
        _C3_LOGISTICS = ("clinker_transport",)
        _C4_DISPATCH = ("dispatch_fuel",)
        _grouped = set(_C1_MEASURES) | set(_C2_TURNOVER) | set(_C3_LOGISTICS) | set(_C4_DISPATCH)
        _other = {k: v for k, v in component_totals.items() if k not in _grouped}
        _t1 = sum(component_totals.get(k, 0.0) for k in _C1_MEASURES)
        calibers = {
            "measure_expenditure_kCNY": _t1,
            # Deprecated alias for pre-2026-09-13 scripts. Same number, misleading
            # name; retained so historical consumers do not silently read zero.
            "incremental_abatement_cost_kCNY": _t1,
            "measure_expenditure_components": list(_C1_MEASURES),
            "capacity_turnover_cost_kCNY": sum(component_totals.get(k, 0.0) for k in _C2_TURNOVER),
            "market_logistics_cost_kCNY": sum(component_totals.get(k, 0.0) for k in _C3_LOGISTICS),
            "dispatch_efficiency_kCNY": sum(component_totals.get(k, 0.0) for k in _C4_DISPATCH),
            "other_kCNY": sum(_other.values()),
            "other_components": _other,
        }
        calibers["model_cost_kCNY"] = sum(
            component_totals.values()
        )
        calibers["closure_check_kCNY"] = calibers["model_cost_kCNY"] - objective_check
        calibers["reported_total_kCNY"] = objective_check
        calibers["caliber_note"] = (
            "measure_expenditure = CCS + CO2 transport/storage + AF + early "
            "retirement + EOR credit. This is EXPENDITURE on mitigation measures, "
            "NOT an incremental abatement cost: it is not differenced against a "
            "counterfactual and it mixes capital, operating and a signed revenue "
            "offset. Dividing it by cumulative abatement to quote a unit cost is a "
            "separate step that must be labelled as such. "
            "capacity_turnover_cost = plant fixed operating cost + "
            "same-site renewal capex; market_logistics_cost = clinker transport; "
            "dispatch_efficiency = deviation-form fuel term. Sum closes to the "
            "reported total by construction (closure_check must be 0). "
            "Planning regret (C_S - C_J) is computed across the paired joint vs "
            "stepwise runs, not in a single run."
        )
        results["cost_calibers"] = calibers

        # Slack vs headroom (checklist item 5). The cumulative budget and the
        # 2060 endpoint cap are HARD <= constraints, so "slack" (exceedance) is
        # always 0 and is a diagnostic of infeasibility, while "headroom"
        # (target - actual) is the economically informative quantity. Report both
        # separately and state which constraint binds.
        _cum_headroom = max(self._cumulative_target - cumulative_actual, 0.0)
        _term_headroom = max(
            self._terminal_2060_cap - results["summary"][2060]["net_co2_kt"], 0.0
        )
        results["cumulative_budget"]["headroom_kt_year"] = _cum_headroom
        results["cumulative_budget"]["terminal_2060_headroom_kt"] = _term_headroom
        results["cumulative_budget"]["binding_constraint"] = (
            "cumulative_budget"
            if _cum_headroom <= max(1.0, 1e-6 * abs(self._cumulative_target))
            else ("terminal_2060_cap" if _term_headroom <= 1.0 else "neither")
        )
        results["constraint_headroom"] = {
            "cumulative_budget_target_kt_year": self._cumulative_target,
            "cumulative_budget_actual_kt_year": cumulative_actual,
            "cumulative_budget_headroom_kt_year": _cum_headroom,
            "cumulative_budget_exceedance_kt_year": max(cumulative_actual - self._cumulative_target, 0.0),
            "terminal_2060_cap_kt": self._terminal_2060_cap,
            "terminal_2060_actual_kt": results["summary"][2060]["net_co2_kt"],
            "terminal_2060_headroom_kt": _term_headroom,
            "terminal_2060_exceedance_kt": max(
                results["summary"][2060]["net_co2_kt"] - self._terminal_2060_cap, 0.0
            ),
            "binding_constraint": results["cumulative_budget"]["binding_constraint"],
            "note": (
                "Both constraints are hard <=, so exceedance is 0 when feasible. "
                "`binding_constraint` is derived from the realized headrooms, not "
                "assumed: whichever headroom is at the tolerance binds. (Empirically "
                "the converged B40 baseline binds the CUMULATIVE budget while the 2060 "
                "endpoint cap stays slack by tens of thousands of kt -- but a "
                "low-quality incumbent can bind the endpoint instead, so always read "
                "the field rather than this note.)"
            ),
        }

        # 2026-09-12: indicative cost of the exogenous mitigation paths (EE / ARM
        # / CCR). Their abatement enters the carbon budget but their costs are
        # NOT part of the objective (COST_BOUNDARY declaration). The anchors are
        # the register's v4 unit costs (EE 60/3.0, ARM 33/1.5+15, LCC 40/2.5),
        # whose rate normalization the sources do not define; the convention here
        # is investment proportional to each period's rate increment and O&M
        # proportional to the realized rate. ORDER-OF-MAGNITUDE diagnostic only
        # -- not a source-anchored cost estimate; do not quote as a cost result.
        ee_prev, arm_prev = 0.0, 0.0
        ratio_prev = float(cfg.BASELINE_CLINKER_RATIO)
        ratio_terminal = float(self.clinker_ratio_path[self.years[-1]])
        ratio_span = max(ratio_prev - ratio_terminal, 1e-9)
        cement_capacity_kt = total_capacity / max(ratio_prev, 1e-9)
        indicative_nominal = {"energy_efficiency": 0.0, "arm": 0.0, "ccr_clinker_ratio": 0.0}
        indicative_discounted = {k: 0.0 for k in indicative_nominal}
        for year in self.years:
            summary = results["summary"][year]
            ee = float(self.ee_path[year])
            arm = float(summary["avg_arm_realized"])
            ratio = float(self.clinker_ratio_path[year])
            clinker_kt = float(summary["clinker_production_kt"])
            cement_kt = clinker_kt / max(ratio, 1e-9)
            weight = float(self.period_weight[year])
            ee_inv = float(cfg.EE_INVESTMENT) * max(ee - ee_prev, 0.0) * total_capacity
            ee_om = weight * float(cfg.EE_OM) * ee * clinker_kt
            arm_inv = float(cfg.ARM_INVESTMENT) * max(arm - arm_prev, 0.0) * total_capacity
            arm_om = weight * (float(cfg.ARM_OM) + float(cfg.ARM_LOGISTICS)) * arm * clinker_kt
            ccr_inv = float(cfg.LCC_INVESTMENT) * max(ratio_prev - ratio, 0.0) * cement_capacity_kt
            ccr_om = (
                weight
                * float(cfg.LCC_OM)
                * (ratio_prev - ratio) / ratio_span
                * cement_kt
            )
            discount = 1.0 / (1.0 + float(cfg.DISCOUNT_RATE)) ** (year - self.years[0])
            for name, amount in (
                ("energy_efficiency", ee_inv + ee_om),
                ("arm", arm_inv + arm_om),
                ("ccr_clinker_ratio", ccr_inv + ccr_om),
            ):
                indicative_nominal[name] += amount
                indicative_discounted[name] += amount * discount
            ee_prev, arm_prev, ratio_prev = ee, arm, ratio
        indicative_total = sum(indicative_discounted.values())
        results["exogenous_path_indicative_costs"] = {
            "convention_note": (
                "Reporting-only diagnostics (not in the objective). Investment is "
                "proportional to each period's rate increment, O&M to the realized "
                "rate; the register's v4 unit-cost anchors do not define a rate "
                "normalization, so treat these as order-of-magnitude only."
            ),
            "nominal_kCNY": indicative_nominal,
            "discounted_kCNY": indicative_discounted,
            "total_discounted_kCNY": indicative_total,
            "share_of_discounted_system_cost": (
                indicative_total / objective if objective > 0 else 0.0
            ),
        }

        self._extract_flow_results(results)
        self._extract_plant_results(results)
        self._extract_external_and_resource_results(results)
        self._extract_regional_demand_results(results)
        self._extract_capacity_decline_diagnostic(results)
        return results

    def _extract_regional_demand_results(self, results):
        """P0-4 v3 outputs: delivered market-node distances and provincial flows.

        These make the regional layer falsifiable: the realised delivery-distance
        distribution can be checked against the observed 200-300 km market radius,
        and the flows aggregated to provinces against the documented corridors
        (Guangxi->Guangdong, Anhui->Jiangsu/Zhejiang).
        """
        if not self.regional_demand_enabled:
            results["regional_demand"] = {"enabled": False}
            return

        plant_province = {
            int(r.plant_id): str(r.province)
            for r in self.plants[["plant_id", "province"]].itertuples(index=False)
        }

        per_period, route_rows = {}, []
        for t in self.T:
            year = self.years[t]
            total_kt, cost_kcny, weighted_km = 0.0, 0.0, 0.0
            distances, inter_prov, intra_kt = [], {}, 0.0
            for i, j in self.dem_arcs:
                flow = self._solution_value("f_dem", i, j, t)
                if flow <= 1e-9:
                    continue
                km = self.dem_arc_distance[(i, j)]
                rate = self.dem_arc_cost_per_t[(i, j)]
                total_kt += flow
                cost_kcny += flow * rate
                weighted_km += flow * km
                distances.append((km, flow))
                src = plant_province.get(int(i), "")
                dst = self.dem_node_province.get(int(j), "")
                if src and src == dst:
                    intra_kt += flow
                else:
                    inter_prov[(src, dst)] = inter_prov.get((src, dst), 0.0) + flow
                route_rows.append({
                    "year": year, "plant_id": int(i), "node_id": int(j),
                    "from_province": src, "to_province": dst,
                    "flow_kt": float(flow), "distance_km": float(km),
                    "transport_cost_cny_per_t": float(rate),
                })
            if distances:
                distances.sort()
                kms = np.array([d[0] for d in distances], dtype=float)
                wts = np.array([d[1] for d in distances], dtype=float)
                order = np.argsort(kms)
                cum = np.cumsum(wts[order]) / wts.sum()
                kms_sorted = kms[order]
                p50 = float(kms_sorted[np.searchsorted(cum, 0.50)])
                p90 = float(kms_sorted[np.searchsorted(cum, 0.90)])
                max_km = float(kms_sorted[-1])
            else:
                p50 = p90 = max_km = 0.0
            inter_total = sum(inter_prov.values())
            per_period[str(year)] = {
                "delivered_kt": total_kt,
                "transport_cost_kCNY": cost_kcny,
                "weighted_avg_km": weighted_km / total_kt if total_kt > 1e-9 else 0.0,
                "p50_km": p50, "p90_km": p90, "max_km": max_km,
                "intra_provincial_kt": intra_kt,
                "intra_provincial_share": intra_kt / total_kt if total_kt > 1e-9 else 0.0,
                "inter_provincial_kt": inter_total,
                "inter_provincial_share": inter_total / total_kt if total_kt > 1e-9 else 0.0,
            }
            results.setdefault("inter_provincial_flows_kt", {})[str(year)] = {
                f"{s}->{d}": v for (s, d), v in sorted(inter_prov.items(), key=lambda kv: -kv[1])
            }

        results["regional_demand"] = {
            "enabled": True,
            "market_unit": "market_node",
            "transport_mode": self.dem_transport_mode,
            "n_market_nodes": len(self.dem_nodes),
            "n_arcs": len(self.dem_arcs),
            "per_period": per_period,
            "inter_provincial_flows_kt": results.get("inter_provincial_flows_kt", {}),
            "validation_target_km": [200.0, 300.0],
        }
        results["clinker_delivery_routes"] = route_rows

    def _extract_capacity_decline_diagnostic(self, results):
        """Change 3: is the model's contraction path inside the observed policy band?

        Reports active capacity by period, the annualised decline rate between
        consecutive periods, and whether each interval sits inside the observed
        2016-2020 band (config.CAPACITY_DECLINE_REFERENCE_ANNUAL). Diagnostic
        only: it never constrains the central solve. The optional constraint
        (MAX_ANNUAL_CAPACITY_DECLINE) is reported when active.
        """
        band = tuple(getattr(self.config, "CAPACITY_DECLINE_REFERENCE_ANNUAL", (0.05, 0.10)))
        active = {
            int(year): float(sum(
                self.cap[i] * float(self._solution_value("y", i, t))
                for i in self.I
            ))
            for t, year in enumerate(self.years)
        }
        per_interval = {}
        years = list(self.years)
        for k in range(1, len(years)):
            prev, cur = years[k - 1], years[k]
            dy = float(cur - prev)
            rate = (1.0 - (active[cur] / active[prev]) ** (1.0 / dy)
                    if active[prev] > 1e-9 else 0.0)
            per_interval[f"{prev}->{cur}"] = {
                "annualised_decline_rate": rate,
                "inside_reference_band": bool(band[0] <= rate <= band[1]),
            }
        results["capacity_decline_diagnostic"] = {
            "note": (
                "Policy-feasibility screen only. Observed 2016-2020 Chinese cement "
                "capacity contraction was about 5-10% per year; the central model "
                "is NOT constrained to that band."
            ),
            "reference_annual_band": list(band),
            "max_annual_capacity_decline_constraint": getattr(
                self.config, "MAX_ANNUAL_CAPACITY_DECLINE", None
            ),
            "active_capacity_kt_by_year": active,
            "per_interval": per_interval,
        }

    def _extract_flow_results(self, results):
        cfg = self.config
        mt_to_kt = float(cfg.STORAGE_MT_TO_KT)
        capacity_scale = float(cfg.STORAGE_CUMULATIVE_SCALE)
        # 2026-09-13: use the EFFECTIVE (well-count and well-life capped) rate that
        # m.dsa_rate_cap / m.eor_rate_cap actually enforce, not the raw raster rate.
        # Falls back to the raw rate only if the constraint builder did not run.
        _eff_rate = getattr(self, "_storage_effective_rate", None)
        if _eff_rate:
            dsa_rate = dict(_eff_rate["dsa"])
            eor_rate = dict(_eff_rate["eor"])
        else:
            rate_scale = float(cfg.STORAGE_RATE_SCALE)
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
                        "fossil_flow_kt": fossil_flow_value(self, route_type, plant_id, storage_idx, t),
                        "biogenic_flow_kt": max(flow - fossil_flow_value(self, route_type, plant_id, storage_idx, t), 0.0),
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
                "flow_capture_gap_kt": total - results["summary"][year]["captured_co2_gross_kt"],
                "fossil_flow_capture_gap_kt": sum(r["fossil_flow_kt"] for r in rows) - commercial,
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
                    self.config.CCS_COST_DECLINE_SCENARIOS[
                        self.config.CCS_COST_DECLINE_CASE
                    ][year]
                ),
                "time_opex_multiplier": float(
                    self.config.CCS_COST_DECLINE_SCENARIOS[
                        self.config.CCS_COST_DECLINE_CASE
                    ][year]
                ),
                "cost_decline_case": str(self.config.CCS_COST_DECLINE_CASE),
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
            "maximum_utilization_change_per_period": None,  # removed in P0-3
            "plant_fixed_operating_cost_cny_per_t_capacity_yr": float(
                self.config.PLANT_FIXED_OPERATING_COST
            ),
            "capacity_retention_cost_reporting": (
                "reported as a separate line; the headline mitigation cost is given "
                "with and without it"
            ),
            "af_technical_tsr_ceiling": float(self.config.AF_TECHNICAL_TSR_CEILING),
            "af_access_allocation_headroom": float(
                self.config.AF_ACCESS_ALLOCATION_HEADROOM
            ),
            "af_expansion_pp_per_period": float(self.config.AF_EXPANSION_PP),
            "ccs_cost_decline_case": str(self.config.CCS_COST_DECLINE_CASE),
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
            # P0-4 v3 distributed market nodes
            "regional_demand_enabled": bool(self.regional_demand_enabled),
            "demand_market_unit": "market_node",
            "demand_market_node_count": int(len(self.dem_nodes)),
            "demand_arc_count": int(len(self.dem_arcs)),
            "demand_transport_mode": self.dem_transport_mode,
            "same_site_renewal_window": str(
                getattr(self.config, "SAME_SITE_RENEWAL_WINDOW", "first_after_expiry")
            ),
            "max_annual_capacity_decline": getattr(
                self.config, "MAX_ANNUAL_CAPACITY_DECLINE", None
            ),
            "national_demand_balance_used": bool(
                getattr(self, "_national_demand_balance_enabled", True)
            ),
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

        # Effective-config dump (checklist item 8, 2026-09-12). Records the values
        # ACTUALLY used by this run, so a switch that silently failed to apply is
        # detectable (a module-vs-instance override bug produced exactly that on
        # 2026-09-12). Distinct from model_assumptions, which is a curated subset.
        def _seg(upper_rate):
            out = []
            for upper, rate in upper_rate:
                out.append([None if upper == float("inf") else float(upper), float(rate)])
            return out
        results["effective_config"] = {
            "carbon_flow_accounting_version": "treated_streams_v2" if self.af_biogenic_co2_per_tce > 0 else "fossil_only_v1",
            "capture_stream_assumption": "annual_segments_with_variable_af_share" if self.af_biogenic_co2_per_tce > 0 else "not_applicable",
            "market_input_provenance": self.data.get("market_input_provenance", {}),
            "model_input_sha256": self.data.get("model_input_sha256"),
            "model_code_sha256": self.data.get("model_code_sha256"),
            "carbon_budget_case": str(self._carbon_budget_case),
            "emission_target_mode": str(self._emission_target_mode),
            # 2026-09-13: the remaining accounting switches the J/S pairing must
            # hold fixed. Without these in the dump, verify_pair_configs.py cannot
            # confirm they matched, and an unrecorded key is not agreement.
            "cumulative_budget_metric": str(
                getattr(self.config, "CUMULATIVE_BUDGET_METRIC", "net_direct")
            ),
            "demand_scenario": str(self.demand_scenario),
            "cost_boundary": str(self.config.COST_BOUNDARY),
            "include_carbon_cost_in_objective": bool(
                self.config.INCLUDE_CARBON_COST_IN_OBJECTIVE
            ),
            "include_full_fuel_cost_in_objective": bool(
                self.config.INCLUDE_FULL_FUEL_COST_IN_OBJECTIVE
            ),
            "planning_mode": str(getattr(self.config, "PLANNING_MODE", "joint")),
            "discount_rate": float(self.config.DISCOUNT_RATE),
            "min_operating_utilization": float(self.config.MIN_OPERATING_UTILIZATION),
            "days_per_year": int(self.config.DAYS_PER_YEAR),
            "plant_fixed_operating_cost_cny_per_t_capacity_yr": float(
                self.config.PLANT_FIXED_OPERATING_COST
            ),
            "early_retirement_cost_cny_per_t_annual_capacity": float(
                self.config.EARLY_RETIREMENT_REPLACEMENT_COST_CNY_PER_T_ANNUAL_CAPACITY
            ),
            "capture_efficiency": float(
                self.config.CCS_PARAMS.get("capture_efficiency", float("nan"))
            ),
            "ccs_cost_decline_case": str(self.config.CCS_COST_DECLINE_CASE),
            "ccs_min_operating_years": int(self.config.CCS_MIN_OPERATING_YEARS),
            "eor_revenue_cny_per_tco2": float(
                self.config.CCS_PARAMS.get("eor_revenue", float("nan"))
            ),
            "eor_revenue_reference_cny_per_tco2": float(
                getattr(self.config, "EOR_REVENUE_REFERENCE", 80.0)
            ),
            "eor_storage_cost_cny_per_tco2": float(
                self.config.CCS_PARAMS.get("eor_storage_cost", float("nan"))
            ),
            "eor_storage_retention": float(
                self.config.CCS_PARAMS.get("eor_storage_retention", float("nan"))
            ),
            "dsa_cost_cny_per_tco2": float(
                self.config.CCS_PARAMS.get("dsa_cost", float("nan"))
            ),
            "same_site_renewal_window": str(
                getattr(self.config, "SAME_SITE_RENEWAL_WINDOW", "first_after_expiry")
            ),
            "same_site_renewal_max_count": int(
                getattr(self.config, "SAME_SITE_RENEWAL_MAX_COUNT", 1) or 0
            ),
            "same_site_renewal_min_capacity_td": float(
                self.config.SAME_SITE_RENEWAL_MIN_CAPACITY_TD
            ),
            "max_annual_capacity_decline": getattr(
                self.config, "MAX_ANNUAL_CAPACITY_DECLINE", None
            ),
            "max_capacity_decline_per_period": getattr(
                self.config, "MAX_CAPACITY_DECLINE_PER_PERIOD", None
            ),
            "af_technical_tsr_ceiling": float(self.config.AF_TECHNICAL_TSR_CEILING),
            "af_access_allocation_headroom": float(
                self.config.AF_ACCESS_ALLOCATION_HEADROOM
            ),
            # 2026-09-13: the caliber the AF constraints were actually built on, the
            # resulting per-plant heat intensities, and the two AF coefficients in
            # the model's own unit. Dumped so that a run cannot silently use a
            # different caliber than the one the writer assumes.
            "af_energy_caliber": str(self.af_energy_caliber),
            "af_plant_heat_intensity_tce_per_t": sorted(
                {round(v, 9) for v in self.plant_heat_intensity.values()}
            ),
            "af_expansion_fraction_of_heat": float(
                getattr(
                    self.config,
                    "AF_EXPANSION_FRACTION_OF_HEAT",
                    self.config.AF_EXPANSION_PP / 100.0,
                )
            ),
            "af_expansion_pp_per_period": float(self.config.AF_EXPANSION_PP),
            "beta_af": float(self.config.BETA_AF),
            "af_investment_cny_per_tce": float(
                self.config.AF_INVESTMENT_CNY_PER_TCE
            ),
            "af_om_cny_per_tce": float(self.config.AF_OM_CNY_PER_TCE),
            "af_biogenic_co2_per_tce": float(self.af_biogenic_co2_per_tce),
            "coal_ef_tco2_per_tce": float(self.coal_ef),
            "tce_per_t_clinker_legacy": float(self.config.TCE_PER_T_CLINKER),
            "terminal_truncation_window_years": int(
                getattr(self.config, "TERMINAL_TRUNCATION_WINDOW_YEARS", 20)
            ),
            "demand_transport_mode": self.dem_transport_mode,
            "demand_transport_segments": _seg(
                getattr(self.config, "DEMAND_TRANSPORT_COST_SEGMENTS", ())
            ),
            "demand_intra_province_treated_as_zero": False,
            "regional_demand_enabled": bool(self.regional_demand_enabled),
            "demand_market_node_count": int(len(self.dem_nodes)),
            "demand_arc_count": int(len(self.dem_arcs)),
            # Which market-layer build this run used. A different node/arc file is
            # a different spatial model, so a pair built on different builds is not
            # comparable (verify_pair_configs.py treats these as must-match).
            "demand_market_node_file": str(
                Path(str(getattr(self.config, "DEMAND_MARKET_NODE_FILE", ""))).name
            ),
            "demand_market_arc_file": str(
                Path(str(getattr(self.config, "DEMAND_MARKET_ARC_FILE", ""))).name
            ),
            # 2026-09-14: R6 terminal-value arm and storage-rate sensitivity keys.
            # Both are treatments for paired comparisons, so they must be visible
            # to verify_pair_configs.py (must-match) and to result readers.
            "terminal_value_mode": str(
                getattr(self.config, "TERMINAL_VALUE_MODE", "none")
            ),
            "terminal_value_asset_lives": dict(
                getattr(
                    self.config,
                    "TERMINAL_VALUE_ASSET_LIVES",
                    {"ccs": 25, "renewal": 40},
                )
            ),
            "storage_rate_scale": float(
                getattr(self.config, "STORAGE_RATE_SCALE", 1.0)
            ),
            "storage_cumulative_scale": float(
                getattr(self.config, "STORAGE_CUMULATIVE_SCALE", 1.0)
            ),
        }

        # Base-year anchor provenance (checklist item U2, 2026-09-12). The 2025
        # utilization is a CALIBRATION VALUE, not plant-level observed data.
        _gap = self.data.get("baseyear_province_gap_kt") or {}
        _short = {str(k): float(v) for k, v in _gap.items() if float(v) < -1e-6}
        _nat = float(results["summary"][self.years[0]]["clinker_production_kt"])
        results["baseyear_calibration"] = {
            "nature": "calibration value, NOT plant-level observed utilization",
            "construction_chain": [
                "provincial cement output (official statistics) x Liao effective clinker ratio -> provincial clinker",
                "divide by the province's aggregate design annual capacity (t/d x 310)",
                "assign the SAME utilization to every line in the province",
                "truncate at 1.0, then recompute the national base-year clinker ratio from realized output",
            ],
            "province_gap_kt": {str(k): float(v) for k, v in _gap.items()},
            "provinces_truncated": _short,
            "max_abs_province_gap_kt": float(max((abs(v) for v in _gap.values()), default=0.0)),
            "national_reference_production_kt": _nat,
            "note": (
                "A negative gap means the province's clinker demand exceeded its own "
                "capacity and was truncated at u=1. Some provinces' cement output is "
                "met with clinker produced elsewhere, so cement output x ratio is NOT "
                "provincial clinker output; the market transport layer does not repair "
                "this production-side anchor. Report the gap before/after truncation "
                "and do NOT remove it by changing DAYS_PER_YEAR."
            ),
        }

        # End-of-horizon treatment (checklist item 9, 2026-09-12; bias claim
        # withdrawn and exposure quantified 2026-09-13; exposure caliber fixed
        # 2026-09-14). Stock investments are charged ONCE in their decision year
        # in the objective, so the exposure statistic must NOT carry a period
        # weight. (Before 2026-09-14 the CCS arm multiplied by period_weight,
        # inflating the reported exposure ~4-fold -- e.g. central_J 501.5 -> 117.3
        # bn, 86.5% -> 20.2% of measure expenditure.) The direction of the
        # end-of-horizon bias is NOT asserted: charging a near-horizon asset in
        # full while its service is truncated over-costs late investment, but
        # assigning no salvage value at all also removes the option value of
        # waiting, and post-2060 commitments are simply unmodelled. Rather than
        # argue the sign, report the exposure.
        _tv_mode = str(getattr(self.config, "TERMINAL_VALUE_MODE", "none"))
        _trunc_window = float(
            getattr(self.config, "TERMINAL_TRUNCATION_WINDOW_YEARS", 20)
        )
        _last_year = self.years[-1]
        _cutoff_year = _last_year - _trunc_window
        _trunc_capex = {"ccs": 0.0, "renewal": 0.0}
        _salvage_credited = {"ccs": 0.0, "renewal": 0.0}
        for t in self.T:
            year = self.years[t]
            discount = 1.0 / (1.0 + float(self.config.DISCOUNT_RATE)) ** (year - self.years[0])
            _nom_ccs = discount * float(
                self.config.CCS_PARAMS["capture_investment"]
            ) * sum(
                self._solution_value("ccs_new_design", i, t) for i in self.I
            )
            _nom_renew = discount * float(
                self.config.SAME_SITE_RENEWAL_COST_CNY_PER_T_ANNUAL_CAPACITY
            ) * sum(self.cap[i] * self._solution_value("r", i, t) for i in self.I)
            if year >= _cutoff_year:
                _trunc_capex["ccs"] += _nom_ccs
                _trunc_capex["renewal"] += _nom_renew
            _salvage_credited["ccs"] += _nom_ccs * (
                1.0 - self._terminal_charge_factor("ccs", year)
            )
            _salvage_credited["renewal"] += _nom_renew * (
                1.0 - self._terminal_charge_factor("renewal", year)
            )
        _trunc_total = _trunc_capex["ccs"] + _trunc_capex["renewal"]
        _measure_t1 = (
            results.get("cost_calibers", {}).get("measure_expenditure_kCNY")
            if isinstance(results.get("cost_calibers"), dict)
            else None
        )
        results["horizon_terminal_treatment"] = {
            "ccs_commitment_window_years": int(self.config.CCS_MIN_OPERATING_YEARS),
            "ccs_commitment_enforced_within_horizon_only": True,
            "declared_terminal_mode": str(self.config.CCS_TERMINAL_COMMITMENT_MODE),
            "terminal_value_mode": _tv_mode,
            "terminal_value_assigned_to_ccs": _tv_mode != "none",
            "terminal_value_assigned_to_renewal": _tv_mode != "none",
            "terminal_value_credited_kCNY": {
                "ccs_capture_investment": _salvage_credited["ccs"],
                "same_site_renewal": _salvage_credited["renewal"],
                "total": _salvage_credited["ccs"] + _salvage_credited["renewal"],
            },
            "renewal_capex_charged_in_full_at_renewal": _tv_mode == "none",
            "truncation_window_years": int(_trunc_window),
            "truncation_cutoff_year": int(_cutoff_year),
            "truncated_capex_discounted_kCNY": {
                "ccs_capture_investment": _trunc_capex["ccs"],
                "same_site_renewal": _trunc_capex["renewal"],
                "total": _trunc_total,
            },
            "truncated_capex_caliber": (
                "lump-sum (objective caliber): stock investments counted once at "
                "their decision-year discounted value, WITHOUT period weights"
            ),
            "truncated_capex_share_of_measure_expenditure": (
                _trunc_total / _measure_t1 if _measure_t1 and abs(_measure_t1) > 1e-9 else None
            ),
            "note": (
                "Whether a terminal value is assigned depends on "
                "terminal_value_mode (central: none; the R6 arm applies the "
                "guarded annuity-consistent charge factor and reports the "
                "credited amount in terminal_value_credited_kCNY). The CCS "
                "minimum-operating commitment is enforced only within the "
                "horizon (no post-2060 constraint or cost). The DIRECTION of "
                "the end-of-horizon bias is not asserted: near-horizon assets "
                "are charged in full while their service is truncated "
                "(over-costing late investment), but the absence of salvage "
                "value also removes the option value of waiting (under-costing "
                "it), and post-2060 commitments are unmodelled. "
                "`truncated_capex_discounted_kCNY` measures the exposure "
                "directly -- the discounted CCS and renewal capital spent "
                "inside the last `truncation_window_years`, in the objective's "
                "lump-sum caliber -- so a robustness claim can be checked "
                "against it instead of argued. Disclose this convention, and "
                "this quantity, in Methods/SI."
            ),
        }
