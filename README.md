# DGX Spark Agent Skills

> 第三届 NVIDIA DGX Spark 黑客松 · Agent Skills 开发挑战赛 参赛作品

## 项目简介

一套**跑在笔记本上的本地三层视觉巡检系统**，交付 **8 个 Agent Skills**，分两组：

- **巡检组（4 个）** —— 1 编排 + 3 窄触发子技能，场景是**电子厂洁净车间的着装合规检查**（防尘帽 / 防静电服）。
  系统按**「便宜层先判、贵层只在必要时介入」**分级路由：无人的帧在 Tier 0 直接短路，
  不进颜色启发式、也不调用本地视觉模型。
- **MES 组（4 个）** —— 不止于"**识别出来**"，而是把发现**落进 MES 变成业务动作**：
  按业务规则定部门与隔离、生成异常单、单据号查重、回执确认、闭环编排。
  见下方「**MES 桥**」一节；接口真源是 `docs/agents/mes-bridge-contract.md`。

> 完整立意、场景定义与全部决策见 `docs/agents/decision-log.md`；交付说明见 `docs/DELIVERY.md`。

## 快速开始

> **本节目标：全新克隆 → 照抄下面命令 → 跑出结果。** 命令为 **Git Bash** 语法，步骤顺序不能换。

### 第 0 步 · 环境要求 `[来源: docs/DELIVERY.md §5.1；docs/local_tier_benchmark.json 的 meta]`

- **Windows 11 + Git Bash**（下面命令均按 Git Bash 写；PowerShell / cmd 需自行改写）
- **Python 3.12**（实测 3.12.10）。系统默认 `python` 可能是别的版本，**建环境时显式用 `py -3.12`**
- **NVIDIA GPU（必需）**：Tier 0 / Tier 1 走 CUDA。实测环境为 **RTX 5060 Laptop GPU**
  （compute capability 12.0 / sm_120，显存总量 8150.6 MiB，驱动 591.91）
- **磁盘约 7 GB**：权重 4.3 GB + CUDA 版 torch 约 2.5 GB
- 联网**仅在下载权重与启用 Tier 2（云端）时需要**，后者需有效的 StepFun API Key

### 第 1 步 · 建虚拟环境（**必须先做——否则第 3 步无处可装**）

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate      # 之后所有命令都在这个环境里跑
python --version                   # 必须显示 3.12.x
```

> 本 README 后续一律写 `python` / `pip`，**前提是这一步已经 `activate`**。
> 不想 activate 的话，把 `python` 换成 `./.venv/Scripts/python.exe`、`pip` 换成 `./.venv/Scripts/pip`，二者等价。
> 🔴 **不要再回头用 `py -3.12` 跑后面的命令**——那会绕开 `.venv` 用系统解释器，
> 包即使装好了也会 `ModuleNotFoundError`。

### 第 2 步 · 下载权重（不入库，**必须先做**）

```bash
bash scripts/fetch_ms.sh      # Qwen3-VL-2B → models/Qwen3-VL-2B-Instruct/（约 4.3 GB）
bash scripts/fetch_yolo.sh    # yolo11n.pt   → models/（约 5.6 MB）
```

> 权重单文件超 GitHub 100 MB 上限，已在 `.gitignore` 中排除，**克隆后 `models/` 是空的**。
> 下载完成后本地三层流水线可**完全离线运行**。备用通道 `scripts/fetch.sh`（备用候选 `scripts/fetch_smol.sh`）。
>
> ⚠️ **跳过这一步不会立刻报错，只会降级**：缺权重时 Tier 0 记为「**本层未运行**」
> （结果里的 `short_circuit` 为 `tier0_unavailable: …`，跑【①】时控制台也会打印一行「未运行」），
> 而**不是**「画面里没有人」。两种情况下表面都是 `tier_calls` 全 0、`findings` 0，**含义却相反**——
> 安全场景里把「装不上」读成「没问题」会放走真违规的人。
>
> ⚠️ **若你看到下面这条报错，就是漏了第 2 步**（它完全不提「模型文件缺失」，容易把人带偏）：
> `huggingface_hub.errors.HFValidationError: Repo id must use alphanumeric chars, '-', '_' or '.' …`
> ——`transformers` 在本地路径不存在时，会把该路径当成 HuggingFace repo id 去校验。
> **解法不是改路径写法，是把权重下下来。**

### 第 3 步 · 装依赖（**必须分两步，顺序不能换**）`[来源: docs/DELIVERY.md §5.2]`

只跑 `pip install -r requirements.txt` 会装到 PyPI 的 **CPU 版 torch**，本地三层流水线用不上 GPU。

```bash
# 3a · 先装 CUDA 版 torch（必须指定 cu128 专用索引）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3b · 再装其余依赖（requirements.txt，共 8 项）
pip install -r requirements.txt

