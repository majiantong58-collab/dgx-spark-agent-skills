# NVIDIA 官方 Agent Skills 仓库侦察报告

> 侦察时间：2026-09-27 · 方法：`git clone --depth 1` + GitHub API + 本地静态统计
> 本地副本：`<repo>\.scratch\nvidia-skills`（浅克隆，可随时复查；`<repo>` = 本仓库克隆目录）

---

## 1. 仓库存在性与身份

| 项 | 值 |
|---|---|
| 官方全名 | **NVIDIA/skills**（组织 NVIDIA，org id 1728152） |
| 星标数 | **3,445** |
| 最后更新 | 2026-09-26T16:01:04Z |
| 官方描述 | "Agent Skills for NVIDIA products — install into Claude Code, Codex, and other coding agents to run Physical AI, robotics, simulation, CUDA, and RAG workflows end to end." |
| 文档站 | https://docs.nvidia.com/skills |
| 许可证 | 双许可 Apache-2.0 + CC-BY-4.0 |
| 安装方式 | `npx skills add nvidia/skills`（依赖 vercel-labs/skills CLI ≥ v1.5.16） |

**定位很关键：这是一个 catalog（目录/镜像站），不是创作仓库。** README 原文写明：skills 由各产品团队在自己的 repo 维护，通过自动化同步管线**每日镜像**到这里。所以这里的约定 = NVIDIA 对全公司 skill 的作者规范，权威性极高。

**NVIDIA 官方生态里的姊妹仓库**（同一波官方投入，值得一并看）：

| 仓库 | 星标 | 用途 |
|---|---|---|
| `NVIDIA/SkillSpector` | **18,357** | AI agent skill 安全扫描器：漏洞、恶意模式、prompt injection、数据外泄、供应链风险 |
| `NVIDIA/SkillEvaluator` | 518 | 多层技能评测框架：质量门、**语义重叠检测**、合成评测集生成、live agent 评测 |
| `NVIDIA/nurec-skills` | 45 | Omniverse NuRec 神经重建 |
| `NVIDIA/digital-health-skills` | 10 | 数字健康 |
| `NVIDIA/nvidia-kaggle` | 335 | Kaggle 竞赛全流程 |

---

## 2. 目录结构约定

顶层：`skills/`（383 个技能，**扁平一层，一个技能一个目录**）、`components.d/`（49 个产品注册表）、`plugins/`、`plugins.d/`、`docs/`、`fern/`、`.claude-plugin/`、`.agents/plugins/`。

命名约定：目录名 = `<产品前缀>-<动作>`，产品前缀强制（`cuopt-*`、`deepstream-*`、`vss-*`、`tao-*`、`nemotron-*`）。

**技能目录内的标准布局**（官方强制，同步管线会卡）：

```text
skills/<skill-name>/
├── SKILL.md          # 必需 — agent 读取的指令
├── skill-card.md     # 必需 — 治理卡（owner/license/风险/输出格式）
├── skill.oms.sig     # 必需 — 分离式 OMS 签名，可用 nv-agent-root-cert.pem 验签
├── evals/evals.json  # 必需 — Tier-3 评测数据集（缺失则跳过 live 评测）
├── BENCHMARK.md      # 评测产出 — 基准报告，随技能发布
├── references/       # 可选 — 236 个技能有
├── scripts/          # 可选 — 132 个技能有
└── assets/           # 可选 — 33 个技能有
```

实测计数：`SKILL.md` 383、`BENCHMARK.md` 383、`skill-card.md` 383、`evals/` 目录 380、`references/` 236、`scripts/` 132、`assets/` 33。

产物是**五件套强制 + 三件套可选**，`evals/` 密度(380/383)远高于 `scripts/`(132/383)——评测比脚本更被看重。

---

## 3. SKILL.md frontmatter 字段清单

全量 383 个文件的字段频次统计：

| 字段 | 出现次数 | 占比 | 说明 |
|---|---|---|---|
| `name` | 383 | 100% | 必填，与目录名一致 |
| `description` | 383 | 100% | 必填 |
| `license` | 379 | 99% | `Apache-2.0` / `CC-BY-4.0` / `CC-BY-4.0 AND Apache-2.0` |
| `metadata` | 350 | 91% | 嵌套块：`author` / `tags` / `domain` / `version` / `service` / `reviewed` |
| `compatibility` | 170 | 44% | 环境要求（平台、CUDA 版本等） |
| `allowed-tools` | 100 | 26% | 工具白名单 |
| `version` | 97 | 25% | 顶层也可写 |
| `tags` | 86 | 22% | |
| `when_to_use` | 31 | 8% | **独立于 description 的触发说明字段** |
| `tools` | 18 | 5% | |
| `author` | 15 | 4% | |
| `service` / `reviewed` / `permissions` / `owner` | 各 11 | 3% | 治理向 |
| `argument-hint` | 6 | 2% | |
| `disable-model-invocation` | 4 | 1% | |
| `title` | 3 | <1% | |
| `user_invocable` / `triggers` / `argument` | 各 2 | <1% | |
| `origin` / `data_classification` | 各 1 | <1% | |

