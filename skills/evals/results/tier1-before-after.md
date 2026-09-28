# 受控实验：加入英文触发词对 Tier 1 分数的影响

**日期**：2026-09-27 · **工具**：NVIDIA SkillEvaluator v0.3.0（Tier 1 静态，无 LLM provider，零 API 费用）

## 实验设计

- **唯一变量**：在 `description` 中追加一个英文触发短语，命中官方 `trigger_words = ["use","when","for","helps","allows"]` 匹配集
- **对照条件**：中文表达逐字未改；`不适用于：` 负向边界段逐字未改；正文一字未动
- **长度约束**：总长 ≤190 字符（官方 `>200` 会扣 5 分，须避免净收益被抵消）

---

## 1. 改前 / 改后原文（逐字）

### inspection-orchestrator

**改前**（166 字符）
```
工业安全巡检的总入口与窄路由层。当用户给出巡检图像/视频帧或巡检任务、但未指明具体识别类型时触发；
负责分派到隐患识别、仪表读数、报告生成三个子技能，并决定本地/云端推理层级。
不适用于：已指明单一识别类型的请求（直接调用对应子技能）、纯文本问答、图像编辑修图、通用 OCR 取字、
非工业场景的图像描述与评价（如风景照构图点评）。
```

**改后**（184 字符）— 末行新增 `Use when 未指明识别类型。`
```
工业安全巡检的总入口与窄路由层。当用户给出巡检图像/视频帧或巡检任务、但未指明具体识别类型时触发；
负责分派到隐患识别、仪表读数、报告生成三个子技能，并决定本地/云端推理层级。
不适用于：已指明单一识别类型的请求（直接调用对应子技能）、纯文本问答、图像编辑修图、通用 OCR 取字、
非工业场景的图像描述与评价（如风景照构图点评）。
Use when 未指明识别类型。
```

### safety-hazard-detection

**改前**（135 字符）
```
识别工业巡检图像中的人员安全违规与现场隐患：未戴安全帽、未穿反光衣、违规闯入、通道堵塞、设备渗漏、明火烟雾。
当用户提供车间/厂区/工地图像并要求查隐患、查违章、安全检查时使用。
不适用于：仪表读数、纯文字文档或表格识别、无图像的文本提问、报告排版生成、图像美化与编辑。
```

**改后**（152 字符）— 末行新增 `Use when 需查安全隐患。`
```
识别工业巡检图像中的人员安全违规与现场隐患：未戴安全帽、未穿反光衣、违规闯入、通道堵塞、设备渗漏、明火烟雾。
当用户提供车间/厂区/工地图像并要求查隐患、查违章、安全检查时使用。
不适用于：仪表读数、纯文字文档或表格识别、无图像的文本提问、报告排版生成、图像美化与编辑。
Use when 需查安全隐患。
```

### gauge-reading

**改前**（138 字符）
```
读取工业仪表图像中的数值与状态：压力表、温度表、液位计、电流/电压表、阀门开度。
当用户提供仪表盘面/表计照片并要求读数、抄表、看压力/温度/液位时使用。
不适用于：人员行为与安全隐患识别、设备铭牌/标签的 OCR 取字、无仪表盘面的场景照片、纯文本数据表、历史数据趋势分析。
```

**改后**（155 字符）— 末行新增 `Use when 需读仪表数值。`
```
读取工业仪表图像中的数值与状态：压力表、温度表、液位计、电流/电压表、阀门开度。
当用户提供仪表盘面/表计照片并要求读数、抄表、看压力/温度/液位时使用。
不适用于：人员行为与安全隐患识别、设备铭牌/标签的 OCR 取字、无仪表盘面的场景照片、纯文本数据表、历史数据趋势分析。
Use when 需读仪表数值。
```

### inspection-report

**改前**（156 字符）
```
把已完成的隐患识别与仪表读数结果汇总成结构化巡检报告：分级、整改建议、导出 Markdown/JSON。
当用户要求生成/汇总/导出巡检报告，或已有巡检结论需要成文时使用。
不适用于：从零识别图像内容、单张图像的即时判读、仪表读数本身、
无巡检数据的通用文案写作（含工作总结、宣传稿、新闻稿等非巡检报告类文档）。
```