# 3c · 自检：两个值都要对
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# 期望形如：2.11.0+cu128 True
```

> `+cu128` 后缀消失、或 `False` ⇒ torch 被 CPU 版覆盖，**重跑 3a**。
>
> `[核实程度]` **已在隔离的干净克隆上实测跑通**：第 1 步建环境；
> 第 4 步的**服务启动、页面 200、`/photos` 接口**；第 5 步的 ①②③⑤
> （② 四个 skill 全 PASS；③⑤ 退出码 0；① 在给定 `--photos` 时退出码 0、且未改写 `docs/local_tier_metrics.json`）。
> **未在干净环境重跑**：第 2 步（4.3 GB 权重下载）、第 3 步（CUDA 版 torch 安装）、
> 以及 ④（需 StepFun 凭据）——都要拉数 GB 或依赖 GPU/付费接口，本次未执行。
> 这三项的命令沿用既有实测记录（`docs/DELIVERY.md` §5.1–§5.2、`docs/local_tier_benchmark.json` 的 `meta`）。

### 第 4 步 · 跑演示界面（**先跑这个**）

```bash
python ui/server.py
```

浏览器打开 <http://127.0.0.1:8770>，点左侧的**内置样片**，或直接把一张车间照片拖进去，等结果
（**有人帧**约 14.35–25.2 s；**无人帧** 0.11–0.16 s 就返回——Tier 0 判定无人即短路，根本不进贵层）。

> 启动时先预热（终端有 `[prewarm]` 日志）：Tier 0 冷启动约 4 s + Tier 1 权重加载约 20 s，
> **这期间页面还没就绪**。（若样片目录为空，预热会跳过，服务立刻起来——此时首帧要现付冷启动。）
> 这是**唯一不需要自备素材**的入口。它只调 `run_frame`，**不写任何实验产物**
> （不碰 `docs/local_tier_*.json*`，也不碰 `skills/evals/results/`）；界面自己的台账写在 `ui/ui_runs.jsonl`，只追加。
> 常用参数：`--port`（默认 8770）· `--no-prewarm`（跳过预热）· `--host`（默认 127.0.0.1，避免 Windows 防火墙弹窗）。
>
> ⚠️ **服务能起来 ≠ 能出结果**：权重没下（第 2 步没做）时，服务照常启动、页面照常打开，
> 但点「开始检测」会失败。**第 2 步是硬前提。**
>
> ⚠️ 内置样片取自 `assets/samples/`。**若该目录为空**（页面左侧只见标题、没有可点的图），
> 直接拖一张你自己的工业场景照片即可，走的是同一条链路。

### 第 5 步 · 其余入口

| # | 用途 | 命令 |
|---|---|---|
| ① | 本地三层流水线（**会写产物**） | `python skills/safety-hazard-detection/scripts/local_tier_pipeline.py --photos <你的图片目录>` |
| ② | 合规校验（交付门禁） | `agentskills validate skills/<name>`（**8 个 skill** 各跑一次；退出码 0 = 通过） |
| ③ | 端到端最小通路 | `python skills/evals/run_e2e.py --offline` |
| ④ | 四臂对照评测（**需 StepFun 凭据**） | `python skills/evals/run_comparison.py --arm B --runs 3 --concurrency 5 --out skills/evals/results/out-b.json` |
| ⑤ | 逐层性能基准复现 | `python skills/evals/bench_layers.py --layer tier0_5 --photo <你的图片> --out-dir .scratch` |

> ⚠️ **① 必须给 `--photos`**：实拍素材 `assets/real_photos/` 含可辨认的工人人脸、当事人未同意公开发布，
> 故被 `.gitignore` 排除、**克隆后不存在**。不带参数时脚本会明确报错退出（退出码 1，不写任何文件）；
> 给一个放着自己图片的目录即可跑通，放 3 张更接近下表的分层效果。
>
> **① 默认不覆盖 `docs/local_tier_metrics.json`**——那是本 README「分层效果」表的真值来源，
> 且是在固定的三张实拍图上测的。要覆盖须显式加 `--force`。
> 但**① 会向 `docs/local_tier_variance.jsonl` 追加一条**墙钟记录（该文件设计为只追加，
> 新旧数值并列留存，不覆盖历史）；原始产物另存 `models/runs/<tag>-run*.json`。
>
> 🔴 **④ 的 `--concurrency` 必须 ≤ 5**。脚本默认值是 8，但本账户实测并发上限为 5，超出会大量触发 429。
>
> ③ 用 `--offline` 时产物前缀是 `offline-`，**写的是新文件、不覆盖任何已冻结的证据**；
> 若去掉 `--offline`（需有效 StepFun 凭据），前缀变回 `a4-`，会**覆盖 `skills/evals/results/a4-baseline.json`**
> ——该文件是冻结的 v1 证据（D-012 事故），故本 README 只给 `--offline` 形式。
>
> ④ 的 `--out` 写的是**新文件**（`out-b.json` 目前不存在），不覆盖任何既有证据；若该文件已存在，
> 脚本会拒绝覆盖并提示加 `--force`。
>
> ⚠️ **⑤ 务必带 `--out-dir`**。`--layer` 与 `--photo` 都是必需的（`--photo` 不给会明确报错退出）。
> 但 `--out-dir` 默认是脚本同目录 `skills/evals/`，会把**已入库的原始样本
> `bench_raw_<layer>.json` 直接覆盖掉**——那是本 README 逐层基准表的真值来源之一。
> 换一张图重测出的数与原样本**不可比**（`docs/local_tier_benchmark.md` 有言在先），
> 覆盖等于让已发布的数字失去出处，故上表把 `--out-dir` 写进命令。
> 想逐位复现原样本，需自备 1280×960 的车间照片——原图因隐私不入库。
>
> **需要 StepFun 凭据的只有 ④**；①②③（带 `--offline`）⑤ 全部离线。要跑 ④ 时在项目根建 `.env`
> （**本仓库不写入任何真实凭据**）：`STEPFUN_API_KEY` · `STEPFUN_BASE_URL`
> （国内站 `https://api.stepfun.com/v1`，国际站 `https://api.stepfun.ai/v1`）· `STEPFUN_MODEL`（`step-5-preview`）。
> **不配 `.env` 也能跑 ①②③⑤** —— 本次三张照片的实测即为 `cloud_authorized=False` 的纯本地运行。
>
> `[来源: docs/DELIVERY.md §5.3–§5.5；D-010 / D-012 / D-017]`

