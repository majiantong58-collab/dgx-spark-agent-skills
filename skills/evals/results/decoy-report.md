# 对照评测结果

- 模型：`step-5-preview`　日期：2026-09-27　运行次数：[3]　聚合：majority（comparison-design.md §2 取多数票）

## 主表（§3）

| # | 指标 | A 臂 | B 臂 | C 臂 | D 臂 |
|---|---|---|---|---|---|
| 1 | 负向误触发率 FTR | 0.000 | 0.000 | 0.000 | 0.222 |
| 2 | 负向正确拒绝率 | 1.000 | 1.000 | 1.000 | 0.778 |
| 3 | 触发准确率 | 0.444 | 0.667 | 0.667 | 0.778 |
| 4 | 路由序列精确匹配率 | 0.500 | 0.750 | 0.750 | 0.500 |
| 5 | 结论正确率 | — | — | — | — |
| 6 | 读数 MAE（满量程归一） | — | — | — | — |
| 7 | **编造量程数** | 0 | 0 | 0 | 0 |
| 8 | **幻觉项数** | 16 | 3 | 3 | 0 |
| 9 | **边界合规率** | — | — | — | — |
| 10 | 本地兜底率 | — | — | — | — |
| 11 | Tier 2 调用次数/任务 | 1.000 | 1.000 | 1.000 | 1.000 |
| 12 | P95 端到端延迟 | 43500.000 | 18797.000 | 22014.000 | 28813.000 |
| 13 | 触发稳定性 | 0.889 | 0.963 | 0.926 | 0.963 |

> 表中 `n/a` 的指标（6、9、10）属读数层，**明确不在本次测量范围内**，见文末「本次测量范围」。

## 诊断指标（不属于 §3 的 13 项，单列；这是「skill 到底有没有用」最直白的证据）

| 诊断项 | A 臂 | B 臂 | C 臂 | D 臂 |
|---|---|---|---|---|
| 指标 1 FTR（**本技能口径**） | 0.000 | 0.000 | 0.000 | 0.222 |
| 广义触发率（**任何技能**被误调用） | 0.556 | 0.333 | 0.333 | 0.222 |
| 幽灵技能调用次数（点了不存在的技能名） | 18 | 0 | 0 | 0 |
- A 臂幻觉出的技能名：`data_analysis`、`excel_analysis`、`image_analysis`、`leak_detection`、`ocr`、`pressure_gauge_reading`、`report_generation`、`safety_helmet_detection`

> 为什么两个口径都要看：本技能口径下，**模型点了别的技能（含不存在的技能名）不算误触发**。
> 若只报 FTR，一个「见任务就触发、乱点名」的臂会与「安静拒绝」的臂得到同样的 0.000。

### 硬门禁指标（单列，不参与加权平均）

- **fabricated_range_count**：A=PASS；B=PASS；C=PASS；D=PASS
- **hallucinated_items**：A=FAIL；B=FAIL；C=FAIL；D=PASS
- **boundary_compliance_rate**：A=N/A（本次不适用）；B=N/A（本次不适用）；C=N/A（本次不适用）；D=N/A（本次不适用）

### 有效样本 / 总样本

- A 臂：用例 9/9，负例 9/9，调用失败 0，响应无法解析 0，经重试成功 0
- B 臂：用例 9/9，负例 9/9，调用失败 0，响应无法解析 0，经重试成功 0
- C 臂：用例 9/9，负例 9/9，调用失败 0，响应无法解析 0，经重试成功 0
- D 臂：用例 9/9，负例 9/9，调用失败 0，响应无法解析 1，经重试成功 0

## 差值表（§4.2）

| # | 指标 | Δ1 = B − A | 方向判读 | Δ2 = FTR(C) − FTR(B) |
|---|---|---|---|---|
| 1 | 负向误触发率 FTR | 0.000 | same | **+0.000** |
| 2 | 负向正确拒绝率 | 0.000 | same |  |
| 3 | 触发准确率 | 0.222 | improved |  |
| 4 | 路由序列精确匹配率 | 0.250 | improved |  |
| 5 | 结论正确率 | — | n/a |  |
| 6 | 读数 MAE（满量程归一） | — | n/a |  |
| 7 | 编造量程数 | 0 | same |  |
| 8 | 幻觉项数 | -13 | improved |  |
| 9 | 边界合规率 | — | n/a |  |
| 10 | 本地兜底率 | — | n/a |  |
| 11 | Tier 2 调用次数/任务 | 0.000 | same |  |
| 12 | P95 端到端延迟 | -24703.000 | improved |  |
| 13 | 触发稳定性 | 0.074 | improved |  |

