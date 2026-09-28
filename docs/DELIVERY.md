# 交付说明文档 — 巡检 Agent Skills 套件

> 第三届 NVIDIA DGX Spark 黑客松 · Agent Skills 开发挑战赛
> 状态：§1–§6、§8 已完成；**§7 未完成——实验被基础设施阻塞，不是零结果**（见 §7）
> 场景：**电子厂洁净车间 · 着装合规**（v2）

**标注约定**
`[已实测]` = 本文档作者在本机实际执行并观察到结果；`[来源: 文件:行号]` = 从仓库读到、未实际执行；
`[落盘]` = 数字取自仓库内的指标文件；`[未验证]` = 既未实测也无仓库依据。

> **逐层性能数字的唯一真值来源**：`docs/local_tier_benchmark.json` / `.md`。
> 其他文档一律**引用**该文件，不得各写各的。（早期 `[未落盘]` 标记已**全部清除**。）

---

## §1 项目简介

官方 Agent Skills 规范要求 skill 的 `description` 写明「不适用于什么」，但**从未公开量化它对运行时误触发率的边际收益**。本项目**设计并预注册**了消融实验以补这个空白：同一套 skill、多组 description 变体，测负向条件带来的净收益 Δ2。

> ⚠️ **本交付不提供 Δ2 数值。** 原四臂实验的 C 臂操作**未真正施加**，结果不可解释；
> 重做版（五臂 · 690 次调用）**已预注册、执行器就绪，但未运行**。
> 因此本节描述的是**实验设计**，不是已完成的结论。详见 §7 与
> `skills/evals/ablation-v2/STATUS.md`。

**电子厂洁净车间的着装合规检查**是**场景载体**，让方法不抽象、可演示；**量化方法本身才是本项目的贡献主体**。本项目**不主张**行业 know-how 优势，**不承诺**真实产线落地效果。

---

## §2 技术栈说明

### 2.1 本地推理栈（三层，全部在本机跑通）

| 项 | 形态 | 作用 | 依据 |
|---|---|---|---|
| **YOLO11n** | 本地 `.pt`，`models/yolo11n.pt` | **Tier 0**：人形定位与计数 | `[已实测]` 权重文件存在 |
| **颜色-几何启发式** | 纯代码，零模型依赖 | **Tier 0.5**：着装颜色初筛 | `[来源: local-tier-limitations.md:6]` |
| **Qwen3-VL-2B** | 本地 `models/Qwen3-VL-2B-Instruct/` | **Tier 1**：本地视觉判读 | `[已实测]` 权重文件存在 |

> **Tier 0 不认识任何 PPE 类别。** COCO 版 yolo11n 没有「防尘帽 / 防静电服」类别
> （也没有「安全帽 / 反光衣」）。它的职责**仅为**人形定位与计数，**不作为 PPE 判定依据**。
> `[来源: local-tier-limitations.md:60-63]`

### 2.2 云端与工具链

| 项 | 版本 / 形态 | 作用 | 依据 |
|---|---|---|---|
| **StepFun `step-5-preview`** | 云端 API | **Tier 2**：多目标冲突 / 成文报告（**本次未调用**，见 §3.3） | `[来源: .env:STEPFUN_MODEL]`、D-010 |
| **Python** | **3.12.10** | 运行时。本机默认 Python 为 3.14，故显式用 `py -3.12` | `[已实测]` `py -3.12 -V` |
| **`.venv`** | 项目虚拟环境 | 内含官方校验器 CLI `agentskills.exe`；含 `torch 2.11.0+cu128` / `torchvision 0.26.0+cu128` / `transformers 5.17.0` / `ultralytics 8.4.159` | `[已实测]` `ls .venv/Lib/site-packages/` |
| **Agent Skills 规范** | `SKILL.md` + `scripts/` + `references/` + `evals/` | skill 的四件套结构 | `[来源: skills/README.md:55-63]` |
| **NVIDIA `skills-ref`** | PyPI 包 | frontmatter 合规校验（交付门禁） | `[来源: skills/evals/check-compliance.md:3-19]` |
| **NVIDIA `SkillEvaluator`** | **v0.3.0** | 静态质检（**零 API 成本**）；Tier 3 live 评测已裁决不做 | D-016 |

> ✅ **`requirements.txt` 已补齐**：`transformers` / `ultralytics` 已列入；
> `torch` / `torchvision` 因需 **cu128 专用索引**，改为**两步安装**，见 §5.2。
> 此前「照清单从零安装无法复现本地流水线」的缺口**已修复**。
> `[已实测]` 索引 `https://download.pytorch.org/whl/cu128` 返回 **HTTP 200**；`.venv` 实装 `torch 2.11.0+cu128`。

### 2.3 交付的 8 个 skill（巡检组 1 编排 + 3 窄触发 ｜ MES 组 4）

**巡检组**（场景：电子厂洁净车间着装合规）

| skill | 职责（一句话） |
|---|---|
| `inspection-orchestrator` | **编排**：决定调谁、定层级 |
| `safety-hazard-detection` | **窄触发**：图像 → 隐患标签 |
| `gauge-reading` | **窄触发**：表盘 → 一个数 |
| `inspection-report` | **窄触发**：结论 → 报告 |

**MES 组**（把巡检发现落成 MES 里的业务动作；接口真源 `docs/agents/mes-bridge-contract.md`）

| skill | 职责（一句话） |
|---|---|
| `mes-business-rules` | **知识层**：部门映射 / 单据号规则 / 隔离语义（含 `[团队自定]` 标注） |
| `mes-inspection-intake` | **窄触发**：发现 → 异常单（产出 `inbox.json` + `xj-records.json`） |
| `mes-record-query` | **窄触发**：查工单 / 设备 / 异常单；**单据号查重** |
| `mes-closed-loop` | **编排**：识别→判级→落单→回执 的窄路由（**只路由不干活**） |

> MES 组的「最小可复现宿主页」在 `docs/mes-demo/`（`python -m http.server` 三条命令跑通）。

---

## §3 本地三层流水线

### 3.1 架构与各层职责

请求自下而上逐层升级，**每层都可以短路**——便宜层能定案，就不进贵层。

| 层 | 载体 | 职责 | 结论权限 |
|---|---|---|---|
| **Tier 0** | YOLO11n（本地） | 人形定位与计数；**未检出人形框的帧直接短路**（≠「画面无人」，见 §8.2⑪） | 不下结论 |
| **Tier 0.5** | 颜色-几何启发式 | 着装颜色初筛，给「有正面证据 / 无证据」（当前站点参数**仅配蓝色区间**，见 §8.2①） | 仅在 `conf ≥ 0.75` 时下 `info`。**未打码照片上 7 条全为 `uncertain`**（最高 0.4632）；**打码后有一条达 0.7525 → 输出过 `info`**（见 §4 末） |
| **Tier 1** | Qwen3-VL-2B（本地） | 视觉判读。**设计意图**：确认或推翻 Tier 0.5。**当前实现**：输出只挂结果顶层，**不参与判定链路**（§8.2⑩） | **不下结论**（当前实现） |
| **Tier 2** | StepFun `step-5-preview`（云端） | 多目标冲突 / 成文措辞 | 可下结论（本次未授权、未触发、未验证，见 §3.3） |