**改后**（174 字符）— 末行新增 `Use when 需生成巡检报告。`
```
把已完成的隐患识别与仪表读数结果汇总成结构化巡检报告：分级、整改建议、导出 Markdown/JSON。
当用户要求生成/汇总/导出巡检报告，或已有巡检结论需要成文时使用。
不适用于：从零识别图像内容、单张图像的即时判读、仪表读数本身、
无巡检数据的通用文案写作（含工作总结、宣传稿、新闻稿等非巡检报告类文档）。
Use when 需生成巡检报告。
```

---

## 2. 字符数对照

| skill | 改前 | 改后 | 增量 | ≤190 | ≤200（官方扣分线） |
|---|---|---|---|---|---|
| inspection-orchestrator | 166 | **184** | +18 | ✅ | ✅ |
| safety-hazard-detection | 135 | **152** | +17 | ✅ | ✅ |
| gauge-reading | 138 | **155** | +17 | ✅ | ✅ |
| inspection-report | 156 | **174** | +18 | ✅ | ✅ |

（增量含 YAML 折行产生的 1 个连接空格。）

---

## 3. Tier 1 分数对照

### Discoverability（权重 25%）

| skill | 改前 | 改后 | Δ |
|---|---|---|---|
| inspection-orchestrator | 85 | **95** | **+10** |
| safety-hazard-detection | 85 | **95** | **+10** |
| gauge-reading | 85 | **95** | **+10** |
| inspection-report | 85 | **95** | **+10** |

### Overall

| skill | 改前 | 改后 | Δ | Grade |
|---|---|---|---|---|
| inspection-orchestrator | 76.0 | **78.5** | **+2.5** | C → C |
| safety-hazard-detection | 77.8 | **80.2** | **+2.4** | **C → B** |
| gauge-reading | 77.8 | **80.2** | **+2.4** | **C → B** |
| inspection-report | 76.0 | **78.5** | **+2.5** | C → C |

（ΔOverall = ΔDiscoverability × 权重 0.25，四个 skill 完全吻合：10 × 0.25 = 2.5。）

### 扣分项变化

| skill | 改前 Discoverability 扣分项 | 改后 |
|---|---|---|
| 全部 4 个 | −10 `Description doesn't mention WHEN to use this skill`<br>−5 `No '## Purpose' section` | ~~−10~~ **已消失**<br>−5 保留 |

**改后 4 个 skill 的 Discoverability 只剩 1 条扣分项**（缺 `## Purpose` 段），且该项与本次变量无关。

---

## 4. 完整性验证（改后逐项复检）

| 检查 | 结果 |
|---|---|
| 中文前缀与改前逐字相同 | ✅ 4/4（程序化全等比较：`改后 == 改前 + " Use when …。"`） |
| `不适用于：` 负向段逐字未变 | ✅ 4/4（段落字节级比较） |
| 命中 `trigger_words` 匹配集 | ✅ 4/4 |
| 总长 ≤190 字符 | ✅ 4/4 |
| `skills-ref validate` | ✅ 4/4 仍为 `Valid skill`（退出码 0） |
| 正文改动 | 无（仅 `description` 字段） |

验证脚本口径：以 YAML 解析后的 `description` 值为准（`>-` 折行标量展开后单行字符串），与评测器内部取值方式一致。

---

## 5. 结论

**四个 skill 的 Discoverability 各提高 10 分、Overall 各提高约 2.5 分，而中文语义与负向边界段逐字未变。**

分数变化全部来自英文字符串匹配——评测器的 WHEN-to-use 检查以 `["use","when","for","helps","allows"]` 作子串匹配，与描述是否真的说明了使用时机无关。本次加入的 `Use when …` 短语本身不承载任何改前没有的信息（改前中文已表达同一触发条件），却使该项从"未通过"变为"通过"。

这构成一个**可复现的实证**：该静态指标度量的是描述文本的**字符串特征**，而非其**语义内容**。NVIDIA 自己的论文亦持此立场（arXiv:2608.20614 有专节 "Static Scores Are Not Runtime Evidence"，并报告结构分与 LLM-judge 分 Spearman ρ=0.14）。

**方法学含义**：静态检查是有效的**形式一致性门禁**，其结论应被理解为"文本形式是否合规"，而非"技能是否更容易被正确触发"。涉及触发质量的判断，需要运行时证据。

