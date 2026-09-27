# Skills — 工业安全巡检 Agent Skills 套件

> 本目录是**自研编配层**。官方 skill 一律**不修改**，只做调用与编排。
> 官方红线原话：「千万不要去直接修改官方的 skill，其实你就负责编配，去负责改内容，
> 它原来千问其实就不再就不认了。」（何坤）

> **交付状态（重要，先读这条）**：四臂对照评测已跑完，结果已落盘。
>
> - **本地三层流水线已实现并实测**：入口 `safety-hazard-detection/scripts/local_tier_pipeline.py`，
>   Tier 0（YOLO11n）/ Tier 0.5（颜色-几何启发式）/ Tier 1（Qwen3-VL-2B）三层跑通。
>   逐层调用次数与短路记录见 `../docs/local_tier_metrics.json`，逐帧输出见 `pipeline_results.json`。
>   逐层延迟 / 显存基准见 `../docs/local_tier_benchmark.json`（**与调用次数不是同一轮，不可交叉引用**）。
> - **Tier 2（StepFun `step-5-preview`）适配层已实现，但本次运行未获授权**
>   （`cloud_authorized=False`，`route.enforce_safety_boundary` 将其压回本地，实测 tier2 调用为 0）。
>   **Tier 2 通路未被触发、也未被验证**——不得据此表述为「云端按需触发」。
> - **四臂评测已完成**：40 条用例 × 4 臂 × 3 次重复 = **480 次调用**。
>   逐臂结果 `results/{A,B,C,D}.json`；汇总报告 `results/report.md`；诊断指标 `results/diagnostics.json`；
>   token / 成本 / 方差 `results/variance-log.md`；诱饵用例结果 `results/decoy-{A,B,C,D}.json`。
> - **核心结果（如实陈述，含零结果）**：Δ1 = B − A 显著为正（触发准确率 +0.425、结论正确率 +0.833）；
>   **Δ2 = FTR(C) − FTR(B) = 0.000**（本技能口径，负例样本 16/16 完整）——
>   本次样本**未观测到** `不适用于：` 段的边际收益，**既不支持也不否定**其作用。
>   **不得表述为「负向条件带来净收益」**，也不得把 Δ2 当作 NVIDIA 语汇的 Skill Lift 报出（不同轴）。
> - 复现入口：`py -3.12 skills/evals/run_e2e.py`（`--offline` 可跳过 API 调用）；
>   对照评测 `py -3.12 skills/evals/run_comparison.py --concurrency 5`（**并发不得超过 5**）。
>
> **⚠️ 测试素材是程序合成的示意图，不是真实工业照片**，只能用于打通链路与采集 token 基线，
> **不得**作为识别准确率的证据。来源与授权登记见 `evals/results/a4-baseline.json` 的 `assets`。

---

## 1. 目录结构（对齐官方规范）

```
skills/
├── README.md                      ← 本文件：拆分理由与路由关系
├── evals/                         ← 跨技能评测层（不属于任何单个 skill）
│   ├── comparison-design.md       带 skill vs 不带 skill 的四臂对照设计（A5 执行规格）
│   ├── metrics.json               指标定义（机器可读）
│   ├── run_comparison.py          评测执行器（四臂 A/B/C/D 均已跑通；--concurrency 必须 ≤ 5）
│   ├── run_e2e.py                 端到端最小通路 + token 采集（含合成测试图生成）
│   ├── bench_layers.py            逐层性能基准复现脚本（--layer tier0|tier0_5|tier1）
│   ├── bench_raw_tier*.json       基准原始样本（tier0 / tier0_5 / tier1）
│   ├── pipeline_results.json      三张照片的完整 findings
│   ├── assets/                    测试图（程序合成，来源登记见 results/a4-baseline.json）
│   └── results/                   结果 JSON 与报告（设计上随仓库提交）
│       ├── {A,B,C,D}.json         四臂逐用例逐次原始结果
│       ├── report.md              四臂汇总报告（主表 / 差值表 / 敏感性 / 失败模式）
│       ├── diagnostics.json       诊断指标（广义触发率、幽灵技能调用等）
│       ├── variance-log.md        token / 成本 / 方差证据
│       ├── decoy-{A,B,C,D}.json   16 条负向诱饵用例逐臂结果
│       ├── tier1-static.json      Tier 1 静态质检（SkillEvaluator）
│       ├── a4-baseline.json       早期 token 明细 + 160 次调用外推
│       └── a4-sample-report.md    端到端产出的样例报告
├── inspection-orchestrator/       ← 编排层：只路由，无业务逻辑
├── safety-hazard-detection/       ← 窄技能 1：安全隐患识别
├── gauge-reading/                 ← 窄技能 2：仪表读数
└── inspection-report/             ← 窄技能 3：巡检报告生成
```

每个 skill 目录均为官方的四件套结构：