### 3.2 实测数据

**逐层调用次数**（**确定性指标**，取自 `docs/local_tier_metrics.json`，三张实拍照片）：

| 照片 | Tier 0 | Tier 0.5 | Tier 1 | Tier 2 | findings | 短路 |
|---|---|---|---|---|---|---|
| photo1 | 1 | 1 | 1 | 0 | 6 | — |
| photo2 | 1 | 1 | 1 | 0 | 1 | — |
| photo3 | 1 | **0** | **0** | 0 | 0 | **`no_person`：未进入 Tier 0.5，未调用 Tier 1** |
| **合计** | **3** | **2** | **2** | **0** | 7 | — |

`[落盘] docs/local_tier_metrics.json`

**分层收益的机制**：photo3 在 **Tier 0 即未检出人形框 → 直接短路**，既没有进 Tier 0.5，**也没有调用 Tier 1 的视觉模型**。这就是分层省下的成本——**不是把模型跑得更快，而是根本不跑**。

> ✅ **该短路路径曾同时承载检测器故障，现已分开**（2026-09-28 修复）：
> `_yolo_person_boxes(strict=True)` 在 `ultralytics` 未安装或权重缺失时抛
> `DetectorUnavailable`；管线捕获后写**另一条** `short_circuit` 码
> （`tier0_unavailable: …`，且 `tier_calls.tier0` 记 **0**，不记成「跑过」），
> 界面显示「**未能运行**」并注明「这不代表画面里没有人」。
> **「确实无人」与「检测器没跑起来」现已在数据层与界面层都能分开。**
> `[来源: local_tier_pipeline.py:122-133；ui/index.html:482,859,891]`　详见 §8.2⑪。

**墙钟时间（记录值，3 张照片）**：**0.11 – 25.20 s**；三张合计 **23.11 – 33.68 s**。
> ⚠️ **墙钟时间会波动，不作为对外指标引用**；**对外请引用上表的 `tier_calls`**（确定性）。
> `[落盘] docs/local_tier_variance.jsonl`（**只追加台账**，三轮 v2 运行的区间；`docs/local_tier_metrics.json` **只记单次点测**，不给区间）

### 3.2.1 逐层基准（**唯一真值来源**）

> 本节数字**一律取自** `docs/local_tier_benchmark.json` / `.md`（2026-09-27 重跑版）。
> **其他文档一律引用此处，不得各写各的。**
> **`meta.same_machine_same_round = true`**——同一台机、同一轮完成，**可直接引用**。
> **两个时间口径不可混成一个数**：冷启动几秒、稳态几十毫秒，**差好几个数量级**。
> 全部为 **`[min, max]` 区间**，不给单点。

| 层 | 组件 | `cold_start_s` | `steady_state_ms` | `runs` / 样本 |
|---|---|---|---|---|
| **tier0** | YOLO11n（COCO person 检测, GPU） | **[3.976, 4.147]** | **[14.29, 51.42]** | 3 / 15 |
| **tier0_5** | 颜色/几何启发式（CPU，无模型） | **[1.862, 1.894]** | **[16.12, 18.58]** | 3 / 15 |
| **tier1** | Qwen3-VL-2B-Instruct bf16（GPU） | **[19.362, 20.638]** | **[9046.6, 10603.29]**（≈ **9.05–10.60 s**） | 3 / 15 |

**显存（MiB）**：

| 层 | `after_load` | `peak` | `after` |
|---|---|---|---|
| **tier0** | 42.1 | **59.8** | 42.1 |
| **tier0_5** | `null` | `null` | `null`（纯 CPU，**不估算、不填 0**） |
| **tier1** | 4059.0 | **4546.9** | **4096.3** |

**口径定义**：`cold_start_s` = 从**进程启动**到首次出结果（含解释器启动、import、**CUDA 初始化**、
模型加载、首次推理）；`steady_state_ms` = **模型已加载后**单次调用墙钟。三层**各自独立进程**。

> ✅ **Tier 0 稳态区间是双峰的，且原因已查清——不是随机离群，是系统性现象**：
> **每个进程内稳态第 1 次调用恒为 ~43–51 ms，第 2 次起落到 ~14–16 ms**；
> 三个进程**各自复现**（首值 44.08 / 42.78 / 51.42 ms）。
> 这是**进程内首次调用仍受 CUDA 分配器 / 图预热影响**。
> **口径二选一，两个都给**：
> - **含预热 `[14.29, 51.42]`** —— 保守，**对外推荐用这个**（区间已含该效应，未剔除）
> - 完全预热后 **`[14.29, 17.41]`**
> `[落盘] docs/local_tier_benchmark.md` §「波动说明」

> 💡 **`vram_after_mb` 是「能否长跑」的证据**：
> tier0 推理后**完全回落到加载后水平**（42.1），**无累积**；
> **tier1 推理后 4096.3，比加载后的 4059.0 高 37.3 MiB，未完全回落**
> （PyTorch 分配器缓存所致，**非必然泄漏**）→ **长跑前建议加显存监控**。

**tier0_5 极稳**：15 样本全落在 `[16.12, 18.58]`，**无预热效应**——验证了「纯 CPU 无状态」的预期。
**tier1 波动**：稳态极差 **1556.69 ms**，相对约 **17%**；**生成长度固定 180 tokens**
（`max_new_tokens=200`），故波动**来自推理本身而非输出长度差异**。

**模型体积**：`yolo11n.pt` **5,613,764 B**；Tier 1 模型目录 **4,266,649,720 B**（13 文件）。
**本次环境**：RTX 5060 Laptop / **sm_120 (12,0)** / 显存总量 **8150.6 MiB** / 驱动 **591.91** /
`torch 2.11.0+cu128` / Python 3.12.10 / Windows 11。

### 3.3 Tier 2 本次未调用——**原因需要说清**

`tier2_used: false`，全轮 **Tier 2 调用 0 次**。

但**原因不是「路由器判断不需要」**，而是：**本次运行 Tier 2 未获授权**（`cloud_authorized=False`），
`route.enforce_safety_boundary` 会将其**压回本地**。

`[落盘] docs/local_tier_metrics.json` 的 `note` 字段原话：
> 「Tier 2 未授权（cloud_authorized=False），route.enforce_safety_boundary 会将其压回本地；实测 tier2 调用为 0。」

`[来源: skills/inspection-orchestrator/scripts/route.py:73,217；tier_budget.py:99-105]`
（`cloud_authorized` 默认 `False`；未授权一律不放行，policy §3 硬约束。）

> **因此不能表述为「云端按需触发、本次无需」。** 本次是**授权关闭下的纯本地运行**。
> 这恰好也验证了安全边界生效——但它**没有**验证 Tier 2 的路由触发逻辑。
>
> **本次运行未启用云端授权，Tier 2 通路未被触发、也未被验证。因此本次数据不能用于说明「云端按需触发」的效率。**

