"""Not-for 段消融实验 v2 执行器（五臂：A / B / C / C′ / D）。

判读规则见同目录 `PREREGISTRATION.md`（跑之前落盘，跑完不许改）。

与 `../run_comparison.py` 的关系：**复用**其用例加载、调用重试、聚合、评分、口径函数，
只**新增** C′ 臂的载荷构造。A / B / C / D 四臂的 system 载荷与 `run_comparison.skill_payload`
**逐字节相同**（`--selftest` 会核对这一点）。

**不修改交付的 skills/ 目录**：C′ 的变体在运行时「读原件 → 内存删段 → 拼 system prompt」。

用法：
    py -3.12 run_ablation.py --selftest                       # 零 API 成本：核对载荷与 C′ 剥离
    py -3.12 run_ablation.py --gate --out results/gate.json    # 复现门禁（A/B/C × 原 16 负例 × 3）
    py -3.12 run_ablation.py --arm Cp --out results/Cp.json
    py -3.12 run_ablation.py --report results/{A,B,C,Cp,D}.json --out report.md
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Sequence

# 就地改编码，不替换 sys.stdout 对象——替换会让 import 本模块的脚本失去自己的 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
EVALS = HERE.parent          # skills/evals —— run_comparison.py 所在
ROOT = HERE.parent.parent.parent  # 项目根
sys.path.insert(0, str(EVALS))
import run_comparison as rc  # noqa: E402

ARMS = ("A", "B", "C", "Cp", "D")
ARM_LABEL = {
    "A": "裸模型",
    "B": "全量（交付形态）",
    "C": "原消融（仅 description）",
    "Cp": "C′（真消融）",
    "D": "仅描述",
}

SKILLS = ROOT / "skills"
SKILL_NAMES = ("safety-hazard-detection", "gauge-reading", "inspection-report", "inspection-orchestrator")

NOT_FOR_PREFIX = "不适用于："
BODY_BOUNDARY_RE = re.compile(r"^##\s*负向边界", re.MULTILINE)
REF_EXCLUSION_MARKERS = ("不适用本清单",)

HARD_NEG_PATH = HERE / "cases-hard-negatives.jsonl"
ORIGINAL_CASES_GLOB = "skills/*/evals/cases.jsonl"

# 历史值（skills/evals/results/report.md，v1 描述）
HISTORICAL = {
    "A": {"ftr": 0.0, "broad": 0.5625, "phantom": 76},
    "B": {"ftr": 0.0, "broad": 0.0625, "phantom": 0},
    "C": {"ftr": 0.0, "broad": 0.1875, "phantom": 0},
    "D": {"ftr": 0.0, "broad": 0.0, "phantom": 0},
}

# 预注册 §3 冻结的子集
SUBSET_MAIN = "S1_全部负例"
SUBSET_HARD = "S2_新增硬负例"
SUBSET_DISCRIMINATIVE = "S3_Not-for可判别"
EXCLUDED_FROM_S3 = {"hard-gauge-neg-001"}  # 预注册 §3：该条不由 Not-for 判别

BOOTSTRAP_ITERS = 10000
BOOTSTRAP_SEED = 20260927


# ---------------------------------------------------------------- C′ 载荷构造


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    return (parts[1] if len(parts) >= 3 else ""), (parts[2] if len(parts) >= 3 else text)


def description_of(skill: str, *, strip_not_for: bool) -> str:
    front = _split_frontmatter((SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"))[0]
    lines, collecting = [], False
    for line in front.splitlines():
        if line.startswith("description:"):
            collecting = True
            continue
        if collecting:
            if not line.startswith((" ", "\t")):
                break
            lines.append(line.strip())
    desc = " ".join(lines).strip()
    if strip_not_for:
        idx = desc.find(NOT_FOR_PREFIX)
        if idx != -1:
            desc = desc[:idx].strip()
    return desc


def body_of(skill: str, *, strip_boundary: bool) -> str:
    body = _split_frontmatter((SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"))[1]
    if strip_boundary:
        m = BODY_BOUNDARY_RE.search(body)
        if m:
            body = body[: m.start()]
    return body.strip()


def references_of(skill: str, *, strip_exclusions: bool) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    d = SKILLS / skill / "references"
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        if strip_exclusions:
            text = "\n".join(
                ln for ln in text.splitlines() if not any(m in ln for m in REF_EXCLUSION_MARKERS)
            )
        out.append((p.name, text.strip()))
    return out


def skill_payload_v2(skill: str, arm: str) -> str:
    """五臂的 system 侧载荷。A/B/C/D 与 run_comparison.skill_payload 逐字节一致。"""
    if arm == "A":
        return ""
    if arm == "B":
        strip_nf, strip_bd, strip_rx = False, False, False
    elif arm == "C":
        strip_nf, strip_bd, strip_rx = True, False, False
    elif arm == "Cp":
        strip_nf, strip_bd, strip_rx = True, True, True
    elif arm == "D":
        return f"[skill: {skill}]\n\ndescription: {description_of(skill, strip_not_for=False)}"
    else:
        raise ValueError(f"未知臂：{arm}")

    parts = [f"[skill: {skill}]", f"description: {description_of(skill, strip_not_for=strip_nf)}"]
    parts.append(body_of(skill, strip_boundary=strip_bd))
    parts += [
        f"\n[reference: {name}]\n{text}"
        for name, text in references_of(skill, strip_exclusions=strip_rx)
    ]
    return "\n\n".join(parts)


def patch_runner() -> None:
    """把五臂载荷接进 run_comparison 的调用链（build_prompt 在调用时查全局名）。"""
    rc.skill_payload = skill_payload_v2  # type: ignore[assignment]


# ---------------------------------------------------------------- 用例集


def load_all_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 (合并集 46, 原 40, 新 6)。顺序：原用例按路径排序，新用例追加在后。"""
    original = rc.load_cases(sorted(glob.glob(str(ROOT / ORIGINAL_CASES_GLOB))))
    hard = rc.load_cases([str(HARD_NEG_PATH)])
    return original + hard, original, hard


