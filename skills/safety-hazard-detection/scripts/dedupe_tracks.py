"""多帧去重与合并。

同一物理目标在连续帧中重复命中时只保留一条结论，避免报告被刷屏。

判定「同一条违规」的判据（可解释、可复核）：

1. **同一 hazard 标签**——`code` / `hazard_code` 完全相同；
2. **同一主体**——两条 bbox 的 IoU ≥ `IOU_THRESHOLD`。
   bbox 取自条目的 `bbox` 字段；findings 契约（routing-table.md §3）**不单列该字段**，
   坐标只存在于 `evidence_ref`（`frame_0001#bbox[x1, y1, x2, y2]`）里，故缺字段时从
   `evidence_ref` 反解——否则所有条目都会退化成 `[0, 0, 0, 0]` 而被**错误地并成一条**。
   bbox 退化到零面积时 IoU 无定义，退化为「两个 bbox 完全相等才算同一主体」。

比对锚点是该目标**最近一次命中**的 bbox（`last_bbox`）而非首个命中帧的 bbox：
同一目标在相邻帧间只做小幅位移，锚定最近帧才不会因累计漂移而把一条轨迹拆成多条。
这只在输入是**同一段连续监控**时成立——跨点位 / 跨时段的片段应分次调用。

被合并的重复条目**不丢弃**：完整保留在幸存条目的 `merged_from` 里并逐条标记
`status="duplicate"`，幸存条目自身标记 `status="merged"`（未合并过则为 `"unique"`）。
因此 `len(merge_detections(...))` 就是**唯一违规数**，可直接用于报告计数。

本模块不修改入参：输出条目全部为新构造的 dict。
"""

from __future__ import annotations

import re
from typing import Any, Sequence

# 判为同一主体的 IoU 阈值。本模块是该阈值的**唯一定义处**——调用方通过
# merge_detections(iou_threshold=...) 注入，其它模块不得重复写同一字面量
# （与 inspection-orchestrator/scripts/tier_budget.py 的单一来源约定一致）。
IOU_THRESHOLD = 0.5

# 两个来源都拿不到坐标时的占位框：此时无法区分主体，退化为「同 code 即同一目标」
_FALLBACK_BBOX = (0, 0, 0, 0)

# findings 契约把坐标编在 evidence_ref 里（detect_via_cloud 就是这么写的），缺 bbox 字段时据此反解
_BBOX_IN_REF = re.compile(r"#bbox\[\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\]")


def _get(item: Any, name: str, default: Any = None) -> Any:
    """同时兼容 dict 条目（跨技能契约）与 `Detection` 数据类条目。"""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _code_of(item: Any) -> str:
    """`Detection` 用 `hazard_code`，findings 契约用 `code`。"""
    return str(_get(item, "hazard_code") or _get(item, "code") or "").strip()


def _bbox_of(item: Any) -> tuple[int, int, int, int]:
    """取条目 bbox：优先 `bbox` 字段，其次从 `evidence_ref` 的 `#bbox[...]` 反解。"""
    raw = _get(item, "bbox")
    if raw:
        values = [int(v) for v in raw][:4]
        return tuple(values + [0] * (4 - len(values)))  # type: ignore[return-value]
    ref = _get(item, "evidence_ref")
    if isinstance(ref, str):
        m = _BBOX_IN_REF.search(ref)
        if m:
            return tuple(int(g) for g in m.groups())  # type: ignore[return-value]
    return _FALLBACK_BBOX


def _frame_label(item: Any, frame_index: int) -> str:
    """优先沿用条目自带的帧号（`evidence_ref` 的 `#` 前缀），否则按顺序编号。"""
    ref = _get(item, "evidence_ref")
    if isinstance(ref, str) and "#" in ref:
        return ref.split("#", 1)[0]
    return f"frame_{frame_index:04d}"


def iou(a: Sequence[int], b: Sequence[int]) -> float:
    """计算两个 bbox 的交并比。

    零面积 bbox（`x1 == x2` 或 `y1 == y2`）无法用面积比比较：两个 bbox
    **完全相同**时返回 1.0，否则返回 0.0。
    """
    ax1, ay1, ax2, ay2 = (int(v) for v in a)
    bx1, by1, bx2, by2 = (int(v) for v in b)
    inter = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    union = max(0, ax2 - ax1) * max(0, ay2 - ay1) + max(0, bx2 - bx1) * max(0, by2 - by1) - inter
    if union <= 0:
        return 1.0 if (ax1, ay1, ax2, ay2) == (bx1, by1, bx2, by2) else 0.0
    return inter / union