### 3.4 关于「适配 DGX Spark」

本流水线跑在**笔记本（RTX 5060 Laptop 8 GB / Windows）**上，是**同架构的受限版**。

我们**未申请到 DGX Spark 云节点**，因此按**可伸缩架构**设计：三层分级、每层可独立替换载体。
**同一套代码在 DGX Spark 上换用更大的本地模型即可放大**——但**本版本未在 DGX Spark 上实测**，
文档统一表述为「边缘优先，架构可平移」。

---

## §4 安全设计原则

> ### 核心原则：**便宜层不下最终结论。**

三层流水线每往上一层都更贵。便宜的层当然想早点给答案——但在安全场景里，**早给答案比不给答案更危险**。

两类错误，方向相反：

| 错误 | 表现 | 后果 |
|---|---|---|
| **假指控** | **没看到 ≠ 没有** | 冤枉一个穿戴合规的人，**摧毁对系统的信任** |
| **假安心** | **看到了但拿不准 ≠ 没问题** | 放走一个真违规的人 |

**在安全场景里，假指控比漏检更危险。** 漏检只损失一次检查机会；假指控会让系统整体失去可信度。

### 落地规则

**只有置信度 ≥ 0.75 才能下结论** —— 且这个 **0.75 与升级阈值是同一个常量**（`ACCEPT_CONFIDENCE`），
不另立一套规则。

`[来源: skills/safety-hazard-detection/scripts/local_tier_pipeline.py:137,157]`
```python
severity = "info" if conf >= tier_budget.ACCEPT_CONFIDENCE else "uncertain"
```
> 源码注释原话：「severity 与升级判据**共用同一个阈值**。为什么必须统一：若 severity 另立一套规则
> （例如『找到就给 info』），就会出现**同一帧在两个环节得到相反结论**。」

**Tier 0.5 只要没有正面证据，`severity` 一律 `uncertain`，绝不允许输出 `warning` / `critical`。**
`[来源: local-tier-limitations.md:34-44]`

> ⚠️ **源码注释中的「除非 Tier 1 确认」这一从句当前未实现。** findings 在
> `local_tier_pipeline.py:185-203` 就已定稿，Tier 1 是在 `:219` **之后**才被调用，
> 其输出只写进结果顶层 `tier1_answer`（`:246`），**不回写 `findings`**。
> 详见 §8.2⑩。**该从句描述的是设计意图，不是当前行为。**

### 这不是性能问题：白色召回为 0 是**实现缺陷**，修完仍不过线是**度量结构问题**

启发式**看不到蓝色，只能说明它没看见蓝色——它在当前配置下看不见白色着装**。
白色掩膜里混有大量噪声连通块（墙面、机柜、反光全在其中），
对白色人员的**召回为 0**。

**因此「没找到」不构成该人员未佩戴 PPE 的证据。**

**但成因必须说清，否则会被误读成「设计如此」。这个 0 是缺陷，不是能力上限：**

| 事实 | 依据 |
|---|---|
| 站点参数把**帽子和衣服双双收成「只有蓝色」一个区间** | `local_tier_pipeline.py:55` |
| 注释写明「白色区间本身饱和度为 0，**不能被它误杀**」 | `ppe_color_probe.py:105` |
| 而紧接其下的实现对**所有颜色区间的并集**统一施加 `sat_floor >= 60` | `ppe_color_probe.py:106-108` |
| 白色区间是 `S ∈ [0, 45]`；`45 < 60` ⇒ **恒被清零，与图像内容无关** | `ppe_color_probe.py:36` |
| ⇒ **存活率 0.0000**——这是**区间交集为空**的算术必然，**不依赖任何一次测量** | 推导 |
| 实测白色像素饱和度为中位 **20–21**、90 分位 **37–38**（均 `<< 60`），与上式一致 | 实跑 |
| 把白色区间加回去，输出与当前**逐位完全相同**（死代码的直接证据） | 实跑 |

- **注释与实现在同一处直接矛盾**：注释声明白色豁免，实现未给任何豁免。
- **量到的白色掩膜数字**（`0df3783c…jpg`，逐项复核，供他人复算）：

  | 口径 | 像素占比（未清理） | 面积 ≥400 的连通块 |
  |---|---|---|
  | 代码里的白色区间（`ppe_color_probe.py:36`，`S∈[0,45]`） | **9.58%** | **24** |
  | `probe_white_killed.py` 另设的白区间（`S∈[0,55]`） | **10.91%** | **22** |

  白色像素饱和度：**中位 20–21、90 分位 37–38**（两种口径），阈值 **60**。
  ⚠️ **早期文档写的「覆盖率 11.7% / 17 个连通块」在两种口径下都复算不出来**，
  已按上表替换；**今后引用请连口径一起写。**
- **后果**：车间里穿白色防护服的工人，系统从原理上看不见。
- **但修复后并不改变结论**：把缺失颜色区间补回后，
  **照片1** 把握范围 **0.08–0.46**；**含照片2 时为 0.08–0.56**（照片2 那位到 0.5575）。
  **两种范围都全部低于 0.75 阈值**，故「本层不下结论」不变。
  **这属于「修了也不够」，不属于「设计如此」。**

### 实测佐证（修复前 → 修复后）

| | 修复前 | 修复后 |
|---|---|---|
| photo1 的 3 人 | 被误标 `warning` | 全部 `uncertain` |
| 整轮 7 条 findings | — | 见下方**实际计数** |

**整轮 severity 实际计数**（全量 7 条记录，非抽样）：

| severity | 计数 |
|---|---|
| `uncertain` | **7** |
| `info` | **0** |
| `warning` | **0** |
| `critical` | **0** |

**7 条**全是 `uncertain`——即**这一轮没有下任何最终结论**。置信度区间 **0.000 – 0.463**，**全部低于 0.75 阈值**。

`[落盘] skills/evals/pipeline_results.json`　`[已实测]` 统计方式：`json.load` → 递归收集所有含 `severity` 的记录 → `collections.Counter`。
（该文件为**旧 `main()` 最后一次写入、已停止更新**；当前等价产物为 `models/runs/<tag>-run<N>.json`。）

**正面证据率必须随结论一起给**（**这不是召回率**——本场景无 ground truth）：
photo1 上启发式对 6 人中 **3 人有正面证据，3/6**。