- **Δ2 = FTR(C) − FTR(B) = 0.000**（**本技能口径**，与主表指标 1 同源；FTR 越低越好，正值 = Not-for 段净收益）
- Δ2 有效样本：负例 9/9（满足）
- 可靠性判定：**可靠** —— B/C 两臂负例样本完整、无失败、无解析失败，且有效负例数一致

## 敏感性：换聚合口径 Δ2 还成立吗

主结论采用 **majority**（comparison-design.md §2「取多数票」）。下表每一行都写明**口径、定义与分母**，与主表指标 1 的关系是逐位相等（同一份逐次运行判定）。

**表 A — 本技能口径（= 主表指标 1 的口径；分母 = 有效负例 9 条）**
：只算「该用例 `skill` 所指技能」被误调用，逐次运行判定后取票。

| 聚合口径 | FTR(B) | FTR(C) | Δ2 |
|---|---|---|---|
| majority（主结论） | 0.000 | 0.000 | 0.000 |
| any（任一次误调用即算） | 0.000 | 0.000 | 0.000 |
| all（每次都误调用才算） | 0.000 | 0.000 | 0.000 |

- 三种口径下 Δ2 均为 0，**本次样本未观测到差异**（既不支持也不否定 Not-for 段的作用）。

**表 B — 广义口径（诊断；分母同为有效负例 9 条）**：任何技能被调用即算误触发（含点名了本项目不存在的技能）。**与表 A 不可混用、不可相减。**

| 聚合口径 | FTR(B) | FTR(C) | Δ2 |
|---|---|---|---|
| majority（主结论） | 0.333 | 0.333 | 0.000 |
| any（任一次误调用即算） | 0.333 | 0.444 | 0.111 |
| all（每次都误调用才算） | 0.333 | 0.333 | 0.000 |

## NVIDIA 语汇双轨表述

- decoy 用例数：9（expect_trigger=false 的用例（decoy = 不该被调用的诱饵任务））
- B→C 的选择压力下 routing 变化：0.000
- 与本评测 Skill Lift 轴的对应关系：with-skill vs without-skill —— 本评测里对应 Δ1 = B − A（A = 不加载 skill）
- 可否等同：**不可**
- 换算说明：Δ2 与 NVIDIA 语汇的 `Skill Lift` **不是同一轴**。Skill Lift 对照的是「加载 skill / 不加载 skill」，本评测中对应 Δ1 = B − A；Δ2 是**同一个 skill 内部**的description 变体对照（B 含 Not-for 段 vs C 删去 Not-for 段），度量的是负向条件对routing 的影响，即「选择压力下的 routing 变化」。两者不可等同、不可相加，也不能把 Δ2 当作 Skill Lift 报出去。

## 失败模式归类（§4.4）

| 模式 | A 臂 | B 臂 | C 臂 | D 臂 |
|---|---|---|---|---|
| false_trigger | 5 | 3 | 3 | 2 |
| missed_trigger | 0 | 0 | 0 | 0 |
| wrong_conclusion | 1 | 1 | 1 | 2 |
| boundary_breach | 本次不适用 | 本次不适用 | 本次不适用 | 本次不适用 |
| silent_degradation | 0 | 0 | 0 | 1 |
| hallucination | 5 | 3 | 3 | 2 |

## 逐用例附录（§4.3）

`广义触发` 与 `本技能误触发` 两列并存，是为了让读者能把附录的失败模式标注与主表指标 1（本技能口径）对上——两者口径不同，数值本就可以不同。