def merge_detections(
    frames: Sequence[Sequence[Any]],
    *,
    iou_threshold: float = IOU_THRESHOLD,
    cross_frame: bool = True,
) -> list[dict[str, Any]]:
    """跨帧合并同一目标，保留最高置信度并记录命中的帧号。

    Args:
        frames: 按时间排序的、每帧的检测结果列表。
        iou_threshold: 判为同一目标的 IoU 阈值。
        cross_frame: True 时跨帧合并；False 时仅帧内 NMS。

    Returns:
        去重后的结论列表——**一条 = 一条唯一违规**。每条含 `evidence_ref`
        （首个命中帧 + 该帧 bbox）、`frames` / `frame_count`（命中帧）、
        `hit_count`（并入的原始条目数）、`merged_from`（重复条目明细，不丢弃）。
    """
    out: list[dict[str, Any]] = []
    for frame_index, frame in enumerate(frames):
        pool = out if cross_frame else []  # 仅帧内 NMS 时，比对池每帧重置
        for item in frame:
            code = _code_of(item)
            bbox = _bbox_of(item)
            confidence = float(_get(item, "confidence", 0.0) or 0.0)
            frame_label = _frame_label(item, frame_index)
            # code 为空表示无法判定标签，一律不合并（不猜）
            target = next(
                (
                    m
                    for m in pool
                    if code
                    and m["code"] == code
                    and iou(m["last_bbox"], bbox) >= iou_threshold
                ),
                None,
            )
            if target is None:
                survivor = {
                    "kind": _get(item, "kind", "hazard"),
                    "code": code,
                    "label": _get(item, "label", code),
                    "severity": _get(item, "severity"),
                    "confidence": confidence,
                    "bbox": list(bbox),  # 首个命中帧的 bbox，与 evidence_ref 一致
                    "last_bbox": list(bbox),  # 最近一次命中，仅用于下一步比对
                    "source": _get(item, "source"),
                    "evidence": _get(item, "evidence", ""),
                    "evidence_ref": f"{frame_label}#bbox{list(bbox)}",
                    "uncertain": bool(_get(item, "uncertain", False)),
                    "requires_human_review": bool(
                        _get(item, "requires_human_review", False)
                    ),
                    "frames": [frame_label],
                    "frame_count": 1,
                    "hit_count": 1,
                    "status": "unique",
                    "merged_from": [],
                }
                # tier 原样透传；入参没有该键时不写键——写成 None 会顶掉调用方的
                # setdefault("tier", 0)，把 Tier 2 条目错标成 Tier 0。
                if _get(item, "tier") is not None:
                    survivor["tier"] = _get(item, "tier")
                pool.append(survivor)
                continue
            # 命中同一目标：不新建条目，把这次命中并入幸存条目并留痕
            target["merged_from"].append(
                {
                    "frame": frame_label,
                    "bbox": list(bbox),
                    "confidence": confidence,
                    "status": "duplicate",
                }
            )
            target["hit_count"] += 1
            target["status"] = "merged"
            target["last_bbox"] = list(bbox)
            if frame_label not in target["frames"]:
                target["frames"].append(frame_label)
                target["frame_count"] += 1
            target["confidence"] = max(target["confidence"], confidence)
            target["uncertain"] = target["uncertain"] or bool(_get(item, "uncertain", False))
            target["requires_human_review"] = target["requires_human_review"] or bool(
                _get(item, "requires_human_review", False)
            )
        if not cross_frame:
            out.extend(pool)
    return out


def mark_single_frame_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """单帧孤立证据标 `uncertain`（见 hazard-taxonomy.md §3）。

    返回新列表，不修改入参。

    本函数只置位 `uncertain`（§3 要求的 severity 降一档由
    `detect_hazards.apply_taxonomy` 统一执行，本模块不复制第二份降档表）。
    """
    marked: list[dict[str, Any]] = []
    for item in items:
        new = dict(item)
        if int(new.get("frame_count", len(new.get("frames") or []) or 1)) <= 1:
            new["uncertain"] = True
            new["uncertain_reason"] = "单帧孤立证据（跨帧不复现）"
            new["requires_human_review"] = True
        marked.append(new)
    return marked
