# DGX Spark Agent Skills

> 第三届 NVIDIA DGX Spark 黑客松 · Agent Skills 开发挑战赛 参赛作品

## 项目简介

一套**跑在笔记本上的本地三层视觉巡检系统**，交付 **4 个 Agent Skills**（1 编排 + 3 窄触发子技能），
场景是**电子厂洁净车间的着装合规检查**（防尘帽 / 防静电服）。

系统按**「便宜层先判、贵层只在必要时介入」**分级路由：无人的帧在 Tier 0 直接短路，
不进颜色启发式、也不调用本地视觉模型。

> 完整立意、场景定义与全部决策见 `docs/agents/decision-log.md`；交付说明见 `docs/DELIVERY.md`。

## 快速开始

> 本节命令**逐条取自 `docs/DELIVERY.md` §5**，未自行编写。DELIVERY 中标注为 `[未验证]` 的条目在此沿用同一标注。

### 环境要求 `[来源: docs/DELIVERY.md §5.1；docs/local_tier_benchmark.json 的 meta]`

- **Windows**（本项目在 Windows 11 上开发与验证）
- **Python 3.12**（实测 3.12.10）。本机默认 `python` 为 3.14，请显式使用 `py -3.12`
- **NVIDIA GPU（必需）**：本地三层流水线需要 CUDA。实测环境为 **RTX 5060 Laptop GPU**
  （compute capability 12.0 / sm_120，显存总量 8150.6 MiB，驱动 591.91）
- **权重不随仓库分发**（单文件超 GitHub 限制，已在 `.gitignore` 中排除）——
  **需先下载**：先跑 `scripts/fetch_ms.sh`（推荐通道），再跑 `scripts/fetch_yolo.sh` 取 YOLO 权重。
  下载完成后，本地三层流水线可**完全离线运行**。备用通道 `scripts/fetch.sh`（备用候选 `scripts/fetch_smol.sh`）
- 联网**仅在下载权重与启用 Tier 2（云端）时需要**，后者需有效的 StepFun API Key

### 安装（步骤 0 下载权重；步骤 1–2 依赖安装**必须分两步**）`[来源: docs/DELIVERY.md §5.2；步骤 0 取自 scripts/ 下脚本自身]`

只跑 `pip install -r requirements.txt` 会装到 PyPI 的 **CPU 版 torch**，本地三层流水线用不上 GPU。

```bash
# 步骤 0 · 下载权重（不入库，必须先做）
bash scripts/fetch_ms.sh
bash scripts/fetch_yolo.sh

# 步骤 1 · CUDA 版 torch（必须指定 cu128 专用索引）
./.venv/Scripts/pip install torch torchvision \
    --index-url https://download.pytorch.org/whl/cu128

# 步骤 2 · 其余依赖（requirements.txt，共 8 项）
./.venv/Scripts/pip install -r requirements.txt
```

> 步骤 2 之后请确认 `torch.__version__` 仍带 **`+cu128`** 后缀；后缀消失说明被 CPU 版覆盖，重跑步骤 1。
>
> `[未验证]`：上面各条命令**未从零重跑**（虚拟环境与权重均已存在）；`py -3.12 -m venv .venv` 建环境命令同样 `[未验证]`。

### 配置 `[来源: docs/DELIVERY.md §5.3]`

在项目根目录创建 `.env`，需要三个变量（**本仓库不写入任何真实凭据**）：

| 变量名 | 用途 |
|---|---|
| `STEPFUN_API_KEY` | StepFun API 凭据 |
| `STEPFUN_BASE_URL` | API 端点。国内站 `https://api.stepfun.com/v1`；国际站 `https://api.stepfun.ai/v1` |
| `STEPFUN_MODEL` | 主力模型名（`step-5-preview`） |

> **不配 `.env` 也能跑本地三层流水线** —— 本次三张照片的实测即为 `cloud_authorized=False` 的纯本地运行。

### 运行

