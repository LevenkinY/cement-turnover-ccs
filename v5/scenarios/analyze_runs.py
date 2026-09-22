#!/usr/bin/env python
"""Extract and analyse key results across a set of v5 runs.

Purpose: turn a directory of result JSONs into (a) a run-level table with solver
error, (b) the cost/emission/asset aggregates the paper claims rest on, (c) an
asset-retention overlap matrix, and (d) bound-valid planning losses against a
reference run. Writes Markdown + CSV so the numbers are traceable to files.

Why the loss needs bounds: R is a difference of two OPTIMISED costs, so it is known
only to within each run's gap. The reported interval is
[L_fixed - U_joint, U_fixed - L_joint] where L/U are each run's bound/objective.

Usage
-----
    python v5/scenarios/analyze_runs.py <dir-or-json>... [--reference NAME]
                                        [--out DIR] [--csv]

Options
    --reference NAME   run directory name used as the joint reference for losses
                       and for asset-set overlap (default: the first run found)
    --out DIR          where to write report.md / report.csv (default: ./analysis)
"""

from __future__ import annotations

import argparse
import csv
import json
from comparison_contract import classify, differences, interval, fixed, invalid_carbon_run
from pathlib import Path

YEARS = ["2025", "2030", "2035", "2040", "2045", "2050", "2055", "2060"]


def _load_runs(paths):
    """Collect (label, payload, source_path) from files or directories."""
    runs = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for json_path in sorted(path.rglob("*_results.json")):
                # keep the immediate parent dir name as the label
                runs.append((json_path.parent.name, json.loads(json_path.read_text()), json_path))
        elif path.suffix == ".json":
            runs.append((path.parent.name or path.stem, json.loads(path.read_text()), path))
        else:
            raise SystemExit(f"analyze_runs: not a .json or directory: {path}")
    if not runs:
        raise SystemExit("analyze_runs: no result JSONs found")
    return runs


def _num(value):
    return float(value) if isinstance(value, (int, float)) else None


def _solver(payload):
    solver = payload.get("solver") or {}
    obj, bound = _num(solver.get("objective_value")), _num(solver.get("objective_bound"))
    return {
        "objective": obj,
        "bound": bound,
        "gap": _num(solver.get("mip_gap")),
        "status": solver.get("status"),
        "seconds": _num(solver.get("solve_time_s")),
        "profile": solver.get("profile"),
    }


def _outcome(payload):
    """Whether a run produced a usable incumbent."""
    if invalid_carbon_run(payload):
        return "INVALID CARBON ACCOUNTING"
    solver = payload.get("solver") or {}
    status = str(solver.get("status") or "").lower()
    if solver.get("objective_value") is None:
        return "NO INCUMBENT"
    if "infeasible" in status:
        return "INFEASIBLE"
    return "ok"


def _summary(payload):
    return payload.get("summary") or {}


def _cfg(payload):
    return payload.get("effective_config") or payload.get("model_assumptions") or {}


def _bn(value):
    return f"{value/1e6:,.2f}" if isinstance(value, (int, float)) else "-"


def _planning_loss(ref_payload, run_payload):
    kind = classify(ref_payload, run_payload)
    result = interval(ref_payload, run_payload)
    if result is None:
        return None
    result.update(kind=kind, resolved=kind == "fixed_path_loss" and result["low"] > 0,
                  inconsistent=kind == "fixed_path_loss" and result["high"] < 0)
    return result


def _operating(payload, year):
    plants = payload.get("plants") or {}
    return {pid for pid, rec in plants.items() if round(float(rec["y"][year] or 0.0)) == 1}


def _overlap(ref_payload, run_payload, year):
    a, b = _operating(ref_payload, year), _operating(run_payload, year)
    union = a | b
    if not union:
        return None
    return {
        "n_ref": len(a),
        "n_run": len(b),
        "changed": len(a ^ b),
        "jaccard": len(a & b) / len(union),
    }