### 真实示例原文（`skills/deepstream-dev/SKILL.md` 第 1-12 行）

```yaml
---
name: deepstream-dev
description: NVIDIA DeepStream SDK development with Python pyservicemaker API. Use when building video analytics pipelines, GStreamer-based video processing, TensorRT inference integration, object detection/tracking, or Kafka/message broker integration.
owner: NVIDIA CORPORATION
metadata:
  author: "NVIDIA CORPORATION <info@nvidia.com>"
service: deepstream
version: 1.1.1
reviewed: 2026-04-24
license: CC-BY-4.0 AND Apache-2.0
---
```

**要点**：核心必填面只有 4 个（`name` / `description` / `license` / `metadata`），其余全是可选增量。没有 `model:`、没有 `hooks:`、没有强制 `version:`。规范偏"少即是多"。

---

## 4. `description` 字段的实际写法（核心观察）

| 指标 | 值 |
|---|---|
| 样本量 | 383 |
| 最短 / 最长 | 1 / **850** 字符 |
| 均值 | **141** 字符 |
| 超 500 字符 | 13 个（3%） |
| 超 1024 字符 | **0 个** |
| 含触发词（`Use when` 等） | 61 个（16%） |
| **含负向条件** | **68 个（17.8%）** |

结构高度统一，是「**做什么 + Use when <触发场景列表>**」两段式，且大量使用产品词 + 领域词堆叠以提升召回。

### 负向条件：官方**确实在用**，且写进 description（决定性证据）

以下为 68 例中的原文摘录（逐字，未删改）：

```text
# skills/dicom-metadata-extract/SKILL.md
description: Used for extracting selected metadata from one DICOM file and flagging
standard-tag PHI presence. Not for anonymization or clinical use.

# skills/digital-health-clinical-asr-build/SKILL.md
description: "Stage 2 of the Clinical ASR Flywheel. Use when curating clinical terms,
tagging IPA, and synthesizing a NeMo manifest. NOT for scoring
(use /digital-health-clinical-asr-eval)."

# skills/holoscan-install-container/SKILL.md
description: "Install Holoscan SDK via the NGC Docker container. Use for
container-based installs; not for native apt/pip/Conda installs."

# skills/hsb-ip-create-top/SKILL.md
description: Create or explain fixed-format HSB FPGA_top.sv wrappers from validated
HOLOLINK_def.svh files. Do not use for def generation or validation.

# skills/amc-run-rtsp-calibration/SKILL.md  (负向条件写在正文)
Do not use this skill for local MP4 files already on disk; route those requests to
`skills/amc-run-video-calibration/SKILL.md`. Do not use it for the bundled sample
dataset; route that to `skills/amc-run-sample-calibration/SKILL.md`.
```

观察到的**四种负向写法**：
1. `Not for <X>` —— 最简，纯排除（dicom-*）
2. `NOT for <X> (use /<other-skill>)` —— **排除 + 显式改道到兄弟技能**（digital-health-*，最强）
3. `not for <X> installs` —— 同族技能之间划线（holoscan-install-container vs -wheel）
4. `Do not use for <X>` —— 命令式禁止（hsb-*）

另外正文级负向更密集：**181/383 个 SKILL.md 正文含** `not for` / `do not use` / `not intended` / `instead use` / `out of scope`。

### 官方文档里对负向条件的明确背书

`docs/evaluating-agent-skills.mdx` 原文：

> "Write tasks that reflect what the skill is actually for. **Include negative cases, where the correct behavior is for the agent *not* to use the skill.**"

BENCHMARK.md 的评测维度里，「Discoverability」定义为：

> "checks whether the agent loads the skill when relevant and **avoids using it when irrelevant**"

底层信号 `skill_efficiency`：

> "checks **routing quality, decoy avoidance**, and redundant tool usage."

**结论：负向条件不是民间技巧，是 NVIDIA 官方规范 + 官方评测指标的直接要求。** 这一条对我们的核心论点是强力支撑，且可以引用官方文档原句。

---

## 5. 技能数量与类别分布