```
<skill-name>/
├── SKILL.md          # 主文件建议 < 500 行；description 含正向触发词 + Not for
├── scripts/          # 确定性工具（部分已实现、部分仍为占位，见开头「交付状态」）
├── references/       # 判定标准 / 巡检项定义
└── evals/            # cases.jsonl + README.md
```

## 2. 为什么这样拆（拆分理由）

官方心法第 1 条：**窄触发强路由——拆成子 skill，别做宽泛 skill。**

### 2.1 判据：一个 skill 只干一件事

拆分的依据不是「功能多少」，而是**触发条件能否用一句话写清楚且互不重叠**。
凡是需要靠「也」「顺便」来描述的，一律拆出去。

| skill | 一句话职责 | 触发条件 | 明确不做什么 |
|---|---|---|---|
| `inspection-orchestrator` | 决定调谁、定层级 | 有图像/任务，**但未指明识别类型** | 不识别、不读数、不成文 |
| `safety-hazard-detection` | 图像 → 隐患标签 | 有图像且有**隐患语义** | 不读数、不写报告、不做趋势 |
| `gauge-reading` | 表盘 → 一个数 | 画面里**有仪表盘面** | 不判隐患、不做趋势、不成文 |
| `inspection-report` | 结构化结论 → 报告 | **已有结论**要成文 | 不识别、不读数、不新增结论 |

四个职责两两不相交——这是「窄触发」的可验证判据，也是 `evals/` 中负向用例的设计依据。

### 2.2 为什么编排层单独成一个 skill（而不是塞进子技能）

编排的触发条件是「**用户没说清楚要干什么**」，与三个子技能的触发条件正交。
把它做成独立 skill，好处有三：

1. 用户已指明类型时**不经过编排层**，少一跳、少延迟、少一次误路由机会。
2. 三个子技能可以独立被 Agent 直接调用，也可被编排层串起来——**组合而非耦合**。
3. 三层分级路由（Tier 0/1/2）是**横切关注点**，只有一个地方实现才不会互相打架。

### 2.3 为什么不做「一个大的巡检 skill」

宽泛 skill 的 `description` 必然含糊，含糊的 `description` 必然过度触发——
这正撞在官方承认的两个痛点上：**触发稳定性差** 与 **目录碎片化**。
本项目用「4 个窄 skill + 16 条负向用例」把这个风险显式量化（见 `evals/comparison-design.md` 的 C 臂消融）。

## 3. 路由关系

```
                     用户请求
                        │
        ┌───────────────┴───────────────┐
        │  已指明单一识别类型？            │
        └───────┬───────────────┬───────┘
              是│               │否
                ▼               ▼
    ┌───────────────────┐   ┌──────────────────────┐
    │ 直接进对应子技能    │   │ inspection-orchestrator│
    └─────────┬─────────┘   └───────────┬──────────┘
              │                         │ 输入规范化 + 安全边界 + 路由
              │           ┌─────────────┼─────────────┐
              ▼           ▼             ▼             ▼
    ┌──────────────────┐ ┌────────────┐ ┌──────────────┐
    │safety-hazard-    │ │gauge-      │ │inspection-   │
    │detection         │ │reading     │ │report        │
    └────────┬─────────┘ └─────┬──────┘ └──────▲───────┘
             │                 │                │
             └─────────────────┴────────────────┘
                    串行汇入，不并行
              （避免同帧被 Tier 2 重复计费）
```

**冲突消解优先级**：用户明确指定的单一技能 > 关键词判定 > 默认编排。
详见 `inspection-orchestrator/references/routing-table.md`。

**跨技能数据契约**：三条子链路通过 `routing-table.md` 定义的结构化 Schema 串接，
`inspection-report` 依赖该契约。契约硬规则是每条结论必带 `confidence` 与 `evidence_ref`。

## 4. 官方规范对齐自查

