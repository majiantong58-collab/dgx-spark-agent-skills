# 实验版本关系说明（v1 → v2）

> 本文说明 `skills/evals/results/` 下各实验产物**对应哪一版技能描述**。
> 结论一句话：**那批结果是 v1 描述下跑的；v2 改的是场景对齐，因此结果的适用范围要标注为「v1」。**

## 1. 版本定义

| 版本 | 含义 | 四个 `SKILL.md` 的 md5 |
|---|---|---|
| **v1** | 原始描述：场景假设为**工地 / 生产车间**，PPE 项为「安全帽 / 反光衣」 | `gauge-reading` `95aaa0cdbf0e9fb77595883780f7438f`<br>`inspection-orchestrator` `03971927d03798f26c4d326b88e0b526`<br>`inspection-report` `cf8fb46daf349f58877e1a7cddf67e5b`<br>`safety-hazard-detection` `fe712cf3210d19490b94020c403df34a` |
| **v2** | 场景对齐：真实场景为**电子厂洁净车间**，PPE 项改为「防尘帽 / 防静电服」；旧项保留为 v1 遗留 | `gauge-reading` `95aaa0cdbf0e9fb77595883780f7438f`（未变）<br>`inspection-orchestrator` `03971927d03798f26c4d326b88e0b526`（未变）<br>`inspection-report` `cf8fb46daf349f58877e1a7cddf67e5b`（未变）<br>**`safety-hazard-detection` `9dd0b9febc38952b10bfe5752cbc5154`（已变）** |

**v2 只改动了一个 `SKILL.md`**（`safety-hazard-detection`），另三个 md5 与 v1 完全一致。

## 2. 哪些实验结果属于 v1

`skills/evals/results/` 下的**全部产物**均标注为「**v1 描述下的结果**」：

`A.json` · `B.json` · `C.json` · `D.json` · `decoy-A/B/C/D.json` · `a4-baseline.json` ·
`a4-sample-report.md` · `report.md` · `decoy-report.md` · `diagnostics.json` ·
`variance-log.md` · `tier1-static.json` · `tier1-static.md` · `tier1-before-after.md`

**这些文件不得修改**——它们是实验证据，包含模型当时的原始响应文本。
改了就等于篡改证据，且会让其中引用的 `hazard_code` 失去可查证性。

## 2b. Tier 1 静态分三阶段对照（**归因必须按这条时间线读**）

静态分经历**两轮受控实验**，**本轮场景对齐是第三轮**。取基准时若只看「最初」那一列，
会把前两轮我们自己量到的效应误读成「工具漂移」——那是错的。

| 阶段 | orchestrator | hazard | gauge | report | 本阶段效应 |
|---|---|---|---|---|---|
| 最初基线 | 76.0 | 77.8 | 77.8 | 76.0 | — |
| + 英文触发词 | 78.5 | 80.2 | 80.2 | 78.5 | **+2.5** |
| + Purpose 段 | **79.8** | **81.5** | **81.5** | **79.8** | **+1.25** |
| **本轮：场景对齐（v2）** | **79.8** | **81.5** | **81.5** | **79.8** | **±0** |

**+3.8（= 2.5 + 1.25）是前两轮受控实验的累计效应，不是工具侧漂移。**
两轮相加与实测位移逐位吻合。

**本轮真正的结论是：场景对齐使静态分「零变化」。**
改了 `hazard_code`、改了场景、改了 4 个文件的措辞，**分数一分未动**。
这是**预期内**的——本轮只换名词、未动结构，静态检查器本就不该有反应。

> **为什么必须较这个真**：同一组数有两种说法。「工具漂移」会让读者连带怀疑我们此前所有
> Tier 1 数字；「我们自己量过的两轮效应」则让那批数字更可信。**写法不同，可信度天差地别。**
>
> 另需注意：`gauge-reading` 在本轮**一个字节都没改**，分数同样停在 81.5——
> 它是天然的阴性对照，**正是它证明了本轮 Δ=0 而不是又一次位移。**

