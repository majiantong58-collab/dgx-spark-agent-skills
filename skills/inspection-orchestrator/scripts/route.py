"""编排层路由与输入规范化。

本模块只做「决定调哪个子技能」，不含任何识别业务逻辑。
识别一律下沉到 safety-hazard-detection / gauge-reading / inspection-report。

契约见 ../references/routing-table.md
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SkillName = Literal[
    "safety-hazard-detection",
    "gauge-reading",
    "inspection-report",
]
Tier = Literal[0, 1, 2]

# 输入规范化护栏：低于此边长的帧不足以支撑任何可信结论，直接拒收
MIN_FRAME_EDGE = 64
MIN_FRAME_COUNT = 1
MAX_FRAME_COUNT = 60

# 关键词表——与 references/routing-table.md §1 逐行对应。
# 判定顺序即冲突消解优先级：明确指定 > 关键词 > 默认编排。
HAZARD_KEYWORDS = (
    "隐患", "违章", "违规", "安全帽", "反光衣", "安全带", "ppe", "闯入", "警戒",
    "通道", "堵塞", "占压", "渗漏", "泄漏", "积液", "明火", "烟雾", "裸露",
    "配电箱", "凌乱", "定置", "5s", "安全检查", "作业",
    # v2 场景对齐：电子厂洁净车间的真实 PPE 词汇。
    # 只增不删——旧的「安全帽 / 反光衣」保留，否则 v1 实验结果中模型自创的
    # helmet_detection / reflective_clothing_detection 将无从追溯（见
    # docs/agents/experiment-version-note.md）。
    "防尘帽", "防静电服", "静电服", "洁净服", "无尘服", "工服", "洁净车间",
)
GAUGE_KEYWORDS = (
    "表盘", "指针", "读数", "抄表", "压力表", "温度表", "液位", "仪表", "量程",
)
REPORT_KEYWORDS = (
    "报告", "成文", "导出", "汇总", "排版", "巡检记录", "出个表",
)
# 非工业场景——命中即 out_of_scope，不进入任何识别
OUT_OF_SCOPE_KEYWORDS = (
    "街景", "街拍", "办公", "家居", "客厅", "卧室", "自拍", "风景", "美食",
    "宠物", "旅游", "菜谱",
)
# 未命中任何关键词时的默认去向：隐患识别覆盖面最广，作为默认编排目标
DEFAULT_SKILL: SkillName = "safety-hazard-detection"


@dataclass(frozen=True)
class RouteDecision:
    """一次路由决策。"""

    skill: SkillName
    reason: str
    tier: Tier
    requires_cloud_auth: bool = False


@dataclass(frozen=True)
class NormalizedInput:
    """规范化后的任务输入。"""

    task_id: str
    frames: list[str] = field(default_factory=list)
    site: str = "未指定"
    captured_at: str | None = None
    cloud_authorized: bool = False
    raw_text: str = ""
    requested_skill: SkillName | None = None


def normalize_input(payload: dict[str, Any]) -> NormalizedInput:
    """校验并规范化输入：可解码性、分辨率、帧数、站点与授权状态。

    Args:
        payload: 原始任务负载，含 frames / text / site / cloud_authorized 等键。

    Returns:
        规范化后的 NormalizedInput。

    Raises:
        ValueError: 图像不可解码、分辨率过低或帧数为 0 时抛出，不进入识别。

    注：纯文本请求（无 frames）按契约在此拒收，由调用方在进入本函数前直接回答。
    """
    frames = list(payload.get("frames") or [])
    if not frames:
        raise ValueError("frames 为空：无图像的任务不进编排层，直接回答")
    if len(frames) > MAX_FRAME_COUNT:
        raise ValueError(f"帧数 {len(frames)} 超过上限 {MAX_FRAME_COUNT}")

    checked: list[str] = []
    for raw in frames:
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"帧不存在：{path}")
        try:
            from PIL import Image

            with Image.open(path) as im:
                width, height = im.size
                im.verify()
        except Exception as exc:
            raise ValueError(f"帧不可解码：{path}（{type(exc).__name__}）") from exc
        if min(width, height) < MIN_FRAME_EDGE:
            raise ValueError(f"分辨率过低：{path} 为 {width}x{height}，短边需 ≥ {MIN_FRAME_EDGE}")
        checked.append(str(path))

    requested = payload.get("requested_skill")
    if requested is not None and requested not in (
        "safety-hazard-detection",
        "gauge-reading",
        "inspection-report",
    ):
        raise ValueError(f"未知的 requested_skill：{requested}")

    return NormalizedInput(
        task_id=str(payload.get("task_id") or uuid.uuid4()),
        frames=checked,
        site=str(payload.get("site") or "未指定"),
        captured_at=payload.get("captured_at"),
        cloud_authorized=bool(payload.get("cloud_authorized", False)),
        raw_text=str(payload.get("text") or ""),
        requested_skill=requested,
    )


def _hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    """返回命中的关键词（大小写不敏感），供 reason 追溯。"""
    lowered = text.lower()
    return [kw for kw in keywords if kw.lower() in lowered]


def _tier_for(skill: SkillName) -> Tier:
    """子技能的起始层级——与 routing-table.md §1 的 tier 列一致。"""
    return {"safety-hazard-detection": 0, "gauge-reading": 1, "inspection-report": 2}[skill]


def plan_routes(inp: NormalizedInput) -> list[RouteDecision]:
    """按 routing-table.md 选出子技能序列（多目标时串行，不并行）。

    冲突消解优先级：用户明确指定的单一技能 > 关键词判定 > 默认编排。
    非工业场景返回空列表，由调用方给出 out_of_scope。

    Args:
        inp: 规范化输入。

    Returns:
        有序的路由决策列表；空列表表示不路由。
    """
    text = inp.raw_text

    # 1) 非工业场景——最高优先级拦截，连明确指定也不放行
    if _hits(text, OUT_OF_SCOPE_KEYWORDS):
        return []

    # 2) 用户明确指定的单一技能 > 关键词判定（routing-table.md §1 冲突消解）
    if inp.requested_skill is not None:
        return [
            RouteDecision(
                skill=inp.requested_skill,
                reason=f"用户明确指定：{inp.requested_skill}",
                tier=_tier_for(inp.requested_skill),
            )
        ]

    hazard_hits = _hits(text, HAZARD_KEYWORDS)
    gauge_hits = _hits(text, GAUGE_KEYWORDS)
    report_hits = _hits(text, REPORT_KEYWORDS)

    decisions: list[RouteDecision] = []

    if hazard_hits and gauge_hits:
        decisions.append(
            RouteDecision("safety-hazard-detection", f"关键词命中：{'/'.join(hazard_hits)}", 0)
        )
        decisions.append(RouteDecision("gauge-reading", f"关键词命中：{'/'.join(gauge_hits)}", 1))
    elif gauge_hits:
        decisions.append(RouteDecision("gauge-reading", f"关键词命中：{'/'.join(gauge_hits)}", 1))
    elif hazard_hits:
        decisions.append(
            RouteDecision("safety-hazard-detection", f"关键词命中：{'/'.join(hazard_hits)}", 0)
        )
    else:
        decisions.append(
            RouteDecision(DEFAULT_SKILL, "默认编排：未命中任何关键词，按最广覆盖子技能处理", 0)
        )

    # 3) 有结论且要求成文 → 串行汇入报告层（多目标不并行，避免同帧重复计费）
    if report_hits:
        decisions.append(
            RouteDecision("inspection-report", f"关键词命中：{'/'.join(report_hits)}", 2)
        )
    return decisions


def enforce_safety_boundary(
    decisions: list[RouteDecision], inp: NormalizedInput
) -> list[RouteDecision]:
    """安全边界闸门——在调用任何子技能之前执行。

    未获云端授权时强制把 tier 降为 0/1，禁止任何像素外发。

    Args:
        decisions: 待执行的原始路由决策。
        inp: 规范化输入，其 cloud_authorized 决定是否放行 Tier 2。

    Returns:
        施加边界后的新列表（不修改入参，保持不可变）。
    """
    if inp.cloud_authorized:
        return [
            RouteDecision(d.skill, d.reason, d.tier, requires_cloud_auth=d.tier == 2)
            for d in decisions
        ]
    # 未授权：禁止任何像素外发，Tier 2 一律压回 Tier 1
    return [
        RouteDecision(d.skill, f"{d.reason}（未获云端授权，Tier 2 压回本地）", min(d.tier, 1), False)
        if d.tier == 2
        else RouteDecision(d.skill, d.reason, d.tier, False)
        for d in decisions
    ]


def assemble_result(
    inp: NormalizedInput,
    decisions: list[RouteDecision],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """汇总子技能结果，补充 source_skill / tier / requires_human_review / partial。

    本函数不生成报告——报告一律交给 inspection-report。
    """
    normalized: list[dict[str, Any]] = []
    for raw in findings:
        item = dict(raw)
        item.setdefault("kind", "hazard")
        item.setdefault("tier", 0)
        item.setdefault("uncertain", False)
        item.setdefault("source", "safety-hazard-detection")
        # source_skill 是 source 的显式别名：编排层用它标注「这条是哪一跳产出的」
        item.setdefault("source_skill", item["source"])
        # critical 无论置信度多高都必须人工复核（hazard-taxonomy.md §4）
        item.setdefault(
            "requires_human_review", item.get("severity") == "critical" or item["uncertain"]
        )
        normalized.append(item)

    return {
        "task_id": inp.task_id,
        "site": inp.site,
        "captured_at": inp.captured_at,
        "routes": [
            {"skill": d.skill, "reason": d.reason, "tier": d.tier,
             "requires_cloud_auth": d.requires_cloud_auth}
            for d in decisions
        ],
        "source_skills": [d.skill for d in decisions],
        "findings": normalized,
        # partial = 存在显式标注不确定的条目；裁剪必须回报，不得静默
        "partial": any(item["uncertain"] for item in normalized),
        # 免责措辞的**单一来源**是 inspection-report/references/output-schema.md §4，
        # 与 render_markdown.DISCLAIMER 逐字一致。此处必须逐字照抄——差一个字符
        # render_footer 的等值判重就会失效，页脚会打印两行近义声明。
        "disclaimers": [
            "本报告由 AI 辅助生成，结论基于图像证据自动判定，需经人工复核确认。"
            "本报告不作为处罚、停机或联锁动作的唯一依据。"
        ],
    }