**383 个技能**（`benchmarks.json` 记 382，差 1 为 plugin 内的 `nvidia-skill-finder`）。

官方分类法取自 `skills.sh.json` 的 `groupings`（18 类）：

| 类别 | 数量 | | 类别 | 数量 |
|---|---:|---|---|---:|
| Vision AI | 85 | | Simulation and Modeling | 9 |
| Training AI | 72 | | Decision Optimization | 8 |
| Networking | 58 | | Conversational AI | 7 |
| Physical AI | 43 | | Robotics Simulation | 5 |
| Agentic AI | 23 | | Data Science | 3 |
| GPU Development | 18 | | AI Storage | 3 |
| Infrastructure | 16 | | Quantum Computing | 2 |
| Robotics | 14 | | Gaming | 1 |
| Inference AI | 14 | | Cybersecurity | 1 |

**Vision AI 是第一大类（85 个，22%）**，与我们的项目方向高度重合，可参考样本极多。

---

## 6. 官方校验工具 / 模板 / 脚手架

| 工具 | 作用 |
|---|---|
| **SkillSpector** (`NVIDIA/SkillSpector`) | 安全扫描器。跨 Claude Code / Codex / MCP，检测漏洞、恶意模式、prompt injection、数据外泄、供应链风险。可扫单文件 / 目录 / git repo / zip，支持 JSON 输出与 CI 集成。是 SkillEvaluator 的 Tier 1 组件。 |
| **SkillEvaluator** (`NVIDIA/SkillEvaluator`) | 三层评测框架，见下。 |
| **Skill Card 生成器** | `NVIDIA/Trustworthy-AI` 仓库的 `Skill Card.md` 技能，交互式走完治理卡各节。 |
| **签名验签** | `pip install model-signing` + `model_signing verify certificate SKILL_DIR --signature SKILL_DIR/skill.oms.sig --certificate_chain nv-agent-root-cert.pem --ignore_unsigned_files`。信任锚：`nv-agent-root-cert.pem`。 |
| **注册表校验** | `components.d/<slug>.yml` 声明制；未注册的 `skills/` 目录会被 `prune-orphans.sh` 按小时同步**自动删除**。`catalog-exceptions.yml` 是白名单。 |
| **台账文件** | `versions.json`（每技能 content_digest sha256 + last_commit + last_modified）、`benchmarks.json`（3,535 条结果行 + `skills_without_results` 清单）、`skills.sh.json`（分类分组）、`CHANGELOG.md`（Keep a Changelog）。 |

### SkillEvaluator 三层结构（官方质量门）

| Tier | 内容 | 能否阻断发布 |
|---|---|---|
| **Tier 1 验证** | Schema、license、PII、Unicode 安全 + SkillSpector 安全扫描 | **能**（高severity） |
| **Tier 2 去重** | 对 catalog 做**语义重叠检测** | 建议性 |
| **Tier 3 live 评测** | 真实 agent 在沙箱跑任务集，**有技能 vs 无技能各一次** | **能**（verdict 门） |

---

## 7. 四个观察点的明确回答

### ① description 里有没有「负向条件」写法？

**有。17.8%（68/383）的 description 含负向条件**，另有 47%（181/383）在正文含负向表述。官方评测文档明文要求写 negative cases，评测维度 Discoverability 明确考核"该不用时不用"，`skill_efficiency` 考核"routing quality, decoy avoidance"。
→ **我们的核心论点成立，且有一手官方文档 + 383 例语料双重背书。**

### ② 有没有 `evals/` 或测试用例目录？格式是什么？

**有，380 个技能带 `evals/evals.json`**，是发布必需产物（缺失则 Tier 3 跳过，等同报告缺失）。接受位置：`evals/evals.json`、`evals/*.json`、`eval/*.json`、`benchmark/evals.json`。

格式为 **JSON 数组**，每个用例字段：

```json
{
  "id": "<skill-name>-001",
  "question": "用户原始请求（自然语言，含真实参数与故障注入）",
  "expected_skill": "amc-run-rtsp-calibration",
  "expected_script": "skills/.../scripts/run_rtsp_calibration.py",
  "ground_truth": "期望 agent 走完的完整流程叙述",
  "expected_behavior": [
    "agent 识别出正确技能并以其 SKILL.md 为依据",
    "agent 在 capture 前先验 VIOS 健康",
    "...",
    "agent 不打印凭证/token"
  ]
}
```

