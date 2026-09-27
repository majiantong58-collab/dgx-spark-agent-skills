"""Tier 1 仪表读数：表盘定位 -> 指针/数字区域分割 -> 读数。

只做「表盘 -> 带单位的数」，不做隐患判定、不做趋势、不写报告。
量程未知时**必须中止并回问**，不得反推。见 ../references/reading-rules.md。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

GaugeType = Literal[
    "pressure", "temperature", "level", "flow", "current", "voltage", "valve"
]


@dataclass(frozen=True)
class GaugeReading:
    """单块表的读数结果（未做越限判定）。"""

    gauge_id: str
    gauge_type: GaugeType
    value: float | None
    unit: str
    range_: tuple[float, float] | None
    confidence: float
    uncertain: bool = False
    note: str = ""


def locate_dial(image: Any) -> list[tuple[int, int, int, int]]:
    """定位图像中的表盘区域。

    Returns:
        表盘 bbox 列表；多表场景按从左到右、从上到下排序，与用户给的表位编号对齐。
    """
    raise NotImplementedError("B2 实现")


def segment_needle(image: Any, dial_bbox: tuple[int, int, int, int]) -> dict[str, Any]:
    """分割指针与刻度区域，返回指针角度与刻度起止角。"""
    raise NotImplementedError("B2 实现")


def read_numeric(image: Any, region: tuple[int, int, int, int]) -> tuple[str | None, float]:
    """识别数字表读数（含小数点与缺笔画处理）。

    Returns:
        (数字串, 置信度)；数字串为 None 表示无法识别。
    """
    raise NotImplementedError("B2 实现")


def read_needle(
    needle: dict[str, Any],
    *,
    value_range: tuple[float, float] | None,
    unit: str | None,
) -> GaugeReading:
    """指针表读数：角度 -> 量程线性映射。

    量程或单位未知时**必须**返回 uncertain 结果并附 note 请求补充，
    绝不假设量程。

    Args:
        needle: `segment_needle` 的输出。
        value_range: 已知量程；None 表示未知。
        unit: 已知单位；None 表示未知。

    Returns:
        GaugeReading；`requires_human_review` 由上层恒置 True。
    """
    raise NotImplementedError("B2 实现")


def read_all(
    image: Any, *, gauge_ids: list[str], value_ranges: dict[str, tuple[float, float]]
) -> list[GaugeReading]:
    """批量读表。gauge_ids 与检测到的表盘数量不一致时拒绝出结果。"""
    raise NotImplementedError("B2 实现")
