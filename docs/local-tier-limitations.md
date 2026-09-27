# 本地三层（Tier 0 / 0.5 / 1）局限与已知缺口

> 本文供并入 `docs/DELIVERY.md` 的「局限」节。所有条目均为实测得到，不是推测。
> 生成依据：`skills/safety-hazard-detection/scripts/local_tier_pipeline.py` 在三张实拍照片上的运行结果。

## 1. Tier 0.5（颜色/几何启发式）的能力边界：能确认「有」，不能断言「无」

**这是安全设计约束，不是性能问题。**

启发式看不到蓝色，只能说明它没看见蓝色——**它本来就看不见白色着装**。
实测白色掩膜覆盖率 11.7%、17 个噪声连通块（墙面、机柜、反光全在其中），
对白色人员的**召回为 0**。因此「没找到」不构成该人员未佩戴 PPE 的证据。

在安全场景里**假指控比漏检更危险**：漏检只损失一次检查机会，
假指控会冤枉一个穿戴合规的人，并摧毁对系统的信任。

**实现约束**：Tier 0.5 只要没有正面证据，`severity` 一律为 `uncertain`，
**绝不允许**输出 `warning` / `critical`。除非 Tier 1 确认。
（实测：修复前 photo1 有 3 人被误标 `warning`，修复后全为 `uncertain`；
整轮 7 条 findings 中 `warning`/`critical` 出现 **0** 次。）

**召回率必须随结论一起给**：photo1 上启发式对 6 人中 3 人有正面证据，**召回 3/6**。

## 2. `next_tier` 无法承载「需要自然语言描述」这一触发条件

`escalation-policy.md` §2 将「需要自然语言描述而 Tier 0 只给标签」列为
Tier 0 → 1 的独立触发条件，但 `next_tier(current, confidence, *, has_conflict)`
签名中没有对应形参。**policy 有定义、接口未承载。** 调用方需自行判定后直接指定层级。

## 3. `should_escalate_to_cloud` 无法判定 Tier 1 → 2 的触发条件

policy 的 Tier 2 触发条件是「同一帧 ≥3 个互相冲突的候选」与「需要成文报告措辞」，
二者都无法从该函数签名（只有 `current` / `confidence` / `budget`）推导。
**policy 有定义、接口未承载。**

当前实现是**闸门**而非触发器，只判定三条可判定项：
`cloud_authorized`、预算未耗尽、`current >= 1`（不越级）且 `confidence >= UNCERTAIN_CONFIDENCE`
（policy 明文：Tier 1 复核后仍低置信 → uncertain，不升 Tier 2）。
调用方必须在**已认定触发条件成立**的前提下调用本函数。**未臆造规则。**

## 4. `record_failure` 是累计计数，不是 policy 所说的「连续」失败

policy §4 写的是「同一子技能**连续**失败 2 次 → 停止重试」。
本模块没有 `record_success`，`BudgetState` 也无「上次结果」字段，
**无法实现成功的重置语义**。当前为累计计数。**实现与 policy 措辞存在偏差，已知悉。**

## 5. `summarize_budget` 无法计算「本地兜底率」

该指标是 policy 的核心目标（> 90%），但 `BudgetState` 只有
`tier2_calls` / `retries` / `wall_clock_ms`，**没有总任务数与本地解决数**。
因此 `local_fallback_rate` 输出 `None`，**不臆造数值**。
需调用方累计 `tasks_total` 与 `tasks_resolved_locally` 后才能计算。

## 6. 人数不可宣称精确

photo1 上 **YOLO 报 6 人、Tier 1 VLM 报 5 人**，两者不一致，**未逐像素人工复核，无法裁决谁对**
（YOLO 第 6 个框置信度仅 0.301，本就偏低）。
**演示时以 VLM 为准，但不得宣称「精确计数」。** 与报告模板既有的免责声明同性质。

## 7. Tier 0 不认识任何 PPE 类别

COCO 版 yolo11n **没有「防尘帽 / 防静电服」类别**（也没有「安全帽 / 反光衣」）。
Tier 0 的职责仅为**人形定位与计数**，不作为 PPE 判定依据。
另外实测场景为**电子厂无尘车间**（蓝色防尘帽 + 蓝色防静电服），
与 `escalation-policy.md` 原有的工地假设（安全帽 / 反光衣）**不一致**，待场景确认后统一。
