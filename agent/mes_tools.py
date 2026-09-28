"""MES Agent 的工具层：把已有技能脚本包成「大脑能调的动作」。

设计原则（沿用本项目一路的规矩）
--------------------------------
1. **不重写业务逻辑**。查询走 `mes-record-query/query_core.py`，落单走
   `mes-inspection-intake/intake_core.py` —— 那两处是契约的唯一实现。
   本文件只做「参数校验 + 调用 + 把人话结果整理成字符串」。
2. **错了就说错**。契约强制的字段（confidence / evidence_ref）缺了直接报错，
   不用默认值兜底 —— 兜底会让「没有证据的单」看起来像正常单。
3. **零依赖**。只用标准库，所以整个 agent 能跑在 `.venv` 里（那里有 torch），
   也能跑在系统 python 里，两边都不需要装包。

消费方：`agent/mes_agent.py`（大脑循环）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 两个技能的脚本目录：加进 sys.path 后直接 import 它们的 core
_QUERY_DIR = REPO / "skills" / "mes-record-query" / "scripts"
_INTAKE_DIR = REPO / "skills" / "mes-inspection-intake" / "scripts"
for _d in (_QUERY_DIR, _INTAKE_DIR):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

# 这两个 core 是「只读 / 可复现」技能的实现，import 不能顺手写 .pyc
sys.dont_write_bytecode = True

import query_core as qcore  # noqa: E402
import intake_core as icore  # noqa: E402


class ToolError(Exception):
    """工具执行失败。消息是给人看的，会被原样回灌给大脑。"""


# --------------------------------------------------------------------------
# 宿主页与数据目录：缺省序与 query.py 一致（--proto > MES_PROTO > 仓库内宿主页）
# --------------------------------------------------------------------------

def resolve_hosts(proto: str | None = None, data_dir: str | None = None):
    """返回 (原型 index.html, mes-data 目录)。**不猜路径**：找不到就报错问。"""
    raw = proto or os.environ.get("MES_PROTO")
    if not raw:
        cand = REPO / "docs" / "mes-demo" / "index.html"
        if not cand.is_file():
            raise ToolError(
                "找不到 MES 宿主页：仓库内 docs/mes-demo/index.html 不存在，"
                "请用 MES_PROTO 环境变量指定原型 index.html 的位置（本工具不猜路径）"
            )
        raw = str(cand)
    p = Path(raw)
    if p.is_dir():
        p = p / "index.html"
    if not p.is_file():
        raise ToolError(f"宿主页不存在：{p.name}")
    dd = Path(data_dir) if data_dir else p.parent / "mes-data"
    return p, dd


def _load(proto: str | None, data_dir: str | None):
    """读原型 + mes-data。每次调用都重读 —— 因为 agent 可能刚写完单，
    缓存会让它读到旧世界（「我刚落的单查不到」是最难查的一类 bug）。"""
    page, dd = resolve_hosts(proto, data_dir)
    log: dict = {}
    text = qcore.read_text(page, log)
    data = qcore.load_mes_data(dd, log)
    return text, data, page, dd


def _redact(s: str) -> str:
    """抹掉本机绝对路径（契约 §D）。"""
    out = str(s)
    for root, tag in ((REPO, "<repo>"), (Path.home(), "<home>")):
        for form in (str(root), root.as_posix()):
            out = out.replace(form, tag)
    return out


# --------------------------------------------------------------------------
# 工具 1–4：只读查询（全部复用 query_core）
# --------------------------------------------------------------------------

def query_exception(no: str = "", dept: str = "", status: str = "", **kw) -> str:
    text, data, _, _ = _load(kw.get("proto"), kw.get("data_dir"))
    if no:
        qcore.validate("exc", no)
    # 🔴 dept / status 必须在这层自己守：query_core.query_exceptions 的**列表**分支
    # 只做过滤、不做枚举校验（守卫 _guard 只覆盖「按单号查单条」那条路），
    # 所以传一个不存在的部门会**静默返回「命中 0 行」**——读起来像「没有这种单」，
    # 实际是「你给的词根本不在枚举里」。两种含义差别很大，这里直接判死。
    if dept and dept not in qcore.EXC_DEPTS:
        raise ToolError(f"部门不在枚举内：{dept!r}（只允许 {'/'.join(qcore.EXC_DEPTS)}）")
    if status and status not in qcore.EXC_STATUS:
        raise ToolError(f"状态不在枚举内：{status!r}（只允许 {'/'.join(qcore.EXC_STATUS)}）")
    lines = qcore.query_exceptions(text, no or "", dept or None, status or None)
    # mes-data 里我们自己的产出入也要一并看（契约 §C：两处都查）
    for _name, rec in data["records"]:
        if no and rec.get("no") == no:
            lines.append(f"（我们的产出入亦命中）{json.dumps(rec, ensure_ascii=False)}")
        elif not no and dept and rec.get("dept") == dept:
            lines.append(f"（我们的产出入亦命中）{json.dumps(rec, ensure_ascii=False)}")
    return "\n".join(lines) if lines else "没查到匹配的异常单。"


def query_workorder(no: str, **kw) -> str:
    text, _, _, _ = _load(kw.get("proto"), kw.get("data_dir"))
    qcore.validate("wo", no)
    lines = qcore.query_workorder(text, no)
    return "\n".join(lines) if lines else f"没查到工单 {no}。"


def query_equipment(code: str, **kw) -> str:
    text, _, _, _ = _load(kw.get("proto"), kw.get("data_dir"))
    qcore.validate("dev", code)
    lines = qcore.query_equipment(text, code)
    return "\n".join(lines) if lines else f"没查到设备 {code}。"


def check_number(no: str, **kw) -> str:
    text, data, _, _ = _load(kw.get("proto"), kw.get("data_dir"))
    qcore.validate("check", no)
    lines = qcore.check_number(qcore.scan_proto(text), data, no)
    return "\n".join(lines) if lines else f"{no}：没查到占用记录。"


# --------------------------------------------------------------------------
# 工具 5：落单（写）
# --------------------------------------------------------------------------

def create_exception(desc: str, dept: str, confidence: float,
                     evidence_ref: str, source: str = "safety-hazard-detection",
                     date: str = "", time: str = "", **kw) -> str:
    """把一条发现落成 MES 品质异常单。

    🔴 confidence 与 evidence_ref 是**契约强制的**（routing-table §3：上游硬规则
    要求拒收无置信度条目；evidence_ref 必填）。本工具**不提供默认值** ——
    给了默认值，就会产出「看起来正常、实际没有证据」的单，那比报错坏得多。
    """
    if confidence is None:
        raise ToolError("缺 confidence：契约要求拒收无置信度的条目（不给默认值）")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise ToolError(f"confidence 必须是数字，收到 {confidence!r}") from None
    if not (0.0 <= confidence <= 1.0):
        raise ToolError(f"confidence 需在 0–1 之间，收到 {confidence}")
    if not str(evidence_ref).strip():
        raise ToolError("缺 evidence_ref：契约要求必填（指出证据在哪）")

    finding = {
        "code": "PPE-VIOLATION",
        "label": desc,
        "confidence": confidence,
        "evidence_ref": evidence_ref,
        "source": source,
    }
    if date:
        finding["captured_at"] = f"{date}T{time or '00:00'}:00+08:00"

    _page, dd = resolve_hosts(kw.get("proto"), kw.get("data_dir"))
    out = dd / "inbox.json"
    try:
        result = icore.commit_findings(
            json.dumps(finding, ensure_ascii=False), str(out), date or None, dept or None
        )
    except icore.IntakeError as exc:
        raise ToolError(f"落单被拒：{exc}") from None

    progress = result.get("progress") or []
    return "落单完成：\n" + "\n".join(progress)


# --------------------------------------------------------------------------
# 清单：给大脑看的工具定义（JSON Schema）+ 执行表
# --------------------------------------------------------------------------

_WRITE_OPTS = {
    "proto": {"type": "string", "description": "宿主页 index.html 路径；不填用仓库内默认"},
    "data_dir": {"type": "string", "description": "mes-data 目录；不填取宿主页同级的 mes-data"},
}

TOOL_SCHEMAS = [
    {
        "name": "query_exception",
        "description": "查 MES 品质异常单。给 no 查单条详情；不给 no 则按 dept / status 列列表。"
                       "不带任何参数 = 列出全部。",
        "input_schema": {
            "type": "object",
            "properties": {
                "no": {"type": "string", "description": "异常单号，如 QA-20260813-100"},
                "dept": {"type": "string", "enum": ["供应商", "生产部", "设备部", "采购部"]},
                "status": {"type": "string", "enum": ["found", "handling", "recheck", "closed"]},
                **_WRITE_OPTS,
            },
        },
    },
    {
        "name": "query_workorder",
        "description": "按工单号查工单：状态 / 数量 / 产线。工单号形如 MO-20260812-006 或 MO-2026-08-006。",
        "input_schema": {
            "type": "object",
            "properties": {"no": {"type": "string"}, **_WRITE_OPTS},
            "required": ["no"],
        },
    },
    {
        "name": "query_equipment",
        "description": "按设备编号查设备台账：名称型号 / 工位 / 车间产线 / 接口类型 / 状态。",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "设备编号，如 FT-01"}, **_WRITE_OPTS},
            "required": ["code"],
        },
    },
    {
        "name": "check_number",
        "description": "单号查重：给一个候选号，判「可用 / 已占用」，并指出占用在哪一处。"
                       "**落单前应先查重**。",
        "input_schema": {
            "type": "object",
            "properties": {"no": {"type": "string"}, **_WRITE_OPTS},
            "required": ["no"],
        },
    },
    {
        "name": "create_exception",
        "description": "把一条巡检发现落成 MES 品质异常单（**写操作**）。"
                       "confidence 与 evidence_ref 为契约强制，必须来自一次真实检测，不得编造。",
        "input_schema": {
            "type": "object",
            "properties": {
                "desc": {"type": "string", "description": "异常现象，如「洁净间 2 号工位 1 名人员未穿防静电服」"},
                "dept": {"type": "string", "enum": ["供应商", "生产部", "设备部", "采购部"]},
                "confidence": {"type": "number", "description": "检测置信度 0–1，来自真实检测结果"},
                "evidence_ref": {"type": "string", "description": "证据文件相对路径，来自真实检测结果"},
                "source": {"type": "string", "description": "产出该发现的技能名"},
                "date": {"type": "string", "description": "YYYY-MM-DD；不填用系统当天"},
                "time": {"type": "string", "description": "HH:MM"},
            },
            "required": ["desc", "dept", "confidence", "evidence_ref"],
        },
    },
]

EXECUTORS = {
    "query_exception": query_exception,
    "query_workorder": query_workorder,
    "query_equipment": query_equipment,
    "check_number": check_number,
    "create_exception": create_exception,
}


def execute(name: str, args: dict) -> tuple[str, bool]:
    """执行一个工具。返回 (结果文本, 是否成功)。

    失败也返回文本而不是抛出去 —— 大脑需要看到失败原因才能改主意，
    把异常吞掉它只会重复同一个错。
    """
    fn = EXECUTORS.get(name)
    if fn is None:
        return f"没有这个工具：{name}", False
    try:
        return fn(**args), True
    except (ToolError, qcore.QueryError, icore.IntakeError) as exc:
        return f"工具执行失败：{_redact(exc)}", False
    except TypeError as exc:  # 参数名写错
        return f"工具参数不对：{_redact(exc)}", False
    except Exception as exc:  # noqa: BLE001 - 不吞，但也不让 agent 崩掉
        return f"工具异常 {type(exc).__name__}：{_redact(exc)}", False
