#!/usr/bin/env python
"""桥契约测试 —— 让「契约漂移」在结构上不可能悄无声息地发生。

被测对象：skills/mes-inspection-intake/scripts/commit.py（skill 侧产出）
执法依据：docs/agents/mes-bridge-contract.md（v1.1）
期望值来源：**全部从契约 / 单一措辞来源文档中现解析**，本文件不存放期望值的副本。
    ⇒ 改契约 ⇒ 本测试的期望随之移动；只改实现不改契约 ⇒ 本测试变红。

退出码：0=全部通过，1=有失败（与 skills/evals/run_e2e.py 的 `return 0 if ... else 1` 一致）。

用法：
    py -3 skills/evals/contract_bridge.py              # 一键跑
    py -3 skills/evals/contract_bridge.py --keep       # 保留产出目录，便于肉眼查看
    py -3 skills/evals/contract_bridge.py --selftest   # 变异自检：证明本测试确有抓错能力
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
DEFAULT_CONTRACT = REPO / "docs" / "agents" / "mes-bridge-contract.md"
DEFAULT_SKILL = REPO / "skills" / "mes-inspection-intake"
DISCLAIMER_DOC = REPO / "skills" / "inspection-report" / "references" / "output-schema.md"
DEFAULT_FIXTURE = DEFAULT_SKILL / "evals" / "fixtures" / "finding-demo.json"
# 原型侧落点（契约 §C 的 "交付物/mes-prototype/mes-data/"），与 invda 同级工作区


def default_proto_root():
    """定位原型宿主页。**此处不写死任何目录名**（公开仓库不得含客户名）。

    默认指向**仓库内** `docs/mes-demo`：绿灯要亮在评委能复现的产物上，
    而不是一个私有的外部原型上（自有发现：外部路径一断，T11 会静默跳过而 headline 仍全绿）。
    本地跑真原型用 `MES_PROTO` 覆盖。
    """
    env = os.environ.get("MES_PROTO")
    if env:
        return Path(env)
    return REPO / "docs" / "mes-demo"


DEFAULT_PROTO = default_proto_root()

RUNS = 3                      # T3：连跑 3 次
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
EXIT_OK, EXIT_FAIL, EXIT_INCOMPLETE = 0, 1, 2   # 2 = 无 FAIL 但有 SKIP（「绿而不完整」）

WINDOWS_DRIVE_RE = re.compile(r"(?<![\w<])[A-Za-z]:[\\/](?![/\\])")
POSIX_ABS_RE = re.compile(r"/(?:home|Users|root|tmp|opt|var)/")


class ContractError(Exception):
    """契约文档本身读不出期望值——必须显式失败，不得静默跳过。"""


class AnchorStale(Exception):
    """**测试台问题**：变异锚点在被测文件里找不到了（实现合法变更所致）。

    与「被测方违契」严格区分：这条不是产品缺陷，是测试要跟着改锚点。
    单列一个异常类型，是为了让自检能逐条降级报告，而不是整轮崩掉。
    """


# ---------------------------------------------------------------- 契约解析

def _fmt_to_re(template, subs):
    """`QA-YYYYMMDD-NNN` → `^QA-\\d{8}-\\d{3}$`（占位符按 subs 展开，其余逐字转义）。"""
    keys = sorted(subs, key=len, reverse=True)
    out, i = "^", 0
    while i < len(template):
        for key in keys:
            if template.startswith(key, i):
                out += subs[key]
                i += len(key)
                break
        else:
            out += re.escape(template[i])
            i += 1
    return out + "$"


def parse_contract(path):
    """从契约文档现解析出全部期望值。解析不到 = 契约漂移，直接失败。"""
    text = Path(path).read_text(encoding="utf-8")
    doc = {}

    head = re.search(r"^#\s*(.+)$", text, re.M)
    doc["title"] = head.group(1).strip() if head else "<无标题>"
    versions = re.findall(r"^\|\s*\*\*?(v[\d.]+)\*\*?\s*\|", text, re.M)
    doc["latest_version"] = versions[-1] if versions else "<变更表未解析>"

    # §C 的 ```json 示例 → 信封 / 记录 / provenance 字段集与 schema_version
    sec_c = re.search(r"## C[^\n]*\n(.*?)(?=\n## D)", text, re.S)
    if not sec_c:
        raise ContractError("契约 §C 段落定位失败")
    block = re.search(r"```json\s*\n(.*?)```", sec_c.group(1), re.S)
    if not block:
        raise ContractError("契约 §C 找不到 ```json 示例块")
    example = json.loads(block.group(1))
    doc["example"] = example
    doc["envelope_keys"] = list(example)
    rec = example["records"][0]
    doc["record_keys"] = list(rec)
    doc["prov_keys"] = list(rec["provenance"])
    doc["schema_version"] = example["schema_version"]
    doc["example_disclaimer"] = rec["provenance"]["disclaimer"]

    # §A.1 部门枚举
    row = re.search(r"\|\s*部门枚举[^|\n]*\|([^|\n]*)\|", text)
    if not row:
        raise ContractError("契约 §A.1 找不到「部门枚举」行")
    doc["dept_enum"] = [d.strip() for d in row.group(1).split("/") if d.strip()]

    # §C.1 序号下限
    floor = re.search(r"序号下限[^\n]*?`(\d+)`", text)
    if not floor:
        raise ContractError("契约 §C.1 找不到「序号下限」数值")
    doc["seq_floor"] = int(floor.group(1))

    # §C.1 / §C.2 单号格式样例
    no_tok = re.search(r"`(QA-[A-Z0-9-]+)`", text)
    rel_tok = re.search(r"`(XJ<YYYYMMDD><NNN>)`", text)
    if not no_tok or not rel_tok:
        raise ContractError("契约里找不到 QA/XJ 单号格式样例")
    doc["no_tok"], doc["rel_tok"] = no_tok.group(1), rel_tok.group(1)
    doc["no_re"] = _fmt_to_re(no_tok.group(1), {"YYYYMMDD": r"\d{8}", "NNN": r"\d{3}"})
    doc["rel_re"] = _fmt_to_re(rel_tok.group(1), {"<YYYYMMDD>": r"\d{8}", "<NNN>": r"\d{3}"})

    # §C.4 xj-records 记录字段
    row = re.search(r"\|\s*记录字段\s*\|([^|\n]*)\|", text)
    if not row:
        raise ContractError("契约 §C.4 找不到「记录字段」行")
    # 去重保序：字段说明里会再次提到别的字段名（如「对应异常单 `no`」），不去重会显示成重复字段
    doc["xj_record_keys"] = list(dict.fromkeys(re.findall(r"`([a-z_]+)`", row.group(1))))
    if not doc["xj_record_keys"]:
        raise ContractError("契约 §C.4 记录字段解析为空")

    # §B.2 iso 的语义层约束（v1.5 裁决：JSON 留布尔，映射责任在 loader）
    row = re.search(r"\|\s*`iso`\s*\|\s*[^|\n]*\|([^|\n]*)\|", text)
    if not row:
        raise ContractError("契约 §B.2 找不到 `iso` 行")
    if "JSON 侧为布尔" not in row.group(1):
        raise ContractError(f"契约 §B.2 `iso` 行未声明「JSON 侧为布尔」：{row.group(1).strip()[:60]}")
    doc["iso_rule"] = "JSON 侧为布尔"

    # §C.5 iso 默认值（v1.6）——必须锚在 §C.5 的**规范表格**上。
    # ⚠ 曾用全文首个「默认改 `x`」：它落在 §G 变更表(:387) 而非 §C.5(:269)。值当时碰巧相同，
    #   但那是在读变更日志而不是读条款 —— 换一版 changelog 就会误取。同类风险见 §C.6 审计。
    c5 = re.search(r"### C\.5(.*?)(?=\n#{2,3}\s)", text, re.S)
    if not c5:
        raise ContractError("契约 §C.5 段落定位失败")
    row = re.search(r"\|\s*\*\*默认值\*\*\s*\|([^|\n]*)\|", c5.group(1))
    if not row:
        raise ContractError("契约 §C.5 找不到「默认值」行")
    m = re.search(r"`(true|false)`", row.group(1))
    if not m:
        raise ContractError(f"契约 §C.5 默认值行内无布尔值：{row.group(1).strip()[:60]}")
    doc["iso_default"] = (m.group(1) == "true")

    # §C.7 kind ↔ data-view 映射（v1.10/v1.11）——两个标识差一个 qm- 前缀，混用会静默注入 0 条
    c7 = re.search(r"### C\.7(.*?)(?=\n#{2,3}\s)", text, re.S)
    if not c7:
        raise ContractError("契约 §C.7 段落定位失败")
    b7 = c7.group(1)
    for key, pat, label in (("kind_value", r"`records\[\]\.kind`", "JSON records[].kind"),
                            ("view_value", r"`section\[data-view\]`", "DOM section[data-view]")):
        row = re.search(r"\|[^|\n]*" + pat + r"[^|\n]*\|([^|\n]*)\|", b7)
        if not row:
            raise ContractError(f"契约 §C.7 找不到 {label} 行")
        m = re.search(r'"([^"]+)"', row.group(1))
        if not m:
            raise ContractError(f"契约 §C.7 {label} 行内无带引号取值：{row.group(1).strip()[:50]}")
        doc[key] = m.group(1)
    if "qm-" not in doc["view_value"] or "qm-" in doc["kind_value"]:
        raise ContractError(f"契约 §C.7 前后缀关系不成立：kind={doc['kind_value']!r} "
                            f"view={doc['view_value']!r}（本条全部意义就在这个差异上）")

    # §E.1 查询入口约定（v1.13，采纳 R5 报的缺口）——本仓库约定 [data-q]
    m = re.search(r"触发元素标记为\s*\*\*`(\[[^`]+\])`", text)
    if not m:
        raise ContractError("契约 §E.1 找不到「查询触发元素」约定")
    doc["query_attr"] = m.group(1)

    # §B.1 计数基数（v1.11）——契约明写 base 惰性初始化为 96，故期望值不必靠「注入前快照」猜
    m = re.search(r"base 惰性初始化为\s*`(\d+)`", text)
    if not m:
        raise ContractError("契约 §B.1 找不到「base 惰性初始化为 N」")
    doc["base_total"] = int(m.group(1))

    # §C.6 产物来源可验证性（**v1.10 更正**）——只在 ✅ 段取期望。
    # ⚠ v1.9 的「produced_at ↔ mtime」判别式已被 R3 证伪（任何新写文件 Δ 都≈0，查不出手写），
    #   契约把它移入 ❌ 段并保留对照。**已撤回的文字不得作期望源** —— 这里刻意只读 ✅ 段，
    #   并把判别式的**实际作用域**与**它证明不了什么**一并取出，供断言输出如实标注。
    c6 = re.search(r"### C\.6(.*?)(?=\n#{2,3}\s)", text, re.S)
    if not c6:
        raise ContractError("契约 §C.6 段落定位失败")
    body = c6.group(1)
    if "逐字节相同" not in body:
        raise ContractError("契约 §C.6 找不到「复现＝逐字节相同」这一有效来源证明")
    doc["provenance_proof"] = "复现＝逐字节相同"
    doc["mtime_retracted"] = "❌" in body or "已更正" in body
    row = re.search(r"\|\s*`produced_at ↔ mtime`[^|]*\|([^|]*)\|([^|]*)\|", body)
    if not row:
        raise ContractError("契约 §C.6 找不到 produced_at↔mtime 的「能/不能证明」行")
    doc["mtime_proves"] = re.sub(r"[*`]", "", row.group(1)).strip()
    doc["mtime_not_proves"] = re.sub(r"[*`]", "", row.group(2)).strip()

    # §C.1 日期回落链（v1.4）——顺序也由契约决定
    row = re.search(r"\|\s*日期来源\s*\|([^|\n]*)\|", text)
    if not row:
        raise ContractError("契约 §C.1 找不到「日期来源」行")
    chain = row.group(1)
    pos = {tok: chain.find(tok) for tok in ("--date", "captured_at", "系统当天")}
    if any(p < 0 for p in pos.values()):
        raise ContractError(f"契约 §C.1 日期回落链三要素不全：{chain.strip()}")
    doc["date_chain"] = [t for t, _ in sorted(pos.items(), key=lambda kv: kv[1])]

    # §C.3 映射表本体（**这张表就是本 skill 的业务规则**）——正向四行
    sec = re.search(r"### C\.3(.*?)(?=\n#{2,3}\s)", text, re.S)
    if not sec:
        raise ContractError("契约 §C.3 段落定位失败")
    if "本表是团队自定" not in sec.group(1):
        raise ContractError("契约 §C.3 未声明「本表是团队自定」——该标注是引用方的硬要求")
    doc["dept_table_team_defined"] = "[团队自定]"
    rows = []
    for line in sec.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        dept = next((m.group(1) for cell in cells[1:]
                     for m in [re.search(r"`([^`]+)`", cell)]
                     if m and m.group(1) in doc["dept_enum"]), None)
        if not dept:
            continue                       # 表头「落 `dept`」与分隔行在此被滤掉
        cat = re.sub(r"[`*]", "", cells[0]).strip()
        # v1.7 第三列「当前可触发？」——它决定夹具能不能用这一类（见 T5b/T5c）
        producible = "✅" in (cells[2] if len(cells) > 2 else "")
        if cat:
            rows.append((cat, dept, producible))
    if len(rows) < 4:
        raise ContractError(f"契约 §C.3 映射表只解析出 {len(rows)} 行，至少应有 4 行")
    if not any(r[2] for r in rows):
        raise ContractError("契约 §C.3 表未标出任何「当前可触发」行——"
                            "v1.7 的可触发列是夹具准入的判据，不能缺失")
    doc["dept_table"] = rows

    # §C.3 映射不中：拒绝猜测 + --dept 出口（v1.4）
    hint = re.search(r"提示用\s*`(--dept)`", text)
    if not hint:
        raise ContractError("契约 §C.3 找不到「--dept」出口提示")
    doc["dept_hint"] = hint.group(1)
    if "不得默认归入某部门" not in text:
        raise ContractError("契约 §C.3 找不到「不得默认归入某部门」硬约束")

    # §B.4 幂等验收数字（v1.4）——T11-loader 启用后直接用
    b4 = re.search(r"### B\.4(.*?)(?=\n#{2,3}\s)", text, re.S)
    if not b4:
        raise ContractError("契约 §B.4 幂等段定位失败")
    keep = re.search(r"data-total[^\n]*?保持\s*`?(\d+)`?", b4.group(1))
    switch = re.search(r"切回\s*\*\*≥\s*(\d+)\s*次", b4.group(1))
    if not keep or not switch:
        raise ContractError("契约 §B.4 验收数字（data-total / 切回次数）无法解析")
    doc["idem_total"] = int(keep.group(1))
    doc["idem_switches"] = int(switch.group(1))

    return doc


def parse_disclaimer_source(path):
    """§4 的 ```text 代码块 —— 契约 §C 指定的 disclaimer 单一措辞来源。"""
    text = Path(path).read_text(encoding="utf-8")
    sec = re.search(r"## 4\.[^\n]*免责声明[^\n]*\n(.*)", text, re.S)
    if not sec:
        raise ContractError(f"{path} 找不到 §4 免责声明段")
    block = re.search(r"```text\s*\n(.*?)\n```", sec.group(1), re.S)
    if not block:
        raise ContractError(f"{path} §4 找不到 ```text 措辞块")
    return block.group(1).strip()