| # | 用途 | 命令 | 状态 |
|---|---|---|---|
| ① | 本地三层流水线 | `skills/safety-hazard-detection/scripts/local_tier_pipeline.py`（参数以脚本内 `argparse` 为准） | `[未验证]` |
| ② | 合规校验（交付门禁） | `./.venv/Scripts/agentskills.exe validate skills/gauge-reading` | `[已实测]` 4/4 通过，退出码 0 |
| ③ | 端到端最小通路 | `py -3.12 skills/evals/run_e2e.py`（`--offline` 跳过 API 调用） | `[未实测]` |
| ④ | 四臂对照评测 | `py -3.12 skills/evals/run_comparison.py --arm B --runs 3 --out skills/evals/results/out-b.json` | `[未实测]` |
| ⑤ | 逐层性能基准复现 | `py -3.12 skills/evals/bench_layers.py --layer <tier0\|tier0_5\|tier1>` | `[来源: docs/local_tier_benchmark.md]` |

> ⚠️ **①未核实具体命令行参数**，故不给示例命令以免误导。
> ⚠️ **③会写入 `skills/evals/results/`，曾覆盖过 `a4-baseline.json`**（决策日志 D-012）。运行前请先备份该目录。
> 🔴 **④的 `--concurrency` 必须 ≤ 5**。脚本默认值为 8，但本账户实测并发上限为 5，超出会大量触发 429。
>
> `[来源: docs/DELIVERY.md §5.4、§5.5；D-010 / D-012 / D-017]`

## 三层架构与各层状态

请求自下而上逐层升级，**每层都可以短路**——便宜层能定案，就不进贵层。

| 层 | 组件 | 载体 | 职责 | 状态 |
|---|---|---|---|---|
| **Tier 0** | YOLO11n | 本地权重（不入库，见快速开始） | 人形定位与计数；**无人的帧直接短路** | **已实现** |
| **Tier 0.5** | 颜色-几何启发式 | 纯代码，零模型依赖 | 着装颜色初筛 | **已实现** |
| **Tier 1** | Qwen3-VL-2B | 本地权重（不入库，见快速开始） | 本地视觉判读，确认或推翻 Tier 0.5 | **已实现** |
| **Tier 2** | StepFun `step-5-preview` | 云端 API | 多目标冲突 / 成文措辞 | **已实现；本次运行未启用云端授权** |

> **Tier 0 不认识任何 PPE 类别。** COCO 版 yolo11n 没有「防尘帽 / 防静电服」类别，
> 它的职责**仅为**人形定位与计数，**不作为 PPE 判定依据**。`[来源: docs/local-tier-limitations.md]`

### 逐层性能基准 `[来源: docs/local_tier_benchmark.json / docs/local_tier_benchmark.md]`

> ⚠️ **逐层延迟与显存数字的唯一来源是 `docs/local_tier_benchmark.json`。**
> 它与 `docs/local_tier_metrics.json` **各管一摊**：**本表管延迟 / 显存**，
> metrics 文件管 **`tier_calls` 各层调用次数**。**两者数字不得互相引用、不得混用**（且不属于同一轮，见文末）。

| 层 | 冷启动 `[min, max]` | 稳态单次 `[min, max]`（3 次运行 × 5 样本 = 15） | 显存 after_load / peak / after（MiB） |
|---|---|---|---|
| **Tier 0**（YOLO11n，GPU） | **[3.976, 4.147] s** | **[14.29, 51.42] ms** | 42.1 / **59.8** / 42.1 |
| **Tier 0.5**（启发式，CPU，无模型） | **[1.862, 1.894] s** | **[16.12, 18.58] ms** | `null`（纯 CPU，不占显存） |
| **Tier 1**（Qwen3-VL-2B bf16，GPU） | **[19.362, 20.638] s** | **[9046.6, 10603.29] ms**（≈ 9.05 – 10.60 s） | 4059.0 / **4546.9** / 4096.3 |
| **Tier 2**（StepFun 云端） | — | — | — |

**口径说明——冷启动与稳态不可合成一个数**：

- **冷启动** ＝ 从**进程启动**（模块 import 时刻）到该层**首次产出结果**，含解释器启动、import、
  CUDA 初始化、模型加载、首次推理。
- **稳态** ＝ 模型已加载后的单次调用。
  两者差几个数量级（如 Tier 0：冷启动约 4 s 对稳态约 15 ms），**合成一个数即失去意义**。