| 用例 | 臂 | 期望触发 | 广义触发 | 本技能误触发 | 稳定性 | 有效/总 | 命中 | 失败模式 |
|---|---|---|---|---|---|---|---|---|
| gauge-decoy-001 | A | False | True | False | 1.000 | 3/3 | 否 | false_trigger |
| gauge-decoy-002 | A | False | True | False | 1.000 | 3/3 | 否 | false_trigger |
| hazard-decoy-001 | A | False | True | False | 1.000 | 3/3 | 否 | false_trigger |
| hazard-decoy-002 | A | False | True | False | 0.667 | 3/3 | 否 | false_trigger |
| report-decoy-001 | A | False | False | False | 1.000 | 3/3 | 是 | — |
| orch-decoy-001 | A | False | True | False | 0.667 | 3/3 | 否 | false_trigger |
| orch-decoy-002 | A | False | False | False | 1.000 | 3/3 | 是 | — |
| orch-decoy-003 | A | False | False | False | 0.667 | 3/3 | 否 | wrong_conclusion |
| orch-decoy-004 | A | False | False | False | 1.000 | 3/3 | 是 | — |
| gauge-decoy-001 | B | False | True | False | 1.000 | 3/3 | 否 | false_trigger |
| gauge-decoy-002 | B | False | False | False | 1.000 | 3/3 | 是 | — |
| hazard-decoy-001 | B | False | False | False | 1.000 | 3/3 | 否 | wrong_conclusion |
| hazard-decoy-002 | B | False | False | False | 1.000 | 3/3 | 是 | — |
| report-decoy-001 | B | False | False | False | 1.000 | 3/3 | 是 | — |
| orch-decoy-001 | B | False | True | False | 0.667 | 3/3 | 否 | false_trigger |
| orch-decoy-002 | B | False | False | False | 1.000 | 3/3 | 是 | — |
| orch-decoy-003 | B | False | True | False | 1.000 | 3/3 | 否 | false_trigger |
| orch-decoy-004 | B | False | False | False | 1.000 | 3/3 | 是 | — |
| gauge-decoy-001 | C | False | True | False | 1.000 | 3/3 | 否 | false_trigger |
| gauge-decoy-002 | C | False | False | False | 1.000 | 3/3 | 是 | — |
| hazard-decoy-001 | C | False | False | False | 0.667 | 3/3 | 否 | wrong_conclusion |
| hazard-decoy-002 | C | False | False | False | 1.000 | 3/3 | 是 | — |
| report-decoy-001 | C | False | False | False | 1.000 | 3/3 | 是 | — |
| orch-decoy-001 | C | False | True | False | 0.667 | 3/3 | 否 | false_trigger |
| orch-decoy-002 | C | False | False | False | 1.000 | 3/3 | 是 | — |
| orch-decoy-003 | C | False | True | False | 1.000 | 3/3 | 否 | false_trigger |
| orch-decoy-004 | C | False | False | False | 1.000 | 3/3 | 是 | — |
| gauge-decoy-001 | D | False | False | False | 1.000 | 3/3 | 否 | wrong_conclusion |
| gauge-decoy-002 | D | False | False | False | 1.000 | 3/3 | 是 | — |
| hazard-decoy-001 | D | False | False | False | 1.000 | 3/3 | 否 | wrong_conclusion |
| hazard-decoy-002 | D | False | False | False | 1.000 | 3/3 | 是 | — |
| report-decoy-001 | D | False | False | False | 1.000 | 3/3 | 是 | — |
| orch-decoy-001 | D | False | True | True | 0.667 | 3/3 | 否 | false_trigger |
| orch-decoy-002 | D | False | False | False | 1.000 | 3/3 | 是 | — |
| orch-decoy-003 | D | False | True | True | 1.000 | 3/3 | 否 | false_trigger |
| orch-decoy-004 | D | False | False | False | 1.000 | 3/3 | 是 | — |

## 结论（§4.5）

一句话结论：从 description 删除 `不适用于：` 段后，负向误触发率从 0.000 变为 0.000，Δ2 = +0.000（+0.0 个百分点）——正值即 Not-for 段的净收益。

## 本次测量范围

本实验为**纯文本消融**（A5 不发图），按设计只测**触发/路由层**：

- **本次测量**：指标 1、2、3、4、5、7、8、11、12、13
- **明确不在本次测量范围内**：
  - 指标 6 读数 MAE（满量程归一）：需期望读数与满量程才能算，属读数层
  - 指标 9 边界合规率：需免责声明 / requires_human_review / uncertain 字段，属读数层
  - 指标 10 本地兜底率：需 Tier 0/1 链路，本执行器只用云端单次调用
- 硬门禁中涉及指标 9 的整条标注「本次不适用」——**不是通过，也不是失败**。
- 未扩 `USER_TEMPLATE` / 输出契约来强行凑这些指标（降级优先，非本次核心）。

## 口径备注

- 本次只测**触发/路由层**指标（1–5、7、8、11–13）。指标 6、9、10 属读数层，需要图像输入与更宽的输出契约，**明确不在本次测量范围内**（不是「测不出来」）。
- 口径差异（务必对照）：指标 1 FTR 用 metrics.json 规定的**本技能口径**（只算「该用例 skill 所指技能」被误调用），故负例触发但点名了别的技能时 FTR 仍记 0；`negative_any_trigger_rate` 为**广义口径**（任何技能被调用即算）。两者会显著不同，附录里的 `false_trigger` 标注对应**广义口径**——FTR 与其并存时以此说明调和。
- 指标 4 已按定义收窄为「编排层用例」（`skill == inspection-orchestrator` 且带 `expect_route`），本臂纳入分母 0 条时不予放宽、如实标注分母不足。
- 契约局限（未修）：`USER_TEMPLATE` 规定拒绝时输出 `skills: []`，故无法表达「拒绝本技能、但点名另一个技能」的意图——2026-09-27 移除了 6 条负例的 `expect_route`字段（gauge-neg-001 / orch-neg-001 / report-neg-001,002 / hazard-neg-002,003），`expect` 散文意图原样保留；本次未加 `suggested_skills` 字段，因为改契约即改 prompt，会让已产出与将产出的数据不可比。
- 指标 8 为**下界**口径：只统计「应当不触发却仍产出 findings」的条目数；正向用例的输入回溯需人工或模型复核。
- 指标 7 的依据：用例带 `expect_value` = 素材给了量程；不带而输出里出现 range/value 即算编造。
- 聚合规则：§2 规定的多数票（triggered = 触发次数*2 >= 有效运行数）；方差以逐用例 trigger_rate 与 stability 记录，并在「敏感性」一节并列三种口径。
- **1 次有效运行的响应无法解析为 JSON**，已按「未触发」计入，FTR 因此偏乐观 —— 看数前先核对这个计数。
- 主指标可靠性：**不可靠**（负例上有 1 次响应无法解析（按未触发计入，FTR 偏乐观））。
---

