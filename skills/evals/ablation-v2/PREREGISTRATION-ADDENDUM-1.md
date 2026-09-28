# 预注册 · 附注 1：新硬负例的触发词核验

> **落盘时间：2026-09-27 22:52 (+0800)**
> **写于复现门禁运行期间、主实验之前。§4 判读规则未改动，本条只补充事实。**

主实验开跑前，对 6 条新硬负例做了「是否真命中该技能核心触发词」的机械核验
（脚本：`.scratch/ablation-v2/verify_hard_negs.py`；判据：技能 `description` **正向段**
（`不适用于：` 之前的部分）里的核心词，是否出现在用例的 **`input` 行**里）。

**只看 `input` 行，不看 `assets`** —— 模型看到的是「任务：{input}」与「素材说明：{assets}」两行，
触发词必须落在**任务行**才算 near-miss；拿素材行凑命中是自欺。

| 用例 | 技能 | 任务行命中词 | 命中数 | 评价 |
|---|---|---|---|---|
| `hard-hazard-neg-001` | safety-hazard-detection | 防尘帽、洁净车间、车间 | 3 | 强 |
| `hard-hazard-neg-002` | safety-hazard-detection | 防尘帽、防静电服 | 2 | 强 |
| `hard-orch-neg-001` | inspection-orchestrator | 巡检 | **1** | **偏弱** |
| `hard-report-neg-001` | inspection-report | 巡检报告、报告 | 2 | 强 |
| `hard-gauge-neg-001` | gauge-reading | 压力、压力表、照片 | 3 | 强 |
| `hard-orch-neg-002` | inspection-orchestrator | （无） | **0** | **弱** |

## 处置：**保留，不删不改**，理由如下

1. **改了就是动预注册。** 用例清单在 `PREREGISTRATION.md` §2 逐条写死，现在删改会破坏冻结纪律。
2. **两条 orch 负例测的不是词面，是路由语义。** `inspection-orchestrator` 的 description 正向段写的是
   「负责分派到隐患识别、仪表读数、报告生成三个子技能」——即它的职责是**多目标分派**：
   - `hard-orch-neg-001`：有巡检上下文 + **多个整改项要分组**，形态像「多目标的活」，
     但用户要的是分组与发信，不需要任何识别 → 测 orch 会不会把非识别任务也揽进来。
   - `hard-orch-neg-002`：**一句话里两个识别目标**（读表 + 铭牌型号），形态最像 orch 该介入的场景，
     但用户已指明要读表 → 测 orch 会不会在类型已指明时仍然介入。
   两条的正解都不是靠词面拒绝，而是靠「orch 只在这三件事**未指明**时才触发」这条语义边界。
   `hard-orch-neg-002` 的任务行虽未逐字命中核心词，但含「读数」（description 中「仪表读数」的子串）
   与「照片」（description 写的是「图像/视频帧」），属**部分匹配**。
3. **判读时会单独标注。** 最终报告必须写明：两条 orch 硬负例的词面强度弱于其余四条，
   若 Δ2′ 的效应只体现在 hazard/report/gauge 的负例上，不得据 orch 的零差异声称「orch 的 Not-for 无用」。

## 对 §3 子集的影响：**无**

S1 = 22 条、S2 = 6 条、S3 = 21 条，成员一律不变。本附注**不改变任何分母**。