**波动与已知异常（有多少报多少，不掩盖）**：

- 🔴 **Tier 0 的稳态区间是双峰的，且可解释**：每个进程内**第 1 次稳态调用恒为 ~43–51 ms**，
  第 2 次起落到 **~14–16 ms**，三个进程各自复现。这是**进程内首次调用仍受 CUDA 分配器 / 图预热影响的
  系统性现象，不是随机离群**。上表区间**已包含该效应、未剔除**——因为它会真实地出现在每个新进程的第一次调用上。
  **若只关心完全预热后的值，参考区间为 [14.29, 17.41] ms。**
- Tier 0.5 极稳：15 个样本全落在 [16.12, 18.58]，无预热效应（纯 CPU 无状态）。
- Tier 1 稳态极差 1556.69 ms（相对波动约 17%）；生成长度固定 180 tokens（`max_new_tokens=200`），
  故波动来自推理本身而非输出长度差异。

**显存（MiB，`1024^2` 字节）——一条诚实的警示**：

- **Tier 1 推理后显存未完全回落**：`after` 4096.3 MiB 比 `after_load` 4059.0 MiB **高 37.3 MiB**。
  文件定性为 **PyTorch 分配器缓存所致，非必然泄漏**，并建议**长跑前加监控**。
- **Tier 0 推理后完全回落**（42.1 → 42.1 MiB），无残留。
- Tier 0.5 三个显存字段一律 `null`：**不估算、不填 0**。

> **脚注（口径差异，非数字对不上）**：早前文档中的 Tier 0「约 90 MB」为 `reserved` 口径，
> 本表 **59.8 MiB** 为 `max_memory_allocated` 口径，**两者不可直接比较**。

**测量条件**：**每层独立进程**运行——同进程会让三层共占显存并互相污染加载耗时。
环境：RTX 5060 Laptop GPU（sm_120）· torch 2.11.0+cu128 · Python 3.12.10 · Windows 11。
复现：`py -3.12 skills/evals/bench_layers.py --layer <tier0|tier0_5|tier1>`；
原始样本 `skills/evals/bench_raw_tier0.json` · `bench_raw_tier0_5.json` · `bench_raw_tier1.json`。

**Tier 2 不列性能数字**：本轮云端调用 **0 次**，无实测依据。

> ✅ **同轮声明**：benchmark 文件的 `meta.same_machine_same_round` = **`true`**——
> 三层为**同一台机、同一轮**完成，**下游可引用本表**。
> 🔴 **但基准轮与 `tier_calls` 那一轮不是同一轮**，故**本表数字与下方调用次数不得交叉引用**。

### 分层效果（确定性指标）`[来源: docs/local_tier_metrics.json]`

三张实拍照片的**逐层调用次数**——这是确定性指标，不受机器负载影响：

| 照片 | Tier 0 | Tier 0.5 | Tier 1 | Tier 2 | findings | 短路 |
|---|---|---|---|---|---|---|
| photo1 | 1 | 1 | 1 | 0 | 6 | — |
| photo2 | 1 | 1 | 1 | 0 | 1 | — |
| photo3 | 1 | **0** | **0** | 0 | 0 | **`no_person`：未进入 Tier 0.5，未调用 Tier 1** |
| **合计** | **3** | **2** | **2** | **0** | **7** | — |

photo3 在 Tier 0 判定无人即短路——**不是把模型跑得更快，而是根本不跑**。
墙钟时间上，无人帧与走完全程的帧**相差约两个数量级**（单次点测 0.11–0.16 s 对 14.35–25.2 s）。
> ⚠️ **墙钟时间会波动，不作为对外指标引用**；三次重跑合计 **23.11 / 23.67 / 33.68 s**。
> `[来源: docs/local_tier_variance.jsonl]`

### Tier 2 本次未调用——原因需说清 `[来源: docs/local_tier_metrics.json 的 note 字段]`

`tier2_used: false`，全轮 Tier 2 调用 **0 次**。但原因**不是**「路由器判断不需要」，
而是**本次运行 Tier 2 未获授权**（`cloud_authorized=False`），`route.enforce_safety_boundary` 会将其**压回本地**。