## 三层架构与各层状态

请求自下而上逐层升级，**每层都可以短路**——便宜层能定案，就不进贵层。

| 层 | 组件 | 载体 | 职责 | 状态 |
|---|---|---|---|---|
| **Tier 0** | YOLO11n | 本地权重（不入库，见快速开始） | 人形定位与计数；**未检出人形框的帧直接短路**（≠「画面无人」——**检测器故障已与「画面无人」分开**，见 §局限） | **已实现** |
| **Tier 0.5** | 颜色-几何启发式 | 纯代码，零模型依赖 | 着装颜色初筛 | **已实现** |
| **Tier 1** | Qwen3-VL-2B | 本地权重（不入库，见快速开始） | 本地视觉判读；**设计意图**是复核 Tier 0.5，**当前输出不参与判定链路**（见 `docs/DELIVERY.md` §8.2⑩） | ⚠️ **已调用，但不参与判定** |
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
复现：`python skills/evals/bench_layers.py --layer <tier0|tier0_5|tier1> --photo <你的图片> --out-dir .scratch`；
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
| **4 个巡检 skill**（本赛核心交付物） | `skills/inspection-orchestrator/` · `safety-hazard-detection/` · `gauge-reading/` · `inspection-report/` |
| **4 个 MES skill**（把发现落成业务动作） | `skills/mes-business-rules/` · `mes-inspection-intake/` · `mes-record-query/` · `mes-closed-loop/` |
| **可交互演示界面**（跑得起来的入口） | `ui/server.py` + `ui/index.html`（`python ui/server.py` → <http://127.0.0.1:8770>） |
| **演示样片**（打码后，可公开） | `assets/samples/`（3 张，界面内置） |
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
3. **Tier 0.5 对白色着装召回为 0**——
   「没找到」不构成未佩戴 PPE 的证据。**成因是实现缺陷，不是设计约束**：白色区间被饱和度下限整体清零，
   且站点参数只配了蓝色区间（技能自己的场景表却写着「蓝色**或白色**」）。
   **但修复后把握仍全部低于 0.75 阈值，本层仍然不下结论。** 详见 `docs/local-tier-limitations.md` §1。
4. **本轮没有下任何最终结论**：7 条 findings **全部为 `uncertain`**，置信度区间 **0.000–0.463**，全部低于 0.75 阈值。
5. **精确人数不可宣称**：photo1 上 YOLO 报 6 人、Tier 1 VLM 报 5 人，未逐像素人工复核，无法裁决谁对。
6. **测试素材是程序合成的**：四臂消融用的测试图是用 Pillow 画的示意图，
   仓库标注 `usable_as_accuracy_evidence: false`，**不能作为识别准确率的证据**。
