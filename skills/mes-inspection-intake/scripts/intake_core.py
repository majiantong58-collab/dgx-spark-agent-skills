"""mes-inspection-intake 逻辑层。

契约：docs/agents/mes-bridge-contract.md v1（§C 数据契约 / §D 安全约束）。
本模块 import 无副作用：不打印、不退出、不写文件；入口见 scripts/commit.py。

规则来源限定：§C / §D + decision-log.md D-030。契约未覆盖处一律标 [团队自定] 并上报，
不自行发明业务规则。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = "1"
PRODUCED_BY = "mes-inspection-intake"

# 逐字取自契约 §C 示例 = 单一措辞来源 inspection-report/references/output-schema.md §4（长版，不得改写）。
# v1.3：契约示例此前为短版，与自称的来源打架；已裁决全链统一用长版。已知小瑕：长版主语是「本报告」，
# 用在单据上略有错位——有意接受的代价（另立第二措辞源 = 多一个要同步的东西）。
DISCLAIMER = "本报告由 AI 辅助生成，结论基于图像证据自动判定，需经人工复核确认。本报告不作为处罚、停机或联锁动作的唯一依据。"

# 契约 §A.1 / §C.3：责任部门枚举（原型 index.html:2230 与 :9305 两处同值）
DEPT_ENUM = ("供应商", "生产部", "设备部", "采购部")

# 契约 §C.1：QA-YYYYMMDD-NNN（3 位序，按日重置）· §C.2：XJ<YYYYMMDD><NNN>
NO_RE = re.compile(r"^QA-(\d{8})-(\d{3})$")
REL_RE = re.compile(r"^XJ(\d{8})(\d{3})$")
GAUGE_CODE_RE = re.compile(r"^[A-Z]{1,4}-\d{1,4}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 契约 §D：原型 esc() 只转义 & < >，不转义引号 ⇒ 产出串不得含 " 或 '
QUOTE_MAP = {'"': "”", "'": "’"}

TZ = timezone(timedelta(hours=8))  # 演示时区，与原型世界日期同口径
MAX_SEQ = 999
XJ_FILENAME = "xj-records.json"

# 序号下限（契约 §C.1 v1.1：峰值取 max(100, 当日既有产出 max+1)）。
# 原「从 001 起」与「M1 fixture 用原型世界日期」互斥——库内 QA-20260813-001/002/003 已占用
# （R2-S 2026-09-28 实测），故自产号统一走 100 系列。
SEQ_START = 100

# 契约 §C.3 部门映射 —— [团队自定]，依据 decision-log.md D-030 裁决 3。
# MES 无现场安全巡检业务对象（D-030 事实 1），本表不出自 MES / SRS 任何材料。
DEPT_RULES = (
    (("PPE", "人员", "闯入", "明火"), "生产部", "人员违规"),
    (("通道", "堵塞", "占道"), "生产部", "通道堵塞"),
    (("渗漏", "泄漏", "滴漏"), "设备部", "设备渗漏"),
    (("仪表", "读数", "表盘", "指针"), "设备部", "仪表读数异常"),
)


class IntakeError(Exception):
    """可预期失败。消息面向人，且不得含本机绝对路径（契约 §D）。"""


# 契约 §B.2（v1.5）：JSON 侧 iso 为**布尔**，呈现映射归 loader（false → 「未隔离」）。
# 取值规则为 [团队自定]——MES / SRS 没有任何「巡检发现该不该隔离」的规定。
#   实测语义：原型「隔离标识」= 物料 / 在制品的**扣留**标识（:2251 表头 · :2203「生成隔离标识禁止流转」·
#   :9308 抽屉字段名「隔离标识（数量 / 区域）」+ 取值 `已隔离 · 2,400 · QC 隔离区`）。
#   🔴 决定性的两条种子行：:2256 电机线圈电阻超差 = **未隔离**、:2260 绕线 PIN 超长 = **已隔离**
#   —— 两条**同为物料类**却取值不同 ⇒ iso 不是「是否涉及物料」，而是「**是否实际执行了物料隔离**」。
# 我们的 4 类发现（人员 / 通道 / 渗漏 / 仪表）都不扣留任何物料 ⇒ 默认 **False**。
# 置 True 的条件（[团队自定]）：发现明确涉及在制产品 / 物料批次**且已执行隔离**。
#   当前上游 finding 契约（routing-table.md §3）无此信号源 ⇒ **不实现分支**：未定义的口径不发明。
ISO_DEFAULT = False


def strip_quotes(value):
    """递归剔除字符串中的 " 与 '（契约 §D）。返回 (净化后的对象, 替换次数)。"""
    if isinstance(value, str):
        count = sum(value.count(ch) for ch in QUOTE_MAP)
        for src, dst in QUOTE_MAP.items():
            value = value.replace(src, dst)
        return value, count
    if isinstance(value, dict):
        out, total = {}, 0
        for key, val in value.items():
            out[key], count = strip_quotes(val)
            total += count
        return out, total
    if isinstance(value, list):
        out_list, total = [], 0
        for item in value:
            clean, count = strip_quotes(item)
            out_list.append(clean)
            total += count
        return out_list, total
    return value, 0