def negatives_of(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in cases if not c["expect_trigger"]]


# ---------------------------------------------------------------- 运行产物读写


def load_arm_results(path: str) -> tuple[str, list[rc.CaseResult]]:
    blob = json.loads(Path(path).read_text(encoding="utf-8"))
    arm = str(blob["arm"])
    results = [
        rc.CaseResult(
            case_id=str(r["case_id"]),
            arm=arm,  # type: ignore[arg-type]
            run_index=int(r["run_index"]),
            triggered=bool(r["triggered"]),
            route=[str(s) for s in r.get("route", [])],
            output={"findings": [], "usage": r.get("usage", {})},
            latency_ms=int(r.get("latency_ms", 0)),
            tier2_calls=1,
            raw_response=str(r.get("raw_response", "")),
            error=str(r.get("error", "")),
            attempts=int(r.get("attempts", 0)),
        )
        for r in blob["results"]
    ]
    return arm, results


def save_arm(arm: str, cases: Sequence[dict[str, Any]], results: Sequence[rc.CaseResult],
             runs: int, concurrency: int, out: str) -> None:
    tokens = sum(r.output["usage"].get("total_tokens", 0) for r in results)
    failed = sum(1 for r in results if r.error)
    blob = {
        "arm": arm,
        "n_cases": len(cases),
        "runs": runs,
        "concurrency": concurrency,
        "skill_payload_chars": len(rc.build_prompt(cases[0], arm)) if cases else 0,
        "total_tokens": tokens,
        "n_errors": failed,
        "results": [
            {
                "case_id": r.case_id,
                "run_index": r.run_index,
                "triggered": r.triggered,
                "route": r.route,
                "usage": r.output["usage"],
                "latency_ms": r.latency_ms,
                "raw_response": r.raw_response,
                "error": r.error,
                "attempts": r.attempts,
            }
            for r in results
        ],
    }
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    retried = sum(1 for r in results if r.attempts > 1)
    print(f"[{arm}] {len(results)} 次运行，{tokens} tokens，失败 {failed}，重试救回 {retried} → {out}")