**关键设计**（对我们的 skill 设计有直接借鉴价值）：
- `expected_behavior` 是**原子化断言列表**，可逐条判分，而非整段评分。
- 负面用例**故意混入同族干扰项**。例：`amc-run-rtsp-calibration-002` 给 4 路 `cam_00..cam_03` 流但不给校准资产，`ground_truth` 要求 agent **识别信息不足并追问**，`expected_behavior` 明写"不得从流名/流数推断用了样例数据集""不得静默默认 detector_type"。
- 故障注入用例：`-003` 故意让 VIOS 不可达，断言"不得在 VIOS 宕机时尝试 capture""不得伪造 capture session 或校准结果"。
- 安全断言在每个用例里都重复出现（"不得打印凭证"），是硬性底线。

### ③ 有没有技能间路由 / 不重叠的官方说明？

**有，两层机制：**

1. **显式路由技能** `nvidia-skill-finder`（在 `plugins/` 内），自称 "capability detector and catalog router"，配 `references/taxonomy-routing.md` 定义 **"Stable Catalog Lanes"**（稳定的分类泳道，18 类，每类给出关键词边界）。其 description 本身就是负向条件的教科书：列举 20+ 触发词后收尾 `Do not use for generic non-NVIDIA route, optimize, deploy, AI, video, data, or infrastructure tasks.`
2. **description 层改道**：兄弟技能在 description 或正文里点名把请求推给另一个 skill（`amc-run-rtsp-calibration` → `amc-run-video-calibration`；`digital-health-clinical-asr-build` → `/digital-health-clinical-asr-eval`）。这是把"不重叠"编码进触发面，而非事后靠人判。
3. **SkillEvaluator Tier 2** 对 catalog 做语义重叠检测（advisory，不阻断）。

→ **"技能间如何不重叠"在 NVIDIA 是显式工程问题，有专门的路由技能 + 分类泳道文档 + 自动化重叠检测。**

### ④ 有没有 DGX Spark / 本地推理 / 视觉的 skill？

- **DGX Spark：没有专属技能。** `skills/` 下无任何 `dgx-*` 目录。DGX Spark 只作为**部署目标**出现在其他技能的 references 里：`hsb-setup/`（`docs/platform-mapping.md`、`windows/README-WINDOWS.md`）、`vss-deploy-profile/`、`vss-deploy-detection-tracking-3d/`、`vss-summarize-video/`、`nemotron-voice-agent-builder/references/`（`platforms/deployment.md`、`frameworks/omni.md`、`networking/remote-webrtc.md`）、`deepstream-run-mv3dt/references/generate-configs.md`、`holoscan-setup/`。
  - 最有价值的原文：nemotron-voice-agent-builder 的 edge 指引写 **"DGX Spark uses the standalone DGX Spark Nano 9B NIM"**（端口/显存调优建议：先 `0.40`）。同处提到 DGX Spark 上 LLM 跑在统一内存里"**很慢**"。
  - 另一条踩坑记录：某些模型/cookiecutter 模板"被标为 amd64-only，在 arm64 主机（如 DGX Spark）上会**静默失败**"。
  - **这是一个明确的空白位**——官方尚无 DGX Spark 专属技能，只有散落的平台适配说明。
- **本地推理：无独立类别**。最接近的是 `jetson-inference-mem-tune`、`tao-run-inference-service`、以及 Inference AI 类（14 个，主打 NIM / Dynamo / 服务化）。
- **视觉：极丰富**，Vision AI 85 个技能：`deepstream-*`（7 个）、`vss-*`（15 个）、`tao-*`（30+ 个，含 finetune / analyze / convert）、`rtvi-vlm-customize-model`、`nemo-mbridge-perf-moe-vlm-training`、以及 `physical-ai-event-video-generation` 等。

---

## 8. 对我们项目最可直接复用的三条

1. **description 写负向条件**：官方 17.8% 采用率 + 明文评测要求，可直接作为规范条目，并引用 `docs/evaluating-agent-skills.mdx` 原句。
2. **`evals/evals.json` 用例格式**：`expected_behavior` 原子断言 + 干扰项负面用例 + 故障注入，是现成的、被 NVIDIA 官方的评测流水线验证过的格式，可直接借鉴（不做无谓自创）。
3. **description 长度的隐性天花板**：均值 141 字符、仅 3% 超 500、**无一超 1024**，说明存在事实上的软上限。我们给 description 定长度规范时可以此为据，而非拍脑袋。

---

## 附：复查命令

```bash
# 本地副本
ls <repo>/.scratch/nvidia-skills/skills | wc -l

# 负向条件在 description 中的分布
cd <repo>/.scratch/nvidia-skills
find . -name SKILL.md -not -path "./.git*" -exec grep -H '^description:' {} \; \
  | grep -Ei 'do not use|not for |not intended|instead use|not suitable'
```
