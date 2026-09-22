"""No solver calls: physical balances, configuration propagation, report types."""
import copy
import importlib.util
import io
import contextlib
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

import pandas as pd
from pyomo.environ import ConcreteModel, Set, Var, NonNegativeReals, Binary, value, Constraint

from src_v5.model.carbon_streams import add_carbon_streams
from src_v5.provenance import validate_market_inputs
import src_v5.main as runner

SCENARIOS = Path(__file__).resolve().parents[2] / 'scenarios'
sys.path.insert(0, str(SCENARIOS))
from comparison_contract import classify, interval
from verify_pair_configs import MUST_MATCH


def toy():
    m = ConcreteModel()
    m.I = Set(initialize=[1]); m.T = Set(initialize=[0])
    m.PS_dsa = Set(initialize=[(1, 1)], dimen=2)
    m.PS_eor = Set(initialize=[(1, 2)], dimen=2)
    for name in ['u', 'af_supply', 'captured']:
        setattr(m, name, Var(m.I, m.T, within=NonNegativeReals))
    m.z = Var(m.I, m.T, within=Binary)
    m.f_p_dsa = Var(m.PS_dsa, m.T, within=NonNegativeReals)
    m.f_p_eor = Var(m.PS_eor, m.T, within=NonNegativeReals)
    owner = SimpleNamespace(config=SimpleNamespace(AF_TECHNICAL_TSR_CEILING=.6, BETA_AF=.55),
        coal_ef=2.66, I=[1], years=[2030], cap={1:100},
        plant_heat_intensity={1:.1}, ee_path={2030:0}, arm_path={},
        province_map={1:'P'}, emission_factors={1:{'proc_ef':.5}},
        ps_dsa=[(1,1)], ps_eor=[(1,2)])
    add_carbon_streams(owner, m, .9, 1.31)
    return m


def feasible(m):
    for c in m.component_data_objects(Constraint, active=True):
        b = value(c.body)
        if c.lower is not None and b < value(c.lower)-1e-8:
            return False
        if c.upper is not None and b > value(c.upper)+1e-8:
            return False
    return True


def set_streams(m, fraction):
    m.u[1,0].value=1; m.af_supply[1,0].value=4
    m.z[1,0].value=int(fraction>0)
    # Identical compositions for this test, with a non-captured remainder.
    for kind, sink, q, a in [('dsa',1,60*fraction,2.4*fraction),('eor',2,40*fraction,1.6*fraction)]:
        getattr(m,'capture_stream_q_'+kind)[1,sink,0].value=q
        getattr(m,'capture_stream_af_'+kind)[1,sink,0].value=a
        f=.9*(.766*q-.55*2.66*a)
        getattr(m,'f_p_'+kind)[1,sink,0].value=f+.9*1.31*a
    m.af_captured_energy[1,0].value=4*fraction
    m.captured[1,0].value=.9*(76.6-.55*2.66*4)*fraction


def test_partial_and_full_capture_conserve_both_carbons():
    m=toy()
    for frac in [0,.25,.5,1]:
        set_streams(m,frac)
        assert feasible(m)
        gross=value(m.captured_gross[1,0])
        assert abs(gross-value(m.captured[1,0])-.9*1.31*4*frac)<1e-8
        credit=value(m.fossil_flow_dsa[1,1,0])+.9*value(m.fossil_flow_eor[1,2,0])
        wrong=value(m.f_p_dsa[1,1,0])+.9*value(m.f_p_eor[1,2,0])
        assert abs(wrong-credit-.9*1.31*(2.4+.9*1.6)*frac)<1e-8


def test_capture_cannot_process_af_without_corresponding_clinker():
    m=toy();set_streams(m,.5)
    m.capture_stream_af_dsa[1,1,0].value=3
    assert not feasible(m)


def test_no_ccs_means_zero_physical_capture():
    m=toy();set_streams(m,0)
    assert feasible(m) and value(m.captured_gross[1,0])==0


