# PPT 情报提取（intel-ppt）

- **来源**：`补充信息/图片文字提取.md`（37 张赛事直播 PPT 截图，拍摄于 2026-09-26 23:36–23:48）
- **提取者**：R1 侦察兵｜**提取日期**：2026-09-27
- **标注约定**：【引用】= PPT 原文照录；【推断】= 我的解读，非 PPT 明说
- **方法**：全文通读 + 关键词交叉校验（ROS / 机器人 / GX10 / 华硕 / 报名 / 奖项 / 提交 / 截止 / 算力）

---

## 1. 官方评分标准（含与现有文档的冲突）

【引用】PPT 首页即为完整评审标准表，六维度如下：

| 维度 | 权重 | PPT 原文要点 |
|---|---|---|
| 项目实用性、行业落地价值与技术创新性 | **25%** | 技术实现、架构与方案具备创新性，充分体现 DGX Spark 平台优势，突破传统思路并解决技术痛点 |
| 智能体与模型优化技术深度 | **25%** | 多智能体协同、模型调优深度、**Skills 设计与融合**、差异化技术方案 |
| 项目完整性 | **20%** | 功能完整、运行稳定，**前后端完整**、文档规范详实，实现逻辑清晰，可顺利完成演示 |
| 平台适配性 | **15%** | 充分发挥 DGX Spark 平台的全栈能力，合理运用 NVIDIA 技术栈、开源模型和 SDK 等工具以及 **StepFun 阶跃星辰模型的使用** |
| 演示效果 | **10%** | **Demo 视频**演示流畅、展示清晰、逻辑严谨，直观呈现作品价值 |
| 赛事征文 | **5%** | 参赛成果记录，DGX Spark 黑客松**"十日谈"**开发历程 |

### 冲突警示（重要）

现有文档记的「项目完整性 **30%**」与 PPT 不符。

- PPT 为 **20%**；六项相加 `25+25+20+15+10+5 = 100` 自洽。
- 现有记法 `25+25+30+15+10+5 = 110`，**超出 100%**，数学上不成立。
- 【推断】以 PPT 的 **20%** 为准，现有文档该处需更正。其余五项权重与现有记录一致。

---

## 2. 提交流程与提交物清单

**未提及。**

【引用】全文未出现提交入口、提交平台、截止时间、文件格式、命名规范、压缩包结构等任何一项。与「交什么」沾边的只有三处间接线索：

- 赛事征文 5% ——「参赛成果记录，DGX Spark 黑客松"十日谈"开发历程」
- 演示效果 10% —— Demo 视频（暗示需产出演示视频）
- 项目完整性 20% ——「前后端完整、文档规范详实」（暗示需交付可运行的完整项目 + 文档）

【推断】赛后需交三件：可运行项目（含前端 + 后端 + 文档）、Demo 视频、开发历程征文。具体渠道与格式本文件无从得知，须另行查证。

---

## 3. 「ROS Mini 机器人」是什么

**PPT 里没有出现这个词，也没有出现任何机器人硬件型号。**

逐词校验结果：

| 检索词 | 命中 |
|---|---|
| `ROS` | **0 次** |
| `机器人` | **2 次**，均为应用领域列举，非产品 |
| `robot` / `robotics` | **1 次**（英文 README 句子） |
| `GX10` / `华硕` / `ASUS` | **0 次** |

两处 `机器人` 上下文：

【引用】第 565 行（PPT 第 33 页结语）：

> 同样的方法可以原样搬到 GPU 数据分析、优化求解、RAG、机器人、科学计算、边缘部署或分布式训练。

【引用】第 305 行（NVIDIA/skills README 原文）：

> Physical AI and robotics workflows, simulation, CUDA-X libraries, RAG and AI Blueprints, and platform tools.

【推断】结论：**「ROS Mini 机器人」极可能是错记或外部信息串入**，本 PPT 不支持该词。PPT 里唯一相关的同类概念是 **Physical AI & Omniverse** 技能分组（`omniverse-cad-to-simready`、`physical-ai-defect-image-generation`、`paidf-auto-labeling`、`warp-debug-gradients`），属于 **仿真与合成数据软件栈**，不是实机机器人，更不是"ROS Mini"这类硬件形态。**若团队方案依赖一台 ROS Mini 机器人，本 PPT 不构成任何依据，需立即回溯该信息的真实来源。**

---

## 4. Agent Skills 规范（PPT 给得最实的一块）

【引用】Skill 的定义与目录结构：

> Skill = 一份可分发的指令包：**SKILL.md + 参考资料 + 脚本**

【引用】第 32 页明确目录构成与治理产物：

> 就是一个目录：SKILL.md + scripts/ + references/ + evals/
> 每个发布的 Skill 必带 skill-card.md、skill.oms.sig、Tier-3 evals