# ---------------------------------------------------------------- 工具

def walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, val in node.items():
            yield key
            yield from walk_strings(val)
    elif isinstance(node, list):
        for item in node:
            yield from walk_strings(item)


def run_producer(skill_root, finding, out_path, extra=()):
    cmd = [
        sys.executable, str(Path(skill_root) / "scripts" / "commit.py"),
        "--finding", str(finding), "--out", str(out_path), *extra,
    ]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def path_leaks(text, *roots):
    """§D 只要求抹掉**本机绝对路径**；相对路径不是泄露，不参与判定。"""
    leaks = []
    for root in roots:
        root = Path(root)
        if not root.is_absolute():
            continue
        for form in (str(root), root.as_posix()):
            if form and form in text:
                leaks.append(f"原文含绝对路径 {form}")
    if WINDOWS_DRIVE_RE.search(text):
        leaks.append("含 Windows 盘符绝对路径")
    if POSIX_ABS_RE.search(text):
        leaks.append("含 POSIX 绝对路径")
    return leaks


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 主测试

def run_suite(skill_root, contract_path, disclaimer_doc, fixture, workdir, keep=False,
              loader="auto", proto_root=None):
    """跑一轮完整契约测试。返回 (results, meta)。不抛异常、不退出。"""
    results = []
    meta = {}

    def add(cid, title, status, detail=""):
        results.append({"id": cid, "title": title, "status": status, "detail": detail})

    def check(cid, title, ok, detail=""):
        add(cid, title, PASS if ok else FAIL, detail)
        return ok

    try:
        c = parse_contract(contract_path)
        src_wording = parse_disclaimer_source(disclaimer_doc)
    except (ContractError, OSError, ValueError) as exc:
        add("T0", "契约/措辞来源可解析", FAIL, f"{type(exc).__name__}: {exc}")
        return results, meta
    add("T0", "契约/措辞来源可解析", PASS, f"契约自述 {c['title']}｜变更表最新 {c['latest_version']}")
    meta["contract"] = c
    src = Path(skill_root)
    meta["skill_root"] = src
    meta["xj_record_keys"] = c["xj_record_keys"]

    # ---- 产出：连跑 RUNS 次，同一个产出目录（T3 需要）
    fx = read_json(fixture)
    world_date = str(fx.get("captured_at") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    date8 = world_date.replace("-", "")
    workdir = Path(workdir).resolve()   # T8 需要绝对路径才验得到 §D 的抹路径要求
    workdir.mkdir(parents=True, exist_ok=True)

    runs = [run_producer(src, fixture, workdir / "inbox.json", ["--date", world_date])
            for _ in range(RUNS)]
    bad = [i + 1 for i, p in enumerate(runs) if p.returncode != 0]
    if bad:
        add("T-run", f"连跑 {RUNS} 次均成功", FAIL,
            f"第 {bad} 次退出码非 0；stderr={runs[bad[0] - 1].stderr.strip()[:200]}")
        return results, meta
    add("T-run", f"连跑 {RUNS} 次均成功", PASS, f"产出目录 {workdir}")
    meta["workdir"] = workdir

    inbox = read_json(workdir / "inbox.json")
    xj_path = workdir / "xj-records.json"
    xj = read_json(xj_path) if xj_path.exists() else None
    records = inbox.get("records") or []
    meta["nos"] = [r.get("no") for r in records]

    # ---- T1 schema_version
    check("T1", "schema_version 与契约 §C 示例一致",
          inbox.get("schema_version") == c["schema_version"],
          f"期望 {c['schema_version']!r}，实得 {inbox.get('schema_version')!r}")

    # ---- T2 records[] 逐字段对齐（信封 + 记录 + provenance，不多不少）
    problems = []
    if set(inbox) != set(c["envelope_keys"]):
        problems.append(f"信封多={sorted(set(inbox) - set(c['envelope_keys']))} "
                        f"缺={sorted(set(c['envelope_keys']) - set(inbox))}")
    if not records:
        problems.append("records 为空，无法校验")
    for rec in records:
        if set(rec) != set(c["record_keys"]):
            problems.append(f"记录{rec.get('no')} 多={sorted(set(rec) - set(c['record_keys']))} "
                            f"缺={sorted(set(c['record_keys']) - set(rec))}")
        prov = rec.get("provenance")
        if not isinstance(prov, dict) or set(prov) != set(c["prov_keys"]):
            problems.append(f"记录{rec.get('no')} provenance 字段不符："
                            f"{sorted(prov) if isinstance(prov, dict) else type(prov).__name__}")
    check("T2", "records[] 与 §C 示例逐字段对齐（不多不少）", not problems,
          "；".join(problems) if problems
          else f"信封 {len(c['envelope_keys'])} + 记录 {len(c['record_keys'])} "
               f"+ provenance {len(c['prov_keys'])} 字段全对齐，共 {len(records)} 条")

    # ---- T1b 产物可复现性（§C.6 v1.10：**本轮唯一有效的来源证明**）
    # 同一 fixture、同一 --date，写进两个各自空白的目录 ⇒ 除 produced_at 外应**逐字节相同**。
    # ⚠ 不要退回 v1.9 的「produced_at ↔ mtime Δ≤1s」当来源证明：R3 已证伪——任何新写文件 Δ 都≈0，
    #   手写者当场写文件同样 Δ≈0。该判别式**只能查倒填时间的老件**，证明不了「非手写」。
    repro = workdir / "repro"
    repro_a, repro_b = repro / "a", repro / "b"
    run_producer(src, fixture, repro_a / "inbox.json", ["--date", world_date])
    run_producer(src, fixture, repro_b / "inbox.json", ["--date", world_date])
    problems, seen = [], []

    def _normalize(text):
        return re.sub(r'"produced_at":\s*"[^"]*"', '"produced_at": "<归一>"', text)

    for name in ("inbox.json", "xj-records.json"):
        pa, pb = repro_a / name, repro_b / name
        if not (pa.is_file() and pb.is_file()):
            problems.append(f"{name} 两次产出不齐（{pa.is_file()}/{pb.is_file()}）")
            continue
        ra, rb = _normalize(pa.read_text(encoding="utf-8")), _normalize(pb.read_text(encoding="utf-8"))
        seen.append(f"{name} {len(pa.read_bytes())}B/CRLF={pa.read_bytes().count(b'\\r\\n')}")
        if ra != rb:
            first = next((i for i, (x, y) in enumerate(zip(ra, rb)) if x != y), min(len(ra), len(rb)))
            problems.append(f"{name} 两次产出**不可逐字节复现**（首个差异在第 {first} 字符处）："
                            f"{ra[max(0, first - 30):first + 30]!r} ≠ {rb[max(0, first - 30):first + 30]!r}")
    check("T1b", f"产物可复现（{c['provenance_proof']}；§C.6 判别式「{c['mtime_proves']}」"
                 f"证明不了「{c['mtime_not_proves']}」）", not problems,
          "；".join(problems) if problems else "；".join(seen))

    # ---- T2b iso：JSON 布尔 + 取 §C.5 默认值（§B.2 v1.5 / §C.5 v1.6）
    bad_iso = [f"{r.get('no')}={r.get('iso')!r}" for r in records
               if not isinstance(r.get("iso"), bool)]
    off_default = [f"{r.get('no')}={r.get('iso')!r}" for r in records
                   if r.get("iso") is not c["iso_default"]]
    problems = []
    if bad_iso:
        problems.append(f"非布尔值：{bad_iso}（呈现映射归 loader，skill 不得越界）")
    if off_default:
        problems.append(f"非 §C.5 默认值 {c['iso_default']}：{off_default}（契约要求不做类型分流）")
    check("T2b", f"iso 为 JSON 布尔且取 §C.5 默认值 {c['iso_default']}", not problems,
          "；".join(problems) if problems
          else f"{len(records)} 条均为布尔 {c['iso_default']}")

    # ---- T3 序号下限 + 连跑递增且互不相同
    seqs, shape_bad = [], []
    for rec in records:
        no = str(rec.get("no") or "")
        if not re.match(c["no_re"], no):
            shape_bad.append(f"{no!r} 不符 {c['no_re']}")
            continue
        if not no.startswith(f"QA-{date8}-"):
            shape_bad.append(f"{no!r} 日期段非 {date8}（--date 已显式传入）")
        seqs.append(int(no.rsplit("-", 1)[1]))
    floor_bad = [s for s in seqs if s < c["seq_floor"]]
    rising = all(b > a for a, b in zip(seqs, seqs[1:]))
    uniq = len(set(seqs)) == len(seqs)
    check("T3", f"序号下限 {c['seq_floor']}，连跑 {RUNS} 次递增且互不相同",
          not shape_bad and not floor_bad and rising and uniq and len(seqs) == RUNS,
          "；".join(shape_bad + ([f"低于下限：{floor_bad}"] if floor_bad else [])
                    + ([] if rising else [f"非递增：{seqs}"])
                    + ([] if uniq else [f"有重复：{seqs}"]))
          if (shape_bad or floor_bad or not rising or not uniq or len(seqs) != RUNS)
          else f"{records[0]['no']} … {records[-1]['no']}（{seqs}）")

    # ---- T3b 日期回落链（§C.1 v1.4：--date > captured_at > 系统当天）
    # 主流程恒传 --date ⇒ 该链测不到（R2-S 指出的盲区）。此处在**三个独立产出目录**各跑一次。
    fb = workdir / "fallback"
    fb.mkdir(parents=True, exist_ok=True)
    no_cap = fb / "no_captured_at.json"
    no_cap.write_text(json.dumps({k: v for k, v in fx.items() if k != "captured_at"},
                                 ensure_ascii=False), encoding="utf-8")
    cap_date = str(fx.get("captured_at") or "")[:10]
    other_date = "2026-07-01"      # 故意与 captured_at 不同，否则验不出「谁压过谁」
    tz8_today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    local_today = datetime.now().strftime("%Y-%m-%d")
    fb_cases = [
        ("a", "--date 压过 captured_at",
         run_producer(src, fixture, fb / "a" / "inbox.json", ["--date", other_date]),
         {other_date}, f"--date={other_date} vs captured_at={cap_date}"),
        ("b", "captured_at 回落",
         run_producer(src, fixture, fb / "b" / "inbox.json", []),
         {cap_date}, f"不传 --date，期望取 captured_at={cap_date}"),
        ("c", "系统当天兜底",
         run_producer(src, no_cap, fb / "c" / "inbox.json", []),
         {local_today, tz8_today},
         f"无 --date 无 captured_at，期望当天（本地 {local_today} / +08:00 {tz8_today}）"),
    ]
    problems, seen = [], []
    for sub, label, proc, want, why in fb_cases:
        if proc.returncode != 0:
            problems.append(f"{label}：rc={proc.returncode} {proc.stderr.strip()[:120]}")
            continue
        try:
            last = read_json(fb / sub / "inbox.json")["records"][-1]
        except (OSError, ValueError, IndexError, KeyError) as exc:
            problems.append(f"{label}：产出不可读（{type(exc).__name__}）")
            continue
        got, no = str(last.get("date")), str(last.get("no"))
        seg = no[3:11] if no.startswith("QA-") and len(no) >= 15 else "<单号格式异常>"
        seen.append(f"{label}={got}")
        if got not in want or seg != got.replace("-", ""):
            problems.append(f"{label}：日期得 {got!r}／单号段 {seg!r}，期望 {sorted(want)}（{why}）")
    check("T3b", "日期回落链 " + " > ".join(c["date_chain"]), not problems,
          "；".join(problems) if problems else "；".join(seen))

    # ---- T4 rel 形如 XJ<YYYYMMDD><NNN>，无连字符
    bad_rel = [r.get("rel") for r in records
               if not re.match(c["rel_re"], str(r.get("rel") or ""))]
    hyphen = [r.get("rel") for r in records if "-" in str(r.get("rel") or "")]
    check("T4", f"rel 形如 {c['rel_tok']} 且无连字符", not bad_rel and not hyphen,
          f"不符格式={bad_rel} 含连字符={hyphen}" if (bad_rel or hyphen)
          else f"共 {len(records)} 条，样例 {records[0].get('rel')}")

    # ---- T5 dept 属枚举
    bad_dept = sorted({str(r.get("dept")) for r in records if r.get("dept") not in c["dept_enum"]})
    check("T5", "dept ∈ §A.1 枚举", not bad_dept,
          f"越界值 {bad_dept}（枚举 {c['dept_enum']}）" if bad_dept
          else f"取值 {sorted({r['dept'] for r in records})}")

    # ---- T5b/T5b2/T5c §C.3 映射表 [团队自定]
    # 🔴 [团队自定]：本表**不出自 MES / SRS 任何材料**（decision-log D-030；CONTEXT.md 规则）。
    #    输出必须带此标注，防止后来读测试的人误当成 MES 原生规则。
    # 为什么值得测：这张表就是本 skill 的业务规则本体。它漂了，单据会**静默进错部门**，
    #    而单据进了错部门，界面上完全看不出来。
    # ⚠ v1.7 追加约束（与本单原计划冲突，已按契约收窄）：「当前可触发」列标 ❌ 的行
    #    **不得进测试夹具**——上游当前对这三类产不出结论，拿它们做夹具＝描述不存在的输入
    #    （与 D-018「从未为真」同形）。故拆成：可触发行走端到端夹具，其余行只核**规则**。
    rows = c["dept_table"]
    tag = c["dept_table_team_defined"]
    live = [(cat, dept) for cat, dept, ok in rows if ok]
    dm_dir = workdir / "deptmap"
    dm_dir.mkdir(parents=True, exist_ok=True)

    # T5b：只用「当前可触发」的行做夹具，走完整 commit.py
    dm_fixture = dm_dir / "live-rows.json"
    dm_fixture.write_text(json.dumps({
        "captured_at": f"{world_date}T14:32:00+08:00", "site": "洁净间 3 号工位",
        "findings": [{"kind": "hazard", "code": "SAFE", "label": cat, "confidence": 0.8,
                      "evidence_ref": f"mes-data/evidence/dept-{i:02d}.jpg"}
                     for i, (cat, _) in enumerate(live)],
    }, ensure_ascii=False), encoding="utf-8")
    proc = run_producer(src, dm_fixture, dm_dir / "inbox.json", ["--date", world_date])
    problems, echo = [], []
    if proc.returncode != 0:
        problems.append(f"{tag} 产出失败 rc={proc.returncode}：{proc.stderr.strip()[:140]}")
    else:
        got = read_json(dm_dir / "inbox.json")["records"]
        if len(got) != len(live):
            problems.append(f"{tag} 落单 {len(got)} 条，期望 {len(live)}")
        for (cat, want), rec in zip(live, got):
            echo.append(f"{cat}→{rec.get('dept')}")
            if rec.get("dept") != want:
                problems.append(f"{tag} {cat} 落 {rec.get('dept')!r}，§C.3 要求 {want!r}"
                                f" —— 单据已静默进错部门，界面看不出来")
    check("T5b", f"§C.3 映射 {tag}（端到端，仅用可触发行 {[c0 for c0, _ in live]}）",
          not problems, "；".join(problems) if problems else f"{tag} " + "；".join(echo))

    # T5b2/T5c：整表逐行核对 + 夹具准入 —— 走**子进程**，避免模块缓存把变异副本串味
    fix_labels = []
    for fx in sorted((src / "evals" / "fixtures").glob("*.json")):
        try:
            doc = read_json(fx)
        except (OSError, ValueError):
            continue
        for f in (doc.get("findings") or []):
            if isinstance(f, dict) and f.get("label"):
                fix_labels.append((fx.name, str(f["label"]), str(f.get("code") or "")))
    probe_script = (
        "import json,sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import intake_core\n"
        "out=[]\n"
        "for code,lab in json.loads(sys.argv[2]):\n"
        "    try:\n"
        "        d,r=intake_core.map_dept({'label':lab,'code':code})\n"
        "        out.append([d,r])\n"
        "    except Exception as e:\n"
        "        out.append([None,type(e).__name__+': '+str(e)])\n"
        "print(json.dumps(out,ensure_ascii=False))\n")
    probe_args = ([[ "SAFE", cat] for cat, _, _ in rows]
                  + [[c or "SAFE", lab] for _, lab, c in fix_labels])
    probe = subprocess.run(
        [sys.executable, "-c", probe_script, str(src / "scripts"),
         json.dumps(probe_args, ensure_ascii=False)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    probed = None
    if probe.returncode == 0:
        try:
            probed = json.loads(probe.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            probed = None

    if probed is None:
        check("T5b2", f"§C.3 映射表逐行核对 {tag}", False,
              f"规则探针失败 rc={probe.returncode}：{(probe.stderr or probe.stdout).strip()[:140]}")
        check("T5c", f"§C.3 夹具准入（{tag}：❌ 行不得进夹具）", False, "规则探针失败")
    else:
        rule_out = probed[:len(rows)]
        problems, echo = [], []
        for (cat, want, ok), (got_dept, reason) in zip(rows, rule_out):
            if got_dept is None:
                problems.append(f"{tag} {cat} 映射抛错：{reason[:80]}")
                continue
            echo.append(f"{cat}→{got_dept}{'' if ok else '(前瞻)'}")
            if got_dept != want:
                problems.append(f"{tag} {cat} 规则落 {got_dept!r}，§C.3 要求 {want!r}")
            if tag not in str(reason):
                problems.append(f"{tag} {cat} 的映射理由未带 {tag} 标注：{reason!r}")
        check("T5b2", f"§C.3 映射表逐行核对 {tag}（{len(rows)} 行，后 "
                      f"{sum(1 for _, _, ok in rows if not ok)} 行为前瞻性规则）",
              not problems, "；".join(problems) if problems else f"{tag} " + "；".join(echo))

        # T5c：契约 v1.7 —— 夹具只能用「当前可触发」那一类发现
        allowed = [cat for cat, _, ok in rows if ok]
        problems, seen = [], []
        for (name, lab, _), (got_dept, reason) in zip(fix_labels, probed[len(rows):]):
            fired = next((cat for cat, _, ok in rows if not ok and cat in str(reason)), None)
            if fired:
                problems.append(f"{name} 的夹具用了**当前不可触发**的类别 {fired!r}"
                                f"（标签 {lab[:40]!r}）—— v1.7：夹具只可用 {allowed}")
            elif got_dept is None:
                problems.append(f"{name} 的夹具映射失败：{str(reason)[:70]}")
            else:
                seen.append(f"{name}:{lab[:18]}→{got_dept}")
        check("T5c", f"§C.3 夹具准入 {tag}（❌ 行不得进夹具；仅可用 {allowed}）",
              not problems, "；".join(problems) if problems
              else (f"{len(fix_labels)} 条夹具发现全部落在可触发类别｜" + "；".join(seen)))

    # ---- T6 指涉完整性：每条 rel 都能在 xj-records.json 里找到对应记录
    if xj is None:
        check("T6a", "rel 指涉完整性（xj-records.json 存在且逐条命中）", False,
              f"{xj_path.name} 不存在——rel 指向了凭空的号")
    else:
        xj_nos = {str(r.get("no")) for r in (xj.get("records") or [])}
        missing = [r.get("rel") for r in records if str(r.get("rel")) not in xj_nos]
        check("T6a", "rel 指涉完整性（xj-records.json 存在且逐条命中）", not missing,
              f"rel 在 xj-records.json 中无对应记录：{missing}" if missing
              else f"{len(records)} 条 rel 全部命中（xj 记录 {xj_nos}）")

    # ---- T6b（扩展项）xj-records 记录字段是否符合 §C.4
    if xj is None:
        check("T6b", "xj-records 记录字段符合 §C.4", False, "文件不存在")
    else:
        want = set(c["xj_record_keys"])
        problems = []
        for r in xj.get("records") or []:
            if set(r) != want:
                problems.append(f"多={sorted(set(r) - want)} 缺={sorted(want - set(r))}")
        check("T6b", "xj-records 记录字段符合 §C.4", not problems and bool(xj.get("records")),
              f"§C.4 要求 {sorted(want)}；实际 {problems[0]}" if problems
              else f"{len(xj.get('records') or [])} 条字段全对齐")

    # ---- T7 字符串值不含 ASCII 引号（§D）
    quoted = []
    for name, doc in (("inbox.json", inbox), ("xj-records.json", xj)):
        if doc is None:
            continue
        for text in walk_strings(doc):
            if '"' in text or "'" in text:
                quoted.append(f"{name}:{text!r}")
    check("T7", "所有字符串值不含 ASCII 引号 \" 或 '", not quoted,
          f"命中 {quoted[:3]}" if quoted else "两文件全部字符串值命中 0")

    # ---- T8 失败路径：退出码 1 且不泄露本机绝对路径
    fail_dir = workdir / "fail"
    fail_dir.mkdir(parents=True, exist_ok=True)
    bad_finding = fail_dir / "unmappable.json"
    bad_finding.write_text(json.dumps({
        "captured_at": f"{world_date}T14:32:00+08:00",
        "findings": [{"code": "ZZZ-XYZ", "label": "量子隧穿异常", "confidence": 0.5,
                      "evidence_ref": "mes-data/evidence/x.jpg"}],
    }, ensure_ascii=False), encoding="utf-8")
    missing = fail_dir / "nope" / "missing.json"
    unmapped_out = fail_dir / "a" / "inbox.json"
    cases = {
        "映射不到部门": run_producer(src, bad_finding, unmapped_out),
        "发现文件不存在": run_producer(src, missing, fail_dir / "b" / "inbox.json"),
    }
    problems, unmapped_blob = [], ""
    for label, proc in cases.items():
        blob = (proc.stdout or "") + (proc.stderr or "")
        if label == "映射不到部门":
            unmapped_blob = blob
        if proc.returncode != 1:
            problems.append(f"{label}：退出码 {proc.returncode}（期望 1）")
        if not blob.strip():
            problems.append(f"{label}：失败但无任何输出（静默失败）")
        leaks = path_leaks(blob, REPO, src, Path.home(), fail_dir)
        if leaks:
            problems.append(f"{label}：泄露路径 {leaks}")
    check("T8", "失败路径退出码=1 且不泄露本机绝对路径", not problems,
          "；".join(problems) if problems
          else "；".join(f"{k}→rc={p.returncode}" for k, p in cases.items()))

    # ---- T8b 映射不中：拒绝猜测 + --dept 出口可用（§C.3 v1.4）
    problems = []
    if unmapped_out.exists():
        problems.append("映射不中仍产出了单据（默认兜底）")
    if c["dept_hint"] not in unmapped_blob:
        problems.append(f"失败信息未提示出口 {c['dept_hint']}")
    exit_dept = c["dept_enum"][-1]          # 出口要真能用，否则「拒绝猜测」等于死路
    hatch = run_producer(src, bad_finding, fail_dir / "d" / "inbox.json", ["--dept", exit_dept])
    if hatch.returncode != 0:
        problems.append(f"出口不可用：--dept {exit_dept} → rc={hatch.returncode} "
                        f"{(hatch.stderr or '').strip()[:120]}")
    else:
        try:
            got_dept = read_json(fail_dir / "d" / "inbox.json")["records"][-1].get("dept")
        except (OSError, ValueError, IndexError, KeyError):
            got_dept = "<产出不可读>"
        if got_dept != exit_dept:
            problems.append(f"--dept 未被采纳：得 {got_dept!r}，期望 {exit_dept!r}")
    check("T8b", "映射不中拒绝猜测（不落单 + 提示 --dept + 出口可用）", not problems,
          "；".join(problems) if problems
          else f"无产出文件、提示含 {c['dept_hint']}、--dept {exit_dept} 可用")

    # ---- T9 provenance.disclaimer 与单一措辞来源逐字一致
    actual = [r.get("provenance", {}).get("disclaimer") for r in records]
    check("T9a", "disclaimer == 契约 §C 示例（实现↔契约）",
          all(a == c["example_disclaimer"] for a in actual),
          f"实得 {actual[0]!r}" if actual else "无记录")
    check("T9b", "契约 §C 示例 == §4 单一措辞来源（契约↔来源）",
          c["example_disclaimer"] == src_wording,
          f"契约示例 {c['example_disclaimer']!r} ≠ {disclaimer_doc.name} §4 {src_wording!r}"
          if c["example_disclaimer"] != src_wording
          else "两处逐字一致")

    # ---- E1 评测用例门（**非桥契约**，属 MES 线交付前门）：`expect_route` 分级
    # 裁决：MES 组（`skills/mes-*`）**强制**；legacy 四个技能只做信息性报告、不计入 PASS/FAIL。
    # 理由（决定性的是第二条）：① 它们不在本轮范围 ② 改输入会让 `skills/evals/results/`
    # 已落盘的结果与输入对不上 ⇒ 须重跑 ⇒ 须模型与 GPU ⇒ 提交前来不及。
    # **造一组对不上的输入与输出，比留一组区分度为 0 的负例更糟。**（依据 `cases-decoy-README.md` §1）
    mes_problems, legacy_info, n_mes = [], [], 0
    for cases in sorted(REPO.glob("skills/*/evals/cases.jsonl")):
        skill = cases.parent.parent.name
        is_mes = skill.startswith("mes-")
        try:
            rows = [json.loads(ln) for ln in cases.read_text(encoding="utf-8").splitlines()
                    if ln.strip()]
        except (OSError, ValueError) as exc:
            (mes_problems if is_mes else legacy_info).append(
                f"{skill}: cases.jsonl 不可解析（{type(exc).__name__}）")
            continue
        missing = sum(1 for r in rows if "expect_route" not in r)
        negs = [r for r in rows if r.get("expect_trigger") is False]
        neg_blank = sum(1 for r in negs if not r.get("expect_route"))
        if is_mes:
            n_mes += 1
            if missing:
                mes_problems.append(f"{skill}: {missing}/{len(rows)} 条**缺 expect_route 字段**")
            if neg_blank:
                mes_problems.append(
                    f"{skill}: {neg_blank}/{len(negs)} 条负例 `expect_route` 为空 ⇒ "
                    f"诱饵/选择压力维度无法机器判定（`cases-decoy-README.md` §1 同形）")
        else:
            legacy_info.append(f"{skill}: 负例 {len(negs)} 条，其中 {neg_blank} 条缺/空 expect_route")
    check("E1", f"MES 组评测用例强制 expect_route（{n_mes} 个技能）", not mes_problems,
          "；".join(mes_problems) if mes_problems
          else f"{n_mes} 个 MES 用例集：负例 expect_route 全部有值，无缺字段")
    meta["legacy_route_info"] = legacy_info

    # ---- T11-loader 集成半场：产出 → 原型 DOM 真渲染（§B.1/§B.2/§B.4/§E.1/§F）
    # 数字（§B.4 的 97 / 切回次数）来自上面的契约解析，不在此硬编码。
    if loader == "off":
        add("T11-loader", "产出 → 原型 DOM 真渲染（集成半场）", SKIP,
            "本次以 --no-loader 显式跳过（集成半场需起浏览器，约 10s）")
    else:
        try:
            import contract_bridge_loader as loader_mod
            sub = loader_mod.run_loader_checks(
                proto_root, src, fixture, workdir, c["idem_total"], c["idem_switches"],
                base_total=c["base_total"], kind_value=c["kind_value"],
                view_value=c["view_value"], query_attr=c["query_attr"])
            if loader == "on":      # 显式要求跑却缺前置 ≠ 可以跳过，必须红
                sub = [dict(r, status=FAIL, detail="--loader 要求跑集成半场，但前置缺失：" + r["detail"])
                       if r["status"] == SKIP else r for r in sub]
            results.extend(sub)
        except ImportError as exc:
            add("T11-loader", "产出 → 原型 DOM 真渲染（集成半场）", SKIP,
                f"未找到 contract_bridge_loader.py：{exc}")

    if not keep:
        pass  # workdir 由调用方清理
    return results, meta


# ---------------------------------------------------------------- 输出

def report(results, meta):
    c = meta.get("contract")
    print("=== MES 桥契约测试 ===")
    if c:
        print(f"契约   {c['title']}｜变更表最新 {c['latest_version']}")
        print(f"解析   信封{len(c['envelope_keys'])} 记录{len(c['record_keys'])} "
              f"provenance{len(c['prov_keys'])} 字段｜部门{c['dept_enum']}｜"
              f"序号下限{c['seq_floor']}｜no={c['no_re']}｜rel={c['rel_re']}")
        print(f"§C.4  xj 记录字段要求 {c['xj_record_keys']}")
    if meta.get("skill_root"):
        print(f"被测   {Path(meta['skill_root']) / 'scripts' / 'commit.py'}")
    if meta.get("workdir"):
        print(f"产出   {meta['workdir']}")
    if meta.get("nos"):
        print(f"单号   {', '.join(str(n) for n in meta['nos'])}")
    print()
    for r in results:
        print(f"{r['status']:<4}  {r['id']:<11} {r['title']}")
        if r["detail"]:
            print(f"      └─ {r['detail']}")
    n_pass = sum(r["status"] == PASS for r in results)
    n_fail = sum(r["status"] == FAIL for r in results)
    n_skip = sum(r["status"] == SKIP for r in results)
    print(f"\n--- 结果：{n_pass} PASS / {n_fail} FAIL / {n_skip} SKIP ---")
    if n_skip:
        # 未执行项**写在 headline 正下方**：只看数字的人也必须看到「有东西没跑」。
        # （只印计数、把原因埋在下文，正是「绿而不完整」被读成「全绿」的那条路。）
        names = "、".join(f"{r['id']}（{r['detail'].splitlines()[0][:60]}）"
                          for r in results if r["status"] == SKIP)
        print(f"⚠️  {n_skip} 项**未执行**（不计入通过）——非全绿：{names}")
    if n_fail:
        print("失败明细：")
        for r in results:
            if r["status"] == FAIL:
                print(f"  [{r['id']}] {r['title']} —— {r['detail']}")
    if n_skip:
        print("跳过明细：")
        for r in results:
            if r["status"] == SKIP:
                print(f"  [{r['id']}] {r['title']} —— {r['detail']}")
    legacy = meta.get("legacy_route_info") or []
    if legacy:
        print("\nℹ️  legacy 用例集**信息性报告**（按裁决**不计入 PASS/FAIL**；"
              "属已知在档缺口 `cases-decoy-README.md` §1）：")
        for line in legacy:
            print(f"     · {line}")
    return n_fail == 0


# ---------------------------------------------------------------- 变异自检

# 锚点里这些词没有辨识度：拿它们找候选只会给出噪音行
_ANCHOR_STOPWORDS = {
    "True", "False", "None", "and", "or", "not", "if", "else", "elif", "for", "while",
    "in", "is", "try", "except", "raise", "return", "def", "class", "import", "from",
    "with", "as", "pass", "lambda", "yield", "global", "assert", "del", "break",
    "continue", "self", "cls", "str", "int", "len", "print",
}


def _near_misses(text, anchor, limit=3):
    """给一个过期锚点找现存的最像的行，让人一眼看出实现改成了什么。

    取 token 的判据是**罕见度优先**（文件里出现行数最少的那个），长度只做次要排序：
    否则 `True`/`None` 这类高频词会赢过 `iso` 这种真正有辨识度的名字，给出噪音候选。
    """
    lines = text.splitlines()
    best = None                                   # (排序键, token, 截断后的候选行)
    for tok in set(re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,}", anchor)) - _ANCHOR_STOPWORDS:
        hits = [(i + 1, ln.strip()) for i, ln in enumerate(lines) if tok in ln]
        if not hits:
            continue
        key = (len(hits), -len(tok))              # 罕见度优先，长度只作次要排序
        if best is None or key < best[0]:
            best = (key, tok, hits[:limit])
    return (best[1], best[2]) if best else (None, [])


def _anchor_stale(cid, anchor, where, text, why):
    """构造一条**读得懂**的过期锚点报告：指明这是测试台问题，不是被测方问题。"""
    tok, near = _near_misses(text, anchor)
    body = "\n".join(f"           :{ln:<5} {txt[:110]}" for ln, txt in near)
    tail = (f"  → 近似候选（含 {tok!r}，取其前 {len(near)} 行）：\n{body}" if near
            else "  → 文件里找不到近似候选：这段代码可能已被整体移除或重命名。")
    return AnchorStale(
        f"[变异 {cid}] 锚点{why}：{anchor!r}\n"
        f"  → 定位：{where}\n"
        f"  → 这是**测试台问题**（锚点过期），不是被测方违契 —— 请更新锚点，不要改期望值。\n"
        f"{tail}")


def _mutate_line(text, anchor, new_line, index=None, span=1, before=0, where="", cid=""):
    """把命中锚点的行（向前 before 行起、共 span 行）换成 new_line。锚点不唯一即响亮报错。

    before 用于锚点落在多行调用**内部**时（如 raise IntakeError( 的参数字符串），
    必须连调用行一起替换，否则会留下悬空的开括号 ⇒ 变异体语法错误、测不到行为。
    """
    lines = text.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if anchor in ln]
    if index is None and len(hits) != 1:
        raise _anchor_stale(cid, anchor, where, text, f"命中 {len(hits)} 行，无法唯一定位")
    if index is not None and len(hits) <= index:
        raise _anchor_stale(cid, anchor, where, text, f"只命中 {len(hits)} 行，取不到第 {index} 个")
    at = hits[0] if index is None else hits[index]
    start = at - before
    if start < 0:
        raise _anchor_stale(cid, anchor, where, text, f"在第 {at + 1} 行，向前取不到 {before} 行")
    eol = "\n" if lines[at + span - 1].endswith("\n") else ""
    lines[start:at + span] = [new_line + eol]
    return "".join(lines)


QUOTED_FIXTURE = {
    "site": "洁净间 3 号工位",
    "captured_at": "2026-08-13T14:32:00+08:00",
    "findings": [{
        "code": "PPE-NO-SUIT",
        "label": '洁净间 "3 号" 工位 1 名人员未穿防静电服',
        "confidence": 0.86,
        "evidence_ref": "mes-data/evidence/x.jpg",
    }],
}

MUTATIONS = [
    dict(cid="T1", path="scripts/intake_core.py", anchor='SCHEMA_VERSION = ',
         new='SCHEMA_VERSION = "9"', why="信封 schema_version 改成 9"),
    dict(cid="T2", path="scripts/intake_core.py", anchor='"kind": "quality-exception",',
         new='        "kind": "quality-exception",\n        "extra": 1,',
         why="记录里多塞一个字段"),
    dict(cid="T3", path="scripts/intake_core.py", anchor='SEQ_START = ',
         new='SEQ_START = 1', why="序号下限从 100 改成 1"),
    dict(cid="T4", path="scripts/intake_core.py", anchor='return f"XJ{date8}{seq:03d}"',
         new='    return f"XJ-{date8}-{seq:03d}"', why="rel 加连字符"),
    dict(cid="T5", path="scripts/intake_core.py", anchor='契约 §C.3：人员违规 → 生产部',
         new='        return "制造部", "[团队自定] 契约 §C.3：人员违规 → 制造部"',
         why="dept 落到枚举外的值"),
    dict(cid="T5b2", path="scripts/intake_core.py", anchor='"泄漏"',
         new='    (("渗漏", "泄漏", "滴漏"), "生产部", "设备渗漏"),',
         why="§C.3 表里「设备渗漏→设备部」被改错部门"),
    dict(cid="T5b", path="scripts/intake_core.py", anchor='"明火"',
         new='    (("PPE", "人员", "闯入", "明火"), "制造部", "人员违规"),',
         why="可触发行「人员违规→生产部」被改错部门（单据静默进错部门）"),
    dict(cid="T5c", path="scripts/intake_core.py", anchor='"泄漏"',
         new='    (("渗漏", "泄漏", "滴漏"), "设备部", "设备渗漏"),',
         why="往夹具目录塞一条用了「当前不可触发」类别的夹具（v1.7 准入）",
         extra_fixture=("dept-forbidden.json", {"findings": [
             {"kind": "hazard", "code": "SAFE", "label": "设备渗漏",
              "confidence": 0.8, "evidence_ref": "mes-data/evidence/x.jpg"}]})),
    dict(cid="T6a", path="scripts/intake_core.py", anchor='"no": rel,',
         new='        "no": exception_no,',
         why="xj 记录的 no 不再等于 rel（rel 变成凭空的号）"),
    dict(cid="T7", path="scripts/intake_core.py", anchor='QUOTE_MAP = ',
         new='QUOTE_MAP = {}', fixture=QUOTED_FIXTURE,
         why="关掉引号剔除 + 用带引号的 label"),
    dict(cid="T8", path="scripts/commit.py", anchor="return 1", index=0,
         new="        return 0", why="失败路径返回 0"),
    dict(cid="T8", path="scripts/commit.py", anchor="[intake] !! {redact(exc)}",
         new='        print(f"[intake] !! {exc}", file=sys.stderr)',
         why="失败信息不再抹路径"),
    dict(cid="T9a", path="scripts/intake_core.py", anchor='DISCLAIMER = ',
         new='DISCLAIMER = "本结论不构成处罚、停机或联锁动作的唯一依据。"',
         why="免责措辞多一个句号"),
    # --- v1.4 新增断言的变异：三处链路各断一环，证明回落链与 --dept 出口都真的被测到
    dict(cid="T1b", path="scripts/intake_core.py", anchor='        "desc": desc,',
         new='        "desc": desc + str(datetime.now().microsecond),',
         why="产物含非确定性内容（两次产出不再逐字节相同）"),
    dict(cid="T2b", path="scripts/intake_core.py", anchor='        "iso": ISO_DEFAULT,',
         new='        "iso": "已隔离",', why="skill 越界做了 loader 的呈现映射（§B.2）"),
    dict(cid="T2b", path="scripts/intake_core.py", anchor="ISO_DEFAULT = ",
         new="ISO_DEFAULT = True", why="iso 默认值偏离 §C.5"),
    dict(cid="T3b", path="scripts/intake_core.py", anchor="if date_override:",
         new="    if False:", why="--date 失效（第一条链断）"),
    dict(cid="T3b", path="scripts/intake_core.py", anchor="if stamp:",
         new="    if False:", why="captured_at 回落失效（第二条链断）"),
    dict(cid="T3b", path="scripts/intake_core.py", anchor='        now.strftime("%Y%m%d"),',
         new='        "20200101",', why="系统当天兜底失效（第三条链断）"),
    dict(cid="T8b", path="scripts/intake_core.py",
         anchor='"契约 §C.3 映射表未覆盖该发现，拒绝猜测："',
         new='    return "生产部", "默认兜底"', span=3, before=1,
         why="映射不中改成默认归入生产部"),
    dict(cid="T8b", path="scripts/intake_core.py", anchor="请用 --dept 显式指定",
         new="        f\"code={code or '<空>'} label={finding.get('label') or '<空>'}\"",
         why="失败信息不给 --dept 出口提示"),
    dict(cid="T8b", path="scripts/intake_core.py", anchor="if override:",
         new="    if False:", why="--dept 出口被忽略（拒绝猜测变成死路）"),
]


def selftest(base_kwargs):
    """对 skill 副本逐个注入违规，断言对应检查确实变红——这一步证明本测试有效力。"""
    print("=== 变异自检：证明本测试确有抓错能力 ===")
    tmp = Path(tempfile.mkdtemp(prefix="cb_selftest_"))
    failures, stale, inputs = [], [], []
    try:
        for i, mut in enumerate(MUTATIONS):
            cid, rel, why = mut["cid"], mut["path"], mut["why"]
            root = tmp / f"m{i:02d}_{cid}"
            dst = root / "skills" / "mes-inspection-intake"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(base_kwargs["skill_root"], dst)
            target = dst / rel
            try:
                target.write_text(
                    _mutate_line(target.read_text(encoding="utf-8"), mut["anchor"],
                                 mut["new"], mut.get("index"), mut.get("span", 1),
                                 mut.get("before", 0),
                                 where=f"{rel}（被测技能副本）", cid=cid),
                    encoding="utf-8")
            except AnchorStale as exc:          # 逐条降级：一个锚点过期不该让整轮崩掉
                stale.append(str(exc))
                print(f"STALE 变异 {cid:<5} {why}\n"
                      f"      → 锚点过期，本变异**未执行**（测试台问题，非被测方问题）")
                continue
            fixture = base_kwargs["fixture"]
            if mut.get("fixture"):
                fixture = root / "quoted.json"
                fixture.write_text(json.dumps(mut["fixture"], ensure_ascii=False),
                                   encoding="utf-8")
            if mut.get("extra_fixture"):        # 往副本的夹具目录里塞文件（T5c 用）
                name, payload = mut["extra_fixture"]
                (dst / "evals" / "fixtures" / name).write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            results, _ = run_suite(skill_root=dst, contract_path=base_kwargs["contract_path"],
                                   disclaimer_doc=base_kwargs["disclaimer_doc"],
                                   fixture=fixture, workdir=root / "out",
                                   loader="off")   # 变异只针对 skill 侧，无需起 17 次浏览器
            got = {r["id"]: r["status"] for r in results}
            if got.get("T0") == FAIL:
                # 契约/措辞来源读不出来 ⇒ 未跑到被测代码，**无法判定**。这是输入问题，
                # 不是「变异没被逮到」——两者混为一谈会让人误以为测试失去了效力。
                detail = next((r["detail"] for r in results if r["id"] == "T0"), "")
                inputs.append(f"{cid}（{why}）→ {detail}")
                print(f"INPUT 变异 {cid:<5} {why}\n"
                      f"      → 契约/措辞来源不可解析，未跑到被测代码，**无法判定**（输入问题，非效力问题）")
                continue
            red = got.get(cid) == FAIL
            if not red:
                failures.append(f"{cid}（{why}）未变红：{got.get(cid)}")
            print(f"{'OK  ' if red else 'BAD '} 变异 {cid:<5} {why}  → {cid}={got.get(cid)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    total = len(MUTATIONS)
    ran = total - len(stale) - len(inputs)
    print(f"\n--- 变异自检：{ran - len(failures)}/{ran} 个变异被逮到 ---")
    print(f"    分母 = 本文件 MUTATIONS 条目数：共 {total} 条；执行 {ran}，"
          f"锚点过期未执行 {len(stale)}，输入不可解析未判定 {len(inputs)}")
    print("    该表随测试文件一起冻结 ⇒ **分母不应随运行变动**；若变了，"
          "要么表被改（须重冻），要么执行数被 stale/input 扣掉（上一行已列出）。")
    for f in failures:
        print(f"  BAD {f}")
    if stale:
        print(f"\n!! 测试台问题（{len(stale)} 条，**不是被测方违契**）——请更新下列锚点后重跑：\n")
        for s in stale:
            print(s)
    if inputs:
        print(f"\n!! 输入问题（{len(inputs)} 条，**不是测试失去效力**）"
              f"——契约/措辞来源读不出期望值，先修输入再判定：\n")
        for s in inputs:
            print(f"  {s}")
    return not failures and not stale and not inputs


# ---------------------------------------------------------------- 入口

def build_parser():
    p = argparse.ArgumentParser(prog="contract_bridge",
                                description="MES 桥契约测试（skill 侧产出 ↔ 契约 v1.1）")
    p.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    p.add_argument("--skill-root", default=str(DEFAULT_SKILL))
    p.add_argument("--disclaimer-doc", default=str(DISCLAIMER_DOC))
    p.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    p.add_argument("--workdir", default=None, help="产出目录（默认新建临时目录）")
    p.add_argument("--proto", default=str(DEFAULT_PROTO),
                   help="宿主页/原型目录（T11 集成半场用；也可用 MES_PROTO 环境变量）")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--loader", dest="loader", action="store_const", const="on", default="auto",
                     help="强制跑集成半场；前置缺失即判 FAIL（默认 auto：能跑就跑，缺前置记 SKIP）")
    grp.add_argument("--no-loader", dest="loader", action="store_const", const="off",
                     help="跳过集成半场（只跑 skill 侧，秒级）")
    p.add_argument("--keep", action="store_true", help="保留临时产出目录")
    p.add_argument("--selftest", action="store_true", help="变异自检：证明本测试有效力（skill 侧）")
    p.add_argument("--selftest-loader", action="store_true",
                   help="变异自检：证明 T11 集成半场各断言有效力（起浏览器，约 2-3 分钟）")
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)

    if args.selftest:
        return EXIT_OK if selftest({
            "skill_root": Path(args.skill_root),
            "contract_path": Path(args.contract),
            "disclaimer_doc": Path(args.disclaimer_doc),
            "fixture": Path(args.fixture),
        }) else EXIT_FAIL

    if args.selftest_loader:
        import contract_bridge_loader as lm
        c = parse_contract(Path(args.contract))
        return EXIT_OK if lm.selftest_loader(
            Path(args.proto), Path(args.skill_root),
            Path(args.fixture), c["idem_total"], c["idem_switches"],
            Path(tempfile.mkdtemp(prefix="cb_loader_st_"))) else EXIT_FAIL

    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="cb_bridge_"))
    proto = Path(args.proto)          # 默认值已由 default_proto_root() 处理过环境变量
    try:
        results, meta = run_suite(Path(args.skill_root), Path(args.contract),
                                  Path(args.disclaimer_doc), Path(args.fixture), workdir,
                                  loader=args.loader, proto_root=proto)
        green = report(results, meta)
        incomplete = any(r["status"] == SKIP for r in results)
    finally:
        if not args.keep and not args.workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    if not green:
        return EXIT_FAIL
    # 「绿而不完整」：无 FAIL 但有 SKIP ⇒ 单独退出码 2。只读退出码的门再也无法把
    # 「某一半压根没跑」当成通过——这是 SKIP 能伪装成「没跑但不影响」的堵法。
    return EXIT_INCOMPLETE if incomplete else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