def payload(fixed=False):
    c={k:0 for k in MUST_MATCH}; c['planning_mode']='joint'
    return {'scenario':'S1','effective_config':c,
            'capacity_path_counterfactual':{'enabled':fixed},
            'solver':{'objective_value':110.,'objective_bound':100.,'solution_count':1}}


def test_comparison_types_and_signed_cost_interval():
    a=payload();b=payload(True)
    assert classify(a,b)=='fixed_path_loss'
    b['effective_config']['discount_rate']=.08
    assert classify(a,b)=='cross_setting_cost_difference'
    b['solver'].update(objective_value=95.,objective_bound=90.)
    assert interval(a,b)=={'point':-15.,'low':-20.,'high':-5.}
    assert classify(a,payload())=='repeat_candidate'
    b['effective_config']['af_biogenic_co2_per_tce']=1.31
    assert classify(a,b)=='invalid_carbon_accounting'


def test_invalid_solver_intervals_are_not_silently_reordered():
    a=payload();b=payload(True)
    b['solver'].update(objective_value=95., objective_bound=100.)
    assert interval(a,b) is None
    b['solver'].update(objective_value=float('nan'), objective_bound=90.)
    assert interval(a,b) is None


def test_analyzer_uses_same_setting_partner(tmp_path):
    import json
    import analyze_runs
    runs=[]
    for name, r in [('reference',payload()),('cost_joint',payload()),('cost_fixed',payload(True))]:
        if name.startswith('cost_'):
            r['effective_config']['plant_fixed_operating_cost_cny_per_t_capacity_yr']=53.2
        path=tmp_path/name/'S1_results.json';path.parent.mkdir();path.write_text(json.dumps(r));runs.append(str(path))
    out=tmp_path/'report'
    with contextlib.redirect_stdout(io.StringIO()):
        assert analyze_runs.main([*runs,'--reference','reference','--out',str(out)])==0
    report=(out/'report.md').read_text()
    assert '| cost_fixed | cost_joint | fixed_path_loss |' in report
    assert '| cost_joint | reference | cross_setting_cost_difference |' in report


def test_market_preflight_rejects_silent_wrong_data(tmp_path):
    nodes=pd.DataFrame([{'node_id':1,'lon':110.,'lat':30.,'province':'P','pop':1.,'pop_share_within_province':1.}])
    np=tmp_path/'nodes.csv';ap=tmp_path/'arcs.csv'
    nodes.to_csv(np,index=False)
    pd.DataFrame([{'plant_id':1,'node_id':1,'distance_km':10.}]).to_csv(ap,index=False)
    c=SimpleNamespace(DEMAND_MARKET_NODE_FILE=np,DEMAND_MARKET_ARC_FILE=ap)
    d={'regional_demand_enabled':True,'market_nodes':nodes,'demand_arcs':{(1,1):10.}}
    assert validate_market_inputs(d,c)['nodes_loaded']==1
    d['demand_arcs'][(1,1)]=11.
    import pytest
    with pytest.raises(ValueError):validate_market_inputs(d,c)


def test_market_override_reaches_module_before_load_and_resets(tmp_path,monkeypatch):
    a=tmp_path/'nodes.csv';b=tmp_path/'arcs.csv';a.touch();b.touch()
    seen=[]
    class Stop(Exception):pass
    def loader():
        seen.append((runner.config.DEMAND_MARKET_NODE_FILE, runner._config_module.DEMAND_MARKET_NODE_FILE))
        raise Stop()
    monkeypatch.setattr(runner,'load_all',loader)
    try:
        for kw in [{'demand_market_node_file':str(a),'demand_market_arc_file':str(b)},{}]:
            try:
                with contextlib.redirect_stdout(io.StringIO()):runner.run_scenario(**kw)
            except Stop:pass
        assert seen[0]==(a,a)
        default=runner._CONFIG_OVERRIDE_DEFAULTS['DEMAND_MARKET_NODE_FILE']
        assert seen[1]==(default,default)
    finally:runner._reset_config_overrides()