> ⚠️ **「有正面证据」不等于「下结论」**：photo1 的 `person_index 1` 虽然
> `cap_found=True` 且 `coverall_found=True`，但 `confidence=0.4632 < 0.75`，因此**仍判为 `uncertain`**。
> 这正是 §4 那条规则在起作用——**看到了但拿不准 ≠ 没问题**。
>
> ⚠️ **可达成性**：`conf = min(helmet_cov, vest_cov)` 取最弱一环
> （`local_tier_pipeline.py:153`）。**在未打码的这批照片上**，实测头盔区最大覆盖 **0.4632**、
> 背心区最大覆盖可达 **0.8116** —— 即**头盔项是绑住这一批的那个**，
> 7 条 findings 因此全部为 `uncertain`，最高 0.4632 < 0.75。
>
> 🔴 **但必须说清：这条线是可越过的，不是结构上不可达。**
> 在**打码后**的同一张照片上，实测把握达到 **0.7525 > 0.75**，
> 系统**确实输出了一条 `info`**（该轮 5 条：4 × `uncertain` + 1 × `info`）。
> 见 `docs/face-blur-rerun-ledger.md` §1.3。
>
> **这条比它看起来重要**：越过判定线的不是「穿戴更规范」，而是**一次隐私处理（人脸马赛克）**。
> 即 **`info`（本层唯一可能下的结论）可以由一个与 PPE 状态无关的图像处理动作产生** ——
> 这说明该把握值是**未标定的色块覆盖率代理量**，不是合规概率。
> **演示与文案中不得把「达到判定线」读作「该系统认为此人合规」。**
> 详见 §8.2②。
`[来源: local-tier-limitations.md:19-22；skills/evals/pipeline_results.json]`

---

## §5 部署说明

### 5.1 环境要求

- **Windows**（本项目在 Windows 11 上开发与验证）
- **Python 3.12**（实测 3.12.10）。注意：本机默认 `python` 为 3.14，请显式用 `py -3.12`
- **NVIDIA GPU（必需）**：本地三层流水线需要 CUDA，实测显存峰值 **4546.9 MiB**（≈4.44 GiB）。
  本项目实测环境 **RTX 5060 Laptop 8 GB**（sm_120 / 驱动 591.91 / `torch 2.11.0+cu128`）。`[已实测]`
- **磁盘**：克隆后需**再预留约 5 GB**（模型权重约 4.3 GB + CUDA 版 torch 约 2.5 GB）。`[已实测]`
- **联网**：**首次部署必需**（下载权重 + 安装依赖）。**权重就位后，本地三层可完全离线运行**。

**GPU 自检**（装完依赖后跑一次）：

```bash
./.venv/Scripts/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```
预期输出 `2.11.0+cu128 True`。若为 `False`，多半是装成了 CPU 版 torch——见 §5.2。

#### 🔴 模型权重：**不在仓库内分发，必须自行下载**

**`models/` 已被 `.gitignore` 排除**（`.gitignore:24`）——**克隆仓库后没有任何权重文件**。
因体积原因不随仓库分发。`[已实测]` `git check-ignore` 确认。

**需要下载的内容与目标路径**：

| 文件 | 目标路径 | 体积 |
|---|---|---|
| YOLO11n 权重 | `models/yolo11n.pt` | **5,613,764 B（约 5.4 MB）** |
| Qwen3-VL-2B-Instruct | `models/Qwen3-VL-2B-Instruct/`（13 个文件） | **4,266,649,720 B（约 4.0 GiB）** |
| **合计** | | **约 4.3 GB** |

**下载源实测对比**（同机、同时段实测）：

| 源 | 实测速度 | 结论 |
|---|---|---|
| `hf-mirror.com`（HuggingFace 镜像） | **约 10 KB/s** | ❌ **实际不可用**（4 GB 需数天） |
| **ModelScope 魔搭** `modelscope.cn` | **约 30 MB/s** | ✅ **推荐**（4 GB 约 2–3 分钟） |

> 💡 **这条经验在国内网络环境下应普遍适用：优先用 ModelScope。**

**ModelScope 下载地址的形式**（逐文件下载，取自现有脚本）：

```
https://www.modelscope.cn/api/v1/models/Qwen/Qwen3-VL-2B-Instruct/repo?Revision=master&FilePath=<文件名>
```
（需逐一下载 `config.json` / `model.safetensors` / `tokenizer.json` 等 13 个文件；
其中 `model.safetensors` 约 4.26 GB，是体积主体。）

> ✅ **下载脚本已入库**：`scripts/fetch_ms.sh`、`scripts/fetch_yolo.sh`（备用 `scripts/fetch.sh`、
> 候选 `scripts/fetch_smol.sh`）。脚本用 `cd "$(dirname "$0")/.."` **自行定位仓库根**，
> **不含本机绝对路径，可直接复用**。
>
> ```bash
> bash scripts/fetch_ms.sh      # Qwen3-VL-2B → models/Qwen3-VL-2B-Instruct/
> bash scripts/fetch_yolo.sh    # yolo11n.pt   → models/
> ```

### 5.2 依赖安装

**必须分两步。** 只跑 `pip install -r requirements.txt` 会装到 PyPI 的 **CPU 版 torch**，
本地三层流水线**用不上 GPU**。

**步骤 1 · CUDA 版 torch（必须指定 cu128 专用索引）**

```bash
./.venv/Scripts/pip install torch torchvision \
    --index-url https://download.pytorch.org/whl/cu128
```

**步骤 2 · 其余依赖**

```bash
./.venv/Scripts/pip install -r requirements.txt
```

> ⚠️ 步骤 2 之后请确认 `torch.__version__` 仍带 **`+cu128`** 后缀。
> 若后缀消失，说明被 PyPI 的 CPU 版覆盖，**重跑步骤 1** 即可。

**依据**：`[已实测]` 索引 URL 返回 **HTTP 200**；`.venv` 实装
`torch 2.11.0+cu128` / `torchvision 0.26.0+cu128`，与上述索引一致。
`[未验证]`：上面两条命令**本人未从零重跑**（虚拟环境已存在）。
建环境命令 `py -3.12 -m venv .venv` **必需且应先于上面两步执行**（否则 `.venv/Scripts/pip` 不存在），
已在 README「快速开始 第 1 步」中列为独立步骤。
`requirements.txt` 顶部已写明同一套两步流程。

**依赖源提示（`[已实测]`）**：本项目开发机上配置的 **阿里云 PyPI 镜像已损坏**——
`pip install` 稳定报 `IncompleteRead`（两次失败落在**同一字节偏移**，非偶发），换官方源即恢复。
若你也遇到类似报错，改用官方源：

```bash
./.venv/Scripts/pip install -r requirements.txt --index-url https://pypi.org/simple/
```

> 说明：本次验证中，8 个固定版本对官方 PyPI **全部解析成功、无冲突**；对阿里云镜像**确定性失败**。
> **这是环境问题，与本仓库无关**，但值得写出来以免评委卡在同一处。

### 5.3 `.env` 配置

在项目根目录创建 `.env`，需要**三个变量**（**本文档不写入任何真实凭据**）：

| 变量名 | 用途 |
|---|---|
| `STEPFUN_API_KEY` | StepFun API 凭据 |
| `STEPFUN_BASE_URL` | API 端点。**国内站为 `https://api.stepfun.com/v1`**；国际站为 `https://api.stepfun.ai/v1` |
| `STEPFUN_MODEL` | 主力模型名（`step-5-preview`） |