def _walk_strings(node):
    """深度遍历，产出全部字符串值（用于扫既有单号，不扫原型 DOM）。"""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)


def _keep_max(bucket, date8, seq):
    if seq > bucket.get(date8, 0):
        bucket[date8] = seq


def scan_existing(out_dir):
    """扫产出目录既有 *.json 取号（契约 §C.1：不扫原型 DOM）。

    返回 {"QA": {date8: max_seq}, "XJ": {date8: max_seq}}。目录里的坏 JSON 不阻塞取号。
    """
    maxima = {"QA": {}, "XJ": {}}
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return maxima
    for path in sorted(out_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for text in _walk_strings(doc):
            match = NO_RE.match(text)
            if match:
                _keep_max(maxima["QA"], match.group(1), int(match.group(2)))
            match = REL_RE.match(text)
            if match:
                _keep_max(maxima["XJ"], match.group(1), int(match.group(2)))
    return maxima


def next_no(date8, maxima):
    """当日 QA 单号 max+1（契约 §C.1：3 位序，按日重置）；下限见 SEQ_START。"""
    seq = max(SEQ_START, maxima["QA"].get(date8, 0) + 1)
    if seq > MAX_SEQ:
        raise IntakeError(
            f"当日单号已用尽：{date8} 已达 {MAX_SEQ} 条，契约 §C.1 只留 3 位序"
        )
    maxima["QA"][date8] = seq
    return f"QA-{date8}-{seq:03d}"


def next_rel(date8, maxima):
    """当日 XJ 关联单号 max+1（契约 §C.2，无连字符）；下限见 SEQ_START。"""
    seq = max(SEQ_START, maxima["XJ"].get(date8, 0) + 1)
    if seq > MAX_SEQ:
        raise IntakeError(
            f"当日 XJ 单号已用尽：{date8} 已达 {MAX_SEQ} 条，契约 §C.2 只留 3 位序"
        )
    maxima["XJ"][date8] = seq
    return f"XJ{date8}{seq:03d}"


def resolve_when(doc, date_override, now=None):
    """定日期/时间口径。返回 (YYYY-MM-DD, YYYYMMDD, HH:MM, 来源说明)。

    优先级：--date（仅覆盖日期段）> finding 的 captured_at > 系统当天。
    契约 §C.1 只规定 --date 与默认当天；captured_at 回落为 [团队自定] 补充。
    """
    now = now or datetime.now(TZ)
    stamp = None
    captured = doc.get("captured_at")
    if isinstance(captured, str) and captured.strip():
        raw = captured.strip()
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            raise IntakeError(f"captured_at 不是 ISO8601 时间：{raw}") from None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=TZ)
        stamp = stamp.astimezone(TZ)

    if date_override:
        if not DATE_RE.match(date_override):
            raise IntakeError(f"--date 需为 YYYY-MM-DD：{date_override}")
        day = datetime.strptime(date_override, "%Y-%m-%d")
        clock = (stamp or now).strftime("%H:%M")
        return day.strftime("%Y-%m-%d"), day.strftime("%Y%m%d"), clock, "--date 覆盖"
    if stamp:
        return (
            stamp.strftime("%Y-%m-%d"),
            stamp.strftime("%Y%m%d"),
            stamp.strftime("%H:%M"),
            "finding.captured_at（[团队自定] 回落口径）",
        )
    return (
        now.strftime("%Y-%m-%d"),
        now.strftime("%Y%m%d"),
        now.strftime("%H:%M"),
        "系统当天（契约 §C.1 默认）",
    )