### 4.1 结构与命名

- **目录**：`SKILL.md` + `scripts/`（可执行脚本）+ `references/`（细节按需加载）+ `evals/`
- **命名**：【引用】示例为 `name: photo-to-3d-scene` → 【推断】kebab-case
- **frontmatter 字段**：`name` / `description` / `Use when:` / `license`（示例 `Apache-2.0`）
- **体积约束**：【引用】「# 主流程 < 100 行」
- **触发词**：【引用】「Trigger keywords 写进 description；红色 = Negative Triggers（何时不触发）」——description 里要同时写**正向触发词**和**负向触发条件**（"Not for ..."）

### 4.2 渐进式披露（核心机制）

【引用】「启动只读 description，命中之后才读正文（渐进式披露）」

【引用】「常驻 = description 约 100 token / 技能」

→ 上下文成本账：skill 常驻只占 ~100 token 的 description，命中才加载正文。**这就是"窄触发、强路由"能被工程化的原因。**

### 4.3 三条自建 Skill 心法（PPT 明说"自建 skill 同样适用"）

【引用】：

> 1. **窄触发、强路由** —— 一个 skill 只管一类事，SKILL.md 是路由表不是百科（省 token 且不误伤）
> 2. **前置提问** —— 关键参数不全时先问用户，不允许 Agent 猜测（cuOpt 的 "Required questions"）
> 3. **安全边界内嵌** —— 不改 checked-in 配置、不打印明文 token、能复用缓存结果就不调贵模型

### 4.4 evals 的硬性要求

【引用】「任务集随 skill 提交（evals/evals.json），且必须包含**负向用例**（正确答案是"不调用该 skill"的场景）」

【引用】「PASS 标准：至少一个受支持 Agent 在全部配置维度上通过」

Tier 3 评测五维度：**Security · Correctness · Discoverability · Effectiveness · Efficiency**（同一 Agent、同一任务集，跑带 skill 与不带 skill 两遍，差值即贡献，结果发布为 `BENCHMARK.md`）。

### 4.5 治理五件套（缺一不进目录）

Cataloged（产品团队收录）→ Scanned（SkillSpector 安全扫描）→ Evaluated（双 agent 五维评测）→ Signed（OpenSSF 签名 + 根证书）→ Documented（skill-card 信任记录）

【引用】「缺任何一件治理产物，同步流水线会直接拒绝它」

### 4.6 格式归属

【引用】「01 / 格式｜Anthropic 开源规范：一个目录 + SKILL.md + 按需资源；Claude Code、Codex、Cursor、OpenClaw 通用」→ 【推断】即 Anthropic Agent Skills 开放规范，非 NVIDIA 私规。

---

## 5. 推荐/要求的技术栈（点名清单）

### 5.1 模型

- **StepFun 阶跃星辰**（评分标准明文要求使用）：Step 5 Preview（【引用】「已可通过产品和 API 使用，**10 月 15 日正式开源**」）；StepAudio-Skills（TTS/ASR/语音推理）
- **Nemotron-3.5-Lightning-30B-A3B-NVFP4**、**Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark**
- **Qwen3-VL-4B-Instruct-FP8**、**Qwen3.8-Flash-Next**（⚠ 见文末 OCR 存疑项）
- 调用约定：【引用】「换模型 = 改三个值：**base_url | model_name | api_key**」，且「接口兼容 ≠ 行为等价，所以换模型要过**回归评测**」

### 5.2 平台与框架

NVIDIA 技术栈：NeMo / Megatron-Core / DALI / Dynamo / NIM / TensorRT-LLM / AI-Q Research Agent / cuOpt / cuDF / cuVS / vGPU / OpenShell / NemoClaw / NeMo Guardrails / TAO / DeepStream / VSS / RAG Blueprint / Omniverse / Jetson

### 5.3 工具链与版本

| 工具 | 版本/用法 |
|---|---|
| skills CLI | 【引用】「需要 skills CLI **v1.5.16** 或更新版本」；`npx skills@latest add nvidia/skills --list` |
| model-signing | `pip install model-signing`；`model_signing verify certificate ...` |
| SkillSpector | Tier 1 扫描，68 种漏洞模式 / 17 类别；输入 Git 仓库/URL/zip/目录/单文件，输出 JSON/Markdown/SARIF |
| 客户端 | `--agent claude-code \| codex \| cursor \| kiro-cli \| cortex (Snowflake CoCo)`；可重复指定 |
| MCP | 作为工具连接层被反复提及 |

【推断】技术栈的"官方偏好"非常明确：**NVIDIA 软件栈 + 开放模型 + MCP + Anthropic 格式的 Skill**，四者组合即"平台适配性 15%"的答卷方向。

---

## 6. 硬件与算力获取

