"""Linear annual capture-stream accounting, with no biogenic budget credit.

For phi > 0, annual production is partitioned into treated streams delivered to
each sink and an untreated remainder. Each stream has one capture efficiency
for fossil and biogenic carbon. AF shares may differ between annual operating
segments; this is not a constant-composition whole-year flue-gas assumption.
"""
from pyomo.environ import Constraint, Expression, NonNegativeReals, Var


def add_carbon_streams(owner, m, efficiency, phi):
    theta = float(owner.config.AF_TECHNICAL_TSR_CEILING)
    beta = float(owner.config.BETA_AF)
    coal = float(owner.coal_ef)
    by_plant = {i: [] for i in owner.I}
    fossil_terms = {i: [] for i in owner.I}
    af_terms = {i: [] for i in owner.I}

    def coefficients(i, t):
        year = owner.years[t]
        heat = owner.plant_heat_intensity[i] * (1 - owner.ee_path[year])
        arm = owner.arm_path.get((owner.province_map[i], year), 0.0)
        process = float(owner.emission_factors[i]['proc_ef']) * (1 - arm)
        return heat, process + coal * heat

    for kind, pairs in [('dsa', owner.ps_dsa), ('eor', owner.ps_eor)]:
        index = getattr(m, 'PS_' + kind)
        q = Var(index, m.T, within=NonNegativeReals)
        a = Var(index, m.T, within=NonNegativeReals)
        setattr(m, 'capture_stream_q_' + kind, q)
        setattr(m, 'capture_stream_af_' + kind, a)
        fossil = Expression(index, m.T, rule=lambda mm, i, s, t, q=q, a=a:
                            efficiency * (coefficients(i, t)[1] * q[i, s, t]
                                          - beta * coal * a[i, s, t]))
        setattr(m, 'fossil_flow_' + kind, fossil)
        flow = getattr(m, 'f_p_' + kind)
        setattr(m, 'capture_stream_flow_' + kind, Constraint(
            index, m.T, rule=lambda mm, i, s, t, flow=flow, fossil=fossil, a=a:
            flow[i, s, t] == fossil[i, s, t] + efficiency * phi * a[i, s, t]))
        setattr(m, 'capture_stream_heat_' + kind, Constraint(
            index, m.T, rule=lambda mm, i, s, t, q=q, a=a:
            a[i, s, t] <= theta * coefficients(i, t)[0] * q[i, s, t]))
        for i, s in pairs:
            by_plant[i].append((q, s))
            af_terms[i].append((a, s))
            fossil_terms[i].append((fossil, s))

    m.capture_stream_production = Expression(m.I, m.T, rule=lambda mm, i, t:
        sum(q[i, s, t] for q, s in by_plant[i]))
    m.af_captured_energy = Var(m.I, m.T, within=NonNegativeReals)
    m.capture_stream_af_balance = Constraint(m.I, m.T, rule=lambda mm, i, t:
        mm.af_captured_energy[i, t] == sum(a[i, s, t] for a, s in af_terms[i]))
    m.capture_stream_fossil_balance = Constraint(m.I, m.T, rule=lambda mm, i, t:
        mm.captured[i, t] == sum(f[i, s, t] for f, s in fossil_terms[i]))
    m.capture_stream_production_bound = Constraint(m.I, m.T, rule=lambda mm, i, t:
        mm.capture_stream_production[i, t] <= owner.cap[i] * mm.u[i, t])
    m.capture_stream_status = Constraint(m.I, m.T, rule=lambda mm, i, t:
        mm.capture_stream_production[i, t] <= owner.cap[i] * mm.z[i, t])
    m.capture_stream_af_bound = Constraint(m.I, m.T, rule=lambda mm, i, t:
        mm.af_captured_energy[i, t] <= mm.af_supply[i, t])
    m.capture_stream_untreated_heat = Constraint(m.I, m.T, rule=lambda mm, i, t:
        mm.af_supply[i, t] - mm.af_captured_energy[i, t]
        <= theta * coefficients(i, t)[0]
        * (owner.cap[i] * mm.u[i, t] - mm.capture_stream_production[i, t]))
    m.captured_gross = Expression(m.I, m.T, rule=lambda mm, i, t:
        mm.captured[i, t] + efficiency * phi * mm.af_captured_energy[i, t])


def fossil_flow_value(owner, kind, i, s, t):
    if owner.af_biogenic_co2_per_tce <= 0:
        return owner._solution_value('f_p_' + kind, i, s, t)
    year = owner.years[t]
    heat = owner.plant_heat_intensity[i] * (1 - owner.ee_path[year])
    process = float(owner.emission_factors[i]['proc_ef']) * (
        1 - owner.arm_path.get((owner.province_map[i], year), 0.0))
    q = owner._solution_value('capture_stream_q_' + kind, i, s, t)
    a = owner._solution_value('capture_stream_af_' + kind, i, s, t)
    return float(owner.config.CCS_PARAMS['capture_efficiency']) * (
        (process + owner.coal_ef * heat) * q
        - float(owner.config.BETA_AF) * owner.coal_ef * a)