> **本次运行未启用云端授权，Tier 2 通路未被触发、也未被验证。因此本次数据不能用于说明「云端按需触发」的效率。**

### 关于「适配 DGX Spark」

本流水线跑在**笔记本（RTX 5060 Laptop / Windows）**上，是**同架构的受限版**。
我们**未申请到 DGX Spark 云节点**，因此按**可伸缩架构**设计：三层分级、每层可独立替换载体。
**本版本未在 DGX Spark 上实测**，文档统一表述为「边缘优先，架构可平移」。`[来源: docs/DELIVERY.md §3.4]`

## 核心实验结果（四臂消融）

实验已跑完：**40 条用例 × 4 臂 × 3 次重复 = 480 次调用**，实测成本 **12.34 元**。

| 指标 | A 臂（不加载 skill） | B 臂（全量） | C 臂（删 Not-for 段） | D 臂（仅 description） |
|---|---|---|---|---|
| 触发准确率 | 0.550 | **0.975** | 0.900 | 1.000 |
| 结论正确率 | 0.167 | **1.000** | 1.000 | 0.167 |
| 编造量程数 | **4**（FAIL） | 0 | 0 | 0 |
| 幻觉项数 | **19**（FAIL） | 0 | 0 | 0 |
| 幽灵技能调用次数 | **76** | 0 | 0 | 0 |

**结论（如实陈述，含零结果）**：

- **Δ1 = B − A 显著为正**——加载 skill 相对不加载，触发准确率 +0.425、结论正确率 +0.833，
  且 A 臂触发硬门禁失败（编造量程 4、幻觉项 19、点名 76 次不存在的技能）。
- **Δ2 = FTR(C) − FTR(B) = 0.000**（本技能口径，负例样本 16/16 完整，可靠性判定「可靠」）。
  即：**在本次样本上，删除 `不适用于：` 段未观测到差异——这是一个零结果，既不支持也不否定 Not-for 段的作用**，
  不能表述为「负向条件带来净收益」。三种聚合口径（majority / any / all）下 Δ2 均为 0。
- 广义口径（任何技能被误调用即算）下 Δ2 = **0.125**（B 0.062 → C 0.188），与主口径**不可混用、不可相减**。

> ⚠️ **Δ2 与 NVIDIA 语汇的 `Skill Lift` 不是同一轴**：Skill Lift 对照「加载 / 不加载 skill」（本评测对应 Δ1），
> Δ2 是同一 skill 内部的 description 变体对照。**两者不可等同、不可相加，也不能把 Δ2 当作 Skill Lift 报出去。**
>
> `[来源: skills/evals/results/report.md；skills/evals/results/variance-log.md]`

## 交付物指引

| 交付物 | 位置 |
|---|---|
| **4 个 skill**（本赛核心交付物） | `skills/inspection-orchestrator/` · `safety-hazard-detection/` · `gauge-reading/` · `inspection-report/` |
| **权重下载脚本**（不入库，跑前必做） | `scripts/fetch_ms.sh` · `scripts/fetch_yolo.sh`（备用 `scripts/fetch.sh` · `scripts/fetch_smol.sh`） |
| **交付说明**（技术栈 + 部署 + 安全设计） | `docs/DELIVERY.md` |
| **产品需求与实现状态** | `docs/PRD.md` |
| **逐层性能基准**（冷启动 / 稳态 / 显存，机器可读） | `docs/local_tier_benchmark.json` · `docs/local_tier_benchmark.md` |
| **逐层基准复现脚本 + 原始样本** | `skills/evals/bench_layers.py` · `skills/evals/bench_raw_tier0.json` · `bench_raw_tier0_5.json` · `bench_raw_tier1.json` |
| **逐层调用次数**（`tier_calls`，机器可读） | `docs/local_tier_metrics.json` |
| **墙钟方差证据**（三次重跑） | `docs/local_tier_variance.jsonl` |
| **流水线逐帧结果**（三张照片的完整 findings） | `skills/evals/pipeline_results.json` |
| **四臂评测结果** | `skills/evals/results/{A,B,C,D}.json`、`report.md`、`diagnostics.json`、`variance-log.md` |
| **评测设计 / 指标定义 / 合规门禁** | `skills/evals/comparison-design.md` · `metrics.json` · `check-compliance.md` |
| **能力边界说明** | `docs/local-tier-limitations.md` |
| **演示视频脚本** | `docs/demo-script.md`（**脚本已就绪；视频成片未落盘入库**） |
| **赛事征文草稿** | `docs/article-draft.md` |
| **决策日志 / ADR** | `docs/agents/decision-log.md` · `docs/adr/` |