# ---------------------------------------------------------------- 子集评分


def score_subset(results: Sequence[rc.CaseResult], all_cases: Sequence[dict[str, Any]],
                 keep: set[str]) -> dict[str, Any]:
    """只在 `keep` 这批用例上评分（results 相应过滤，与 score() 同源同口径）。"""
    cases = [c for c in all_cases if str(c["id"]) in keep]
    sub = [r for r in results if r.case_id in keep]
    return rc.score(sub, cases)


def own_skill_of(cases: Sequence[dict[str, Any]]) -> dict[str, str]:
    return {str(c["id"]): str(c.get("skill", "")) for c in cases}


def case_own_hits(results: Sequence[rc.CaseResult], own: dict[str, str],
                  case_ids: Sequence[str]) -> dict[str, list[int]]:
    """逐用例的逐次运行判定：1 = 本次运行误调用了本技能。"""
    acc: dict[str, list[int]] = {cid: [] for cid in case_ids}
    for r in results:
        if r.case_id not in acc or r.error or rc._payload_of(r) is None:
            continue
        target = own.get(r.case_id, "")
        acc[r.case_id].append(1 if (r.triggered and (target in r.route or not r.route)) else 0)
    return acc


def run_level_delta(b: dict[str, list[int]], c: dict[str, list[int]],
                    case_ids: Sequence[str]) -> dict[str, Any]:
    bv = [v for cid in case_ids for v in b.get(cid, [])]
    cv = [v for cid in case_ids for v in c.get(cid, [])]
    out = {
        "point": None, "b_rate": None, "c_rate": None,
        "n_runs": len(bv), "b_hits": sum(bv), "c_hits": sum(cv),
    }
    if not bv or not cv:
        return out
    b_rate, c_rate = sum(bv) / len(bv), sum(cv) / len(cv)
    out.update({"point": c_rate - b_rate, "b_rate": b_rate, "c_rate": c_rate})
    return out