7. **Tier 1 显存未完全回落**（推理后 +37.3 MiB，疑为分配器缓存，非必然泄漏）——**长跑前建议加监控**。
8. **零结果如实呈现**：Δ2 = 0.000（见上），本样本未观测到 Not-for 段的边际收益。
9. **团队无行业背景、无专有数据**，全部使用公开数据；**不主张任何生产环境下的落地效果**。

### 关于测试素材的声明

**测试素材为真实车间照片；因涉及肖像权（画面含可辨认的工人人脸，当事人未同意公开发布），
我们刻意不公开未打码的原图**——照片仅在本地实验中用于验证链路。

**仓库内图像仅含已打码样片与合成图；本地实验用未打码原图不入库。**
（本节第 6 条所述的合成示意图属「合成图」那一类，可随仓库分发。）

> 🔴 **截图含脸张数做不到逐张判定，请勿引用任何具体张数。**
> 该目录按最坏情况整体处置：`ui/screenshots/` **整个目录不进仓库**，不做筛选式的部分入库。
> 审计过程与依据见 `docs/agents/clone-preflight-findings.md` 硬伤 3 与第三部分。

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
├── ui/
│   ├── server.py                 # 演示界面（零新依赖：标准库 http.server + 自包含 HTML）
│   ├── index.html                # 单页前端
│   └── ui_runs.jsonl             # 界面自己的运行台账（只追加；不含绝对路径）
├── assets/
│   └── samples/                  # 打码后的演示样片（界面内置图；公开安全）
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
│   ├── agents/                   # 决策日志、情报、团队分工（含 mes-bridge-contract.md 契约真源）
│   ├── mes-demo/                 # MES 桥最小可复现宿主页 ↗ 见下节（示例数据，独立可跑）
│   └── adr/                      # Architecture Decision Records
├── requirements.txt              # 依赖清单（8 项，需两步安装）
├── CONTEXT.md                    # 项目上下文和背景
└── CLAUDE.md                     # Claude Code 配置
```

> **不入库内容**（已在 `.gitignore` 中排除，理由见该文件注释）：
> ① 模型权重（单文件超 GitHub 限制）——用 `scripts/fetch_ms.sh` + `scripts/fetch_yolo.sh` 获取；
> ② 含可辨认人脸的实拍素材 `assets/real_photos/`（肖像权，当事人未同意公开发布）——
> 这是第 5 步【①】**必须自带 `--photos`** 的原因；
> ③ `.env` 等凭据文件；④ `.venv/`、`.scratch/` 等本地环境与暂存区；
> ⑤ `ui/screenshots/`（按最坏情况**整目录**不入库，不做筛选式部分入库——见 §关于测试素材的声明）。
>
> **随仓库分发**的是打码后的 `assets/samples/`——演示界面第 4 步用的就是它。

## MES 桥 · 最小可复现宿主页 → `docs/mes-demo/`

MES 桥（`skills/mes-inspection-intake` 产出 → 落进 MES 界面）此前**只能跑在一份不在本仓库的外部原型上**，
⇒ 克隆本仓库后**跑不起来**。`docs/mes-demo/` 提供一份**独立可跑**的最小宿主页，
按 [`docs/agents/mes-bridge-contract.md`](docs/agents/mes-bridge-contract.md) **从契约重写**（非剪裁外部原型），
因此它同时证明：**那份契约是一份真接口规范，而不是对某一份实现的追认。**
（契约当前版本以该文件首行为准，本处不复述，避免两处版本号漂移。）

在仓库根执行**两条命令**即可跑通（详见 [`docs/mes-demo/README.md`](docs/mes-demo/README.md)）：

```bash
python -m http.server 8000
# 打开 http://localhost:8000/docs/mes-demo/index.html
```

合规 fixture 随仓库分发，**打开页面即可看到落单**：计数 `共 97 条`（库内 96 + 本次 1），首行出现示例异常单。
全部为**自造示例数据**，不含客户名或第三方数据。自带 `docs/mes-demo/verify_host_page.py` 自检 14 项。
`mes-data/` 下的数据是**真产出物**（由 `skills/mes-inspection-intake/scripts/commit.py` 从
`docs/mes-demo/evals/finding-demo.json` 生成，可逐字节复现），非手写件——见该目录 README。

## 开发工作流

1. 在 GitHub Issues 中创建任务
2. 使用 Claude Code 和工程技能开发
3. 提交代码到 GitHub
4. 定期更新文档和演示视频

## 相关链接

- **GitHub 仓库**: https://github.com/majiantong58-collab/dgx-spark-agent-skills
- **NVIDIA 开发者社区**: https://developer.nvidia.com
- **NVIDIA 中国开发者日**: 10月15日（苏州金鸡湖会展中心）