| 依据（官方规范 / 讲师心法） | 本套件的落实 |
|---|---|
| 目录结构 `SKILL.md + scripts/ + references/ + evals/` | 四个 skill 均为四件套，见上方目录树 |
| 命名 `kebab-case` | 全部 kebab-case |
| 主文件建议 **< 500 行**（官方两处均为 **500 行**；「100 行」全站零命中，非官方值） | 四个 `SKILL.md` 的「主流程」小节均为 7 步，**实测 13–16 行**（不含空行的计数口径） |
| metadata（`name` + `description`）**启动加载**约 100 token | 四个 description 均为一段，**纯汉字计数实测 111–139 字**（gauge 111 / hazard 115 / report 122 / orchestrator 139），未展开正文细节。**description 自身硬限为 1024 字符**，四个均远低于该限 |
| `description` 含正向触发词**与**负向条件 | 四个 description 均以「不适用于：…」结尾，见 §5 |
| **讲师心法**① 窄触发强路由（**非官方规范**） | 3 个窄子技能 + 1 个路由层，职责两两不相交（§2.1） |
| **讲师心法**② 前置问题规定好，不许猜（**非官方规范**） | 每个 `SKILL.md` 有独立的「前置问题」小节，4 条，缺一即问 |
| **讲师心法**③ 安全边界内嵌（**非官方规范**） | 四个 `SKILL.md` 的**主流程第 2 步**均为「安全边界」，不在末尾 |
| 环境差异放外部适配层 | `scripts/` 只封装调用，模型/设备可切换，业务规则在 `references/` |
| 阈值单一来源 | 分级阈值 `0.40` / `0.75` 的**唯一代码常量定义处**是 `inspection-orchestrator/scripts/tier_budget.py`；全仓另有 7 处复述（`SKILL.md` 主流程、`hazard-taxonomy.md`、`escalation-policy.md` 与本文件等文档/docstring），属**有意的可读性复述**而非第二来源——改阈值必须同步这 8 处 |
| 不修改官方 skill | 本目录全部为自研文件；未安装、未改动任何官方 skill |

> **字数与负向覆盖的取舍**：为让 16 条负例**全部**落在 `不适用于` 段的拦截范围内（§6 最后一条），
> 四个 description 补入了铭牌 OCR、非工业场景图像、无数据的通用公文等负向措辞，字数因此上浮到 111–139 字。
>
> **更正**：原此处记为「已高于『约 100 token』的官方建议值」，该表述**有误**——
> 「约 100 token」指 **metadata（`name` + `description`）启动加载**的预算，**不是** description 单字段上限；
> description 自身硬限为 **1024 字符**，四个均远低于该限，**不存在字数超标**。
>
> **取舍本身仍然成立**：负向覆盖需要在有限额度内取舍，覆盖缺失会**直接稀释 Δ2、污染核心指标**。

## 5. description 示例（正向 + 负向同段）

```yaml
description: >-
  识别工业巡检图像中的人员安全违规与现场隐患：未戴防尘帽、未穿防静电服、未戴安全帽、未穿反光衣、违规闯入、通道堵塞、设备渗漏、明火烟雾。
  当用户提供车间/洁净室/厂区/工地图像并要求查隐患、查违章、安全检查时使用。
  不适用于：仪表读数、纯文字文档或表格识别、无图像的文本提问、报告排版生成、图像美化与编辑。
```

前两句是**正向触发词**，末句是**负向条件**——官方要求两者写在同一个 `description` 里，
因为路由时只能看到 description。C 臂消融实验专门测量这句话的净收益。

## 6. 评测

- 用例总量：**40 条**（正向 21 / **负向 16** / 空结论 3），分布在四个 `evals/cases.jsonl`
- 三条轴严格区分，判据是**「正确答案是什么」**而不是「输入长什么样」：
  - `negative` —— **正确答案是不调用该技能**（官方要求，16 条）
  - `positive` —— 应触发且应给出具体结论（21 条）
  - `positive_empty` —— **应触发**，但输入不足以支撑任何**确定结论**：正确输出是**空集**、`uncertain`、
    或**显式裁剪后的部分结果**（裁剪必须回报，不得静默）。共同判据是**不得为满足请求而编造或拔高结论**（3 条）
- **FTR 口径（必须按此读，否则指标失去意义）**：
  `FTR = 负向用例中「该用例 `skill` 字段所指技能」被错误调用的占比` —— 即**本技能**口径，**不是**「任意技能」口径。
  依据是官方原话「有些任务的正确答案就是**不调用这个 Skill**」（单数）。
  交叉路由的负例（如 `orch-neg-001` 的正确去向是 `gauge-reading`）在「任意技能」口径下会把**正确路由**计成误触发，
  该口径因此被否决；这类用例的正确性由「路由序列精确匹配率」单独考核。
- 对照评测：四臂 A 基线 / B 全量 / **C 消融（删掉 Not for）** / D 仅描述
- 核心结论指标：**`Δ2 = FTR(C) − FTR(B)`** —— FTR 越低越好，故**正值 = Not-for 段带来的净收益**
- 负向用例的 Not-for 覆盖：16 条负例必须**全部**落在 description 的 `不适用于` 段可拦截范围内，
  否则 C 臂消融（删掉 Not for 段）对该条无影响，Δ2 会被稀释、实验在该部分混淆

- **负例输入的相关性（读 Δ2 前必看）**：`gauge-neg-001` 与 `report-neg-001` 输入文本完全相同，
  一旦判错会在两个技能的 FTR 上**同时**计错，`Δ2` 一次最多跳 `2/16 = 0.125`（普通负例的 2 倍）——
  详见 `evals/README.md`

执行规格见 `evals/comparison-design.md`，指标定义见 `evals/metrics.json`。