**DGX Spark 的获取方式（申请 / 租用 / 自备 / 远程算力）——未提及。**

PPT 只把 DGX Spark 当作既有的运行平台，给出的全是**使用细节**：

【引用】「DGX Spark 用 **30081 端口 standalone LLM**」；「.env 不得直接修改（copy → generated.env → dry-run → resolved.yml）」

其他端口（来自实操页）：Agent `8000`、传感器列表 `30888`。

【引用】「Note: sshpass is used to let agent access to another DGX Spark」→ 【推断】演示环境是**局域网内多台 DGX Spark 互访**，通过 sshpass 让 Agent 跨机操作。

⚠ 安全提示：源文档第 366 行含一段**明文 SSH 账号与口令**（`[已脱敏:SSH账号]@[已脱敏:内网IP]`，属直播演示环境）。该条为私网地址，但**明文凭据出现在截图素材中**本身是风险，且素材会被提交/分发，建议在对外材料中打码。

**「华硕 GX10」未在 PPT 中出现**（0 命中）。

---

## 7. 时间线

**赛程节点（报名 / 初赛 / 复赛 / 决赛 / 截止日期）——未提及。**

PPT 中仅有的日期均为旁证信息：

| 时间 | 事件 |
|---|---|
| 2026-02 | NVIDIA/skills 仓库创建 |
| 2026-05 | NVIDIA Verified Agent Skills 官方博客发布 |
| 2026-08 | 技能数达 343 |
| 2026-09 | 采用现状数据截止月 |
| 2026-09-18 | Catalog 快照（40+ 产品族） |
| **10 月 15 日** | **Step 5 Preview 正式开源**（唯一未来日期，赛期内！） |

【推断】「十日谈」（评分表第 6 项）暗示赛程约 **10 天**，与"开发历程征文"呼应。**10-15 Step 5 开源**很可能是赛程中的一个可借力节点。真实赛程须另行查证。

---

## 8. 讲师反复强调的点（＝官方偏好）

按出现频次与强调强度排序：

1. **安全与治理贯穿全篇**（17+ 页涉及）：SKILL.md 是新的供应链攻击面；五件套缺一不进目录；「信任不来自注册表的徽章，而来自**可验证的完整性与透明度**」。SkillSpector 覆盖提示注入、数据外渗、权限提升、过度代理、MCP 工具投毒等。
2. **窄触发 + 渐进式披露**：SKILL.md 是**路由表不是百科**；description 决定触发；正文 < 100 行；细节放 references/ 按需加载。反复出现 3 次以上。
3. **用实测数据代替断言**：Tier 3「同一个 Agent，同一任务集，跑两遍 —— 带 skill 与不带 skill，差值即 skill 的实测贡献」。官方 BENCHMARK 数字：Correctness 96%(+81)、Effectiveness 80%(+75)、Discoverability 90%(+70)。
4. **必须包含负向用例**：evals 里要有"正确答案是不调用该 skill"的场景；description 要写 Negative Triggers。
5. **不做危险动作**：不改 checked-in 配置、不打印明文 token、能复用缓存就不调贵模型。
6. **可复现与溯源**：【引用】「记录你用的是哪个上游提交」。
7. **格式已收敛**：50+ 客户端收敛到同一格式；「长 prompt 是一次性代码，Skill 是可复用代码」。
8. **分工即生态**：【引用】「一帧是 NVIDIA 的格式，一帧是 StepFun 的大脑，一帧是 NVIDIA 的治理。生态本来就是分工的。」

### 8.1 最值得记的一条架构原则

【引用】第 32 页：

> 改了官方 Skill，签名就不再成立 —— 所以**环境差异一律放外部适配层，业务逻辑一律放自研 Skill**。

【推断】这条直接决定了工程分层：凡针对我们自身环境的适配（路径、端口、凭据、硬件差异）放外部适配层；业务逻辑写进自研 Skill。**这几乎就是官方给参赛作品的架构建议。**

---

## 9. 奖项设置

**未提及。** 全文 0 处提到奖金、奖品、名次、获奖名额、证书或任何激励。

仅有的一条纪律性条款（属"交流公约"，非奖项）：

【引用】

> - 交流群仅交流技术、赛事相关内容，文明交流
> - 欢迎问题反馈组委会，社媒不当言论依规处理追责
> - 社媒分享 AI 作品按平台规范标注 AI 生成
> - 请勿泄露 API 账号、密钥等敏感信息，保障账号安全

【推断】第 3 条值得注意：**对外分享作品时必须标注 AI 生成**，这是硬性合规要求。

---

## 10. 其他对参赛策略有用的信息

**报名要求 / 团队人数 / 评审方式（评委构成、答辩形式）——均未提及。**

可用信息如下：

### 10.1 选型五步流程（官方给出的方法论，可反向用于自证严谨性）

【引用】