## 诚实的局限

本节只列结论，**完整清单与依据见 `docs/DELIVERY.md` §8**。

1. **未在 DGX Spark 上实测** —— 未申请到节点，本版本是笔记本上的同架构受限版（见上）。
2. **不可检测项**：通道堵塞、设备渗漏、明火烟雾、未戴手套 / 口罩——Tier 0 与 Tier 0.5 均**无此判据**；
   本流水线**不做仪表读数**（读数由 `gauge-reading` 负责）。**表上一个 ❌，就是演示里一句不能说的话。**
3. **Tier 0.5 对白色着装召回为 0**（白色掩膜覆盖率 11.7%、17 个噪声连通块）——
   「没找到」不构成未佩戴 PPE 的证据，这是**能力边界，不是调参能解决的**。
4. **本轮没有下任何最终结论**：7 条 findings **全部为 `uncertain`**，置信度区间 **0.000–0.463**，全部低于 0.75 阈值。
5. **精确人数不可宣称**：photo1 上 YOLO 报 6 人、Tier 1 VLM 报 5 人，未逐像素人工复核，无法裁决谁对。
6. **测试素材是程序合成的**：四臂消融用的测试图是用 Pillow 画的示意图，
   仓库标注 `usable_as_accuracy_evidence: false`，**不能作为识别准确率的证据**。
7. **Tier 1 显存未完全回落**（推理后 +37.3 MiB，疑为分配器缓存，非必然泄漏）——**长跑前建议加监控**。
8. **零结果如实呈现**：Δ2 = 0.000（见上），本样本未观测到 Not-for 段的边际收益。
9. **团队无行业背景、无专有数据**，全部使用公开数据；**不主张任何生产环境下的落地效果**。

### 关于测试素材的声明

**测试素材为真实车间照片；因涉及肖像权（画面含可辨认的工人人脸，当事人未同意公开发布），
我们刻意不公开该素材**——照片仅在本地实验中用于验证链路，**公开仓库不含任何含人脸的素材**。
本节第 6 条所述的合成示意图是另一类素材，可随仓库分发。

## 真值来源声明

**本 README 中出现的每一个性能 / 评测数字，均可回溯到下列已落盘文件。未落盘的数字一律未写入。**
评委可按此清单逐项核查：

| 数字类别 | 落盘文件 |
|---|---|
| 逐层冷启动 / 稳态延迟 / 显存 / 吞吐条件 | `docs/local_tier_benchmark.json`（原始样本 `skills/evals/bench_raw_tier0.json` 等） |
| 逐层调用次数、Tier 2 授权状态、短路原因 | `docs/local_tier_metrics.json` |
| 墙钟时间（三次重跑区间） | `docs/local_tier_variance.jsonl` |
| 四臂 13 项指标、Δ1 / Δ2、敏感性分析、硬门禁判定 | `skills/evals/results/report.md`、`diagnostics.json` |
| 逐臂逐次原始结果 | `skills/evals/results/{A,B,C,D}.json` |
| token / 成本 / 方差 | `skills/evals/results/variance-log.md` |
| findings 条数与 severity 计数、置信度区间 | `skills/evals/pipeline_results.json`（统计方法见 `docs/DELIVERY.md` §4） |
| 用例构成（40 = 正向 21 / 负向 16 / 空结论 3） | `skills/README.md` §6、各 skill 的 `evals/cases.jsonl` |
| 依赖清单（8 项） | `requirements.txt` |
| 环境（Python 3.12.10、RTX 5060 Laptop、torch 2.11.0+cu128） | `docs/local_tier_benchmark.json` 的 `meta`、`docs/DELIVERY.md` §5.1 |

**口径纪律**（引用时请一并遵守）：