`[来源: .env 中变量名与注释]`。**注意**：该 Key **无 `sk-` 前缀**，不要用前缀做校验；端点必须与 Key 所属站点匹配，否则返回 401。`[来源: D-010]`

> **不配 `.env` 也能跑本地三层流水线**——本次三张照片的实测即为 `cloud_authorized=False` 的纯本地运行（见 §3.3）。
> Tier 2 相关命令才需要 Key。

### 5.4 如何运行

**① 本地三层流水线 — `[已实测]`**

入口脚本：`skills/safety-hazard-detection/scripts/local_tier_pipeline.py`
`[来源: local-tier-limitations.md:4；local_tier_metrics.json 的 source 字段]`

> ⚠️ **必须显式指定输入图片**：该脚本原读 `assets/real_photos/`（因肖像权不入库，克隆后不存在）。
> 用 `--photos <目录>` 指定自备图片；不给会明确报错退出（退出码 1，**不写任何文件**）。
> 默认按 `assets/real_photos/` → `assets/samples/` 取第一个有图的。
>
> ⚠️ **默认不覆盖 `docs/local_tier_metrics.json`**（README「分层效果」表的真值来源）；
> 要覆盖须显式加 `--force`。
> **但会向 `docs/local_tier_variance.jsonl` 追加一条**墙钟记录（该文件设计为只追加，不覆盖历史）。

```bash
.venv/Scripts/python.exe skills/safety-hazard-detection/scripts/local_tier_pipeline.py \
    --photos <你的图片目录>
```

**①-b 逐层基准测试 — `[来源: docs/local_tier_benchmark.md:76-84]`**

> ⚠️ **必须给 `--out-dir`**：默认写脚本同目录，会把**已入库的** `bench_raw_<layer>.json`
> 真值来源直接覆盖掉；且换一张图重测的数与原样本**不可比**。
> `--layer` 与 `--photo` 均为必填（`--photo` 不给会明确报错退出）。

```bash
for L in tier0 tier0_5 tier1; do
  for I in 1 2 3; do
    .venv/Scripts/python.exe skills/evals/bench_layers.py \
        --layer $L --photo <你的图片> --out-dir .scratch > .scratch/bench_runs/$L-$I.json
  done
done
```

（**每层独立进程、重复 3 次**；`steady_state_samples` 共 15 个/层。）

> **每层独立进程**——同进程会让三层共占显存并互相污染加载耗时。
> 结果落盘于 `docs/local_tier_benchmark.json`（§3.2.1 的唯一真值来源）。

> ✅ **脚本已入库**：`skills/evals/bench_layers.py`（原 `models/bench_layers.py` 的路径已作废）。
> `models/` 已被 `.gitignore` 排除，**克隆后为空**——请先按 §5.1 下载权重。
> 另注：`--layer` / `--photo` 是必填，`--help` 可用（中文 Windows 的 GBK 控制台已加护栏，见 §5.6）。

**② 合规校验（交付门禁）— `[已实测]`**

```bash
./.venv/Scripts/agentskills.exe validate skills/gauge-reading
```

批量跑：

```bash
for d in inspection-orchestrator safety-hazard-detection gauge-reading inspection-report; do
  ./.venv/Scripts/agentskills.exe validate "skills/$d" || echo "FAILED: $d"
done
```

`[来源: skills/evals/check-compliance.md:11-19]`。
**实测结果**：
- **2026-09-28**：**8 个 skill** 全部输出 `Valid skill: skills\<name>`，**退出码 0**（含新增的 4 个 MES skill）。
- （此前记录：4 个 skill 全部通过 —— 巡检组建立时测得，保留作为历史。）

运行后 `skills/*/SKILL.md` 的 md5 未变（该校验为只读）。

**③ 端到端最小通路 — `[已实测 --offline]`**

```bash
.venv/Scripts/python.exe skills/evals/run_e2e.py            # 真实调用 StepFun
.venv/Scripts/python.exe skills/evals/run_e2e.py --offline  # 不调 API，只跑结构自检
```

> `--offline` 的产物前缀是 `offline-`（`offline-sample-report.md` / `offline-baseline.json`），
> **是新文件、不覆盖**已冻结的 `a4-baseline.json`；去掉 `--offline` 才会用回 `a4-` 前缀并覆盖它（D-012）。

`[来源: skills/README.md:21；run_e2e.py:190-191]`

> ⚠️ **警告**：该脚本会写入 `skills/evals/results/`，**曾覆盖过 `a4-baseline.json`**（见决策日志 D-012）。运行前请先备份该目录。

**④ 对照评测（四臂消融）— `[未实测]`**

> 🔴 **这是 v1 执行器。** 现行重做版为**五臂 A/B/C/C′/D、46 用例 × 3 次 = 690 次调用**，
> 入口为 `skills/evals/ablation-v2/run_ablation.py`。**重做版已预注册、执行器就绪，
> 但因 API 账户配额耗尽未运行。** 详见 §7 与 `skills/evals/ablation-v2/STATUS.md`。

```bash
.venv/Scripts/python.exe skills/evals/run_comparison.py --arm B --runs 3 --concurrency 5 --out skills/evals/results/out-b.json
```

可用参数：`--arm {A,B,C,D}` · `--cases` · `--runs`（默认 3）· `--limit N`（冒烟）· `--out` · `--report` · `--concurrency` · `--force`（允许覆盖产物）
`[来源: run_comparison.py:1051-1068]`

> 🔴 **`--concurrency` 必须 ≤ 5**。脚本默认值为 8，但**本账户实测并发上限为 5**，超出会大量触发 429（实测 A 臂失败率 40%）。要一次跑干净请显式传 `--concurrency 5`。
> `[来源: run_comparison.py:39-41]`、D-017

### 5.5 常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| 打印报告时抛 `UnicodeEncodeError` | 报告含 `−`(U+2212) 与 `⚠`，**Windows GBK 控制台**无法编码 | 加 `--out <file>` **写入文件**（走 UTF-8，不受影响） |
| `bench_layers.py --help` 抛 `UnicodeEncodeError: 'gbk' codec can't encode character '⚠'` | 同上，但崩在 `parser.print_help()`——**`--out` 那个解法在这里无效**，`--help` 在解析参数之前就死了 | ✅ 已在 `main()` 开头加 `_console_gbk_safe()` 护栏（保留 GBK 编码、仅把错误策略改为 `replace`，与 `run_comparison.py::_print_markdown` 同一处置）。**中文 Windows 无需任何额外参数**，实测 `--help` 退出码 0 |
| HTTP 401 | `STEPFUN_BASE_URL` 与 Key 所属站点不匹配 | 国内站用 `.com`，国际站用 `.ai` |
| 返回空 `content` | `step-5-preview` 是推理模型，思维链与答案**共享 `max_tokens`** | 提高 `max_tokens`；且提示词避免让模型复述题面 |
| 大量 429 | 并发超过账户上限 5 | 显式 `--concurrency 5`；**注意这是账户级限制，你的 Key 上限可能不同** |
| `pip install` 报 `IncompleteRead` | **本机配置的阿里云 PyPI 镜像已损坏**（非偶发） | 换官方源：`--index-url https://pypi.org/simple/`（见 §5.2） |
| `agentskills` 命令找不到 | 未安装 `skills-ref` | 已列入 `requirements.txt`（`skills-ref==0.1.1`）；重跑 §5.2 步骤 2 |
| 克隆后 `models/` 是空的 | **`models/` 被 `.gitignore` 排除，权重不随仓库分发** | 按 §5.1 自行下载（约 4.3 GB） |

