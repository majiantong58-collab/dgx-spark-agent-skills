"""读数三重复核：量程合理性 / 指针-数字一致性 / 多帧一致性。

规则见 ../references/reading-rules.md §1。
校验不通过时**降置信或判误读**，绝不静默放过。
"""

from __future__ import annotations

from typing import Any, Sequence

FS_TOLERANCE = 0.02  # 满量程的 2%
MULTI_FRAME_SPREAD = 0.01  # 满量程的 1%


def check_range(value: float, value_range: tuple[float, float]) -> bool:
    """量程合理性：R_min <= value <= R_max。不通过即判误读。"""
    raise NotImplementedError("A4 实现")


def check_needle_vs_digital(
    needle_value: float, digital_value: float, value_range: tuple[float, float]
) -> bool:
    """指针表若同时有数字标注，两者偏差须 < 2% FS。"""
    raise NotImplementedError("A4 实现")


def check_multi_frame(
    values: Sequence[float], value_range: tuple[float, float]
) -> tuple[float, bool]:
    """多帧一致性：极差 < 1% FS 时取中位数。

    Returns:
        (中位数, 是否一致)。不一致时调用方须标 `uncertain`。
    """
    raise NotImplementedError("A4 实现")


def finalize(reading: Any, checks: dict[str, bool]) -> Any:
    """按校验结果给出最终 confidence 与 uncertain 标记。

    任一项不通过 -> 降置信；量程校验不通过 -> confidence = 0。
    返回新的读数对象，不修改入参。
    """
    raise NotImplementedError("A4 实现")


def judge_out_of_range(
    value: float,
    threshold: float | None,
    *,
    confidence: float,
    uncertain: bool,
) -> bool | None:
    """越限判定——阈值未知时返回 None，并写 `阈值未知，未判定`。

    阈值只能由用户或设备台账给出，**不得自定义**。
    仅当非 uncertain 且 confidence >= 0.85 时才可能为 True。
    """
    raise NotImplementedError("A4 实现")