- **墙钟时间只给区间，不给单点**——同配置重跑的数值不得互相套用。
- **冷启动与稳态分列，不合成一个数**——两者口径不同，混合后失去意义。
- **延迟一律报 `[min, max]` 区间**，不得用「约」掩盖波动，也不得隐去已知异常
  （如 Tier 0 每进程首次调用的 ~43–51 ms）。
- **逐层延迟 / 显存只引 `docs/local_tier_benchmark.json`；各层调用次数只引 `docs/local_tier_metrics.json`**
  ——两文件各管一摊，**不得交叉引用数字**，且二者**不属于同一轮测量**。
- **加速比只说「相差约两个数量级」**，不报单点倍数。
- **Δ2 只在「本技能口径」下作为主结论**；广义口径数字单列，两者不可相减。
- 未在真值来源文件中落盘的数值，本 README 一律未引用。

## 竞赛信息

- **截止日期**: 2026年9月29日 23:59
- **总决赛**: 2026年10月15日（苏州金鸡湖）
- **奖品**: 冠军获得华硕 Ascent GX10 + StepPlan Max（价值6666元）

## 项目结构

```
.
├── skills/                       # ← 本赛核心交付物
│   ├── inspection-orchestrator/  #   编排：决定调谁、定层级
│   ├── safety-hazard-detection/  #   窄触发：图像 → 隐患标签（含本地三层流水线）
│   ├── gauge-reading/            #   窄触发：表盘 → 一个数
│   ├── inspection-report/        #   窄触发：结论 → 报告
│   └── evals/                    #   顶层四臂消融套件（A/B/C/D，40 条用例）
│       ├── run_comparison.py     #     评测执行器（--concurrency 必须 ≤ 5）
│       ├── run_e2e.py            #     端到端最小通路 + token 采集
│       ├── bench_layers.py       #     逐层性能基准复现脚本
│       ├── bench_raw_tier*.json  #     基准原始样本
│       ├── pipeline_results.json #     三张照片的完整 findings
│       └── results/              #     逐臂结果 JSON + 报告（随仓库提交）
├── scripts/
│   ├── fetch_ms.sh               #   权重下载（推荐通道，ModelScope）
│   ├── fetch_yolo.sh             #   YOLO 权重下载
│   ├── fetch.sh                  #   备用通道
│   └── fetch_smol.sh             #   备用候选
├── docs/
│   ├── DELIVERY.md               # 交付说明（技术栈 + 部署 + 安全设计 + 局限）
│   ├── PRD.md                    # 产品需求与实现状态
│   ├── local-tier-limitations.md # 能力边界说明
│   ├── local_tier_benchmark.json # 逐层性能基准（机器可读，唯一真值来源）
│   ├── local_tier_benchmark.md   # 逐层性能基准（人读）
│   ├── local_tier_metrics.json   # 逐层调用次数（机器可读）
│   ├── local_tier_variance.jsonl # 墙钟方差证据
│   ├── demo-script.md            # 演示视频脚本
│   ├── article-draft.md          # 赛事征文草稿
│   ├── agents/                   # 决策日志、情报、团队分工
│   └── adr/                      # Architecture Decision Records
├── requirements.txt              # 依赖清单（8 项，需两步安装）
├── CONTEXT.md                    # 项目上下文和背景
└── CLAUDE.md                     # Claude Code 配置
```

> **不入库内容**（已在 `.gitignore` 中排除，理由见该文件注释）：
> ① 模型权重（单文件超 GitHub 限制）——用 `scripts/fetch_ms.sh` + `scripts/fetch_yolo.sh` 获取；
> ② 含可辨认人脸的实拍素材（肖像权，当事人未同意公开发布）；
> ③ `.env` 等凭据文件；④ `.venv/`、`.scratch/` 等本地环境与暂存区。

## 开发工作流

1. 在 GitHub Issues 中创建任务
2. 使用 Claude Code 和工程技能开发
3. 提交代码到 GitHub
4. 定期更新文档和演示视频

## 相关链接

- **GitHub 仓库**: https://github.com/majiantong58-collab/dgx-spark-agent-skills
- **NVIDIA 开发者社区**: https://developer.nvidia.com
- **NVIDIA 中国开发者日**: 10月15日（苏州金鸡湖会展中心）