---

## 附：复现命令

```bash
# 改前基线
for d in inspection-orchestrator safety-hazard-detection gauge-reading inspection-report; do
  skillevaluator tier1 quality-check "skills/$d" -r json -o "skills/evals/results/tier1-raw/$d"
done

# 施加变量：在每个 description 末尾追加 "Use when <短语>。"

# 改后
for d in inspection-orchestrator safety-hazard-detection gauge-reading inspection-report; do
  skillevaluator tier1 quality-check "skills/$d" -r json -o "skills/evals/results/tier1-raw-after/$d"
done
```

原始输出：`tier1-raw/*/skillevaluator-quality.json`（改前）、`tier1-raw-after/*/skillevaluator-quality.json`（改后）

---
---

# 第二轮：第二个独立变量 —— 补 `## Purpose` 段

**日期**：2026-09-27 · 同一工具（v0.3.0，Tier 1 静态，零 API 费用）

## 一、实验设计

- **唯一变量**：新增一个 `## Purpose` 顶层章节
- **对照条件**：第一轮加入的英文触发短语保留不动；`不适用于：` 段、中文语义、其余正文全部不动
- **变量独立性**：与第一轮（英文触发词）互不重叠——第一轮作用于 `description` 的字符串特征，本轮作用于正文的**结构特征**

### 位置依据

四个文档的结构完全一致：

```
# <标题>
<一句无标题导语>
## 前置问题
## 主流程
## 输出契约
## 负向边界
```

`## Purpose` 插在**导语之后、`## 前置问题` 之前**，与其余顶层章节同级。依据：NVIDIA 的结构评分把 Purpose 归为**定位性顶层章节**（orientation section），应与其它顶层章节并列、且位于流程性章节之前。此位置不打乱任何现有结构，也不需移动或改写任何既有文字。

### 内容来源

四段 Purpose 均由**团队已写定的 `description` 推导**，只做陈述性复述，**不新增任何能力声明**：

| skill | `## Purpose` 正文 |
|---|---|
| inspection-orchestrator | 工业安全巡检的总入口与窄路由层。接收巡检图像/视频帧或巡检任务，在未指明具体识别类型时分派到隐患识别、仪表读数、报告生成三个子技能，并决定本地/云端推理层级。 |
| safety-hazard-detection | 从工业巡检图像中识别人身安全违规与现场隐患，覆盖未戴安全帽、未穿反光衣、违规闯入、通道堵塞、设备渗漏、明火烟雾六类目标。 |
| gauge-reading | 读取工业仪表盘面的数值与状态，覆盖压力表、温度表、液位计、电流/电压表、阀门开度五类表计。 |
| inspection-report | 把已完成的隐患识别与仪表读数结果汇总成结构化巡检报告，包含分级与整改建议，并支持导出 Markdown/JSON。 |

---

## 二、三列分数对照

### Discoverability（权重 25%）

| skill | ① 改前 | ② 加英文触发词后 | ③ 补 Purpose 后 | Δ①→② | Δ②→③ |
|---|---|---|---|---|---|
| inspection-orchestrator | 85 | 95 | **100** | +10 | +5 |
| safety-hazard-detection | 85 | 95 | **100** | +10 | +5 |
| gauge-reading | 85 | 95 | **100** | +10 | +5 |
| inspection-report | 85 | 95 | **100** | +10 | +5 |

### Overall

| skill | ① 改前 | ② 加英文触发词后 | ③ 补 Purpose 后 | Grade |
|---|---|---|---|---|
| inspection-orchestrator | 76.0 | 78.5 | **79.8** | C |
| safety-hazard-detection | 77.8 | 80.2 | **81.5** | B |
| gauge-reading | 77.8 | 80.2 | **81.5** | B |
| inspection-report | 76.0 | 78.5 | **79.8** | C |

### 扣分项变化

| 阶段 | Discoverability 扣分项 |
|---|---|
| ① 改前 | −10 缺 WHEN-to-use 匹配 · −5 缺 `## Purpose` |
| ② 加英文触发词后 | −5 缺 `## Purpose` |
| ③ 补 Purpose 后 | **无（100 分，0 条 issues）** |

