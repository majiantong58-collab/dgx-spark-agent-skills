"""分级升级判据与预算护栏。

策略见 ../references/escalation-policy.md。
核心目标：本地兜底率 > 90%，单帧图像默认不送 Tier 2。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 阈值是可配置常量，不是魔法数字——改这里必须同步改 hazard-taxonomy.md 与 evals
# 本模块是分级阈值的**唯一定义处**（单一来源）：子技能脚本只引用，不得重复写同一字面量
ACCEPT_CONFIDENCE = 0.75
REVIEW_CONFIDENCE = 0.40
GAUGE_ACCEPT_CONFIDENCE = 0.85
UNCERTAIN_CONFIDENCE = 0.50
# gauge-reading 的 Tier 1 复核下界（SKILL.md 主流程第 6 步的 `0.5 ≤ conf < 0.85`）
# 与 UNCERTAIN_CONFIDENCE 是同一个阈值，用别名而非第二个字面量，避免两处漂移
GAUGE_REVIEW_CONFIDENCE = UNCERTAIN_CONFIDENCE

# 单次巡检任务的 Tier 2 调用上限（保守默认）
MAX_TIER2_CALLS_PER_TASK = 3
# 同一子技能连续失败上限
MAX_RETRIES_PER_SKILL = 2


@dataclass(frozen=True)
class BudgetState:
    """一次任务的预算状态。"""

    tier2_calls: int = 0
    retries: dict[str, int] | None = None
    wall_clock_ms: int = 0

    @property
    def tier2_exhausted(self) -> bool:
        """Tier 2 预算是否已耗尽。"""
        return self.tier2_calls >= MAX_TIER2_CALLS_PER_TASK


def next_tier(current: int, confidence: float, *, has_conflict: bool = False) -> int:
    """按升级判据给出下一层级，保证**不越级**。

    Args:
        current: 当前层级（0/1/2）。
        confidence: 当前结果的置信度。
        has_conflict: 是否出现 ≥3 个互相冲突的候选。

    Returns:
        下一层级；与 current 相同表示留在原层级。

    实现依据 escalation-policy.md §2（**不越级**，每次最多 +1）：
      - Tier 0：`conf >= ACCEPT_CONFIDENCE` 视为「高置信命中，单目标」→ 留在 0；
        否则 → 1。注：policy 的数值判据只写了 `0.40 <= conf < 0.75` 这一段，
        `conf < 0.40` 未被显式覆盖，此处按 §4「Tier 0 失败 → 升 Tier 1」外推，
        并以层级定义表「Tier 0 = 高置信命中」为据。**此段为外推，待裁决**。
      - Tier 1：`has_conflict` → 2（policy 明文「同一帧 ≥3 冲突候选 → Tier 1 → 2」）；
        `conf < UNCERTAIN_CONFIDENCE` → 留在 1（policy 明文「输出 uncertain，**不升 Tier 2**」）；
        其余（含 0.5–0.75 未定义区间）→ 留在 1。
        ⚠️ 当「低置信」与「冲突」同时成立时，policy 未规定优先级，此处取**冲突优先**
        （冲突是明文列出的 Tier 1→2 触发条件，低置信只规定「不升」而非「禁止升级」）。
        **此优先级为外推，待裁决**。
      - Tier 2：终态，返回 2。

    未覆盖的触发条件：「需要自然语言描述而 Tier 0 只给标签」在 policy 中列为
    Tier 0→1 的独立触发条件，但本函数签名无对应参数，调用方需自行判定后
    直接指定层级，或在后续版本加入 `needs_description` 形参。**待裁决**。
    """
    if current >= 2:
        return 2
    if current <= 0:
        return 0 if confidence >= ACCEPT_CONFIDENCE else 1
    # current == 1
    if has_conflict:
        return 2
    if confidence < UNCERTAIN_CONFIDENCE:
        return 1
    return 1


def should_escalate_to_cloud(
    current: int, confidence: float, budget: BudgetState, *, cloud_authorized: bool
) -> bool:
    """判定是否允许升到 Tier 2。

    必须**同时**满足：已授权、预算未耗尽、且触发条件成立。
    Tier 1 复核后仍低置信 → 输出 uncertain，**不升 Tier 2**。

    Returns:
        True 表示允许升级；False 表示回落本地并可能返回 partial。

    本函数是**闸门**，不是触发条件探测器。policy 的 Tier 2 触发条件是
    「同一帧 ≥3 个互相冲突的候选」与「需要成文报告措辞」，二者都无法从
    本函数签名（只有 current / confidence / budget）推导——**签名与 policy
    之间存在缺口，待裁决**。因此这里只实现三个可判定的闸门，并要求调用方
    在**已经认定触发条件成立**的前提下调用：

      1. `cloud_authorized`——未授权一律 False（policy §3 硬约束）
      2. `not budget.tier2_exhausted`——超预算 False，返回 partial 不静默降级
      3. `current >= 1`——**不越级**，Tier 0 不能直跳 2
      4. `confidence >= UNCERTAIN_CONFIDENCE`——policy 明文：Tier 1 复核后
         仍低置信 → uncertain，**不升 Tier 2**（避免为无结论付费）
    """
    if not cloud_authorized:
        return False
    if budget.tier2_exhausted:
        return False
    if current < 1:
        return False
    return confidence >= UNCERTAIN_CONFIDENCE


def record_failure(state: BudgetState, skill: str) -> BudgetState:
    """记录一次失败，返回新的预算状态（不可变，不修改入参）。

    上限见 MAX_RETRIES_PER_SKILL（policy §4「同一子技能连续失败 2 次 → 停止重试」）。
    调用方用 `retries[skill] >= MAX_RETRIES_PER_SKILL` 判定是否停止重试。

    ⚠️ policy 说的是「**连续**失败」，但本模块没有 `record_success`，
    BudgetState 也无「上次结果」字段，因此**无法实现成功的重置语义**——
    当前实现是累计计数，不是连续计数。**待裁决**：是补一个重置入口，
    还是接受累计语义并回写 policy 措辞。
    """
    retries = dict(state.retries or {})
    retries[skill] = retries.get(skill, 0) + 1
    return BudgetState(tier2_calls=state.tier2_calls, retries=retries,
                       wall_clock_ms=state.wall_clock_ms)


def summarize_budget(state: BudgetState) -> dict[str, Any]:
    """输出本地兜底率、Tier 2 调用数等指标，供评测与遥测使用。

    ⚠️ 「本地兜底率」**无法从 BudgetState 算出**——该结构只有 tier2_calls /
    retries / wall_clock_ms，没有总任务数与本地解决数。policy 的目标是
    「本地兜底率 > 90%」，要算它必须在调用方累计 `tasks_total` 与
    `tasks_resolved_locally`。此处只输出可导出量，并显式置
    `local_fallback_rate: None`，**不臆造数值**。**待裁决**。
    """
    retries = dict(state.retries or {})
    return {
        "tier2_calls": state.tier2_calls,
        "tier2_budget_remaining": max(0, MAX_TIER2_CALLS_PER_TASK - state.tier2_calls),
        "tier2_exhausted": state.tier2_exhausted,
        "retries": retries,
        "exhausted_skills": sorted(s for s, n in retries.items() if n >= MAX_RETRIES_PER_SKILL),
        "wall_clock_ms": state.wall_clock_ms,
        # 需要调用方提供 tasks_total / tasks_resolved_locally 才能计算，见 docstring
        "local_fallback_rate": None,
    }