`[来源: D-010、D-012、D-017；本轮实测]`

### 5.6 「评委视角」自查：从零克隆会踩到的隐含假设

**假设从零克隆仓库、逐条走 §5 每一步**，以下是查出的「在本机成立、在别人机器上不一定」之处及处置：

| # | 隐含假设 | 后果 | 处置 |
|---|---|---|---|
| 1 | 「权重已预置在 `models/`」 | 🔴 **本机成立，克隆后为空**——`models/` 被 gitignore | ✅ §5.1 已改为**下载说明**（含体积、目标路径、双源实测） |
| 2 | 「`agentskills` 命令可用」 | 🔴 **全新环境不存在**——`skills-ref` 未在依赖清单 | ✅ **已加入 `requirements.txt`** |
| 3 | 「pip 能正常装」 | 🟠 本机镜像损坏会卡住 | ✅ §5.2 加官方源回退 + §5.5 加行 |
| 4 | 「`models/bench_layers.py` 存在」 | 🟠 克隆后不存在（同被 gitignore） | ✅ **已迁移**至 `skills/evals/bench_layers.py` 并入库，§5.4 命令已更新 |
| 5 | 「`./.venv/Scripts/` 路径」 | 🟡 Windows 布局；macOS/Linux 为 `.venv/bin/` | 已声明「本项目在 Windows 上验证」 |
| 6 | 「`py -3.12` 可用」 | 🟡 Windows 专用启动器 | 已声明平台；非 Windows 用 `python3.12` |
| 7 | 「并发上限 = 5」 | 🟡 **账户级**限制，随 Key 而异 | ✅ §5.5 已注明「你的 Key 上限可能不同」 |
| 8 | 「磁盘够用」 | 🟡 实际 `models/` 占 **8.9 GB**（含两份 Qwen3-VL-2B：`-Instruct` 与 `-ModelScope`） | ✅ 运行**只需** `-Instruct` + `yolo11n.pt`（约 4.3 GB）；**另一份是下载源副本，可删** |
| 9 | 流水线命令行参数 | 🟡 未核实 | ✅ 已补：新增 `--photos <目录>`（指定输入图片）与 `--force`（覆盖 metrics 守卫）；无图时明确报错退出、不写文件 |

---

## §6 skill 结构说明

（与 `docs/PRD.md` §6 保持一致）

```
skills/
├── inspection-orchestrator/   # 编排：决定调谁、定层级
├── safety-hazard-detection/   # 窄触发：图像 → 隐患标签（含本地三层流水线）
├── gauge-reading/             # 窄触发：表盘 → 一个数
├── inspection-report/         # 窄触发：结论 → 报告
│        每个技能 = SKILL.md + scripts/ + references/ + evals/
└── evals/                     # 顶层消融套件（v1：四臂 A/B/C/D，40 条用例；重做版见 ablation-v2/）
```

**单个 skill 的四件套结构**：

```
<skill-name>/
├── SKILL.md      # 主流程、触发条件（description 含正向触发词 + 负向条件）
├── scripts/      # 确定性工具
├── references/   # 判定标准 / 巡检项定义
└── evals/        # cases.jsonl + README.md
```
`[来源: skills/README.md:55-63]`

**拆分判据**：不是「功能多少」，而是**触发条件能否用一句话说清且互不重叠**——四者两两不相交。
`[来源: docs/PRD.md §6]`

**顶层 `skills/evals/`**（跨技能评测层，不属于任何单个 skill）：`run_comparison.py`（评测执行器）、
`run_e2e.py`（端到端最小通路 + token 采集）、`metrics.json`（指标定义）、`cases-decoy.jsonl`、
`comparison-design.md`（四臂对照设计）、`check-compliance.md`（合规门禁）、`results/`（结果 JSON）。
`[来源: skills/README.md:29-40；ls skills/evals/]`

---

## §7 实验设计与结果

> 🔴 **未完成 —— 被基础设施阻塞，不是零结果，也不是有效应。**
> **本交付不提供 Δ2 / Δ2′ 的任何数值。**

### 7.1 当前状态

| 事项 | 状态 |
|---|---|
| 预注册判读规则 | ✅ **已冻结**（`PREREGISTRATION.md` 22:42 落盘，**先于任何 API 调用**）+ 附注 1（22:52，跑前） |
| 执行器 | ✅ 五臂 A/B/C/C′/D，`--selftest` **PASS** |
| 用例集 | ✅ 24 正 + 22 负 = 46 条 |
| **主实验** | ❌ **未运行。690 次调用一次都没发。** |
| 原因 | **StepFun 账户配额耗尽（HTTP 402 `quota_exceeded`）**，**非实验差异** |
| 判读状态 | **不可判读（基础设施阻塞）** |

**规模与成本参考**：5 臂 × 46 用例 × 3 次 = **690 次调用**；预估 ≈ **140 万 tokens**。
并发默认 **5**（本账户实测上限）。**纯云端 API，不占 GPU。**

**配额排除的三个可能**（`ablation-v2/results/GATE-OUTCOME.md`）：
`models.list` 正常且 `step-5-preview` 在架（key 有效）／换 `step-3`、`step-1-8k` **同样 402**（账户级非模型级）／
探针 5 次全部 402（非瞬时抖动）。

### 7.2 原四臂结果 `Δ2 = 0.000` **不可解释** —— 三个已知混淆

原四臂实验（`skills/evals/results/`，**v1 描述**）得到 `Δ2 = FTR(C) − FTR(B) = 0.000`，
四臂 FTR 全为 0。**该结果不可解释，不能读作「负向条件无效」：**

| # | 混淆 | 说明 |
|---|---|---|
| **1（最严重）** | **C 臂的操作根本没施加成功** | 四个 `SKILL.md` **正文**都有一节逐条复述 description 里的 `不适用于：`。原 C 臂只从 description 删那句，**正文照常加载 ⇒ 边界信息仍然在上下文里**。代码依据：`skills/evals/run_comparison.py:183-212` 的 `skill_payload`。**C′ 臂**（本轮新增）才是真施加。 |
| **2** | **主指标漏报** | A 臂（裸模型）实测**广义触发率 0.562**、编造 **36 个**不存在的技能名、幽灵技能调用 **76 次**；而「本技能口径」的 FTR **记成了 0.000**。**观察到了过度触发，指标没记。** |
| **3** | **负例偏易** | 原 16 条负例里只有 **6 条**是真 near-miss。裸模型都不误触发的负例，测不出任何操作的效果。 |

