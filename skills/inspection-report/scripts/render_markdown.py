"""把已组装的结构渲染为 Markdown。固定小节顺序见 ../references/output-schema.md §2。

本模块只做渲染——不做分级、不做建议映射、不引入新结论。
"""

from __future__ import annotations

from typing import Any

REQUIRED_SECTIONS = [
    "关键问题",
    "重要问题",
    "一般问题",
    "附录：低风险与待复核项",
    "免责声明",
]

# 小节 → severity（附录单独处理，见 render）
_SECTION_SEVERITY = {"关键问题": "critical", "重要问题": "high", "一般问题": "medium"}

DISCLAIMER = (
    "本报告由 AI 辅助生成，结论基于图像证据自动判定，需经人工复核确认。"
    "本报告不作为处罚、停机或联锁动作的唯一依据。"
)

_NOT_SPECIFIED = "未指定"


def _value(value: Any) -> str:
    """缺值一律渲染为 `未指定`；不得用当前时间冒充巡检时间。"""
    return str(value) if value not in (None, "") else _NOT_SPECIFIED


def render_header(meta: dict[str, Any]) -> str:
    """渲染抬头：点位 / 巡检人 / 巡检时间 / 生成时间 / 判定标准版本。

    缺失字段渲染为 `未指定`，**不得**用当前时间冒充巡检时间。
    """
    return (
        "# 安全巡检报告\n"
        f"> 点位：{_value(meta.get('site'))} ｜ 巡检人：{_value(meta.get('inspector'))} ｜ "
        f"巡检时间：{_value(meta.get('captured_at'))} ｜ "
        f"生成时间：{_value(meta.get('generated_at'))} ｜ "
        f"判定标准版本：{_value(meta.get('standard_version'))}"
    )


def _render_item(index: int, item: dict[str, Any]) -> str:
    """渲染单个条目。uncertain 标记原样保留，不做清洗。"""
    flags = []
    if item.get("uncertain"):
        flags.append("**uncertain**")
    if item.get("requires_human_review"):
        flags.append("需人工复核")
    flag_text = f" ｜ {'，'.join(flags)}" if flags else ""
    evidence = item.get("evidence") or item.get("evidence_ref")
    return (
        f"{index}. `{item.get('code')}` {item.get('label', '')}"
        f"（severity={item.get('severity')}，confidence={item.get('confidence')}，"
        f"tier={item.get('tier')}）{flag_text}\n"
        f"   - 证据：{_value(evidence)}\n"
        f"   - 整改建议：{item.get('recommendation', _NOT_SPECIFIED)}"
    )


def render_section(title: str, items: list[dict[str, Any]]) -> str:
    """渲染单个分级小节；空小节渲染为「本级别未发现问题」。"""
    body = (
        "\n".join(_render_item(i, item) for i, item in enumerate(items, start=1))
        if items
        else "本级别未发现问题。"
    )
    return f"## {title}\n\n{body}"


def render_uncertain(items: list[dict[str, Any]]) -> str:
    """渲染待复核项——必须原样保留 `uncertain` 标记，不得清洗。"""
    if not items:
        return "无待复核项。"
    return "\n".join(_render_item(i, item) for i, item in enumerate(items, start=1))


def render_footer(disclaimers: list[str]) -> str:
    """渲染页脚，强制包含 DISCLAIMER 原文。"""
    lines = [f"> {DISCLAIMER}"]
    lines += [f"> {text}" for text in disclaimers if text.strip() != DISCLAIMER]
    return "\n".join(lines)


def render(built: dict[str, Any]) -> str:
    """总入口：按 REQUIRED_SECTIONS 顺序渲染完整 Markdown。

    任何小节缺失即报错——不输出半成品报告。
    """
    missing = [key for key in ("summary", "items", "disclaimers") if key not in built]
    if missing:
        raise ValueError(f"报告结构缺字段，拒绝输出半成品：{', '.join(missing)}")
    if not built["disclaimers"]:
        raise ValueError("disclaimers 为空，违反 output-schema.md 校验规则 5")

    items = list(built["items"])
    by_severity = {
        severity: [i for i in items if i.get("severity") == severity]
        for severity in _SECTION_SEVERITY.values()
    }
    # 附录 = 低风险 + 全部待复核项（去重，保持 items 原序）
    appendix = [
        i for i in items if i.get("severity") == "low" or i.get("uncertain")
    ]

    sections = [
        render_header(built),
        render_section("1. 关键问题（critical）", by_severity["critical"]),
        render_section("2. 重要问题（high）", by_severity["high"]),
        render_section("3. 一般问题（medium）", by_severity["medium"]),
        f"## 4. {REQUIRED_SECTIONS[3]}\n\n{render_uncertain(appendix)}",
        f"## 5. {REQUIRED_SECTIONS[4]}\n\n{render_footer(list(built['disclaimers']))}",
    ]
    return "\n\n".join(sections) + "\n"
