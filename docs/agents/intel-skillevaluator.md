# NVIDIA SkillEvaluator 侦察：它怎么定义和测量「触发质量」

> 侦察日期：2026-09-27 · 仓库 `https://github.com/NVIDIA/SkillEvaluator`（Apache-2.0，HTTP 200 可访问）
> 配套论文：arXiv:2608.20614《Evaluating Skills, Not Just Agents: Agentic Continuous Evaluation of Skills》（ACES 框架，15 页，已被 Agent Skills '26 / ACM CAIS 2026 与 KDD 2026 Workshop 接收）

---

## 0. 结论先行（Q6 影响立意，最优先）

**NVIDIA 已经量化了「description 写多长」，但没有量化「负向条件对误触发率的影响」。** 我们的立意需要**收窄措辞**，但空位依然存在。见 §6。

---

## 1. Tier 1 / 2 / 3 是什么

出处：`README.md`（三档总表）、`docs/tier1-validation.mdx`、`docs/tier2-deduplication.mdx`、`docs/tier3-live-evaluation.mdx`

三档可独立运行，命令分别为 `skillevaluator tier1|tier2|tier3 ./my-skill`。

| Tier | 回答的问题 | 输入 | 输出/指标 | 依赖 |
|---|---|---|---|---|
| **Tier 1 Validation** | 安全且格式良好吗？ | skill 目录 | 确定性质量门：schema、quality-check（四类加权评分）、security-scan、pii-scan、lint-scripts；可选 `rubric-eval`（九条 LLM-as-judge 量表） | 静态检查**不需要**模型 key；完整覆盖需外部扫描器 |
| **Tier 2 Deduplication** | 指引重复或重叠吗？ | skill 目录（+ 可选 `--catalog`） | 语义重叠检测：intra-skill 校验、LLM 分析、语义聚类（`semantic_clustering.py`、`chunker.py`） | embeddings + chat |
| **Tier 3 Live Evaluation** | 它真的让 agent 变强了吗？ | skill 目录 + eval 数据集 | **Skill Lift**、pass@k、六个运行时指标、五个报告维度 | provider key + 受支持的 agent + 运行中的 sandbox（默认 Docker） |

### Tier 3 细节（重点）

