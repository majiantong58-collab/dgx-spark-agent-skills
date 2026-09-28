#!/usr/bin/env python
"""mes-closed-loop 闭环编排逻辑。

🔴 **编排层只做路由，不含识别 / 判级 / 落单 / 查询逻辑——一律下沉到子技能。**

链路（每一步的产物必须被下一步真正消费，见 `run_chain()` 的消费证明）：
    识别产物 ──► mes-business-rules ──► mes-inspection-intake ──► mes-record-query ──► inspection-report
   (findings)      (dept/iso 判据)        (inbox.json)            (占用回执)          (成文)

与 invda `inspection-orchestrator` 的边界（一刀切）：
  · 它  = 给了图但**未指明识别类型** → 管「识别什么」
  · 本  = **必须出现 MES 语境** → 管「发现如何变成业务动作」；识别一律**调**它，不自己判
  · 没提 MES → 不进 MES 侧（gate 直接判 false）

契约：`docs/agents/mes-bridge-contract.md` v1.9（§C.3 部门映射 / §C.5 iso / §C.6 产物可验证性）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]


class LoopError(Exception):
    """可预期失败：调用方打印人话并以退出码 1 结束。"""


def sys_path_add(path: Path) -> None:
    """跨技能 import 手法：把子技能 scripts/ 挂上 sys.path（mes-team.md §10）。"""
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------------
# 触发闸门：MES 语境（[团队自定] —— MES 无「哪些话算 MES 语境」的明文规则）
# --------------------------------------------------------------------------

RE_DOCNO = re.compile(r"(?<![\w-])(?:MO-\d{8}-\d{3}|MO-\d{4}-\d{2}-\d{4}|QA-\d{8}-\d{3})(?!\d)")

# 业务动作词：把「发现」推向「系统里的单」的动词与对象
INTAKE_WORDS = ("落单", "开单", "建单", "落成", "录入", "录进", "入系统", "报单", "提单")
QUERY_WORDS = ("查一下", "查询", "查查", "什么状态", "状态是", "是否占用", "可用吗", "被占用", "台账里")
MES_WORDS = ("MES", "mes", "异常单", "品质异常", "巡检单", "工单", "整改", "闭环", "台帐", "台账",
             "追溯", "回执", "存档", "归档")


def gate(text: str) -> dict:
    """判定是否进入 MES 侧。返回 {trigger, hits, why}。"""
    hits = sorted({w for w in MES_WORDS if w in text})
    docs = RE_DOCNO.findall(text or "")
    for w in INTAKE_WORDS + QUERY_WORDS:
        if w in (text or ""):
            hits.append(w)
    hits = sorted(set(hits))
    if docs or hits:
        why = "、".join(([f"单号 {d}" for d in docs] + hits)[:6])
        return {"trigger": True, "hits": hits, "docs": docs, "why": why}
    return {"trigger": False, "hits": [], "docs": [],
            "why": "未检出 MES 语境（无单号、无落单/查询动作词、无 MES 业务对象）"}


def plan(text: str) -> list:
    """决定 MES 侧子技能序列。返回 [(步骤, 技能, 理由)]。"""
    g = gate(text)
    if not g["trigger"]:
        return []
    wanted_intake = any(w in text for w in INTAKE_WORDS)
    wanted_query = any(w in text for w in QUERY_WORDS) or bool(g["docs"])
    if wanted_intake:
        return [
            ("识别", "inspection-orchestrator → safety-hazard-detection",
             "有图/发现但未指明识别类型 → 调识别层（编排层不自己判）"),
            ("判级/部门/隔离", "mes-business-rules", "§C.3 部门映射 + §C.5 iso 口径"),
            ("落单", "mes-inspection-intake", "§C.1 取号（下限 100）+ 写 inbox.json"),
            ("回执", "mes-record-query", "查重前置 + 落单后确认号已占用"),
            ("成文", "inspection-report", "结论成文与导出"),
        ]
    if wanted_query:
        return [("查询", "mes-record-query", "只读查询，不落单")]
    return [("判级", "mes-business-rules", "只要口径，无落单也无查询")]


def recognition_route(text: str, frames: list | None = None, site: str = "未指定") -> list:
    """把识别路由**委托**给 invda `inspection-orchestrator`（编排层不自己判识别）。

    🔴 无帧则不委托：该编排层的 `normalize_input` **按契约拒收纯文本请求**
    （`route.py:91`「无图像的任务不进编排层」）。**本层不伪造帧路径**去骗过校验。
    """
    if not frames:
        return ["识别路由：未给帧 → 不委托（orchestrator 按契约拒收无帧请求 route.py:91）；"
                "帧齐备时再由识别层判定识别子技能"]
    try:
        sys_path_add(SKILLS / "inspection-orchestrator" / "scripts")
        import route as orch  # noqa: E402

        inp = orch.normalize_input({"frames": list(frames), "text": text, "site": site})
        return [f"识别路由（委托 orchestrator）：{d.skill} · tier={d.tier} · {d.reason}"
                for d in orch.plan_routes(inp)]
    except Exception as exc:  # noqa: BLE001 - 委托失败降级为人工指定，闭环其余步骤不依赖它
        return [f"识别路由：委托失败（{type(exc).__name__}: {exc}），降级为人工指定识别子技能"]


# --------------------------------------------------------------------------
# 闭环执行 + 空转防护（每步产物必须被下一步消费）
# --------------------------------------------------------------------------

def _load_finding(path: Path) -> dict:
    if not path.is_file():
        raise LoopError(f"识别产物不存在：{path.name}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoopError(f"识别产物不是合法 JSON：{path.name} 第 {exc.lineno} 行") from exc
    finds = doc.get("findings") if isinstance(doc, dict) else None
    if not finds:
        raise LoopError("识别产物内无 findings[]：没有发现就没有业务动作可编排")
    return doc


def rules_expect(finding: dict) -> dict:
    """查 mes-business-rules 得判据（本步只读规则，不做决定）。

    锚点：契约 §C.3「人员违规（PPE / 闯入）→ 生产部」；§C.5「iso 默认 false」。
    """
    label = f"{finding.get('label', '')}{finding.get('code', '')}"
    if "防静电" in label or "服装" in label or "PPE" in label.upper() or "人员" in label:
        return {"dept": "生产部", "iso": False, "rule": "§C.3 人员违规 → 生产部；§C.5 iso=false"}
    raise LoopError(f"规则未覆盖该发现类型（§C.3 只覆盖 4 类，v1.7 起演示仅可用「人员违规」）：{label[:24]}")


def run_chain(finding_path: Path, out_dir: Path, proto: Path, candidate: str | None = None) -> dict:
    """跑闭环。返回 {log, checks, record}。任一步消费证明失败即抛 LoopError。"""
    log, checks = [], []

    # ── 步 0：识别产物（由识别层产出；编排层不识别，故从产物起跑）
    doc = _load_finding(finding_path)
    finding = doc["findings"][0]
    log.append(f"识别产物：{finding_path.name} · {len(doc['findings'])} 条发现 · "
               f"site={doc.get('site', '未指定')}")

    # ── 步 1：mes-business-rules → 判据（下游 intake 必须消费它）
    exp = rules_expect(finding)
    log.append(f"规则判据：dept={exp['dept']} iso={exp['iso']}（{exp['rule']}）")

    # ── 步 2：mes-record-query 查重 **前置**（候选号已占用则不得落单）
    sys_path_add(SKILLS / "mes-record-query" / "scripts")
    import query_core  # noqa: E402

    read_log = {}
    proto_text = query_core.read_text(proto, read_log)
    proto_hits = query_core.scan_proto(proto_text)
    data = query_core.load_mes_data(out_dir, read_log)
    if candidate:
        c = query_core.check_number(proto_hits, data, candidate)
        verdict = "已占用" if "已占用" in "".join(c) else "可用"
        log.append(f"查重前置：{candidate} → {verdict}")
        if verdict == "已占用":
            raise LoopError(f"候选号 {candidate} 已被占用，按查重前置规则**不落单**（换号或让 intake 自取号）")
        checks.append("查重前置：候选号未被占用 → 允许落单")
    else:
        log.append(f"查重前置：未给候选号；intake 按 §C.1 自取号（下限 100），落单后回执复核")

    # ── 步 3：mes-inspection-intake 落单（本步是全链唯一的写动作）
    sys_path_add(SKILLS / "mes-inspection-intake" / "scripts")
    import intake_core  # noqa: E402

    out_dir.mkdir(parents=True, exist_ok=True)
    inbox = out_dir / "inbox.json"
    result = intake_core.commit_findings(str(finding_path), str(inbox), None, None)
    if not inbox.is_file():
        raise LoopError("空转断链：intake 回来了但没有产出 inbox.json —— 落单步等于空转")
    try:
        produced = json.loads(inbox.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoopError(f"空转断链：intake 产出的 inbox.json 不是合法 JSON 第 {exc.lineno} 行") from exc
    if not produced.get("records"):
        raise LoopError("空转断链：inbox.json 的 records[] 为空 —— 没有单据可回执")
    rec = produced["records"][-1]
    log.append(f"落单产出：{inbox.name} · no={rec['no']} rel={rec['rel']} dept={rec['dept']} iso={rec['iso']}")

    # 消费证明 ①：rules 的判据被 intake 真正消费（不是调了没用）
    if rec["dept"] != exp["dept"]:
        raise LoopError(f"空转断链：规则判据 dept={exp['dept']}，而 intake 落的是 {rec['dept']}")
    if bool(rec["iso"]) != exp["iso"]:
        raise LoopError(f"空转断链：规则判据 iso={exp['iso']}，而 intake 落的是 {rec['iso']}")
    checks.append(f"消费证明① rules→intake：dept={rec['dept']} / iso={rec['iso']} 与判据一致")

    xj = out_dir / "xj-records.json"
    if not xj.is_file():
        raise LoopError("空转断链：§C.2 要求 rel 指向的 XJ 记录由 intake 一并产出，但未见到 xj-records.json")
    xj_doc = json.loads(xj.read_text(encoding="utf-8"))
    rel_refs = [r.get("no") for r in xj_doc.get("records", [])]
    if rec["rel"] not in rel_refs:
        raise LoopError(f"空转断链：inbox 的 rel={rec['rel']} 在 xj-records.json 中查无对应记录")
    checks.append(f"消费证明② intake→§C.2：rel={rec['rel']} 在 xj-records.json 内有实体记录")

    # ── 步 4：mes-record-query 回执（重新读盘 —— 必须看得见刚落的单）
    read_log2 = {}
    data2 = query_core.load_mes_data(out_dir, read_log2)
    fresh = [h for h in data2["hits"] if h["no"] == rec["no"]]
    if not fresh:
        raise LoopError(f"空转断链：刚落的 {rec['no']} 在 mes-data 回执中查不到 —— intake 产物未进 query")
    checks.append(f"消费证明③ intake→query：{rec['no']} 经查重回执判为已占用"
                  f"（命中 {fresh[0]['where']} 字段 {fresh[0]['hint']}）")
    log.append(f"回执：{rec['no']} → 已占用（{fresh[0]['where']}）")

    # ── 步 5：inspection-report 成文（消费上一步产物；本步只构造并校验输入信封）
    envelope = {
        "hazard_code": finding.get("code"),
        "confidence": finding.get("confidence"),
        "site": doc.get("site", "未指定"),
        "captured_at": doc.get("captured_at"),
        "mes_record": {"no": rec["no"], "rel": rec["rel"], "dept": rec["dept"]},
        "receipt": {"checked_by": "mes-record-query", "verdict": "已占用"},
    }
    missing = [k for k in ("hazard_code", "confidence") if envelope.get(k) in (None, "")]
    if missing:
        raise LoopError(f"空转断链：报告输入缺 {'/'.join(missing)}（inspection-report 前置硬要求，缺则拒收）")
    if not envelope["mes_record"]["no"]:
        raise LoopError("空转断链：报告输入未引用刚落下的 MES 单号")
    checks.append(f"消费证明④ query→report：报告输入引用 mes_record.no={rec['no']}，"
                  f"且 hazard_code/confidence 齐备")

    return {"log": log, "checks": checks, "record": rec, "envelope": envelope,
            "progress": result.get("progress", [])}