> 1. 先说清目标动作：部署、生成、训练、检索、评估，还是排障？
> 2. 在 Catalog 里找最接近的 Skill，读它的 description 和「不适用」范围
> 3. 检查前置依赖：硬件、凭证、产品版本对不对得上
> 4. 读 skill-card.md 里的风险与许可，确认能不能商用、在哪些区域部署
> 5. 先跑最小样例再接业务数据，并记录你用的是哪个上游提交

### 10.2 官方演示过的"两个官方 Skill 串一个自研 Skill"范式

【引用】「能不能串起来，看的是**输出契约**，不是名字像不像。」

`tao-generate-image-grounding`（图片 + caption → 短语/像素边界框/score）→ Grounding JSON → KITTI 转换 → `tao-generate-referring-expressions`（图片 + KITTI 框 → 区域描述/整图 caption/分组表达）→ **自研后处理 local-pedestrian-detector**

【推断】这是 PPT 里**唯一完整的"自研 Skill 如何与官方 Skill 组合"示范**，极可能就是评委期待的作品形态：**不要从零造轮子，而是用官方 Skill 当积木，自研部分补最后一公里。**

### 10.3 参考标杆案例：vss-deploy-profile

官方当作"好 Skill"范本展示：SKILL.md 只做路由表；把产品团队验证过的知识内置（端口、.env 安全流程）；附 `scripts/normalize_resolved_yml.py` 等已验证脚本；随附 evals + BENCHMARK.md + 签名 + Skill Card。

### 10.4 治理工具链全开源

【引用】「SkillSpector / SkillEvaluator / Skill Card 模板均开源，任何组织可自建同样的信任链」→ 【推断】我们可以直接把这三样用在自己的作品上，成本为零，且正中评分标准里的"技术深度"。

### 10.5 采用的量级（可用于佐证选题价值）

NVIDIA/skills 仓库 ★3,181 / 373 forks；skills.sh 前 100 个 skill 累计约 187,000 次安装；目录规模 41 条产品线、300+ verified skills（另一页记 366 个技能 / 49 个产品），每日从产品仓自动同步。

### 10.6 Skill 的已知软肋（PPT 自曝，可作为"差异化技术方案"的切入点）

【引用】第 29 页 BOUNDARIES：

> - 触发稳定性：Claude 常不主动触发（HN: "silent failure"），触发词工程是方向，但仍是开放问题
> - 目录碎片化：.claude/skills 和 .agents/skills 各自为政
> - 信任根自分发：根证书就放在仓库里，信任根由被验证者自己分发

【推断】**第 1 条和第 3 条是官方亲口承认的未解难题**。若作品能在这两点上给出可验证的改进，直接命中"突破传统思路并解决技术痛点"（25% 维度）与"差异化技术方案"（25% 维度）。

---

## 附 A：与现有文档的差异汇总（供 team lead 决策）

| 项 | 现有文档 | PPT 原文 | 建议 |
|---|---|---|---|
| 项目完整性权重 | 30% | **20%** | **以 PPT 为准，立即更正**（现有合计 110%，不成立） |
| 其余五项权重 | 25/25/15/10/5 | 25/25/15/10/5 | 一致，无需改动 |
| StepFun 阶跃星辰 | 未列为评分项 | **写在"平台适配性"评分说明里** | 必须主动使用，否则失分 |
| Skills 设计与融合 | 未强调 | **写在"技术深度"评分说明里** | 作品形态应围绕 Skill 组织 |
| "十日谈"征文 | 未知 | 占 5%，需记录开发历程 | 需从第一天开始留痕 |
| ROS Mini 机器人 | 疑似被引用 | **PPT 0 命中** | 需回溯信息来源 |

## 附 B：OCR 存疑项（不可直接引用）

1. `Qwen3.8-Flash-Next`（第 152 行）—— 与同页 `Qwen3-VL-4B-Instruct-FP8` 并列于 VSS pipeline，且与第 18 页的 `qwen-flash` 呼应。**「Qwen3.8」不像真实型号命名**，疑为 OCR 讹误（可能为 Qwen3-VL 系列或 Qwen3-Flash）。引用前须核对。
2. `Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark` —— 后缀 `-DSpark` 疑为 DGX Spark 相关标记或 OCR 拼接，未能确证。
3. `npm`/`npx` 相关命令建议以 skills CLI 官方文档为准（PPT 自身也提示「用 skills@latest 可以避开旧版装上却不显示的问题」）。

## 附 C：本次未覆盖的范围

本报告**仅提炼该 PPT 文字提取**，未查阅 GitHub 仓库、赛事官网、报名页面或任何外部资料。第 2、6、7、9、10 题中的"未提及"仅代表 **PPT 中未提及**，不代表赛事不存在相关规定。**这些缺口需由其他信息源补齐。**