## 预注册假设的判定（H-decoy）

本集于 **2026-09-27 02:50** 落盘，当时全量实验正在运行、**未看到任何 Δ2**（见 `cases-decoy-README.md` §0）。
假设原文（冻结，不得修改）：

> 若 Not-for 段具有净收益，则本集上的 Δ2 应显著大于既有集上的 Δ2。
> **若本集上的 Δ2 同样为 0，则负向条件（Not-for 段）的运行时收益在我们的场景下不成立。**

### 判定：**假设不成立**（触发否定分支）

| 口径 | 本集 Δ2（有效负例 9/9，可靠） | 既有集 Δ2（有效负例 16/16，可靠） | 预注册要求 | 结论 |
|---|---|---|---|---|
| 本技能口径（指标 1） | **+0.000** | +0.000 | 显著大于既有集 | **不满足 → 不成立** |
| 广义口径（诊断） | **+0.000**（majority） | +0.125（majority） | — | 亦为 0 |

三种聚合口径（majority / any / all）下，本集**本技能口径 Δ2 全为 0.000**（表 A）。
广义口径下仅 `any` 一行为 +0.111，来自**单条用例的单次运行**（见下），不构成效应。

**结论：即便在专门构造、最有利于负向条件生效的 9 条高区分度同族干扰上，
删除 description 的 `不适用于：` 段也不改变误触发率。按预注册措辞，Δ2 = 0 是强否定结果。**

### 9 条用例原始值（3 次运行全列，供读者自行核算）

| 用例 | B 臂 triggered×3 | B 臂 route | C 臂 triggered×3 | C 臂 route | 差异 |
|---|---|---|---|---|---|
| gauge-decoy-001 | [True, True, True] | [('safety-hazard-detection',)] | [True, True, True] | [('safety-hazard-detection',)] |  |
| gauge-decoy-002 | [False, False, False] | [()] | [False, False, False] | [()] |  |
| hazard-decoy-001 | [False, False, False] | [()] | [False, True, False] | [(), ('gauge-reading',)] | **← B/C 不同** |
| hazard-decoy-002 | [False, False, False] | [()] | [False, False, False] | [()] |  |
| report-decoy-001 | [False, False, False] | [()] | [False, False, False] | [()] |  |
| orch-decoy-001 | [True, True, True] | [('gauge-reading', 'safety-hazard-detection'), ('safety-hazard-detection', 'gauge-reading')] | [True, True, True] | [('gauge-reading', 'safety-hazard-detection'), ('safety-hazard-detection', 'gauge-reading')] |  |
| orch-decoy-002 | [False, False, False] | [()] | [False, False, False] | [()] |  |
| orch-decoy-003 | [True, True, True] | [('inspection-report',)] | [True, True, True] | [('inspection-report',)] |  |
| orch-decoy-004 | [False, False, False] | [()] | [False, False, False] | [()] |  |

**唯一差异**：`hazard-decoy-001`（应转 gauge-reading，不该调 safety-hazard-detection）
B 臂 3 次全未触发，C 臂 **3 次中有 1 次**触发并路由到 gauge-reading。
方向与假设一致（删掉 Not-for 段后 C 更差），但**量级是 27 次运行中的 1 次**，处于噪声水平，
不足以支撑「显著大于」的判定。

## 口径限制（必须与结论同读）

1. **广义口径会把「正确转交他技能」计为误触发**。本集 4 条用例的 `expect_route` 声明了同族目标
   （如 `gauge-decoy-001` 正确行为是转 safety-hazard-detection），模型照做时 `call_skill=true`，
   广义口径记一次误触发，实际是**正确路由**。故广义率偏高，本技能口径不受影响。
2. **契约无法表达「拒绝本技能、点名另一技能」**：`USER_TEMPLATE` 规定拒绝即 `skills: []`。
   本集 4 条声明同族目标的用例因此**不可被机器判定为「路由正确」**——这是预注册时未预见的限制，
   本次**未修改任何用例或契约**，如实记录。
3. 本集为补充实验，**不替代主结果**（`cases-decoy-README.md` §4）。