- **配对实验设计**：同一批 eval case 跑**两臂**——with-skill arm 与 without-skill baseline arm（除非传 `--skip-baseline`）。两臂都在 Harbor 环境中执行，**唯一实验变量就是 skill 本身**。
- **Skill Lift** = 两臂的**带符号差值**，即「这个 skill 的净贡献」的直测。
- **pass@k**：每 case 多次尝试时提供可靠性信号。
- 支持 agent：`codex`、`claude-code`（`claude` 是别名）、`opencode`。默认按 provider 配对：NVIDIA Build→OpenCode、OpenAI→Codex、Anthropic→Claude Code。
- 底座：Tier 3 由 [Harbor](https://github.com/harbor-framework/harbor)（开源 agent 评测框架）驱动；Tier 1 安全扫描由 [SkillSpector](https://github.com/NVIDIA/SkillSpector) 提供。
- 轨迹标准化为 **ATIF**（Agent Trajectory Interchange Format）。
- `--block-on-agent-eval` 可把 Tier 3 从 advisory 提升为门禁。

---

## 2. `Discoverability` 维度怎么打分

**关键：`Discoverability` 在 NVIDIA 体系里是「结构性文档扫描」维度，不是运行时测量。** 两者同名但完全不同，别混淆。

### 2a. 静态结构性 Discoverability（权重 0.25）

出处：论文 arXiv:2608.20614 正文（HTML 版，约第 508-513 行）；`src/skillevaluator/validators/quality_score.py`

论文列出的评分项，逐项原文提炼：

- **Description length（50–150 preferred；>200 flagged as overlong）**
- **trigger vocabulary**（`use`、`when`、`for`）
- **avoidance of vague wording**
- **explicit negative/boundary phrasing** ← 直接对应我们的议题
- directory-name conventions
- tone（first/second person）
- **"WHEN to use" guidance**

论文原文把结构性评分描述为：「aggregates roughly **50 deterministic rule checks** across Correctness, **Discoverability**, Reliability, and Efficiency for n=145 real skills」，默认 70 分门禁。

**没有公开的评分公式**（每项权重、如何合成 0-100 的细节未在论文或 docs 中给出）。可执行实现见 `src/skillevaluator/validators/quality_score.py`。

### 2b. 运行时 Discoverability（Tier 3 五维度之一）

出处：`src/skillevaluator/tier3/harbor/metrics.py` 的 `DIMENSION_DISPLAY` / `DIMENSION_QUESTIONS`、`docs/tier3-live-evaluation.mdx`

Tier 3 默认评分下报告领先呈现五个「人可读」维度：

| 维度 | 回答的问题 | 底层 evaluator | 权重 |
|---|---|---|---|
| Security | Is it safe to use? | `security` | 1.0 |
| Correctness | Does it do what it's supposed to? | `accuracy` | 1.0 |
| **Discoverability** | **Is it loaded when it should be?** | **`skill_execution`** | **1.0** |
| Effectiveness | Is it better with the skill than without? | `goal_accuracy` 0.5 + `behavior_check` 0.5 | 0.5/0.5 |
| Efficiency | Does it use fewer tool calls and tokens? | `skill_efficiency` | 1.0 |

映射定义在 `src/skillevaluator/constants.py` 的 `DIMENSION_MAPPING`（第 519-549 行）。**运行时 Discoverability 完全由 `skill_execution` 这单一指标决定，权重 1.0，无公式**——它就是 `skill_execution` 的显示名。

---

## 3. `skill_efficiency` 信号的定义

出处：论文正文（第 1360-1373 行）；`metrics.py`

官方描述（`METRIC_DESCRIPTIONS`）：**"Routing correctness, workspace-aware skill reads, tool call productivity"**

它是**确定性**指标，含**两个子检查**：

- **`routing`**：agent 是否只读取了被允许的 workspace 内 skill——isolation 模式下只能读 target skill；group 模式下只能读 target + 配置的 supporting skills。
- **`tool_efficiency`**：productive tool calls / total tool calls，带**显式浪费指标**——`--help` fishing（拿 help 当探索）、在错误路径上做探索性 `ls`、任务进行中安装包。

判定方式：**子检查 pass/fail 的均值**（"Score is the mean of pass/fail sub-check outcomes"）。

### 「decoy avoidance」的正式名字是 routing premium

出处：论文正文（第 1667-1720 行，含隔离 vs 分组 workspace 对照图）

论文的实验设计区分两种 workspace：

- **Isolation**：workspace 里**只有** target skill（如 `git-skill`）。用户请求 "sync my repo with origin"，agent 无 routing 决策可言 → `Lift_iso` **纯测内容**。
- **Group**：workspace 里除 target skill 外还有 **4 个 decoy skills**（论文举例：`api-debugger`、`log-triage`、`config-validator`、`release-planner`）。agent 需从多个 skill 中选出 target → `Lift_grp` **测内容 + routing**。

> **routing premium = `Lift_grp` − `Lift_iso`**

论文原文："is the **routing premium**: how much the measured skill value [depends on operating among others] rather than operate in isolation. A near-zero or negative routing premium..."（下文被截断，但语义是 routing premium 接近零或为负说明该 skill 在选择压力下没有优势）。

**「decoy」是 NVIDIA 的正式术语**，用来制造选择压力以暴露 routing 质量——这与我们关心的「负向条件能否抑制误触发」是同一问题的两种问法。

---

## 4. 公开的指标名 / 术语（原文列出）

出处：`src/skillevaluator/tier3/harbor/metrics.py`、论文

**六个默认运行时指标**（`DEFAULT_METRICS`，metric set 名 `skill-evaluator-default-v2`）：

| 指标名 | 显示名 | 官方一句话定义 |
|---|---|---|
| `security` | Security | Trace scan for unsafe operations, secret leakage, and unauthorized access |
| `skill_execution` | Skill Execution | Activation, script run, workflow order, error recovery |
| `skill_efficiency` | Efficiency | Routing correctness, workspace-aware skill reads, tool call productivity |
| `accuracy` | Accuracy | Factual correctness (5-criterion LLM rubric) |
| `goal_accuracy` | Goal Accuracy | Did the agent achieve the user's goal? |
| `behavior_check` | Behavior Check | Adherence to expected workflow steps |

（旧版 `skill-evaluator-default-v1` 无 `security`。另有 `token_efficiency`，**故意仅报告不参与评分**，注释理由是避免 token 用量单独改变质量判定。）

**五个报告维度**：`security` / `correctness` / `discoverability` / `effectiveness` / `efficiency`

**其他公开术语**：

- **Skill Lift** — 核心指标，with/without 两臂的带符号差值
- **routing premium** — `Lift_grp − Lift_iso`
- **pass@k** — 多次尝试的可靠性信号
- **ATIF** — Agent Trajectory Interchange Format，轨迹标准化格式
- **routing** / **tool_efficiency** — `skill_efficiency` 的两个子检查
- **negative case** — 数据集四桶之一

⚠️ **重要：NVIDIA 没有使用 `false trigger rate` / `FTR` / `precision` / `recall` 这套术语。** 我们自造的 `Δ2 = FTR(C) − FTR(B)` 与 NVIDIA 的口径**不直接对齐**。要对齐，应改用其既有语汇（`skill_execution` 的下降、negative case 上的 routing 表现）。

### 数据集四桶（negative case 的官方定位）

出处：`docs/eval-datasets.mdx`「The four case buckets」

| Bucket | Intent |
|---|---|
| Explicit | The user names the skill directly. |
| Implicit | The user describes the task without naming the skill. |
| Contextual | The task appears inside a realistic project scenario. |
| **Negative** | **A request that should not activate the skill.** |

`EVAL.md` 的 `## Negative Cases` 标题可被生成器解析为结构化提示。`--no-llm` 模板模式下 negative 桶默认省略。

---

## 5. 我们能不能直接拿它跑自己的 skill？

**能，但 Tier 3 门槛不低。** 出处：`README.md` Quickstart、`docs/installation.mdx`、`docs/tier3-live-evaluation.mdx`

### 安装（官方推荐 uv）

```bash
uv tool install --python 3.13 "skillevaluator[all] @ git+https://github.com/NVIDIA/SkillEvaluator.git"
```

要求 Python **3.12 或 3.13**（badge 标注）。仓库有 `pyproject.toml` 与 `uv.lock`，是标准 Python 包，**有可执行代码**（`src/skillevaluator/`，含完整 `cli.py`），不是空壳。

### 分档门槛

| 档位 | 门槛 | 对我们 |
|---|---|---|
| **Tier 1 静态** | `skillevaluator tier1 ./my-skill`，**无需模型 key** | ✅ **最低成本可用**。`--tiers 1` 可完全离线、确定性（同输入同退出码），配 `skillevaluator[security]` + Semgrep + SkillSpector + Gitleaks 可得完整证据 |
| Tier 1 + LLM | 需 provider key，跑 rubric-eval（九条量表）与 LLM 安全分析 | ⚠️ 需 key |
| **Tier 2** | embeddings + chat | ⚠️ 需 key |
| **Tier 3** | provider key + 受支持 agent + **运行中的 Docker sandbox** + Harbor | ❌ **重**。需 `docker info` 通过、agent 凭证、`skillevaluator doctor --env-mode docker` 全绿 |

有 `skillevaluator doctor --env-mode docker` 做前置体检，秒级返回缺什么，**不必盲跑烧算力**。

### 对我们的可行性判断

- **可立即做**：Tier 1 静态 Discoverability 扫描（含 "explicit negative/boundary phrasing" 与 description 长度检查）——**零 key 成本**，可直接产出我们 4 个 skill 的分数。
- **成本较高**：Tier 3 live（Docker + key + agent）。若要跑 routing premium 或 negative case 的实测，这是唯一途径。

---

## 6. Q6：它有没有公开「负向条件 vs 触发质量」的量化结论？

### 结论：**部分有，我们必须收窄措辞。**

#### 已经有的（会影响立意）

1. **「写多长」已有官方数值**：**Description length 50–150 preferred；>200 flagged as overlong**（论文正文，结构性 Discoverability 维度，权重 0.25）。
   → 我们原立意说「没公开写多少的量化答案」，**这句在静态层面站不住了**。

2. **「显式负向/边界措辞」已被列为评分项**：`explicit negative/boundary phrasing` 是结构性 Discoverability 的评分标准之一。
   → 我们原立意说「官方只要求写负向条件但没给量化答案」——**前半句成立，但 NVIDIA 确实把它做成了一个加分项**。

#### 仍然空着的（我们的真实空位）

3. **负向措辞对「运行时触发质量」的影响，NVIDIA 没有量化。** 而且论文**自己指出了这个空位的存在**，用的正是我们需要的论证：

   - 结构性分数与 LLM-judge 分数**互相不一致**：Spearman **ρ = 0.14**、Pearson **r = 0.08**（n=145）
   - 默认 70 分门禁**过于宽松**：**94.5%** 的 skill 通过，但只有 **48.9%** 摸到 80 分线
   - 论文原话：*"neither scan-only axis observes discovery, tool use, workflow order, or task success"*
   - 章节标题直接叫 **"Static Scores Are Not Runtime Evidence"**

4. **负向条件的效果只被定性描述，从未被定量**。论文报告 negative case 时给的是**质性分类**而非系数：negative 单元格分两类——执行不稳定 vs 「skill 让 agent 行为朝错误方向改变」（agent 找到/尝试读 skill，却产出截断或元层级回答、跳过验证、多花工具调用而无收益）。论文还区分了 **"never discovered" vs "discovered but misused"**，两者都对文档扫描不可见。

### 对立的净影响：立意应这样改

| 原表述 | 判定 | 建议改为 |
|---|---|---|
| 「官方没公开 description 写多长的量化答案」 | ❌ **已被 NVIDIA 填上**（50–150 preferred） | 承认该数值存在，但指出它是**约定性静态规则、非实证最优**，且与 LLM-judge 判断 ρ=0.14 不一致 |
| 「官方要求写负向条件但没量化其收益」 | ✅ **成立** | 保留，并可升级为：NVIDIA 把负向措辞当**静态加分项**（存在性检查），而**它对 live 误触发率的边际收益从未被测量** |
| 我们自造 `Δ2 = FTR(C) − FTR(B)` | ⚠️ **术语未对齐** | 要么改用 NVIDIA 语汇（`skill_execution` 变化 / negative case 上的 routing），要么明确声明自造并给出与 NVIDIA 口径的换算 |

**一句话**：NVIDIA 补上了「写多少」的静态约定，但**恰恰是它自己的论文证明了静态约定无法预测运行时行为**。我们的空位从「没人回答」变成「NVIDIA 承认这层不可见、但没去测」——**这个说法更弱一点，但因为站在对方论文的实证结论上，反而更难被反驳。**

---

## 7. 参考出处汇总

| 内容 | URL / 路径 |
|---|---|
| 仓库主页与三档总表 | `https://github.com/NVIDIA/SkillEvaluator` → `README.md` |
| Tier 1 文档 | `docs/tier1-validation.mdx` |
| Tier 3 文档 | `docs/tier3-live-evaluation.mdx` |
| 数据集四桶 / negative case | `docs/eval-datasets.mdx` |
| 论文 | `https://arxiv.org/abs/2608.20614`（HTML 全文 `https://arxiv.org/html/2608.20614v1`） |
| 六指标定义 | `src/skillevaluator/tier3/harbor/metrics.py` |
| 维度权重映射 | `src/skillevaluator/constants.py`（`DIMENSION_MAPPING`，L519-549） |
| 五维度判分提示词 | `src/skillevaluator/evaluation/dimension_judge.py` |
| 结构性质量评分实现 | `src/skillevaluator/validators/quality_score.py` |
| 九条量表判分 | `src/skillevaluator/validators/rubric_eval.py` |
| NVIDIA Verified Skills 流水线 | `https://github.com/NVIDIA/skills` |
| Tier 1 安全扫描器 | `https://github.com/NVIDIA/SkillSpector` |
| Tier 3 sandbox 底座 | `https://github.com/harbor-framework/harbor` |