> **因此：「原四臂实验表明负向条件没有运行时收益」这一表述不成立。**
> 不是「测了没有效应」，是**变量没施加成功**。

### 7.3 如实记录的诚实边界（重做版）

- **C′ 有个消不掉的耦合**：C′ 删掉的那段正文里**同时含兄弟技能名**，
  故 C′ 相对 B **同时**少了两样东西——(a) 域排除条件（要测的）与 (b) 路由提示（搭便车的）。
  **两个变量绑在一起，无法分离。**
- **残留边界线索**：四个正文首段仍有「只做一件事：…不读数、不成文、不做趋势分析」这类
  **正向范围陈述**，隐含边界信息，本轮**不删**。
  **若重做后 Δ2′ 仍为 0，这是「零结果仍不可解释」的首要候选解释**，
  届时**不得反过来声称「已证明 Not-for 无用」**。
- **两条 orch 硬负例词面偏弱**（命中核心词 1 个 / 0 个），**保留不改**（改了就是动预注册）。
  若 Δ2′ 的效应只体现在 hazard/report/gauge 上，**不得据 orch 的零差异声称「orch 的 Not-for 无用」**。

**恢复方法**：配额充上后原样跑 `run_ablation.py --gate`，门禁通过后逐臂执行。
完整命令与判读规则见 `skills/evals/ablation-v2/STATUS.md`。

---

## §8 局限与能力边界（**必读**）

### 8.1 不可检测项 —— **表上一个 ❌，就是演示里一句不能说的话**

| 不可检测 / 不可宣称 | 原因 |
|---|---|
| **通道堵塞** | Tier 0（COCO 版 yolo11n）**无该类别**；Tier 0.5 是颜色/几何启发式，**无此判据** |
| **设备渗漏** | 同上——两类模型均无此判据 |
| **明火烟雾** | 同上——两类模型均无此判据 |
| **未戴手套 / 口罩** | COCO 版 yolo11n **没有 PPE 类别**；启发式只筛颜色，不辨具体装备 |
| **精确人数** | photo1 上 **YOLO 报 6 人、Tier 1 VLM 报 5 人**，两者不一致，**未逐像素人工复核，无法裁决谁对**（YOLO 第 6 个框置信度仅 0.301）。**系统内不存在裁决环节**——`tier1_answer` 是自由文本，从未被解析为计数与 YOLO 比对。**不得宣称「精确计数」，也不得「以 VLM 为准」**：实测模型自述的计数**随提示词措辞变化**（原提示词 5 人 / 编号提示词 6 人，均 `do_sample=False` 确定性复现） |
| **仪表读数** | 读数由独立技能 `gauge-reading` 负责；本地三层流水线**不做读数** |
| **白色着装的 PPE 状态** | Tier 0.5 当前**只配了蓝色区间**，对白色着装召回为 0——**「没找到白色帽子」不构成未佩戴的证据**（成因是缺陷，见 §8.2①） |

`[来源: local-tier-limitations.md:85-99、§6、§11]`

> ⚠️ **本表只覆盖「检测不了某类对象」。另有一类限制不属于此表，单列于 §8.4：
> 「故障与正常不可区分」——那不是能力边界，是可靠性缺口（**其中检测器故障一项已修复，见 §8.4**）。**

### 8.2 其他已知缺口

**① Tier 0.5 对白色着装召回为 0 —— 成因是死代码，不是设计边界**
白色掩膜里混有大量噪声连通块，对白色人员的**召回为 0**。
**「没找到」不构成未佩戴 PPE 的证据**（详见 §4）。

**但归因必须准确**：站点参数把帽子与衣服**双双收成「只有蓝色」一个区间**；
`ppe_color_probe.py:105` 的注释写明「白色区间…不能被它误杀」，
而 `:106-108` 对**所有区间的并集**统一施加 `sat_floor >= 60`，
白色区间 `S ∈ [0,45]` ⇒ **恒被清零**。白色像素饱和度中位 21 / 90 分位 38 ⇒ **存活率 0.0000**；
把白色区间加回去，输出**逐位完全相同**（死代码的直接证据）。
**修复后把握仍在 0.08–0.46，全部低于阈值——「不下结论」不变，但这是「修了也不够」，不是「设计如此」。**
`[来源: local-tier-limitations.md §1]`

**② 接口无法承载 policy 定义的部分触发条件**
- `next_tier(...)` 签名中**没有**「需要自然语言描述」这一形参——**policy 有定义、接口未承载**
- `should_escalate_to_cloud(...)` 无法判定 Tier 1 → 2 的触发条件（签名只有 `current`/`confidence`/`budget`）；
  当前实现是**闸门**而非触发器，**未臆造规则**
`[来源: local-tier-limitations.md:55-70]`

**③ `record_failure` 是累计计数，不是 policy 所说的「连续」失败**
无 `record_success`，无法实现成功的重置语义。**实现与 policy 措辞存在偏差，已知悉。**
`[来源: local-tier-limitations.md:72-76]`

**④ 「本地兜底率」当前无法计算**
`BudgetState` 没有总任务数与本地解决数，因此 `local_fallback_rate` 输出 `None`，**不臆造数值**。
`[来源: local-tier-limitations.md:78-83]`

**⑤ 测试素材是程序合成的**
四臂消融用的测试图（`synthetic_workshop.png`）是**用 Pillow 画的示意图，不是真实车间照片**，
仓库标注 `usable_as_accuracy_evidence: false`。可验证链路与 token 开销，**不能作为识别准确率的证据**。

**⑥ Δ2 没有可报的数值 —— 不是「等待回填」**
原四臂的 `Δ2 = 0.000` **不可解释**（C 臂操作未施加成功、主指标漏报、负例偏易，见 §7.2）；
重做版 **690 次调用一次未发**（配额 402）。**判读状态＝不可判读（基础设施阻塞）。**
**任何把 Δ2 = 0.000 说成「未观测到负向条件的运行时收益」的表述均不成立。**
详见 §7 与 `skills/evals/ablation-v2/STATUS.md`。

**⑦ 场景版本：v1 检测项仍在 taxonomy 中（遗留）**
当前场景为 **v2：电子厂洁净车间 · 着装合规（防尘帽 / 防静电服）**。
v1 的检测项（**安全帽 / 反光衣**）**仍保留在 taxonomy 中**，原因：**保留 v1 实验结果的对照基线**，
不作删除。`escalation-policy.md` 中原有的工地假设尚未与 v2 场景统一——**已知悉，待统一**。
`[来源: local-tier-limitations.md:101-106]`

**⑧ 未在 DGX Spark 上实测**（见 §3.4）。

**⑨ 团队无行业背景、无专有数据**，全部使用公开数据；**不主张任何产线落地效果**。

