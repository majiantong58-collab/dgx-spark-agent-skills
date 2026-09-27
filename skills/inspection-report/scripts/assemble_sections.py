"""组装巡检报告结构：校验输入、分级排序、映射整改建议。

只做汇总与措辞——**不新增上游未给出的结论**。
Schema 见 ../references/output-schema.md；建议措辞表见 ../references/severity-levels.md。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
REMEDIATION_TABLE_FILE = Path(__file__).resolve().parent.parent / "references" / "severity-levels.md"
FALLBACK_RECOMMENDATION = "整改建议待定"

_REMEDIATION_ROW = re.compile(r"^\|\s*`(?P<code>[A-Z][A-Z0-9-]*)`\s*\|(?P<text>[^|]+)\|")


def validate_findings(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """校验上游结论：每条须含 code 与 confidence，否则**拒收并回报**。

    缺置信度的条目不得静默丢弃——必须出现在返回值中以便上报。

    Returns:
        被拒收的条目列表；空列表表示全部合格。
    """
    rejected: list[dict[str, Any]] = []
    for item in findings:
        missing = [
            key
            for key in ("code", "confidence", "evidence_ref")
            if item.get(key) in (None, "", [])
        ]
        if missing:
            rejected.append({**item, "rejected_reason": f"缺少必填字段：{', '.join(missing)}"})
    return rejected


def load_remediation_table(path: Path | str = REMEDIATION_TABLE_FILE) -> dict[str, str]:
    """读取 severity-levels.md 的整改建议映射表。

    映射表是**唯一**措辞来源；表里没有的 code 一律输出「整改建议待定」。
    """
    text = Path(path).read_text(encoding="utf-8")
    table: dict[str, str] = {}
    for line in text.splitlines():
        m = _REMEDIATION_ROW.match(line.strip())
        if m:
            table[m.group("code")] = m.group("text").strip()
    if not table:
        raise ValueError(f"整改建议表解析为空：{path}")
    return table


def sort_items(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 severity 排序，同级按点位号；返回新列表，不修改入参。"""
    return sorted(
        (dict(item) for item in findings),
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity", "low")), len(SEVERITY_ORDER)),
            str(item.get("code", "")),
        ),
    )


def attach_recommendations(
    items: Sequence[dict[str, Any]], table: dict[str, str]
) -> list[dict[str, Any]]:
    """套用整改建议。命中不到时用「整改建议待定」，不做自由发挥。"""
    return [
        {**item, "recommendation": table.get(str(item.get("code")), FALLBACK_RECOMMENDATION)}
        for item in items
    ]


def build_summary(items: Sequence[dict[str, Any]]) -> dict[str, int]:
    """统计 total / critical / high / medium / low / uncertain_count / tier2_calls。"""
    severities = [str(item.get("severity", "low")) for item in items]
    return {
        "total": len(items),
        "critical": severities.count("critical"),
        "high": severities.count("high"),
        "medium": severities.count("medium"),
        "low": severities.count("low"),
        "uncertain_count": sum(1 for item in items if item.get("uncertain")),
        "tier2_calls": sum(1 for item in items if item.get("tier") == 2),
    }


def verify_roundtrip(
    built: dict[str, Any], findings: Sequence[dict[str, Any]]
) -> list[str]:
    """回读校验：报告里每条 code 必须能在输入中找到对应项。

    Returns:
        找不到对应项的 code 列表；非空时调用方**必须中止输出**。
    """
    known = {str(item.get("code")) for item in findings}
    return [str(item.get("code")) for item in built.get("items", []) if str(item.get("code")) not in known]


def build_report(
    findings: Sequence[dict[str, Any]], *, meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    """把上游结论组装成 output-schema.md §1 的完整 JSON 结构。

    缺值的键一律补 `null` / `未指定`，**不省略键**。业务规则全部在 references/，
    本函数只做组装与统计。

    Raises:
        ValueError: 条目不满足 output-schema.md §3 校验规则 1/2 时中止，不输出半成品。
    """
    meta = dict(meta or {})
    rejected = validate_findings(findings)
    if rejected:
        raise ValueError(f"拒收 {len(rejected)} 条缺字段的结论：{[r['code'] for r in rejected]}")

    items = attach_recommendations(sort_items(findings), load_remediation_table())
    for index, item in enumerate(items, start=1):
        item["index"] = index

    built: dict[str, Any] = {
        "report_id": str(meta.get("report_id") or uuid.uuid4()),
        "site": str(meta.get("site") or "未指定"),
        "inspector": meta.get("inspector"),
        "captured_at": meta.get("captured_at"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "standard_version": str(meta.get("standard_version") or "hazard-taxonomy v0.1"),
        "summary": build_summary(items),
        "items": items,
        "partial": bool(meta.get("partial", False)),
        "disclaimers": list(meta.get("disclaimers") or []),
    }

    orphans = verify_roundtrip(built, findings)
    if orphans:
        raise ValueError(f"回读校验失败，报告含无法回溯的条目：{orphans}")
    return built
