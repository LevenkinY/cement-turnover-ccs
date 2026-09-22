"""Classify comparisons before attaching economic interpretations."""
import math
from verify_pair_configs import MUST_MATCH, _canonical, _effective, _planning_mode

STRUCTURAL = {'planning_mode', 'carbon_target_active', 'capacity_path_fixed'}
PROVENANCE = {'market_input_provenance', 'model_input_sha256', 'model_code_sha256'}
PATH_LABELS = {'demand_market_arc_file', 'demand_market_node_file'}


def invalid_carbon_run(payload):
    c = _effective(payload)
    return (float(c.get('af_biogenic_co2_per_tce', 0) or 0) > 0
            and c.get('carbon_flow_accounting_version') != 'treated_streams_v2')


def differences(a, b):
    ac, bc = _effective(a), _effective(b)
    keys = (set(ac) | set(bc)) - STRUCTURAL - PATH_LABELS - PROVENANCE
    # Phi=0 has the same equations before and after the accounting repair.
    if not any(float(c.get('af_biogenic_co2_per_tce', 0) or 0) for c in (ac, bc)):
        keys -= {'carbon_flow_accounting_version', 'capture_stream_assumption'}
    diff = [k for k in sorted(keys) if _canonical(ac.get(k)) != _canonical(bc.get(k))]
    for k in ('scenario', 'demand_scenario', 'carbon_budget_case'):
        if a.get(k) != b.get(k):
            diff.append(k)
    for k in ('model_input_sha256', 'model_code_sha256'):
        if ac.get(k) and bc.get(k) and ac[k] != bc[k]:
            diff.append(k)
    return sorted(set(diff))


def fixed(payload):
    return bool((payload.get('capacity_path_counterfactual') or {}).get('enabled'))


def classify(a, b):
    if invalid_carbon_run(a) or invalid_carbon_run(b):
        return 'invalid_carbon_accounting'
    ac, bc = _effective(a), _effective(b)
    if not ac or not bc:
        return 'unverified'
    if ac.get("model_code_sha256") and bc.get("model_code_sha256") and ac["model_code_sha256"] != bc["model_code_sha256"]:
        return "unverified"
    if differences(a, b):
        return 'cross_setting_cost_difference'
    if any(k not in ac or k not in bc for k in MUST_MATCH if k not in STRUCTURAL | PATH_LABELS):
        return 'unverified'
    if 'stepwise_capacity' in {_planning_mode(a), _planning_mode(b)}:
        return 'cross_setting_cost_difference'
    if not fixed(a) and fixed(b):
        guard = b.get('capacity_path_guard') or {}
        if guard.get('status') in {'FAIL', 'failed'}:
            return 'unverified'
        return 'fixed_path_loss'
    if not fixed(a) and not fixed(b):
        return 'repeat_candidate'
    return 'cross_setting_cost_difference'


def interval(a, b):
    sa, sb = a.get('solver', {}), b.get('solver', {})
    vals = [sa.get('objective_bound'), sa.get('objective_value'),
            sb.get('objective_bound'), sb.get('objective_value')]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
        return None
    la, ua, lb, ub = vals
    if la > ua + max(1e-6, abs(ua)*1e-8) or lb > ub + max(1e-6, abs(ub)*1e-8):
        return None
    for s in (sa, sb):
        if s.get('solution_count', 1) <= 0 or 'infeasible' in str(s.get('status', '')).lower():
            return None
    return {'point': ub-ua, 'low': lb-ua, 'high': ub-la}