**⑩ Tier 1 的输出不参与判定链路（对照实验证实）**
findings 在 `local_tier_pipeline.py:185-203` **就已定稿**；Tier 1 在 `:219` **之后**才被调用，
输出只写进结果顶层 `tier1_answer`（`:246`），**不回写 `findings`**。
全仓库读该字段的只有 `ui/index.html:932` 的引文块与 `.scratch/` 下的探针。
**决定性对照**：把「模型说全部合规」与「模型说 3 号没戴帽」分别喂进去，
**机器判定逐字段完全相同**。

> **因此 §3.1 架构表中 Tier 1「确认或推翻 Tier 0.5」是**设计意图**，不是当前行为；
> §4 的「除非 Tier 1 确认」同样未实现。该层目前是**描述者，不是判定者**——
> 它被调用、产生成本，但**不改变任何一条结论**。**
`[来源: local-tier-limitations.md §8]`

**⑪ 检测器故障曾伪装成「画面里没有人」——✅ 已修复（2026-09-28）**
`_yolo_person_boxes()` 在 `ultralytics` 未安装或**权重文件缺失**时**返回空表而不抛异常**
⇒ 走短路分支 ⇒ 界面显示「跳过 · 上游无信号」。**当时整机检测挂掉与「画面里没人」不可区分。**

**修复后**：探针新增 `DetectorUnavailable`，`strict=True` 时抛异常（`ppe_color_probe.py:218-244`）；
管线以 `strict=True` 调用并捕获，失败时写**另一条** `short_circuit` 码 `tier0_unavailable: …`
且 `tier_calls.tier0` **保持 0**（不记成「跑过」，`local_tier_pipeline.py:122-133`）；
界面显示「**未能运行**」并注明「**这不代表画面里没有人**」（`ui/index.html:482,859,891`）。

**本次实测验证**（CPU，阻断 `ultralytics` 导入，不加载模型）：
`strict=False` 仍静默返回空表；`strict=True` **抛出 `DetectorUnavailable`**。
⇒ **数据层与界面层现在都能分开这两件事。**

> ⚠️ **仍存在的边界**：探针 CLI 的**默认**仍是宽松行为（`strict=False`）。
> 这是刻意的（独立工具不应因缺依赖而崩），但**用默认值的调用方仍会看到静默空表**。
`[来源: local-tier-limitations.md §9]`

**⑫ Tier 1 的逐人输出「未验证接地」（n=1 扰动对照）**
只抹掉编号图 **1 号框顶部 20%**，其余像素不变 → **1 号仍答「是」（未翻转），
而 3 号、4 号从「是」翻成「否」**。**改动只发生在一个框内，结论漂到了别的框上。**
`[来源: .scratch/prompt_num.log（基线，跑 2 次全「是」）／.scratch/grounding.log（扰动后）]`

> **诚实边界**：n=1 帧、n=1 次扰动、扰动方式粗糙。
> **只够说「不能假定它接地」，不够说「它不可能接地」。**

**⑬ 实拍照片已打码，且打码改变了检测结果**
演示用原图含可辨认人脸（当事人未同意公开），已产出打码版
（`scripts/blur_faces.py` → `assets/real_photos/blurred/`）。**打码不是无操作的**：
人员区域 **6 处 → 5 处**；有人把握 **0.4632 → 0.7525（越过 0.75 判定线）**；
另一张 **1 处 → 2 处**（同一人被检出两个重叠框）。

- **本文档全部照片级数字取自未打码原图**（`local_tier_pipeline.py:280` 的非递归 glob 排除 `blurred/`），
  而原图**不随仓库分发** ⇒ **这些数字无法从可发布素材复现**。
- 上表打码后的数字**尚未落盘**。**引用前必须先落盘。**
- **打码改变了检测结果——这件事本身就是一条证据**：检测链路对头部区域的像素扰动敏感。
`[来源: local-tier-limitations.md §11]`

**⑭ 环境曾有自动装包污染**
`.venv` 中曾出现 `pi_heif`（某次坏文件触发的自动安装），**不在 `requirements.txt` 内**。
**提交前须确认已卸载**，否则评审 `pip freeze` 会看到清单外的包。
`[已实测] ls .venv/Lib/site-packages/`

### 8.3 口径说明：**为什么早期文档里的数字与现在对不上**

本项目演进过程中先后出现过两批逐层性能数字。**两批都是真测的**，差异来自**口径与样本**，
不是系统换了——**特此并列，以免被误读为两套不同的系统**。

| 指标 | 早前对话中的值 | 本次基准 | 差异原因 |
|---|---|---|---|
| **tier1 冷启动** | 3.11 s（仅模型加载） | **[19.362, 20.638] s** | **口径不同**：3.11 s 只是 `from_pretrained`；本口径含解释器启动、transformers import、**CUDA 初始化**与首次推理 |
| **tier1 稳态** | 13.9 s / 261 tokens | **[9046.6, 10603.29] ms** / 180 tokens | **生成长度不同**：早前上限 400、实生成 **261**；本次上限 200、实生成 **180** |
| **tier0 稳态** | 10–13 ms | **[14.29, 51.42] ms** | 早前为 **3 次乐观样本**（且未含每个新进程的首次调用）；本次 **15 样本**，**含进程内首次调用的预热效应** |
| **tier0 显存峰值** | 90 MB | **59.8 MiB** | **两个口径，不可直接比**：早前 90 MB 是 `reserved`；本次是 `max_memory_allocated` |

> **结论**：早前数字**本身没错，但口径、样本数与指标定义不同**——**不是两套系统**。
> **今后一律以 `docs/local_tier_benchmark.json` / `.md` 为准**；本文档 §3.2.1 已全部改为引用该文件。
> `[来源: docs/local_tier_benchmark.md §「与早前口头数字的差异」]`

### 8.4 「故障与正常不可区分」——**不是能力边界，是可靠性缺口**（3 项中 **1 项已修复**）

§8.2 ⑪ 与本节同属一类：**系统在失败时的对外表现与正常状态重叠**。
单列一节，以免与 §8.1 的「检测不了某类对象」混淆——**前者不可修，后者可修。**

| 缺口 | 对外表现 | 状态 |
|---|---|---|
| **检测器故障**（未装 `ultralytics` / 权重缺失） | ~~「跳过 · 上游无信号」——与「画面确实无人」同一句话~~ | ✅ **已修复 2026-09-28**：`strict=True` 抛 `DetectorUnavailable`，管线写 `tier0_unavailable` 码且 `tier_calls.tier0` 记 0，界面显示「**未能运行 / 这不代表画面里没有人**」。**中栏描述的是修复前的状态** |
| **Tier 1 无裁决**（模型自述计数与检测器不一致） | 分歧不上屏、不告警，**只存在于原始文本里** | ❌ 未修复 |
| **Tier 1 不接地** | 逐人「是/否」**无接地保证**，但输出格式与真实判定无法区分 | ❌ 未修复（且 n=1，**尚不足以定性**） |

> **共同后果**：这三条都会让「系统看起来正常工作」。
> **演示与文案中不得把「没有报错」当作「检测成功」的证据。**