def _capacity(payload, cap_kt, year, key="u"):
    return sum(cap_kt.get(pid, 0.0) * float(rec[key][year] or 0.0)
               for pid, rec in (payload.get("plants") or {}).items())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="result JSON files or directories")
    parser.add_argument("--reference", default=None, help="run label used as the reference")
    parser.add_argument("--out", default="analysis", help="output directory")
    parser.add_argument("--csv", action="store_true", help="also write report.csv")
    args = parser.parse_args(argv)

    runs = _load_runs(args.paths)
    ref_label = args.reference or runs[0][0]
    ref = next((payload for label, payload, _ in runs if label == ref_label), None)
    if ref is None:
        raise SystemExit(f"analyze_runs: reference {ref_label!r} not among "
                         f"{[label for label, _, _ in runs]}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    add = lines.append

    # ── 1. run table ────────────────────────────────────────────────────────
    add(f"# 结果提取与分析\n")
    add(f"参考运行（用于损失与资产重合）：**{ref_label}**　|　共 {len(runs)} 次运行\n")
    add("> INVALID CARBON ACCOUNTING 的旧φ结果仅保留作错误诊断，所有成本/资产表中的这些行均不可引用。历史同配置无完整指纹时，重复解仅为候选，不自动合并上下界。\n")
    add("## 1 运行与求解误差\n")
    add("| 运行 | 情景 | 需求 | 状态 | objective (bn) | bound (bn) | gap | 用时(s) |")
    add("|---|---|---|---|---:|---:|---:|---:|")
    for label, payload, _ in runs:
        s = _solver(payload)
        add(f"| {label} | {payload.get('scenario','-')} | {payload.get('demand_scenario','-')} "
            f"| {_outcome(payload)} | {_bn(s['objective'])} | {_bn(s['bound'])} "
            f"| {'' if s['gap'] is None else format(100*s['gap'],'.3f')+'%'} "
            f"| {'' if s['seconds'] is None else format(s['seconds'],',.0f')} |")
    add("")

    # ── 2. cost calibers ───────────────────────────────────────────────────
    add("## 2 成本口径（折现，bn CNY）\n")
    add("| 运行 | 措施支出 | 产能周转 | 市场物流 | 调度效率 | 模型成本 | closure_check |")
    add("|---|---:|---:|---:|---:|---:|---:|")
    for label, payload, _ in runs:
        cc = payload.get("cost_calibers") or {}
        add(f"| {label} | {_bn(cc.get('measure_expenditure_kCNY'))} "
            f"| {_bn(cc.get('capacity_turnover_cost_kCNY'))} "
            f"| {_bn(cc.get('market_logistics_cost_kCNY'))} "
            f"| {_bn(cc.get('dispatch_efficiency_kCNY'))} "
            f"| {_bn(cc.get('model_cost_kCNY'))} "
            f"| {cc.get('closure_check_kCNY')} |")
    add("")

    # ── 3. per-year aggregates ─────────────────────────────────────────────
    add("## 3 逐年关键量\n")
    for label, payload, _ in runs:
        if _outcome(payload) != "ok":
            add(f"### {label} — 无可用解\n")
            continue
        add(f"### {label}\n")
        add("| 年 | 在运线 | 产能加权 u | 净 CO2 (kt) | 捕集 (kt) | AF 率 | 在运 CCS 厂 |")
        add("|---|---:|---:|---:|---:|---:|---:|")
        for year in YEARS:
            row = _summary(payload).get(year) or {}
            add(f"| {year} | {row.get('n_plants_operating','-')} "
                f"| {'' if row.get('capacity_weighted_utilization') is None else format(row['capacity_weighted_utilization'],'.4f')} "
                f"| {'' if row.get('net_co2_kt') is None else format(row['net_co2_kt'],',.0f')} "
                f"| {'' if row.get('captured_co2_kt') is None else format(row['captured_co2_kt'],',.0f')} "
                f"| {'' if row.get('national_af_rate') is None else format(row['national_af_rate'],'.4f')} "
                f"| {row.get('n_plants_ccs_active','-')} |")
        add("")

    # ── 4. constraints and end-of-horizon exposure ─────────────────────────
    add("## 4 约束绑定与期末敞口\n")
    add("| 运行 | 绑定约束 | 累计预算余量 (kt·yr) | 2060 端点余量 (kt) | 截断资本 (bn) | 占措施支出 |")
    add("|---|---|---:|---:|---:|---:|")
    for label, payload, _ in runs:
        ch = payload.get("constraint_headroom") or {}
        ht = payload.get("horizon_terminal_treatment") or {}
        trunc = (ht.get("truncated_capex_discounted_kCNY") or {}).get("total")
        add(f"| {label} | {ch.get('binding_constraint','-')} "
            f"| {'' if ch.get('cumulative_budget_headroom_kt_year') is None else format(ch['cumulative_budget_headroom_kt_year'],',.2f')} "
            f"| {'' if ch.get('terminal_2060_headroom_kt') is None else format(ch['terminal_2060_headroom_kt'],',.1f')} "
            f"| {_bn(trunc)} "
            f"| {'' if ht.get('truncated_capex_share_of_measure_expenditure') is None else format(100*ht['truncated_capex_share_of_measure_expenditure'],'.1f')+'%'} |")
    add("")

    # ── 5. asset-set overlap (the "which assets persist" claim) ────────────
    add("## 5 在运资产集重合（相对参考）\n")
    add("| 运行 | " + " | ".join(f"{y}: 变化/在运" for y in YEARS[1:]) + " | Jaccard 2060 |")
    add("|---" * (len(YEARS)) + "|")
    for label, payload, _ in runs:
        if _outcome(payload) != "ok" or _outcome(ref) != "ok":
            add(f"| {label} | 无可用解 |")
            continue
        cells, jac = [], None
        for year in YEARS[1:]:
            ov = _overlap(ref, payload, year)
            if ov is None:
                cells.append("-")
            else:
                cells.append(f"{ov['changed']}/{ov['n_run']}")
                if year == "2060":
                    jac = f"{ov['jaccard']:.3f}"
        add(f"| {label} | " + " | ".join(cells) + f" | {jac or '-'} |")
    add("")

    # Comparisons have distinct estimands; a coefficient change is not regret.
    add("## 6 配对损失与跨设定成本差\n")
    add("> 固定路径优先匹配同标签joint；其余为相对指定参考的成本差。仅同设定限制问题适用R≥0。历史无输入/代码指纹的匹配仍需人工核验。区间不等于Δbound。\n")
    add("| 运行 | 比较参考 | 类型 | 点差(bn) | 区间(bn) | 判定 |")
    add("|---|---|---|---:|---|---|")
    labels = {label: payload for label, payload, _ in runs}
    for label, payload, _ in runs:
        if label == ref_label:
            continue
        partner_label = label[:-6] + "_joint" if label.endswith("_fixed") else ref_label
        partner = labels.get(partner_label, ref)
        if partner_label not in labels:
            partner_label = ref_label
        # A procedural self-check belongs to its exact source run, not to a later
        # better incumbent of the same unrestricted model.
        cf = payload.get("capacity_path_counterfactual") or {}
        is_selfcheck = False
        if cf.get("enabled") and cf.get("source_scenario") == payload.get("scenario"):
            source = Path(cf.get("source_path", "")).resolve()
            for source_label, source_payload, source_path in runs:
                if source_path.resolve() == source:
                    partner_label, partner = source_label, source_payload
                    is_selfcheck = True
                    break
        loss = _planning_loss(partner, payload)
        if loss is None:
            add(f"| {label} | {partner_label} | 无有效上下界 | - | - | 不比较 |")
            continue
        kind = loss["kind"]
        if kind in {"invalid_carbon_accounting", "unverified"}:
            add(f"| {label} | {partner_label} | {kind} | - | - | 不可作结论 |")
            continue
        verdict = ("确认正损失" if loss["resolved"] else "区间与嵌套关系冲突，核验模型/界限"
                   if loss["inconsistent"] else "正损失未确认" if kind == "fixed_path_loss"
                   else "不适用R≥0；包含重新计价" if kind == "cross_setting_cost_difference"
                   else "重复解差异；不是参数效应")
        if is_selfcheck:
            verdict = "固定源路径程序检查；允许重优化改善原incumbent，不是资源忽略损失"
        add(f"| {label} | {partner_label} | {kind} | {loss['point']/1e6:+.2f} | "
            f"[{loss['low']/1e6:+.2f}, {loss['high']/1e6:+.2f}] | {verdict} |")
    add("")
    add("### 同设定重复候选（不自动合并未经指纹确认的模型）\n")
    for label, payload, source in runs:
        if label != ref_label and classify(ref, payload) == "repeat_candidate":
            diag = _solver(payload)
            add(f"- {label}: incumbent={_bn(diag['objective'])}, bound={_bn(diag['bound'])} bn。"
                "若输入与方程一致，可复用较好可行解；同参数资产差异属于求解/近优不确定性。")
    add("")

    # ── 7. effective config drift ──────────────────────────────────────────
    add("## 7 有效配置漂移（相对参考）\n")
    ref_cfg = _cfg(ref)
    for label, payload, _ in runs:
        if label == ref_label:
            continue
        cfg = _cfg(payload)
        diffs = [k for k in sorted(set(ref_cfg) | set(cfg))
                 if ref_cfg.get(k) != cfg.get(k)]
        if diffs:
            add(f"- **{label}**：{', '.join(diffs)}")
        else:
            add(f"- **{label}**：与参考逐项一致")
    add("\n> 配对比较前必须过 `v5/scenarios/verify_pair_configs.py`；本节只是概览。\n")

    # ── 8. values manifest ─────────────────────────────────────────────────
    add("## 8 结果文件清单（可追溯）\n")
    for label, _, path in runs:
        add(f"- `{label}` → `{path}`")
    add("")

    report = out_dir / "report.md"
    report.write_text("\n".join(lines))
    print(f"[analyze] wrote {report}")

    if args.csv:
        csv_path = out_dir / "report.csv"
        with csv_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["run", "scenario", "demand", "outcome", "objective_kCNY",
                             "bound_kCNY", "gap", "seconds"])
            for label, payload, path in runs:
                s = _solver(payload)
                writer.writerow([label, payload.get("scenario"), payload.get("demand_scenario"),
                                 _outcome(payload), s["objective"], s["bound"], s["gap"],
                                 s["seconds"]])
        print(f"[analyze] wrote {csv_path}")

    # console summary
    print()
    print(f"{'run':<26}{'status':>12}{'objective(bn)':>15}{'gap':>9}{'bound(bn)':>14}")
    for label, payload, _ in runs:
        s = _solver(payload)
        print(f"{label:<26}{_outcome(payload):>12}"
              f"{(s['objective']/1e6 if s['objective'] else float('nan')):>15,.2f}"
              f"{(100*s['gap'] if s['gap'] is not None else float('nan')):>8.2f}%"
              f"{(s['bound']/1e6 if s['bound'] else float('nan')):>14,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