**口径提醒**：上表分数由 `skillevaluator quality-check` 产出（不是 `tier1` 子命令，
后者的 JSON 只有 passed / issue_count，没有百分制）。详见 `skills/evals/check-compliance.md`。

## 3. 一条有力的旁证：v1 描述确实把模型引向了工地语义

在 A 臂（无技能约束）的原始响应里，模型**自创了技能名**
`helmet_detection` 与 `reflective_clothing_detection`（见 `results/A.json`，
其中 `"skills":["helmet_detection","instrument_detection"]`）。

也就是说：**模型在完全自由发挥时，把任务理解成了「检测安全帽 / 反光衣」**——
这正是 v1 描述写明的工地 PPE 项。这条旁证说明 v1 描述对模型的语义引导是**真实存在且可观测的**，
不是推测。

v2 把描述改为「防尘帽 / 防静电服、洁净室」之后，同一引导方向也会随之改变；
**因此 v1 的实验结论不能直接套用到 v2。**

## 4. v2 改了什么（本次场景对齐）

**契约层（6 个文件）**
- `skills/safety-hazard-detection/SKILL.md` — description / Purpose / 前置问题 / 输出契约示例
- `references/hazard-taxonomy.md` — 版本号 v0.1→**v0.2**；新增 `PPE-NO-CAP` / `PPE-NO-SUIT`；旧码标注 v1 遗留
- `references/ppe-rules.md` — 场景表新增「电子厂洁净车间」并置顶；附实测能力边界
- `inspection-report/references/severity-levels.md` — 新增两条整改建议；旧两条标注 v1 遗留
- `inspection-report/references/output-schema.md` — 示例 code/label 与 `standard_version` 改为 v0.2
- `inspection-orchestrator/references/routing-table.md` — 契约示例 code 并集

**路由（1 个文件，只增不删）**
- `inspection-orchestrator/scripts/route.py` — `HAZARD_KEYWORDS` 新增
  `防尘帽 / 防静电服 / 静电服 / 洁净服 / 无尘服 / 工服 / 洁净车间`（24 → 31 词）；
  **旧词「安全帽 / 反光衣」保留**，否则本节第 3 条的旁证将无从追溯。

**用例（改动 2 条，均在 `skills/safety-hazard-detection/evals/cases.jsonl`）**

| 用例 id | 改动 |
|---|---|
| `hazard-pos-001` | `PPE-NO-HELMET` → **`PPE-NO-CAP`**；assets/input 改为「洁净车间 / 未戴防尘帽」 |
| `hazard-pos-005` | `PPE-NO-VEST` → **`PPE-NO-SUIT`**；assets 改为「洁净区人员未穿防静电服」 |

**未改动的用例（有意保留 v1 语义）**：`hazard-pos-002`（工地安全带）、`hazard-pos-003`、
`hazard-pos-004`、`hazard-neg-001~004`、`hazard-empty-001`。
`hazard-neg-004`（「安全帽的报废年限是多久？」）**是负例**，检的是「无图不触发」，
与场景无关，保留可继续测出 v1 的负向边界。

**文档层**：`skills/README.md` §5 description 示例已同步为 v2。
**尚未同步**：`docs/PRD.md:187`、`docs/demo-script.md:42`、`docs/agents/decision-log.md:254,282,283`
（decision-log 属历史记录，建议原样保留并加版本标注，不重写）。

## 5. 尚未纳入 v2 的遗留项

- `skills/evals/run_e2e.py` 合成的 E2E 素材**画的是黄色安全帽**（v1 语义）；
  改用例后该素材与新场景不一致，**需重新生成素材**才能反映洁净车间场景。
- A5 / decoy 实验**未在 v2 上重跑**。若需 v2 结论，必须重跑，不能沿用 v1 数字。

## 6. 复核命令

```bash
# 合规门禁（v2 已实测 4/4 通过）
for d in inspection-orchestrator safety-hazard-detection gauge-reading inspection-report; do
  ./.venv/Scripts/agentskills.exe validate "skills/$d"
done

# 证据未被篡改
md5sum skills/evals/results/*
```
