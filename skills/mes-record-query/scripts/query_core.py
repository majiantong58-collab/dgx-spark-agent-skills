#!/usr/bin/env python
"""mes-record-query 查询逻辑（纯只读）。

数据来源两处，缺一不可（契约 §C:133 规定 mes-data 位置）：
  ① MES 原型 index.html —— 静态种子行（工单 / 设备台账 / 异常单）
  ② <mes-data>/*.json —— 我们自己的产出入（inbox.json / xj-records.json）

本模块**不写任何文件**：被读文件在读取时与进程结束前各算一次 sha256，
由调用方用 `self_check()` 比对，作为只读自证。

锚点（行号为 交付物/mes-prototype/index.html 实测，2026-09-28）：
  WO_ST        :11345-11353   工单状态 → [中文, badge]
  WORKORDERS   :11354         工单行 {no,qty,ps,pe,st,sync,line,prog,reason}
  异常单行      :2255          <tr data-no data-rel data-dept data-status data-date>
  设备台账行    :5520-5526     <tr data-dcm-eq-row data-ws data-line data-st>
  占位符示例    :2228 / :10370 / :11714  「如 QA-…」等 —— 不算占用
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class QueryError(Exception):
    """可预期失败：调用方打印人话并以退出码 1 结束。"""


# --- 单号格式（真源：契约 §C.1 QA-YYYYMMDD-NNN / §C.2 XJ<YYYYMMDD><NNN>） ---
_NUM = r"(?:QA-\d{8}-\d{3}(?!\d)|MO-\d{8}-\d{3}(?!\d)|MO-\d{4}-\d{2}-\d{4}(?!\d)|XJ\d{11}(?!\d))"
RE_ANY_NUM = re.compile(r"(?<![\w-])" + _NUM)

RE_EXC = re.compile(r"QA-\d{8}-\d{3}")
RE_WO = re.compile(r"MO-\d{8}-\d{3}|MO-\d{4}-\d{2}-\d{4}")
RE_DEV = re.compile(r"[A-Z]{2,4}-\d{2,4}")

# 选择器格式校验：选择器 → (正则, 人话示例)
SELECTORS = {
    "wo": (RE_WO, "工单号形如 MO-20260812-006"),
    "dev": (RE_DEV, "设备编号形如 FT-01"),
    "exc": (RE_EXC, "异常单号形如 QA-20260813-001"),
}

# 原型里的示例占位符（「如 QA-20260813-001」）是提示文本、不是占用，先抹掉再扫
RE_PLACEHOLDER = re.compile(r"placeholder\s*[:=]\s*([\"']).*?\1")

# 命中处的字段名（给「在哪一处」提供可核对的锚点）
RE_HINT = re.compile(r"(data-[a-z-]+|related_exception|no|rel|wo)\s*[:=]\s*[\"']?$")


# --------------------------------------------------------------------------
# 读文件 + 只读自证
# --------------------------------------------------------------------------

def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_text(path: Path, read_log: dict) -> str:
    """读文本并登记 sha256（读前算一次，供事后比对）。"""
    if not path.is_file():
        raise QueryError(f"文件不存在或不是文件：{path.name}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QueryError(f"读取失败：{path.name} —— {exc}") from exc
    read_log[path] = hashlib.sha256(raw).hexdigest()
    return raw.decode("utf-8", errors="replace")


def self_check(read_log: dict) -> list:
    """重算被读文件 sha256；返回与读前不一致的清单（空 = 只读自证通过）。"""
    drift = []
    for path, before in read_log.items():
        try:
            after = _digest(path)
        except OSError as exc:
            drift.append((path.name, before[:12], f"重读失败 {exc}"))
            continue
        if after != before:
            drift.append((path.name, before[:12], after[:12]))
    return drift


# --------------------------------------------------------------------------
# 原型 HTML：解析
# --------------------------------------------------------------------------

def _strip_placeholders(text: str) -> str:
    return RE_PLACEHOLDER.sub("placeholder=", text)


def _hint(line: str, start: int) -> str:
    m = RE_HINT.search(line[max(0, start - 48):start])
    return m.group(1) if m else "未识别字段"


def scan_proto(text: str) -> list:
    """扫原型全文的单号占用。返回 [{no, where, hint}]，where 带行号。"""
    hits = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = _strip_placeholders(raw)
        for m in RE_ANY_NUM.finditer(line):
            hits.append({"no": m.group(0), "where": f"原型:{i}", "hint": _hint(line, m.start())})
    return hits


def _js_str(line: str, key: str):
    m = re.search(rf"\b{key}:\s*'([^']*)'", line)
    return m.group(1) if m else None


def _js_num(line: str, key: str):
    m = re.search(rf"\b{key}:\s*(\d+)", line)
    return m.group(1) if m else None


def parse_wo_state(text: str) -> dict:
    """解析 WO_ST 映射（:11345）。返回 {st: (中文, badge)}。"""
    block = re.search(r"var\s+WO_ST\s*=\s*\{(?P<body>.*?)\};", text, re.S)
    if not block:
        raise QueryError("原型内未找到 WO_ST 状态映射（版本可能已变，锚点见 references/query-sources.md）")
    out = {}
    for m in re.finditer(r"(\w+):\s*\[\s*'([^']*)'\s*,\s*'([^']*)'", block.group("body")):
        out[m.group(1)] = (m.group(2), m.group(3))
    return out


def parse_workorders(text: str) -> dict:
    """解析 WORKORDERS（:11354）。返回 {no: {…}}。"""
    rows = {}
    for line in text.splitlines():
        if "no: '" not in line or "st: '" not in line:
            continue
        no = _js_str(line, "no")
        if not no or not RE_WO.fullmatch(no):
            continue
        rows[no] = {
            "no": no,
            "qty": _js_num(line, "qty"),
            "ps": _js_str(line, "ps"),
            "pe": _js_str(line, "pe"),
            "st": _js_str(line, "st"),
            "sync": _js_str(line, "sync"),
            "line": _js_str(line, "line"),
            "reason": _js_str(line, "reason"),
        }
    return rows


RE_EXC_BLOCK = re.compile(
    r"<tr\s+(?P<attrs>[^>]*data-no=\"[^\"]+\"[^>]*)>(?P<body>.*?)</tr>", re.S
)
RE_TD = re.compile(r"<td[^>]*>(?P<v>.*?)</td>", re.S)


def _attr(attrs: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', attrs)
    return m.group(1) if m else ""


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def parse_exceptions(text: str) -> list:
    """解析 qm-quality-exception 行（:2255 起）。"""
    rows = []
    for m in RE_EXC_BLOCK.finditer(text):
        attrs, body = m.group("attrs"), m.group("body")
        tds = [_plain(t.group("v")) for t in RE_TD.finditer(body)]
        title = re.search(r'title="([^"]*)"', body)
        rows.append({
            "no": _attr(attrs, "data-no"),
            "rel": _attr(attrs, "data-rel"),
            "dept": _attr(attrs, "data-dept"),
            "status": _attr(attrs, "data-status"),
            "date": _attr(attrs, "data-date"),
            "desc": title.group(1) if title else (tds[3] if len(tds) > 3 else ""),
            "iso_show": tds[6] if len(tds) > 6 else "?",
            "owner": tds[7] if len(tds) > 7 else "?",
            "time": tds[8] if len(tds) > 8 else "?",
        })
    return rows


RE_EQ_BLOCK = re.compile(r"<tr\s+data-dcm-eq-row\b(?P<attrs>[^>]*)>(?P<body>.*?)</tr>", re.S)


def parse_equipment(text: str) -> list:
    """解析 dcm-equipment-ledger 行（:5520 起）。"""
    rows = []
    for m in RE_EQ_BLOCK.finditer(text):
        attrs, body = m.group("attrs"), m.group("body")
        tds = [_plain(t.group("v")) for t in RE_TD.finditer(body)]
        if not tds:
            continue
        rows.append({
            "code": tds[0],
            "name": tds[1] if len(tds) > 1 else "?",
            "station": tds[2] if len(tds) > 2 else "?",
            "ws_line": tds[3] if len(tds) > 3 else "?",
            "iface": tds[4] if len(tds) > 4 else "?",
            "st": _attr(attrs, "data-st"),
            "st_show": tds[5] if len(tds) > 5 else "?",
        })
    return rows


# --------------------------------------------------------------------------
# mes-data：扫描（schema 无关 —— 递归取全部字符串值）
# --------------------------------------------------------------------------

def _walk(node, prefix=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, node


def load_mes_data(data_dir: Path, read_log: dict) -> dict:
    """读 mes-data/*.json。返回 {hits, files, records, notes}。"""
    hits, files, records, notes = [], [], [], []
    if not data_dir.is_dir():
        return {"hits": hits, "files": files, "records": records,
                "notes": [f"mes-data 目录不存在（{data_dir.name}），本次未纳入"]}

    for jf in sorted(data_dir.glob("*.json")):
        text = read_text(jf, read_log)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise QueryError(f"mes-data 内含坏 JSON：{jf.name} 第 {exc.lineno} 行 —— 不猜测、不跳过") from exc
        files.append(jf.name)
        for path, val in _walk(data):
            if isinstance(val, str) and RE_ANY_NUM.fullmatch(val):
                hits.append({"no": val, "where": f"mes-data:{jf.name}", "hint": path})
        for rec in (data.get("records") or []):
            if isinstance(rec, dict):
                records.append((jf.name, rec))
    if not files:
        notes.append("mes-data 目录为空，本次未纳入")
    return {"hits": hits, "files": files, "records": records, "notes": notes}


# --------------------------------------------------------------------------
# 四类查询
# --------------------------------------------------------------------------

def query_workorder(text: str, no: str) -> list:
    row = parse_workorders(text).get(no)
    if not row:
        return [f"工单 {no}：原型内未找到（WORKORDERS 只有原型种子行；ERP 同步来的新单不在本库）"]
    label, _badge = parse_wo_state(text).get(row["st"], (row["st"], ""))
    return [
        f"工单 {row['no']}",
        f"  状态：{label}（原型枚举值 {row['st']}）",
        f"  数量：{row['qty']} 台",
        f"  产线：{row['line'] or '未派线（line: null）'}",
        f"  计划：{row['ps']} → {row['pe']}",
        f"  同步：{row['sync']}（INT-ERP-001 快照时点）",
    ] + ([f"  暂停原因：{row['reason']}"] if row["reason"] else [])


def query_equipment(text: str, code: str) -> list:
    for row in parse_equipment(text):
        if row["code"] != code:
            continue
        return [
            f"设备 {row['code']}",
            f"  名称 / 型号：{row['name']}",
            f"  所属工位：{row['station']}",
            f"  车间 / 产线：{row['ws_line']}",
            f"  接口类型：{row['iface']}",
            f"  状态：{row['st_show']}（原型行属性 data-st={row['st']}）",
            "  采集标识：MachineSN 与设备编号同源映射（INT-DCM-002，原型 :15197）",
        ]
    return [f"设备 {code}：原型设备台账内未找到（台账共 {len(parse_equipment(text))} 行）"]


def query_exceptions(text: str, exc_no: str, dept: str, status: str) -> list:
    rows = parse_exceptions(text)
    out = []
    if exc_no:
        mine = [r for r in rows if r["no"] == exc_no]
        if not mine:
            out.append(f"异常单 {exc_no}：原型 qm-quality-exception 内未找到（原型共 {len(rows)} 行）")
        for r in mine:
            out += [
                f"异常单 {r['no']}",
                f"  关联单：{r['rel']}",
                f"  描述：{r['desc']}",
                f"  责任部门：{r['dept']}",
                f"  状态：{r['status']} / 隔离列显示：{r['iso_show']}",
                f"  日期 / 时间：{r['date']} {r['time']}",
                f"  责任人：{r['owner']}",
            ]
    else:
        sel = [r for r in rows if (not dept or r["dept"] == dept) and (not status or r["status"] == status)]
        cond = " · ".join(x for x in (f"部门={dept}" if dept else "", f"状态={status}" if status else "") if x)
        out.append(f"异常单查询（{cond or '全部'}）：命中 {len(sel)} / 原型共 {len(rows)} 行")
        for r in sel[:20]:
            out.append(f"  {r['no']}  {r['dept']}  {r['status']}  {r['date']}  {r['desc'][:28]}")
        if len(sel) > 20:
            out.append(f"  …（其余 {len(sel) - 20} 行略）")
    return out


def check_number(proto_hits: list, data: dict, candidate: str) -> list:
    """查重：原型 + mes-data 两处都查，任一命中即「已占用」。

    偏向「报已占用」：号撞了只是麻烦，漏报会让 intake 发出重复单。
    """
    p_hits = [h for h in proto_hits if h["no"] == candidate]
    d_hits = [h for h in data["hits"] if h["no"] == candidate]
    out = [
        f"查重 {candidate} —— 扫描范围：原型（{len({h['no'] for h in proto_hits})} 个已占用号）"
        f" · mes-data（{len(data['files'])} 个文件 / {len({h['no'] for h in data['hits']})} 个已占用号）"
    ]
    if p_hits or d_hits:
        out.append("  判定：已占用 —— 不可用")
        keyed = [x for x in p_hits if x["hint"] != "未识别字段"]
        for h in keyed[:5]:
            out.append(f"  命中·原型：{h['where']}（字段 {h['hint']} ← 行属性）")
        if len(keyed) > 5:
            out.append(f"  命中·原型：另 {len(keyed) - 5} 处行属性引用（该号被多处引用）")
        rest = [x for x in p_hits if x["hint"] == "未识别字段"]
        if rest:
            where = ", ".join(x["where"].split(":")[1] for x in rest[:6])
            out.append(f"  命中·原型：另 {len(rest)} 处出现于非行属性上下文（行 {where}）")
        for h in d_hits:
            out.append(f"  命中·mes-data：{h['where']}（字段 {h['hint']}）")
    else:
        out.append("  判定：可用 —— 原型与 mes-data 均未占用")
    out += [f"  备注：{n}" for n in data["notes"]]
    out.append("  提示：本技能只判定、不发号；要落新单请用 mes-inspection-intake（它按契约 §C.1 从 100 起取号）")
    return out


def validate(selector: str, value: str) -> None:
    if selector == "check":
        if RE_ANY_NUM.fullmatch(value):
            return
        raise QueryError(
            f"候选号格式非法：{value} —— 本技能只认已知单号格式（异常单 QA-YYYYMMDD-NNN / 工单 MO-… / 巡检记录 XJ…）"
        )
    rx, human = SELECTORS[selector]
    if not rx.fullmatch(value):
        raise QueryError(f"号格式非法：{value} —— {human}")