def pick_findings(doc):
    """取上游 findings（契约见 inspection-orchestrator/references/routing-table.md §3）。"""
    if not isinstance(doc, dict):
        raise IntakeError("发现文件顶层不是 JSON 对象")
    if isinstance(doc.get("findings"), list):
        findings = doc["findings"]
    elif "code" in doc or "label" in doc:
        findings = [doc]  # 单条 finding 直接给也接受
    else:
        raise IntakeError(
            "找不到 findings 数组（上游契约：inspection-orchestrator/references/routing-table.md §3）"
        )
    if not findings:
        raise IntakeError("findings 为空，没有可落单的发现")
    return findings


def map_dept(finding, override=None):
    """契约 §C.3 部门映射 [团队自定]。返回 (dept, 理由)。映射不中即报错，不用默认值兜底。"""
    if override:
        if override not in DEPT_ENUM:
            raise IntakeError(
                f"--dept 不在枚举内：{override}（契约 §A.1 枚举：{'/'.join(DEPT_ENUM)}）"
            )
        return override, "命令行显式指定 [团队自定]"

    code = str(finding.get("code") or "").strip()
    upper = code.upper()
    if upper.startswith("PPE-"):
        return "生产部", "[团队自定] 契约 §C.3：人员违规 → 生产部"
    if str(finding.get("kind") or "").strip().lower() == "gauge" or GAUGE_CODE_RE.match(upper):
        return "设备部", "[团队自定] 契约 §C.3：仪表读数异常 → 设备部"

    haystack = f"{upper} {finding.get('label') or ''} {finding.get('reason') or ''}"
    for keys, dept, label in DEPT_RULES:
        if any(key in haystack for key in keys):
            return dept, f"[团队自定] 契约 §C.3：{label} → {dept}"

    raise IntakeError(
        "契约 §C.3 映射表未覆盖该发现，拒绝猜测："
        f"code={code or '<空>'} label={finding.get('label') or '<空>'}；请用 --dept 显式指定"
    )


def build_record(finding, dept, no, rel, date_str, time_str):
    """契约 §C 逐字段。字段名与顺序对齐契约示例。"""
    if finding.get("confidence") is None:
        raise IntakeError(
            "finding 缺 confidence——上游契约硬规则（routing-table.md §3）要求拒收无置信度条目"
        )
    evidence = str(finding.get("evidence_ref") or "").strip()
    if not evidence:
        raise IntakeError("finding 缺 evidence_ref——上游契约硬规则要求该项必填")
    desc = str(finding.get("label") or "").strip()
    if not desc:
        raise IntakeError("finding 缺 label，异常现象不能为空")

    return {
        "kind": "quality-exception",
        "no": no,
        "rel": rel,
        "dept": dept,
        "desc": desc,
        "iso": ISO_DEFAULT,
        "finder": "巡检 Agent",
        "time": time_str,
        "date": date_str,
        "provenance": {
            "source_skill": str(finding.get("source") or "未标注"),
            "confidence": finding["confidence"],
            "evidence_ref": evidence,
            "disclaimer": DISCLAIMER,
        },
    }


def build_xj_record(rel, date_str, time_str, obj, finding, source_skill, confidence, exception_no):
    """契约 §C.4：rel 指向的 XJ 巡检记录由本 skill 一并产出。

    字段逐项对齐 §C.4「记录字段」行：no / date / time / obj / finding / source_skill /
    confidence / related_exception（不多不少）。信封与 inbox.json 同构。
    本版无自动消费方（原型不读它）——它是 rel 的指涉对象，供人工 / 审计追溯。
    """
    return {
        "no": rel,
        "date": date_str,
        "time": time_str,
        "obj": obj,
        "finding": finding,
        "source_skill": source_skill,
        "confidence": confidence,
        "related_exception": exception_no,
    }


def load_envelope(path):
    """读既有产出。坏文件 / 版本不符一律拒绝，不静默覆盖（契约 §F 精神：禁止静默失败）。"""
    path = Path(path)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise IntakeError(
            f"{path.name} 不是合法 JSON——本工具不覆盖坏文件，请删除它或改用别的 --out"
        ) from None
    if not isinstance(doc, dict):
        raise IntakeError(f"{path.name} 顶层不是对象——请删除它或改用别的 --out")
    version = str(doc.get("schema_version") or "")
    if version != SCHEMA_VERSION:
        raise IntakeError(
            f"{path.name} 的 schema_version={version or '<缺失>'}，本工具只写 {SCHEMA_VERSION}；"
            "契约 §F 要求版本不一致时显式报错，不得静默覆盖"
        )
    if not isinstance(doc.get("records"), list):
        raise IntakeError(f"{path.name} 缺 records 数组——请删除它或改用别的 --out")
    return doc