def bootstrap_delta(b: dict[str, list[int]], c: dict[str, list[int]],
                    case_ids: Sequence[str], *, iters: int = BOOTSTRAP_ITERS,
                    seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """对**用例**做有放回重抽样，给出 run 级 Δ 的 95% 自助区间。"""
    rng = random.Random(seed)
    n = len(case_ids)
    if not n:
        return {"low": None, "high": None, "iters": 0}
    deltas = []
    for _ in range(iters):
        pick = [case_ids[rng.randrange(n)] for _ in range(n)]
        bv = [v for cid in pick for v in b.get(cid, [])]
        cv = [v for cid in pick for v in c.get(cid, [])]
        if not bv or not cv:
            continue
        deltas.append(sum(cv) / len(cv) - sum(bv) / len(bv))
    if not deltas:
        return {"low": None, "high": None, "iters": 0}
    deltas.sort()
    return {
        "low": deltas[int(0.025 * len(deltas))],
        "high": deltas[min(len(deltas) - 1, int(0.975 * len(deltas)))],
        "iters": len(deltas),
    }


def rule_of_three(hits: int, n: int) -> float | None:
    """0 次命中时真实率的 95% 上界 ≈ 3/n；非 0 命中返回 None（该近似不适用）。"""
    return None if hits or not n else 3.0 / n


# ---------------------------------------------------------------- 报告


def _f(v: Any, digits: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def analyse(results_by_arm: dict[str, list[rc.CaseResult]], all_cases: Sequence[dict[str, Any]],
            original: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """按预注册 §3 的三个子集算全部量。返回结构化结果供渲染。"""
    all_neg = [str(c["id"]) for c in negatives_of(all_cases)]
    hard_neg = [str(c["id"]) for c in negatives_of(all_cases) if str(c["id"]).startswith("hard-")]
    disc_neg = [cid for cid in all_neg if cid not in EXCLUDED_FROM_S3]
    orig_ids = {str(c["id"]) for c in original}
    orig_neg = [str(c["id"]) for c in negatives_of(original)]

    subsets = {
        SUBSET_MAIN: set(all_neg),
        SUBSET_HARD: set(hard_neg),
        SUBSET_DISCRIMINATIVE: set(disc_neg),
    }
    own = own_skill_of(all_cases)

    out: dict[str, Any] = {"subsets": {}, "scores": {}, "case_ids": {
        "S1": all_neg, "S2": hard_neg, "S3": disc_neg, "orig_neg": orig_neg}}
    for arm, results in results_by_arm.items():
        out["scores"][arm] = {name: score_subset(results, all_cases, keep) for name, keep in subsets.items()}

    for name, keep in subsets.items():
        ids = sorted(keep)
        entry: dict[str, Any] = {"n_negatives": len(ids)}
        for rule in rc.SENSITIVITY_RULES:
            row = {}
            for arm in ("B", "C", "Cp"):
                s = out["scores"].get(arm, {}).get(name)
                row[arm] = None if s is None else rc._ftr_by_rule(s["cases"], rule, broad=False)
            d2 = None if None in (row["B"], row["C"]) else row["C"] - row["B"]
            d2p = None if None in (row["B"], row["Cp"]) else row["Cp"] - row["B"]
            entry[rule] = {"ftr_b": row["B"], "ftr_c": row["C"], "ftr_cp": row["Cp"],
                           "delta2": d2, "delta2p": d2p}
        # run 级
        b = case_own_hits(results_by_arm.get("B", []), own, ids)
        c = case_own_hits(results_by_arm.get("C", []), own, ids)
        cp = case_own_hits(results_by_arm.get("Cp", []), own, ids)
        entry["run_level_delta2"] = run_level_delta(b, c, ids)
        entry["run_level_delta2p"] = run_level_delta(b, cp, ids)
        entry["bootstrap_delta2p"] = bootstrap_delta(b, cp, ids)
        entry["bootstrap_delta2"] = bootstrap_delta(b, c, ids)
        entry["rule_of_three_b"] = rule_of_three(
            entry["run_level_delta2p"]["b_hits"] or 0, entry["run_level_delta2p"]["n_runs"] or 0)
        entry["rule_of_three_cp"] = rule_of_three(
            entry["run_level_delta2p"]["c_hits"] or 0, entry["run_level_delta2p"]["n_runs"] or 0)
        entry["discordant"] = [
            {"case_id": cid, "b_hits": sum(b.get(cid, [])), "cp_hits": sum(cp.get(cid, [])),
             "n_runs": len(b.get(cid, [])), "skill": own.get(cid, "")}
            for cid in ids
            if sum(b.get(cid, [])) != sum(cp.get(cid, []))
        ]
        out["subsets"][name] = entry

    # 复现对照：原 40 条用例子集
    out["reproduction"] = {}
    for arm, results in results_by_arm.items():
        if arm not in HISTORICAL:
            continue
        s = score_subset(results, all_cases, orig_ids)
        out["reproduction"][arm] = {
            "ftr": s["false_trigger_rate"], "broad": s["negative_any_trigger_rate"],
            "phantom": s["phantom_skill_count"], "hist": HISTORICAL[arm],
            "samples": s["samples"], "reliable": s["reliable"],
        }
    return out


def render(results_by_arm: dict[str, list[rc.CaseResult]], analysis: dict[str, Any],
           meta: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Not-for 段消融实验 v2 · 五臂结果")
    add("")
    add(f"- 模型：`{meta['model']}`　温度 0　每用例 {meta['runs']} 次　并发 {meta['concurrency']}")
    add(f"- 用例：{meta['n_cases']} 条（正 {meta['n_pos']} / 负 {meta['n_neg']}）")
    add("- 判读规则：`PREREGISTRATION.md`，2026-09-27 22:42 (+0800) 落盘，**先于本次运行**")
    add(f"- 运行时间：{meta['when']}")
    add("")

    # --- 1. 五臂主表
    add("## 1. 五臂 · 主口径表（S1 = 全部负例）")
    add("")
    add("| 臂 | skill 载荷 | **本技能口径 FTR** | **广义触发率** | **幽灵技能计数** | 负例有效/总 | 可靠 |")
    add("|---|---|---|---|---|---|---|")
    for arm in ARMS:
        s = analysis["scores"].get(arm, {}).get(SUBSET_MAIN)
        if s is None:
            continue
        add(
            f"| **{arm}** | {ARM_LABEL[arm]} | **{_f(s['false_trigger_rate'])}** "
            f"| {_f(s['negative_any_trigger_rate'])} | {s['phantom_skill_count']} "
            f"| {s['samples']['negatives_valid']}/{s['samples']['negatives_total']} "
            f"| {'是' if s['reliable'] else '**否**'} |"
        )
    add("")
    add("> 幽灵技能计数沿用 `run_comparison.py:599` 的定义：对**全部运行**计数，不只负例。")
    add("")

    # --- 2. 三个子集
    add("## 2. 三个子集（预注册冻结，非事后挑选）")
    add("")
    add("| 子集 | 负例数 | 臂 | 本技能口径 FTR | 广义触发率 | 幽灵技能 |")
    add("|---|---|---|---|---|---|")
    for name in (SUBSET_MAIN, SUBSET_HARD, SUBSET_DISCRIMINATIVE):
        sub = analysis["subsets"][name]
        for arm in ARMS:
            s = analysis["scores"].get(arm, {}).get(name)
            if s is None:
                continue
            add(
                f"| {name} | {sub['n_negatives']} | **{arm}** | {_f(s['false_trigger_rate'])} "
                f"| {_f(s['negative_any_trigger_rate'])} | {s['phantom_skill_count']} |"
            )
    add("")

    # --- 3. Δ2 / Δ2′
    add("## 3. Δ2 与 Δ2′（三种聚合口径 + run 级 + 自助区间）")
    add("")
    for name in (SUBSET_MAIN, SUBSET_HARD, SUBSET_DISCRIMINATIVE):
        sub = analysis["subsets"][name]
        add(f"### {name}（负例 {sub['n_negatives']} 条，每用例 {meta['runs']} 次）")
        add("")
        add("| 聚合口径 | FTR(B) | FTR(C) | **Δ2 = C − B** | FTR(C′) | **Δ2′ = C′ − B** |")
        add("|---|---|---|---|---|---|")
        for rule in rc.SENSITIVITY_RULES:
            e = sub[rule]
            d2 = e["delta2"]
            d2p = e["delta2p"]
            add(
                f"| {rule} | {_f(e['ftr_b'])} | {_f(e['ftr_c'])} | **{_f(d2)}** "
                f"| {_f(e['ftr_cp'])} | **{_f(d2p)}** |"
            )
        rl, rlp = sub["run_level_delta2"], sub["run_level_delta2p"]
        boot, boot2 = sub["bootstrap_delta2p"], sub["bootstrap_delta2"]
        add("")
        add(
            f"- **run 级 Δ2′ = {_f(rlp['point'])}**（C′ {rlp['c_hits']}/{rlp['n_runs']} − "
            f"B {rlp['b_hits']}/{rlp['n_runs']} 次运行），"
            f"95% 自助区间 **[{_f(boot['low'])}, {_f(boot['high'])}]**"
            f"（对用例有放回重抽样 {boot['iters']} 次，种子 {BOOTSTRAP_SEED}）"
        )
        add(
            f"- run 级 Δ2 = {_f(rl['point'])}（C {rl['c_hits']}/{rl['n_runs']}），"
            f"95% 自助区间 [{_f(boot2['low'])}, {_f(boot2['high'])}]"
        )
        add(
            f"- run 级分辨率 = 1/{rlp['n_runs']} = "
            f"{_f(None if not rlp['n_runs'] else 1/rlp['n_runs'])}；"
            f"case 级分辨率 = 1/{sub['n_negatives']} = {_f(1/sub['n_negatives'])}"
        )
        if sub["discordant"]:
            add("")
            add("- **翻转用例（B 与 C′ 逐次命中数不同）**：")
            add("")
            add("  | 用例 | 技能 | B 命中/次数 | C′ 命中/次数 |")
            add("  |---|---|---|---|")
            for d in sub["discordant"]:
                add(f"  | {d['case_id']} | {d['skill']} | {d['b_hits']}/{d['n_runs']} | {d['cp_hits']}/{d['n_runs']} |")
        else:
            add("- **翻转用例：无**（B 与 C′ 在每一条负例上的逐次命中数完全相同）")
        add("")

    # --- 4. 复现对照
    add("## 4. 复现对照（原 40 条用例子集 vs 历史 v1 记录）")
    add("")
    add("| 臂 | 本技能 FTR（本轮/历史） | 广义触发率（本轮/历史） | 幽灵技能（本轮/历史） | 判定 |")
    add("|---|---|---|---|---|")
    for arm in ("A", "B", "C", "D"):
        r = analysis["reproduction"].get(arm)
        if not r:
            continue
        h = r["hist"]
        same_ftr = r["ftr"] == h["ftr"]
        same_broad = r["broad"] is not None and abs(r["broad"] - h["broad"]) <= 0.125
        same_phantom = r["phantom"] == h["phantom"]
        verdict = "完全一致" if (same_ftr and same_broad and same_phantom) else (
            "FTR/广义一致，幽灵数不同" if (same_ftr and same_broad) else "**有差异**")
        add(
            f"| {arm} | {_f(r['ftr'])} / {_f(h['ftr'])} | {_f(r['broad'])} / {_f(h['broad'])} "
            f"| {r['phantom']} / {h['phantom']} | {verdict} |"
        )
    add("")
    add("> 广义触发率容差 ±0.125 = ±2/16（原负例 16 条，最小步长 1/16=0.0625）。")
    add("> 幽灵技能计数在此表上按**原 40 条用例的全部运行**统计，与历史 76 次同分母，可直接比。")
    add("")

    # --- 5. Phantom 明细
    add("## 5. 各臂幽灵技能名明细（S1 全部运行内）")
    add("")
    for arm in ARMS:
        s = analysis["scores"].get(arm, {}).get(SUBSET_MAIN)
        if s is None:
            continue
        names = s.get("phantom_skill_names") or []
        add(f"- **{arm}**（{s['phantom_skill_count']} 次）：{('`' + '`, `'.join(names) + '`') if names else '（无）'}")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 子命令


def selftest() -> int:
    """零 API 成本：核对 A/B/C/D 载荷与原执行器逐字节一致，并验证 C′ 剥离。"""
    ok = True
    for skill in SKILL_NAMES:
        for arm in ("A", "B", "C", "D"):
            mine, theirs = skill_payload_v2(skill, arm), rc.skill_payload(skill, arm)
            same = mine == theirs
            ok &= same
            print(f"{skill:26s} {arm} 与原执行器逐字节一致={same} len={len(mine)}")
    print()
    for skill in SKILL_NAMES:
        b, c, cp = (skill_payload_v2(skill, a) for a in ("B", "C", "Cp"))
        residuals = [
            m for m in ("不适用于", "不该被调用", "不调用", "不适用本清单", "不归", "交 gauge-reading")
            if m in cp
        ]
        print(
            f"{skill:26s} B={len(b):5d} C={len(c):5d} C′={len(cp):5d} "
            f"C′−B={len(cp)-len(b):+5d} 残留={residuals or '（无）'}"
        )
        ok &= not residuals
    print()
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def run_one(arm: str, args: argparse.Namespace) -> int:
    cases, _, _ = load_all_cases()
    if args.limit:
        cases = cases[: args.limit]
    results = rc.run_arm(arm, cases, runs=args.runs, concurrency=args.concurrency)
    if args.out:
        save_arm(arm, cases, results, args.runs, args.concurrency, args.out)
    else:
        failed = sum(1 for r in results if r.error)
        print(f"[{arm}] {len(results)} 次运行，失败 {failed}")
    return 0


def run_gate(args: argparse.Namespace) -> int:
    """复现门禁：A/B/C × 原 16 条负例 × 3 次（预注册 §5）。不通过即停。"""
    _, original, _ = load_all_cases()
    neg = negatives_of(original)
    print(f"门禁用例：原 {len(original)} 条中的 {len(neg)} 条负例 × {args.runs} 次 × 3 臂")
    out: dict[str, Any] = {}
    verdicts: list[bool] = []
    for arm in ("A", "B", "C"):
        results = rc.run_arm(arm, neg, runs=args.runs, concurrency=args.concurrency)
        s = rc.score(results, neg)
        h = HISTORICAL[arm]
        ftr, broad = s["false_trigger_rate"], s["negative_any_trigger_rate"]
        ok_ftr = ftr == h["ftr"]
        ok_broad = broad is not None and abs(broad - h["broad"]) <= 0.125
        verdicts.append(bool(ok_ftr and ok_broad))
        out[arm] = {
            "ftr": ftr, "broad": broad, "phantom": s["phantom_skill_count"],
            "hist_ftr": h["ftr"], "hist_broad": h["broad"],
            "ftr_ok": ok_ftr, "broad_ok": ok_broad,
            "samples": s["samples"], "reliable": s["reliable"],
            "results": [
                {"case_id": r.case_id, "run_index": r.run_index, "triggered": r.triggered,
                 "route": r.route, "usage": r.output["usage"], "latency_ms": r.latency_ms,
                 "raw_response": r.raw_response, "error": r.error, "attempts": r.attempts}
                for r in results
            ],
        }
        print(
            f"  {arm}: FTR={ftr}（历史 {h['ftr']}，{'OK' if ok_ftr else '**差异**'}） "
            f"广义={broad}（历史 {h['broad']}，{'OK' if ok_broad else '**差异**'}） "
            f"幽灵={s['phantom_skill_count']}"
        )
    passed = all(verdicts)
    out["_verdict"] = {"pass": passed, "arms": {"ABC"[i]: verdicts[i] for i in range(3)}}
    print(f"\n门禁判定：{'通过 —— 可跑主实验' if passed else '**不通过 —— 停止，先报告差异**'}")
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"写入 {args.out}")
    return 0 if passed else 1


def run_report(args: argparse.Namespace) -> int:
    results_by_arm: dict[str, list[rc.CaseResult]] = {}
    for path in sorted(args.report):
        arm, results = load_arm_results(path)
        if arm in results_by_arm:
            print(f"警告：{arm} 臂出现多份结果文件，后者覆盖前者：{path}")
        results_by_arm[arm] = results
    all_cases, original, _ = load_all_cases()
    analysis = analyse(results_by_arm, all_cases, original)
    meta = {
        "model": "step-5-preview",
        "runs": 3,
        "concurrency": args.concurrency,
        "n_cases": len(all_cases),
        "n_neg": sum(1 for c in all_cases if not c["expect_trigger"]),
        "n_pos": sum(1 for c in all_cases if c["expect_trigger"]),
        "when": args.when,
    }
    markdown = render(results_by_arm, analysis, meta)
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"写入 {args.out}")
    else:
        print(markdown)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"写入 {args.json_out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Not-for 消融 v2（五臂）")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--gate", action="store_true", help="复现门禁：A/B/C × 原 16 负例 × 3")
    parser.add_argument("--arm", choices=list(ARMS))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out")
    parser.add_argument("--json-out")
    parser.add_argument("--report", nargs="*", default=[])
    parser.add_argument("--when", default="")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    patch_runner()

    if args.arm:
        return run_one(args.arm, args)
    if args.gate:
        return run_gate(args)
    if args.report:
        return run_report(args)
    parser.error("需要 --selftest / --gate / --arm / --report")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