**ΔOverall 与 ΔDiscoverability × 0.25 在所有 skill、所有阶段完全吻合**（5 × 0.25 = 1.25 ≈ 1.3），说明两轮变量均未波及其他维度。

**方法学含义**：两个互相独立的变量（`description` 的字符串特征、正文的结构特征）各自独立地移动了同一个分数，是两次独立复现。这说明该静态评分对文档的**结构性字符串特征**敏感——这是静态方法的设计属性，也是其边界。

---

## 三、完整性验证（第二轮）

要证明的命题：**只加了 `## Purpose` 段，其余一字未动。**

### 验证命令

```bash
cd "<repo>"
.venv/Scripts/python.exe - <<'PYEOF'
import re
PRE={'inspection-orchestrator':51,'safety-hazard-detection':51,'gauge-reading':50,'inspection-report':48}
NEG={'inspection-orchestrator':"不适用于：已指明单一识别类型的请求（直接调用对应子技能）、纯文本问答、图像编辑修图、通用 OCR 取字、",
'safety-hazard-detection':"不适用于：仪表读数、纯文字文档或表格识别、无图像的文本提问、报告排版生成、图像美化与编辑。",
'gauge-reading':"不适用于：人员行为与安全隐患识别、设备铭牌/标签的 OCR 取字、无仪表盘面的场景照片、纯文本数据表、历史数据趋势分析。",
'inspection-report':"不适用于：从零识别图像内容、单张图像的即时判读、仪表读数本身、"}
for s,p in PRE.items():
    t=open(f"skills/{s}/SKILL.md",encoding="utf-8").read()
    rt=re.sub(r"## Purpose\n\n.*?\n\n(?=## 前置问题)","",t,count=1,flags=re.S)
    print(s, "now",len(t.splitlines()), "| roundtrip",len(rt.splitlines()), "| pre",p,
          "| neg_intact", NEG[s] in t, "| headings",
          all(h in t for h in ["前置问题","主流程","输出契约","负向边界"]))
PYEOF
```

### 验证结果

| skill | 当前行数 | **移除 Purpose 段后** | 该轮改前行数 | 负向段完好 | 四个原有章节 |
|---|---|---|---|---|---|
| inspection-orchestrator | 55 | **51** | 51 ✅ | ✅ | ✅ |
| safety-hazard-detection | 55 | **51** | 51 ✅ | ✅ | ✅ |
| gauge-reading | 54 | **50** | 50 ✅ | ✅ | ✅ |
| inspection-report | 52 | **48** | 48 ✅ | ✅ | ✅ |

**往返比对（round-trip）**：把新插入的 `## Purpose` 块按正则精确移除后，行数**逐一精确回落**到第一轮结束时的记录值。每文件恰好 +4 行（空标题行、空行、正文、空行），不多不少。

| 检查 | 结果 |
|---|---|
| `不适用于：` 段字节级比对 | ✅ 4/4 未变 |
| 移除新增段后行数回落到改前记录值 | ✅ 4/4 |
| 四个原有 `##` 章节均存在 | ✅ 4/4 |
| `.venv/Scripts/agentskills.exe validate` | ✅ 4/4 `Valid skill`（退出码 0） |
| `description` 字段 | 未触碰（第一轮状态保持） |

---

## 四、冻结基线（md5）

**四个 `SKILL.md` 自此刻起冻结**，A5 实验期间不得再改动。

| skill | 行数 | MD5 |
|---|---|---|
| inspection-orchestrator | 55 | `03971927d03798f26c4d326b88e0b526` |
| safety-hazard-detection | 55 | `fe712cf3210d19490b94020c403df34a` |
| gauge-reading | 54 | `95aaa0cdbf0e9fb77595883780f7438f` |
| inspection-report | 52 | `cf8fb46daf349f58877e1a7cddf67e5b` |

**冻结后校验命令**：

```bash
cd "<repo>"
md5sum skills/*/SKILL.md
```

预期输出（实测，字母序）：

```
95aaa0cdbf0e9fb77595883780f7438f *skills/gauge-reading/SKILL.md
03971927d03798f26c4d326b88e0b526 *skills/inspection-orchestrator/SKILL.md
cf8fb46daf349f58877e1a7cddf67e5b *skills/inspection-report/SKILL.md
fe712cf3210d19490b94020c403df34a *skills/safety-hazard-detection/SKILL.md
```