def build_envelope(existing, records, produced_at):
    merged = list(existing["records"]) if existing else []
    return {
        "schema_version": SCHEMA_VERSION,
        "produced_by": PRODUCED_BY,
        "produced_at": produced_at,
        "records": merged + records,
    }


def assert_lf(path):
    """🔴 断言产物内**不得含 `\\r`**（契约 §C.6 的来源证明要求跨平台逐字节可复现）。

    **按字节读**，不经文本模式——文本模式会把 `\\r\\n` 归一成 `\\n`，正好把要抓的东西抹掉。
    """
    data = Path(path).read_bytes()
    cr = data.count(bytes([13]))          # 13 == CR；用 bytes([13]) 免掉转义层数带来的歧义
    if cr:
        raise IntakeError(
            f"产物含 CR：{Path(path).name} 有 {cr} 个 CR —— "
            f"违反契约 §C.6「除 produced_at 外逐字节相同」（跨平台不可复现）。"
            f"写文件须显式 newline=LF。"
        )


def commit_findings(finding_path, out_path, date_override=None, dept_override=None, now=None):
    """把发现落成 inbox.json（+ 同目录 XJ 记录）。返回 {progress: [...]}, 失败抛 IntakeError。

    写入位置由调用方给定；本技能默认不指定MES 工作区路径（由 M1 闸的调用方决定）。
    """
    finding_path = Path(finding_path)
    out_path = Path(out_path)
    if not finding_path.is_file():
        raise IntakeError(f"找不到发现文件：{finding_path}")
    try:
        doc = json.loads(finding_path.read_text(encoding="utf-8"))
    except ValueError:
        raise IntakeError(f"{finding_path.name} 不是合法 JSON，无法解析") from None
    except OSError as exc:
        # 只取 strerror：exc 本体可能带完整路径，会破坏 §D 的抹路径要求
        raise IntakeError(f"{finding_path.name} 读取失败：{exc.strerror or type(exc).__name__}") from None

    findings = pick_findings(doc)
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    envelope = load_envelope(out_path)
    xj_path = out_dir / XJ_FILENAME
    xj_envelope = load_envelope(xj_path)

    now = now or datetime.now(TZ)
    date_str, date8, time_str, when_source = resolve_when(doc, date_override, now)
    maxima = scan_existing(out_dir)
    site = str(doc.get("site") or "未指定").strip() or "未指定"

    records, xj_records, reasons = [], [], []
    quote_hits = 0
    for finding in findings:
        dept, reason = map_dept(finding, dept_override)
        no = next_no(date8, maxima)
        rel = next_rel(date8, maxima)
        record, hits = strip_quotes(
            build_record(finding, dept, no, rel, date_str, time_str)  # §D：产出值不得含引号
        )
        xj_record, xj_hits = strip_quotes(
            build_xj_record(  # 取值一律回引已净化的异常单记录，避免两处口径分叉
                rel, date_str, time_str, site, record["desc"],
                record["provenance"]["source_skill"], record["provenance"]["confidence"], no,
            )
        )
        records.append(record)
        xj_records.append(xj_record)
        reasons.append(f"{no} · {dept}（{reason}）· rel={rel}")
        quote_hits += hits + xj_hits

    produced_at = now.isoformat(timespec="seconds")
    # 🔴 newline="\n"：文本模式默认按 os.linesep 翻译，Windows 上会把 \n 写成 \r\n。
    # 契约 §C.6 的来源证明是「同 fixture 重跑 ⇒ 除 produced_at 外**逐字节相同**」——
    # 若换行随平台变，这条主张跨平台即假。故显式钉死 LF。
    out_path.write_text(
        json.dumps(build_envelope(envelope, records, produced_at), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    xj_path.write_text(
        json.dumps(build_envelope(xj_envelope, xj_records, produced_at), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # 写完立刻按**字节**复验，不留「本该 LF 却写成 CRLF」的静默窗口
    for _p in (out_path, xj_path):
        assert_lf(_p)

    progress = [
        f"日期口径：{date_str}（{when_source}）",
        f"落单 {len(records)} 条 → {out_path.name}",
        f"关联巡检记录 {len(xj_records)} 条 → {xj_path.name}",
        *reasons,
    ]
    if quote_hits:
        progress.append(f"引号替换 {quote_hits} 处（契约 §D：产出值不得含 \" 或 '）")
    progress.append("schema_version=1，上游 loader 注入 qm-quality-exception（契约 §B.1）")
    return {"progress": progress, "records": records, "xj_records": xj_records}
